#!/usr/bin/env python3
"""Prepare survey CSVs and train native LSM models into DTAG's model tree.

The native C++ LSM executable consumes a headered CSV with no respondent-index
column.  This script makes that contract explicit and reproducible:

    source CSV
      -> optional deterministic row sample
      -> remove respondent index column
      -> normalize missing values to empty strings
      -> drop columns that are all empty IN THE TRAINING SAMPLE
      -> write prepared CSV + training index/provenance
      -> run native LSM
      -> place final model under models/lsm/<family>/<model_name>/

It can use configs/native_lsm_catalog.yaml or simply train every CSV in a
directory.  Nothing is written to the legacy models.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import yaml

from dtag_paths import model_root, resolve_repo_path


ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_catalog(path: Path) -> Dict[str, Any]:
    obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"Catalog must be a mapping: {path}")
    return obj


def resolve_lsm_commit(lsm_bin: Path) -> str:
    # Typical layout is <lsm_repo>/bin/LSM.
    for parent in [lsm_bin.parent.parent, lsm_bin.parent, *lsm_bin.parents]:
        if (parent / ".git").exists():
            try:
                return subprocess.check_output(
                    ["git", "-C", str(parent), "rev-parse", "HEAD"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
            except Exception:
                pass
    return ""


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        s = out[c]
        # Preserve categorical text; native LSM uses empty string as missing.
        s = s.where(~s.isna(), "")
        s = s.astype(str).str.strip()
        s = s.replace({"nan": "", "NaN": "", "None": "", "<NA>": ""})
        out[c] = s
    return out


def choose_index_column(df: pd.DataFrame, requested: str) -> Optional[str]:
    req = (requested or "").strip()
    if req and req.lower() not in {"auto", "none", "off"}:
        if req not in df.columns:
            raise ValueError(f"Requested index column {req!r} is not present")
        return req
    if req.lower() in {"none", "off"}:
        return None

    # Conservative auto-detection: known respondent-ID names first; otherwise
    # only treat the first column as an index when it is nearly unique.
    by_lower = {str(c).strip().lower(): str(c) for c in df.columns}
    for key in (
        "respondent_id", "respondentid", "respid", "resp_id", "respno",
        "resno", "caseid", "case_id", "id",
    ):
        if key in by_lower:
            return by_lower[key]

    if len(df.columns):
        c = str(df.columns[0])
        nonempty = df[c].dropna()
        if len(nonempty) and nonempty.nunique(dropna=True) / max(1, len(nonempty)) >= 0.98:
            return c
    return None


def deterministic_sample(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    if n <= 0 or n >= len(df):
        return df.copy()
    return df.sample(n=n, random_state=seed, replace=False).sort_index()


def write_training_index(path: Path, values: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump([str(x) for x in values], f)


def unique_match(source_dir: Path, patterns: List[str]) -> Optional[Path]:
    hits: List[Path] = []
    for pat in patterns:
        hits.extend(source_dir.glob(pat))
    hits = sorted({p.resolve() for p in hits if p.is_file() and p.suffix.lower() == ".csv"})
    if not hits:
        return None
    if len(hits) > 1:
        names = "\n  ".join(str(p) for p in hits[:20])
        raise RuntimeError(
            f"Catalog patterns matched more than one CSV. Narrow the pattern or use --input.\n  {names}"
        )
    return hits[0]


def prepared_paths(work_root: Path, family: str, model_name: str) -> tuple[Path, Path, Path]:
    work = work_root / family / model_name
    return work, work / "prepared.csv", work / "training_index.json.gz"


def prepare_one(
    source: Path,
    family: str,
    model_name: str,
    output_dir: Path,
    work_root: Path,
    index_column: str,
    sample_size: int,
    seed: int,
    drop_columns: List[str],
    alpha: float,
    subset_mode: str,
    max_exact_levels: int,
    fast_levels: int,
    lsm_commit: str,
    force: bool,
) -> tuple[Path, Dict[str, Any]]:
    work, prepared_csv, training_index = prepared_paths(work_root, family, model_name)
    work.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    if prepared_csv.exists() and not force:
        manifest_path = output_dir / "training_manifest.json"
        if manifest_path.exists():
            return prepared_csv, json.loads(manifest_path.read_text(encoding="utf-8"))

    df0 = pd.read_csv(source, dtype=str, keep_default_na=False, low_memory=False)
    raw_rows = len(df0)
    raw_cols = len(df0.columns)

    idx_col = choose_index_column(df0, index_column)
    sampled = deterministic_sample(df0, sample_size, seed)

    if idx_col is not None:
        row_ids = sampled[idx_col].tolist()
    else:
        row_ids = sampled.index.tolist()

    sampled = normalize_frame(sampled)

    dropped_requested = []
    for c in drop_columns:
        if c in sampled.columns:
            sampled = sampled.drop(columns=[c])
            dropped_requested.append(c)

    if idx_col is not None and idx_col in sampled.columns:
        sampled = sampled.drop(columns=[idx_col])

    # This is deliberately AFTER row sampling.  A column that is populated in
    # the full survey can still be empty in the selected training sample.
    all_empty = [
        str(c) for c in sampled.columns
        if sampled[c].astype(str).str.strip().eq("").all()
    ]
    if all_empty:
        sampled = sampled.drop(columns=all_empty)

    if sampled.shape[1] == 0:
        raise RuntimeError(f"No model features remain after preprocessing: {source}")

    sampled.to_csv(prepared_csv, index=False)
    write_training_index(training_index, row_ids)

    manifest: Dict[str, Any] = {
        "format": "dtag-native-lsm-training-manifest-v1",
        "model_name": model_name,
        "family": family,
        "backend": "native_lsm",
        "source_file": str(source.resolve()),
        "source_sha256": sha256_file(source),
        "raw_rows": raw_rows,
        "raw_columns": raw_cols,
        "training_rows": len(sampled),
        "training_columns": len(sampled.columns),
        "index_column": idx_col,
        "sample_size_requested": sample_size if sample_size > 0 else None,
        "sample_seed": seed,
        "training_index_file": str(training_index.resolve()),
        "prepared_csv": str(prepared_csv.resolve()),
        "prepared_sha256": sha256_file(prepared_csv),
        "feature_names": [str(c) for c in sampled.columns],
        "feature_hash": hashlib.sha256(
            "\n".join(map(str, sampled.columns)).encode("utf-8")
        ).hexdigest(),
        "dropped_requested_columns": dropped_requested,
        "dropped_all_empty_columns": all_empty,
        "alpha": alpha,
        "subset_mode": subset_mode,
        "max_exact_levels": max_exact_levels,
        "fast_levels": fast_levels,
        "lsm_git_commit": lsm_commit,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model_dir": str(output_dir.resolve()),
    }
    (output_dir / "training_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return prepared_csv, manifest


def run_lsm(
    lsm_bin: Path,
    prepared_csv: Path,
    output_dir: Path,
    alpha: float,
    threads: int,
    subset_mode: str,
    max_exact_levels: int,
    fast_levels: int,
    force: bool,
    dry_run: bool,
) -> None:
    complete = (
        (output_dir / "meta.txt").exists()
        and (output_dir / "source_maps").is_dir()
        and (output_dir / "trees" / "binary").is_dir()
    )
    if complete and not force:
        print(f"SKIP complete model: {output_dir}")
        return

    cmd = [
        str(lsm_bin),
        str(prepared_csv),
        str(alpha),
        str(output_dir),
        "--threads", str(threads),
        "--subset-mode", subset_mode,
        "--max-exact-levels", str(max_exact_levels),
        "--fast-levels", str(fast_levels),
    ]
    print(shlex.join(cmd))
    if dry_run:
        return
    subprocess.run(cmd, check=True)

    if not (output_dir / "source_maps").is_dir():
        raise RuntimeError(f"LSM completed but source_maps/ is missing: {output_dir}")
    if not (output_dir / "trees" / "binary").is_dir():
        raise RuntimeError(f"LSM completed but trees/binary/ is missing: {output_dir}")


def catalog_jobs(
    catalog: Dict[str, Any],
    source_dir: Path,
    selected: List[str],
    family_filter: str,
) -> List[Dict[str, Any]]:
    models = catalog.get("models", {}) or {}
    jobs: List[Dict[str, Any]] = []
    for name, spec in models.items():
        if not isinstance(spec, dict):
            continue
        family = str(spec.get("family", "")).strip()
        if family_filter and family != family_filter:
            continue
        if selected and name not in selected:
            continue
        patterns = [str(x) for x in (spec.get("source_globs") or [])]
        source = unique_match(source_dir, patterns) if patterns else None
        if source is None:
            print(f"MISSING source for {name}; patterns={patterns}", file=sys.stderr)
            continue
        item = dict(spec)
        item["name"] = str(name)
        item["family"] = family
        item["source"] = source
        jobs.append(item)

    # Planned survey families can be populated directly from a directory even
    # before every wave has an explicit catalog entry.  This is especially
    # useful for Eurobarometer, where each ZA wave becomes its own native LSM.
    if family_filter and not selected:
        planned = (catalog.get("planned_families", {}) or {}).get(family_filter)
        if isinstance(planned, dict):
            source_glob = str(planned.get("source_glob", "*.csv"))
            output_template = str(
                planned.get("output_template", f"models/lsm/{family_filter}/{{stem}}")
            )
            existing_sources = {Path(j["source"]).resolve() for j in jobs}
            for source in sorted(source_dir.glob(source_glob)):
                if not source.is_file() or source.suffix.lower() != ".csv":
                    continue
                source = source.resolve()
                if source in existing_sources:
                    continue
                stem = source.stem
                item = {
                    "name": stem,
                    "family": family_filter,
                    "source": source,
                    "output": output_template.format(stem=stem, ZA=stem.upper()),
                }
                jobs.append(item)
    return jobs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_dir", nargs="?", default=".", help="Directory containing survey CSVs")
    ap.add_argument("--catalog", default="configs/native_lsm_catalog.yaml")
    ap.add_argument("--model", action="append", default=[], help="Catalog model name; repeat as needed")
    ap.add_argument("--family", default="", help="Restrict catalog models to one survey family")
    ap.add_argument("--input", action="append", default=[], help="Direct CSV path; bypass catalog matching")
    ap.add_argument("--model-name", default="", help="Name for a single --input CSV")
    ap.add_argument("--output-root", default=str(model_root(ROOT)))
    ap.add_argument("--work-root", default="outputs/native_lsm_training")
    ap.add_argument("--lsm-bin", default=os.environ.get("LSM_BIN", ""))
    ap.add_argument("--index-column", default="auto", help="column name, auto, or none")
    ap.add_argument("--drop-column", action="append", default=[])
    ap.add_argument("--sample-size", type=int, default=0, help="0 = all rows")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--alpha", type=float, default=0.1)
    ap.add_argument("--threads", type=int, default=max(1, os.cpu_count() or 1))
    ap.add_argument("--subset-mode", choices=["exact", "fast", "auto"], default="auto")
    ap.add_argument("--max-exact-levels", type=int, default=20)
    ap.add_argument("--fast-levels", type=int, default=16)
    ap.add_argument("--prepare-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    source_dir = Path(args.source_dir).expanduser().resolve()
    output_root = resolve_repo_path(args.output_root, ROOT)
    work_root = (ROOT / args.work_root).resolve() if not Path(args.work_root).is_absolute() else Path(args.work_root).resolve()

    if args.input:
        if len(args.input) > 1 and args.model_name:
            raise SystemExit("--model-name can only be used with one --input")
        jobs = []
        for raw in args.input:
            p = Path(raw).expanduser().resolve()
            if not p.exists():
                raise SystemExit(f"Missing input: {p}")
            name = args.model_name or p.stem
            family = args.family or "custom"
            jobs.append({"name": name, "family": family, "source": p})
    else:
        catalog_path = (ROOT / args.catalog).resolve() if not Path(args.catalog).is_absolute() else Path(args.catalog).resolve()
        catalog = load_catalog(catalog_path)
        jobs = catalog_jobs(catalog, source_dir, args.model, args.family)

    if not jobs:
        raise SystemExit("No matching CSV jobs found.")

    lsm_bin = Path(args.lsm_bin).expanduser().resolve() if args.lsm_bin else None
    if not args.prepare_only and not args.dry_run:
        if lsm_bin is None or not lsm_bin.is_file():
            raise SystemExit("Provide --lsm-bin /path/to/lsm/bin/LSM or set LSM_BIN")
        if not os.access(lsm_bin, os.X_OK):
            raise SystemExit(f"LSM binary is not executable: {lsm_bin}")

    lsm_commit = resolve_lsm_commit(lsm_bin) if lsm_bin else ""

    for job in jobs:
        name = str(job["name"])
        family = str(job.get("family") or args.family or "custom")
        source = Path(job["source"]).resolve()

        output_rel = str(job.get("output", "")).strip()
        if output_rel:
            output_dir = resolve_repo_path(output_rel, ROOT)
        else:
            output_dir = output_root / family / name

        if args.force and output_dir.exists():
            # A forced retrain must start from a clean model directory.
            # Native LSM writes tree_<id>.bin files but does not guarantee
            # removal of obsolete files from a previous wider model. Leaving
            # stale trees behind can make the serialized model width disagree
            # with the newly prepared training feature set.
            print(f"REMOVE stale model directory: {output_dir}")
            shutil.rmtree(output_dir)

        sample_size = int(job.get("sample_size", args.sample_size) or 0)
        index_column = str(job.get("index_column", args.index_column))
        alpha = float(job.get("alpha", args.alpha))
        subset_mode = str(job.get("subset_mode", args.subset_mode))
        max_exact_levels = int(job.get("max_exact_levels", args.max_exact_levels))
        fast_levels = int(job.get("fast_levels", args.fast_levels))

        print(f"\n== {name} ==")
        print(f"source: {source}")
        print(f"model : {output_dir}")

        prepared_csv, _manifest = prepare_one(
            source=source,
            family=family,
            model_name=name,
            output_dir=output_dir,
            work_root=work_root,
            index_column=index_column,
            sample_size=sample_size,
            seed=args.seed,
            drop_columns=list(args.drop_column),
            alpha=alpha,
            subset_mode=subset_mode,
            max_exact_levels=max_exact_levels,
            fast_levels=fast_levels,
            lsm_commit=lsm_commit,
            force=args.force,
        )

        if not args.prepare_only:
            if lsm_bin is None:
                # dry-run without a concrete binary: still print a portable command.
                bin_text = "$LSM_BIN"
                print(
                    f"{bin_text} {shlex.quote(str(prepared_csv))} {alpha} "
                    f"{shlex.quote(str(output_dir))} --threads {args.threads} "
                    f"--subset-mode {subset_mode} --max-exact-levels {max_exact_levels} "
                    f"--fast-levels {fast_levels}"
                )
            else:
                run_lsm(
                    lsm_bin=lsm_bin,
                    prepared_csv=prepared_csv,
                    output_dir=output_dir,
                    alpha=alpha,
                    threads=args.threads,
                    subset_mode=subset_mode,
                    max_exact_levels=max_exact_levels,
                    fast_levels=fast_levels,
                    force=args.force,
                    dry_run=args.dry_run,
                )

    print(f"\nPrepared/processed {len(jobs)} native LSM model job(s).")


if __name__ == "__main__":
    main()
