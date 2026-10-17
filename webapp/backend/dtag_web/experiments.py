"""Experiments: record what was done to a respondent, then rerun it N times and summarise.

A **recipe** is the respondent spec plus the list of actions taken in the web app, recorded as
*intent* so that a rerun re-decides what to ask at its own state:

    {"ask": "question text"}                                   a typed question (literal)
    {"next": "open" | "connected"}                             an informative next question (re-chosen)
    {"push": "up" | "down", "mode": ..., "include_pole_items": bool}   one optimizer push (re-optimized)
    {"auto_push": "up" | "down", "steps": n, "mode": ..., "include_pole_items": bool}
    {"sequence": ["question", ...]}                            a question sequence (literal)
    {"reset": true}

Pushes and next questions also keep the question asked originally (``original``) for reference.

Each **run** creates a fresh respondent from the spec (so the persona interpretation can differ), with
its own random seed (``seed = base_seed + run``, which matters for resp_mode "draw"), replays the
actions, and logs every question actually asked. Results go to a folder:

    <experiments dir>/<name>_<timestamp>/
        recipe.json  manifest.json  report.md
        runs/run_01/trace.jsonl       every action/question: items, answers changed, I before/after, push outcome
        runs/run_01/state_changes.csv every answer that changed (old -> new) at every step
        runs/run_01/states.csv        the full survey state after every question (long format)
        runs/run_01/session_log/      the same files as the web app's "Full log (ZIP)", unpacked
        summary/steps.csv        one row per question asked (run, action, question, items, I before/after)
        summary/checkpoints.csv  ideology after each action, per run
        summary/stats.csv        per checkpoint: n, mean, sd, 95% bootstrap CI, min, max
        summary/questions.csv    which question each run asked at each action (re-optimized pushes)
        summary/final_answers.csv  final state: answer frequencies per item across runs
        summary/state_changes.csv  every answer change in every run, one table
        summary/states.csv         full state after every question in every run, one table
        summary/stats.json       everything the web app shows

The experiments dir is ``$DTAG_EXPERIMENTS_DIR`` or ``<repo>/experiments``.
"""
from __future__ import annotations

import csv
import io
import json
import os
import random
import re
import subprocess
import threading
import time
import uuid
import zipfile
from dataclasses import fields
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import DTAG_ROOT

MAX_RUNS = 200
CREDIT = "DTAG · ZeD Lab, University of Kentucky · ishanu_ch@uky.edu"


# ----------------------------------------------------------------------------- recording

def record(es: Any, action: Dict[str, Any]) -> None:
    """Append one action (intent) to the session's experiment log."""
    log = getattr(es, "experiment_actions", None)
    if log is None:
        log = es.experiment_actions = []
    if action.get("reset"):
        log.clear()  # an experiment starts from a fresh respondent
        return
    log.append(action)


def recipe(es: Any, name: str = "") -> Dict[str, Any]:
    """The replayable recipe for this session: respondent spec + recorded actions."""
    ideo = es.ideology_summary()
    s = es.session
    return {
        "version": 1,
        "name": name or f"{es.spec.name}",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source_session": es.id,
        "respondent": {"spec": es.spec.as_dict()},
        "actions": list(getattr(es, "experiment_actions", []) or []),
        "original": {
            "ideology_enabled": ideo["enabled"],
            "initial_ideology": ideo["initial"],
            "trajectory": [{"step": int(k), "ideology": float(v)} for k, v in (s.ideology_series or [])] if ideo["enabled"] else [],
            "questions": [{"query_idx": r.get("query_idx"), "question": r.get("question"),
                           "selected_variables": r.get("selected_variables")} for r in s.results],
        },
    }


def describe_action(a: Dict[str, Any]) -> str:
    if "ask" in a:
        return f"Ask: {a['ask']}"
    if "next" in a:
        return f"Next question ({a['next']})"
    if "push" in a:
        return f"Push {a['push']} ({a.get('mode', 'realistic')})"
    if "auto_push" in a:
        return f"Auto-push {a['auto_push']} ×{a.get('steps')} ({a.get('mode', 'realistic')})"
    if "sequence" in a:
        return f"Sequence of {len(a['sequence'])} questions"
    return json.dumps(a)


# ----------------------------------------------------------------------------- running

def experiments_dir() -> Path:
    d = Path(os.environ.get("DTAG_EXPERIMENTS_DIR") or (DTAG_ROOT / "experiments")).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _spec_from_dict(engine: Any, d: Dict[str, Any]) -> Any:
    from dtag_engine import ProfileSpec  # scripts/ is on sys.path once dtag_web is imported

    names = {f.name for f in fields(ProfileSpec)}
    return ProfileSpec(**{k: v for k, v in d.items() if k in names})


