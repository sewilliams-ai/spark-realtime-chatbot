# Planning Archive

This file indexes archived planning efforts only.

## Bidirectional Conversation Handoff

### Status

Complete.

### Summary

Ported the useful main-branch handoff mechanics into `claw` as a lean,
process-local, bidirectional conversation-transfer layer. The final UX shows a
`Continue Call` option in the Start New Chat modal only when another active
device owns a live call, preserves completed conversation context across
phone/laptop transfers, shows an inline bring-back action on the displaced
device, and recovers video input after empty-ASR and WebSocket timing edge
cases found during live testing.

### Archived Files

- `.planning/archive/2026-05-06-bidirectional-conversation-handoff/task_plan.md`
- `.planning/archive/2026-05-06-bidirectional-conversation-handoff/findings.md`
- `.planning/archive/2026-05-06-bidirectional-conversation-handoff/progress.md`

### Planning Notes

- The initial plan intentionally avoided a new `handoff.py`; the final
  implementation kept handoff helpers in `server.py` because the feature is
  tightly coupled to `VoiceSession`, live WebSockets, and active call state.
- The UX plan changed after live review: the offer belongs in the Start New
  Chat modal on the second device, not only after camera/mic setup.
- Duplicate prompts were removed by treating the modal/bring-back button as
  the confirmation and auto-resuming the matching WebSocket offer.
- The displaced-device prompt moved from a fixed bottom banner to an inline
  conversation panel.
- Live testing found a video-call bug where empty ASR could leave VAD paused;
  `resumeVideoCallListening()` now clears the processing state and restarts
  listening. The same recovery path handles resumed WebSocket timing races.

### Implementation Commits

- `d581518 [feat] add bidirectional conversation handoff`
- `8ef7bf4 [feat] surface pre-call handoff option`
- `2fead25 [fix] skip duplicate handoff confirmation`
- `6b213c4 [fix] skip duplicate bring-back confirmation`
- `2c47fa5 [fix] render transfer back prompt inline`
- `0abbd15 [fix] resume video input after empty asr`
- `731f029 [fix] recover video input on websocket race`

### Test Status

- `.venv-gpu/bin/python bench/test_handoff.py`: **PASS**.
- `.venv-gpu/bin/python -m py_compile server.py bench/test_handoff.py`: **PASS**.
- `node --check static/js/app.js`: **PASS**.
- `.venv-gpu/bin/python bench/test_demo_prompts.py`: **PASS**.
- `git diff --check`: **PASS**.
- Live HTTPS/WSS desktop -> mobile -> desktop smoke: **PASS**.

## WHOOP Integration

### Status

Complete.

### Summary

Implemented the Beat 3 private health/WHOOP demo: speech-safe health prompt context, local WHOOP OAuth/cache/cron refresh, dummy fallback health data, and supporting tests/docs. The original root planning files have been archived at `.planning/archive/2026-05-05-whoop-health-agent/` so they no longer collide with active handoff planning.

### Implementation Plan (`PLAN.md`)

~~~~markdown
# Beat 3 — Private Health Agent Plan

> Status: planning only. Codex executes from this file. No code in this PR.

## 1. Goal

Make Beat 3 (the restaurant menu beat) more compelling and more privacy-charged.
The narration on stage is:

> "I uploaded my high-blood-pressure diagnosis to the Spark this morning.
> Google Translate could read this Chinese-only menu, but Spark also has my
> bloodwork, what I ate yesterday, and my WHOOP recovery — locally. So it can
> recommend something that's actually safer for me, without my doctor's notes
> ever leaving the box."

The agent's *spoken* answer must:

- Recommend a visible/translated dish and a visible dish to skip.
- Use food-language reasons only ("salty", "deep-fried", "lighter today").
- **Never** name the diagnosis, the medication, or raw numbers in the default
  spoken path. Sensitive labels stay on the box; that's the demo point.
- Disclose more only if the user explicitly asks "why?" / "tell me my
  numbers."

Spoken target:

> "I'd go with the steamed sea bass over the salt-and-pepper pork chop — the
> pork chop is deep-fried and pretty heavy on sodium today."

## 2. Current state (audit)

Beat 3 is currently 100% prompt-driven inside `VIDEO_CALL_PROMPT` in
`prompts.py:212-217`, under the heading `LOCAL PRIVATE DEMO MEMORY`. The hard-
coded memory is "first half marathon" goals + "yesterday the user ate ramen,"
with a generic "lighter / higher-protein / lower-salt" recommendation rule.

Relevant code paths today:

- `prompts.py`
  - `DEFAULT_SYSTEM_PROMPT` (lines 106-134) — global voice persona.
  - `VIDEO_CALL_PROMPT` (lines 167-222) — used on the phone path; contains the
    menu-beat memory and recommendation rules at lines 212-217.
  - `_load_claw_persona()` (lines 70-100) — reference pattern for local file
    injection into a system prompt. Health context will use a parallel module
    (not this loader) so the privacy boundary is auditable.
- `server.py`
  - Phone video-call branch lines 2118-2325. System prompt is built at
    line 2173 as `f"{base_prompt}\n\n{VIDEO_CALL_PROMPT}"`. Face context is
    appended at line 2177 — same hook we will use for health context.
  - `is_workspace_update_request` (lines 1439-1454) is the Beat 4 short-
    circuit. Health-context injection happens *after* that check on the
    remaining VLM path.
  - `load_demo_files()` (lines 1695-1716) iterates only top-level `.csv` /
    `.txt` / `.md` files, so the planned `health/` JSON subdirectory does
    not leak today; we still add an explicit skip for `health` to keep the
    intent obvious if anyone later flips on recursion.
- `tools.py`
  - Tool schemas in `ALL_TOOLS` (line 37) and dispatch via `_INLINE_DISPATCH`
    (line 1016). **No new tool** — see §9.
