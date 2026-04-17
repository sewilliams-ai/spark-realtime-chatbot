# 🦞 Claw × Realtime2 — Voice + Vision + Real-World Actions

Integration between **realtime2** (this repo — low-latency voice+vision loop on DGX Spark) and **OpenClaw "Claw"** (Kedar's personal assistant, already running as `openclaw-gateway` at `127.0.0.1:18789`).

## Architecture

```
   You (phone browser or dashboard)
             │
             │ WSS /ws/voice
             ▼
 ┌────────────────────────┐        ┌──────────────────────────┐
 │   realtime2 server.py  │        │  Ollama :11434           │
 │   ┌──────────────┐     │        │  qwen3.6:35b-a3b         │◄─── single model,
 │   │ ASR (whisper)│     │───────►│  OpenAI-compatible       │     shared KV cache
 │   │ VLM (Qwen3.6)│     │        │  reasoning_effort=none   │
 │   │ Kokoro CUDA  │     │        │                          │
 │   │ Agent loop   │     │        └──────────────────────────┘
 │   │ 7 inline + 1 │     │                     ▲
 │   │ 🦞 ask_claw  │─────┼─────┐               │
 │   └──────────────┘     │     │               │
 └────────────────────────┘     │               │
                                ▼               │
                       ┌──────────────────────────────────┐
                       │  Claw — openclaw-gateway :18789  │
                       │  ┌────────────────────────────┐  │
                       │  │ Main agent (qwen3.6)       │──┘
                       │  │ Workspace: ~/.openclaw/…   │
                       │  │ Persistent memory          │
                       │  │ 53 skills (12 ready):      │
                       │  │  • easy-todo               │
                       │  │  • Telegram                │
                       │  │  • ~50 bundled others      │
                       │  └────────────────────────────┘
                       └──────────────────────────────────┘
```

**One model, two agents.** Both realtime2's Qwen3.6 and Claw's Qwen3.6 share the same Ollama process and KV cache. No duplicate load; `ask_claw` does not pay a second model-warmup cost.

## Split of responsibilities

| Concern | Owner | Why |
|---|---|---|
| ASR (Whisper) | realtime2 | latency-sensitive, sentence-by-sentence |
| VLM (scene / face / whiteboard) | realtime2 | 20 frames/sec possible; Claw doesn't see |
| TTS (Kokoro CUDA, ~40 ms TTFT) | realtime2 | user hears voice from the same box |
| Fast local tools (read/write/run_python) | realtime2 | sub-second, no network |
| Long-lived memory, persistent TODOs, calendar | **Claw** | Claw already owns the user's state |
| Messaging (Telegram, iMessage, Slack, WA) | **Claw** | Claw has the accounts wired; realtime2 doesn't |
| Web search, browser automation | **Claw** | Claw has a browser sandbox + web-search skill |
| Cron / reminders | **Claw** | Persistent daemons — must live outside an ephemeral voice session |
| "Something Kedar-specific" — 1Password, notes, devices | **Claw** | lives in `~/.openclaw/workspace/` |

Rule of thumb: **if state has to outlive this conversation, route it to Claw.**

## How `ask_claw` works

realtime2 exposes a single tool, `ask_claw(message, thinking?)`, to Qwen3.6. When the model emits a tool call, realtime2 shells out to the OpenClaw CLI:

```
openclaw agent --local --agent main \
    --message "<...>" \
    --thinking low --json --timeout 120
```

Claw runs its own agent turn, dispatches whichever of the 53 skills applies, returns `{ "payloads": [{"text": "..."}], ... }`. realtime2 extracts the reply, appends it as a `tool` message, and Qwen3.6 synthesizes the final spoken response.

Latency (measured end-to-end with easy-todo):

- Qwen3.6 decides to call `ask_claw`: ~1.3 s
- Claw full round-trip (`thinking=low`, todo skill CLI): ~24 s
- Qwen3.6 synthesizes final sentence: ~1.0 s
- **Total: ~26 s** — the user hears "working on it" immediately, then the confirmation.

For realtime "conversation" responses, `ask_claw` is **not** the right tool. It's for "do something in the world" — which users implicitly tolerate taking longer because a real action is happening.

## Use cases that earn the trifecta (voice + vision + Claw)

These are Claw-specific — they use skills Kedar already has wired:

1. **"Add that to my todos."** Point camera at something (notes on whiteboard, product label, screenshot on laptop). VLM reads it, `ask_claw` adds it as a structured todo. Skill: `easy-todo`.
2. **"Text Anja: running 10 min late."** No camera needed; voice only. Skill: Telegram.
3. **"What's on my calendar today? Read it out."** Skill: calendar (when wired).
4. **"Screenshot my Slack and summarize the #launches channel."** OpenClaw browser skill → screenshot → VLM → spoken summary.
5. **"Remember: marinara sauce is Rao's brand, jar in the door."** Pointing at fridge. VLM confirms product, Claw persists to memory via `memory.md`.
6. **"Remind me tomorrow morning to follow up with Daniel."** Skill: cron + reminders.
7. **"What's this error in my terminal?"** VLM reads screenshot → `ask_claw` → Claw web-searches + explains.
8. **"Order me a birthday card for Mom."** Claw's browser skill opens a shopping flow.

The pattern: **realtime2 is the eyes and voice, Claw is the identity and hands.**

## Setup checklist

- [x] OpenClaw gateway running at `:18789` (already is — `openclaw-gateway` process visible).
- [x] Ollama running at `:11434` with `qwen3.6:35b-a3b` pulled.
- [x] `~/.openclaw/openclaw.json` uses `local-proxy/qwen3.6:35b-a3b` as primary model.
- [x] `openclaw agent --local --agent main --message "hi" --json --thinking off` returns a valid reply.
- [x] realtime2 `tools.py` has `ask_claw` registered in `ALL_TOOLS`.
- [x] Sidebar checkbox for `🦞 ask_claw` in `static/index.html`.
- [x] WebSocket path tested: text_message → Qwen3.6 → `ask_claw` → OpenClaw → T17 added.

## Config knobs

| env | default | purpose |
|---|---|---|
| `OPENCLAW_BIN` | `openclaw` on PATH, falls back to nvm install path | override for non-standard installs |
| `OPENCLAW_AGENT` | `main` | which Claw agent to target (only `main` exists today) |
| `OPENCLAW_TIMEOUT` | `120` | seconds the CLI may run before we kill it |

## Reproduce the end-to-end smoke test

```bash
# (1) Confirm both models are on the same Ollama
curl -s http://localhost:11434/api/tags | jq -r '.models[].name' | grep qwen3.6

# (2) Confirm Claw uses qwen3.6
openclaw agents list | grep Model

# (3) Direct tool invocation
python3 -c "
import asyncio, sys; sys.path.insert(0,'.')
from tools import execute_tool
print(asyncio.run(execute_tool('ask_claw', {'message':'what is 2+2','thinking':'off'})))
"

# (4) Full agent loop (Qwen3.6 → ask_claw → Claw)
python3 <<'PY'
import asyncio, json, sys, urllib.request
sys.path.insert(0, '.')
from tools import ALL_TOOLS, execute_tool

async def run():
    messages = [
        {"role":"system","content":"Delegate todos/reminders/messaging to Claw via ask_claw."},
        {"role":"user","content":"Add 'check Grafana dashboards' to my todo list."},
    ]
    for i in range(3):
        r = urllib.request.Request("http://localhost:11434/v1/chat/completions",
            data=json.dumps({"model":"qwen3.6:35b-a3b","messages":messages,
                "tools":[ALL_TOOLS["ask_claw"]], "stream":False, "reasoning_effort":"none"}).encode(),
            headers={"Content-Type":"application/json"})
        resp = json.loads(urllib.request.urlopen(r, timeout=60).read())
        m = resp["choices"][0]["message"]; tc = m.get("tool_calls") or []
        if not tc: print("reply:", m.get("content")); break
        messages.append({"role":"assistant","content":None,"tool_calls":tc})
        for c in tc:
            out = await execute_tool(c["function"]["name"], json.loads(c["function"]["arguments"]))
            messages.append({"role":"tool","tool_call_id":c["id"],"name":c["function"]["name"],"content":out})
            print("tool out:", out[:200])

asyncio.run(run())
PY
```

## Honest caveats

- **24 s for a todo add** is slow. Most of that is Claw's prompt tree (system + 50 tool schemas + workspace context) loading into Qwen3.6. Tighten Claw's agent prompt or cache Ollama's KV to reduce.
- **Container awareness.** The `ask_claw` tool shells out to the `openclaw` binary; if realtime2 runs in a container, the binary must be visible (mount or `--network host` + host path) or switch to calling OpenClaw's ACP WebSocket directly.
- **No barge-in for ask_claw.** If a `ask_claw` turn takes 25 s and the user changes their mind, there's no way to cancel today.
- **Claw announces its own model to Ollama.** Both realtime2 and Claw send requests to Ollama simultaneously; if they overlap with reasoning turns, the second request will queue. Acceptable for demo, worth measuring under load.
- **Security.** `~/.openclaw/openclaw.json` has Kedar's Telegram bot token and a Gemini API key in plaintext. Rotate both; consider a `credentials/` file outside the main config.

## What's next

- **ACP WebSocket client** instead of CLI shell-out — removes the 2-3 s node startup cost per call. Library: `@modelcontextprotocol/sdk` is bundled in OpenClaw; the Python side would use `websockets` + the ACP JSON-RPC shape.
- **Cancel token for ask_claw.** If the user barge-ins, send SIGTERM or send a JSON-RPC cancel.
- **Vision → Claw context.** Today `ask_claw(message)` gets only the text. Consider compressing the latest VLM observation into the message for richer context ("the screen shows a Slack thread about the Q2 launch, summarize and add an action item to…").
- **Skills Kedar should install.** `calendar-sync` (Google Calendar), `browser` already available, `1password` to drive login flows. `openclaw skills list` shows 41 more bundled but not yet ready.
