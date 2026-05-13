# Spark Realtime Chatbot — Redesign Spec

**Date:** 2026-05-13
**Author:** Selena Williams (`sewilliams@nvidia.com`)
**Branch plan:** new `redesign` cut from `9ed57101`; `claw` HEAD is the behavioral oracle until `redesign` reaches parity and replaces it.

---

## 1. Goal

Rebuild the voice chatbot so that (a) all prompt content is decoupled from agent logic via an external registry, (b) the agent topology is non-redundant with a clean subagent / tool dispatch surface, and (c) the mobile-audio bug that drops mic input after TTS or handoff is fixed by replacing scattered audio-state booleans with a formal state machine. The rebuild preserves every demo capability that exists on `claw` HEAD, but achieves it through honest, configurable wiring rather than prompt-level demo theater — the repo is going to press, and a grep of `prompts.yaml` must not reveal hardcoded "when the user says X, say Y" instructions.

## 2. Motivation

`spark-realtime-chatbot` is an open-source DGX-Spark voice/vision assistant being shown to press. Two problems block that:

1. **The current implementation is rigged for the live demo.** `prompts.py` mixes assistant behavior with user-specific demo content ("user ate ramen yesterday," "DEMO MODE: act as if you can place orders"). A press person grepping the repo would find a coordinated lie between `DEMO_MODE_ADDENDUM` (`prompts.py:30`) and `_filter_for_demo` (`server.py:67`) — the prompt tells the model to fake action capabilities and the tool filter strips the honest escape hatch.
2. **Audio reliability bug on the laptop→mobile transition.** Audio state is scattered across implicit booleans (`videoCallProcessing`, `ttsAborted`, `is_speaking`, `vad_paused`, `muted`) in both `server.py` and `static/js/app.js`. After TTS playback or handoff resume on mobile, one of those booleans gets stuck and silently blocks mic input. Multiple recent commits (`4b05bec`, `fc7b689`, `ef83723`, `1877a56`) chase the symptom; the root cause is the lack of a single source of truth for audio state.

The rebuild addresses both by reshaping what `prompts.py` and `tools.py` actually are: data versus loader, declarative versus dispatched. The press story becomes honest because the architecture *enforces* the honesty — there is no place in the code to hide a "when user says X" hack.

## 3. Pattern Audit

Per `~/selena/CLAUDE.md`, before any plan that adds files or modules. Three precedents in the fork-point (`9ed57101`) shape the design:

1. **`prompts.py` is already registry-shaped.** It exposes `get_vision_prompt(template_name)`, a `VISION_TEMPLATE_PROMPTS` dict, and prompt constants accessed by name. **Decoupling means backing this registry with external data**, not inventing a parallel module.
2. **`tools.py` has an `ALL_TOOLS` list + `execute_tool()` dispatch** at fork-point. This is the existing pattern for "declarative entries with a central dispatcher." The new tool/subagent registry **mirrors and extends** this surface; the file is renamed `subagents.py` to highlight the agent layer that's now the headline feature.
3. **`clients/` is where external-service wrappers live** (`asr.py`, `llm.py`, `vlm.py`, `tts.py`, `face.py`, `whoop.py`, `claw_acp.py`). The Claw/openclaw integration stays in `clients/claw_acp.py` (already present on `claw` HEAD). No new clients package is introduced.

For every new module added, the audit row:

| New thing | Decision | Rationale |
|---|---|---|
| `prompts.yaml` | **Extending** `prompts.py`'s existing registry shape | Backs the existing `get_vision_prompt(name)` API with data instead of Python dict literals; same lookup-by-name pattern, different storage |
| `subagents.py` | **Extending** `tools.py`'s `ALL_TOOLS` + dispatch | Same registry shape, broader contents (subagents + inline + action tools), one file; renamed to reflect the dispatch-by-name flat-dict pattern |
| `audio_session.py` | **No precedent** at fork-point — justified | Audio state today is scattered across two files (`server.py`, `static/js/app.js`) and ~5 implicit booleans; centralizing it is the only viable mechanism for the bug fix and for testable invariants |
| `local_data/` | **Extending** `demo_files/` | Same role (data files separate from code); renamed because "local_data" reads as "your local context, swap as needed" while "demo_files" reads as "demo-specific rigging" |
| `tests/` | **No precedent** for a pytest tree — justified | Fork-point has no tests; `bench/` exists but is ad-hoc scripts. A real regression suite is the precondition for safe TDD migration |

No new top-level packages are introduced.

## 4. Scope

### In scope (rebuilt onto `9ed57101`)

