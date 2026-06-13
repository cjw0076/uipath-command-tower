# Competition Command Tower

A working **UiPath Maestro Case** engine that runs a portfolio of parallel
hackathon competitions as exception-heavy cases — automating rules intake,
deadline normalisation across PDT/EDT/KST, multi-agent work routing, retry and
re-entry recovery, blocking human-in-the-loop approval gates, and an append-only
audit trail.

It is a **real, offline-runnable system**, not a slide deck: a stdlib-Python
state machine, a 30+ test pytest suite, a portfolio benchmark, and an interactive
FastAPI dashboard where an operator clears the human-task gates from the browser
and watches the cases advance. The same code targets a live UiPath Automation
Cloud tenant by setting two environment variables.

```
Track   : UiPath AgentHack 2026 — UiPath Maestro Case
Platform: UiPath Automation Cloud (Maestro)
License : MIT
Runs    : offline, no credentials  (python -m command_tower)
```

---

## What it does

Running six or more competitions at once is an **exception-management** problem,
not a checklist:

- Rules change *after* you read them (a deadline moves, an asset is added).
- Deadlines mix PDT, EDT and KST and quietly conflict.
- A single missing credential blocks one competition without affecting the rest.
- Work must fan out to different coding agents (Claude Code, Codex, Gemini CLI)
  and a UiPath Robot, then re-consolidate into one auditable readiness report.
- Credential use and final submission must **never** be taken by automation
  without an explicit human approval.

A generic project tracker cannot express that exception density. UiPath **Maestro
Case** can — it is the construct built for dynamic, long-running work that mixes
robots, AI agents, and human decision points. Competition Command Tower models
each competition as a Maestro **case instance** advancing through seven stages,
with exception branches, retry policies, re-entry, and two mandatory human gates.

### The seven stages

| # | Stage | Primary actor | Human gate |
|---|---|---|---|
| 1 | Contest Intake | UiPath Robot (rules/deadline parser) | |
| 2 | Rule Verification | Maestro AI Agent | (ack on stale critical rule) |
| 3 | **Credential & Access Gate** | **Operator** | ✋ blocking |
| 4 | Work Routing | Maestro AI Agent | |
| 5 | Builder Execution | Claude Code / Codex / Gemini lanes | |
| 6 | Readiness Audit | AI Agent + Robot (checklist) | |
| 7 | **Submission Gate** | **Operator** | ✋ blocking |

Full stage specs, data contracts, and exception paths:
[docs/maestro_case_design.md](docs/maestro_case_design.md).

### The four exception classes (plus a bonus) — handled, not just logged

| Exception | Detection | Resolution path |
|---|---|---|
| **Blocked credential** (`CREDENTIAL_BLOCKED`) | a required credential is missing, or a builder task hits a live-platform boundary | re-enter Stage 3, post a human task; operator approves / skips / cancels |
| **Stale rule** (`STALE_RULE_CHANGED`) | live rules page drifted after intake | non-critical → re-verify & continue; critical field → post a blocking operator acknowledgment |
| **Timezone conflict** (`DEADLINE_CONFLICT`) | deadline text carries both PDT and EDT | resolve to the earlier (EDT) cutoff, flag `DEADLINE_CONSERVATIVE`, continue (audited) |
| **Platform upload failure** (`PLATFORM_UPLOAD_FAILED`) | submission upload fails first attempt | retry with exponential backoff up to max-attempts; escalate to operator if exhausted |
| *bonus* **Artifact secret** (`ARTIFACT_SECRET_FOUND`) | a builder artifact embeds a credential reference | hard-block / quarantine, scrub, re-enter Stage 5 so it regenerates public-safe |

Every transition, retry, re-entry, exception, and human decision emits exactly
one append-only `AuditEvent` carrying its case, stage, actor, and timestamp.

---

## Try it

### CLI demo (offline, no credentials)

