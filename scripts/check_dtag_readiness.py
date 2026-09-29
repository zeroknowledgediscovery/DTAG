#!/usr/bin/env python3
"""Native-LSM-only DTAG readiness checker.

Checks the clean runtime surface without requiring an OpenAI call:
- Python syntax and required packages
- native LSM Python bindings
- config model/map paths
- configured native validation models
- model/map variable overlap
- GSS polar-vector asset
- question-set CSVs
- Eurobarometer native model/map coverage and fallback provenance

Writes:
  outputs/readiness/DTAG_READINESS_REPORT.md
"""
from __future__ import annotations

import argparse
import csv
import importlib
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml

ROOT_DEFAULT = Path(__file__).resolve().parents[1]
TEXT_COLUMNS = [
    "question_text_filled",
    "question_text",
    "variable_label",
    "dta_variable_label",
    "pdf_short_label",
]


@dataclass
class Finding:
    level: str
    item: str
    detail: str = ""


@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)

    def add(self, level: str, item: str, detail: str = "") -> None:
        self.findings.append(Finding(level.upper(), item, detail))

    def ok(self, item: str, detail: str = "") -> None:
        self.add("OK", item, detail)

    def warn(self, item: str, detail: str = "") -> None:
        self.add("WARN", item, detail)

    def fail(self, item: str, detail: str = "") -> None:
        self.add("FAIL", item, detail)

    def info(self, item: str, detail: str = "") -> None:
        self.add("INFO", item, detail)

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for f in self.findings:
            out[f.level] = out.get(f.level, 0) + 1
        return out

    def print_console(self) -> None:
        for f in self.findings:
            suffix = f" -- {f.detail}" if f.detail else ""
            print(f"[{f.level:<4}] {f.item}{suffix}")
        print("\nSUMMARY", self.counts())

    def markdown(self) -> str:
        counts = self.counts()
        lines = [
            "# DTAG native readiness report",
            "",
            f"- OK: {counts.get('OK', 0)}",
            f"- WARN: {counts.get('WARN', 0)}",
            f"- FAIL: {counts.get('FAIL', 0)}",
            f"- INFO: {counts.get('INFO', 0)}",
            "",
            "| Level | Item | Detail |",
            "|---|---|---|",
        ]
        for f in self.findings:
            detail = str(f.detail).replace("|", "\\|").replace("\n", "<br>")
            item = str(f.item).replace("|", "\\|")
            lines.append(f"| {f.level} | {item} | {detail} |")
        lines.append("")
        return "\n".join(lines)


def resolve(root: Path, value: str) -> Path:
    p = Path(str(value)).expanduser()
    return p if p.is_absolute() else (root / p)


def load_config(path: Path) -> Dict[str, Any]:
    obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"Config is not a mapping: {path}")
    return obj


