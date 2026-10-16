"""Country conditioning reaches sessions through dtag_core (pipeline_localized patches it)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import dtag_core  # noqa: E402


def test_localized_forced_assignments_reach_sessions():
    import dtag_session
    import pipeline_localized
    fn = pipeline_localized.build_forced_assignments
    assert dtag_core.build_forced_assignments is fn
    assert dtag_session.core.build_forced_assignments is fn


def test_dtag_config_resolves_profiles_like_engine():
    import dtag_config
    root = Path(__file__).resolve().parents[2]
    cfg = dtag_config.load_config(root / "configs" / "dtag_config.yaml")
    assert dtag_config.config_root(root / "configs" / "dtag_config.yaml") == root
    name = sorted(cfg["interactive_profiles"])[0]
    r = dtag_config.resolve_profile(cfg, name, root)
    assert r["name"] == name and r["qnet"] and r["map"] and r["persona"]
