#!/usr/bin/env python3
"""Deterministic Computex workspace routing checks.

Run:
  .venv-gpu/bin/python bench/test_computex_workspace.py
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import asyncio
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server
from tools import ALL_TOOLS, execute_tool, is_agent_tool


def main() -> int:
    assert "html_assistant" in ALL_TOOLS
    assert "codebase_assistant" in ALL_TOOLS
    assert is_agent_tool("html_assistant")
    assert is_agent_tool("codebase_assistant")
    assert is_agent_tool("workspace_update_assistant")
    sentinel = json.loads(asyncio.run(execute_tool("codebase_assistant", {
        "task": "Build this sketch into a working MVP",
        "context": "Agent Monitor UI to FastAPI dashboard to Task History database",
        "output_dir": "../agent_monitor_mvp",
    })))
    assert sentinel["agent_type"] == "codebase_assistant"
    assert sentinel["output_dir"] == "../agent_monitor_mvp"

    with TemporaryDirectory() as tmp:
        server.WORKSPACE_ROOT = Path(tmp).resolve()
        session = server.VoiceSession.__new__(server.VoiceSession)

        assert session.infer_markdown_output_path(
            "Turn this Agent Workbench sketch into an MVP brief"
        ) == "mvp_brief.md"
        assert session.infer_markdown_output_path(
            "Draft the team update from dinner"
        ) == "team_update.md"

        codebase_dir = session.resolve_workspace_codebase_dir("../Agent Monitor MVP!")
        assert codebase_dir == Path(tmp).resolve() / "workspace" / "agent_monitor_mvp"
        run_dir = session.resolve_mvp_run_dir()
        assert "test_assets/mvp-generation-runs" in str(run_dir.relative_to(Path(tmp).resolve()))

        prompt = session.build_codebase_agent_prompt(
            "Build this diagram into a working MVP",
            "Agent Monitor UI -> Agent Dashboard FastAPI -> Task History database",
            codebase_dir,
            run_dir,
        )
        assert "Qwen3.6" in prompt
        assert "Work only inside this directory" in prompt
        assert "Do not edit the Spark realtime chatbot repo" in prompt
        assert "Output exactly these files: app.py, task_history.json, mvp_brief.md" in prompt
        assert "Treat sparse hand-drawn sketches as product intent" in prompt
        assert "polished 2026 SaaS operations dashboard" in prompt
        assert "<<<FILE: app.py>>>" in prompt
        assert "Do not create AGENTS.md" in prompt
        assert "Do not create frontend/, backend/, database/" in prompt
        assert not hasattr(session, "run_codex_codebase_turn")
        assert server._codebase_preview_path("agent_monitor_mvp") == "/generated/agent_monitor_mvp/"
        rewritten = server._rewrite_codebase_preview_content(
            b'<script>fetch("/api/tasks"); fetch(`/api/status`)</script>',
            "text/html; charset=utf-8",
            "agent_monitor_mvp",
        ).decode("utf-8")
        assert '"/generated/agent_monitor_mvp/api/tasks' in rewritten
        assert "`/generated/agent_monitor_mvp/api/status" in rewritten

        blocks = """<<<FILE: app.py>>>
from fastapi import FastAPI
app = FastAPI()
<<<END FILE>>>
<<<FILE: task_history.json>>>
[]
<<<END FILE>>>
<<<FILE: mvp_brief.md>>>
# MVP Brief

## Architecture

