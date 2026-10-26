"""Prolific eligibility decisions are evidence-based flags, never API rejections."""
import pytest

from human_study.rejection_eligibility import assess_rejection_eligibility


def questions(texts):
    return [
        {"phase": "intervention", "question_id": f"q{i:03d}", "raw_text_response": text}
        for i, text in enumerate(texts)
    ]


def quality(failures, *, score=0):
    return {
        "eligible_imc_failed_ids": [f"imc_{i}" for i in range(failures)],
        "human_review_recommended": score >= 35 or failures > 0,
        "score": score,
    }


@pytest.mark.parametrize("failures", [0, 1, 2])
def test_fewer_than_three_imc_failures_not_sufficient_without_objective_low_effort(failures):
    # Deliberately all short or identical but meaningful text: arbitrary
    # score cannot justify withholding payment.
    result = assess_rejection_eligibility(
        questions(["yes"] * 26), quality(failures, score=100),
    )
    assert result["eligible_for_rejection"] is False
    assert result["quality_score_not_a_rejection_criterion"] is True
    assert result["two_failures_need_independent_evidence"] == (failures == 2)
    assert result["prolific_rejection_executed"] is False


def test_three_valid_imc_failures_eligible_subject_to_investigator_review():
    result = assess_rejection_eligibility(
        questions(["My opinion is coherent and nuanced."] * 26), quality(3, score=0)
    )
    assert result["eligible_for_rejection"] is True
    assert result["basis"] == "at_least_three_valid_imc_failures"
    assert result["review_required_before_prolific_rejection"] is True


def test_two_failures_plus_sustained_obvious_keyboard_mash_is_eligible():
    result = assess_rejection_eligibility(
        questions(["asdfghjkl"] * 20 + ["I have a considered answer"] * 6),
        quality(2, score=0),
    )
    assert result["eligible_for_rejection"] is True
    assert result["basis"] == "two_valid_imc_failures_plus_repeated_obvious_gibberish"
    assert result["low_effort_evidence"]["match_count"] == 20
    assert len(result["low_effort_evidence"]["question_ids"]) == 20
    assert result["prolific_rejection_executed"] is False


def test_two_failures_plus_only_a_few_keyboard_mashes_not_sufficient():
    result = assess_rejection_eligibility(
        questions(["asdf"] * 4 + ["Valid answer"] * 22), quality(2, score=90),
    )
    assert result["eligible_for_rejection"] is False
    assert result["low_effort_evidence"]["confirmed_by_strict_text_rule"] is False


def test_one_failure_and_obvious_gibberish_still_ineligible_under_combined_rule():
    result = assess_rejection_eligibility(
        questions(["asdfghjkl"] * 26), quality(1, score=100),
    )
    assert result["eligible_for_rejection"] is False


def test_empty_and_early_ended_sessions_fail_closed():
    result = assess_rejection_eligibility(questions(["asdf"] * 6), quality(2, score=100))
    assert not result["eligible_for_rejection"]
    assert result["low_effort_evidence"]["minimum_required_matches"] is None


def test_prolific_configs_use_five_verbatim_imcs_in_order():
    from pathlib import Path
    from human_study.study_config import StudyConfig

    root = Path(__file__).resolve().parents[2]
    for path in [
        root / "human_study/config/study.prolific.example.yaml",
        root / "human_study/config/study.prolific.gcptest.yaml",
    ]:
        cfg = StudyConfig.load(path)
        checks = cfg.attention_checks
        assert len(checks) == 5
        assert [check.after_substantive for check in checks] == [3, 8, 13, 18, 24]
        assert all(check.kind == "instructed_token" and check.render == "verbatim"
                   for check in checks)
        assert all(check.passes(check.instruction) for check in checks)
        assert len({check.expected_token for check in checks}) == 5
        assert cfg.prolific.attention_fail_threshold == 3
        for check in checks:
            assert check.instruction.lower().startswith("attention check:")
            assert not check.passes("I cannot answer this")
            assert check.passes(f"Here is {check.expected_token.upper()}")
