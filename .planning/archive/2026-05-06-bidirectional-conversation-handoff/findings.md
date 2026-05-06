# Findings - Bidirectional Conversation Handoff

## Current `claw` State

- Runtime check on 2026-05-06: no process was listening on `8443` or `8445`,
  so current socket failures are connection-refused, not a handoff bug.
- `server.py:291-308` serves `index.html` with cache-busters for
  `/static/css/styles.css` and `/static/js/app.js`. This must be preserved;
  `main`'s older `index()` would regress this.
- `server.py:315-347` defines `VoiceSession` with WebSocket-local state only.
  There is no `chat_id`, `conversation_id`, `device_type`, or handoff registry
  in `claw`.
- `server.py:339-344` initializes `conversation_history` as one system message.
  This is the server-side context to hydrate/publish.
- `server.py:883-925` is the text-call happy path; user message appended at
  `server.py:889`, assistant message appended at `server.py:921`.
- `server.py:1337-1343` is another text-call final response append/send path.
- `server.py:2164-2171` appends video-call user transcription; video-call
  assistant responses are appended at `server.py:2375-2404` depending on
  tool/no-tool branches.
- `server.py:1974-2004` handles reset/system prompt/voice/tool controls.
  These settings should be included in conversation state.
- `static/js/app.js:198-209` keeps browser chat state in memory/localStorage,
  and `static/js/app.js:272-280` loads it from
  `localStorage["spark_realtime_chats"]`.
- `static/js/app.js:1604-1663` serializes visible DOM messages to localStorage.
  This is useful for a reconnect sync message, but it is browser-local.
- `static/js/app.js:2038-2065` opens `/ws/voice` without query params today.
- `static/js/app.js:2654-2958` handles JSON messages but has no handoff cases.

## `main` Handoff Precedent

- `git show main:server.py:66-132` adds process-local `handoff_snapshots` and
  `active_voice_sessions`, sanitizes model history, summarizes visible
  messages, prunes stale snapshots, and selects the newest desktop candidate.
- `git show main:server.py:298-311` adds `/api/handoff/status` for mobile to
  discover the newest laptop chat. Do not port this for the first pass because
  the desired UX only shows handoff after a second device connects during an
  active call.
- `git show main:server.py:320-385` extends `VoiceSession` with `chat_id` and
  `device_type`, plus `export_handoff_snapshot()`,
  `publish_handoff_snapshot()`, and `hydrate_from_handoff_snapshot()`.
- `git show main:server.py:360-363` blocks publishing from non-desktop
  sessions. This is the main reason `main` cannot support mobile -> desktop.
- `git show main:server.py:1740-1754` sends `handoff_resumed` without speaking
  a fixed handoff line. Keep that quiet-resume behavior.
- `git show main:server.py:1757-1779` transfers control only to mobile. This
  should be replaced by a device-agnostic transfer.
- `git show main:server.py:1786-1810` accepts `device`, `chat_id`, and
  `handoff_source` query params and can auto-resume from the query.
- `git show main:server.py:1929-1954` accepts `sync_client_history` to let a
  browser republish visible messages after refresh.
- `git show main:static/js/app.js:249-445` implements mobile-only discovery,
  prompt UI, resume, and local history sync. It works but uses inline styling
  and laptop-specific language.
- `git show main:static/js/app.js:2225-2263` adds WebSocket query params and
  stale-socket protection. Useful to port carefully.
- `git show main:static/js/app.js:2896-2948` handles
  `handoff_available`, `handoff_resumed`, `handoff_transferred`,
  `handoff_declined`, and `handoff_unavailable`.

## Current Conversation Persistence

- Server-side conversation history is in memory on each `VoiceSession`.
- Browser-visible chat history is persisted in the browser's `localStorage`
  under `spark_realtime_chats`.
- Normal conversation history is not written to a server-side file, cache, or
  database by `claw`.
- Server stdout logs do print some transcript/response snippets. The handoff
  implementation should avoid adding logs that print raw conversation content.
- Agent/tool flows can write output files (`workspace/`, markdown/html files,
  personal todo files), but that is tool behavior, not general conversation
  persistence.
- WHOOP tokens and health YAML are unrelated to handoff; do not store handoff
  data in `demo_files/health.yaml`, `whoop_auth.json`, or logs.

## Recommended Data Model

Use two ids:

