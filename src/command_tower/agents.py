"""Multi-agent work routing + a deterministic, offline simulated executor.

Stage 4 (Work Routing) classifies each builder task and assigns it to an agent
*lane* — Claude Code, Codex CLI, Gemini CLI, or a UiPath Robot — using the
routing table from the Maestro Case design. Stage 5 (Builder Execution) then
runs each task through :class:`SimulatedExecutor`, which produces a deterministic
result packet so the whole demo runs offline with zero external API calls.

The executor is intentionally deterministic (hash-seeded) so tests and the eval
harness are reproducible. Swapping in a real CLI dispatcher (the production path)
means replacing :class:`SimulatedExecutor` with one that shells out to the agent
CLIs — the routing, result-packet shape, and audit hooks stay identical.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

from .models import now_iso, new_id


class AgentLane(str, Enum):
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    GEMINI = "gemini"
    ROBOT = "robot"             # UiPath Studio Web automation


# task-type -> (primary lane, backup lane). Mirrors the design routing table.
ROUTING_TABLE: dict[str, tuple[AgentLane, AgentLane]] = {
    "code":          (AgentLane.CODEX, AgentLane.CLAUDE_CODE),
    "tests":         (AgentLane.CODEX, AgentLane.CLAUDE_CODE),
    "architecture":  (AgentLane.CLAUDE_CODE, AgentLane.CODEX),
    "wording":       (AgentLane.CLAUDE_CODE, AgentLane.CODEX),
    "ideation":      (AgentLane.GEMINI, AgentLane.CLAUDE_CODE),
    "repo_ops":      (AgentLane.ROBOT, AgentLane.CLAUDE_CODE),
    "demo_script":   (AgentLane.CLAUDE_CODE, AgentLane.CODEX),
    "deck":          (AgentLane.CLAUDE_CODE, AgentLane.ROBOT),
    "rule_memory":   (AgentLane.CLAUDE_CODE, AgentLane.CODEX),
}

# keyword -> task type, used to classify a free-text task description.
_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("test", "pytest", "coverage"), "tests"),
    (("implement", "code", "build", "endpoint", "api", "backend", "script"), "code"),
    (("architecture", "design", "critique", "review", "refactor"), "architecture"),
    (("readme", "wording", "copy", "description", "narrative", "devpost"), "wording"),
    (("idea", "brainstorm", "alternative", "explore"), "ideation"),
    (("repo", "push", "release", "git", "license"), "repo_ops"),
    (("demo", "narration", "walkthrough"), "demo_script"),
    (("slide", "deck", "presentation"), "deck"),
    (("rule", "staleness", "deadline", "memory"), "rule_memory"),
]


def classify_task(description: str) -> str:
    """Map a free-text builder task to one of the routing task types."""
    low = description.lower()
    for keys, ttype in _KEYWORDS:
        if any(k in low for k in keys):
            return ttype
    return "code"  # safe default: hand unknown work to the implementation lane


@dataclass
class DispatchPacket:
    """A bounded task assigned to an agent lane (Stage 4 output)."""

    packet_id: str
    case_id: str
    goal: str
    task_type: str
    lane: str                              # AgentLane value (primary or backup)
    primary_lane: str
    backup_lane: str
    output_format: str = "artifact"
    stop_conditions: list[str] = field(default_factory=list)
    deadline_utc: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResultPacket:
    """A builder-execution result (Stage 5 output)."""

    packet_id: str
    case_id: str
    lane: str
    status: str                            # "done" | "blocked" | "failed"
    artifact: str                          # logical artifact name produced
    agent_id: str                          # for the coding-agent bonus evidence
    detail: str = ""
    blocker_code: str | None = None
    public_safe: bool = True
    ts: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorkRouter:
    """Stage-4 router: classify tasks and assign lanes, honouring availability.

    ``disabled_lanes`` carries lanes whose credentials the operator declined
    (e.g. SKIP_CREDENTIAL at Stage 3); a task whose primary lane is disabled
    falls back to its backup, and the fallback is recorded for the audit trail.
    """

    def __init__(self, disabled_lanes: set[str] | None = None) -> None:
        self.disabled_lanes = disabled_lanes or set()
        self.fallbacks: list[tuple[str, str, str]] = []  # (goal, primary, backup)

    def route(self, case_id: str, tasks: list[str],
              deadline_utc: str | None = None) -> list[DispatchPacket]:
        packets: list[DispatchPacket] = []
        for goal in tasks:
            ttype = classify_task(goal)
            primary, backup = ROUTING_TABLE[ttype]
            lane = primary
            if primary.value in self.disabled_lanes:
                lane = backup
                self.fallbacks.append((goal, primary.value, backup.value))
            packets.append(DispatchPacket(
                packet_id=new_id("dp"),
                case_id=case_id,
                goal=goal,
                task_type=ttype,
                lane=lane.value,
                primary_lane=primary.value,
                backup_lane=backup.value,
                stop_conditions=["credential_boundary", "public_safety_violation"],
                deadline_utc=deadline_utc,
            ))
        return packets


class SimulatedExecutor:
    """Deterministic offline executor for Stage 5.

    Each packet yields a reproducible result keyed on a hash of the goal, so the
    demo, tests, and eval all see identical outcomes without any external CLI.
    Certain goals are deliberately steered to blocked/unsafe outcomes so the
    exception machinery (credential boundary, public-safety quarantine) is
    exercised end-to-end.
    """

    # human-readable lane -> agent id used in bonus-evidence attribution
    _AGENT_IDS = {
        AgentLane.CLAUDE_CODE.value: "claude-code@command-tower",
        AgentLane.CODEX.value: "codex@command-tower",
        AgentLane.GEMINI.value: "gemini-cli@command-tower",
        AgentLane.ROBOT.value: "uipath-robot@command-tower",
    }

    def execute(self, packet: DispatchPacket, *, scrubbed: bool = False) -> ResultPacket:
        """Run one dispatch packet.

        ``scrubbed`` is set when the case has already had a quarantined artifact
        scrubbed (after a Stage-6 re-entry), so the previously-unsafe artifact
        is regenerated public-safe rather than failing again — the recovery path.
        """
        h = int(hashlib.sha256(packet.goal.encode("utf-8")).hexdigest(), 16)
        agent_id = self._AGENT_IDS[packet.lane]

        # a goal that explicitly needs a live platform call hits a credential
        # boundary -> blocked result -> Stage 5 re-enters Stage 3.
        low = packet.goal.lower()
        if "live platform" in low or "automation cloud call" in low:
            return ResultPacket(
                packet_id=packet.packet_id, case_id=packet.case_id,
                lane=packet.lane, status="blocked", artifact="(none)",
                agent_id=agent_id, blocker_code="CREDENTIAL_BLOCKED",
                detail="task requires a live Automation Cloud session")

        # a goal carrying a secret marker produces an unsafe artifact -> Stage 6
        # quarantines it (ARTIFACT_SECRET_FOUND). After a scrub it comes back safe.
        if ("secret" in low or "api key" in low) and not scrubbed:
            return ResultPacket(
                packet_id=packet.packet_id, case_id=packet.case_id,
                lane=packet.lane, status="done", artifact=f"artifact_{packet.task_type}",
                agent_id=agent_id, public_safe=False,
                detail="artifact embeds a credential reference; needs scrub")

        return ResultPacket(
            packet_id=packet.packet_id, case_id=packet.case_id,
            lane=packet.lane, status="done",
            artifact=f"artifact_{packet.task_type}_{h % 1000:03d}",
            agent_id=agent_id, public_safe=True,
            detail=f"{packet.task_type} produced by {packet.lane}")
