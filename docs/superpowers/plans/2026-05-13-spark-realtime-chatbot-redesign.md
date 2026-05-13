# Spark Realtime Chatbot Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the voice chatbot from fork-point `9ed57101` with prompt content fully decoupled from agent logic (YAML registry), redundant agents collapsed, audio state formalized as a state machine, and demo-mode prompt-rigging removed — preserving every demo capability through honest simulated-action tools with real-backend hooks. `claw` HEAD remains the behavioral oracle until `redesign` reaches parity and replaces it.

**Architecture:** Flat-file structure at repo root — `prompts.yaml` (templates as data) + `prompts.py` (loader + context providers) + `subagents.py` (one dict of all tool handlers, sectioned) + `audio_session.py` (runtime state machine) + `server.py` (voice loop, dispatch-only). Tests in `tests/` organized by layer: L1 prompt snapshots, L2a registry contents, L2b per-handler, L3 E2E demo beats (GPU-gated), L4 state-machine invariants. Spec lives at `docs/superpowers/specs/2026-05-13-spark-realtime-chatbot-redesign-design.md`.

**Tech Stack:** Python 3.11, FastAPI, faster-whisper (ASR), Kokoro TTS, Qwen3.6 / Qwen3-VL / Nemotron via OpenAI-compatible local server, Jinja2 (prompt templates), PyYAML (registry), pytest + syrupy (snapshot tests), Silero VAD (browser-side), WebSocket transport.

**Pre-flight checks:**
- `claw` branch is checked out and contains the latest features (the oracle).
- `9ed57101` is the merge-base with `main` (the rebuild starting point).
- Local Qwen/Nemotron stack runs on `http://localhost:11434/v1` for L3 tests in phase 8a.

---

## Phase 1: Foundation

### Task 1.1: Cut `redesign` branch from fork-point

**Files:**
- No file changes — branch operation only.

- [ ] **Step 1: Verify clean working tree on `claw`**

Run: `git status`
Expected: Working tree shows unrelated modifications and untracked files but no staged changes from this work. If staged work exists, stash it before proceeding: `git stash push -m "pre-redesign-branch"`.

- [ ] **Step 2: Create and check out `redesign` branch from fork-point**

Run: `git checkout -b redesign 9ed57101c9ac2ec55b03b1f6515cab7f011f1b43`
Expected: Output like `Switched to a new branch 'redesign'`.

- [ ] **Step 3: Confirm state**

Run: `git log --oneline -5`
Expected: Shows commits ending at `9ed57101` (single commit or fork-point's history).

Run: `ls -la prompts.py server.py tools.py audio.py 2>&1 | head -5`
Expected: All four files exist (fork-point layout).

- [ ] **Step 4: Push the new branch to origin (optional but recommended)**

Run: `git push -u origin redesign`
Expected: New branch published.

---

### Task 1.2: Add pytest infrastructure

**Files:**
- Modify: `requirements.txt` — add test deps
- Create: `tests/__init__.py`
- Create: `pytest.ini`

- [ ] **Step 1: Add test dependencies to `requirements.txt`**

Append to `requirements.txt`:

```
pytest>=8.0.0
pytest-asyncio>=0.23.0
syrupy>=4.6.0
jinja2>=3.1.0
```

- [ ] **Step 2: Install them**

Run: `pip install pytest pytest-asyncio syrupy jinja2`
Expected: Successfully installs (or "already satisfied").

- [ ] **Step 3: Create `tests/__init__.py`**

Create empty file: `tests/__init__.py` (zero bytes).

- [ ] **Step 4: Create `pytest.ini`**

```ini
[pytest]
testpaths = tests
asyncio_mode = auto
markers =
    gpu: tests requiring the local LLM stack (skipped on CPU-only environments)
addopts = -ra --strict-markers
```

- [ ] **Step 5: Verify pytest invokes cleanly**

Run: `pytest --collect-only 2>&1 | tail -5`
Expected: "no tests ran" or "collected 0 items" — no errors about config.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt tests/__init__.py pytest.ini
git commit -m "[chore] add pytest infrastructure"
```

---

### Task 1.3: Create `tests/conftest.py` with shared fixtures

**Files:**
- Create: `tests/conftest.py`

- [ ] **Step 1: Write `tests/conftest.py`**

```python
"""Shared fixtures for the redesign test suite."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest


@pytest.fixture
def tmp_workspace(tmp_path, monkeypatch):
    """Isolate workspace/ writes into a per-test temp directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)
    return workspace


@dataclass
class FakeLLMResult:
    text: str = ""
    tool_calls: list[dict] = None

    def __post_init__(self):
        if self.tool_calls is None:
            self.tool_calls = []


class FakeLLMClient:
    """In-memory LLM stub. Set `next_response` before each call you want to control."""
    def __init__(self):
        self.next_response: FakeLLMResult = FakeLLMResult(text="ok")
        self.calls: list[dict] = []

    async def complete(self, *, system=None, messages=None, **kwargs):
        self.calls.append({"system": system, "messages": messages, **kwargs})
        return self.next_response


@dataclass
class FakeVoiceContext:
    qwen: FakeLLMClient
    nemotron: FakeLLMClient


@pytest.fixture
def fake_ctx() -> FakeVoiceContext:
    """Minimal VoiceContext stub with stubbed LLM clients."""
    return FakeVoiceContext(qwen=FakeLLMClient(), nemotron=FakeLLMClient())


@pytest.fixture
def fixed_providers() -> dict[str, Any]:
    """Frozen values for prompt-registry tests. Substitutes for real providers."""
    return {
        "assistant_name": "Claw",
        "claw_persona": "<FROZEN_PERSONA>",
        "user_health_context": "<FROZEN_HEALTH>",
        "workspace_context": "<FROZEN_WORKSPACE>",
    }


def read_jsonl(path: Path) -> list[dict]:
    """Test helper: read a JSONL file written by an action handler."""
    import json
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
```

- [ ] **Step 2: Verify the fixtures load**

Run: `pytest --collect-only 2>&1 | tail -3`
Expected: No errors. Empty test run is fine.

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "[chore] add shared pytest fixtures"
```

---

### Task 1.4: Add empty `subagents.py` skeleton

**Files:**
- Create: `subagents.py`

- [ ] **Step 1: Write `subagents.py` skeleton**

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
from __future__ import annotations

from typing import Any


# ============================================================
# REGISTRY
# ============================================================
# Single dict of name → entry. Dispatch and schema generation read from it.

TOOLS: dict[str, dict] = {}   # populated at the bottom of this file


async def dispatch(name: str, args: dict, ctx) -> Any:
    """Invoke a registered tool by name. Uniform path for inline / subagent / action tools."""
    return await TOOLS[name]["handler"](args=args, ctx=ctx)


def tool_schemas_for_llm() -> list[dict]:
    """Convert TOOLS into OpenAI-compatible tool definitions for the voice LLM."""
    return [
        {"type": "function", "function": {
            "name": name,
            "description": e["description"],
            "parameters": e["parameters"],
        }}
        for name, e in TOOLS.items()
    ]


# ============================================================
# SUBAGENTS  (added in Phase 4)
# ============================================================

# ============================================================
# INLINE TOOLS  (added in Phase 5.1)
# ============================================================

# ============================================================
# REAL ACTION TOOLS  (added in Phase 5.2)
# ============================================================

# ============================================================
# SIMULATED ACTION TOOLS
# ============================================================
# These tools demonstrate the *kinds* of integrations Spark can drive.
# Each has a real schema and a working handler that logs to
# workspace/actions_log.jsonl and returns a believable confirmation.
# To wire your own backend, replace the body of the handler with a real
# API call — the schema, registry entry, and call site stay the same.
# (Added in Phase 5.6.)


# ============================================================
# REGISTRY ASSEMBLY
# ============================================================
# Read this block to see what's wired up. Each tool entry: name → {
#   "description": str, "parameters": JSON Schema,
#   "handler": async callable, "kind": "inline"|"subagent"|"action",
#   "output_kind": "string"|"artifact"|"sentinel",
#   "prompt_key": str | None,
# }

