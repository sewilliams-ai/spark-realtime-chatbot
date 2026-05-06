# Task Plan — PLAN.md for Beat 3 Private Health Agent

## Goal

Produce a Codex-executable implementation plan in `PLAN.md` that turns Beat 3
(restaurant menu beat) from generic "fitness goals + yesterday's ramen" into a
privacy-charged "private local health data on Spark" story. Planning only —
no code implementation in this PR.

## Scope

- Audit the current menu beat code paths (prompts.py, server.py, tools.py,
  frontend toggles, TESTING.md, MILESTONES.md).
- Research the WHOOP API (OAuth flow, endpoints, scopes, caching strategy,
  stub fallback).
- Design a health-context integration appropriate for this repo (tool vs
  context provider vs deterministic fast path; pick a hybrid).
- Replace the menu beat story with high blood pressure + bloodwork + recent
  meals + WHOOP signals.
- Specify files to edit/add, data shapes, prompt changes, tests, manual demo
  script, and acceptance criteria.

## Phases

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Data scaffolding: `demo_files/health.yaml`, PyYAML dependency, WHOOP token ignore, menu fixture | complete |
| 2 | Prompt loader + always-on injection; isolate health files from `load_demo_files()` | complete |
| 3 | WHOOP OAuth client and routes if `WHOOP_CLIENT_ID` / `WHOOP_CLIENT_SECRET` are set | complete |
| 4 | Testing documentation and WHOOP milestone closeout | complete |

## Decisions (final, post user review)

- **Architecture:** always-on prompt injection at module import time,
  matching the existing `_load_claw_persona()` pattern in `prompts.py:70-100`.
  No intent matcher, no inline tool, no UI toggle, no `VoiceSession.__init__`
  change.
- **WHOOP client placement:** `clients/whoop.py` — sits with the other
  external-service clients (asr, llm, tts, vlm, face, claw_acp). No
  top-level `health/` package.
- **Loader placement:** `_load_health_context()` is a function in
  `prompts.py` next to `_load_claw_persona()`, concatenated onto
  `VIDEO_CALL_PROMPT` at import time.
- **Data file:** one flat `demo_files/health.yaml` holding condition,
  bloodwork, meals, goals, and the WHOOP subtree. WHOOP refresh job
  replaces only `whoop:`. Tokens are separate (`demo_files/whoop_auth.json`,
  gitignored, chmod 600). PyYAML added to `requirements.txt`.
- **Privacy story:** primary concern is high blood pressure (lisinopril) +
  elevated LDL. Replaces "first half marathon" framing. The fact of
  uploading the diagnosis is part of the demo *narration*; the agent's
  spoken output never names the diagnosis, the medication, or raw numbers
  in the default path. Disclosure ladder: food-language → category word
  (on "why?") → numbers (on explicit request).
- **Demo-file isolation:** edit `load_demo_files()` (server.py:1695) to
  skip `health.yaml` and `whoop_auth.json` so the reasoning agent
  never sees them.
- **Trade-off accepted:** server restart required to pick up fresh WHOOP
  data, since the loader runs at import time. Acceptable for a demo;
  swap to session-init load later if hot-refresh becomes a requirement.

## Out of Scope

- Implementation (this PR is planning only).
- New top-level package (no `health/`).
- New inline tool, frontend toggle, or intent matcher.
- `VoiceSession.__init__` changes.
- Refactor of `tools.py` dispatch.
- Changes to ASR/TTS/VLM clients or to Beats 1, 2, 4.
- Persona-file edits in `~/.openclaw/workspace/`.

## Acceptance Criteria

- Phases 1, 2, and 4 complete with tests passing.
- Phase 3 either complete with credentials or cleanly skipped because credentials are absent.
- Health prompt context is speech-safe by construction: no raw digits, diagnoses,
  medications, or sensitive category labels in default prompt output.
- WHOOP tokens are ignored before any credential write.
- `MILESTONES.md` closes the WHOOP Integration entry.
