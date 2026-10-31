"""Synthetic tests for item-level DTAG directional decomposition; no private data."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyze_item_directional_contributions as analyzer


def save(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class ItemAnalysisTest(unittest.TestCase):
    def test_complete_reconstruction_multi_and_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = root / "input"
            analysis.mkdir()
            gss = root / "map.csv"
            save(gss, [
                dict(variable="nateduc", question_text="How much spending on education?", question_text_filled=""),
                dict(variable="otherx", question_text="Your favorite animal?", question_text_filled=""),
                dict(variable="a", question_text="Attitudes regarding cats", question_text_filled=""),
            ])
            sessions, steps, questions, assignments = [], [], [], []
            for name, i0 in (("a", 0.1), ("b", -0.1)):
                indices = [i0 - 0.01*t for t in range(21)]
                sessions.append(dict(
                    session_uid=name, dtag_study_id="prolific-v3-human-opinions-2026-10",
                    protocol="six_question_calibration", policy="left",
                    complete_20_archive="true", baseline_index=indices[0],
                    final_archived_index=indices[-1]))
                for t in range(21):
                    steps.append(dict(session_uid=name, step=t, index=indices[t],
                                      source_question_uid=f"{name}-q{t}" if t else ""))
                    if t == 0:
                        continue
                    target = "nateduc" if t % 2 else "otherx"
                    question_uid = f"{name}-q{t}"
                    questions.append(dict(
                        session_uid=name, question_uid=question_uid,
                        phase="intervention", adaptive_step=t, target_variable=target,
                        index_before=indices[t-1], index_after=indices[t],
                        accepted_assignment_count=2 if t % 2 else 0))
                    if t % 2:
                        for variable in ("nateduc", "a"):
                            assignments.append(dict(
                                session_uid=name, question_uid=question_uid,
                                phase="intervention", mapped_variable=variable,
                                assignment_type="explicit_multi_variable"))
                    else:
                        assignments.append(dict(
                            session_uid=name, question_uid=question_uid,
                            phase="intervention", mapped_variable=target,
                            assignment_type="legacy_single_value"))
            for filename, rows in (
                ("sessions.csv", sessions), ("steps.csv", steps),
                ("questions.csv", questions), ("assignments.csv", assignments)
            ):
                save(analysis / filename, rows)
            participants, events = analyzer.load(analysis, analyzer.gss_map(gss), expected=2)
            self.assertEqual(len(participants), 2)
            self.assertEqual(len(events), 40)
            self.assertTrue(all(abs(p["signed_total"] - 0.2) < 1e-8 for p in participants))
            self.assertTrue(all(abs(p["spending_exposure"] - 0.5) < 1e-8 for p in participants))
            self.assertTrue(all(abs(p["spending_share_positive"] - 0.5) < 1e-8 for p in participants))
            self.assertEqual(sum(e["n_assignments"] > 1 for e in events), 20)
            out = root / "private-output"
            result = analyzer.run(analysis, gss, out, expected=2)
            self.assertEqual(result["calibrated_complete_n"], 2)
            self.assertTrue((out / "summary_PRIVATE.json").exists())
            self.assertTrue((out / "mapped_answers_PRIVATE.csv").exists())
            with (out / "target_questions_PRIVATE.csv").open(encoding="utf-8") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 4)

    def test_exact_permutation(self):
        rows = [
            dict(policy="left", phenotype="initially_right", share=1.0),
            dict(policy="left", phenotype="initially_left", share=0.0),
            dict(policy="left", phenotype="initially_left", share=0.0),
        ]
        result = analyzer.exact_permutation(rows, "share")
        self.assertAlmostEqual(result["one_sided_p"], 1 / 3)
        self.assertEqual(result["number_of_permutations"], 3)


if __name__ == "__main__":
    unittest.main()