- Voice + video call + face recognition pipeline (pre-fork, treated as gold standard, **mechanically migrated**)
- Three fork-point subagents — `markdown_assistant`, `html_assistant`, `reasoning_assistant` — **mechanical cut/paste** from `VoiceSession` methods in `server.py` into `subagents.py`. No internal refactor.
- `workspace_update_assistant` — present at fork; **functionality preserved, internals refactored** to fit the new registry shape.
- Five Nemotron reasoning variants (`reasoning`, `math`, `planning`, `analysis`, `prioritization`) — migrated to `prompts.yaml` entries.
- Inline tools that exist on `claw` HEAD and serve the demo: `read_file`, `list_files`, `write_file`, `web_search`, `remember_fact`, `recall_fact`, `claw_recall`, `claw_remember`, `ask_claw`. (Note: `run_python` is intentionally excluded from v1 for press-facing safety — RCE-via-LLM surface is hard to defend in a public demo; can be added back behind a config flag in a follow-up.)
- Real action tools from `claw` HEAD: `add_todo`, `list_todos`, `complete_todo`, `send_telegram`.
- Seven new simulated action tools: `place_order`, `set_smart_home`, `post_message`, `send_email`, `place_call`, `send_money`, `simulate_action` (catch-all).
- Cross-device handoff (laptop↔mobile) — rebuilt cleanly atop the audio state machine.
- Prompt registry (`prompts.yaml` + `prompts.py` loader) — replaces all hardcoded prompts.
- Context providers in `prompts.py` — load dynamic content (persona, health, workspace) at render time; commented-out real-backend alternatives below each default.
- Audio state machine (`audio_session.py`) — single source of truth for audio session state.
- pytest test suite — Layer 1 (prompt snapshots), Layer 2a (registry contents), Layer 2b (per-handler), Layer 4 (audio state machine + error recovery).
- Manual handoff gate — committed checklist run before merge.

### Removed

- `codebase_assistant` (added on `claw` HEAD) — code-sketch capability folds into `html_assistant`.
- `DEMO_MODE_ADDENDUM` (`prompts.py:30-51`) — the press-rigging block.
- `_filter_for_demo` (`server.py:67`) — the `ask_claw` tool-stripping shim that paired with `DEMO_MODE_ADDENDUM`.
- All scattered audio-state booleans on the server side and JS side.

### Untouched

- `clients/*` — all external-service clients (`asr.py`, `llm.py`, `vlm.py`, `tts.py`, `face.py`, `claw_acp.py`, `whoop.py`).
- `static/js/app.js` desktop-path audio plumbing (only the state-coupling parts are touched; VAD, audio capture, WebSocket transport untouched).
- Dockerfile, `requirements-docker.txt`, launch scripts.
- Voice + video call + face recognition wiring (treated as gold standard).
- Internals of `markdown_assistant`, `reasoning_assistant`, `html_assistant` (mechanical move only).

### Out of scope (explicitly punted)

- MCP-style subagent transport.
- Hot-reload of prompts (boot-time load with `--validate` is sufficient).
- Containerization changes.
- Performance work beyond the audio bug (TTS overlap, ASR latency, etc. ship as-is).
- Replacing the Nemotron variants.
- An `adding_a_tool.md` docs page (kept terse via section banners in `subagents.py`).
- Splitting `clients/` further — left as-is.

## 5. Architecture

### 5.1 File layout (post-rebuild)

```
spark-realtime-chatbot/
├── prompts.py              # registry loader + context providers (one file)
├── prompts.yaml            # all prompt templates as data
├── subagents.py            # registry + ALL handlers (subagents, inline, real action, simulated)
├── audio_session.py        # runtime audio state machine
├── server.py               # voice loop + WebSocket only (no agent internals)
├── local_data/             # health.yaml, persona files, calendar.yaml — your context, swap as needed
├── clients/                # external-service wrappers (untouched)
├── static/                 # frontend (audio plumbing untouched; state-coupling rewritten)
└── tests/
    ├── __snapshots__/prompts/      # one .txt per prompt
    ├── conftest.py                 # shared fixtures
    ├── test_prompts.py             # Layer 1
    ├── test_tool_registry.py       # Layer 2a
    ├── test_subagent_handlers.py   # Layer 2b — subagents
    ├── test_action_handlers.py     # Layer 2b — action tools
    ├── test_inline_handlers.py     # Layer 2b — inline tools
    ├── test_audio_state.py         # Layer 4 + error-recovery suite
    └── manual_handoff_gate.md      # the merge checklist
```

Five Python files at root + `prompts.yaml` + `clients/` (untouched) + `static/` (mostly untouched) + `local_data/` + `tests/`. Flat by intent: scrolling between sections is preferred over navigating directory trees.

### 5.2 Prompt registry

**`prompts.yaml`** holds every prompt template as data. Each entry has three fields:

