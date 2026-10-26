"""Deterministic safeguards for researcher-only automated quality triage."""
from types import SimpleNamespace

from human_study.quality_review import summarize_quality


def q(phase="baseline", *, short=False, duplicate=False, fast=False, item="survey"):
    return {"phase": phase, "target_variable": item, "attention_passed": True,
            "response_quality": {"short": short,
                                 "duplicate_of": "previous-q" if duplicate else None,
                                 "fast": fast}}


CHECKS = [
    SimpleNamespace(check_id="imc_one", kind="instructed_token"),
    SimpleNamespace(check_id="factual", kind="factual"),
    SimpleNamespace(check_id="imc_two", kind="instructed_token"),
]


def test_short_but_nonduplicate_answers_do_not_trigger_review():
    questions = [q(short=True)] * 2 + [q()] * 8
    result = summarize_quality(questions, CHECKS, None)
    assert result["score"] == 5  # 25 × 20%; brevity alone is a weak signal
    assert result["priority"] == "routine"
    assert not result["human_review_recommended"]
    assert result["may_determine_payment_or_rejection"] is False


def test_multiple_signals_increase_review_priority():
    questions = (
        [q(short=True, duplicate=True, fast=True)] * 7
        + [q(short=True, fast=True)] * 3
    )
    result = summarize_quality(questions, CHECKS, None)
    assert result["score"] == 81  # 65×.7 + 25×1.0 + 10×1.0 = 80.5 -> 81
    assert result["priority"] == "high"
    assert "many_near_duplicate_answers" in result["signals"]
    assert "many_short_answers" in result["signals"]
    assert "many_fast_answers_server_elapsed" in result["signals"]


def test_factual_failure_is_not_policy_eligible():
    questions = [q() for _ in range(10)]
    questions += [
        {**q(phase="attention", item="imc_one"), "attention_passed": False},
        {**q(phase="attention", item="factual"), "attention_passed": False},
        {**q(phase="attention", item="imc_two"), "attention_passed": True},
    ]
    result = summarize_quality(questions, CHECKS, None)
    assert result["eligible_imc_total"] == 2
    assert result["eligible_imc_failed"] == 1
    assert result["other_check_failed_ids"] == ["factual"]
    assert result["priority"] == "review"
    assert result["score"] == 0  # attention flags are separate from prose score
    assert result["review_only"]


def test_two_instructional_failures_trigger_high_priority():
    questions = [q() for _ in range(10)]
    questions += [
        {**q(phase="attention", item="imc_one"), "attention_passed": False},
        {**q(phase="attention", item="imc_two"), "attention_passed": False},
    ]
    result = summarize_quality(questions, CHECKS, None)
    assert result["priority"] == "high"
    assert result["eligible_imc_failed"] == 2
    assert result["score"] == 0


def test_empty_or_legacy_question_lists_are_safe():
    result = summarize_quality([], CHECKS, None)
    assert result["score"] == 0
    assert result["priority"] == "routine"
    assert result["fractions"]["near_duplicate_fraction"] == 0