- `static/index.html` tool toggles at lines 269-321. **No new toggle** —
  see §9.
- `TESTING.md` Beat 3 prompt regression at lines 24-25 — wording will
  change.
- `MILESTONES.md` already has a "WHOOP Integration" stub (lines 7-27)
  marked In Progress; this plan closes it.

## 3. WHOOP API summary

OAuth 2.0 (Authorization Code with the `offline` scope to receive a refresh
token):

- Authorization URL: `https://api.prod.whoop.com/oauth/oauth2/auth`
- Token URL:         `https://api.prod.whoop.com/oauth/oauth2/token`
- Redirect URI must be `https://...` or `whoop://...` (no
  `http://localhost`). Use the existing self-signed HTTPS host —
  `https://localhost:8445/whoop/callback`.
- Scopes (exact strings):
  `read:recovery`, `read:sleep`, `read:cycles`, `read:workout`,
  `read:profile`, `read:body_measurement`, `offline`.

Endpoints used (v2): `/v2/recovery`, `/v2/activity/sleep`, `/v2/cycle`,
`/v2/activity/workout`, `/v2/user/profile/basic`,
`/v2/user/measurement/body`. Full table is in `findings.md`.

Local caching: the WHOOP refresh job writes its normalized response into
the `whoop:` subtree of the single demo file `demo_files/health.yaml` (see
§5). Each endpoint block carries a `fetched_at` ISO-8601 timestamp. The
hot-path reader does one YAML load.

When credentials are absent, the YAML's `whoop:` subtree (committed with
realistic stub values) is the source of truth. The agent doesn't know or
care which produced it — demo wording is identical either way.

## 4. Architecture decision

**Always-on context injection, baked into the prompt constants at import
time — same pattern the repo already uses for Claw persona files.**

The existing precedent (prompts.py:70-100) is `_load_claw_persona()`,
which reads `~/.openclaw/workspace/{SOUL,USER,MEMORY}.md` and is
concatenated onto `DEFAULT_SYSTEM_PROMPT` and `VIDEO_CALL_PROMPT` at
module import time:

```python
DEFAULT_SYSTEM_PROMPT = """...""" + _load_claw_persona() + _maybe_demo_suffix()
```

Mirror that. Add `_load_health_context()` to `prompts.py` that reads
`demo_files/health.yaml` and returns a speech-safe block; concatenate it
onto `VIDEO_CALL_PROMPT`. The VLM sees the same context every turn; the
prompt rules — not a code matcher — govern when to use it.

```
phone speaks → ASR → server.py video-call branch
                       │
                       ├── is_workspace_update_request? ─→ Beat 4 short-circuit
                       │
                       └─ VLM(image, VIDEO_CALL_PROMPT)
                              ↑
                              └ at import time:
                                VIDEO_CALL_PROMPT = "..." + _load_claw_persona()
                                                  + _load_health_context()
                                                  + _maybe_demo_suffix()
```

What we get for free with this pattern: zero per-turn cost, zero per-
session boilerplate, no `VoiceSession.__init__` changes, the same testing
shape as `_load_claw_persona`.

Trade-off: server restart is required for a fresh WHOOP refresh to
appear in the prompt. For the demo that's fine — operator runs
`python -m clients.whoop --refresh` once before recording and restarts.
If hot-refresh becomes a requirement later, we move the loader call
into `VoiceSession.__init__` and cache on `self`; the YAML format and
the loader function don't change.

## 5. New module layout

No new package. The work spreads across existing homes:

```
clients/
  whoop.py              # NEW. OAuth + endpoint fetchers + cron entry; writes
                        # the whoop: subtree of demo_files/health.yaml.
                        # Sits alongside asr.py, llm.py, tts.py, vlm.py,
                        # face.py, claw_acp.py — the existing pattern for
                        # external-service clients.

prompts.py
  _load_health_context  # NEW function next to _load_claw_persona (lines
                        # 70-100). Reads demo_files/health.yaml, returns
                        # a speech-safe prompt block. Concatenated onto
                        # VIDEO_CALL_PROMPT at module import time.

demo_files/
  health.yaml           # ALL health context: condition, bloodwork, meals,
                        # goals, whoop. Hand-edited stub by default; the
                        # WHOOP refresh job replaces only the `whoop:` subtree.
  whoop_auth.json       # WHOOP OAuth tokens — gitignored, chmod 600
```

Rationale:

- `clients/whoop.py` over a top-level `health/whoop.py`: WHOOP is an HTTP client to an
  external service. That's exactly what `clients/` is for. Putting it
  anywhere else creates two locations for "talks to a remote API."
- `_load_health_context()` over `health/context.py`: the repo already does
  prompt injection via the `_load_claw_persona()` pattern in `prompts.py`.
  Adding a parallel loader function next to it is the smallest change
  that fits the existing shape. A separate module would be ceremony for
  ~50 lines.
- One flat `demo_files/health.yaml` over a directory of mixed files: see
  the format-collapse note in `findings.md`. PyYAML must be added to
  `requirements.txt`.
- `whoop_auth.json` separate from the YAML: tokens are sensitive,
  chmod 600, and gitignored — they shouldn't ride alongside human-
  curated content.

There's no new package, no `__init__.py` to write, no intents matcher, no
inline tool, no frontend toggle, no per-session cache.

## 6. Data model (fake data shape)

Single file: `demo_files/health.yaml`. All sub-trees are optional —
`context.py` tolerates missing keys. The WHOOP cron job replaces only the
`whoop:` subtree on refresh, leaving the rest untouched.

