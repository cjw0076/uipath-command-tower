# Maestro Case Design: Competition Command Tower

Updated: 2026-06-08 KST

## Case Overview

- **Case name:** Competition Command Tower
- **UiPath track:** UiPath Maestro Case
- **Purpose:** Manage a portfolio of parallel hackathon competitions through
  intake, rule verification, credential approval, multi-agent work routing,
  builder execution, readiness audit, and human-approved submission.
- **Primary exception class:** operator-gated credentials, stale rules,
  timezone deadline conflicts, and multi-stage blocker accumulation.

## Input and Output Contracts

### Case Input (per competition instance)

| Field | Type | Source |
|---|---|---|
| `competition_url` | string (URL) | Operator or upstream monitor |
| `rules_url` | string (URL) | Scraped from official page |
| `deadline_raw` | string | Official page text (may contain PDT/EDT/KST ambiguity) |
| `track_name` | string | Operator selection or scrape inference |
| `credential_refs` | list[string] | Required env var or secret names |
| `public_repo_required` | boolean | From rules |
| `coding_agent_bonus` | boolean | From rules |

### Case Output (per competition instance)

| Field | Type | Consumer |
|---|---|---|
| `readiness_packet` | Markdown doc | Operator review, demo recording |
| `submission_checklist` | JSON | Stage 7 human task form |
| `blocker_list` | list[{stage, reason, gate_action}] | Action Center inbox |
| `audit_trail` | append-only ledger | AIOS ledger + submission evidence |
| `next_actions` | list[string] | Operator |

---

## Stage Definitions

### Stage 1: Contest Intake

**Actor:** UiPath Robot (Studio Web automation)

**Purpose:** Ingest a new competition and produce a normalized case record.

**Inputs:** `competition_url`, operator-supplied brief (optional)

**Actions:**
1. Fetch the official rules page and extract: deadline, eligible geographies,
   track names, required submission assets, license requirements, team size
   limits, and coding-agent bonus clause.
2. Normalize the deadline to UTC and compute an internal freeze target
   (48 hours before official deadline).
3. Detect timezone ambiguity (PDT vs EDT) and flag when both appear in source.
4. Create a structured case record with source URL, extraction timestamp, and
   a staleness window (default: re-verify every 7 days).
5. Write the case record to the Automation Cloud data store.

**Outputs:** Normalized case record, deadline triple (raw / UTC / KST), staleness policy.

**Exception paths:**
- Rules page returns 4xx/5xx → retry once, then raise `INTAKE_FETCH_FAILED`;
  case holds at stage 1, alert sent to operator.
- Timezone ambiguity detected → raise `DEADLINE_CONFLICT`; flag in case record;
  continue to stage 2 with conflict marked.
- Required asset list is empty → raise `RULES_INCOMPLETE`; case holds at
  stage 1; operator reviews manually.

---

### Stage 2: Rule Verification

**Actor:** Maestro AI Agent (Claude Code / Codex, invoked via Automation Cloud)

**Purpose:** Cross-check the normalized case record against the live rules page,
identify stale assumptions, and resolve deadline conflicts.

**Inputs:** Stage 1 case record, live rules page content.

**Actions:**
1. Compare extracted fields against the live page.
2. Identify any field that has changed since the last scrape (staleness check).
3. Resolve timezone conflict: check if official FAQ clarifies PDT vs EDT; if
   unresolved, default to the earlier (EDT) interpretation and mark
   `DEADLINE_CONSERVATIVE`.
4. Verify the presence and format of the coding-agent bonus clause.
5. Emit a verification receipt with confidence scores per field.

**Outputs:** Verification receipt, updated case record with stale flags,
resolved deadline (or `DEADLINE_CONFLICT` maintained if unresolvable).

**Decision point — HOLD vs CONTINUE:**
- If staleness delta is greater than 24 hours on any critical field → hold for
  operator acknowledgment before advancing.