TOOLS.update({
    # populated by subsequent phases
})
```

- [ ] **Step 2: Verify it imports**

Run: `python -c "import subagents; print(list(subagents.TOOLS.keys()))"`
Expected: `[]`

- [ ] **Step 3: Commit**

```bash
git add subagents.py
git commit -m "[feat] add empty subagents.py skeleton with registry + dispatch"
```

---

### Task 1.5: Add empty `audio_session.py` skeleton

**Files:**
- Create: `audio_session.py`

- [ ] **Step 1: Write `audio_session.py` skeleton**

```python
"""audio_session.py — runtime audio state machine.

One source of truth for audio session state. Every audio-related event
(VAD-start, TTS-playing, mute, handoff, disconnect) flows through
transition(event). Replaces the scattered booleans in server.py and
static/js/app.js whose drift caused the mobile-handoff audio bug.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


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


class IllegalTransitionError(Exception):
    """Raised when an event arrives in a state that has no defined transition for it."""


# Filled in during Phase 2
TRANSITIONS: dict[tuple[State, Event], State] = {}


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

- [ ] **Step 2: Verify it imports**

Run: `python -c "from audio_session import AudioSession, State, Event; s = AudioSession(); print(s.state)"`
Expected: `State.IDLE`

- [ ] **Step 3: Commit**

```bash
git add audio_session.py
git commit -m "[feat] add empty audio_session.py skeleton"
```

End of Phase 1: green CI baseline, no real tests yet. All four skeletons in place.

---

## Phase 2: Audio State Machine

### Task 2.1: Write Layer 4 tests for the state machine

**Files:**
- Create: `tests/test_audio_state.py`

- [ ] **Step 1: Write the complete test file**

```python
"""Layer 4 — audio state machine + error recovery."""
from __future__ import annotations

import pytest

from audio_session import AudioSession, Event, IllegalTransitionError, State


# -------- Happy-path transitions --------

def test_normal_voice_turn():
    s = AudioSession()
    s.transition(Event.START_LISTENING)
    s.transition(Event.SPEECH_ENDED)
    s.transition(Event.TTS_STARTED)
    s.transition(Event.TTS_FINISHED)
    assert s.state == State.LISTENING
    assert s.should_capture_mic()


def test_mute_during_listening():
    s = AudioSession()
    s.transition(Event.START_LISTENING)
    s.transition(Event.MUTE)
    assert s.state == State.PAUSED
    assert not s.should_capture_mic()
    s.transition(Event.UNMUTE)
    assert s.state == State.LISTENING


def test_mute_during_speaking():
    s = AudioSession()
    s.transition(Event.START_LISTENING)
    s.transition(Event.SPEECH_ENDED)
    s.transition(Event.TTS_STARTED)
    s.transition(Event.MUTE)
    assert s.state == State.PAUSED


def test_disconnect_is_universal():
    for state in State:
        s = AudioSession()
        s.state = state
        s.transition(Event.DISCONNECT)
        assert s.state == State.IDLE


def test_handoff_from_any_state():
    for state in [State.IDLE, State.LISTENING, State.SPEAKING, State.PAUSED]:
        s = AudioSession()
        s.state = state
        s.transition(Event.HANDOFF_START)
        assert s.state == State.HANDING_OFF


def test_handoff_complete_lands_in_listening():
    s = AudioSession()
    s.transition(Event.START_LISTENING)
    s.transition(Event.HANDOFF_START)
    s.transition(Event.HANDOFF_COMPLETE)
    assert s.state == State.LISTENING
    assert s.should_capture_mic()


def test_mobile_bug_scenario_resolves_via_handoff():
    """Regression for commits 4b05bec, fc7b689, ef83723: handoff during TTS."""
    s = AudioSession()
    s.transition(Event.START_LISTENING)
    s.transition(Event.SPEECH_ENDED)
    s.transition(Event.TTS_STARTED)
    s.transition(Event.HANDOFF_START)
    s.transition(Event.HANDOFF_COMPLETE)
    assert s.state == State.LISTENING
    assert s.should_capture_mic()


# -------- Error recovery --------

def test_illegal_transition_does_not_corrupt_state():
    s = AudioSession()
    s.transition(Event.START_LISTENING)
    s.transition(Event.SPEECH_ENDED)
    # State is Processing — SPEECH_ENDED again is illegal
    with pytest.raises(IllegalTransitionError):
        s.transition(Event.SPEECH_ENDED)
    assert s.state == State.PROCESSING
    # Normal flow continues:
    s.transition(Event.TTS_STARTED)
    s.transition(Event.TTS_FINISHED)
    assert s.state == State.LISTENING


def test_tts_finished_from_handing_off_is_illegal():
    s = AudioSession()
    s.transition(Event.START_LISTENING)
    s.transition(Event.SPEECH_ENDED)
    s.transition(Event.TTS_STARTED)
    s.transition(Event.HANDOFF_START)
    with pytest.raises(IllegalTransitionError):
        s.transition(Event.TTS_FINISHED)
    assert s.state == State.HANDING_OFF


def test_history_records_transitions():
    s = AudioSession()
    s.transition(Event.START_LISTENING)
    s.transition(Event.SPEECH_ENDED)
    assert s.history == [
        (State.IDLE, Event.START_LISTENING, State.LISTENING),
        (State.LISTENING, Event.SPEECH_ENDED, State.PROCESSING),
    ]


# -------- should_capture_mic invariant --------

def test_mic_only_captures_in_listening():
    s = AudioSession()
    for state in State:
        s.state = state
        assert s.should_capture_mic() == (state == State.LISTENING)
```

- [ ] **Step 2: Run to confirm they fail (TRANSITIONS is empty)**

Run: `pytest tests/test_audio_state.py -v 2>&1 | tail -20`
Expected: Multiple `FAILED` lines — `IllegalTransitionError: start_listening from idle`. This is correct: tests are red because `TRANSITIONS` is `{}`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_audio_state.py
git commit -m "[test] add failing L4 audio state machine tests"
```

---

### Task 2.2: Populate `TRANSITIONS` to make tests pass

**Files:**
- Modify: `audio_session.py` — fill in `TRANSITIONS`

- [ ] **Step 1: Replace the empty `TRANSITIONS = {}` with the full transition table**

In `audio_session.py`, replace:

```python
# Filled in during Phase 2
TRANSITIONS: dict[tuple[State, Event], State] = {}
```

with:

```python
TRANSITIONS: dict[tuple[State, Event], State] = {
    (State.IDLE,         Event.START_LISTENING):  State.LISTENING,
    (State.LISTENING,    Event.SPEECH_ENDED):     State.PROCESSING,
    (State.LISTENING,    Event.MUTE):             State.PAUSED,
    (State.PROCESSING,   Event.TTS_STARTED):      State.SPEAKING,
    (State.SPEAKING,     Event.TTS_FINISHED):     State.LISTENING,
    (State.SPEAKING,     Event.MUTE):             State.PAUSED,
    (State.PAUSED,       Event.UNMUTE):           State.LISTENING,
    (State.HANDING_OFF,  Event.HANDOFF_COMPLETE): State.LISTENING,
    # HANDOFF_START from any state:
    **{(s, Event.HANDOFF_START): State.HANDING_OFF for s in State},
    # DISCONNECT from any state:
    **{(s, Event.DISCONNECT): State.IDLE for s in State},
}
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/test_audio_state.py -v 2>&1 | tail -20`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add audio_session.py
git commit -m "[feat] implement audio state machine TRANSITIONS table"
```

End of Phase 2: standalone audio state machine + tests green. Not yet integrated into `server.py` (that's phase 6).

---

## Phase 3: Prompt Registry

### Task 3.1: Write `Registry` class + boot validation

**Files:**
- Modify: `prompts.py` — replace contents
- Create: `prompts.yaml` — empty for now

The fork-point's `prompts.py` will be entirely replaced. Save the current content for reference during migration (you'll need to pull individual prompt strings from it in later tasks).

- [ ] **Step 1: Save the fork-point `prompts.py` for reference**

Run: `cp prompts.py /tmp/prompts_forkpoint.py`

- [ ] **Step 2: Replace `prompts.py` with the loader + provider scaffolding**

Write `prompts.py` (full replacement):

```python
"""prompts.py — prompt registry loader and context providers.

This module loads prompts.yaml and renders templates with values from the
context providers defined below. Providers are the only code that knows
where dynamic content (persona, health, workspace files) actually comes from.
YAML stays content-agnostic; swap a provider's implementation here to wire a
different data source without touching any template.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml
from jinja2 import Environment, StrictUndefined, meta


class PromptContextError(Exception):
    """Raised when a required context key has no provider or override."""


class Registry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._templates: dict[str, dict] = {}
        self._providers: dict[str, Callable[[], Awaitable[str | None]]] = {}
        self._env = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
        self._load()

    def _load(self) -> None:
        data = yaml.safe_load(self.path.read_text()) or {}
        for name, entry in data.items():
            template_str = entry["template"]
            self._templates[name] = {
                "context_decl": entry.get("context") or {},
                "template": self._env.from_string(template_str),
                "template_source": template_str,
                "description": entry.get("description", ""),
            }

    def register_provider(self, key: str, provider: Callable[[], Awaitable[str | None]]) -> None:
        self._providers[key] = provider

    async def render(self, name: str, **overrides) -> str:
        entry = self._templates[name]
        context: dict[str, Any] = {}
        for key, kind in entry["context_decl"].items():
            if key in overrides:
                context[key] = overrides[key]
            elif key in self._providers:
                context[key] = await self._providers[key]()
            elif kind == "optional":
                context[key] = None
            else:
                raise PromptContextError(f"missing required context {key!r} for prompt {name!r}")
        return entry["template"].render(**context)

    def list_names(self) -> list[str]:
        return sorted(self._templates.keys())

    def validate(self) -> list[str]:
        """Boot check: every required context key has a provider, and every
        {{ var }} in a template is declared in its entry's context block."""
        errors: list[str] = []
        for name, entry in self._templates.items():
            declared = set(entry["context_decl"].keys())
            ast = self._env.parse(entry["template_source"])
            referenced = meta.find_undeclared_variables(ast)
            for ref in referenced - declared:
                errors.append(f"{name}: template references {{ {ref} }} not declared in context")
            for key, kind in entry["context_decl"].items():
                if kind == "required" and key not in self._providers:
                    errors.append(f"{name}: required context {key!r} has no registered provider")
        return errors


REGISTRY = Registry(Path(__file__).parent / "prompts.yaml")


def validate_at_boot() -> None:
    """Called by server.py at startup. Fails fast with the full error list."""
    errors = REGISTRY.validate()
    if errors:
        raise RuntimeError("Prompt registry validation failed:\n  " + "\n  ".join(errors))


# ============================================================
# CONTEXT PROVIDERS
# ============================================================
# Each provider is an async callable returning str | None.
# Edit a provider's body to swap data sources without touching any template.
# (Added in Task 3.5.)
```

- [ ] **Step 3: Create empty `prompts.yaml`**

Write `prompts.yaml`:

```yaml
# prompts.yaml — prompt templates as data, separate from the loader code.
#
# Each entry declares which context placeholders ({{ var }}) the template uses.
# The actual content for those placeholders is sourced by provider functions
# in prompts.py — this file never mentions specific data sources (files, APIs).
# Edit here to change what a prompt says; edit prompts.py to change where its
# dynamic content comes from.
```

- [ ] **Step 4: Verify imports**

Run: `python -c "from prompts import REGISTRY; print(REGISTRY.list_names())"`
Expected: `[]`

- [ ] **Step 5: Commit**

```bash
git add prompts.py prompts.yaml
git commit -m "[refactor] replace prompts.py with Registry loader + empty prompts.yaml"
```

Note: the server is broken after this commit because `server.py` still imports `DEFAULT_SYSTEM_PROMPT` etc. from `prompts.py`. That's intentional — the next tasks restore parity. Don't try to run the server until phase 3 is done.

---

### Task 3.2: Write L1 prompt snapshot test skeleton

**Files:**
- Create: `tests/test_prompts.py`

- [ ] **Step 1: Write the test file**

```python
"""Layer 1 — prompt registry snapshots."""
from __future__ import annotations

import asyncio

import pytest

from prompts import REGISTRY


def _apply_fixed_providers(fixed_providers: dict) -> None:
    """Substitute frozen values for the providers so snapshots are deterministic."""
    for key, value in fixed_providers.items():
        async def make_provider(v=value):
            return v
        REGISTRY.register_provider(key, make_provider)


@pytest.mark.parametrize("name", REGISTRY.list_names())
def test_prompt_renders_match_snapshot(name, snapshot, fixed_providers):
    _apply_fixed_providers(fixed_providers)
    rendered = asyncio.run(REGISTRY.render(name))
    assert rendered == snapshot
```

- [ ] **Step 2: Run — should collect 0 tests because registry is empty**

Run: `pytest tests/test_prompts.py -v 2>&1 | tail -5`
Expected: "no tests ran" or similar.

- [ ] **Step 3: Commit**

```bash
git add tests/test_prompts.py
git commit -m "[test] add L1 prompt snapshot test skeleton"
```

---

### Task 3.3: Migrate base prompts (`default_system`, `video_call`, `vlm_default`) to YAML

**Files:**
- Modify: `prompts.yaml` — add three entries
- Reference: `/tmp/prompts_forkpoint.py` (the fork-point's prompts), and `git show claw:prompts.py` for the claw HEAD's final content

For each prompt, you migrate the **claw HEAD** version (the oracle) into a Jinja2 template. The persona/health hardcoded sentences are replaced by `{{ placeholder }}` blocks.

- [ ] **Step 1: Read claw HEAD's `DEFAULT_SYSTEM_PROMPT` for reference**

Run: `git show claw:prompts.py | sed -n '395,440p'`
This shows lines 395-440 of `prompts.py` on claw HEAD — the `DEFAULT_SYSTEM_PROMPT` block.

- [ ] **Step 2: Add `default_system` entry to `prompts.yaml`**

Append to `prompts.yaml`:

```yaml
default_system:
  description: Main voice/text mode system prompt used by VoiceSession at session start.
  context:
    assistant_name: required
    claw_persona: optional
    workspace_context: optional
  template: |
    You are {{ assistant_name }}, a fast, concise, voice-first assistant
    running fully on NVIDIA DGX Spark.

    You must always respond in short, natural spoken sentences (1–2 sentences max).
    Never ramble. Never add extra detail unless the user explicitly asks.
    Use tool calls when necessary to help the user.

    Behavior rules:
    - Default to 1–2 short spoken sentences.
    - No lists or bullet points in your replies unless the user specifically asks.
    - Do NOT use any special formatting, asterisks, brackets, or stage directions.
    - Do NOT explain your reasoning or mention that you are an AI model.
    - Be direct and confident — don't hedge unnecessarily.
    - Keep answers minimal and on-topic.

    Style: calm, direct, a little playful. Prioritize brevity.
    {%- if claw_persona %}

    {{ claw_persona }}
    {%- endif %}
    {%- if workspace_context %}

    Current workspace files:
    {{ workspace_context }}
    {%- endif %}
```

- [ ] **Step 3: Add `video_call` entry to `prompts.yaml`**

Append:

```yaml
video_call:
  description: Video-call mode (vision-enabled). Very brief responses.
  context:
    user_health_context: optional
    claw_persona: optional
  template: |
    You are on a live video call. You can see the user.

    RULES:
    - Answer ONLY the specific question asked.
    - Do NOT describe the scene unless explicitly asked.
    - Do NOT mention things the user didn't ask about.
    - Keep responses brief and natural (spoken aloud via TTS).
    - If user says "okay", "thanks", "got it" — just acknowledge briefly.

    Be a helpful friend on a video call, not a surveillance camera.
    {%- if user_health_context %}

    Recent health context from the user's local data:
    {{ user_health_context }}
    {%- endif %}
    {%- if claw_persona %}

    {{ claw_persona }}
    {%- endif %}
