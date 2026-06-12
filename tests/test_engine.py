"""Tests for the Maestro Case state machine: stages, gates, exceptions,
retry/backoff, escalation, re-entry, audit append-only-ness, readiness scoring.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from command_tower.case_engine import CaseEngine  # noqa: E402
from command_tower.models import (  # noqa: E402
    Case, CaseStatus, Competition, StageStatus, TaskDecision, build_stages, new_id,
)
from command_tower.orchestrator import PortfolioOrchestrator, portfolio  # noqa: E402
from command_tower.stages import parse_deadline  # noqa: E402


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def make_case(**over) -> Case:
    defaults = dict(
        key="t", name="Test Comp", rules_url="https://x/rules",
        deadline_raw="2026-08-01 23:59 UTC", track_name="Maestro Case",
        required_assets=["repo", "readme"], credential_refs=["github"],
        credential_available={"github": True}, build_tasks=["Implement the code"],
    )
    defaults.update(over)
    comp = Competition(**defaults)
    return Case(case_id=new_id("case"), competition=comp, stages=build_stages())


def run_to_first_gate(case: Case, eng: CaseEngine) -> Case:
    eng.run_to_block(case)
    return case


# --------------------------------------------------------------------------- #
# stage transitions
# --------------------------------------------------------------------------- #

def test_clean_case_reaches_credential_gate():
    eng = CaseEngine()
    case = make_case()
    eng.run_to_block(case)
    assert case.status == CaseStatus.BLOCKED_HUMAN.value
    assert case.current_stage == 3
    assert case.stage(1).status == StageStatus.DONE.value
    assert case.stage(2).status == StageStatus.DONE.value


def test_stage1_parses_deadline_and_assets():
    eng = CaseEngine()
    case = make_case(deadline_raw="2026-06-29 23:45 EDT")
    eng.run_to_block(case)
    assert case.deadline_utc is not None
    assert case.deadline_kst is not None
    assert case.stage(1).output["required_assets"] == ["repo", "readme"]


def test_stage1_holds_when_no_assets():
    eng = CaseEngine()
    case = make_case(required_assets=[])
    eng.run_to_block(case)
    # RULES_INCOMPLETE -> retries exhaust -> case fails (no assets ever appear)
    assert case.status == CaseStatus.FAILED.value
    assert any(i.code == "RULES_INCOMPLETE" for i in eng.incidents)


def test_full_lifecycle_reaches_submitted():
    eng = CaseEngine()
    case = make_case()
    eng.run_to_block(case)
    # approve credential gate
    t3 = eng.pending_human_tasks(case.case_id)[0]
    eng.decide(case, t3.task_id, TaskDecision.APPROVE.value)
    eng.run_to_block(case)
    # approve submission gate
    t7 = eng.pending_human_tasks(case.case_id)[0]
    assert t7.stage == 7
    eng.decide(case, t7.task_id, TaskDecision.SUBMIT.value)
    assert case.status == CaseStatus.SUBMITTED.value
    assert all(s.status == StageStatus.DONE.value for s in case.stages)


# --------------------------------------------------------------------------- #
# human-gate blocking / decisions
# --------------------------------------------------------------------------- #

def test_advance_refuses_to_move_blocked_case():
    eng = CaseEngine()
    case = make_case()
    eng.run_to_block(case)
    assert case.status == CaseStatus.BLOCKED_HUMAN.value
    # advancing a parked case makes no progress until a decision is recorded
    assert eng.advance(case) is False
    assert case.current_stage == 3


def test_human_gate_blocks_until_decided():
    eng = CaseEngine()
    case = make_case()
    eng.run_to_block(case)
    assert case.stage(4).status == StageStatus.PENDING.value  # not yet reached
    t = eng.pending_human_tasks(case.case_id)[0]
    eng.decide(case, t.task_id, TaskDecision.APPROVE.value)
    eng.run_to_block(case)
    assert case.stage(4).status == StageStatus.DONE.value


def test_decide_rejects_invalid_option():
    eng = CaseEngine()
    case = make_case()
    eng.run_to_block(case)
    t = eng.pending_human_tasks(case.case_id)[0]
    with pytest.raises(ValueError):
        eng.decide(case, t.task_id, "not_an_option")


def test_decide_unknown_task_raises():
    eng = CaseEngine()
    case = make_case()
    with pytest.raises(KeyError):
        eng.decide(case, "ht-doesnotexist", TaskDecision.APPROVE.value)


def test_cannot_decide_twice():
    eng = CaseEngine()
    case = make_case()
    eng.run_to_block(case)
    t = eng.pending_human_tasks(case.case_id)[0]
    eng.decide(case, t.task_id, TaskDecision.APPROVE.value)
    with pytest.raises(ValueError):
        eng.decide(case, t.task_id, TaskDecision.APPROVE.value)


def test_credential_gate_defer_stalls_case():
    eng = CaseEngine()
    case = make_case()
    eng.run_to_block(case)
    t = eng.pending_human_tasks(case.case_id)[0]
    eng.decide(case, t.task_id, TaskDecision.DEFER.value)
    assert case.status == CaseStatus.STALLED.value


def test_credential_gate_cancel_abandons_case():
    eng = CaseEngine()
    case = make_case()
    eng.run_to_block(case)
    t = eng.pending_human_tasks(case.case_id)[0]
    eng.decide(case, t.task_id, TaskDecision.CANCEL.value)
    assert case.status == CaseStatus.ABANDONED.value
    assert case.is_terminal


def test_submission_gate_defer_marks_deferred():
    eng = CaseEngine()
    case = make_case()
    eng.run_to_block(case)
    eng.decide(case, eng.pending_human_tasks(case.case_id)[0].task_id,
               TaskDecision.APPROVE.value)
    eng.run_to_block(case)
    t7 = eng.pending_human_tasks(case.case_id)[0]
    eng.decide(case, t7.task_id, TaskDecision.DEFER.value)
    assert case.status == CaseStatus.DEFERRED.value


def test_submission_gate_skip_platform_submits_doc_first():
    eng = CaseEngine()
    case = make_case()
    eng.run_to_block(case)
    eng.decide(case, eng.pending_human_tasks(case.case_id)[0].task_id,
               TaskDecision.APPROVE.value)
    eng.run_to_block(case)
    t7 = eng.pending_human_tasks(case.case_id)[0]
    eng.decide(case, t7.task_id, TaskDecision.SKIP_PLATFORM.value)
    assert case.status == CaseStatus.SUBMITTED.value
    assert case.stage(7).output["submission_mode"] == "documentation_first"


# --------------------------------------------------------------------------- #
# exception class 1: blocked credential
# --------------------------------------------------------------------------- #

def test_blocked_credential_detected_and_skipped():
    eng = CaseEngine()
    case = make_case(credential_refs=["github", "dacon_api"],
                     credential_available={"github": True, "dacon_api": False})
    eng.run_to_block(case)
    t = eng.pending_human_tasks(case.case_id)[0]
    assert t.context["credentials"]["dacon_api"] == "missing"
    eng.decide(case, t.task_id, TaskDecision.SKIP_CREDENTIAL.value, note="dacon_api")
    assert "dacon_api" in case.disabled_integrations
    assert any(i.code == "CREDENTIAL_BLOCKED" and i.resolved for i in eng.incidents)


def test_builder_credential_boundary_reenters_stage3():
    eng = CaseEngine()
    case = make_case(build_tasks=["Make a live platform call to Automation Cloud"])
    eng.run_to_block(case)
    eng.decide(case, eng.pending_human_tasks(case.case_id)[0].task_id,
               TaskDecision.APPROVE.value)
    eng.run_to_block(case)
    # the blocked builder task re-enters Stage 3 -> a new credential gate appears
    pend = eng.pending_human_tasks(case.case_id)
    assert pend and pend[0].stage == 3
    assert any(i.code == "CREDENTIAL_BLOCKED" for i in eng.incidents)


# --------------------------------------------------------------------------- #
# exception class 2: stale rule
# --------------------------------------------------------------------------- #

def test_stale_critical_rule_posts_ack_gate():
    eng = CaseEngine()
    case = make_case(rule_drift={"deadline_raw": "2026-07-01 23:59 UTC"})
    eng.run_to_block(case)
    t = eng.pending_human_tasks(case.case_id)[0]
    assert t.stage == 2
    assert "deadline_raw" in t.context["drifted_fields"]
    assert any(i.code == "STALE_RULE_CHANGED" for i in eng.incidents)


def test_stale_rule_acknowledged_folds_new_value_and_continues():
    eng = CaseEngine()
    case = make_case(rule_drift={"deadline_raw": "2026-07-05 12:00 UTC"})
    eng.run_to_block(case)
    t = eng.pending_human_tasks(case.case_id)[0]
    eng.decide(case, t.task_id, TaskDecision.APPROVE.value)
    eng.run_to_block(case)
    assert case.rule_drift_acknowledged
    assert case.competition.deadline_raw == "2026-07-05 12:00 UTC"
    assert case.competition.rule_drift == {}
    # now parked at the credential gate (Stage 3) having cleared Stage 2
    assert case.current_stage == 3


def test_stale_rule_ack_cancel_abandons():
    eng = CaseEngine()
    case = make_case(rule_drift={"deadline_raw": "2026-07-05 12:00 UTC"})
    eng.run_to_block(case)
    t = eng.pending_human_tasks(case.case_id)[0]
    eng.decide(case, t.task_id, TaskDecision.CANCEL.value)
    assert case.status == CaseStatus.ABANDONED.value


def test_non_critical_drift_retries_without_gate():
    eng = CaseEngine()
    case = make_case(rule_drift={"track_color": "blue"})  # non-critical field
    eng.run_to_block(case)
    # no stale-rule gate; case proceeds to the credential gate
    pend = eng.pending_human_tasks(case.case_id)
    assert pend and pend[0].stage == 3
    assert any(i.code == "STALE_RULE_CHANGED" for i in eng.incidents)


# --------------------------------------------------------------------------- #
# exception class 3: timezone conflict
# --------------------------------------------------------------------------- #

def test_timezone_conflict_resolves_conservative():
    eng = CaseEngine()
    case = make_case(deadline_raw="2026-06-29 23:45 EDT / 20:45 PDT")
    eng.run_to_block(case)
    assert case.deadline_flag == "DEADLINE_CONSERVATIVE"
    assert any(i.code == "DEADLINE_CONFLICT" and i.resolved for i in eng.incidents)


def test_parse_deadline_picks_earlier_edt():
    # EDT (UTC-4) is the earlier wall-clock cutoff vs PDT (UTC-7)
    utc, kst, zones = parse_deadline("2026-06-29 23:45 EDT / 23:45 PDT")
    assert "EDT" in zones and "PDT" in zones
    assert utc.endswith("03:45:00+00:00")   # 23:45 EDT == 03:45 UTC next day


def test_parse_deadline_kst_conversion():
    utc, kst, zones = parse_deadline("2026-07-01 23:59 KST")
    assert utc.endswith("14:59:00+00:00")   # 23:59 KST == 14:59 UTC
    assert kst.endswith("23:59:00+09:00")


# --------------------------------------------------------------------------- #
# exception class 4: platform upload failure + retry/backoff
# --------------------------------------------------------------------------- #

def test_upload_failure_retries_then_succeeds():
    eng = CaseEngine()
    case = make_case(upload_fails_first_attempt=True)
    eng.run_to_block(case)
    eng.decide(case, eng.pending_human_tasks(case.case_id)[0].task_id,
               TaskDecision.APPROVE.value)
    eng.run_to_block(case)
    t7 = eng.pending_human_tasks(case.case_id)[0]
    eng.decide(case, t7.task_id, TaskDecision.SUBMIT.value)
    assert case.status == CaseStatus.SUBMITTED.value
    inc = [i for i in eng.incidents if i.code == "PLATFORM_UPLOAD_FAILED"]
    assert inc and inc[0].resolved
    assert eng.backoff_log  # a backoff was recorded
    assert case.stage(7).output["upload"]["attempt"] == 2


def test_backoff_delays_are_exponential():
    eng = CaseEngine()
    case = make_case(upload_fails_first_attempt=True)
    eng.run_to_block(case)
    eng.decide(case, eng.pending_human_tasks(case.case_id)[0].task_id,
               TaskDecision.APPROVE.value)
    eng.run_to_block(case)
    eng.decide(case, eng.pending_human_tasks(case.case_id)[0].task_id,
               TaskDecision.SUBMIT.value)
    delays = [b["delay_s"] for b in eng.backoff_log if b["stage"] == 7]
    assert delays and delays[0] == 1   # 2**0


# --------------------------------------------------------------------------- #
# bonus exception: artifact secret quarantine + scrub re-entry
# --------------------------------------------------------------------------- #

def test_unsafe_artifact_quarantined_then_scrubbed():
    eng = CaseEngine()
    case = make_case(build_tasks=["Implement code reading the api key secret"])
    eng.run_to_block(case)
    eng.decide(case, eng.pending_human_tasks(case.case_id)[0].task_id,
               TaskDecision.APPROVE.value)
    eng.run_to_block(case)
    assert case.artifacts_scrubbed
    inc = [i for i in eng.incidents if i.code == "ARTIFACT_SECRET_FOUND"]
    assert inc and inc[0].resolved
    # after scrub, readiness secret-scan passes
    eng.decide(case, eng.pending_human_tasks(case.case_id)[0].task_id,
               TaskDecision.SUBMIT.value)
    assert case.status == CaseStatus.SUBMITTED.value


# --------------------------------------------------------------------------- #
# retry / escalation policy (generic)
# --------------------------------------------------------------------------- #

def test_stage_retry_increments_attempts_then_fails():
    eng = CaseEngine()
    case = make_case(required_assets=[])  # stage 1 always returns not-ok
    eng.run_to_block(case)
    assert case.stage(1).attempts == case.stage(1).max_attempts
    assert case.status == CaseStatus.FAILED.value


def test_reenter_resets_intermediate_stages():
    eng = CaseEngine()
    case = make_case(build_tasks=["Make a live platform call to Automation Cloud"])
    eng.run_to_block(case)
    eng.decide(case, eng.pending_human_tasks(case.case_id)[0].task_id,
               TaskDecision.APPROVE.value)
    eng.run_to_block(case)
    # after re-entry to Stage 3, Stage 4/5 were reset to pending
    assert case.current_stage == 3
    assert case.stage(4).status == StageStatus.PENDING.value
    assert case.stage(5).status == StageStatus.PENDING.value


# --------------------------------------------------------------------------- #
# readiness scoring
# --------------------------------------------------------------------------- #

def test_readiness_report_scores_and_passes():
    eng = CaseEngine()
    case = make_case()
    eng.run_to_block(case)
    eng.decide(case, eng.pending_human_tasks(case.case_id)[0].task_id,
               TaskDecision.APPROVE.value)
    eng.run_to_block(case)
    r = case.readiness
    assert r is not None
    assert 0.0 <= r.score <= 1.0
    assert r.passed is True
    assert not r.critical_failures


def test_readiness_dict_includes_passed_flag():
    eng = CaseEngine()
    case = make_case()
    eng.run_to_block(case)
    eng.decide(case, eng.pending_human_tasks(case.case_id)[0].task_id,
               TaskDecision.APPROVE.value)
    eng.run_to_block(case)
    d = case.readiness.to_dict()
    assert "passed" in d and "score" in d and "items" in d


# --------------------------------------------------------------------------- #
# audit append-only-ness + provenance
# --------------------------------------------------------------------------- #

def test_audit_is_append_only_and_grows():
    eng = CaseEngine()
    case = make_case()
    n0 = len(eng.audit)
    eng.run_to_block(case)
    n1 = len(eng.audit)
    assert n1 > n0
    # the events list is a copy; mutating it does not touch the trail
    evs = eng.audit.events
    evs.clear()
    assert len(eng.audit) == n1


def test_every_audit_event_has_provenance():
    eng = CaseEngine()
    case = make_case()
    eng.run_to_block(case)
    for ev in eng.audit.for_case(case.case_id):
        assert ev.case_id == case.case_id
        assert ev.actor and ev.action and ev.ts
        assert 1 <= ev.stage <= 7


def test_human_decision_is_audited_with_operator():
    eng = CaseEngine()
    case = make_case()
    eng.run_to_block(case)
    t = eng.pending_human_tasks(case.case_id)[0]
    eng.decide(case, t.task_id, TaskDecision.APPROVE.value, operator_id="alice")
    dec = [e for e in eng.audit.for_case(case.case_id) if e.action == "human_decision"]
    assert dec and "alice" in dec[0].actor


def test_audit_write(tmp_path):
    eng = CaseEngine()
    case = make_case()
    eng.run_to_block(case)
    p = tmp_path / "audit.json"
    eng.audit.write(str(p))
    import json
    data = json.loads(p.read_text())
    assert data["count"] == len(eng.audit)
    assert data["events"]


# --------------------------------------------------------------------------- #
# portfolio orchestrator
# --------------------------------------------------------------------------- #

def test_portfolio_has_six_competitions():
    assert len(portfolio()) == 6


def test_orchestrator_seeds_and_runs_all():
    orch = PortfolioOrchestrator()
    cases = orch.seed()
    assert len(cases) == 6
    orch.run_all()
    # every case has at least reached its first gate or terminal
    for c in orch.cases.values():
        assert c.current_stage >= 2


def test_snapshot_totals_consistent():
    orch = PortfolioOrchestrator()
    orch.seed()
    orch.run_all()
    snap = orch.snapshot()
    assert snap["totals"]["cases"] == 6
    assert len(snap["cases"]) == 6
    assert isinstance(snap["pending_human_tasks"], list)


def test_models_to_dict_roundtrip():
    case = make_case()
    d = case.to_dict()
    assert d["case_id"] == case.case_id
    assert len(d["stages"]) == 7
    assert d["competition"]["key"] == "t"