def check_python_syntax(report: Report, root: Path) -> None:
    files = sorted((root / "scripts").glob("*.py"))
    if not files:
        report.fail("python syntax", "no scripts/*.py files found")
        return
    p = subprocess.run(
        [sys.executable, "-m", "py_compile", *map(str, files)],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if p.returncode == 0:
        report.ok("python syntax", f"{len(files)} scripts compiled")
    else:
        report.fail("python syntax", (p.stdout + p.stderr).strip()[:3000])


def check_imports(report: Report) -> None:
    for mod, pkg in [
        ("openai", "openai"),
        ("pandas", "pandas"),
        ("numpy", "numpy"),
        ("matplotlib", "matplotlib"),
        ("pyreadstat", "pyreadstat"),
        ("pdfplumber", "pdfplumber"),
        ("yaml", "pyyaml"),
    ]:
        try:
            importlib.import_module(mod)
            report.ok(f"python package {pkg}")
        except Exception as e:
            report.fail(f"python package {pkg}", str(e))

    for mod in ("predict_distribution", "qdistance"):
        try:
            importlib.import_module(mod)
            report.ok(f"native LSM binding {mod}")
        except Exception as e:
            hint = os.environ.get("LSM_BINDINGS_DIR", "")
            report.fail(
                f"native LSM binding {mod}",
                f"{e}; LSM_BINDINGS_DIR={hint!r}",
            )


def inspect_map(path: Path) -> tuple[bool, str]:
    try:
        import pandas as pd
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception as e:
        return False, f"cannot read CSV: {e}"
    if "variable" not in df.columns:
        return False, f"missing variable column; columns={list(df.columns)}"
    text_col = next((c for c in TEXT_COLUMNS if c in df.columns), "")
    if not text_col:
        return False, f"missing semantic-text column; columns={list(df.columns)}"
    return True, f"rows={len(df)} text_col={text_col}"


def configured_model_map_pairs(cfg: Dict[str, Any]) -> Dict[str, str]:
    """Return model-key -> map-key inferred from interactive profiles."""
    out: Dict[str, str] = {}
    for spec in (cfg.get("interactive_profiles", {}) or {}).values():
        if not isinstance(spec, dict):
            continue
        model = str(spec.get("qnet", "")).strip()
        map_key = str(spec.get("map", "")).strip()
        if model and map_key and model not in out:
            out[model] = map_key
    return out


def check_config(report: Report, root: Path, cfg: Dict[str, Any], overlap: bool) -> None:
    models = cfg.get("models", {}) or {}
    maps = cfg.get("maps", {}) or {}

    if not isinstance(models, dict):
        report.fail("config models", "models must be a mapping")
        return
    if not isinstance(maps, dict):
        report.fail("config maps", "maps must be a mapping")
        return

    for key, value in sorted(models.items()):
        p = resolve(root, str(value))
        valid = p.is_dir() and (p / "source_maps").is_dir() and (p / "trees" / "binary").is_dir()
        if valid:
            report.ok(f"model {key}", str(p.relative_to(root)))
        else:
            report.warn(f"model {key}", f"native model not installed/complete: {p}")

    for key, value in sorted(maps.items()):
        p = resolve(root, str(value))
        if not p.is_file():
            report.warn(f"map {key}", f"not installed: {p}")
            continue
        ok, detail = inspect_map(p)
        if ok:
            report.ok(f"map {key}", detail)
        else:
            report.fail(f"map {key}", detail)

    if not overlap:
        return

    try:
        from model_backend import load_model
        import pandas as pd
    except Exception as e:
        report.fail("model/map overlap", f"cannot import runtime: {e}")
        return

    pairs = configured_model_map_pairs(cfg)
    for model_key in cfg.get("validation_models", []) or []:
        model_key = str(model_key)
        model_value = models.get(model_key)
        map_key = pairs.get(model_key)
        if not model_value or not map_key or map_key not in maps:
            report.warn(
                f"overlap {model_key}",
                "no configured interactive model/map pair",
            )
            continue

        mp = resolve(root, str(model_value))
        map_path = resolve(root, str(maps[map_key]))
        if not mp.is_dir() or not map_path.is_file():
            report.warn(f"overlap {model_key}", "model or map missing")
            continue

        try:
            model = load_model(mp, backend="native_lsm")
            df = pd.read_csv(map_path, dtype=str, keep_default_na=False)
            map_vars = set(df["variable"].astype(str))
            feat = set(map(str, model.feature_names))
            frac = len(feat & map_vars) / max(1, len(feat))
            if frac >= 0.95:
                report.ok(
                    f"overlap {model_key}",
                    f"{len(feat & map_vars)}/{len(feat)} = {frac:.3f}",
                )
            elif frac >= 0.50:
                report.warn(
                    f"overlap {model_key}",
                    f"{len(feat & map_vars)}/{len(feat)} = {frac:.3f}",
                )
            else:
                report.fail(
                    f"overlap {model_key}",
                    f"{len(feat & map_vars)}/{len(feat)} = {frac:.3f}",
                )
        except Exception as e:
            report.fail(f"overlap {model_key}", str(e))


def create_smoke_csv(root: Path) -> Path:
    import pandas as pd

    out = root / "assets/question_sets/smoke/long_gss_smoke.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    questions = [
        "How satisfied are you with the way democracy works?",
        "Do you trust the national government?",
        "Should government do more to reduce income differences?",
        "How important is environmental protection?",
        "What do you think about immigration?",
    ]
    pd.DataFrame({"question": questions}).to_csv(out, index=False)
    return out


def check_question_sets(report: Report, root: Path, cfg: Dict[str, Any]) -> None:
    try:
        import pandas as pd
    except Exception as e:
        report.fail("question sets", f"pandas unavailable: {e}")
        return

    for key, spec in sorted((cfg.get("question_sets", {}) or {}).items()):
        if not isinstance(spec, dict):
            report.warn(f"question set {key}", "invalid config entry")
            continue
        d = resolve(root, str(spec.get("dir", "")))
        pattern = str(spec.get("glob", "*.csv"))
        files = sorted(d.glob(pattern)) if d.is_dir() else []
        if not files:
            report.warn(f"question set {key}", f"no files: {d}/{pattern}")
            continue

        n_questions = 0
        bad = 0
        for p in files:
            try:
                df = pd.read_csv(p, dtype=str, keep_default_na=False)
                col = "question" if "question" in df.columns else df.columns[0]
                n_questions += int(df[col].astype(str).str.strip().ne("").sum())
            except Exception:
                bad += 1

        if bad:
            report.warn(
                f"question set {key}",
                f"files={len(files)} unreadable={bad} questions={n_questions}",
            )
        else:
            report.ok(
                f"question set {key}",
                f"files={len(files)} questions={n_questions}",
            )


