# Findings - Diagram To MVP Codebase Agent

## Context Restored

- Completed Computex demo beat planning exists in root planning files and has
  now been copied to `.planning/archive/2026-05-06-computex-demo-beats-refresh/`.
- The current branch is `claw`.
- Pre-existing untracked files remain `.codex` and `AGENTS.md`; leave them
  alone.

## User Requirements

- Beat 1 must not stop at `mvp_brief.md`.
- Showing the whiteboard diagram and saying "build this / turn this into an
  MVP" should start a coding sub-agent workflow that creates a real local MVP
  codebase.
- The generated system should include:
  - polished UI,
  - FastAPI server,
  - task-history storage,
  - brief with architecture decisions.
- Workspace output must be as flat and concise as possible.
- Current demo beats/script must be saved as a normal reference file, not only
  in archived planning.
- The diagram image and all overnight test/evaluation results should be saved
  somewhere inspectable, but screenshots/logs should not be committed.
- The generated MVP should be evaluated with Playwright-style browser testing,
  preferably using the higher-quality `playwright-interactive` workflow and
  `webapp-testing` helper patterns as fallback.

## Existing Surfaces

- `markdown_assistant` is checked by default and writes markdown through
  `server.py:execute_markdown_agent()`.
- `html_assistant` exists in server/frontend, but only returns an HTML payload
  and does not write a runnable backend or persistence layer.
- `workspace_update_assistant` writes multiple markdown files for the executive
  assistant beat; overloading it for app code would mix unrelated concerns.
- `ask_claw`/OpenClaw is the preferred local coding-agent primitive, but the
  current CLI returns `Cannot convert undefined or null to object` even for a
  smoke prompt. The production workflow therefore tries OpenClaw first and then
  falls back to noninteractive Codex CLI inside the generated workspace.
- `write_file` and `run_python` exist as inline tools, but relying on a VLM to
  issue several correct file-writing tool calls from a sketch is too brittle for
  the main demo path.

## Recommended Shape

Add `codebase_assistant` as one new UI-agent tool, implemented beside the other
agent methods in `server.py`. It prepares a focused build brief, launches a
local OpenClaw coding sub-agent constrained to `workspace/agent_monitor_mvp/`,
falls back to Codex CLI if OpenClaw fails or produces no required files, then
runs evaluation checks and saves evidence.

Recommended generated files for the sub-agent, not committed repo source:

- `app.py`: FastAPI server, embedded HTML/CSS/JS UI, JSON-backed API.
- `task_history.json`: seed task/run history.
- `mvp_brief.md`: architecture decisions, endpoints, data model, run command,
  and tradeoffs.

This is the smallest artifact set that proves the story without creating
frontend/backend/database directory sprawl. If the sub-agent adds files, the
evaluator should flag whether each extra file was necessary.

## File Necessity Conclusions

- Do not add a new top-level package.
- Do not add a separate generated frontend directory.
- Do not add a separate generated backend directory.
- Do not add `requirements.txt` unless tests prove the generated app cannot be
  explained/run from the existing repo environment.
- Do not create a second deterministic unit-test file; extend
  `bench/test_computex_workspace.py`.
- Do not hard-code the generated MVP source into `server.py`.
- Do ignore generated `workspace/*_mvp/` folders so actual generated apps stay
  inspectable locally without becoming repo source.

## Risks

- A pure LLM-generated app may be unstable during the demo. Mitigate by using a
  constrained build brief, flat file limits, and iterative Playwright/browser
  evaluation with saved evidence.
- Adding another agent checkbox is a small UI addition, but enabled tools are
  currently driven by checkboxes. A checked `Codebase Assistant` row is the
  least invasive way to make the tool available.
- `server.py` is already long, but existing UI-agent execution lives there.
  Keeping a sibling method is flatter than adding a new module.
- Python Playwright is not currently installed in `.venv-gpu`; Node Playwright
  exists in the OpenClaw checkout. Chromium had to be installed into the local
  Playwright cache before screenshots could be captured.
- Generated apps can pass syntax checks but still fail browser startup or
  mobile layout. The workflow now repairs once on browser failure, checks
  desktop/mobile screenshots, and fails on mobile horizontal overflow.
