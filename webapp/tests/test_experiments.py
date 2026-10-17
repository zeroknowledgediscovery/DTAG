"""Experiments: actions are recorded as intent, rerun N times on fresh respondents, and summarised."""
from __future__ import annotations

import io
import json
import time
import zipfile


def _session(client, **overrides):
    r = client.post("/api/sessions", json={"profile": "gss2024_cm", "overrides": overrides})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def _wait(client, job_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = client.get(f"/api/experiments/jobs/{job_id}").json()
        if st["status"] not in ("queued", "running"):
            return st
        time.sleep(0.1)
    raise AssertionError("experiment did not finish")


def test_record_and_rerun(fake_client, tmp_path, monkeypatch):
    monkeypatch.setenv("DTAG_EXPERIMENTS_DIR", str(tmp_path))
    sid = _session(fake_client, resp_mode="draw")
    assert fake_client.get(f"/api/sessions/{sid}/experiment").json()["actions"] == []
    fake_client.post(f"/api/sessions/{sid}/questions", json={"question": "Should abortion be legal?"})
    sug = fake_client.get(f"/api/sessions/{sid}/ideology-push?include_pole_items=true").json()
    d = "up" if sug["up"] else "down"
    fake_client.post(f"/api/sessions/{sid}/ideology-push/ask",
                     json={"variable": sug[d]["variable"], "question": sug[d]["question"], "direction": d,
                           "include_pole_items": True})
    rec = fake_client.get(f"/api/sessions/{sid}/experiment?name=t1").json()
    assert rec["actions"][0] == {"ask": "Should abortion be legal?"}
    assert rec["actions"][1]["push"] == d and rec["actions"][1]["original"]["variable"] == sug[d]["variable"]
    assert len(rec["descriptions"]) == 2 and rec["respondent"]["spec"]["model_key"]

    job = fake_client.post(f"/api/sessions/{sid}/experiment/run", json={"runs": 3, "name": "t1", "seed": 7}).json()
    st = _wait(fake_client, job["job_id"])
    assert st["status"] == "done", st
    assert st["completed"] == 3 and st["stats"]["runs"] == 3
    cps = st["stats"]["checkpoints"]
    assert [c["action"] for c in cps] == [0, 1, 2] and all(c["n"] == 3 for c in cps)
    assert cps[0]["ci_lo"] <= cps[0]["mean"] <= cps[0]["ci_hi"]
    assert [r["seed"] for r in st["stats"]["per_run"]] == [8, 9, 10]

    folder = tmp_path / st["folder"]
    for f in ["recipe.json", "manifest.json", "report.md", "summary/steps.csv", "summary/stats.csv",
              "summary/checkpoints.csv", "summary/questions.csv", "summary/final_answers.csv", "summary/stats.json",
              "runs/run_01/trace.jsonl", "runs/run_03/session_log.zip"]:
        assert (folder / f).is_file(), f
    trace = [json.loads(x) for x in (folder / "runs/run_02/trace.jsonl").read_text().splitlines()]
    assert trace[0]["question"] == "Should abortion be legal?" and trace[1]["kind"] == "push"
    assert trace[1].get("question") or trace[1].get("skipped")
    assert json.loads((folder / "manifest.json").read_text())["runs_completed"] == 3

    listed = fake_client.get("/api/experiments").json()
    assert listed[0]["folder"] == st["folder"]
    z = zipfile.ZipFile(io.BytesIO(fake_client.get(f"/api/experiments/{st['folder']}/download").content))
    assert f"{st['folder']}/summary/stats.csv" in z.namelist()

    # reset starts a new experiment
    fake_client.post(f"/api/sessions/{sid}/reset")
    assert fake_client.get(f"/api/sessions/{sid}/experiment").json()["actions"] == []
    assert fake_client.post(f"/api/sessions/{sid}/experiment/run", json={"runs": 2}).status_code == 400


def test_rerun_recipe_and_one_job_at_a_time(fake_client, tmp_path, monkeypatch):
    monkeypatch.setenv("DTAG_EXPERIMENTS_DIR", str(tmp_path))
    sid = _session(fake_client, ideology=False)
    fake_client.post(f"/api/sessions/{sid}/questions", json={"question": "Trust the courts?"})
    rec = fake_client.get(f"/api/sessions/{sid}/experiment").json()
    job = fake_client.post("/api/experiments/run", json={"recipe": rec, "runs": 2}).json()
    st = _wait(fake_client, job["job_id"])
    assert st["status"] == "done" and st["stats"]["ideology_enabled"] is False
    assert fake_client.get(f"/api/experiments/{'..'}/download").status_code == 404
