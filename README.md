# Competition Command Tower

A UiPath Maestro Case workflow for managing a portfolio of parallel hackathon
competitions — automating rules intake, deadline monitoring, multi-agent work
routing, human-in-the-loop approval gates, and submission readiness checks.

## Track

- Hackathon: UiPath AgentHack 2026
- Track: UiPath Maestro Case
- Orchestration layer: UiPath Automation Cloud (Maestro)
- License: MIT

## The Problem

Running six or more parallel competitions simultaneously creates compounding
operational risks:

- Rules change between initial read and submission day without notification.
- Deadlines across PDT, EDT, and KST time zones conflict unpredictably.
- Platform access gates (API keys, cloud credentials, live sessions) block
  specific competitions without affecting others.
- Work must route to different AI agents (Claude Code, Codex, Gemini CLI)
  depending on task type, yet be consolidated into a single auditable readiness
  report.
- Human approvals for credential steps, public repo creation, and final
  submission must not be bypassed by automation.

A generic project-management tool cannot handle the exception density: blocked
credentials, stale rules, timezone conflicts, and multi-model agent lanes need
explicit case branches, retry policies, and escalation paths.

## The Solution: Maestro Case Workflow

Competition Command Tower is implemented as a UiPath Maestro **Case** — the
UiPath construct designed for dynamic, exception-heavy workflows that combine
robots, AI agents, and human decision points.

Each competition in the portfolio is a **case instance**. The case advances
through seven stages. Exceptions can re-enter any earlier stage, trigger a
human approval gate, or hold the case pending an operator credential action.

### Stages at a Glance

| Stage | Name | Primary actor |
|---|---|---|
| 1 | Contest Intake | UiPath Robot (scraper + rule parser) |
| 2 | Rule Verification | AI Agent (Claude Code / Codex / Gemini) |
| 3 | Credential & Access Gate | Human-in-the-loop approval |
| 4 | Work Routing | Maestro Case AI Agent |
| 5 | Builder Execution | AI coding agents (Codex / Claude) |
| 6 | Readiness Audit | AI Agent + Robot (checklist runner) |
| 7 | Submission Gate | Human-in-the-loop final approval |

Full stage specs, decision points, and exception paths are in
[docs/maestro_case_design.md](docs/maestro_case_design.md).

## Architecture

```text
Official contest pages / operator packets
  -> [Stage 1] Contest Intake  (Robot scrapes rules, deadlines, track)
  -> [Stage 2] Rule Verification  (AI Agent checks staleness and conflicts)
  -> [Stage 3] Credential Gate  (HITL: operator approves credential use)
  -> [Stage 4] Work Routing  (AI Agent dispatches to coding-agent lanes)
  -> [Stage 5] Builder Execution  (Codex / Claude / Gemini receive tasks)
  -> [Stage 6] Readiness Audit  (AI Agent + Robot produce checklist)
  -> [Stage 7] Submission Gate  (HITL: operator approves and submits)
  -> Devpost / platform submission + audit trail
```

Detailed Mermaid flowchart with agent/tool labels and exception paths:
[docs/architecture_diagram.md](docs/architecture_diagram.md).

## UiPath Components Used

| Component | Role |
|---|---|
| UiPath Maestro Case | Case lifecycle manager and stage router |
| Maestro AI Agent | Rule verification, work routing, readiness audit |
| UiPath Studio Web | Automation definition for stages 1 and 6 |
| UiPath Automation Cloud | Orchestration, credential store, human task inbox |
| Maestro Human Task | Credential gate (stage 3) and submission gate (stage 7) |
| Action Center | Operator review inbox for blocked cases |
| UiPath Integrations | GitHub, email (deadline alerts), Devpost webhook |

## Agent Type Disclosure

This project uses two agent types, as required by Devpost rules:

- **UiPath Maestro AI Agent** — orchestration-layer agent for rule verification
  and routing decisions, running inside UiPath Automation Cloud.
- **External coding agents** — Claude Code and Codex CLI contributed to design,
  document generation, and artifact construction during development (bonus-point
  track; evidence in
  [docs/agent_evidence_appendix.md](docs/agent_evidence_appendix.md)).

## Setup and Prerequisites

1. UiPath Automation Cloud account with Maestro enabled.
2. UiPath Studio Web for editing automation definitions.
3. A public GitHub repo for the submission target.
4. Optional: environment variables for platform integrations (GitHub token,
   email SMTP, Devpost API key if available). No keys are stored in this repo.

To deploy a new case instance for a competition:

```bash
# 1. Clone this repo and review the Maestro Case design.
git clone https://github.com/<your-org>/uipath-command-tower

# 2. Import the case definition into UiPath Studio Web.
#    Import file: maestro_case_definition/command_tower_case.json (when live)

# 3. Set Automation Cloud credentials (never store in files):
#    - GITHUB_TOKEN in the UiPath Credential Store
#    - DEVPOST_API_KEY in the Credential Store (if available)

# 4. Trigger case intake for a new competition:
#    Action: Maestro > New Case > Competition Command Tower > provide URL
```

For the documentation-first demonstration, all design artifacts and working
specs are in the `docs/` directory. A live Automation Cloud session is required
only for final platform execution.

## Coding-Agent Evidence (Bonus)

Claude Code and Codex CLI were used throughout development. Evidence:

- `docs/agent_evidence_appendix.md` — session transcripts, worklog entries,
  packet receipts, and ledger closeouts with agent attribution.
- `docs/AGENT_WORKLOG.md` (in the private workspace, sanitized summary here) —
  rolling worklog of every agent action since 2026-06-05.

## Privacy

No API keys, credentials, cloud session tokens, private paths, or private
workspace history are written to this repo. Credential steps are
operator-gated and all examples use placeholder values.

## Shipping Checklist

To complete submission after this bundle is public:

- [ ] Create public GitHub repo and push this directory.
- [ ] Log in to UiPath Automation Cloud (Google SSO) and verify Maestro access.
- [ ] Import case definition and run one intake demo in Automation Cloud.
- [ ] Record a 3–5 minute demo video showing intake, a credential-blocked case,
      human approval, and the readiness packet output.
- [ ] Fill in live repo URL, video URL, and deck URL in Devpost fields.
- [ ] Submit on Devpost before 2026-06-29 23:45 EDT.

Full founder-specific steps with copy-paste commands are in
[docs/FOUNDER_SHIP_STEPS.md](docs/FOUNDER_SHIP_STEPS.md).

## Status

- Maestro Case stage design: complete
- Architecture diagram (Mermaid): complete
- Devpost answer draft: complete
- Coding-agent evidence appendix: complete
- MIT license: present
- UiPath Automation Cloud live session: pending (requires Google SSO login)
- Live case demo recording: pending
- Public repo URL: not yet created
- Devpost submission: not yet submitted
