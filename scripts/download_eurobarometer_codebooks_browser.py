#!/usr/bin/env python3
"""Download Eurobarometer variable reports through an existing Chrome session.

Why this exists
---------------
GESIS access.gesis.org may serve variable-report PDFs successfully to an
interactive browser while rejecting ordinary scripted HTTP clients (urllib,
requests, rgesis/search metadata, HEAD probes, etc.).  This downloader does not
try to imitate Chrome.  It attaches over Chrome DevTools Protocol (CDP) to a
Chrome instance launched by the user and lets Chrome itself perform all GESIS
navigation and PDF retrieval.

The browser profile is persistent, so any GESIS cookies/challenges accepted in
that browser remain available to the batch run.

One-time setup
--------------
1. Install the Python controller only (no Playwright browser download needed):

     python3 -m pip install playwright

2. Launch a dedicated real Chrome profile with remote debugging:

     google-chrome \
       --remote-debugging-port=9222 \
       --user-data-dir="$HOME/.cache/dtag-gesis-chrome" \
       https://access.gesis.org/dbk/9151

3. In that Chrome window, confirm that the ZA1544 codebook opens normally.
   Complete any browser challenge/login if GESIS presents one.  Leave Chrome
   running.

Examples
--------
Known direct mapping smoke test:

  python3 scripts/download_eurobarometer_codebooks_browser.py \
      --za ZA1544 --dbk ZA1544=9151

Discover the Archive variable report link in the GESIS study profile using the
same live Chrome session:

  python3 scripts/download_eurobarometer_codebooks_browser.py --za ZA1544

Process every installed native Eurobarometer model:

  python3 scripts/download_eurobarometer_codebooks_browser.py --all

Afterwards:

  python3 scripts/build_eurobarometer_maps.py --all
  python3 scripts/audit_eurobarometer_assets.py

No HTTP request to GESIS is made by Python.  Page navigation and PDF bytes are
obtained from the attached Chrome process via CDP.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / "models" / "lsm" / "eurobarometer"
OUT_ROOT = ROOT / "data" / "eurobarometer" / "codebooks"
MANIFEST = OUT_ROOT / "browser_download_manifest.csv"

STUDY_OVERVIEW_URL = (
    "https://www.gesis.org/en/eurobarometer-data-service/"
    "data-and-documentation/standard-special-eb/study-overview"
)

ZA_RE = re.compile(r"(ZA\s*0*\d+)", re.I)


def normalize_za(value: str) -> str:
    s = str(value).strip().upper().replace(" ", "")
    if s.startswith("ZA"):
        s = s[2:]
    if not s.isdigit():
        raise ValueError(f"Invalid ZA identifier: {value!r}")
    return "ZA" + s.zfill(4)


def za_pattern(za: str) -> re.Pattern[str]:
    digits = re.escape(str(int(normalize_za(za)[2:])))
    return re.compile(rf"\bZA\s*0*{digits}\b", re.I)


def installed_za_ids() -> List[str]:
    if not MODEL_ROOT.is_dir():
        return []
    out = set()
    for p in MODEL_ROOT.iterdir():
        if not p.is_dir():
            continue
        m = ZA_RE.search(p.name)
        if m:
            out.add(normalize_za(m.group(1)))
    return sorted(out, key=lambda z: int(z[2:]))


def parse_dbk_args(values: Iterable[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError(f"--dbk expects ZAxxxx=NNNN, got {raw!r}")
        left, right = raw.split("=", 1)
        za = normalize_za(left)
        try:
            dbk = int(right.strip())
        except ValueError as e:
            raise ValueError(f"Invalid DBK id in {raw!r}") from e
        if dbk <= 0:
            raise ValueError(f"Invalid DBK id in {raw!r}")
        out[za] = dbk
    return out


def existing_verified_pdf(path: Path, za: str) -> bool:
    if not path.is_file() or path.stat().st_size < 1000:
        return False
    try:
        validate_variable_report_pdf(path, za)
        return True
    except Exception:
        return False


def validate_variable_report_pdf(path: Path, expected_za: str, pages: int = 15) -> None:
    expected_za = normalize_za(expected_za)
    pattern = za_pattern(expected_za)
    digits = re.escape(str(int(expected_za[2:])))
    gesis_study = re.compile(
        rf"\bGESIS\s+Study\s+(?:No\.?|Number)\s*(?:ZA\s*)?0*{digits}\b",
        re.I,
    )

    with path.open("rb") as f:
        if f.read(4) != b"%PDF":
            raise RuntimeError("file is not a PDF")

    try:
        with pdfplumber.open(str(path)) as pdf:
            if not pdf.pages:
                raise RuntimeError("PDF has no pages")
            text = "\n".join(
                (p.extract_text() or "")
                for p in pdf.pages[: min(pages, len(pdf.pages))]
            )
    except Exception as e:
        raise RuntimeError(f"cannot parse PDF: {e}") from e

    if not (pattern.search(text) or gesis_study.search(text)):
        raise RuntimeError(f"PDF does not identify expected study {expected_za}")

    low = text.lower()
    markers = (
        "variable report",
        "variable documentation",
        "codebook",
    )
    if not any(x in low for x in markers):
        raise RuntimeError(
            f"PDF identifies {expected_za} but does not look like a variable report/codebook"
        )


def append_manifest(row: dict) -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    fields = [
        "za_id",
        "status",
        "profile_url",
        "document_url",
        "dbk_id",
        "bytes",
        "sha256",
        "local_path",
        "message",
    ]
    exists = MANIFEST.exists()
    with MANIFEST.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fields})


def browser_links(page) -> List[dict]:
    return page.locator("a").evaluate_all(
        """els => els.map(a => ({
            text: (a.innerText || a.textContent || "").replace(/\\s+/g, " ").trim(),
            href: a.href || ""
        }))"""
    )


def wait_dom(page, url: str, timeout_ms: int) -> None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception as e:
        # Some GESIS/browser transitions can abort after the useful document
        # response has already been committed.  Only tolerate the abort when
        # Chrome visibly reached the requested host.
        current = page.url or ""
        if urlparse(current).netloc != urlparse(url).netloc:
            raise RuntimeError(f"Chrome navigation failed for {url}: {e}") from e


def discover_profile_url(page, za: str, timeout_ms: int) -> str:
    wait_dom(page, STUDY_OVERVIEW_URL, timeout_ms)
    pat = za_pattern(za)
    hits = []
    for link in browser_links(page):
        text = str(link.get("text", ""))
        href = str(link.get("href", ""))
        if pat.search(text) or pat.search(href):
            hits.append((0 if pat.search(text) else 1, len(href), href, text))

    if not hits:
        raise RuntimeError(f"{za} not found in GESIS Eurobarometer Study Profiles")

    hits.sort()
    return hits[0][2]


def discover_variable_report_url(page, za: str, profile_url: str, timeout_ms: int) -> str:
    wait_dom(page, profile_url, timeout_ms)

    body = page.locator("body").inner_text(timeout=timeout_ms)
    if not za_pattern(za).search(body) and not za_pattern(za).search(page.url):
        raise RuntimeError(f"Study profile does not identify expected {za}: {page.url}")

    candidates = []
    for link in browser_links(page):
        text = str(link.get("text", "")).strip()
        href = str(link.get("href", "")).strip()
        low = text.lower()
        score = 0
        if "archive variable report" in low:
            score += 10000
        elif "variable report" in low:
            score += 8000
        elif "codebook" in low:
            score += 6000
        if "access.gesis.org/dbk/" in href.lower():
            score += 1500
        if "questionnaire" in low:
            score -= 5000
        if score > 0 and href:
            candidates.append((score, href, text))

    if not candidates:
        raise RuntimeError(f"No Archive variable report link found on {page.url}")

    candidates.sort(key=lambda x: (-x[0], x[1]))
    return candidates[0][1]


def dbk_id_from_url(url: str) -> str:
    m = re.search(r"/dbk/(\d+)", url)
    return m.group(1) if m else ""


def capture_pdf_through_chrome(page, context, url: str, timeout_ms: int) -> bytes:
    """Navigate real Chrome to URL and capture the PDF response through CDP.

    Two paths are enabled simultaneously:
      * Chrome download manager, for attachment responses.
      * Network.getResponseBody, for inline application/pdf responses.
    """
    with tempfile.TemporaryDirectory(prefix="dtag_gesis_browser_") as td:
        tmpdir = Path(td)
        session = context.new_cdp_session(page)
        session.send("Network.enable")
        try:
            session.send(
                "Browser.setDownloadBehavior",
                {
                    "behavior": "allow",
                    "downloadPath": str(tmpdir),
                    "eventsEnabled": True,
                },
            )
        except Exception:
            # Older Chrome versions may expose this under Page instead.
            try:
                session.send(
                    "Page.setDownloadBehavior",
                    {"behavior": "allow", "downloadPath": str(tmpdir)},
                )
            except Exception:
                pass

        pdf_requests: List[dict] = []
        finished = set()

        def on_response(params):
            response = params.get("response", {})
            mime = str(response.get("mimeType", "")).lower()
            rurl = str(response.get("url", ""))
            headers = {
                str(k).lower(): str(v)
                for k, v in (response.get("headers") or {}).items()
            }
            ctype = headers.get("content-type", "").lower()
            if (
                "pdf" in mime
                or "application/pdf" in ctype
                or "access.gesis.org/dbk/" in rurl.lower()
            ):
                pdf_requests.append(
                    {
                        "request_id": params.get("requestId"),
                        "url": rurl,
                        "mime": mime,
                        "ctype": ctype,
                    }
                )

        def on_finished(params):
            rid = params.get("requestId")
            if rid:
                finished.add(rid)

        session.on("Network.responseReceived", on_response)
        session.on("Network.loadingFinished", on_finished)

        nav_error: Optional[Exception] = None
        try:
            page.goto(url, wait_until="commit", timeout=timeout_ms)
        except Exception as e:
            nav_error = e

        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            # Attachment/download path.
            completed = [
                p for p in tmpdir.iterdir()
                if p.is_file() and not p.name.endswith(".crdownload")
            ]
            for p in completed:
                try:
                    data = p.read_bytes()
                except OSError:
                    continue
                if data.startswith(b"%PDF"):
                    return data

            # Inline/network response path.
            for item in reversed(pdf_requests):
                rid = item.get("request_id")
                if not rid or rid not in finished:
                    continue
                try:
                    payload = session.send(
                        "Network.getResponseBody",
                        {"requestId": rid},
                    )
                except Exception:
                    continue

                body = payload.get("body", "")
                if payload.get("base64Encoded"):
                    try:
                        data = base64.b64decode(body)
                    except Exception:
                        continue
                else:
                    data = str(body).encode("latin-1", errors="ignore")

                if data.startswith(b"%PDF"):
                    return data

            page.wait_for_timeout(250)

        detail = f"; navigation error={nav_error}" if nav_error else ""
        raise RuntimeError(
            f"Chrome reached no capturable PDF response for {url}{detail}. "
            "Open this URL manually in the attached Chrome window; if it works, "
            "leave that tab/profile open and rerun."
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="process every installed native Eurobarometer model")
    ap.add_argument("--za", action="append", default=[],
                    help="ZA study id; repeatable")
    ap.add_argument("--dbk", action="append", default=[],
                    help="known mapping ZAxxxx=DBKID; repeatable")
    ap.add_argument("--cdp", default="http://127.0.0.1:9222",
                    help="Chrome DevTools endpoint")
    ap.add_argument("--timeout", type=float, default=90.0,
                    help="per-navigation timeout in seconds")
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    requested = [normalize_za(x) for x in args.za]
    if args.all:
        requested.extend(installed_za_ids())

    known_dbk = parse_dbk_args(args.dbk)
    requested.extend(known_dbk)

    za_ids = sorted(set(requested), key=lambda z: int(z[2:]))
    if not za_ids:
        raise SystemExit("Use --all, --za ZAxxxx, and/or --dbk ZAxxxx=NNNN")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "Missing Playwright Python package. Install only the controller with:\n"
            "  python3 -m pip install playwright\n"
            "Do NOT run 'playwright install'; this script attaches to your existing Chrome."
        )

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    timeout_ms = int(args.timeout * 1000)

    print(f"Chrome CDP:             {args.cdp}")
    print(f"Installed model root:  {MODEL_ROOT}")
    print(f"Codebook output:        {OUT_ROOT}")
    print(f"Studies requested:      {len(za_ids)}")
    print("Transport:              existing interactive Chrome via CDP")
    print()

    ok: List[str] = []
    skip: List[str] = []
    fail: List[str] = []

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.connect_over_cdp(args.cdp)
        except Exception as e:
            raise SystemExit(
                f"Cannot attach to Chrome at {args.cdp}: {e}\n\n"
                "Launch Chrome first, for example:\n"
                "  google-chrome --remote-debugging-port=9222 "
                "--user-data-dir=\"$HOME/.cache/dtag-gesis-chrome\" "
                "https://access.gesis.org/dbk/9151"
            )

        if not browser.contexts:
            raise SystemExit("Attached Chrome exposes no browser context")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()

        for i, za in enumerate(za_ids, 1):
            out = OUT_ROOT / f"{za}_cdb.pdf"
            print("=" * 76)
            print(f"[{i}/{len(za_ids)}] {za}")

            if existing_verified_pdf(out, za) and not args.force:
                print(f"SKIP existing verified variable report: {out}")
                skip.append(za)
                continue

            profile_url = ""
            document_url = ""
            try:
                if za in known_dbk:
                    dbk_id = str(known_dbk[za])
                    document_url = f"https://access.gesis.org/dbk/{dbk_id}"
                    print(f"known DBK:              {dbk_id}")
                else:
                    profile_url = discover_profile_url(page, za, timeout_ms)
                    print(f"study profile:          {profile_url}")
                    document_url = discover_variable_report_url(
                        page, za, profile_url, timeout_ms
                    )
                    dbk_id = dbk_id_from_url(document_url)
                    print(f"Archive variable report:{document_url}")

                data = capture_pdf_through_chrome(
                    page, context, document_url, timeout_ms
                )

                tmp = out.with_suffix(".pdf.part")
                tmp.write_bytes(data)
                try:
                    validate_variable_report_pdf(tmp, za)
                except Exception:
                    tmp.unlink(missing_ok=True)
                    raise
                tmp.replace(out)

                digest = hashlib.sha256(data).hexdigest()
                print(f"saved:                  {out}")
                print(f"size:                   {len(data) / 1024**2:.2f} MiB")
                print(f"sha256:                 {digest}")

                append_manifest(
                    {
                        "za_id": za,
                        "status": "downloaded",
                        "profile_url": profile_url,
                        "document_url": document_url,
                        "dbk_id": dbk_id,
                        "bytes": len(data),
                        "sha256": digest,
                        "local_path": str(out.relative_to(ROOT)),
                        "message": "",
                    }
                )
                ok.append(za)
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                print(f"FAILED: {msg}")
                append_manifest(
                    {
                        "za_id": za,
                        "status": "failed",
                        "profile_url": profile_url,
                        "document_url": document_url,
                        "dbk_id": dbk_id_from_url(document_url),
                        "local_path": str(out.relative_to(ROOT)),
                        "message": msg,
                    }
                )
                fail.append(za)

            if i < len(za_ids) and args.delay > 0:
                time.sleep(args.delay)

    print()
    print("=" * 76)
    print("SUMMARY")
    print(f"downloaded:       {len(ok)}")
    print(f"already present:  {len(skip)}")
    print(f"failed:           {len(fail)}")
    if fail:
        print("failed ZA ids:")
        print(" ".join(fail))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