```

- [ ] **Step 4: Add `vlm_default` entry to `prompts.yaml`**

Append:

```yaml
vlm_default:
  description: Default vision-language-model prompt for one-shot image questions.
  context: {}
  template: |
    Look at the image. Answer ONLY what the user explicitly asks.
    Do NOT describe the scene unprompted. Keep responses to 1–2 sentences.
```

- [ ] **Step 5: Capture L1 snapshots (initial run creates them)**

Run: `pytest tests/test_prompts.py -v --snapshot-update 2>&1 | tail -10`
Expected: 3 tests PASS, snapshots created under `tests/__snapshots__/`.

- [ ] **Step 6: Run again without `--snapshot-update` to confirm stability**

Run: `pytest tests/test_prompts.py -v 2>&1 | tail -10`
Expected: 3 tests PASS, no diffs.

- [ ] **Step 7: Commit**

```bash
git add prompts.yaml tests/__snapshots__/
git commit -m "[refactor] migrate default_system, video_call, vlm_default prompts to YAML"
```

---

### Task 3.4: Migrate Nemotron and vision-template prompts to YAML

**Files:**
- Modify: `prompts.yaml`

- [ ] **Step 1: View claw HEAD's Nemotron prompts**

Run: `git show claw:prompts.py | sed -n '660,735p'`

- [ ] **Step 2: Append five Nemotron entries to `prompts.yaml`**

```yaml
reasoning:
  description: Default Nemotron reasoning variant — direct but constructive.
  context: {}
  template: |
    You are a trusted advisor. Direct but constructive.
    Your responses will be SPOKEN ALOUD via TTS — no markdown or lists.
    Aim for 2–3 sentences max.

math:
  description: Nemotron math reasoning variant.
  context: {}
  template: |
    You are an expert mathematics assistant. Your responses will be
    SPOKEN ALOUD via TTS, so avoid notation that doesn't read aloud well.
    Show the answer clearly in 1–2 spoken sentences.

planning:
  description: Nemotron planning reasoning variant.
  context: {}
  template: |
    Trusted planning advisor. Direct but constructive. SPOKEN ALOUD.
    Lay out the plan in 2–3 sentences a person could repeat.

analysis:
  description: Nemotron analysis reasoning variant.
  context: {}
  template: |
    Trusted analyst. Direct but constructive. SPOKEN ALOUD.
    Cut through to the conclusion in 2–3 sentences.

prioritization:
  description: Nemotron prioritization reasoning variant.
  context: {}
  template: |
    Trusted prioritization advisor. SPOKEN ALOUD.
    Pick the top item and say why in 2 sentences.
```

- [ ] **Step 3: View claw HEAD's vision template prompts**

Run: `git show claw:prompts.py | sed -n '535,640p'`

- [ ] **Step 4: Append four vision-template entries to `prompts.yaml`**

```yaml
vision_whiteboard:
  description: Vision template for whiteboard content (handwritten tasks/notes).
  context: {}
  template: |
    Look at the whiteboard. Read the user's handwriting.
    If you see a task list, summarize the tasks in 1–2 sentences.
    Otherwise answer the user's explicit question.

vision_face:
  description: Vision template for face/portrait shots.
  context: {}
  template: |
    Answer only the user's explicit question about the person in the frame.
    Do not describe their appearance unless asked.

vision_scene:
  description: Vision template for general scene descriptions.
  context: {}
  template: |
    Answer only what the user explicitly asks about the scene.
    Keep responses to 1–2 sentences.

vision_menu:
  description: Vision template for menus / printed text.
  context: {}
  template: |
    Read the menu/printed text in the image.
    Translate or summarize only what the user explicitly asks for.
    Keep responses to 1–2 sentences.
```

- [ ] **Step 5: Update snapshots and verify**

Run: `pytest tests/test_prompts.py -v --snapshot-update 2>&1 | tail -10`
Expected: 12 tests PASS (3 from task 3.3 + 5 Nemotron + 4 vision).

Run: `pytest tests/test_prompts.py -v 2>&1 | tail -10`
Expected: 12 tests PASS, no diffs.

- [ ] **Step 6: Commit**

```bash
git add prompts.yaml tests/__snapshots__/
git commit -m "[refactor] migrate Nemotron + vision-template prompts to YAML"
```

---

### Task 3.5: Migrate subagent system prompts to YAML

**Files:**
- Modify: `prompts.yaml`

- [ ] **Step 1: View claw HEAD's markdown / html / reasoning / workspace_update agent prompts**

Run: `git show claw:prompts.py | sed -n '640,700p'`
Run: `git show claw:server.py | grep -n 'execute_html_agent\|execute_workspace_update_agent' | head -5`

The markdown agent prompt is in `prompts.py:644` on claw HEAD. The html and workspace_update prompts may be defined inline inside their `execute_*_agent` methods on claw HEAD — read those methods on claw to find the actual system-prompt strings.

- [ ] **Step 2: Append subagent entries to `prompts.yaml`**

Use the prompt strings you found in step 1. If a subagent's prompt is defined inline inside the agent function, pull the string verbatim into the YAML entry.

```yaml
markdown_assistant:
  description: System prompt for the markdown_assistant subagent — produces markdown artifacts.
  context: {}
  template: |
    You are a documentation assistant. Create well-structured markdown
    that's readable as plain text. Use headers (#), lists, and clear
    sectioning. No preamble — start with the heading. Keep it focused
    on what was asked.

html_assistant:
  description: System prompt for the html_assistant subagent — produces HTML pages or sketches.
  context: {}
  template: |
    You are an HTML assistant. Produce a single self-contained HTML file.
    Inline CSS in <style>. Inline JS in <script>. No external dependencies.
    Start with <!DOCTYPE html>. Keep it focused on what was asked.

reasoning_assistant:
  description: System prompt for the reasoning_assistant subagent — Nemotron-backed analysis.
  context: {}
  template: |
    You are a trusted advisor. Analyze the problem given.
    Be direct, structured, and concise. Output will be summarized
    back to the user via TTS, so keep your final answer short and clear.

workspace_update_assistant:
  description: System prompt for the workspace_update_assistant subagent — refreshes workspace files.
  context: {}
  template: |
    You are a workspace update assistant. Given a request and a target
    markdown file, produce the updated file's contents. Preserve existing
    structure where possible. Output only the file contents, no preamble.
```

- [ ] **Step 3: Update snapshots and verify**

Run: `pytest tests/test_prompts.py -v --snapshot-update 2>&1 | tail -10`
Expected: 16 tests PASS (12 + 4 subagents).

Run: `pytest tests/test_prompts.py -v 2>&1 | tail -10`
Expected: 16 tests PASS, no diffs.

- [ ] **Step 4: Commit**

```bash
git add prompts.yaml tests/__snapshots__/
git commit -m "[refactor] migrate subagent system prompts to YAML"
```

---

### Task 3.6: Add context providers

**Files:**
- Modify: `prompts.py` — append providers under the `# CONTEXT PROVIDERS` banner

- [ ] **Step 1: View claw HEAD's `_load_claw_persona` for reference**

Run: `git show claw:prompts.py | sed -n '64,105p'`

- [ ] **Step 2: Append the four providers + their registrations to `prompts.py`**

Add after the `# CONTEXT PROVIDERS` banner (use the existing `_load_claw_persona` body — lift its logic):

```python
async def assistant_name() -> str:
    """The voice assistant's display name. Rename here for your deployment."""
    return "Claw"


async def claw_persona() -> str | None:
    """Reads ~/.openclaw/workspace/SOUL.md, USER.md, MEMORY.md.

    Returns None if persona injection is disabled or files are absent.
    """
    if os.environ.get("CLAW_INJECT_PERSONA", "1").lower() in ("0", "false", "no", "off"):
        return None
    workspace = Path(os.environ.get("OPENCLAW_WORKSPACE", os.path.expanduser("~/.openclaw/workspace")))
    persona_files = ("SOUL.md", "USER.md", "MEMORY.md")
    max_bytes = 16 * 1024
    chunks: list[str] = []
    for name in persona_files:
        path = workspace / name
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if len(text) > max_bytes:
            text = text[:max_bytes] + "\n…(truncated)"
        chunks.append(f"\n----- {name} -----\n{text.strip()}")
    if not chunks:
        return None
    return (
        "\n\n# Claw's persistent memory & identity (read-only context)\n"
        "These are your shared memory with the OpenClaw agent on this machine. "
        "Treat them as facts you already know about yourself and the user. "
        "Don't read them out loud verbatim — apply them in your replies."
        + "".join(chunks)
    )


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


async def workspace_context() -> str | None:
    """List workspace/*.md files with their first paragraph each."""
    workspace = Path("workspace")
    if not workspace.exists():
        return None
    sections: list[str] = []
    for md in sorted(workspace.glob("*.md")):
        text = md.read_text(encoding="utf-8").strip()
        first_para = text.split("\n\n", 1)[0]
        if len(first_para) > 200:
            first_para = first_para[:200] + "…"
        sections.append(f"- {md.name}: {first_para}")
    return "\n".join(sections) if sections else None


REGISTRY.register_provider("assistant_name", assistant_name)
REGISTRY.register_provider("claw_persona", claw_persona)
REGISTRY.register_provider("user_health_context", user_health_context)
REGISTRY.register_provider("workspace_context", workspace_context)
```

- [ ] **Step 3: Verify validate_at_boot succeeds**

Run: `python -c "from prompts import validate_at_boot; validate_at_boot(); print('ok')"`
Expected: `ok`

- [ ] **Step 4: L1 snapshots are now rendered with real providers — re-run to capture**

Run: `pytest tests/test_prompts.py -v --snapshot-update 2>&1 | tail -10`
Expected: 16 PASS, snapshots updated (real providers are replaced by `fixed_providers` in tests, so snapshots are unchanged in value — but the test now executes the provider machinery).

Run: `pytest tests/test_prompts.py -v 2>&1 | tail -5`
Expected: 16 PASS.

- [ ] **Step 5: Commit**

```bash
git add prompts.py tests/__snapshots__/
git commit -m "[feat] add context providers with simulated/real backend pattern"
```

---

### Task 3.7: Wire `validate_at_boot()` into `server.py` startup

**Files:**
- Modify: `server.py` — call `validate_at_boot()` during app startup; remove dead `prompts` imports

- [ ] **Step 1: Find the app lifespan / startup hook on fork-point `server.py`**

Run: `grep -n 'lifespan\|@app.on_event\|startup' server.py | head -5`
Identify the startup section (usually near the top of the file, a `@asynccontextmanager` lifespan function).

- [ ] **Step 2: Add `validate_at_boot()` call**

Inside the startup section (before `yield`), add:

```python
from prompts import validate_at_boot
validate_at_boot()
```

If the function doesn't already exist (fork-point may use `@app.on_event("startup")`), use:

```python
from prompts import validate_at_boot

@app.on_event("startup")
async def _validate_prompts():
    validate_at_boot()
```

- [ ] **Step 3: Remove broken imports from `server.py`**

Run: `grep -n 'from prompts import\|import prompts' server.py`
Replace any `from prompts import DEFAULT_SYSTEM_PROMPT` etc. with `from prompts import REGISTRY, validate_at_boot`. The constant references will be fixed in later phases as we touch each call site.

For now, comment out any *use* of the old constants with a marker:

```python
# TODO(phase-3.7-followup): replace with REGISTRY.render(...)
# system_prompt = DEFAULT_SYSTEM_PROMPT
system_prompt = ""  # placeholder until call sites are updated
```

Note this leaves the server runnable but broken. Phase 6 fixes the call sites properly.

- [ ] **Step 4: Verify the module imports and `validate_at_boot` runs**

