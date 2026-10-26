"""Versioned, reproducible participant-level *scientific* quality triage.

Not a Prolific rejection classifier and never a payment decision. The score
is a preliminary heuristic: high means worth human investigation; low does
not certify authenticity. Page latency includes backend work in V3.
"""
from __future__ import annotations


def summarize_quality(questions, attention_checks, quality_settings):
    """Compute a conservative, auditable 0-100 review-priority score.

    The score is built only from existing per-answer response_quality flags.
    Normalizing by the number of answered substantive items makes it comparable
    between sessions, including early-ending adaptive sessions.
    """
    substantive = [q for q in questions if q["phase"] not in ("attention",)]
    count = len(substantive)
    short = sum(bool((q.get("response_quality") or {}).get("short")) for q in substantive)
    duplicate = sum(
        (q.get("response_quality") or {}).get("duplicate_of") is not None
        for q in substantive
    )
    fast = sum(bool((q.get("response_quality") or {}).get("fast")) for q in substantive)
    def rate(n):
        return round(n / count, 4) if count else 0.0

    fractions = {
        "short_answer_fraction": rate(short),
        "near_duplicate_fraction": rate(duplicate),
        "fast_answer_fraction": rate(fast),
    }
    # Candidate pilot weights are explicitly *not* validated thresholds:
    # near-exact repeated prose is more informative than brevity or latency.
    score = round(
        65 * fractions["near_duplicate_fraction"]
        + 25 * fractions["short_answer_fraction"]
        + 10 * fractions["fast_answer_fraction"]
    )
    signals = []
    if fractions["near_duplicate_fraction"] >= 0.30 and count >= 5:
        signals.append("many_near_duplicate_answers")
    if fractions["short_answer_fraction"] >= 0.60 and count >= 5:
        signals.append("many_short_answers")
    if fractions["fast_answer_fraction"] >= 0.70 and count >= 5:
        signals.append("many_fast_answers_server_elapsed")

    by_check = {x.check_id: x for x in attention_checks}
    attention = [q for q in questions if q["phase"] == "attention"]
    eligible = [
        q for q in attention
        if by_check.get(q["target_variable"]) is not None
        and by_check[q["target_variable"]].kind == "instructed_token"
    ]
    eligible_failed = [q["target_variable"] for q in eligible if not q.get("attention_passed")]
    other_failed = [
        q["target_variable"] for q in attention
        if not q.get("attention_passed") and q not in eligible
    ]
    if eligible_failed:
        signals.append("failed_instructed_response_checks")

    # Quality score is solely descriptive. IMC failures are an independent
    # Prolific-policy review trigger; neither warrants automatic rejection.
    priority = "high" if score >= 60 or len(eligible_failed) >= 2 else (
        "review" if score >= 35 or len(eligible_failed) == 1 else "routine"
    )
    return {
        "version": "pilot-review-priority-v1",
        "score": score,
        "priority": priority,
        "human_review_recommended": priority != "routine",
        "substantive_count": count,
        "signals": signals,
        "fractions": fractions,
        "eligible_imc_total": len(eligible),
        "eligible_imc_failed": len(eligible_failed),
        "eligible_imc_failed_ids": eligible_failed,
        "other_check_failed_ids": other_failed,
        "review_only": True,
        "may_determine_payment_or_rejection": False,
        "limitations": "unvalidated pilot triage; speed includes server latency",
    }
