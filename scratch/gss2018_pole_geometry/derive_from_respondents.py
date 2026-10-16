#!/usr/bin/env python3
"""Descriptive GSS 2018 pole construction from ACTUAL respondent CSV.

The pole variable set is fixed before examining party associations (38 original
items plus four predefined questions). Every variable is retained, including
weak or contradictory ones, and a response-pair provenance report is produced.

Default respondent file (Dropbox synchronized local path):
  ~/Dropbox/ZED/Research/MAGICS_research/survey/data/gss/gss_2018.csv

Example (from the DTAG root):
  python scratch/gss2018_pole_geometry/derive_from_respondents.py
  python scratch/gss2018_pole_geometry/derive_from_respondents.py \
    --csv /D1/Dropbox/ZED/Research/MAGICS_research/survey/data/gss/gss_2018.csv \
    --native-eval

The main output remains in scratch/results and does not change canonical poles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit import ANCHOR_ORDER, index as model_index, get_states  # noqa: E402
from optimizer.dtag_bridge import DEFAULT_POLES, World, canonical_map, ensure_model  # noqa: E402

BASE = ROOT / "assets/polar_vectors/gss/gss_2018_polar_vectors.csv"
EXTRA = ("conpress", "eqwlth", "cappun", "goveqinc")
GROUPS = {
    "L": {"strong democrat", "not str democrat", "ind,near dem"},
    "R": {"strong republican", "not str republican", "ind,near rep"},
}
POLVIEWS = {
    "L": {"extremely liberal", "liberal", "slightly liberal"},
    "R": {"slghtly conservative", "conservative", "extrmly conservative"},
}
BAND = {"polviews", "partyid"}
MISSING = {"", "nan", "none", "null"}


def default_csv() -> Path:
    candidates = [
        Path.home() / "Dropbox/ZED/Research/MAGICS_research/survey/data/gss/gss_2018.csv",
        Path("/D1/Dropbox/ZED/Research/MAGICS_research/survey/data/gss/gss_2018.csv"),
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_rows(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing GSS 2018 respondents at {path}. Retrieve the original Dropbox "
            "file under ZED/Research/MAGICS_research/survey/data/gss/gss_2018.csv")
    data = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    data.columns = [str(col).strip() for col in data.columns]
    if data.columns.duplicated().any():
        raise ValueError("Duplicated input CSV variable names")
    for col in data:
        data[col] = data[col].str.strip()
    return data


def pole_schema():
    pole = pd.read_csv(BASE, dtype=str, keep_default_na=False)
    if "variable" not in pole.columns or "L" not in pole.columns or "R" not in pole.columns:
        raise ValueError(f"Malformed baseline pole {BASE}")
    vars_ = list(pole["variable"]) + list(EXTRA)
    if len(vars_) != 42 or len(set(vars_)) != 42:
        raise AssertionError(f"Expected exactly 42 unique fixed variables, got {len(vars_)}")
    baseline = {r["variable"]: {"L": r["L"], "R": r["R"]}
                for r in pole.to_dict("records")}
    return vars_, baseline


def split_hash(index, seed, holdout_fraction):
    """Stable development/evaluation split; independent of political responses."""
    h = hashlib.sha256(f"2018:{seed}:{index}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64 < holdout_fraction


def split_frame(data, seed=2018, holdout_fraction=.25):
    flags = [split_hash(i, seed, holdout_fraction) for i in range(len(data))]
    development = data.loc[[not f for f in flags]].reset_index(drop=True)
    holdout = data.loc[flags].reset_index(drop=True)
    return development, holdout


def weights(data, column="auto"):
    """Use genuine numeric design weights only; reject symbolic LSM bins."""
    if column == "none":
        return np.ones(len(data)), {"column": None, "weighted": False, "reason": "explicit_unweighted"}
    if column == "auto":
        for candidate in ("wtssall", "wtssnr", "wtss", "weight"):
            if candidate in data:
                values = pd.to_numeric(data[candidate].replace("", np.nan), errors="coerce")
                if (values.notna().sum() >= .95 * len(data) and
                        (values.dropna() > 0).all()):
                    return values.to_numpy(dtype=float), {
                        "column": candidate, "weighted": True}
        return np.ones(len(data)), {
            "column": None, "weighted": False,
            "reason": "No valid numeric survey weight (LSM wave may encode weights symbolically)"}
    if column not in data:
        raise ValueError(f"Requested weight column {column!r} unavailable")
    numeric = pd.to_numeric(data[column].replace("", np.nan), errors="coerce")
    if numeric.isna().any() or (numeric <= 0).any():
        raise ValueError(f"{column} contains nonnumeric, zero or negative weights")
    return numeric.to_numpy(dtype=float), {"column": column, "weighted": True}


def response_counts(data, var, group_var, membership, w):
    grouped = {}
    for side, allowed in membership.items():
        mask = data[group_var].isin(allowed).to_numpy() if group_var in data else np.zeros(len(data), bool)
        values = data[var].to_numpy()
        acceptable = mask & (~np.isin(np.char.lower(values.astype(str)), list(MISSING)))
        valid_values = values[acceptable]
        valid_weights = w[acceptable]
        counts = {}
        raw_counts = {}
        for value, weight in zip(valid_values, valid_weights):
            counts[value] = counts.get(value, 0.) + float(weight)
            raw_counts[value] = raw_counts.get(value, 0) + 1
        total = sum(counts.values())
        grouped[side] = {
            "counts": counts,
            "raw_counts": raw_counts,
            "probs": {v: c/total for v, c in counts.items()} if total else {},
            "n_answered": len(valid_values),
            "n_in_group": int(mask.sum()),
            "sum_weights": total}
    return grouped


def choose_pair(grouped, baseline=None, minimum_count=3, min_prob=.05,
                contrast_bonus=.5):
    """Choose two different empirically supported, fairly representative answers.

    Maximize P_L(l)+P_R(r) + bonus[(P_L(l)-P_R(l))+(P_R(r)-P_L(r))]
    over valid distinct responses. The association bonus is declared BEFORE
    examining CM/WF sign or validation outcomes; never select items from
    significance/ideological movement.

    If inadequate data, retain the published baseline answers and report
    fallback explicitly, rather than reducing the number of variables.
    """
    left, right = grouped["L"], grouped["R"]
    L, R = left["probs"], right["probs"]
    labels = sorted(set(L) | set(R))
    def mode(probs):
        return sorted(probs, key=lambda x: (-probs[x], x))[0] if probs else None
    lm, rm = mode(L), mode(R)
    viableL = [v for v in labels
               if left["raw_counts"].get(v, 0) >= minimum_count and L.get(v, 0.) >= min_prob]
    viableR = [v for v in labels
               if right["raw_counts"].get(v, 0) >= minimum_count and R.get(v, 0.) >= min_prob]
    options = []
    for l in viableL:
        for r in viableR:
            if l == r:
                continue
            contrast = L.get(l, 0.)-R.get(l, 0.) + R.get(r, 0.)-L.get(r, 0.)
            merit = L.get(l, 0.)+R.get(r, 0.)+contrast_bonus*contrast
            options.append((merit, l, r, contrast))
    if options:
        _, selectedL, selectedR, contrast = sorted(
            options, key=lambda entry: (-entry[0], entry[1], entry[2]))[0]
        provenance = "distinct_modes" if (selectedL == lm and selectedR == rm) else "contrast_with_modal_conflict"
    elif baseline and baseline["L"] != baseline["R"]:
        selectedL, selectedR = baseline["L"], baseline["R"]
        contrast = L.get(selectedL, 0.)-R.get(selectedL, 0.) + R.get(selectedR, 0.)-L.get(selectedR, 0.)
        provenance = "insufficient_observations_baseline_fallback"
    else:
        raise RuntimeError("Cannot form distinct responses and no legal fixed baseline available")
    return {
        "L": selectedL, "R": selectedR, "method": provenance,
        "L_mode": lm, "R_mode": rm,
        "L_group_n": left["n_in_group"], "R_group_n": right["n_in_group"],
        "L_answered": left["n_answered"], "R_answered": right["n_answered"],
        "L_selected_group_prob": L.get(selectedL, 0.),
        "R_selected_group_prob": R.get(selectedR, 0.),
        "L_selected_count": left["raw_counts"].get(selectedL, 0),
        "R_selected_count": right["raw_counts"].get(selectedR, 0),
        "contrast": float(contrast)}


def evaluate_responses(data, w, decisions, group_var, membership, name):
    result = []
    for row in decisions:
        var = row["variable"]
        gr = response_counts(data, var, group_var, membership, w)
        L, R = gr["L"]["probs"], gr["R"]["probs"]
        l, r = row["L"], row["R"]
        contrast = L.get(l, 0.)-R.get(l, 0.) + R.get(r, 0.)-L.get(r, 0.)
        result.append({
            "variable": var, "validation_strata": name,
            "n_L": gr["L"]["n_answered"], "n_R": gr["R"]["n_answered"],
            "L_rate_of_L_answer": L.get(l, 0.),
            "R_rate_of_L_answer": R.get(l, 0.),
            "L_rate_of_R_answer": L.get(r, 0.),
            "R_rate_of_R_answer": R.get(r, 0.),
            "association": contrast,
            "aligned": bool(contrast > 1e-12) if min(
                gr["L"]["n_answered"], gr["R"]["n_answered"]) >= 5 else None})
    return result


def native_check(poles, out, heldout, *, no_download=False,
                 max_rows=200, seed=2018):
    """Evaluate model geometry and independently held-out RESPONDENT ROWS.

    Exclude polviews/partyid from each respondent's conditioning vector to
    avoid tautologically predicting those very two validation variables.
    """
    from audit import ANCHOR_ORDER
    model_path = ensure_model("gss/gss_2018", None, download=not no_download)
    world = World(str(model_path), str(canonical_map("gss/gss_2018")),
                  str(DEFAULT_POLES), str(out / "native_cache"))
    L = {p["variable"]: p["L"] for p in poles}
    R = {p["variable"]: p["R"] for p in poles}
    invalid = []
    for variable in L:
        possible = world.ctx.possible.get(variable, [])
        if L[variable] not in possible or R[variable] not in possible:
            invalid.append({"variable": variable, "L": L[variable],
                            "R": R[variable], "allowed": possible})
    if invalid:
        (out / "invalid_native_labels.json").write_text(json.dumps(invalid, indent=2))
        raise ValueError(f"{len(invalid)} proposed responses unsupported by native model; "
                         "see invalid_native_labels.json")
    baseline = (dict(world.g.left_map), dict(world.g.right_map))
    variants = {"respondent_derived42": (L, R), "baseline_v2_38": baseline}
    states, dropped = get_states(world)
    summary = []
    for name, (left, right) in variants.items():
        empty = model_index(world, {}, left, right)["index"]
        for persona, state in states.items():
            measure = model_index(world, state, left, right)["index"]
            summary.append({"variant": name, "persona": persona,
                            "index": measure, "relative_to_empty": measure-empty})
        for variable in ("polviews", "partyid"):
            ordered = ANCHOR_ORDER[variable]
            rows = [(j, value) for j, value in enumerate(ordered)
                    if value in world.ctx.possible.get(variable, [])]
            values = [model_index(world, {variable: v}, left, right)["index"]
                      for _, v in rows]
            pairs = [values[j]-values[i] for i in range(len(values)) for j in range(i+1,len(values))]
            summary.append({"variant": name, "persona": f"{variable}_ordered",
                            "comparisons": len(pairs),
                            "concordant": sum(x > 1e-10 for x in pairs),
                            "discordant": sum(x < -1e-10 for x in pairs),
                            "ties": sum(abs(x) <= 1e-10 for x in pairs)})
    # Separate respondent rows used only in evaluation, not in response-pair selection.
    # Keep conditioned variables sparse and avoid partyid/polviews leakage.
    selected = heldout.sample(n=min(max_rows, len(heldout)), random_state=seed)
    outcomes = []
    for i, (_, row) in enumerate(selected.iterrows()):
        raw = {k: str(v) for k, v in row.items()
               if k not in BAND and v not in MISSING and k in world.ctx.idx_map}
        valid, dropped = world.valid(raw)
        record = {"eval_row": i, "partyid": row.get("partyid",""),
                  "polviews": row.get("polviews",""), "n_valid": len(valid)}
        for name, (left,right) in variants.items():
            record[name] = model_index(world, valid, left, right)["index"]
        outcomes.append(record)
    pd.DataFrame(outcomes).to_csv(out / "native_respondent_holdout_indices.csv", index=False)
    measured = []
    respondent_table = pd.DataFrame(outcomes)
    def auc_rank(scoreL, scoreR):
        # Mann-Whitney AUC with half-credit for tied scores.
        # AUC = P(right-score > left-score), independent of calibration origin.
        if len(scoreL) == 0 or len(scoreR) == 0:
            return None
        a = np.asarray(scoreL)[:, None]
        b = np.asarray(scoreR)[None, :]
        return float(np.mean((b > a) + .5*(b == a)))
    for group_key, members in (("partyid", GROUPS), ("polviews", POLVIEWS)):
        for name in variants:
            left_values = respondent_table.loc[
                respondent_table[group_key].isin(members["L"]), name].to_numpy(float)
            right_values = respondent_table.loc[
                respondent_table[group_key].isin(members["R"]), name].to_numpy(float)
            measured.append({
                "variant": name, "heldout_label": group_key,
                "n_L": len(left_values), "n_R": len(right_values),
                "mean_I_L": float(np.mean(left_values)) if len(left_values) else None,
                "mean_I_R": float(np.mean(right_values)) if len(right_values) else None,
                "mean_difference_R_minus_L": (float(np.mean(right_values)-np.mean(left_values))
                                              if len(left_values) and len(right_values) else None),
                "auc_right_above_left": auc_rank(left_values, right_values)})
    pd.DataFrame(measured).to_csv(out / "native_holdout_metrics.csv", index=False)
    (out / "native_summary.json").write_text(json.dumps(
        {"personas": summary, "n_holdout_rows": len(outcomes),
         "heldout_respondent_metrics": measured,
         "excluded_from_conditioning": sorted(BAND),
         "source": "empirical respondent rows, held out of pole construction only",
         "note": "LSM itself was trained previously; not independent of model training"},
        indent=2))
    return {"persona_geometry": summary, "heldout_respondent_metrics": measured}


def run(args):
    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    vars_, baseline = pole_schema()
    data = read_rows(args.csv.expanduser())
    if any(v not in data.columns for v in vars_) or any(v not in data for v in BAND):
        raise ValueError(
            "Input lacks required GSS 2018 variables: " +
            str(sorted(set(vars_ + list(BAND)) - set(data.columns))))
    dev, held = split_frame(data, args.seed, args.holdout_fraction)
    wdev, weight_meta = weights(dev, args.weights)
    whold, _ = weights(held, args.weights if args.weights != "auto" else
                        (weight_meta["column"] or "none"))
    decisions, profiles = [], []
    for var in vars_:
        grouped = response_counts(dev, var, "partyid", GROUPS, wdev)
        chosen = choose_pair(grouped, baseline.get(var),
                             args.minimum_count, args.min_prob, args.contrast_bonus)
        decisions.append({"variable": var, **chosen})
        for side in ("L","R"):
            for answer, p in grouped[side]["probs"].items():
                profiles.append({"variable": var, "party_group": side,
                                 "response": answer, "probability": p,
                                 "n": grouped[side]["raw_counts"][answer],
                                 "n_answered": grouped[side]["n_answered"]})
    if len(decisions) != 42 or any(d["L"] == d["R"] for d in decisions):
        raise AssertionError("All 42 paired pole items must remain distinct")
    polefile = out / "gss_2018_empirical_partyid_42_poles.csv"
    pd.DataFrame([{"variable": d["variable"], "R": d["R"], "L": d["L"]}
                  for d in decisions]).to_csv(polefile, index=False)
    pd.DataFrame(decisions).to_csv(out / "construction_audit.csv", index=False)
    pd.DataFrame(profiles).to_csv(out / "empirical_partyid_marginals.csv", index=False)
    eval_rows = (
        evaluate_responses(held, whold, decisions, "partyid", GROUPS, "partyid_heldout_rows")
        + evaluate_responses(held, whold, decisions, "polviews", POLVIEWS, "polviews_heldout_rows")
    )
    pd.DataFrame(eval_rows).to_csv(out / "heldout_associations.csv", index=False)
    audit = pd.DataFrame(eval_rows)
    def aggregate(name):
        matches = audit[audit.validation_strata == name]
        useful = matches[matches["aligned"].notna()]
        return {
            "n_evaluated": len(matches),
            "n_with_sufficient_stratum_data": len(useful),
            "n_positive_associations": int((useful.association > 1e-12).sum()),
            "n_negative_associations": int((useful.association < -1e-12).sum()),
            "n_ties": int((useful.association.abs() <= 1e-12).sum()),
            "mean_association": float(useful.association.mean())}
    result = {
        "source_type": "Observed respondent-level GSS 2018 CSV, not LSM-generated samples",
        "input_file": str(args.csv),
        "input_sha256": sha256(args.csv),
        "n_rows": len(data), "n_development_rows": len(dev),
        "n_heldout_rows": len(held), "seed": args.seed,
        "holdout_fraction": args.holdout_fraction,
        "baseline_2018_variables": 38, "extra_predeclared": list(EXTRA),
        "n_fixed_pole_variables": len(vars_),
        "group_definition": {k: sorted(v) for k,v in GROUPS.items()},
        "validation_group_definition": {k: sorted(v) for k,v in POLVIEWS.items()},
        "weights": weight_meta, "minimum_count": args.minimum_count,
        "min_prob": args.min_prob, "contrast_bonus": args.contrast_bonus,
        "methods": pd.Series([d["method"] for d in decisions]).value_counts().to_dict(),
        "evaluations": {k: aggregate(k) for k in
                        ("partyid_heldout_rows", "polviews_heldout_rows")},
        "limitations": [
            "The native LSM may have been trained on all 2018 respondent rows;",
            "Holdout rows are independent of pole construction but not necessarily LSM training;",
            "Original LSM GSS CSV might recode weights as symbolic values; unweighted results are disclosed;",
            "A hard marginal-response pole is not a representative joint respondent;",
            "No variables were selected based on held-out ideological differences.",
        ],
    }
    if args.native_eval:
        result["native_evaluation"] = native_check(
            decisions, out, held, no_download=args.no_download,
            max_rows=args.max_native_respondents, seed=args.seed)
    (out / "summary.json").write_text(json.dumps(result, indent=2, default=str))
    lines = ["# Respondent-stratified GSS 2018 ideology pole audit", "",
             f"**Source:** {args.csv}", "",
             f"**Rows:** {len(data)}; development={len(dev)}; evaluation={len(held)}.",
             f"**Variables:** {len(vars_)} fixed (original 38 plus four predefined extras).",
             f"**Survey weights:** {weight_meta}.",
             f"**Question assignments:** {result['methods']}.",
             "", "## Held-out descriptive associations", "",
             "| Test strata | n aligned | n opposite | n tied | mean association |",
             "|---|---:|---:|---:|---:|"]
    for k, v in result["evaluations"].items():
        lines.append(
            f"| {k} | {v['n_positive_associations']} | "
            f"{v['n_negative_associations']} | {v['n_ties']} | "
            f"{v['mean_association']:+.4f} |")
    lines += ["", "These associations do not validate political persuasion.",
              "Response-pair construction uses only development respondents",
              "stratified by partyid. Polviews on heldout respondent rows",
              "is separately reported; no question variable was dropped.",
              "", "See construction_audit.csv for modal conflicts, small counts,",
              "and fallback items. See native_summary.json when --native-eval",
              "is used. Production pole files were not changed.", ""]
    (out / "REPORT.md").write_text("\n".join(lines))
    print("\n".join(lines), flush=True)
    print("Candidate:", polefile, flush=True)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", type=Path, default=default_csv())
    p.add_argument("--out", type=Path,
                   default=Path(__file__).parent / "results" / "respondent_stratified_full")
    p.add_argument("--seed", type=int, default=2018)
    p.add_argument("--holdout-fraction", type=float, default=.25)
    p.add_argument("--weights", default="auto",
                   help="auto | none | exact numeric weight column")
    p.add_argument("--minimum-count", type=int, default=3)
    p.add_argument("--min-prob", type=float, default=.05)
    p.add_argument("--contrast-bonus", type=float, default=.5)
    p.add_argument("--native-eval", action="store_true",
                   help="add native 2018 geometric and respondent-row index evaluation")
    p.add_argument("--max-native-respondents", type=int, default=200)
    p.add_argument("--no-download", action="store_true")
    args = p.parse_args(argv)
    if not 0 < args.holdout_fraction < 1:
        p.error("holdout fraction must be within (0,1)")
    if args.minimum_count < 1 or not 0 <= args.min_prob <= 1:
        p.error("invalid minimum-count or min-prob")
    if args.contrast_bonus < 0 or args.max_native_respondents < 1:
        p.error("contrast-bonus must be >=0, native respondents >=1")
    run(args)


if __name__ == "__main__":
    main()
