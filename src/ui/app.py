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
from ..shared.types import AgentStatus


class AgentPanel(Static):
    """Panel showing all agents and their status."""

    agents: reactive[dict] = reactive({}, always_update=True)

    def render(self) -> Panel:
        table = Table(box=None, expand=True, show_header=False)
        table.add_column("Agent", style="bold")
        table.add_column("Status", justify="right")

        # Always show master
        table.add_row(
            Text("master", style="cyan"),
            Text("active", style="green")
        )

        # Show workers
        for agent_id, agent in self.agents.items():
            status = agent.status
            if status == AgentStatus.IDLE:
                status_text = Text("idle", style="dim")
                icon = "○"
            elif status == AgentStatus.BUSY:
                status_text = Text("busy", style="yellow bold")
                icon = "●"
            else:  # HAS_RESULT
                status_text = Text("done", style="green")
                icon = "✓"

            agent_text = Text(f"{icon} {agent_id}", style="white")
            table.add_row(agent_text, status_text)

            # Show agent type below
            type_text = Text(f"  └─ {agent.config.name}", style="dim")
            table.add_row(type_text, Text(""))

        if not self.agents:
            table.add_row(
                Text("  (no workers)", style="dim"),
                Text("")
            )

        return Panel(table, title="Agents", border_style="blue")


class DelegationPanel(Static):
    """Panel showing active delegations."""

    delegations: reactive[dict] = reactive({}, always_update=True)

    def render(self) -> Panel:
        lines = []

        active = [d for d in self.delegations.values() if d.completed_at is None]
        completed = [d for d in self.delegations.values() if d.completed_at is not None]

        if active:
            for d in active:
                lines.append(Text(f"● {d.agent_id}", style="yellow"))
                lines.append(Text(f"  {d.task[:30]}...", style="dim"))
                lines.append(Text(f"  → {d.intention.type.value}", style="cyan"))
        elif completed:
            lines.append(Text(f"✓ {len(completed)} completed", style="green dim"))
        else:
            lines.append(Text("(none)", style="dim"))

        content = Text("\n").join(lines) if lines else Text("(none)", style="dim")
        return Panel(content, title="Delegations", border_style="blue")


