"""Transactional orchestration with an explicit Firestore -> GCS outbox.

Every answer is accepted once by CAS, then exported, then acknowledged. No next
question is exposed until all pending exports have been verified and committed.
All expensive/native/LLM/GCS operations happen outside transactions.
"""
from __future__ import annotations

import copy
import re
import secrets
import time
import uuid
from datetime import datetime, timezone

from .policy import POLICIES, choose_next_item, initial_rng
from .quality_review import summarize_quality
from .rejection_eligibility import assess_rejection_eligibility
from .state import HumanDTAGState, Observation, apply_observed_answer, initialize_human_state, validate_observation
from .storage import Conflict, IntegrityError
from .study_config import digest


def now():
    return datetime.now(timezone.utc).isoformat()


class ExportPending(RuntimeError):
    pass


class GenerationPending(RuntimeError):
    pass


def verbatim_attention(check):
    return {"displayed_wording": check.instruction, "question_provenance": {
        "provider": "verbatim-attention", "check_id": check.check_id, "kind": check.kind,
        "item_version": check.version, "fallback": False}}


def _normalized(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def response_quality(question, records, settings):
    """Review flags for one written answer; never used for scoring or the LSM.

    fast: answered within settings.fast_seconds of being presented.
    short: fewer than settings.short_words words (substantive answers only).
    duplicate_of: an earlier substantive answer whose normalized text is at
    least settings.duplicate_similarity similar (copy/paste or canned replies).
    """
    from difflib import SequenceMatcher
    text = _normalized(question.get("raw_text_response") or "")
    words = len(text.split())
    substantive = question["phase"] != "attention"
    duplicate = None
    if substantive and text:
        earlier = sorted((r for k, r in records.items() if k.startswith("questions/")
                          and r.get("status") == "answered" and r["phase"] != "attention"
                          and r["question_id"] != question["question_id"]
                          and r.get("raw_text_response")), key=lambda r: r["ordinal"])
        for r in earlier:
            if SequenceMatcher(None, text, _normalized(r["raw_text_response"])).ratio() >= settings.duplicate_similarity:
                duplicate = r["question_id"]
                break
    elapsed = question.get("response_elapsed_seconds") or 0.0
    return {"characters": len(question.get("raw_text_response") or ""), "words": words,
            "elapsed_seconds": elapsed, "fast": elapsed < settings.fast_seconds,
            "short": substantive and words < settings.short_words,
            "duplicate_of": duplicate}


class StudyService:
    def __init__(self, config, adapter, llm, repository, archive, *, failure_hook=None,
                 prolific_required=None, sid_key=None):
        self.config, self.adapter, self.llm = config, adapter, llm
        self.repo, self.archive = repository, archive
        self.hook = failure_hook or (lambda point: None)
        # Whether a PROLIFIC_PID is mandatory; app.py relaxes this in local mode.
        self.prolific_required = (config.prolific is not None and config.prolific.required
                                  if prolific_required is None else prolific_required)
        # Secret for deriving one session per Prolific participant (cookie secret in deployments).
        self.sid_key = (sid_key or "local-unkeyed").encode()
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

    def _route_attention_if_due(self, session):
        """Enter a V3 check at an answer boundary, preserving next scientific step.

        The cursor and resume target are persisted atomically with the preceding
        answer. 'next_step' counts displayed questions; attention_completed
        removes check responses to recover the substantive-answer boundary.
        """
        if self.config.response_mode != "free_text_multi":
            return
        if session["phase"] in ("consent", "declined", "complete", "attention"):
            return
        cursor = session.get("attention_cursor", 0)
        if cursor >= len(self.config.attention_checks):
            return
        count = session["next_step"] - session.get("attention_completed", 0)
        due = self.config.attention_position(self.config.attention_checks[cursor])
        if due < count:
            raise IntegrityError("attention schedule was skipped")
        if due == count:
            session["resume_phase"] = session["phase"]
            session["resume_phase_index"] = session["phase_index"]
            session["phase"] = "attention"
            session["phase_index"] = cursor

    def prolific_sid(self, pid):
        """One session per Prolific participant: a returning PID resumes, never re-enrolls."""
        import hmac
        message = f"{self.config.study_id}\x00{pid}".encode()
        return hmac.new(self.sid_key, message, "sha256").hexdigest()[:32]

    def start(self, sid=None, prolific=None, *, fresh=False):
        """Resume normally; an explicit fresh start creates a distinct session.

        Both staging and production use the same semantics. A new attempt
        retains Prolific linkage but does not overwrite previous archives.
        """
        prolific = {k: v for k, v in (prolific or {}).items() if v} or None
        pid = prolific.get("prolific_pid") if prolific else None
        if fresh:
            sid = None
        if sid:
            try:
                existing = self._load(sid).session.get("prolific") or {}
            except KeyError:
                existing, sid = {}, None
            # A different PID in the link (shared browser) gets that participant's own session.
            if sid and (pid is None or existing.get("prolific_pid") == pid):
                return self.current(sid)
        if self.prolific_required and not pid:
            raise ValueError("Please open this study using the link provided on Prolific.")
        if pid and self.config.prolific is not None and not fresh:
            sid = self.prolific_sid(pid)
            try:
                self.repo.read(sid)
                return self.current(sid)
            except KeyError:
                pass
        else:
            sid = uuid.uuid4().hex
        session = {"session_id": sid, "phase": "consent", "status": "active", "revision": 0,
                   "created_at": now(), "updated_at": now(), "config_hash": self.config.config_hash,
                   "provenance_hash": digest(self.adapter.provenance), "policy": None, "state": None,
                   "phase_index": 0, "next_step": 0, "pending_exports": [], "current_question_id": None,
                   "assignment_rng_state": None, "selection_rng_state": None, "receipt": None,
                   "prolific": prolific}
        # Consent has not yet been given; keep linkage in operational state,
        # but do not archive identifying enrollment data into research GCS.
        if not self.repo.cas(sid, None, session, {}):
            if pid:
                return self.current(sid)  # concurrent first request for the same PID
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
        if accepted:
            # Only consented participants have Prolific identifiers written to
            # the immutable research archive.
            if s.get("prolific"):
                self._export(s, writes, "enrollment",
                             {"kind": "enrollment", "timestamp": s["created_at"],
                              "prolific": s["prolific"]})
            self._route_attention_if_due(s)
        else:
            # Do not retain raw Prolific identifiers from a declined session.
            # The anonymized operational session permits the return-path page.
            s["prolific"] = None
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

    def _item_for(self, variable, phase):
        if phase == "intervention" and self.config.candidate_mode == "native_webapp":
            return self.adapter.dynamic_item(variable)
        return self.config.item(variable)

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
            generation_skips = set(s.get("generation_skipped_ids", ()))
            selection = choose_next_item(state, s["policy"], generation_skips, s["selection_rng_state"], self.config, self.adapter)
            if selection["status"] == "selected":
                # Replay must know which previously attempted questions could
                # not be rendered; this never changes the LSM conditioning.
                selection["generation_skipped_ids"] = sorted(generation_skips)
            if selection["status"] == "no_candidate":
                return None, selection["reason"]
            item = self._item_for(selection["variable"], "intervention")
            dist = {r["answer"]: r["conditional_probability"] for r in selection["per_answer"]}
        else:
            item = self.config.bank(phase)[s["phase_index"]]
            if self.config.response_mode == "free_text_multi" and not s["state"]:
                from .multi_observations import prior_baseline_assignments
                observed = prior_baseline_assignments(snap, allow_revision=self.config.candidate_mode == "native_webapp")
            else:
                observed = s["state"]["observed_state"] if s["state"] else {
                    q["target_variable"]: q["response_value"] for k, q in snap.records.items()
                    if k.startswith("questions/") and q["phase"] == "baseline"
                    and q["status"] == "answered" and q["response_value"] is not None}
            dist = self.adapter.distributions(observed, [item.item_id]).get(item.item_id, {})
        qid = digest([s["session_id"], phase, s["phase_index"], item.item_id])[:32]
        return {"question_id": qid, "target_variable": item.item_id, "phase": phase,
                "step": s["phase_index"], "ordinal": s["next_step"], "status": "generating",
                "original_wording": item.original_wording, "choices": [
                     c.model_dump() if hasattr(c, "model_dump")
                     else {"native_value": c.native_value, "display_label": c.display_label}
                     for c in item.choices],
                "required": item.required, "item_version": item.version, "selection": selection,
                "conditional_distribution": dist, "policy": s["policy"],
                "generation_token": uuid.uuid4().hex, "generation_lease_until": time.time() + 150,
                "created_at": now()}, None

    def _retire_invalid_adaptive_question(self, sid, question, failure_codes, error_name):
        """Retire one candidate for this session, without advancing the study.

        The abandoned item was NEVER displayed, answered or used to update
        the native state. It is archived as an audited generation failure,
        and the same policy/geometry selects the next eligible item.
        """
        for _ in range(10):
            snap = self._load(sid)
            key = f"questions/{question['question_id']}"
            q = snap.records.get(key)
            if (not q or q.get("generation_token") != question["generation_token"]
                    or q["status"] != "generating"):
                return
            failed = set(snap.session.get("generation_skipped_ids", ()))
            failed.add(q["target_variable"])
            snap.session["generation_skipped_ids"] = sorted(failed)
            snap.session["current_question_id"] = None
            record = {**q, "status": "generation_abandoned",
                      "generation_failure_count": q.get("generation_failure_count", 0) + 1,
                      "last_generation_error": error_name,
                      "last_generation_failure_codes": failure_codes}
            writes = {key: record}
            self._export(
                snap.session, writes, q["question_id"] + "-generation-abandoned",
                {"kind": "question_generation_abandoned", "timestamp": now(),
                 "phase": q["phase"], "target_variable": q["target_variable"],
                 "question_id": q["question_id"], "failure_codes": failure_codes,
                 "selection": q.get("selection")},
            )
            if self._write(snap, writes):
                return
        raise Conflict("generation-failure journaling busy; retry")

    def _render_claimed(self, sid, question):
        item = None if question["phase"] == "attention" else self._item_for(question["target_variable"], question["phase"])
        try:
            if question["phase"] == "attention":
                check = self.config.attention_checks[question["step"]]
                rendered = (verbatim_attention(check) if check.render == "verbatim"
                            else self.llm.generate_attention(check))
            # Adaptive items always use the LLM. Any nonadaptive item known to
            # contain a source fragment must also be completed, not displayed raw.
            elif self.config.question_mode == "llm_required" or item.phase == "intervention" or item.source_text_incomplete:
                rendered = self.llm.generate(item)
            else:
                rendered = {"displayed_wording": item.original_wording, "question_provenance": {
                    "provider": "canonical-common-instrument", "item_version": item.version,
                    "source_text_incomplete": False, "fallback": False}}
            provenance = rendered.get("question_provenance", {})
            verbatim = provenance.get("provider") == "verbatim-attention"
            # Only the question generator may grant this: it validates a
            # complete GSS source and records the exact provenance, rather
            # than silently displaying the old truncated semantic-map label.
            complete_source = (
                (
                    provenance.get("provider") == "source-validated"
                    and provenance.get("source_standalone_verified") is True
                    and provenance.get("validation_method") in {
                        "verified_2024_natenviy_source_fallback_v1",
                        "source_grounded_standalone_fallback_v1",
                        "native_map_validated_standalone_fallback_v1",
                    }
                ) or (
                    provenance.get("provider") == "compiled-source"
                    and provenance.get("validation_method") ==
                    "versioned_source_catalog_exact_match_v1"
                    and provenance.get("certification") in (
                        "source_contract", "human_reviewed",
                    )
                    and provenance.get("cache_hit") is True
                    and provenance.get("fallback") is False
                )
            )
            if (item is None or item.source_text_incomplete or self.config.question_mode == "llm_required") and not (verbatim or complete_source) and (
                provenance.get("fallback", True) or
                rendered.get("displayed_wording", "").strip() == question["original_wording"].strip()
            ):
                raise ValueError("Neither generated nor source-validated complete question available")
            if question["phase"] == "intervention" and self.config.candidate_mode == "native_webapp":
                # A different target can still produce the SAME respondent-
                # facing wording if an uncontracted LLM paraphrase drifts.
                # Check the actual historical display, not only variable IDs.
                from .questions import QuestionGenerationError
                candidate_text = _normalized(rendered["displayed_wording"])
                snap = self._load(sid)
                if candidate_text and any(
                    old.get("status") == "answered"
                    and old.get("phase") != "attention"
                    and _normalized(old.get("displayed_wording", "")) == candidate_text
                    for key, old in snap.records.items()
                    if key.startswith("questions/")
                ):
                    raise QuestionGenerationError(
                        "generated wording repeats an earlier displayed question",
                        attempts=[{"rejected": "identical_question_text_already_answered"}],
                    )
        except Exception as exc:
            if item is None or item.source_text_incomplete or self.config.question_mode == "llm_required":
                # Log only bounded error codes; never log model output or participant text.
                import logging
                failure_codes = [
                    str(a.get("error") or a.get("rejected") or "unknown")[:64]
                    for a in getattr(exc, "attempts", [])
                    if isinstance(a, dict)
                ][:3]
                logging.getLogger(__name__).warning(
                    "Question generation failed: study=%s phase=%s variable=%s error=%s codes=%s",
                    self.config.study_id, question["phase"], question["target_variable"],
                    type(exc).__name__, ",".join(failure_codes),
                )
                from .questions import QuestionGenerationError
                invalid_source = (
                    isinstance(exc, QuestionGenerationError) or
                    (isinstance(exc, ValueError) and str(exc) ==
                     "Neither generated nor source-validated complete question available")
                )
                if (invalid_source
                        and question["phase"] == "intervention"
                        and self.config.candidate_mode == "native_webapp"):
                    # A syntactically unrepairable fragment is *not* a reason
                    # to interrupt the participant. Journal it and ask the
                    # next ranked eligible GSS item at this same step.
                    self._retire_invalid_adaptive_question(
                        sid, question, failure_codes, type(exc).__name__
                    )
                    return
                # Baseline items cannot be swapped without changing the
                # instrument. Persist a lease for automatic internal retry.
                for _ in range(10):
                    snap = self._load(sid)
                    key = f"questions/{question['question_id']}"
                    q = snap.records.get(key)
                    if not q or q.get("generation_token") != question["generation_token"] or q["status"] != "generating":
                        return
                    q = {**q, "generation_lease_until": time.time() + 10,
                         "generation_failure_count": q.get("generation_failure_count", 0) + 1,
                         "last_generation_error": type(exc).__name__,
                         "last_generation_failure_codes": failure_codes}
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
                if (self.config.response_mode == "free_text_multi"
                        and self.config.candidate_mode == "instrument"):
                    raise Conflict(
                        "The legacy instrument-limited adaptive bank is exhausted. "
                        "Use the native_webapp candidate mode for dynamically selected questions."
                    )
                s.update(
                    phase="outcome" if self.config.bank("outcome") else "ready_to_complete",
                    phase_index=0, no_candidate_reason=reason,
                )
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

    def _acknowledge_committed_answer(self, sid, result):
        """Keep answer durability distinct from concurrent next-question exports.

        In V1/V2, preserve the original GenerationPending retry contract.
        V3 may ACK an archived answer while its next question is generating,
        even if another worker is exporting that new question. An export
        failure for the answer itself must never be hidden.
        """
        try:
            next_view = self.current(sid)
            return {"accepted": result, "current": next_view, "preparing_next": False}
        except GenerationPending:
            if self.config.response_mode != "free_text_multi":
                raise
            snap = self._load(sid)
            answer_export_key = f"exports/{result['question_id']}-answer"
            answer_export = snap.records.get(answer_export_key)
            if answer_export is None:
                raise IntegrityError("committed answer has no research archive record")
            if (answer_export.get("status") != "committed"
                    or answer_export_key in snap.session["pending_exports"]):
                raise ExportPending(
                    "answer/state saved; research archive synchronization pending; retry"
                )
            # Other pending exports may belong to a concurrent worker
            # presenting the NEXT question, not to this accepted answer.
            # public() withholds its wording until those exports commit.
            view = self.public(snap)
            return {"accepted": result, "current": view,
                    "preparing_next": view["question"] is None
                    and view["phase"] not in ("ready_to_complete", "complete", "declined")}

    def _answer_attention(self, snap, question, request, request_key, fingerprint):
        """Record a V3 attention response; never use it for model conditioning."""
        if request.get("answer_value") is not None or request.get("missing_reason") is not None:
            raise ValueError("attention check requires a written response")
        raw = request.get("text_answer")
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("Please write your response before continuing.")
        check = self.config.attention_checks[question["step"]]
        passed = check.passes(raw)
        q = {**question, "status": "answered", "raw_text_response": raw,
             "response_value": None, "missing_reason": None,
             "response_interpretation": {
                 "status": "attention_check",
                 "method": "exact_token_v3" if check.kind == "instructed_token" else "accepted_answer_v1",
                 "kind": check.kind, "attention_passed": passed, "check_id": check.check_id,
             },
             "attention_passed": passed, "accepted_assignments": [],
             "response_timestamp": now(), "response_elapsed_seconds": max(
                 0, (datetime.now(timezone.utc) -
                     datetime.fromisoformat(question["presented_at"])).total_seconds()),
             }
        q["response_quality"] = response_quality(q, snap.records, self.config.quality)
        session = snap.session
        session["current_question_id"] = None
        session["next_step"] += 1
        cursor = session.get("attention_cursor", 0)
        if cursor != question["step"]:
            raise IntegrityError("attention check cursor diverged from archived order")
        session["attention_cursor"] = cursor + 1
        session["attention_completed"] = session.get("attention_completed", 0) + 1
        substantive = session["next_step"] - session["attention_completed"]
        if (session["attention_cursor"] < len(self.config.attention_checks)
                and self.config.attention_position(
                    self.config.attention_checks[session["attention_cursor"]]
                ) == substantive):
            session["phase_index"] = session["attention_cursor"]
        else:
            session["phase"] = session.pop("resume_phase", "ready_to_complete")
            session["phase_index"] = session.pop("resume_phase_index", 0)
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
            return self._acknowledge_committed_answer(session["session_id"], result)
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
                return self._acknowledge_committed_answer(sid, previous["result"])
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
            item = self._item_for(q["target_variable"], q["phase"])
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
                mapping_provenance = None
                if self.config.candidate_mode == "native_webapp":
                    mapping_provenance = self.llm.map_human_response(
                        q["displayed_wording"], raw_answer)
                    candidates = self.adapter.webapp_mapping_items(
                        mapping_provenance["variables"], self.config)
                    if not candidates:
                        from .questions import AnswerNeedsClarification
                        raise AnswerNeedsClarification(
                            "No native survey variables could be mapped from this response. "
                            "Please clarify your view in your own words."
                        )
                else:
                    candidates = permitted_items(self.config, self.adapter)
                existing = (self._human_state(snap).observed_state
                            if q["phase"] == "intervention"
                            else prior_baseline_assignments(snap, allow_revision=self.config.candidate_mode == "native_webapp"))
                proposed = self.llm.interpret_multi(
                    q["displayed_wording"], raw_answer, list(candidates.values()))
                interpretation = resolve(
                    proposed, raw_answer, candidates, existing,
                    self.adapter, self.config.minimum_mapping_confidence,
                    allow_revision=self.config.candidate_mode == "native_webapp",
                )
                if mapping_provenance is not None:
                    interpretation["variable_mapping"] = mapping_provenance
                    # Same sequential variable order as DTAGSession's
                    # _answer_with_variables, which determines LRU recency.
                    ranking = {v: i for i, v in enumerate(
                        mapping_provenance["variables"])}
                    interpretation["accepted"].sort(
                        key=lambda x: ranking[x["variable"]])
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
            if raw_answer is not None:
                q["response_quality"] = response_quality(q, snap.records, self.config.quality)
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
                    phase="outcome" if self.config.bank("outcome") else "ready_to_complete",
                    phase_index=0,
                )
            elif q["phase"] == "outcome" and s["phase_index"] == len(self.config.bank("outcome")):
                s.update(phase="ready_to_complete", phase_index=0)
            self._route_attention_if_due(s)
            self.hook("before_answer_transaction")
            if self._write(snap, writes):
                self.hook("after_answer_transaction")
                return self._acknowledge_committed_answer(sid, result)
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
            all_questions = sorted((q for k, q in snap.records.items() if k.startswith("questions/")), key=lambda q: q["ordinal"])
            references = [v["object_name"] for k, v in snap.records.items() if k.startswith("exports/")]
            if any(q["status"] not in ("answered", "generation_abandoned") for q in all_questions):
                raise IntegrityError("unanswered question at finalization")
            questions = [q for q in all_questions if q["status"] == "answered"]
            abandoned = [q for q in all_questions if q["status"] == "generation_abandoned"]
            reward = self._reward(s, questions)
            s["completion_code"] = reward["completion_code"]
            writes = {}
            payload = {"kind": "session_final", "timestamp": s["completed_at"], "receipt": s["receipt"],
                       "policy": s["policy"], "consent_version": s["consent_version"],
                       "baseline_index": s["state"]["baseline_index"], "final_index": s["state"]["current_index"],
                       "no_candidate_reason": s.get("no_candidate_reason"), "prolific": s.get("prolific"),
                       "reward": reward,
                       "questions": questions, "generation_abandoned_questions": abandoned,
                       "source_objects": references, "study_configuration": self.config.model_dump(mode="json")}
            base = f"studies/{self.config.study_id}"
            self._export(s, writes, "reward", {"kind": "reward", **reward}, f"{base}/sessions/{sid}/reward.json")
            pid = (s.get("prolific") or {}).get("prolific_pid")
            if pid:
                # Researcher lookup by Prolific participant, alongside the per-session record.
                self._export(s, writes, "reward-by-participant", {"kind": "reward", **reward},
                             f"{base}/rewards/{pid}.json")
            self._export(s, writes, "final", payload, f"{base}/sessions/{sid}/final.json")
            if self._write(snap, writes):
                continue
        raise Conflict("completion busy; retry")

    def _reward(self, session, questions):
        """Completion code and the evidence behind it, archived before it is shown."""
        attention = [q for q in questions if q["phase"] == "attention"]
        failed = [q["target_variable"] for q in attention if not q.get("attention_passed")]
        flags = [q.get("response_quality") or {} for q in questions]
        substantive = [f for q, f in zip(questions, flags) if q["phase"] != "attention"]
        times = sorted(f["elapsed_seconds"] for f in flags if "elapsed_seconds" in f)
        review = summarize_quality(questions, self.config.attention_checks, self.config.quality)
        settings = self.config.prolific
        eligibility = assess_rejection_eligibility(
            questions, review,
            attention_threshold=settings.attention_fail_threshold if settings else 3,
        )
        if settings is None:
            code, category = None, "no_prolific_configuration"
        elif settings.review_code and eligibility["eligible_for_rejection"]:
            # Prolific "Failed attention checks" path is review-only. We NEVER
            # call the Prolific API to reject or withhold participant payment.
            code, category = settings.review_code, "rejection_eligible_review"
        else:
            code, category = settings.completion_code, "complete"
        return {
            "timestamp": session["completed_at"], "receipt": session["receipt"],
            "prolific": session.get("prolific"), "completion_code": code, "code_category": category,
            "reward": settings.reward if settings else None,
            "rejection_eligibility": eligibility,
            "attention": {"total": len(attention), "passed": len(attention) - len(failed),
                          "failed": len(failed), "failed_check_ids": failed,
                          "policy_eligible_total": review["eligible_imc_total"],
                          "policy_eligible_failed": review["eligible_imc_failed"],
                          "policy_eligible_failed_ids": review["eligible_imc_failed_ids"],
                          "non_eligible_failed_ids": review["other_check_failed_ids"],
                          "fail_threshold": settings.attention_fail_threshold if settings else None},
            "quality": {"substantive_answers": len(substantive),
                        "fast_answers": sum(bool(f.get("fast")) for f in flags),
                        "short_answers": sum(bool(f.get("short")) for f in substantive),
                        "duplicate_answers": sum(f.get("duplicate_of") is not None for f in substantive),
                        "median_elapsed_seconds": times[len(times) // 2] if times else None,
                        "review": review,
                        "settings": self.config.quality.model_dump(mode="json")},
            "policy": session["policy"], "consent_version": session["consent_version"],
            "created_at": session["created_at"],
        }

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
        settings = self.config.prolific
        code = (s.get("completion_code") if phase == "complete"
                else settings.no_consent_code if phase == "declined" and settings
                else None)
        return {"session_id": s["session_id"], "phase": phase, "session_version": s["revision"],
                "question": public_q, "progress": {"completed": s["next_step"], "total": total},
                "consent": self.config.consent_text if phase == "consent" else None,
                "receipt": s["receipt"] if phase == "complete" else None,
                # For declined consent this is a *return-request* completion path,
                # not a paid study completion. Prolific must be configured accordingly.
                "completion_code": code,
                "completion_url": (f"{settings.completion_url}?cc={code}" if code and settings else None)}
