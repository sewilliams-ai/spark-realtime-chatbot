# Task Plan - Bidirectional Conversation Handoff

## Goal

Port the useful handoff mechanics from `main` into `claw`, but implement them
as a bidirectional conversation handoff layer rather than a laptop-to-phone-only
feature. A user should be able to start a voice/video conversation on laptop,
continue it on phone, then move it back to laptop while preserving completed
conversation context, system prompt, selected voice, and enabled tools.

## Pattern Audit

### Top-Level Directories

| Path | Purpose | Handoff relevance |
|------|---------|-------------------|
| `clients/` | External-service and model clients (`asr.py`, `llm.py`, `tts.py`, `vlm.py`, `face.py`, `whoop.py`). | Handoff is not an external service, so do not put it here. |
| `static/` | Browser UI (`index.html`, `css/styles.css`, `js/app.js`). | Add handoff affordances here; prefer CSS classes over `main`'s inline styles. |
| `demo_files/` | Demo context and local health cache. | No handoff data belongs here; handoff state should stay in memory. |
| `test_assets/` | Ignored fixtures used by tests. | No runtime dependency. |
| `scripts/` | Operational scripts such as `refresh-whoop.sh`. | No cron/job required for handoff. |
| `bench/` | Benchmark and smoke-test scripts. | Existing pattern for WebSocket smoke tests. |
| `docs/` | Architecture diagram assets/scripts. | Optional documentation only. |
| `workspace/` | Demo-generated workspace output. | Do not use for conversation state. |
| `audio_cache/`, `logs/`, venv dirs | Runtime/generated artifacts. | Do not write handoff history here. |

### Existing Matching Patterns

| Existing code | Observation | Design consequence |
|---------------|-------------|--------------------|
| `server.py:315-347` | `VoiceSession` owns WebSocket-local state including `conversation_history`, selected voice, tools, camera frame, and connection status. | Handoff should hydrate/publish from `VoiceSession`, not create a parallel session class. |
| `server.py:883-925`, `server.py:1337-1343` | Text-call path appends user/assistant messages to `conversation_history`. | Publish handoff state after completed assistant responses. |
| `server.py:2164-2171`, `server.py:2373-2404` | Video-call path separately appends user/assistant messages. | Add publish hooks in video branches too; do not rely only on `process_user_message()`. |
| `server.py:1974-2004` | Reset, voice, prompt, and tool settings mutate session state. | Update shared conversation state after these settings changes. |
| `static/js/app.js:198-209`, `static/js/app.js:272-280` | Browser-visible chat history is persisted to `localStorage["spark_realtime_chats"]`. | Existing local browser history remains local; server handoff state is a process-local bridge, not durable storage. |
| `static/js/app.js:1604-1663` | `saveCurrentChat()` extracts visible messages from DOM into localStorage. | Reuse this for client-history sync when reconnecting/resuming. |
| `static/js/app.js:2038-2065` | Current WebSocket connects with no query params. | Add `device`, `conversation_id`, and `chat_id` query params; handoff offers should be driven by the WebSocket, not pre-call REST discovery. |
| `git show main:server.py:66-132` | `main` has in-memory `handoff_snapshots`, sanitization, TTL pruning, and latest-candidate selection. | Reuse the concept, but generalize away from desktop-only snapshots. |
| `git show main:server.py:343-385` | `main` exports/hydrates system prompt, conversation history, voice, tools, visible messages. | Preserve this payload shape where compatible. |
| `git show main:server.py:1757-1779` | `main` transfers control to mobile and closes the desktop socket. | Replace with device-agnostic ownership transfer. |
| `git show main:static/js/app.js:249-445` | `main` adds mobile-only handoff UI with inline DOM styles. | Keep the flow, but move presentation to CSS and make it bidirectional. |

### Proposed New File / Module

| Proposed | Audit result |
|----------|--------------|
| `handoff.py` | **Not needed for the first implementation.** `server.py` is long, but the existing precedent in `main` puts handoff helpers in `server.py`, and the feature is tightly coupled to `VoiceSession`, live WebSockets, and route handling. Avoid the new file unless the handoff section becomes too large to keep readable. |

No new top-level package is proposed. No new module is required for the first pass.

## Architecture Decision