Run: `python -c "import server; print('import-ok')" 2>&1 | tail -3`
Expected: Either `import-ok` or some other server-side import error unrelated to the prompts module.

- [ ] **Step 5: Commit**

```bash
git add server.py
git commit -m "[refactor] wire validate_at_boot into server startup; mark prompt call sites for phase 6"
```

End of Phase 3: every prompt lives in `prompts.yaml`. `prompts.py` is loader + providers. Demo-mode rigging removed (note: `DEMO_MODE_ADDENDUM`, `_filter_for_demo` were on claw HEAD only; fork-point doesn't have them, so they're not yet in `server.py` on this branch — we won't add them back).

---

## Phase 4: Mechanical Agent Migration

Each task: write the L2b test first; cut the agent method from `server.py` (fork-point version — it's simpler than claw HEAD's) into a handler in `subagents.py`; register; verify the test passes. **No internal refactor.**

### Task 4.1: Migrate `markdown_assistant`

**Files:**
- Create: `tests/test_subagent_handlers.py`
- Modify: `subagents.py` — add `_markdown_handler` and TOOLS entry
- Modify: `server.py` — delete `execute_markdown_agent` method

- [ ] **Step 1: Write the failing test**

Create `tests/test_subagent_handlers.py`:

```python
"""Layer 2b — subagent handler unit tests."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


def test_markdown_handler_writes_artifact(tmp_workspace, fake_ctx, monkeypatch):
    """markdown_assistant invokes the LLM, writes the artifact, returns a summary."""
    from subagents import TOOLS

    fake_ctx.qwen.next_response.text = "# Q4 Plans\n\nGrow revenue. Ship the demo."

    handler = TOOLS["markdown_assistant"]["handler"]
    result = asyncio.run(handler(
        args={"task": "draft Q4 plans", "filename": "q4.md"},
        ctx=fake_ctx,
    ))

    assert (tmp_workspace / "q4.md").exists()
    content = (tmp_workspace / "q4.md").read_text()
    assert "Q4 Plans" in content
    assert result.get("artifact") == "q4.md"
```

- [ ] **Step 2: Run — should fail because TOOLS doesn't have markdown_assistant**

Run: `pytest tests/test_subagent_handlers.py::test_markdown_handler_writes_artifact -v 2>&1 | tail -5`
Expected: `KeyError: 'markdown_assistant'`

- [ ] **Step 3: Read fork-point `execute_markdown_agent` for the handler logic**

Run: `git show 9ed57101:server.py | grep -n 'execute_markdown_agent' | head -3`
Run: `git show 9ed57101:server.py | sed -n '<found-line>,<found-line+40>p'` (replace with the line numbers from the previous command)

- [ ] **Step 4: Add `_markdown_handler` to `subagents.py`**

Under the `# SUBAGENTS` banner in `subagents.py`, add:

```python
async def _markdown_handler(args, ctx):
    """Generate a markdown artifact from a task description."""
    from prompts import REGISTRY
    from pathlib import Path

    system = await REGISTRY.render("markdown_assistant")
    resp = await ctx.qwen.complete(
        system=system,
        messages=[{"role": "user", "content": args["task"]}],
        max_tokens=2000,
    )
    out = Path("workspace") / args["filename"]
    out.parent.mkdir(exist_ok=True)
    out.write_text(resp.text)
    return {"artifact": args["filename"], "summary": "markdown written"}
```

Then add the registry entry inside the `TOOLS.update({...})` block at the bottom of `subagents.py`:

```python
TOOLS.update({
    "markdown_assistant": {
        "description": "Generate a markdown file in workspace/ from a task description.",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "What the markdown should be about"},
                "filename": {"type": "string", "description": "Filename in workspace/, e.g. notes.md"},
            },
            "required": ["task", "filename"],
        },
        "handler": _markdown_handler,
        "kind": "subagent",
        "output_kind": "artifact",
        "prompt_key": "markdown_assistant",
    },
})
```

- [ ] **Step 5: Run the test**

Run: `pytest tests/test_subagent_handlers.py::test_markdown_handler_writes_artifact -v 2>&1 | tail -5`
Expected: PASS.

- [ ] **Step 6: Delete `execute_markdown_agent` from `server.py`**

Find the method definition in `server.py` and delete it. Also delete any associated dispatch case (e.g., `elif tool_name == "markdown_assistant":`).

Run: `grep -n 'execute_markdown_agent\|markdown_assistant' server.py`
Verify only registry-using references remain (or no references — phase 6 wires the new dispatch).

- [ ] **Step 7: Re-run all tests**

Run: `pytest -v 2>&1 | tail -20`
Expected: All tests pass; existing audio tests + this new markdown test.

- [ ] **Step 8: Commit**

```bash
git add subagents.py tests/test_subagent_handlers.py server.py
git commit -m "[refactor] move markdown_assistant from server.py to subagents.py"
```

---

### Task 4.2: Migrate `html_assistant`

**Files:**
- Modify: `tests/test_subagent_handlers.py` — add html test
- Modify: `subagents.py` — add `_html_handler` + TOOLS entry
- Modify: `server.py` — delete `execute_html_agent`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_subagent_handlers.py`:

```python
def test_html_handler_writes_artifact(tmp_workspace, fake_ctx):
    from subagents import TOOLS

    fake_ctx.qwen.next_response.text = "<!DOCTYPE html><html><body>Hello</body></html>"

    handler = TOOLS["html_assistant"]["handler"]
    result = asyncio.run(handler(
        args={"task": "simple hello page", "filename": "hello.html"},
        ctx=fake_ctx,
    ))

    assert (tmp_workspace / "hello.html").exists()
    assert "<html>" in (tmp_workspace / "hello.html").read_text()
    assert result.get("artifact") == "hello.html"
```

- [ ] **Step 2: Verify it fails**

Run: `pytest tests/test_subagent_handlers.py::test_html_handler_writes_artifact -v 2>&1 | tail -3`
Expected: `KeyError: 'html_assistant'`

- [ ] **Step 3: Read fork-point's `execute_html_agent`** (if present) or claw HEAD's (the audit says html_assistant existed at fork-point; if not, lift from claw HEAD)

Run: `git show 9ed57101:server.py | grep -n 'execute_html_agent\|html_assistant'`
If not found at fork-point: `git show claw:server.py | grep -n 'execute_html_agent' | head -3`

- [ ] **Step 4: Add `_html_handler` to `subagents.py`**

Under `# SUBAGENTS`:

```python
async def _html_handler(args, ctx):
    """Generate an HTML artifact from a task description."""
    from prompts import REGISTRY
    from pathlib import Path

    system = await REGISTRY.render("html_assistant")
    resp = await ctx.qwen.complete(
        system=system,
        messages=[{"role": "user", "content": args["task"]}],
        max_tokens=4000,
    )
    out = Path("workspace") / args["filename"]
    out.parent.mkdir(exist_ok=True)
    out.write_text(resp.text)
    return {"artifact": args["filename"], "summary": "html written"}
```

Add registry entry:

```python
TOOLS["html_assistant"] = {
    "description": "Generate a single-file HTML page in workspace/ from a task description.",
    "parameters": {
        "type": "object",
        "properties": {
            "task": {"type": "string"},
            "filename": {"type": "string", "description": "Filename in workspace/, e.g. page.html"},
        },
        "required": ["task", "filename"],
    },
    "handler": _html_handler,
    "kind": "subagent",
    "output_kind": "artifact",
    "prompt_key": "html_assistant",
}
```

- [ ] **Step 5: Run test, verify pass**

Run: `pytest tests/test_subagent_handlers.py::test_html_handler_writes_artifact -v 2>&1 | tail -3`
Expected: PASS.

- [ ] **Step 6: Delete `execute_html_agent` from `server.py`**

- [ ] **Step 7: Commit**

```bash
git add subagents.py tests/test_subagent_handlers.py server.py
git commit -m "[refactor] move html_assistant from server.py to subagents.py"
```

---

### Task 4.3: Migrate `reasoning_assistant`

**Files:**
- Modify: `tests/test_subagent_handlers.py`
- Modify: `subagents.py`
- Modify: `server.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_subagent_handlers.py`:

```python
def test_reasoning_handler_returns_synthesis(fake_ctx):
    from subagents import TOOLS

    fake_ctx.nemotron.next_response.text = "The top priority is reliability."

    handler = TOOLS["reasoning_assistant"]["handler"]
    result = asyncio.run(handler(
        args={"problem": "what should we focus on", "analysis_type": "prioritization"},
        ctx=fake_ctx,
    ))

    assert "reliability" in result["text"]
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/test_subagent_handlers.py::test_reasoning_handler_returns_synthesis -v 2>&1 | tail -3`

- [ ] **Step 3: Add `_reasoning_handler` to `subagents.py`**

```python
async def _reasoning_handler(args, ctx):
    """Nemotron-backed reasoning. analysis_type picks the prompt variant."""
    from prompts import REGISTRY

    analysis_type = args.get("analysis_type", "reasoning")
    valid = {"reasoning", "math", "planning", "analysis", "prioritization"}
    prompt_key = analysis_type if analysis_type in valid else "reasoning"

    system = await REGISTRY.render(prompt_key)
    resp = await ctx.nemotron.complete(
        system=system,
        messages=[{"role": "user", "content": args["problem"]}],
        max_tokens=600,
    )
    return {"text": resp.text}
```

Add registry entry:

```python
TOOLS["reasoning_assistant"] = {
    "description": "Nemotron-backed reasoning. Choose analysis_type from: reasoning, math, planning, analysis, prioritization.",
    "parameters": {
        "type": "object",
        "properties": {
            "problem": {"type": "string"},
            "analysis_type": {"type": "string", "enum": ["reasoning", "math", "planning", "analysis", "prioritization"]},
        },
        "required": ["problem"],
    },
    "handler": _reasoning_handler,
    "kind": "subagent",
    "output_kind": "string",
    "prompt_key": "reasoning",
}
```

- [ ] **Step 4: Pass + delete fork-point method**

Run: `pytest tests/test_subagent_handlers.py::test_reasoning_handler_returns_synthesis -v 2>&1 | tail -3`
Expected: PASS.

Delete `execute_reasoning_agent` from `server.py`.

- [ ] **Step 5: Commit**

```bash
git add subagents.py tests/test_subagent_handlers.py server.py
git commit -m "[refactor] move reasoning_assistant from server.py to subagents.py"
```

---

### Task 4.4: Migrate + refactor `workspace_update_assistant`

This is the one refactored agent. Test pins observable behavior; internals can be cleaned up.

**Files:**
- Modify: `tests/test_subagent_handlers.py`
- Modify: `subagents.py`
- Modify: `server.py`

- [ ] **Step 1: Write the failing test pinning observable behavior**

Append to `tests/test_subagent_handlers.py`:

```python
def test_workspace_update_handler_writes_target_file(tmp_workspace, fake_ctx):
    from subagents import TOOLS

    # Seed an existing file
    (tmp_workspace / "personal_todos.md").write_text("# Todos\n- old item")
    fake_ctx.qwen.next_response.text = "# Todos\n- old item\n- buy milk"

    handler = TOOLS["workspace_update_assistant"]["handler"]
    result = asyncio.run(handler(
        args={"target_file": "personal_todos.md", "items": ["buy milk"]},
        ctx=fake_ctx,
    ))

    updated = (tmp_workspace / "personal_todos.md").read_text()
    assert "buy milk" in updated
    assert result.get("artifact") == "personal_todos.md"
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/test_subagent_handlers.py::test_workspace_update_handler_writes_target_file -v 2>&1 | tail -3`

- [ ] **Step 3: Add `_workspace_update_handler` with cleaned-up internals**

```python
async def _workspace_update_handler(args, ctx):
    """Update a workspace file based on a list of new items.

    Pulls existing content, prompts the LLM to merge in new items, writes back.
    """
    from prompts import REGISTRY
    from pathlib import Path

    target = Path("workspace") / args["target_file"]
    target.parent.mkdir(exist_ok=True)
    existing = target.read_text() if target.exists() else ""
    items_str = "\n".join(f"- {item}" for item in args.get("items", []))

    user_msg = f"Existing file content:\n\n{existing}\n\nAdd these items:\n{items_str}\n\nReturn the full updated file."
    system = await REGISTRY.render("workspace_update_assistant")
    resp = await ctx.qwen.complete(system=system, messages=[{"role": "user", "content": user_msg}], max_tokens=2000)

    target.write_text(resp.text)
    return {"artifact": args["target_file"], "summary": "workspace file updated"}
```

Add registry entry:

```python
TOOLS["workspace_update_assistant"] = {
    "description": "Update a markdown file in workspace/ with a list of new items.",
    "parameters": {
        "type": "object",
        "properties": {
            "target_file": {"type": "string", "description": "Filename in workspace/, e.g. personal_todos.md"},
            "items": {"type": "array", "items": {"type": "string"}, "description": "Items to merge into the file"},
        },
        "required": ["target_file", "items"],
    },
    "handler": _workspace_update_handler,
    "kind": "subagent",
    "output_kind": "artifact",
    "prompt_key": "workspace_update_assistant",
}
```

- [ ] **Step 4: Pass + delete fork-point method**

Run: `pytest tests/test_subagent_handlers.py::test_workspace_update_handler_writes_target_file -v 2>&1 | tail -3`
Expected: PASS.

Delete `execute_workspace_update_agent` from `server.py`.

- [ ] **Step 5: Commit**

```bash
git add subagents.py tests/test_subagent_handlers.py server.py
git commit -m "[refactor] move + refactor workspace_update_assistant"
```

End of Phase 4: 4 subagents in `subagents.py`. `server.py` ~400 lines lighter.

---

## Phase 5: Tool Additions

### Task 5.1: Add inline tools (one task per tool; pattern shown for `read_file`, repeat for others)

For each inline tool: write the test, run-it-fails, add handler, register, run-it-passes, commit.

**Files (per tool):**
- Modify: `tests/test_inline_handlers.py`
- Modify: `subagents.py` — handler + TOOLS entry

#### 5.1.1: `read_file`

- [ ] **Step 1: Create `tests/test_inline_handlers.py` with first test**

```python
"""Layer 2b — inline tool unit tests."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


def test_read_file_returns_contents(tmp_workspace, fake_ctx):
    from subagents import TOOLS

    (tmp_workspace / "notes.md").write_text("# Notes\n\nHello world.")

    handler = TOOLS["read_file"]["handler"]
    result = asyncio.run(handler(args={"path": "workspace/notes.md"}, ctx=fake_ctx))
    assert "Hello world" in result
```

- [ ] **Step 2: Verify fails (KeyError)**

Run: `pytest tests/test_inline_handlers.py -v 2>&1 | tail -3`

- [ ] **Step 3: Add `_read_file_handler` under `# INLINE TOOLS` banner**

```python
async def _read_file_handler(args, ctx):
    """Read a file's contents and return as a string. Restricted to workspace/."""
    from pathlib import Path
    path = Path(args["path"])
    if not str(path.resolve()).startswith(str(Path("workspace").resolve())):
        return f"Error: path {args['path']!r} is outside workspace/"
    if not path.exists():
        return f"Error: file {args['path']!r} not found"
    return path.read_text()
```

Add to `TOOLS`:

```python
TOOLS["read_file"] = {
    "description": "Read the contents of a file in workspace/ and return as text.",
    "parameters": {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Path under workspace/"}},
        "required": ["path"],
    },
    "handler": _read_file_handler,
    "kind": "inline",
    "output_kind": "string",
}
```

- [ ] **Step 4: Run + pass**

Run: `pytest tests/test_inline_handlers.py::test_read_file_returns_contents -v 2>&1 | tail -3`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add subagents.py tests/test_inline_handlers.py
git commit -m "[feat] add read_file inline tool"
```

#### 5.1.2 – 5.1.6: Apply the same TDD pattern for each remaining inline tool

For each tool, repeat: test → fail → handler + entry → pass → commit. Use these handlers (each is ~10-25 lines):

**`list_files`** — handler lists `workspace/**/*` files; test seeds two files and asserts both appear in the result string.

```python
async def _list_files_handler(args, ctx):
    from pathlib import Path
    root = Path("workspace")
    if not root.exists():
        return "(workspace empty)"
    names = sorted(str(p.relative_to(Path("."))) for p in root.rglob("*") if p.is_file())
    return "\n".join(names) if names else "(workspace empty)"

TOOLS["list_files"] = {
    "description": "List all files under workspace/.",
    "parameters": {"type": "object", "properties": {}, "required": []},
    "handler": _list_files_handler, "kind": "inline", "output_kind": "string",
}
```

**`write_file`** — handler writes a string to a workspace path; test asserts file exists with right content.

```python
async def _write_file_handler(args, ctx):
    from pathlib import Path
    path = Path(args["path"])
    if not str(path.resolve()).startswith(str(Path("workspace").resolve())):
        return f"Error: path {args['path']!r} is outside workspace/"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args["content"])
    return f"Wrote {len(args['content'])} chars to {args['path']}"

