"""Terminal UI application using Textual."""

from __future__ import annotations

from typing import TYPE_CHECKING
from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.containers import Vertical, Container
from textual.widgets import Header, Footer, Static, Input, RichLog, Label, ListView, ListItem
from textual.message import Message
from textual import work
from rich.text import Text

from ..shared.events import Event, EventType
from ..shared.types import Worker, WorkerStatus

if TYPE_CHECKING:
    from ..federation import Federation


@dataclass
class WorkerOutput:
    """Stores a single output line from a worker."""
    worker_id: str
    text: str
    style: str = "white"


class WorkerFilterChanged(Message):
    """Message sent when worker filter changes."""
    def __init__(self, worker_id: str | None) -> None:
        self.worker_id = worker_id
        super().__init__()


class WorkerListItem(ListItem):
    """A clickable worker item."""

    def __init__(self, worker_id: str, worker: Worker, selected: bool = False) -> None:
        super().__init__()
        self.worker_id = worker_id
        self.worker = worker
        self._selected = selected

    def compose(self) -> ComposeResult:
        worker = self.worker
        if worker.status == WorkerStatus.IDLE:
            icon = "○"
            style = "dim"
        elif worker.status == WorkerStatus.WORKING:
            icon = "●"
            style = "yellow bold"
        else:  # DONE
            icon = "✓"
            style = "green"

        prefix = "▶ " if self._selected else "  "
        label = f"{prefix}{icon} {self.worker_id[:8]} {worker.type}"
        yield Label(label, classes=style)


class WorkersList(Static):
    """Shows all workers with their status. Click to filter output."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._workers: dict[str, Worker] = {}
        self._selected_id: str | None = None

    @property
    def workers(self) -> dict[str, Worker]:
        return self._workers

    @workers.setter
    def workers(self, value: dict[str, Worker]) -> None:
        self._workers = value
        self._rebuild_list()

    @property
    def selected_id(self) -> str | None:
        return self._selected_id

    @selected_id.setter
    def selected_id(self, value: str | None) -> None:
        self._selected_id = value
        self._rebuild_list()

    def compose(self) -> ComposeResult:
        yield ListView(id="workers-listview")

    def _rebuild_list(self) -> None:
        """Rebuild the worker list."""
        try:
            list_view = self.query_one("#workers-listview", ListView)
        except Exception:
            return  # Widget not mounted yet

        list_view.clear()

        if not self._workers:
            list_view.append(ListItem(Label("No workers yet", classes="dim")))
            return

        # Add "All workers" option
        all_selected = self._selected_id is None
        all_prefix = "▶ " if all_selected else "  "
        all_item = ListItem(Label(f"{all_prefix}◉ ALL WORKERS", classes="bold" if all_selected else ""))
        all_item.worker_id = None  # type: ignore
        list_view.append(all_item)

        # Add each worker
        for worker_id, worker in self._workers.items():
            is_selected = self._selected_id == worker_id
            item = WorkerListItem(worker_id, worker, selected=is_selected)
            list_view.append(item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle worker selection."""
        item = event.item
        if hasattr(item, 'worker_id'):
            worker_id = item.worker_id
            # Toggle: if already selected, deselect (show all)
            if worker_id == self.selected_id:
                self.selected_id = None
            else:
                self.selected_id = worker_id
            self.post_message(WorkerFilterChanged(self.selected_id))