```yaml
# demo_files/health.yaml — fake-but-realistic local data for the demo.
# This file is the single source of truth for private health context.
# WHOOP refresh (clients/whoop.py --refresh) overwrites only the `whoop:`
# subtree. Everything else is hand-edited.

condition:
  primary: high blood pressure
  diagnosed: 2024
  medication: lisinopril 10mg daily
  secondary:
    - elevated LDL cholesterol
  doctor_guidance:
    - keep daily sodium under 2000 mg
    - prefer lean proteins, vegetables, whole grains
    - limit deep-fried foods and cured / processed meats

bloodwork:
  drawn_at: 2026-04-12
  lipid_panel:
    total_cholesterol_mg_dl: 224
    ldl_mg_dl: 152
    hdl_mg_dl: 41
    triglycerides_mg_dl: 168
  metabolic:
    fasting_glucose_mg_dl: 102
    hba1c_percent: 5.7
  blood_pressure_avg_7d:
    systolic: 138
    diastolic: 88
  notes: Borderline metabolic syndrome markers; sodium-sensitive.

meals:
  - date: 2026-05-04
    meal: lunch
    description: tonkotsu ramen with chashu and a soft-boiled egg
    tags: [heavy_sodium, rich_broth, refined_carbs]
  - date: 2026-05-04
    meal: dinner
    description: leftover fried rice
    tags: [heavy_sodium, fried]
  - date: 2026-05-03
    meal: lunch
    description: chicken Caesar salad
    tags: [moderate_sodium]

goals:
  - lower sodium intake
  - prioritize lean protein and vegetables
  - improve cardiovascular fitness without spiking strain on low-recovery days

# Refreshed by clients/whoop.py. Hand-edited stub values committed.
whoop:
  recovery:
    recovery_score: 42
    resting_heart_rate: 64
    hrv_rmssd_milli: 38
    spo2_percentage: 96.8
    fetched_at: 2026-05-05T07:12:00Z
  sleep:
    sleep_performance_percentage: 71
    total_in_bed_time_milli: 23400000
    total_rem_sleep_time_milli: 4200000
    total_slow_wave_sleep_time_milli: 3300000
    fetched_at: 2026-05-05T07:12:00Z
  cycle:
    strain: 14.6
    kilojoule: 11300
    average_heart_rate: 78
    fetched_at: 2026-05-05T07:12:00Z
  recent_workouts:
    - sport: Running
      strain: 11.2
      kilojoule: 2900
      started_at: 2026-05-04T17:30:00Z
    - sport: Strength
      strain: 8.4
      kilojoule: 1500
      started_at: 2026-05-03T18:00:00Z
```

