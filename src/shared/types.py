"""Core types for the agent federation system."""

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class WorkerStatus(Enum):
    IDLE = "idle"
    WORKING = "working"
    DONE = "done"


class MasterStatus(Enum):
    IDLE = "idle"
    THINKING = "thinking"
    CALLING_TOOL = "calling_tool"


class Intention(Enum):
    """What to do when a worker completes."""
    RETURN_TO_USER = "return_to_user"
    REVIEW_BY_MASTER = "review_by_master"


@dataclass
class WorkerConfig:
    """Configuration for a worker type."""
    name: str
    description: str
    system_prompt: str
    allowed_tools: list[str]


@dataclass
class Worker:
    """A worker agent in the federation."""
    id: str
    type: str  # e.g., "general", "coder"
    config: WorkerConfig
    status: WorkerStatus = WorkerStatus.IDLE

    # Current task info (when working or done)
    current_task: str | None = None
    intention: Intention | None = None
    result: str | None = None

    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class MasterState:
    """Current state of the master agent."""
    status: MasterStatus = MasterStatus.IDLE
    current_tool: str | None = None


@dataclass
class FederationState:
    """Global state of the federation."""
    master: MasterState = field(default_factory=MasterState)
    workers: dict[str, Worker] = field(default_factory=dict)
    worker_configs: dict[str, WorkerConfig] = field(default_factory=dict)
    completed_queue: list[str] = field(default_factory=list)  # Worker IDs with results ready
    workspace_path: str = "./workspace"
