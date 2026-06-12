"""Typed domain model for the Competition Command Tower Maestro Case.

Every object here is a plain ``@dataclass`` with a ``to_dict()`` so the engine,
the CLI, the eval harness, and the FastAPI webapp all serialise identically and
nothing leaks internal Python objects across the wire.

The model mirrors the UiPath Maestro Case vocabulary:

* ``Case``        — one competition advancing through the seven stages
  (the Maestro *Case instance*).
* ``Stage``       — a stage definition + its live status on a case
  (the Maestro *Case stage*).
* ``HumanTask``   — a blocking operator decision (the Maestro *Human Task*
  posted to Action Center). The case cannot advance past it until decided.
* ``Incident``    — a raised exception/escalation (the Maestro *exception*),
  carrying the named exception code and the chosen resolution path.
* ``AuditEvent``  — one append-only provenance record (case, stage, actor, ts).
* ``ReadinessReport`` — the Stage-6 checklist outcome with a 0..1 score.
* ``Competition`` — the immutable intake record for one competition.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def now_iso() -> str:
    """A UTC ISO-8601 timestamp (second precision) for audit records."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# enums
# ---------------------------------------------------------------------------

class StageStatus(str, Enum):
    """Lifecycle of a single stage on a case."""

    PENDING = "pending"          # not yet reached
    ACTIVE = "active"            # currently executing
    BLOCKED = "blocked"          # waiting on a human task / unmet precondition
    DONE = "done"                # completed successfully
    FAILED = "failed"            # exhausted retries / hard exception
    SKIPPED = "skipped"          # operator chose to skip (e.g. SKIP_CREDENTIAL)


class CaseStatus(str, Enum):
    """Overall lifecycle of a case (a competition)."""

    INTAKE = "intake"
    RUNNING = "running"
    BLOCKED_HUMAN = "blocked_human"   # parked on a human-task gate
    STALLED = "stalled"               # gate timed out / no operator response
    SUBMITTED = "submitted"
    DEFERRED = "deferred"
    ABANDONED = "abandoned"
    FAILED = "failed"


class TaskDecision(str, Enum):
    """The decisions an operator can take on a blocking human task."""

    # Stage 3 — Credential & Access Gate
    APPROVE = "approve"
    DEFER = "defer"
    SKIP_CREDENTIAL = "skip_credential"
    CANCEL = "cancel"
    # Stage 7 — Submission Gate
    SUBMIT = "submit"
    SKIP_PLATFORM = "skip_platform"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Stage indices are 1-based to match the design doc and judge-facing copy.
STAGE_NAMES = {
    1: "Contest Intake",
    2: "Rule Verification",
    3: "Credential & Access Gate",
    4: "Work Routing",
    5: "Builder Execution",
    6: "Readiness Audit",
    7: "Submission Gate",
}

# The two stages that are mandatory human-in-the-loop gates.
HUMAN_GATE_STAGES = {3, 7}


# ---------------------------------------------------------------------------
# competition intake record
# ---------------------------------------------------------------------------

@dataclass
class Competition:
    """Immutable-ish intake record for one competition (Stage-1 input)."""

    key: str
    name: str
    rules_url: str
    deadline_raw: str                    # raw text, may carry PDT/EDT ambiguity
    track_name: str
    required_assets: list[str] = field(default_factory=list)
    credential_refs: list[str] = field(default_factory=list)
    public_repo_required: bool = True
    coding_agent_bonus: bool = True
    # availability of each credential ref at intake time (the demo seeds this).
    credential_available: dict[str, bool] = field(default_factory=dict)
    # if the live rules page differs from the intake snapshot, this carries the
    # changed field -> new value (drives the stale-rule exception in Stage 2).
    rule_drift: dict[str, str] = field(default_factory=dict)
    # simulated platform-upload outcome for Stage 7 (drives upload-failure exc).
    upload_fails_first_attempt: bool = False
    # stage-5 builder task plan inputs
    build_tasks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuditEvent:
    """One append-only provenance record. Frozen: never mutated after writing."""

    event_id: str
    case_id: str
    stage: int
    actor: str                  # e.g. "robot", "ai_agent", "operator", "engine"
    action: str                 # short verb phrase
    detail: str
    ts: str
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# incident / exception
# ---------------------------------------------------------------------------

@dataclass
class Incident:
    """A raised exception/escalation on a case (a Maestro exception path)."""

    incident_id: str
    case_id: str
    stage: int
    code: str                   # named exception code, e.g. CREDENTIAL_BLOCKED
    severity: str               # Severity value
    summary: str
    resolution: str = ""        # the chosen handling path (filled on handle)
    resolved: bool = False
    raised_ts: str = field(default_factory=now_iso)
    resolved_ts: str | None = None
    attempts: int = 0           # retry attempts spent on this incident

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# human task (blocking gate)
# ---------------------------------------------------------------------------

