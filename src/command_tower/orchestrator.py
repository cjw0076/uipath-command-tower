"""Portfolio orchestrator: load the six competitions, run every case.

The Command Tower runs a *portfolio* of parallel competitions, each as its own
Maestro case. This module seeds the six-competition portfolio (the real sibling
projects in this workspace), registers each as a case on the backend, advances
every case to its first wall, and exposes a single consolidated view of pending
human tasks + readiness across the whole portfolio.

The six competitions are deliberately seeded to exercise the full exception
surface between them:

* a clean case (no exceptions),
* a timezone-conflict case (PDT/EDT),
* a stale-rule case (deadline moved after intake),
* a blocked-credential case (a missing credential),
* a platform-upload-failure case (fails the first submit attempt),
* an artifact-secret case (a builder produces an unsafe artifact).
"""

from __future__ import annotations

from typing import Any

from .case_engine import CaseEngine
from .maestro_adapter import LocalMaestroBackend, MaestroBackend
from .models import Case, Competition, build_stages, new_id


# ---------------------------------------------------------------------------
# the six-competition portfolio
# ---------------------------------------------------------------------------

def portfolio() -> list[Competition]:
    """The six real sibling competitions, seeded to cover every exception."""
    return [
        Competition(
            key="uipath_agenthack",
            name="UiPath AgentHack 2026",
            rules_url="https://uipath-agenthack.devpost.com/rules",
            deadline_raw="2026-06-29 23:45 EDT (PDT header on Devpost)",
            track_name="Maestro Case",
            required_assets=["public repo", "demo video", "deck", "README",
                             "live Automation Cloud run"],
            credential_refs=["uipath_cloud", "github"],
            credential_available={"uipath_cloud": True, "github": True},
            upload_fails_first_attempt=False,
            build_tasks=[
                "Implement the case engine endpoint",
                "Write the pytest suite for stage transitions",
                "Draft the README wording and Devpost description",
                "Produce the demo script narration",
            ],
        ),
        Competition(
            key="splunk_agentic_ops",
            name="Splunk Agentic Ops 2026",
            rules_url="https://splunkbuild.devpost.com/rules",
            # both PDT and EDT in the text -> timezone conflict
            deadline_raw="2026-06-27 17:00 PDT / 20:00 EDT",
            track_name="Agentic SOC Copilot",
            required_assets=["public repo", "demo video", "README"],
            credential_refs=["splunk_cloud", "github"],
            credential_available={"splunk_cloud": True, "github": True},
            build_tasks=[
                "Implement the SPL backend code",
                "Write detection tests",
                "Draft the README wording",
            ],
        ),
        Competition(
            key="find_evil",
            name="FIND EVIL! DFIR 2026",
            rules_url="https://findevil.example/rules",
            deadline_raw="2026-06-25 23:59 UTC",
            track_name="Evidence-Linked Triage",
            required_assets=["public repo", "demo video", "README"],
            credential_refs=["github"],
            credential_available={"github": True},
            # rules drifted after intake: deadline moved earlier (critical field)
            rule_drift={"deadline_raw": "2026-06-24 23:59 UTC"},
            build_tasks=[
                "Implement the triage analyzers code",
                "Write the analyzer tests",
                "Draft the demo script",
            ],
        ),
        Competition(
            key="etri_sleep",
            name="DACON ETRI Sleep 236690",
            rules_url="https://dacon.io/competitions/official/236690/rules",
            deadline_raw="2026-07-15 23:59 KST",
            track_name="Sleep Metric Regression",
            required_assets=["submission csv", "code", "writeup"],
            credential_refs=["dacon_api", "kaggle"],
            # dacon_api is MISSING -> blocked-credential exception at Stage 3
            credential_available={"dacon_api": False, "kaggle": True},
            public_repo_required=False,
            coding_agent_bonus=False,
            build_tasks=[
                "Implement the sleep-period detection code",
                "Write validation tests",
                "Draft the writeup wording",
            ],
        ),
        Competition(
            key="aibias_bbq",
            name="DACON AI-Bias BBQ 236722",
            rules_url="https://dacon.io/competitions/official/236722/rules",
            deadline_raw="2026-07-01 23:59 KST",
            track_name="VQA Bias Mitigation",
            required_assets=["submission csv", "code"],
            credential_refs=["dacon_api"],
            credential_available={"dacon_api": True},
            # submission upload fails the first attempt -> retry/backoff path
            upload_fails_first_attempt=True,
            public_repo_required=False,
            coding_agent_bonus=False,
            build_tasks=[
                "Implement the VLM inference code",
                "Write the consensus tests",
            ],
        ),
        Competition(
            key="rapid_genai",
            name="Rapid GenAI Hackathon 2026",
            rules_url="https://rapid-genai.example/rules",
            deadline_raw="2026-06-28 23:45 EDT (PDT also listed)",
            track_name="Cloud Run Copilot",
            required_assets=["public repo", "demo video", "deck", "README"],
            credential_refs=["gcp", "github"],
            credential_available={"gcp": True, "github": True},
            build_tasks=[
                # this task name routes the executor to an unsafe artifact ->
                # ARTIFACT_SECRET_FOUND, exercising the quarantine path
                "Implement the deploy script that reads the GCP api key secret",
                "Write deployment tests",
                "Draft the README wording",
                "Produce the demo script narration",
            ],
        ),
    ]


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------

class PortfolioOrchestrator:
    """Registers + advances every competition case on a Maestro backend."""

    def __init__(self, backend: MaestroBackend | None = None) -> None:
        self.backend = backend or LocalMaestroBackend()
        self.cases: dict[str, Case] = {}

    @property
    def engine(self) -> CaseEngine:
        # only the local backend exposes a live engine; the cloud path advances
        # via Maestro itself.
        return getattr(self.backend, "engine")  # noqa: B009

    def seed(self, competitions: list[Competition] | None = None) -> list[Case]:
        comps = competitions if competitions is not None else portfolio()
        out: list[Case] = []
        for comp in comps:
            case = Case(case_id=new_id("case"), competition=comp, stages=build_stages())
            self.backend.register_case(case)
            self.cases[case.case_id] = case
            out.append(case)
        return out

    def run_all(self) -> list[Case]:
        """Advance every case to its first wall (block / terminal)."""
        for case in self.cases.values():
            self.backend.advance_case(case)
        return list(self.cases.values())

    # ---- consolidated views ----------------------------------------------
    def pending_human_tasks(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.backend.pending_human_tasks()]

    def incidents(self) -> list[dict[str, Any]]:
        eng = getattr(self.backend, "engine", None)
        if eng is None:
            return []
        return [i.to_dict() for i in eng.incidents]

    def readiness_summary(self) -> list[dict[str, Any]]:
        out = []
        for case in self.cases.values():
            r = case.readiness
            out.append({"case_id": case.case_id, "name": case.competition.name,
                        "score": r.score if r else None,
                        "passed": r.passed if r else None,
                        "status": case.status})
        return out

    def snapshot(self) -> dict[str, Any]:
        """A single consolidated portfolio view (used by CLI + eval + webapp)."""
        cases = [c.to_dict() for c in self.cases.values()]
        return {
            "cases": cases,
            "pending_human_tasks": self.pending_human_tasks(),
            "incidents": self.incidents(),
            "readiness": self.readiness_summary(),
            "totals": {
                "cases": len(cases),
                "blocked_human": sum(1 for c in cases if c["status"] == "blocked_human"),
                "submitted": sum(1 for c in cases if c["status"] == "submitted"),
                "incidents": len(self.incidents()),
            },
        }