def _ideo(r: Dict[str, Any]) -> Dict[str, Optional[float]]:
    i = r.get("ideology") or {}
    return {"before": i.get("before"), "after": i.get("after"), "delta": i.get("delta")}


class ExperimentJob:
    """Rerun a recipe ``runs`` times in a background thread; results are written as they finish."""

    def __init__(self, engine: Any, rec: Dict[str, Any], runs: int, base_seed: Optional[int] = None):
        self.id = uuid.uuid4().hex
        self.engine = engine
        self.recipe = rec
        self.runs = max(1, min(MAX_RUNS, int(runs)))
        self.base_seed = int(base_seed if base_seed is not None else random.randrange(1, 2**30))
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", rec.get("name") or "experiment").strip("_")[:60] or "experiment"
        self.folder = experiments_dir() / f"{name}_{time.strftime('%Y%m%d_%H%M%S')}"
        self.status = "queued"  # queued|running|done|cancelled|error
        self.error: Optional[str] = None
        self.completed = 0
        self.current: Dict[str, Any] = {}
        self.run_records: List[Dict[str, Any]] = []
        self.stats: Optional[Dict[str, Any]] = None
        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.status in ("queued", "running")

    def cancel(self) -> None:
        self._cancel.set()

    def start(self) -> None:
        threading.Thread(target=self._run, name=f"dtag-exp-{self.id[:8]}", daemon=True).start()

    # -- one run -----------------------------------------------------------------

    def _run_once(self, k: int) -> Dict[str, Any]:
        engine = self.engine
        spec = _spec_from_dict(engine, self.recipe["respondent"]["spec"])
        seed = self.base_seed + k
        spec.run = {**dict(spec.run or {}), "seed": seed}
        t0 = time.time()
        es = engine.create_session(spec=spec)
        ideo0 = es.ideology_summary()
        trace: List[Dict[str, Any]] = []
        states: List[Dict[str, Any]] = [{"query_idx": 0, "action": 0, "state": dict(es.session.state)}]
        changes: List[Dict[str, Any]] = []
        checkpoints = [{"action": 0, "label": "start", "ideology": ideo0["current"]}]

        def log(ai: int, a: Dict[str, Any], r: Optional[Dict[str, Any]], **extra: Any) -> None:
            row = {"run": k, "action": ai, "kind": next(iter(a)), "label": describe_action(a), **extra}
            if r is not None:
                row.update({"query_idx": r.get("query_idx"), "question": r.get("question"),
                            "selected_variables": r.get("selected_variables"), "mapping": (r.get("mapping") or {}).get("label"),
                            "state_changed": r.get("state_changed"), "state_updates": r.get("state_updates"),
                            **{f"ideology_{x}": v for x, v in _ideo(r).items()}})
                before = states[-1]["state"]
                after = dict(es.session.state)
                for v in sorted(set(before) | set(after)):
                    if before.get(v) != after.get(v):
                        changes.append({"run": k, "action": ai, "query_idx": r.get("query_idx"), "question": r.get("question"),
                                        "variable": v, "item_text": es.session.ctx.var_map.get(v, ""),
                                        "old": before.get(v), "new": after.get(v)})
                states.append({"query_idx": r.get("query_idx"), "action": ai, "state": after})
                if r.get("push"):
                    p = r["push"]
                    row["push"] = {x: p.get(x) for x in ("mode", "direction", "variable", "mapped_variables", "hit",
                                                        "predicted_modal_delta", "predicted_joint_delta", "realized_delta")}
            trace.append(row)

        def push_once(ai: int, a: Dict[str, Any], direction: str) -> bool:
            sug = engine.ideology_push(es, include_pole_items=bool(a.get("include_pole_items")),
                                       mode=a.get("mode", "realistic"))
            pick = sug.get(direction) if sug.get("enabled") else None
            if pick is None:
                log(ai, a, None, skipped=sug.get(f"{direction}_reason") or sug.get("reason") or "no suggestion")
                return False
            r = es.ask_push(pick["question"], pick["variable"], direction=direction, mode=a.get("mode", "realistic"))
            log(ai, a, r, target_variable=pick["variable"], predicted_delta=pick.get("predicted_delta"))
            return True

        for ai, a in enumerate(self.recipe.get("actions", []), 1):
            if self._cancel.is_set():
                break
            with self._lock:
                self.current = {"run": k, "action": ai, "of": len(self.recipe.get("actions", [])), "label": describe_action(a)}
            if "ask" in a:
                log(ai, a, es.ask(a["ask"]))
            elif "sequence" in a:
                for q in a["sequence"]:
                    log(ai, a, es.ask(q))
            elif "next" in a:
                es.landscape(wait=True)
                n = engine.next_questions(es)
                pick = n.get(a["next"]) if n.get("enabled") else None
                if pick is None:
                    log(ai, a, None, skipped="no suggestion")
                else:
                    log(ai, a, es.ask(pick["question"]), target_variable=pick["v"])
            elif "push" in a:
                push_once(ai, a, a["push"])
            elif "auto_push" in a:
                for _ in range(int(a.get("steps", 1))):
                    if self._cancel.is_set() or not push_once(ai, a, a["auto_push"]):
                        break
            elif "reset" in a:
                es.reset()
            checkpoints.append({"action": ai, "label": describe_action(a), "ideology": es.ideology_summary()["current"]})

        run_dir = self.folder / "runs" / f"run_{k:02d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        with open(run_dir / "trace.jsonl", "w", encoding="utf-8") as f:
            for row in trace:
                f.write(json.dumps(row, default=str) + "\n")
        (run_dir / "state_changes.csv").write_text(_csv(changes, CHANGE_COLS))
        (run_dir / "states.csv").write_text(_csv(_state_rows(k, states), STATE_COLS))
        try:  # the same files as the web app's "Full log (ZIP)", unpacked
            from . import archive

            for name, text in archive.session_files(engine, es, label=f"run{k:02d}").items():
                dest = run_dir / "session_log" / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
        except Exception as e:  # the per-run log is a convenience; the trace is the record
            (run_dir / "session_log_error.txt").write_text(f"{type(e).__name__}: {e}\n")
        return {"run": k, "seed": seed, "seconds": round(time.time() - t0, 2), "trace": trace,
                "checkpoints": checkpoints, "changes": changes, "states": states, "initial_ideology": ideo0["initial"],
                "ideology_enabled": ideo0["enabled"], "final_state": dict(es.session.state),
                "initial_state": dict(es.session.initial_state() or {})}

    # -- the job -----------------------------------------------------------------

    def _run(self) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            (self.folder / "recipe.json").write_text(json.dumps(self.recipe, indent=2, default=str))
            self._write_manifest()
            self.status = "running"
            for k in range(1, self.runs + 1):
                if self._cancel.is_set():
                    break
                rec = self._run_once(k)
                with self._lock:
                    self.run_records.append(rec)
                    self.completed = k
                    self.stats = summarize(self.recipe, self.run_records)
            write_summary(self.folder, self.recipe, self.run_records)
            self.status = "cancelled" if self._cancel.is_set() else "done"
        except Exception as e:
            self.status = "error"
            self.error = f"{type(e).__name__}: {e}"
            if self.run_records:
                try:
                    write_summary(self.folder, self.recipe, self.run_records)
                except Exception:
                    pass
        finally:
            self.finished_at = time.time()
            self._write_manifest()

    def _write_manifest(self) -> None:
        try:
            commit = subprocess.run(["git", "-C", str(DTAG_ROOT), "rev-parse", "--short", "HEAD"],
                                    capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            commit = ""
        spec = self.recipe["respondent"]["spec"]
        (self.folder / "manifest.json").write_text(json.dumps({
            "job_id": self.id, "name": self.recipe.get("name"), "runs_requested": self.runs,
            "runs_completed": self.completed, "status": self.status, "error": self.error,
            "base_seed": self.base_seed, "seeds": f"base_seed + run (1..{self.runs})",
            "model_key": spec.get("model_key"), "map_key": spec.get("map_key"), "profile": spec.get("name"),
            "llm_backend": getattr(self.engine, "llm_backend", None),
            "llm_model": getattr(self.engine, "openai_model_override", None),
            "git_commit": commit, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.started_at)),
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.finished_at)) if self.finished_at else None,
            "credit": CREDIT,
            "variation": "fresh respondent per run (persona interpretation may differ); pushes and next questions "
                         "re-chosen at each run's own state; per-run seed for drawn responses",
        }, indent=2))

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "job_id": self.id, "status": self.status, "error": self.error, "runs": self.runs,
                "completed": self.completed, "current": dict(self.current), "name": self.recipe.get("name"),
                "folder": self.folder.name, "path": str(self.folder), "base_seed": self.base_seed,
                "elapsed_seconds": round((self.finished_at or time.time()) - self.started_at, 1),
                "stats": self.stats,
            }


