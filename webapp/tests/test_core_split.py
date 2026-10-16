"""dtag_core holds the library; pipeline.py is the CLI and a live alias of dtag_core."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import dtag_core  # noqa: E402
import pipeline  # noqa: E402


def test_pipeline_names_are_dtag_core_objects():
    names = [n for n in vars(dtag_core) if not n.startswith("__")]
    assert len(names) > 60
    for n in names:
        assert getattr(pipeline, n) is getattr(dtag_core, n), n
    assert callable(pipeline.main) and not hasattr(dtag_core, "main")


def test_assignment_through_pipeline_reaches_dtag_core():
    orig = pipeline._norm
    try:
        pipeline._norm = lambda s: "patched"
        assert dtag_core._norm("x") == "patched"
    finally:
        pipeline._norm = orig
    assert dtag_core._norm is orig


def test_localized_forced_assignments_reach_sessions():
    import dtag_session
    import pipeline_localized
    fn = pipeline_localized.build_forced_assignments
    assert dtag_core.build_forced_assignments is fn
    assert pipeline.build_forced_assignments is fn
    assert dtag_session.core.build_forced_assignments is fn
