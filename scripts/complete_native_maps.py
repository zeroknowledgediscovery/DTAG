#!/usr/bin/env python3
"""Complete the native-LSM DTAG semantic-map surface.

This orchestrates:
- GSS: build every installed gss_YYYY map.
- Afrobarometer R9: build from the real R9 codebook.
- Eurobarometer: rebuild missing exact maps when a local codebook exists and
  union-fallback maps otherwise.
- WVS7: verify the existing pooled map.
- Final repo-wide map audit.

The script does not download documentation. Supply the Afrobarometer R9
codebook path explicitly if it is not already copied under data/.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> None:
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def euro_models() -> dict[str, Path]:
    root = ROOT / "models/lsm/eurobarometer"
    out = {}
    if not root.is_dir():
        return out
    for p in root.iterdir():
        if not p.is_dir():
            continue
        m = re.search(r"(ZA\d+)", p.name, re.I)
        if m:
            out[m.group(1).upper()] = p
    return out


def euro_maps() -> set[str]:
    root = ROOT / "maps/eurobarometer"
    out = set()
    if not root.is_dir():
        return out
    for p in root.glob("ZA*_map.csv"):
        m = re.search(r"(ZA\d+)", p.name, re.I)
        if m:
            out.add(m.group(1).upper())
    return out


def euro_codebooks() -> set[str]:
    root = ROOT / "data/eurobarometer/codebooks"
    out = set()
    if not root.is_dir():
        return out
    for p in root.glob("ZA*_cdb.pdf"):
        m = re.search(r"(ZA\d+)", p.name, re.I)
        if m:
            out.add(m.group(1).upper())
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--afro-r9-codebook",
        default="data/afrobarometer/codebooks/merged_r9_codebook_2.pdf",
        help="Afrobarometer R9 merged codebook PDF",
    )
    ap.add_argument("--skip-gss", action="store_true")
    ap.add_argument("--skip-afro", action="store_true")
    ap.add_argument("--skip-euro", action="store_true")
    ap.add_argument("--no-force", action="store_true")
    args = ap.parse_args()

    force = not args.no_force

    if not args.skip_gss:
        cmd = [sys.executable, "scripts/build_all_gss_native_maps.py"]
        if force:
            cmd.append("--force")
        run(cmd)

    if not args.skip_afro:
        cb = Path(args.afro_r9_codebook).expanduser()
        if not cb.is_absolute():
            cb = ROOT / cb
        if not cb.is_file():
            raise SystemExit(
                "Afrobarometer R9 codebook is required. Expected:\n"
                f"  {cb}\n"
                "or pass --afro-r9-codebook /path/to/merged_r9_codebook_2.pdf"
            )
        run([
            sys.executable,
            "scripts/getmap_dtag.py",
            "--codebook_pdf", str(cb),
            "--model", "models/lsm/afrobarometer/r9",
            "--model-backend", "native_lsm",
            "--text-mode", "combined",
            "--out", "maps/afromap/afrobarometer_r9_map.csv",
            "--audit_out", "outputs/afrobarometer_r9_map_audit.csv",
        ])

    if not args.skip_euro:
        models = euro_models()
        have_maps = euro_maps()
        codebooks = euro_codebooks()
        missing = sorted(set(models) - have_maps, key=lambda z: int(z[2:]))
        print(f"Eurobarometer missing maps before build: {len(missing)}")

        for za in missing:
            if za in codebooks:
                run([
                    sys.executable,
                    "scripts/build_eurobarometer_maps.py",
                    "--za", za,
                    "--parse-timeout", "600",
                ])
            else:
                run([
                    sys.executable,
                    "scripts/build_eurobarometer_fallback_maps.py",
                    "--za", za,
                    "--build",
                    "--force",
                ])

    wvs_map = ROOT / "maps/wvs7_variable_question_map.csv"
    if not wvs_map.is_file():
        raise SystemExit(f"WVS7 map missing: {wvs_map}")

    run([sys.executable, "scripts/audit_native_maps.py"])


if __name__ == "__main__":
    main()