@dataclass
class HumanTask:
    """A blocking operator decision posted to Action Center.

    While ``status == "pending"`` the case is parked: ``advance()`` refuses to
    move it until ``decide()`` records an operator decision. This is the
    human-in-the-loop invariant the judges look for.
    """

    task_id: str
    case_id: str
    stage: int
    title: str
    prompt: str
    options: list[str]                       # allowed TaskDecision values
    context: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"                  # pending | decided | expired
    decision: str | None = None
    operator_id: str | None = None
    note: str = ""
    created_ts: str = field(default_factory=now_iso)
    decided_ts: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# stage
# ---------------------------------------------------------------------------

@dataclass
class Stage:
    """A stage definition + its live status on one case."""

    index: int
    name: str
    actor: str
    status: str = StageStatus.PENDING.value
    attempts: int = 0
    max_attempts: int = 3
    is_human_gate: bool = False
    started_ts: str | None = None
    finished_ts: str | None = None
    output: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# readiness
# ---------------------------------------------------------------------------

@dataclass
class ReadinessItem:
    item: str
    status: str                 # "pass" | "fail" | "warn"
    critical: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReadinessReport:
    """Stage-6 readiness checklist outcome with a 0..1 completeness score."""

    case_id: str
    items: list[ReadinessItem] = field(default_factory=list)
    score: float = 0.0
    critical_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    generated_ts: str = field(default_factory=now_iso)

    def compute(self) -> "ReadinessReport":
        """Score = (passes + 0.5*warns) / total; record critical failures."""
        if not self.items:
            self.score = 0.0
            return self
        earned = 0.0
        for it in self.items:
            if it.status == "pass":
                earned += 1.0
            elif it.status == "warn":
                earned += 0.5
                self.warnings.append(it.item)
            elif it.status == "fail" and it.critical:
                self.critical_failures.append(it.item)
        self.score = round(earned / len(self.items), 3)
        return self

    @property
    def passed(self) -> bool:
        """Ready for the submission gate: no critical failures."""
        return not self.critical_failures

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["passed"] = self.passed
        return d


# ---------------------------------------------------------------------------
# case
# ---------------------------------------------------------------------------

@dataclass
class Case:
    """One competition advancing through the seven Maestro stages."""

    case_id: str
    competition: Competition
    stages: list[Stage]
    status: str = CaseStatus.INTAKE.value
    current_stage: int = 1
    priority: str = "normal"             # normal | urgent
    deadline_utc: str | None = None
    deadline_kst: str | None = None
    deadline_flag: str | None = None     # e.g. DEADLINE_CONSERVATIVE
    disabled_integrations: list[str] = field(default_factory=list)
    readiness: ReadinessReport | None = None
    # set once the operator/agent scrubs a quarantined (unsafe) artifact, so the
    # Stage-5 re-execution produces a public-safe artifact instead.
    artifacts_scrubbed: bool = False
    # set once the operator acknowledges a stale-rule drift, so Stage-2 re-verify
    # passes with the updated value.
    rule_drift_acknowledged: bool = False
    created_ts: str = field(default_factory=now_iso)
    updated_ts: str = field(default_factory=now_iso)

    # ---- helpers ----------------------------------------------------------
    def stage(self, index: int) -> Stage:
        return self.stages[index - 1]

    @property
    def active_stage(self) -> Stage:
        return self.stage(self.current_stage)

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            CaseStatus.SUBMITTED.value, CaseStatus.DEFERRED.value,
            CaseStatus.ABANDONED.value, CaseStatus.FAILED.value,
        )

    @property
    def is_blocked(self) -> bool:
        return self.status in (
            CaseStatus.BLOCKED_HUMAN.value, CaseStatus.STALLED.value,
        )

    def touch(self) -> None:
        self.updated_ts = now_iso()

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "competition": self.competition.to_dict(),
            "status": self.status,
            "current_stage": self.current_stage,
            "current_stage_name": STAGE_NAMES.get(self.current_stage, "-"),
            "priority": self.priority,
            "deadline_utc": self.deadline_utc,
            "deadline_kst": self.deadline_kst,
            "deadline_flag": self.deadline_flag,
            "disabled_integrations": self.disabled_integrations,
            "stages": [s.to_dict() for s in self.stages],
            "readiness": self.readiness.to_dict() if self.readiness else None,
            "created_ts": self.created_ts,
            "updated_ts": self.updated_ts,
            "is_terminal": self.is_terminal,
            "is_blocked": self.is_blocked,
        }


def build_stages() -> list[Stage]:
    """Construct the seven stages in their default PENDING state."""
    actors = {
        1: "robot", 2: "ai_agent", 3: "operator", 4: "ai_agent",
        5: "coding_agent", 6: "ai_agent", 7: "operator",
    }
    return [
        Stage(index=i, name=STAGE_NAMES[i], actor=actors[i],
              is_human_gate=(i in HUMAN_GATE_STAGES))
        for i in range(1, 8)
    ]
