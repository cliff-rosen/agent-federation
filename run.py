"""Launch the Agent Federation terminal UI."""

import os
import sys

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.shared.events import EventBus
from src.master.loop import MasterAgent
from src.master.state import StateManager
from src.workers.runner import WorkerRunner
from src.ui.app import FederationApp


def main():
    # Ensure workspace exists
    workspace_path = os.path.join(os.path.dirname(__file__), "workspace")
    os.makedirs(workspace_path, exist_ok=True)

    # Create shared event bus
    event_bus = EventBus()

    # Create state manager
    state_manager = StateManager(workspace_path=workspace_path)

    # Create master agent with shared state and events
    master = MasterAgent(
        workspace_path=workspace_path,
        state_manager=state_manager,
        event_bus=event_bus,
    )

    # Create worker runner
    worker_runner = WorkerRunner(
        event_bus=event_bus,
        workspace_path=workspace_path,
    )
    master.set_worker_runner(worker_runner)

    # Launch the UI
    app = FederationApp(master, worker_runner, state_manager)
    app.run()


if __name__ == "__main__":
    main()