```yaml
default_system:
  description: Main voice/text mode system prompt.
  context:
    assistant_name: required
    claw_persona: optional
    workspace_context: optional
  template: |
    You are {{ assistant_name }}, the user's personal AI assistant.
    Style: calm, direct, a little playful. Prioritize brevity.
    {%- if claw_persona %}

    {{ claw_persona }}
    {%- endif %}
```

- `description` — human-readable, required.
- `context` — declared placeholders; each is `required` or `optional`. Boot-time validation refuses to start the server if a `required` key has no registered provider, or if a template references a `{{ var }}` not declared in `context`.
- `template` — Jinja2 body. `StrictUndefined` is enforced; an undeclared variable fails loudly.

**Top-of-file comment** (`prompts.yaml`):

```yaml
# prompts.yaml — prompt templates as data, separate from the loader code.
#
# Each entry declares which context placeholders ({{ var }}) the template uses.
# The actual content for those placeholders is sourced by provider functions
# in prompts.py — this file never mentions specific data sources (files, APIs).
# Edit here to change what a prompt says; edit prompts.py to change where its
# dynamic content comes from.
```

**`prompts.py`** is the loader + context providers. Top-of-file docstring:

```python
"""prompts.py — prompt registry loader and context providers.

This module loads prompts.yaml and renders templates with values from the
context providers defined below. Providers are the only code that knows
where dynamic content (persona, health, workspace files) actually comes from.
YAML stays content-agnostic; swap a provider's implementation here to wire a
different data source without touching any template.
"""
```

API:

```python
class Registry:
    def __init__(self, path: Path) -> None: ...
    async def render(self, name: str, **overrides) -> str: ...
    def register_provider(self, key: str, provider: Callable[[], Awaitable[str | None]]) -> None: ...
    def validate(self) -> list[str]: ...      # boot-time check
    def list_names(self) -> list[str]: ...

REGISTRY = Registry(Path(__file__).parent / "prompts.yaml")

def validate_at_boot() -> None:
    errors = REGISTRY.validate()
    if errors:
        raise RuntimeError("Prompt registry validation failed:\n  " + "\n  ".join(errors))
```

`render()` resolution order for each declared context key:
1. Explicit keyword override.
2. Registered provider (async-awaited).
3. `None` if `optional`.
4. `PromptContextError` if `required`.

### 5.3 Context providers

Live in `prompts.py` under a `# CONTEXT PROVIDERS` banner. Each is an async callable returning `str | None`. Default backend is the simplest one (usually a local file); real-backend skeleton is commented out directly below.

```python
async def user_health_context() -> str | None:
    """The user's recent health context. Local YAML by default."""
    path = Path("local_data/health.yaml")
    return path.read_text() if path.exists() else None

    # --- REAL WHOOP STREAM (uncomment to enable; comment out the block above) ---
    # from clients.whoop import WhoopClient
    # client = WhoopClient(token=os.environ["WHOOP_TOKEN"])
    # recovery = await client.get_recent_recovery()
    # workouts = await client.get_recent_workouts(days=7)
    # return f"Recovery: {recovery.score}/100. Recent workouts: {workouts.summary()}"
```

Providers used in v1:
- `assistant_name` — returns `"Claw"`. One-line edit to rename.
- `claw_persona` — reads `~/.openclaw/workspace/SOUL.md`/`USER.md`/`MEMORY.md`. Existing `_load_claw_persona` logic lifted as-is.
- `user_health_context` — reads `local_data/health.yaml`. WHOOP alternative commented out below.
- `workspace_context` — lists `workspace/*.md` with first paragraph of each.

### 5.4 Subagent / tool registry

`subagents.py` is one flat file. Top-of-file docstring lists what's inside; section banners delimit subagents, inline tools, real action tools, and simulated action tools.

```python
"""subagents.py — capabilities the voice loop can dispatch to.

Subagents (LLM-backed handlers with focused prompts + tool subsets):
  markdown_assistant, html_assistant, reasoning_assistant, workspace_update_assistant

Action tools (real side effects):
  add_todo, list_todos, complete_todo, send_telegram

Action tools (simulated — wire your own backend by replacing the handler):
  place_order, set_smart_home, post_message, send_email, place_call,
  send_money, simulate_action

Inline tools (deterministic, return-to-LLM):
  read_file, write_file, list_files, web_search,
  remember_fact, recall_fact, claw_recall, claw_remember, ask_claw
"""
```

**Registry shape** — flat dict, no dataclass:

```python
TOOLS: dict[str, dict] = {}   # assembled at module bottom

async def dispatch(name: str, args: dict, ctx) -> Any:
    return await TOOLS[name]["handler"](args=args, ctx=ctx)

def tool_schemas_for_llm() -> list[dict]:
    return [
        {"type": "function", "function": {
            "name": name,
            "description": e["description"],
            "parameters": e["parameters"],
        }}
        for name, e in TOOLS.items()
    ]
```

**Entry shape** — plain dict per entry:

```python
TOOLS = {
    "markdown_assistant": {
        "description": "Generate a markdown file in workspace/ from a task description.",
        "parameters": {
            "type": "object",
            "properties": {"task": {"type": "string"}, "filename": {"type": "string"}},
            "required": ["task", "filename"],
        },
        "handler": _markdown_handler,
        "kind": "subagent",
        "output_kind": "artifact",
        "prompt_key": "markdown_assistant",
    },
    # ... etc ...
}
```

`kind` is a human-readable label (`"inline"`, `"subagent"`, `"action"`); `output_kind` (`"string"`, `"artifact"`, `"sentinel"`) tells the voice loop how to route the result.

**Subagent handlers** fetch their prompt from the registry:

```python
async def _markdown_handler(args, ctx):
    system = await REGISTRY.render("markdown_assistant")
    resp = await ctx.qwen.complete(system=system, messages=[{"role": "user", "content": args["task"]}])
    Path(f"workspace/{args['filename']}").write_text(resp.text)
    return {"artifact": args["filename"], "summary": "markdown written"}
```

**Action handlers** (simulated) have the real-backend skeleton commented below:

```python
async def _place_order_handler(args, ctx):
    """Order an item. Logs to actions_log.jsonl by default."""
    entry = {"action": "order", "item": args["item"], "qty": args.get("quantity", 1),
             "ts": now(), "tracking": _fake_tracking_id()}
    Path("workspace/actions_log.jsonl").open("a").write(json.dumps(entry) + "\n")
    return f"Ordered {entry['qty']}× {args['item']}. Tracking: {entry['tracking']}."

    # --- REAL BACKEND (uncomment and remove the block above) ---
    # client = ShopifyClient(api_key=os.environ["SHOPIFY_KEY"])
    # result = await client.create_order(item=args["item"], quantity=args.get("quantity", 1))
    # return f"Ordered {args.get('quantity', 1)}× {args['item']}. Tracking: {result.tracking_id}."
```

**Server interaction** — `server.py` consumes the registry without knowing internals:

```python
from subagents import TOOLS, dispatch, tool_schemas_for_llm
from prompts import REGISTRY, validate_at_boot

# At app startup:
validate_at_boot()

# At session start:
tool_defs = tool_schemas_for_llm()
system_prompt = await REGISTRY.render("default_system")

# On a tool call:
result = await dispatch(call.name, call.args, ctx=self.voice_ctx)
```

The 600+-line `if tool_name == "...": elif ...` dispatch in current `server.py` collapses to the one line above.

### 5.5 Audio state machine

**`audio_session.py`** — one file, ~60 lines of production code. Single source of truth for audio session state.

```python
class State(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    PAUSED = "paused"
    HANDING_OFF = "handing_off"

class Event(Enum):
    START_LISTENING = "start_listening"
    SPEECH_ENDED = "speech_ended"
    TTS_STARTED = "tts_started"
    TTS_FINISHED = "tts_finished"
    MUTE = "mute"
    UNMUTE = "unmute"
    HANDOFF_START = "handoff_start"
    HANDOFF_COMPLETE = "handoff_complete"
    DISCONNECT = "disconnect"

TRANSITIONS: dict[tuple[State, Event], State] = {
    (State.IDLE,         Event.START_LISTENING):    State.LISTENING,
    (State.LISTENING,    Event.SPEECH_ENDED):       State.PROCESSING,
    (State.LISTENING,    Event.MUTE):               State.PAUSED,
    (State.PROCESSING,   Event.TTS_STARTED):        State.SPEAKING,
    (State.SPEAKING,     Event.TTS_FINISHED):       State.LISTENING,
    (State.SPEAKING,     Event.MUTE):               State.PAUSED,
    (State.PAUSED,       Event.UNMUTE):             State.LISTENING,
    (State.HANDING_OFF,  Event.HANDOFF_COMPLETE):   State.LISTENING,
    **{(s, Event.HANDOFF_START): State.HANDING_OFF for s in State},
    **{(s, Event.DISCONNECT):    State.IDLE        for s in State},
}

class IllegalTransitionError(Exception): pass

@dataclass
class AudioSession:
    state: State = State.IDLE
    history: list[tuple[State, Event, State]] = field(default_factory=list)

    def transition(self, event: Event) -> State:
        key = (self.state, event)
        if key not in TRANSITIONS:
            raise IllegalTransitionError(f"{event.value} from {self.state.value}")
        next_state = TRANSITIONS[key]
        self.history.append((self.state, event, next_state))
        self.state = next_state
        return next_state

    def should_capture_mic(self) -> bool:
        return self.state == State.LISTENING
```

