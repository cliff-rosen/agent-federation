"""Master agent orchestration tools."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from ..shared.types import Intention

if TYPE_CHECKING:
    from ..federation import Federation


# Tool definitions for the master agent
MASTER_TOOLS = [
    {
        "name": "list_worker_types",
        "description": "View all available worker types that can be spawned.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_workers",
        "description": "View all current workers and their status (idle, working, done).",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "spawn_worker",
        "description": "Create a new worker of the specified type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "worker_type": {
                    "type": "string",
                    "description": "Type of worker to spawn (e.g., 'general', 'coder', 'researcher').",
                },
            },
            "required": ["worker_type"],
        },
    },
    {
        "name": "delegate",
        "description": "Assign a task to a worker. The worker will run in the background. Use get_completed to check results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "worker_id": {
                    "type": "string",
                    "description": "ID of the worker to delegate to.",
                },
                "task": {
                    "type": "string",
                    "description": "The task description for the worker.",
                },
                "intention": {
                    "type": "string",
                    "enum": ["return_to_user", "review_by_master"],
                    "description": "What to do when the worker completes.",
                },
            },
            "required": ["worker_id", "task", "intention"],
        },
    },
    {
        "name": "get_completed",
        "description": "Check if any workers have completed their tasks and get their results.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "terminate_worker",
        "description": "Shut down a worker.",
        "input_schema": {
            "type": "object",
            "properties": {
                "worker_id": {
                    "type": "string",
                    "description": "ID of the worker to terminate.",
                },
            },
            "required": ["worker_id"],
        },
    },
]


class ToolExecutor:
    """Executes master agent tools."""

    def __init__(self, federation: Federation):
        self.federation = federation

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Execute a tool and return the result."""
        self.federation.event_bus.master_tool_call(tool_name, tool_input)

        handler = getattr(self, f"_tool_{tool_name}", None)
        if not handler:
            result = f"Unknown tool: {tool_name}"
        else:
            result = handler(**tool_input)

        self.federation.event_bus.master_tool_result(tool_name, result)
        return result

    def _tool_list_worker_types(self) -> str:
        configs = self.federation.state.list_worker_types()
        if not configs:
            return "No worker types available."

        lines = ["Available worker types:"]
        for name, config in configs.items():
            lines.append(f"\n- {name}: {config.description}")
        return "\n".join(lines)

    def _tool_list_workers(self) -> str:
        workers = self.federation.state.list_workers()
        if not workers:
            return "No workers running."

        lines = ["Current workers:"]
        for worker_id, worker in workers.items():
            lines.append(f"\n- {worker_id} ({worker.type}): {worker.status.value}")
            if worker.current_task:
                lines.append(f"  Task: {worker.current_task[:50]}...")
            if worker.result:
                lines.append(f"  Result available: yes")
        return "\n".join(lines)

    def _tool_spawn_worker(self, worker_type: str) -> str:
        try:
            worker = self.federation.state.spawn_worker(worker_type)
            self.federation.event_bus.worker_spawned(worker.id, worker.type)
            return f"Spawned {worker_type} worker with ID: {worker.id}"
        except ValueError as e:
            return f"Failed to spawn worker: {e}"

    def _tool_delegate(
        self,
        worker_id: str,
        task: str,
        intention: str,
    ) -> str:
        worker = self.federation.state.get_worker(worker_id)
        if not worker:
            return f"Worker not found: {worker_id}"

        if worker.status.value == "working":
            return f"Worker {worker_id} is already busy."

        # Parse intention
        try:
            intention_enum = Intention(intention)
        except ValueError:
            return f"Invalid intention: {intention}"

        # Assign the task
        self.federation.state.assign_task(worker_id, task, intention_enum)

        # Start the worker in the background
        self.federation.worker_runner.start_worker(worker_id, task)
        return f"Delegated task to worker {worker_id}. Use get_completed to check when done."

    def _tool_get_completed(self) -> str:
        completed = self.federation.state.get_completed_workers()
        if not completed:
            return "No completed tasks."

        lines = ["Completed tasks:"]
        for worker in completed:
            lines.append(f"\n- Worker {worker.id} ({worker.type}):")
            lines.append(f"  Task: {worker.current_task}")
            lines.append(f"  Intention: {worker.intention.value if worker.intention else 'none'}")
            lines.append(f"  Result: {worker.result}")

            # Clear the worker so it can be reused
            self.federation.state.clear_worker(worker.id)

        return "\n".join(lines)

    def _tool_terminate_worker(self, worker_id: str) -> str:
        if self.federation.state.terminate_worker(worker_id):
            return f"Worker {worker_id} terminated."
        return f"Worker not found: {worker_id}"
