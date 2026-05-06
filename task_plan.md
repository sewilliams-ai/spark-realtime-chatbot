# Task Plan - Diagram To MVP Codebase Agent

## Goal

Enable the Computex Beat 1 workflow the user actually wants: when the user
shows the Agent Monitoring diagram and says "build this / turn this sketch into
an MVP," Spark should create a runnable local MVP codebase, not only
`mvp_brief.md`. The generated artifact should include a polished UI, a FastAPI
server, a task-history persistence layer, and a brief containing core
architecture decisions.

## Pattern Audit

### Top-Level Directories

| Path | Purpose | Decision |
|------|---------|----------|
| `clients/` | External ASR/LLM/TTS/VLM/WHOOP/Claw clients. | No new client; this is local workspace generation. |
| `static/` | Main browser UI and existing tool/agent checkboxes. | Extend only if needed to enable/show the new agent. |
| `demo_files/` | Local demo memory/context fixtures. | No new data fixture needed. |
| `docs/` | Durable project/reference docs and generated architecture images. | Put the current demo script here. |
| `workspace/` | Generated demo output scratch area. | Generated MVP codebase belongs here, not in repo source. |
| `bench/` | Prompt/workflow regression scripts. | Extend existing Computex tests where possible. |
| `scripts/` | Operational scripts. | No new script needed for P0. |
| `.planning/` | Archived planning files. | Archive completed Computex plan before this active plan. |

### Existing Matching Code

| Existing code/file | Current behavior | Decision |
|--------------------|------------------|----------|
| `tools.py:ALL_TOOLS` | Defines inline tools and UI-agent sentinels. | Add one `codebase_assistant` UI-agent schema; no new package. |
| `tools.py:is_agent_tool()` / `execute_tool()` | Returns sentinel JSON for UI agents. | Extend the existing sentinel pattern. |
| `server.py:execute_markdown_agent()` | Streams markdown and writes to `workspace/`. | Keep for brief-only requests. |
| `server.py:execute_html_agent()` | Streams a standalone HTML prototype. | Keep for explicit HTML-only asks. |
| `server.py:execute_workspace_update_agent()` | Writes multiple local workspace files for executive updates. | Do not overload it for code generation. |
| `static/index.html` / `static/js/app.js` | Enables checked tools/agents and displays agent completions. | Add minimal UI enablement/completion handling if needed. |
| `bench/test_demo_prompts.py` | Live prompt E2E for Computex text prompts. | Update Beat 1 build prompts to expect codebase routing. |
| `bench/test_whiteboard_image_prompt.py` | Live VLM image test for the Agent Monitoring sketch. | Update image build prompt to expect codebase routing. |
| `bench/test_computex_workspace.py` | Deterministic tool/workspace checks. | Extend instead of creating another unit-test file. |

### Config And Data Conventions

- Generated user/demo artifacts live under `workspace/`.
- Prompt routing lives in `prompts.py`, with concise tool-selection rules.
- UI-agent execution lives as methods on `VoiceSession` in `server.py`.
- Tool exposure is opt-in through existing frontend checkbox state.
- Tests use `.venv-gpu/bin/python`.

## Architecture Decision

Add a narrow `codebase_assistant` UI-agent path that deterministically writes a
small runnable MVP into `workspace/agent_monitor_mvp/`. This is intentionally
not a general repo-editing agent: live demo reliability matters more than
letting the voice assistant mutate the active application source tree.

The generated workspace will be flat and concise:

1. `workspace/agent_monitor_mvp/app.py` - one-file FastAPI server with embedded
   polished HTML/CSS/JS UI and JSON-backed API.
2. `workspace/agent_monitor_mvp/task_history.json` - local task/run history
   storage seed.
3. `workspace/agent_monitor_mvp/mvp_brief.md` - architecture decisions, API
   surface, data model, tradeoffs, and run instructions.

## File Necessity Review

Before implementation, ask for every proposed file: is this necessary, and can
it be condensed?

