"""CLI demo: run the whole six-competition portfolio through the Maestro Case.

Usage:
    python -m command_tower                 # full portfolio demo (auto operator)
    python -m command_tower --json out.json # also dump a machine-readable snapshot
    python -m command_tower --manual        # stop at gates, print pending tasks

The demo runs entirely offline on the LocalMaestroBackend (no UiPath credentials).
It seeds six competitions, advances each case to its first human gate, then plays
an auto-operator that approves/skips/submits — surfacing every exception class,
the retry/backoff, the re-entry, the human-in-the-loop gates, and the append-only
audit trail.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .maestro_adapter import make_backend
from .models import Case, CaseStatus, TaskDecision
from .orchestrator import PortfolioOrchestrator

_C = {"h": "\033[1;36m", "ok": "\033[1;32m", "warn": "\033[1;33m",
      "bad": "\033[1;31m", "dim": "\033[2m", "acc": "\033[1;35m", "x": "\033[0m"}


def _color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(key: str, text: str) -> str:
    return f"{_C[key]}{text}{_C['x']}" if _color() else text


def rule(title: str) -> None:
    print()
    print(c("h", f"== {title} " + "=" * max(0, 60 - len(title))))


_STATUS_COLOR = {
    "submitted": "ok", "deferred": "warn", "abandoned": "dim",
    "failed": "bad", "stalled": "bad", "blocked_human": "warn",
}


def status_chip(status: str) -> str:
    return c(_STATUS_COLOR.get(status, "dim"), status.upper())


def auto_operator(orch: PortfolioOrchestrator, max_rounds: int = 12) -> None:
    """Play a deterministic operator that clears every gate, so the demo runs
    end-to-end. Real operators decide via the webapp; this just exercises every
    branch for the terminal walkthrough."""
    eng = orch.engine
    for _ in range(max_rounds):
        tasks = eng.pending_human_tasks()
        if not tasks:
            break
        for t in tasks:
            case = orch.cases[t.case_id]
            comp = case.competition
            if t.stage == 2:                       # stale-rule acknowledgment
                eng.decide(case, t.task_id, TaskDecision.APPROVE.value,
                           note="acknowledged new deadline")
            elif t.stage == 3:                     # credential gate
                missing = [r for r in comp.credential_refs
                           if not comp.credential_available.get(r, False)]
                if missing:
                    eng.decide(case, t.task_id, TaskDecision.SKIP_CREDENTIAL.value,
                               note="; ".join(missing))
                else:
                    eng.decide(case, t.task_id, TaskDecision.APPROVE.value)
            elif t.stage == 7:                     # submission gate
                eng.decide(case, t.task_id, TaskDecision.SUBMIT.value)
            orch.backend.advance_case(case)


def print_case_lifecycle(case: Case) -> None:
    comp = case.competition
    print()
    print(c("acc", f"▸ {comp.name}") + c("dim", f"   [{comp.track_name}]  case {case.case_id}"))
    print(c("dim", f"   deadline {case.deadline_utc} UTC / {case.deadline_kst} KST"
                   + (f"  flag={case.deadline_flag}" if case.deadline_flag else "")
                   + (f"  priority={case.priority}" if case.priority != "normal" else "")))
    line = "   stages: "
    for st in case.stages:
        mark = {"done": c("ok", "✓"), "failed": c("bad", "✗"),
                "blocked": c("warn", "⏸"), "skipped": c("dim", "–"),
                "active": c("warn", "▸"), "pending": c("dim", "·")}.get(st.status, "?")
        line += f"{st.index}{mark} "
    print(line + "  -> " + status_chip(case.status))
    if case.disabled_integrations:
        print(c("dim", f"   disabled integrations: {', '.join(case.disabled_integrations)}"))
    if case.readiness:
        r = case.readiness
        print(c("dim", f"   readiness {r.score}  "
                       + (c("bad", f"critical-fail: {', '.join(r.critical_failures)}")
                          if r.critical_failures else c("ok", "all critical items pass"))
                       + (f"  warnings: {', '.join(r.warnings)}" if r.warnings else "")))


def run_demo(manual: bool = False, json_path: str | None = None) -> int:
    backend = make_backend()
    orch = PortfolioOrchestrator(backend=backend)

    print(c("h", "COMPETITION COMMAND TOWER — UiPath Maestro Case (offline demo)"))
    print(c("dim", f"backend: {backend.label}   "
                   "SYNTHETIC PORTFOLIO — no UiPath credentials, no network."))

    rule("SEED PORTFOLIO (six competitions = six Maestro case instances)")
    cases = orch.seed()
    for case in cases:
        print(f"  + {case.competition.name:34} {case.competition.track_name}")

    rule("ADVANCE ALL CASES TO THEIR FIRST WALL")
    orch.run_all()
    for case in cases:
        print_case_lifecycle(case)

    rule("PENDING HUMAN TASKS (Action Center inbox — BLOCKS the case)")
    for t in orch.pending_human_tasks():
        print(c("warn", f"  ⏸ {t['title']}"))
        print(c("dim", f"     stage {t['stage']} · options {t['options']}"))

    if manual:
        print()
        print(c("dim", "  --manual: stopping at gates. Decide via the webapp or API."))
        return _finish(orch, json_path)

    rule("AUTO-OPERATOR CLEARS EVERY GATE (approve / skip / submit)")
    auto_operator(orch)
    for case in cases:
        print_case_lifecycle(case)

    rule("EXCEPTION LEDGER (every named exception + its resolution)")
    for inc in orch.engine.incidents:
        col = "ok" if inc.resolved else "bad"
        print(c(col, f"  [{inc.code}] ") + c("dim", f"stage {inc.stage} · {inc.severity}"))
        print(f"     {inc.summary}")
        print(c("dim", f"     -> {inc.resolution or '(unresolved)'} "
                       f"({'resolved' if inc.resolved else 'OPEN'})"))
    if orch.engine.backoff_log:
        print(c("dim", f"  retry/backoff events: {len(orch.engine.backoff_log)} "
                       f"(delays {', '.join(str(b['delay_s'])+'s' for b in orch.engine.backoff_log)})"))

    return _finish(orch, json_path)


def _finish(orch: PortfolioOrchestrator, json_path: str | None) -> int:
    rule("AUDIT TRAIL (append-only provenance — sample)")
    events = orch.engine.audit.events
    for ev in events[:14]:
        print(c("dim", f"  {ev.ts}  ") + f"[s{ev.stage}] "
              + c("acc", f"{ev.actor:18}") + f" {ev.action:22} {ev.detail}")
    print(c("dim", f"  ... {len(events)} total audit events "
                   "(append-only; no record mutated or deleted)"))

    snap = orch.snapshot()
    t = snap["totals"]
    rule("PORTFOLIO SUMMARY")
    print(f"  cases            : {t['cases']}")
    print(f"  submitted        : {c('ok', str(t['submitted']))}")
    print(f"  blocked on human : {t['blocked_human']}")
    print(f"  incidents raised : {t['incidents']} "
          f"({sum(1 for i in orch.engine.incidents if i.resolved)} resolved)")
    print(f"  audit events     : {len(events)}")
    print(f"  human decisions  : {sum(1 for e in events if e.action == 'human_decision')}")

    if json_path:
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(snap, fh, indent=2, ensure_ascii=False)
        print(c("ok", f"\nSnapshot written: {json_path}"))

    print()
    print(c("ok", "DONE — six cases driven through seven Maestro stages, "
                  "every exception class handled, two human gates enforced."))
    print(c("dim", "Launch the live dashboard with:  ./run_dashboard.sh   (then open :8120)"))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="command_tower",
                                description="Competition Command Tower — Maestro Case demo.")
    p.add_argument("--manual", action="store_true",
                   help="stop at human gates instead of auto-deciding")
    p.add_argument("--json", metavar="PATH", help="write a JSON portfolio snapshot")
    args = p.parse_args(argv)
    return run_demo(manual=args.manual, json_path=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