class WorkerDetails(Static):
    """Shows detailed information about the selected worker."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._worker: Worker | None = None
        self._worker_id: str | None = None

    def set_worker(self, worker_id: str, worker: Worker) -> None:
        """Update the displayed worker."""
        self._worker_id = worker_id
        self._worker = worker
        self._refresh_display()

    def clear_worker(self) -> None:
        """Clear the worker display."""
        self._worker = None
        self._worker_id = None
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Rebuild the display."""
        if self._worker is None:
            self.update("[dim]Select a worker to see details[/dim]")
            return

        w = self._worker
        lines = []

        # Header with ID and type
        status_icon = {"idle": "○", "working": "●", "done": "✓"}.get(w.status.value, "?")
        status_color = {"idle": "dim", "working": "yellow", "done": "green"}.get(w.status.value, "white")
        lines.append(f"[bold]{w.type}[/bold] [{status_color}]{status_icon} {w.status.value}[/{status_color}]")
        lines.append(f"[dim]ID:[/dim] {self._worker_id}")

        # Task
        if w.current_task:
            task_display = w.current_task[:80] + "..." if len(w.current_task) > 80 else w.current_task
            lines.append(f"[dim]Task:[/dim] {task_display}")

        # Intention
        if w.intention:
            lines.append(f"[dim]On complete:[/dim] {w.intention.value}")

        # Tools
        if w.config and w.config.allowed_tools:
            tools = ", ".join(w.config.allowed_tools)
            lines.append(f"[dim]Tools:[/dim] {tools}")

        # Description from config
        if w.config and w.config.description:
            lines.append(f"[dim]Desc:[/dim] {w.config.description}")

        self.update("\n".join(lines))


