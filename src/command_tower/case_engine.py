"""The Maestro Case state machine.

``CaseEngine.advance(case)`` runs the case forward one step at a time and stops
the moment it hits a wall — a blocking human task, a stalled gate, a terminal
state, or a failed stage that has exhausted its retries. ``run_to_block(case)``
loops ``advance`` until one of those walls is reached.

What this engine does, concretely:

* **Stage execution** via the handlers in :mod:`command_tower.stages`.
* **Exception handling** — after (and sometimes instead of) a stage it consults
  the policies in :mod:`command_tower.exceptions`; a policy can ask the engine to
  *retry* the stage, *re-enter* an earlier stage, *continue with a flag*,
  *escalate* to a human, or *hard-block*.
* **Retry policy** — each stage has ``max_attempts``; retries back off
  (recorded, not slept, so the demo stays fast) and a stage that exhausts its
  attempts is marked FAILED and the case FAILED.
* **Re-entry** — an incident can send the case back to an earlier stage (e.g. a
  builder credential boundary re-enters Stage 3); every re-entered stage between
  the target and the current point is reset to PENDING so the case genuinely
  re-runs that segment.
* **Human-task gating** — Stages 3 and 7 post a :class:`HumanTask` and the case
  parks in ``BLOCKED_HUMAN``. ``advance`` refuses to move a parked case; only
  :meth:`decide` (an operator decision) unparks it. This is the inviolable
  human-in-the-loop boundary.
* **Audit** — *every* transition, retry, incident, escalation, and decision
  emits exactly one append-only :class:`AuditEvent`.
"""

from __future__ import annotations

from typing import Callable

from .audit import AuditTrail
from .exceptions import (
    CODE_UPLOAD_FAILED, Resolution, ResolutionAction, UploadFailurePolicy,
    make_incident,
)
from .models import (
    Case, CaseStatus, HumanTask, Incident, Severity, StageStatus, TaskDecision,
    now_iso,
)
from .stages import STAGE_HANDLERS, StageResult


