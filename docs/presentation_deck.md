# Competition Command Tower — Presentation Deck

> UiPath AgentHack 2026 · Maestro Case track. Render to slides with Marp/Pandoc,
> or paste each `---` block into Google Slides. Speaker notes under each slide.
> Maps 1:1 to the judging criteria (Business Impact · Platform Usage · Technical
> Execution · Completeness · Creativity · Presentation · coding-agent bonus).

---

## Slide 1 — Title
# Competition Command Tower
### A UiPath Maestro Case that runs a portfolio of parallel hackathons as exception-heavy cases
**One operator. Six competitions. Five working systems shipped.**
`Track: Maestro Case · Platform: UiPath Automation Cloud · MIT`

> Notes: Open on the live dashboard, six cases mid-flight. "This is not a slide
> deck demo — it's a running Maestro Case engine. Let me show you."

---

## Slide 2 — The Problem (Business Impact)
Running 6+ competitions at once is an **exception-management** problem, not a checklist:
- Rules change *after* you read them (deadline moves, asset added)
- Deadlines collide across **PDT / EDT / KST**
- One missing credential blocks one competition — not the others
- Work must fan out to different agents, then reconsolidate into one auditable report
- Credential use + final submission must **never** be auto-taken without human approval

> Notes: A generic PM tool can't express this exception density. This is real
> operational pain — we lived it across six concurrent Devpost deadlines.

---

## Slide 3 — Why Maestro Case (Platform Usage)
**Maestro Case** is the only UiPath construct for dynamic, long-running work mixing
robots, AI agents, and human decision points where the path isn't known at design time.
- Each competition = a **case instance**
- 7 stages, exception branches, retry policies, re-entry, **2 mandatory human gates**

> Notes: We didn't bolt UiPath on — the problem *is* a case-management problem.

---

## Slide 4 — The Seven Stages
| # | Stage | Actor | Human gate |
|---|---|---|---|
| 1 | Contest Intake | UiPath Robot (rules/deadline parser) | |
| 2 | Rule Verification | Maestro AI Agent | ack on stale critical rule |
| 3 | **Credential & Access Gate** | **Operator** | ✋ blocking |
| 4 | Work Routing | Maestro AI Agent | |
| 5 | Builder Execution | AI coding agents (Claude/Codex/Gemini) | |
| 6 | Readiness Audit | AI Agent + Robot | |
| 7 | **Submission Gate** | **Operator** | ✋ blocking |

> Notes: Walk one case left-to-right on the live dashboard's stage bar.

---

## Slide 5 — Exceptions, handled not logged (Technical Execution)
Four exception classes with **detect + handle** policies:
- **Blocked credential** → hold case at gate, escalate to operator
- **Stale rule** (changed after intake) → re-enter Stage 2, supersede old fact
- **Timezone conflict** (PDT/EDT/KST) → normalise + flag the binding deadline
- **Platform upload failure** → retry w/ exponential backoff, then escalate

Every transition emits one **append-only AuditEvent** (case · stage · actor · time).

> Notes: Click the incident feed — show a real STALE_RULE_CHANGED resolving.

---

## Slide 6 — Live Demo (Completeness)
**It runs, offline, right now:**
- `python -m command_tower` → drives all 6 cases through 7 stages
- FastAPI dashboard → approve a gate in the browser, watch the case advance
- **58 passing tests** · portfolio benchmark · SAMPLE_RUN captured
- Demo video: youtu.be/g8fEB-X1hiI

> Notes: Approve the UiPath case's credential gate live; it advances to Submission.

---

## Slide 7 — Automation Cloud path (Platform Usage)
Same code, two backends — the **SplunkRestBackend pattern**:
- `LocalMaestroBackend` — offline, runs the demo & tests
- `UiPathMaestroBackend` — OAuth client-credentials → Maestro process-instances +
  Action Center CreateAppTask/CompleteTask REST. Set two env vars to go live.

> Notes: Credentials are the *only* gate between this demo and a live tenant.

---

## Slide 8 — Creativity & the coding-agent bonus
- **Creativity**: Maestro Case applied to a *meta-problem* — managing the submission
  of competition entries — not a synthetic toy scenario.
- **Bonus**: built with **Claude Code** (+ Codex, Gemini CLI). Evidence chain in
  `docs/agent_evidence_appendix.md`: goal loops → worklog → receipts → ledger.

> Notes: The system that manages competitions was itself built by coding agents.

---

## Slide 9 — Results
- **6** competitions modelled as cases · **7** stages · **2** human gates
- **5** exception classes raised & resolved in a full run · **136** audit events
- **58** passing tests · readiness scoring per case
- Reusable as a UiPath template for *any* team running parallel entries

> Notes: This is repeatable infrastructure, not a one-off.

---

## Slide 10 — Close
# From chat to control plane
**AI agents do the work. UiPath Maestro governs it. Humans approve what matters.**
`github.com/cjw0076/uipath-command-tower · MIT`

> Notes: End on the dashboard, all six cases at SUBMITTED.
