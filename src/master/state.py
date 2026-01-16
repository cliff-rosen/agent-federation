"""State management for the master agent."""

import uuid
from datetime import datetime

from ..shared.types import (
    FederationState,
    WorkerAgent,
    AgentConfig,
    AgentStatus,
    Delegation,
    Intention,
    Message,
)


class StateManager:
    """Manages the federation state."""

    def __init__(self, workspace_path: str = "./workspace"):
        self.state = FederationState(workspace_path=workspace_path)
        self._load_default_templates()

    def _load_default_templates(self) -> None:
        """Load default agent templates."""
        # A simple general-purpose worker for testing
        self.state.agent_templates["general"] = AgentConfig(
            name="general",
            description="A general-purpose worker agent that can handle various tasks.",
            system_prompt="""You are a helpful worker agent in a federation system.
You receive tasks from the master agent and complete them thoroughly.
Always provide clear, complete responses.
If you need to write files, use the workspace directory.""",
            tools=["read_file", "write_file", "search_files"],
        )

        # A research agent
        self.state.agent_templates["researcher"] = AgentConfig(
            name="researcher",
            description="A research agent that gathers and synthesizes information.",
            system_prompt="""You are a research agent. Your job is to gather information,
analyze it, and provide comprehensive summaries. Be thorough and cite sources when possible.""",
            tools=["read_file", "search_files", "web_search"],
        )

        # A coder agent
        self.state.agent_templates["coder"] = AgentConfig(
            name="coder",
            description="A coding agent that writes and modifies code.",
            system_prompt="""You are a coding agent. You write clean, well-structured code.
Follow best practices and include appropriate error handling.""",
            tools=["read_file", "write_file", "search_files", "run_command"],
        )

    def list_agent_types(self) -> dict[str, AgentConfig]:
        """Get all available agent templates."""
        return self.state.agent_templates

    def list_running_agents(self) -> dict[str, WorkerAgent]:
        """Get all running worker agents."""
        return self.state.workers

    def get_agent(self, agent_id: str) -> WorkerAgent | None:
        """Get a specific worker agent."""
        return self.state.workers.get(agent_id)

    def spawn_agent(
        self,
        template_name: str | None = None,
        custom_config: AgentConfig | None = None,
    ) -> WorkerAgent:
        """Spawn a new worker agent from template or custom config."""
        if template_name:
            if template_name not in self.state.agent_templates:
                raise ValueError(f"Unknown agent template: {template_name}")
            config = self.state.agent_templates[template_name]
        elif custom_config:
            config = custom_config
        else:
            raise ValueError("Must provide either template_name or custom_config")

        agent_id = str(uuid.uuid4())[:8]
        agent = WorkerAgent(id=agent_id, config=config)
        self.state.workers[agent_id] = agent
        return agent

    def terminate_agent(self, agent_id: str) -> bool:
        """Terminate a worker agent."""
        if agent_id in self.state.workers:
            del self.state.workers[agent_id]
            return True
        return False

    def clear_agent_context(self, agent_id: str) -> bool:
        """Clear a worker agent's conversation history."""
        agent = self.state.workers.get(agent_id)
        if agent:
            agent.conversation = []
            agent.status = AgentStatus.IDLE
            return True
        return False

    def update_agent_status(self, agent_id: str, status: AgentStatus) -> None:
        """Update a worker agent's status."""
        agent = self.state.workers.get(agent_id)
        if agent:
            agent.status = status

    def add_agent_message(self, agent_id: str, message: Message) -> None:
        """Add a message to a worker agent's conversation."""
        agent = self.state.workers.get(agent_id)
        if agent:
            agent.conversation.append(message)

    def set_agent_result(self, agent_id: str, result: str) -> None:
        """Set the result of a worker agent's last task."""
        agent = self.state.workers.get(agent_id)
        if agent:
            agent.last_result = result
            agent.status = AgentStatus.HAS_RESULT

    def create_delegation(
        self,
        agent_id: str,
        task: str,
        intention: Intention,
        output_path: str | None = None,
    ) -> Delegation:
        """Create a new delegation."""
        delegation_id = str(uuid.uuid4())[:8]
        delegation = Delegation(
            id=delegation_id,
            agent_id=agent_id,
            task=task,
            output_path=output_path,
            intention=intention,
        )
        self.state.delegations[delegation_id] = delegation
        return delegation

    def complete_delegation(self, delegation_id: str, result: str) -> Delegation | None:
        """Mark a delegation as complete."""
        delegation = self.state.delegations.get(delegation_id)
        if delegation:
            delegation.completed_at = datetime.now()
            delegation.result = result
        return delegation

    def get_pending_delegations(self) -> list[Delegation]:
        """Get all incomplete delegations."""
        return [d for d in self.state.delegations.values() if d.completed_at is None]

    def get_completed_delegations(self) -> list[Delegation]:
        """Get all completed delegations."""
        return [d for d in self.state.delegations.values() if d.completed_at is not None]