- If deadline is within 72 hours of current time → escalate to `URGENT` case
  priority.
- Otherwise → advance to stage 3.

**Exception paths:**
- AI Agent cannot reach the rules page → log error, mark fields as
  `UNVERIFIABLE`, continue with prior data and `STALE_UNVERIFIED` flag.
- Agent response is malformed or confidence below 0.5 on deadline field →
  route to `HUMAN_REVIEW_QUEUE`.

---

### Stage 3: Credential and Access Gate

**Actor:** Human-in-the-loop (Maestro Human Task)

**Purpose:** Obtain explicit operator approval before any action that requires
platform credentials, account access, or public artifact creation.

**Inputs:** Case record, list of required credentials (`credential_refs`),
current availability status of each credential.

**Actions:**
1. Maestro generates a human task form listing each required credential,
   its purpose, and its current status (available / missing / expired).
2. The form is posted to the operator's UiPath Action Center inbox.
3. Operator reviews and selects one of:
   - **APPROVE**: credentials are available; case may advance to stage 4.
   - **DEFER**: credentials are being obtained; case holds with a return date.
   - **SKIP_CREDENTIAL**: a specific credential is not obtainable; case
     advances with that integration disabled.
   - **CANCEL**: competition is dropped; case is closed with `ABANDONED` status.

**Gate timeout:** If no response is received within 48 hours, a reminder
alert is sent. After 96 hours of silence, the case is moved to `STALLED`
and removed from the active priority queue.

**Outputs:** Operator decision record, updated credential availability map,
gate receipt with timestamp and operator identity.

**Exception paths:**
- Missing Google SSO session for UiPath login → surface as `UIPATH_LOGIN_BLOCKED`;
  include Google SSO link and instructions in the human task form.
- Public repo creation requires manual GitHub step → include in human task form
  as a checklist item; do not create repo automatically.

---

### Stage 4: Work Routing

**Actor:** Maestro AI Agent

**Purpose:** Decompose the verified case record into a set of bounded tasks and
dispatch each to the appropriate coding agent or automation lane.

**Inputs:** Verified case record, available agent lanes (Codex, Claude Code,
Gemini CLI, UiPath Robot).

**Routing table:**

| Task type | Primary agent | Backup |
|---|---|---|
| Code implementation, test scripts | Codex CLI | Claude Code |
| Architecture critique, public wording | Claude Code | Codex review |
| Alternative idea generation | Gemini CLI | Claude Code |
| Repo and release operations | GitHub automation (Robot) | Local git |
| Rule memory and staleness tracking | Claude Code | Codex |
| Demo script and narration | Claude Code | — |
| Slide deck structure | AI Agent doc generator | Manual |

**Actions:**
1. Create a task list from the case submission requirements.
2. For each task, select the primary agent based on the routing table.
3. Emit a dispatch packet per task: goal, agent assignment, inputs, expected
   output format, stop conditions, deadline.
4. Record routing decisions in the audit trail.

**Outputs:** Dispatch packet set, agent assignment map, routing receipt.

**Exception paths:**
- A required agent lane is unavailable (no session/credentials) → assign to
  fallback agent or hold that task pending operator action; do not silently skip.
- Routing agent produces zero tasks → raise `ROUTING_EMPTY`; hold at stage 4
  and request operator review.

---

### Stage 5: Builder Execution

**Actor:** Dispatched coding agents (Codex / Claude Code / Gemini CLI)

**Purpose:** Execute the assigned tasks and produce public-safe, auditable
artifacts.

**Inputs:** Dispatch packets from stage 4.

**Actions (per task):**
1. Receive dispatch packet.
2. Execute: write code, generate documentation, produce design artifacts, or
   run analysis.
3. Emit a result packet: status, output artifact paths, agent identity (for
   bonus evidence), execution timestamp, and any blockers encountered.
4. Append a worklog entry to the competition's `docs/AGENT_WORKLOG.md`.
5. Write a receipt to the control tower receipts directory (sanitized).

