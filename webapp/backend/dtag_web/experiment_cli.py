"""Run DTAG experiments from the command line, without the web server.

The same engine and experiment runner as the web app's *Experiment* tab: every run is a fresh
respondent from the spec, with its own seed, and pushes are re-chosen at each run's own state.
Results go to the same folder layout (recipe.json, manifest.json, report.md, runs/, summary/).

    dtag-experiment push --profile gss2024_cm --direction down --steps 10 --runs 20
    dtag-experiment push --persona "35 year old nurse in Ohio, moderate" --country "United States" \\
        --year 2024 --direction up --steps 5
    dtag-experiment sequence --profile gss2024_wf --questions questions.txt --runs 20
    dtag-experiment run dtag_recipe_gss2024_cm.json --runs 50      # a recipe saved from the web app
    dtag-experiment profiles

From a source checkout use ``python scripts/dtag_experiment.py ...`` instead of ``dtag-experiment``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DIRECTIONS = {"up": "up", "down": "down", "right": "up", "left": "down"}
PUSH_MODES = ("realistic", "validated", "direct")


# ----------------------------------------------------------------------------- arguments

def _value(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text


def _overrides(args: argparse.Namespace) -> Dict[str, Any]:
    ov: Dict[str, Any] = {}
    for field in ("persona", "country", "year", "date", "resp_mode"):
        v = getattr(args, field, None)
        if v is not None:
            ov[field] = v
    if getattr(args, "persona_file", None):
        ov["persona"] = Path(args.persona_file).read_text(encoding="utf-8").strip()
    for item in getattr(args, "set", None) or []:
        key, sep, val = item.partition("=")
        if not sep or not key.strip():
            raise SystemExit(f"--set expects KEY=VALUE, got {item!r}")
        ov[key.strip()] = _value(val.strip())
    return ov


def read_questions(path: str) -> List[str]:
    """One question per line (blank lines and # comments skipped), or a JSON list of strings."""
    text = (sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")).strip()
    if text.startswith("["):
        qs = json.loads(text)
        if not all(isinstance(q, str) for q in qs):
            raise SystemExit(f"{path}: a JSON question list must contain only strings")
    else:
        qs = [ln.strip() for ln in text.splitlines()]
        qs = [q for q in qs if q and not q.startswith("#")]
    return [q.strip() for q in qs if q.strip()]


def load_recipe(path: str) -> Dict[str, Any]:
    rec = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(rec.get("recipe"), dict):  # the body of POST /api/experiments/run
        rec = rec["recipe"]
    if not isinstance(rec.get("respondent", {}).get("spec"), dict) or not rec.get("actions"):
        raise SystemExit(f"{path}: a recipe needs respondent.spec and a non-empty actions list")
    return rec


def build_spec(engine: Any, args: argparse.Namespace) -> Any:
    ov = _overrides(args)
    if args.profile or args.model:
        return engine.build_spec(profile=args.profile, overrides=ov, model_key=args.model)
    if not ov.get("persona"):
        raise SystemExit("Give --profile, or describe the respondent with --persona (and --country/--year).")
    rec = engine.recommend(persona=ov["persona"], country=ov.get("country", ""), year=ov.get("year"),
                           when=ov.get("date"))
    model = rec.get("default")
    if not model:
        raise SystemExit(f"No survey model covers this respondent; pass --model. ({rec.get('reason') or rec})")
    print(f"model: {model} (recommended; override with --model)", file=sys.stderr)
    return engine.build_spec(model_key=model, overrides=ov)


def actions_from_args(args: argparse.Namespace) -> List[Dict[str, Any]]:
    if args.command == "push":
        a: Dict[str, Any] = {"auto_push": DIRECTIONS[args.direction], "steps": args.steps, "mode": args.mode,
                             "include_pole_items": args.include_pole_items}
        actions = [a]
        if args.then_questions:
            actions.append({"sequence": read_questions(args.then_questions)})
        return actions
    qs = list(args.question or [])
    if args.questions:
        qs += read_questions(args.questions)
    if not qs:
        raise SystemExit("Give the sequence with --questions FILE and/or -q QUESTION.")
    return [{"sequence": qs}]


def make_recipe(engine: Any, args: argparse.Namespace) -> Dict[str, Any]:
    from . import experiments

    if args.command == "run":
        rec = load_recipe(args.recipe)
        if args.name:
            rec["name"] = args.name
        return rec
    spec = build_spec(engine, args)
    actions = actions_from_args(args)
    who = args.profile or spec.model_key.replace("/", "_")  # ad-hoc specs are named "adhoc:<model>"
    default_name = f"{who}_{args.command}" + (f"_{DIRECTIONS[args.direction]}{args.steps}" if args.command == "push" else "")
    return {"version": 1, "name": args.name or default_name, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source": "dtag-experiment", "respondent": {"spec": spec.as_dict()}, "actions": actions,
            "descriptions": [experiments.describe_action(a) for a in actions]}


# ----------------------------------------------------------------------------- running

def _f(x: Optional[float]) -> str:
    return "    —   " if x is None else f"{x:+.4f}"


def print_run(r: Dict[str, Any], out=None) -> None:
    out = out or sys.stdout
    ideo = [c["ideology"] for c in r["checkpoints"]]
    print(f"\nrun {r['run']} (seed {r['seed']}, {r['seconds']:.1f}s): ideology {_f(ideo[0])} -> {_f(ideo[-1])}", file=out)
    for row in r["trace"]:
        if row.get("skipped"):
            print(f"  [{row['action']}] skipped: {row['skipped']}", file=out)
            continue
        if not row.get("question"):
            continue
        target = f" [{row['target_variable']}]" if row.get("target_variable") else ""
        print(f"  [{row['action']}] {_f(row.get('ideology_before'))} -> {_f(row.get('ideology_after'))}"
              f"  {row.get('mapping') or ''}{target}  {row['question']}", file=out)


def run_job(engine: Any, rec: Dict[str, Any], runs: int, seed: Optional[int], quiet: bool = False) -> Any:
    """Run the experiment in the foreground, printing each run as it finishes. Ctrl-C stops after the
    current action; completed runs are kept and summarised."""
    from . import experiments

    job = experiments.ExperimentJob(engine, rec, runs, seed)
    print(f"experiment {rec.get('name')!r}: {job.runs} run(s), base seed {job.base_seed}", file=sys.stderr)
    for i, a in enumerate(rec["actions"], 1):
        print(f"  {i}. {experiments.describe_action(a)}", file=sys.stderr)
    job.start()
    shown = 0
    try:
        while job.running:
            time.sleep(0.5)
            with job._lock:
                done = list(job.run_records[shown:])
            for r in done:
                if not quiet:
                    print_run(r)
                shown += 1
    except KeyboardInterrupt:
        print("\ninterrupted: stopping after the current action...", file=sys.stderr)
        job.cancel()
        while job.running:
            time.sleep(0.2)
    for r in job.run_records[shown:]:
        if not quiet:
            print_run(r)
    return job


# ----------------------------------------------------------------------------- CLI

def _respondent_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("respondent (a preset, or a description like the web app's Who/Where/When)")
    g.add_argument("--profile", help="preset name (see: dtag-experiment profiles), e.g. gss2024_cm")
    g.add_argument("--persona", help="who: free-text description of the respondent")
    g.add_argument("--persona-file", help="read the description from a file")
    g.add_argument("--country", help="where")
    g.add_argument("--year", type=int, help="when (year)")
    g.add_argument("--date", help="when (YYYY-MM-DD; routes Eurobarometer to one fieldwork wave)")
    g.add_argument("--model", help="native survey model key, e.g. gss/gss_2018 (default: recommended)")
    g.add_argument("--resp-mode", dest="resp_mode", choices=("draw", "max"),
                   help="anchor response: draw from the native distribution, or take the modal answer")
    g.add_argument("--set", action="append", metavar="KEY=VALUE",
                   help="any other web-app override (repeatable), e.g. --set semantic_fallback=off")


def _common_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("experiment")
    g.add_argument("--runs", type=int, default=1, help="number of independent runs (default 1, max 200)")
    g.add_argument("--seed", type=int, help="base seed; run k uses seed+k (default: random)")
    g.add_argument("--name", help="experiment name (output folder prefix)")
    g.add_argument("--out", help="experiments folder (default: $DTAG_EXPERIMENTS_DIR or ./experiments)")
    g.add_argument("--mock", action="store_true",
                   help="offline mock LLM (placeholder prose and mapping; for plumbing tests only)")
    g.add_argument("--llm-model", help="OpenAI model for mapping and prose (default: the configured one)")
    g.add_argument("--dry-run", action="store_true", help="print the recipe as JSON and exit without running")
    g.add_argument("--quiet", action="store_true", help="do not print each run's questions")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="dtag-experiment", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("push", help="auto-push a respondent's ideology up or down, N steps per run")
    _respondent_args(p)
    p.add_argument("--direction", required=True, choices=sorted(DIRECTIONS),
                   help="up/right raises the ideology index, down/left lowers it")
    p.add_argument("--steps", type=int, default=5, help="push questions per run (default 5)")
    p.add_argument("--mode", choices=PUSH_MODES, default="realistic",
                   help="push mode, as in the web app's Auto-push tab (default realistic)")
    p.add_argument("--include-pole-items", action="store_true", help="allow items that define the ideology poles")
    p.add_argument("--then-questions", metavar="FILE", help="after the push, ask this question sequence")
    _common_args(p)

    p = sub.add_parser("sequence", help="ask a fixed question sequence, per run")
    _respondent_args(p)
    p.add_argument("--questions", metavar="FILE", help="one question per line, or a JSON list ('-' for stdin)")
    p.add_argument("-q", "--question", action="append", help="a question (repeatable; asked before --questions)")
    _common_args(p)

    p = sub.add_parser("run", help="run a recipe JSON (e.g. downloaded from the web app's Experiment tab)")
    p.add_argument("recipe", help="recipe JSON file")
    _common_args(p)

    sub.add_parser("profiles", help="list the respondent presets")
    return ap


def main(argv: Optional[List[str]] = None, engine: Any = None) -> int:
    args = parser().parse_args(argv)
    if getattr(args, "mock", False):
        os.environ["DTAG_LLM_BACKEND"] = "mock"
    if getattr(args, "llm_model", None):
        os.environ["DTAG_OPENAI_MODEL"] = args.llm_model
    out = getattr(args, "out", None) or os.environ.get("DTAG_EXPERIMENTS_DIR") or "experiments"
    os.environ["DTAG_EXPERIMENTS_DIR"] = str(Path(out).expanduser().resolve())

    from dtag_engine import DTAGEngine, DTAGEngineError

    # The web app's data dir (same rule as app.default_data_dir, which we don't import: importing
    # app builds the FastAPI app), so custom profiles saved in the browser are available here too.
    if engine is None:
        data_dir = Path(os.environ.get("DTAG_WEB_DATA_DIR", "").strip() or Path.home() / ".cache" / "dtag" / "webapp")
        engine = DTAGEngine(profiles_path=data_dir.expanduser().resolve() / "profiles.json")
    try:
        if args.command == "profiles":
            for p in engine.list_profiles():
                print(f"{p['name']:32s} {p.get('model_key', ''):24s} {p.get('error') or p.get('description', '')}")
            return 0
        rec = make_recipe(engine, args)
        if args.dry_run:
            print(json.dumps(rec, indent=2, default=str))
            return 0
        if not engine.llm_ready:
            raise SystemExit("OPENAI_API_KEY is not set (DTAG needs it for persona interpretation, variable "
                             "selection and answer prose). Set it, or pass --mock for an offline plumbing test.")
        job = run_job(engine, rec, args.runs, args.seed, quiet=args.quiet)
    except DTAGEngineError as e:
        raise SystemExit(f"error: {e}")

    st = job.stats or {}
    nc = st.get("net_change") or {}
    if st.get("ideology_enabled") and nc.get("n"):
        ci = f", 95% CI [{_f(nc['ci_lo'])}, {_f(nc['ci_hi'])}]" if nc.get("ci_lo") is not None else ""
        print(f"\nnet ideology change: mean {_f(nc['mean'])} over {nc['n']} run(s){ci}")
    print(f"status: {job.status}" + (f" ({job.error})" if job.error else ""))
    print(f"results: {job.folder}")
    if (job.folder / "report.md").is_file():
        print(f"report:  {job.folder / 'report.md'}")
    return {"done": 0, "cancelled": 130}.get(job.status, 1)


if __name__ == "__main__":
    raise SystemExit(main())
