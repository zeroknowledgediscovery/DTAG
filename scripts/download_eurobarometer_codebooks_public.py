#!/usr/bin/env python3
"""Download public GESIS Eurobarometer codebook/Variable Report PDFs.

No GESIS login is required.  The script derives ZA identifiers from the
installed native Eurobarometer model directories, discovers the public
documentation link for each study, and saves the PDF as:

    data/eurobarometer/codebooks/ZAxxxx_cdb.pdf

Discovery order:
  1. legacy public DBK study-description page
     https://dbk.gesis.org/dbksearch/SDesc2.asp?db=E&no=7575
  2. current public GESIS study page
     https://search.gesis.org/research_data/ZA7575

The legacy DBK route is useful because GESIS historically exposed the
ZAxxxx_cdb.pdf link directly from the study-description page.  Current
access.gesis.org/dbk/<document-id> links and old
dbk.gesis.org/dbksearch/download.asp?id=<document-id> links are both accepted.

The downloader is resumable, validates the PDF signature, writes a manifest,
and sleeps between requests.

Examples:
  python3 scripts/download_eurobarometer_codebooks_public.py --all

  python3 scripts/download_eurobarometer_codebooks_public.py \
      --za ZA7575 --za ZA7783

  python3 scripts/download_eurobarometer_codebooks_public.py \
      --all --delay 2.0

  python3 scripts/download_eurobarometer_codebooks_public.py \
      --all --dry-run

Afterwards:
  python3 scripts/build_eurobarometer_maps.py --all
  python3 scripts/audit_eurobarometer_assets.py
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / "models" / "lsm" / "eurobarometer"
OUT_ROOT = ROOT / "data" / "eurobarometer" / "codebooks"
MANIFEST = OUT_ROOT / "download_manifest.csv"
STUDY_OVERVIEW_URL = (
    "https://www.gesis.org/en/eurobarometer-data-service/"
    "data-and-documentation/standard-special-eb/study-overview"
)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/152.0 Safari/537.36"
)

ZA_RE = re.compile(r"(ZA\d+)", re.I)


@dataclass
class Link:
    href: str
    text: str


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: List[Link] = []
        self._href: Optional[str] = None
        self._text: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = None
        for k, v in attrs:
            if k.lower() == "href":
                href = v
                break
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.links.append(Link(self._href, " ".join(self._text).strip()))
            self._href = None
            self._text = []


def normalize_za(value: str) -> str:
    m = ZA_RE.search(str(value).strip())
    if not m:
        s = str(value).strip()
        if s.isdigit():
            return "ZA" + s.zfill(4)
        raise ValueError(f"Invalid ZA identifier: {value!r}")
    digits = m.group(1)[2:]
    return "ZA" + digits.zfill(4)


def installed_za_ids() -> List[str]:
    if not MODEL_ROOT.is_dir():
        return []
    ids = set()
    for p in MODEL_ROOT.iterdir():
        if not p.is_dir():
            continue
        m = ZA_RE.search(p.name)
        if m:
            ids.add(normalize_za(m.group(1)))
    return sorted(ids, key=lambda z: int(z[2:]))


def request_bytes(url: str, timeout: float = 45.0) -> tuple[bytes, str, str]:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        final_url = resp.geturl()
        ctype = resp.headers.get("Content-Type", "")
    return body, final_url, ctype


def sparql_links(za: str, timeout: float = 45.0) -> List[Link]:
    """Discover public access.gesis.org DBK document URLs from GESIS KG.

    GESIS retired the old dbk.gesis.org catalog and search.gesis.org may
    return HTTP 403 to non-browser clients.  The GESIS Knowledge Graph is the
    supported public machine-readable metadata interface.
    """
    endpoint = "https://data.gesis.org/gesiskg/sparql"
    resource = f"https://data.gesis.org/gesiskg/resource/{za}"
    query = f"""
