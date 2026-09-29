#!/usr/bin/env python3
"""Scan public GESIS access.gesis.org/dbk/<document_id> IDs for Eurobarometer codebooks.

This is a fallback when GESIS metadata/search endpoints reject scripted access.
DBK IDs are document IDs, not ZA study IDs, but Eurobarometer variable reports
were often deposited in batches, so nearby DBK IDs can contain nearby waves.

The scanner first performs a cheap HEAD request. If the HTTP headers expose a
filename containing a ZA identifier, no PDF download is needed. With --deep,
candidate PDFs whose headers do not expose a ZA identifier are downloaded to a
temporary file and the first pages are inspected with pdfplumber.

Examples:

  # Early ECS reports around known ZA0628 -> DBK 9456
  python3 scripts/scan_gesis_dbk_ids.py \
      --center 9456 --radius 75 --deep \
      --target ZA0078 --target ZA0626 --target ZA0627 --target ZA0628

  # Early Eurobarometer reports around known ZA0992 -> DBK 5650
  python3 scripts/scan_gesis_dbk_ids.py \
      --center 5650 --radius 100 --deep \
      --target ZA0986 --target ZA0987 --target ZA0988 --target ZA0989 \
      --target ZA0990 --target ZA0991 --target ZA0992 --target ZA0993 \
      --target ZA0994 --target ZA0995

  # Save matched target PDFs using canonical DTAG names:
  python3 scripts/scan_gesis_dbk_ids.py \
      --center 9456 --radius 75 --deep --save-matches \
      --target ZA0626 --target ZA0627 --target ZA0628

Output mappings are appended to:
  data/eurobarometer/codebooks/dbk_id_map.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "eurobarometer" / "codebooks"
MAP_CSV = OUT_DIR / "dbk_id_map.csv"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/152.0 Safari/537.36"
)

ZA_RE = re.compile(r"\bZA\s*0*(\d{1,5})\b", re.I)


def norm_za(value: str) -> str:
    m = ZA_RE.search(str(value))
    if not m:
        s = re.sub(r"\D", "", str(value))
        if not s:
            raise ValueError(value)
        return "ZA" + s.zfill(4)
    return "ZA" + m.group(1).zfill(4)


def za_from_text(text: str) -> Optional[str]:
    m = ZA_RE.search(text or "")
    return norm_za(m.group(0)) if m else None


def head(dbk_id: int, timeout: float):
    url = f"https://access.gesis.org/dbk/{dbk_id}"
    req = Request(
        url,
        method="HEAD",
        headers={"User-Agent": UA, "Accept": "application/pdf,*/*"},
    )
    with urlopen(req, timeout=timeout) as r:
        headers = {k.lower(): v for k, v in r.headers.items()}
        return r.geturl(), headers


def download(dbk_id: int, dst: Path, timeout: float):
    url = f"https://access.gesis.org/dbk/{dbk_id}"
    req = Request(
        url,
        headers={"User-Agent": UA, "Accept": "application/pdf,*/*"},
    )
    with urlopen(req, timeout=timeout) as r, dst.open("wb") as f:
        shutil.copyfileobj(r, f)
        return r.geturl(), {k.lower(): v for k, v in r.headers.items()}


def inspect_pdf(path: Path, pages: int) -> tuple[Optional[str], str]:
    texts = []
    try:
        with pdfplumber.open(str(path)) as pdf:
            for p in pdf.pages[:pages]:
                t = p.extract_text() or ""
                texts.append(t)
    except Exception as e:
        return None, f"pdf parse failed: {e}"

    text = "\n".join(texts)
    za = za_from_text(text)

    # Prefer reports/codebooks; reject obvious questionnaires/datasets.
    low = text.lower()
    if "variable report" in low or "variable reports" in low:
        kind = "variable_report"
    elif "codebook" in low:
        kind = "codebook"
    elif "questionnaire" in low:
        kind = "questionnaire"
    else:
        kind = "unknown"

    return za, kind


def append_map(dbk_id: int, za: str, kind: str, url: str, local: str = ""):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    exists = MAP_CSV.exists()
    fields = ["dbk_id", "za_id", "kind", "url", "local_path"]
    with MAP_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            w.writeheader()
        w.writerow({
            "dbk_id": dbk_id,
            "za_id": za,
            "kind": kind,
            "url": url,
            "local_path": local,
        })


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--center", type=int)
    g.add_argument("--start", type=int)
    ap.add_argument("--end", type=int)
    ap.add_argument("--radius", type=int, default=50)
    ap.add_argument("--target", action="append", default=[])
    ap.add_argument("--deep", action="store_true",
                    help="download candidate PDFs when headers do not reveal ZA")
    ap.add_argument("--pages", type=int, default=10,
                    help="pages to inspect in deep mode")
    ap.add_argument("--delay", type=float, default=0.35)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--save-matches", action="store_true")
    ap.add_argument("--max-mb", type=float, default=40.0,
                    help="skip deep inspection above this Content-Length")
    args = ap.parse_args()

    if args.center is not None:
        start = max(1, args.center - args.radius)
        end = args.center + args.radius
    else:
        if args.end is None:
            raise SystemExit("--end is required with --start")
        start, end = args.start, args.end

    targets = {norm_za(x) for x in args.target}
    found = {}

    print(f"Scanning DBK IDs {start}..{end}")
    if targets:
        print("Targets:", " ".join(sorted(targets)))
    print("Deep PDF inspection:", args.deep)
    print()

    with tempfile.TemporaryDirectory(prefix="gesis_dbk_scan_") as td:
        tmpdir = Path(td)

        for dbk_id in range(start, end + 1):
            if targets and targets.issubset(found):
                break

            try:
                final_url, headers = head(dbk_id, args.timeout)
            except HTTPError as e:
                if e.code not in (404, 403):
                    print(f"{dbk_id}: HEAD HTTP {e.code}")
                time.sleep(args.delay)
                continue
            except (URLError, TimeoutError, OSError) as e:
                print(f"{dbk_id}: HEAD {type(e).__name__}: {e}")
                time.sleep(args.delay)
                continue

            ctype = headers.get("content-type", "").lower()
            dispo = headers.get("content-disposition", "")
            clen = headers.get("content-length", "")
            hdr_text = " ".join([dispo, final_url])
            za = za_from_text(hdr_text)
            low_hdr = hdr_text.lower()
            if "_cdb.pdf" in low_hdr or "codebook" in low_hdr or "variable_report" in low_hdr:
                kind = "codebook"
            elif "_bq.pdf" in low_hdr or "questionnaire" in low_hdr:
                kind = "questionnaire"
            else:
                kind = "header"

            is_pdf = ("pdf" in ctype) or (".pdf" in dispo.lower())
            if not is_pdf:
                time.sleep(args.delay)
                continue

            size_mb = None
            try:
                size_mb = int(clen) / 1024**2 if clen else None
            except ValueError:
                pass

            # Deep inspection when ZA is absent OR headers identify only a
            # generic/questionnaire document. This prevents saving a BQ PDF as
            # ZAxxxx_cdb.pdf merely because its filename contains the ZA id.
            pdf_path = None
            if args.deep and (za is None or kind in ("header", "questionnaire")):
                if size_mb is not None and size_mb > args.max_mb:
                    print(f"{dbk_id}: PDF {size_mb:.1f} MiB, skip deep (> {args.max_mb} MiB)")
                    time.sleep(args.delay)
                    continue

                pdf_path = tmpdir / f"{dbk_id}.pdf"
                try:
                    final_url, get_headers = download(dbk_id, pdf_path, args.timeout)
                    if pdf_path.stat().st_size < 1000:
                        time.sleep(args.delay)
                        continue
                    with pdf_path.open("rb") as f:
                        if f.read(4) != b"%PDF":
                            time.sleep(args.delay)
                            continue
                    za, kind = inspect_pdf(pdf_path, args.pages)
                except Exception as e:
                    print(f"{dbk_id}: deep inspect failed: {e}")
                    time.sleep(args.delay)
                    continue

            if za:
                wanted = (not targets) or (za in targets)
                usable = kind in ("variable_report", "codebook")
                marker = "TARGET" if wanted else "other"
                print(f"{dbk_id}: {za} [{kind}] {marker}")

                if wanted and usable:
                    local = ""
                    if args.save_matches:
                        out = OUT_DIR / f"{za}_cdb.pdf"
                        OUT_DIR.mkdir(parents=True, exist_ok=True)

                        if pdf_path is None:
                            pdf_path = tmpdir / f"{dbk_id}.pdf"
                            final_url, _ = download(dbk_id, pdf_path, args.timeout)

                        # Save only verified variable reports/codebooks.
                        if kind in ("variable_report", "codebook"):
                            shutil.copy2(pdf_path, out)
                            local = str(out.relative_to(ROOT))
                            print(f"         saved -> {local}")

                    found[za] = dbk_id
                    append_map(dbk_id, za, kind, final_url, local)

            time.sleep(args.delay)

    print()
    print("FOUND")
    for za, dbk_id in sorted(found.items()):
        print(f"{za} -> {dbk_id}")

    if targets:
        missing = sorted(targets - set(found))
        if missing:
            print()
            print("NOT FOUND IN THIS RANGE")
            print(" ".join(missing))
            raise SystemExit(1)


if __name__ == "__main__":
    main()