**Invariants enforced:**
1. Mic capture gated by state, never by separate booleans (`should_capture_mic()` is the only authority).
2. `TTS_FINISHED` must land in `LISTENING` — the missed transition that causes the current bug.
3. `HANDOFF_COMPLETE` must land in `LISTENING` — never `SPEAKING` or `PROCESSING`.
4. `DISCONNECT` is universal — any state → `IDLE`.

**Server integration** — `VoiceSession` owns one `AudioSession`; every place that today reads or writes one of the scattered booleans now goes through it:

```python
# Before
if not self.is_speaking and not self.muted:
    process_audio_chunk(chunk)

# After
if self.audio.should_capture_mic():
    process_audio_chunk(chunk)
```

**Client integration** (`static/js/app.js`) — JS drops its own booleans; receives state broadcasts from server and gates behavior on them:

```javascript
ws.on("state", (msg) => { currentServerState = msg.state; });
if (currentServerState === "listening") { sendAudioChunk(chunk); }
```

**Error recovery** — `IllegalTransitionError` is recoverable on the server side, not fatal:

```python
def handle_client_event(self, event_name: str):
    try:
        new_state = self.audio.transition(Event[event_name.upper()])
        self.broadcast_state(new_state)
    except IllegalTransitionError as e:
        log.info("audio.race", current=self.audio.state.value, attempted=event_name, err=str(e))
        self.broadcast_state(self.audio.state)
```

The race between client and server during state updates (~50-100ms window over WebSocket) exists in the current system too — today it manifests as silent state corruption; with the state machine it surfaces as a logged event and a resync broadcast. The same race is also why the manual handoff gate exists — for hardware-level conditions the state machine cannot model (cellular latency spikes, Bluetooth audio device switching, etc.).

## 6. Test plan

| Layer | What it pins | Speed | Oracle |
|---|---|---|---|
| **L1** Prompt snapshots | `prompts.yaml` rendered with fixed providers produces byte-identical strings to claw HEAD | ms | committed snapshot files |
| **L2a** Registry contents | `TOOLS` contains expected names with well-formed schemas | ms | hand-listed expected set |
| **L2b** Per-handler tests | Each handler's side effect (file written, log entry, return string) is correct given canned args | ms | direct assertion |
| **L3** E2E demo-beat tests | For each demo beat: real local LLM selects the tool, invokes it, synthesizes a response. Soft-match on phrases. Audio bypassed. | seconds per beat | LLM running locally |
| **L4** Audio state machine | Every (state, event) transition + 5-test error-recovery suite | ms | property assertions |
| **Manual gate** | Real laptop↔phone handoff: audio heard, audio played, no silent drops | minutes | user |

L1 / L2a / L2b / L4 are CPU-only and run on every PR. L3 is GPU-bound (requires the local Qwen/Nemotron stack running) and runs as part of acceptance (phase 8a), not on every commit. The manual gate (phase 8b) runs after L3 passes.

### Layer 1 example

```python
@pytest.mark.parametrize("name", REGISTRY.list_names())
def test_prompt_renders_match_snapshot(name, snapshot, fixed_providers):
    fixed_providers.apply(REGISTRY)
    rendered = asyncio.run(REGISTRY.render(name))
    snapshot.assert_match(rendered, f"prompts/{name}.txt")
```

Snapshots committed under `tests/__snapshots__/prompts/<name>.txt`. PR reviewers see prompt changes as text diffs.

### Layer 2a example

```python
def test_expected_tools_registered():
    expected = {
        # subagents
        "markdown_assistant", "html_assistant", "reasoning_assistant", "workspace_update_assistant",
        # real action tools
        "add_todo", "list_todos", "complete_todo", "send_telegram",
        # simulated action tools
        "place_order", "set_smart_home", "post_message", "send_email",
        "place_call", "send_money", "simulate_action",
        # inline tools
        "read_file", "list_files", "write_file", "web_search",
        "remember_fact", "recall_fact", "claw_recall", "claw_remember", "ask_claw",
    }
    assert set(TOOLS.keys()) == expected

def test_tool_schemas_valid():
    for name, entry in TOOLS.items():
        assert "description" in entry and entry["description"]
        assert entry["parameters"]["type"] == "object"
        # ... etc — JSON Schema validation
```

### Layer 2b example

```python
def test_add_todo_appends_to_jsonl(tmp_workspace):
    asyncio.run(_add_todo_handler({"text": "buy milk"}, ctx=fake_ctx()))
    todos = read_jsonl(tmp_workspace / "todos.jsonl")
    assert todos[-1]["text"] == "buy milk"

def test_place_order_logs_action(tmp_workspace):
    result = asyncio.run(_place_order_handler({"item": "salmon", "quantity": 1}, ctx=fake_ctx()))
    assert "Ordered 1× salmon" in result
    actions = read_jsonl(tmp_workspace / "actions_log.jsonl")
    assert actions[-1]["action"] == "order"
```

