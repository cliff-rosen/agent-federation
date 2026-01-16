"""Event system for streaming status updates throughout the federation."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol
from datetime import datetime


class EventType(Enum):
    # Master events
    MASTER_THINKING = "master_thinking"
    MASTER_TEXT = "master_text"
    MASTER_TOOL_CALL = "master_tool_call"
    MASTER_TOOL_RESULT = "master_tool_result"
    MASTER_DONE = "master_done"
    MASTER_ERROR = "master_error"

    # Worker events
    WORKER_SPAWNED = "worker_spawned"
    WORKER_THINKING = "worker_thinking"
    WORKER_TEXT = "worker_text"
    WORKER_TOOL_CALL = "worker_tool_call"
    WORKER_TOOL_RESULT = "worker_tool_result"
    WORKER_DONE = "worker_done"
    WORKER_ERROR = "worker_error"
    WORKER_TERMINATED = "worker_terminated"

    # Delegation events
    DELEGATION_STARTED = "delegation_started"
    DELEGATION_COMPLETED = "delegation_completed"

    # User-facing
    STATUS_UPDATE = "status_update"


@dataclass
class Event:
    """An event in the federation."""
    type: EventType
    timestamp: datetime
    agent_id: str | None  # None for master events
    data: dict[str, Any]

    @classmethod
    def create(cls, type: EventType, agent_id: str | None = None, **data) -> "Event":
        return cls(type=type, timestamp=datetime.now(), agent_id=agent_id, data=data)


class EventHandler(Protocol):
    """Protocol for event handlers."""
    def __call__(self, event: Event) -> None: ...


class EventBus:
    """Simple event bus for broadcasting events to handlers."""

    def __init__(self):
        self._handlers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        self._handlers.remove(handler)

    def emit(self, event: Event) -> None:
        for handler in self._handlers:
            handler(event)

    # Convenience methods for common events
    def master_text(self, text: str) -> None:
        self.emit(Event.create(EventType.MASTER_TEXT, text=text))

    def master_tool_call(self, tool_name: str, tool_input: dict) -> None:
        self.emit(Event.create(EventType.MASTER_TOOL_CALL, tool_name=tool_name, tool_input=tool_input))

    def master_tool_result(self, tool_name: str, result: Any) -> None:
        self.emit(Event.create(EventType.MASTER_TOOL_RESULT, tool_name=tool_name, result=result))

    def worker_spawned(self, agent_id: str, agent_type: str) -> None:
        self.emit(Event.create(EventType.WORKER_SPAWNED, agent_id=agent_id, agent_type=agent_type))

    def worker_text(self, agent_id: str, text: str) -> None:
        self.emit(Event.create(EventType.WORKER_TEXT, agent_id=agent_id, text=text))

    def worker_tool_call(self, agent_id: str, tool_name: str, tool_input: dict) -> None:
        self.emit(Event.create(EventType.WORKER_TOOL_CALL, agent_id=agent_id, tool_name=tool_name, tool_input=tool_input))

    def worker_done(self, agent_id: str, result: str) -> None:
        self.emit(Event.create(EventType.WORKER_DONE, agent_id=agent_id, result=result))

    def delegation_started(self, delegation_id: str, agent_id: str, task: str) -> None:
        self.emit(Event.create(EventType.DELEGATION_STARTED, delegation_id=delegation_id, agent_id=agent_id, task=task))

    def delegation_completed(self, delegation_id: str, agent_id: str, result: str) -> None:
        self.emit(Event.create(EventType.DELEGATION_COMPLETED, delegation_id=delegation_id, agent_id=agent_id, result=result))

    def status_update(self, message: str) -> None:
        self.emit(Event.create(EventType.STATUS_UPDATE, message=message))


def console_event_handler(event: Event) -> None:
    """Simple console handler for debugging."""
    prefix = f"[{event.type.value}]"
    if event.agent_id:
        prefix += f" [{event.agent_id}]"

    if event.type == EventType.MASTER_TEXT or event.type == EventType.WORKER_TEXT:
        print(f"{prefix} {event.data.get('text', '')}", end="", flush=True)
    elif event.type == EventType.MASTER_TOOL_CALL or event.type == EventType.WORKER_TOOL_CALL:
        print(f"\n{prefix} Calling: {event.data.get('tool_name')}")
    elif event.type == EventType.STATUS_UPDATE:
        print(f"\n{prefix} {event.data.get('message')}")
    elif event.type in (EventType.MASTER_DONE, EventType.WORKER_DONE):
        print(f"\n{prefix} Complete")
