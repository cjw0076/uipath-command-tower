# Deficiency Closure — UiPath AgentHack 2026

## Goal

Move from "good package" to "prize-safe package" by closing the official judging gaps for UiPath AgentHack 2026.

Official source: `https://uipath-agenthack.devpost.com/`

## Official Criteria → Evidence

| Criterion | Current evidence | Closure state |
|---|---|---|
| Business Impact & Adoption Potential | Real six-competition control-plane problem; exception-heavy portfolio workflow; reusable for teams running parallel Devpost/contest entries. | Closed |
| Platform Usage | Maestro Case is the core abstraction; seven stages, two Action Center human gates, Maestro AI Agent stages, Robot intake/audit, dual Local/UiPath backend. | Mostly closed; live Automation Cloud proof still required. |
| Technical Execution, Feasibility & Versatility | `58` passing tests, deterministic eval, dual backend, mocked UiPath REST tests, exception/retry/re-entry policy, FastAPI dashboard. | Closed |
| Completeness of Delivery | Public repo, README, setup instructions, demo video, deck doc, eval report, submission package. | Mostly closed; live Automation Cloud URL still required. |
| Creativity & Innovation | Uses Maestro Case for a real meta-orchestration problem: governing coding agents and submissions, not a toy workflow. | Closed |
| Presentation | Demo video, 10-slide deck, hero visual, README, architecture diagram, Devpost copy. | Closed; supplemental live clip would improve after Automation Cloud deployment. |
| Coding-agent bonus | Claude Code, Codex, and Gemini evidence chain in `docs/agent_evidence_appendix.md`; Stage 5 routes coding-agent lanes. | Closed |

## Remaining P0 Gap

**Live UiPath Automation Cloud proof is missing.**

The official page states that solutions must run on UiPath Automation Cloud. Without a live tenant URL or OAuth-backed run evidence, the entry risks losing Platform Usage and Completeness points even though the local system works.

### Founder-Gated Values Needed

Provide these through a secure channel or active environment, never in public docs:

- `UIPATH_CLIENT_ID`
- `UIPATH_CLIENT_SECRET`
- `UIPATH_ORG`
- `UIPATH_TENANT`
- `UIPATH_FOLDER_ID`
- required scopes/permissions for Orchestrator, Maestro process instances, and Action Center tasks

Equivalent alternative: founder manually deploys/imports in Automation Cloud and returns the live Maestro/Orchestrator URL plus one screenshot.

## When Values Arrive

Run:

```bash
export UIPATH_CLIENT_ID=...
export UIPATH_CLIENT_SECRET=...
export UIPATH_ORG=...
export UIPATH_TENANT=...
export UIPATH_FOLDER_ID=...

PYTHONPATH=src python -c "from command_tower.maestro_adapter import make_backend; print(type(make_backend()).__name__)"
PYTHONPATH=src python -m command_tower
python -m pytest -q
python eval/run_eval.py
```

Expected backend: `UiPathMaestroBackend`.

## Devpost Finalization Rule

Prepare/fill all fields, but final external submit remains founder-gated unless explicit current-session final-submit confirmation is given.
