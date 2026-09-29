#!/usr/bin/env python3
"""Audit that the native-lsm-clean DTAG checkout contains no legacy surface."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OBSOLETE_PATHS = [
    "models/gss",
    "DTAG",
    "node_relations.csv",
    "ZA4669_features.txt",
    "models/wvs",
    "models/afrobarometer",
    "scripts/legacy_long_names",
    "docs/legacy",
    "docs/RC1_SCOPE.md",
    "CONFIG_PROFILES.md",
    "DTAG_EXAMPLES_FULL.md",
    "commands.sh",
    "scripts/pushmodel.sh",
    "scripts/pushdata.sh",
    "bin/run_gss2022_divergence.sh",
    "bin/run_gss2022_master.sh",
    "bin/run_gss2022_original.sh",
    "bin/postprocess_master.sh",
    "bin/postprocess_divergence.sh",
    "bin/postprocess_all_variants_quadrant.sh",
    "bin/complete_native_models.sh",
    "scripts/magics_artifacts.sh",
    "scripts/make_map.py",
    "configs/personas_gss_2022_example.json",
    "configs/personas_gss_multiyear_template.json",
    "configs/personas_wvs_template.json",
    "configs/model_inventory_template.csv",
    "maps/map.csv",
    "maps/map20162020.csv",
    "maps/map2022.csv",
    "maps/map2024.csv",
]

SOURCE_EXTENSIONS = {".py", ".sh", ".yaml", ".yml", ".json"}
BANNED_SOURCE_PATTERNS = {
    "Quasinet runtime/dependency": re.compile(r"\bquasinet\b", re.I),
    "RC1 migration surface": re.compile(r"\brc1\b", re.I),
    "old Pipeline6 name": re.compile(r"pipeline6", re.I),
    "old DTAG expansion": re.compile(r"Digital\s+Twin\s+Attitude\s+Generator", re.I),
    "old model tree": re.compile(r"models/(?:gss|wvs|afrobarometer)/"),
}


def iter_source_files():
    for base in ("scripts", "bin", "configs"):
        root = ROOT / base
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.resolve() == Path(__file__).resolve():
                continue
            if p.suffix.lower() in SOURCE_EXTENSIONS or p.name.endswith(".sh"):
                yield p


def git_tracked(path: Path) -> bool:
    rel = str(path.relative_to(ROOT))
    p = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", rel],
        cwd=ROOT,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return p.returncode == 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--allow-local-legacy",
        action="store_true",
        help="warn rather than fail for untracked local obsolete paths",
    )
    args = ap.parse_args()

    failures = []
    warnings = []

    print("OBSOLETE PATH CHECK")
    for rel in OBSOLETE_PATHS:
        p = ROOT / rel
        if not p.exists():
            print(f"OK   absent: {rel}")
            continue

        tracked = git_tracked(p)
        msg = f"{rel} exists ({'tracked' if tracked else 'local/untracked'})"
        if tracked or not args.allow_local_legacy:
            failures.append(msg)
            print("FAIL", msg)
        else:
            warnings.append(msg)
            print("WARN", msg)

    print("\nSOURCE REFERENCE CHECK")
    for p in iter_source_files():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            failures.append(f"cannot read {p.relative_to(ROOT)}: {e}")
            continue
        for label, rx in BANNED_SOURCE_PATTERNS.items():
            if rx.search(text):
                msg = f"{p.relative_to(ROOT)}: {label}"
                failures.append(msg)
                print("FAIL", msg)

    required = [
        "README.md",
        "VERSION",
        "scripts/dtag_paths.py",
        "scripts/model_backend.py",
        "scripts/pipeline.py",
        "scripts/pipeline_localized.py",
        "scripts/audit_native_maps.py",
        "bin/dtag_demo.sh",
        "configs/dtag_config.yaml",
        "models/lsm/README.md",
        "maps/README.md",
    ]
    print("\nREQUIRED CLEAN SURFACE")
    for rel in required:
        if (ROOT / rel).exists():
            print(f"OK   {rel}")
        else:
            failures.append(f"missing required file: {rel}")
            print(f"FAIL missing: {rel}")

    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="replace")
    if "Digital Twin Anchored Generation" not in readme:
        failures.append("README does not define DTAG as Digital Twin Anchored Generation")

    print("\nPYTHON SYNTAX")
    scripts = sorted((ROOT / "scripts").glob("*.py"))
    proc = subprocess.run(
        [sys.executable, "-m", "py_compile", *map(str, scripts)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if proc.returncode:
        failures.append("Python syntax check failed")
        print(proc.stdout)
        print(proc.stderr)
    else:
        print(f"OK   compiled {len(scripts)} scripts")

    print("\nSUMMARY")
    print("failures:", len(failures))
    print("warnings:", len(warnings))

    if warnings:
        print("\nWARNINGS")
        for x in warnings:
            print("-", x)

    if failures:
        print("\nFAILURES")
        for x in failures:
            print("-", x)
        raise SystemExit(1)

    print("\nPASS: native-only DTAG repository cleanup is complete.")


if __name__ == "__main__":
    main()
