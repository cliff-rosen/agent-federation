"""Core types for the agent federation system."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from datetime import datetime


class AgentStatus(Enum):
    IDLE = "idle"
    BUSY = "busy"
    HAS_RESULT = "has_result"


class IntentionType(Enum):
    RETURN_TO_USER = "return_to_user"
    PASS_TO_AGENT = "pass_to_agent"
    REVIEW_BY_MASTER = "review_by_master"


@dataclass
class Intention:
    """What should happen when a delegation completes."""
    type: IntentionType
    target_agent_id: str | None = None  # For PASS_TO_AGENT
    transform_instructions: str | None = None  # For PASS_TO_AGENT


@dataclass
class Message:
    """A message in a conversation."""
    role: str  # "user", "assistant", "tool_result"
    content: Any
    tool_use_id: str | None = None  # For tool results


@dataclass
class ToolCall:
    """A tool call from the LLM."""
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class AgentConfig:
    """Configuration for an agent (from template or custom)."""
    name: str
    description: str
    system_prompt: str
    tools: list[str]  # Tool names this agent can use


@dataclass
class WorkerAgent:
    """A running worker agent instance."""
    id: str
    config: AgentConfig
    conversation: list[Message] = field(default_factory=list)
    status: AgentStatus = AgentStatus.IDLE
    last_result: str | None = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Delegation:
    """An active delegation to a worker agent."""
    id: str
    agent_id: str
    task: str
    output_path: str | None
    intention: Intention
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    result: str | None = None


@dataclass
class FederationState:
    """Global state of the federation."""
    workers: dict[str, WorkerAgent] = field(default_factory=dict)
    delegations: dict[str, Delegation] = field(default_factory=dict)
    agent_templates: dict[str, AgentConfig] = field(default_factory=dict)
    workspace_path: str = "./workspace"