### Layer 3 — E2E demo-beat tests (`tests/test_demo_beats_e2e.py`)

Modeled on the existing `bench/test_demo_prompts.py` pattern: each demo beat is sent as a user message to the real local LLM with the full prompt registry rendered and the full `TOOLS` schema attached. The test captures the LLM's tool call, runs it through `dispatch()`, feeds the result back to the LLM, captures the synthesized response, and asserts:

- The expected tool was selected (or no tool, for pure-synthesis beats).
- Tool arguments are sensible (key fields present and well-formed).
- The synthesized response contains expected phrases (soft match via `contains_any`).
- The synthesized response does NOT contain forbidden phrases (e.g., `"I can't"`, `"I don't have access"`, or private-data leaks).

Two test modes:
- **Per-beat:** each beat as its own test, fresh conversation state. Catches per-utterance regressions.
- **Sequenced:** all demo beats run as one continuous conversation, conversation state persisting. Catches "context corruption across turns" regressions.

```python
# tests/test_demo_beats_e2e.py
from dataclasses import dataclass

@dataclass
class DemoBeat:
    name: str
    prompt: str
    expected_tool: str | None
    expected_phrases: list[str]
    forbidden_phrases: list[str] = ()

DEMO_BEATS = [
    DemoBeat("intro", "Hi, can you hear me?",
             expected_tool=None,
             expected_phrases=["yes", "hear you"],
             forbidden_phrases=["I can't"]),
    DemoBeat("exec_brief", "Draft me an executive brief about Q4 plans",
             expected_tool="markdown_assistant",
             expected_phrases=["brief", "Q4"]),
    DemoBeat("order", "Order me some salmon for dinner",
             expected_tool="place_order",
             expected_phrases=["ordered", "tracking"],
             forbidden_phrases=["I can't", "I don't have"]),
    DemoBeat("smart_home", "Dim the lights to 30%",
             expected_tool="set_smart_home",
             expected_phrases=["lights", "30"]),
    DemoBeat("email", "Send an email to Sarah about the meeting tomorrow",
             expected_tool="send_email",
             expected_phrases=["sent", "Sarah"]),
    # ... one entry per demo beat ...
]

@pytest.mark.gpu
@pytest.mark.parametrize("beat", DEMO_BEATS, ids=lambda b: b.name)
def test_beat_per_beat(beat, real_llm_client):
    """Each beat runs against fresh conversation state."""
    result = run_one_turn_with_real_llm(beat.prompt, real_llm_client)
    if beat.expected_tool:
        assert result.tool_name == beat.expected_tool, f"Expected {beat.expected_tool}, got {result.tool_name}"
    assert contains_any(result.synthesis, beat.expected_phrases)
    assert not contains_any(result.synthesis, beat.forbidden_phrases)

@pytest.mark.gpu
def test_full_demo_sequence(real_llm_client):
    """All beats in one continuous conversation."""
    state = ConversationState()
    for beat in DEMO_BEATS:
        result = run_one_turn_with_real_llm(beat.prompt, real_llm_client, state=state)
        if beat.expected_tool:
            assert result.tool_name == beat.expected_tool, \
                f"At beat {beat.name!r}: expected {beat.expected_tool}, got {result.tool_name}"
        assert contains_any(result.synthesis, beat.expected_phrases), \
            f"At beat {beat.name!r}: synthesis {result.synthesis!r} missing any of {beat.expected_phrases}"
        state.append_assistant_turn(result.synthesis)
```

L3 tests are marked `@pytest.mark.gpu` so they're skippable on CPU-only CI; they run as part of acceptance (phase 8) when the local LLM stack is up.

### Layer 4 + error recovery

Every (state, event) pair in `TRANSITIONS` gets an explicit happy-path test, plus the 5-test error-recovery suite (Section D): state non-corruption, server-side recovery, repeated illegal transitions don't degrade, mobile-bug scenario recovers via `HANDOFF_COMPLETE`, and illegal transition is logged with diagnostic info.

### Manual handoff gate

Committed as `tests/manual_handoff_gate.md`. User runs through it before merging `redesign`. Any "no" answer blocks merge:

```markdown
1. Open the app in laptop browser. Start a voice call.
2. Say "hello, are you there?" — confirm response heard.
3. Open the app in phone browser. Accept the handoff offer.
4. Phone: say "what was I just asking about?" — confirm:
   - [ ] Audio sent from phone is received by server
   - [ ] Response audio plays on phone, not laptop
   - [ ] Response references the laptop utterance
5. Phone: say "draft me a markdown note about Q4" — confirm markdown_assistant fires and artifact appears.
6. Phone: say "order me some salmon" — confirm place_order fires (NOT ask_claw), response includes tracking ID, actions_log.jsonl has the entry.
7. Phone: mute, unmute, speak — confirm audio heard.
8. Hand back to laptop. Repeat step 2.
```

