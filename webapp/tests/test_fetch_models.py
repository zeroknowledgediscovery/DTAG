"""Public model download: manifest, SHA256, zstd extraction, safety, cache reuse."""
from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

import pytest
import zstandard as zstd

import fetch_models


def _make_archive(path: Path, top: str, extra_member: tarfile.TarInfo | None = None, extra_data: bytes = b"") -> str:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for rel, data in {
            f"{top}/source_maps/json_shards/0.json": b'{"0": {"column_header": "x", "column_strings_map": ["a", "b"]}}',
            f"{top}/trees/binary/tree_0.bin": b"\x00\x01",
            f"{top}/meta.txt": b"fake",
        }.items():
            ti = tarfile.TarInfo(rel)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        if extra_member is not None:
            extra_member.size = len(extra_data)
            tf.addfile(extra_member, io.BytesIO(extra_data) if extra_data else None)
    path.write_bytes(zstd.ZstdCompressor().compress(buf.getvalue()))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(base: Path, key: str, sha: str) -> dict:
    return {
        "release": "vTEST",
        "base_url": base.as_uri(),
        "models": {key: {"archive": f"{key}.tar.zst", "sha256": sha, "size_bytes": 1}},
    }


def test_download_verify_extract_and_cache_reuse(tmp_path):
    key = "gss/gss_2099"
    store = tmp_path / "store"
    (store / "gss").mkdir(parents=True)
    sha = _make_archive(store / f"{key}.tar.zst", "gss_2099")
    root = tmp_path / "cache"
    stages = []
    dest = fetch_models.fetch_one(root, _manifest(store, key, sha), key, progress=lambda s, d, t: stages.append(s), log=lambda *_: None)
    assert dest == root / key
    assert fetch_models.installed(root, key)
    assert (dest / "trees" / "binary" / "tree_0.bin").is_file()
    assert {"downloading", "verifying", "extracting", "installed"} <= set(stages)
    # no temporary directories left beside the model
    assert [p.name for p in (root / "gss").iterdir()] == ["gss_2099"]

    # second request reuses the cache: no download
    (store / f"{key}.tar.zst").unlink()
    logs = []
    fetch_models.fetch_one(root, _manifest(store, key, sha), key, log=logs.append)
    assert logs and logs[0].startswith("OK installed")


def test_sha256_mismatch_rejected(tmp_path):
    key = "gss/gss_2098"
    store = tmp_path / "store"
    (store / "gss").mkdir(parents=True)
    _make_archive(store / f"{key}.tar.zst", "gss_2098")
    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        fetch_models.fetch_one(tmp_path / "cache", _manifest(store, key, "f" * 64), key, log=lambda *_: None)
    assert not fetch_models.installed(tmp_path / "cache", key)


@pytest.mark.parametrize(
    "member",
    [
        tarfile.TarInfo("../escape.txt"),
        tarfile.TarInfo("/abs/escape.txt"),
    ],
)
def test_path_traversal_rejected(tmp_path, member):
    key = "gss/gss_2097"
    store = tmp_path / "store"
    (store / "gss").mkdir(parents=True)
    sha = _make_archive(store / f"{key}.tar.zst", "gss_2097", member, b"x")
    with pytest.raises(RuntimeError, match="Unsafe path"):
        fetch_models.fetch_one(tmp_path / "cache", _manifest(store, key, sha), key, log=lambda *_: None)
    assert not (tmp_path / "escape.txt").exists()


def test_symlink_member_rejected(tmp_path):
    key = "gss/gss_2096"
    store = tmp_path / "store"
    (store / "gss").mkdir(parents=True)
    link = tarfile.TarInfo("gss_2096/evil")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    sha = _make_archive(store / f"{key}.tar.zst", "gss_2096", link)
    with pytest.raises(RuntimeError, match="link"):
        fetch_models.fetch_one(tmp_path / "cache", _manifest(store, key, sha), key, log=lambda *_: None)


def test_model_key_validation():
    assert fetch_models.validate_model_key("gss/gss_2024") == "gss/gss_2024"
    for bad in ["../x", "gss/../../etc", "other/x", "gss/gss 2024", "gss", "/gss/gss_2024"]:
        with pytest.raises(ValueError):
            fetch_models.validate_model_key(bad)


def test_unknown_key_not_in_manifest(tmp_path):
    with pytest.raises(KeyError):
        fetch_models.fetch_one(tmp_path, {"models": {}, "base_url": "file:///x"}, "gss/gss_2024", log=lambda *_: None)


def test_default_root_matches_runtime_resolution(monkeypatch, tmp_path):
    import dtag_paths

    monkeypatch.setenv("DTAG_MODEL_ROOT", str(tmp_path))
    assert fetch_models.default_root() == dtag_paths.model_root() == tmp_path.resolve()


@pytest.mark.network
def test_public_manifest_loads():
    try:
        m = fetch_models.load_manifest(timeout=30)
    except Exception as e:  # pragma: no cover - network dependent
        pytest.skip(f"public manifest unreachable: {e}")
    assert m["release"] == fetch_models.DEFAULT_RELEASE
    models = m["models"]
    assert len(models) == 252
    fams = {}
    for k in models:
        fams[k.split("/")[0]] = fams.get(k.split("/")[0], 0) + 1
    assert fams == {"gss": 35, "afrobarometer": 9, "wvs": 1, "eurobarometer": 207}
    for entry in models.values():
        assert len(entry["sha256"]) == 64 and entry["archive"].endswith(".tar.zst")