`context.py` parses `meals[]` and renders relative phrasing ("yesterday's
ramen") at summary time using today's date. Numeric values from
`bloodwork` and `whoop` are converted to qualitative labels (`high`,
`borderline`, `low`) by simple thresholds; raw numbers never enter the
prompt block (see §11).

### Output of `prompts._load_health_context()`

The loader reads `demo_files/health.yaml` and returns a single string,
speech-safe by construction. No raw digits, no diagnosis names. Example:

```
HEALTH CONTEXT (PRIVATE — do not name aloud):
- The user has a flagged cardiovascular concern and is medication-managed.
  Treat sodium and saturated fat as something to minimize today.
- Recent bloodwork flags: LDL high, fasting glucose borderline, average BP
  elevated. Use these only to inform recommendations; do not recite values
  or category names ("blood pressure", "cholesterol") aloud unless the user
  explicitly asks why.
- WHOOP yesterday: day strain high, recovery low, sleep below target.
- Recent meals: yesterday's lunch was a salty, rich noodle bowl; yesterday's
  dinner was fried rice. The user has had two heavy / salty meals in a row.

RECOMMENDATION STYLE (food-language only):
- Recommend ONE visible/translated dish and ONE visible dish to avoid.
- Reason in food terms ("lighter", "lower-sodium", "less fried"). Do not
  name medical labels or numbers.
- Tie to the meal pattern only ("after yesterday's ramen") not to the
  diagnosis.
- One or two short spoken sentences.

DISCLOSURE RULES:
- If asked "why that?" follow up with food-language reasons first.
- If pressed (e.g. "what do you know about my health?", "tell me my
  numbers"), then it is appropriate to mention the underlying category
  ("you've got a blood-pressure flag") and, only on direct request, the
  specific numbers.
```

The block is built from `demo_files/health.yaml` once at module import
time (when `prompts.py` is loaded). Numbers from `bloodwork` and `whoop`
are converted into qualitative labels (`high`, `borderline`, `low`) by
simple thresholds inside `_load_health_context()`. Raw numbers stay in
the YAML; they do not enter the prompt.

## 7. Prompt changes (`prompts.py`)

### 7a. Replace the `LOCAL PRIVATE DEMO MEMORY` block in `VIDEO_CALL_PROMPT`

Delete `prompts.py` lines 212-217 and replace with:

```
PRIVATE HEALTH-AWARE BEHAVIOR:
- This Spark holds the user's private health context — condition, recent
  bloodwork, recent meals, WHOOP recovery and strain. The server appends a
  HEALTH CONTEXT block to this prompt every turn. Use it for any health-
  shaped question (menu picks, workout/sleep timing, "should I…").
- Default privacy rule: NEVER speak diagnosis names, medication names,
  or raw numeric values aloud. Use food-language reasons only ("salty",
  "fried", "lighter today") and meal-history reasons ("after yesterday's
  ramen"). Treat the demo as a public/social setting.
- For Chinese-only or other foreign-language menus: silently OCR and
  translate visible items to English first. Do not narrate the
  translation. If you cannot read an item, say the menu text is unclear
  and ask the user to move closer.
- When asked what to order, recommend exactly ONE visible/translated dish
  and ONE to skip, in one or two short spoken sentences. Recommended dish
  must appear in the visible menu — no invented dishes.
- Good wording: "I'd go with [visible dish] over [visible dish] — the
  [skipped one] is [food-language reason]."
- Disclosure ladder: if the user asks "why?" stay in food language. If they
  press ("what do you know about my health?", "what are my numbers?",
  "tell me the data") then it is appropriate to mention the underlying
  category and, on explicit request, specifics — quietly, in one
  sentence, not as a recital.
```

Also remove the "first half marathon" and "ramen yesterday" hard-codes —
they are now data-driven via the HEALTH CONTEXT block.

### 7b. Add `_load_health_context()` next to `_load_claw_persona()`

Mirror the persona pattern. The function reads
`demo_files/health.yaml` (PyYAML), converts raw numbers to qualitative
labels, and returns the speech-safe block from §6. Concatenate it onto
`VIDEO_CALL_PROMPT`:

```python
VIDEO_CALL_PROMPT = """...""" + _load_claw_persona() + _load_health_context() + _maybe_demo_suffix()
```

The function tolerates missing keys: any subtree absent from the YAML
becomes a one-line "X data unavailable" note in the block.

### 7c. Leave `DEFAULT_SYSTEM_PROMPT` alone

The Spark-on-laptop voice persona doesn't need health context. The
phone path (`VIDEO_CALL_PROMPT`) is the only place that gets the
injection.

### 7d. Health channel separate from `_load_claw_persona()`

Health files do not flow through Claw persona injection. The two
loaders are siblings — same shape, different files, different privacy
boundary. Keep them separate so the boundary stays auditable.

## 8. Server changes (`server.py`)

The injection happens inside `VIDEO_CALL_PROMPT` itself (§7b), so
`server.py` does not need to be changed for prompt assembly. Only one
small edit is required: tightening `load_demo_files()` so it can never
sweep up the new YAML or token file.

### 8a. Demo-file isolation

`load_demo_files()` (line 1695) reads top-level `.csv` / `.txt` / `.md`
files only. `health.yaml` and `whoop_auth.json` are not in the suffix
allowlist today, so they don't leak into the reasoning agent's customer-
feedback context. Still add an explicit guard at the top of the loop so
intent is unambiguous if the suffix list ever changes:

```python
SENSITIVE_NAMES = {"health.yaml", "whoop_auth.json"}
for file_path in sorted(demo_dir.iterdir()):
    if file_path.is_dir():
        continue
    if file_path.name in SENSITIVE_NAMES:
        continue
    ...
```

## 9. No new tool, no UI toggle

The earlier plan added a `get_health_context` inline tool and a frontend
checkbox. Both are dropped:

- The VLM already has the context every turn — a tool call would be a
  redundant roundtrip.
- A toggle implies "off by default," which contradicts the demo's
  "always on, always private" framing.

If we ever need a "show me my data" affordance for the user, it's a
separate `claw_recall`-style fast path or a /health admin route, not a
per-turn tool.

## 10. WHOOP integration (`clients/whoop.py`)

Sits next to `clients/asr.py`, `clients/llm.py`, etc. Cron-friendly
skeleton. Codex implements per §3:

```python
@dataclass
class WhoopConfig:
    client_id:     str | None = os.environ.get("WHOOP_CLIENT_ID")
    client_secret: str | None = os.environ.get("WHOOP_CLIENT_SECRET")
    redirect_uri:  str        = os.environ.get(
        "WHOOP_REDIRECT_URI",
        "https://localhost:8445/whoop/callback",
    )
    scopes: tuple[str, ...] = (
        "read:recovery", "read:sleep", "read:cycles", "read:workout",
        "read:profile", "read:body_measurement", "offline",
    )

def auth_url(state: str) -> str: ...
async def exchange_code(code: str) -> dict: ...
async def refresh_token(refresh_token: str) -> dict: ...
async def fetch_all() -> dict: ...
def write_to_health_yaml(whoop_data: dict) -> None:
    """Load demo_files/health.yaml, replace ONLY the `whoop:` subtree,
    write back atomically. Preserves comments and ordering when possible
    (use ruamel.yaml round-trip if comment fidelity matters; PyYAML is
    fine for the demo)."""

# Cron entry point — a script can call this to refresh from cron:
#   */15 * * * * cd /path/to/repo && python -m clients.whoop --refresh
def main() -> int: ...
```

### Server-side endpoints (FastAPI, in `server.py`)

Two routes, gated behind `WHOOP_CLIENT_ID` being set:

- `GET /whoop/login`     → redirects to WHOOP `auth_url`. Stores
  `state` server-side and validates on callback.
- `GET /whoop/callback`  → exchanges code, writes tokens to
  `demo_files/whoop_auth.json` (chmod 600), kicks `fetch_all()`,
  returns a small "WHOOP connected" HTML.

If `WHOOP_CLIENT_ID` is unset:
- The committed stub `whoop:` subtree of `health.yaml` is the source of
  truth — no fallback logic needed.
- `/whoop/login` and `/whoop/callback` are not registered.

Gitignore additions:

```
demo_files/whoop_auth.json
```

`demo_files/health.yaml` IS committed (with stub data). The refresh job
mutates it in place; if running with real creds you may want to also
gitignore it locally — that's an operator choice, not part of the
default repo.

## 11. Privacy and grounding rules (encoded in §6 and §7a)

Demo-critical — restated for tests:

1. Default spoken output never names a diagnosis (e.g. "high blood
   pressure", "hypertension"), a medication ("lisinopril"), a category
   word ("blood pressure", "cholesterol", "LDL"), or a raw number.
2. Disclosure ladder: food-language → category word (only on explicit
   "why?" pressing) → raw numbers (only on explicit "tell me my
   numbers" / "the data").
3. Recommended dish must be a visible / translated menu item. No
   invented dishes.
4. Recommendation reason ties to food-language and / or recent meal
   pattern, not to a medical signal.
5. Health files never enter `load_demo_files()` (§8c).

## 12. Phased implementation steps for Codex

Three commit-sized phases, plus tests + milestone closeout. The earlier
six-phase plan collapses because the inline tool / UI toggle / intent
matcher are gone.

**Phase 1 — Data scaffolding (no behavior change).**
1. Create `demo_files/health.yaml` per §6.
2. Add `PyYAML` to `requirements.txt`.
3. Gitignore `demo_files/whoop_auth.json`.
4. (Optional but useful for Test D) Add `demo_files/menu_zh.png` fixture
   and a small `demo_files/menu_zh_dishes.json` of expected English dish
   names for grounding assertions.

Commit: `[feat] add fake local health data for Beat 3`

**Phase 2 — Prompt loader + always-on injection.**
1. Add `_load_health_context()` to `prompts.py` next to
   `_load_claw_persona()`. Reads `demo_files/health.yaml` (PyYAML),
   converts numbers to qualitative labels, returns the speech-safe
   block from §6. Tolerant of missing keys.
2. Concatenate it onto `VIDEO_CALL_PROMPT` per §7b.
3. Replace the hard-coded `LOCAL PRIVATE DEMO MEMORY` block in
   `VIDEO_CALL_PROMPT` (lines 212-217) with the new privacy-safe
   instructions from §7a.
4. Edit `load_demo_files()` per §8a.

Commit: `[feat] inject always-on private health context into VLM prompt`

**Phase 3 — Real WHOOP OAuth (optional, behind env var).**
1. Add `clients/whoop.py` implementing `auth_url`, `exchange_code`,
   `refresh_token`, `fetch_all`, `write_to_health_yaml`, and `main`
   (cron entry). `write_to_health_yaml` replaces only the `whoop:`
   subtree of `demo_files/health.yaml`.
2. Add `/whoop/login` and `/whoop/callback` in `server.py`, registered
   only when `WHOOP_CLIENT_ID` is set.
3. Document env vars and the cron line in `README.md`.

Commit: `[feat] add WHOOP OAuth flow with local cache and stub fallback`

**Phase 4 — Tests + milestone close.**
1. Update `TESTING.md` per §13.
2. Update `MILESTONES.md` WHOOP entry to "Done" with summary.

Commit: `[docs] record WHOOP/health-context milestone completion`

## 13. Tests (TESTING.md additions)

Use the existing heredoc-driven pattern (template: TESTING.md lines
86-118).

### Test A — `_load_health_context()` is speech-safe

```python
from prompts import _load_health_context, VIDEO_CALL_PROMPT
block = _load_health_context()
assert isinstance(block, str) and len(block) > 50
# No raw digits from health.yaml bloodwork or whoop subtrees
for token in ("138", "88", "152", "224", "168", "102", "42", "11.2", "14.6"):
    assert token not in block, f"raw number leaked: {token}"
# No diagnosis / medication names
for token in (
    "high blood pressure", "hypertension", "lisinopril",
    "ldl", "cholesterol",
):
    assert token.lower() not in block.lower(), f"sensitive label leaked: {token}"
# Qualitative signal is present
assert "sodium" in block.lower()
assert "ramen" in block.lower()           # via parsed meals[]
# And the block was actually wired into VIDEO_CALL_PROMPT at import time
assert block in VIDEO_CALL_PROMPT
```

### Test B — `load_demo_files()` does not leak health data

```python
from server import VoiceSession
session = VoiceSession.__new__(VoiceSession)
ctx = session.load_demo_files()
for token in ("blood pressure", "ldl", "lisinopril", "138", "152"):
    assert token.lower() not in ctx.lower()
```

### Test C — Graceful degrade with WHOOP subtree missing

Load a copy of `health.yaml` with the `whoop:` key deleted, point
`_load_health_context()` at it (e.g. via a `HEALTH_YAML_PATH` env var
the loader honors). Assert it still returns a non-empty block that
mentions the condition (qualitatively) and recent meals, and includes a
phrase like "WHOOP data unavailable."

### Test D — Live prompt regression: spoken output is privacy-safe

Extend the existing Beat 3 live prompt suite at `TESTING.md:1-30`:

1. Send a Chinese-menu fixture image (e.g. `demo_files/menu_zh.png`).
2. Send transcription: "What should I order from this menu?"
3. Assert the response:
   - contains exactly one English dish name from
     `demo_files/menu_zh_dishes.json`,
   - contains a "skip" / "instead of" / "over" connective,
   - does NOT contain any of: `blood pressure`, `hypertension`,
     `cholesterol`, `LDL`, `lisinopril`, `diagnosis`, or any digit
     from the bloodwork JSON,
   - includes a food-language reason
     (`salty`, `sodium`, `fried`, `heavy`, `lighter`, `richer`).

### Test E — Disclosure ladder

Three live prompt turns in sequence:

1. "What should I order?" — assert spoken text is privacy-safe per
   Test D.
2. "Why?" — assert response stays in food language; assert no medical
   labels.
3. "What do you know about my health?" — *now* allow medical category
   words ("blood pressure" is OK, raw digits still not), assert exactly
   one short sentence, assert it does not enumerate raw numbers.

### Test F — Import-time concatenation, hot-edit not picked up

```python
import importlib, prompts
first = prompts.VIDEO_CALL_PROMPT
# Mutating the YAML mtime alone does NOT change the live constant —
# the loader runs at import time. (This documents the trade-off; if a
# future change moves the loader to session init, this test moves too.)
import pathlib
pathlib.Path("demo_files/health.yaml").touch()
assert prompts.VIDEO_CALL_PROMPT == first
# Re-import IS what picks up new content (i.e. server restart).
importlib.reload(prompts)
assert isinstance(prompts.VIDEO_CALL_PROMPT, str)
```

### Test G — Real WHOOP OAuth (manual)

Manual smoke test, recorded as PASS/FAIL with output:

1. `export WHOOP_CLIENT_ID=… WHOOP_CLIENT_SECRET=…`
2. Open `https://localhost:8445/whoop/login`, complete consent.
3. Confirm `demo_files/health.yaml`'s `whoop.recovery.fetched_at` is
   within the last few minutes, and `demo_files/whoop_auth.json`
   exists with mode 600.
4. Re-run Test A; confirm summary still privacy-safe with live data.
5. Confirm `condition`, `bloodwork`, `meals`, `goals` subtrees in
   `health.yaml` are unchanged after the refresh.

## 14. Manual demo script

1. Spark is running on `https://localhost:8445`. WHOOP either live
   (Phase 3) or stubbed (Phase 1) — the demo wording is identical.
2. Phone is connected. Camera is on.
3. **Selena (narration):** "I uploaded my high-blood-pressure diagnosis,
   recent bloodwork, and WHOOP data to the Spark this morning. Now let's
   pretend I'm at a Taiwanese restaurant."
4. Selena holds the Chinese menu fully in frame.
5. **Selena (to agent):** "Hey Claw, what should I order?"
6. **Expected spoken response (one to two sentences, food-language only):**

   > "I'd go with the steamed sea bass over the salt-and-pepper pork
   > chop — the pork chop is deep-fried and pretty heavy on sodium today."

7. **Selena (callback):** "Did you tell anyone in the room I have high
   blood pressure?"
8. **Expected:** one-sentence affirmation that the diagnosis stayed on
   the box. The agent may now use the category word ("yep, your blood-
   pressure flag and your bloodwork stayed local — I just steered you
   toward something lighter").
9. **(Optional Q&A)** "What's my recovery today?" → answers
   qualitatively ("low — go easier"); only recites a number if the
   user says "what's the number."

## 15. Acceptance criteria

The plan is "done" when, in this order:

1. **Privacy-safe spoken output** — Tests A and D pass; across at least 3
   consecutive runs of the live prompt suite, the agent never spoke a
   diagnosis, medication, category word, or raw number in the default
   menu turn.
2. **Disclosure ladder** — Test E passes: "why?" stays food-language;
   "what do you know about my health?" surfaces a category word but no
   raw digits.
3. **Health-data tests** — Tests B, C, F pass under the project's
   existing python suite invocation.
4. **Story rewrite** — `prompts.py` no longer references "half marathon"
   or hard-codes yesterday's meal; that data is sourced from
   `demo_files/health/`.
5. **Graceful degrade** — disconnect the network, delete the WHOOP cache,
   keep the stub: Beat 3 still produces a coherent recommendation in
   under 4 seconds end-to-end.
6. **Grounded recommendation** — recommended dish is a translation of a
   visible menu item; skipped dish is also visible (Test D).
7. **WHOOP OAuth (optional, can ship after demo)** — Test G recorded as
   PASS in `TESTING.md`, with cache file timestamps verifying live data.
8. **Milestone closeout** — `MILESTONES.md` WHOOP entry updated to Done.

## 16. Out of scope (don't do)

- No refactor of `tools.py` dispatch.
- No new inline tool, no frontend toggle.
- No new top-level package (no `health/`); WHOOP goes in `clients/`,
  the loader goes in `prompts.py`.
- No intent-matcher in `server.py`.
- No `VoiceSession.__init__` change; injection is at module import time.
- No changes to ASR/TTS/VLM clients.
- No changes to Beats 1, 2, 4 prompts or routing.
- No persona-file edits in `~/.openclaw/workspace/`.
- No new database; flat files are sufficient for the demo lifetime.
- No multi-user support.
~~~~

### Task Planning (`task_plan.md`)

~~~~markdown
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
~~~~

### Findings (`findings.md`)

~~~~markdown
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
~~~~

### Progress (`progress.md`)

~~~~markdown
# Progress Log

## Session 2026-05-05 — write PLAN.md for Beat 3 health agent

### Phase 1 — Audit current code paths · complete
- Read `prompts.py`, `server.py` (lines 1-2330 sampled), `tools.py` (lines
  1-1083 sampled), `static/index.html` toggles, `MILESTONES.md`, and
  `TESTING.md`.
- Located the menu-beat block at `prompts.py:212-217` (LOCAL PRIVATE DEMO
  MEMORY).
- Identified `server.py:2173` as the system-prompt construction site and
  `server.py:2177` (face_context) as the precedent for context appending.
- Identified `is_workspace_update_request` at `server.py:1439` as the
  reference pattern for deterministic intent matchers (later
  superseded — final design uses always-on injection, no matcher).
- Confirmed `load_demo_files()` at `server.py:1695` would leak health data
  into the reasoning agent context unless explicitly skipped.

### Phase 2 — WHOOP API research · complete
- Pulled OAuth flow from developer.whoop.com/docs/developing/oauth.
- Pulled v2 endpoint list, exact scope strings, and key response fields
  from developer.whoop.com/api.
- Decision: use `offline` scope for refresh tokens; cache JSON per
  endpoint; redirect through `https://localhost:8445/whoop/callback` to
  satisfy WHOOP's `https://`-only redirect rule.

### Phase 3 — Architecture decision · complete
- Chose **hybrid** (context provider + intent injection + optional inline
  tool). See `findings.md` for rejected alternatives.
- Decided against extending `_load_claw_persona()` to keep privacy
  channels separate.

### Phase 4 — Write PLAN.md · complete
- Wrote `PLAN.md` (replaced prior planning placeholder).
- Includes: goal, audit summary, WHOOP summary, architecture decision,
  module layout, fake data shapes, prompt rewrites, server-side changes,
  inline tool spec, OAuth integration, six commit-sized phases, seven
  tests (A-G), manual demo script, eight acceptance criteria, out-of-scope
  list.

### Files changed this session
- `PLAN.md` — overwrote with the new health-agent plan.
- `task_plan.md` — created (planning-with-files skill).
- `findings.md` — created (planning-with-files skill).
- `progress.md` — created (this file).

### Errors encountered
None.

### Next session entry point
The plan is complete. Next session should begin Codex execution starting
with **Phase 1 (Data scaffolding)** in `PLAN.md` § 12. No re-planning
needed; if scope changes, update `PLAN.md` first, then add a new phase
table here.

---

## Session 2026-05-05 (cont.) — plan revisions after user review

User reviewed PLAN.md and pushed back on several over-engineered choices.
Multiple revision rounds applied.

### Revision 1 — privacy wording for demo
Demo *narration* mentions the uploaded high-BP diagnosis on stage; the
agent's *spoken output* must NOT name the diagnosis, the medication, or
raw numbers in the default path. Disclosure ladder added:
food-language → category word (on "why?") → numbers (on explicit
request). Spoken target updated to a food-only line:
"I'd go with the steamed sea bass over the salt-and-pepper pork chop —
the pork chop is deep-fried and pretty heavy on sodium today."
Forbidden-terms list added in findings.md.

### Revision 2 — architecture simplification
Original plan had three coupled paths for one fact (intent matcher +
conditional injection + separate `get_health_context` tool + frontend
toggle). User flagged this as overkill. Collapsed to **always-on prompt
injection**: the health summary is built once and concatenated into
`VIDEO_CALL_PROMPT`. No intent matcher. No new inline tool. No frontend
toggle. Drop `health/intents.py`. The VLM gets the same context for any
health-shaped question (menu, sleep, workout) and prompt rules govern
when to use it.

### Revision 3 — file format collapse
User pushed back on JSON for everything, then on the JSON+markdown mix.
Final: **one flat `demo_files/health.yaml`** holding condition,
bloodwork, meals, goals, and the WHOOP subtree. WHOOP refresh job
replaces only the `whoop:` subtree. Tokens stay in a separate gitignored
file (renamed to `demo_files/whoop_auth.json` later in the session) with
chmod 600. PyYAML added to `requirements.txt`.

### Revision 4 — module placement (the big one)
User asked why `whoop.py` wasn't in `clients/` (where asr/llm/tts/vlm/
face/claw_acp already live), and why `context.py` was a separate module
when `prompts.py:_load_claw_persona()` was already the precedent for
file-backed prompt injection. Both correct.

Final placement:
- `clients/whoop.py` — sits with the other external-service clients.
- `_load_health_context()` — function in `prompts.py` next to
  `_load_claw_persona()`, concatenated onto `VIDEO_CALL_PROMPT` at
  module import time.
- No top-level `health/` package. No `VoiceSession.__init__` change.

Trade-off accepted: server restart required to pick up fresh WHOOP data.
For demo cadence that's fine. Migration path noted (move loader to
session init) if hot-refresh is ever required.

### Revision 5 — naming
`health_tokens.json` → `whoop_auth.json` across PLAN.md, findings.md,
task_plan.md. More accurate (it's WHOOP OAuth credentials, not health
data) and scales naturally for future services.

### Process meta-feedback
User pointed out that the misses in the original plan
(`clients/`-precedent, `_load_claw_persona`-precedent) would have
caused AI bloat if Codex had run autonomously. Captured as:

1. Auto-memory at
   `~/.claude/projects/-home-nvidia-selena-projects-spark-realtime-chatbot/memory/feedback_audit_before_design.md`
   plus `MEMORY.md` index — feedback memory: explicit pattern-audit pass
   required before any new file/module/package.
2. `~/selena/CLAUDE.md` — auto-loaded into context for every project
   under `selena/`. Hard rule: pattern audit before design. Default
   placements (`clients/`, `prompts.py` siblings, session-class methods,
   `demo_files/`). "Don't add when not needed" list. Plan output shape
   requirement.

### Codex plugin setup
Installed `codex` plugin from `openai/codex-plugin-cc` marketplace.
`/codex:setup` reports ready: Node 22.22.2, npm 10.9.7, Codex CLI
0.125.0, ChatGPT login active. Review gate disabled. Plugin's
`task --write` mode gives `workspace-write` sandbox, which is the
recommended autonomy level for executing PLAN.md. The dangerous
`--dangerously-bypass-approvals-and-sandbox` flag is NOT exposed by
the plugin's wrapper (only direct `!codex …` invocation can pass it
through, and is unnecessary here since the work stays inside the
project workspace).

### Files changed in this revision pass
- `PLAN.md` — substantial rewrite: §4 architecture, §5 module layout,
  §6 data model collapsed to YAML, §7 prompt rules updated for privacy
  ladder, §8 server changes shrunk to just the `load_demo_files` filter,
  §9 dropped tool/toggle entirely, §10 paths updated to `clients/whoop`,
  §12 phase list collapsed, §13 tests updated.
- `findings.md` — added "Architecture simplification (2026-05-05
  revision)", "Module placement", "File-format collapse", and detailed
  privacy/forbidden-terms section.