- `chat_id`: browser-local UI id from `static/js/app.js:203-205`.
- `conversation_id`: stable cross-device id for handoff ownership.

Use one process-local registry concept in `server.py`:

```python
@dataclass
class ConversationState:
    conversation_id: str
    owner_session_id: str
    owner_device: str
    owner_chat_id: str
    system_prompt: str
    conversation_history: list[dict[str, str]]
    enabled_tools: list[str]
    selected_voice: str
    visible_messages: list[dict[str, str]]
    updated_at: float
    message_count: int
    summary: str
```

`server.py` should keep live sockets separately:

```python
active_voice_sessions: dict[str, VoiceSession]  # keyed by session_id
conversation_states: dict[str, ConversationState]  # keyed by conversation_id
```

Do not add `handoff.py` in the first pass. Although `server.py` is already
large, the existing `main` precedent keeps handoff helpers in `server.py`, and
the feature is mostly glue around `VoiceSession`, active WebSockets, and the
`/ws/voice` route. Revisit extraction only if the handoff section grows large
enough that it obscures the existing route/session flow.

## UX Recommendation

Match Teams-style transfer semantics for the demo:

1. First device starts a call normally; no handoff UI appears.
2. When a second device opens the app while that call is active, the Start New
   Chat modal polls `/api/handoff/status` and reveals a third `Continue Call`
   option only if another active device owns a live call.
3. If accepted, the new device opens the correct call mode, sends
   `resume_handoff`, hydrates from the latest completed state, and becomes
   the owner.
4. The previous device stops mic/camera/TTS, shows "Continued on phone/laptop"
   inline where conversation content appears, and offers "Bring back".
5. Clicking "Bring back" opens a fresh WebSocket with the same
   `conversation_id`, hydrates from the latest state, and transfers ownership
   back.

This is not mid-stream migration. It is context-preserving transfer at turn
boundaries, which is the right complexity for this repo and demo.

The final flow intentionally avoids double confirmation: the modal/bring-back
button is the confirmation, and the subsequent WebSocket `handoff_available`
message auto-resumes when it matches that pending choice. The fallback bottom
banner remains only for direct WebSocket offers outside the modal path.

## Live-Test Findings 2026-05-06

- The first implementation's WebSocket-only offer appeared only after the
  user had already selected a call mode and granted camera/mic. That was too
  late for the desired UX. Adding `/api/handoff/status` and a hidden
  `Continue Call` card in `static/index.html` lets the second device transfer
  an active call from the Start New Chat modal.
- Laptop -> mobile and mobile -> laptop transfer both worked after adding
  quiet auto-resume for a pending modal or bring-back choice. Without that
  guard, the accepting device saw a second "Continue here?" prompt after it
  had already chosen to transfer.
- The displaced device's bring-back UI is better as an inline panel inside
  the conversation area than as a fixed bottom banner. The fixed banner
  remains as a fallback prompt for unplanned `handoff_available` events.
- A video-call reliability bug appeared after repeated transfers: the backend
  received `video_call_data`, but ASR returned an empty transcript. The
  frontend previously ignored empty `asr_result`, leaving
  `videoCallProcessing` true and VAD paused until the 30-second fallback.
  `resumeVideoCallListening()` now clears the processing/speaking flags,
  restores the listening status, and restarts VAD for empty ASR results.
- A related timing race existed if VAD captured speech before the resumed
  WebSocket was open, or if the WebSocket closed between WAV conversion and
  payload send. Those branches now recover through the same
  `resumeVideoCallListening()` helper instead of leaving video input stuck.

## Risks / Gotchas

- `main` is older than `claw` in important places. Do not merge whole files:
  it would risk losing WHOOP routes, health prompt behavior, cache-busted
  index serving, `_filter_for_demo`, barge-in handling, and the recent socket
  initialization fix.
- The current frontend's `createMessageElement()` appends to the active DOM.
  Handoff replay should verify whether it returns `{container, content}` or a
  DOM node at the call site to avoid double-appending.
- Handoff state should publish after completed assistant messages, not after
  every partial/transient response.
- Tool-call messages with `content: None` must be excluded from visible and
  model-safe handoff history, matching `main`'s sanitization.
- Device detection is heuristic. Use it only for UX defaults; server should
  accept explicit `device` query params.
- If two tabs on the same device are open, "same device" should not prevent
  explicit resume by `conversation_id`; it should only suppress automatic
  offers.
