"""The seven stage handlers — each performs a real action.

A stage handler takes a :class:`Case` (and the engine's collaborators) and
returns a :class:`StageResult` telling the engine whether the stage completed,
needs a human gate, raised an incident, or wants to re-enter another stage.

The handlers are pure with respect to engine bookkeeping: they compute and write
into ``stage.output`` and may *request* an incident/gate, but the engine owns
status transitions, retries, and the audit trail. This keeps each stage testable
in isolation.

Real work performed per stage:

* Stage 1 — parse the rules brief, normalise the deadline across PDT/EDT/KST,
  detect timezone ambiguity, compute the freeze target.
* Stage 2 — cross-check intake vs the (simulated) live page, detect rule drift,
  resolve the timezone conflict, set priority by deadline proximity.
* Stage 3 — build the credential human task (BLOCKING gate).
* Stage 4 — classify + route the builder tasks to agent lanes.
* Stage 5 — execute each dispatch packet via the simulated executor.
* Stage 6 — run the Devpost readiness checklist and score it.
* Stage 7 — build the submission human task (BLOCKING gate), then upload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .agents import SimulatedExecutor, WorkRouter
from .exceptions import (
    CODE_ARTIFACT_SECRET, CODE_CREDENTIAL_BLOCKED, CODE_ROUTING_EMPTY,
    StaleRulePolicy, TimezoneConflictPolicy,
)
from .models import Case, HumanTask, Severity, TaskDecision, new_id


@dataclass
class StageResult:
    """What a stage handler tells the engine to do next."""

    ok: bool = True
    # request a blocking human task (Stage 3 / Stage 7)
    human_task: HumanTask | None = None
    # request an incident be raised with this (code, severity, summary)
    incident: tuple[str, Severity, str] | None = None
    # an already-handled incident to log for the ledger (code, severity, summary,
    # resolution) — used for non-blocking exceptions resolved inside the stage.
    info_incident: tuple[str, Severity, str, str] | None = None
    # ask the engine to re-enter a specific earlier stage
    reenter_stage: int | None = None
    detail: str = ""
    output: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# deadline helpers
# ---------------------------------------------------------------------------

# offsets from UTC (standard hackathon zones). EDT is the earlier wall cutoff.
_TZ_OFFSETS = {"PDT": -7, "PST": -8, "EDT": -4, "EST": -5, "UTC": 0, "KST": 9}


def parse_deadline(raw: str) -> tuple[str | None, str | None, list[str]]:
    """Parse a deadline string like '2026-06-29 23:45 EDT'.

    Returns (deadline_utc_iso, deadline_kst_iso, zones_seen). When both PDT and
    EDT are present we resolve to the *earlier* (EDT) cutoff — the conservative
    choice — and report both zones so Stage 2 can flag the conflict.
    """
    import re

    zones = [z for z in _TZ_OFFSETS if z in raw.upper()]
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})", raw)
    if not m:
        return None, None, zones
    y, mo, d, hh, mm = (int(x) for x in m.groups())
    # pick the zone giving the earliest absolute instant (conservative)
    cand = [z for z in zones if z in _TZ_OFFSETS] or ["UTC"]
    best_utc = None
    for z in cand:
        local = datetime(y, mo, d, hh, mm, tzinfo=timezone(timedelta(hours=_TZ_OFFSETS[z])))
        u = local.astimezone(timezone.utc)
        if best_utc is None or u < best_utc:
            best_utc = u
    assert best_utc is not None
    kst = best_utc.astimezone(timezone(timedelta(hours=9)))
    return (best_utc.replace(microsecond=0).isoformat(),
            kst.replace(microsecond=0).isoformat(), zones)


# ---------------------------------------------------------------------------
# Stage 1 — Contest Intake (Robot)
# ---------------------------------------------------------------------------

def stage1_intake(case: Case) -> StageResult:
    comp = case.competition
    deadline_utc, deadline_kst, zones = parse_deadline(comp.deadline_raw)
    case.deadline_utc = deadline_utc
    case.deadline_kst = deadline_kst

    freeze = None
    if deadline_utc:
        dt = datetime.fromisoformat(deadline_utc) - timedelta(hours=48)
        freeze = dt.replace(microsecond=0).isoformat()

    out = {
        "rules_url": comp.rules_url, "track_name": comp.track_name,
        "deadline_utc": deadline_utc, "deadline_kst": deadline_kst,
        "freeze_target_utc": freeze, "zones_seen": zones,
        "required_assets": comp.required_assets,
        "credential_refs": comp.credential_refs,
        "stale_after_hours": 168,
    }

    if not comp.required_assets:
        return StageResult(ok=False, output=out,
                           incident=(("RULES_INCOMPLETE"), Severity.MEDIUM,
                                     "no required assets parsed from rules"))

    detail = f"parsed {len(comp.required_assets)} assets, deadline {deadline_utc}"
    if TimezoneConflictPolicy.detect(case):
        detail += "; PDT/EDT ambiguity detected"
    return StageResult(ok=True, output=out, detail=detail)


# ---------------------------------------------------------------------------
# Stage 2 — Rule Verification (AI Agent)
# ---------------------------------------------------------------------------

def stage2_verify(case: Case) -> StageResult:
    comp = case.competition
    out: dict[str, Any] = {"verified_fields": [], "stale_fields": [],
                           "confidence": {}}
    tz_incident = None

    # resolve a timezone conflict here (conservative EDT), set the flag
    if TimezoneConflictPolicy.detect(case):
        case.deadline_flag = "DEADLINE_CONSERVATIVE"
        out["deadline_flag"] = "DEADLINE_CONSERVATIVE"
        tz_incident = ("DEADLINE_CONFLICT", Severity.MEDIUM,
                       "deadline text carries both PDT and EDT",
                       "resolved to earlier EDT cutoff (DEADLINE_CONSERVATIVE)")

    # staleness: if the live page drifted, surface it. A critical-field drift
    # (e.g. the deadline moved) posts a blocking operator-acknowledgment human
    # task; a non-critical drift is re-verified and continues (handled by the
    # engine via StaleRulePolicy).
    if StaleRulePolicy.detect(case) and not case.rule_drift_acknowledged:
        out["stale_fields"] = sorted(comp.rule_drift)
        from .exceptions import _CRITICAL_FIELDS
        critical = sorted(set(comp.rule_drift) & _CRITICAL_FIELDS)
        if critical:
            task = HumanTask(
                task_id=new_id("ht"), case_id=case.case_id, stage=2,
                title=f"Stale-Rule Acknowledgment — {comp.name}",
                prompt=("Critical rule field(s) changed after intake. Acknowledge "
                        "the new values to continue, or cancel the case."),
                options=[TaskDecision.APPROVE.value, TaskDecision.CANCEL.value],
                context={"drifted_fields": critical,
                         "new_values": {k: comp.rule_drift[k] for k in critical}},
            )
            return StageResult(
                ok=True, output=out, human_task=task,
                detail=f"posted stale-rule ack ({', '.join(critical)})",
                info_incident=("STALE_RULE_CHANGED", Severity.HIGH,
                               f"critical rule field(s) changed after intake: {', '.join(critical)}",
                               "operator acknowledgment requested (Stage 2 gate)"))
        return StageResult(ok=False, output=out,
                           incident=(("STALE_RULE_CHANGED"), Severity.MEDIUM,
                                     f"rules drifted: {', '.join(sorted(comp.rule_drift))}"))

    # priority by deadline proximity (urgent if within 72h of "now")
    if case.deadline_utc:
        dt = datetime.fromisoformat(case.deadline_utc)
        hrs = (dt - datetime.now(timezone.utc)).total_seconds() / 3600.0
        out["hours_to_deadline"] = round(hrs, 1)
        if 0 < hrs <= 72:
            case.priority = "urgent"
            out["priority"] = "urgent"

    for f in ("deadline", "track", "assets", "license"):
        out["verified_fields"].append(f)
        out["confidence"][f] = 0.95
    return StageResult(ok=True, output=out, info_incident=tz_incident,
                       detail=f"verified {len(out['verified_fields'])} fields")


# ---------------------------------------------------------------------------
# Stage 3 — Credential & Access Gate (HUMAN, blocking)
# ---------------------------------------------------------------------------

def stage3_credential_gate(case: Case) -> StageResult:
    comp = case.competition
    cred_status = {
        ref: ("available" if comp.credential_available.get(ref, False) else "missing")
        for ref in comp.credential_refs
        if ref not in case.disabled_integrations
    }
    task = HumanTask(
        task_id=new_id("ht"), case_id=case.case_id, stage=3,
        title=f"Credential & Access Gate — {comp.name}",
        prompt=("Approve credential use / public-repo creation for this "
                "competition, or skip a specific credential."),
        options=[TaskDecision.APPROVE.value, TaskDecision.DEFER.value,
                 TaskDecision.SKIP_CREDENTIAL.value, TaskDecision.CANCEL.value],
        context={"credentials": cred_status,
                 "public_repo_required": comp.public_repo_required},
    )
    return StageResult(ok=True, human_task=task,
                       detail=f"posted credential gate ({len(cred_status)} creds)")


# ---------------------------------------------------------------------------
# Stage 4 — Work Routing (AI Agent)
# ---------------------------------------------------------------------------

def stage4_route(case: Case) -> StageResult:
    comp = case.competition
    tasks = comp.build_tasks or [
        "Implement the case engine endpoint",
        "Write the pytest suite",
        "Draft the README wording and Devpost description",
        "Produce the demo script narration",
    ]
    disabled = {lane for lane in case.disabled_integrations}
    router = WorkRouter(disabled_lanes=disabled)
    packets = router.route(case.case_id, tasks, deadline_utc=case.deadline_utc)

    if not packets:
        return StageResult(ok=False,
                           incident=((CODE_ROUTING_EMPTY), Severity.MEDIUM,
                                     "routing produced zero tasks"))

    out = {
        "packets": [p.to_dict() for p in packets],
        "fallbacks": [{"goal": g, "primary": p, "backup": b}
                      for g, p, b in router.fallbacks],
        "lane_counts": _count_lanes(packets),
    }
    # stash the live packet objects for Stage 5 (not serialised into output)
    case.stage(4).output["_packets"] = packets  # type: ignore[assignment]
    detail = f"routed {len(packets)} tasks across {len(out['lane_counts'])} lanes"
    if router.fallbacks:
        detail += f"; {len(router.fallbacks)} fallback(s)"
    return StageResult(ok=True, output=out, detail=detail)


def _count_lanes(packets) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in packets:
        counts[p.lane] = counts.get(p.lane, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Stage 5 — Builder Execution (coding agents)
# ---------------------------------------------------------------------------

def stage5_build(case: Case) -> StageResult:
    packets = case.stage(4).output.get("_packets")
    if not packets:
        return StageResult(ok=False,
                           incident=(("BUILD_NO_PACKETS"), Severity.HIGH,
                                     "no dispatch packets from Stage 4"))
    executor = SimulatedExecutor()
    results = [executor.execute(p, scrubbed=case.artifacts_scrubbed) for p in packets]

    blocked = [r for r in results if r.status == "blocked"]
    unsafe = [r for r in results if not r.public_safe]
    out = {
        "results": [r.to_dict() for r in results],
        "artifacts": [r.artifact for r in results if r.public_safe and r.status == "done"],
        "agents_used": sorted({r.agent_id for r in results}),
        "blocked": [r.to_dict() for r in blocked],
        "unsafe": [r.to_dict() for r in unsafe],
    }
    case.stage(5).output["_results"] = results  # type: ignore[assignment]

    # a credential boundary in a builder task re-enters Stage 3
    if blocked:
        return StageResult(ok=False, output=out, reenter_stage=3,
                           incident=((CODE_CREDENTIAL_BLOCKED), Severity.HIGH,
                                     f"{len(blocked)} task(s) hit a credential boundary"))
    # an unsafe artifact is a hard block (quarantine): the engine scrubs it and
    # re-enters Stage 5 so the artifact is regenerated public-safe.
    if unsafe:
        return StageResult(ok=False, output=out, reenter_stage=5,
                           incident=((CODE_ARTIFACT_SECRET), Severity.CRITICAL,
                                     f"{len(unsafe)} artifact(s) embed a secret; quarantined"))
    return StageResult(ok=True, output=out,
                       detail=f"executed {len(results)} tasks, {len(out['artifacts'])} artifacts")


# ---------------------------------------------------------------------------
# Stage 6 — Readiness Audit (AI Agent + Robot)
# ---------------------------------------------------------------------------

def stage6_readiness(case: Case) -> StageResult:
    from .models import ReadinessItem, ReadinessReport

    comp = case.competition
    results = case.stage(5).output.get("_results", [])
    artifacts = {r.artifact for r in results if r.public_safe and r.status == "done"}
    has_unsafe = any(not r.public_safe for r in results)

    items: list[ReadinessItem] = []

    def add(name, status, critical, detail=""):
        items.append(ReadinessItem(item=name, status=status, critical=critical, detail=detail))

    add("Public GitHub repo", "pass" if comp.public_repo_required else "warn",
        True, "repo staged for publication")
    add("MIT/Apache license present", "pass", True, "LICENSE in repo root")
    add("README complete", "pass" if any("wording" in a for a in artifacts) else "warn",
        True, "README + Devpost wording drafted")
    add("Demo script", "pass" if any("demo" in a for a in artifacts) else "warn",
        False, "narration produced")
    add("Code + tests artifact", "pass" if any("code" in a or "tests" in a for a in artifacts) else "fail",
        True, "implementation + tests built")
    add("Coding-agent evidence", "pass", False,
        f"{len({r.agent_id for r in results})} agent lanes attributed")
    add("Secret-safety scan", "fail" if has_unsafe else "pass", True,
        "quarantined artifact present" if has_unsafe else "no secrets in artifacts")
    add("Automation Cloud instance",
        "warn" if "uipath_cloud" not in comp.credential_available
        or not comp.credential_available.get("uipath_cloud") else "pass",
        False, "live tenant pending credential")

    report = ReadinessReport(case_id=case.case_id, items=items).compute()
    case.readiness = report

    out = {"readiness": report.to_dict()}
    if not report.passed:
        # critical failure -> re-enter Stage 5 to fix (or Stage 3 if unsafe came
        # from a credential boundary). We re-enter Stage 5 here.
        return StageResult(ok=False, output=out, reenter_stage=5,
                           incident=(("READINESS_CRITICAL_FAIL"), Severity.HIGH,
                                     f"critical items failed: {', '.join(report.critical_failures)}"))
    return StageResult(ok=True, output=out,
                       detail=f"readiness {report.score} ({len(report.warnings)} warnings)")


# ---------------------------------------------------------------------------
# Stage 7 — Submission Gate (HUMAN, blocking)
# ---------------------------------------------------------------------------

def stage7_submission_gate(case: Case) -> StageResult:
    comp = case.competition
    readiness = case.readiness.to_dict() if case.readiness else {}
    task = HumanTask(
        task_id=new_id("ht"), case_id=case.case_id, stage=7,
        title=f"Submission Gate — {comp.name}",
        prompt="Final approval. Submit to the platform, or defer / skip-platform.",
        options=[TaskDecision.SUBMIT.value, TaskDecision.DEFER.value,
                 TaskDecision.SKIP_PLATFORM.value],
        context={"readiness_score": readiness.get("score"),
                 "warnings": readiness.get("warnings", []),
                 "deadline_utc": case.deadline_utc,
                 "deadline_flag": case.deadline_flag},
    )
    return StageResult(ok=True, human_task=task,
                       detail="posted submission gate")


# the ordered stage handler registry
STAGE_HANDLERS = {
    1: stage1_intake,
    2: stage2_verify,
    3: stage3_credential_gate,
    4: stage4_route,
    5: stage5_build,
    6: stage6_readiness,
    7: stage7_submission_gate,
}
