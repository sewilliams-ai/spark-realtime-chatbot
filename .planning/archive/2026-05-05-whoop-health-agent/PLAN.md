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