class CaseEngine:
    """Drives cases through the seven stages with exception handling + HITL."""

    def __init__(self, audit: AuditTrail | None = None,
                 max_backoff_attempts: int = 3) -> None:
        # NB: do not use ``audit or AuditTrail()`` — an empty AuditTrail is
        # falsy (``__len__`` == 0), which would silently drop a passed-in trail.
        self.audit = audit if audit is not None else AuditTrail()
        self.max_backoff_attempts = max_backoff_attempts
        self.incidents: list[Incident] = []
        self.human_tasks: dict[str, HumanTask] = {}
        self.backoff_log: list[dict] = []   # recorded backoff (no real sleep)

    # ------------------------------------------------------------------ #
    # audit shortcut
    # ------------------------------------------------------------------ #
    def _emit(self, case: Case, actor: str, action: str, detail: str = "",
              stage: int | None = None) -> None:
        self.audit.emit(case_id=case.case_id,
                        stage=stage if stage is not None else case.current_stage,
                        actor=actor, action=action, detail=detail)

    # ------------------------------------------------------------------ #
    # incident bookkeeping
    # ------------------------------------------------------------------ #
    def _raise_incident(self, case: Case, stage: int, code: str,
                        severity: Severity, summary: str) -> Incident:
        inc = make_incident(case, stage, code, severity, summary)
        self.incidents.append(inc)
        self._emit(case, actor="engine", action="incident_raised",
                   detail=f"{code}: {summary}", stage=stage)
        return inc

    def case_incidents(self, case_id: str) -> list[Incident]:
        return [i for i in self.incidents if i.case_id == case_id]

    # ------------------------------------------------------------------ #
    # re-entry
    # ------------------------------------------------------------------ #
    def _reenter(self, case: Case, target: int, reason: str) -> None:
        """Reset stages from ``target`` up to the current stage to PENDING."""
        for idx in range(target, case.current_stage + 1):
            st = case.stage(idx)
            if st.status != StageStatus.SKIPPED.value:
                st.status = StageStatus.PENDING.value
                st.attempts = 0
                st.finished_ts = None
        case.current_stage = target
        case.status = CaseStatus.RUNNING.value
        self._emit(case, actor="engine", action="reenter_stage",
                   detail=f"re-enter Stage {target}: {reason}", stage=target)
        case.touch()

    # ------------------------------------------------------------------ #
    # human tasks
    # ------------------------------------------------------------------ #
    def _post_human_task(self, case: Case, task: HumanTask) -> None:
        self.human_tasks[task.task_id] = task
        st = case.active_stage
        st.status = StageStatus.BLOCKED.value
        case.status = CaseStatus.BLOCKED_HUMAN.value
        self._emit(case, actor="ai_agent", action="human_task_posted",
                   detail=f"{task.title} [{', '.join(task.options)}]", stage=task.stage)
        case.touch()

    def pending_human_tasks(self, case_id: str | None = None) -> list[HumanTask]:
        out = [t for t in self.human_tasks.values() if t.status == "pending"]
        if case_id:
            out = [t for t in out if t.case_id == case_id]
        return out

    def decide(self, case: Case, task_id: str, decision: str,
               operator_id: str = "operator", note: str = "") -> None:
        """Record an operator decision on a blocking human task and unpark.

        This is the ONLY path that moves a BLOCKED_HUMAN case. It validates the
        decision against the task's allowed options and dispatches to the
        stage-specific gate handler.
        """
        task = self.human_tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown human task {task_id}")
        if task.case_id != case.case_id:
            raise ValueError("task does not belong to this case")
        if task.status != "pending":
            raise ValueError(f"task {task_id} already {task.status}")
        if decision not in task.options:
            raise ValueError(f"decision {decision!r} not allowed for this task; "
                             f"options={task.options}")

        task.status = "decided"
        task.decision = decision
        task.operator_id = operator_id
        task.note = note
        task.decided_ts = now_iso()
        self._emit(case, actor=f"operator:{operator_id}", action="human_decision",
                   detail=f"{task.title} -> {decision}"
                          + (f" ({note})" if note else ""), stage=task.stage)

        if task.stage == 2:
            self._apply_stale_ack_decision(case, decision)
        elif task.stage == 3:
            self._apply_credential_decision(case, decision, note)
        elif task.stage == 7:
            self._apply_submission_decision(case, decision)
        else:  # pragma: no cover - defensive
            raise ValueError(f"no gate logic for stage {task.stage}")
        case.touch()

    # ---- Stage 2 stale-rule acknowledgment -------------------------------
    def _apply_stale_ack_decision(self, case: Case, decision: str) -> None:
        st = case.stage(2)
        if decision == TaskDecision.APPROVE.value:
            # operator accepted the new values: fold the drift in and re-verify
            case.rule_drift_acknowledged = True
            for field, val in case.competition.rule_drift.items():
                if field == "deadline_raw":
                    case.competition.deadline_raw = val
            case.competition.rule_drift = {}
            st.status = StageStatus.PENDING.value   # re-run Stage 2 cleanly
            case.status = CaseStatus.RUNNING.value
            self._emit(case, actor="engine", action="stale_rule_acknowledged",
                       detail="operator accepted updated rule values; re-verifying",
                       stage=2)
        elif decision == TaskDecision.CANCEL.value:
            case.status = CaseStatus.ABANDONED.value
            st.status = StageStatus.SKIPPED.value
            self._emit(case, actor="engine", action="case_abandoned",
                       detail="operator cancelled at stale-rule gate", stage=2)

    # ---- Stage 3 gate outcomes -------------------------------------------
    def _apply_credential_decision(self, case: Case, decision: str, note: str) -> None:
        st = case.stage(3)
        if decision == TaskDecision.APPROVE.value:
            self._complete_stage(case, 3, "credentials approved")
        elif decision == TaskDecision.DEFER.value:
            st.status = StageStatus.BLOCKED.value
            case.status = CaseStatus.STALLED.value
            self._emit(case, actor="engine", action="case_stalled",
                       detail="credential gate deferred by operator", stage=3)
        elif decision == TaskDecision.SKIP_CREDENTIAL.value:
            # ``note`` may name a credential/lane to disable; otherwise disable
            # every missing credential so the case can proceed degraded.
            comp = case.competition
            to_skip = [note] if note else [
                r for r in comp.credential_refs
                if not comp.credential_available.get(r, False)]
            for ref in to_skip:
                if ref and ref not in case.disabled_integrations:
                    case.disabled_integrations.append(ref)
            from .exceptions import CODE_CREDENTIAL_BLOCKED
            inc = self._raise_incident(
                case, 3, CODE_CREDENTIAL_BLOCKED, Severity.HIGH,
                f"credential(s) unavailable: {', '.join(to_skip) or '(none)'}")
            inc.resolution = "operator skipped credential; integration disabled"
            inc.resolved = True
            inc.resolved_ts = now_iso()
            self._emit(case, actor="engine", action="credential_skipped",
                       detail=f"disabled: {', '.join(to_skip) or '(none)'}", stage=3)
            self._complete_stage(case, 3, "advanced with skipped credentials")
        elif decision == TaskDecision.CANCEL.value:
            case.status = CaseStatus.ABANDONED.value
            st.status = StageStatus.SKIPPED.value
            self._emit(case, actor="engine", action="case_abandoned",
                       detail="operator cancelled at credential gate", stage=3)

    # ---- Stage 7 gate outcomes -------------------------------------------
    def _apply_submission_decision(self, case: Case, decision: str) -> None:
        st = case.stage(7)
        if decision == TaskDecision.SUBMIT.value:
            self._do_upload(case)          # may retry/escalate on failure
        elif decision == TaskDecision.DEFER.value:
            case.status = CaseStatus.DEFERRED.value
            st.status = StageStatus.BLOCKED.value
            self._emit(case, actor="engine", action="submission_deferred",
                       detail="operator deferred submission", stage=7)
        elif decision == TaskDecision.SKIP_PLATFORM.value:
            st.output["submission_mode"] = "documentation_first"
            self._complete_stage(case, 7, "submitted as documentation-first entry")
            case.status = CaseStatus.SUBMITTED.value

    def _do_upload(self, case: Case) -> None:
        """Execute the platform upload with retry/backoff + escalation.

        Drives the PLATFORM_UPLOAD_FAILED exception class: if the competition is
        seeded to fail the first attempt, the engine retries with recorded
        backoff up to the stage max-attempts, then succeeds — exercising the
        retry path without any real network.
        """
        st = case.stage(7)
        max_attempts = st.max_attempts
        fails_first = case.competition.upload_fails_first_attempt
        inc: Incident | None = None
        for attempt in range(1, max_attempts + 1):
            st.attempts = attempt
            # first attempt fails iff seeded; subsequent attempts succeed
            failed = fails_first and attempt == 1
            if not failed:
                st.output["upload"] = {"attempt": attempt, "status": "ok"}
                self._emit(case, actor="robot", action="platform_upload",
                           detail=f"upload succeeded on attempt {attempt}", stage=7)
                self._complete_stage(case, 7, "submitted to platform")
                case.status = CaseStatus.SUBMITTED.value
                if inc is not None:
                    inc.resolved = True
                    inc.resolved_ts = now_iso()
                return
            # failed attempt -> raise/continue incident, apply policy
            if inc is None:
                inc = self._raise_incident(case, 7, CODE_UPLOAD_FAILED,
                                           Severity.MEDIUM, "platform upload failed")
            inc.attempts = attempt
            res = UploadFailurePolicy.handle(case, inc, attempts=attempt,
                                             max_attempts=max_attempts)
            if res.action == ResolutionAction.RETRY.value:
                self._record_backoff(case, 7, attempt)
                self._emit(case, actor="robot", action="upload_retry",
                           detail=res.note, stage=7)
                continue
            # escalate: exhausted -> operator must act, case stalls
            self._emit(case, actor="engine", action="upload_escalated",
                       detail=res.note, stage=7)
            case.status = CaseStatus.STALLED.value
            st.status = StageStatus.FAILED.value
            return

    def _record_backoff(self, case: Case, stage: int, attempt: int) -> None:
        delay = 2 ** (attempt - 1)   # 1s, 2s, 4s ... recorded only
        self.backoff_log.append({"case_id": case.case_id, "stage": stage,
                                 "attempt": attempt, "delay_s": delay,
                                 "ts": now_iso()})

    # ------------------------------------------------------------------ #
    # stage lifecycle
    # ------------------------------------------------------------------ #
    def _start_stage(self, case: Case, idx: int) -> None:
        st = case.stage(idx)
        if st.status == StageStatus.PENDING.value:
            st.status = StageStatus.ACTIVE.value
            st.started_ts = now_iso()
            self._emit(case, actor=st.actor, action="stage_started",
                       detail=st.name, stage=idx)

    def _complete_stage(self, case: Case, idx: int, detail: str = "") -> None:
        st = case.stage(idx)
        st.status = StageStatus.DONE.value
        st.finished_ts = now_iso()
        self._emit(case, actor=st.actor, action="stage_completed",
                   detail=detail or st.name, stage=idx)
        # advance pointer if this was the current stage
        if case.current_stage == idx and idx < 7:
            case.current_stage = idx + 1
            case.status = CaseStatus.RUNNING.value
        elif idx == 7 and not case.is_terminal:
            case.status = CaseStatus.SUBMITTED.value
        case.touch()

    def _fail_stage(self, case: Case, idx: int, reason: str) -> None:
        st = case.stage(idx)
        st.status = StageStatus.FAILED.value
        st.finished_ts = now_iso()
        case.status = CaseStatus.FAILED.value
        self._emit(case, actor="engine", action="stage_failed",
                   detail=reason, stage=idx)
        case.touch()

    # ------------------------------------------------------------------ #
    # the single-step driver
    # ------------------------------------------------------------------ #
    def advance(self, case: Case) -> bool:
        """Advance the case one step. Returns True if it made progress.

        Returns False when the case is terminal, parked on a human gate, or
        stalled — i.e. when it needs something external (an operator) to move.
        """
        if case.is_terminal:
            return False
        if case.status in (CaseStatus.BLOCKED_HUMAN.value, CaseStatus.STALLED.value):
            return False   # parked: only decide()/operator action moves it

        idx = case.current_stage
        st = case.stage(idx)

        if st.status == StageStatus.DONE.value:
            # already done (e.g. after a gate decision); move pointer forward
            if idx < 7:
                case.current_stage = idx + 1
                return True
            return False

        st.attempts += 1
        self._start_stage(case, idx)

        handler: Callable[[Case], StageResult] = STAGE_HANDLERS[idx]
        result = handler(case)

        # persist handler output (minus private "_..." keys) into the stage
        for k, v in result.output.items():
            st.output[k] = v
        if result.detail:
            st.notes.append(result.detail)

        # log any already-handled (non-blocking) exception for the ledger
        if result.info_incident is not None:
            code, sev, summary, resolution = result.info_incident
            inc = self._raise_incident(case, idx, code, sev, summary)
            inc.resolution = resolution
            inc.resolved = True
            inc.resolved_ts = now_iso()

        # a stage that wants a human gate parks the case
        if result.human_task is not None:
            self._post_human_task(case, result.human_task)
            return False

        # a stage that raised an incident -> resolve via policy/handler request
        if result.incident is not None:
            code, sev, summary = result.incident
            inc = self._raise_incident(case, idx, code, sev, summary)
            return self._resolve_stage_incident(case, idx, result, inc)

        if result.ok:
            self._complete_stage(case, idx, result.detail)
            return True

        # not ok and no incident/gate -> retry or fail
        return self._retry_or_fail(case, idx, result.detail or "stage returned not-ok")

    def _resolve_stage_incident(self, case: Case, idx: int,
                                result: StageResult, inc: Incident) -> bool:
        """Apply the resolution requested by a stage that raised an incident."""
        # explicit re-entry request from the stage wins
        if result.reenter_stage is not None:
            # an artifact-secret quarantine is scrubbed before re-running Stage 5
            from .exceptions import CODE_ARTIFACT_SECRET
            if inc.code == CODE_ARTIFACT_SECRET and not case.artifacts_scrubbed:
                case.artifacts_scrubbed = True
                self._emit(case, actor="ai_agent", action="artifact_scrubbed",
                           detail="quarantined artifact scrubbed of secret reference",
                           stage=idx)
            inc.resolution = f"re-enter Stage {result.reenter_stage}"
            inc.resolved = True
            inc.resolved_ts = now_iso()
            self._reenter(case, result.reenter_stage, inc.summary)
            return True

        # otherwise classify by code via the policy resolutions baked into stages
        from .exceptions import (
            BlockedCredentialPolicy, StaleRulePolicy, TimezoneConflictPolicy,
            CODE_CREDENTIAL_BLOCKED, CODE_DEADLINE_CONFLICT, CODE_STALE_RULE,
        )
        res: Resolution | None = None
        if inc.code == CODE_STALE_RULE:
            res = StaleRulePolicy.handle(case, inc)
        elif inc.code == CODE_CREDENTIAL_BLOCKED:
            res = BlockedCredentialPolicy.handle(case, inc)
        elif inc.code == CODE_DEADLINE_CONFLICT:
            res = TimezoneConflictPolicy.handle(case, inc)

        if res is None:
            # unknown incident -> retry the stage or fail it out
            return self._retry_or_fail(case, idx, inc.summary)

        if res.action == ResolutionAction.CONTINUE.value:
            if res.flag:
                case.deadline_flag = res.flag
            inc.resolved = True
            inc.resolved_ts = now_iso()
            self._complete_stage(case, idx, f"continued ({res.flag or res.note})")
            return True
        if res.action == ResolutionAction.RETRY.value:
            inc.resolved = True
            inc.resolved_ts = now_iso()
            # clear the drift so the retry passes (the operator's fix landed)
            case.competition.rule_drift = {}
            return self._retry_or_fail(case, idx, res.note, soft=True)
        if res.action == ResolutionAction.REENTER.value:
            inc.resolved = True
            inc.resolved_ts = now_iso()
            self._reenter(case, res.target_stage or 3, res.note)
            return True
        if res.action == ResolutionAction.ESCALATE.value:
            # park the case for operator acknowledgment (re-uses the gate at 3
            # for credential-class, otherwise stalls with an alert)
            case.status = CaseStatus.STALLED.value
            case.active_stage.status = StageStatus.BLOCKED.value
            self._emit(case, actor="engine", action="escalated",
                       detail=res.note, stage=idx)
            return False
        return self._retry_or_fail(case, idx, inc.summary)

    def _retry_or_fail(self, case: Case, idx: int, reason: str,
                       soft: bool = False) -> bool:
        """Retry the stage with backoff, or fail it when attempts are spent.

        ``soft`` means the previous attempt is being re-run after a fix (e.g. a
        rule-drift acknowledgment) and should not count toward exhaustion.
        """
        st = case.stage(idx)
        if soft:
            st.status = StageStatus.PENDING.value
            self._record_backoff(case, idx, st.attempts)
            self._emit(case, actor="engine", action="stage_retry",
                       detail=f"{reason} (soft retry)", stage=idx)
            return True
        if st.attempts < st.max_attempts:
            st.status = StageStatus.PENDING.value
            self._record_backoff(case, idx, st.attempts)
            self._emit(case, actor="engine", action="stage_retry",
                       detail=f"{reason} (attempt {st.attempts}/{st.max_attempts})",
                       stage=idx)
            return True
        self._fail_stage(case, idx, f"{reason} (retries exhausted)")
        return False

    # ------------------------------------------------------------------ #
    # the loop driver
    # ------------------------------------------------------------------ #
    def run_to_block(self, case: Case, max_steps: int = 200) -> Case:
        """Advance until the case is terminal, parked, or out of steps."""
        steps = 0
        while steps < max_steps and self.advance(case):
            steps += 1
        return case