**Output artifact requirements:**
- No secrets, credentials, API keys, or private path references.
- All file paths relative to the public repo root.
- Each artifact references its originating dispatch packet ID.

**Outputs:** Artifact set, result packets, updated worklog entries.

**Exception paths:**
- Agent hits a credential boundary (e.g., platform API call requires live
  session) → emit a `CREDENTIAL_BLOCKED` result packet; return to stage 3 for
  gate re-evaluation.
- Agent produces an artifact that fails the public safety check → quarantine
  artifact, do not advance it to the readiness stage, alert operator.
- Stop condition triggered (see dispatch packet) → agent halts and emits a
  partial result packet; case holds.

---

### Stage 6: Readiness Audit

**Actor:** Maestro AI Agent + UiPath Robot (checklist runner)

**Purpose:** Verify that all required submission assets are present, correct,
and public-safe before presenting to the operator for final approval.

**Inputs:** All artifacts from stage 5, submission requirements from stage 1.

**Checklist items (Devpost standard):**

| Item | Check |
|---|---|
| Public GitHub repo | URL exists and is publicly accessible |
| MIT or Apache 2.0 license file | Present in repo root |
| README | Contains UiPath components, setup, prerequisites, agent disclosure |
| Demo video | URL exists, duration ≤ 5 minutes |
| Devpost project page | Fields filled, description complete |
| Presentation deck | URL provided |
| Live Automation Cloud instance | Running or documented as blocker |
| Coding-agent bonus evidence | Appendix present and references real sessions |
| Secret safety scan | No keys, tokens, or private paths in public artifacts |

**Actions:**
1. Run the checklist programmatically (Robot fetches URLs, checks file presence).
2. AI Agent reviews README and Devpost draft for completeness and clarity.
3. Generate a readiness packet: pass/fail per item, blockers, recommended fixes.
4. If all critical items pass → advance to stage 7.
5. If critical items fail → return to stage 5 (specific tasks only) or to
   stage 3 (credential blocker).

**Outputs:** Readiness packet (Markdown), pass/fail checklist JSON, blockers list.

**Exception paths:**
- Video URL is missing → mark as `DEMO_MISSING`; downgrade case priority but
  allow stage 7 to proceed if all other items pass (human decides).
- Secret scan finds a potential secret → hard block; artifact quarantined; must
  be fixed before stage 7.
- Automation Cloud instance is not live → mark as `PLATFORM_NOT_LIVE`; escalate
  to stage 7 with human decision required.

---

### Stage 7: Submission Gate

**Actor:** Human-in-the-loop (Maestro Human Task)

**Purpose:** Final human approval and submission execution. Automation stops
here until the operator explicitly approves.

**Inputs:** Readiness packet, checklist, blocker list, all artifact URLs.

**Actions:**
1. Maestro generates a submission task form with all required Devpost fields
   pre-filled from the readiness packet.
2. The form is posted to the operator's Action Center inbox.
3. Operator reviews, makes any last edits, and selects:
   - **SUBMIT**: trigger automated Devpost submission (if Devpost API is
     available) or display the final copy-paste package.
   - **DEFER**: submission is not ready; specify which items need fixing.
   - **SKIP_PLATFORM**: live platform demonstration is not achievable; submit
     as documentation-first entry.
4. On SUBMIT approval, the Robot executes: final repo push, Devpost form
   submission (or presents the package for manual submit).
5. Append submission receipt to the audit trail and ledger.

**Outputs:** Submission receipt, final audit trail entry, case status set to
`SUBMITTED` or `DEFERRED`.

**Exception paths:**
- Devpost API unavailable → switch to copy-paste package; human completes
  manually; Robot captures confirmation URL.
- Repo push fails (auth/SSH issue) → surface as `REPO_PUSH_FAILED`;
  operator action required.
- Post-submit confirmation not received within 10 minutes → alert operator
  to verify on Devpost dashboard.

