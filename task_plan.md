# Task Plan - Computex Demo Beats Refresh

## Goal

Replace the current hard-coded 4-beat demo script with the new Computex story:
desktop cold open, desktop whiteboard-to-MVP/productivity, mobile private
health menu ordering, mobile executive-assistant update, and optional desktop
"back home" review. The implementation should remove old Beat 2 fashion and
Beat 4 handwritten-umbrella artifacts, preserve the proven WHOOP/privacy and
handoff work, and keep the code lean by extending existing prompt, tool, test,
and workspace surfaces.

## Pattern Audit

### Top-Level Directories

| Path | Purpose | Demo-beat relevance |
|------|---------|---------------------|
| `clients/` | External-service/model clients such as ASR, LLM, TTS, VLM, face, WHOOP, and Claw ACP. | No new client is needed for demo beats. Existing `ask_claw`, WHOOP, VLM, ASR, and TTS clients remain unchanged. |
| `static/` | Browser UI for voice/video calls, handoff, tool checkboxes, markdown/html editors. | No new UI surface is required for the first pass; existing tool panels and handoff UX are enough. |
| `demo_files/` | Local demo context files read by the app or tests. | Add one flat Computex/private-memory fixture here if needed; mirror `health-dummy-data.yaml`, not a new directory. |
| `test_assets/` | Ignored image/fixture assets for prompt tests. | Keep menu fixtures here; add any new sketch/menu images here only if prompt tests need visual assets. |
| `workspace/` | Generated demo output scratch area. | Clear/regenerate old README/realtime/todo artifacts; keep `.gitkeep`. New Beat 1 and Beat 3 outputs should land here. |
| `bench/` | Benchmarks and smoke/regression scripts. | Update `bench/test_demo_prompts.py`; do not create another prompt test unless the existing file becomes unwieldy. |
| `scripts/` | Operational scripts such as WHOOP refresh. | No demo-beat script needed. |
| `docs/` | Static architecture documentation assets. | No runtime dependency; update only if demo docs need a diagram later. |
| `audio_cache/`, `logs/`, venv dirs | Runtime/generated local artifacts. | Leave alone. |
| `.planning/` | Archived planning work. | Keep completed plans archived; active root planning files now describe this Computex demo refresh. |

### Existing Matching Code And Files

| Existing code/file | Current behavior | Decision |
|--------------------|------------------|----------|
| `prompts.py:_load_claw_persona()` | Injects local Claw persona files into prompt constants. | Use this for real personal/coding preferences when available; do not duplicate those preferences in code. |
| `prompts.py:_load_health_context()` | Reads `demo_files/health.yaml` or dummy fallback, converts health/WHOOP numbers to qualitative labels, appends to `VIDEO_CALL_PROMPT`. | Keep and reuse for new Beat 2. |
| `prompts.py:VIDEO_CALL_PROMPT` | Contains cold-open wording, fashion beat, README/realtime tool rules, old handwritten todo rules, exact Redis answer, and health-menu rules. | Replace the old beat-specific section with a concise Computex demo section. |
| `prompts.py:VISION_TEMPLATE_PROMPTS` | Contains unused/generic fashion, whiteboard, notes templates. | Remove old demo-specific fashion phrasing; keep generic templates only if harmless. |
| `prompts.py:MARKDOWN_ASSISTANT_PROMPT` | Hard-codes README/realtime design doc shape. | Generalize for MVP briefs and project scaffolding; keep README support as fallback. |
| `tools.py:ALL_TOOLS` | Has schemas for markdown, workspace update, reasoning, inline tools; frontend has an HTML checkbox but `html_assistant` is missing from tool schemas. | Add `html_assistant` schema only if Beat 1 needs a visible MVP artifact; this extends an existing server/frontend executor, not a new tool family. |
| `tools.py:is_agent_tool()` / `execute_tool()` | UI agent tool sentinel handling excludes `html_assistant`. | Include `html_assistant` if schema is enabled. |
| `server.py:execute_html_agent()` | Existing HTML streaming executor. | Reuse for optional MVP/prototype; no new module. |
| `server.py:infer_markdown_output_path()` | Routes README/realtime/personal/project tasks to workspace markdown paths. | Add Computex paths such as `mvp_brief.md`, `team_update.md`, and `executive_brief.md`. |
| `server.py:is_workspace_update_request()` | Old Beat 4 handwritten-note short-circuit. | Replace or broaden with new executive-update logic; avoid preserving the umbrella/Redis handwritten script. |
| `server.py:extract_workspace_todos()` / `apply_workspace_todo_updates()` | Hard-codes old handwritten items and writes `project_dashboard/tasks.md`, `realtime_design.md`, `personal_todos.md`. | Replace old item list and file sections with Computex team update/action-items/personal gift outputs. |
| `bench/test_demo_prompts.py` | Locked to old Beat 1 README/realtime, Beat 2 fashion, Beat 3 menu, Beat 4 handwritten todos. | Rewrite for new Computex beats and keep it as the main live prompt E2E. |
| `TESTING.md` | Records old prompt regression output and old deterministic Beat 4 tests. | Add a superseding Computex section; old historical entries can remain lower in the file if clearly superseded. |
| `README.md` | "Things to try" still lists old whiteboard/fashion examples. | Update to the new Computex demo flow. |
| `workspace/README.md`, `workspace/realtime_design.md`, `workspace/project_dashboard/tasks.md`, `workspace/personal_todos.md` | Untracked old generated artifacts from the previous demo. | Remove/regenerate during implementation; keep only `.gitkeep` before generating new demo outputs. |

