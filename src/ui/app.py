"""Terminal UI application using Textual."""

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Input, RichLog
from textual.reactive import reactive
from textual import work
from rich.text import Text
from rich.panel import Panel
from rich.table import Table

from ..shared.events import Event, EventType
from ..shared.types import WorkerStatus, MasterStatus


class MasterPanel(Static):
    """Panel showing master agent status."""

    status: reactive[MasterStatus] = reactive(MasterStatus.IDLE)
    current_tool: reactive[str | None] = reactive(None)

    def render(self) -> Panel:
        if self.status == MasterStatus.IDLE:
            status_text = Text("idle", style="dim")
        elif self.status == MasterStatus.THINKING:
            status_text = Text("thinking...", style="yellow")
        elif self.status == MasterStatus.CALLING_TOOL:
            tool = self.current_tool or "unknown"
            status_text = Text(f"calling {tool}", style="cyan")
        else:
            status_text = Text(str(self.status), style="white")

        return Panel(status_text, title="Master", border_style="green")


class WorkersPanel(Static):
    """Panel showing all workers and their status."""

    workers: reactive[dict] = reactive({}, always_update=True)

    def render(self) -> Panel:
        if not self.workers:
            content = Text("No workers", style="dim")
            return Panel(content, title="Workers", border_style="blue")

        table = Table(box=None, expand=True, show_header=False, padding=(0, 1))
        table.add_column("Worker", style="bold", no_wrap=True)
        table.add_column("Status", justify="right", no_wrap=True)

        for worker_id, worker in self.workers.items():
            # Status indicator
            if worker.status == WorkerStatus.IDLE:
                status_text = Text("idle", style="dim")
                icon = "○"
            elif worker.status == WorkerStatus.WORKING:
                status_text = Text("working", style="yellow bold")
                icon = "●"
            else:  # DONE
                status_text = Text("done", style="green")
                icon = "✓"

            # Worker name with icon
            name_text = Text(f"{icon} {worker.type}-{worker_id[:4]}", style="white")
            table.add_row(name_text, status_text)

            # Show current task if working
            if worker.status == WorkerStatus.WORKING and worker.current_task:
                task_preview = worker.current_task[:35]
                if len(worker.current_task) > 35:
                    task_preview += "..."
                table.add_row(
                    Text(f"  {task_preview}", style="dim italic"),
                    Text("")
                )

            # Show result preview if done
            if worker.status == WorkerStatus.DONE and worker.result:
                result_preview = worker.result[:35].replace("\n", " ")
                if len(worker.result) > 35:
                    result_preview += "..."
                table.add_row(
                    Text(f"  → {result_preview}", style="green dim"),
                    Text("")
                )

        return Panel(table, title="Workers", border_style="blue")