- `task_plan.md` — Decisions block rewritten to reflect the final
  design.
- `~/selena/CLAUDE.md` — created (cross-project norms).
- `~/.claude/projects/-home-nvidia-selena-projects-spark-realtime-chatbot/memory/{feedback_audit_before_design.md,MEMORY.md}` — created.

### Errors encountered
None. All revisions landed cleanly.

### Next session entry point (revised)
Plan is final. Next session executes `PLAN.md` §12 phases via
`/codex:rescue` with `task --write`, one phase per Codex turn,
committing after each. No re-planning needed unless something in the
existing repo has shifted under us — re-run the Pattern Audit
(per `~/selena/CLAUDE.md`) at the top of Phase 1 just to confirm.

---

## Session 2026-05-05 — implement PLAN.md phases 1-4

### Phase 1 — Data scaffolding · complete

Built the flat private health data scaffold in `demo_files/health.yaml`, added `PyYAML` to `requirements.txt`, added `demo_files/whoop_auth.json` to `.gitignore`, and created the Chinese-menu grounding fixtures `demo_files/menu_zh.png` and `demo_files/menu_zh_dishes.json`. Tests run: `.venv-gpu/bin/python -m pip install PyYAML` (already satisfied), `git check-ignore -v demo_files/whoop_auth.json`, a `.venv-gpu` YAML/PNG/JSON validation heredoc, and `git diff --check` on the Phase 1 text files; all passed. Commit: `6266481 [feat] add fake local health data for Beat 3`.

