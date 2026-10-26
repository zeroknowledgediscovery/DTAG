"""Conservative Prolific rejection-eligibility screening, never a rejection action.

The study uses a stricter-than-Prolific rule for a >=5-minute experiment:
  * at least three failed, eligible instructional-manipulation checks (IMCs); OR
  * at least two failed eligible IMCs PLUS independently observed and
    objectively obvious repetitive gibberish throughout substantive answers.

An internal prose-quality score, short answers, per-question speed and semantic
opinions are NEVER evidence sufficient for rejection. The generated flag
requires a human to verify the archive and applicable Prolific policy.
See https://researcher-help.prolific.com/en/articles/445153-
prolific-s-attention-and-comprehension-check-policy
"""
from __future__ import annotations

import math
import re
from collections import Counter

VERSION = "prolific-rejection-eligibility-v1"

# Extremely narrow examples of non-answers rather than controversial judgments
# of respondent beliefs. These are not a general gibberish classifier.
_OBVIOUS_GIBBERISH = frozenset({
    "asdf", "asdfgh", "asdfghjkl", "qwerty", "qwertyuiop",
    "zxcv", "zxcvbnm", "hjkl", "aaaaaaa", "xxxxxxxx", "123456789",
})


def _normalized(text):
    return re.sub(r"\s+", " ", str(text or "").casefold()).strip()


def obvious_repetitive_gibberish(questions):
    """Flag only demonstrably nonresponsive filler across most of a session.

    This is *not* based on the internal quality score or on agreement,
    demographics, ideological consistency, or word-count/response speed.
    """
    substantive = [q for q in questions if q.get("phase") != "attention"]
    n = len(substantive)
    evidence = [
        q for q in substantive
        if _normalized(q.get("raw_text_response")) in _OBVIOUS_GIBBERISH
    ]
    by_text = Counter(_normalized(q.get("raw_text_response")) for q in evidence)
    most_common, count = by_text.most_common(1)[0] if by_text else ("", 0)
    threshold = max(5, math.ceil(0.60 * n))
    strong = n >= 8 and count >= threshold
    return {
        "confirmed_by_strict_text_rule": strong,
        "evidence_kind": "repeated_obvious_keyboard_mash" if strong else None,
        "match_count": count if strong else 0,
        "substantive_count": n,
        "question_ids": [
            q.get("question_id") for q in substantive
            if strong and _normalized(q.get("raw_text_response")) == most_common
        ],
        # The archived answers hold verbatim evidence for a human investigator.
        "minimum_required_matches": threshold if n >= 8 else None,
        "human_verification_required": True,
    }


def assess_rejection_eligibility(questions, quality_review, *, attention_threshold=3):
    """Return reproducible, limited eligibility; do not take platform action."""
    failures = list(quality_review.get("eligible_imc_failed_ids") or [])
    fail_count = len(failures)
    gibberish = obvious_repetitive_gibberish(questions)
    # The minimum allowable Prolific threshold is two for studies >=5 minutes;
    # the *study's stricter* criterion is at least 3.
    threshold = max(3, int(attention_threshold))
    enough_imc = fail_count >= threshold
    corroborated = fail_count >= 2 and gibberish["confirmed_by_strict_text_rule"]
    eligible = enough_imc or corroborated
    if enough_imc:
        basis = "at_least_three_valid_imc_failures"
    elif corroborated:
        basis = "two_valid_imc_failures_plus_repeated_obvious_gibberish"
    else:
        basis = None
    # Flag a possible two-check case for investigator examination, but do not
    # call it eligible just because short/repeated answers score highly.
    needs_extra_evidence = (
        fail_count >= 2 and not eligible and
        bool(quality_review.get("human_review_recommended"))
    )
    return {
        "version": VERSION,
        "eligible_for_rejection": eligible,
        "basis": basis,
        "valid_imc_failures": fail_count,
        "failed_check_ids": failures,
        "required_imc_failures_without_independent_evidence": threshold,
        "low_effort_evidence": gibberish,
        "two_failures_need_independent_evidence": needs_extra_evidence,
        "quality_score_not_a_rejection_criterion": True,
        "review_required_before_prolific_rejection": True,
        "prolific_rejection_executed": False,
    }
