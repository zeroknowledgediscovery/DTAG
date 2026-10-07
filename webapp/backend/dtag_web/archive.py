"""Complete session logs as ZIP archives, for later analysis and reports.

One archive per respondent (``build_session_zip``) or several respondents in one archive with
an aligned ideology comparison (``build_bundle_zip``). Everything is derived from the engine's
own export (``DTAGEngine.export_session``), so the archive and the JSON export always agree.
The history covers the questions since the session was created or last reset.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ARCHIVE_SCHEMA = "dtag-session-archive/1"


def _csv(rows: Sequence[Sequence[Any]]) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def _json(obj: Any) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False, default=str) + "\n"


def _fmt(v: Optional[float], digits: int = 4) -> str:
    return "—" if v is None else f"{v:+.{digits}f}"


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "x"


def folder_name(es: Any, label: Optional[str] = None) -> str:
    parts = ["dtag"] + ([safe_name(label)] if label else []) + [safe_name(es.spec.model_key.replace("/", "_")), es.id[:8]]
    return "_".join(parts)


# ----------------------------------------------------------------------------- tables

def _trajectory_rows(export: Dict[str, Any]) -> List[List[Any]]:
    ide = export["ideology"]
    start = ide.get("initial")
    rows = [["step", "query_idx", "question", "mapping", "state_changed", "ideology", "delta", "change_from_initial"]]
    rows.append([0, "", "(initial state)", "", "", start, "", 0.0 if start is not None else ""])
    for i, q in enumerate(export["questions"], 1):
        after = q["ideology"]["after"]
        rows.append([
            i, q["query_idx"], q["question"], q["mapping"]["label"], q["state_changed"], after,
            q["ideology"]["delta"], (after - start) if (after is not None and start is not None) else "",
        ])
    return rows


def _state_change_rows(export: Dict[str, Any], var_text: Dict[str, str]) -> List[List[Any]]:
    """Replay the state from the initial assignments so each change carries its previous value."""
    cur = dict(export["initialization"].get("initial_state") or {})
    rows = [["query_idx", "question", "variable", "survey_question", "previous_value", "new_value", "change"]]
    for q in export["questions"]:
        for var, val in (q.get("state_updates") or {}).items():
            prev = cur.get(var)
            rows.append([q["query_idx"], q["question"], var, var_text.get(var, ""), "" if prev is None else prev, val,
                         "set" if prev is None else ("unchanged" if prev == val else "changed")])
            cur[var] = val
        for var in q.get("state_evicted") or []:
            rows.append([q["query_idx"], q["question"], var, var_text.get(var, ""), cur.pop(var, ""), "", "evicted"])
    return rows


def _state_rows(state: Dict[str, Any], var_text: Dict[str, str]) -> List[List[Any]]:
    return [["variable", "value", "survey_question"]] + [[k, v, var_text.get(k, "")] for k, v in state.items()]


# ------------------------------------------------------------------------------ chart

def _svg_chart(series: List[Tuple[str, str, List[Tuple[int, float]]]], title: str) -> str:
    """Minimal dependency-free line chart: [(name, colour, [(step, value)])]."""
    W, H, L, R, T, B = 640, 300, 64, 90, 34, 40
    pts = [p for _, _, s in series for p in s]
    if not pts:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="80"><text x="10" y="40" '
                f'font-family="sans-serif" font-size="13">{title}: no ideology values</text></svg>\n')
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    pad = max((hi - lo) * 0.15, 0.002)
    lo, hi = lo - pad, hi + pad
    xmax = max(1, max(s for s, _ in pts))
    x = lambda s: L + (W - L - R) * s / xmax  # noqa: E731
    y = lambda v: T + (H - T - B) * (hi - v) / (hi - lo)  # noqa: E731
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="sans-serif">',
           f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
           f'<text x="{L}" y="20" font-size="13" font-weight="bold" fill="#1c2330">{title}</text>']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#e3e6ea"/>')
        out.append(f'<text x="{L - 6}" y="{y(v) + 4:.1f}" font-size="10" text-anchor="end" fill="#5b6573">{v:+.3f}</text>')
    if lo < 0 < hi:
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="#8a93a0" stroke-dasharray="4 3"/>')
    for s in range(0, xmax + 1, max(1, xmax // 12)):
        out.append(f'<text x="{x(s):.1f}" y="{H - B + 16}" font-size="10" text-anchor="middle" fill="#5b6573">{"init" if s == 0 else f"Q{s}"}</text>')
    out.append(f'<text x="{(L + W - R) / 2:.0f}" y="{H - 6}" font-size="10" text-anchor="middle" fill="#5b6573">question number</text>')
    for name, colour, s in series:
        if not s:
            continue
        path = " ".join(f'{"M" if i == 0 else "L"}{x(a):.1f},{y(b):.1f}' for i, (a, b) in enumerate(s))
        out.append(f'<path d="{path}" fill="none" stroke="{colour}" stroke-width="2"/>')
        out += [f'<circle cx="{x(a):.1f}" cy="{y(b):.1f}" r="3" fill="{colour}"/>' for a, b in s]
        a, b = s[-1]
        out.append(f'<text x="{x(a) + 8:.1f}" y="{y(b) + 4:.1f}" font-size="11" font-weight="bold" fill="#1c2330">{name}</text>')
    out.append("</svg>\n")
    return "\n".join(out)


def _series(export: Dict[str, Any]) -> List[Tuple[int, float]]:
    ide = export["ideology"]
    if not ide.get("enabled") or ide.get("initial") is None:
        return []
    pts = [(0, ide["initial"])]
    pts += [(i, q["ideology"]["after"]) for i, q in enumerate(export["questions"], 1) if q["ideology"]["after"] is not None]
    return pts

# ----------------------------------------------------------------------------- report

def _report(export: Dict[str, Any], label: Optional[str], seq: Optional[Dict[str, Any]]) -> str:
    p, m, ide, cfg = export["profile"], export["model"], export["ideology"], export["config"]
    init = export["initialization"]
    qs = export["questions"]
    who = f"Respondent {label}" if label else "Respondent"
    lines = [
        f"# DTAG session report — {who}",
        "",
        f"- Exported: {export['exported_at']}  ·  session `{export['session_id']}`  ·  DTAG {export['dtag'].get('version')}"
        f" (commit {export['dtag'].get('git_commit') or 'unknown'})",
        f"- History since: {export['history']['since']} (resets so far: {export['history']['resets']})",
        f"- Model: `{m['key']}` (release {m.get('release')}, sha256 {str(m.get('sha256') or '')[:12]}…), map `{(export.get('map') or {}).get('key', '')}`",
        f"- Country: {p.get('country') or '—'}  ·  year/wave: {p.get('year') or '—'}  ·  date: {p.get('date') or '—'}",
        f"- Response mode `{cfg.get('resp_mode')}`, semantic fallback `{cfg.get('semantic_fallback')}`, seed {cfg.get('seed')},"
        f" LLM `{(export.get('llm') or {}).get('openai_model', '')}` ({(export.get('llm') or {}).get('backend', '')})",
        "",
        "## Persona",
        "",
        "\n".join("> " + ln for ln in (export["persona"]["full_text"] or "").splitlines() or [">"]),
        "",
        f"Initial survey state: {len(init.get('initial_state') or {})} variables"
        f" ({len(init.get('forced_assignments') or {})} forced by geography/time); dropped LLM assignments: "
        f"{len(init.get('persona_assignments_dropped') or [])}. Details in `persona_initialization.json` and `initial_state.csv`.",
        "",
        "## Ideology",
        "",
    ]
    if ide.get("enabled"):
        lines += [
            f"- Initial {_fmt(ide.get('initial'))} → current {_fmt(ide.get('current'))} "
            f"(change {_fmt(ide.get('change_from_initial'))})",
            f"- Poles: `{(ide.get('poles') or {}).get('file')}` ({(ide.get('poles') or {}).get('items')} items); "
            "negative is nearer the L pole, positive nearer the R pole. Chart: `ideology.svg`.",
        ]
        movers = sorted([q for q in qs if q["ideology"]["delta"]], key=lambda q: -abs(q["ideology"]["delta"]))[:5]
        if movers:
            lines += ["- Largest moves: " + "; ".join(f"Q{q['query_idx']} {_fmt(q['ideology']['delta'])}" for q in movers)]
    else:
        lines += [f"- Not available: {ide.get('disable_reason')}"]
    if seq:
        lines += ["", "## Question sequence", "",
                  f"- `{seq.get('name') or '(unnamed)'}`: {seq.get('completed')}/{seq.get('total')} questions, status {seq.get('status')}"
                  f", from Q{seq.get('first_query_idx')}" + (" (respondent reset first)" if seq.get("reset_first") else "")]
    lines += ["", f"## Questions ({len(qs)})", "",
              "| Q | Question | Mapping | Survey answers | State | ΔI | I |", "|---:|---|---|---|---|---:|---:|"]
    for q in qs:
        anchors = "; ".join(f"`{a['variable']}`={a['response']}" for a in q.get("anchors", [])[:4])
        lines.append(f"| {q['query_idx']} | {q['question'].replace('|', '/')} | {q['mapping']['label']} | {anchors.replace('|', '/')} | "
                     f"{'changed' if q['state_changed'] else '—'} | {_fmt(q['ideology']['delta'])} | {_fmt(q['ideology']['after'])} |")
    lines += ["", "Full answers, evidence and distributions: `questions.jsonl`; state progression: `state_changes.csv`.", ""]
    return "\n".join(lines)


README = """DTAG session archive ({schema})