## 7. Phased implementation

| Phase | Scope | Commits | Approximate effort |
|---|---|---|---|
| **1** | Foundation: branch + skeleton (`pyproject.toml`, `tests/`, empty `subagents.py`, empty `audio_session.py`) | ~4 | 1 day |
| **2** | Audio state machine: write tests, implement `audio_session.py` to pass them (standalone, not yet integrated) | 2 | ½ day |
| **3** | Prompt registry: `Registry` class, `prompts.yaml` migration of all prompts, context providers, server call-site updates, deletion of `DEMO_MODE_ADDENDUM` and `_filter_for_demo` | 7 | 1-2 days |
| **4** | Mechanical agent migration: cut/paste `markdown_assistant`, `reasoning_assistant`, `html_assistant`, then refactor `workspace_update_assistant`. Per-handler test before each move. | 5 | 1 day |
| **5** | Tool additions: 6 inline tools, 4 real action tools, `ask_claw` + `claw_recall`/`claw_remember`, code-sketch absorption into `html_assistant`, 7 simulated action tools, final L2a registry-contents test | ~20 | 2-3 days |
| **6** | Server integration: `VoiceSession` uses `dispatch()`, `AudioSession` wired in, scattered booleans removed, JS updated to consume state broadcasts, `handle_client_event` error recovery | 4 | 1 day |
| **7** | Handoff: cross-device logic lifted from `claw` HEAD, routed through state machine; `local_data/` seeded | 4 | 1 day |
| **8a** | Acceptance — automated: full L1/L2a/L2b/L4 suite green; L3 E2E demo-beat tests run against the live local LLM and pass (correct tool per beat, soft-match synthesis, no forbidden phrases). Fix any failures and iterate. | — | ½-1 day |
| **8b** | Acceptance — manual: handoff gate ticked, demo storyboard run end-to-end by user with audio on real hardware | — | ½ day if it passes |
| **9** | Merge: `redesign` → `claw` | 1 | — |

**Total:** ~7-10 working days at full focus.

**Critical-path dependencies:**
- Phase 2 (audio state machine) and Phase 3 (prompt registry) are independent — parallelizable.
- Phase 4 depends on Phase 3 (handlers call `REGISTRY.render`).
- Phase 5 depends on Phase 4 (uses the same `TOOLS` dict).
- Phase 6 depends on Phases 2, 3, 4, 5 (full integration).
- Phase 7 depends on Phase 6.

**TDD ordering inside each phase:**
1. Write the test that asserts the desired behavior (recorded against `claw` HEAD where applicable).
2. Implement the change so the test passes.
3. Re-run the full suite — earlier phases' tests must still be green.

## 8. Acceptance criteria

Each is independently verifiable. All must pass before phase 9 (merge).

1. **All prompts in `prompts.yaml`.** Manual inspection of `prompts.py` and `server.py` shows no triple-quoted strings that read as assistant instructions (only module/function docstrings remain). Boot-time `validate_at_boot()` succeeds — every declared `required` context key has a registered provider, and every `{{ var }}` in a template is declared in its entry's `context` block.
2. **No `DEMO_MODE_ADDENDUM`, no `_filter_for_demo`, no `CLAW_DEMO_MODE` references** anywhere in the codebase.
3. **`TOOLS` registry has exactly the expected entries** (L2a test passes with the full enumeration in Section 6 above).
4. **All Layer 1, 2a, 2b, and 4 tests green.** Full `pytest` run completes cleanly with no skips (except `@pytest.mark.gpu` on CPU-only environments), no warnings about uncaught test conditions.
5. **Layer 3 E2E demo-beat tests pass.** Each beat: correct tool selected, soft-match synthesis assertions hold, no forbidden phrases. Sequenced full-demo test also passes.
6. **`server.py` does not contain `if tool_name ==`-style switches.** Single-line `await dispatch(...)` is the only invocation path.
7. **Audio state booleans removed.** A grep for `videoCallProcessing`, `ttsAborted`, `is_speaking`, `vad_paused` returns no matches in production code (only test fixtures may reference them historically).
8. **Manual handoff gate (`tests/manual_handoff_gate.md`) ticked completely.** Recorded by the user after running on real hardware.
9. **Demo storyboard end-to-end on the demo machine.** User runs the live demo and confirms each beat (intro, markdown brief, action tool, smart home, ordering, handoff) produces the expected behavior.
10. **No regression in voice + video + face recognition** vs. `claw` HEAD. Verified by manual call test (steps 1-2 of the gate, plus a video-call segment).
11. **Press-credibility check.** A `grep -rE 'ramen|half.marathon|executive.brief|WHOOP' prompts.yaml` returns zero results. (User-specific facts live only in `local_data/`.)