# ----------------------------------------------------------------------------- statistics

def _boot_ci(xs: List[float], n: int = 2000, seed: int = 0) -> List[Optional[float]]:
    if len(xs) < 2:
        return [None, None]
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(xs) for _ in xs) / len(xs) for _ in range(n))
    return [means[int(0.025 * n)], means[int(0.975 * n) - 1]]


def _sd(xs: List[float]) -> Optional[float]:
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def summarize(rec: Dict[str, Any], runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-checkpoint ideology statistics, push outcomes and question variety across runs."""
    actions = rec.get("actions", [])
    labels = ["start"] + [describe_action(a) for a in actions]
    checkpoints = []
    for ai, label in enumerate(labels):
        xs = [c["ideology"] for r in runs for c in r["checkpoints"] if c["action"] == ai and c["ideology"] is not None]
        lo, hi = _boot_ci(xs, seed=ai)
        checkpoints.append({"action": ai, "label": label, "n": len(xs),
                            "mean": sum(xs) / len(xs) if xs else None, "sd": _sd(xs), "ci_lo": lo, "ci_hi": hi,
                            "min": min(xs) if xs else None, "max": max(xs) if xs else None})
    # net change from each run's own start
    net = [r["checkpoints"][-1]["ideology"] - r["checkpoints"][0]["ideology"] for r in runs
           if r["checkpoints"][0]["ideology"] is not None and r["checkpoints"][-1]["ideology"] is not None]
    lo, hi = _boot_ci(net, seed=99)
    pushes = [row["push"] for r in runs for row in r["trace"] if row.get("push")]
    hits = [p["hit"] for p in pushes if p.get("hit") is not None]
    per_action_questions = []
    for ai in range(1, len(labels)):
        qs = [row.get("question") for r in runs for row in r["trace"] if row["action"] == ai and row.get("question")]
        distinct: Dict[str, int] = {}
        for q in qs:
            distinct[q] = distinct.get(q, 0) + 1
        top = sorted(distinct.items(), key=lambda kv: -kv[1])[:5]
        per_action_questions.append({"action": ai, "label": labels[ai], "asked": len(qs), "distinct": len(distinct),
                                     "top": [{"question": q, "count": c} for q, c in top],
                                     "skipped": sum(1 for r in runs for row in r["trace"] if row["action"] == ai and row.get("skipped"))})
    return {
        "runs": len(runs),
        "ideology_enabled": any(r.get("ideology_enabled") for r in runs),
        "checkpoints": checkpoints,
        "per_run": [{"run": r["run"], "seed": r["seed"], "ideology": [c["ideology"] for c in r["checkpoints"]],
                     "questions": sum(1 for row in r["trace"] if row.get("question")), "seconds": r["seconds"]} for r in runs],
        "net_change": {"n": len(net), "mean": sum(net) / len(net) if net else None, "sd": _sd(net), "ci_lo": lo, "ci_hi": hi},
        "push": {"n": len(pushes), "hit_rate": (sum(1 for h in hits if h) / len(hits)) if hits else None,
                 "mean_realized": (sum(p["realized_delta"] for p in pushes if p.get("realized_delta") is not None)
                                   / max(1, sum(1 for p in pushes if p.get("realized_delta") is not None))) if pushes else None},
        "questions": per_action_questions,
        "original": rec.get("original", {}),
    }


CHANGE_COLS = ["run", "action", "query_idx", "question", "variable", "item_text", "old", "new"]
STATE_COLS = ["run", "query_idx", "action", "variable", "answer"]


def _state_rows(run: int, states: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Full survey state after every question, long format (one row per run x step x item)."""
    return [{"run": run, "query_idx": st["query_idx"], "action": st["action"], "variable": v, "answer": a}
            for st in states for v, a in sorted(st["state"].items())]


def _csv(rows: List[Dict[str, Any]], cols: List[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({c: (json.dumps(r.get(c)) if isinstance(r.get(c), (list, dict)) else r.get(c)) for c in cols})
    return buf.getvalue()


def write_summary(folder: Path, rec: Dict[str, Any], runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = folder / "summary"
    out.mkdir(parents=True, exist_ok=True)
    st = summarize(rec, runs)
    steps = [row for r in runs for row in r["trace"]]
    (out / "steps.csv").write_text(_csv(steps, ["run", "action", "label", "kind", "query_idx", "question", "target_variable",
                                                "selected_variables", "mapping", "state_changed", "state_updates",
                                                "ideology_before", "ideology_after", "ideology_delta", "predicted_delta",
                                                "push", "skipped"]))
    cps = [{"run": r["run"], "seed": r["seed"], **c} for r in runs for c in r["checkpoints"]]
    (out / "checkpoints.csv").write_text(_csv(cps, ["run", "seed", "action", "label", "ideology"]))
    (out / "stats.csv").write_text(_csv(st["checkpoints"], ["action", "label", "n", "mean", "sd", "ci_lo", "ci_hi", "min", "max"]))
    qrows = [{"run": row["run"], "action": row["action"], "label": row["label"], "question": row.get("question"),
              "target_variable": row.get("target_variable"), "selected_variables": row.get("selected_variables")}
             for row in steps if row.get("question") or row.get("skipped")]
    (out / "questions.csv").write_text(_csv(qrows, ["run", "action", "label", "question", "target_variable", "selected_variables"]))
    freq: Dict[tuple, int] = {}
    for r in runs:
        for v, a in r["final_state"].items():
            freq[(v, a)] = freq.get((v, a), 0) + 1
    fa = [{"variable": v, "answer": a, "runs": c, "share": round(c / len(runs), 4)} for (v, a), c in
          sorted(freq.items(), key=lambda kv: (kv[0][0], -kv[1]))]
    (out / "final_answers.csv").write_text(_csv(fa, ["variable", "answer", "runs", "share"]))
    (out / "state_changes.csv").write_text(_csv([c for r in runs for c in r.get("changes", [])], CHANGE_COLS))
    (out / "states.csv").write_text(_csv([row for r in runs for row in _state_rows(r["run"], r.get("states", []))], STATE_COLS))
    (out / "stats.json").write_text(json.dumps(st, indent=2, default=str))
    (folder / "report.md").write_text(_report(rec, st))
    return st


def _fmt(x: Optional[float], d: int = 4) -> str:
    return "—" if x is None else f"{x:+.{d}f}"


def _fmt_sd(x: Optional[float], d: int = 4) -> str:
    return "—" if x is None else f"{x:.{d}f}"


def _report(rec: Dict[str, Any], st: Dict[str, Any]) -> str:
    sp = rec["respondent"]["spec"]
    lines = [f"# Experiment: {rec.get('name')}", "", f"_{CREDIT}_", "",
             f"- Respondent: {sp.get('name')} · model {sp.get('model_key')} · persona: {sp.get('persona', '')[:200]}",
             f"- Runs: {st['runs']} (fresh respondent each run; pushes and next questions re-chosen per run)", "",
             "## Actions", ""] + [f"{i}. {describe_action(a)}" for i, a in enumerate(rec.get("actions", []), 1)]
    if st["ideology_enabled"]:
        nc = st["net_change"]
        lines += ["", "## Ideology", "",
                  f"Net change from each run's start: mean {_fmt(nc['mean'])}, sd {_fmt_sd(nc['sd'])}, "
                  f"95% CI [{_fmt(nc['ci_lo'])}, {_fmt(nc['ci_hi'])}] (n = {nc['n']}).", "",
                  "| after | n | mean | sd | 95% CI | min | max |", "|---|---:|---:|---:|---|---:|---:|"]
        for c in st["checkpoints"]:
            lines.append(f"| {c['label']} | {c['n']} | {_fmt(c['mean'])} | {_fmt_sd(c['sd'])} | "
                         f"[{_fmt(c['ci_lo'])}, {_fmt(c['ci_hi'])}] | {_fmt(c['min'])} | {_fmt(c['max'])} |")
    if st["push"]["n"]:
        p = st["push"]
        rate = "—" if p["hit_rate"] is None else f"{p['hit_rate']:.0%}"
        lines += ["", f"Pushes asked: {p['n']}; mapping hit rate {rate}; mean realized change {_fmt(p['mean_realized'])}."]
    lines += ["", "## Questions asked per action", ""]
    for q in st["questions"]:
        lines.append(f"- **{q['label']}**: {q['asked']} asked, {q['distinct']} distinct" + (f", {q['skipped']} skipped" if q["skipped"] else ""))
        for t in q["top"][:3]:
            lines.append(f"  - {t['count']}× {t['question']}")
    return "\n".join(lines) + "\n"


def zip_folder(folder: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                z.write(p, f"{folder.name}/{p.relative_to(folder)}")
    return buf.getvalue()


class ExperimentManager:
    """One experiment job at a time (they are CPU/LLM heavy); jobs are kept for polling."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, ExperimentJob] = {}

    def start(self, job: ExperimentJob) -> ExperimentJob:
        with self._lock:
            busy = [j for j in self._jobs.values() if j.running]
            if busy:
                raise RuntimeError(f"An experiment is already running ({busy[0].recipe.get('name')}); wait or cancel it.")
            self._jobs[job.id] = job
        job.start()
        return job

    def get(self, job_id: str) -> Optional[ExperimentJob]:
        return self._jobs.get(job_id)
