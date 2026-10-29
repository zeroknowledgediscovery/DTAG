#!/usr/bin/env python3
"""Early phenotype prediction from ALL DTAG Left/Right push studies.

Use sign(LSM index after adaptive question 3 or 4) as the *initial phenotype*.
Score actual push success from question k to question 20, NOT from the initial
calibration index or the common empty-state index. Includes original randomized
four-arm study, fixed Left/Right, and no-calibration Left/Right studies.

Read-only Firestore REST; never read participant prose or Prolific IDs.
Optional CSV output contains only aggregate counts and accuracy metrics.
No LSM reruns, experiment changes, or external ML dependencies except numpy.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean
from urllib.parse import quote

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_left_live import token, list_docs, fields, numeric

STUDIES = {
    "prolific-v3-human-opinions-2026-10": (6, "calibrated"),
    "prolific-v3-left-followup-2026-10": (6, "calibrated"),
    "prolific-v3-right-followup-2026-10": (6, "calibrated"),
    "dtag-v3-nocal-left-2026-10": (0, "no-calibration"),
    "dtag-v3-nocal-right-2026-10": (0, "no-calibration"),
}
EPS = 1e-10
STEPS = 20


def lean(v):
    return "right" if v > EPS else "left" if v < -EPS else "center"


def success(policy, delta):
    return delta > EPS if policy == "right" else delta < -EPS


def example(trajectory, policy, regime, k):
    assert len(trajectory) == STEPS + 1 and policy in ("left", "right")
    index = trajectory[k]
    later = trajectory[STEPS] - index
    won = success(policy, later)
    return dict(policy=policy, regime=regime, phenotype=lean(index),
                index_at_k=index, within_early_delta=index-trajectory[1],
                later_delta=later, success=won,
                label=policy + ("_success" if won else "_fail"))


def url(project, database, study):
    return ("https://firestore.googleapis.com/v1/projects/"
            + quote(project, safe="") + "/databases/" + quote(database, safe="()")
            + "/documents/studies/" + quote(study, safe="") + "/sessions")


def retrieve(project, database, credential, studies=STUDIES):
    participants, counts = [], Counter()
    for study, (baseline_questions, regime) in studies.items():
        root = url(project, database, study)
        docs = list_docs(root, credential, (
            "phase", "policy", "consent_accepted", "next_step", "attention_completed",
            "state.baseline_index", "state.current_index"))
        counts[(study, "sessions")] += len(docs)
        for doc in docs:
            header = fields(doc)
            policy = header.get("policy")
            if header.get("consent_accepted") is not True or policy not in ("left", "right"):
                continue
            counts[(study, "eligible_" + policy)] += 1
            state = header.get("state") or {}
            baseline = numeric(state.get("baseline_index"))
            current = numeric(state.get("current_index"))
            if baseline is None or current is None:
                counts[(study, "no_state")] += 1
                continue
            answered = (int(header.get("next_step") or 0)
                        - int(header.get("attention_completed") or 0)
                        - baseline_questions)
            if answered < STEPS:
                counts[(study, "partial_" + policy)] += 1
                continue
            if answered != STEPS:
                counts[(study, "unexpected_progress")] += 1
                continue
            sid = doc["name"].rsplit("/", 1)[-1]
            qs = list_docs(root + "/" + quote(sid, safe="") + "/questions",
                           credential, ("phase", "status", "step",
                                        "index_result.index_before",
                                        "index_result.index_after"))
            after, before, bad = {}, {}, False
            for raw in qs:
                q = fields(raw)
                if q.get("phase") != "intervention" or q.get("status") != "answered":
                    continue
                step = q.get("step")
                result = q.get("index_result") or {}
                value = numeric(result.get("index_after"))
                previous = numeric(result.get("index_before"))
                if (not isinstance(step, int) or not 0 <= step < STEPS
                        or value is None or previous is None or step in after):
                    bad = True
                    continue
                after[step], before[step] = value, previous
            if bad or set(after) != set(range(STEPS)):
                counts[(study, "bad_trajectory")] += 1
                continue
            path = [baseline] + [after[i] for i in range(STEPS)]
            if (abs(path[-1]-current) > 1e-7 or any(
                    abs(before[i]-path[i]) > 1e-7 for i in range(STEPS))):
                counts[(study, "broken_index_chain")] += 1
                continue
            participants.append(dict(policy=policy, regime=regime,
                                     study=study, trajectory=path))
            counts[(study, "complete_" + policy)] += 1
    return participants, counts


def wilson(won, total):
    if not total:
        return float("nan"), float("nan")
    z = 1.95996398454
    p = won/total
    denom = 1 + z*z/total
    center = (p+z*z/(2*total))/denom
    margin = z*math.sqrt((p*(1-p)+z*z/(4*total))/total)/denom
    return max(0, center-margin), min(1, center+margin)


def summarize(examples, grouping):
    groups = defaultdict(list)
    for x in examples:
        groups[tuple(x[c] for c in grouping)].append(x)
    answer = []
    for key, group in sorted(groups.items()):
        n = len(group)
        wins = sum(x["success"] for x in group)
        lo, hi = wilson(wins, n)
        answer.append({**dict(zip(grouping, key)), "n": n,
                       "success_count": wins, "success_rate": wins/n,
                       "ci95_low": lo, "ci95_high": hi,
                       "mean_later_delta": fmean(x["later_delta"] for x in group)})
    return answer


def feature(x):
    """Only Q1..Qk indices and assigned arm; never preadaptive index or party."""
    arm = 1.0 if x["policy"] == "right" else -1.0
    index = max(-5.0, min(5.0, x["index_at_k"]/0.10))
    slope = max(-5.0, min(5.0, x["within_early_delta"]/0.10))
    return [1.0, arm, index, arm*index, slope, arm*slope]


def sigmoid(v):
    return 1.0/(1.0+np.exp(-np.clip(v, -40.0, 40.0)))


def fit_logistic(train, lam=4.0):
    """Fixed ridge penalty, fitted on training participants only."""
    x = np.asarray([feature(t) for t in train], dtype=float)
    y = np.asarray([float(t["success"]) for t in train])
    beta = np.zeros(6)
    penalty = np.eye(6)*lam
    penalty[0, 0] = 0
    for _ in range(35):
        probs = sigmoid(x@beta)
        weights = np.maximum(probs*(1-probs), 1e-8)
        hessian = x.T@(x*weights[:, None]) + penalty
        grad = x.T@(probs-y) + penalty@beta
        update = np.linalg.solve(hessian, grad)
        beta -= update
        if np.max(np.abs(update)) < 1e-8:
            break
    return beta


def predict(train, x, method):
    if method == "logistic":
        return float(sigmoid(np.dot(feature(x), fit_logistic(train))))
    subgroup = [r for r in train if r["policy"] == x["policy"]]
    if method == "phenotype":
        subgroup = [r for r in subgroup if r["phenotype"] == x["phenotype"]]
    # Laplace smoothing; never uses the held-out participant's outcome.
    return (1+sum(r["success"] for r in subgroup))/(2+len(subgroup))


def loo(examples, method):
    guesses = []
    for i, x in enumerate(examples):
        p = predict(examples[:i]+examples[i+1:], x, method)
        label = x["policy"] + ("_success" if p >= 0.5 else "_fail")
        guesses.append(dict(policy=x["policy"], actual=x["label"],
                            predicted=label, true=x["success"],
                            guess=p >= 0.5, prob=p))
    return guesses


def accuracy(predictions):
    n = len(predictions)
    tp = sum(p["true"] and p["guess"] for p in predictions)
    tn = sum(not p["true"] and not p["guess"] for p in predictions)
    fp = sum(not p["true"] and p["guess"] for p in predictions)
    fn = sum(p["true"] and not p["guess"] for p in predictions)
    sensitivity = tp/(tp+fn) if tp+fn else float("nan")
    specificity = tn/(tn+fp) if tn+fp else float("nan")
    low, high = wilson(tp+tn, n)
    return dict(n=n, correct=tp+tn, accuracy=(tp+tn)/n,
                accuracy_ci_low=low, accuracy_ci_high=high,
                balanced_accuracy=(sensitivity+specificity)/2,
                brier=fmean((r["prob"]-float(r["true"]))**2 for r in predictions),
                tp=tp, tn=tn, fp=fp, fn=fn)


def write_csv(out, name, rows):
    if not rows:
        return
    with (out/name).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def report(examples, name, k, fit=True):
    print(f"\n{name}: {len(examples)} complete trajectories")
    groups = summarize(examples, ("policy", "phenotype"))
    print("Push  Index sign at Qk   N    Success (95% Wilson CI)    Mean Δ Qk→Q20")
    for r in groups:
        print(f"{r['policy']:5s} {r['phenotype']:12s} {r['n']:4d}  "
              f"{r['success_count']:3d}/{r['n']:<3d} = {r['success_rate']:5.1%} "
              f"[{r['ci95_low']:5.1%}, {r['ci95_high']:5.1%}] "
              f"    {r['mean_later_delta']:+.5f}")
    metrics, conf = [], []
    if len(examples) >= 2 and fit:
        print("Leave-one-out prediction of LEFT_SUCCESS / LEFT_FAIL / RIGHT_SUCCESS / RIGHT_FAIL")
        print("Policy-only baseline vs policy+sign vs early-index regularized logistic:")
        for method in ("policy", "phenotype", "logistic"):
            guesses = loo(examples, method)
            m = accuracy(guesses)
            print(f"  {method:9s}: accuracy {m['correct']}/{m['n']}={m['accuracy']:.1%} "
                  f"[{m['accuracy_ci_low']:.1%},{m['accuracy_ci_high']:.1%}]; "
                  f"balanced={m['balanced_accuracy']:.1%}; Brier={m['brier']:.3f}")
            metrics.append(dict(sample=name, k=k, method=method, **m))
            matrix = Counter((x["actual"], x["predicted"]) for x in guesses)
            for label in ("left_success", "left_fail", "right_success", "right_fail"):
                total = sum(c for (a,b),c in matrix.items() if a == label)
                correct = matrix[(label,label)]
                print(f"    {label:13s} correctly predicted: {correct}/{total}")
            conf.extend(dict(sample=name, k=k, method=method, actual=a, predicted=b, n=n)
                        for (a,b),n in sorted(matrix.items()))
    return groups, metrics, conf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="pkcsaas-01")
    parser.add_argument("--database", default="dtag-human-pilot")
    parser.add_argument("--study", action="append", help="Restrict to one or more listed studies")
    parser.add_argument("--horizons", default="3,4")
    parser.add_argument("--out", type=Path, help="Private output directory; aggregates only")
    args = parser.parse_args()
    try:
        horizons = sorted({int(x) for x in args.horizons.split(",")})
    except ValueError:
        parser.error("--horizons needs comma-separated integer question numbers")
    if not horizons or any(not 1 <= k < STEPS for k in horizons):
        parser.error("horizons must be 1..19")
    studies = STUDIES
    if args.study:
        unknown = set(args.study)-set(STUDIES)
        if unknown:
            parser.error("unknown study ID: "+", ".join(sorted(unknown)))
        studies = {s: STUDIES[s] for s in args.study}
    credential = token()
    participants, counts = retrieve(args.project, args.database, credential, studies)
    print("ALL fixed/directional DTAG arms; model-inferred ideology index")
    print("Early phenotype = sign(index after Qk); endpoint = sign(index at Q20 - index at Qk)")
    print("No pre-adaptive calibration index or Prolific party used as predictor.")
    for study in studies:
        print(study, {k:v for (s,k),v in counts.items() if s == study})
    print("Valid 20-answer trajectories:", len(participants))
    if not participants:
        return
    output, scores, matrices = [], [], []
    for k in horizons:
        print(f"\n================ AFTER ADAPTIVE QUESTION {k} ================")
        examples = [example(p["trajectory"], p["policy"], p["regime"], k)
                    for p in participants]
        for sample, group in (
            ("all", examples),
            ("calibrated", [x for x in examples if x["regime"] == "calibrated"]),
            ("no-calibration", [x for x in examples if x["regime"] == "no-calibration"]),
        ):
            cells, metrics, confusion = report(group, sample, k, fit=len(group)>=8)
            output.extend(dict(k=k, sample=sample, **row) for row in cells)
            scores.extend(metrics)
            matrices.extend(confusion)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        write_csv(args.out, "push_phenotype_success.csv", output)
        write_csv(args.out, "push_phenotype_prediction_cv.csv", scores)
        write_csv(args.out, "push_phenotype_confusion_cv.csv", matrices)
        print("\nAggregate CSVs:", args.out)
    print("\nInterpretation: Qk→Q20 tests subsequent push, not early accumulated movement.")
    print("LOOCV is internal prediction validation, not new-cohort external validation.")
    print("An individual's unobserved opposite-arm response cannot be determined.")


if __name__ == "__main__":
    main()
