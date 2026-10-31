#!/usr/bin/env python3
"""Decompose DTAG human-study index movement by selected survey question.

Input: PRIVATE export_dtag_analysis_data.py CSVs (sessions, steps, questions,
assignments) plus public GSS 2024 map. No new model inference, LLM calls,
cloud access, or participant text. Outputs ONLY to a PRIVATE directory outside
this repository. Never commit the output or private input CSVs.

The additive quantity is the observed per-question increment I_t-I_(t-1),
not a causal item effect. Multi-variable mappings cannot be uniquely
partitioned into individual effects without rerunning the LSM.

One planned exploratory hypothesis: among initially-Right participants
assigned Left push, spending/program questions account for a larger share of
positive leftward step increments than among initially-Left Left-push users.
An exact participant-label permutation test is reported (n=4 vs n=17 in
current completed calibrated cohorts); interpretation is descriptive.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from statistics import fmean

CALIBRATED = {
    "prolific-v3-human-opinions-2026-10",
    "prolific-v3-left-followup-2026-10",
    "prolific-v3-right-followup-2026-10",
}
EPS = 1e-10
N = 20
# Predeclared category: public-spending and government-program questions.
# 'nat*' is the GSS national-spending item family; the non-nat regex
# identifies additional question-map wording about spending/programs.
SPENDING_TEXT = re.compile(
    r"\b(spend(?:ing)?|welfare|social security|government (?:aid|assistance|"
    r"program|benefit|support)|public (?:aid|assistance|benefit)|"
    r"medicare|medicaid|food stamps|unemployment benefits)\b", re.I
)


def read_csv(path: Path):
    if not path.is_file():
        raise ValueError(f"Missing required private/exported file: {path}")
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def number(x, label):
    try:
        y = float(x)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid {label}: {x!r}") from None
    if not math.isfinite(y):
        raise ValueError(f"Nonfinite {label}: {x!r}")
    return y


def truth(x):
    return str(x).strip().lower() in ("true", "yes", "1")


def put_csv(path, rows, fields):
    with path.open("x", encoding="utf-8", newline="") as f:
        os.chmod(path, 0o600)
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def mean(values):
    return fmean(values) if values else None


def category(variable, mapping):
    var = (variable or "").strip().lower()
    if not var:
        return "unmapped_or_missing"
    # Map text is a question about allocation, not respondent party label.
    text = mapping.get(var, "")
    return "spending_program" if var.startswith("nat") or SPENDING_TEXT.search(text) else "other"


def gss_map(path):
    rows = read_csv(path)
    if not rows or not {"variable", "question_text"}.issubset(rows[0]):
        raise ValueError("Expected GSS map variable,question_text columns")
    return {r["variable"].strip().lower(): (r.get("question_text_filled") or
             r["question_text"]) for r in rows if r.get("variable")}


def classify(i0):
    if i0 < -EPS:
        return "initially_left"
    if i0 > EPS:
        return "initially_right"
    return "initially_center"


def load(analysis_dir, mapping, expected=71):
    sessions = read_csv(analysis_dir / "sessions.csv")
    steps = read_csv(analysis_dir / "steps.csv")
    questions = read_csv(analysis_dir / "questions.csv")
    assignments = read_csv(analysis_dir / "assignments.csv")
    eligible = {}
    for row in sessions:
        if (row.get("dtag_study_id") not in CALIBRATED or
                row.get("protocol") != "six_question_calibration" or
                not truth(row.get("complete_20_archive"))):
            continue
        uid = row["session_uid"]
        if uid in eligible:
            raise ValueError("Duplicate completed calibrated session")
        if row["policy"] not in ("left", "right", "neutral", "random"):
            raise ValueError("Unrecognized calibrated policy")
        eligible[uid] = row
    if expected is not None and len(eligible) != expected:
        raise ValueError(f"Expected {expected} complete calibrated sessions, got {len(eligible)}")

    step_by_uid = defaultdict(dict)
    for row in steps:
        uid = row.get("session_uid")
        if uid not in eligible:
            continue
        t = int(row["step"])
        if t in step_by_uid[uid]:
            raise ValueError("Duplicate step in archived session")
        step_by_uid[uid][t] = row

    q_by_key = {}
    for row in questions:
        if row.get("session_uid") not in eligible or row.get("phase") != "intervention":
            continue
        t = int(row["adaptive_step"])
        key = (row["session_uid"], t)
        if key in q_by_key:
            raise ValueError("Duplicate intervention question at same adaptive step")
        q_by_key[key] = row

    assignments_by_question = defaultdict(list)
    for row in assignments:
        if row.get("session_uid") in eligible and row.get("phase") == "intervention":
            assignments_by_question[(row["session_uid"], row["question_uid"])].append(row)

    participants, events = [], []
    for uid, session in sorted(eligible.items()):
        idx = step_by_uid.get(uid, {})
        if set(idx) != set(range(N + 1)):
            raise ValueError("Complete session lacks exactly steps 0..20")
        start = number(idx[0]["index"], "baseline index")
        end = number(idx[N]["index"], "final index")
        for key, value in (("baseline_index", start), ("final_archived_index", end)):
            if not math.isclose(number(session[key], key), value, rel_tol=0, abs_tol=1e-7):
                raise ValueError(f"Private export inconsistency: {key}")
        policy = session["policy"]
        direction = -1 if policy == "left" else 1 if policy == "right" else 0
        phenotype = classify(start)
        initial = len(events)
        for t in range(1, N + 1):
            old = number(idx[t - 1]["index"], "index previous")
            curr = number(idx[t]["index"], "index current")
            q = q_by_key.get((uid, t))
            if q is None:
                raise ValueError("Missing question for archived adaptive step")
            if idx[t].get("source_question_uid") != q.get("question_uid"):
                raise ValueError("Question UID does not match archived step")
            for k, value in (("index_before", old), ("index_after", curr)):
                if q.get(k) not in ("", None) and not math.isclose(
                        number(q[k],k), value, rel_tol=0, abs_tol=1e-6):
                    raise ValueError(f"Question {k} inconsistent with step trajectory")
            target = (q.get("target_variable") or "").strip().lower()
            if not target:
                raise ValueError("Adaptive question is missing target_variable")
            items = assignments_by_question.get((uid, q["question_uid"]), [])
            reported = int(q.get("accepted_assignment_count") or 0)
            legacy = (reported == 0 and len(items) == 1 and
                      items[0].get("assignment_type") == "legacy_single_value")
            if reported != len(items) and not legacy:
                raise ValueError("Accepted-assignment count does not match private export")
            mapped_values = sorted({((a.get("mapped_variable") or "").strip().lower(),
                                    (a.get("native_value") or "").strip().lower())
                                    for a in items if a.get("mapped_variable")})
            mapped = sorted({v for v,_ in mapped_values})
            # The prompted target is the primary unit of attribution. Mapped
            # variables are associations only, because one question can set >1.
            cat = category(target, mapping)
            associated_spending = any(category(v, mapping) == "spending_program" for v in mapped)
            delta = curr - old
            signed = direction * delta
            events.append(dict(session_uid=uid, policy=policy, phenotype=phenotype,
                               step=t, target=target, target_category=cat,
                               mapped_variables=mapped, mapped_values=mapped_values,
                               any_mapped_spending=associated_spending,
                               n_assignments=len(items), delta=delta,
                               signed=signed, positive_gain=max(0.0, signed),
                               negative_gain=max(0.0, -signed)))
        if len(events) - initial != N:
            raise ValueError("Expected exactly twenty events")
        telescoped = sum(r["delta"] for r in events[initial:])
        if not math.isclose(telescoped, end - start, rel_tol=0, abs_tol=1e-8):
            raise ValueError("Per-question increments do not telescope to endpoint")
        for evt in events[initial:]:
            evt["success"] = direction * (end - start) > EPS if direction else None
            evt["group"] = evt["policy"] + "/" + evt["phenotype"] + "/" + (
                "success" if evt["success"] else "nonresponse" if direction else "control")
        subset = events[initial:]
        gain = sum(r["positive_gain"] for r in subset)
        spend_gain = sum(r["positive_gain"] for r in subset
                         if r["target_category"] == "spending_program")
        participants.append(dict(uid=uid, policy=policy, phenotype=phenotype,
                                 study=session["dtag_study_id"], signed_total=direction*(end-start),
                                 spending_share_positive=(spend_gain/gain if gain > EPS else 0.0),
                                 spending_exposure=sum(r["target_category"] == "spending_program"
                                                       for r in subset)/N,
                                 positive_total=gain,
                                 spending_signed=sum(r["signed"] for r in subset
                                                     if r["target_category"] == "spending_program"),
                                 success=direction*(end-start)>EPS if direction else None))
    return participants, events


def summarize(events, key, mapping):
    grouped = defaultdict(list)
    for r in events:
        grouped[key(r)].append(r)
    rows = []
    for group, records in sorted(grouped.items()):
        people = len({r["session_uid"] for r in records})
        rows.append(dict(zip(mapping, group), n_sessions=people, n_questions=len(records),
                         mean_signed_per_question=mean([r["signed"] for r in records]),
                         sum_signed=round(sum(r["signed"] for r in records), 12),
                         sum_positive=round(sum(r["positive_gain"] for r in records), 12),
                         sum_negative=round(sum(r["negative_gain"] for r in records), 12),
                         mean_raw_delta=mean([r["delta"] for r in records]),
                         multi_assignment_steps=sum(r["n_assignments"]>1 for r in records),
                         any_mapped_spending_steps=sum(r["any_mapped_spending"] for r in records)))
    return rows


def exact_permutation(p, field, max_combinations=500_000):
    selected=[r for r in p if r["policy"] == "left" and
              r["phenotype"] in ("initially_left", "initially_right")]
    group=[r[field] for r in selected if r["phenotype"] == "initially_right"]
    rest=[r[field] for r in selected if r["phenotype"] == "initially_left"]
    if not group or not rest:
        return {"n_initially_right":len(group), "n_initially_left":len(rest),
                "difference_in_means":None,"one_sided_p":None,"two_sided_p":None}
    observed = fmean(group) - fmean(rest)
    vals = group + rest
    n, k = len(vals), len(group)
    total = math.comb(n, k)
    if total > max_combinations:
        raise ValueError("Exact permutation test exceeds safety combination cap")
    ge = 0
    ae = 0
    vtot = sum(vals)
    for chosen in combinations(range(n), k):
        s = sum(vals[i] for i in chosen)
        d = s/k - (vtot-s)/(n-k)
        ge += d >= observed - 1e-12
        ae += abs(d) >= abs(observed) - 1e-12
    return {"n_initially_right":k,"n_initially_left":n-k,
            "mean_initially_right":fmean(group),"mean_initially_left":fmean(rest),
            "difference_in_means":observed,"one_sided_p":ge/total,
            "two_sided_p":ae/total,"number_of_permutations":total}


def run(analysis_dir, map_file, out, expected=71):
    root = Path(__file__).resolve().parents[2]
    analysis_dir = analysis_dir.expanduser().resolve()
    out = out.expanduser().resolve()
    if out.is_relative_to(root):
        raise ValueError("PRIVATE output must be outside the public DTAG checkout")
    if out.exists():
        raise ValueError("Output path already exists; use a new private directory")
    mapping = gss_map(map_file.expanduser())
    participants, events = load(analysis_dir, mapping, expected)
    category_rows=summarize(events,lambda r:(r["policy"],r["phenotype"],r["group"],r["target_category"]),
                            ("policy","initial_phenotype","subgroup","target_category"))
    question_rows=summarize(events,lambda r:(r["policy"],r["phenotype"],r["target"]),
                            ("policy","initial_phenotype","target_variable"))
    mapped=defaultdict(lambda:Counter())
    for r in events:
        for v,value in r["mapped_values"]:
            # A mapping can participate in the same step as other mappings.
            # Its associated delta cannot be interpreted as variable causality.
            key=(r["policy"],r["phenotype"],v,value)
            mapped[key]["associated_question_count"] += 1
            if r["signed"] > EPS:
                mapped[key]["associated_positive_steps"] += 1
            mapped[key]["associated_signed_step_sum"] += r["signed"]
    mapped_rows=[dict(policy=p,initial_phenotype=phen,mapped_variable=v,
                      mapped_native_value=value,**dict(d))
                 for (p,phen,v,value),d in sorted(mapped.items())]
    out.mkdir(parents=True,mode=0o700)
    os.chmod(out,0o700)
    put_csv(out/"question_categories_PRIVATE.csv",category_rows,
            ("policy","initial_phenotype","subgroup","target_category", "n_sessions",
             "n_questions","mean_signed_per_question","sum_signed","sum_positive",
             "sum_negative","mean_raw_delta","multi_assignment_steps","any_mapped_spending_steps"))
    put_csv(out/"target_questions_PRIVATE.csv",question_rows,
            ("policy","initial_phenotype","target_variable","n_sessions",
             "n_questions","mean_signed_per_question","sum_signed","sum_positive",
             "sum_negative","mean_raw_delta","multi_assignment_steps","any_mapped_spending_steps"))
    put_csv(out/"mapped_answers_PRIVATE.csv",mapped_rows,
            ("policy","initial_phenotype","mapped_variable","mapped_native_value",
             "associated_question_count","associated_positive_steps",
             "associated_signed_step_sum"))
    tests={
        "spending_share_of_positive_leftward_increments":exact_permutation(
            participants,"spending_share_positive"),
        "spending_question_exposure_share":exact_permutation(
            participants,"spending_exposure"),
    }
    summary={
        "schema_version":1,
        "method":"Question-level additive observed index increments; mapped variables are nonadditive associations",
        "calibrated_complete_n":len(participants),
        "by_policy_baseline":dict(sorted(Counter((r["policy"]+"/"+r["phenotype"])
                          for r in participants).items())),
        "tests":tests,
        "spending_definition":"target variable begins 'nat' OR GSS map question wording matches fixed spending/program keyword list",
        "caveats":["Exploratory association, not causal effects of individual items.",
                   "Assignment-to-index increments are joint for multi-variable answers.",
                   "n initially-Right Left-push is small; permutation test conditions on observed cohort.",
                   "When no positive signed steps occur, positive-share is defined as 0."],
    }
    with (out/"summary_PRIVATE.json").open("x",encoding="utf-8") as f:
        os.chmod(out/"summary_PRIVATE.json",0o600)
        json.dump(summary,f,indent=2,sort_keys=True)
        f.write("\n")
    print("Archived calibrated completions:",len(participants))
    print("Policy/baseline:",summary["by_policy_baseline"])
    for name,result in tests.items():
        print(name, json.dumps(result,sort_keys=True))
    print("PRIVATE analysis outputs:",out)
    print("No participant-level records, raw responses, or Prolific identifiers were exported.")
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--analysis-dir",type=Path,required=True)
    p.add_argument("--gss-map",type=Path,default=Path("maps/gss/gss_2024_map.csv"))
    p.add_argument("--out",type=Path,required=True,help="NEW PRIVATE folder outside repository")
    p.add_argument("--expect-complete",type=int,default=71)
    a=p.parse_args()
    run(a.analysis_dir,a.gss_map,a.out,a.expect_complete)


if __name__ == "__main__":
    main()