### Proposed New Files Or Modules

| Proposed | Audit result |
|----------|--------------|
| `demo_files/computex-demo.yaml` | **Mirrors** `demo_files/health-dummy-data.yaml`: one flat YAML demo fixture, not a new package. Use only if we need deterministic org-chart, dinner, and relationship memory without hard-coding those details in the prompt. |
| New top-level package/module | **Rejected.** Existing homes cover the work. No `demo_beats/`, `executive_assistant.py`, or new top-level directory. |
| New agent tool name | **Avoid initially.** Prefer generalizing `workspace_update_assistant`. Add `html_assistant` schema only because the server/frontend executor already exists. |

## Architecture Decision

Keep the demo implementation prompt-and-tool driven, with only small
deterministic server helpers where stage reliability requires a real workspace
state change. Do not build a separate demo orchestration layer.

The new demo should be represented in three places:

1. `prompts.py` for concise behavior rules and tool selection.
2. Existing tool/server paths for real artifacts in `workspace/`.
3. `bench/test_demo_prompts.py` and focused unit checks for regression safety.

Use data files, not prose hard-codes, for reusable private context. Health data
continues through `_load_health_context()`. If the executive-assistant beat
needs stable org-chart or gift-memory context, add a single flat
`demo_files/computex-demo.yaml` plus `_load_computex_demo_context()` in
`prompts.py`, sibling to `_load_health_context()`.

## Target Demo Script

| Beat | Device | User moment | Expected behavior | Unlock |
|------|--------|-------------|-------------------|--------|
| Cold open | Desktop | "Hey, am I on camera?" | Short confirmation that camera/audio are on and Spark is ready. | Realtime voice/vision confidence. |
| Beat 1: Whiteboarding/Productivity | Desktop | Show agent dashboard sketch. "Turn this sketch into an MVP. I'm going to dinner; write me a brief for when I get back." | Acknowledge: "On it. I'll use your saved git hygiene and coding preferences." Generate a reviewable MVP brief/scaffold, and optionally an HTML prototype if the HTML agent is enabled and stable. | Vision-enabled local coding/productivity agent. |
| Beat 2: Restaurant Menu Ordering | Mobile | Show Chinese menu. "What should I order?" | Recommend visible/translated menu items using private health/WHOOP/recent-meal context, but do not speak diagnosis names, medications, sensitive category labels, or raw numbers by default. | Local private health data is safe and useful. |
| Beat 3: Executive Assistant | Mobile | After dinner: "Update my team: the strategic alignment meeting went amazing... assign action items... save a todo to buy pineapple cakes for my husband." | Produce a team update/action-items artifact and personal todo; respond with gift memory: "You got him pineapple cakes last year, maybe try high mountain oolong tea?" If real outbound messaging is not configured, create the local update artifact rather than pretending in non-demo mode. | Long-context personal/org assistant with local memory. |
| Beat 4: Back Home | Desktop | Review workspace after mobile handoff. | Show MVP/brief, team update/action items, and personal todo/gift recommendation. | Multi-interface, multi-domain agent continuity. |

## Removal Plan For Old Demo Artifacts

Remove or supersede these old hard-coded behaviors:

- Beat 2 fashion/outfit route from `VIDEO_CALL_PROMPT`, `bench/test_demo_prompts.py`, and README "Things to try".
- Exact Redis pub/sub answer and "Yeah, do it" `realtime_design.md` follow-up as a core beat.
- Old handwritten todo route for `add streaming updates`, `Redis pub/sub`, `write events table`, `React hook`, `test reconnect`, and `buy umbrella`.
- Old transient ack: "I'm adding these to the React/FastAPI/MySQL project dashboard we started from your whiteboard this morning."
- Old generated workspace artifacts: `workspace/README.md`, `workspace/realtime_design.md`, `workspace/project_dashboard/tasks.md`, and `workspace/personal_todos.md` content from the previous script.

Keep these because they still support the new demo:

- Cold-open camera/audio readiness behavior.
- Health/WHOOP prompt loader and privacy constraints.
- Bidirectional handoff.
- Markdown assistant, workspace update assistant, inline todo/messaging tools, and optional HTML assistant executor.

