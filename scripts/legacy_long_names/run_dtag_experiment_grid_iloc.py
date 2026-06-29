#!/usr/bin/env python3
"""
Run DTAG/pipeline6 or pipeline6iloc experiments over a grid of personas, question CSVs, order variants,
and stochastic replicates, with outputs organized for postprocessing.

This launcher is designed for pipeline6.py / pipeline6iloc.py, which expect:
  --autoplay_csv <questions.csv>
  --polar_vectors <polar_vectors.csv>
  --logs_dir <directory>
  --assets_dir <directory>

Default personas match the earlier WF/CM DTAG tests, but a JSON file can override them.

Example:
  python3 run_dtag_experiment_grid.py \
    --pipeline ./pipeline6.py \
    --question_dir ./assets/question_sets \
    --outdir ./dtag_batch_out \
    --map maps/map2022.csv \
    --polar_vectors assets/polar_vectors.csv \
    --runs_per_condition 6 \
    --parallel 8 \
    --variants forward,reverse,shuffle \
    --shuffle_orders 3

Persona JSON format:
[
  {
    "id": "WF",
    "qnet": "../survey/models/gss/gss_2022female.pkl.gz",
    "persona": "22 year old white female ... highly progressive",
    "year": 2022,
    "country": "United States"
  },
  {
    "id": "CM",
    "qnet": "../survey/models/gss/gss_2022male.pkl.gz",
    "persona": "45 year old white male ... conservative"
  }
]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import shutil
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd


DEFAULT_PERSONAS = [
    {
        "id": "WF",
        "qnet": "../survey/models/gss/gss_2022female.pkl.gz",
        "persona": "22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive",
    },
    {
        "id": "CM",
        "qnet": "../survey/models/gss/gss_2022male.pkl.gz",
        "persona": "45 year old white male with children in rural Alabama, regular news consumer, working in farming, veteran, conservative",
    },
]


def safe_slug(x: str, max_len: int = 96) -> str:
    x = str(x or "").strip()
    x = re.sub(r"\.[Cc][Ss][Vv]$", "", x)
    x = re.sub(r"[^A-Za-z0-9._-]+", "_", x)
    x = x.strip("._-") or "item"
    if len(x) <= max_len:
        return x
    h = hashlib.sha1(x.encode("utf-8")).hexdigest()[:8]
    return f"{x[: max_len - 9]}_{h}"


def abspath(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def mkdir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_questions_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str).fillna("")
    if df.shape[1] == 0:
        raise ValueError(f"No columns found in question CSV: {path}")
    if "question" not in df.columns:
        # pipeline6.py accepts first column if no 'question', but for generated variants
        # we normalize to a clean question column.
        df = df.rename(columns={df.columns[0]: "question"})
    df["question"] = df["question"].astype(str).str.strip()
    df = df[df["question"] != ""].copy()
    if "step" not in df.columns:
        df.insert(0, "step", range(1, len(df) + 1))
    return df


def write_question_variant(df: pd.DataFrame, out_csv: Path) -> None:
    keep_cols = []
    if "step" in df.columns:
        keep_cols.append("step")
    if "question" in df.columns:
        keep_cols.append("question")
    # Preserve additional metadata columns after question when present. pipeline6 will use 'question'.
    for c in df.columns:
        if c not in keep_cols:
            keep_cols.append(c)
    out = df.loc[:, keep_cols].copy()
    out["step"] = range(1, len(out) + 1)
    out.to_csv(out_csv, index=False)


def make_question_variants(
    src_csv: Path,
    variant_dir: Path,
    variants: Sequence[str],
    shuffle_orders: int,
    seed: int,
) -> List[Tuple[str, Path]]:
    df0 = read_questions_csv(src_csv)
    qset = safe_slug(src_csv.stem)
    out: List[Tuple[str, Path]] = []
    mkdir(variant_dir)

    for var in variants:
        var = var.strip().lower()
        if not var:
            continue
        if var == "forward":
            vname = "forward"
            out_csv = variant_dir / f"{qset}__{vname}.csv"
            write_question_variant(df0, out_csv)
            out.append((vname, out_csv))
        elif var == "reverse":
            vname = "reverse"
            out_csv = variant_dir / f"{qset}__{vname}.csv"
            write_question_variant(df0.iloc[::-1].reset_index(drop=True), out_csv)
            out.append((vname, out_csv))
        elif var == "shuffle":
            n = max(1, int(shuffle_orders))
            for j in range(n):
                rng = random.Random(seed + j + int(hashlib.sha1(str(src_csv).encode()).hexdigest()[:8], 16))
                idx = list(range(len(df0)))
                rng.shuffle(idx)
                vname = f"shuffle{j:02d}"
                out_csv = variant_dir / f"{qset}__{vname}.csv"
                write_question_variant(df0.iloc[idx].reset_index(drop=True), out_csv)
                out.append((vname, out_csv))
        else:
            raise ValueError(f"Unknown variant '{var}'. Use forward, reverse, shuffle.")
    return out


def load_personas(path: str) -> List[Dict[str, object]]:
    if not path:
        return list(DEFAULT_PERSONAS)
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, list):
        raise ValueError("personas_json must contain a list of persona objects")
    personas: List[Dict[str, object]] = []
    for i, p in enumerate(obj):
        if not isinstance(p, dict):
            raise ValueError(f"persona entry {i} is not an object")
        for key in ("id", "qnet", "persona"):
            if key not in p or not str(p[key]).strip():
                raise ValueError(f"persona entry {i} missing required key: {key}")
        item: Dict[str, object] = {
            "id": safe_slug(str(p["id"]), 48),
            "qnet": str(p["qnet"]),
            "persona": str(p["persona"]),
        }
        # Optional per-persona pass-throughs supported by pipeline6iloc.py
        # Examples: {"year": 2022, "country": "United States", "continent": "North America"}
        for opt in ("year", "country", "continent"):
            if opt in p and str(p[opt]).strip():
                item[opt] = p[opt]
        # Optional raw args for one persona, parsed with shlex.
        if "extra_pipeline_args" in p and str(p["extra_pipeline_args"]).strip():
            item["extra_pipeline_args"] = str(p["extra_pipeline_args"])
        personas.append(item)
    return personas

@dataclass
class Job:
    job_id: str
    persona_id: str
    persona: str
    qnet: str
    question_set: str
    variant: str
    source_question_csv: str
    autoplay_csv: str
    replicate: int
    seed: int
    tag: str
    run_dir: str
    stdout_path: str
    cmd: List[str]


@dataclass
class JobResult:
    job_id: str
    status: str
    returncode: int
    seconds: float
    stdout_path: str
    run_dir: str
    meta_json: str = ""
    ideology_csv: str = ""
    questions_csv: str = ""
    final_state_json: str = ""
    error: str = ""


def discover_artifacts(run_dir: str) -> Dict[str, str]:
    rd = Path(run_dir)
    def newest(pattern: str) -> str:
        files = sorted(rd.glob(pattern), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        return str(files[0]) if files else ""
    return {
        "meta_json": newest("*.meta.json"),
        "ideology_csv": newest("*.ideology.csv"),
        "questions_csv": newest("*.questions.csv"),
        "final_state_json": newest("*.final_state.json"),
    }


def run_one(job: Job, dry_run: bool = False) -> JobResult:
    t0 = time.time()
    mkdir(Path(job.stdout_path).parent)
    mkdir(job.run_dir)
    if dry_run:
        with open(job.stdout_path, "w", encoding="utf-8") as f:
            f.write("DRY RUN\n")
            f.write(" ".join(job.cmd) + "\n")
        return JobResult(job_id=job.job_id, status="dry_run", returncode=0, seconds=0.0, stdout_path=job.stdout_path, run_dir=job.run_dir)

    try:
        with open(job.stdout_path, "w", encoding="utf-8") as out:
            out.write("COMMAND\n")
            out.write(" ".join(job.cmd) + "\n\n")
            out.flush()
            p = subprocess.run(job.cmd, stdout=out, stderr=subprocess.STDOUT, text=True)
        seconds = time.time() - t0
        artifacts = discover_artifacts(job.run_dir)
        return JobResult(
            job_id=job.job_id,
            status="ok" if p.returncode == 0 else "failed",
            returncode=int(p.returncode),
            seconds=seconds,
            stdout_path=job.stdout_path,
            run_dir=job.run_dir,
            **artifacts,
        )
    except Exception as e:
        seconds = time.time() - t0
        return JobResult(
            job_id=job.job_id,
            status="exception",
            returncode=999,
            seconds=seconds,
            stdout_path=job.stdout_path,
            run_dir=job.run_dir,
            error=repr(e),
        )


def write_csv(path: Path, rows: Iterable[Dict[str, object]], fieldnames: Optional[List[str]] = None) -> None:
    rows = list(rows)
    if not fieldnames:
        keys: List[str] = []
        for r in rows:
            for k in r.keys():
                if k not in keys:
                    keys.append(k)
        fieldnames = keys
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_jsonl(path: Path, rows: Iterable[Dict[str, object]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run DTAG pipeline6 experiments in parallel over question CSVs.")
    ap.add_argument("--pipeline", default="./pipeline6.py", help="Path to pipeline6.py")
    ap.add_argument("--question_dir", required=True, help="Directory containing question CSV files")
    ap.add_argument("--question_glob", default="*.csv", help="Glob for question CSVs inside question_dir")
    ap.add_argument("--outdir", required=True, help="Batch output directory")
    ap.add_argument("--map", required=True, help="Survey variable map CSV passed to pipeline6.py")
    ap.add_argument("--polar_vectors", required=True, help="Polar reference vector CSV passed to pipeline6.py")
    ap.add_argument("--personas_json", default="", help="Optional JSON list of personas. Defaults to WF and CM from prior tests.")

    ap.add_argument("--runs_per_condition", type=int, default=6, help="Stochastic replicates per persona/question-set/order variant")
    ap.add_argument("--parallel", type=int, default=4, help="Number of parallel subprocesses")
    ap.add_argument("--variants", default="forward", help="Comma-separated order variants: forward,reverse,shuffle")
    ap.add_argument("--shuffle_orders", type=int, default=3, help="Number of shuffled order variants when variant includes shuffle")
    ap.add_argument("--seed_base", type=int, default=1000, help="Base RNG seed for pipeline6 replicates and shuffled question orders")

    ap.add_argument("--python", default=sys.executable or "python3", help="Python executable")
    ap.add_argument("--openai_model", default="gpt-4.1-mini", help="OpenAI model passed to pipeline6.py")
    ap.add_argument("--state_keep", type=int, default=500)
    ap.add_argument("--k", type=int, default=50)
    ap.add_argument("--prefilter", type=int, default=200)
    ap.add_argument("--max_assign", type=int, default=50)
    ap.add_argument("--assign_prefilter", type=int, default=500)
    ap.add_argument("--resp_mode", choices=["max", "draw"], default="draw")
    ap.add_argument("--timing", action="store_true", help="Pass --timing to pipeline6.py")
    ap.add_argument("--extra_pipeline_args", default="", help="Optional raw extra args appended to every pipeline6.py call")
    ap.add_argument("--dry_run", action="store_true", help="Write manifests and commands, but do not execute jobs")
    ap.add_argument("--overwrite", action="store_true", help="Allow reuse of existing outdir")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    if outdir.exists() and any(outdir.iterdir()) and not args.overwrite:
        raise SystemExit(f"Outdir exists and is not empty: {outdir}. Use --overwrite or choose a new outdir.")

    pipeline = Path(args.pipeline)
    qdir = Path(args.question_dir)
    if not pipeline.exists():
        raise SystemExit(f"pipeline not found: {pipeline}")
    if not qdir.exists():
        raise SystemExit(f"question_dir not found: {qdir}")

    mkdir(outdir)
    design_dir = mkdir(outdir / "design")
    generated_q_dir = mkdir(outdir / "question_variants")
    runs_root = mkdir(outdir / "runs")
    stdout_root = mkdir(outdir / "stdout")
    assets_dir = mkdir(outdir / "assets_cache")

    # Snapshot key inputs for reproducibility.
    shutil.copy2(pipeline, design_dir / "pipeline6.snapshot.py")
    shutil.copy2(args.polar_vectors, design_dir / "polar_vectors.snapshot.csv")
    with open(design_dir / "launcher_args.json", "w", encoding="utf-8") as f:
        json.dump(vars(args), f, indent=2)

    personas = load_personas(args.personas_json)
    with open(design_dir / "personas_used.json", "w", encoding="utf-8") as f:
        json.dump(personas, f, indent=2, ensure_ascii=False)

    qfiles = sorted(qdir.glob(args.question_glob))
    qfiles = [p for p in qfiles if p.is_file() and p.suffix.lower() == ".csv"]
    # Avoid accidentally treating manifest/label files as experimental question sets.
    qfiles = [p for p in qfiles if "manifest" not in p.stem.lower() and "label" not in p.stem.lower() and "readme" not in p.stem.lower()]
    if not qfiles:
        raise SystemExit(f"No question CSVs found under {qdir} matching {args.question_glob}")

    variants = [v.strip().lower() for v in args.variants.split(",") if v.strip()]
    q_variants_by_source: Dict[str, List[Tuple[str, Path]]] = {}
    for qf in qfiles:
        qset = safe_slug(qf.stem)
        vdir = mkdir(generated_q_dir / qset)
        q_variants_by_source[str(qf)] = make_question_variants(
            src_csv=qf,
            variant_dir=vdir,
            variants=variants,
            shuffle_orders=args.shuffle_orders,
            seed=args.seed_base,
        )

    extra_args = shlex.split(args.extra_pipeline_args) if args.extra_pipeline_args.strip() else []

    jobs: List[Job] = []
    for persona in personas:
        pid = safe_slug(persona["id"], 48)
        for qf in qfiles:
            qset = safe_slug(qf.stem)
            for variant, var_csv in q_variants_by_source[str(qf)]:
                for rep in range(int(args.runs_per_condition)):
                    seed = int(args.seed_base) + rep + 100_000 * (abs(hash((pid, qset, variant))) % 1000)
                    tag = safe_slug(f"{pid}__{qset}__{variant}__r{rep:03d}", 140)
                    run_dir = runs_root / pid / qset / variant / f"rep_{rep:03d}"
                    stdout_path = stdout_root / pid / qset / variant / f"rep_{rep:03d}.out"
                    cmd = [
                        args.python,
                        str(pipeline),
                        "--qnet", persona["qnet"],
                        "--map", args.map,
                        "--persona", persona["persona"],
                        "--autoplay_csv", str(var_csv),
                        "--state_keep", str(args.state_keep),
                        "--k", str(args.k),
                        "--prefilter", str(args.prefilter),
                        "--max_assign", str(args.max_assign),
                        "--assign_prefilter", str(args.assign_prefilter),
                        "--resp_mode", args.resp_mode,
                        "--openai_model", args.openai_model,
                        "--seed", str(seed),
                        "--tag", tag,
                        "--polar_vectors", args.polar_vectors,
                        "--assets_dir", str(assets_dir),
                        "--logs_dir", str(run_dir),
                    ]
                    if args.timing:
                        cmd.append("--timing")
                    # Optional per-persona WVS/location-aware controls for pipeline6iloc.py.
                    if persona.get("year") is not None and str(persona.get("year", "")).strip():
                        cmd.extend(["--year", str(persona["year"])])
                    if str(persona.get("country", "")).strip():
                        cmd.extend(["--country", str(persona["country"])])
                    if str(persona.get("continent", "")).strip():
                        cmd.extend(["--continent", str(persona["continent"])])
                    if str(persona.get("extra_pipeline_args", "")).strip():
                        cmd.extend(shlex.split(str(persona["extra_pipeline_args"])))
                    cmd.extend(extra_args)
                    job_id = hashlib.sha1("|".join([pid, qset, variant, str(rep), str(seed)]).encode()).hexdigest()[:12]
                    jobs.append(Job(
                        job_id=job_id,
                        persona_id=pid,
                        persona=persona["persona"],
                        qnet=persona["qnet"],
                        question_set=qset,
                        variant=variant,
                        source_question_csv=str(qf),
                        autoplay_csv=str(var_csv),
                        replicate=rep,
                        seed=seed,
                        tag=tag,
                        run_dir=str(run_dir),
                        stdout_path=str(stdout_path),
                        cmd=cmd,
                    ))

    job_dicts = []
    for j in jobs:
        d = asdict(j)
        d["cmd"] = " ".join(j.cmd)
        job_dicts.append(d)
    write_csv(outdir / "jobs_planned.csv", job_dicts)
    write_jsonl(outdir / "jobs_planned.jsonl", job_dicts)

    print(f"Planned jobs: {len(jobs)}")
    print(f"Personas: {len(personas)}")
    print(f"Question CSVs: {len(qfiles)}")
    print(f"Order variants per source: {', '.join(variants)}")
    print(f"Output: {outdir}")
    if args.dry_run:
        print("Dry run only: commands written, no experiments executed.")

    results: List[JobResult] = []
    parallel = max(1, int(args.parallel))
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        futures = [ex.submit(run_one, j, args.dry_run) for j in jobs]
        done = 0
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            done += 1
            print(f"[{done}/{len(jobs)}] {res.status}: {res.job_id} ({res.seconds:.1f}s)", flush=True)

    result_dicts = [asdict(r) for r in results]
    write_csv(outdir / "jobs_finished.csv", result_dicts)
    write_jsonl(outdir / "jobs_finished.jsonl", result_dicts)

    # Merge planned-job metadata with discovered artifact paths for easy postprocessing.
    planned_by_id = {j.job_id: asdict(j) for j in jobs}
    index_rows: List[Dict[str, object]] = []
    for r in results:
        row = dict(planned_by_id.get(r.job_id, {}))
        row.update(asdict(r))
        row["cmd"] = " ".join(row.get("cmd", [])) if isinstance(row.get("cmd"), list) else row.get("cmd", "")
        index_rows.append(row)
    write_csv(outdir / "runs_index.csv", index_rows)
    write_jsonl(outdir / "runs_index.jsonl", index_rows)

    n_ok = sum(1 for r in results if r.status in {"ok", "dry_run"})
    n_fail = len(results) - n_ok
    print("DONE")
    print(f"ok_or_dry_run: {n_ok}")
    print(f"failed_or_exception: {n_fail}")
    print(f"runs_index: {outdir / 'runs_index.csv'}")
    print(f"jobs_finished: {outdir / 'jobs_finished.csv'}")

    if n_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
