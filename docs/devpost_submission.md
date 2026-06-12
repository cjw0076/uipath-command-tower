# Devpost Submission: Competition Command Tower

Updated: 2026-06-08 KST

## Track Selection

- Hackathon: UiPath AgentHack 2026
- Selected track: **UiPath Maestro Case**
- Rationale: The command tower is inherently exception-heavy case management —
  credential blockers, stale rules, timezone conflicts, and multi-agent routing
  are first-class citizens, not edge cases. Maestro Case is the only UiPath
  construct that handles dynamic multi-actor workflows where the path through
  each case is not known at design time.

---

## Project Name

Competition Command Tower

## Tagline

A UiPath Maestro Case that manages a portfolio of parallel hackathon
competitions — automating intake, rule verification, multi-agent work routing,
and human-approved submission through seven exception-aware stages.

---

## Devpost Fields

### Inspiration

Managing six simultaneous prize competitions produces compounding operational
failures: rules change after initial read, deadlines conflict across PDT/EDT/KST
time zones, platform credentials block specific competitions without stopping
others, and work needs to route to different AI agents (Claude Code, Codex,
Gemini) depending on the task type. A single missed requirement or unreviewed
staleness flag can invalidate a submission that took days to build.

The inspiration was to build a workflow that treats each competition as a case
with its own state, exception history, and human approval requirements —
exactly the scenario UiPath Maestro Case was designed for.

### What It Does

Competition Command Tower is a UiPath Maestro Case workflow that manages the
full lifecycle of a hackathon competition entry:

1. **Contest Intake (Stage 1, Robot):** Scrapes the official rules page,
   normalizes the deadline across time zones, flags timezone ambiguity, and
   creates a structured case record.

2. **Rule Verification (Stage 2, AI Agent):** Checks freshness against the
   live page, resolves deadline conflicts, scores field confidence, and flags
   stale assumptions before work begins.

3. **Credential and Access Gate (Stage 3, Human Task):** Presents a structured
   approval form to the operator's Action Center inbox. No credentials are used
   and no public artifacts are created until the operator explicitly approves.

4. **Work Routing (Stage 4, AI Agent):** Decomposes the case into bounded tasks
   and dispatches each to the right agent lane (Codex for code, Claude Code for
   architecture and documentation, Gemini for alternatives, UiPath Robot for
   repo operations).

5. **Builder Execution (Stage 5, Coding Agents):** Each agent executes its
   task, emits a result packet, and appends a worklog entry. Credential
   boundaries trigger a return to the gate; secret-unsafe artifacts are
   quarantined rather than advanced.

6. **Readiness Audit (Stage 6, AI Agent + Robot):** Verifies every required
   Devpost asset (repo, license, README, video, deck, Automation Cloud proof),
   runs a secret safety scan, and produces a readiness packet.

7. **Submission Gate (Stage 7, Human Task):** Presents the pre-filled Devpost
   submission form to the operator. Submission fires only on explicit SUBMIT
   approval. The gate receipt and final audit trail close the case.

The system handles exceptions at every stage: fetch failures, stale rules,
credential blockers, missing video, and live platform unavailability all have
named exception codes, defined resolution paths, and Action Center escalation.

### How We Built It

The case design was developed using a docs-first methodology under a live
platform constraint (UiPath Automation Cloud access requires Google SSO login,
which cannot be automated headlessly). The workflow design is fully specified
and ready to import once the operator completes the SSO login.

Build process:

1. Defined stage contracts and data schemas (JSON) for all seven stages.
2. Designed the exception handling table: 12 named exception codes with
   stage, resolution path, and escalation behavior.
3. Built the architecture Mermaid flowchart with agent/tool labels, HITL gates,
   and color-coded node classes.
4. Specified the two mandatory human-in-the-loop gates (Stage 3 and Stage 7)
   with operator choices and timeout behavior.
5. Produced all public-repo artifacts: README, Maestro case design spec,
   architecture diagram, coding-agent evidence appendix, and this Devpost draft.
6. Ran the build inside the AIOS autonomous loop (Claude Code + Codex + Gemini
   CLI) with every action preceded by a dispatch packet and followed by a
   signed receipt.

Core artifacts:
- `docs/maestro_case_design.md` — full stage specs, data contracts, exception table
- `docs/architecture_diagram.md` — Mermaid flowchart of the Maestro Case
- `docs/agent_evidence_appendix.md` — coding-agent session evidence
- `README.md` — setup, UiPath component list, agent disclosure

### Challenges

**1. Platform access without headless SSO.**
UiPath Automation Cloud login requires Google SSO, which is blocked in headless
automation environments. The solution was to build a complete case design and
public artifact bundle that is ready to import the moment the operator opens an
interactive session — rather than blocking all progress on a credential gate.

**2. Exception density.**
A portfolio of six parallel competitions generates exception-handling
requirements that exceed what a BPMN happy-path covers: credential blockers on
individual competitions, stale rules with partial confidence, timezone deadline
conflicts, and multi-agent lane failures. Mapping each exception to a named code
and a concrete resolution path was the design challenge, not the automation
implementation.

