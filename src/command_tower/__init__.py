"""Competition Command Tower — a UiPath Maestro Case engine.

A real, offline-runnable agentic case-management system modelled on UiPath
Maestro Case: each competition is a case advancing through seven stages with
exception handling, retry/backoff, re-entry, blocking human-in-the-loop gates,
multi-agent work routing, and an append-only audit trail.

Public API::

    from command_tower import (
        CaseEngine, PortfolioOrchestrator, portfolio,
        LocalMaestroBackend, UiPathMaestroBackend, make_backend,
        Case, Competition, build_stages,
    )
"""

from __future__ import annotations

from .audit import AuditTrail
from .case_engine import CaseEngine
from .maestro_adapter import (
    LocalMaestroBackend, MaestroBackend, UiPathMaestroBackend, make_backend,
)
from .models import (
    Case, CaseStatus, Competition, HumanTask, Incident, ReadinessReport,
    Severity, Stage, StageStatus, TaskDecision, build_stages,
)
from .orchestrator import PortfolioOrchestrator, portfolio

__version__ = "1.0.0"

__all__ = [
    "AuditTrail", "CaseEngine", "PortfolioOrchestrator", "portfolio",
    "LocalMaestroBackend", "UiPathMaestroBackend", "MaestroBackend",
    "make_backend", "Case", "CaseStatus", "Competition", "HumanTask",
    "Incident", "ReadinessReport", "Severity", "Stage", "StageStatus",
    "TaskDecision", "build_stages", "__version__",
]
