# Findings — Beat 3 Health Agent Planning

## Code-path audit (current state)

### `prompts.py`
- `DEFAULT_SYSTEM_PROMPT` lines 106-134 — global voice persona; no health
  content. Leave alone.
- `VIDEO_CALL_PROMPT` lines 167-222 — used on the phone path.
  - Lines 212-217 are the "LOCAL PRIVATE DEMO MEMORY" block: hard-coded
    "first half marathon" goals + "yesterday the user ate ramen" + generic
    lighter/higher-protein/lower-salt rules. **This is the block to replace.**
- `_load_claw_persona()` lines 70-100 — established pattern for local file
  injection into a system prompt. The health context loader
  `_load_health_context()` is added as a sibling function in the same
  file (kept distinct from the persona loader so the privacy boundary
  remains auditable). Both are concatenated onto `VIDEO_CALL_PROMPT` at
  module import time.
- `VISION_TEMPLATE_PROMPTS` (lines 229-326) — none touch the menu beat.

### `server.py`
- Phone video-call branch lines 2118-2325. System prompt is constructed at
  line 2173 as `f"{base_prompt}\n\n{VIDEO_CALL_PROMPT}"`. **Health
  context is already inside `VIDEO_CALL_PROMPT`** because
  `_load_health_context()` is concatenated in at import time — server.py
  needs no change for prompt assembly.
- `is_workspace_update_request` lines 1439-1454 — short-circuits the VLM
  path for Beat 4. Reference pattern only; no parallel intent matcher
  is being added (the final design uses always-on injection rather than
  intent gating).
- `load_demo_files()` lines 1695-1716 — iterates top-level `.csv` /
  `.txt` / `.md` files under `demo_files/`. Customer feedback CSVs/TXTs
  feed the reasoning agent. The new `health.yaml` and `whoop_auth.json`
  use suffixes already outside the allowlist, so they don't leak today;
  still add an explicit name-based skip guard to keep intent obvious if
  the suffix list ever changes.
- `apply_workspace_todo_updates` lines 1478-1525 — example of
  deterministic multi-file workspace mutation that is unrelated but
  shows the codebase's preferred style for demo-determinism.

### `tools.py`
**No change.** The earlier plan added a `get_health_context` inline
tool; the final design dropped it. The VLM has the health context every
turn via prompt injection, so a per-turn tool call would be redundant.

### `static/index.html`
**No change.** No frontend toggle is added; health context is always
on. The earlier plan's `toolGetHealthContext` checkbox was dropped.

### `MILESTONES.md`
- Lines 7-27 already contain a "WHOOP Integration" milestone marked **In
  Progress**. This plan fulfills that milestone — close it on Phase 6.

### `TESTING.md`
- Lines 1-30 are the live prompt regression suite against
  `qwen3.6:35b-a3b`. Beat 3 expected wording at lines 24-25 will need to
  change to the new health-led wording.
- Beat 4 deterministic routing test pattern lines 86-118 is the template
  for the new health tests (heredoc-driven Python via `<<'PY'`).

### Frontend pipeline summary

```
phone mic → ASR (faster-whisper, GPU) → server.py video-call branch
  → is_workspace_update_request(text)? Beat 4 short-circuit
  → VLM(image, VIDEO_CALL_PROMPT)
       ↑
       └ at import time, prompts.py concatenates:
         VIDEO_CALL_PROMPT = "..." + _load_claw_persona()
                                   + _load_health_context()
                                   + _maybe_demo_suffix()
  → TTS (Kokoro, GPU)
```

## WHOOP API (developer.whoop.com)

### OAuth 2.0 Authorization Code with offline scope

- Authorization URL: `https://api.prod.whoop.com/oauth/oauth2/auth`
- Token URL: `https://api.prod.whoop.com/oauth/oauth2/token`
- Redirect URI must use `https://...` or `whoop://...`. No plain
  `http://localhost`. Use the existing self-signed HTTPS host:
  `https://localhost:8445/whoop/callback`.
