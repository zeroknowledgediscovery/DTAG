"""DTAG polarization question-set optimizer.

    python -m optimizer check    --config optimizer/config.example.yaml   # model, map, poles, participants, LLM
    python -m optimizer bank     --config ...                              # build + map the question bank only
    python -m optimizer run      --config ...                              # bank -> search -> validation -> report
    python -m optimizer validate --config ... --sequence path/to/question_set_detail.csv

Add ``--quick`` for a small smoke run, ``--out DIR`` to choose the output folder,
``--provider/--llm-model`` to switch LLM backends without editing the config.
Run from the repository root. See optimizer/README.md.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import csv
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import yaml

from . import bank as bankmod
from . import population
from .dtag_bridge import (DEFAULT_POLES, REPO, RUN_DEFAULTS, JsonCache, World, canonical_map, ensure_model,
                          map_question, model_record, sha256)
from .evaluate import (baselines, order_controls, per_participant, report_md,
                       state_diagnostics, summarize, write_csv, write_question_set)
from .llm import DTAGClient, make_llm
from .search import Searcher
from .simulate import Simulator

DEFAULTS: Dict[str, Any] = {
    "model": "gss/gss_2024",
    "model_root": None,            # default: DTAG model cache ($DTAG_MODEL_ROOT or ~/.cache/dtag/models)
    "download": True,
    "map": None,                   # default: the model's canonical semantic map
    "poles": str(DEFAULT_POLES),   # canonical poles; GSS waves switch to their wave-specific file
    "out": "outputs/optimizer/run",
    "cache": None,                 # LLM results cache (default: <out>/llm_cache.json)
    "workers": None,               # default: all CPU cores
    "llm": {"provider": "openai", "model": "gpt-4.1-mini"},
    "dtag": dict(RUN_DEFAULTS),
    "participants": {"file": "optimizer/personas/gss2024_spectrum.yaml", "decode": "auto", "neutral_band": 0.005,
                     "country": "United States", "year": None,
                     "core_variables": ["polviews", "partyid"], "protect_mapped": True,
                     "perturb": {"drop": 0.15, "resample": 0.15}},
    "bank": {"source": "map", "file": None, "rewrite": False, "mapping": "source", "min_source_recall": 0.5,
             "max_items": None, "include": None, "exclude": None},
    "search": {"length": 10, "min_length": 6, "resp_mode": "draw", "objective": "robust", "seed": 7,
               "screen_reps": 2, "pool": 30, "per_group": 8, "greedy_pool": 20, "search_reps": 4, "budget": 60},
    "validate": {"reps": 30, "states_per_persona": 10, "reps_per_state": 20,
                 "augment_count": 5, "order_baselines": 5,
                 "seed": 900001, "baselines": 20, "baseline_reps": 4},
}
QUICK = {"bank": {"max_items": 60}, "search": {"length": 6, "min_length": 4, "screen_reps": 1, "pool": 10, "per_group": 3,
                                                "greedy_pool": 8, "search_reps": 2, "budget": 6},
         "validate": {"reps": 6, "states_per_persona": 2, "reps_per_state": 3,
                      "augment_count": 2, "order_baselines": 1,
                      "baselines": 4, "baseline_reps": 2}}


def merge(a: Dict, b: Dict) -> Dict:
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(args) -> Dict[str, Any]:
    cfg = copy.deepcopy(DEFAULTS)
    if args.config:
        cfg = merge(cfg, yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {})
    if args.quick:
        cfg = merge(cfg, QUICK)
    if args.out:
        cfg["out"] = args.out
    if args.provider:
        cfg["llm"] = {"provider": args.provider, **({"model": args.llm_model} if args.llm_model else {})}
    elif args.llm_model:
        cfg["llm"]["model"] = args.llm_model
    if args.workers:
        cfg["workers"] = args.workers
    return cfg


class Ctx:
    """Resolved model/map/poles, the main-process World, LLM, cache and logging."""

    def __init__(self, cfg: Dict[str, Any], need_llm: bool = True):
        self.cfg = cfg
        self.out = Path(cfg["out"]).expanduser()
        self.out.mkdir(parents=True, exist_ok=True)
        self._logf = open(self.out / "log.txt", "a", encoding="utf-8")
        self.model_path = ensure_model(cfg["model"], cfg["model_root"], cfg["download"])
        self.map_path = Path(cfg["map"]).expanduser() if cfg["map"] else canonical_map(cfg["model"])
        self.world_args = (str(self.model_path), str(self.map_path), str(cfg["poles"]), str(self.out / "assets_cache"))
        self.log(f"model {cfg['model']} at {self.model_path}; map {self.map_path.name}")
        self.world = World(*self.world_args)
        self.log(f"poles {self.world.poles_summary()['file']} ({self.world.poles_summary()['items']} items)")
        self.cache = JsonCache(Path(cfg["cache"]).expanduser() if cfg["cache"] else self.out / "llm_cache.json")
        self.llm = make_llm(cfg["llm"]) if need_llm else None
        self.client = DTAGClient(self.llm) if self.llm else None
        self.llm_model = getattr(self.llm, "model", "") or "none"

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        if hasattr(self, "_logf"):
            self._logf.write(line + "\n")
            self._logf.flush()

    def year(self):
        y = self.cfg["participants"].get("year")
        if y is None and self.cfg["model"].startswith("gss/gss_"):
            y = int(self.cfg["model"].rsplit("_", 1)[-1])
        return y

    def needs_llm(self) -> bool:
        c = self.cfg
        people = population.load(c["participants"]["file"])
        decode = c["participants"]["decode"] == "always" or any(p["text"] and not p["state"] for p in people)
        return decode or c["bank"]["rewrite"] or c["bank"]["mapping"] in ("dtag", "verify")

    def participants(self):
        c = self.cfg["participants"]
        self.log(f"participants from {c['file']}:")
        people = population.prepare(self.world, population.load(c["file"]), c["decode"], self.client, self.llm_model,
                                    self.cfg["dtag"], self.cache, float(c["neutral_band"]), c.get("country"), self.year(),
                                    log=self.log, protect_mapped=bool(c.get("protect_mapped", True)),
                                    core_variables=c["core_variables"])
        write_csv(self.out / "participants.csv", [
            {"id": p["id"], "group": {1: "positive", -1: "negative", 0: "neutral"}[p["direction"]], "I0": round(p["I0"], 5),
             "variables": len(p["state"]), "protected": ";".join(p["protected"]),
             "expected_mismatches": len(p["expected_mismatches"]),
             "state_source": p["state_source"], "dropped": "; ".join(p["dropped"]),
             "text": p["text"]} for p in people])
        (self.out / "participants.json").write_text(json.dumps(people, indent=1, ensure_ascii=False))
        return people

    def bank(self, rebuild: bool = False, people=None):
        b = self.cfg["bank"]
        path = self.out / "bank.jsonl"
        manifest_path = self.out / "bank_fingerprint.json"
        protected = sorted({v for p in (people or []) for v in p.get("protected", [])})
        signature = {"bank": b, "model": self.cfg["model"], "map_sha256": sha256(self.map_path),
                     "protected": protected, "llm": self.cfg["llm"], "dtag": self.cfg["dtag"]}
        fingerprint = hashlib.sha256(json.dumps(signature, sort_keys=True, default=str).encode()).hexdigest()
        if path.is_file() and manifest_path.is_file() and not rebuild:
            try:
                saved = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved = {}
            if saved.get("fingerprint") == fingerprint:
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
                self.log(f"bank: reusing {path} ({len(rows)} questions)")
                return rows
            self.log("bank: source/map/persona/LLM configuration changed, rebuilding")
        if b["source"] == "file":
            rows = bankmod.load_file(b["file"])
        else:
            rows = bankmod.from_map(self.world, b.get("max_items"), b.get("include"),
                                    b.get("exclude"), set(protected))
        self.log(f"bank: {len(rows)} candidate questions from {b['source']}")
        if b["rewrite"]:
            if b["source"] != "map":
                self.log("bank.rewrite applies to source=map only; skipped")
            else:
                rows = bankmod.rewrite(self.world, self.llm, rows, log=self.log)
        rows = bankmod.map_bank(self.world, self.client, self.llm_model, rows, b["mapping"],
                                self.cfg["dtag"], self.cache, float(b["min_source_recall"]), log=self.log)
        safe = [q for q in rows if not set(q["variables"]) & set(protected)]
        self.log(f"bank: discarded {len(rows)-len(safe)} questions mapping to protected persona items")
        if not safe:
            raise SystemExit("Question bank empty after protected-anchor filtering")
        bankmod.save(safe, path)
        manifest_path.write_text(json.dumps({"fingerprint": fingerprint, "signature": signature},
                                            indent=2, default=str), encoding="utf-8")
        return safe

    def simulator(self, people, bank):
        # Augmented context must not pre-answer candidate items or alter ideology poles.
        exclude = {v for q in bank for v in q["variables"]}
        exclude |= {v for p in people for v in p.get("protected", [])}
        exclude |= set(self.world.g.left_map) | set(self.world.g.right_map)
        cfg = {**self.cfg["participants"]["perturb"],
               "core": self.cfg["participants"]["core_variables"],
               "exclude_vars": sorted(exclude)}
        return Simulator(self.world_args, cfg, self.cfg["workers"])

    def manifest(self, bank_size: int) -> Dict[str, Any]:
        try:
            commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        except Exception:
            commit = ""
        rec = model_record(self.cfg["model"])
        return {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "git_commit": commit, "python": platform.python_version(),
                "model": {"key": self.cfg["model"], "path": str(self.model_path), "release": rec.get("release"),
                          "sha256": rec.get("sha256")},
                "map": {"file": self.map_path.name, "path": str(self.map_path), "sha256": sha256(self.map_path)},
                "poles": self.world.poles_summary(), "llm": self.llm.describe() if self.llm else None,
                "llm_calls": getattr(self.llm, "calls", 0), "bank_size": bank_size, "config": self.cfg}


def validate_and_report(ctx: Ctx, sim: Simulator, people, bank, seq: List[str], length: int, extra: Dict[str, Any]):
    cfg = ctx.cfg
    by_id = {q["id"]: q for q in bank}
    v = cfg["validate"]
    band = float(cfg["participants"]["neutral_band"])
    n_states = int(v.get("states_per_persona", 1))
    reps = int(v.get("reps_per_state") or v["reps"])
    runs = sim.make_runs(people, reps, int(v["seed"]), only_directed=False,
                         states_per_persona=n_states, augment_count=int(v.get("augment_count", 0)))
    ctx.log(f"validation: {len(runs)} held-out trajectories on {n_states} starting states/persona, "
            f"{reps} draws/state; direction from actual starting ideology")
    trajs = sim.simulate(runs, [by_id[i]["variables"] for i in seq],
                         cfg["search"]["resp_mode"], trajectories=True)
    rng = np.random.default_rng(12345)
    per_len = []
    chosen_state_rows, chosen_state_summary = [], {}
    for k in range(1, len(seq) + 1):
        st = dict(length=k, **summarize(people, runs, trajs, k, rng, neutral_band=band))
        state_rows, diag = state_diagnostics(people, runs, trajs, k, rng, band)
        if n_states > 1:
            # State is the independent unit. Repeated answer draws per state are nested.
            for name, direction in (("positive", 1), ("negative", -1)):
                st[name]["mean_signed_change_ci"] = diag["groups"][name]["mean_signed_change_ci"]
                values = np.array([row["mean_signed_change"] for row in state_rows
                                   if row["start_group"] == direction])
                if len(values) > 1:
                    scale = float(values.std(ddof=1))
                    st[name]["t"] = float(values.mean() / (scale / np.sqrt(len(values)))) if scale > 0 else (
                        float("inf") if values.mean() > 0 else float("-inf"))
            positive = np.array([r["mean_signed_change"] for r in state_rows if r["start_group"] == 1])
            negative = np.array([r["mean_signed_change"] for r in state_rows if r["start_group"] == -1])
            if len(positive) > 1 and len(negative) > 1:
                gap = rng.choice(positive, (2000, len(positive))).mean(axis=1) + (
                    rng.choice(negative, (2000, len(negative))).mean(axis=1))
                st["separation_change_ci"] = [float(positive.mean()+negative.mean()),
                                               float(np.quantile(gap, .025)), float(np.quantile(gap, .975))]
            st["both_outward_ci_exclude_zero"] = bool(
                st["positive"]["mean_signed_change_ci"][1] > 0 and
                st["negative"]["mean_signed_change_ci"][1] > 0)
        per_len.append(st)
        if k == length:
            chosen_state_rows, chosen_state_summary = state_rows, diag
    summary = per_len[length - 1]
    parts = per_participant(people, runs, trajs, length, rng, neutral_band=band)
    for name in ("positive", "negative"):
        ci = summary[name]["mean_signed_change_ci"]
        ctx.log(f"  {name}: signed change {ci[0]:+.4f} [{ci[1]:+.4f}, {ci[2]:+.4f}], "
                f"states with mean outward {chosen_state_summary['groups'][name]['share_states_mean_outward']:.0%}")
    ctx.log(f"  separation change: {summary['separation_change_ci']}")
    baseline_rows, baseline_summary = [], None
    if int(v["baselines"]) > 0:
        baseline_rows, baseline_summary = baselines(
            sim, people, bank, length, int(v["baselines"]), int(v["baseline_reps"]),
            int(v["seed"]) + 1, cfg["search"]["resp_mode"], cfg["search"]["objective"],
            seq[:length], neutral_band=band, validation_runs=runs)
        ctx.log(f"  random-bank percentile by objective: {baseline_summary['percentile_objective']:.0%}")
    order_rows = order_controls(sim, people, runs, bank, seq[:length],
                                int(v.get("order_baselines", 0)), cfg["search"]["resp_mode"],
                                band, int(v["seed"]) + 7)
    detail = [{"step": n, "id": i, "question": by_id[i]["question"],
               "variables": ";".join(by_id[i]["variables"]),
               "mapping": by_id[i].get("mapping", ""),
               "survey_wording": "; ".join(ctx.world.text.get(z, "") for z in by_id[i]["variables"])}
              for n, i in enumerate(seq, 1)]
    write_question_set(ctx.out / "question_set.csv", [d["question"] for d in detail[:length]])
    write_question_set(ctx.out / "question_set_full.csv", [d["question"] for d in detail])
    write_csv(ctx.out / "question_set_detail.csv", detail)
    write_csv(ctx.out / "per_participant.csv", parts)
    write_csv(ctx.out / "per_state.csv", chosen_state_rows)
    write_csv(ctx.out / "baselines.csv", baseline_rows)
    write_csv(ctx.out / "order_baselines.csv", order_rows)
    flat = [{"length": row["length"],
             **{f"{g}_{key}": row[g][key] for g in ("positive", "negative")
                for key in ("mean_signed_change", "t", "share_outward")},
             **{f"{g}_ci_low": row[g]["mean_signed_change_ci"][1] for g in ("positive", "negative")},
             **{f"{g}_ci_high": row[g]["mean_signed_change_ci"][2] for g in ("positive", "negative")},
             "separation_change": row["separation_change_ci"][0],
             "separation_ci_low": row["separation_change_ci"][1],
             "separation_ci_high": row["separation_change_ci"][2],
             "both_ci_exclude_zero": row["both_outward_ci_exclude_zero"]} for row in per_len]
    write_csv(ctx.out / "per_length.csv", flat)
    # Record each DISTINCT initialized state for exact downstream audits.
    starts = {}
    for r in runs:
        starts.setdefault(r[4], {
            "state_id": r[4], "participant": people[r[0]]["id"], "I_start": r[2],
            "state": r[1], "protected_values": people[r[0]].get("protected_values", {})})
    with open(ctx.out / "starting_states.jsonl", "w", encoding="utf-8") as fh:
        for record in starts.values():
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    (ctx.out / "state_diagnostics.json").write_text(
        json.dumps(chosen_state_summary, indent=2, default=float))
    np.savez_compressed(ctx.out / "validation_trajectories.npz",
                        trajectories=np.asarray(trajs), participant=np.asarray([r[0] for r in runs]),
                        direction=np.asarray([1 if r[2] > band else -1 if r[2] < -band else 0 for r in runs]),
                        initial_ideology=np.asarray([r[2] for r in runs]),
                        state_id=np.asarray([r[4] for r in runs]))
    val = {"length": length, "runs_per_state": reps, "states_per_persona": n_states,
           "runs_per_participant": reps*n_states, "summary": summary, "per_length": per_len,
           "state_diagnostics": chosen_state_summary,
           "order_baselines": len(order_rows), "baselines": baseline_summary, **extra}
    (ctx.out / "validation.json").write_text(json.dumps(val, indent=2, default=float))
    (ctx.out / "manifest.json").write_text(json.dumps(ctx.manifest(len(bank)), indent=2, default=str))
    (ctx.out / "report.md").write_text(report_md(
        cfg, ctx.manifest(len(bank)), people, detail, val, per_len, baseline_summary, parts), encoding="utf-8")
    ctx.log(f"wrote {ctx.out}/report.md and question_set.csv ({length} questions)")


def cmd_check(ctx: Ctx, args) -> None:
    ctx.participants()
    if ctx.llm:
        ctx.log(f"LLM {ctx.llm.describe()}: test call ...")
        out = ctx.llm.complete('Return {"ok": true}.', schema={"type": "object", "properties": {"ok": {"type": "boolean"}},
                                                                  "required": ["ok"], "additionalProperties": False},
                               schema_name="ping")
        ctx.log(f"  reply: {out}")
    ctx.log("check passed")


def cmd_run(ctx: Ctx, args) -> None:
    cfg, s = ctx.cfg, ctx.cfg["search"]
    people = ctx.participants()
    bank = ctx.bank(args.rebuild_bank, people)
    sim = ctx.simulator(people, bank)
    try:
        se = Searcher(sim, people, bank, s["resp_mode"], s["objective"], log=ctx.log,
                      neutral_band=float(cfg["participants"]["neutral_band"]))
        seed = int(s["seed"])
        screen_runs = sim.make_runs(people, int(s["screen_reps"]), seed * 10 + 1)
        ctx.log(f"screening {len(bank)} questions on {len(screen_runs)} runs")
        pool, screen_rows = se.screen(screen_runs, int(s["pool"]), int(s["per_group"]))
        write_csv(ctx.out / "screening.csv", screen_rows)
        ctx.log(f"greedy build of {s['length']} questions from the top {s['greedy_pool']}")
        seq = se.greedy(pool[: int(s["greedy_pool"])], screen_runs, int(s["length"]))
        search_runs = sim.make_runs(people, int(s["search_reps"]), seed * 10 + 2)
        ctx.log(f"local search: {s['budget']} evaluations on {len(search_runs)} runs, pool {len(pool)}")
        seq, history = se.local_search(seq, pool, search_runs, int(s["budget"]), seed)
        length, len_rows = se.choose_length(seq, search_runs, int(s["min_length"]))
        ctx.log(f"chosen length {length} (on search runs); {se.evals} sequence evaluations in total")
        (ctx.out / "search.json").write_text(json.dumps({"sequence": seq, "chosen_length": length, "length_scores": len_rows,
                                                         "history": history, "pool": pool, "evaluations": se.evals},
                                                        indent=1, default=float))
        validate_and_report(ctx, sim, people, bank, seq, length, {"search_sequence": seq})
    finally:
        sim.close()


def read_sequence(ctx: Ctx, path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for n, r in enumerate(rows, 1):
        q = r["question"].strip()
        vs = [v for v in (r.get("variables") or "").replace(",", ";").split(";") if v.strip()]
        if not vs:
            if not ctx.client:
                raise SystemExit(f"{path} has no `variables` column; configure an LLM so DTAG can map the questions.")
            key = ctx.cache.key("validate_map", sha256(ctx.map_path), q,
                                ctx.llm_model, ctx.cfg["dtag"])
            m = ctx.cache.get(key)
            if m is None:
                m = map_question(ctx.world, ctx.client, q, ctx.llm_model, ctx.cfg["dtag"])
                ctx.cache.put(key, m)
            vs, mapping = m["variables"], m["mapping"]
        else:
            mapping = "given"
        out.append({"id": f"s{n:02d}", "question": q, "variables": vs, "mapping": mapping})
        ctx.log(f"  {n:2d}. {q[:70]} -> {vs or 'NO SURVEY ITEM'}")
    return out


def cmd_validate(ctx: Ctx, args) -> None:
    cfg = ctx.cfg
    people = ctx.participants()
    seq_rows = read_sequence(ctx, args.sequence)
    bank = [q for q in seq_rows if q["variables"]]
    if cfg["validate"]["baselines"] and cfg["bank"]["source"]:
        try:
            bank_all = ctx.bank(False, people)
            bank = bank + [q for q in bank_all if q["id"] not in {b["id"] for b in bank}]
        except SystemExit:
            pass
    sim = ctx.simulator(people, bank)
    try:
        seq = [q["id"] for q in seq_rows if q["variables"]]
        validate_and_report(ctx, sim, people, bank, seq, len(seq), {"validated_file": str(args.sequence)})
    finally:
        sim.close()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m optimizer", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["check", "bank", "run", "validate"])
    ap.add_argument("--config", help="YAML config (see optimizer/config.example.yaml)")
    ap.add_argument("--out", help="output folder (overrides the config)")
    ap.add_argument("--quick", action="store_true", help="small smoke-test settings")
    ap.add_argument("--provider", help="LLM provider: openai | anthropic | command | python | mock")
    ap.add_argument("--llm-model", help="LLM model name for the provider")
    ap.add_argument("--workers", type=int, help="worker processes (default: all cores)")
    ap.add_argument("--rebuild-bank", action="store_true", help="rebuild the question bank even if bank.jsonl exists")
    ap.add_argument("--sequence", help="validate: CSV with a question column (and optional variables column)")
    args = ap.parse_args(argv)
    if args.command == "validate" and not args.sequence:
        ap.error("validate needs --sequence")
    os.chdir(REPO)
    cfg = load_config(args)
    if args.command == "validate" and not args.out:
        cfg["out"] = str(Path(cfg["out"]) / "validation" / Path(args.sequence).stem)
    probe = Ctx.__new__(Ctx)
    probe.cfg = cfg
    need_llm = args.command == "check" or probe.needs_llm() or (args.command == "validate")
    try:
        ctx = Ctx(cfg, need_llm=need_llm)
    except RuntimeError as e:
        if args.command == "validate" or not probe.needs_llm():
            ctx = Ctx(cfg, need_llm=False)
            ctx.log(f"LLM not available ({e}); continuing without it")
        else:
            raise SystemExit(f"LLM setup failed: {e}")
    ctx.log(f"optimizer {args.command}: out={ctx.out}")
    if args.command == "check":
        cmd_check(ctx, args)
    elif args.command == "bank":
        ctx.bank(rebuild=True, people=ctx.participants())
    elif args.command == "run":
        cmd_run(ctx, args)
    else:
        cmd_validate(ctx, args)


if __name__ == "__main__":
    main()
