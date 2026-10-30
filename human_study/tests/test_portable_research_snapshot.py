"""Portable DTAG research snapshot wrapper syntax and safety regressions.

Does not authenticate to Google Cloud or access participant records.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "portable_research_snapshot.sh"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_bash_syntax():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_private_key_is_not_part_of_cloud_snapshot_bundle():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "gcloud secrets create" in source
    assert "gcloud secrets versions access" in source
    assert "gcloud storage cp --recursive --if-generation-match=0" in source
    assert "cp \"$key\" \"$staging/" not in source
    assert "gcloud storage cp \"$key\"" not in source
    assert "publicAccessPrevention" in source
    assert "SHA256SUMS.txt" in source
    assert "if [[ -e \"$dest\" ]]" in source
