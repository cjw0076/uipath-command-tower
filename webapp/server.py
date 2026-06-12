"""FastAPI backend for the Competition Command Tower dashboard.

Hosts a live, stateful portfolio: it seeds the six competitions, advances every
case to its first wall, and serves the consolidated Maestro Case view. The
dashboard is genuinely interactive — the operator clears the blocking human-task
gates (credential gate, stale-rule acknowledgment, submission gate) right from
the browser, and the engine advances the case in response.

Runs entirely offline on the LocalMaestroBackend (no UiPath credentials). Set the
``UIPATH_CLIENT_ID``/``UIPATH_CLIENT_SECRET`` env vars and ``make_backend`` will
target a live Automation Cloud tenant instead — same API surface.

Endpoints:
    GET  /                         -> the dashboard SPA
    GET  /api/cases                -> all six cases (consolidated)
    GET  /api/case/{id}            -> one case (stages, output, readiness)
    GET  /api/incidents            -> exception ledger
    GET  /api/human-tasks          -> pending blocking gates
    POST /api/human-tasks/{id}/decide  -> operator decision (advances the case)
    GET  /api/audit                -> append-only audit trail
    POST /api/reset                -> reseed the portfolio
    GET  /api/health               -> liveness

Run:
    PYTHONPATH=src uvicorn webapp.server:app --host 127.0.0.1 --port 8120
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from command_tower.maestro_adapter import make_backend  # noqa: E402
from command_tower.orchestrator import PortfolioOrchestrator  # noqa: E402

WEB_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Competition Command Tower", version="1.0.0")


# ---------------------------------------------------------------------------
# live portfolio state (single in-process orchestrator)
# ---------------------------------------------------------------------------

class _State:
    def __init__(self) -> None:
        self.orch: PortfolioOrchestrator | None = None

    def ensure(self) -> PortfolioOrchestrator:
        if self.orch is None:
            self.reset()
        assert self.orch is not None
        return self.orch

    def reset(self) -> PortfolioOrchestrator:
        orch = PortfolioOrchestrator(backend=make_backend())
        orch.seed()
        orch.run_all()
        self.orch = orch
        return orch


STATE = _State()


def _orch() -> PortfolioOrchestrator:
    return STATE.ensure()


def _case_or_404(case_id: str):
    orch = _orch()
    case = orch.cases.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"unknown case {case_id}")
    return orch, case


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    orch = _orch()
    return {"status": "ok", "backend": orch.backend.label,
            "cases": len(orch.cases), "synthetic": orch.backend.label == "local"}


@app.get("/api/cases")
def cases():
    orch = _orch()
    snap = orch.snapshot()
    return {"backend": orch.backend.label,
            "cases": snap["cases"], "totals": snap["totals"]}


@app.get("/api/case/{case_id}")
def case_detail(case_id: str):
    orch, case = _case_or_404(case_id)
    d = case.to_dict()
    d["incidents"] = [i.to_dict() for i in orch.engine.case_incidents(case_id)]
    d["audit"] = [e.to_dict() for e in orch.engine.audit.for_case(case_id)]
    d["pending_human_tasks"] = [t.to_dict()
                                for t in orch.engine.pending_human_tasks(case_id)]
    return JSONResponse(d)


@app.get("/api/incidents")
def incidents():
    orch = _orch()
    return {"incidents": [i.to_dict() for i in orch.engine.incidents],
            "backoff": orch.engine.backoff_log}


@app.get("/api/human-tasks")
def human_tasks():
    orch = _orch()
    tasks = [t.to_dict() for t in orch.engine.pending_human_tasks()]
    # decorate each task with its competition name for the UI
    for t in tasks:
        case = orch.cases.get(t["case_id"])
        t["competition"] = case.competition.name if case else "-"
    return {"human_tasks": tasks}


class Decision(BaseModel):
    decision: str
    operator_id: str = "operator"
    note: str = ""


@app.post("/api/human-tasks/{task_id}/decide")
def decide(task_id: str, body: Decision):
    orch = _orch()
    task = orch.engine.human_tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"unknown task {task_id}")
    case = orch.cases.get(task.case_id)
    if case is None:  # pragma: no cover - defensive
        raise HTTPException(status_code=404, detail="case for task not found")
    try:
        orch.engine.decide(case, task_id, body.decision,
                           operator_id=body.operator_id, note=body.note)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # advance the case as far as it will go after the decision
    orch.backend.advance_case(case)
    return {"ok": True, "case_id": case.case_id, "case_status": case.status,
            "current_stage": case.current_stage}


@app.get("/api/audit")
def audit(limit: int = 200):
    orch = _orch()
    evs = orch.engine.audit.events[-limit:]
    return {"count": len(orch.engine.audit), "events": [e.to_dict() for e in evs]}


@app.post("/api/reset")
def reset():
    orch = STATE.reset()
    return {"ok": True, "cases": len(orch.cases)}


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as fh:
        return fh.read()
