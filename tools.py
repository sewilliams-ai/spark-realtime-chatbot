"""Tool definitions and execution for OpenAI-compatible tool calling."""

import json
from typing import Any, Dict, List


# Available tools (OpenAI format) - registry of all possible tools
ALL_TOOLS = {
    # Agents (complex workflows)
    "markdown_assistant": {
        "type": "function",
        "function": {
            "name": "markdown_assistant",
            "description": "A markdown documentation assistant that writes README files, design docs, guides, and other markdown documents into the shared workspace/ scratch folder. Use this when the user asks to convert a diagram, whiteboard, notes, or design into markdown.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The documentation task description, e.g. 'Write a README for my project' or 'Create API documentation for the user service'"
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional context about the project or topic to document"
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional relative markdown path inside workspace/. Use 'README.md' for a project README and 'realtime_design.md' for a realtime architecture sketch."
                    }
                },
                "required": ["task"]
            }
        }
    },

    "workspace_update_assistant": {
        "type": "function",
        "function": {
            "name": "workspace_update_assistant",
            "description": "Updates multiple files in the shared workspace/ scratch folder from handwritten notes or todos. Use this when the user says to add notes, todos, or action items to the project, especially when some items belong in project_dashboard/tasks.md, realtime_design.md, and personal_todos.md. Do not use markdown_assistant for multi-file todo routing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The workspace update request, e.g. 'Add these handwritten todos to the project'"
                    },
                    "context": {
                        "type": "string",
                        "description": "Visible handwritten notes or extracted todo items, plus any relevant project context"
                    },
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional extracted todo items from the visible note"
                    }
                },
                "required": ["task"]
            }
        }
    },

    # Nemotron-powered reasoning agent
    "reasoning_assistant": {
        "type": "function",
        "function": {
            "name": "reasoning_assistant",
            "description": "ONLY use for customer data and feature prioritization questions. Has LOCAL DATA FILES with customer feedback and feature requests. Use ONLY when user asks about: customer feedback, feature requests, what to build, prioritization, or roadmap vs customer data. DO NOT use for architecture, system design, caching, performance, or technical questions - answer those directly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "problem": {
                        "type": "string",
                        "description": "The customer data question - e.g. 'What features should we prioritize?' or 'What are customers asking for?'"
                    },
                    "context": {
                        "type": "string",
                        "description": "Any roadmap or plan visible (whiteboard) to compare against customer data. Leave empty if just asking about customer data."
                    },
                    "analysis_type": {
                        "type": "string",
                        "enum": ["general", "comparison", "prioritization", "planning"],
                        "description": "Type: 'prioritization' for feature questions, 'comparison' for roadmap vs customer data"
                    }
                },
                "required": ["problem"]
            }
        }
    },
}


def get_enabled_tools(enabled_tool_ids: List[str]) -> List[Dict[str, Any]]:
    """Get list of tool definitions for enabled tool IDs."""
    tools = []
    for tool_id in enabled_tool_ids:
        if tool_id in ALL_TOOLS and ALL_TOOLS[tool_id] is not None:
            tools.append(ALL_TOOLS[tool_id])
    return tools


async def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    """Execute a tool and return the result as a string."""
    if tool_name == "markdown_assistant":
        task = arguments.get("task", "")
        context = arguments.get("context", "")
        output_path = arguments.get("output_path", "")
        return json.dumps({
            "agent_type": "markdown_assistant",
            "task": task,
            "context": context,
            "output_path": output_path,
            "status": "initiated"
        })

    elif tool_name == "reasoning_assistant":
        # Nemotron-powered reasoning agent
        problem = arguments.get("problem", "")
        context = arguments.get("context", "")
        analysis_type = arguments.get("analysis_type", "general")
        return json.dumps({
            "agent_type": "reasoning_assistant",
            "problem": problem,
            "context": context,
            "analysis_type": analysis_type,
            "status": "initiated"
        })

    elif tool_name == "workspace_update_assistant":
        task = arguments.get("task", "")
        context = arguments.get("context", "")
        items = arguments.get("items", [])
        return json.dumps({
            "agent_type": "workspace_update_assistant",
            "task": task,
            "context": context,
            "items": items if isinstance(items, list) else [],
            "status": "initiated"
        })

    return json.dumps({"error": f"Unknown tool: {tool_name}"})
