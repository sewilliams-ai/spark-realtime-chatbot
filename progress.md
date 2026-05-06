# Progress - Computex Demo Beats Refresh

## Session 2026-05-06 - planning

Started a new active planning-with-files effort for replacing the old demo
beats with the Computex demo script. Restored the previous root planning
context, confirmed the completed handoff plan is already archived, ran the
planning catch-up script, checked git status, read `~/selena/CLAUDE.md`, and
audited current hard-coded beat behavior across `prompts.py`, `server.py`,
`tools.py`, `bench/test_demo_prompts.py`, `TESTING.md`, `README.md`,
`demo_files/`, and `workspace/`.

Findings: the old script is hard-coded in multiple layers. Cold open remains
useful. Old Beat 1 README/Redis behavior lives in `VIDEO_CALL_PROMPT`,
`MARKDOWN_ASSISTANT_PROMPT`, path inference, tests, and docs. Old Beat 2
fashion lives in `VIDEO_CALL_PROMPT`, an unused fashion template, tests, and
docs. Old Beat 3 private menu should be kept but moved into the new Beat 2
story. Old Beat 4 handwritten todos/umbrella lives in prompt rules, deterministic
server helpers, VLM short-circuit acknowledgements, tests, and untracked
workspace artifacts. The repo already has an `html_assistant` UI/server
executor but no `tools.py` schema, making it an optional lean extension for the
MVP beat.

Wrote the new active `task_plan.md` and `findings.md` for the Computex demo
beats refresh. No runtime code changes or artifact deletion have been executed
yet; cleanup is Phase 1 of the implementation plan so it can be reviewed and
committed deliberately.

## Session 2026-05-06 - Phase 1 cleanup and fixture

Started implementation. Cleared the previous generated workspace demo artifacts
so the next demo run starts from `workspace/.gitkeep`, and added
`demo_files/computex-demo.yaml` as a flat dummy context fixture for team roles,
the dinner setup, and the Taipei gift-memory beat. This mirrors the existing
flat dummy health fixture pattern and avoids a new package or top-level demo
directory.

## Session 2026-05-06 - Phase 2 prompt refresh

Added `prompts._load_computex_demo_context()` next to the existing health
loader and appended the local Computex context to `VIDEO_CALL_PROMPT`. Replaced
the active video-call demo instructions with the Computex flow: Agent Workbench
MVP brief to `mvp_brief.md`, private health menu recommendation, and executive
assistant team-update/personal-gift behavior. Removed old active prompt strings
for the fashion beat, exact Redis/pub-sub judgment, handwritten todo list, and
React/FastAPI/MySQL project-dashboard acknowledgment. Tests run:
`.venv-gpu/bin/python -m py_compile prompts.py`, prompt-loader smoke assertions,
and `git diff --check`; all passed.