TOOLS["write_file"] = {
    "description": "Write a string to a file in workspace/. Creates parent directories.",
    "parameters": {"type": "object",
                   "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                   "required": ["path", "content"]},
    "handler": _write_file_handler, "kind": "inline", "output_kind": "string",
}
```

**`web_search`** — lift from claw HEAD. Run `git show claw:tools.py | grep -n web_search` to find the implementation; copy verbatim into `subagents.py`. Test mocks the HTTP call with `monkeypatch` and asserts a results string is returned.

**`remember_fact`** — writes a JSONL entry to `workspace/facts.jsonl`. Test asserts the file has the new entry.

```python
async def _remember_fact_handler(args, ctx):
    import json
    from pathlib import Path
    from datetime import datetime
    entry = {"fact": args["fact"], "ts": datetime.utcnow().isoformat()}
    p = Path("workspace/facts.jsonl")
    p.parent.mkdir(exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return f"Remembered: {args['fact']}"

TOOLS["remember_fact"] = {
    "description": "Save a fact for later recall.",
    "parameters": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]},
    "handler": _remember_fact_handler, "kind": "inline", "output_kind": "string",
}
```

**`recall_fact`** — reads `workspace/facts.jsonl`, filters by substring. Test seeds two facts, recalls one.

```python
async def _recall_fact_handler(args, ctx):
    import json
    from pathlib import Path
    p = Path("workspace/facts.jsonl")
    if not p.exists():
        return "(no facts remembered)"
    q = args.get("query", "").lower()
    matching = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if not q or q in entry["fact"].lower():
            matching.append(entry["fact"])
    return "\n".join(matching) if matching else "(no matching facts)"

TOOLS["recall_fact"] = {
    "description": "Recall remembered facts matching a query substring.",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": []},
    "handler": _recall_fact_handler, "kind": "inline", "output_kind": "string",
}
```

After each tool: test added → handler + TOOLS entry → `pytest tests/test_inline_handlers.py -v` passes → commit with message `[feat] add <toolname> inline tool`.

---

### Task 5.2: Add real action tools (lift from claw HEAD)

For each: test → handler (lifted from claw HEAD) → commit.

#### 5.2.1: `add_todo`

- [ ] **Step 1: Create `tests/test_action_handlers.py` with first test**

```python
"""Layer 2b — action tool unit tests."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


def test_add_todo_appends_to_jsonl(tmp_workspace, fake_ctx):
    from subagents import TOOLS

    handler = TOOLS["add_todo"]["handler"]
    asyncio.run(handler(args={"text": "buy milk"}, ctx=fake_ctx))

    p = tmp_workspace / "todos.jsonl"
    assert p.exists()
    entries = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    assert entries[-1]["text"] == "buy milk"
    assert entries[-1]["done"] is False
```

- [ ] **Step 2: Run test fail**

Run: `pytest tests/test_action_handlers.py -v 2>&1 | tail -3`

- [ ] **Step 3: Add `_add_todo_handler` under `# REAL ACTION TOOLS` banner**

```python
async def _add_todo_handler(args, ctx):
    """Append a todo to workspace/todos.jsonl."""
    import json
    from datetime import datetime
    from pathlib import Path
    entry = {"text": args["text"], "ts": datetime.utcnow().isoformat(), "done": False}
    p = Path("workspace/todos.jsonl")
    p.parent.mkdir(exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return f"Added: {args['text']}"

TOOLS["add_todo"] = {
    "description": "Add a todo item to the user's list.",
    "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    "handler": _add_todo_handler, "kind": "action", "output_kind": "string",
}
```

- [ ] **Step 4: Pass + commit**

```bash
git add subagents.py tests/test_action_handlers.py
git commit -m "[feat] add add_todo real action tool"
```

#### 5.2.2: `list_todos`, `complete_todo`, `send_telegram`

Same TDD pattern. Code stubs:

```python
async def _list_todos_handler(args, ctx):
    import json
    from pathlib import Path
    p = Path("workspace/todos.jsonl")
    if not p.exists():
        return "(no todos)"
    entries = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    pending = [e for e in entries if not e["done"]]
    if not pending:
        return "(no pending todos)"
    return "\n".join(f"- {e['text']}" for e in pending)

TOOLS["list_todos"] = {
    "description": "List the user's pending todo items.",
    "parameters": {"type": "object", "properties": {}, "required": []},
    "handler": _list_todos_handler, "kind": "action", "output_kind": "string",
}
```

```python
async def _complete_todo_handler(args, ctx):
    import json
    from pathlib import Path
    p = Path("workspace/todos.jsonl")
    if not p.exists():
        return "(no todos)"
    text_match = args["text"].lower()
    entries = []
    completed = None
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if not e["done"] and text_match in e["text"].lower() and completed is None:
            e["done"] = True
            completed = e["text"]
        entries.append(e)
    with p.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return f"Completed: {completed}" if completed else f"No pending todo matched: {args['text']!r}"

TOOLS["complete_todo"] = {
    "description": "Mark a pending todo as done by matching its text.",
    "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    "handler": _complete_todo_handler, "kind": "action", "output_kind": "string",
}
```

For **`send_telegram`** — lift from `claw` HEAD:
```bash
git show claw:tools.py | grep -n 'send_telegram' | head -3
```
Copy the function body verbatim into `subagents.py`. Test: mock `requests.post` and assert the call was made.

Each: test → handler → pass → commit.

---

### Task 5.3: Add Claw integration tools (`ask_claw`, `claw_recall`, `claw_remember`)

**Files:**
- Modify: `tests/test_action_handlers.py`
- Modify: `subagents.py`

These thin wrappers delegate to `clients/claw_acp.py` (already on `claw` HEAD; copy it onto `redesign` if not present).

- [ ] **Step 1: Ensure `clients/claw_acp.py` exists on `redesign`**

Run: `ls clients/claw_acp.py 2>&1`
If missing: `git show claw:clients/claw_acp.py > clients/claw_acp.py && git add clients/claw_acp.py`

- [ ] **Step 2: Write the test**

Append to `tests/test_action_handlers.py`:

```python
def test_ask_claw_delegates_to_client(monkeypatch, fake_ctx):
    from subagents import TOOLS

    async def fake_query(q):
        return f"answer-to: {q}"

    monkeypatch.setattr("clients.claw_acp.query", fake_query)

    handler = TOOLS["ask_claw"]["handler"]
    result = asyncio.run(handler(args={"query": "what is q4 plan"}, ctx=fake_ctx))
    assert "answer-to: what is q4 plan" in result
```

- [ ] **Step 3: Add handlers under `# INLINE TOOLS` banner (ask_claw is information-fetch, not side-effect)**

```python
async def _ask_claw_handler(args, ctx):
    """Delegate an information question to the OpenClaw agent via clients/claw_acp.py."""
    from clients.claw_acp import query
    return await query(args["query"])

TOOLS["ask_claw"] = {
    "description": "Ask the OpenClaw agent (slower, more capable). Use for information lookups, NOT actions.",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    "handler": _ask_claw_handler, "kind": "inline", "output_kind": "string",
}

async def _claw_recall_handler(args, ctx):
    """Retrieve a stored fact from Claw's memory."""
    from clients.claw_acp import recall
    return await recall(args["key"])

