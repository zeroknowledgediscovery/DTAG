"""Question sequences: run a list of questions through one respondent.

A sequence is orchestration only. Each question goes through the normal
``EngineSession.ask`` (same native anchors, fallback rules and state updates
as interactive questions), in order, so the respondent's survey state carries
forward across the whole sequence. Runs in a background thread; callers poll
for progress and results, and may cancel between questions.
"""
from __future__ import annotations

import csv
import io
import threading
import time
import uuid
from typing import Any, Dict, List, Optional


def parse_question_lines(text: str) -> List[str]:
    """One question per line; skip blanks, ``#`` comments and a ``question`` header.

    A CSV whose header row has a ``question`` column (e.g. ``step,question``, the
    format of ``assets/question_sets``) is read by that column instead.
    """
    lines = str(text).splitlines()
    first = next((ln.strip() for ln in lines if ln.strip()), "")
    header = [h.strip().strip('"').lower() for h in next(csv.reader([first]))] if first else []
    if len(header) > 1 and "question" in header:
        col = header.index("question")
        out = []
        for row in csv.reader(io.StringIO("\n".join(ln for ln in lines if ln.strip())) ):
            if len(row) > col and row[col].strip() and row[col].strip().lower() != "question":
                q = row[col].strip()
                if not q.startswith("#"):
                    out.append(q)
        return out
    out: List[str] = []
    for i, line in enumerate(lines):
        q = line.strip().strip('"').strip()
        if not q or q.startswith("#"):
            continue
        if i == 0 and q.lower() == "question":
            continue
        out.append(q)
    return out


def _ideology(results: List[Dict[str, Any]], start: Optional[float]) -> Dict[str, Any]:
    vals = [r["ideology"]["after"] for r in results if r["ideology"]["after"] is not None]
    enabled = start is not None
    end = vals[-1] if vals else start
    movers = sorted(
        (
            {"query_idx": r["query_idx"], "question": r["question"], "delta": r["ideology"]["delta"],
             "mapping": r["mapping"]["label"], "anchors": {a["variable"]: a["response"] for a in r["anchors"]}}
            for r in results if r["ideology"]["delta"]
        ),
        key=lambda m: -abs(m["delta"]),
    )
    return {
        "enabled": enabled,
        "start": start,
        "end": end,
        "net_change": (end - start) if (enabled and end is not None) else None,
        "min": min([start] + vals) if enabled else None,
        "max": max([start] + vals) if enabled else None,
        "top_movers": movers[:8],
    }


class SequenceJob:
    def __init__(self, es: Any, questions: List[str], name: str = "", reset_first: bool = False):
        self.id = uuid.uuid4().hex
        self.es = es
        self.questions = list(questions)
        self.name = name
        self.reset_first = reset_first
        self.status = "queued"  # queued|running|done|cancelled|error
        self.error: Optional[str] = None
        self.results: List[Dict[str, Any]] = []
        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self.ideology_start: Optional[float] = None
        self.first_query_idx: Optional[int] = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.status in ("queued", "running")

    def cancel(self) -> None:
        self._cancel.set()

    def start(self) -> None:
        threading.Thread(target=self._run, name=f"dtag-seq-{self.id[:8]}", daemon=True).start()

    def _run(self) -> None:
        try:
            if self.reset_first:
                self.es.reset()
            s = self.es.session
            self.ideology_start = s.ideology_series[-1][1] if (s.ideology_enabled and s.ideology_series) else None
            self.first_query_idx = s.query_count + 1
            self.status = "running"
            for q in self.questions:
                if self._cancel.is_set():
                    self.status = "cancelled"
                    break
                r = self.es.ask(q)
                with self._lock:
                    self.results.append(r)
            else:
                self.status = "done"
        except Exception as e:  # surfaced to the client; the session keeps what completed
            self.status = "error"
            self.error = f"{type(e).__name__}: {e}"
        finally:
            self.finished_at = time.time()

    def snapshot(self, since: int = 0) -> Dict[str, Any]:
        with self._lock:
            results = list(self.results)
        return {
            "job_id": self.id,
            "session_id": self.es.id,
            "name": self.name,
            "status": self.status,
            "error": self.error,
            "total": len(self.questions),
            "completed": len(results),
            "reset_first": self.reset_first,
            "first_query_idx": self.first_query_idx,
            "elapsed_seconds": round((self.finished_at or time.time()) - self.started_at, 2),
            "results": results[since:],
            "results_offset": since,
            "ideology": _ideology(results, self.ideology_start),
        }


class SequenceManager:
    """At most one active sequence per session; the latest job is kept for polling."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, SequenceJob] = {}  # session_id -> latest job

    def active(self, session_id: str) -> Optional[SequenceJob]:
        with self._lock:
            job = self._jobs.get(session_id)
        return job if job is not None and job.running else None

    def get(self, session_id: str) -> Optional[SequenceJob]:
        with self._lock:
            return self._jobs.get(session_id)

    def start(self, es: Any, questions: List[str], name: str = "", reset_first: bool = False) -> SequenceJob:
        with self._lock:
            cur = self._jobs.get(es.id)
            if cur is not None and cur.running:
                raise RuntimeError("A question sequence is already running for this respondent.")
            job = SequenceJob(es, questions, name=name, reset_first=reset_first)
            self._jobs[es.id] = job
        job.start()
        return job

    def drop(self, session_id: str) -> None:
        with self._lock:
            job = self._jobs.pop(session_id, None)
        if job is not None:
            job.cancel()
