#!/usr/bin/env python3
"""Is GSS 2018's ideology pole well calibrated? Independent model audit.

No question optimization, no changes to canonical model or poles.
Run from repository root:
    python scratch/gss2018_pole_geometry/audit.py --static-only
    python scratch/gss2018_pole_geometry/audit.py
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from optimizer.dtag_bridge import DEFAULT_POLES, World, canonical_map, ensure_model, model_record, sha256  # noqa: E402

POLE_DIR = ROOT / "assets" / "polar_vectors"
REF = ROOT / "assets" / "question_sets" / "personas" / "target_states.json"
CACHED = ROOT / "outputs" / "optimizer" / "sequence_library" / "cache" / "gss_2018_base_personas.json"
CORE = ("polviews", "partyid")
# Ordered GSS labels are an explicit, independent external orientation check,
# not a pole-definition change. Unrecognized alternatives remain unranked.
ANCHOR_ORDER = {
    "polviews": [
        "extremely liberal", "liberal", "slightly liberal",
        "moderate", "slghtly conservative",
        "conservative", "extrmly conservative"],
    "partyid": [
        "strong democrat", "not str democrat",
        "ind,near dem", "independent",
        "ind,near rep", "not str republican",
        "strong republican"]
}


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows, columns):
    with Path(path).open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def inventory(out):
    waves = {yr: {r["variable"]: {"L": r["L"], "R": r["R"]}
                  for r in read_csv(POLE_DIR / "gss" / f"gss_{yr}_polar_vectors.csv")}
             for yr in (2016, 2018, 2024)}
    old = {r[""]: {"L": r["L"], "R": r["R"]}
           for r in read_csv(POLE_DIR / "polar_vectors_v1.csv")}
    a, b = waves[2018], waves[2024]
    shared = set(a) & set(b)
    # Ground semantic scrutiny in the committed GSS codebook-derived map.
    wording = {r["variable"]: (r.get("question_text_filled") or r.get("question_text") or "")
               for r in read_csv(ROOT / "maps/gss/gss_2018_map.csv")}
    flagged = {
        "viruses": "scientific knowledge, not political ideology",
        "intmil": "interest in military issues is not necessarily ideological",
        "colmil": "free speech for militarist; ideological loading ambiguous",
        "libmil": "censorship of militarist book; ideological loading ambiguous",
        "spkmil": "speech by militarist; ideological loading ambiguous",
    }
    rows = [
        {"variable": v, "in_2018": v in a, "in_2024": v in b,
         "2018_question": wording.get(v, ""),
         "2018_L": a.get(v, {}).get("L", ""), "2018_R": a.get(v, {}).get("R", ""),
         "2024_L": b.get(v, {}).get("L", ""), "2024_R": b.get(v, {}).get("R", ""),
         "labels_differ": v in shared and a[v] != b[v],
         "semantic_review_flag": flagged.get(v, "")}
        for v in sorted(set(a) | set(b))]
    write_csv(out / "wave_pole_inventory.csv", rows, list(rows[0]))
    changes = [
        {"variable": v, "v1_L": old[v]["L"], "v1_R": old[v]["R"],
         "v2_L": a[v]["L"], "v2_R": a[v]["R"]}
        for v in sorted(a) if v in old and a[v] != old[v]]
    write_csv(out / "v1_v2_changes.csv", changes,
              ["variable", "v1_L", "v1_R", "v2_L", "v2_R"])
    resolved = [r for r in read_csv(POLE_DIR / "gss" / "pole_resolution_report.csv")
                if r["wave"] == "2018"]
    summary = {
        "counts": {str(y): len(v) for y, v in waves.items()},
        "shared_2018_2024": len(shared),
        "extra_2018": sorted(set(a) - set(b)),
        "extra_2018_questions": {v: wording.get(v, "") for v in sorted(set(a) - set(b))},
        "anchors_in_2018_pole": [v for v in CORE if v in a],
        "different_labels": sorted(v for v in shared if a[v] != b[v]),
        "nominal_v1_v2_answer_changes": [r["variable"] for r in changes],
        "2018_unresolved": [
            r for r in resolved if r["status"] == "dropped" and r["reason"] != "item not in wave"],
        "semantic_review_flags": flagged,
        "2018_pole_sha256": sha256(POLE_DIR / "gss/gss_2018_polar_vectors.csv")}
    (out / "static_summary.json").write_text(json.dumps(summary, indent=2))
    return summary, waves


def get_states(world, cached_path=None):
    states = {"empty": {}}
    rejected = []
    references = json.loads(REF.read_text(encoding="utf-8"))
    for label in ("CM", "WF"):
        accepted, invalid = world.valid(references[label]["state"])
        missing = set(CORE) - set(accepted)
        if missing:
            raise ValueError(f"2018 rejected {label} political anchors {sorted(missing)}. "
                             f"Rejected assignments: {invalid}")
        states[f"{label}_core"] = {k: accepted[k] for k in CORE}
        states[f"{label}_rich"] = accepted
        rejected += [{"persona": label, "assignment": item} for item in invalid]
    if cached_path is not None and Path(cached_path).is_file():
        for entry in json.loads(Path(cached_path).read_text(encoding="utf-8")):
            name = entry["id"].lower()
            label = "CM" if name.startswith("cm") else "WF" if name.startswith("wf") else None
            if label:
                accepted, invalid = world.valid(entry["state"])
                states[f"{label}_cached"] = accepted
                rejected += [{"persona": f"{label}_cached", "assignment": item} for item in invalid]
    return states, rejected


def index(world, state, L, R):
    from dtag_core import build_pole_vector, build_full_vector_from_state
    m = world.m
    sl, sr = (build_pole_vector(m, v, world.ctx.idx_map) for v in (L, R))
    s = build_full_vector_from_state(m, state, world.ctx.idx_map)
    denominator = float(m.qdistance(sl, sr))
    if not math.isfinite(denominator) or denominator <= 0:
        raise ValueError("Pole distance zero or nonfinite")
    if hasattr(m, "distances_to_state"):
        dl, dr = m.distances_to_state(sl, sr, s)
    else:
        dl, dr = m.qdistance(sl, s), m.qdistance(sr, s)
    value = float((dl - dr) / denominator)
    if not math.isfinite(value):
        raise ValueError("Nonfinite index")
    return {"index": value, "d_left": float(dl), "d_right": float(dr),
            "d_LR": denominator, "numerator": float(dl-dr)}


def variants(world, waves):
    from dtag_core import load_polar_vectors_csv
    from polar_vectors import load_corrections, resolve_poles

    v2L, v2R = dict(world.g.left_map), dict(world.g.right_map)
    rawL, rawR = load_polar_vectors_csv(str(POLE_DIR / "polar_vectors_v1.csv"))
    v1L, v1R, resolution = resolve_poles(
        rawL, rawR, world.ctx.possible, load_corrections())
    common_v1 = sorted(set(v2L) & set(v1L))
    common_2024 = sorted(set(v2L) & set(waves[2024]))
    subset = lambda vals, names: {k: vals[k] for k in names}
    result = {
        "2018_v2_all": (v2L, v2R),
        "2018_v1_all_resolved": (v1L, v1R),
        "2018_v1_matched_items": (subset(v1L, common_v1), subset(v1R, common_v1)),
        "2018_v2_matched_items": (subset(v2L, common_v1), subset(v2R, common_v1)),
        "2018_v2_common_with_2024": (subset(v2L, common_2024),
                                    subset(v2R, common_2024)),
        "2018_v2_without_viruses": (
            {k: v for k, v in v2L.items() if k != "viruses"},
            {k: v for k, v in v2R.items() if k != "viruses"}),
    }
    details = {
        "v1_pairs": len(v1L), "v2_pairs": len(v2L),
        "v1_matched_pairs": len(common_v1),
        "common_with_2024_pairs": len(common_2024),
        "v1_resolver_dropped": [r for r in resolution if r["status"] == "dropped"],
        "warning": "2024 here is only a 27-variable filter; all indexes use the 2018 model"}
    return result, details


def run_native(out, static, waves, args):
    model_path = ensure_model("gss/gss_2018", None, download=not args.no_download)
    world = World(str(model_path), str(canonical_map("gss/gss_2018")),
                  str(DEFAULT_POLES), str(out / "native_cache"))
    expected = waves[2018]
    if set(world.g.left_map) != set(expected) or any(
        world.g.left_map[v] != pair["L"] or world.g.right_map[v] != pair["R"]
        for v, pair in expected.items()):
        raise RuntimeError("Runtime pole file does not match 2018 committed pole CSV")
    states, rejected = get_states(world, args.cached_personas if args.include_cached else None)
    pairs, details = variants(world, waves)
    results = []
    for name, (L, R) in pairs.items():
        for persona, state in states.items():
            results.append({"variant": name, "persona": persona,
                            "n_state_assignments": len(state), "n_pole_pairs": len(L),
                            **index(world, state, L, R)})
    lookup = {(r["variant"], r["persona"]): r["index"] for r in results}
    for row in results:
        row["minus_empty_same_pole"] = (
            row["index"] - lookup[(row["variant"], "empty")])
        row["minus_2018_v2_all"] = (
            row["index"] - lookup[("2018_v2_all", row["persona"])])
    for persona, state in states.items():
        if abs(float(world.I(state)) - lookup[("2018_v2_all", persona)]) > 1e-9:
            raise AssertionError("Index calculation differs from production DTAG World.I")
    output_csv = write_csv
    output_csv(out / "native_variants.csv", results,
               ["variant", "persona", "n_state_assignments", "n_pole_pairs",
                "index", "d_left", "d_right", "d_LR", "numerator",
                "minus_empty_same_pole", "minus_2018_v2_all"])
    # Externally ordered anchor sweep: test orientation without redefining poles.
    sweep = []
    sweep_diagnostics = {}
    for anchor, order in ANCHOR_ORDER.items():
        available = set(world.ctx.possible.get(anchor, []))
        selected = [(i, value) for i, value in enumerate(order) if value in available]
        sweep_diagnostics[anchor] = {
            "expected_labels": order, "tested_labels": [value for _, value in selected],
            "not_found": [value for value in order if value not in available],
            "unranked_model_labels": sorted(available.difference(order))}
        for rank, label in selected:
            state = {anchor: label}
            for variant in ("2018_v2_all", "2018_v1_matched_items",
                            "2018_v2_common_with_2024"):
                L, R = pairs[variant]
                val = index(world, state, L, R)["index"]
                sweep.append({"variable": anchor, "response_label": label,
                              "order_liberal_to_conservative": rank,
                              "variant": variant, "index": val,
                              "minus_empty_same_pole": val - lookup[(variant, "empty")]})
        ordered = [r for r in sweep if r["variable"] == anchor
                   and r["variant"] == "2018_v2_all"]
        actual = [r["index"] for r in ordered]
        pairs_checked = [(actual[j] - actual[i]) for i in range(len(actual))
                         for j in range(i+1, len(actual))]
        concordant = sum(delta > 1e-10 for delta in pairs_checked)
        discordant = sum(delta < -1e-10 for delta in pairs_checked)
        tied = len(pairs_checked) - concordant - discordant
        sweep_diagnostics[anchor]["pairwise_monotonicity_reversals_v2"] = discordant
        sweep_diagnostics[anchor]["n_pairwise_comparisons"] = len(pairs_checked)
        sweep_diagnostics[anchor]["concordant"] = concordant
        sweep_diagnostics[anchor]["discordant"] = discordant
        sweep_diagnostics[anchor]["ties"] = tied
        sweep_diagnostics[anchor]["concordance_ties_half_credit"] = (
            (concordant + 0.5 * tied) / len(pairs_checked)
            if pairs_checked else None)
    output_csv(out / "anchor_monotonicity.csv", sweep,
               ["variable", "response_label", "order_liberal_to_conservative",
                "variant", "index", "minus_empty_same_pole"])
    loo = []
    if not args.skip_loo:
        fullL, fullR = pairs["2018_v2_all"]
        for remove in sorted(fullL):
            L = {k: v for k, v in fullL.items() if k != remove}
            R = {k: v for k, v in fullR.items() if k != remove}
            for persona, state in states.items():
                now = index(world, state, L, R)["index"]
                original = lookup[("2018_v2_all", persona)]
                loo.append({"removed_pole_item": remove, "persona": persona,
                            "full_index": original, "without_index": now,
                            "change_in_index": now-original,
                            "changed_sign": (now > 0) != (original > 0)})
    output_csv(out / "leave_one_out.csv", loo,
               ["removed_pole_item", "persona", "full_index",
                "without_index", "change_in_index", "changed_sign"])
    payload = {"model": "gss/gss_2018", "map_sha256": sha256(Path(world.map_path)),
               "pole_sha256": sha256(Path(world.g.path)),
               "model_manifest_entry": model_record("gss/gss_2018"),
               "variants": details, "conditioned_states": states,
               "rejected_reference_assignments": rejected,
               "indices": results, "leave_one_out": loo,
               "anchor_sweep": sweep, "anchor_sweep_diagnostics": sweep_diagnostics}
    (out / "native_summary.json").write_text(json.dumps(payload, indent=2, default=str))
    return payload


def write_report(out, static, native=None):
    lines = ["# GSS 2018 pole adequacy audit", "",
             "Independent diagnostic. No question optimization and no changes to production poles.",
             "", "## Static facts", "",
             f"Pole sizes: 2016={static['counts']['2016']}, "
             f"2018={static['counts']['2018']}, 2024={static['counts']['2024']}.",
             f"2018/2024 overlap: {static['shared_2018_2024']} variables.",
             "2018-only: " + ", ".join(static["extra_2018"]),
             "Wave-dependent response labels: " + ", ".join(static["different_labels"]),
             "Unresolved 2018 canonical item(s): " +
             ", ".join(x["item"] for x in static["2018_unresolved"]), "",
             "The 2018 pole may be syntactically valid without its zero point being",
             "substantively calibrated. Compare WF against I(empty), not just against zero."]
    if native is None:
        lines += ["", "Native model diagnostic not yet run. Run without --static-only."]
    else:
        lookup = {(r["variant"], r["persona"]): r for r in native["indices"]}
        variants_used = list(dict.fromkeys(r["variant"] for r in native["indices"]))
        names = ("empty", "CM_core", "WF_core", "CM_rich", "WF_rich")
        lines += ["", "## Native-model index (same model, different pole definitions)", "",
                  "| Pole variant | " + " | ".join(names) + " |",
                  "|---|" + "---:|" * len(names)]
        for variant in variants_used:
            fmt = lambda name: (
                f"{lookup[(variant, name)]['index']:+.5f}"
                if (variant, name) in lookup else "—")
            lines.append("| " + variant + " | " + " | ".join(fmt(n) for n in names) + " |")
        lines += ["", "## Interpretation", "",
                  "2018 v2 anchor monotonicity diagnostics: " +
                  json.dumps(native["anchor_sweep_diagnostics"], sort_keys=True), "" ,
                  "1. Verify an empty-state offset before interpreting the absolute sign.",
                  "2. Determine whether CM > WF even if both are positive.",
                  "3. Compare v1/v2 on the matched item set; do not confuse pole",
                  "   composition with answer-category changes.",
                  "4. Compare 2018 full 38-item pole with its 27-item common subset.",
                  "5. Inspect the effect of removing the science-knowledge item viruses.",
                  "6. Inspect leave_one_out.csv, recognizing that changes are nonadditive.",
                  "7. Check anchor_monotonicity.csv: does the 2018 index rise",
                  "   from liberal/Democratic to conservative/Republican survey labels?",
                  "8. Verify observations under core and rich states, and optional",
                  "   LLM-decoded cached states. A descriptive persona is not a population sample.",
                  "", "Do not revise canonical poles solely to make a chosen persona negative."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--static-only", action="store_true")
    p.add_argument("--no-download", action="store_true")
    p.add_argument("--skip-loo", action="store_true")
    p.add_argument("--include-cached", action="store_true")
    p.add_argument("--cached-personas", type=Path, default=CACHED)
    p.add_argument("--out", type=Path, default=Path(__file__).parent / "results")
    args = p.parse_args(argv)
    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    summary, waves = inventory(out)
    print("Static 2018 pairs =", summary["counts"]["2018"],
          "shared with 2024 =", summary["shared_2018_2024"], flush=True)
    native = None
    if not args.static_only:
        native = run_native(out, summary, waves, args)
        for row in native["indices"]:
            if row["persona"] in ("empty", "CM_core", "WF_core") and row["variant"] in (
                    "2018_v2_all", "2018_v1_all_resolved", "2018_v2_common_with_2024"):
                print(row["variant"], row["persona"], f"I={row['index']:+.5f}",
                      f"I-I(empty)={row['minus_empty_same_pole']:+.5f}", flush=True)
    write_report(out, summary, native)
    print("Report:", out / "REPORT.md", flush=True)


if __name__ == "__main__":
    main()
