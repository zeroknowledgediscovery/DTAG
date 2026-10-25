"""Prolific linkage, completion codes, reward records, factual checks and quality flags.

Synthetic fixture model and scripted LLM only: no OpenAI, GCP or Prolific traffic.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from human_study.app import create_app
from human_study.service import StudyService
from human_study.storage import MemoryArchive, MemoryRepository
from human_study.study_config import AttentionCheck, StudyConfig
from test_v3_multi_observations import MultiFixtureLLM, make_v3, request

ROOT = Path(__file__).resolve().parents[2]
PID = "5f1e2d3c4b5a69788796a5b4"


def prolific_config(instrument, adapter, *, review_code="REVIEW42", threshold=2):
    config, _, _ = make_v3(instrument, adapter)
    base = config.model_dump(mode="json")
    base.update(study_id="prolific-fixture", prolific={
        "completion_code": "C0MPLETE1", "review_code": review_code,
        "attention_fail_threshold": threshold, "reward": "GBP 3.00"})
    base["attention_checks"] = [
        {"check_id": "attention_token", "instruction": "Include the exact word cobalt in your reply.",
         "expected_token": "cobalt", "after_substantive": 2},
        {"check_id": "attention_sky", "kind": "factual", "render": "verbatim",
         "instruction": "Attention check: what colour is a clear daytime sky?",
         "accepted_answers": ["blue"], "after_substantive": 5},
    ]
    return StudyConfig.model_validate(base)


def run(svc, answers, *, pid=PID):
    first = svc.start(prolific={"prolific_pid": pid, "prolific_study_id": "S1", "prolific_session_id": "X1"})
    sid = first["session_id"]
    view = svc.consent(sid, True, first["session_version"])
    shown = []
    while view["question"] is not None:
        phase = view["phase"]
        shown.append((phase, view["question"]["text"]))
        view = svc.answer(sid, request(view, answers(phase, len(shown))))["current"]
    assert view["phase"] == "ready_to_complete"
    return sid, svc.complete(sid), shown


DISTINCT = [
    "Yes, I support it because it protects families.",
    "Probably yes; costs matter but the benefit seems larger to me.",
    "I lean yes after thinking about my neighbours and local schools.",
    "Yes overall, although government often wastes money on this.",
    "My answer is yes since fairness should come first here.",
    "Honestly yes, my own experience at work convinced me.",
    "Yes, though I would want strict oversight and regular reviews.",
    "Mostly yes because the evidence I have read points that way.",
    "Yes, my parents taught me to value this and I still agree.",
    "I would say yes, provided nobody is forced into anything.",
]


def substantive(i):
    return DISTINCT[i % len(DISTINCT)]


def test_full_session_passing_checks_gets_completion_code_and_reward_record(instrument, adapter):
    config = prolific_config(instrument, adapter)
    archive = MemoryArchive()
    svc = StudyService(config, adapter, MultiFixtureLLM(), MemoryRepository(), archive)
    answers = {"attention": lambda i: "blue" if i > 4 else "ok: cobalt"}
    sid, done, shown = run(svc, lambda phase, i: answers.get(phase, substantive)(i))
    assert done["phase"] == "complete"
    assert done["completion_code"] == "C0MPLETE1"
    assert done["completion_url"] == "https://app.prolific.com/submissions/complete?cc=C0MPLETE1"
    # The factual check is displayed exactly as configured, not LLM-rewritten.
    assert ("attention", "Attention check: what colour is a clear daytime sky?") in shown

    base = f"studies/{config.study_id}"
    reward = json.loads(archive.objects[f"{base}/sessions/{sid}/reward.json"])
    assert reward == json.loads(archive.objects[f"{base}/rewards/{PID}.json"])
    assert reward["completion_code"] == "C0MPLETE1" and reward["code_category"] == "complete"
    assert reward["prolific"] == {"prolific_pid": PID, "prolific_study_id": "S1", "prolific_session_id": "X1"}
    assert reward["attention"] == {"total": 2, "passed": 2, "failed": 0, "failed_check_ids": [],
                                   "fail_threshold": 2}
    assert reward["reward"] == "GBP 3.00"
    final = json.loads(archive.objects[f"{base}/sessions/{sid}/final.json"])
    assert final["reward"] == {k: v for k, v in reward.items() if k in final["reward"]}
    assert final["reward"]["completion_code"] == "C0MPLETE1" and final["prolific"]["prolific_pid"] == PID
    enrollment = json.loads(archive.objects[f"{base}/sessions/{sid}/events/enrollment.json"])
    assert enrollment["prolific"]["prolific_pid"] == PID
    # Distinct written answers are not flagged as copies.
    assert reward["quality"]["duplicate_answers"] == 0
    assert reward["quality"]["substantive_answers"] == 7


def test_failed_checks_at_threshold_get_review_code(instrument, adapter):
    config = prolific_config(instrument, adapter)
    archive = MemoryArchive()
    svc = StudyService(config, adapter, MultiFixtureLLM(), MemoryRepository(), archive)
    sid, done, _ = run(svc, lambda phase, i: "asdf" if phase == "attention" else "yes")
    assert done["completion_code"] == "REVIEW42"
    reward = json.loads(archive.objects[f"studies/{config.study_id}/sessions/{sid}/reward.json"])
    assert reward["code_category"] == "attention_review"
    assert reward["attention"]["failed_check_ids"] == ["attention_token", "attention_sky"]
    # Identical one-word substantive answers are flagged for review, never scored.
    assert reward["quality"]["duplicate_answers"] == 6
    assert reward["quality"]["short_answers"] == 7
    assert reward["quality"]["fast_answers"] == 9


def test_without_review_code_failures_are_recorded_but_code_is_shared(instrument, adapter):
    config = prolific_config(instrument, adapter, review_code=None)
    svc = StudyService(config, adapter, MultiFixtureLLM(), MemoryRepository(), MemoryArchive())
    _, done, _ = run(svc, lambda phase, i: "nothing" if phase == "attention" else substantive(i))
    assert done["completion_code"] == "C0MPLETE1"


def test_returning_pid_resumes_its_session_and_pid_is_required(instrument, adapter):
    config = prolific_config(instrument, adapter)
    svc = StudyService(config, adapter, MultiFixtureLLM(), MemoryRepository(), MemoryArchive())
    with pytest.raises(ValueError, match="Prolific"):
        svc.start()
    first = svc.start(prolific={"prolific_pid": PID})
    view = svc.consent(first["session_id"], True, first["session_version"])
    svc.answer(first["session_id"], request(view, substantive(1)))
    # Lost cookie: same PID gets the same session back, with progress kept.
    again = svc.start(prolific={"prolific_pid": PID})
    assert again["session_id"] == first["session_id"]
    assert again["progress"]["completed"] == 1
    # A different PID on a browser holding another participant's cookie gets its own session.
    other = svc.start(first["session_id"], prolific={"prolific_pid": "OTHER123"})
    assert other["session_id"] != first["session_id"] and other["phase"] == "consent"
    assert svc.start(first["session_id"])["session_id"] == first["session_id"]


def test_pid_session_id_depends_on_secret(instrument, adapter):
    config = prolific_config(instrument, adapter)
    a = StudyService(config, adapter, MultiFixtureLLM(), MemoryRepository(), MemoryArchive(), sid_key="a" * 40)
    b = StudyService(config, adapter, MultiFixtureLLM(), MemoryRepository(), MemoryArchive(), sid_key="b" * 40)
    assert a.prolific_sid(PID) != b.prolific_sid(PID)
    assert len(a.prolific_sid(PID)) == 32


def test_api_links_prolific_parameters_and_returns_completion_code(instrument, adapter):
    config = prolific_config(instrument, adapter)
    svc = StudyService(config, adapter, MultiFixtureLLM(), MemoryRepository(), MemoryArchive())
    client = TestClient(create_app(svc, cookie_secret="test-secret-stable-not-for-deployment" * 2))
    headers = {"Origin": "http://testserver"}
    assert client.post("/api/human/start", json={}, headers=headers).status_code == 422
    assert client.post("/api/human/start", json={"prolific_pid": "bad pid!"}, headers=headers).status_code == 422
    view = client.post("/api/human/start", json={"prolific_pid": PID, "prolific_study_id": "S1",
                                                 "prolific_session_id": "X1"}, headers=headers).json()
    view = client.post("/api/human/consent", json={"accepted": True, "expected_session_version": view["session_version"]},
                       headers=headers).json()
    i = 0
    while view["question"] is not None:
        i += 1
        text = ("cobalt blue" if view["phase"] == "attention" else substantive(i))
        view = client.post("/api/human/answer", json=request(view, text), headers=headers).json()["current"]
    done = client.post("/api/human/complete", json={}, headers=headers).json()
    assert done["completion_code"] == "C0MPLETE1"
    receipt = client.get("/api/human/receipt").json()
    assert receipt["type"] == "prolific_completion"
    assert receipt["completion_url"].endswith("?cc=C0MPLETE1")


def test_attention_check_validation():
    with pytest.raises(ValueError, match="verbatim"):
        AttentionCheck(check_id="attention_x", kind="factual", instruction="What colour is grass?",
                       accepted_answers=("green",))
    with pytest.raises(ValueError, match="expected_token"):
        AttentionCheck(check_id="attention_x", instruction="Write anything you like here.")
    with pytest.raises(ValueError, match="show the expected token"):
        AttentionCheck(check_id="attention_x", render="verbatim", instruction="Write the colour word.",
                       expected_token="cobalt")
    week = AttentionCheck(check_id="attention_w", kind="factual", render="verbatim",
                          instruction="How many days are in a week?", accepted_answers=("7", "seven"))
    assert week.passes("There are 7.") and week.passes("SEVEN days")
    assert not week.passes("17") and not week.passes("sevens")


def test_prolific_example_config_is_6_plus_20_plus_5_with_pole_baseline():
    config = StudyConfig.load(ROOT / "human_study/config/study.prolific.example.yaml")
    assert not config.reviewed
    assert [i.item_id for i in config.bank("baseline")] == [
        "gunlaw", "grass", "abany", "natfare", "natenvir", "natarms"]
    assert config.intervention_steps == 20 and config.candidate_mode == "native_webapp"
    assert [config.attention_position(c) for c in config.attention_checks] == [3, 8, 13, 18, 24]
    poles = (ROOT / "assets/polar_vectors/gss/gss_2024_polar_vectors.csv").read_text().splitlines()
    pole_ids = {line.split(",")[0] for line in poles[1:]}
    assert {i.item_id for i in config.bank("baseline")} <= pole_ids
    assert config.prolific.completion_code.startswith("CHANGEME")


def test_placeholder_codes_refused_outside_local(monkeypatch):
    from human_study import app as app_module
    monkeypatch.setenv("DTAG_ENV", "staging")
    monkeypatch.setenv("DTAG_STUDY_CONFIG", str(ROOT / "human_study/config/study.prolific.example.yaml"))
    data = StudyConfig.load(ROOT / "human_study/config/study.prolific.example.yaml").model_dump(mode="json")
    data["reviewed"] = True
    monkeypatch.setattr(app_module, "configured_service", app_module.configured_service)
    monkeypatch.setattr(StudyConfig, "load", classmethod(lambda cls, path: cls.model_validate(data)))
    for name, value in {"DTAG_GCS_BUCKET": "bucket", "DTAG_COOKIE_SECRET": "s" * 40,
                        "DTAG_CODE_COMMIT": "a" * 40, "OPENAI_API_KEY": "test"}.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match="placeholder Prolific"):
        app_module.configured_service()


def test_export_includes_prolific_linkage_code_and_quality(instrument, adapter, tmp_path):
    import csv
    from human_study.export import export_records
    config = prolific_config(instrument, adapter)
    archive = MemoryArchive()
    svc = StudyService(config, adapter, MultiFixtureLLM(), MemoryRepository(), archive)
    sid, _, _ = run(svc, lambda phase, i: "asdf" if phase == "attention" else "yes")
    name = f"studies/{config.study_id}/sessions/{sid}/final.json"
    export_records([(name, json.loads(archive.objects[name]))], tmp_path / "export")
    with (tmp_path / "export/participants.csv").open() as f:
        (row,) = list(csv.DictReader(f))
    assert row["prolific_pid"] == PID and row["completion_code"] == "REVIEW42"
    assert row["code_category"] == "attention_review" and row["attention_failed"] == "2"
    assert row["duplicate_answers"] == "6"
    with (tmp_path / "export/answers.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert [r["attention_passed"] for r in rows if r["phase"] == "attention"] == ["False", "False"]
    assert all(json.loads(r["response_quality"])["fast"] for r in rows)
