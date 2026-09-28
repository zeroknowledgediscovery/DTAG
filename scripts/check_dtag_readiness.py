#!/usr/bin/env python3
"""
DTAG readiness checker.

Run from the DTAG repo root:

    python3 scripts/check_dtag_readiness.py

or from the tmprepo root:

    python3 DTAG/scripts/check_dtag_readiness.py --root DTAG

What it checks:
  - core scripts/config/requirements exist
  - Python files compile
  - required packages can be imported
  - models/maps referenced in configs/dtag_config.yaml exist
  - question-set CSVs are well formed, including comma-containing questions
  - GSS polar vectors exist
  - WVS config path mismatch, if present
  - Afrobarometer maps/models availability
  - Eurobarometer CSV/PDF pairs, maps, integrated fallback map, and models
  - optional qnet/map overlap, when quasinet can load models

It writes:
  outputs/readiness/DTAG_READINESS_REPORT.md
  outputs/readiness/run_core_smokes.sh
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


TEXT_COLUMNS = [
    "question_text_filled",
    "question_text",
    "dta_variable_label",
    "pdf_short_label",
]

ZA_RE = re.compile(r"(ZA\d{4,5})", re.IGNORECASE)


@dataclass
class Finding:
    level: str
    item: str
    detail: str = ""
    fix: str = ""


@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)

    def add(self, level: str, item: str, detail: str = "", fix: str = "") -> None:
        self.findings.append(Finding(level.upper(), item, detail, fix))

    def ok(self, item: str, detail: str = "") -> None:
        self.add("OK", item, detail)

    def warn(self, item: str, detail: str = "", fix: str = "") -> None:
        self.add("WARN", item, detail, fix)

    def fail(self, item: str, detail: str = "", fix: str = "") -> None:
        self.add("FAIL", item, detail, fix)

    def info(self, item: str, detail: str = "") -> None:
        self.add("INFO", item, detail)

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for f in self.findings:
            out[f.level] = out.get(f.level, 0) + 1
        return out

    def print_console(self) -> None:
        widths = {"OK": 6, "INFO": 6, "WARN": 6, "FAIL": 6}
        for f in self.findings:
            prefix = f"[{f.level:<4}]"
            line = f"{prefix} {f.item}"
            if f.detail:
                line += f" -- {f.detail}"
            print(line)
            if f.fix:
                print(f"       fix: {f.fix}")
        print("\nSUMMARY", self.counts())

    def to_markdown(self) -> str:
        counts = self.counts()
        lines = [
            "# DTAG readiness report",
            "",
            "## Summary",
            "",
            f"- OK: {counts.get('OK', 0)}",
            f"- WARN: {counts.get('WARN', 0)}",
            f"- FAIL: {counts.get('FAIL', 0)}",
            f"- INFO: {counts.get('INFO', 0)}",
            "",
            "## Findings",
            "",
            "| Level | Item | Detail | Suggested fix |",
            "|---|---|---|---|",
        ]
        for f in self.findings:
            lines.append(
                "| "
                + " | ".join(
                    md_escape(x)
                    for x in [f.level, f.item, f.detail or "", f.fix or ""]
                )
                + " |"
            )
        lines.append("")
        return "\n".join(lines)


def md_escape(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", "<br>")


def rel(root: Path, p: Path) -> str:
    try:
        return str(p.resolve().relative_to(root.resolve()))
    except Exception:
        return str(p)


def load_yaml(path: Path, report: Report) -> Dict[str, Any]:
    if not path.exists():
        report.fail("config", f"Missing {path}", f"Create {path} or run from the DTAG root")
        return {}
    try:
        import yaml  # type: ignore
    except Exception as e:
        report.fail("PyYAML", f"Cannot import yaml: {e}", "pip install pyyaml")
        return {}
    try:
        obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        report.fail("config parse", f"Could not parse {path}: {e}")
        return {}
    if not isinstance(obj, dict):
        report.fail("config parse", f"{path} is not a mapping/object")
        return {}
    report.ok("config parse", rel(path.parent.parent if path.parent.name == "configs" else path.parent, path))
    return obj


def resolve_path(root: Path, p: Any) -> Path:
    pp = Path(str(p)).expanduser()
    if pp.is_absolute():
        return pp
    return root / pp


def check_file(report: Report, root: Path, path: str, label: str, required: bool = True) -> bool:
    p = resolve_path(root, path)
    if p.exists():
        report.ok(label, rel(root, p))
        return True
    if required:
        report.fail(label, f"Missing {path}")
    else:
        report.warn(label, f"Missing optional {path}")
    return False


def run_cmd(cmd: Sequence[str], cwd: Path, timeout: int = 120) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(
            list(cmd), cwd=str(cwd), capture_output=True, text=True, timeout=timeout
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        return 124, e.stdout or "", e.stderr or "timeout"
    except Exception as e:
        return 127, "", str(e)


def check_imports(report: Report) -> None:
    pkgs = [
        ("openai", "openai"),
        ("pandas", "pandas"),
        ("numpy", "numpy"),
        ("matplotlib", "matplotlib"),
        ("quasinet", "quasinet"),
        ("pyreadstat", "pyreadstat"),
        ("pdfplumber", "pdfplumber"),
        ("yaml", "pyyaml"),
    ]
    for import_name, pip_name in pkgs:
        try:
            __import__(import_name)
            report.ok(f"python package {pip_name}")
        except Exception as e:
            report.fail(
                f"python package {pip_name}",
                str(e),
                f"pip install {pip_name}",
            )


def check_pycompile(report: Report, root: Path) -> None:
    py_files = sorted((root / "scripts").glob("*.py"))
    if not py_files:
        report.fail("py_compile", "No scripts/*.py files found")
        return
    code, out, err = run_cmd([sys.executable, "-m", "py_compile", *map(str, py_files)], cwd=root)
    if code == 0:
        report.ok("py_compile", f"compiled {len(py_files)} scripts")
    else:
        report.fail("py_compile", (out + err).strip()[:2000])


def check_config_paths(report: Report, root: Path, cfg: Dict[str, Any]) -> None:
    models = cfg.get("models", {}) or {}
    maps = cfg.get("maps", {}) or {}
    if not isinstance(models, dict):
        report.fail("config.models", "models is not a mapping")
        models = {}
    if not isinstance(maps, dict):
        report.fail("config.maps", "maps is not a mapping")
        maps = {}

    for key, val in sorted(models.items()):
        p = resolve_path(root, val)
        if p.exists():
            report.ok(f"config model {key}", rel(root, p))
        else:
            fix = ""
            s = str(val)
            if key.startswith("wvs") and (root / "models/wvs/LSM60K.gz").exists():
                fix = "Change this config entry to: models/wvs/LSM60K.gz"
            elif "gss_2024" in key and (root / "models/gss/gss_2024.gz").exists():
                fix = "Config points to sex-specific 2024 models; only models/gss/gss_2024.gz was found. Either create sex-specific 2024 models or change personas to use gss_2024.gz."
            elif "euro" in key.lower():
                fix = "Place model at models/eurobarometer/LSM_ZAxxxx.gz, or update configs/dtag_config.yaml to the actual path."
            report.fail(f"config model {key}", f"Missing {s}", fix)

    for key, val in sorted(maps.items()):
        p = resolve_path(root, val)
        if p.exists():
            ok, detail, fix = inspect_map_file(p)
            if ok:
                report.ok(f"config map {key}", f"{rel(root, p)}; {detail}")
            else:
                report.fail(f"config map {key}", f"{rel(root, p)}; {detail}", fix)
        else:
            fix = ""
            if "euro" in key.lower():
                fix = "Generate Eurobarometer maps from data/eurobarometer/ZA*.csv + ZA*.pdf using scripts/generate_eurobarometer_maps.sh."
            report.fail(f"config map {key}", f"Missing {val}", fix)


def inspect_map_file(p: Path) -> Tuple[bool, str, str]:
    try:
        import pandas as pd
        df = pd.read_csv(p, dtype=str, nrows=20).fillna("")
    except Exception as e:
        return False, f"cannot read CSV: {e}", "Fix CSV formatting"
    cols = list(df.columns)
    if "variable" not in cols:
        return False, f"missing variable column; columns={cols}", "Map must include variable column"
    text_col = next((c for c in TEXT_COLUMNS if c in cols), None)
    if not text_col:
        return False, f"missing text column; columns={cols}", f"Add one of {TEXT_COLUMNS}"
    return True, f"columns OK; text_col={text_col}", ""


def check_core_layout(report: Report, root: Path) -> None:
    required_files = [
        "requirements.txt",
        "configs/dtag_config.yaml",
        "scripts/pipeline_localized.py",
        "scripts/run.py",
        "scripts/run_grid.py",
        "scripts/post.py",
        "scripts/postprocess.py",
        "scripts/smoke_test.py",
    ]
    for x in required_files:
        check_file(report, root, x, f"core file {x}")
    for d in ["assets", "bin", "configs", "data", "maps", "models", "outputs", "scripts"]:
        p = root / d
        if p.exists() and p.is_dir():
            report.ok(f"core directory {d}")
        else:
            report.fail(f"core directory {d}", f"Missing {d}")

    for x in ["bin/run_smoketest.sh", "bin/list_experiments.sh", "bin/run_config.sh", "bin/post_config.sh"]:
        check_file(report, root, x, f"wrapper {x}", required=False)


def check_openai_env(report: Report) -> None:
    if os.environ.get("OPENAI_API_KEY"):
        report.ok("OPENAI_API_KEY", "set in environment")
    else:
        report.warn("OPENAI_API_KEY", "not set; LLM/pipeline smoke tests will fail", "export OPENAI_API_KEY='...' before running pipeline tests")


def check_polar_vectors(report: Report, root: Path) -> None:
    p = root / "assets/polar_vectors/polar_vectors.csv"
    if p.exists():
        try:
            with p.open(newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, [])
            has_variable_col = (
                "variable" in header
                or (len(header) >= 1 and str(header[0]).strip() == "")
            )
            has_poles = (("L" in header and "R" in header) or "pole" in header)
            if has_variable_col and has_poles:
                report.ok("GSS polar vectors", f"{rel(root, p)}; header={header}")
            else:
                report.warn("GSS polar vectors", f"header may be incompatible: {header}")
        except Exception as e:
            report.fail("GSS polar vectors", str(e))
    else:
        report.fail("GSS polar vectors", "Missing assets/polar_vectors/polar_vectors.csv", "Required for GSS ideology tests with --require_polar_vectors")


def check_question_sets(report: Report, root: Path, cfg: Dict[str, Any], create_smoke: bool) -> None:
    if create_smoke:
        make_smoke_csv(root, report)

    qsets = cfg.get("question_sets", {}) or {}
    if not isinstance(qsets, dict):
        report.fail("question_sets", "config question_sets is not a mapping")
        return

    for name, spec in sorted(qsets.items()):
        if not isinstance(spec, dict):
            report.warn(f"question_set {name}", "not a mapping")
            continue
        qdir = resolve_path(root, spec.get("dir", ""))
        glob = str(spec.get("glob", "*.csv"))
        if not qdir.exists():
            report.fail(f"question_set {name}", f"Missing dir {rel(root, qdir)}")
            continue
        files = sorted(qdir.glob(glob))
        if not files:
            report.fail(f"question_set {name}", f"No files match {rel(root, qdir)}/{glob}")
            continue
        bad = []
        total_q = 0
        for f in files:
            ok, n, detail = inspect_question_csv(f)
            total_q += n
            if not ok:
                bad.append(f"{rel(root, f)}: {detail}")
        if bad:
            report.fail(f"question_set {name}", f"{len(files)} files, {len(bad)} malformed", " | ".join(bad[:5]))
        else:
            report.ok(f"question_set {name}", f"{len(files)} files; {total_q} total questions")


def inspect_question_csv(p: Path) -> Tuple[bool, int, str]:
    try:
        import pandas as pd
        df = pd.read_csv(p, dtype=str).fillna("")
    except Exception as e:
        return False, 0, f"read error: {e}"
    if df.shape[1] == 0:
        return False, 0, "no columns"
    if not isinstance(df.index, pd.RangeIndex):
        return False, len(df), "non-default index; likely unquoted commas in question text. Recreate with pandas/to_csv or quote questions."
    col = "question" if "question" in df.columns else df.columns[0]
    qs = [str(x).strip() for x in df[col].tolist() if str(x).strip()]
    if not qs:
        return False, 0, f"no non-empty questions in column {col}"
    suspicious = [q for q in qs if len(q) < 8 or q.startswith((",", "or ", "and "))]
    if suspicious:
        return False, len(qs), f"suspicious question fragments, e.g. {suspicious[:3]}"
    return True, len(qs), "OK"


def make_smoke_csv(root: Path, report: Report) -> None:
    out = root / "assets/question_sets/smoke/long_gss_smoke.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
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
    try:
        import pandas as pd
        pd.DataFrame({"question": questions}).to_csv(out, index=False)
        report.ok("created smoke question CSV", rel(root, out))
    except Exception as e:
        report.fail("created smoke question CSV", str(e), "pip install pandas")


def find_za_files(root: Path) -> Dict[str, Dict[str, List[Path]]]:
    base = root / "data/eurobarometer"
    out: Dict[str, Dict[str, List[Path]]] = {}
    if not base.exists():
        return out
    for p in sorted(base.glob("**/*")):
        if not p.is_file():
            continue
        m = ZA_RE.search(p.name)
        if not m:
            continue
        za = m.group(1).upper()
        kind = None
        suf = p.suffix.lower()
        if suf == ".csv":
            kind = "csv"
        elif suf == ".pdf":
            kind = "pdf"
        elif suf in {".dta", ".sav"}:
            kind = "data_other"
        if kind:
            out.setdefault(za, {"csv": [], "pdf": [], "data_other": []})[kind].append(p)
    return out


def check_eurobarometer(report: Report, root: Path) -> None:
    base_data = root / "data/eurobarometer"
    base_maps = root / "maps/euromap"
    base_models = root / "models/eurobarometer"
    if not base_data.exists():
        report.warn("Eurobarometer data", "data/eurobarometer not present", "Create data/eurobarometer and place ZAxxxx*.csv and ZAxxxx*.pdf files there")
        return

    za_files = find_za_files(root)
    if not za_files:
        report.warn("Eurobarometer data", "No ZA*.csv or ZA*.pdf files found", "Place flat files such as data/eurobarometer/ZA7575*.csv and ZA7575*.pdf")
        return

    report.info("Eurobarometer ZA files", f"found {len(za_files)} ZA IDs under {rel(root, base_data)}")

    if base_maps.exists():
        report.ok("Eurobarometer map directory", rel(root, base_maps))
    else:
        report.fail("Eurobarometer map directory", "Missing maps/euromap", "mkdir -p maps/euromap")

    if base_models.exists():
        report.ok("Eurobarometer model directory", rel(root, base_models))
    else:
        report.warn("Eurobarometer model directory", "Missing models/eurobarometer", "mkdir -p models/eurobarometer; place LSM_ZAxxxx.gz models there")

    integrated = base_maps / "eurobarometer_integrated_fallback_map.csv"
    prefixed = base_maps / "eurobarometer_all_prefixed_map.csv"
    if integrated.exists():
        report.ok("Eurobarometer integrated fallback map", rel(root, integrated))
    else:
        report.warn(
            "Eurobarometer integrated fallback map",
            "Missing maps/euromap/eurobarometer_integrated_fallback_map.csv",
            "Run: bash scripts/generate_eurobarometer_maps.sh --drop-admin",
        )
    if prefixed.exists():
        report.ok("Eurobarometer all-prefixed map", rel(root, prefixed))
    else:
        report.info("Eurobarometer all-prefixed map", "not present; only needed for pooled prefixed qnets")

    n_ready = 0
    n_missing_map = 0
    n_missing_model = 0
    n_missing_pair = 0
    examples = []
    for za, files in sorted(za_files.items()):
        has_csv = bool(files.get("csv"))
        has_pdf = bool(files.get("pdf"))
        if not (has_csv and has_pdf):
            n_missing_pair += 1
            report.warn(
                f"Eurobarometer {za} data/codebook pair",
                f"csv={len(files.get('csv', []))}; pdf={len(files.get('pdf', []))}",
                f"Need both data/eurobarometer/{za}*.csv and {za}*.pdf",
            )
            continue
        map_path = base_maps / f"eurobarometer_{za}_map.csv"
        model_candidates = []
        if base_models.exists():
            model_candidates = sorted(base_models.glob(f"*{za}*.gz")) + sorted(base_models.glob(f"*{za}*.pkl.gz"))
            default_model = base_models / f"LSM_{za}.gz"
            if default_model.exists() and default_model not in model_candidates:
                model_candidates.insert(0, default_model)
        if map_path.exists() and model_candidates:
            n_ready += 1
            report.ok(f"Eurobarometer {za}", f"csv+pdf+map+model present")
        else:
            if not map_path.exists():
                n_missing_map += 1
            if not model_candidates:
                n_missing_model += 1
            examples.append(za)
    report.info(
        "Eurobarometer readiness summary",
        f"ZA IDs={len(za_files)}; ready={n_ready}; missing_pair={n_missing_pair}; missing_map={n_missing_map}; missing_model={n_missing_model}; examples={examples[:8]}",
    )
    if n_missing_map:
        report.warn(
            "Eurobarometer maps missing",
            f"{n_missing_map} ZA IDs have CSV/PDF pairs but no individual map",
            "Install scripts/getmap_eurobarometer.py and scripts/generate_eurobarometer_maps.sh, then run: bash scripts/generate_eurobarometer_maps.sh --drop-admin",
        )
    if n_missing_model:
        report.warn(
            "Eurobarometer models missing",
            f"{n_missing_model} ZA IDs have no matching model in models/eurobarometer",
            "Train or copy qnet/LSM files named models/eurobarometer/LSM_ZAxxxx.gz; maps alone are not enough to run DTAG.",
        )


def get_experiment_pairs(root: Path, cfg: Dict[str, Any]) -> List[Tuple[str, Path, Path]]:
    pairs: List[Tuple[str, Path, Path]] = []
    models = cfg.get("models", {}) or {}
    maps = cfg.get("maps", {}) or {}
    exps = cfg.get("experiments", {}) or {}
    if not isinstance(exps, dict):
        return pairs
    for exp_name, exp in exps.items():
        if not isinstance(exp, dict):
            continue
        map_key = str(exp.get("map", ""))
        map_val = maps.get(map_key, map_key)
        map_path = resolve_path(root, map_val)
        personas = exp.get("personas", []) or []
        if not isinstance(personas, list):
            continue
        for p in personas:
            if not isinstance(p, dict):
                continue
            qkey = str(p.get("qnet", ""))
            qval = models.get(qkey, qkey)
            qnet_path = resolve_path(root, qval)
            label = f"{exp_name}:{p.get('id', qkey)}"
            pairs.append((label, qnet_path, map_path))
    # unique by path pair
    seen = set()
    out = []
    for label, q, m in pairs:
        key = (str(q.resolve()), str(m.resolve()))
        if key not in seen:
            seen.add(key)
            out.append((label, q, m))
    return out


def check_overlap(report: Report, root: Path, cfg: Dict[str, Any]) -> None:
    try:
        from quasinet.qnet import load_qnet  # type: ignore
    except Exception as e:
        report.warn("qnet/map overlap", f"Cannot import quasinet.qnet.load_qnet: {e}", "pip install quasinet")
        return
    try:
        import pandas as pd
    except Exception as e:
        report.warn("qnet/map overlap", f"Cannot import pandas: {e}", "pip install pandas")
        return

    pairs = get_experiment_pairs(root, cfg)
    # Add Eurobarometer exact map/model pairs.
    for mp in sorted((root / "maps/euromap").glob("eurobarometer_ZA*_map.csv")):
        m = ZA_RE.search(mp.name)
        if not m:
            continue
        za = m.group(1).upper()
        qnet = root / "models/eurobarometer" / f"LSM_{za}.gz"
        pairs.append((f"eurobarometer:{za}", qnet, mp))

    if not pairs:
        report.warn("qnet/map overlap", "no experiment pairs found")
        return

    for label, qnet_path, map_path in pairs:
        if not qnet_path.exists() or not map_path.exists():
            continue
        try:
            m = load_qnet(str(qnet_path))
            qvars = set(map(str, getattr(m, "feature_names")))
            df = pd.read_csv(map_path, dtype=str).fillna("")
            map_vars = set(df["variable"].astype(str)) if "variable" in df.columns else set()
            inter = qvars & map_vars
            frac = len(inter) / max(1, len(qvars))
            detail = f"qnet={len(qvars)} map={len(map_vars)} overlap={len(inter)} frac_qnet={frac:.3f}"
            if frac >= 0.80:
                report.ok(f"overlap {label}", detail)
            elif frac >= 0.50:
                report.warn(f"overlap {label}", detail, "Acceptable for quick tests but inspect qnet-only variables before paper runs")
            else:
                report.fail(f"overlap {label}", detail, "Regenerate map with qnet alignment or fix variable-name normalization")
        except Exception as e:
            report.warn(f"overlap {label}", f"could not load/check: {e}")


def write_smoke_script(root: Path, outdir: Path, cfg: Dict[str, Any]) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    script = outdir / "run_core_smokes.sh"
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f"cd {shlex.quote(str(root.resolve()))}",
        "",
        "echo '== Static checks =='",
        "python3 -m py_compile scripts/*.py",
        "python3 scripts/run.py --config configs/dtag_config.yaml --list || true",
        "",
        "echo '== Create quoted 10-question smoke CSV =='",
        "python3 scripts/check_dtag_readiness.py --create-smoke-csv --no-pycompile --no-imports --no-overlap --no-write-commands >/dev/null",
        "",
        "if [ -z \"${OPENAI_API_KEY:-}\" ]; then",
        "  echo 'OPENAI_API_KEY is not set; skipping API-dependent smoke tests.'",
        "  exit 0",
        "fi",
        "",
        "echo '== OpenAI smoke test =='",
        "bin/run_smoketest.sh gpt-4.1-mini || true",
        "",
        "echo '== GSS single question with polar vectors =='",
        gss_single_command(),
        "",
        "echo '== GSS 10-question sequence: answer_only =='",
        gss_long_command("answer_only"),
        "",
        "echo '== GSS 10-question sequence: update_state =='",
        gss_long_command("update_state"),
        "",
        "echo '== WVS India 2017 10-question sequence, no ideology =='",
        wvs_long_command(),
        "",
        "echo '== Afrobarometer R5 Nigeria 10-question sequence, no ideology =='",
        afro_long_command(),
        "",
        "echo '== Batch dry-run =='",
        "python3 scripts/run.py --config configs/dtag_config.yaml --experiment gss2022_divergence --dry-run || true",
        "",
        "echo 'Smoke tests complete.'",
    ]
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    script.chmod(0o755)
    return script


def gss_common(extra: List[str]) -> str:
    args = [
        "python3", "scripts/pipeline_localized.py",
        "--map", "maps/map2022.csv",
        "--qnet", "models/gss/gss_2022female.pkl.gz",
        "--persona", "22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive",
        "--polar_vectors", "assets/polar_vectors/polar_vectors.csv",
        "--require_polar_vectors",
        "--assets_dir", "assets",
        "--year", "2022",
        "--country", "United States",
        "--state_keep", "500",
        "--k", "6",
        "--prefilter", "200",
        "--min_map_score", "1.0",
        "--semantic_k", "6",
        "--semantic_prefilter", "80",
        "--semantic_min_confidence", "0.35",
        "--semantic_resp_mode", "max",
        "--max_assign", "50",
        "--assign_prefilter", "500",
        "--resp_mode", "max",
        "--seed", "1000",
        "--timing",
    ] + extra
    return " \\\n  ".join(shlex.quote(a) for a in args)


def gss_single_command() -> str:
    return gss_common([
        "--logs_dir", "outputs/smoke_gss_wf_single",
        "--tag", "smoke_gss_wf_single",
        "--semantic_fallback", "answer_only",
        "--question", "What do you think about immigration?",
    ])


def gss_long_command(mode: str) -> str:
    return gss_common([
        "--logs_dir", f"outputs/smoke_gss_wf_long_{mode}",
        "--tag", f"smoke_gss_wf_long_{mode}",
        "--semantic_fallback", mode,
        "--autoplay_csv", "assets/question_sets/smoke/long_gss_smoke.csv",
    ])


def wvs_long_command() -> str:
    args = [
        "python3", "scripts/pipeline_localized.py",
        "--map", "maps/wvs7_variable_question_map.csv",
        "--qnet", "models/wvs/LSM60K.gz",
        "--persona", "35 year old male, urban, college educated, regular news consumer, politically moderate",
        "--assets_dir", "assets",
        "--logs_dir", "outputs/smoke_wvs7_india_long",
        "--tag", "WVS7_India_long",
        "--year", "2017",
        "--country", "India",
        "--continent", "Asia",
        "--autoplay_csv", "assets/question_sets/smoke/long_gss_smoke.csv",
        "--state_keep", "500",
        "--k", "6",
        "--prefilter", "200",
        "--min_map_score", "1.0",
        "--semantic_fallback", "answer_only",
        "--semantic_k", "6",
        "--semantic_prefilter", "80",
        "--semantic_min_confidence", "0.35",
        "--semantic_resp_mode", "max",
        "--max_assign", "50",
        "--assign_prefilter", "500",
        "--resp_mode", "max",
        "--seed", "1000",
        "--timing",
        "--no_ideology",
    ]
    return " \\\n  ".join(shlex.quote(a) for a in args)


def afro_long_command() -> str:
    args = [
        "python3", "scripts/pipeline_localized.py",
        "--map", "maps/afromap/afrobarometer_r5_map.csv",
        "--qnet", "models/afrobarometer/LSM_merged_r5_data.gz",
        "--persona", "35 year old urban male in Nigeria, regular news consumer, politically attentive, moderate",
        "--assets_dir", "assets",
        "--logs_dir", "outputs/smoke_afro_r5_nigeria_long",
        "--tag", "Afrobarometer_R5_Nigeria_long",
        "--country", "Nigeria",
        "--continent", "Africa",
        "--autoplay_csv", "assets/question_sets/smoke/long_gss_smoke.csv",
        "--state_keep", "500",
        "--k", "6",
        "--prefilter", "200",
        "--min_map_score", "1.0",
        "--semantic_fallback", "answer_only",
        "--semantic_k", "6",
        "--semantic_prefilter", "80",
        "--semantic_min_confidence", "0.35",
        "--semantic_resp_mode", "max",
        "--max_assign", "50",
        "--assign_prefilter", "500",
        "--resp_mode", "max",
        "--seed", "1000",
        "--timing",
        "--no_ideology",
    ]
    return " \\\n  ".join(shlex.quote(a) for a in args)


def main() -> None:
    ap = argparse.ArgumentParser(description="Check DTAG repo readiness and generate smoke-test commands.")
    ap.add_argument("--root", default=".", help="DTAG root directory. Use --root DTAG if running from tmprepo root.")
    ap.add_argument("--config", default="configs/dtag_config.yaml")
    ap.add_argument("--outdir", default="outputs/readiness")
    ap.add_argument("--no-imports", action="store_true")
    ap.add_argument("--no-pycompile", action="store_true")
    ap.add_argument("--overlap", action="store_true", help="Load qnets and check model-map feature overlap. May take time.")
    ap.add_argument("--no-overlap", action="store_true", help="Explicitly skip overlap check.")
    ap.add_argument("--create-smoke-csv", action="store_true", help="Create assets/question_sets/smoke/long_gss_smoke.csv with correct quoting.")
    ap.add_argument("--no-write-commands", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    report = Report()

    if not root.exists():
        report.fail("root", f"Missing {root}")
        report.print_console()
        raise SystemExit(2)

    report.info("root", str(root))
    check_core_layout(report, root)
    check_openai_env(report)
    if not args.no_imports:
        check_imports(report)
    if not args.no_pycompile:
        check_pycompile(report, root)

    cfg_path = resolve_path(root, args.config)
    cfg = load_yaml(cfg_path, report)
    if cfg:
        check_config_paths(report, root, cfg)
        check_polar_vectors(report, root)
        check_question_sets(report, root, cfg, create_smoke=args.create_smoke_csv)
        check_eurobarometer(report, root)
        if args.overlap and not args.no_overlap:
            check_overlap(report, root, cfg)

    outdir = resolve_path(root, args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    report_path = outdir / "DTAG_READINESS_REPORT.md"
    report_path.write_text(report.to_markdown(), encoding="utf-8")
    if not args.no_write_commands:
        smoke_path = write_smoke_script(root, outdir, cfg)
        report.info("wrote smoke script", rel(root, smoke_path))
    report.info("wrote report", rel(root, report_path))

    report.print_console()

    counts = report.counts()
    if counts.get("FAIL", 0) > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
