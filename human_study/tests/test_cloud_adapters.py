"""Protocol tests for cloud adapters without spending or live credentials."""
from types import SimpleNamespace

import pytest
from google.api_core.exceptions import PreconditionFailed

from human_study.storage import IntegrityError
from human_study.storage_gcs import GCSArchive


class Blob:
    generation = 7

    def __init__(self):
        self.content = None
        self.writes = 0

    def upload_from_string(self, content, **kwargs):
        assert kwargs["if_generation_match"] == 0 and kwargs["checksum"] == "crc32c"
        if self.content is not None:
            raise PreconditionFailed("already exists")
        self.writes += 1
        self.content = content

    def reload(self, **kwargs):
        pass

    def download_as_bytes(self, **kwargs):
        assert kwargs["if_generation_match"] == self.generation
        assert kwargs["checksum"] == "crc32c"
        return self.content


def test_gcs_create_only_identical_retry_and_integrity_conflict():
    blob = Blob()
    client = SimpleNamespace(bucket=lambda name: SimpleNamespace(blob=lambda key: blob))
    archive = GCSArchive("test-private", client)
    archive.put("immutable.json", {"answer": "yes"})
    archive.put("immutable.json", {"answer": "yes"})
    assert blob.writes == 1
    with pytest.raises(IntegrityError):
        archive.put("immutable.json", {"answer": "no"})


def test_gcs_probe_requires_private_uniform_bucket():
    bucket = SimpleNamespace(reload=lambda **kw: None, iam_configuration=SimpleNamespace(
        uniform_bucket_level_access_enabled=True, public_access_prevention="inherited"))
    archive = GCSArchive("test-private", SimpleNamespace(bucket=lambda _: bucket))
    with pytest.raises(RuntimeError, match="enforced"):
        archive.probe()


def test_firestore_bigint_roundtrip_uses_nonreserved_field_names():
    # Regression for live Cloud Run: the 13th baseline answer persists PCG64
    # 128-bit RNG states, which must not use Firestore's reserved __.*__ names.
    import re
    from human_study.storage_firestore import BIGINT_FIELD, encode, decode
    from human_study.policy import initial_rng

    rng = initial_rng(2**127 + 19)
    data = {
        "assignment_rng_state": rng,
        "selection_rng_state": initial_rng(2**127 + 31),
        "nested": [{"large_negative": -(2**100), "large_positive": 2**127 + 1}],
        "signed64_max": 2**63 - 1,
        "signed64_min": -(2**63),
        "not_an_int": True,
    }
    encoded = encode(data)

    def check(node):
        if isinstance(node, dict):
            assert not any(re.fullmatch(r"__.*__", k) for k in node)
            for v in node.values():
                check(v)
        elif isinstance(node, list):
            for v in node:
                check(v)

    check(encoded)
    assert BIGINT_FIELD == "dtag_bigint_decimal"
    assert decode(encoded) == data
    assert decode({"__dtag_bigint__": str(2**127)}) == 2**127
    assert encode(2**63 - 1) == 2**63 - 1
    assert encode(2**63) == {BIGINT_FIELD: str(2**63)}
    assert encode(True) is True


def test_firestore_cas_serialization_and_transaction_retry(monkeypatch):
    import human_study.storage_firestore as module
    from human_study.policy import initial_rng
    monkeypatch.setattr(module.firestore, "transactional", lambda fn: fn)
    database = {}
    class Ref:
        def __init__(self, path): self.path = path
        def collection(self, name): return Collection(self.path + "/" + name)
        def get(self, transaction=None):
            value = database.get(self.path)
            return SimpleNamespace(exists=value is not None, to_dict=lambda: value)
    class Collection:
        def __init__(self, path): self.path = path
        def document(self, name): return Ref(self.path + "/" + name)
    class Tx:
        def set(self, ref, value): database[ref.path] = value
    fake = SimpleNamespace(collection=lambda c: Collection(c), transaction=lambda: Tx())
    repo = module.FirestoreRepository("study", client=fake)
    session = {"revision": 0, "rng": initial_rng(2**127)}
    assert repo.cas("sid", None, session, {"events/first": {"kind": "consent"}})
    assert not repo.cas("sid", None, session, {})
    assert not repo.cas("sid", 99, session, {})
    assert repo.cas("sid", 0, session, {})
    stored = module.decode(database["studies/study/sessions/sid"])
    assert stored["revision"] == 1 and stored["rng"] == session["rng"]
