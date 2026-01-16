"""Federation coordinator - owns all components."""

import os

from .shared.events import EventBus
from .master.state import StateManager


class Federation:
    """Central coordinator for the agent federation.

    Owns all shared resources:
    - event_bus: Communication channel for streaming events
    - state: Manages workers, configs, and task state
    - workspace_path: Shared filesystem location

    Components access these via the federation reference rather than
    having dependencies passed separately.
    """

    def __init__(self, workspace_path: str | None = None):
        # Resolve workspace path
        if workspace_path is None:
            workspace_path = os.path.join(os.getcwd(), "workspace")
        self.workspace_path = workspace_path
        os.makedirs(workspace_path, exist_ok=True)

        # Core shared resources
        self.event_bus = EventBus()
        self.state = StateManager(workspace_path=workspace_path)

        # Components (initialized lazily or set externally)
        self._master: "MasterAgent | None" = None
        self._worker_runner: "WorkerRunner | None" = None

    @property
    def master(self) -> "MasterAgent":
        """Get or create the master agent."""
        if self._master is None:
            from .master.loop import MasterAgent
            self._master = MasterAgent(self)
        return self._master

    @property
    def worker_runner(self) -> "WorkerRunner":
        """Get or create the worker runner."""
        if self._worker_runner is None:
            from .workers.runner import WorkerRunner
            self._worker_runner = WorkerRunner(self)
        return self._worker_runner

    def run(self, message: str) -> str:
        """Send a message to the master agent and get the response."""
        return self.master.run(message)


# Type hints for lazy imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .master.loop import MasterAgent
    from .workers.runner import WorkerRunner
