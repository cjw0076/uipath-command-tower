# Coding-Agent Evidence Appendix

Updated: 2026-06-08 KST

This appendix documents use of AI coding agents throughout the development of
Competition Command Tower. Per UiPath AgentHack rules, verified coding-agent
contribution earns up to +2 bonus points when evidence is integrated and
documented.

---

## Agents Used

| Agent | Role | Evidence type |
|---|---|---|
| Claude Code (claude-sonnet-4-6) | Architecture design, documentation, stage specs, public-safety review | Session worklog entries, receipts, this appendix |
| Codex CLI | Code and automation scaffolding, dispatch packets, result packets | Worklog entries, dispatch packet receipts |
| Gemini CLI | Alternative idea generation, critique of routing decisions | Worklog entries (referenced in control tower receipts) |

---

## Session Evidence

### 2026-06-05: Project Initialization

- Agent: Claude Code
- Action: Created competition workspace structure, drafted initial competition
  brief, issued UIA-001 command packet.
- Artifacts produced:
  - `docs/packets/UIA-001-command-packet.md`
  - `docs/ledger.md` (initial entry)
  - `README.md` (initial version)
- Worklog reference: `docs/AGENT_WORKLOG.md` entry 2026-06-05
- Receipt: `control_tower/receipts/20260606T074712+0900_uipath-maestro-stage-map.md`

### 2026-06-06: Stage Map and README Outline

- Agent: Claude Code (autonomous tick loop)
- Action: Produced the Maestro Case stage map and README outline under a
  docs-first, credential-blocked constraint.
- Artifacts produced:
  - `docs/maestro_case_stage_map.md`
  - `docs/maestro_readme_outline.md`
- Worklog reference: `docs/AGENT_WORKLOG.md` entries 07:47–08:01 KST
- Receipts:
  - `control_tower/receipts/20260606T074712+0900_uipath-maestro-stage-map.md`
  - `control_tower/receipts/20260606T074803+0900_uipath-maestro-stage-map.md`
  - `control_tower/receipts/20260606T080132+0900_uipath-maestro-readme-outline.md`
- Loop packets:
  - `control_tower/goal_loops/20260606T073743+0900_uipath_agenthack_2026`
  - `control_tower/goal_loops/20260606T074059+0900_uipath_agenthack_2026`

### 2026-06-06: Blocker Gate Management

- Agent: Claude Code (autonomous tick, multiple passes)
- Action: Re-evaluated credential gates across all six active competitions.
  Recorded each blocker state as a structured receipt. Maintained case in
  a well-defined `blocked` state rather than silently failing.
- Artifacts produced:
  - `control_tower/autonomous_runs/20260606T0*` (multiple run directories)
  - `control_tower/receipts/20260606T20*` (multiple gate-blocker receipts)
  - `control_tower/FAST_RESUME_PLAN.md`
- Worklog reference: `docs/AGENT_WORKLOG.md` entries 20:00–20:46 KST
- Key receipts:
  - `control_tower/receipts/20260606T200025+0900_uipath-session-credentials-ready.md`
  - `control_tower/receipts/20260606T204224+0900_gate-blocker-204204.md`
  - `control_tower/receipts/20260606T204230+0900_uipath-session-blocker-204224-03.md`

### 2026-06-08: Full Submission Bundle

- Agent: Claude Code (claude-sonnet-4-6)
- Action: Generated the complete public-repo staging bundle for Devpost
  submission, including this file. All artifacts produced under the
  docs-first constraint (no live UiPath session required for design phase).
- Artifacts produced:
  - `public_repo_staging/uipath-command-tower/README.md`
  - `public_repo_staging/uipath-command-tower/docs/maestro_case_design.md`
  - `public_repo_staging/uipath-command-tower/docs/architecture_diagram.md`
  - `public_repo_staging/uipath-command-tower/docs/agent_evidence_appendix.md`
  - `public_repo_staging/uipath-command-tower/docs/devpost_submission.md`
  - `public_repo_staging/uipath-command-tower/LICENSE`
  - `docs/AGENT_WORKLOG.md` (updated)
  - `docs/ledger.md` (updated)

---

## Autonomous Loop Architecture

All agent sessions run inside the **AIOS control-plane loop**:

```text
autonomous_tick.sh --record
  -> goal_loop packet created (JSON: goal, agent, stop conditions, deadline)
  -> agent executes
  -> result packet emitted (status, artifacts, blockers)
  -> receipt appended to control_tower/receipts/
  -> worklog entry appended to docs/AGENT_WORKLOG.md
  -> ledger updated
```

This loop structure means every agent action is:
1. Preceded by a dispatch packet (intent declared before execution).
2. Followed by a result packet (outcome recorded after execution).
3. Cross-referenced by a timestamp-named receipt in the control tower.
4. Summarized in the competition's ledger.

Judges can verify the chain: `goal_loops/` → `AGENT_WORKLOG.md` → `receipts/`
→ `ledger.md`. The artifacts at each step are named to make the chain
unambiguous.

---

## Control Tower Evidence Files (Public-Safe Summary)

The private workspace contains the full control tower with `autonomous_runs/`,
`goal_loops/`, and `receipts/` directories. The following sanitized references
are safe to include in public artifacts:

| Path pattern | Content |
|---|---|
| `control_tower/receipts/20260606T074712+0900_uipath-maestro-stage-map.md` | Stage map first draft receipt |
| `control_tower/receipts/20260606T080132+0900_uipath-maestro-readme-outline.md` | README outline receipt |
| `control_tower/receipts/20260606T200025+0900_uipath-session-credentials-ready.md` | Credential arrival gate |
| `control_tower/receipts/20260606T204224+0900_gate-blocker-204204.md` | Gate blocker state receipt |
| `control_tower/FAST_RESUME_PLAN.md` | Operator-facing resume guide post-blocker |
| `docs/AGENT_WORKLOG.md` | Rolling worklog (all agent actions since 2026-06-05) |
| `docs/ledger.md` | Append-only ledger of significant decisions |

None of these files contain API keys, session tokens, private paths beyond the
competition workspace, or personal identifiers beyond a public GitHub username.

---

## Reproducibility Note

The AIOS loop is reproducible by any operator with access to the workspace:

```bash
# From the competition workspace root:
./control_tower/tools/autonomous_tick.sh --record

# This will:
# 1. Check submission gates for all active competitions.
# 2. Create a new run directory under autonomous_runs/.
# 3. Emit goal loop packets for each competition.
# 4. Append gate status to AGENT_WORKLOG.md.
# 5. Write a receipt to control_tower/receipts/.
```

For the UiPath competition specifically, replacing the `UIPATH_CLIENT_ID` and
`UIPATH_CLIENT_SECRET` gate check with a live Automation Cloud session proof
would advance the case from `blocked` to `active` and unlock the builder stage.

---

## Coding-Agent Bonus Criteria Checklist

| Criterion | Status | Evidence |
|---|---|---|
| Named agent(s) used | Done | Claude Code (claude-sonnet-4-6), Codex CLI, Gemini CLI |
| Agent contribution is visible in artifacts | Done | Worklog entries, receipts, this appendix |
| Evidence is integrated (not just mentioned) | Done | Receipt chain: goal packet → worklog → receipt → ledger |
| Contribution is reproducible | Done | `autonomous_tick.sh` loop is rerunnable |
| No private data in public evidence | Done | All paths sanitized; no keys or tokens |
