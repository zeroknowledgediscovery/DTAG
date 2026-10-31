#!/usr/bin/env python3
"""NHB explanatory analyses from the already-audited PRIVATE DTAG export.

No cloud API, no LLM, no model inference. Uses existing
analyze_item_directional_contributions.load() to audit the 71 complete
six-calibration trajectories and their exact question-event indices.

PRIVATE output: rich group, wave, target and native answer-category tables.
PUBLIC output: coarse, disclosure-checked aggregate CSVs ready for Git,
stored only in tex/Figures/nhb_explanatory/. No participant identifiers,
free-text, timestamps, question displays or unvetted native values are
ever written to public CSVs.

Q4 resistance is a *within-study descriptive partition*, not a validated
psychological phenotype. Predicted delta targets one survey variable;
observed delta may reflect several accepted assignments. These are not
interchangeable causal or prediction-calibration estimands.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
import math
import os
from pathlib import Path
import random
import re
from statistics import fmean

import analyze_item_directional_contributions as core

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "tex" / "Figures" / "nhb_explanatory"
EPS = 1e-10
PUBLIC_MIN_PEOPLE = 5
PUBLIC_MIN_EVENTS = 8
STAGES = {"early": range(1, 5), "late": range(5, 21), "all": range(1, 21)}
GSS_CODES = {
    "religion_culture": {"religinf", "relpersn", "sprtprsn", "bible", "pray", "prayer"},
    "civil_liberties": {"colath", "polhitok", "polescap", "rghtsmin"},
    "sexual_reproductive": {"premarsx", "homosex", "marsame", "abhlth", "letdie1", "suicide1"},
    "institutions": {"contv", "conbus", "consci", "conmedic", "conarmy"},
    "political_ratings": {"rateincumb24", "ratechall224", "ratemaga"},
}
TOPIC_WORDS = (
    ("religion_culture", r"\b(religion|religious|spiritual|church|prayer|bible)\b"),
    ("civil_liberties", r"\b(free speech|allowed to speak|allowed to teach|civil libert|right of minorit)\b"),
    ("sexual_reproductive", r"\b(abortion|sexual|homosexual|same.sex|premarital|suicide|end (his|her|their) life)\b"),
    ("institutions", r"\b(confidence in|running these institutions)\b"),
    ("political_ratings", r"\b(rating of|partisan|democrat|republican)\b"),
    ("immigration", r"\b(immigrant|immigration)\b"),
)


def load_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def maybe_float(value):
    if value is None or str(value).strip() == "":
        return None
    x = float(value)
    if not math.isfinite(x):
        raise ValueError("Nonfinite exported prediction")
    return x


def write_csv(path, fields, rows, private=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700 if private else 0o755)
    if private:
        os.chmod(path.parent, 0o700)
    with path.open("x" if private else "w", encoding="utf-8", newline="") as f:
        if private:
            os.chmod(path, 0o600)
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def mean(xs):
    return fmean(xs) if xs else None


def qtile(xs, q):
    ys = sorted(xs)
    if not ys:
        return None
    k = (len(ys) - 1) * q
    lo = math.floor(k)
    hi = math.ceil(k)
    return ys[lo] * (hi - k) + ys[hi] * (k - lo) if hi != lo else ys[lo]


def bootstrap_person_mean(values, seed, boots):
    if not values:
        return (None, None, None)
    m = mean(values)
    rng = random.Random(seed)
    n = len(values)
    draws = [sum(values[rng.randrange(n)] for _ in range(n)) / n
             for _ in range(boots)]
    return (m, qtile(draws, .025), qtile(draws, .975))


def topic(variable, mapping):
    name = variable.lower()
    if core.category(name, mapping) == "spending_program":
        return "spending_program"
    for cat, codes in GSS_CODES.items():
        if name in codes:
            return cat
    question = (mapping.get(name) or "").lower()
    for cat, pattern in TOPIC_WORDS:
        if re.search(pattern, question):
            return cat
    return "other"


def study_wave(study):
    if study == "prolific-v3-human-opinions-2026-10":
        return "original_randomized"
    if study == "prolific-v3-left-followup-2026-10":
        return "fixed_left"
    if study == "prolific-v3-right-followup-2026-10":
        return "fixed_right"
    raise ValueError("Unexpected study for calibrated participant")


def enrich(root, mapping, expect=71, check_q4=True):
    participants, events = core.load(root, mapping, expected=expect)
    steps = {(r["session_uid"], int(r["step"])): r for r in load_csv(root / "steps.csv")
             if r.get("step") not in ("", None)}
    questions = {(r["session_uid"], int(r["adaptive_step"])): r
                 for r in load_csv(root / "questions.csv")
                 if r.get("phase") == "intervention"
                 and r.get("adaptive_step") not in ("", None)}
    by_uid = {p["uid"]: dict(p) for p in participants}
    # Include explicit zeros for categories absent in a valid cohort.
    q4_counter = Counter({"TP": 0, "FP": 0, "FN": 0, "TN": 0})
    for uid, p in by_uid.items():
        p["wave"] = study_wave(p["study"])
        s0 = steps[(uid, 0)]
        s4 = steps[(uid, 4)]
        s20 = steps[(uid, 20)]
        baseline = float(s0["index"])
        delta4 = float(s4["index"]) - baseline
        delta20 = float(s20["index"]) - baseline
        if p["policy"] == "right":
            if p["phenotype"] == "initially_left":
                flag = (delta4 / 4) <= EPS
                p["subgroup"] = "right_initially_left_q4_flagged" if flag else "right_initially_left_q4_unflagged"
                outcome = delta20 <= EPS
                q4_counter["TP" if flag and outcome else "FP" if flag else
                           "FN" if outcome else "TN"] += 1
            else:
                p["subgroup"] = "right_initially_right"
        elif p["policy"] == "left":
            p["subgroup"] = "left_" + p["phenotype"]
        else:
            p["subgroup"] = p["policy"] + "_all"
        p["delta4"] = delta4
        p["delta20"] = delta20
    if check_q4 and tuple(q4_counter[k] for k in ("TP", "FP", "FN", "TN")) != (17, 2, 0, 10):
        raise ValueError(f"Archived Q4 confusion matrix changed: {dict(q4_counter)}")
    if check_q4:
        counts = Counter(p["subgroup"] for p in by_uid.values())
        if (counts["right_initially_left_q4_flagged"],
            counts["right_initially_left_q4_unflagged"],
            counts["right_initially_right"]) != (19, 10, 9):
            raise ValueError("Q4 cohort mismatch")
    enhanced = []
    for event in events:
        uid = event["session_uid"]
        step = event["step"]
        record = steps.get((uid, step))
        question = questions.get((uid, step))
        if record is None or question is None:
            raise ValueError("Missing step/question for already-verified event")
        if record.get("source_question_uid") != question.get("question_uid"):
            raise ValueError("Mismatched step-to-question UID")
        observed = maybe_float(record.get("observed_step_delta"))
        if observed is not None and not math.isclose(observed, event["delta"], abs_tol=1e-7):
            raise ValueError("Observed step delta does not match exact archived index difference")
        prediction = maybe_float(record.get("predicted_target_only_delta"))
        question_pred = maybe_float(question.get("predicted_target_only_delta"))
        if prediction is None:
            prediction = question_pred
        elif question_pred is not None and not math.isclose(prediction, question_pred, abs_tol=1e-6):
            raise ValueError("Question/step predicted deltas disagree")
        p = by_uid[uid]
        direction = -1 if p["policy"] == "left" else 1 if p["policy"] == "right" else 0
        e = dict(event)
        e.update(phenotype=p["phenotype"], subgroup=p["subgroup"], wave=p["wave"],
                 direction=direction, topic=topic(event["target"], mapping),
                 predicted_signed=direction * prediction if prediction is not None and direction else None,
                 predicted_raw=prediction,
                 predicted_scope=(record.get("predicted_scope") or question.get("predicted_scope") or "unrecorded"),
                 observed_scope=(record.get("observed_scope") or question.get("observed_scope") or "unrecorded"),
                 is_single=(event["n_assignments"] == 1),
                 is_target_aligned=(event["n_assignments"] == 1
                                    and len(event["mapped_values"]) == 1
                                    and event["mapped_values"][0][0] == event["target"]),
                 stage=("early" if step <= 4 else "late"))
        enhanced.append(e)
    return by_uid, enhanced, q4_counter


def groups(participants):
    gp = defaultdict(list)
    for p in participants.values():
        gp[p["policy"] + "_all"].append(p["uid"])
        gp[p["subgroup"]].append(p["uid"])
    return {k: sorted(set(v)) for k, v in gp.items()}


def stage_metrics(group, stage, ids, events, participants, boots, seed):
    ids = set(ids)
    ev = [e for e in events if e["session_uid"] in ids and e["step"] in STAGES[stage]]
    by_person = defaultdict(list)
    for e in ev:
        by_person[e["session_uid"]].append(e)
    if len(by_person) != len(ids):
        raise ValueError("Missing steps from group")
    sums = [sum(e["signed"] if e["direction"] else e["delta"]
                for e in by_person[uid]) for uid in sorted(ids)]
    value, ci_lo, ci_hi = bootstrap_person_mean(sums, seed, boots)
    paired = [e for e in ev if e["predicted_signed"] is not None]
    comparable = [e for e in paired if e["is_target_aligned"]]
    def paired_metrics(xs):
        if not xs:
            return (None, None, None, None)
        err = [e["signed"] - e["predicted_signed"] for e in xs]
        def sign(v):
            return 1 if v > EPS else -1 if v < -EPS else 0
        matches = [sign(e["signed"]) == sign(e["predicted_signed"]) for e in xs]
        return (mean(err), mean([abs(x) for x in err]), mean(matches),
                mean([e["predicted_signed"] for e in xs]))
    bias, mae, sign_match, pred_mean = paired_metrics(comparable)
    bias_all, mae_all, match_all, pred_all = paired_metrics(paired)
    return dict(group=group, stage=stage, n_sessions=len(ids), n_events=len(ev),
                mean_signed_displacement=value, ci95_low=ci_lo, ci95_high=ci_hi,
                n_steps_predicted=len(paired),
                n_steps_target_aligned_prediction=len(comparable),
                n_steps_multi=sum(e["n_assignments"] > 1 for e in ev),
                n_steps_no_assignment=sum(e["n_assignments"] == 0 for e in ev),
                mean_predicted_signed_target_aligned=pred_mean,
                mean_error_signed_target_aligned=bias,
                mae_target_aligned=mae, sign_agreement_target_aligned=sign_match,
                mean_predicted_signed_all=pred_all,
                mean_error_signed_all=bias_all, mae_all=mae_all,
                sign_agreement_all=match_all)


def topic_records(events, gp, public):
    out = []
    for group in ("right_initially_left_q4_flagged",
                  "right_initially_left_q4_unflagged", "right_initially_right",
                  "right_all", "left_all"):
        ids = set(gp[group])
        for stage in ("early", "late", "all"):
            subset = [e for e in events if e["session_uid"] in ids
                      and e["step"] in STAGES[stage]]
            by_topic = defaultdict(list)
            for e in subset:
                by_topic[e["topic"]].append(e)
            retained, suppressed = [], []
            for cat, rs in sorted(by_topic.items()):
                people = len({r["session_uid"] for r in rs})
                if not public or (people >= PUBLIC_MIN_PEOPLE and len(rs) >= PUBLIC_MIN_EVENTS):
                    retained.append((cat, rs))
                else:
                    suppressed.extend(rs)
            if public and suppressed and (
                    len({x["session_uid"] for x in suppressed}) >= PUBLIC_MIN_PEOPLE
                    and len(suppressed) >= PUBLIC_MIN_EVENTS):
                retained.append(("other_or_suppressed", suppressed))
            for cat, rs in retained:
                if not rs:
                    continue
                out.append(dict(group=group, stage=stage, topic=cat,
                                n_sessions_with_topic=len({e["session_uid"] for e in rs}),
                                n_selections=len(rs),
                                exposure_share=len(rs) / len(subset),
                                mean_signed_per_selection=mean([e["signed"] for e in rs]),
                                sum_positive=sum(e["positive_gain"] for e in rs),
                                sum_signed=sum(e["signed"] for e in rs),
                                n_multi_assignment=sum(e["n_assignments"] > 1 for e in rs)))
    return out


def target_records(events, gp, public):
    rows = []
    for group in ("right_initially_left_q4_flagged",
                  "right_initially_left_q4_unflagged", "right_all", "left_all"):
        ids = set(gp[group])
        for stage in ("early", "late"):
            count = defaultdict(list)
            for e in events:
                if e["session_uid"] in ids and e["step"] in STAGES[stage]:
                    count[e["target"]].append(e)
            for target, rs in sorted(count.items()):
                people = len({e["session_uid"] for e in rs})
                if public and (people < PUBLIC_MIN_PEOPLE or len(rs) < PUBLIC_MIN_EVENTS
                               or re.fullmatch(r"[a-z][a-z0-9_]{1,35}", target) is None):
                    continue
                rows.append(dict(group=group, stage=stage, target_variable=target,
                                 n_sessions=people, n_selections=len(rs),
                                 sum_positive=sum(e["positive_gain"] for e in rs),
                                 sum_signed=sum(e["signed"] for e in rs),
                                 mean_signed_per_selection=mean([e["signed"] for e in rs])))
    return rows


def response_records(events, gp):
    out = []
    for group in ("right_initially_left_q4_flagged",
                  "right_initially_left_q4_unflagged", "right_all", "left_all"):
        ids = set(gp[group])
        for stage in ("early", "late"):
            d = defaultdict(list)
            for e in events:
                if e["session_uid"] in ids and e["step"] in STAGES[stage]:
                    for var, value in e["mapped_values"]:
                        d[(e["target"], var, value)].append(e)
            for (target, var, value), rs in sorted(d.items()):
                out.append(dict(group=group, stage=stage, target_variable=target,
                                mapped_variable=var, native_value=value,
                                n_sessions=len({e["session_uid"] for e in rs}),
                                n_event_associations=len(rs),
                                sum_associated_signed=sum(e["signed"] for e in rs),
                                sum_associated_positive=sum(e["positive_gain"] for e in rs),
                                n_multi_assignment=sum(e["n_assignments"] > 1 for e in rs)))
    return out


def curated_answers(private_rows, allowlist):
    if allowlist is None:
        return []
    allowed = {}
    for r in load_csv(allowlist):
        var = (r.get("mapped_variable") or "").strip().lower()
        val = (r.get("native_value") or "").strip().lower()
        label = (r.get("public_label") or "").strip()
        if var and val and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 \-/,()]{0,55}", label):
            allowed[(var, val)] = label
        elif any((var, val, label)):
            raise ValueError("Answer allowlist has incomplete or unsafe label")
    released = []
    for r in private_rows:
        if r["group"] not in ("left_all", "right_all"):
            continue
        if r["n_sessions"] < PUBLIC_MIN_PEOPLE or r["n_event_associations"] < PUBLIC_MIN_EVENTS:
            continue
        label = allowed.get((r["mapped_variable"], r["native_value"]))
        if label is not None:
            released.append({k: r[k] for k in (
                "group", "stage", "target_variable", "mapped_variable", "n_sessions",
                "n_event_associations", "sum_associated_signed", "n_multi_assignment")}
                | {"curated_category": label})
    return released


def binned_predictions(events, gp, boots, seed):
    out = []
    for group in ("left_all", "right_all"):
        ids = set(gp[group])
        selected = sorted((e for e in events
                           if e["session_uid"] in ids and e["predicted_signed"] is not None
                           and e["is_target_aligned"]),
                          key=lambda e: e["predicted_signed"])
        if len(selected) < 5 * PUBLIC_MIN_EVENTS:
            continue
        for j in range(5):
            subset = selected[j * len(selected) // 5: (j + 1) * len(selected) // 5]
            by_person = defaultdict(list)
            for e in subset:
                by_person[e["session_uid"]].append(e)
            if len(subset) < PUBLIC_MIN_EVENTS or len(by_person) < PUBLIC_MIN_PEOPLE:
                continue
            # Participant-cluster bootstrap for the *event-weighted* mean:
            # resample participants (and all their events) as intact clusters.
            clusters = [(sum(e["signed"] for e in es), len(es))
                        for _, es in sorted(by_person.items())]
            rng = random.Random(seed + j)
            draws = []
            for _ in range(boots):
                sampled = [clusters[rng.randrange(len(clusters))]
                           for _ in range(len(clusters))]
                draws.append(sum(x for x, _ in sampled) / sum(n for _, n in sampled))
            out.append(dict(group=group, bin=j+1,
                            n_events=len(subset), n_sessions=len(by_person),
                            mean_predicted_signed=mean([e["predicted_signed"] for e in subset]),
                            mean_observed_signed=mean([e["signed"] for e in subset]),
                            ci95_low=qtile(draws, .025),
                            ci95_high=qtile(draws, .975)))
    return out


def trajectory_records(events, gp, boots, seed):
    rows = []
    for i, group in enumerate(("right_initially_left_q4_flagged",
                               "right_initially_left_q4_unflagged",
                               "right_initially_right")):
        ids = set(gp[group])
        d = defaultdict(dict)
        for e in events:
            if e["session_uid"] in ids:
                d[e["session_uid"]][e["step"]] = e["delta"]
        for t in range(21):
            values = [sum(d[uid][j] for j in range(1, t+1)) for uid in sorted(ids)]
            m, lo, hi = bootstrap_person_mean(values, seed + i * 23 + t, boots)
            rows.append(dict(group=group, step=t, n_sessions=len(ids),
                             mean_delta=m, ci95_low=lo, ci95_high=hi))
    return rows


def run(analysis_dir, private_out, public_out=PUBLIC, gss_map=None,
        answer_allowlist=None, expected=71, boots=2000, seed=20261031,
        validate_q4=True):
    analysis_dir = Path(analysis_dir).expanduser().resolve()
    private_out = Path(private_out).expanduser().resolve()
    public_out = Path(public_out).expanduser().resolve()
    if private_out.is_relative_to(ROOT) or private_out.is_relative_to(public_out):
        raise ValueError("Private results must remain outside the DTAG repository")
    if private_out.exists():
        raise ValueError("Private output exists; use a new directory to prevent accidental overwrites")
    if public_out != PUBLIC.resolve():
        raise ValueError("Public CSVs must be written only to tex/Figures/nhb_explanatory")
    if analysis_dir.is_relative_to(ROOT):
        raise ValueError("Private input archives must be outside the DTAG repository")
    if boots < 100:
        raise ValueError("At least 100 bootstrap replicates required")
    mapping = core.gss_map(Path(gss_map or ROOT/"maps/gss/gss_2024_map.csv"))
    p, e, confusion = enrich(analysis_dir, mapping, expected, validate_q4)
    gp = groups(p)
    stage_rows = [stage_metrics(group, stage, ids, e, p, boots, seed + idx)
                  for idx, (group, ids) in enumerate(sorted(gp.items()))
                  for stage in STAGES]
    topics_private = topic_records(e, gp, False)
    topics_public = topic_records(e, gp, True)
    targets_private = target_records(e, gp, False)
    targets_public = target_records(e, gp, True)
    answer_private = response_records(e, gp)
    answer_public = curated_answers(answer_private, answer_allowlist)
    bin_public = binned_predictions(e, gp, boots, seed)
    traj_public = trajectory_records(e, gp, boots, seed)
    private_out.mkdir(parents=True, mode=0o700)
    os.chmod(private_out, 0o700)
    stages = ("group","stage","n_sessions","n_events","mean_signed_displacement",
              "ci95_low","ci95_high","n_steps_predicted","n_steps_target_aligned_prediction",
              "n_steps_multi","n_steps_no_assignment",
              "mean_predicted_signed_target_aligned","mean_error_signed_target_aligned",
              "mae_target_aligned","sign_agreement_target_aligned","mean_predicted_signed_all",
              "mean_error_signed_all","mae_all","sign_agreement_all")
    topics = ("group","stage","topic","n_sessions_with_topic","n_selections",
              "exposure_share","mean_signed_per_selection","sum_positive",
              "sum_signed","n_multi_assignment")
    targets = ("group","stage","target_variable","n_sessions","n_selections",
               "sum_positive","sum_signed","mean_signed_per_selection")
    answers = ("group","stage","target_variable","mapped_variable","native_value",
               "n_sessions","n_event_associations","sum_associated_signed",
               "sum_associated_positive","n_multi_assignment")
    write_csv(private_out/"all_stage_metrics_PRIVATE.csv", stages, stage_rows, True)
    write_csv(private_out/"topic_exposure_PRIVATE.csv", topics, topics_private, True)
    write_csv(private_out/"target_questions_PRIVATE.csv", targets, targets_private, True)
    write_csv(private_out/"mapped_native_answers_PRIVATE.csv", answers, answer_private, True)
    # Predicted/realized comparison split by wave and scope; not public because
    # study-wave x phenotype cells can be small or uniquely identifying.
    wave_rows = []
    for (wave, policy, sub), subset in sorted({
        key: [x for x in e if (x["wave"], x["policy"], x["subgroup"]) == key]
        for key in set((x["wave"], x["policy"], x["subgroup"]) for x in e)
    }.items()):
        for scope, rr in sorted({q: [x for x in subset if x["predicted_scope"] == q]
                                 for q in {x["predicted_scope"] for x in subset}}.items()):
            paired = [x for x in rr if x["predicted_signed"] is not None]
            wave_rows.append(dict(wave=wave, policy=policy, subgroup=sub, predicted_scope=scope,
                                  n_sessions=len({x["session_uid"] for x in rr}),
                                  n_steps=len(rr), n_prediction=len(paired),
                                  n_target_aligned=sum(x["is_target_aligned"] for x in paired),
                                  mean_signed=mean([x["signed"] for x in rr]),
                                  mean_predicted=mean([x["predicted_signed"] for x in paired]),
                                  mean_prediction_minus_observed=mean([
                                      x["predicted_signed"]-x["signed"] for x in paired])))
    write_csv(private_out/"prediction_by_wave_and_scope_PRIVATE.csv",
              ("wave","policy","subgroup","predicted_scope","n_sessions",
               "n_steps","n_prediction","n_target_aligned","mean_signed",
               "mean_predicted","mean_prediction_minus_observed"), wave_rows, True)
    # Public-safe release: no raw answer values, individual rows, or tiny
    # target/topic cells. The private results must NEVER be git added.
    public_out.mkdir(parents=True, exist_ok=True)
    write_csv(public_out/"nhb_resistance_stage_metrics.csv", stages,
              [r for r in stage_rows if r["n_sessions"] >= PUBLIC_MIN_PEOPLE])
    write_csv(public_out/"nhb_question_topics.csv", topics, topics_public)
    write_csv(public_out/"nhb_target_questions.csv", targets, targets_public)
    write_csv(public_out/"nhb_predicted_observed_quintiles.csv",
              ("group","bin","n_events","n_sessions","mean_predicted_signed",
               "mean_observed_signed","ci95_low","ci95_high"), bin_public)
    write_csv(public_out/"nhb_right_q4_trajectories.csv",
              ("group","step","n_sessions","mean_delta","ci95_low","ci95_high"), traj_public)
    write_csv(public_out/"nhb_curated_answer_categories.csv",
              ("group","stage","target_variable","mapped_variable",
               "n_sessions","n_event_associations","sum_associated_signed",
               "n_multi_assignment","curated_category"), answer_public)
    manifest = dict(schema_version=1, n_sessions=len(p), n_events=len(e),
                    q4_confusion=dict(confusion),
                    group_counts={g: len(ids) for g, ids in gp.items()},
                    prediction_available=sum(x["predicted_signed"] is not None for x in e),
                    prediction_target_aligned=sum(x["predicted_signed"] is not None and x["is_target_aligned"] for x in e),
                    prediction_scope_counts=dict(Counter(x["predicted_scope"] for x in e)),
                    curated_answer_values_published=len(answer_public),
                    topic_definition="Exploratory GSS code/topic-word heuristics; inspect code before interpretation",
                    caveats=[
                        "Cross-wave policy differences are not a single randomized causal effect.",
                        "Q4 groups were defined by observed first-four-question displacement.",
                        "Predicted target-only change is not the same estimand as observed multi-variable full-state change; target-aligned single-assignment steps are reported separately.",
                        "Mapped answer values are joint-step associations, not causal effects of a value.",
                        "Public response-value rows require a reviewed answer allowlist and a disclosure threshold.",
                    ])
    (private_out/"manifest_PRIVATE.json").write_text(json.dumps(manifest, indent=2) + "\n")
    os.chmod(private_out/"manifest_PRIVATE.json", 0o600)
    # Public manifest intentionally omits scope strings, private wave details
    # and participant identifiers. Existing published subgroup totals known.
    release = {k: manifest[k] for k in ("schema_version", "n_sessions", "n_events",
                                         "prediction_available", "prediction_target_aligned",
                                         "curated_answer_values_published", "caveats")}
    release["files"] = [
        "nhb_resistance_stage_metrics.csv", "nhb_question_topics.csv",
        "nhb_target_questions.csv", "nhb_predicted_observed_quintiles.csv",
        "nhb_right_q4_trajectories.csv", "nhb_curated_answer_categories.csv"]
    (public_out/"nhb_manifest.json").write_text(json.dumps(release, indent=2) + "\n")
    print("Verified calibrated sessions:", len(p), "adaptive questions:", len(e))
    print("Q4 confusion:", dict(confusion), "Right groups:",
          {g: len(ids) for g, ids in gp.items() if g.startswith("right_")})
    print("Directional step predictions available:", manifest["prediction_available"],
          "target-aligned single-assignment predictions:", manifest["prediction_target_aligned"])
    print("Private detailed outputs:", private_out)
    print("Public aggregate outputs (REVIEW before git add):", public_out)
    print("No participant identifiers or native answer values appear in public outputs.")
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--analysis-dir", type=Path, required=True)
    ap.add_argument("--private-out", type=Path, required=True,
                    help="New private directory OUTSIDE repo; never commit")
    ap.add_argument("--gss-map", type=Path, default=ROOT/"maps/gss/gss_2024_map.csv")
    ap.add_argument("--public-out", type=Path, default=PUBLIC)
    ap.add_argument("--answer-allowlist", type=Path, default=None,
                    help="Optional researcher-reviewed CSV: mapped_variable,native_value,public_label")
    ap.add_argument("--expect-complete", type=int, default=71)
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261031)
    a = ap.parse_args()
    run(a.analysis_dir, a.private_out, a.public_out, a.gss_map,
        a.answer_allowlist, a.expect_complete, a.bootstrap, a.seed)


if __name__ == "__main__":
    main()