TOOLS["claw_recall"] = {
    "description": "Recall a fact previously stored via claw_remember.",
    "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
    "handler": _claw_recall_handler, "kind": "inline", "output_kind": "string",
}

async def _claw_remember_handler(args, ctx):
    """Store a fact in Claw's memory."""
    from clients.claw_acp import remember
    await remember(args["key"], args["value"])
    return f"Remembered: {args['key']}"

TOOLS["claw_remember"] = {
    "description": "Store a fact in Claw's persistent memory under a key.",
    "parameters": {"type": "object",
                   "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
                   "required": ["key", "value"]},
    "handler": _claw_remember_handler, "kind": "action", "output_kind": "string",
}
```

- [ ] **Step 4: Pass + commit**

Run: `pytest tests/test_action_handlers.py -v 2>&1 | tail -3`
Expected: All pass.

```bash
git add subagents.py clients/claw_acp.py tests/test_action_handlers.py
git commit -m "[feat] add ask_claw / claw_recall / claw_remember Claw-integration tools"
```

---

### Task 5.4: Absorb code-sketch into `html_assistant`

**Files:**
- Modify: `prompts.yaml` — extend `html_assistant` template
- Modify: `tests/__snapshots__/prompts/html_assistant.txt`
- Modify: `tests/test_subagent_handlers.py` — add code-sketch test

- [ ] **Step 1: Update `html_assistant` prompt to handle both pages AND code sketches**

Edit `prompts.yaml`, replace the `html_assistant` entry's `template` with:

```yaml
html_assistant:
  description: System prompt for the html_assistant subagent — produces HTML pages or code sketches.
  context: {}
  template: |
    You are an HTML / code-sketch assistant. Given a task, produce either:
    (a) a single self-contained HTML file (inline CSS in <style>, inline JS
        in <script>, no external dependencies, starting with <!DOCTYPE html>), or
    (b) a code sketch — a brief, working snippet in the requested language,
        wrapped in a complete HTML page that displays the code and a
        rendered demo if applicable.

    Pick (a) for "make a page / website / dashboard" asks. Pick (b) for
    "sketch a script / write code that does X" asks. Either way, the
    output is a single complete HTML file. Keep it focused.
```

- [ ] **Step 2: Update snapshot**

Run: `pytest tests/test_prompts.py -v --snapshot-update 2>&1 | tail -3`

- [ ] **Step 3: Write code-sketch test**

Append to `tests/test_subagent_handlers.py`:

```python
def test_html_handler_handles_code_sketch(tmp_workspace, fake_ctx):
    from subagents import TOOLS

    fake_ctx.qwen.next_response.text = (
        "<!DOCTYPE html><html><body><pre>def hello(): print('hi')</pre>"
        "<button onclick=\"alert('hi')\">run</button></body></html>"
    )
    handler = TOOLS["html_assistant"]["handler"]
    result = asyncio.run(handler(
        args={"task": "sketch a python hello function", "filename": "hello_sketch.html"},
        ctx=fake_ctx,
    ))

    content = (tmp_workspace / "hello_sketch.html").read_text()
    assert "<pre>" in content
    assert "hello" in content
    assert result["artifact"] == "hello_sketch.html"
```

- [ ] **Step 4: Pass + commit**

Run: `pytest tests/test_subagent_handlers.py -v 2>&1 | tail -5`
Expected: all pass.

```bash
git add prompts.yaml tests/__snapshots__/prompts/html_assistant.txt tests/test_subagent_handlers.py
git commit -m "[feat] absorb code-sketch capability into html_assistant"
```

---

### Task 5.5: Add simulated action tools (pattern shown for `place_order`; repeat for the rest)

Each simulated tool has: simulated handler at top of function, commented-out real-backend skeleton below.

#### 5.5.1: `place_order`

- [ ] **Step 1: Write test**

Append to `tests/test_action_handlers.py`:

```python
def test_place_order_logs_action(tmp_workspace, fake_ctx):
    from subagents import TOOLS

    handler = TOOLS["place_order"]["handler"]
    result = asyncio.run(handler(args={"item": "salmon", "quantity": 1}, ctx=fake_ctx))

    assert "Ordered 1× salmon" in result
    assert "Tracking:" in result

    log = tmp_workspace / "actions_log.jsonl"
    assert log.exists()
    entries = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    assert entries[-1]["action"] == "order"
    assert entries[-1]["item"] == "salmon"
    assert entries[-1]["qty"] == 1
```

- [ ] **Step 2: Add `_place_order_handler` under `# SIMULATED ACTION TOOLS` banner**

```python
def _fake_tracking_id() -> str:
    import secrets
    return secrets.token_hex(3).upper()


def _log_action(entry: dict) -> None:
    import json
    from datetime import datetime
    from pathlib import Path
    entry = {**entry, "ts": datetime.utcnow().isoformat()}
    p = Path("workspace/actions_log.jsonl")
    p.parent.mkdir(exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(entry) + "\n")


async def _place_order_handler(args, ctx):
    """Order an item. Logs to actions_log.jsonl by default."""
    qty = args.get("quantity", 1)
    tracking = _fake_tracking_id()
    _log_action({"action": "order", "item": args["item"], "qty": qty, "tracking": tracking})
    return f"Ordered {qty}× {args['item']}. Tracking: {tracking}."

    # --- REAL BACKEND (uncomment and remove the block above) ---
    # client = ShopifyClient(api_key=os.environ["SHOPIFY_KEY"])
    # result = await client.create_order(item=args["item"], quantity=args.get("quantity", 1))
    # return f"Ordered {args.get('quantity', 1)}× {args['item']}. Tracking: {result.tracking_id}."

TOOLS["place_order"] = {
    "description": "Place an order for an item (food, products, deliveries, services, bookings).",
    "parameters": {"type": "object",
                   "properties": {"item": {"type": "string"}, "quantity": {"type": "integer"}},
                   "required": ["item"]},
    "handler": _place_order_handler, "kind": "action", "output_kind": "string",
}
```

- [ ] **Step 3: Pass + commit**

Run: `pytest tests/test_action_handlers.py::test_place_order_logs_action -v 2>&1 | tail -3`
Expected: PASS.

```bash
git add subagents.py tests/test_action_handlers.py
git commit -m "[feat] add place_order simulated action tool"
```

#### 5.5.2 – 5.5.7: Same pattern for remaining six tools

For each (test, handler, commit):

**`set_smart_home`** — args `{device, state}`. Log action `{action: "smart_home", device, state}`. Return `"Set {device} to {state}."`.

**`post_message`** — args `{channel, content}`. Log `{action: "message", channel, content_preview: content[:80]}`. Return `"Posted to #{channel}."`.

**`send_email`** — args `{to, subject, body}`. Log `{action: "email", to, subject}`. Return `"Sent email to {to}: {subject}."`.

**`place_call`** — args `{contact}`. Log `{action: "call", contact}`. Return `"Calling {contact}…"`.

**`send_money`** — args `{recipient, amount}`. Log `{action: "payment", recipient, amount}`. Return `"Sent ${amount} to {recipient}."`.

**`simulate_action`** — args `{domain, description}`. Log `{action: "generic", domain, description}`. Return `"Done — logged as {domain} action."`. This is the catch-all.

Each tool's full handler follows the `_place_order_handler` structure with its own `--- REAL BACKEND ---` commented section. Each tool's test is shaped like `test_place_order_logs_action`.

After all six: commit each separately or batch them under `[feat] add remaining simulated action tools`. One commit per tool is cleaner for review.

---

### Task 5.6: Add L2a registry-contents test

**Files:**
- Create: `tests/test_tool_registry.py`

- [ ] **Step 1: Write the test**

```python
"""Layer 2a — registry contents + schema validity."""
from __future__ import annotations

import pytest

from subagents import TOOLS


EXPECTED_TOOLS = {
    # subagents
    "markdown_assistant", "html_assistant", "reasoning_assistant", "workspace_update_assistant",
    # inline tools
    "read_file", "list_files", "write_file", "web_search",
    "remember_fact", "recall_fact",
    "ask_claw", "claw_recall", "claw_remember",
    # real action tools
    "add_todo", "list_todos", "complete_todo", "send_telegram",
    # simulated action tools
    "place_order", "set_smart_home", "post_message", "send_email",
    "place_call", "send_money", "simulate_action",
}


def test_expected_tools_registered():
    assert set(TOOLS.keys()) == EXPECTED_TOOLS, (
        f"Missing: {EXPECTED_TOOLS - set(TOOLS.keys())} ; "
        f"Extra: {set(TOOLS.keys()) - EXPECTED_TOOLS}"
    )


def test_every_tool_has_required_fields():
    required = {"description", "parameters", "handler", "kind", "output_kind"}
    for name, entry in TOOLS.items():
        missing = required - set(entry.keys())
        assert not missing, f"{name}: missing fields {missing}"


def test_every_tool_parameters_is_valid_json_schema_object():
    for name, entry in TOOLS.items():
        p = entry["parameters"]
        assert p["type"] == "object", f"{name}: parameters.type must be 'object'"
        assert "properties" in p, f"{name}: parameters.properties missing"
        for prop_name, prop_def in p["properties"].items():
            assert "type" in prop_def, f"{name}.{prop_name}: type missing"


def test_kind_is_one_of_three_values():
    valid = {"inline", "subagent", "action"}
    for name, entry in TOOLS.items():
        assert entry["kind"] in valid, f"{name}: kind {entry['kind']!r} not in {valid}"


def test_subagents_have_prompt_key():
    for name, entry in TOOLS.items():
        if entry["kind"] == "subagent":
            assert "prompt_key" in entry, f"{name}: subagent needs prompt_key"
```

- [ ] **Step 2: Run + fix any drift**

Run: `pytest tests/test_tool_registry.py -v 2>&1 | tail -10`
Expected: all 5 tests PASS. If `test_expected_tools_registered` fails, the diff message tells you what's missing or extra — fix `EXPECTED_TOOLS` or the `TOOLS` dict.

- [ ] **Step 3: Commit**

```bash
git add tests/test_tool_registry.py
git commit -m "[test] add L2a registry-contents and schema tests"
```

End of Phase 5: full registry assembled. ~25 tools across 4 categories in one flat file. All tests green.

---

## Phase 6: Server Integration

### Task 6.1: Replace `server.py` tool-dispatch switch with `dispatch()`

**Files:**
- Modify: `server.py` — find the `if tool_name ==` block and replace

- [ ] **Step 1: Find the dispatch switch**

Run: `grep -n 'if tool_name ==\|elif tool_name ==' server.py | head -5`

- [ ] **Step 2: Replace with single-line dispatch**

