# Progress - Diagram To MVP Codebase Agent

## Session 2026-05-06 - planning and script preservation

Started a new active planning-with-files effort for the updated Beat 1 goal:
diagram prompt to actual generated MVP codebase. Read `~/selena/CLAUDE.md`,
the prior root planning files, and the key tool/agent paths in `tools.py`,
`server.py`, `prompts.py`, `static/index.html`, `static/js/app.js`, and the
bench tests. Archived the completed Computex demo beat plan to
`.planning/archive/2026-05-06-computex-demo-beats-refresh/`. Drafted the new
active plan with an explicit file-necessity review, per the user's flat and
concise workspace requirement. Next step: save the current demo script in
`docs/COMPUTEX_DEMO_SCRIPT.md`, then implement `codebase_assistant`.

Saved the current demo script to `docs/COMPUTEX_DEMO_SCRIPT.md` and marked
Phase 1 complete. The registry install path was blocked by GitHub
unauthenticated API rate limiting, but direct git access worked. Installed
`webapp-testing`, `frontend-design`, `code-reviewer`, and
`security-compliance` from `vadimcomanescu/codex-skills` via the skill
installer's git fallback. Read the relevant frontend implementation, webapp
testing, code-review, and threat-model guidance before starting Phase 2.

User clarified that `codebase_assistant` must be an agentic coding workflow,
not a hard-coded generated MVP template. Updated the plan and findings to pivot
from deterministic scaffolding to a constrained Claw/OpenClaw coding sub-agent
plus Playwright-style evaluation/refinement. User also asked for durable
morning inspection artifacts: screenshots/logs should not be committed and will
be saved under ignored `test_assets/mvp-generation-runs/` for each generated
MVP run.

Implemented `codebase_assistant` as a UI-agent route in `tools.py`,
`prompts.py`, `server.py`, and the existing frontend. Build requests now route
to a codebase-generating agent while brief-only requests keep using
`markdown_assistant`. The server constrains output to `workspace/*_mvp/`, tries
OpenClaw first, falls back to noninteractive Codex CLI when OpenClaw fails to
produce files, prunes generated planning/config artifacts, and reports
`codebase_complete` with files and evaluation details.

Added Playwright-style evidence capture through the existing Node Playwright
module. The evaluator starts the generated FastAPI app, captures desktop and
mobile screenshots, records browser logs, checks for console errors, and fails
on mobile horizontal overflow. Installed the local Chromium browser cache after
the first screenshot pass exposed the missing Playwright browser. Added one
repair pass for app-start failures and used a focused Codex repair to eliminate
mobile overflow in the generated MVP.

Ran the real workflow. OpenClaw currently fails with `Cannot convert undefined
or null to object`, so the Codex fallback built and repaired
`workspace/agent_monitor_mvp/`. Final generated files are `app.py`,
`task_history.json`, and `mvp_brief.md`; browser evaluation passed with
screenshots saved under `test_assets/mvp-generation-runs/20260506-173640/`.
The generated app and all screenshots/logs remain ignored by git.

Final verification passed: Python `py_compile`, `node --check`, `git diff
--check`, deterministic Computex workspace routing, live text prompt E2E with
build/brief/menu/executive variants, whiteboard image prompt E2E, generated
MVP browser evaluation with desktop/mobile screenshots, and the handoff helper
smoke test. Prompt tests were tightened for the new codebase route, stringified
workspace-update `items`, gift-todo preservation, and image-readback retries.
