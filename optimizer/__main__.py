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
        if path.is_file() and not rebuild:
            rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
            self.log(f"bank: reusing {path} ({len(rows)} questions; --rebuild-bank to rebuild)")
            return rows
        if b["source"] == "file":
            rows = bankmod.load_file(b["file"])
        else:
            pvars = {v for p in (people or []) for v in p["state"]}
            rows = bankmod.from_map(self.world, b.get("max_items"), b.get("include"), b.get("exclude"), pvars)
        self.log(f"bank: {len(rows)} candidate questions from {b['source']}")
        if b["rewrite"]:
            if b["source"] != "map":
                self.log("bank.rewrite applies to source=map only; skipped")
            else:
                rows = bankmod.rewrite(self.world, self.llm, rows, log=self.log)
        rows = bankmod.map_bank(self.world, self.client, self.llm_model, rows, b["mapping"], self.cfg["dtag"],
                                self.cache, float(b["min_source_recall"]), log=self.log)
        if not rows:
            raise SystemExit("The bank is empty after mapping.")
        bankmod.save(rows, path)
        return rows

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
    runs = sim.make_runs(people, int(v["reps"]), int(v["seed"]), only_directed=False)
    ctx.log(f"validation: {len(runs)} held-out runs ({v['reps']} per participant)")
    trajs = sim.simulate(runs, [by_id[i]["variables"] for i in seq], cfg["search"]["resp_mode"], trajectories=True)
    rng = np.random.default_rng(12345)
    directed = [r for r in runs if people[r[0]]["direction"] != 0]
    dtrajs = [t for r, t in zip(runs, trajs) if people[r[0]]["direction"] != 0]
    per_len = [dict(length=L, **summarize(people, directed, dtrajs, L, rng)) for L in range(1, len(seq) + 1)]
    summary = per_len[length - 1]
    parts = per_participant(people, runs, trajs, length, rng)
    for g in ("positive", "negative"):
        s = summary[g]
        ctx.log(f"  {g}: signed change {s['mean_signed_change_ci'][0]:+.4f} [{s['mean_signed_change_ci'][1]:+.4f},"
                f" {s['mean_signed_change_ci'][2]:+.4f}]  t={s['t']:+.2f}  outward {s['share_outward']:.0%}")
    sc = summary["separation_change_ci"]
    ctx.log(f"  separation change {sc[0]:+.4f} [{sc[1]:+.4f}, {sc[2]:+.4f}]")
    base_rows, base_summary = [], None
    if int(v["baselines"]) > 0:
        ctx.log(f"baselines: {v['baselines']} random {length}-question sequences")
        base_rows, base_summary = baselines(sim, people, bank, length, int(v["baselines"]), int(v["baseline_reps"]),
                                            int(v["seed"]) + 1, cfg["search"]["resp_mode"], cfg["search"]["objective"], seq[:length])
        ctx.log(f"  optimized beats {base_summary['percentile_objective']:.0%} of random sets on the objective, "
                f"{base_summary['percentile_separation_change']:.0%} on separation change")

    detail = [{"step": n, "id": i, "question": by_id[i]["question"], "variables": ";".join(by_id[i]["variables"]),
               "mapping": by_id[i].get("mapping", ""), "survey_wording": "; ".join(ctx.world.text.get(x, "") for x in by_id[i]["variables"])}
              for n, i in enumerate(seq, 1)]
    write_question_set(ctx.out / "question_set.csv", [d["question"] for d in detail[:length]])
    write_question_set(ctx.out / "question_set_full.csv", [d["question"] for d in detail])
    write_csv(ctx.out / "question_set_detail.csv", detail)
    write_csv(ctx.out / "per_participant.csv", parts)
    write_csv(ctx.out / "baselines.csv", base_rows)
    flat = [{"length": r["length"],
             **{f"{g}_{k}": r[g][k] for g in ("positive", "negative") for k in ("mean_signed_change", "t", "share_outward")},
             **{f"{g}_ci_low": r[g]["mean_signed_change_ci"][1] for g in ("positive", "negative")},
             **{f"{g}_ci_high": r[g]["mean_signed_change_ci"][2] for g in ("positive", "negative")},
             "separation_change": r["separation_change_ci"][0], "separation_ci_low": r["separation_change_ci"][1],
             "separation_ci_high": r["separation_change_ci"][2], "both_ci_exclude_zero": r["both_outward_ci_exclude_zero"]}
            for r in per_len]
    write_csv(ctx.out / "per_length.csv", flat)
    np.savez_compressed(ctx.out / "validation_trajectories.npz", trajectories=np.array(trajs),
                        participant=np.array([r[0] for r in runs]),
                        direction=np.array([people[r[0]]["direction"] for r in runs]))
    val = {"length": length, "runs_per_participant": int(v["reps"]), "summary": summary, "per_length": per_len,
           "baselines": base_summary, **extra}
    (ctx.out / "validation.json").write_text(json.dumps(val, indent=1, default=float))
    manifest = ctx.manifest(len(bank))
    (ctx.out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    (ctx.out / "report.md").write_text(report_md(cfg, manifest, people, detail, val, per_len, base_summary, parts), encoding="utf-8")
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
            m = map_question(ctx.world, ctx.client, q, ctx.llm_model, ctx.cfg["dtag"])
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