- Access tokens: short-lived (`expires_in` in seconds, exact value not
  documented). Refresh token is issued only when the `offline` scope is
  in the auth request. Existing refresh token is invalidated on use.

### Scopes (exact strings)

| Scope | Purpose |
|-------|---------|
| `read:recovery` | Recovery score, RHR, HRV, SpO2 |
| `read:sleep` | Sleep performance, total/REM/SWS sleep |
| `read:cycles` | Day strain, kilojoules |
| `read:workout` | Per-workout strain/kilojoules |
| `read:profile` | User identity (cache key) |
| `read:body_measurement` | Height, weight, max HR |
| `offline` | Required to receive a refresh token |

### Endpoints (v2)

| Method | Path | Scope | Key fields |
|--------|------|-------|-----------|
| GET | `/v2/recovery` | `read:recovery` | `recovery_score`, `resting_heart_rate`, `hrv_rmssd_milli`, `spo2_percentage` |
| GET | `/v2/cycle/{cycleId}/recovery` | `read:recovery` | as above |
| GET | `/v2/activity/sleep` | `read:sleep` | `sleep_performance_percentage`, `total_in_bed_time_milli`, `total_rem_sleep_time_milli`, `total_slow_wave_sleep_time_milli` |
| GET | `/v2/activity/sleep/{sleepId}` | `read:sleep` | as above |
| GET | `/v2/cycle` | `read:cycles` | `strain`, `kilojoule`, `average_heart_rate` |
| GET | `/v2/cycle/{cycleId}` | `read:cycles` | as above |
| GET | `/v2/activity/workout` | `read:workout` | `strain`, `kilojoule`, `average_heart_rate` |
| GET | `/v2/activity/workout/{workoutId}` | `read:workout` | as above |
| GET | `/v2/user/profile/basic` | `read:profile` | `user_id`, `email`, `first_name`, `last_name` |
| GET | `/v2/user/measurement/body` | `read:body_measurement` | `height_meter`, `weight_kilogram`, `max_heart_rate` |

### Local caching strategy

- Single source of truth: `demo_files/health.yaml` with a `whoop:`
  subtree. Each endpoint block carries a `fetched_at` ISO-8601
  timestamp.
- The WHOOP refresh job in `clients/whoop.py` overwrites only the
  `whoop:` subtree; `condition`, `bloodwork`, `meals`, and `goals`
  subtrees stay hand-edited.
- When credentials are absent, the committed stub `whoop:` subtree is
  the source of truth. No separate stub or cache files.
- OAuth tokens live in `demo_files/whoop_auth.json` (gitignored,
  chmod 600) — kept separate from the YAML because they're sensitive
  and have a different write cadence.
- `_load_health_context()` reads the YAML once at module import time;
  the result is baked into `VIDEO_CALL_PROMPT`. Server restart picks
  up a fresh refresh.

## Architecture decision rationale (final)

- **Inline tool** rejected: VLM has to OCR/translate the menu image
  *and* call the tool. Two model hops introduce flake on a 2-hour
  build, and the tool-result roundtrip duplicates context the VLM
  could already see.