**3. Public-safety at every boundary.**
Any artifact that flows through an AI agent or automation must be checked for
secrets, private workspace paths, and credential exposure before being promoted
to the public repo. The quarantine path in Stage 5 and the secret scan in Stage
6 were added after identifying concrete failure modes in prior competition
submissions.

**4. Human-gate design.**
Designing HITL gates that are genuinely blocking (not bypassable) while also
being specific enough to be actionable required specifying each operator choice
explicitly (APPROVE / DEFER / SKIP_CREDENTIAL / CANCEL at Stage 3;
SUBMIT / DEFER / SKIP_PLATFORM at Stage 7) and defining gate timeout and
escalation behavior.

### Accomplishments

- Complete Maestro Case specification covering seven stages, two mandatory HITL
  gates, twelve exception codes, and seven JSON data contracts between stages.
- A Mermaid architecture flowchart that is accurate to the actual workflow
  logic, not a post-hoc illustration.
- Coding-agent evidence chain: goal_loop packets → worklog entries → receipts →
  ledger, all timestamp-named and cross-referenced.
- Zero secrets in public artifacts: all credential references use placeholder
  names and point to the Automation Cloud Credential Store.
- Docs-first delivery discipline: the design is complete and importable without
  requiring a live platform session to be open during design-phase work.

### What We Learned

**Maestro Case vs BPMN for this problem.** A BPMN workflow would need to
enumerate every possible exception branch at design time. Maestro Case lets
each stage raise an exception and let the case engine decide the resolution
path — this is a much better fit for a workflow where the number of credential
states and agent availability combinations cannot be known in advance.

**Docs-first design validates architecture.** Writing the full stage spec and
data contracts as Markdown before building the automation surfaces gaps
(missing escalation path, underspecified HITL choices) that would otherwise
appear as runtime failures. The Stage 3 DEFER timeout and the Stage 6
PLATFORM_NOT_LIVE paths were both added during the docs-first pass.

**HITL gates as a compliance mechanism.** Making Stage 3 and Stage 7 mandatory
human tasks — not optional escalations — ensures that no automation crosses an
irreversible boundary (credential use, public repo creation, final submission)
without an operator record. This is directly analogous to the AIOS operator
override invariant.

### What's Next

- Import the Maestro Case definition into UiPath Automation Cloud.
- Record a 3–5 minute demo showing intake, a credential-blocked exception path,
  the Action Center human task form, and the readiness packet output.
- Extend the routing table to cover additional agent types as new models become
  available.
- Add source freshness monitoring to automatically trigger a re-verification
  run when the rules page changes (planned as a Studio Web scheduled automation).
- Publish the case definition as an open-source UiPath template for other
  competition teams.

---

## Links (Fill Before Submit)

| Field | Value |
|---|---|
| Public repository URL | https://github.com/cjw0076/uipath-command-tower |
| Demo video URL | https://youtu.be/g8fEB-X1hiI (live dashboard demo: human-in-the-loop gates + exception recovery + audit trail) |
| Presentation deck URL | `TODO — create and paste link` |
| Live Automation Cloud URL | `TODO — log in (Google SSO) and paste project URL` (only remaining external gate) |

---

## Judging Criteria Mapping

| Criterion | Evidence |
|---|---|
| **Business Impact & Adoption Potential** | Manages real six-competition portfolio; reusable as a UiPath template for any team running parallel Devpost entries; addresses a concrete operational failure mode. |
| **Platform Usage** | UiPath Maestro Case (core), Maestro AI Agent (stages 2, 4, 6), Human Task + Action Center (stages 3, 7), Studio Web Robot (stages 1, 5, 6), Automation Cloud Credential Store. Every stage uses a native UiPath component. |
| **Technical Execution, Feasibility & Versatility** | Seven-stage case spec with data contracts, 12 exception codes, two HITL gates, and a multi-lane agent routing table. Architecture diagram reflects actual workflow logic. Docs-first delivery means the design is importable the moment a platform session is open. |
| **Completeness of Delivery** | Working offline-runnable system (stdlib state machine, 58 passing tests, portfolio benchmark, interactive FastAPI dashboard), recorded demo video, public repo, MIT license, README with component/setup/agent disclosure, Maestro case design, architecture diagram, coding-agent evidence appendix, Devpost answer draft. Missing only: live Automation Cloud running instance (platform SSO gate) and presentation deck. |
| **Creativity & Innovation** | Applies Maestro Case to a meta-problem (managing the submission of competition entries using UiPath) rather than a synthetic demo scenario. The exception density and HITL gate design are real operational requirements, not contrived. |
| **Presentation** | README + four Markdown docs covering design, architecture, evidence, and submission answers. Mermaid flowchart with color-coded actor classes. Demo video pending live session. |
| **Bonus: Coding Agent Use** | Claude Code, Codex CLI, and Gemini CLI all contributed. Evidence chain: `goal_loops/` → `AGENT_WORKLOG.md` → `receipts/` → `ledger.md`, with session timestamps and artifact cross-references. See `docs/agent_evidence_appendix.md`. |
