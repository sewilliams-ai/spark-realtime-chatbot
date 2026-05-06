# Findings - Computex Demo Beats Refresh

## Planning Context Restored

- The completed bidirectional handoff plan was still present in root
  `task_plan.md`, `findings.md`, and `progress.md`, but it has already been
  archived at `.planning/archive/2026-05-06-bidirectional-conversation-handoff/`.
- The planning catch-up script produced no unsynced context output.
- Current git status before planning showed only pre-existing untracked local
  files: `.codex`, `AGENTS.md`, and `workspace/*`.

## Current Hard-Coded Demo Beats

### Cold Open

- `prompts.py:412` explicitly instructs the assistant to answer camera/audio
  readiness with wording like "Yep. You're on camera, audio is clear, and I'm
  ready."
- `bench/test_demo_prompts.py:85-103` tests this cold-open behavior.
- This remains aligned with the new Computex script and should stay.

### Old Beat 1 - Whiteboard README + Redis Judgment

- `prompts.py:417` describes `markdown_assistant` as the tool for converting a
  diagram/whiteboard into markdown/README.
- `prompts.py:421-424` hard-codes README and `realtime_design.md` examples.
- `prompts.py:447` hard-codes the exact React Dashboard -> FastAPI -> MySQL
  improvement answer: polling MySQL will not scale, add Redis pub/sub, then
  use `markdown_assistant` for `realtime_design.md`.
- `prompts.py:581-582` in `MARKDOWN_ASSISTANT_PROMPT` hard-codes README and
  realtime design document sections.
- `server.py:1530-1539` maps tasks containing "readme" to `README.md` and
  realtime/Redis terms to `realtime_design.md`.
- `bench/test_demo_prompts.py:106-163` tests the old README, improvement, and
  realtime follow-up flow.
- `TESTING.md:168-177`, `TESTING.md:252-253`, and later historical sections
  record these as active checks.
- `README.md:233-234` still lists Whiteboard -> README and architecture review
  as things to try.

### Old Beat 2 - Fashion Check

- `prompts.py:413` embeds video-call outfit-check behavior in the main
  `VIDEO_CALL_PROMPT`, including "despite the late-night coding."
- `prompts.py:469-483` includes a fashion template with the same video-call
  outfit guidance.
- The `VISION_TEMPLATE_PROMPTS` dictionary appears unused by current frontend
  code, but stale demo wording there can still confuse future prompt work.
- `bench/test_demo_prompts.py:166-181` tests fashion as Beat 2.
- `TESTING.md:179-180`, `TESTING.md:465`, and fashion-specific historical
  sections record this as a demo behavior.

### Old Beat 3 - Private Menu

- `prompts._load_health_context()` at `prompts.py:318-337` returns the private
  health prompt block. It still includes a generic example phrase
  "after yesterday's ramen" at `prompts.py:330`.
- `prompts.py:449-455` contains active private health/menu behavior:
  health-shaped questions use private context, Chinese menus are silently
  translated, and recommendations must use visible menu items without spoken
  private labels or raw numbers.
- `demo_files/health-dummy-data.yaml` contains the current dummy health,
  recent meals, jetlag/run, and WHOOP values. It already supports the new
  restaurant-menu beat.
- `bench/test_demo_prompts.py:184-211` tests the private menu recommendation.
- This beat remains, but it moves from old Beat 3 to new Beat 2 and should be
  rewritten around the Computex/Taipei dinner story.

### Old Beat 4 - Handwritten Todos + Umbrella

- `prompts.py:418` describes `workspace_update_assistant` as routing
  handwritten todos to `project_dashboard/tasks.md`, `realtime_design.md`,
  and `personal_todos.md`.
- `prompts.py:426-430` hard-codes the old handwritten list, including
  "add streaming updates", "Redis pub/sub", "write events table",
  "React hook", "test reconnect", and "buy umbrella".
- `prompts.py:430` hard-codes the spoken acknowledgment about the
  React/FastAPI/MySQL project dashboard.
- `server.py:1587-1628` extracts old handwritten todo items and falls back to
  that exact list when the user says "add these to the project."
- `server.py:1639-1656` normalizes old todo wording, including "buy umbrella".
- `server.py:1658-1669` routes "umbrella" and other personal keywords to
  personal todos.
- `server.py:1671-1686` detects old Beat 4 handwritten-note commands before
  VLM tool roundtrip.
- `server.py:1710-1757` writes old Beat 4 sections into
  `project_dashboard/tasks.md`, `realtime_design.md`, and
  `personal_todos.md` using `spark-beat4-*` markers.
- `server.py:2491-2500` has a VLM image-branch short-circuit for old Beat 4
  with the hard-coded React/FastAPI/MySQL acknowledgement.
- `server.py:2597-2599` repeats the same acknowledgement when the model calls
  `workspace_update_assistant`.
- `bench/test_demo_prompts.py:214-238` tests old Beat 4 handwritten todos.
- `TESTING.md:185-187`, `TESTING.md:240-283`, and later sections record old
  Beat 4 as an active regression.
- Untracked generated workspace files currently contain old Beat 4 output:
  `workspace/realtime_design.md`, `workspace/project_dashboard/tasks.md`, and
  `workspace/personal_todos.md`.

## Existing Tool And Agent Surfaces