Find the function/method that handles tool calls (usually inside `VoiceSession`'s LLM-response handling). Replace the `if/elif` switch with:

```python
from subagents import dispatch, tool_schemas_for_llm

# ... inside the tool-call handler:
result = await dispatch(call.name, call.args, ctx=self.voice_ctx)
```

And replace the hand-rolled tool list (`ALL_TOOLS`) lookup with:

```python
tool_defs = tool_schemas_for_llm()
```

- [ ] **Step 3: Add a small smoke test**

Append to `tests/test_tool_registry.py`:

```python
def test_dispatch_invokes_correct_handler(fake_ctx, tmp_workspace):
    """Smoke test: dispatching by name routes to the right handler."""
    import asyncio
    from subagents import dispatch

    asyncio.run(dispatch("add_todo", {"text": "smoke test todo"}, ctx=fake_ctx))
    todos = (tmp_workspace / "todos.jsonl").read_text()
    assert "smoke test todo" in todos
```

- [ ] **Step 4: Run all tests**

Run: `pytest -v 2>&1 | tail -15`
Expected: all tests green.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_tool_registry.py
git commit -m "[refactor] replace server.py tool dispatch switch with dispatch() call"
```

---

### Task 6.2: Wire `AudioSession` into `VoiceSession`

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Add import and field**

In `server.py`, in the `VoiceSession` class definition, add:

```python
from audio_session import AudioSession, Event, IllegalTransitionError
```

In `VoiceSession.__init__`:

```python
self.audio = AudioSession()
```

- [ ] **Step 2: Replace scattered booleans**

Find each boolean and update:

| Old code | New code |
|---|---|
| `self.is_speaking = False` | (delete) |
| `self.ttsAborted = False` | (delete) |
| `self.muted = False` | (delete) |
| `self.vad_paused = False` | (delete) |
| `if not self.is_speaking and not self.muted:` | `if self.audio.should_capture_mic():` |
| `self.is_speaking = True` | `self.audio.transition(Event.TTS_STARTED)` |
| `self.is_speaking = False` | `self.audio.transition(Event.TTS_FINISHED)` |
| `self.muted = True` | `self.audio.transition(Event.MUTE)` |
| `self.muted = False` | `self.audio.transition(Event.UNMUTE)` |

Hunt each one down with `grep -n 'is_speaking\|ttsAborted\|self\.muted\|vad_paused' server.py` and substitute.

- [ ] **Step 3: Add `handle_client_event` with error recovery**

Add a new method on `VoiceSession`:

```python
async def handle_client_event(self, event_name: str) -> None:
    """Convert a client-side event name into an AudioSession transition.

    Recovers from IllegalTransitionError by logging and re-broadcasting state.
    """
    try:
        event = Event[event_name.upper()]
    except KeyError:
        return  # unknown event name — ignore silently for forward-compat
    try:
        new_state = self.audio.transition(event)
        await self.broadcast_state(new_state)
    except IllegalTransitionError as e:
        # Race: client emitted based on stale state. Re-broadcast actual.
        # (replace with your project's logger; here we use print to keep deps minimal)
        print(f"audio.race current={self.audio.state.value} attempted={event_name} err={e}")
        await self.broadcast_state(self.audio.state)
```

And a `broadcast_state` method:

```python
async def broadcast_state(self, state) -> None:
    """Send the current audio state to the connected client."""
    if self.websocket:
        await self.websocket.send_json({"type": "state", "state": state.value})
```

- [ ] **Step 4: Add an error-recovery test**

Append to `tests/test_audio_state.py`:

```python
def test_server_recovers_from_stale_client_event(monkeypatch):
    """VoiceSession-style handler catches IllegalTransitionError and resyncs."""
    import asyncio
    from audio_session import AudioSession, Event, IllegalTransitionError, State

    class FakeSession:
        def __init__(self):
            self.audio = AudioSession()
            self.broadcasts: list = []
            self.logs: list = []

        async def broadcast_state(self, state):
            self.broadcasts.append(state)

        async def handle_client_event(self, event_name):
            try:
                event = Event[event_name.upper()]
            except KeyError:
                return
            try:
                new_state = self.audio.transition(event)
                await self.broadcast_state(new_state)
            except IllegalTransitionError as e:
                self.logs.append({"current": self.audio.state.value, "attempted": event_name, "err": str(e)})
                await self.broadcast_state(self.audio.state)

    sess = FakeSession()
    sess.audio.transition(Event.START_LISTENING)
    sess.audio.transition(Event.SPEECH_ENDED)

    asyncio.run(sess.handle_client_event("speech_ended"))   # illegal from Processing

    assert sess.audio.state == State.PROCESSING
    assert sess.broadcasts[-1] == State.PROCESSING
    assert sess.logs and sess.logs[-1]["attempted"] == "speech_ended"
```

- [ ] **Step 5: Pass + commit**

Run: `pytest -v 2>&1 | tail -15`
Expected: all green.

```bash
git add server.py tests/test_audio_state.py
git commit -m "[refactor] wire AudioSession into VoiceSession; replace scattered booleans"
```

---

### Task 6.3: Update `static/js/app.js` to consume server state broadcasts

**Files:**
- Modify: `static/js/app.js`

- [ ] **Step 1: Find the JS state booleans**

Run: `grep -n 'videoCallProcessing\|ttsAborted\|is_speaking\|vad_paused' static/js/app.js | head -10`

- [ ] **Step 2: Add a `currentServerState` variable + WebSocket handler**

Near the top of `static/js/app.js`, add:

```javascript
let currentServerState = "idle";

function onServerStateMessage(msg) {
  if (msg.type === "state") {
    currentServerState = msg.state;
  }
}
```

In the WebSocket `onmessage` handler, dispatch to `onServerStateMessage` when `msg.type === "state"`.

- [ ] **Step 3: Replace boolean checks with state checks**

Find each JS boolean and update:

| Old code | New code |
|---|---|
| `if (!videoCallProcessing && !ttsAborted)` | `if (currentServerState === "listening")` |
| `if (is_speaking)` | `if (currentServerState === "speaking")` |
| `videoCallProcessing = true` | `ws.send(JSON.stringify({type: "client_event", event: "tts_started"}))` |
| `videoCallProcessing = false` | `ws.send(JSON.stringify({type: "client_event", event: "tts_finished"}))` |

- [ ] **Step 4: Server-side: handle the `client_event` message**

In `server.py`'s WebSocket message handler, add:

```python
elif msg.get("type") == "client_event":
    await self.handle_client_event(msg["event"])
```

- [ ] **Step 5: Manual smoke test**

Start the server, open the browser, start a voice call, say something. Watch the server logs for `audio.race` entries — there should be very few (race-induced ones only).

- [ ] **Step 6: Commit**

```bash
git add static/js/app.js server.py
git commit -m "[refactor] JS consumes server state broadcasts; remove client-side booleans"
```

---

### Task 6.4: Update prompt call sites in `server.py` to use `REGISTRY.render`

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Find the TODO markers from task 3.7**

Run: `grep -n 'TODO(phase-3.7-followup)' server.py`

- [ ] **Step 2: Replace each marker with `await REGISTRY.render(...)`**

For each spot, identify which prompt to render and which providers/overrides apply. Common ones:

```python
# Voice session start
self.system_prompt = await REGISTRY.render("default_system")

# Video call mode
video_system = await REGISTRY.render("video_call")

# Vision template (whiteboard, face, scene, menu)
vision_system = await REGISTRY.render(f"vision_{template_name}")
```

- [ ] **Step 3: Verify the server boots**

Run: `python -c "import server" 2>&1 | tail -3`
Expected: clean import.

If you can: `python -m uvicorn server:app --port 8443 &` then `curl http://localhost:8443/health` — expect 200.

- [ ] **Step 4: Commit**

```bash
git add server.py
git commit -m "[refactor] replace TODO placeholders with REGISTRY.render at call sites"
```

End of Phase 6: full integration. State machine + registry + tool dispatch all live in production code. `server.py` is meaningfully shorter.

---

## Phase 7: Handoff Rebuild

### Task 7.1: Lift handoff endpoints from `claw` HEAD, simplified atop state machine

**Files:**
- Modify: `server.py` — port handoff routes/handlers
- Reference: `git show claw:server.py | grep -n 'handoff'`

- [ ] **Step 1: View claw HEAD's handoff routes**

Run: `git show claw:server.py | grep -n 'handoff\|handoff_offer\|handoff_resume' | head -20`

- [ ] **Step 2: Port the handoff-state-transfer logic**

Copy the handoff route handlers (e.g., `GET /api/handoff/status`, the WebSocket message types for handoff offer/accept/decline) from claw HEAD into `server.py` on `redesign`. **But:** replace any mobile-specific state-recovery code (the things added in commits `4b05bec`, `fc7b689`, `ef83723`) with single `self.audio.transition(Event.HANDOFF_START)` / `HANDOFF_COMPLETE` calls. The state machine handles recovery.

Typical pattern after port:

```python
async def offer_handoff(self, target_device_type: str) -> None:
    self.audio.transition(Event.HANDOFF_START)
    # ... transfer conversation_history, current state, etc. ...
    await self.broadcast_state(self.audio.state)

async def complete_handoff(self) -> None:
    self.audio.transition(Event.HANDOFF_COMPLETE)
    await self.broadcast_state(self.audio.state)
```

- [ ] **Step 3: Verify L4 handoff tests still pass**

Run: `pytest tests/test_audio_state.py -v 2>&1 | tail -10`
Expected: all green (the state machine is already exercised; this commit only adds the integration).

- [ ] **Step 4: Commit**

```bash
git add server.py
git commit -m "[feat] port handoff routes from claw HEAD; route state through AudioSession"
```

---

### Task 7.2: Port handoff UI in `static/js/app.js`

**Files:**
- Modify: `static/js/app.js`
- Modify: `static/index.html` (if handoff UI components live there)

- [ ] **Step 1: View claw HEAD's handoff UI**

Run: `git show claw:static/js/app.js | grep -n 'handoff' | head -20`

- [ ] **Step 2: Port the offer panel, accept/decline buttons, and the resume flow**

Copy verbatim, then replace any client-side boolean state mutations with state-broadcast consumption (continuing the pattern from task 6.3).

- [ ] **Step 3: Manual smoke test**

Open the app on laptop, then on phone. Confirm handoff offer appears on phone.

- [ ] **Step 4: Commit**

```bash
git add static/js/app.js static/index.html
git commit -m "[feat] port handoff UI from claw HEAD; consume state broadcasts"
```

---

### Task 7.3: Seed `local_data/` with demo files

**Files:**
- Create: `local_data/health.yaml`
- Create: `local_data/README.md`

- [ ] **Step 1: Copy claw HEAD's demo health file**

```bash
git show claw:demo_files/health-dummy-data.yaml > local_data/health.yaml
```

- [ ] **Step 2: Create `local_data/README.md`**

```markdown
# local_data/

Local user context consumed by prompt context providers in `prompts.py`.
This is your data — swap any file with your own. The demo ships with
example content so the assistant has something interesting to talk about
in a fresh clone.

Files:
- `health.yaml` — recent health log. Replaced by real WHOOP data if
  you uncomment the `user_health_context` provider's WHOOP branch.
```

- [ ] **Step 3: Commit**

```bash
git add local_data/
git commit -m "[feat] seed local_data/ with demo health context + README"
```

End of Phase 7: feature parity with claw HEAD (audio bug fixed, demo-mode rigging gone).

---

## Phase 8a: Automated Acceptance

### Task 8a.1: Write Layer 3 E2E demo-beat test infrastructure

**Files:**
- Create: `tests/test_demo_beats_e2e.py`
- Create: `tests/demo_beat_fixtures.py`

- [ ] **Step 1: Write `tests/demo_beat_fixtures.py`**

```python
"""Demo storyboard — beats exercised by L3 E2E tests."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DemoBeat:
    name: str
    prompt: str
    expected_tool: str | None
    expected_phrases: list[str]
    forbidden_phrases: list[str] = field(default_factory=lambda: ["I can't", "I don't have access"])


DEMO_BEATS: list[DemoBeat] = [
    DemoBeat("intro", "Hi, can you hear me?",
             expected_tool=None,
             expected_phrases=["yes", "hear"]),
    DemoBeat("exec_brief", "Draft me an executive brief about Q4 plans",
             expected_tool="markdown_assistant",
             expected_phrases=["brief", "Q4"]),
    DemoBeat("html_dashboard", "Build me a simple dashboard webpage",
             expected_tool="html_assistant",
             expected_phrases=["working on", "dashboard"]),
    DemoBeat("reasoning", "Help me prioritize: ship the demo or fix the bug?",
             expected_tool="reasoning_assistant",
             expected_phrases=["priority", "demo"]),
    DemoBeat("todo_add", "Add 'review the spec' to my todos",
             expected_tool="add_todo",
             expected_phrases=["added", "spec"]),
    DemoBeat("todo_list", "What's on my todo list?",
             expected_tool="list_todos",
             expected_phrases=["spec"]),
    DemoBeat("order", "Order me some salmon for dinner",
             expected_tool="place_order",
             expected_phrases=["ordered", "tracking"]),
    DemoBeat("smart_home", "Dim the lights to 30%",
             expected_tool="set_smart_home",
             expected_phrases=["lights", "30"]),
    DemoBeat("email", "Send an email to Sarah about the meeting tomorrow",
             expected_tool="send_email",
             expected_phrases=["sent", "Sarah"]),
    DemoBeat("slack", "Post to the team channel that I'm running late",
             expected_tool="post_message",
             expected_phrases=["posted"]),
    DemoBeat("call", "Call Mom",
             expected_tool="place_call",
             expected_phrases=["calling", "Mom"]),
    DemoBeat("money", "Send Sarah $40 for dinner",
             expected_tool="send_money",
             expected_phrases=["sent", "40"]),
]
```

- [ ] **Step 2: Write `tests/test_demo_beats_e2e.py`**

```python
"""Layer 3 — E2E demo-beat tests against the local LLM stack."""
from __future__ import annotations

import asyncio
import json
import os
from urllib.request import Request, urlopen

import pytest

from subagents import TOOLS, dispatch, tool_schemas_for_llm
from prompts import REGISTRY
from tests.demo_beat_fixtures import DEMO_BEATS


LLM_URL = os.environ.get("LLM_SERVER_URL", "http://localhost:11434/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3.6:35b-a3b")


def _llm_complete(messages, tools=None):
    payload = {"model": LLM_MODEL, "messages": messages, "stream": False, "max_tokens": 900}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    req = Request(LLM_URL, data=json.dumps(payload).encode("utf-8"),
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["choices"][0]["message"]


def _contains_any(haystack: str, needles: list[str]) -> bool:
    h = haystack.lower()
    return any(n.lower() in h for n in needles)


class FakeCtx:
    """Simple ctx for handler execution during E2E tests."""
    def __init__(self):
        from tests.conftest import FakeLLMClient
        self.qwen = FakeLLMClient()
        self.nemotron = FakeLLMClient()


@pytest.mark.gpu
@pytest.mark.parametrize("beat", DEMO_BEATS, ids=lambda b: b.name)
def test_demo_beat(beat, tmp_workspace):
    """Per-beat: fresh state, fire one user turn through the real LLM."""
    system = asyncio.run(REGISTRY.render("default_system"))
    msg = _llm_complete(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": beat.prompt}],
        tools=tool_schemas_for_llm(),
    )
    tool_calls = msg.get("tool_calls") or []

    if beat.expected_tool:
        assert tool_calls, f"No tool called for {beat.name!r} (prompt: {beat.prompt!r})"
        actual = tool_calls[0]["function"]["name"]
        assert actual == beat.expected_tool, \
            f"For {beat.name!r}: expected {beat.expected_tool}, got {actual}"

        # Execute the tool, get synthesis turn
        args = json.loads(tool_calls[0]["function"]["arguments"] or "{}")
        ctx = FakeCtx()
        result = asyncio.run(dispatch(actual, args, ctx=ctx))
        synthesis_msg = _llm_complete(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": beat.prompt},
                msg,
                {"role": "tool", "tool_call_id": tool_calls[0].get("id", "0"),
                 "content": str(result)},
            ],
        )
        synthesis = synthesis_msg.get("content") or ""
    else:
        synthesis = msg.get("content") or ""

    assert _contains_any(synthesis, beat.expected_phrases), \
        f"For {beat.name!r}: synthesis {synthesis!r} missing any of {beat.expected_phrases}"
    assert not _contains_any(synthesis, beat.forbidden_phrases), \
        f"For {beat.name!r}: synthesis {synthesis!r} contains forbidden phrase"


@pytest.mark.gpu
def test_full_demo_sequence(tmp_workspace):
    """All beats in one continuous conversation."""
    system = asyncio.run(REGISTRY.render("default_system"))
    state = [{"role": "system", "content": system}]
    ctx = FakeCtx()

    for beat in DEMO_BEATS:
        state.append({"role": "user", "content": beat.prompt})
        msg = _llm_complete(messages=state, tools=tool_schemas_for_llm())
        state.append(msg)
        tool_calls = msg.get("tool_calls") or []
        if beat.expected_tool:
            actual = tool_calls[0]["function"]["name"] if tool_calls else None
            assert actual == beat.expected_tool, \
                f"At beat {beat.name!r}: expected {beat.expected_tool}, got {actual}"
            args = json.loads(tool_calls[0]["function"]["arguments"] or "{}")
            result = asyncio.run(dispatch(actual, args, ctx=ctx))
            state.append({"role": "tool", "tool_call_id": tool_calls[0].get("id", "0"),
                          "content": str(result)})
            synthesis_msg = _llm_complete(messages=state)
            state.append(synthesis_msg)
            synthesis = synthesis_msg.get("content") or ""
        else:
            synthesis = msg.get("content") or ""
        assert _contains_any(synthesis, beat.expected_phrases), \
            f"At beat {beat.name!r}: synthesis missing expected phrases"
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_demo_beats_e2e.py tests/demo_beat_fixtures.py
git commit -m "[test] add L3 E2E demo-beat tests"
```

---

### Task 8a.2: Run L3 tests against the local LLM stack, fix failures

- [ ] **Step 1: Start the local LLM if not running**

Verify: `curl -s http://localhost:11434/v1/models | head` returns JSON.

- [ ] **Step 2: Run L3 tests**

Run: `pytest tests/test_demo_beats_e2e.py -v -m gpu 2>&1 | tail -30`
Expected: All beats pass per-beat and in sequence.

- [ ] **Step 3: Triage any failures**

For each failure, decide:
- **Wrong tool selected** → look at the LLM's chosen tool; if the prompt is ambiguous, tighten the `description` field in `subagents.py` so the LLM picks correctly. Then re-record L1 snapshot if any prompt changed.
- **Synthesis missing expected phrase** → loosen the `expected_phrases` (use shorter common substrings) OR adjust the handler's return string for clarity.
- **Forbidden phrase present** → trace it back: was it `I can't` from `ask_claw`? That's an action-tool gap → add a more specific tool. Was it from the model? Strengthen the default system prompt.

Each fix is its own commit:

```bash
git add <files>
git commit -m "[fix] tighten <toolname> description for L3 reliability"
```

- [ ] **Step 4: Re-run until all pass**

Iterate. When the per-beat suite + the sequenced test both pass:

```bash
git add <any-remaining-changes>
git commit --allow-empty -m "[chore] L3 E2E demo-beat suite passing"
```

End of phase 8a: full automated suite green including L3.

---

## Phase 8b: Manual Acceptance

### Task 8b.1: Commit the manual handoff gate checklist

**Files:**
- Create: `tests/manual_handoff_gate.md`

- [ ] **Step 1: Write the checklist**

```markdown
# Manual handoff gate

Run before merging `redesign` to `claw`. Required: laptop + phone on the
same network; server running on laptop with HTTPS.

## Procedure

1. Open the app in laptop browser. Start a voice call.
2. Say "hello, are you there?" — confirm response heard.
3. Open the app in phone browser. Accept the handoff offer.
4. Phone: say "what was I just asking about?" — confirm:
   - [ ] Audio sent from phone is received by server (check logs)
   - [ ] Response audio plays on phone, not laptop
   - [ ] Response references the laptop utterance
5. Phone: say "draft me a quick markdown note about Q4" — confirm:
   - [ ] markdown_assistant fires
   - [ ] Artifact appears in workspace/
6. Phone: ask for an action — "order me some salmon" — confirm:
   - [ ] place_order fires (NOT ask_claw)
   - [ ] Response: "Ordered..." with a tracking ID
   - [ ] actions_log.jsonl has the new entry
7. Phone: mute, then unmute. Speak after unmute. Confirm audio heard.
8. Hand back to laptop. Repeat step 2.

Any "no" answer blocks merge. If a step fails, file a new test reproducing
the failure scenario in tests/test_audio_state.py (state-machine level) or
tests/test_demo_beats_e2e.py (LLM-level), fix the underlying issue, and
re-run this gate.
```

- [ ] **Step 2: Commit**

```bash
git add tests/manual_handoff_gate.md
git commit -m "[docs] add manual handoff gate checklist"
```

---

### Task 8b.2: Execute the manual gate

This step is performed by the user, not the agent.

- [ ] **Step 1: User runs through `tests/manual_handoff_gate.md` step-by-step**

- [ ] **Step 2: Demo storyboard end-to-end**

User additionally runs the live demo storyboard end-to-end on the demo machine — every beat, voice + video.

- [ ] **Step 3: If anything fails**

Stop. File a regression test reproducing the failure. Fix. Re-run the gate.

- [ ] **Step 4: When gate ticks completely**

Mark `phase-8b-passed` in the conversation. Proceed to phase 9.

End of phase 8b: human-verified.

---

## Phase 9: Merge

### Task 9.1: Merge `redesign` → `claw`

This step needs explicit user authorization before executing.

- [ ] **Step 1: Pause for user confirmation**

Confirm with user: "All acceptance criteria met. Merge `redesign` into `claw` (or replace `claw` with `redesign`)? Y/N"

- [ ] **Step 2 (option A): Fast-forward style replacement**

If the user wants to preserve old claw history under a tag:

```bash
git tag claw-pre-redesign claw
git checkout claw
git reset --hard redesign
```

- [ ] **Step 2 (option B): Merge with history**

```bash
git checkout claw
git merge --no-ff redesign -m "[feat] merge redesign branch — prompt registry, subagent dispatch, audio state machine"
```

- [ ] **Step 3: Push (only if user explicitly asks)**

```bash
git push origin claw
# (optional) git push origin claw-pre-redesign
```

- [ ] **Step 4: Celebrate**

The rebuild is done.

---

## Appendix: Quick reference for repeated patterns

### Adding a new tool to the registry

1. Write a test in the appropriate `tests/test_*_handlers.py`.
2. Run it to confirm it fails.
3. Add the handler function under the appropriate section banner in `subagents.py`.
4. Add the registry entry in the `TOOLS.update({...})` block at the bottom.
5. Run the test to confirm it passes.
6. Run `pytest tests/test_tool_registry.py` — if the EXPECTED_TOOLS set is now stale, update it.
7. Commit with message `[feat] add <toolname> <kind> tool`.

### Adding a new prompt

1. Append the entry to `prompts.yaml` (description / context / template).
2. Run `pytest tests/test_prompts.py --snapshot-update` to capture the new snapshot.
3. Run `pytest tests/test_prompts.py` (no flag) to confirm stable.
4. Commit `[feat] add <prompt_name> prompt`.

### Lifting code from `claw` HEAD

```bash
# View a file
git show claw:path/to/file.py | sed -n 'START,ENDp'

# Lift verbatim
git show claw:path/to/file.py > path/to/file.py

# Stage and commit
git add path/to/file.py
git commit -m "[refactor] lift <thing> from claw HEAD"
```

### Running the full suite

```bash
# CPU-only (L1, L2a, L2b, L4) — fast, every commit
pytest -v -m "not gpu"

# Include L3 — requires local LLM server running
pytest -v

# Just one layer
pytest tests/test_prompts.py -v        # L1
pytest tests/test_tool_registry.py -v  # L2a
pytest tests/test_subagent_handlers.py tests/test_action_handlers.py tests/test_inline_handlers.py -v  # L2b
pytest tests/test_audio_state.py -v    # L4
pytest tests/test_demo_beats_e2e.py -v # L3 (gpu)
```