```bash
python -m command_tower               # or: ./run_demo.sh
```

Seeds the six-competition portfolio, advances every case to its first human
gate, then plays an auto-operator that clears every gate — surfacing each
exception class, the retry/backoff, the re-entry, and the audit trail. A full
captured run is in [eval/SAMPLE_RUN.txt](eval/SAMPLE_RUN.txt).

```bash
python -m command_tower --manual      # stop at the gates; decide via the webapp
python -m command_tower --json out/portfolio_snapshot.json
```

### Interactive dashboard

```bash
pip install -r webapp/requirements.txt
./run_dashboard.sh                    # http://127.0.0.1:8120
```

Six case cards advance through the seven stages live. A **Pending Human Tasks**
panel lets you Approve / Skip / Submit a credential or submission gate — the
POST advances the case in-engine and the board updates. An exception feed, a
per-case readiness score, and the append-only audit timeline complete the view.
Click any case for its stage output, incidents, and full audit trail.

### Tests + benchmark

```bash
python -m pytest -q                   # 58 tests, all green
python eval/run_eval.py               # portfolio benchmark + CI gate
```

The eval drives all six cases through the engine and asserts: every case reaches
a terminal state, every raised incident is resolved, ≥4 distinct exception
classes were exercised, and every submitted case passed its readiness audit.

---

## UiPath components used

| Component | Role in Command Tower |
|---|---|
| **UiPath Maestro Case** | the case lifecycle + stage router (`case_engine.py`) |
| **Maestro AI Agent** | rule verification, work routing, readiness audit (stages 2/4/6) |
| **Maestro Human Task / Action Center** | the credential gate (3) and submission gate (7) |
| **UiPath Robot / Studio Web** | contest intake scrape + readiness checklist runner (stages 1/6) |
| **UiPath Automation Cloud** | orchestration host, credential store, audit store |
| **UiPath Integrations** | GitHub (repo ops), deadline-alert email, Devpost upload |

The mapping from our objects to Maestro constructs is the `MaestroBackend`
interface in [`maestro_adapter.py`](src/command_tower/maestro_adapter.py):
`Case → Maestro process instance`, `Stage → process variable update`,
`HumanTask → Action Center task`, `AuditEvent → process comment`.

## Automation Cloud deployment path (credentials are the only gate)

