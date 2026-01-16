"""Master agent orchestration tools.

These are the tools available to the master agent for managing the federation.
"""

from typing import Any

from ..shared.types import Intention, IntentionType
from ..shared.events import EventBus
from .state import StateManager


# Tool definitions in Anthropic API format
MASTER_TOOLS = [
    {
        "name": "list_agent_types",
        "description": "View all available agent templates that can be spawned.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_running_agents",
        "description": "View all currently running worker agents and their status.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_agent_detail",
        "description": "Get detailed information about a specific worker agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "The ID of the agent to inspect.",
                },
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "spawn_agent",
        "description": "Create a new worker agent instance from a template.",
        "input_schema": {
            "type": "object",
            "properties": {
                "template_name": {
                    "type": "string",
                    "description": "Name of the agent template to use (e.g., 'general', 'researcher', 'coder').",
                },
            },
            "required": ["template_name"],
        },
    },
    {
        "name": "delegate",
        "description": "Assign a task to a worker agent. The agent will execute the task and the result will be handled according to the specified intention.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "The ID of the worker agent to delegate to.",
                },
                "task": {
                    "type": "string",
                    "description": "The task description/prompt for the agent.",
                },
                "intention": {
                    "type": "string",
                    "enum": ["return_to_user", "pass_to_agent", "review_by_master"],
                    "description": "What to do when the task completes.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional workspace path to write results to.",
                },
            },
            "required": ["agent_id", "task", "intention"],
        },
    },
    {
        "name": "terminate_agent",
        "description": "Shut down a worker agent instance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "The ID of the agent to terminate.",
                },
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "clear_agent_context",
        "description": "Reset a worker agent's conversation history while keeping it running.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "The ID of the agent to clear.",
                },
            },
            "required": ["agent_id"],
        },
    },
]


class ToolExecutor:
    """Executes master agent tools."""

    def __init__(
        self,
        state_manager: StateManager,
        event_bus: EventBus,
        worker_runner: Any = None,  # Will be set to WorkerRunner
    ):
        self.state = state_manager
        self.events = event_bus
        self.worker_runner = worker_runner

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Execute a tool and return the result as a string."""
        self.events.master_tool_call(tool_name, tool_input)

        handler = getattr(self, f"_tool_{tool_name}", None)
        if not handler:
            result = f"Unknown tool: {tool_name}"
        else:
            result = handler(**tool_input)

        self.events.master_tool_result(tool_name, result)
        return result

    def _tool_list_agent_types(self) -> str:
        templates = self.state.list_agent_types()
        if not templates:
            return "No agent templates available."

        lines = ["Available agent templates:"]
        for name, config in templates.items():
            lines.append(f"\n- {name}: {config.description}")
            lines.append(f"  Tools: {', '.join(config.tools)}")
        return "\n".join(lines)

    def _tool_list_running_agents(self) -> str:
        agents = self.state.list_running_agents()
        if not agents:
            return "No agents currently running."

        lines = ["Running agents:"]
        for agent_id, agent in agents.items():
            lines.append(f"\n- {agent_id} ({agent.config.name})")
            lines.append(f"  Status: {agent.status.value}")
            lines.append(f"  Messages: {len(agent.conversation)}")
        return "\n".join(lines)

    def _tool_get_agent_detail(self, agent_id: str) -> str:
        agent = self.state.get_agent(agent_id)
        if not agent:
            return f"Agent not found: {agent_id}"

        lines = [
            f"Agent: {agent_id}",
            f"Type: {agent.config.name}",
            f"Status: {agent.status.value}",
            f"Created: {agent.created_at.isoformat()}",
            f"Messages in context: {len(agent.conversation)}",
            f"Tools: {', '.join(agent.config.tools)}",
        ]
        if agent.last_result:
            lines.append(f"Last result: {agent.last_result[:200]}...")
        return "\n".join(lines)

    def _tool_spawn_agent(self, template_name: str) -> str:
        try:
            agent = self.state.spawn_agent(template_name=template_name)
            self.events.worker_spawned(agent.id, agent.config.name)
            return f"Spawned agent '{agent.config.name}' with ID: {agent.id}"
        except ValueError as e:
            return f"Failed to spawn agent: {e}"

    def _tool_delegate(
        self,
        agent_id: str,
        task: str,
        intention: str,
        output_path: str | None = None,
    ) -> str:
        agent = self.state.get_agent(agent_id)
        if not agent:
            return f"Agent not found: {agent_id}"

        # Parse intention
        intention_type = IntentionType(intention)
        intention_obj = Intention(type=intention_type)

        # Create delegation record
        delegation = self.state.create_delegation(
            agent_id=agent_id,
            task=task,
            intention=intention_obj,
            output_path=output_path,
        )

        self.events.delegation_started(delegation.id, agent_id, task)

        # Execute the delegation synchronously using the worker runner
        if self.worker_runner:
            result = self.worker_runner.run(agent, task)
            self.state.set_agent_result(agent_id, result)
            self.state.complete_delegation(delegation.id, result)
            self.events.delegation_completed(delegation.id, agent_id, result)

            # Handle intention
            if intention_type == IntentionType.RETURN_TO_USER:
                return f"Delegation complete. Result from {agent_id}:\n\n{result}"
            elif intention_type == IntentionType.REVIEW_BY_MASTER:
                return f"Delegation complete. Review the result and decide next steps:\n\n{result}"
            else:
                return f"Delegation complete with result:\n\n{result}"
        else:
            return f"Delegation created (ID: {delegation.id}) but no worker runner configured."

    def _tool_terminate_agent(self, agent_id: str) -> str:
        if self.state.terminate_agent(agent_id):
            return f"Agent {agent_id} terminated."
        return f"Agent not found: {agent_id}"

    def _tool_clear_agent_context(self, agent_id: str) -> str:
        if self.state.clear_agent_context(agent_id):
            return f"Agent {agent_id} context cleared."
        return f"Agent not found: {agent_id}"
