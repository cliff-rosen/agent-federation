"""Worker runner using Claude Agent SDK."""

from __future__ import annotations

import asyncio
import threading
import traceback
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..federation import Federation

# Try to import Claude Agent SDK, fall back to simple mode if not available
HAS_SDK = False
ToolUseBlock = None
ToolResultBlock = None

try:
    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        TextBlock,
        ResultMessage,
    )
    HAS_SDK = True
    # These might not exist in all SDK versions
    try:
        from claude_agent_sdk import ToolUseBlock as _ToolUseBlock
        ToolUseBlock = _ToolUseBlock
    except ImportError:
        pass
    try:
        from claude_agent_sdk import ToolResultBlock as _ToolResultBlock
        ToolResultBlock = _ToolResultBlock
    except ImportError:
        pass
except ImportError:
    pass


class WorkerRunner:
    """Runs workers in background threads using Claude Agent SDK."""

    def __init__(self, federation: Federation):
        self.federation = federation
        self._threads: dict[str, threading.Thread] = {}

    def start_worker(self, worker_id: str, task: str) -> None:
        """Start a worker in a background thread."""
        worker = self.federation.state.get_worker(worker_id)
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
        events = self.federation.event_bus
        state = self.federation.state

        # Emit started event so UI can refresh
        events.worker_started(worker_id, task)
        events.worker_text(worker_id, f"Starting task: {task}\n")

        try:
            if not HAS_SDK:
                # Fallback: simulation for testing with progress updates
                events.worker_text(worker_id, "[SDK not installed - running in test mode]\n\n")

                # Simulate some work with progress
                events.worker_text(worker_id, "Analyzing task...\n")
                await asyncio.sleep(1)

                events.worker_tool_call(worker_id, "WebSearch", {"query": task})
                events.worker_text(worker_id, "[Calling WebSearch...]\n")
                await asyncio.sleep(2)
                events.worker_text(worker_id, "[Tool completed]\n\n")

                events.worker_text(worker_id, "Processing results...\n")
                await asyncio.sleep(1)

                events.worker_text(worker_id, "Generating response...\n")
                await asyncio.sleep(1)

                result_text = f"[Test mode] Simulated completion of task: {task}\n\nThis is a placeholder response that would contain the actual results from the Claude Agent SDK."
                events.worker_text(worker_id, f"\n{result_text}\n")

                state.complete_task(worker_id, result_text)
                events.worker_done(worker_id, result_text)
                return

            events.worker_text(worker_id, "Initializing Claude Agent SDK...\n")

            # Assert for type checker - we return early above if HAS_SDK is False
            assert HAS_SDK

            options = ClaudeAgentOptions(
                system_prompt=system_prompt,
                allowed_tools=allowed_tools,
                permission_mode="acceptEdits",
                cwd=self.federation.workspace_path,
            )

            result_text = ""

            async with ClaudeSDKClient(options=options) as client:
                events.worker_text(worker_id, "Connected. Sending query...\n")
                await client.query(task)

                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                result_text += block.text
                                events.worker_text(worker_id, block.text)
                            elif ToolUseBlock is not None and isinstance(block, ToolUseBlock):
                                # Emit tool call event
                                tool_name = getattr(block, 'name', 'unknown')
                                events.worker_tool_call(worker_id, tool_name, {})
                                events.worker_text(worker_id, f"\n[Calling {tool_name}...]\n")
                            elif ToolResultBlock is not None and isinstance(block, ToolResultBlock):
                                # Tool completed - emit some feedback
                                events.worker_text(worker_id, "[Tool completed]\n")

                    elif isinstance(message, ResultMessage):
                        # Task complete
                        if hasattr(message, 'result') and message.result:
                            result_text = message.result

            # Mark complete
            state.complete_task(worker_id, result_text or "Task completed.")
            events.worker_done(worker_id, result_text)

        except Exception as e:
            error_msg = f"Worker error: {e}\n{traceback.format_exc()}"
            events.worker_text(worker_id, f"\n[ERROR] {error_msg}\n")
            state.complete_task(worker_id, error_msg)
            events.worker_done(worker_id, error_msg)

        finally:
            # Clean up thread reference
            if worker_id in self._threads:
                del self._threads[worker_id]