- `tools.py:37` defines `ALL_TOOLS`. Current tool names are:
  `read_file`, `write_file`, `list_files`, `run_python`, `web_search`,
  `remember_fact`, `recall_fact`, `add_todo`, `list_todos`, `complete_todo`,
  `claw_recall`, `claw_remember`, `send_telegram`, `ask_claw`,
  `markdown_assistant`, `workspace_update_assistant`, and
  `reasoning_assistant`.
- `static/index.html:345-347` already has an `html_assistant` checkbox, and
  `server.py:1864-1927` already implements `execute_html_agent()`, but
  `tools.py` has no `html_assistant` schema or sentinel. If Beat 1 should
  visibly build an MVP artifact, exposing this existing executor is the
  leanest path.
- `server.py:1062-1450` runs the main LLM/tool loop for text/voice messages.
  It already has UI-agent handling for `markdown_assistant`,
  `reasoning_assistant`, and `workspace_update_assistant`.
- `server.py:2487-2726` runs the video-call image path. It includes the old
  Beat 4 short-circuit before regular VLM/tool handling.
- `prompts.py:28-55` has `CLAW_DEMO_MODE`, which makes non-wired real-world
  actions sound confidently done and strips `ask_claw` from tool definitions.
  For a rock-solid demo, prefer concrete local workspace artifacts over
  pretending an email was sent unless the user intentionally runs demo mode.

## Workspace State

Current untracked workspace artifacts are from the previous script:

- `workspace/README.md`: old agent dashboard README generated from a sketch.
- `workspace/realtime_design.md`: old Redis pub/sub realtime design plus
  `spark-beat4-realtime-followup`.
- `workspace/project_dashboard/tasks.md`: old handwritten engineering tasks.
- `workspace/personal_todos.md`: old "Buy umbrella" personal todo.

The repo tracks only `workspace/.gitkeep`; generated workspace files are local
scratch artifacts. It is appropriate to remove or regenerate them as part of
the implementation cleanup phase.

## Recommended New Demo Data

To avoid putting the new executive-assistant story directly into the prompt,
use a single flat YAML fixture if deterministic memory is needed:

```yaml
# demo_files/computex-demo.yaml - DUMMY DATA FOR DEMO/TESTING ONLY.
relationship_memory:
  partner_label: husband
  past_taipei_gift: pineapple cakes
  recommended_taipei_gift: high mountain oolong tea
team:
  - name: Avery
    role: hardware partnerships
  - name: Morgan
    role: product strategy
  - name: Riley
    role: engineering lead
dinner_context:
  default_meeting: strategic alignment dinner with hardware partners
  default_action_theme: prioritize the partner-facing MVP path
```

If added, load it through `_load_computex_demo_context()` in `prompts.py`,
sibling to `_load_health_context()`, and append it to `VIDEO_CALL_PROMPT`.
This mirrors the existing prompt-loader pattern and keeps the new memory
editable without another package.

## Recommended Implementation Shape

- Keep cold open as-is.
- Replace the old Beat 1 exact README/Redis flow with "MVP brief/scaffold from
  sketch." Make the reliable baseline a markdown artifact such as
  `workspace/mvp_brief.md` or `workspace/agent_dashboard_mvp.md`. Expose the
  existing HTML assistant only if we want a visual prototype and can test it.
- Keep private menu logic, but rewrite the prompt/test around the Computex
  story: Chinese menu, private health data, WHOOP/recent meals, no spoken
  private labels/numbers.
- Replace old Beat 4 handwritten routing with new executive update routing:
  team update/action items plus personal souvenir todo. Prefer local
  `workspace/team_update.md` / `workspace/executive_brief.md` artifacts and
  `personal_todos.md` over real email integration in P0.
- If the user later wants real sending, add/configure a real outbound channel
  after the script is stable. Current `send_telegram` can send if a bot and
  chat/alias are configured; there is no SMTP/email client in the repo.

## Open Product Decision For Implementation

The script says "sends an email." The repo does not currently have a real
email tool. P0 should choose one of these before implementation:

1. **Recommended for stability:** create a local `workspace/team_update.md`
   artifact and speak "Drafting the email now." This is honest and inspectable.
2. **Demo-mode theater:** with `CLAW_DEMO_MODE=1`, speak as if sent. This is
   less inspectable and should not be the only proof point.
3. **Real outbound:** wire SMTP or configure a Telegram/team alias. This is
   more work and more failure-prone than the beat requires.

## Risks

- The current demo behaviors are spread across prompt text, server helper
  methods, tool schemas, prompt tests, docs, and local workspace artifacts.
  Removing only one layer will leave stale old-beat behavior.
- `CLAW_DEMO_MODE` can hide gaps by speaking as if real actions happened.
  Useful for theater, risky for debugging. Tests should run in normal mode
  unless explicitly validating demo-mode wording.
- Adding a new top-level module for demo orchestration would be avoidable
  bloat. Existing `prompts.py`, `server.py`, `tools.py`, and `workspace/`
  are the right homes.
- The model may over-say private health details in the menu beat unless
  prompt tests continue asserting forbidden terms and raw digits.
- The "MVP" beat can become too ambitious if it requires full autonomous code
  generation live. The plan should guarantee a brief/scaffold first, then
  optionally add the HTML prototype path once stable.
