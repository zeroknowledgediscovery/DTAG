#!/usr/bin/env python3
"""
Repository-level DTAG readiness audit.

Run from the repository root, where ./DTAG is the active simulator folder:

    python3 DTAG/scripts/assess_dtag_repo.py

Optional deeper model/map feature-overlap check:

    python3 DTAG/scripts/assess_dtag_repo.py --overlap

Outputs:
    DTAG/outputs/readiness/REPO_ASSESSMENT.md
    DTAG/outputs/readiness/recommended_smoke_commands.sh
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

TEXT_COLUMNS = ["question_text_filled", "question_text", "dta_variable_label", "pdf_short_label"]
ZA_RE = re.compile(r"(ZA\d{4,5})", re.IGNORECASE)

@dataclass
class Finding:
    level: str
    item: str
    detail: str = ""
    fix: str = ""

@dataclass
class Audit:
    findings: List[Finding] = field(default_factory=list)

    def add(self, level: str, item: str, detail: str = "", fix: str = "") -> None:
        self.findings.append(Finding(level.upper(), item, detail, fix))

    def ok(self, item: str, detail: str = "") -> None:
        self.add("OK", item, detail)

    def info(self, item: str, detail: str = "") -> None:
        self.add("INFO", item, detail)

    def warn(self, item: str, detail: str = "", fix: str = "") -> None:
        self.add("WARN", item, detail, fix)

    def fail(self, item: str, detail: str = "", fix: str = "") -> None:
        self.add("FAIL", item, detail, fix)

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for f in self.findings:
            out[f.level] = out.get(f.level, 0) + 1
        return out

    def print(self) -> None:
        for f in self.findings:
            print(f"[{f.level:<4}] {f.item}" + (f" -- {f.detail}" if f.detail else ""))
            if f.fix:
                print(f"       fix: {f.fix}")
        print("\nSUMMARY:", self.counts())

    def md(self) -> str:
        counts = self.counts()
        lines = [
            "# DTAG repository assessment",
            "",
            "This report is generated from the files present in the current checkout.",
            "",
            "## Summary",
            "",
            f"- OK: {counts.get('OK',0)}",
            f"- WARN: {counts.get('WARN',0)}",
            f"- FAIL: {counts.get('FAIL',0)}",
            f"- INFO: {counts.get('INFO',0)}",
            "",
            "## Findings",
            "",
            "| Level | Item | Detail | Fix |",
            "|---|---|---|---|",
        ]
        for f in self.findings:
            lines.append("| " + " | ".join(md_escape(x) for x in [f.level, f.item, f.detail, f.fix]) + " |")
        lines.append("")
        return "\n".join(lines)

def md_escape(x: Any) -> str:
    return str(x or "").replace("|", "\\|").replace("\n", "<br>")

def resolve_root(explicit: str = "") -> Tuple[Path, Path]:
    if explicit:
        dtag = Path(explicit).expanduser().resolve()
        return dtag.parent, dtag
    cwd = Path.cwd().resolve()
    if (cwd / "DTAG" / "configs" / "dtag_config.yaml").exists():
        return cwd, cwd / "DTAG"
    if (cwd / "configs" / "dtag_config.yaml").exists():
        return cwd.parent, cwd
    raise SystemExit("Cannot find DTAG/configs/dtag_config.yaml. Run from the repository root or pass --root DTAG.")

def rel(base: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except Exception:
        return str(path)

def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""

def load_yaml(path: Path, audit: Audit) -> Dict[str, Any]:
    if not path.exists():
        audit.fail("config", f"missing {path}")
        return {}
    try:
        import yaml  # type: ignore
    except Exception as e:
        audit.fail("PyYAML", str(e), "pip install pyyaml")
        return {}
    try:
        obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        audit.fail("config parse", str(e), "Fix YAML syntax")
        return {}
    if not isinstance(obj, dict):
        audit.fail("config parse", "top-level object is not a mapping")
        return {}
    audit.ok("config parse", rel(path.parent.parent, path))
    return obj

def check_exists(audit: Audit, dtag: Path, p: str, label: Optional[str] = None, required: bool = True) -> bool:
    path = dtag / p
    item = label or p
    if path.exists():
        audit.ok(item, rel(dtag, path))
        return True
    if required:
        audit.fail(item, f"missing {p}")
    else:
        audit.warn(item, f"missing optional {p}")
    return False

def run_cmd(cmd: Sequence[str], cwd: Path, timeout: int = 120) -> Tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode, p.stdout
    except subprocess.TimeoutExpired as e:
        return 124, (e.stdout or "") + "\nTIMEOUT"
    except Exception as e:
        return 127, str(e)

def check_layout(audit: Audit, repo: Path, dtag: Path) -> None:
    audit.info("repository root", rel(repo, repo))
    audit.info("DTAG root", rel(repo, dtag))
    for d in ["assets", "bin", "configs", "data", "maps", "models", "outputs", "scripts"]:
        if (dtag / d).is_dir():
            audit.ok(f"directory {d}", rel(dtag, dtag / d))
        else:
            audit.fail(f"directory {d}", f"missing DTAG/{d}")
    required = [
        "requirements.txt", "configs/dtag_config.yaml", "scripts/pipeline.py", "scripts/run.py", "scripts/run_grid.py",
        "scripts/post.py", "scripts/postprocess.py", "scripts/smoke_test.py", "scripts/check_dtag_readiness.py",
    ]
    for p in required:
        check_exists(audit, dtag, p, f"core file {p}")
    for p, label in [
        ("scripts/interactive.py", "named interactive profile runner"),
        ("bin/interactive_config.sh", "interactive profile wrapper"),
        ("scripts/start_experiment.py", "attribute/country/year router"),
        ("bin/start_experiment.sh", "attribute-router wrapper"),
    ]:
        check_exists(audit, dtag, p, f"convenience {label}", required=False)
    for p, label in [
        ("scripts/getmap_eurobarometer.py", "Eurobarometer PDF/codebook map parser"),
        ("scripts/generate_eurobarometer_maps.sh", "flat ZA CSV/PDF batch map generator"),
        ("scripts/select_eurobarometer_map.py", "Eurobarometer individual/fallback map selector"),
    ]:
        check_exists(audit, dtag, p, f"tool {label}", required=False)
    wrapper = repo / "run_dtag_readiness.sh"
    if wrapper.exists():
        text = read_text(wrapper)
        if "DTAG_latest" in text and "DTAG/configs/dtag_config.yaml" not in text:
            audit.fail(
                "root readiness wrapper",
                "run_dtag_readiness.sh still looks for DTAG_latest and will fail from this repo root",
                "Replace it with a wrapper that calls: python3 DTAG/scripts/check_dtag_readiness.py --root DTAG --create-smoke-csv \"$@\"",
            )
        elif "DTAG/scripts/check_dtag_readiness.py" in text or "--root DTAG" in text:
            audit.ok("root readiness wrapper", "points at DTAG")
        else:
            audit.warn("root readiness wrapper", "present but root-detection logic is unclear")
    else:
        audit.warn("root readiness wrapper", "missing run_dtag_readiness.sh", "Add a root-level wrapper for the readiness check")

def check_python(audit: Audit, dtag: Path, skip_imports: bool) -> None:
    py_files = [str(p) for p in sorted((dtag / "scripts").glob("*.py"))]
    if py_files:
        code, out = run_cmd([sys.executable, "-m", "py_compile", *py_files], cwd=dtag)
        if code == 0:
            audit.ok("python syntax", "scripts/*.py compile")
        else:
            audit.fail("python syntax", out[:3000], "Fix Python syntax errors before runtime tests")
    else:
        audit.fail("python syntax", "no scripts/*.py found")
    if skip_imports:
        return
    for mod, pkg in [("openai","openai"),("pandas","pandas"),("numpy","numpy"),("matplotlib","matplotlib"),("quasinet","quasinet"),("pyreadstat","pyreadstat"),("pdfplumber","pdfplumber"),("yaml","pyyaml")]:
        try:
            __import__(mod)
            audit.ok(f"python package {pkg}")
        except Exception as e:
            audit.fail(f"python package {pkg}", str(e), f"pip install {pkg}")
    if os.environ.get("OPENAI_API_KEY"):
        audit.ok("OPENAI_API_KEY", "set")
    else:
        audit.warn("OPENAI_API_KEY", "not set; LLM-dependent smoke tests will not run", "export OPENAI_API_KEY='...'")

def inspect_map(path: Path) -> Tuple[bool, str, str]:
    try:
        import pandas as pd
        df = pd.read_csv(path, dtype=str, nrows=200).fillna("")
    except Exception as e:
        return False, f"cannot read CSV: {e}", "Fix CSV formatting"
    cols = list(df.columns)
    if "variable" not in cols:
        return False, f"missing variable column; columns={cols}", "Map must contain a variable column"
    text_col = next((c for c in TEXT_COLUMNS if c in cols), None)
    if not text_col:
        return False, f"missing text column; columns={cols}", f"Map needs one of {TEXT_COLUMNS}"
    usable = int((df[text_col].astype(str).str.len() > 20).sum())
    return True, f"columns OK; text_col={text_col}; usable_sample={usable}/{len(df)}", ""

def check_config(audit: Audit, dtag: Path, cfg: Dict[str, Any]) -> None:
    models = cfg.get("models", {}) or {}
    maps = cfg.get("maps", {}) or {}
    exps = cfg.get("experiments", {}) or {}
    if not isinstance(models, dict):
        audit.fail("config.models", "not a mapping"); models = {}
    if not isinstance(maps, dict):
        audit.fail("config.maps", "not a mapping"); maps = {}
    if not isinstance(exps, dict):
        audit.fail("config.experiments", "not a mapping"); exps = {}
    for key, value in sorted(models.items()):
        p = dtag / str(value)
        if p.exists():
            audit.ok(f"config model {key}", str(value))
        else:
            fix = ""
            if key in {"gss_2024_female", "gss_2024_male"} and (dtag / "models/gss/gss_2024.gz").exists():
                fix = "Either create gss_2024female.pkl.gz/gss_2024male.pkl.gz or change config/personas to use models/gss/gss_2024.gz."
            if "euro" in key.lower():
                fix = "Place models/eurobarometer/LSM_ZAxxxx.gz and add config keys."
            audit.fail(f"config model {key}", f"missing {value}", fix)
    for key, value in sorted(maps.items()):
        p = dtag / str(value)
        if p.exists():
            ok, detail, fix = inspect_map(p)
            audit.ok(f"config map {key}", f"{value}; {detail}") if ok else audit.fail(f"config map {key}", f"{value}; {detail}", fix)
        else:
            audit.fail(f"config map {key}", f"missing {value}")
    audit.info("configured experiments", ", ".join(sorted(exps.keys())) if exps else "none")
    if not any("afro" in k.lower() for k in exps):
        audit.warn("Afrobarometer config experiments", "models/maps exist, but no Afrobarometer experiment is configured", "Add afrobarometer_r5_nigeria and/or r1-r9 experiments to configs/dtag_config.yaml.")
    if not any("euro" in k.lower() for k in exps):
        audit.warn("Eurobarometer config experiments", "none configured", "Add Eurobarometer experiments after maps/models exist.")
    if not any("wvs" in k.lower() for k in exps):
        audit.warn("WVS config experiments", "none configured", "Add WVS profiles/experiments if needed.")

def check_gss(audit: Audit, dtag: Path) -> None:
    gss_dir = dtag / "models/gss"
    present = [p.name for p in gss_dir.glob("*") if p.is_file()]
    audit.info("GSS models", ", ".join(present[:20]) + (" ..." if len(present) > 20 else ""))
    for f in ["gss_2022female.pkl.gz", "gss_2022male.pkl.gz", "gss_2022white.pkl.gz", "gss_2022black.pkl.gz"]:
        audit.ok(f"GSS model {f}") if (gss_dir / f).exists() else audit.warn(f"GSS model {f}", "missing optional demographic model")
    if (gss_dir / "gss_2024.gz").exists():
        audit.ok("GSS 2024 pooled/all model", "models/gss/gss_2024.gz")
    if not (gss_dir / "gss_2024female.pkl.gz").exists() or not (gss_dir / "gss_2024male.pkl.gz").exists():
        audit.warn("GSS 2024 sex-specific models", "config references gss_2024female.pkl.gz and gss_2024male.pkl.gz, but only pooled gss_2024.gz is visible", "Either train/copy sex-specific 2024 models or update config to use gss_2024.gz.")
    for m in ["map2022.csv", "map20162020.csv"]:
        p = dtag / "maps" / m
        if p.exists():
            ok, detail, fix = inspect_map(p)
            audit.ok(f"GSS map {m}", detail) if ok else audit.fail(f"GSS map {m}", detail, fix)
        else:
            audit.fail(f"GSS map {m}", "missing")
    if not (dtag / "maps/map2024.csv").exists():
        audit.warn("GSS 2024 map", "map2024.csv not present; config uses map2022 for 2024 templates", "Generate maps/map2024.csv from GSS 2024 data/codebook before paper-scale 2024 experiments.")
    polar = dtag / "assets/polar_vectors/polar_vectors.csv"
    if polar.exists():
        try:
            with polar.open(newline="", encoding="utf-8") as f:
                header = next(csv.reader(f), [])
            audit.ok("GSS polar vectors", f"assets/polar_vectors/polar_vectors.csv; header={header}")
        except Exception as e:
            audit.fail("GSS polar vectors", str(e))
    else:
        audit.fail("GSS polar vectors", "missing assets/polar_vectors/polar_vectors.csv", "Required for GSS ideology trajectories.")

def check_wvs(audit: Audit, dtag: Path) -> None:
    audit.ok("WVS model", "models/wvs/LSM60K.gz") if (dtag / "models/wvs/LSM60K.gz").exists() else audit.fail("WVS model", "missing models/wvs/LSM60K.gz")
    p = dtag / "maps/wvs7_variable_question_map.csv"
    if p.exists():
        ok, detail, fix = inspect_map(p)
        audit.ok("WVS map", detail) if ok else audit.fail("WVS map", detail, fix)
    else:
        audit.fail("WVS map", "missing maps/wvs7_variable_question_map.csv")
    if not (dtag / "assets/country_specs/wvs").exists():
        audit.info("WVS country specs", "not present; pipeline can still use built-in coordinate forcing if features are present")

def check_afro(audit: Audit, dtag: Path) -> None:
    mdir = dtag / "models/afrobarometer"
    amap = dtag / "maps/afromap"
    models = {p.name for p in mdir.glob("*.gz")} if mdir.exists() else set()
    maps = {p.name for p in amap.glob("*.csv")} if amap.exists() else set()
    audit.info("Afrobarometer models", f"{len(models)} gz files")
    audit.info("Afrobarometer maps", f"{len(maps)} csv files")
    for r in range(1, 10):
        model_ok = f"merged_r{r}_data.gz" in models or f"LSM_merged_r{r}_data.gz" in models
        map_ok = f"afrobarometer_r{r}_map.csv" in maps
        if model_ok and map_ok:
            audit.ok(f"Afrobarometer R{r}", "model+map present")
        elif model_ok and not map_ok:
            audit.warn(f"Afrobarometer R{r}", "model present; map missing", f"Generate maps/afromap/afrobarometer_r{r}_map.csv")
        elif map_ok and not model_ok:
            audit.warn(f"Afrobarometer R{r}", "map present; model missing", f"Place models/afrobarometer/merged_r{r}_data.gz or LSM_merged_r{r}_data.gz")
        else:
            audit.warn(f"Afrobarometer R{r}", "model and map missing")
    typo = dtag / "maps/afromap/afrobaromete_r1_map.csv"
    if typo.exists():
        audit.warn("Afrobarometer duplicate typo map", "afrobaromete_r1_map.csv duplicates afrobarometer_r1_map.csv", "Remove the typo copy when cleaning the repo.")

def check_euro(audit: Audit, dtag: Path) -> None:
    base = dtag / "data/eurobarometer"
    maps = dtag / "maps/euromap"
    models = dtag / "models/eurobarometer"
    if not base.exists():
        audit.warn("Eurobarometer data directory", "DTAG/data/eurobarometer is not present in committed files", "Create data/eurobarometer and place flat pairs: ZA1543*.csv and ZA1543*.pdf.")
    else:
        za: Dict[str, Dict[str, List[Path]]] = {}
        for p in base.glob("**/*"):
            if not p.is_file():
                continue
            m = ZA_RE.search(p.name)
            if not m:
                continue
            zid = m.group(1).upper()
            za.setdefault(zid, {"csv": [], "pdf": [], "other": []})
            if p.suffix.lower() == ".csv":
                za[zid]["csv"].append(p)
            elif p.suffix.lower() == ".pdf":
                za[zid]["pdf"].append(p)
            elif p.suffix.lower() in {".sav", ".dta"}:
                za[zid]["other"].append(p)
        if not za:
            audit.warn("Eurobarometer ZA files", "no ZA*.csv/ZA*.pdf files detected", "Use names like data/eurobarometer/ZA1543_anything.csv and ZA1543_anything.pdf.")
        else:
            audit.info("Eurobarometer ZA files", f"found {len(za)} ZA IDs")
            missing_pairs = [z for z, v in za.items() if not v["csv"] or not v["pdf"]]
            if missing_pairs:
                audit.warn("Eurobarometer incomplete CSV/PDF pairs", f"{len(missing_pairs)} incomplete: {missing_pairs[:10]}", "Every ZA needs at least one ZA*.csv and one ZA*.pdf.")
            else:
                audit.ok("Eurobarometer CSV/PDF pairs", f"{len(za)} complete pairs")
    if maps.exists():
        audit.ok("Eurobarometer map directory", "maps/euromap")
        individual = sorted(maps.glob("eurobarometer_ZA*_map.csv"))
        fallback = maps / "eurobarometer_integrated_fallback_map.csv"
        prefixed = maps / "eurobarometer_all_prefixed_map.csv"
        audit.ok("Eurobarometer individual maps", f"{len(individual)} files") if individual else audit.warn("Eurobarometer individual maps", "none found", "Generate one map per ZA wave.")
        audit.ok("Eurobarometer integrated fallback map", "maps/euromap/eurobarometer_integrated_fallback_map.csv") if fallback.exists() else audit.warn("Eurobarometer integrated fallback map", "missing", "Generate fallback map after individual maps.")
        audit.ok("Eurobarometer prefixed pooled map", "present") if prefixed.exists() else audit.info("Eurobarometer prefixed pooled map", "not present; only needed if pooled qnet uses ZAxxxx__variable names")
    else:
        audit.warn("Eurobarometer map directory", "missing maps/euromap", "Create it and generate maps.")
    if models.exists():
        audit.ok("Eurobarometer model directory", "models/eurobarometer")
        emodels = sorted(models.glob("*.gz")) + sorted(models.glob("*.pkl.gz"))
        audit.ok("Eurobarometer models", f"{len(emodels)} model files") if emodels else audit.warn("Eurobarometer models", "directory exists but no .gz/.pkl.gz models", "Train/copy one model per ZA wave, e.g. LSM_ZA1543.gz.")
    else:
        audit.warn("Eurobarometer model directory", "missing models/eurobarometer", "Train/copy models such as models/eurobarometer/LSM_ZA1543.gz.")
    if not (dtag / "scripts/getmap_eurobarometer.py").exists():
        audit.fail("Eurobarometer map parser", "missing scripts/getmap_eurobarometer.py", "Add the Eurobarometer-specific parser.")
    if not (dtag / "scripts/generate_eurobarometer_maps.sh").exists():
        audit.fail("Eurobarometer batch map generator", "missing scripts/generate_eurobarometer_maps.sh", "Add the flat ZA map generator.")
    if not (dtag / "scripts/select_eurobarometer_map.py").exists():
        audit.warn("Eurobarometer map selector", "missing scripts/select_eurobarometer_map.py", "Add selector so individual maps fallback to integrated map.")

def question_csv_ok(path: Path) -> Tuple[bool, str]:
    try:
        import pandas as pd
        df = pd.read_csv(path, dtype=str).fillna("")
    except Exception as e:
        return False, f"read error: {e}"
    if df.empty:
        return False, "empty CSV"
    if not isinstance(df.index, pd.RangeIndex):
        return False, "non-default index; likely unquoted commas in question text"
    col = "question" if "question" in df.columns else df.columns[0]
    qs = [str(x).strip() for x in df[col].tolist() if str(x).strip()]
    if not qs:
        return False, f"no questions in column {col}"
    bad = [q for q in qs if len(q) < 8 or q.lower().startswith(("or ", "and ", "but "))]
    if bad:
        return False, f"suspicious fragments: {bad[:3]}"
    return True, f"{len(qs)} questions"

def check_question_sets(audit: Audit, dtag: Path, cfg: Dict[str, Any], create_smoke: bool) -> None:
    if create_smoke:
        smoke_dir = dtag / "assets/question_sets/smoke"
        smoke_dir.mkdir(parents=True, exist_ok=True)
        smoke = smoke_dir / "long_gss_smoke.csv"
        questions = [
            "Should the number of immigrants to America nowadays be increased, decreased, or kept the same?",
            "Do immigrants take jobs away from people born in America?",
            "Do immigrants increase crime rates?",
            "Should undocumented immigrants be allowed to become citizens?",
            "Do you think the government should do more to reduce income differences?",
            "Should taxes on high-income people be increased?",
            "Do you favor or oppose stricter gun-control laws?",
            "How important is it for the government to protect the environment?",
            "Do you trust the federal government?",
            "Are you satisfied with the way democracy works in America?",
        ]
        with smoke.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["question"])
            w.writeheader()
            for q in questions:
                w.writerow({"question": q})
        audit.ok("smoke question file", "assets/question_sets/smoke/long_gss_smoke.csv")
    qsets = cfg.get("question_sets", {}) or {}
    if not isinstance(qsets, dict):
        audit.fail("question_sets", "not a mapping"); return
    for name, spec in sorted(qsets.items()):
        if not isinstance(spec, dict):
            audit.warn(f"question set {name}", "not a mapping"); continue
        qdir = dtag / str(spec.get("dir", ""))
        glob = str(spec.get("glob", "*.csv"))
        if not qdir.exists():
            audit.fail(f"question set {name}", f"missing {rel(dtag, qdir)}"); continue
        files = sorted(qdir.glob(glob))
        if not files:
            audit.fail(f"question set {name}", f"no files match {rel(dtag, qdir)}/{glob}"); continue
        nbad = 0; ntotal = 0
        for f in files:
            ok, detail = question_csv_ok(f)
            if not ok:
                nbad += 1; audit.warn(f"question CSV {rel(dtag,f)}", detail, "Recreate with a real CSV writer or quote commas.")
            else:
                try: ntotal += int(detail.split()[0])
                except Exception: pass
        audit.warn(f"question set {name}", f"{len(files)} files; {nbad} problematic") if nbad else audit.ok(f"question set {name}", f"{len(files)} files; {ntotal} questions")

def check_pipeline_capabilities(audit: Audit, dtag: Path) -> None:
    text = read_text(dtag / "scripts/pipeline.py")
    for flag in ["--question", "--loop", "--autoplay_csv", "--semantic_fallback", "--semantic_k", "--semantic_prefilter", "--semantic_min_confidence", "--semantic_resp_mode", "--polar_vectors", "--no_ideology", "--require_polar_vectors", "--year", "--country", "--continent"]:
        audit.ok(f"pipeline flag {flag}") if flag in text else audit.fail(f"pipeline flag {flag}", "not found in scripts/pipeline.py")
    audit.ok("semantic fallback modes", "answer_only and update_state present") if ("answer_only" in text and "update_state" in text) else audit.fail("semantic fallback modes", "missing answer_only/update_state")
    audit.ok("location/year forcing function", "build_forced_assignments present") if "build_forced_assignments" in text else audit.warn("location/year forcing function", "not found")

def write_recommended_smokes(outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    script = outdir / "recommended_smoke_commands.sh"
    body = '''#!/usr/bin/env bash
set -euo pipefail

# Run this from the repository root. Subshells keep DTAG-relative paths valid.

echo "== Static DTAG audit =="
python3 DTAG/scripts/assess_dtag_repo.py --root DTAG --create-smoke-csv

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "OPENAI_API_KEY is not set; stopping before LLM-dependent smoke tests."
  exit 0
fi

echo "== GSS: single question with polar vectors =="
(
  cd DTAG
  python3 scripts/pipeline.py \
    --map maps/map2022.csv \
    --qnet models/gss/gss_2022female.pkl.gz \
    --persona "22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive" \
    --polar_vectors assets/polar_vectors/polar_vectors.csv \
    --require_polar_vectors \
    --assets_dir assets \
    --logs_dir outputs/smoke_gss_wf_single \
    --tag smoke_gss_wf_single \
    --year 2022 \
    --country "United States" \
    --question "What do you think about immigration?" \
    --state_keep 500 --k 6 --prefilter 200 --min_map_score 1.0 \
    --semantic_fallback answer_only --semantic_k 6 --semantic_prefilter 80 --semantic_min_confidence 0.35 --semantic_resp_mode max \
    --max_assign 50 --assign_prefilter 500 --resp_mode max --seed 1000 --timing
)

echo "== GSS: long sequence answer_only =="
(
  cd DTAG
  python3 scripts/pipeline.py \
    --map maps/map2022.csv \
    --qnet models/gss/gss_2022female.pkl.gz \
    --persona "22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive" \
    --polar_vectors assets/polar_vectors/polar_vectors.csv \
    --require_polar_vectors \
    --assets_dir assets \
    --logs_dir outputs/smoke_gss_wf_long_answer_only \
    --tag smoke_gss_wf_long_answer_only \
    --year 2022 \
    --country "United States" \
    --autoplay_csv assets/question_sets/smoke/long_gss_smoke.csv \
    --state_keep 500 --k 6 --prefilter 200 --min_map_score 1.0 \
    --semantic_fallback answer_only --semantic_k 6 --semantic_prefilter 80 --semantic_min_confidence 0.35 --semantic_resp_mode max \
    --max_assign 50 --assign_prefilter 500 --resp_mode max --seed 1000 --timing
)

echo "== WVS: India 2017 long sequence, no ideology =="
(
  cd DTAG
  python3 scripts/pipeline.py \
    --map maps/wvs7_variable_question_map.csv \
    --qnet models/wvs/LSM60K.gz \
    --persona "35 year old male, urban, college educated, regular news consumer, politically moderate" \
    --assets_dir assets \
    --logs_dir outputs/smoke_wvs7_india_long \
    --tag WVS7_India_long \
    --year 2017 --country "India" --continent "Asia" \
    --autoplay_csv assets/question_sets/smoke/long_gss_smoke.csv \
    --state_keep 500 --k 6 --prefilter 200 --min_map_score 1.0 \
    --semantic_fallback answer_only --semantic_k 6 --semantic_prefilter 80 --semantic_min_confidence 0.35 --semantic_resp_mode max \
    --max_assign 50 --assign_prefilter 500 --resp_mode max --seed 1000 --timing --no_ideology
)

echo "== Afrobarometer: R5 Nigeria long sequence, no ideology =="
(
  cd DTAG
  python3 scripts/pipeline.py \
    --map maps/afromap/afrobarometer_r5_map.csv \
    --qnet models/afrobarometer/LSM_merged_r5_data.gz \
    --persona "35 year old urban male in Nigeria, regular news consumer, politically attentive, moderate" \
    --assets_dir assets \
    --logs_dir outputs/smoke_afro_r5_nigeria_long \
    --tag Afrobarometer_R5_Nigeria_long \
    --country "Nigeria" --continent "Africa" \
    --autoplay_csv assets/question_sets/smoke/long_gss_smoke.csv \
    --state_keep 500 --k 6 --prefilter 200 --min_map_score 1.0 \
    --semantic_fallback answer_only --semantic_k 6 --semantic_prefilter 80 --semantic_min_confidence 0.35 --semantic_resp_mode max \
    --max_assign 50 --assign_prefilter 500 --resp_mode max --seed 1000 --timing --no_ideology
)

echo "== Batch dry-run =="
(cd DTAG && python3 scripts/run.py --config configs/dtag_config.yaml --experiment gss2022_divergence --dry-run)

echo "Done."
'''
    script.write_text(body, encoding="utf-8")
    script.chmod(0o755)

def check_overlap(audit: Audit, dtag: Path, cfg: Dict[str, Any]) -> None:
    try:
        import pandas as pd
        from quasinet.qnet import load_qnet  # type: ignore
    except Exception as e:
        audit.warn("model/map overlap", f"skipped: {e}"); return
    pairs: List[Tuple[str, Path, Path]] = []
    models = cfg.get("models", {}) or {}; maps = cfg.get("maps", {}) or {}; exps = cfg.get("experiments", {}) or {}
    if isinstance(exps, dict):
        for ename, exp in exps.items():
            if not isinstance(exp, dict): continue
            map_key = str(exp.get("map", "")); map_path = dtag / str(maps.get(map_key, map_key))
            for p in exp.get("personas", []) or []:
                if isinstance(p, dict):
                    qkey = str(p.get("qnet", "")); qnet_path = dtag / str(models.get(qkey, qkey))
                    pairs.append((f"{ename}:{p.get('id',qkey)}", qnet_path, map_path))
    pairs.extend([
        ("afro_r5", dtag / "models/afrobarometer/LSM_merged_r5_data.gz", dtag / "maps/afromap/afrobarometer_r5_map.csv"),
        ("wvs7", dtag / "models/wvs/LSM60K.gz", dtag / "maps/wvs7_variable_question_map.csv"),
        ("gss2022_female", dtag / "models/gss/gss_2022female.pkl.gz", dtag / "maps/map2022.csv"),
        ("gss2022_male", dtag / "models/gss/gss_2022male.pkl.gz", dtag / "maps/map2022.csv"),
    ])
    seen = set()
    for label, qnet_path, map_path in pairs:
        key = (qnet_path.resolve(), map_path.resolve())
        if key in seen: continue
        seen.add(key)
        if not qnet_path.exists() or not map_path.exists(): continue
        try:
            model = load_qnet(str(qnet_path)); qvars = set(map(str, getattr(model, "feature_names")))
            df = pd.read_csv(map_path, dtype=str).fillna(""); mvars = set(df["variable"].astype(str)) if "variable" in df.columns else set()
            inter = qvars & mvars; frac = len(inter) / max(1, len(qvars)); msg = f"qnet={len(qvars)} map={len(mvars)} overlap={len(inter)} frac={frac:.3f}"
            if frac >= 0.80: audit.ok(f"overlap {label}", msg)
            elif frac >= 0.50: audit.warn(f"overlap {label}", msg, "Usable for smoke tests; inspect before publication-scale runs.")
            else: audit.fail(f"overlap {label}", msg, "Regenerate map with model/qnet feature-name alignment.")
        except Exception as e:
            audit.warn(f"overlap {label}", f"could not check: {e}")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="", help="DTAG root; default auto-detects ./DTAG or current directory")
    ap.add_argument("--skip-imports", action="store_true")
    ap.add_argument("--overlap", action="store_true", help="load qnets and check feature overlap; slower")
    ap.add_argument("--create-smoke-csv", action="store_true")
    args = ap.parse_args()
    repo, dtag = resolve_root(args.root)
    audit = Audit()
    check_layout(audit, repo, dtag)
    check_python(audit, dtag, args.skip_imports)
    cfg = load_yaml(dtag / "configs/dtag_config.yaml", audit)
    if cfg:
        check_config(audit, dtag, cfg)
        check_pipeline_capabilities(audit, dtag)
        check_gss(audit, dtag)
        check_wvs(audit, dtag)
        check_afro(audit, dtag)
        check_euro(audit, dtag)
        check_question_sets(audit, dtag, cfg, args.create_smoke_csv)
        if args.overlap:
            check_overlap(audit, dtag, cfg)
    outdir = dtag / "outputs/readiness"
    outdir.mkdir(parents=True, exist_ok=True)
    report = outdir / "REPO_ASSESSMENT.md"
    report.write_text(audit.md(), encoding="utf-8")
    write_recommended_smokes(outdir)
    audit.info("wrote assessment", rel(dtag, report))
    audit.info("wrote smoke commands", "outputs/readiness/recommended_smoke_commands.sh")
    audit.print()
    if audit.counts().get("FAIL", 0):
        sys.exit(1)

if __name__ == "__main__":
    main()
