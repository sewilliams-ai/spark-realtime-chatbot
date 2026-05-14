# Computex Demo Script

This is the current canonical demo script for Spark Realtime Chatbot. Keep this
file in sync with prompt/tool behavior so future sessions can recover the demo
story after context compaction.

## Demo Overview

Spark is a local, realtime, multimodal agent that can see, hear, reason over
private context, use tools, preserve conversation across devices, and create
local artifacts. The Computex story moves from desktop productivity, to mobile
private health help, to executive follow-up, then back to desktop review.

## Diagram Prop For Beat 1

Show a simple whiteboard-style Agent Monitoring MVP sketch:

```text
Agent Monitor UI  ->  Agent Dashboard FastAPI  ->  Task History database
                           |
                           v
                      Activity Feed
```

Recommended labels:

- Agent Monitor: React dashboard, start/pause agents, live status cards.
- Agent Dashboard: FastAPI backend, WebSocket updates, agent task router.
- Task History: database, events and runs, audit trail.
- Activity Feed: recent events, errors/retries, completed tasks.
- MVP checklist: overview cards, agent list, run history, activity feed.

The generated local test image is recreated by
`bench/test_whiteboard_image_prompt.py` at
`test_assets/agent_workbench_whiteboard.png`.

## Cold Open - Desktop

User:

> Hey, am I on camera?

Agent:

> Yep. You're on camera, audio is clear, and I'm ready.

Unlock: establishes realtime voice and vision before the real demo starts.

## Beat 1 - Whiteboarding / Productivity - Desktop

User shows the Agent Monitoring MVP sketch and says:

> Hey Claw, please turn this sketch into an MVP. I'm going to dinner; write me
> a brief to review for when I get back.

Target behavior:

- Agent acknowledges briefly:
  > On it.
- Agent calls `html_assistant` and streams a self-contained HTML prototype of the
  Agent Monitoring dashboard into the live preview panel.
- The prototype includes:
  - the visible dashboard panels (overview cards, agent list, run history,
    activity feed),
  - inline CSS for a polished look,
  - minimal vanilla JavaScript for the interactive controls.

Unlock: Spark is a vision-enabled local agent that turns a simple sketch into a
visual prototype the audience can see immediately.

> **Follow-up (out of scope for this branch):** the `html_assistant` handler
> currently streams the prototype to the live UI only. Persisting the HTML to
> `workspace/agent_monitor_mvp.html` and writing a companion `mvp_brief.md` so
> Beat 4 has files to review is tracked as a follow-up task. Until that lands,
> Beat 4's artifact list below still references the legacy codebase artifacts.

## Beat 2 - Restaurant Menu Ordering - Mobile

User hands a Chinese menu to the audience or camera and says:

> Hey Claw, what should I order?

Target behavior:

- Agent recommends visible translated menu items.
- Recommendation uses private local health context, recent meals, travel, and
  WHOOP-style signals.
- Spoken answer must not mention diagnosis names, medication names, sensitive
  category labels, or raw numeric values.

Example:

> I'd go with the steamed fish and greens over the fried chicken cutlet because
> those are lighter after your recent heavy meals.

Unlock: local private context makes recommendations personal without sending
sensitive health data away.

## Beat 3 - Executive Assistant - Mobile

After dinner, user says:

> Claw, update my team: the strategic alignment meeting went amazing. Our
> hardware partners agreed to invest if we prioritize the partner-facing MVP.
> Send this update to my team, assign action items based on my org chart, and
> save a todo to buy pineapple cakes for my husband.

Target behavior:

- Agent writes local team-update/action-item artifacts.
- Agent uses local gift memory and says:
  > Drafting the team update now. You got him pineapple cakes last year; maybe
  > try high mountain oolong tea this time.

Unlock: Spark acts as an executive assistant with local organization and
relationship memory.

## Beat 4 - Back Home Review - Desktop

User hands the live conversation back to desktop and reviews generated local
artifacts:

- `workspace/agent_monitor_mvp/app.py`
- `workspace/agent_monitor_mvp/task_history.json`
- `workspace/agent_monitor_mvp/mvp_brief.md`
- `workspace/team_update.md`
- `workspace/executive_brief.md`
- `workspace/personal_todos.md`

Unlock: Spark is a multi-interface, context-preserving, local agent for work,
health, and personal follow-through.

## Reliability Notes

- Keep the diagram visually simple and text labels large.
- Ask for a brief only when you only want `mvp_brief.md`.
- Keep generated workspace output flat: no separate frontend/backend/database
  directory tree unless a later demo explicitly needs it.