### Phase 2 — Prompt loader and always-on injection · complete

Built `prompts._load_health_context()` as a sibling to `_load_claw_persona()`, added qualitative health/WHOOP/meal summaries from `demo_files/health.yaml`, concatenated the speech-safe block into `VIDEO_CALL_PROMPT` at import time, replaced the hard-coded half-marathon/ramen memory with privacy-safe menu behavior, and added the explicit `health.yaml` / `whoop_auth.json` skip guard to `VoiceSession.load_demo_files()`. Tests run: `.venv-gpu/bin/python -m py_compile prompts.py server.py`, Test A speech-safe loader, Test B demo-file isolation, Test C missing-WHOOP graceful degrade via `HEALTH_YAML_PATH`, Test F import-time concatenation, a hard-code removal `rg`, and `git diff --check`; all passed. Commit: `b5aa9d8 [feat] inject always-on private health context into VLM prompt`.

### Phase 3 — WHOOP OAuth · skipped

Skipped Phase 3 because both `WHOOP_CLIENT_ID` and `WHOOP_CLIENT_SECRET` were unset in the runtime environment. Tests run: `.venv-gpu/bin/python` environment check for `WHOOP_CLIENT_ID` and `WHOOP_CLIENT_SECRET`; both reported unset, so no WHOOP client, routes, credential file, or credential write were created. Commit: none because the phase was intentionally skipped and produced no code changes.