FastAPI plus JSON.
<<<END FILE>>>
<<<FILE: README.md>>>
ignored
<<<END FILE>>>
"""

        codebase_dir.mkdir(parents=True)
        generated_files, parse_errors = session.write_qwen_codebase_files(codebase_dir, blocks)
        assert generated_files["app"] == "workspace/agent_monitor_mvp/app.py"
        assert any("README.md" in error for error in parse_errors), parse_errors
        assert not (codebase_dir / "README.md").exists()
        (codebase_dir / "task_plan.md").write_text("extra\n", encoding="utf-8")
        (codebase_dir / "AGENTS.md").write_text("extra\n", encoding="utf-8")
        removed = session.prune_codebase_workspace(codebase_dir)
        assert "task_plan.md" in removed
        assert "AGENTS.md" in removed
        assert not (codebase_dir / "task_plan.md").exists()
        files = session.summarize_codebase_files(codebase_dir)
        assert session.codebase_has_required_files(codebase_dir)
        evaluation = session.write_codebase_eval_summary(
            run_dir,
            codebase_dir,
            files,
            "agent stdout",
            "",
            0,
            {"status": "SKIP", "reason": "unit test"},
            {"status": "PASS", "preview_path": "/generated/agent_monitor_mvp/"},
        )
        assert evaluation["codebase_path"] == "workspace/agent_monitor_mvp"
        assert evaluation["preview"]["status"] == "PASS"
        assert evaluation["run_dir"].startswith("test_assets/mvp-generation-runs/")
        assert all(check["status"] == "PASS" for check in evaluation["checks"]), evaluation
        assert (run_dir / "SUMMARY.md").exists()
        assert not (Path(tmp).resolve() / "docs" / "test-results").exists()

        request = (
            "Update my team: the strategic alignment dinner went amazing. "
            "Hardware partners agreed to invest if we prioritize the partner-facing MVP. "
            "Assign action items and save a todo to buy pineapple cakes for my husband."
        )
        assert session.is_workspace_update_request(request)
        sketch_request = (
            "Please convert this sketch to an MVP. "
            "I'm going to dinner, write me a briefer review when I get back."
        )
        assert session.is_codebase_build_request(sketch_request)
        assert not session.is_workspace_update_request(sketch_request)
        session.conversation_history = [
            {"role": "user", "content": "Hey Claude, please turn the sketch into an MVP."},
            {"role": "assistant", "content": "On it."},
        ]
        split_followup = "Thanks, I'm going to dinner write me a brief to review for when I get back"
        assert session.is_codebase_brief_followup_request(split_followup)
        assert not session.is_workspace_update_request(split_followup)
        departure_followup = "Thanks. I'm going to head to dinner, but..."
        assert session.is_codebase_brief_followup_request(departure_followup)
        assert not session.is_workspace_update_request(departure_followup)
        assert session.is_codebase_brief_followup_request("Save a brief for me.")
        assert not session.is_workspace_update_request("Dinner was fun; write me a brief when I get back")
        assert not session.is_workspace_update_request("Add these to the project")
        partial_fragment = "Awesome. Please turn."
        assert session.is_incomplete_codebase_fragment(partial_fragment)
        assert not session.is_incomplete_codebase_fragment("Please turn the camera")
        session._pending_codebase_fragment = partial_fragment
        combined_request = session.codebase_intent_text("diagram into a front-end MVP.")
        assert session.is_codebase_build_request(combined_request)
        assert not getattr(session, "_pending_codebase_fragment", "")

        todos = session.extract_workspace_todos("Update my team", request, [])
        assert any("Avery" in item for item in todos), todos
        assert any("Morgan" in item for item in todos), todos
        assert any("Riley" in item for item in todos), todos
        assert any("oolong" in item.lower() for item in todos), todos
        string_items = session.extract_workspace_todos(
            "Draft update",
            "Dinner was strong.",
            '["Avery: follow up", "Personal: Buy high mountain oolong tea for husband"]',
        )
        assert any("husband" in item.lower() for item in string_items), string_items

        result = session.apply_workspace_todo_updates(todos, "Update my team", request)
        root = Path(tmp)
        team = (root / result["files"]["team_update"]).read_text()
        brief = (root / result["files"]["executive_brief"]).read_text()
        personal = (root / result["files"]["personal_todos"]).read_text()
        joined = team + brief + personal

        assert "Hardware partners" in team
        assert "Agent Workbench" in brief
        assert "high mountain oolong tea" in personal
        assert "spark-computex-team-update" in team
        assert "spark-computex-executive-brief" in brief
        assert "spark-computex-personal-todos" in personal
        for stale in ("spark-beat4", "Buy umbrella", "Redis pub/sub"):
            assert stale not in joined, stale

    print("computex workspace routing: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
