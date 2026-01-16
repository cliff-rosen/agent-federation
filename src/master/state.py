"""State management for the federation."""

import uuid

from ..shared.types import (
    FederationState,
    Worker,
    WorkerConfig,
    WorkerStatus,
    MasterState,
    MasterStatus,
    Intention,
)


class StateManager:
    """Manages the federation state."""

    def __init__(self, workspace_path: str = "./workspace"):
        self.state = FederationState(workspace_path=workspace_path)
        self._load_default_configs()

    def _load_default_configs(self) -> None:
        """Load default worker configurations."""
        self.state.worker_configs["general"] = WorkerConfig(
            name="general",
            description="A general-purpose worker that can handle various tasks.",
            system_prompt="You are a helpful worker agent. Complete tasks thoroughly and clearly.",
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        )

        self.state.worker_configs["coder"] = WorkerConfig(
            name="coder",
            description="A coding specialist for writing and modifying code.",
            system_prompt="You are a coding agent. Write clean, well-structured code with good error handling.",
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        )

        self.state.worker_configs["researcher"] = WorkerConfig(
            name="researcher",
            description="A research agent for gathering and analyzing information.",
            system_prompt="You are a research agent. Gather information thoroughly and provide clear summaries.",
            allowed_tools=["Read", "Glob", "Grep", "WebFetch", "WebSearch"],
        )

    # --- Master state ---

    def set_master_status(self, status: MasterStatus, tool: str | None = None) -> None:
        """Update master agent status."""
        self.state.master.status = status
        self.state.master.current_tool = tool

    def get_master_state(self) -> MasterState:
        """Get current master state."""
        return self.state.master

    # --- Worker configs ---

    def list_worker_types(self) -> dict[str, WorkerConfig]:
        """Get all available worker configurations."""
        return self.state.worker_configs

    # --- Workers ---

    def list_workers(self) -> dict[str, Worker]:
        """Get all workers."""
        return self.state.workers

    def get_worker(self, worker_id: str) -> Worker | None:
        """Get a specific worker."""
        return self.state.workers.get(worker_id)

    def spawn_worker(self, worker_type: str) -> Worker:
        """Spawn a new worker of the given type."""
        if worker_type not in self.state.worker_configs:
            raise ValueError(f"Unknown worker type: {worker_type}")

        config = self.state.worker_configs[worker_type]
        worker_id = str(uuid.uuid4())[:8]

        worker = Worker(
            id=worker_id,
            type=worker_type,
            config=config,
        )
        self.state.workers[worker_id] = worker
        return worker

    def terminate_worker(self, worker_id: str) -> bool:
        """Terminate a worker."""
        if worker_id in self.state.workers:
            del self.state.workers[worker_id]
            # Also remove from completed queue if present
            if worker_id in self.state.completed_queue:
                self.state.completed_queue.remove(worker_id)
            return True
        return False

    # --- Task assignment ---

    def assign_task(
        self,
        worker_id: str,
        task: str,
        intention: Intention,
    ) -> bool:
        """Assign a task to a worker."""
        worker = self.state.workers.get(worker_id)
        if not worker:
            return False

        worker.status = WorkerStatus.WORKING
        worker.current_task = task
        worker.intention = intention
        worker.result = None
        return True

    def complete_task(self, worker_id: str, result: str) -> bool:
        """Mark a worker's task as complete."""
        worker = self.state.workers.get(worker_id)
        if not worker:
            return False

        worker.status = WorkerStatus.DONE
        worker.result = result

        # Add to completed queue for master to pick up
        if worker_id not in self.state.completed_queue:
            self.state.completed_queue.append(worker_id)

        return True

    def clear_worker(self, worker_id: str) -> bool:
        """Reset a worker to idle state."""
        worker = self.state.workers.get(worker_id)
        if not worker:
            return False

        worker.status = WorkerStatus.IDLE
        worker.current_task = None
        worker.intention = None
        worker.result = None

        # Remove from completed queue if present
        if worker_id in self.state.completed_queue:
            self.state.completed_queue.remove(worker_id)

        return True

    # --- Completion queue ---

    def get_completed_workers(self) -> list[Worker]:
        """Get workers that have completed their tasks."""
        return [
            self.state.workers[wid]
            for wid in self.state.completed_queue
            if wid in self.state.workers
        ]

    def pop_completed(self) -> Worker | None:
        """Pop the next completed worker from the queue."""
        while self.state.completed_queue:
            worker_id = self.state.completed_queue.pop(0)
            worker = self.state.workers.get(worker_id)
            if worker and worker.status == WorkerStatus.DONE:
                return worker
        return None