SELECT ?p ?o
WHERE {{
  <{resource}> ?p ?o .
  FILTER(isIRI(?o))
  FILTER(CONTAINS(STR(?o), "access.gesis.org/dbk/"))
}}
"""
    body = urlencode({"query": query}).encode("utf-8")
    req = Request(
        endpoint,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    links: List[Link] = []
    for binding in payload.get("results", {}).get("bindings", []):
        p = binding.get("p", {}).get("value", "")
        o = binding.get("o", {}).get("value", "")
        if not o:
            continue
        pred = p.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        links.append(Link(o, pred))
    return links


def probe_document_label(url: str, timeout: float = 20.0) -> str:
    """Return useful HTTP filename/content-type metadata without downloading."""
    try:
        req = Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"},
            method="HEAD",
        )
        with urlopen(req, timeout=timeout) as resp:
            cd = resp.headers.get("Content-Disposition", "")
            ct = resp.headers.get("Content-Type", "")
            return f"{cd} {ct}".strip()
    except Exception:
        return ""


def request_html(url: str, timeout: float = 45.0) -> tuple[str, str]:
    body, final_url, _ = request_bytes(url, timeout=timeout)
    # GESIS pages are usually UTF-8, but tolerate older DBK encodings.
    for enc in ("utf-8", "latin-1"):
        try:
            return body.decode(enc), final_url
        except UnicodeDecodeError:
            pass
    return body.decode("utf-8", errors="replace"), final_url


def parse_links(text: str, base_url: str) -> List[Link]:
    parser = LinkParser()
    parser.feed(text)
    out = []
    for x in parser.links:
        href = html.unescape(x.href.strip())
        if not href:
            continue
        out.append(Link(urljoin(base_url, href), re.sub(r"\s+", " ", x.text).strip()))
    return out


def score_link(za: str, link: Link) -> int:
    target = f"{za}_cdb.pdf".lower()
    href = link.href.lower()
    text = link.text.lower()
    joined = href + " " + text
    score = 0

    if target in joined:
        score += 5000
    if "_cdb.pdf" in joined:
        score += 3000
    if "variable report" in joined:
        score += 1800
    if "codebook" in joined:
        score += 1500
    if "variable" in joined and "report" in joined:
        score += 900
    if "access.gesis.org/dbk/" in href:
        score += 700

    # When links came from GESIS KG, link.text is the predicate local-name.
    # Prefer codebook/documentation relations and avoid dataset payload links.
    if "codebook" in text:
        score += 4000
    if "otherdoc" in text or "document" in text:
        score += 1800
    if "questionnaire" in text:
        score += 400
    if "dataset" in text:
        score -= 2500
    if "dbksearch/download.asp" in href:
        score += 650
    if href.endswith(".pdf"):
        score += 500
    if za.lower() in joined:
        score += 300

    # Questionnaires are useful, but they are secondary to the variable report.
    if "questionnaire" in joined:
        score -= 600

    return score


def candidate_links(za: str, links: Iterable[Link]) -> List[tuple[int, Link]]:
    scored = []
    for link in links:
        s = score_link(za, link)
        if s > 0:
            scored.append((s, link))
    scored.sort(key=lambda x: (-x[0], x[1].href))
    return scored


def _rescore_with_headers(
    za: str,
    scored: List[tuple[int, Link]],
    timeout: float,
) -> List[tuple[int, Link, str]]:
    """Use public HTTP metadata to distinguish codebooks from questionnaires."""
    out: List[tuple[int, Link, str]] = []
    for base_score, link in scored:
        label = probe_document_label(link.href, timeout=min(timeout, 20.0))
        low = label.lower()
        extra = 0
        if "_cdb.pdf" in low:
            extra += 8000
        if "variable report" in low:
            extra += 5000
        if "codebook" in low:
            extra += 4000
        if "questionnaire" in low:
            extra -= 1200
        if "basic bilingual" in low:
            extra -= 800
        out.append((base_score + extra, link, label))
    out.sort(key=lambda x: (-x[0], x[1].href))
    return out


def discover_from_eurobarometer_overview(
    za: str,
    timeout: float,
) -> tuple[str, str, int]:
    """Resolve ZA -> GESIS study profile -> Archive variable report.

    This is the preferred route for Standard/Special Eurobarometer.  GESIS
    publishes a public study-overview index containing all ZA identifiers, and
    each study profile links its Archive variable report directly.
    """
    index_text, index_final = request_html(STUDY_OVERVIEW_URL, timeout=timeout)
    index_links = parse_links(index_text, index_final)

    za_low = za.lower()
    profile_hits: List[Link] = []
    for link in index_links:
        text_low = link.text.lower()
        href_low = link.href.lower()
        if za_low in text_low or za_low in href_low:
            profile_hits.append(link)

    if not profile_hits:
        raise RuntimeError(
            f"{za} not found on Eurobarometer study-overview index"
        )

    # Exact textual ZA match is strongly preferred when more than one link
    # happens to mention the identifier.
    profile_hits.sort(
        key=lambda x: (
            0 if re.search(rf"\b{re.escape(za_low)}\b", x.text.lower()) else 1,
            len(x.href),
            x.href,
        )
    )

    diagnostics = []
    for profile in profile_hits:
        try:
            page_text, page_final = request_html(profile.href, timeout=timeout)
        except Exception as e:
            diagnostics.append(
                f"{profile.href}: {type(e).__name__}: {e}"
            )
            continue

        links = parse_links(page_text, page_final)

        # The study profiles use labels such as "Archive variable report".
        report_links = []
        for link in links:
            txt = link.text.lower()
            href = link.href.lower()
            score = 0
            if "archive variable report" in txt:
                score += 10000
            elif "variable report" in txt:
                score += 8000
            elif "codebook" in txt:
                score += 6000

            if "access.gesis.org/dbk/" in href:
                score += 1500
            if href.endswith(".pdf"):
                score += 500
            if "questionnaire" in txt:
                score -= 3000

            if score > 0:
                report_links.append((score, link))

        if report_links:
            report_links.sort(key=lambda x: (-x[0], x[1].href))
            score, best = report_links[0]
            return best.href, page_final, score

        diagnostics.append(
            f"{page_final}: no Archive variable report/codebook link found"
        )

    raise RuntimeError("; ".join(diagnostics))


def discover_document(za: str, timeout: float) -> tuple[str, str, int]:
    diagnostics = []

    # 1) Preferred route for Eurobarometer: the public GESIS study-profile
    # index. It contains ZA identifiers and links each study to its Archive
    # variable report without requiring login or search.gesis.org.
    try:
        return discover_from_eurobarometer_overview(za, timeout=timeout)
    except Exception as e:
        diagnostics.append(
            f"Eurobarometer study overview: {type(e).__name__}: {e}"
        )

    # 2) Secondary route: dereference the public GESIS KG resource page.
    # This page exposes the dataset metadata directly and includes public
    # access.gesis.org/dbk/... documentation links.  It avoids both the
    # retired DBK catalog and the search.gesis.org anti-bot response.
    resource_page = f"https://data.gesis.org/gesiskg/resource/{za}"
    try:
        text, final_page = request_html(resource_page, timeout=timeout)
        links = [
            x for x in parse_links(text, final_page)
            if "access.gesis.org/dbk/" in x.href.lower()
        ]
        if links:
            scored = candidate_links(za, links)
            rescored = _rescore_with_headers(za, scored, timeout)
            if rescored:
                score, best, label = rescored[0]
                return best.href, final_page, score
        diagnostics.append(
            f"{resource_page}: no public access.gesis.org/dbk documentation links found"
        )
    except Exception as e:
        diagnostics.append(f"{resource_page}: {type(e).__name__}: {e}")

    # 3) SPARQL route, retained as a secondary option.  Some deployments of
    # the endpoint reject POST/GET requests transiently, so failure here is not
    # fatal as long as the resource page works.
    try:
        kg_links = sparql_links(za, timeout=timeout)
        if kg_links:
            scored = candidate_links(za, kg_links)
            rescored = _rescore_with_headers(za, scored, timeout)
            if rescored:
                score, best, label = rescored[0]
                return best.href, resource_page, score
        diagnostics.append("GESIS KG SPARQL: no access.gesis.org/dbk document links found")
    except Exception as e:
        diagnostics.append(f"GESIS KG SPARQL: {type(e).__name__}: {e}")

    # 4) Compatibility fallbacks.
    digits = str(int(za[2:]))
    pages = [
        f"https://dbk.gesis.org/dbksearch/SDesc2.asp?db=E&no={digits}",
        f"https://search.gesis.org/research_data/{za}",
    ]

    for page in pages:
        try:
            text, final_page = request_html(page, timeout=timeout)
        except Exception as e:
            diagnostics.append(f"{page}: {type(e).__name__}: {e}")
            continue

        links = parse_links(text, final_page)
        scored = candidate_links(za, links)
        if scored:
            rescored = _rescore_with_headers(za, scored, timeout)
            score, best, label = rescored[0]
            return best.href, final_page, score

        diagnostics.append(f"{page}: no codebook/Variable Report link found")

    raise RuntimeError("; ".join(diagnostics))


def looks_like_pdf(data: bytes, ctype: str) -> bool:
    return data.startswith(b"%PDF") or "application/pdf" in ctype.lower()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def append_manifest(row: dict) -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    exists = MANIFEST.exists()
    fields = [
        "za_id",
        "status",
        "source_page",
        "document_url",
        "final_url",
        "bytes",
        "sha256",
        "local_path",
        "message",
    ]
    with MANIFEST.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fields})


def existing_pdf(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 1000:
        return False
    try:
        with path.open("rb") as f:
            return f.read(4) == b"%PDF"
    except OSError:
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="use all installed Eurobarometer native models")
    ap.add_argument("--za", action="append", default=[], help="specific ZA id; repeatable")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between studies")
    ap.add_argument("--timeout", type=float, default=45.0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="process at most N ZA ids")
    args = ap.parse_args()

    requested = [normalize_za(x) for x in args.za]
    if args.all:
        requested.extend(installed_za_ids())

    za_ids = sorted(set(requested), key=lambda z: int(z[2:]))
    if args.limit > 0:
        za_ids = za_ids[: args.limit]

    if not za_ids:
        raise SystemExit("Use --all and/or one or more --za ZAxxxx arguments.")

    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    print(f"Installed model root: {MODEL_ROOT}")
    print(f"Codebook output:       {OUT_ROOT}")
    print(f"Studies requested:     {len(za_ids)}")
    print("Authentication:        none (public documentation route)")
    print()

    ok = []
    skipped = []
    failed = []

    for idx, za in enumerate(za_ids, 1):
        out = OUT_ROOT / f"{za}_cdb.pdf"
        print("=" * 72)
        print(f"[{idx}/{len(za_ids)}] {za}")

        if existing_pdf(out) and not args.force:
            print(f"SKIP existing valid PDF: {out}")
            skipped.append(za)
            continue

        try:
            doc_url, source_page, score = discover_document(za, args.timeout)
            print(f"source page:  {source_page}")
            print(f"document:     {doc_url}")
            print(f"link score:   {score}")

            if args.dry_run:
                ok.append(za)
                continue

            data, final_url, ctype = request_bytes(doc_url, timeout=args.timeout)
            if not looks_like_pdf(data, ctype):
                prefix = data[:80].decode("utf-8", errors="replace").replace("\n", " ")
                raise RuntimeError(
                    f"download is not a PDF; content-type={ctype!r}; prefix={prefix!r}"
                )

            tmp = out.with_suffix(out.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(out)

            digest = sha256_bytes(data)
            print(f"saved:        {out}")
            print(f"size:         {len(data) / 1024**2:.2f} MiB")
            print(f"sha256:       {digest}")

            append_manifest(
                {
                    "za_id": za,
                    "status": "downloaded",
                    "source_page": source_page,
                    "document_url": doc_url,
                    "final_url": final_url,
                    "bytes": len(data),
                    "sha256": digest,
                    "local_path": str(out.relative_to(ROOT)),
                    "message": "",
                }
            )
            ok.append(za)

        except (HTTPError, URLError, TimeoutError, RuntimeError, OSError) as e:
            msg = f"{type(e).__name__}: {e}"
            print(f"FAILED: {msg}", file=sys.stderr)
            append_manifest(
                {
                    "za_id": za,
                    "status": "failed",
                    "local_path": str(out.relative_to(ROOT)),
                    "message": msg,
                }
            )
            failed.append(za)

        if idx < len(za_ids) and args.delay > 0:
            time.sleep(args.delay)

    print()
    print("=" * 72)
    print("SUMMARY")
    print(f"downloaded/discovered: {len(ok)}")
    print(f"already present:       {len(skipped)}")
    print(f"failed:                {len(failed)}")
    if failed:
        print("failed ZA ids:")
        print(" ".join(failed))
        (OUT_ROOT / "failed_public_downloads.txt").write_text(
            "\n".join(failed) + "\n", encoding="utf-8"
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