class ChatLog(RichLog):
    """Chat log with message styling."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._streaming_buffer = ""
        self._streaming_style = "white"

    def _flush_buffer(self) -> None:
        """Write any buffered streaming text."""
        if self._streaming_buffer:
            lines = self._streaming_buffer.split("\n")
            for line in lines:
                if line:
                    self.write(Text(line, style=self._streaming_style))
            self._streaming_buffer = ""

    def add_user_message(self, text: str) -> None:
        self._flush_buffer()
        self.write(Text(f"> {text}", style="bold green"))

    def add_master_text(self, text: str) -> None:
        """Buffer streaming text from master."""
        self._streaming_style = "white"
        self._streaming_buffer += text
        if "\n" in self._streaming_buffer:
            parts = self._streaming_buffer.rsplit("\n", 1)
            if len(parts) == 2:
                complete, remainder = parts
                for line in complete.split("\n"):
                    if line:
                        self.write(Text(line, style=self._streaming_style))
                self._streaming_buffer = remainder

    def add_tool_call(self, tool_name: str) -> None:
        self._flush_buffer()
        self.write(Text(f"[{tool_name}]", style="cyan"))

    def add_worker_output(self, worker_id: str, text: str) -> None:
        """Show worker output."""
        self._flush_buffer()
        for line in text.split("\n"):
            if line:
                self.write(Text(f"  [{worker_id}] {line}", style="dim"))

    def add_status(self, message: str) -> None:
        self._flush_buffer()
        self.write(Text(f">> {message}", style="blue"))

    def add_error(self, message: str) -> None:
        self._flush_buffer()
        self.write(Text(f"[error] {message}", style="red bold"))

    def add_separator(self) -> None:
        self._flush_buffer()
        self.write(Text("─" * 40, style="dim"))


class FederationApp(App):
    """Main terminal UI application."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 2;
        grid-columns: 3fr 1fr;
        grid-rows: 1fr auto;
    }

    #chat-container {
        row-span: 1;
        border: solid green;
        padding: 0 1;
    }

    #sidebar {
        row-span: 1;
        padding: 0 1;
        min-width: 30;
    }

    #input-container {
        column-span: 2;
        height: 3;
        padding: 0 1;
    }

    ChatLog {
        background: $surface;
    }

    MasterPanel {
        height: auto;
        margin-bottom: 1;
    }

    WorkersPanel {
        height: auto;
    }

    Input {
        dock: bottom;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear", "Clear"),
    ]

    def __init__(self, master_agent, worker_runner, state_manager):
        super().__init__()
        self.master = master_agent
        self.worker_runner = worker_runner
        self.state_manager = state_manager

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal():
            with Vertical(id="chat-container"):
                yield ChatLog(id="chat", highlight=True, markup=True)

            with Vertical(id="sidebar"):
                yield MasterPanel(id="master-panel")
                yield WorkersPanel(id="workers-panel")

        with Horizontal(id="input-container"):
            yield Input(placeholder="Enter message...", id="input")

        yield Footer()

    def on_mount(self) -> None:
        """Set up event handling when app mounts."""
        self.query_one("#input", Input).focus()
        self.chat = self.query_one("#chat", ChatLog)
        self.master_panel = self.query_one("#master-panel", MasterPanel)
        self.workers_panel = self.query_one("#workers-panel", WorkersPanel)

        # Subscribe to events
        self.master.event_bus.subscribe(self.handle_event)

        self.chat.add_status("Agent Federation ready")

    def handle_event(self, event: Event) -> None:
        """Handle events from the federation."""
        self.call_from_thread(self._process_event, event)

    def _process_event(self, event: Event) -> None:
        """Process event on the main thread."""
        # Master events
        if event.type == EventType.MASTER_TEXT:
            self.chat.add_master_text(event.data.get("text", ""))

        elif event.type == EventType.MASTER_TOOL_CALL:
            tool_name = event.data.get("tool_name", "unknown")
            self.chat.add_tool_call(tool_name)
            self.master_panel.status = MasterStatus.CALLING_TOOL
            self.master_panel.current_tool = tool_name

        elif event.type == EventType.MASTER_TOOL_RESULT:
            self.master_panel.status = MasterStatus.THINKING

        elif event.type == EventType.MASTER_DONE:
            self.chat.add_separator()
            self.master_panel.status = MasterStatus.IDLE
            self.master_panel.current_tool = None

        # Worker events
        elif event.type == EventType.WORKER_SPAWNED:
            self._refresh_workers()
            agent_type = event.data.get("agent_type", "")
            agent_id = event.data.get("agent_id", "")
            self.chat.add_status(f"Spawned {agent_type} worker: {agent_id}")

        elif event.type == EventType.WORKER_STARTED:
            self._refresh_workers()
            agent_id = event.data.get("agent_id", "")
            self.chat.add_status(f"Worker {agent_id} started")

        elif event.type == EventType.WORKER_TEXT:
            pass  # Workers run in background, we show result when done

        elif event.type == EventType.WORKER_DONE:
            self._refresh_workers()
            agent_id = event.data.get("agent_id", "")
            self.chat.add_status(f"Worker {agent_id} completed")

        elif event.type == EventType.STATUS_UPDATE:
            self.chat.add_status(event.data.get("message", ""))

    def _refresh_workers(self) -> None:
        """Refresh the workers panel."""
        self.workers_panel.workers = dict(self.state_manager.state.workers)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input."""
        message = event.value.strip()
        if not message:
            return

        event.input.value = ""
        self.chat.add_user_message(message)
        self.master_panel.status = MasterStatus.THINKING
        self.run_master(message)

    @work(thread=True)
    def run_master(self, message: str) -> None:
        """Run the master agent in a background thread."""
        try:
            self.master.run(message)
        except Exception as e:
            self.call_from_thread(self.chat.add_error, str(e))
            self.call_from_thread(
                setattr, self.master_panel, "status", MasterStatus.IDLE
            )

    def action_clear(self) -> None:
        """Clear the chat log."""
        self.chat.clear()

    def action_quit(self) -> None:
        """Quit the app."""
        self.exit()
