"""Master agent agentic loop with streaming."""

from __future__ import annotations

import anthropic
from typing import TYPE_CHECKING

from ..shared.events import EventType, Event
from ..shared.types import MasterStatus
from .tools import MASTER_TOOLS, ToolExecutor

if TYPE_CHECKING:
    from ..federation import Federation


MASTER_SYSTEM_PROMPT = """You are the Master Agent in an agent federation system.

Your role is to:
1. Receive and interpret user requests
2. Decide whether to handle tasks directly or delegate to worker agents
3. Manage worker lifecycle (spawn, delegate, terminate)
4. Check for completed work and deliver results to users

Available tools:
- list_worker_types: See what types of workers you can create
- spawn_worker: Create a new worker
- delegate: Assign a task to a worker (runs in background)
- get_completed: Check for finished work and get results
- list_workers: See all workers and their status
- terminate_worker: Shut down a worker

Workflow for delegation:
1. Spawn a worker of the appropriate type
2. Delegate the task with an intention (return_to_user or review_by_master)
3. The worker runs in the background
4. Call get_completed to check results
5. Handle based on the intention

For simple questions, handle them directly without delegation.
For complex tasks, delegate to specialized workers."""


class MasterAgent:
    """The master agent with streaming agentic loop."""

    def __init__(
        self,
        federation: Federation,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
    ):
        self.federation = federation
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.tool_executor = ToolExecutor(federation)
        self.conversation: list[dict] = []

    def run(self, user_message: str) -> str:
        """Run the agentic loop for a user message. Returns final response."""
        self.federation.state.set_master_status(MasterStatus.THINKING)
        self.conversation.append({"role": "user", "content": user_message})

        final_response = ""

        while True:
            response_text, tool_calls = self._call_llm_streaming()

            if tool_calls:
                # Build assistant message with text and tool use
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

                self.conversation.append({"role": "assistant", "content": assistant_content})

                # Execute tools
                tool_results = []
                for tc in tool_calls:
                    self.federation.state.set_master_status(MasterStatus.CALLING_TOOL, tc["name"])
                    result = self.tool_executor.execute(tc["name"], tc["input"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": result,
                    })

                self.conversation.append({"role": "user", "content": tool_results})
                self.federation.state.set_master_status(MasterStatus.THINKING)
            else:
                final_response = response_text
                if response_text:
                    self.conversation.append({"role": "assistant", "content": response_text})
                self.federation.state.set_master_status(MasterStatus.IDLE)
                self.federation.event_bus.emit(Event.create(EventType.MASTER_DONE))
                break

        return final_response

    def _call_llm_streaming(self) -> tuple[str, list[dict]]:
        """Call LLM with streaming, returning (text, tool_calls)."""
        collected_text = ""
        tool_calls = []
        current_tool_call = None

        with self.client.messages.stream(
            model=self.model,
            max_tokens=4096,
            system=MASTER_SYSTEM_PROMPT,
            messages=self.conversation,
            tools=MASTER_TOOLS,
        ) as stream:
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
                        self.federation.event_bus.master_text(text_chunk)
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