### Phase 4 — Tests and milestone closeout · complete

Updated `TESTING.md` with the Beat 3 health-context tests and live Chinese-menu regression result, marked the WHOOP Integration milestone Done in `MILESTONES.md`, and added the `fried pork chop(s)` translation variant to `demo_files/menu_zh_dishes.json` after the live model translated `椒盐猪排` that way. Tests run: `.venv-gpu/bin/python -m py_compile prompts.py server.py`, Tests A, B, C, D, and F, fixture alias validation, WHOOP credential-gate check, and `git diff --check`; all passed. One harness-only syntax error occurred on the first Test D heredoc attempt, then the corrected harness passed; the first strict fixture assertion also showed the translation variant, which was resolved by adding the alias rather than changing product behavior. Commit: `bffb71e [docs] record WHOOP/health-context milestone completion`.

---

## Session 2026-05-05 — reopen Phase 3 after WHOOP credentials were set

### Phase 3 — WHOOP OAuth · complete

Reopened Phase 3 after `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET`, and `WHOOP_REDIRECT_URI=https://localhost:8443/whoop/callback` were present via `source ~/.bashrc`. Built `clients/whoop.py` with auth URL generation, code exchange, refresh-token support, WHOOP v2 endpoint fetches, normalized cache writing to only the `whoop:` subtree of `demo_files/health.yaml`, and chmod `600` auth token storage in `demo_files/whoop_auth.json`; added `/whoop/login` and `/whoop/callback` routes in `server.py` gated behind the env vars; documented setup, scopes, and refresh usage in `README.md`; and updated `TESTING.md` / `MILESTONES.md`. Tests run: `py_compile` for `clients/whoop.py` and `server.py`, auth URL config check, temp YAML/token writer check, route registration check, login redirect check, `git diff --check`, and a final absence check for `demo_files/whoop_auth.json`; all passed. Manual browser consent is still pending. Commit: `6ae6520 [feat] add WHOOP OAuth flow with local cache and stub fallback`.

### Relative meal metadata cleanup · in progress

Changed the meal metadata schema from fixed ISO dates to relative `when:` labels so the demo story stays fresh across recording days. The loader remains backward-compatible with old `date:` fields and normalizes strings like `2 days ago` to digit-free prompt text. The committed `health.yaml` change was staged from the HEAD blob so refreshed live WHOOP values remain local-only.

### Scheduled WHOOP refresh and dummy fallback · complete

Added `scripts/refresh-whoop.sh` as the cron-safe refresh wrapper, with `flock` locking, `~/.bashrc` env loading, `python -m clients.whoop --refresh`, and `touch prompts.py` for uvicorn reload. Split health data so local live WHOOP cache is `demo_files/health.yaml` (gitignored) and the committed scripted fixture is `demo_files/health-dummy-data.yaml`, including the morning-run / jetlag demo story. Installed a daily `06:00` system-local crontab entry that appends to `logs/whoop-refresh.log`. Tests run: `py_compile` for `prompts.py` and `clients/whoop.py`, `bash -n scripts/refresh-whoop.sh`, dummy explicit source check, dummy fallback check, live writer header check, and `git diff --check`; all passed. Commit: `9bcc29b [feat] add scheduled WHOOP refresh and dummy health fallback`.
~~~~
