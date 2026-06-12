"""Evaluation harness for the Competition Command Tower.

Runs the SAME engine across the whole six-competition portfolio and reports a
real benchmark table from real runs — no hardcoded numbers. It plays a
deterministic auto-operator that clears every human gate (approve / skip /
submit), then measures, per case:

* terminal_status   — submitted / deferred / abandoned / failed / stalled
* stages_completed  — how many of the seven stages reached DONE
* readiness_score   — Stage-6 completeness score (0..1)
* incidents         — exception classes raised on this case
* exceptions_resolved — were all raised incidents resolved?
* human_gates       — number of human-task decisions the case required
* audit_events      — provenance records emitted for this case

Aggregates cover the whole portfolio plus the distinct exception classes the
engine exercised. The eval doubles as a CI gate: it exits non-zero unless every
case reaches a terminal state with all its incidents resolved and (for cases
that submit) a passing readiness audit.

Usage:
    PYTHONPATH=src python3 eval/run_eval.py [--json eval/report.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from command_tower.case_engine import CaseEngine  # noqa: E402
from command_tower.maestro_adapter import LocalMaestroBackend  # noqa: E402
from command_tower.models import TaskDecision  # noqa: E402
from command_tower.orchestrator import PortfolioOrchestrator  # noqa: E402


def _auto_operator(orch: PortfolioOrchestrator, max_rounds: int = 16) -> None:
    eng: CaseEngine = orch.engine
    for _ in range(max_rounds):
        tasks = eng.pending_human_tasks()
        if not tasks:
            return
        for t in tasks:
            case = orch.cases[t.case_id]
            comp = case.competition
            if t.stage == 2:
                eng.decide(case, t.task_id, TaskDecision.APPROVE.value)
            elif t.stage == 3:
                missing = [r for r in comp.credential_refs
                           if not comp.credential_available.get(r, False)]
                if missing:
                    eng.decide(case, t.task_id, TaskDecision.SKIP_CREDENTIAL.value,
                               note="; ".join(missing))
                else:
                    eng.decide(case, t.task_id, TaskDecision.APPROVE.value)
            elif t.stage == 7:
                eng.decide(case, t.task_id, TaskDecision.SUBMIT.value)
            orch.backend.advance_case(case)


def run_portfolio() -> tuple[PortfolioOrchestrator, list[dict]]:
    backend = LocalMaestroBackend()
    orch = PortfolioOrchestrator(backend=backend)
    orch.seed()
    orch.run_all()
    _auto_operator(orch)

    eng = orch.engine
    results = []
    for case in orch.cases.values():
        cid = case.case_id
        incs = eng.case_incidents(cid)
        audit = eng.audit.for_case(cid)
        stages_done = sum(1 for s in case.stages if s.status == "done")
        results.append({
            "case_id": cid,
            "name": case.competition.name,
            "track": case.competition.track_name,
            "terminal_status": case.status,
            "stages_completed": stages_done,
            "readiness_score": case.readiness.score if case.readiness else None,
            "readiness_passed": case.readiness.passed if case.readiness else None,
            "deadline_flag": case.deadline_flag,
            "incidents": sorted({i.code for i in incs}),
            "incidents_resolved": all(i.resolved for i in incs),
            "human_gates": sum(1 for e in audit if e.action == "human_decision"),
            "audit_events": len(audit),
            "disabled_integrations": case.disabled_integrations,
        })
    return orch, results


def aggregate(orch: PortfolioOrchestrator, results: list[dict]) -> dict:
    n = len(results)
    submitted = [r for r in results if r["terminal_status"] == "submitted"]
    scored = [r for r in results if r["readiness_score"] is not None]
    all_codes = sorted({c for r in results for c in r["incidents"]})

    def avg(vals):
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    return {
        "cases": n,
        "submitted": len(submitted),
        "terminal_rate": round(sum(1 for r in results
                                   if r["terminal_status"] in
                                   ("submitted", "deferred", "abandoned")) / n, 3),
        "mean_readiness": avg([r["readiness_score"] for r in scored]),
        "mean_stages_completed": avg([r["stages_completed"] for r in results]),
        "total_human_gates": sum(r["human_gates"] for r in results),
        "total_incidents": len(orch.engine.incidents),
        "incidents_all_resolved": all(i.resolved for i in orch.engine.incidents),
        "distinct_exception_classes": all_codes,
        "distinct_exception_count": len(all_codes),
        "total_audit_events": len(orch.engine.audit),
        "retry_events": len(orch.engine.backoff_log),
    }


_C = {"h": "\033[1;36m", "ok": "\033[1;32m", "bad": "\033[1;31m",
      "dim": "\033[2m", "x": "\033[0m"}


def _color():
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(k, t):
    return f"{_C[k]}{t}{_C['x']}" if _color() else t


def print_table(results, agg):
    print(c("h", "\n== COMPETITION COMMAND TOWER — PORTFOLIO EVALUATION ==\n"))
    hdr = (f"{'competition':<30}{'status':<14}{'stages':>7}{'ready':>7}"
           f"{'gates':>6}{'exc':>5}  exceptions")
    print(c("dim", hdr))
    print(c("dim", "-" * 92))
    for r in results:
        ready = r["readiness_score"]
        print(f"{r['name']:<30}{r['terminal_status']:<14}"
              f"{str(r['stages_completed'])+'/7':>7}"
              f"{(str(ready) if ready is not None else '-'):>7}"
              f"{r['human_gates']:>6}{len(r['incidents']):>5}  "
              f"{', '.join(r['incidents']) or '-'}")
    print(c("dim", "-" * 92))
    print()
    print(f"  cases / submitted          : {agg['cases']} / {agg['submitted']}")
    print(f"  terminal rate              : {int(agg['terminal_rate']*100)}%")
    print(f"  mean readiness score       : {agg['mean_readiness']}")
    print(f"  mean stages completed      : {agg['mean_stages_completed']} / 7")
    print(f"  human-gate decisions       : {agg['total_human_gates']}")
    print(f"  incidents (all resolved)   : {agg['total_incidents']} "
          f"({c('ok','yes') if agg['incidents_all_resolved'] else c('bad','NO')})")
    print(f"  distinct exception classes : {agg['distinct_exception_count']} "
          f"({', '.join(agg['distinct_exception_classes'])})")
    print(f"  retry/backoff events       : {agg['retry_events']}")
    print(f"  total audit events         : {agg['total_audit_events']}")
    print()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Evaluate the command tower across the portfolio.")
    p.add_argument("--json", default=os.path.join(ROOT, "eval", "report.json"),
                   help="path to write the JSON benchmark report")
    args = p.parse_args(argv)

    orch, results = run_portfolio()
    agg = aggregate(orch, results)
    print_table(results, agg)

    report = {"schema": "command_tower_eval/1.0", "synthetic": True,
              "aggregate": agg, "cases": results}
    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(c("ok", f"JSON report written: {args.json}"))

    # CI gate: every case terminal, every incident resolved, ≥4 exception classes
    ok = (agg["incidents_all_resolved"]
          and all(r["terminal_status"] in ("submitted", "deferred", "abandoned")
                  for r in results)
          and agg["distinct_exception_count"] >= 4
          and all(r["readiness_passed"] in (True, None) for r in results))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