## File-Level Plan

| File | Planned change |
|------|----------------|
| `prompts.py` | Replace old demo-beat instructions with Computex flow. Keep cold open and private health rules. Remove fashion and old handwritten/Redis exact scripts. Add `_load_computex_demo_context()` only if using `demo_files/computex-demo.yaml`. |
| `demo_files/computex-demo.yaml` | Optional new flat fixture for team org chart, dinner context, spouse gift memory, and default action-item mapping. Use comments marking it dummy demo data. |
| `tools.py` | If using HTML for Beat 1, add `html_assistant` to `ALL_TOOLS`, `is_agent_tool()`, and `execute_tool()` sentinel handling. Otherwise do not touch. |
| `server.py` | Generalize old workspace update helpers from handwritten-task routing to Computex update routing. Add/refine path inference for `mvp_brief.md`, `team_update.md`, `executive_brief.md`, and `personal_todos.md`. Remove old Beat 4 fallback item list. |
| `bench/test_demo_prompts.py` | Rewrite live prompt suite for new beats: cold open, MVP/brief tool call, private menu recommendation, executive assistant update/gift memory, and absence of old fashion/umbrella/Redis scripts. |
| `TESTING.md` | Add a new Computex demo regression section and mark old prompt suite as superseded if necessary. |
| `README.md` | Update "Things to try" to Computex demo flow. |
| `MILESTONES.md` | Add a new milestone entry once implementation/tests pass. |
| `workspace/` | Remove old generated artifacts at implementation start, then let new demo runs regenerate the new MVP/brief/team/todo artifacts. Do not commit generated workspace output unless explicitly requested. |

## Phased Implementation Plan

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Cleanup and fixture design: remove old generated workspace artifacts, decide whether `demo_files/computex-demo.yaml` is needed, and add it if needed with dummy org/gift context | completed |
| 2 | Prompt refresh: replace old beat instructions in `VIDEO_CALL_PROMPT` and assistant prompts with the Computex beats while preserving health privacy and cold-open behavior | completed |
| 3 | Tool/server routing: expose `html_assistant` if needed, generalize workspace update behavior for MVP brief/team update/personal todo, and delete old handwritten-umbrella routing | completed |
| 4 | Prompt and workflow tests: rewrite `bench/test_demo_prompts.py`; add unit checks for workspace routing and absence of old hard-coded strings | completed |
| 5 | Docs and milestone closeout: update README, TESTING, MILESTONES, and progress; commit each phase with existing `[feat]`, `[fix]`, `[docs]` format | pending |

## Tests

Use `.venv-gpu/bin/python` for Python checks.

1. Syntax/static:
   - `.venv-gpu/bin/python -m py_compile prompts.py server.py tools.py bench/test_demo_prompts.py`
   - `node --check static/js/app.js`
   - `git diff --check`
2. Prompt E2E:
   - `.venv-gpu/bin/python bench/test_demo_prompts.py`
   - Expected cases: cold open, Beat 1 MVP/brief tool path, Beat 2 private menu, Beat 3 executive update/gift memory, old-beat absence checks.
3. Unit/sentinel:
   - Tool schema sentinel includes expected agent tools and no stale `html_assistant` gap if HTML remains enabled in UI.
   - Workspace update helper writes new Computex files and does not write old `spark-beat4-*` sections.
   - Health-context privacy Test A remains passing: no raw digits or sensitive labels in `_load_health_context()` output.
4. Optional live workflow:
   - Desktop Beat 1 starts artifact generation.
   - Handoff to mobile.
   - Mobile menu recommendation passes privacy script.
   - Mobile executive update writes workspace/todo artifacts.
   - Bring back to desktop and inspect generated workspace outputs.

## Acceptance Criteria

- New demo beats are the only current scripted prompt regression path.
- Old fashion, exact Redis-improvement, handwritten todo, and umbrella demo scripts are removed from active prompts/tests/docs.
- Cold open still works with a short camera/audio readiness response.
- Beat 1 reliably creates at least a reviewable MVP brief/scaffold; optional HTML prototype is enabled only if the existing HTML executor is exposed and tested.
- Beat 2 uses health/WHOOP context without speaking private medical labels or raw numbers by default.
- Beat 3 creates a concrete team update/action-items artifact and a personal todo/gift recommendation grounded in local demo memory.
- Beat 4 can show the generated workspace state after handoff back to desktop.
- No new top-level packages or unnecessary frontend toggles are introduced.
- Existing WHOOP, handoff, ASR/TTS/VLM, and core tool behavior stay intact.

## Out Of Scope

- Real SMTP/email integration unless the user explicitly wants it after the plan.
- A new database for org/team state.
- Mid-run autonomous codebase generation beyond the existing agent/tool surfaces.
- Reworking the handoff system.
- Changing the WHOOP OAuth/cron architecture.
