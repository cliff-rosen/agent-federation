"""Master agent agentic loop with streaming."""

import anthropic

from ..shared.events import EventBus, EventType, Event
from .state import StateManager
from .tools import MASTER_TOOLS, ToolExecutor


MASTER_SYSTEM_PROMPT = """You are the Master Agent in an agent federation system.

Your role is to:
1. Receive and interpret user requests
2. Decide whether to handle tasks directly or delegate to specialized worker agents
3. Manage worker agent lifecycle (spawn, delegate, terminate)
4. Coordinate complex workflows across multiple agents
5. Ensure work products are delivered back to the user

Available worker agent types can be discovered using list_agent_types.

When delegating:
- Spawn an appropriate agent type for the task
- Use the delegate tool to assign work
- The intention parameter determines what happens when the agent completes:
  - "return_to_user": The result goes directly to the user
  - "review_by_master": You review the result and decide next steps
  - "pass_to_agent": Forward to another agent (for pipelines)

For simple questions or tasks, you can handle them directly.
For complex tasks, delegate to specialized workers.

Always be clear about what you're doing and why."""


class MasterAgent:
    """The master agent with streaming agentic loop."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        workspace_path: str = "./workspace",
    ):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.event_bus = EventBus()
        self.state_manager = StateManager(workspace_path=workspace_path)
        self.tool_executor = ToolExecutor(self.state_manager, self.event_bus)
        self.conversation: list[dict] = []

    def set_worker_runner(self, runner) -> None:
        """Set the worker runner for executing delegations."""
        self.tool_executor.worker_runner = runner

    def run(self, user_message: str) -> str:
        """Run the agentic loop for a user message. Returns final response."""
        # Add user message to conversation
        self.conversation.append({"role": "user", "content": user_message})

        final_response = ""

        while True:
            # Call LLM with streaming
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

                # Execute tools and collect results
                tool_results = []
                for tc in tool_calls:
                    result = self.tool_executor.execute(tc["name"], tc["input"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": result,
                    })

                self.conversation.append({"role": "user", "content": tool_results})

                # Continue loop
            else:
                # No tool calls - we have the final response
                final_response = response_text
                if response_text:
                    self.conversation.append({"role": "assistant", "content": response_text})
                self.event_bus.emit(Event.create(EventType.MASTER_DONE))
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
                    if event.content_block.type == "text":
                        pass  # Text block starting
                    elif event.content_block.type == "tool_use":
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
                        self.event_bus.master_text(text_chunk)
                    elif hasattr(event.delta, "partial_json"):
                        if current_tool_call:
                            current_tool_call["_input_json"] += event.delta.partial_json

                elif event.type == "content_block_stop":
                    if current_tool_call:
                        # Parse the accumulated JSON
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