The history covers the questions asked since the session was created or last reset.

  report.md                  human-readable summary (persona, model, settings, ideology, all questions)
  manifest.json              versions, model checksum, counts and a checksum of every file
  session.json               complete engine export (the authoritative full record)
  settings.json              profile, run configuration, LLM, requested and resolved geography/time
  persona.txt                the persona description used
  persona_initialization.json  LLM persona assignments (raw), dropped ones, rationale, forced assignments
  initial_state.csv          initial survey state (variable, value, survey question)
  final_state.csv            survey state after the last question
  questions.csv              one row per question (mapping, survey answers, state updates, ideology, timings)
  questions.jsonl            one JSON record per question with the answer, evidence and full distributions
  ideology_trajectory.csv    ideology after every question (step 0 = initial state)
  ideology.svg               chart of the trajectory
  state_changes.csv          every state change, with the previous value
  poles.csv                  the polar-vector file used for the ideology index (if any)
  sequence.json              the latest question sequence run since the last reset (if any)
"""


# ---------------------------------------------------------------------------- archives

def session_files(engine: Any, es: Any, label: Optional[str] = None, sequence: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """All archive members for one respondent, as {relative name: text}."""
    export = engine.export_session(es)
    if label:
        export["label"] = label
    var_text = dict(getattr(es.session.ctx, "var_map", {}) or {})
    init = export["initialization"]
    files: Dict[str, str] = {
        "README.txt": README.format(schema=ARCHIVE_SCHEMA),
        "report.md": _report(export, label, sequence),
        "session.json": _json(export),
        "settings.json": _json({k: export.get(k) for k in ("profile", "config", "random_seed", "response_mode",
                                                           "semantic_fallback", "llm", "geography", "time", "map", "model")}),
        "persona.txt": (export["persona"]["full_text"] or "") + "\n"
                       + (f"\n[base persona of the preset]\n{export['persona']['base']}\n"
                          if export["persona"].get("base") and export["persona"]["base"] != export["persona"]["full_text"] else ""),
        "persona_initialization.json": _json({k: init.get(k) for k in (
            "persona_assignments_llm_raw", "persona_assignments_dropped", "persona_assignment_rationale",
            "forced_assignments", "geography", "initial_state", "ideology_initial", "timings_init")}),
        "initial_state.csv": _csv(_state_rows(init.get("initial_state") or {}, var_text)),
        "final_state.csv": _csv(_state_rows(export.get("final_state") or {}, var_text)),
        "questions.csv": engine.export_csv(es),
        "questions.jsonl": "".join(json.dumps(q, ensure_ascii=False, default=str) + "\n" for q in export["questions"]),
        "ideology_trajectory.csv": _csv(_trajectory_rows(export)),
        "ideology.svg": _svg_chart([(label or "I", "#2a78d6", _series(export))],
                                   f"Ideology — {('Respondent ' + label + ' · ') if label else ''}{export['model']['key']}"),
        "state_changes.csv": _csv(_state_change_rows(export, var_text)),
    }
    pole_path = getattr(es.session.polar, "path", None)
    if pole_path and Path(pole_path).is_file():
        files["poles.csv"] = Path(pole_path).read_text(encoding="utf-8")
    if sequence:
        files["sequence.json"] = _json({k: v for k, v in sequence.items() if k != "results"})
    files["manifest.json"] = _json({
        "archive_schema": ARCHIVE_SCHEMA,
        "exported_at": export["exported_at"],
        "label": label,
        "session_id": es.id,
        "created_at": export["created_at"],
        "history": export["history"],
        "dtag": export["dtag"],
        "model": export["model"],
        "map": (export.get("map") or {}).get("key"),
        "poles": (export["ideology"].get("poles") or {}),
        "question_count": len(export["questions"]),
        "ideology": {k: export["ideology"].get(k) for k in ("enabled", "initial", "current", "change_from_initial")},
        "files": {name: {"bytes": len(text.encode("utf-8")), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
                  for name, text in sorted(files.items())},
    })
    return files


def _zip(members: Dict[str, str]) -> bytes:
    buf = io.BytesIO()
    stamp = time.localtime()[:6]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in members.items():
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text.encode("utf-8"))
    return buf.getvalue()


def build_session_zip(engine: Any, es: Any, label: Optional[str] = None, sequence: Optional[Dict[str, Any]] = None) -> bytes:
    root = folder_name(es, label)
    return _zip({f"{root}/{k}": v for k, v in session_files(engine, es, label, sequence).items()})


def build_bundle_zip(engine: Any, items: List[Tuple[Any, str, Optional[Dict[str, Any]]]]) -> bytes:
    """Several respondents [(session, label, sequence)] plus an aligned ideology comparison."""
    members: Dict[str, str] = {}
    exports, colours = [], ["#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7"]
    for es, label, seq in items:
        root = folder_name(es, label)
        files = session_files(engine, es, label, seq)
        members.update({f"{root}/{k}": v for k, v in files.items()})
        exports.append((label, root, json.loads(files["session.json"])))
    steps = max((len(e["questions"]) for _, _, e in exports), default=0)
    head = ["step"]
    for label, _, _ in exports:
        head += [f"{label}_question", f"{label}_ideology", f"{label}_change_from_initial"]
    rows = [head]
    for k in range(steps + 1):
        row: List[Any] = [k]
        for _, _, e in exports:
            start = e["ideology"].get("initial")
            if k == 0:
                row += ["(initial state)", start, 0.0 if start is not None else ""]
            elif k <= len(e["questions"]):
                q = e["questions"][k - 1]
                after = q["ideology"]["after"]
                row += [q["question"], after, (after - start) if (after is not None and start is not None) else ""]
            else:
                row += ["", "", ""]
        rows.append(row)
    members["comparison.csv"] = _csv(rows)
    members["comparison.svg"] = _svg_chart(
        [(label, colours[i % len(colours)], _series(e)) for i, (label, _, e) in enumerate(exports)], "Ideology comparison")
    summary = [{"label": label, "folder": root, "session_id": e["session_id"], "model": e["model"]["key"],
                "persona": e["persona"]["full_text"], "questions": len(e["questions"]),
                "ideology": {k: e["ideology"].get(k) for k in ("initial", "current", "change_from_initial")}}
               for label, root, e in exports]
    members["bundle_manifest.json"] = _json({"archive_schema": ARCHIVE_SCHEMA, "bundle": True,
                                             "exported_at": exports[0][2]["exported_at"] if exports else None,
                                             "respondents": summary})
    members["README.txt"] = ("DTAG bundle: one folder per respondent (see each folder's README.txt and report.md),\n"
                             "comparison.csv / comparison.svg align their ideology trajectories by question number,\n"
                             "bundle_manifest.json lists the respondents.\n")
    return _zip(members)