def check_polar_vectors(report: Report, root: Path) -> None:
    p = root / "assets/polar_vectors/polar_vectors.csv"
    if p.is_file():
        report.ok("GSS polar vectors", str(p.relative_to(root)))
    else:
        report.warn("GSS polar vectors", "assets/polar_vectors/polar_vectors.csv missing")


def check_eurobarometer(report: Report, root: Path) -> None:
    model_root = root / "models/lsm/eurobarometer"
    map_root = root / "maps/eurobarometer"
    codebook_root = root / "data/eurobarometer/codebooks"

    models = []
    if model_root.is_dir():
        models = sorted(
            p for p in model_root.iterdir()
            if p.is_dir()
            and (p / "source_maps").is_dir()
            and (p / "trees" / "binary").is_dir()
        )

    maps = list(map_root.glob("ZA*_map.csv")) if map_root.is_dir() else []
    codebooks = list(codebook_root.glob("ZA*_cdb.pdf")) if codebook_root.is_dir() else []

    if not models:
        report.warn("Eurobarometer models", "no installed native ZA models")
        return

    model_zas = {p.name.split("_")[0].upper() for p in models}
    map_zas = {p.stem.replace("_map", "").upper() for p in maps}
    cb_zas = {p.name.split("_")[0].upper() for p in codebooks}

    missing = sorted(model_zas - map_zas)
    exact = sorted(model_zas & map_zas & cb_zas)
    fallback = sorted((model_zas & map_zas) - cb_zas)

    if missing:
        report.warn(
            "Eurobarometer runnable coverage",
            f"{len(model_zas)-len(missing)}/{len(model_zas)} maps; missing={len(missing)}",
        )
    else:
        report.ok(
            "Eurobarometer runnable coverage",
            f"{len(model_zas)}/{len(model_zas)} models have per-ZA maps",
        )

    report.info(
        "Eurobarometer map provenance",
        f"exact_codebook={len(exact)} union_fallback={len(fallback)}",
    )

    unresolved = 0
    total = 0
    if fallback:
        try:
            import pandas as pd
            for za in fallback:
                p = map_root / f"{za}_map.csv"
                df = pd.read_csv(p, dtype=str, keep_default_na=False)
                if "map_provenance" in df.columns:
                    total += len(df)
                    unresolved += int((df["map_provenance"] == "UNRESOLVED_NATIVE").sum())
            if total:
                report.warn(
                    "Eurobarometer fallback quality",
                    f"resolved={(total-unresolved)/total:.3f}; "
                    f"resolved={total-unresolved}/{total}; unresolved={unresolved}",
                )
        except Exception as e:
            report.warn("Eurobarometer fallback quality", str(e))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT_DEFAULT))
    ap.add_argument("--config", default="configs/dtag_config.yaml")
    ap.add_argument("--create-smoke-csv", action="store_true")
    ap.add_argument("--overlap", action="store_true")
    ap.add_argument("--skip-imports", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    config_path = resolve(root, args.config)

    report = Report()

    required = [
        "requirements.txt",
        "scripts/model_backend.py",
        "scripts/pipeline.py",
        "scripts/pipeline_localized.py",
        "scripts/interactive.py",
        "scripts/run.py",
        "scripts/run_grid.py",
        "scripts/post.py",
        "scripts/postprocess.py",
        "scripts/eurobarometer_native.py",
        "configs/dtag_config.yaml",
        "bin/interactive_config.sh",
        "bin/run_config.sh",
        "bin/post_config.sh",
        "bin/dtag_demo.sh",
    ]
    for rel in required:
        p = root / rel
        if p.exists():
            report.ok(f"core {rel}")
        else:
            report.fail(f"core {rel}", "missing")

    check_python_syntax(report, root)

    if not args.skip_imports:
        check_imports(report)

    try:
        cfg = load_config(config_path)
        report.ok("config parse", str(config_path.relative_to(root)))
        check_config(report, root, cfg, overlap=args.overlap)
        if args.create_smoke_csv:
            out = create_smoke_csv(root)
            report.ok("smoke question CSV", str(out.relative_to(root)))
        check_question_sets(report, root, cfg)
    except Exception as e:
        report.fail("configuration", str(e))

    check_polar_vectors(report, root)
    check_eurobarometer(report, root)

    report.print_console()

    outdir = root / "outputs/readiness"
    outdir.mkdir(parents=True, exist_ok=True)
    report_path = outdir / "DTAG_READINESS_REPORT.md"
    report_path.write_text(report.markdown(), encoding="utf-8")
    print(f"\nreport: {report_path}")

    if report.counts().get("FAIL", 0):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
