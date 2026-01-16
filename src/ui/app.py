"""Terminal UI application using Textual."""

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Input, RichLog, ListView, ListItem, Label
from textual.reactive import reactive
from textual.message import Message
from textual import work
from rich.text import Text
from rich.panel import Panel

from ..shared.events import Event, EventType
from ..shared.types import WorkerStatus, MasterStatus


class WorkerSelected(Message):
    """Message sent when a worker is selected."""
    def __init__(self, worker_id: str | None) -> None:
        self.worker_id = worker_id
        super().__init__()


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


class WorkerItem(ListItem):
    """A clickable worker item."""

    def __init__(self, worker_id: str, worker) -> None:
        super().__init__()
        self.worker_id = worker_id
        self.worker = worker

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

        label = f"{icon} {worker.type}-{self.worker_id[:4]} [{worker.status.value}]"
        yield Label(label, classes=style)


class WorkersPanel(Static):
    """Panel showing all workers - click to select."""

    worker_data: reactive[dict] = reactive({}, always_update=True)
    selected_id: reactive[str | None] = reactive(None)

    def compose(self) -> ComposeResult:
        yield ListView(id="workers-list")

    def watch_worker_data(self, worker_data: dict) -> None:
        """Update the list when workers change."""
        list_view = self.query_one("#workers-list", ListView)
        list_view.clear()

        if not worker_data:
            list_view.append(ListItem(Label("No workers", classes="dim")))
            return

        for worker_id, worker in worker_data.items():
            item = WorkerItem(worker_id, worker)
            if worker_id == self.selected_id:
                item.highlighted = True
            list_view.append(item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle worker selection."""
        if isinstance(event.item, WorkerItem):
            self.selected_id = event.item.worker_id
            self.post_message(WorkerSelected(event.item.worker_id))


class WorkerOutputPanel(Static):
    """Panel showing selected worker's streaming output."""

    worker_id: reactive[str | None] = reactive(None)

    def compose(self) -> ComposeResult:
        yield RichLog(id="worker-output", highlight=True, markup=True)

    @property
    def log(self) -> RichLog:
        return self.query_one("#worker-output", RichLog)

    def set_worker(self, worker_id: str | None, worker=None) -> None:
        """Set the worker to display."""
        self.worker_id = worker_id
        try:
            self.log.clear()
            if worker_id and worker:
                self.log.write(Text(f"Worker: {worker.type}-{worker_id[:4]}", style="bold"))
                if worker.current_task:
                    self.log.write(Text(f"Task: {worker.current_task}", style="dim"))
                self.log.write(Text("─" * 30, style="dim"))
        except Exception:
            pass  # Widget not ready yet

    def add_text(self, text: str) -> None:
        """Add streaming text."""
        try:
            self.log.write(Text(text, style="white"))
        except Exception:
            pass

    def add_tool_call(self, tool_name: str) -> None:
        """Add tool call."""
        try:
            self.log.write(Text(f"[{tool_name}]", style="cyan"))
        except Exception:
            pass

    def add_done(self, result: str) -> None:
        """Mark complete."""
        try:
            self.log.write(Text("─" * 30, style="dim"))
            self.log.write(Text("Done", style="green bold"))
        except Exception:
            pass


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
        grid-size: 2 3;
        grid-columns: 3fr 1fr;
        grid-rows: 2fr 1fr auto;
    }

    #chat-container {
        row-span: 1;
        border: solid green;
        padding: 0 1;
    }

    #sidebar-top {
        row-span: 1;
        padding: 0 1;
        min-width: 30;
    }

    #sidebar-bottom {
        row-span: 1;
        padding: 0 1;
        min-width: 30;
        border: solid blue;
    }

    #worker-detail {
        row-span: 1;
        border: solid yellow;
        padding: 0 1;
    }

    #input-container {
        column-span: 2;
        height: 3;
        padding: 0 1;
    }

    ChatLog {
        background: $surface;
    }

    #worker-output {
        background: $surface;
        height: 100%;
    }

    MasterPanel {
        height: auto;
        margin-bottom: 1;
    }

    WorkersPanel {
        height: 100%;
    }

    #workers-list {
        height: 100%;
    }

    Input {
        dock: bottom;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear", "Clear"),
        ("escape", "deselect", "Deselect"),
    ]

    def __init__(self, master_agent, worker_runner, state_manager):
        super().__init__()
        self.master = master_agent
        self.worker_runner = worker_runner
        self.state_manager = state_manager
        self.selected_worker_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal():
            with Vertical(id="chat-container"):
                yield ChatLog(id="chat", highlight=True, markup=True)

            with Vertical(id="sidebar-top"):
                yield MasterPanel(id="master-panel")
                yield WorkersPanel(id="workers-panel")

        with Horizontal():
            with Vertical(id="worker-detail"):
                yield WorkerOutputPanel(id="worker-output-panel")

        with Horizontal(id="input-container"):
            yield Input(placeholder="Enter message...", id="input")

        yield Footer()

    def on_mount(self) -> None:
        """Set up event handling when app mounts."""
        self.query_one("#input", Input).focus()
        self.chat = self.query_one("#chat", ChatLog)
        self.master_panel = self.query_one("#master-panel", MasterPanel)
        self.workers_panel = self.query_one("#workers-panel", WorkersPanel)
        self.worker_output = self.query_one("#worker-output-panel", WorkerOutputPanel)

        # Subscribe to events
        self.master.event_bus.subscribe(self.handle_event)

        self.chat.add_status("Agent Federation ready")
        self.chat.add_status("Click a worker to see its output")

    def on_worker_selected(self, message: WorkerSelected) -> None:
        """Handle worker selection."""
        self.selected_worker_id = message.worker_id
        worker = self.state_manager.get_worker(message.worker_id) if message.worker_id else None
        self.worker_output.set_worker(message.worker_id, worker)

    def action_deselect(self) -> None:
        """Deselect worker."""
        self.selected_worker_id = None
        self.workers_panel.selected_id = None
        self.worker_output.set_worker(None, None)

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
            agent_id = event.agent_id or ""
            self.chat.add_status(f"Spawned {agent_type} worker: {agent_id}")

        elif event.type == EventType.WORKER_STARTED:
            self._refresh_workers()
            agent_id = event.agent_id or ""
            self.chat.add_status(f"Worker {agent_id} started")
            # Auto-select the started worker
            self.selected_worker_id = agent_id
            self.workers_panel.selected_id = agent_id
            worker = self.state_manager.get_worker(agent_id)
            self.worker_output.set_worker(agent_id, worker)

        elif event.type == EventType.WORKER_TEXT:
            agent_id = event.agent_id or ""
            text = event.data.get("text", "")
            # Show in worker output if this worker is selected
            if agent_id == self.selected_worker_id:
                self.worker_output.add_text(text)

        elif event.type == EventType.WORKER_TOOL_CALL:
            agent_id = event.agent_id or ""
            tool_name = event.data.get("tool_name", "")
            # Show in worker output if this worker is selected
            if agent_id == self.selected_worker_id:
                self.worker_output.add_tool_call(tool_name)

        elif event.type == EventType.WORKER_DONE:
            self._refresh_workers()
            agent_id = event.agent_id or ""
            result = event.data.get("result", "")
            self.chat.add_status(f"Worker {agent_id} completed")
            # Update worker output if selected
            if agent_id == self.selected_worker_id:
                self.worker_output.add_done(result)

        elif event.type == EventType.STATUS_UPDATE:
            self.chat.add_status(event.data.get("message", ""))

    def _refresh_workers(self) -> None:
        """Refresh the workers panel."""
        self.workers_panel.worker_data = dict(self.state_manager.state.workers)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input."""
        message = event.value.strip()
        if not message:
            return

        event.input.value = ""
        self.chat.add_user_message(message)
        self.master_panel.status = MasterStatus.THINKING
        self.run_master(message)

    @work(thread=True, exclusive=True)
    def run_master(self, message: str) -> None:
        """Run the master agent in a background thread."""
        try:
            self.master.run(message)
        except Exception as e:
            self.call_from_thread(self.chat.add_error, str(e))
        finally:
            self.call_from_thread(
                setattr, self.master_panel, "status", MasterStatus.IDLE
            )

    def action_clear(self) -> None:
        """Clear the chat log."""
        self.chat.clear()

    def action_quit(self) -> None:
        """Quit the app."""
        self.workers.cancel_all()
        self.exit()
