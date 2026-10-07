"""Complete session logs as ZIP archives (fake native backend, mock LLM)."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import time
import zipfile

QS = [
    "Which statement about immigrants matches your view?",
    "Do you favor or oppose gun permits?",
    "[nomatch] What is your favourite colour?",
]
EXPECTED = {
    "README.txt", "report.md", "manifest.json", "session.json", "settings.json", "persona.txt",
    "persona_initialization.json", "initial_state.csv", "final_state.csv", "questions.csv",
    "questions.jsonl", "ideology_trajectory.csv", "ideology.svg", "state_changes.csv", "poles.csv",
}


def _session(client, profile="gss2024_cm"):
    return client.post("/api/sessions", json={"profile": profile}).json()["session_id"]


def _zip(client, url):
    r = client.get(url)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert "attachment" in r.headers["content-disposition"]
    return zipfile.ZipFile(io.BytesIO(r.content))


def _members(z):
    root = z.namelist()[0].split("/")[0]
    return root, {n.split("/", 1)[1]: z.read(n).decode("utf-8") for n in z.namelist()}


def _rows(text):
    return list(csv.reader(io.StringIO(text)))


def test_zip_covers_history_since_reset(fake_client):
    sid = _session(fake_client)
    fake_client.post(f"/api/sessions/{sid}/questions", json={"question": "Do you think of yourself as liberal or conservative?"})
    assert fake_client.post(f"/api/sessions/{sid}/reset").status_code == 200
    for q in QS:
        fake_client.post(f"/api/sessions/{sid}/questions", json={"question": q})

    root, f = _members(_zip(fake_client, f"/api/sessions/{sid}/export?format=zip&label=A"))
    assert root.startswith("dtag_A_gss_gss_2024_")
    assert EXPECTED <= set(f), set(f) ^ EXPECTED

    man = json.loads(f["manifest.json"])
    assert man["question_count"] == 3 and man["label"] == "A" and man["history"]["resets"] == 1
    for name, meta in man["files"].items():  # every listed file is present and matches its checksum
        assert hashlib.sha256(f[name].encode("utf-8")).hexdigest() == meta["sha256"], name

    assert [r[8] for r in _rows(f["questions.csv"])[1:]] == QS  # pre-reset question not included
    assert len(f["questions.jsonl"].splitlines()) == 3
    traj = _rows(f["ideology_trajectory.csv"])
    assert len(traj) == 1 + 1 + 3 and traj[1][2] == "(initial state)"
    sess = json.loads(f["session.json"])
    assert sess["persona"]["full_text"] in f["persona.txt"] and sess["label"] == "A"
    assert sess["ideology"]["initial"] == float(traj[1][5])

    # state_changes replays from the initial state: each previous value is what the state held before
    init = {r[0]: r[1] for r in _rows(f["initial_state.csv"])[1:]}
    cur = dict(init)
    for qidx, _q, var, _txt, prev, new, change in _rows(f["state_changes.csv"])[1:]:
        if change == "evicted":
            cur.pop(var, None)
            continue
        assert prev == cur.get(var, "")
        cur[var] = new
    final = {r[0]: r[1] for r in _rows(f["final_state.csv"])[1:]}
    assert cur == final

    assert "Respondent A" in f["report.md"] and "| 3 |" in f["report.md"]
    assert f["ideology.svg"].startswith("<svg")


def test_zip_includes_sequence_until_a_later_reset(fake_client):
    sid = _session(fake_client)
    fake_client.post(f"/api/sessions/{sid}/sequence", json={"text": "\n".join(QS[:2]), "name": "pair", "reset_first": True})
    t0 = time.time()
    while fake_client.get(f"/api/sessions/{sid}/sequence").json()["status"] in ("queued", "running"):
        assert time.time() - t0 < 60
        time.sleep(0.05)
    _, f = _members(_zip(fake_client, f"/api/sessions/{sid}/export?format=zip"))
    seq = json.loads(f["sequence.json"])
    assert seq["name"] == "pair" and seq["completed"] == 2 and "results" not in seq
    assert "## Question sequence" in f["report.md"]

    fake_client.post(f"/api/sessions/{sid}/reset")
    _, f = _members(_zip(fake_client, f"/api/sessions/{sid}/export?format=zip"))
    assert "sequence.json" not in f and json.loads(f["manifest.json"])["question_count"] == 0


def test_bundle_has_both_respondents_and_comparison(fake_client):
    a, b = _session(fake_client, "gss2024_cm"), _session(fake_client, "gss2024_wf")
    for q in QS:
        fake_client.post(f"/api/sessions/{a}/questions", json={"question": q})
    fake_client.post(f"/api/sessions/{b}/questions", json={"question": QS[0]})

    z = _zip(fake_client, f"/api/export/bundle?ids={a},{b}&labels=A,B")
    names = z.namelist()
    tops = {n.split("/")[0] for n in names if "/" in n}
    assert len(tops) == 2 and any(t.startswith("dtag_A_") for t in tops) and any(t.startswith("dtag_B_") for t in tops)
    for t in tops:
        assert f"{t}/report.md" in names and f"{t}/manifest.json" in names
    comp = _rows(z.read("comparison.csv").decode())
    assert comp[0] == ["step", "A_question", "A_ideology", "A_change_from_initial",
                       "B_question", "B_ideology", "B_change_from_initial"]
    assert len(comp) == 1 + 1 + 3 and comp[3][4] == ""  # B asked only one question
    bm = json.loads(z.read("bundle_manifest.json"))
    assert [r["label"] for r in bm["respondents"]] == ["A", "B"] and bm["respondents"][1]["questions"] == 1


def test_export_validation(fake_client):
    sid = _session(fake_client)
    assert fake_client.get(f"/api/sessions/{sid}/export?format=pdf").status_code == 422
    assert fake_client.get("/api/sessions/nope/export?format=zip").status_code == 404
    assert fake_client.get("/api/export/bundle?ids=nope").status_code == 404
    # JSON export now records the history window
    h = fake_client.get(f"/api/sessions/{sid}/export").json()["history"]
    assert h["resets"] == 0 and h["since"]