---

## Data Contracts Between Stages

```
Stage 1 → Stage 2: case_record_v1.json
  {competition_url, rules_url, deadline_utc, deadline_kst, deadline_raw,
   deadline_conflict, track_name, required_assets[], credential_refs[],
   public_repo_required, coding_agent_bonus, source_ts, stale_after_hours}

Stage 2 → Stage 3: verified_case_record.json
  {+ verification_receipt{field, confidence, stale_delta},
     resolved_deadline, deadline_flag, priority}

Stage 3 → Stage 4: gated_case_record.json
  {+ operator_decision, approved_ts, operator_id, credential_map{name, status},
     disabled_integrations[]}

Stage 4 → Stage 5: dispatch_packet_set.json
  {packets[{packet_id, goal, agent, inputs, output_format,
            stop_conditions, deadline_utc}]}

Stage 5 → Stage 6: artifact_manifest.json
  {artifacts[{packet_id, path, type, agent_id, ts, public_safe}],
   result_packets[], worklog_entries[]}

Stage 6 → Stage 7: readiness_packet.json
  {checklist[{item, status, url, blocker}], blockers[],
   submission_fields{title, description, repo_url, video_url, deck_url},
   recommendation}

Stage 7: submission_receipt.json
  {case_id, submitted_ts, devpost_url, repo_url, video_url,
   operator_id, final_status}
```

---

## Exception Handling Summary

| Exception code | Stage detected | Resolution path |
|---|---|---|
| `INTAKE_FETCH_FAILED` | 1 | Retry once; hold if persistent; operator alert |
| `DEADLINE_CONFLICT` | 1, 2 | Mark conservative (earlier) deadline; continue with flag |
| `RULES_INCOMPLETE` | 1 | Hold at stage 1; operator manual review |
| `STALE_UNVERIFIED` | 2 | Continue with flag; operator acknowledgment required |
| `HUMAN_REVIEW_QUEUE` | 2 | Route to Action Center; hold |
| `UIPATH_LOGIN_BLOCKED` | 3 | Surface Google SSO instructions in human task; hold |
| `CREDENTIAL_BLOCKED` | 3, 5 | Return to stage 3; gate re-evaluation |
| `ROUTING_EMPTY` | 4 | Hold at stage 4; operator review |
| `ARTIFACT_SECRET_FOUND` | 6 | Hard block; quarantine; agent must fix |
| `DEMO_MISSING` | 6 | Downgrade priority; human decides in stage 7 |
| `PLATFORM_NOT_LIVE` | 6 | Flag in stage 7; human decides |
| `REPO_PUSH_FAILED` | 7 | Surface to operator; Robot retries with new credentials |

---

## Human-in-the-Loop Gates

Two mandatory HITL gates prevent automation from crossing irreversible
boundaries without operator consent:

**Gate 1 (Stage 3 — Credential & Access Gate)**
- Triggered: always, before any credential use or public artifact creation.
- Operator choices: APPROVE, DEFER, SKIP_CREDENTIAL, CANCEL.
- Cannot be bypassed by automation under any circumstance.

**Gate 2 (Stage 7 — Submission Gate)**
- Triggered: always, before any Devpost submission or final repo push.
- Operator choices: SUBMIT, DEFER, SKIP_PLATFORM.
- Cannot be bypassed by automation under any circumstance.

Both gates use UiPath Action Center with a structured task form. All gate
decisions are appended to the audit trail with operator identity and timestamp.

---

## Audit Trail and Ledger

Every stage transition, exception, and human decision appends an immutable
record to the case audit trail. The audit trail is:

- Append-only (no record is modified or deleted after writing).
- Stored in the Automation Cloud data store (private) and summarized in the
  sanitized public `docs/ledger.md` (no credentials or private paths).
- Referenced by the coding-agent bonus evidence appendix.

This design satisfies the AIOS append-only audit invariant and gives judges
concrete evidence of workflow execution history.
