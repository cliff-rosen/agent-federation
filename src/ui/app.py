"""Terminal UI application using Textual."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.containers import Vertical, Container
from textual.widgets import Header, Footer, Static, Input, RichLog, Label
from textual.reactive import reactive
from textual import work
from rich.text import Text
from rich.panel import Panel
from rich.table import Table

from ..shared.events import Event, EventType
from ..shared.types import WorkerStatus

if TYPE_CHECKING:
    from ..federation import Federation


class MasterStatus_Widget(Static):
    """Shows master agent status."""

    status: reactive[str] = reactive("idle")

    def render(self) -> Text:
        if self.status == "idle":
            return Text("Master: idle", style="dim")
        elif self.status == "thinking":
            return Text("Master: thinking...", style="yellow bold")
        else:
            return Text(f"Master: {self.status}", style="cyan bold")


class WorkersList(Static):
    """Shows all workers with their status."""

    workers: reactive[dict] = reactive({}, always_update=True)

    def render(self) -> Panel:
        if not self.workers:
            content = Text("No workers", style="dim")
        else:
            table = Table(box=None, show_header=False, padding=(0, 1))
            table.add_column("Status", width=3)
            table.add_column("ID", width=10)
            table.add_column("Type", width=12)
            table.add_column("Task", overflow="ellipsis")

            for worker_id, worker in self.workers.items():
                if worker.status == WorkerStatus.IDLE:
                    icon = Text("○", style="dim")
                    status_style = "dim"
                elif worker.status == WorkerStatus.WORKING:
                    icon = Text("●", style="yellow bold")
                    status_style = "yellow"
                else:  # DONE
                    icon = Text("✓", style="green bold")
                    status_style = "green"

                task = worker.current_task or ""
                if len(task) > 30:
                    task = task[:27] + "..."

                table.add_row(
                    icon,
                    Text(worker_id[:8], style=status_style),
                    Text(worker.type, style=status_style),
                    Text(task, style="dim"),
                )

            content = table

        return Panel(content, title="Workers", border_style="blue")


class FederationApp(App):
    """Main terminal UI application."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 3;
        grid-columns: 2fr 1fr;
        grid-rows: 1fr 1fr auto;
    }

    #left-top {
        border: solid green;
        padding: 0 1;
    }

    #right-top {
        padding: 0 1;
    }

    #left-bottom {
        border: solid yellow;
        padding: 0 1;
    }

    #right-bottom {
        border: solid gray;
        padding: 0 1;
    }

    #input-row {
        column-span: 2;
        height: 3;
        padding: 0 1;
    }

    #chat-log {
        height: 100%;
    }

    #worker-output {
        height: 100%;
    }

    #event-log {
        height: 100%;
    }

    MasterStatus_Widget {
        height: 1;
        margin-bottom: 1;
    }

    WorkersList {
        height: 100%;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear", "Clear"),
    ]

    def __init__(self, federation: Federation) -> None:
        super().__init__()
        self.federation = federation
        # Store output per worker so we don't lose it when switching
        self.worker_outputs: dict[str, list[str]] = {}
        self.active_worker_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        # Top row: Chat (left), Master+Workers (right)
        with Container(id="left-top"):
            yield Label("Chat with Master", classes="title")
            yield RichLog(id="chat-log", highlight=True, markup=True)

        with Vertical(id="right-top"):
            yield MasterStatus_Widget(id="master-status")
            yield WorkersList(id="workers-list")

        # Bottom row: Worker output (left), Event log (right)
        with Container(id="left-bottom"):
            yield Label("Worker Output", classes="title")
            yield RichLog(id="worker-output", highlight=True, markup=True)

        with Container(id="right-bottom"):
            yield Label("Event Log", classes="title")
            yield RichLog(id="event-log", highlight=True, markup=True)

        # Input row
        with Container(id="input-row"):
            yield Input(placeholder="Enter message for master agent...", id="input")

        yield Footer()

    def on_mount(self) -> None:
        """Set up event handling when app mounts."""
        self.query_one("#input", Input).focus()

        # Get widget references
        self.chat_log = self.query_one("#chat-log", RichLog)
        self.worker_output = self.query_one("#worker-output", RichLog)
        self.event_log = self.query_one("#event-log", RichLog)
        self.master_status = self.query_one("#master-status", MasterStatus_Widget)
        self.workers_list = self.query_one("#workers-list", WorkersList)

        # Subscribe to events
        self.federation.event_bus.subscribe(self.handle_event)

        self.chat_log.write(Text("Agent Federation ready. Type a message to begin.", style="blue"))

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
                self.chat_log.write(Text(text, style="white"), scroll_end=True)

        elif event.type == EventType.MASTER_TOOL_CALL:
            tool_name = event.data.get("tool_name", "unknown")
            self.chat_log.write(Text(f"[calling {tool_name}]", style="cyan"), scroll_end=True)
            self.master_status.status = f"calling {tool_name}"

        elif event.type == EventType.MASTER_TOOL_RESULT:
            self.master_status.status = "thinking"

        elif event.type == EventType.MASTER_DONE:
            self.chat_log.write(Text("─" * 30, style="dim"), scroll_end=True)
            self.master_status.status = "idle"

        elif event.type == EventType.WORKER_SPAWNED:
            self._refresh_workers()
            agent_type = event.data.get("agent_type", "")
            agent_id = event.agent_id or ""
            self.chat_log.write(
                Text(f">> Spawned {agent_type} worker: {agent_id}", style="blue"),
                scroll_end=True
            )
            # Initialize output storage for this worker
            self.worker_outputs[agent_id] = []

        elif event.type == EventType.WORKER_STARTED:
            self._refresh_workers()
            agent_id = event.agent_id or ""
            task = event.data.get("task", "")
            self.chat_log.write(
                Text(f">> Worker {agent_id} started: {task[:50]}", style="blue"),
                scroll_end=True
            )
            # Switch to this worker's output
            self._switch_to_worker(agent_id)

        elif event.type == EventType.WORKER_TEXT:
            agent_id = event.agent_id or ""
            text = event.data.get("text", "")
            if text:
                # Store the output
                if agent_id not in self.worker_outputs:
                    self.worker_outputs[agent_id] = []
                self.worker_outputs[agent_id].append(text)

                # Display if this is the active worker
                if agent_id == self.active_worker_id:
                    self.worker_output.write(Text(text, style="white"), scroll_end=True)

        elif event.type == EventType.WORKER_TOOL_CALL:
            agent_id = event.agent_id or ""
            tool_name = event.data.get("tool_name", "")
            if agent_id == self.active_worker_id:
                self.worker_output.write(
                    Text(f"[{tool_name}]", style="cyan"),
                    scroll_end=True
                )

        elif event.type == EventType.WORKER_DONE:
            self._refresh_workers()
            agent_id = event.agent_id or ""
            self.chat_log.write(
                Text(f">> Worker {agent_id} completed", style="green"),
                scroll_end=True
            )
            if agent_id == self.active_worker_id:
                self.worker_output.write(
                    Text("─── DONE ───", style="green bold"),
                    scroll_end=True
                )

        elif event.type == EventType.STATUS_UPDATE:
            msg = event.data.get("message", "")
            self.chat_log.write(Text(f">> {msg}", style="blue"), scroll_end=True)

    def _refresh_workers(self) -> None:
        """Refresh the workers list."""
        self.workers_list.workers = dict(self.federation.state.list_workers())

    def _switch_to_worker(self, worker_id: str) -> None:
        """Switch worker output panel to show a specific worker."""
        self.active_worker_id = worker_id
        self.worker_output.clear()
        self.worker_output.write(
            Text(f"=== Worker {worker_id} ===", style="bold yellow"),
            scroll_end=True
        )
        # Replay any stored output for this worker
        if worker_id in self.worker_outputs:
            for text in self.worker_outputs[worker_id]:
                self.worker_output.write(Text(text, style="white"), scroll_end=True)

    def _log_event(self, event: Event) -> None:
        """Log event to the event log."""
        try:
            event_type = event.type.value
            agent_id = event.agent_id or ""

            # Format data, truncating long values
            data_parts = []
            for k, v in event.data.items():
                v_str = str(v)
                if len(v_str) > 40:
                    v_str = v_str[:37] + "..."
                data_parts.append(f"{k}={v_str}")
            data_str = ", ".join(data_parts) if data_parts else ""

            if agent_id:
                line = f"[{event_type}] ({agent_id}) {data_str}"
            else:
                line = f"[{event_type}] {data_str}"

            self.event_log.write(Text(line, style="dim"), scroll_end=True)
        except Exception:
            pass

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input."""
        message = event.value.strip()
        if not message:
            return

        event.input.value = ""
        self.chat_log.write(Text(f"> {message}", style="bold green"), scroll_end=True)
        self.master_status.status = "thinking"
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
        finally:
            self.call_from_thread(setattr, self.master_status, "status", "idle")

    def action_clear(self) -> None:
        """Clear the chat log."""
        self.chat_log.clear()

    def action_quit(self) -> None:
        """Quit the app."""
        self.exit()