Use a compact process-local conversation handoff section inside `server.py`,
next to the existing app globals and `VoiceSession` class. This preserves
`main`'s proven snapshot/hydrate mechanics while fixing its desktop-only
assumptions, without adding a new module or a pre-call REST discovery path for
a feature that is mostly WebSocket/session glue.

The key shift is from `handoff_snapshots[desktop_chat_id]` to
`conversation_states[conversation_id]`:

```python
ConversationState(
    conversation_id="conv_...",
    owner_session_id="session_...",
    owner_device="desktop" | "mobile",
    owner_chat_id="chat_...",
    system_prompt="...",
    conversation_history=[...],
    enabled_tools=[...],
    selected_voice="af_bella",
    visible_messages=[...],
    updated_at=...,
)
```

`chat_id` remains a browser-local UI id. `conversation_id` becomes the stable
cross-device id used for ownership transfer.

## Implementation Phases

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Add `server.py` conversation handoff helpers with sanitized conversation state, TTL pruning, candidate selection, and focused unit tests | completed |
| 2 | Integrate server-side session identity, active-call detection, bidirectional publish/hydrate, and generic transfer control | completed |
| 3 | Add frontend conversation identity, device detection, WebSocket query params, and local chat-state replay on resume | completed |
| 4 | Add Teams-style bidirectional UX shown only after a second device joins an active call: "continue on this device" prompt and "bring back" banner/button on the displaced device | completed |
| 5 | Add tests/docs: `TESTING.md` entries, static assertions, two-socket desktop->mobile->desktop smoke test, and milestone note | completed |

## File Plan

| File | Change |
|------|--------|
| `server.py` | Add a small conversation handoff section for state helpers, then add `conversation_id`, `chat_id`, and `device_type` to `VoiceSession`; publish after completed turns/settings; detect when a second device joins an active call; hydrate on resume; generic `transfer_conversation_control()`. Keep WHOOP routes, cache busting, `_filter_for_demo`, and barge-in logic intact. |
| `static/js/app.js` | Add device/conversation ids, WebSocket params, handoff messages, and transfer-back handler. Avoid wholesale `main` import. |
| `static/index.html` | No planned change for first pass; the handoff offer should not appear before starting a call. |
| `static/css/styles.css` | Add minimal reusable classes for the in-call handoff prompt/banner only if JS-only styling is not enough. |
| `TESTING.md` | Document unit/static/live smoke tests for bidirectional handoff. |
| `MILESTONES.md` | Add/close a short entry once implementation and tests pass. |

## Tests

1. `python -m py_compile server.py`
2. `bench/test_handoff.py` unit-smoke test for server-side handoff helpers: sanitize history, preserve system prompt/tools/voice, prune TTL, return a candidate only when another active device joins an active call, transfer desktop -> mobile, and transfer mobile -> desktop.
3. Static JS checks: `node --check static/js/app.js`; assertions for `conversation_id`, `resume_handoff`, `handoff_transferred`, `handoff_required`, and transfer-back button handler.
4. Regression checks: current `/whoop/login` route remains untouched, health prompt code remains untouched, and `git diff --check` passes.
5. Live WSS smoke remains optional for a running GPU server: connect with `device=desktop`, complete a turn, connect `device=mobile`, receive in-call handoff offer, resume, then bring back from desktop with the same `conversation_id`.

Use `.venv-gpu/bin/python` for Python tests.

## Acceptance Criteria

- Desktop -> mobile and mobile -> desktop both preserve completed user and assistant messages.
- Handoff offer appears only when a second device joins while an active call exists.
- No handoff offer appears before starting a call.
- Handoff preserves `system_prompt`, `enabled_tools`, and `selected_voice`.
- The previous owner receives a clear transfer event and can bring the conversation back without losing context.
- No normal conversation history is written to project files, logs, cache, database, or `demo_files` by the handoff layer.
- Handoff state is process-local and TTL-pruned; server restart loses handoff state by design.
- Current `claw` changes are preserved: WHOOP OAuth/cron, health context, cache-busted index serving, demo-mode tool filtering, barge-in cancellation, and WebSocket initialization fix.
- Tests in the plan pass and are recorded in `TESTING.md`.

## Out Of Scope

- Mid-utterance audio buffer migration.
- In-flight TTS playback migration.
- In-flight tool-call migration.
- Multi-device simultaneous active audio.
- Durable server-side conversation database.
- QR-code pairing or authentication beyond same-app/same-network demo assumptions.
