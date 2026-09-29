#!/usr/bin/env python3
"""Build configs/model_coverage.json: which countries/years each native model covers.

The web application uses this index to recommend a native model from a
respondent's country and time *before* the model is downloaded. It is derived
from the models themselves: each public ``.tar.zst`` archive is streamed and
only its ``source_maps`` JSON shards are parsed (trees are never written to
disk).

Per model it records:

* ``country_feature`` / ``country_values``: the categorical country variable
  DTAG's localized pipeline would hard-condition (same feature-priority rule as
  ``pipeline_localized``), with its full support;
* ``nation_feature`` / ``nation_values``: for waves whose only country variable
  is not named "country" (older Eurobarometer ``v3``/``NATION``), the variable
  whose map label is NATION/COUNTRY -- coverage information only, since the
  pipeline cannot hard-condition it;
* ``year_feature`` / ``year_values``: e.g. WVS7 ``A_YEAR``;
* ``coordinate_values``: WVS-style O1_LONGITUDE/O2_LATITUDE support.

Usage:
  python scripts/build_model_coverage.py                 # all 252 public models
  python scripts/build_model_coverage.py --family afrobarometer
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import tarfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

import zstandard as zstd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_models  # noqa: E402
import pipeline_localized as localized  # noqa: E402

OUT = ROOT / "configs" / "model_coverage.json"


def _map_path(key: str) -> Optional[Path]:
    fam, name = key.split("/", 1)
    if fam == "eurobarometer":
        za = name.split("_", 1)[0].upper()
        p = ROOT / "maps" / "eurobarometer" / f"{za}_map.csv"
    elif fam == "afrobarometer":
        p = ROOT / "maps" / "afromap" / f"afrobarometer_{name.lower()}_map.csv"
    elif fam == "gss":
        p = ROOT / "maps" / "gss" / f"{name}_map.csv"
    else:
        p = ROOT / "maps" / "wvs7_variable_question_map.csv"
    return p if p.is_file() else None


def _nation_label_vars(key: str) -> List[str]:
    p = _map_path(key)
    if p is None:
        return []
    out = []
    with p.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            label = " ".join(str(row.get(c, "")) for c in ("variable_label", "question_text")).strip().upper()
            if re.match(r"^(NATION|COUNTRY)\b", label) and "REGION" not in label:
                out.append(str(row.get("variable", "")).strip())
    return out


def read_source_maps(url: str) -> Dict[str, List[str]]:
    """Stream an archive and return {feature: support} from source-map shards."""
    support: Dict[str, List[str]] = {}
    with urllib.request.urlopen(url, timeout=300) as r:
        with zstd.ZstdDecompressor().stream_reader(r) as zr:
            with tarfile.open(fileobj=zr, mode="r|") as tf:
                for m in tf:
                    if not (m.isfile() and "/source_maps/" in m.name and m.name.endswith(".json")):
                        continue
                    obj = json.loads(tf.extractfile(m).read().decode("utf-8"))
                    recs = [obj] if "column_header" in obj else [v for v in obj.values() if isinstance(v, dict)]
                    for node in recs:
                        name = str(node.get("column_header", "")).strip()
                        vals = node.get("column_strings_map")
                        if not name:
                            continue
                        if isinstance(vals, list):
                            support[name] = [str(x) for x in vals if x not in (None, "")]
                        elif isinstance(node.get("to_str"), dict):
                            pairs = sorted((int(k), str(v)) for k, v in node["to_str"].items() if str(k).isdigit())
                            support[name] = [v for _, v in pairs if v]
    return support


def summarize(key: str, support: Dict[str, List[str]]) -> Dict[str, object]:
    feats = [f for f in support if support[f]]
    country_feats = sorted(
        [f for f in feats if "country" in f.lower() and "region" not in f.lower()],
        key=localized._country_feature_priority,
    )
    rec: Dict[str, object] = {"features": len(support)}
    if country_feats:
        rec["country_feature"] = country_feats[0]
        rec["country_values"] = support[country_feats[0]]
    elif key.startswith("eurobarometer/"):
        for v in _nation_label_vars(key):
            if support.get(v):
                rec["nation_feature"] = v
                rec["nation_values"] = support[v]
                break
    for yf in ("A_YEAR", "year"):
        if support.get(yf):
            rec["year_feature"] = yf
            rec["year_values"] = sorted(support[yf])
            break
    if "O1_LONGITUDE" in support and "O2_LATITUDE" in support:
        rec["coordinate_features"] = ["O1_LONGITUDE", "O2_LATITUDE"]
        rec["coordinate_values"] = {f: support[f] for f in ("O1_LONGITUDE", "O2_LATITUDE")}
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", choices=["gss", "afrobarometer", "wvs", "eurobarometer"])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    manifest = fetch_models.load_manifest()
    keys = sorted(manifest["models"])
    if args.family:
        keys = [k for k in keys if k.startswith(args.family + "/")]

    out_path = Path(args.out)
    existing = json.loads(out_path.read_text()) if out_path.is_file() else {}
    models: Dict[str, object] = dict(existing.get("models", {}))

    def job(key: str):
        url = manifest["base_url"].rstrip("/") + "/" + manifest["models"][key]["archive"]
        return key, summarize(key, read_source_maps(url))

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = [ex.submit(job, k) for k in keys]
        for i, f in enumerate(as_completed(futs), 1):
            key, rec = f.result()
            models[key] = rec
            print(f"[{i}/{len(keys)}] {key}: {rec.get('country_feature') or rec.get('nation_feature') or '-'} "
                  f"({len(rec.get('country_values') or rec.get('nation_values') or [])} values)", flush=True)

    out = {
        "schema": "dtag-model-coverage/1",
        "release": manifest.get("release"),
        "generated_by": "scripts/build_model_coverage.py",
        "note": "Derived from native model source maps. country_values are the categorical support DTAG can "
                "hard-condition; nation_values are coverage-only (not conditionable by the pipeline).",
        "models": dict(sorted(models.items())),
    }
    out_path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path} ({len(models)} models)")


if __name__ == "__main__":
    main()
