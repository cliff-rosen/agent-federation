"""Worker agent runner - executes worker agent tasks to completion."""

import anthropic

from ..shared.types import WorkerAgent, AgentStatus, Message
from ..shared.events import EventBus


# Simple tools for worker agents (expandable)
WORKER_TOOLS = {
    "read_file": {
        "name": "read_file",
        "description": "Read the contents of a file from the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file (relative to workspace).",
                },
            },
            "required": ["path"],
        },
    },
    "write_file": {
        "name": "write_file",
        "description": "Write content to a file in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file (relative to workspace).",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write.",
                },
            },
            "required": ["path", "content"],
        },
    },
    "search_files": {
        "name": "search_files",
        "description": "Search for files matching a pattern in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match files.",
                },
            },
            "required": ["pattern"],
        },
    },
}


class WorkerRunner:
    """Runs worker agents to completion with streaming."""

    def __init__(
        self,
        event_bus: EventBus,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        workspace_path: str = "./workspace",
    ):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.event_bus = event_bus
        self.workspace_path = workspace_path

    def run(self, agent: WorkerAgent, task: str) -> str:
        """Run a worker agent on a task until completion. Returns final response."""
        agent.status = AgentStatus.BUSY

        # Build conversation - start with task as user message
        conversation = [
            {"role": "user", "content": task}
        ]

        # Get tools for this agent
        tools = [WORKER_TOOLS[t] for t in agent.config.tools if t in WORKER_TOOLS]

        final_response = ""

        while True:
            # Call LLM with streaming
            response_text, tool_calls = self._call_llm_streaming(
                agent, conversation, tools
            )

            if tool_calls:
                # Build assistant message
                assistant_content = []
                if response_text:
                    assistant_content.append({"type": "text", "text": response_text})
                for tc in tool_calls:
                    assistant_content.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["input"],
                    })

                conversation.append({"role": "assistant", "content": assistant_content})

                # Execute tools
                tool_results = []
                for tc in tool_calls:
                    self.event_bus.worker_tool_call(agent.id, tc["name"], tc["input"])
                    result = self._execute_tool(tc["name"], tc["input"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": result,
                    })

                conversation.append({"role": "user", "content": tool_results})
            else:
                # No tool calls - done
                final_response = response_text
                if response_text:
                    conversation.append({"role": "assistant", "content": response_text})
                self.event_bus.worker_done(agent.id, final_response)
                break

        # Update agent state
        agent.conversation = [
            Message(role=m["role"], content=m["content"])
            for m in conversation
        ]
        agent.status = AgentStatus.HAS_RESULT
        agent.last_result = final_response

        return final_response

    def _call_llm_streaming(
        self, agent: WorkerAgent, conversation: list, tools: list
    ) -> tuple[str, list[dict]]:
        """Call LLM with streaming for a worker agent."""
        collected_text = ""
        tool_calls = []
        current_tool_call = None

        stream_kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "system": agent.config.system_prompt,
            "messages": conversation,
        }
        if tools:
            stream_kwargs["tools"] = tools

        with self.client.messages.stream(**stream_kwargs) as stream:
            for event in stream:
                if event.type == "content_block_start":
                    if hasattr(event.content_block, "type"):
                        if event.content_block.type == "tool_use":
                            current_tool_call = {
                                "id": event.content_block.id,
                                "name": event.content_block.name,
                                "input": {},
                                "_input_json": "",
                            }

                elif event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        text_chunk = event.delta.text
                        collected_text += text_chunk
                        self.event_bus.worker_text(agent.id, text_chunk)
                    elif hasattr(event.delta, "partial_json"):
                        if current_tool_call:
                            current_tool_call["_input_json"] += event.delta.partial_json

                elif event.type == "content_block_stop":
                    if current_tool_call:
                        import json
                        try:
                            current_tool_call["input"] = json.loads(
                                current_tool_call["_input_json"] or "{}"
                            )
                        except json.JSONDecodeError:
                            current_tool_call["input"] = {}
                        del current_tool_call["_input_json"]
                        tool_calls.append(current_tool_call)
                        current_tool_call = None

        return collected_text, tool_calls

    def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """Execute a worker tool."""
        import os
        import glob as glob_module

        if tool_name == "read_file":
            path = os.path.join(self.workspace_path, tool_input["path"])
            try:
                with open(path, "r") as f:
                    return f.read()
            except FileNotFoundError:
                return f"File not found: {tool_input['path']}"
            except Exception as e:
                return f"Error reading file: {e}"

        elif tool_name == "write_file":
            path = os.path.join(self.workspace_path, tool_input["path"])
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(tool_input["content"])
                return f"Successfully wrote to {tool_input['path']}"
            except Exception as e:
                return f"Error writing file: {e}"

        elif tool_name == "search_files":
            pattern = os.path.join(self.workspace_path, tool_input["pattern"])
            try:
                matches = glob_module.glob(pattern, recursive=True)
                if matches:
                    # Make paths relative to workspace
                    rel_matches = [
                        os.path.relpath(m, self.workspace_path) for m in matches
                    ]
                    return "Found files:\n" + "\n".join(rel_matches)
                return "No files found matching pattern."
            except Exception as e:
                return f"Error searching files: {e}"

        return f"Unknown tool: {tool_name}"