class ChatLog(RichLog):
    """Chat log with message styling."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._streaming_buffer = ""
        self._streaming_style = "white"

    def _flush_buffer(self) -> None:
        """Write any buffered streaming text."""
        if self._streaming_buffer:
            self.write(Text(self._streaming_buffer, style=self._streaming_style))
            self._streaming_buffer = ""

    def add_user_message(self, text: str) -> None:
        self._flush_buffer()
        self.write(Text(f"> {text}", style="bold green"))

    def add_master_text(self, text: str) -> None:
        """Buffer streaming text from master."""
        self._streaming_style = "white"
        self._streaming_buffer += text
        # Write on newlines or periodically
        if "\n" in text or len(self._streaming_buffer) > 80:
            self._flush_buffer()

    def add_master_tool(self, tool_name: str) -> None:
        self._flush_buffer()
        self.write(Text(f"[tool] {tool_name}", style="cyan"))

    def add_worker_text(self, agent_id: str, text: str) -> None:
        """Buffer streaming text from worker."""
        self._streaming_style = "dim"
        self._streaming_buffer += text
        if "\n" in text or len(self._streaming_buffer) > 80:
            self._flush_buffer()

    def add_worker_start(self, agent_id: str) -> None:
        self._flush_buffer()
        self._streaming_buffer = f"[{agent_id}] "
        self._streaming_style = "yellow"

    def add_status(self, message: str) -> None:
        self._flush_buffer()
        self.write(Text(f">> {message}", style="blue"))

    def add_error(self, message: str) -> None:
        self._flush_buffer()
        self.write(Text(f"[error] {message}", style="red bold"))

    def add_done(self) -> None:
        self._flush_buffer()
        self.write(Text("---", style="dim"))


class FederationApp(App):
    """Main terminal UI application."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 3 2;
        grid-columns: 2fr 1fr;
        grid-rows: 1fr auto;
    }

    #chat-container {
        column-span: 1;
        row-span: 1;
        border: solid green;
        padding: 0 1;
    }

    #sidebar {
        column-span: 1;
        row-span: 1;
        padding: 0;
    }

    #input-container {
        column-span: 2;
        height: 3;
        padding: 0 1;
    }

    ChatLog {
        background: $surface;
    }

    AgentPanel {
        height: auto;
        margin-bottom: 1;
    }

    DelegationPanel {
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
        self._current_worker_id = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal():
            with Vertical(id="chat-container"):
                yield ChatLog(id="chat", highlight=True, markup=True)

            with Vertical(id="sidebar"):
                yield AgentPanel(id="agents")
                yield DelegationPanel(id="delegations")

        with Horizontal(id="input-container"):
            yield Input(placeholder="Enter message...", id="input")

        yield Footer()

    def on_mount(self) -> None:
        """Set up event handling when app mounts."""
        self.query_one("#input", Input).focus()
        self.chat = self.query_one("#chat", ChatLog)
        self.agent_panel = self.query_one("#agents", AgentPanel)
        self.delegation_panel = self.query_one("#delegations", DelegationPanel)

        # Subscribe to events
        self.master.event_bus.subscribe(self.handle_event)

        self.chat.add_status("Agent Federation System ready")
        self.chat.add_status("Type a message to begin")

    def handle_event(self, event: Event) -> None:
        """Handle events from the federation."""
        # Use call_from_thread to safely update UI from worker thread
        self.call_from_thread(self._process_event, event)

    def _process_event(self, event: Event) -> None:
        """Process event on the main thread."""
        if event.type == EventType.MASTER_TEXT:
            self.chat.add_master_text(event.data.get("text", ""))

        elif event.type == EventType.MASTER_TOOL_CALL:
            tool_name = event.data.get("tool_name", "unknown")
            self.chat.add_master_tool(tool_name)

        elif event.type == EventType.MASTER_DONE:
            self.chat.add_done()
            self._current_worker_id = None

        elif event.type == EventType.WORKER_SPAWNED:
            agent_id = event.data.get("agent_id", "")
            agent_type = event.data.get("agent_type", "")
            self.chat.add_status(f"Spawned {agent_type} worker: {agent_id}")
            self._refresh_agents()

        elif event.type == EventType.WORKER_TEXT:
            agent_id = event.data.get("agent_id", "")
            text = event.data.get("text", "")
            if self._current_worker_id != agent_id:
                self._current_worker_id = agent_id
                self.chat.add_worker_start(agent_id)
            self.chat.add_worker_text(agent_id, text)

        elif event.type == EventType.WORKER_TOOL_CALL:
            agent_id = event.data.get("agent_id", "")
            tool_name = event.data.get("tool_name", "")
            self.chat.add_status(f"[{agent_id}] using {tool_name}")

        elif event.type == EventType.WORKER_DONE:
            agent_id = event.data.get("agent_id", "")
            self.chat.add_status(f"Worker {agent_id} completed")
            self._refresh_agents()

        elif event.type == EventType.DELEGATION_STARTED:
            self._refresh_delegations()

        elif event.type == EventType.DELEGATION_COMPLETED:
            self._refresh_delegations()

        elif event.type == EventType.STATUS_UPDATE:
            self.chat.add_status(event.data.get("message", ""))

    def _refresh_agents(self) -> None:
        """Refresh the agents panel."""
        self.agent_panel.agents = dict(self.state_manager.state.workers)

    def _refresh_delegations(self) -> None:
        """Refresh the delegations panel."""
        self.delegation_panel.delegations = dict(self.state_manager.state.delegations)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input."""
        message = event.value.strip()
        if not message:
            return

        # Clear input
        event.input.value = ""

        # Show user message
        self.chat.add_user_message(message)

        # Run master agent in background worker
        self.run_master(message)

    @work(thread=True)
    def run_master(self, message: str) -> None:
        """Run the master agent in a background thread."""
        try:
            self.master.run(message)
        except Exception as e:
            self.call_from_thread(self.chat.add_error, str(e))

    def action_clear(self) -> None:
        """Clear the chat log."""
        self.chat.clear()

    def action_quit(self) -> None:
        """Quit the app."""
        self.exit()
