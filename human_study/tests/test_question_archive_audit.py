"""Audit archived respondent-facing questions without displaying participant answers."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_completed_questions.py"
SPEC = importlib.util.spec_from_file_location("audit_completed_questions", SCRIPT)
audit_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_mod)


def _make_record(var, phase, original, shown, labels, *, incomplete=False, **provenance):
    return (
        {
            "item_id": var,
            "original_wording": original,
            "source_text_incomplete": incomplete,
            "choices": [{"native_value": v, "display_label": v} for v in labels],
            "phase": phase,
        },
        {
            "target_variable": var,
            "phase": phase,
            "original_wording": original,
            "displayed_wording": shown,
            "choices": [{"native_value": v, "display_label": v} for v in labels],
            "question_provenance": provenance,
            "response_value": "SECRET_ANSWER_DO_NOT_PRINT",
        },
    )


def fixture_final():
    cases = [
        _make_record("conbus", "baseline",
                     "(I am going to name some institutions. How much confidence do you have?) Major companies",
                     "(I am going to name some institutions. How much confidence do you have?) Major companies",
                     ["a great deal", "only some", "hardly any"], provider="canonical-common-instrument"),
        _make_record("workhard", "intervention", "to work hard",
                     "How important is it to work hard?",
                     ["most important", "2nd important", "3rd important", "4th important", "least important"],
                     incomplete=True, provider="openai", mapper_hit=True),
        _make_record("eqwlth", "intervention", "Some people think the government should",
                     "Should government reduce income differences?",
                     ["2.0", "3.0", "government should help"],
                     incomplete=True, provider="openai", mapper_hit=True),
        _make_record("helpful", "baseline",
                     "Would you say that most people try to be helpful?",
                     "Would you say that most people try to be helpful?",
                     ["yes", "no"], provider="canonical-common-instrument"),
    ]
    for idx, (_, q) in enumerate(cases):
        q["ordinal"] = idx
    return {
        "session_id": "SECRET_SESSION_DO_NOT_PRINT",
        "policy": "SECRET_POLICY_DO_NOT_PRINT",
        "questions": [q for _, q in cases],
        "study_configuration": {"items": [item for item, _ in cases]},
    }


def test_flags_unjoined_baseline_and_invalid_adaptive_scales():
    rows = audit_mod.audit(fixture_final())
    assert len(rows) == 4
    def codes(row):
        return {i["reason"] for i in row["issues"]}

    assert "UNJOINED_OR_TRUNCATED_SOURCE_VISIBLE" in codes(rows[0])
    assert "RANKING_REQUIRES_COMPLETE_COMPARATIVE_TASK" in codes(rows[1])
    assert "UNEXPLAINED_NUMERIC_RESPONSE_LABELS" in codes(rows[2])
    assert rows[3]["issues"] == []
    assert "response_value" not in rows[0]
    assert "session_id" not in rows[0]


def test_printed_report_omits_private_answers_and_ids(tmp_path, capsys):
    path = tmp_path / "final.json"
    path.write_text(json.dumps(fixture_final()), encoding="utf-8")
    assert audit_mod.main([str(path)]) == 0
    report = capsys.readouterr().out
    assert "conbus" in report and "workhard" in report
    assert "SECRET_ANSWER_DO_NOT_PRINT" not in report
    assert "SECRET_SESSION_DO_NOT_PRINT" not in report
    assert "SECRET_POLICY_DO_NOT_PRINT" not in report
    assert audit_mod.main([str(path), "--fail-on-issues"]) == 2
