"""Transactional orchestration with an explicit Firestore -> GCS outbox.

Every answer is accepted once by CAS, then exported, then acknowledged. No next
question is exposed until all pending exports have been verified and committed.
All expensive/native/LLM/GCS operations happen outside transactions.
"""
from __future__ import annotations

import copy
import secrets
import time
import uuid
from datetime import datetime, timezone

from .policy import POLICIES, choose_next_item, initial_rng
from .state import HumanDTAGState, Observation, apply_observed_answer, initialize_human_state, validate_observation
from .storage import Conflict, IntegrityError
from .study_config import digest


def now():
    return datetime.now(timezone.utc).isoformat()


class ExportPending(RuntimeError):
    pass


class GenerationPending(RuntimeError):
    pass


class StudyService:
    def __init__(self, config, adapter, llm, repository, archive, *, failure_hook=None):
        self.config, self.adapter, self.llm = config, adapter, llm
        self.repo, self.archive = repository, archive
        self.hook = failure_hook or (lambda point: None)
        self.adapter.validate_config(config)

    def _load(self, sid):
        snap = self.repo.read(sid)
        if snap.session["config_hash"] != self.config.config_hash or snap.session["provenance_hash"] != digest(self.adapter.provenance):
            raise Conflict("this session uses a different instrument/model/code version; investigator assistance is required")
        return snap

    def _write(self, snap, writes):
        snap.session["updated_at"] = now()
        return self.repo.cas(snap.session["session_id"], snap.session["revision"], snap.session, writes)

    def _export(self, session, writes, eid, payload, name=None):
        payload = {"schema_version": "1", "study_id": self.config.study_id,
                   "session_id": session["session_id"], "config_hash": self.config.config_hash,
                   "provenance": self.adapter.provenance, **payload}
        payload["content_sha256"] = digest(payload)
        name = name or f"studies/{self.config.study_id}/sessions/{session['session_id']}/events/{eid}.json"
        key = f"exports/{eid}"
        writes[key] = {"status": "pending", "object_name": name, "payload": payload}
        session["pending_exports"] = list(session.get("pending_exports", [])) + [key]
        # Semantic event log is a subcollection, never an ever-growing session field.
        writes[f"events/{eid}"] = {"event_id": eid, "kind": payload.get("kind"), "timestamp": payload.get("timestamp"),
                                   "gcs_object_name": name, "content_sha256": payload["content_sha256"]}

    def start(self, sid=None):
        if sid:
            return self.current(sid)
        sid = uuid.uuid4().hex
        session = {"session_id": sid, "phase": "consent", "status": "active", "revision": 0,
                   "created_at": now(), "updated_at": now(), "config_hash": self.config.config_hash,
                   "provenance_hash": digest(self.adapter.provenance), "policy": None, "state": None,
                   "phase_index": 0, "next_step": 0, "pending_exports": [], "current_question_id": None,
                   "assignment_rng_state": None, "selection_rng_state": None, "receipt": None}
        if not self.repo.cas(sid, None, session, {}):
            raise Conflict("unable to enroll session")
        return self.current(sid)

    def reconcile(self, sid):
        for _ in range(100):
            snap = self._load(sid)
            pending = snap.session["pending_exports"]
            if not pending:
                return snap
            key = pending[0]
            record = snap.records[key]
            try:
                self.hook("before_gcs_create")
                self.archive.put(record["object_name"], record["payload"])
                self.hook("after_gcs_create")
            except IntegrityError:
                raise
            except Exception as exc:
                raise ExportPending("answer/state saved; research archive synchronization pending; retry") from exc
            snap = self._load(sid)
            if key not in snap.session["pending_exports"]:
                continue
            snap.session["pending_exports"].remove(key)
            current = copy.deepcopy(snap.records[key])
            current["status"] = "committed"
            self.hook("before_export_commit")
            if self._write(snap, {key: current}):
                self.hook("after_export_commit")
        raise Conflict("export reconciliation busy; retry")

    def consent(self, sid, accepted, expected_version):
        snap = self.reconcile(sid)
        s = snap.session
        if s["phase"] != "consent":
            if accepted and s.get("consent_version") == self.config.consent_version:
                return self.current(sid)
            raise Conflict("consent already recorded")
        if s["revision"] != expected_version:
            raise Conflict("session changed; refresh and retry")
        s.update(phase="baseline" if accepted else "declined", consent_version=self.config.consent_version,
                 consent_timestamp=now(), consent_accepted=accepted)
        writes = {}
        self._export(s, writes, "consent", {"kind": "consent", "timestamp": s["consent_timestamp"],
                     "accepted": accepted, "consent_version": self.config.consent_version,
                     "consent_text": self.config.consent_text})
        if not self._write(snap, writes):
            raise Conflict("concurrent consent; retry")
        return self.current(sid)

    def _human_state(self, snap):
        data = copy.deepcopy(snap.session["state"])
        observations = []
        for q in sorted((v for k, v in snap.records.items() if k.startswith("questions/")), key=lambda q: q["ordinal"]):
            if q["status"] == "answered" and q["phase"] in ("baseline", "intervention"):
                if self.config.response_mode == "free_text_multi":
                    for assignment in q.get("accepted_assignments", []):
                        observations.append(Observation(q["question_id"], assignment["variable"],
                                                        assignment["native_value"], q["phase"]))
                else:
                    observations.append(Observation(q["question_id"], q["target_variable"], q["response_value"],
                                                    q["phase"], q.get("missing_reason")))
        data["observations"] = tuple(observations)
        for key in ("asked_ids", "excluded_ids", "reserved_outcome_ids"):
            data[key] = tuple(data[key])
        return HumanDTAGState(**data)

    def _compact(self, state):
        data = state.as_dict()
        data.pop("observations")
        return data

    def _baseline_completed(self, snap, writes):
        s = snap.session
        records = {**snap.records, **writes}
        qs = sorted((q for k, q in records.items() if k.startswith("questions/") and q["phase"] == "baseline"),
                    key=lambda q: q["ordinal"])
        if self.config.response_mode == "free_text_multi":
            from .multi_observations import initial_state
            state = initial_state(self.config, self.adapter, s["session_id"], qs)
        else:
            obs = [Observation(q["question_id"], q["target_variable"], q["response_value"], "baseline", q.get("missing_reason")) for q in qs]
            state = initialize_human_state(self.config.model_key, obs, self.config, self.adapter, s["session_id"])
        seed = secrets.randbits(128)
        # The randomization result, seed and scheme are persisted atomically with baseline acceptance.
        import numpy as np
        bit = np.random.PCG64(seed)
        before = bit.state
        policy = POLICIES[int(np.random.Generator(bit).integers(4))]
        s.update(state=self._compact(state), policy=policy, assignment_rng_state=bit.state,
                 selection_rng_state=initial_rng(secrets.randbits(128)), phase="intervention", phase_index=0)
        self._export(s, writes, "assignment", {"kind": "randomization", "timestamp": now(),
                      "policy": policy, "rng_before": before, "rng_after": bit.state,
                      "scheme": "unstratified-uniform-four-arm-v1", "baseline_index": state.baseline_index,
                      "initial_observed_state": dict(state.initial_observed_state)})

    def _prepare_question(self, snap):
        s = snap.session
        phase = s["phase"]
        selection = None
        if phase == "attention":
            check = self.config.attention_checks[s["phase_index"]]
            qid = digest([s["session_id"], phase, s["phase_index"], check.check_id])[:32]
            return {
                "question_id": qid, "target_variable": check.check_id,
                "phase": phase, "step": s["phase_index"], "ordinal": s["next_step"],
                "status": "generating", "original_wording": check.instruction,
                "choices": [], "required": True, "item_version": check.version,
                "selection": None, "conditional_distribution": {}, "policy": s["policy"],
                "generation_token": uuid.uuid4().hex,
                "generation_lease_until": time.time() + 150, "created_at": now(),
            }, None
        if phase == "intervention":
            state = self._human_state(snap)
            selection = choose_next_item(state, s["policy"], set(), s["selection_rng_state"], self.config, self.adapter)
            if selection["status"] == "no_candidate":
                return None, selection["reason"]
            item = self.config.item(selection["variable"])
            dist = {r["answer"]: r["conditional_probability"] for r in selection["per_answer"]}
        else:
            item = self.config.bank(phase)[s["phase_index"]]
            observed = s["state"]["observed_state"] if s["state"] else {
                q["target_variable"]: q["response_value"] for k, q in snap.records.items()
                if k.startswith("questions/") and q["phase"] == "baseline" and q["status"] == "answered" and q["response_value"] is not None}
            dist = self.adapter.distributions(observed, [item.item_id]).get(item.item_id, {})
        qid = digest([s["session_id"], phase, s["phase_index"], item.item_id])[:32]
        return {"question_id": qid, "target_variable": item.item_id, "phase": phase,
                "step": s["phase_index"], "ordinal": s["next_step"], "status": "generating",
                "original_wording": item.original_wording, "choices": [c.model_dump() for c in item.choices],
                "required": item.required, "item_version": item.version, "selection": selection,
                "conditional_distribution": dist, "policy": s["policy"],
                "generation_token": uuid.uuid4().hex, "generation_lease_until": time.time() + 150,
                "created_at": now()}, None

    def _render_claimed(self, sid, question):
        item = None if question["phase"] == "attention" else self.config.item(question["target_variable"])
        try:
            if question["phase"] == "attention":
                rendered = self.llm.generate_attention(
                    self.config.attention_checks[question["step"]])
            # Adaptive items always use the LLM. Any nonadaptive item known to
            # contain a source fragment must also be completed, not displayed raw.
            elif self.config.question_mode == "llm_required" or item.phase == "intervention" or item.source_text_incomplete:
                rendered = self.llm.generate(item)
            else:
                rendered = {"displayed_wording": item.original_wording, "question_provenance": {
                    "provider": "canonical-common-instrument", "item_version": item.version,
                    "source_text_incomplete": False, "fallback": False}}
            if (item is None or item.source_text_incomplete or self.config.question_mode == "llm_required") and (
                rendered.get("question_provenance", {}).get("fallback", True) or
                rendered.get("displayed_wording", "").strip() == question["original_wording"].strip()
            ):
                raise ValueError("LLM did not complete an incomplete source question")
        except Exception as exc:
            if item is None or item.source_text_incomplete or self.config.question_mode == "llm_required":
                # Never show source/fallback in V2. Persist a short generation
                # retry lease so the participant can resume after an LLM outage.
                for _ in range(10):
                    snap = self._load(sid)
                    key = f"questions/{question['question_id']}"
                    q = snap.records.get(key)
                    if not q or q.get("generation_token") != question["generation_token"] or q["status"] != "generating":
                        return
                    q = {**q, "generation_lease_until": time.time() + 10,
                         "generation_failure_count": q.get("generation_failure_count", 0) + 1,
                         "last_generation_error": type(exc).__name__}
                    if self._write(snap, {key: q}):
                        raise GenerationPending("a complete question could not be prepared; retry shortly") from exc
                raise Conflict("question generation is busy; retry")
            rendered = {"displayed_wording": item.original_wording, "question_provenance": {
                "provider": "fallback", "fallback": True, "fallback_reason": "generation failed", "input_item_id": item.item_id}}
        for _ in range(10):
            snap = self._load(sid)
            key = f"questions/{question['question_id']}"
            q = snap.records.get(key)
            if not q or q.get("generation_token") != question["generation_token"] or q["status"] != "generating":
                return
            q = {**q, **rendered, "status": "presented", "presented_at": now()}
            writes = {key: q}
            folder = {"baseline": "baseline", "intervention": "questions", "outcome": "outcomes", "attention": "attention"}[q["phase"]]
            name = f"studies/{self.config.study_id}/sessions/{sid}/{folder}/{q['question_id']}-presented.json"
            self._export(snap.session, writes, q["question_id"] + "-presented",
                         {"kind": "question_presented", "timestamp": q["presented_at"], "question": q}, name)
            if self._write(snap, writes):
                return
        raise Conflict("question rendering busy; retry")

    def current(self, sid):
        for _ in range(20):
            snap = self.reconcile(sid)
            s = snap.session
            if s["phase"] in ("consent", "declined", "ready_to_complete", "complete"):
                return self.public(snap)
            qid = s.get("current_question_id")
            if qid:
                q = snap.records[f"questions/{qid}"]
                if q["status"] == "presented":
                    return self.public(snap)
                if q["status"] == "generating":
                    if q["generation_lease_until"] > time.time():
                        raise GenerationPending("question preparation in progress; retry shortly")
                    q = {**q, "generation_token": uuid.uuid4().hex, "generation_lease_until": time.time() + 150}
                    if self._write(snap, {f"questions/{qid}": q}):
                        self._render_claimed(sid, q)
                    continue
            question, reason = self._prepare_question(snap)
            if question is None:
                s.update(phase="attention" if self.config.attention_checks else
                               "outcome" if self.config.bank("outcome") else "ready_to_complete",
                         phase_index=0, no_candidate_reason=reason)
                writes = {}
                self._export(s, writes, "no-candidate", {"kind": "no_candidate", "reason": reason, "timestamp": now()})
                self._write(snap, writes)
                continue
            s["current_question_id"] = question["question_id"]
            if question["selection"]:
                s["selection_rng_state"] = question["selection"]["rng_state"]
            if self._write(snap, {f"questions/{question['question_id']}": question}):
                self._render_claimed(sid, question)
        raise Conflict("session busy; retry")

    def _answer_attention(self, snap, question, request, request_key, fingerprint):
        """Record a V3 attention response; never use it for model conditioning."""
        import re
        if request.get("answer_value") is not None or request.get("missing_reason") is not None:
            raise ValueError("attention check requires a written response")
        raw = request.get("text_answer")
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("Please write your response before continuing.")
        check = self.config.attention_checks[question["step"]]
        passed = bool(re.search(r"\\b" + re.escape(check.expected_token) + r"\\b",
                                raw, flags=re.IGNORECASE))
        q = {**question, "status": "answered", "raw_text_response": raw,
             "response_value": None, "missing_reason": None,
             "response_interpretation": {
                 "status": "attention_check", "method": "exact_token_v3",
                 "attention_passed": passed, "check_id": check.check_id,
             },
             "attention_passed": passed, "accepted_assignments": [],
             "response_timestamp": now(), "response_elapsed_seconds": max(
                 0, (datetime.now(timezone.utc) -
                     datetime.fromisoformat(question["presented_at"])).total_seconds()),
             }
        session = snap.session
        session["current_question_id"] = None
        session["phase_index"] += 1
        session["next_step"] += 1
        if session["phase_index"] == len(self.config.attention_checks):
            session.update(
                phase="outcome" if self.config.bank("outcome") else "ready_to_complete",
                phase_index=0,
            )
        result = {"question_id": q["question_id"], "accepted": True,
                  "accepted_at": q["response_timestamp"]}
        writes = {f"questions/{q['question_id']}": q,
                  request_key: {"fingerprint": fingerprint, "result": result}}
        name = (f"studies/{self.config.study_id}/sessions/{session['session_id']}"
                f"/attention/{q['question_id']}.json")
        self._export(session, writes, q["question_id"] + "-answer",
                     {"kind": "answer_accepted", "timestamp": now(),
                      "question": q, "policy": session["policy"]}, name)
        self.hook("before_answer_transaction")
        if self._write(snap, writes):
            self.hook("after_answer_transaction")
            return {"accepted": result, "current": self.current(session["session_id"])}
        raise Conflict("concurrent attention-check response; retry")

    def answer(self, sid, request):
        fingerprint = digest({k: request.get(k) for k in
                              ("question_id", "answer_value", "text_answer", "missing_reason")})
        request_key = "requests/" + digest(request["idempotency_key"])
        for _ in range(10):
            snap = self._load(sid)
            s = snap.session
            previous = snap.records.get(request_key)
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise Conflict("idempotency key was already used for a different answer")
                return {"accepted": previous["result"], "current": self.current(sid)}
            if s["pending_exports"]:
                self.reconcile(sid)
                continue
            if s["revision"] != request["expected_session_version"] or s["current_question_id"] != request["question_id"]:
                raise Conflict("stale or out-of-order question; refresh before answering")
            key = f"questions/{request['question_id']}"
            q = copy.deepcopy(snap.records[key])
            if q["status"] != "presented":
                raise Conflict("question is not awaiting an answer")
            if q["phase"] == "attention":
                return self._answer_attention(snap, q, request, request_key, fingerprint)
            item = self.config.item(q["target_variable"])
            raw_answer, interpretation = None, None
            accepted_assignments = []
            if self.config.response_mode == "free_text_multi":
                if request.get("answer_value") is not None or request.get("missing_reason") is not None:
                    raise ValueError("V3 requires written responses, not preselected categories")
                raw_answer = request.get("text_answer")
                if not isinstance(raw_answer, str) or not raw_answer.strip():
                    raise ValueError("Please write your response before continuing.")
                from .multi_observations import (
                    permitted_items, prior_baseline_assignments, resolve, apply,
                )
                candidates = permitted_items(self.config, self.adapter)
                existing = (self._human_state(snap).observed_state
                            if q["phase"] == "intervention"
                            else prior_baseline_assignments(snap))
                proposed = self.llm.interpret_multi(
                    q["displayed_wording"], raw_answer, list(candidates.values()))
                interpretation = resolve(proposed, raw_answer, candidates, existing,
                                         self.adapter, self.config.minimum_mapping_confidence)
                accepted_assignments = interpretation["accepted"]
                native = next((row["native_value"] for row in accepted_assignments
                               if row["variable"] == q["target_variable"]), None)
                missing = "prefer_not_to_answer" if interpretation["status"] == "missing" else None
            elif self.config.response_mode == "free_text_llm":
                if request.get("answer_value") is not None or request.get("missing_reason") is not None:
                    raise ValueError("V2 requires a written response, not a preselected category")
                raw_answer = request.get("text_answer")
                if not isinstance(raw_answer, str) or not raw_answer.strip():
                    raise ValueError("Please write your response before continuing.")
                native, missing, interpretation = self.llm.interpret(
                    item, q["displayed_wording"], raw_answer)
            else:
                if request.get("text_answer") is not None:
                    raise ValueError("This version requires a category selection")
                native, missing = request["answer_value"], request["missing_reason"]
            obs = Observation(q["question_id"], q["target_variable"], native, q["phase"], missing)
            if self.config.response_mode != "free_text_multi":
                validate_observation(obs, item, self.adapter)
            result = {"question_id": q["question_id"], "accepted": True}
            if q["phase"] == "intervention":
                if self.config.response_mode == "free_text_multi":
                    new_state, scientific_result = apply(
                        self._human_state(snap), q, accepted_assignments, self.adapter)
                else:
                    new_state, scientific_result = apply_observed_answer(
                        self._human_state(snap), q, obs.native_value,
                        self.adapter, self.config, missing_reason=obs.missing_reason)
                s["state"] = self._compact(new_state)
                q["index_result"] = scientific_result
            q.update(status="answered", response_value=obs.native_value, missing_reason=obs.missing_reason,
                     accepted_assignments=accepted_assignments if self.config.response_mode == "free_text_multi" else None,
                     raw_text_response=raw_answer, response_interpretation=interpretation,
                     response_timestamp=now(), response_elapsed_seconds=max(0, (datetime.now(timezone.utc) -
                         datetime.fromisoformat(q["presented_at"])).total_seconds()))
            result["accepted_at"] = q["response_timestamp"]
            s["current_question_id"] = None
            s["phase_index"] += 1
            s["next_step"] += 1
            writes = {key: q, request_key: {"fingerprint": fingerprint, "result": result}}
            folder = {"baseline": "baseline", "intervention": "questions", "outcome": "outcomes", "attention": "attention"}[q["phase"]]
            name = f"studies/{self.config.study_id}/sessions/{sid}/{folder}/{q['question_id']}.json"
            self._export(s, writes, q["question_id"] + "-answer", {"kind": "answer_accepted", "timestamp": now(),
                          "question": q, "policy": s["policy"]}, name)
            if q["phase"] == "baseline" and s["phase_index"] == len(self.config.bank("baseline")):
                self._baseline_completed(snap, writes)
            elif q["phase"] == "intervention" and s["phase_index"] == self.config.intervention_steps:
                s.update(
                    phase="attention" if self.config.attention_checks else
                          "outcome" if self.config.bank("outcome") else "ready_to_complete",
                    phase_index=0,
                )
            elif q["phase"] == "outcome" and s["phase_index"] == len(self.config.bank("outcome")):
                s.update(phase="ready_to_complete", phase_index=0)
            self.hook("before_answer_transaction")
            if self._write(snap, writes):
                self.hook("after_answer_transaction")
                return {"accepted": result, "current": self.current(sid)}
        raise Conflict("concurrent submission; refresh and retry")

    def complete(self, sid):
        for _ in range(10):
            snap = self.reconcile(sid)
            s = snap.session
            if s["phase"] == "complete":
                return self.public(snap)
            if s["phase"] != "ready_to_complete":
                raise Conflict("required study phases are incomplete")
            if s.get("receipt"):
                # final.json was reconciled successfully. Only now expose completion.
                s.update(phase="complete", completion_status="archived")
                if self._write(snap, {}):
                    return self.current(sid)
                continue
            s["receipt"] = secrets.token_hex(6).upper()
            s["completed_at"] = now()
            questions = sorted((q for k, q in snap.records.items() if k.startswith("questions/")), key=lambda q: q["ordinal"])
            references = [v["object_name"] for k, v in snap.records.items() if k.startswith("exports/")]
            if any(q["status"] != "answered" for q in questions):
                raise IntegrityError("unanswered question at finalization")
            writes = {}
            payload = {"kind": "session_final", "timestamp": s["completed_at"], "receipt": s["receipt"],
                       "policy": s["policy"], "consent_version": s["consent_version"],
                       "baseline_index": s["state"]["baseline_index"], "final_index": s["state"]["current_index"],
                       "questions": questions, "source_objects": references, "study_configuration": self.config.model_dump(mode="json")}
            self._export(s, writes, "final", payload, f"studies/{self.config.study_id}/sessions/{sid}/final.json")
            if self._write(snap, writes):
                continue
        raise Conflict("completion busy; retry")

    def public(self, snap):
        s = snap.session
        phase = s["phase"]
        q = snap.records.get(f"questions/{s.get('current_question_id')}")
        public_q = None
        if q and q["status"] == "presented" and not s["pending_exports"]:
            public_q = {"question_id": q["question_id"], "text": q["displayed_wording"],
                        "choices": [{"value": c["native_value"], "label": c["display_label"]} for c in q["choices"]],
                        "required": q["required"], "response_mode": self.config.response_mode}
        total = (len(self.config.bank("baseline")) + self.config.intervention_steps +
                 len(self.config.bank("outcome")) + len(self.config.attention_checks))
        return {"session_id": s["session_id"], "phase": phase, "session_version": s["revision"],
                "question": public_q, "progress": {"completed": s["next_step"], "total": total},
                "consent": self.config.consent_text if phase == "consent" else None,
                "receipt": s["receipt"] if phase == "complete" else None}
