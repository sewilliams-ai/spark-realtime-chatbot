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
        assert "Work only inside this directory" in prompt
        assert "Do not edit the Spark realtime chatbot repo" in prompt
        assert "app.py, task_history.json, mvp_brief.md" in prompt
        assert "Do not create AGENTS.md" in prompt
        assert "Do not create frontend/, backend/, database/" in prompt

        codebase_dir.mkdir(parents=True)
        (codebase_dir / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
        (codebase_dir / "task_history.json").write_text("[]\n", encoding="utf-8")
        (codebase_dir / "mvp_brief.md").write_text("# MVP Brief\n\n## Architecture\n\nFastAPI plus JSON.\n", encoding="utf-8")
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
        )
        assert evaluation["codebase_path"] == "workspace/agent_monitor_mvp"
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
        assert not session.is_workspace_update_request("Add these to the project")

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
