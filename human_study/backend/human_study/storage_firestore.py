"""Firestore Native mode; all side effects are outside retryable transactions."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac

from google.cloud import firestore

from .storage import Snapshot, Conflict


# Firestore reserves field names matching __.*__, even in nested maps.
# Use an ordinary field name for the decimal representation of 128-bit PCG64
# integers. Keep decoding the legacy form for previously serialized snapshots.
BIGINT_FIELD = "dtag_bigint_decimal"
LEGACY_BIGINT_FIELD = "__dtag_bigint__"


def encode(value):
    # PCG64 uses unsigned 128-bit integers; Firestore integers are signed 64-bit.
    if isinstance(value, int) and not isinstance(value, bool) and not -(2**63) <= value < 2**63:
        return {BIGINT_FIELD: str(value)}
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [encode(v) for v in value]
    return value


def decode(value):
    if isinstance(value, dict):
        if len(value) == 1 and BIGINT_FIELD in value:
            return int(value[BIGINT_FIELD])
        if len(value) == 1 and LEGACY_BIGINT_FIELD in value:
            return int(value[LEGACY_BIGINT_FIELD])
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


class FirestoreRepository:
    durable = True
    COLLECTIONS = ("questions", "events", "exports", "requests")

    def __init__(self, study_id, database="(default)", client=None):
        self.client = client if client is not None else firestore.Client(database=database)
        self.root = self.client.collection("studies").document(study_id)

    def ref(self, sid):
        return self.root.collection("sessions").document(sid)

    @staticmethod
    def _read_collection(ref, collection):
        """Read one independent record collection over the existing gRPC client."""
        return {
            f"{collection}/{doc.id}": decode(doc.to_dict())
            for doc in ref.collection(collection).stream()
        }

    def read(self, sid):
        ref = self.ref(sid)
        # A writer commits both its revision and all record writes atomically.
        # Keep BOTH revision reads and the retry loop: overlapping independent
        # collection streams must never result in a torn scientific snapshot.
        # Firestore's gRPC client can be shared by threads. This changes only
        # transport overlap, not ordering, query scope, or stored values.
        for _ in range(8):
            before = ref.get()
            if not before.exists:
                raise KeyError(sid)
            with ThreadPoolExecutor(max_workers=len(self.COLLECTIONS)) as pool:
                batches = list(pool.map(
                    lambda collection: self._read_collection(ref, collection),
                    self.COLLECTIONS,
                ))
            records = {}
            for batch in batches:
                records.update(batch)
            after = ref.get()
            if before.to_dict()["revision"] == after.to_dict()["revision"]:
                return Snapshot(decode(after.to_dict()), records)
        raise Conflict("session is busy; retry")

    def cas(self, sid, revision, session, writes):
        ref = self.ref(sid)
        transaction = self.client.transaction()

        @firestore.transactional
        def commit(tx):
            old = ref.get(transaction=tx)
            if (not old.exists and revision is not None) or (old.exists and old.to_dict()["revision"] != revision):
                return False
            new = dict(session, revision=0 if revision is None else revision + 1,
                       committed_at=firestore.SERVER_TIMESTAMP)
            tx.set(ref, encode(new))
            for path, value in writes.items():
                collection, key = path.split("/", 1)
                if collection not in self.COLLECTIONS or "/" in key:
                    raise ValueError("invalid internal document path")
                tx.set(ref.collection(collection).document(key), encode(value))
            return True

        return commit(transaction)

    def has_prior_prolific_consent(self, pid, study_ids, sid_key):
        """Check prior enrollments by deterministic HMAC ID; no full-study scan."""
        for old_study_id in study_ids:
            key = hmac.new(sid_key, f"{old_study_id}\x00{pid}".encode(),
                           hashlib.sha256).hexdigest()[:32]
            doc = (self.client.collection("studies").document(old_study_id)
                   .collection("sessions").document(key).get())
            if doc.exists and (doc.to_dict() or {}).get("consent_accepted") is True:
                return True
        return False

    def probe(self):
        # Fail on absent database or unusable ADC; no participant data returned.
        list(self.root.collection("readiness").limit(1).stream())
