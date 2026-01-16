"""Worker runner using Claude Agent SDK."""

import asyncio
import threading
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage, TextBlock, ResultMessage

from ..shared.events import EventBus
from ..master.state import StateManager


class WorkerRunner:
    """Runs workers in background threads using Claude Agent SDK."""

    def __init__(
        self,
        state_manager: StateManager,
        event_bus: EventBus,
        workspace_path: str = "./workspace",
    ):
        self.state = state_manager
        self.events = event_bus
        self.workspace_path = workspace_path
        self._threads: dict[str, threading.Thread] = {}

    def start_worker(self, worker_id: str, task: str) -> None:
        """Start a worker in a background thread."""
        worker = self.state.get_worker(worker_id)
        if not worker:
            return

        # Run in background thread
        thread = threading.Thread(
            target=self._run_worker_sync,
            args=(worker_id, task, worker.config.system_prompt, worker.config.allowed_tools),
            daemon=True,
        )
        self._threads[worker_id] = thread
        thread.start()

    def _run_worker_sync(
        self,
        worker_id: str,
        task: str,
        system_prompt: str,
        allowed_tools: list[str],
    ) -> None:
        """Synchronous wrapper to run async worker code."""
        asyncio.run(self._run_worker_async(worker_id, task, system_prompt, allowed_tools))

    async def _run_worker_async(
        self,
        worker_id: str,
        task: str,
        system_prompt: str,
        allowed_tools: list[str],
    ) -> None:
        """Run a worker using Claude Agent SDK."""
        # Emit started event so UI can refresh
        self.events.worker_started(worker_id, task)

        try:
            options = ClaudeAgentOptions(
                system_prompt=system_prompt,
                allowed_tools=allowed_tools,
                permission_mode="acceptEdits",
                cwd=self.workspace_path,
            )

            result_text = ""

            async with ClaudeSDKClient(options=options) as client:
                await client.query(task)

                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                result_text += block.text
                                self.events.worker_text(worker_id, block.text)

                    elif isinstance(message, ResultMessage):
                        # Task complete
                        if message.result:
                            result_text = message.result

            # Mark complete
            self.state.complete_task(worker_id, result_text or "Task completed.")
            self.events.worker_done(worker_id, result_text)

        except Exception as e:
            error_msg = f"Worker error: {e}"
            self.state.complete_task(worker_id, error_msg)
            self.events.worker_done(worker_id, error_msg)

        finally:
            # Clean up thread reference
            if worker_id in self._threads:
                del self._threads[worker_id]