- **Hard-coded prompt baking** (today's state) rejected: stale,
  unverifiable, no path to live WHOOP data.
- **Hybrid intent-matcher + conditional injection** (earlier revision)
  rejected: three coupled paths for one fact. Replaced with the
  simpler design below after pattern-audit feedback.
- **Final: always-on prompt injection at module import time.** Mirrors
  the existing `_load_claw_persona()` pattern at prompts.py:70-100.
  `_load_health_context()` reads `demo_files/health.yaml`, returns a
  speech-safe block, and is concatenated onto `VIDEO_CALL_PROMPT` at
  import time. The VLM has the same context for every turn (menu,
  sleep, workout, etc.); prompt rules govern when to use it. Zero
  per-turn cost. No intent matcher. No new inline tool. No frontend
  toggle. No `VoiceSession.__init__` change.

## New story (replacing fitness/marathon framing)

- Primary concern: **high blood pressure** (lisinopril 10mg).
- Secondary: elevated LDL cholesterol (152 mg/dL, drawn 2026-04-12).
- Recent meals: tonkotsu ramen (lunch) + leftover fried rice (dinner) —
  both heavy-sodium.
- WHOOP yesterday: day strain 14.6, recovery 42% (low), sleep 71%
  performance.
- Privacy rule: never speak raw digits unless user asks for "my numbers"
  / "the data" / "the details."

## Demo wording target

The demo *narration* (what Selena says on stage) reveals that a high-blood-
pressure diagnosis was uploaded to the Spark. The agent's *spoken response*
must NOT name that diagnosis — the demo frames the menu beat as a public /
social setting, and the privacy point is precisely that sensitive labels stay
on the box. The agent acts on the diagnosis but does not broadcast it.

Spoken target (recommended dish + skipped dish + neutral, food-only reason):

> "I'd go with the steamed sea bass over the salt-and-pepper pork chop — the
> pork chop is deep-fried and pretty heavy on sodium today."

Acceptable variations:

- "Lighter today — the steamed fish over the pork chop. The pork chop is
  fried and salty."
- "Sea bass beats the pork chop today; the pork chop is deep-fried and
  likely high-sodium."

Forbidden in spoken output (unless user explicitly asks "why?" / "what do
you know about my health?" / "tell me my numbers"):

- "blood pressure", "hypertension", "high BP"
- "cholesterol", "LDL"
- "your diagnosis", "your condition"
- specific numeric values (138/88, LDL 152, etc.)
- the medication name "lisinopril"

If the user explicitly asks the *why* in private (e.g. "why that one?"), the
agent may then refer to the underlying reason, still without numbers
("because of your blood pressure" is fine; "138 over 88" is not).

This rule replaces the earlier "tie the reason to ONE concrete signal like
blood pressure" wording in PLAN.md §6/§7a — those need updating to neutral
food-language reasons in the default spoken path.

## References

- WHOOP OAuth: https://developer.whoop.com/docs/developing/oauth (fetched
  2026-05-05).
- WHOOP API v2 endpoint reference: https://developer.whoop.com/api
  (fetched 2026-05-05).

## Plan review findings (resolved)

An earlier review of PLAN.md against the repo and WHOOP docs surfaced
several issues. All have been resolved in the final PLAN.md:

- ✅ Speech-safe prompt block (no raw numbers, no diagnosis names) is
  now mandatory; tests assert it.
- ✅ WHOOP API responses are nested collection records — the YAML stub
  shape uses flattened convenience views; `clients/whoop.py` is the
  adapter layer.
- ✅ Beat 4 workspace short-circuit stays first; health context lives
  inside `VIDEO_CALL_PROMPT` itself via import-time concatenation, so
  there's no separate "inject after Beat 4" step.
- ✅ UI-tool contradiction resolved by dropping the
  `get_health_context` tool and the `toolGetHealthContext` toggle
  entirely. Health context is always on via prompt injection.
- ✅ Demo meal dates updated to `2026-05-04` so "yesterday's ramen"
  resolves correctly relative to the demo date.
- ✅ Phase 1 includes adding `demo_files/menu_zh.png` and a
  `demo_files/menu_zh_dishes.json` fixture for Test D grounding.
- ✅ Gitignore covers `demo_files/whoop_auth.json`. OAuth `state`
  validation is part of the callback handler.
- ✅ `load_demo_files()` skip uses an explicit name-based guard
  (`SENSITIVE_NAMES = {"health.yaml", "whoop_auth.json"}`).

## Architecture simplification (2026-05-05 revision)

The original PLAN.md design is over-engineered for the demo. Open issues:
intent matcher + conditional injection + a separate inline tool together
amount to three coupled paths for one fact ("the user has health data").

Simpler design (revised again — see "Module placement" below):

1. `clients/whoop.py` — fetch + OAuth, runnable from cron or
   `/whoop/login`. Writes the `whoop:` subtree of `demo_files/health.yaml`.
   Sits next to the other external-service clients (`asr.py`, `llm.py`,
   `tts.py`, `vlm.py`, `face.py`, `claw_acp.py`).
2. `prompts.py::_load_health_context()` — a sibling of the existing
   `_load_claw_persona()` (prompts.py:70-100). Reads
   `demo_files/health.yaml`, returns a speech-safe block. Concatenated
   onto `VIDEO_CALL_PROMPT` at module import time, exactly the way Claw
   persona is concatenated onto `DEFAULT_SYSTEM_PROMPT`.
3. `server.py` — only change is adding `health.yaml` /
   `whoop_auth.json` to the `load_demo_files()` skip list. No
   `VoiceSession.__init__` change, no per-turn appending. The injection
   already lives inside `VIDEO_CALL_PROMPT`.

Drops from the previous plan:

- `health/intents.py` and `is_menu_recommendation_request` — not needed; the
  context is always available, the prompt rules govern when to use it.
- The `get_health_context` inline tool — the VLM already has the context.
  If we ever want a "show me my data" affordance, it's a separate
  `claw_recall`-style fast path, not a per-turn tool call.
- The `static/index.html` toggle — health context is always on.
- The `health/` top-level package — collapsed entirely. WHOOP belongs in
  `clients/`; the loader belongs next to `_load_claw_persona()`.

This works for any health-shaped question (menu, "should I run today?",
"when should I sleep?") because the context is always present.

### Module placement

Two architectural choices firmed up after re-reading the repo:

- **WHOOP client → `clients/whoop.py`.** `clients/` is already the home
  of HTTP/IPC clients to external services (ASR, LLM, TTS, VLM, face,
  Claw ACP). WHOOP is exactly that — OAuth + REST against
  `api.prod.whoop.com`. A separate `health/` package would create two
  homes for "talks to a remote API."
- **Health context loader → function in `prompts.py`.** The repo already
  injects external context into prompts via `_load_claw_persona()` at
  prompts.py:70-100. Mirroring it as `_load_health_context()` in the
  same file is the smallest change that fits the existing pattern. A
  new module for ~50 lines would be ceremony.

### Latency note

Loader runs once at module import (when `prompts.py` first loads). The
result is baked into `VIDEO_CALL_PROMPT` as a string constant. Marginal
cost per turn is just the ~200-400 extra tokens in the system prompt —
roughly 50-100 ms added prefill on local Qwen3.6, generation unchanged.
Persona injection already adds a comparable amount today and is
acceptable. Trade-off: server restart required to pick up a fresh WHOOP
refresh. If hot-refresh becomes a requirement, move the loader call from
import-time concatenation to `VoiceSession.__init__`; the YAML format
and the loader function don't change.

### File-format collapse → one flat YAML

Even the JSON / markdown split is too much ceremony for a 2-hour demo.
Final decision: **one flat YAML** at `demo_files/health.yaml` holding
everything — condition, bloodwork, meals, goals, and the latest WHOOP
signals as nested subtrees. Tokens stay in their own gitignored JSON
because they're sensitive (`demo_files/whoop_auth.json`, chmod 600).

Trade-offs:

- One file is dramatically easier to eyeball on stage ("here is
  literally everything the agent knows about my body, in one file").
- YAML cleanly mixes narrative-ish content (`condition`, `goals`) with
  structured numeric panels (`bloodwork`) and API-shaped blocks (`whoop`).
- The WHOOP refresh job replaces only the `whoop:` subtree on disk.
  PyYAML round-trip is fine for the demo; ruamel.yaml only matters if
  comment fidelity becomes a requirement.
- PyYAML must be added to `requirements.txt` (small dep, already widely
  used).

Drops vs the previous revision: no `condition.md`, no `meal_history.md`,
no `bloodwork.json`, no `whoop_stub.json`, no `whoop_cache/` directory.
The single `health.yaml` is the source of truth; the agent doesn't know
or care whether the WHOOP subtree came from the committed stub or a
fresh API pull.
