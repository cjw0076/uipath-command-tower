"""Exception/escalation policies for the four named exception classes.

Maestro Case is exception-first: the value is not the happy path but what the
workflow does when reality diverges. Each policy here pairs a *detector* (does
this exception apply to this case right now?) with a *handler* (what resolution
path does the engine take — retry, re-enter an earlier stage, or escalate to a
human gate?).

The four exception classes the demo exercises:

* ``BLOCKED_CREDENTIAL`` (CREDENTIAL_BLOCKED)
    A stage needs a credential the operator has not approved, or a builder task
    hit a live-platform boundary. Handling: re-enter Stage 3 (the credential
    gate) and post a human task.
* ``STALE_RULE`` (STALE_RULE_CHANGED)
    The live rules page changed after intake (deadline moved, an asset added).
    Handling: retry the verification with the new value; if a critical field
    drifted, hold for operator acknowledgment.
* ``TIMEZONE_CONFLICT`` (DEADLINE_CONFLICT)
    The deadline text carries both PDT and EDT. Handling: resolve to the earlier
    (conservative) interpretation and continue with a DEADLINE_CONSERVATIVE flag
    — no human needed, but it is audited.
* ``PLATFORM_UPLOAD_FAILURE`` (PLATFORM_UPLOAD_FAILED)
    The submission upload fails on its first attempt. Handling: retry with
    backoff up to the stage max-attempts; escalate to the operator only if all
    retries are exhausted.

Each policy returns a :class:`Resolution` telling the engine what to do; the
engine (not the policy) performs the state change and emits the audit event, so
the policies stay pure and unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from .models import Incident, Severity, new_id, now_iso

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import Case


class ResolutionAction(str, Enum):
    RETRY = "retry"                  # retry the current stage (with backoff)
    REENTER = "reenter"              # jump back to an earlier stage
    CONTINUE = "continue"            # accept + continue, with a flag
    ESCALATE = "escalate"            # raise a human task / operator alert
    HARD_BLOCK = "hard_block"        # quarantine; cannot advance until fixed


@dataclass
class Resolution:
    """What the engine should do about a detected incident."""

    action: str                      # ResolutionAction value
    target_stage: int | None = None  # for REENTER
    flag: str | None = None          # e.g. DEADLINE_CONSERVATIVE
    note: str = ""


# ---------------------------------------------------------------------------
# exception codes (named, append-only catalogue)
# ---------------------------------------------------------------------------

CODE_CREDENTIAL_BLOCKED = "CREDENTIAL_BLOCKED"
CODE_STALE_RULE = "STALE_RULE_CHANGED"
CODE_DEADLINE_CONFLICT = "DEADLINE_CONFLICT"
CODE_UPLOAD_FAILED = "PLATFORM_UPLOAD_FAILED"
CODE_ARTIFACT_SECRET = "ARTIFACT_SECRET_FOUND"
CODE_ROUTING_EMPTY = "ROUTING_EMPTY"


def make_incident(case: "Case", stage: int, code: str, severity: Severity,
                  summary: str) -> Incident:
    return Incident(
        incident_id=new_id("inc"), case_id=case.case_id, stage=stage,
        code=code, severity=severity.value, summary=summary, raised_ts=now_iso())


# ---------------------------------------------------------------------------
# 1. blocked credential
# ---------------------------------------------------------------------------

class BlockedCredentialPolicy:
    code = CODE_CREDENTIAL_BLOCKED

    @staticmethod
    def detect(case: "Case") -> bool:
        """True if any required credential is unavailable and not yet skipped."""
        comp = case.competition
        for ref in comp.credential_refs:
            if ref in case.disabled_integrations:
                continue
            if not comp.credential_available.get(ref, False):
                return True
        return False

    @staticmethod
    def handle(case: "Case", incident: Incident) -> Resolution:
        # Always route credential blocks back through the human-gate at Stage 3.
        incident.resolution = "re-enter Stage 3 credential gate (human task)"
        return Resolution(action=ResolutionAction.REENTER.value, target_stage=3,
                          note="credential unavailable; operator approval required")


# ---------------------------------------------------------------------------
# 2. stale rule (rule changed after intake)
# ---------------------------------------------------------------------------

# fields whose drift forces an operator acknowledgment rather than a silent retry
_CRITICAL_FIELDS = {"deadline_raw", "license", "team_size", "required_assets"}


class StaleRulePolicy:
    code = CODE_STALE_RULE

    @staticmethod
    def detect(case: "Case") -> bool:
        return bool(case.competition.rule_drift)

    @staticmethod
    def handle(case: "Case", incident: Incident) -> Resolution:
        drift = case.competition.rule_drift
        critical = sorted(set(drift) & _CRITICAL_FIELDS)
        if critical:
            incident.severity = Severity.HIGH.value
            incident.resolution = (
                f"critical field(s) drifted ({', '.join(critical)}); "
                "hold for operator acknowledgment")
            return Resolution(action=ResolutionAction.ESCALATE.value,
                              note=f"stale critical fields: {', '.join(critical)}")
        incident.resolution = "non-critical drift; re-verify and continue"
        return Resolution(action=ResolutionAction.RETRY.value,
                          note="re-run rule verification with updated values")


# ---------------------------------------------------------------------------
# 3. timezone conflict
# ---------------------------------------------------------------------------

class TimezoneConflictPolicy:
    code = CODE_DEADLINE_CONFLICT

    @staticmethod
    def detect(case: "Case") -> bool:
        raw = (case.competition.deadline_raw or "").upper()
        return ("PDT" in raw or "PST" in raw) and ("EDT" in raw or "EST" in raw)

    @staticmethod
    def handle(case: "Case", incident: Incident) -> Resolution:
        # EDT is 3h ahead of PDT, so the EDT reading is the earlier wall-clock
        # cutoff -> the safe (conservative) choice.
        incident.resolution = "resolved to earlier EDT interpretation (conservative)"
        return Resolution(action=ResolutionAction.CONTINUE.value,
                          flag="DEADLINE_CONSERVATIVE",
                          note="PDT/EDT ambiguity -> pick earlier EDT cutoff")


# ---------------------------------------------------------------------------
# 4. platform upload failure
# ---------------------------------------------------------------------------

class UploadFailurePolicy:
    code = CODE_UPLOAD_FAILED

    @staticmethod
    def detect(case: "Case", attempt_failed: bool) -> bool:
        return attempt_failed

    @staticmethod
    def handle(case: "Case", incident: Incident, *, attempts: int,
               max_attempts: int) -> Resolution:
        if attempts < max_attempts:
            incident.severity = Severity.MEDIUM.value
            incident.resolution = (
                f"retry upload with backoff (attempt {attempts + 1}/{max_attempts})")
            return Resolution(action=ResolutionAction.RETRY.value,
                              note="transient upload failure; backoff + retry")
        incident.severity = Severity.HIGH.value
        incident.resolution = "retries exhausted; escalate to operator"
        return Resolution(action=ResolutionAction.ESCALATE.value,
                          note="upload still failing after max attempts")


# the catalogue the engine iterates over for auto-detected (state-based) classes
DETECTABLE_POLICIES = (
    TimezoneConflictPolicy,    # check first: cheap, non-blocking
    StaleRulePolicy,
    BlockedCredentialPolicy,
)