| Proposed file/change | Necessary? | Condense decision |
|----------------------|------------|-------------------|
| `docs/COMPUTEX_DEMO_SCRIPT.md` | Yes. The user explicitly asked to save the current demo beats/script outside archived planning. | Single docs file; no separate beat files. |
| `tools.py` `codebase_assistant` schema | Yes. Existing `markdown_assistant` writes docs only, and `html_assistant` is UI-only. A dedicated multi-file codebase route avoids semantic overload. | One schema entry only. |
| `server.py` codebase helper methods | Yes. Existing UI-agent methods live here; adding a sibling keeps flat structure. | Keep deterministic templates in this file; no new module. |
| `static/index.html` agent checkbox | Likely yes because enabled tools are sent from checkboxes. | One checked checkbox in existing Agents section; no new panel. |
| `static/js/app.js` completion handling | Yes if we want the user to see the files generated. | One message handler; no modal/editor. |
| `workspace/agent_monitor_mvp/app.py` | Yes. Demonstrates actual UI + FastAPI server in runnable code. | Embed UI in FastAPI app to avoid separate `frontend/` or `static/` files. |
| `workspace/agent_monitor_mvp/task_history.json` | Yes. Demonstrates persistent task history without adding SQLite or a database service. | One JSON file; no migrations/schema files. |
| `workspace/agent_monitor_mvp/mvp_brief.md` | Yes. User explicitly wants architecture decisions in the brief. | Combine README/run instructions into the brief; no separate README. |
| New unit-test file | No. | Extend `bench/test_computex_workspace.py`. |
| New prompt image-test file | Already exists. | Update `bench/test_whiteboard_image_prompt.py`; no second image test. |
| New top-level package | No. | Rejected. |

## Demo Script Reference

Save the current script in `docs/COMPUTEX_DEMO_SCRIPT.md` and keep it as the
canonical overnight reference.

## Phased Implementation Plan

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Archive completed Computex planning, save current demo script, and create this active plan with the file-necessity review | completed |
| 2 | Add `codebase_assistant` routing: prompts, tool schema, server helper, minimal frontend enablement/completion UI | in_progress |
| 3 | Update prompt and workflow tests, including image prompt routing and deterministic generated-code checks | pending |
| 4 | Run iterative tests, fix failures under the 3-strike rule, update docs/milestones/progress, and commit | pending |

## Tests

Use `.venv-gpu/bin/python`.

1. Static/syntax:
   - `.venv-gpu/bin/python -m py_compile prompts.py tools.py server.py bench/test_demo_prompts.py bench/test_computex_workspace.py bench/test_whiteboard_image_prompt.py`
   - `node --check static/js/app.js`
   - `git diff --check`
2. Deterministic workflow:
   - `.venv-gpu/bin/python bench/test_computex_workspace.py`
   - Assert `codebase_assistant` is exposed, generated app files are flat, `app.py` compiles, JSON parses, and `mvp_brief.md` contains architecture decisions.
3. Live prompt E2E:
   - `.venv-gpu/bin/python bench/test_demo_prompts.py`
   - Beat 1 build variants should route to `codebase_assistant`; brief-only variants should still route to `markdown_assistant`.
4. Live image prompt E2E:
   - `.venv-gpu/bin/python bench/test_whiteboard_image_prompt.py`
   - The actual Agent Monitoring PNG should route the build request to `codebase_assistant`.
5. Regression:
   - `.venv-gpu/bin/python bench/test_handoff.py`
   - Health/privacy prompt tests remain covered by existing suite; rerun if prompt changes touch health rules.

## Acceptance Criteria

- Showing the Agent Monitoring diagram and asking Spark to build an MVP routes
  to a codebase-building agent.
- The generated MVP is runnable from the workspace and includes UI, FastAPI API,
  and task-history persistence.
- The generated UI is polished enough for a demo: dashboard cards, agent list,
  action items, activity feed, and clear status states.
- The generated workspace stays concise: no frontend/backend/database directory
  sprawl and no unnecessary files.
- Brief-only asks still create `mvp_brief.md` through the markdown assistant.
- Existing menu, executive assistant, handoff, and WHOOP prompt behavior remains
  intact.

## Out Of Scope

- A general-purpose autonomous coding agent that edits this app's repo.
- Real database service setup; JSON persistence is enough for the demo MVP.
- Package installation or dev-server orchestration for generated apps.
- New top-level packages or nested workspace scaffolding.
