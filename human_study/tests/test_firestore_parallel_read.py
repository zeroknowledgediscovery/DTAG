"""Non-network correctness and controlled I/O-latency benchmark of Firestore reads.

The fake models four independent collection RPCs, optimistic revision checks,
and a concurrent revision change. No Google Cloud project or human data needed.
"""
from __future__ import annotations

import copy
import threading
import time

import pytest

from human_study.storage import Conflict
from human_study.storage_firestore import FirestoreRepository, encode


class Document:
    def __init__(self, key, payload):
        self.id = key
        self._payload = payload

    def to_dict(self):
        return copy.deepcopy(self._payload)


class SessionRef:
    def __init__(self, collections=None, *, latency=0.0, fail_once=False,
                 conflict_forever=False, present=True):
        self.collections = collections or {
            "questions": {"q1": {"target_variable": "colmslm", "ordinal": 1}},
            "events": {"ev1": {"kind": "question_presented"}},
            "exports": {"ex1": {"status": "committed"}},
            "requests": {"rq1": {"fingerprint": "identical"}},
        }
        self.latency = latency
        self.get_calls = 0
        self.fail_once = fail_once
        self.conflict_forever = conflict_forever
        self.present = present
        self.lock = threading.Lock()
        self.active_streams = 0
        self.max_active_streams = 0

    def get(self):
        with self.lock:
            self.get_calls += 1
            number = self.get_calls
            if self.conflict_forever:
                revision = number
            elif self.fail_once:
                revision = 1 if number == 1 else 2
            else:
                revision = 1
        result = Document("session", {
            "revision": revision,
            "session_id": "session-example",
            "rng_state": encode(2**127),
        })
        result.exists = self.present
        return result

    def collection(self, name):
        return CollectionRef(self, name)


class CollectionRef:
    def __init__(self, parent, name):
        self.parent, self.name = parent, name

    def stream(self):
        p = self.parent
        with p.lock:
            p.active_streams += 1
            p.max_active_streams = max(p.max_active_streams, p.active_streams)
        try:
            if p.latency:
                time.sleep(p.latency)
            for key, payload in p.collections.get(self.name, {}).items():
                yield Document(key, payload)
        finally:
            with p.lock:
                p.active_streams -= 1


class FakeParent:
    def __init__(self, ref):
        self._ref = ref

    def document(self, name):
        assert name in ("s", "test-study")
        return self if name == "test-study" else self._ref

    def collection(self, _name):
        return self


class FakeClient:
    def __init__(self, ref):
        self.ref = ref

    def collection(self, name):
        assert name == "studies"
        return FakeParent(self.ref)


def repo(ref):
    return FirestoreRepository("test-study", client=FakeClient(ref))


def test_parallel_snapshot_preserves_all_record_paths_and_native_rng_values():
    ref = SessionRef()
    snap = repo(ref).read("s")
    assert set(snap.records) == {
        "questions/q1", "events/ev1", "exports/ex1", "requests/rq1",
    }
    assert snap.session["rng_state"] == 2**127
    assert snap.session["revision"] == 1
    assert snap.records["questions/q1"]["target_variable"] == "colmslm"
    assert ref.max_active_streams >= 1
    assert ref.get_calls == 2


def test_parallel_snapshot_restarts_when_revision_changed_mid_read():
    ref = SessionRef(fail_once=True)
    snap = repo(ref).read("s")
    assert ref.get_calls == 4  # before/after, then retry before/after
    assert snap.session["revision"] == 2


def test_parallel_snapshot_fails_closed_on_continuous_concurrent_writes():
    ref = SessionRef(conflict_forever=True)
    with pytest.raises(Conflict, match="session is busy"):
        repo(ref).read("s")
    assert ref.get_calls == 16


def test_parallel_snapshot_missing_session_remains_key_error():
    ref = SessionRef(present=False)
    with pytest.raises(KeyError, match="'s'"):
        repo(ref).read("s")
    assert ref.get_calls == 1


def test_parallel_snapshot_propagates_collection_rpc_failures():
    ref = SessionRef()
    original = ref.collection

    class BrokenCollection:
        def stream(self):
            raise OSError("simulated Firestore RPC outage")
            yield  # pragma: no cover: keeps this an iterator

    ref.collection = lambda name: BrokenCollection() if name == "exports" else original(name)
    with pytest.raises(OSError, match="simulated Firestore RPC outage"):
        repo(ref).read("s")


def test_simulated_latency_parallel_vs_original_serial(capsys):
    """Controlled I/O only: demonstrates mechanism, not actual GCP latency."""
    ref = SessionRef(latency=0.05)
    t0 = time.perf_counter()
    original = {
        f"{collection}/{d.id}": d.to_dict()
        for collection in FirestoreRepository.COLLECTIONS
        for d in ref.collection(collection).stream()
    }
    serial_seconds = time.perf_counter() - t0
    t1 = time.perf_counter()
    snapshot = repo(ref).read("s")
    parallel_seconds = time.perf_counter() - t1
    assert snapshot.records == original
    assert ref.max_active_streams >= 2  # independent Firestore reads do overlap
    print(
        f"Simulated four 50ms Firestore streams: "
        f"serial={serial_seconds:.3f}s; parallel={parallel_seconds:.3f}s; "
        f"ratio={serial_seconds / parallel_seconds:.2f}x"
    )
    # No timing threshold: CI CPU scheduling does not represent Cloud Run.