## 9. Out of scope

- MCP transport / external subagent processes.
- Hot-reload of prompts at runtime.
- Container changes (Dockerfile, `requirements-docker.txt`).
- Performance work beyond fixing the audio bug.
- Replacing or restructuring Nemotron reasoning variants.
- Splitting `clients/*` further.
- `adding_a_tool.md` documentation page (file-internal banner comments suffice).
- Per-prompt or per-tool file fragmentation (flat-file preference is intentional).
- Real-backend implementations for simulated tools (skeletons live commented-out in handlers).

## 10. Future work (post-merge review)

The following are intentionally deferred to a follow-up after this rebuild merges. Each warrants its own brainstorming and spec, and should be reviewed only once v1 has been exercised live and the audio bug is verified gone.

- **`html_assistant` writes generated code to local files.** Today's `html_assistant` (with the code-sketch capability absorbed from `codebase_assistant`) returns generated HTML as a string and writes a single artifact under `workspace/`. Expanding it into a multi-file project generator — e.g., emitting a directory tree with markers like `<<<FILE: app.py>>>...<<<END FILE>>>`, similar to the pattern used by the deleted `codebase_assistant` — is potential future work. The right shape of multi-file output depends on how the live demo audience actually uses the assistant, so this is best decided after watching the v1 demo run.
- **`run_python` tool with sandboxed execution.** Excluded from v1 due to RCE-via-LLM risk in a press-facing repo. A sandboxed version (subprocess with restricted environment, or a remote sandboxed worker) could be added behind a config flag.
- **Real-backend implementations for simulated tools.** Wiring real Shopify/Slack/Twilio/etc. APIs follows the documented in-file pattern (uncomment the alternative block, comment out the simulated handler). Doing this for any specific integration is its own scoped piece of work.
- **Performance work.** Lower-latency ASR, TTS streaming overlap with LLM generation, etc. Out of scope for this rebuild; re-evaluate after the state-machine refactor lands and the audio bug is verified gone.

---

## Appendix: Mapping current code to redesigned modules

For ease of cross-reference during the migration:

| Today (claw HEAD) | After rebuild |
|---|---|
| `prompts.py:402 DEFAULT_SYSTEM_PROMPT` | `prompts.yaml: default_system` |
| `prompts.py:437 VLM_DEFAULT_PROMPT` | `prompts.yaml: vlm_default` |
| `prompts.py:463 VIDEO_CALL_PROMPT` | `prompts.yaml: video_call` |
| `prompts.py:540 VISION_TEMPLATE_PROMPTS` (dict) | `prompts.yaml: vision_<name>` (one entry each) |
| `prompts.py:664 NEMOTRON_REASONING_PROMPT` | `prompts.yaml: reasoning` |
| `prompts.py:680 NEMOTRON_MATH_PROMPT` | `prompts.yaml: math` |
| `prompts.py:690 NEMOTRON_PLANNING_PROMPT` | `prompts.yaml: planning` |
| `prompts.py:704 NEMOTRON_ANALYSIS_PROMPT` | `prompts.yaml: analysis` |
| `prompts.py:719 NEMOTRON_PRIORITIZATION_PROMPT` | `prompts.yaml: prioritization` |
| `prompts.py:644 MARKDOWN_ASSISTANT_PROMPT` | `prompts.yaml: markdown_assistant` |
| `prompts.py:30 DEMO_MODE_ADDENDUM` | **deleted** (style folded into `default_system`; capability claims replaced by simulated tools) |
| `prompts.py:71 _load_claw_persona()` | `prompts.py: claw_persona()` provider |
| `prompts.py:102 _load_health_context()` | `prompts.py: user_health_context()` provider |
| `prompts.py:54 _maybe_demo_suffix()` | **deleted** |
| `server.py:67 _filter_for_demo` | **deleted** |
| `server.py:693 VoiceSession` | `server.py` — slimmed down, no agent handlers, uses `dispatch()` |
| `server.py:3154 execute_codebase_agent` | **deleted** (code-sketch absorbed into `html_assistant`) |
| `server.py:3119 execute_workspace_update_agent` | `subagents.py: _workspace_update_handler` (refactored) |
| `server.py:3313 execute_markdown_agent` | `subagents.py: _markdown_handler` (mechanical move) |
| `server.py:3387 execute_html_agent` | `subagents.py: _html_handler` (mechanical move + code-sketch absorption) |
| `server.py:3481 execute_reasoning_agent` | `subagents.py: _reasoning_handler` (mechanical move) |
| `tools.py: ALL_TOOLS` | `subagents.py: TOOLS` (flat dict) |
| Scattered audio booleans (`server.py` + `static/js/app.js`) | `audio_session.py: AudioSession` |
| `demo_files/` | `local_data/` (renamed; same role) |
