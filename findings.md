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
  MVP" should create a real local MVP codebase.
- The generated system should include:
  - polished UI,
  - FastAPI server,
  - task-history storage,
  - brief with architecture decisions.
- Workspace output must be as flat and concise as possible.
- Current demo beats/script must be saved as a normal reference file, not only
  in archived planning.

## Existing Surfaces

- `markdown_assistant` is checked by default and writes markdown through
  `server.py:execute_markdown_agent()`.
- `html_assistant` exists in server/frontend, but only returns an HTML payload
  and does not write a runnable backend or persistence layer.
- `workspace_update_assistant` writes multiple markdown files for the executive
  assistant beat; overloading it for app code would mix unrelated concerns.
- `ask_claw` can delegate to a broader coding agent, but it is slower and less
  predictable for a live stage demo.
- `write_file` and `run_python` exist as inline tools, but relying on a VLM to
  issue several correct file-writing tool calls from a sketch is too brittle for
  the main demo path.

## Recommended Shape

Add `codebase_assistant` as one new UI-agent tool, implemented beside the other
agent methods in `server.py`. It should write a deterministic, polished MVP
scaffold into `workspace/agent_monitor_mvp/` based on the visible sketch
context.

Recommended generated files:

- `app.py`: FastAPI server, embedded HTML/CSS/JS UI, JSON-backed API.
- `task_history.json`: seed task/run history.
- `mvp_brief.md`: architecture decisions, endpoints, data model, run command,
  and tradeoffs.

This is the smallest artifact set that proves the story without creating
frontend/backend/database directory sprawl.

## File Necessity Conclusions

- Do not add a new top-level package.
- Do not add a separate generated frontend directory.
- Do not add a separate generated backend directory.
- Do not add `requirements.txt` unless tests prove the generated app cannot be
  explained/run from the existing repo environment.
- Do not create a second deterministic unit-test file; extend
  `bench/test_computex_workspace.py`.

## Risks

- A pure LLM-generated multi-file app may be unstable during the demo. Use
  deterministic templates for the app and rely on the model only for routing
  and visible-context extraction.
- Adding another agent checkbox is a small UI addition, but enabled tools are
  currently driven by checkboxes. A checked `Codebase Assistant` row is the
  least invasive way to make the tool available.
- `server.py` is already long, but existing UI-agent execution lives there.
  Keeping a sibling method is flatter than adding a new module.
