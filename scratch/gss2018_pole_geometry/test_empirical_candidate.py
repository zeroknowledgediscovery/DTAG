#!/usr/bin/env python3
"""Native LSM evaluation for a FIXED respondent-derived 2018 pole CSV.

Does not change poles, tune response values, or select pole variables.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit import ANCHOR_ORDER, get_states, index, read_csv  # noqa: E402
from optimizer.dtag_bridge import World, ensure_model, canonical_map, DEFAULT_POLES  # noqa: E402


def eval_candidate(pole_csv: Path, out: Path, *, no_download=False):
    out.mkdir(parents=True, exist_ok=True)
    data = read_csv(pole_csv)
    L = {r["variable"]: r["L"] for r in data}
    R = {r["variable"]: r["R"] for r in data}
    if len(data) < 38 or len(data) > 45 or set(L) != set(R) or len(L) != len(data):
        raise ValueError("Candidate must specify 38–45 UNIQUE variables with both poles")
    if any(L[k] == R[k] for k in L):
        raise ValueError("Every pole response pair must be distinct")
    model = ensure_model("gss/gss_2018", None, download=not no_download)
    world = World(str(model), str(canonical_map("gss/gss_2018")),
                  str(DEFAULT_POLES), str(out / "cache"))
    invalid = {k: {"L": L[k], "R": R[k],
                   "available": world.ctx.possible.get(k)}
               for k in L if L[k] not in world.ctx.possible.get(k, ())
               or R[k] not in world.ctx.possible.get(k, ())}
    if invalid:
        (out / "invalid_labels.json").write_text(json.dumps(invalid, indent=2))
        raise ValueError(f"{len(invalid)} candidate pole response labels absent in native 2018 model")
    from audit import inventory
    _, waves = inventory(out)
    common = set(L) & set(waves[2024])
    pairs = {"respondent_derived": (L, R),
             "manual_v2_2018": (world.g.left_map, world.g.right_map)}
    if len(common) >= 2:
        pairs["respondent_derived_common2024"] = (
            {k: L[k] for k in common}, {k: R[k] for k in common})
    states, invalid_rich = get_states(world)
    results, orientation = [], []
    for name, (left, right) in pairs.items():
        baseline = index(world, {}, left, right)["index"]
        for person, state in states.items():
            obj = index(world, state, left, right)
            results.append({"variant": name, "persona": person, "n_items": len(left),
                            "I": obj["index"], "I_minus_empty": obj["index"]-baseline,
                            "d_LR": obj["d_LR"]})
        for var, order in ANCHOR_ORDER.items():
            available = [ans for ans in order if ans in world.ctx.possible.get(var, [])]
            scores = [index(world, {var: v}, left, right)["index"] for v in available]
            delta = [scores[j]-scores[i] for i in range(len(scores))
                     for j in range(i+1,len(scores))]
            orientation.append({"variant": name, "anchor": var, "n_labels": len(available),
                                "total_pairs": len(delta),
                                "concordant": sum(x > 1e-10 for x in delta),
                                "discordant": sum(x < -1e-10 for x in delta),
                                "ties": sum(abs(x) <= 1e-10 for x in delta),
                                "concordance_with_half_ties": (
                                    (sum(x > 1e-10 for x in delta) +
                                     .5*sum(abs(x) <= 1e-10 for x in delta))/len(delta)
                                    if delta else None)})
    import csv
    for filename, rows in (("native_persona_indices.csv", results),
                           ("native_anchor_orientation.csv", orientation)):
        with (out / filename).open("w", newline="") as f:
            writer = csv.DictWriter(f, rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    info = {
        "source_pole": str(pole_csv), "pole_items": len(L),
        "valid_native_labels": True, "native_model": str(model),
        "candidate_construction": "Empirical respondent-stratified, not model conditional",
        "source_data": "A Dropbox 357-respondent probe from a previous 20% split, "
                       "not the entire GSS 2018 dataset",
        "note": "No external respondent test here; simple one-anchor model conditions only. "
                "An apparent persona sign reversal does not validate the pole.",
        "personas": results, "anchor_orientations": orientation,
        "unavailable_reference_fields": invalid_rich,
    }
    (out / "summary.json").write_text(json.dumps(info, indent=2))
    lines = [
        "# Native model check of fixed empirical GSS 2018 pole", "",
        f"Pole file: {pole_csv}, {len(L)} items.",
        "All chosen answers are legal GSS 2018 native-model responses.", "",
        "| Variant | I(empty) | I(CM core) | I(WF core) | CM−WF |",
        "|---|---:|---:|---:|---:|",
    ]
    lookup = {(r["variant"],r["persona"]): r["I"] for r in results}
    for name in pairs:
        empty,cm,wf = (lookup[(name, person)]
                       for person in ("empty","CM_core","WF_core"))
        lines.append(f"| {name} | {empty:+.5f} | {cm:+.5f} | {wf:+.5f} | {cm-wf:+.5f} |")
    lines += ["", "## Native seven-category ordering (one-anchor conditions)", "",
              "| Variant | Anchor | Concordant | Discordant | Ties |",
              "|---|---|---:|---:|---:|"]
    for row in orientation:
        lines.append(
            f"| {row['variant']} | {row['anchor']} | {row['concordant']} | "
            f"{row['discordant']} | {row['ties']} |")
    lines += [
        "", "Comparison against CM/WF, or one-variable conditioned model states,",
        "is not independent respondent-level validation. The respondent-derived",
        "pole was learned on actual responses from a small Dropbox extract.",
        "The entire 2018 respondent dataset is to be processed by",
        "derive_from_respondents.py on the user's machine.", ""]
    (out / "REPORT.md").write_text("\n".join(lines))
    print("\n".join(lines), flush=True)
    return info


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--poles", type=Path, default=Path(__file__).parent /
                   "candidates/gss_2018_partyid_empirical42_probe357.csv")
    p.add_argument("--out", type=Path,
                   default=Path(__file__).parent / "results/native_empirical42_probe357")
    p.add_argument("--no-download", action="store_true")
    args = p.parse_args(argv)
    eval_candidate(args.poles.expanduser().resolve(), args.out.expanduser().resolve(),
                   no_download=args.no_download)


if __name__ == "__main__":
    main()
