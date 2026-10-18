"""dtag-experiment: the web app's experiments (push, sequence, recipe) from the command line."""
from __future__ import annotations

import json

import pytest

from dtag_web import experiment_cli


def _folder(tmp_path, prefix):
    found = [p for p in tmp_path.iterdir() if p.name.startswith(prefix)]
    assert len(found) == 1, found
    return found[0]


def test_push_then_sequence(fake_engine, tmp_path, capsys):
    qs = tmp_path / "qs.txt"
    qs.write_text("# comment\nShould abortion be legal?\n\nDo you favor the death penalty?\n")
    rc = experiment_cli.main(["push", "--profile", "gss2024_cm", "--direction", "left", "--steps", "2",
                              "--include-pole-items", "--then-questions", str(qs), "--runs", "2", "--seed", "5",
                              "--out", str(tmp_path / "exps")], engine=fake_engine)
    assert rc == 0
    folder = _folder(tmp_path / "exps", "gss2024_cm_push_down2_")
    rec = json.loads((folder / "recipe.json").read_text())
    assert rec["actions"] == [
        {"auto_push": "down", "steps": 2, "mode": "realistic", "include_pole_items": True},
        {"sequence": ["Should abortion be legal?", "Do you favor the death penalty?"]},
    ]
    st = json.loads((folder / "summary" / "stats.json").read_text())
    assert st["runs"] == 2 and [r["seed"] for r in st["per_run"]] == [6, 7]
    for f in ["report.md", "manifest.json", "summary/steps.csv", "runs/run_02/trace.jsonl"]:
        assert (folder / f).is_file(), f
    out = capsys.readouterr().out
    assert "run 1 (seed 6" in out and "Should abortion be legal?" in out and "status: done" in out


def test_sequence_from_flags_and_recipe_replay(fake_engine, tmp_path):
    out = str(tmp_path / "exps")
    assert experiment_cli.main(["sequence", "--profile", "gss2024_cm", "-q", "Should abortion be legal?",
                                "--name", "seq", "--out", out, "--quiet"], engine=fake_engine) == 0
    rec_path = _folder(tmp_path / "exps", "seq_") / "recipe.json"
    # a recipe saved by the web app or by a previous run replays as-is; the POST body form works too
    wrapped = tmp_path / "body.json"
    wrapped.write_text(json.dumps({"recipe": json.loads(rec_path.read_text()), "runs": 9}))
    assert experiment_cli.main(["run", str(wrapped), "--runs", "2", "--name", "again", "--out", out, "--quiet"],
                               engine=fake_engine) == 0
    st = json.loads((_folder(tmp_path / "exps", "again_") / "summary" / "stats.json").read_text())
    assert st["runs"] == 2 and st["questions"][0]["asked"] == 2


def test_persona_without_profile_uses_recommended_model(fake_engine, tmp_path, capsys):
    rc = experiment_cli.main(["push", "--persona", "45 year old farmer in rural Alabama", "--country", "United States",
                              "--year", "2024", "--direction", "up", "--dry-run"], engine=fake_engine)
    assert rc == 0
    rec = json.loads(capsys.readouterr().out)
    assert rec["respondent"]["spec"]["model_key"] == "gss/gss_2024"
    assert rec["respondent"]["spec"]["persona"] == "45 year old farmer in rural Alabama"
    assert rec["name"] == "gss_gss_2024_push_up5" and rec["actions"][0]["auto_push"] == "up"


def test_argument_errors(fake_engine, tmp_path):
    with pytest.raises(SystemExit, match="--questions FILE"):
        experiment_cli.main(["sequence", "--profile", "gss2024_cm"], engine=fake_engine)
    with pytest.raises(SystemExit, match="--profile"):
        experiment_cli.main(["push", "--direction", "up"], engine=fake_engine)
    with pytest.raises(SystemExit, match="KEY=VALUE"):
        experiment_cli.main(["push", "--profile", "gss2024_cm", "--direction", "up", "--set", "oops"],
                            engine=fake_engine)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"actions": []}))
    with pytest.raises(SystemExit, match="respondent.spec"):
        experiment_cli.main(["run", str(bad)], engine=fake_engine)