class StreamingLog(RichLog):
    """A RichLog that handles streaming text without adding newlines between chunks."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._buffer = ""

    def write_streaming(self, text: str, style: str = "white") -> None:
        """Write streaming text, only outputting complete lines."""
        self._buffer += text

        # Output complete lines
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line:  # Don't write empty lines
                self.write(Text(line, style=style))

    def flush_buffer(self) -> None:
        """Flush any remaining buffered text."""
        if self._buffer:
            self.write(Text(self._buffer, style="white"))
            self._buffer = ""


class FederationApp(App):
    """Main terminal UI application."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 3 1;
        grid-columns: 2fr 1fr 1fr;
    }

    /* Left column - Chat */
    #chat-area {
        border: solid green;
        padding: 0 1;
    }

    /* Middle column - Workers, Details, Output */
    #middle-area {
        height: 100%;
    }

    #workers-area {
        border: solid blue;
        padding: 0 1;
        height: auto;
        max-height: 30%;
    }

    #worker-details-area {
        border: solid cyan;
        padding: 0 1;
        height: auto;
    }

    #worker-output-area {
        border: solid yellow;
        padding: 0 1;
        height: 1fr;
    }

    /* Right column - Event log (full height) */
    #event-log-area {
        border: solid gray;
        padding: 0 1;
    }

    #chat-log {
        height: 1fr;
    }

    #chat-input {
        dock: bottom;
        height: 3;
    }

    #worker-output {
        height: 100%;
    }

    #event-log {
        height: 100%;
    }

    #workers-listview {
        height: 100%;
    }

    WorkersList {
        height: 100%;
    }

    #worker-details {
        height: auto;
        padding: 0;
    }

    .section-title {
        text-style: bold;
        color: $text-muted;
        height: 1;
    }

    #filter-label {
        height: 1;
        color: $warning;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear", "Clear"),
        ("escape", "show_all_workers", "Show All"),
    ]

    def __init__(self, federation: Federation) -> None:
        super().__init__()
        self.federation = federation
        # Store all worker output for filtering
        self.all_worker_output: list[WorkerOutput] = []
        self.filter_worker_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        # Left column: Chat with master
        with Vertical(id="chat-area"):
            yield Label("Chat with Master", classes="section-title")
            yield StreamingLog(id="chat-log", highlight=True, markup=True)
            yield Input(placeholder="Message to master...", id="chat-input")

        # Middle column: Workers, Details, Output
        with Vertical(id="middle-area"):
            # Workers list (click to filter)
            with Container(id="workers-area"):
                yield Label("Workers (click to filter)", classes="section-title")
                yield WorkersList(id="workers-list")

            # Worker details
            with Container(id="worker-details-area"):
                yield Label("Worker Details", classes="section-title")
                yield WorkerDetails(id="worker-details")

            # Worker output
            with Vertical(id="worker-output-area"):
                yield Label("Worker Output", id="filter-label")
                yield RichLog(id="worker-output", highlight=True, markup=True)

        # Right column: Event log
        with Vertical(id="event-log-area"):
            yield Label("Event Log", classes="section-title")
            yield RichLog(id="event-log", highlight=True, markup=True)

        yield Footer()

    def on_mount(self) -> None:
        """Set up event handling when app mounts."""
        self.query_one("#chat-input", Input).focus()

        # Get widget references
        self.chat_log = self.query_one("#chat-log", StreamingLog)
        self.worker_output = self.query_one("#worker-output", RichLog)
        self.event_log = self.query_one("#event-log", RichLog)
        self.workers_list = self.query_one("#workers-list", WorkersList)
        self.worker_details = self.query_one("#worker-details", WorkerDetails)
        self.filter_label = self.query_one("#filter-label", Label)

        # Subscribe to events
        self.federation.event_bus.subscribe(self.handle_event)

        # Load initial workers
        self._refresh_workers()

        self.chat_log.write(Text("Ready. Type a message to begin.", style="dim"))

    def on_worker_filter_changed(self, message: WorkerFilterChanged) -> None:
        """Handle worker filter change."""
        self.filter_worker_id = message.worker_id
        self._update_filter_label()
        self._update_worker_details()
        self._redraw_worker_output()

    def action_show_all_workers(self) -> None:
        """Show output from all workers."""
        self.filter_worker_id = None
        self.workers_list.selected_id = None
        self._update_filter_label()
        self._update_worker_details()
        self._redraw_worker_output()

    def _update_worker_details(self) -> None:
        """Update the worker details panel based on current selection."""
        if self.filter_worker_id is None:
            self.worker_details.clear_worker()
        else:
            worker = self.federation.state.get_worker(self.filter_worker_id)
            if worker:
                self.worker_details.set_worker(self.filter_worker_id, worker)

    def _update_filter_label(self) -> None:
        """Update the filter label to show current filter."""
        if self.filter_worker_id:
            self.filter_label.update(f"Worker Output [{self.filter_worker_id[:8]}]")
        else:
            self.filter_label.update("Worker Output [ALL]")

    def _redraw_worker_output(self) -> None:
        """Redraw the worker output panel with current filter."""
        self.worker_output.clear()

        for output in self.all_worker_output:
            if self.filter_worker_id is None or output.worker_id == self.filter_worker_id:
                self._write_worker_line(output)

    def _write_worker_line(self, output: WorkerOutput) -> None:
        """Write a single worker output line."""
        short_id = output.worker_id[:8] if output.worker_id else "???"
        # Only show prefix if showing all workers
        if self.filter_worker_id is None:
            self.worker_output.write(Text(f"[{short_id}] {output.text}", style=output.style))
        else:
            self.worker_output.write(Text(output.text, style=output.style))

    def _add_worker_output(self, worker_id: str, text: str, style: str = "white") -> None:
        """Add worker output and display if matches filter."""
        output = WorkerOutput(worker_id=worker_id, text=text, style=style)
        self.all_worker_output.append(output)

        # Display if matches current filter
        if self.filter_worker_id is None or self.filter_worker_id == worker_id:
            self._write_worker_line(output)

    def handle_event(self, event: Event) -> None:
        """Handle events from the federation."""
        self.call_from_thread(self._process_event, event)

    def _process_event(self, event: Event) -> None:
        """Process event on the main thread."""
        # Always log to event log
        self._log_event(event)

        # Route by event type
        if event.type == EventType.MASTER_TEXT:
            text = event.data.get("text", "")
            if text:
                self.chat_log.write_streaming(text, style="white")

        elif event.type == EventType.MASTER_TOOL_CALL:
            tool_name = event.data.get("tool_name", "unknown")
            self.chat_log.flush_buffer()
            self.chat_log.write(Text(f"[{tool_name}]", style="cyan"))

        elif event.type == EventType.MASTER_TOOL_RESULT:
            pass  # Just logged in event log

        elif event.type == EventType.MASTER_DONE:
            self.chat_log.flush_buffer()
            self.chat_log.write(Text("─" * 20, style="dim"))

        elif event.type == EventType.WORKER_SPAWNED:
            self._refresh_workers()
            agent_type = event.data.get("agent_type", "")
            agent_id = event.agent_id or ""
            self.chat_log.flush_buffer()
            self.chat_log.write(Text(f">> Spawned {agent_type}: {agent_id[:8]}", style="blue"))

        elif event.type == EventType.WORKER_STARTED:
            self._refresh_workers()
            agent_id = event.agent_id or ""
            self._add_worker_output(agent_id, f"─── started ───", style="yellow bold")

        elif event.type == EventType.WORKER_TEXT:
            agent_id = event.agent_id or ""
            text = event.data.get("text", "")
            if text:
                # Handle multi-line text
                for line in text.split("\n"):
                    if line:
                        self._add_worker_output(agent_id, line, style="white")

        elif event.type == EventType.WORKER_TOOL_CALL:
            agent_id = event.agent_id or ""
            tool_name = event.data.get("tool_name", "")
            self._add_worker_output(agent_id, f"[calling {tool_name}]", style="cyan")

        elif event.type == EventType.WORKER_DONE:
            self._refresh_workers()
            agent_id = event.agent_id or ""
            self._add_worker_output(agent_id, f"─── done ───", style="green")
            self.chat_log.flush_buffer()
            self.chat_log.write(Text(f">> Worker {agent_id[:8]} completed", style="green"))

        elif event.type == EventType.STATUS_UPDATE:
            msg = event.data.get("message", "")
            self.chat_log.flush_buffer()
            self.chat_log.write(Text(f">> {msg}", style="blue"))

    def _refresh_workers(self) -> None:
        """Refresh the workers list and details."""
        workers = dict(self.federation.state.list_workers())
        self.workers_list.workers = workers
        # Also refresh details if a worker is selected (status may have changed)
        if self.filter_worker_id:
            self._update_worker_details()

    def _log_event(self, event: Event) -> None:
        """Log event to the event log."""
        try:
            event_type = event.type.value
            agent_id = event.agent_id[:8] if event.agent_id else ""

            # Format data compactly
            data_parts = []
            for k, v in event.data.items():
                v_str = str(v)
                if len(v_str) > 30:
                    v_str = v_str[:27] + "..."
                data_parts.append(f"{k}={v_str}")
            data_str = " ".join(data_parts) if data_parts else ""

            # Color code by event type
            if "worker" in event_type:
                style = "yellow"
            elif "master" in event_type:
                style = "cyan"
            else:
                style = "dim"

            if agent_id:
                line = f"[{event_type}] {agent_id} {data_str}"
            else:
                line = f"[{event_type}] {data_str}"

            self.event_log.write(Text(line, style=style))
        except Exception:
            pass

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input."""
        message = event.value.strip()
        if not message:
            return

        event.input.value = ""
        self.chat_log.flush_buffer()
        self.chat_log.write(Text(f"> {message}", style="bold green"))
        self.run_master(message)

    @work(thread=True, exclusive=True)
    def run_master(self, message: str) -> None:
        """Run the master agent in a background thread."""
        try:
            self.federation.run(message)
        except Exception as e:
            self.call_from_thread(
                self.chat_log.write,
                Text(f"[ERROR] {e}", style="red bold")
            )

    def action_clear(self) -> None:
        """Clear the chat log."""
        self.chat_log.clear()

    def action_quit(self) -> None:
        """Quit the app."""
        self.exit()