The system ships with **two backends behind one interface** (the same pattern as
our sibling projects' pluggable backends):

- **`LocalMaestroBackend`** — in-process, offline. Runs the demo, the tests, and
  the dashboard with zero credentials.
- **`UiPathMaestroBackend`** — the documented production path. It authenticates
  to UiPath Identity Server (OAuth 2.0 `client_credentials` at
  `https://cloud.uipath.com/identity_/connect/token`), then maps each Maestro
  construct onto the real Automation Cloud / Orchestrator REST endpoints
  (Maestro `process-instances`, Action Center `CreateAppTask` / `CompleteTask`,
  process comments), sending the `X-UIPATH-OrganizationUnitId` folder header on
  every call. It is real, correct REST code — unit-tested against a mocked HTTP
  layer in [`tests/test_maestro_adapter.py`](tests/test_maestro_adapter.py) — and
  drops onto a live tenant with no other change.

The one-line switch is automatic:

```bash
export UIPATH_CLIENT_ID=...        # External Application (confidential) client id
export UIPATH_CLIENT_SECRET=...    # never stored in this repo
export UIPATH_ORG=your-org
export UIPATH_TENANT=DefaultTenant
export UIPATH_FOLDER_ID=...        # Orchestrator folder (organization unit) id
./run_dashboard.sh                 # now targets your Automation Cloud tenant
```

`make_backend()` returns the cloud backend when those vars are present and the
local backend otherwise. No secret, token, or private path is ever written to
this repo.

## Coded-vs-low-code agent disclosure

Per Devpost rules, this project uses two agent types:

- **UiPath Maestro AI Agent (low-code / orchestration-layer)** — the rule
  verification, work routing, and readiness-audit decisions run as Maestro AI
  Agent steps inside Automation Cloud. The stage handlers in
  [`stages.py`](src/command_tower/stages.py) are the agent logic those steps run.
- **External coding agents (coded)** — Claude Code / Codex / Gemini CLI are the
  *builder lanes* the case routes work to in Stage 5
  ([`agents.py`](src/command_tower/agents.py)); the offline demo runs them through
  a deterministic simulated executor so no external API is needed.

## Built with coding agents (bonus criterion)

This entire codebase was built with **Claude Code** as the coding agent — the
engine, the seven stage handlers, the exception policies, the dual Maestro
backend, the FastAPI dashboard, the 58-test suite, and the eval harness. Agent
attribution for every builder lane is carried through the `ResultPacket.agent_id`
field and surfaced in the readiness audit's "Coding-agent evidence" item; the
session/worklog evidence is in
[docs/agent_evidence_appendix.md](docs/agent_evidence_appendix.md).

---

## Architecture

```text
Official contest pages / operator packets
  -> [1] Contest Intake     Robot: parse rules, normalise deadline (PDT/EDT/KST), freeze target
  -> [2] Rule Verification  AI Agent: staleness + timezone conflict resolution, priority
  -> [3] Credential Gate    HUMAN: approve / defer / skip-credential / cancel   ✋ BLOCKS
  -> [4] Work Routing       AI Agent: classify + route tasks to agent lanes
  -> [5] Builder Execution  Claude/Codex/Gemini/Robot lanes -> artifacts + result packets
  -> [6] Readiness Audit    AI Agent + Robot: Devpost checklist, score, secret scan
  -> [7] Submission Gate    HUMAN: submit / defer / skip-platform               ✋ BLOCKS
  -> platform submission + append-only audit trail

  exceptions can RE-ENTER an earlier stage (5->3 on credential boundary,
  6->5 on readiness fail), RETRY with backoff (upload), or ESCALATE to a human.
```

Detailed Mermaid flowchart with agent/tool labels and exception paths:
[docs/architecture_diagram.md](docs/architecture_diagram.md).

## Layout

```
src/command_tower/
  models.py          typed domain model (Case, Stage, HumanTask, Incident, AuditEvent, ReadinessReport)
  case_engine.py     the Maestro Case state machine: advance/retry/re-enter/escalate/human-gate
  stages.py          the seven stage handlers (real intake/verify/route/build/audit work)
  agents.py          multi-agent routing table + deterministic offline executor
  exceptions.py      the four exception classes: detection + handling policies
  audit.py           append-only audit trail
  maestro_adapter.py LocalMaestroBackend + UiPathMaestroBackend (real cloud REST)
  orchestrator.py    six-competition portfolio loader + consolidated views
  __main__.py        CLI demo (full lifecycle + audit + SAMPLE_RUN)
webapp/              FastAPI server.py + single-page dashboard (index.html)
tests/               pytest suite (58 tests)
eval/                run_eval.py portfolio benchmark + SAMPLE_RUN.txt
docs/                Maestro case design, architecture diagram, agent evidence, Devpost draft
```

## Privacy

No API keys, credentials, cloud session tokens, private paths, or private
workspace history are written to this repo. Credential and submission steps are
operator-gated, and all examples use placeholder values.

## Shipping checklist

- [ ] Create the public GitHub repo and push this directory.
- [ ] Log in to UiPath Automation Cloud and verify Maestro access.
- [ ] Set the `UIPATH_*` external-application credentials; run one live intake.
- [ ] Record a 3–5 minute demo (intake → credential-blocked case → human approval
      → readiness packet → submission gate).
- [ ] Fill in the live repo URL, video URL, and deck URL on Devpost.
- [ ] Submit on Devpost before 2026-06-29 23:45 EDT.
