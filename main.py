"""Main entry point for the Agent Federation System.

Test scenarios:
1. Basic: Ask master a simple question (no delegation)
2. Delegation: Ask master something that requires spawning a worker

Example usage:
    python main.py "What is 2 + 2?"
    python main.py "Spawn a general worker and have it write a haiku to haiku.txt"
"""

import sys
import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.shared.events import EventBus, console_event_handler
from src.master.loop import MasterAgent
from src.workers.runner import WorkerRunner


def main():
    # Ensure workspace exists
    workspace_path = os.path.join(os.path.dirname(__file__), "workspace")
    os.makedirs(workspace_path, exist_ok=True)

    # Create event bus with console handler
    event_bus = EventBus()
    event_bus.subscribe(console_event_handler)

    # Create master agent
    master = MasterAgent(workspace_path=workspace_path)
    master.event_bus = event_bus  # Share event bus

    # Create worker runner and connect to master
    worker_runner = WorkerRunner(
        event_bus=event_bus,
        workspace_path=workspace_path,
    )
    master.set_worker_runner(worker_runner)

    # Get user input
    if len(sys.argv) > 1:
        user_message = " ".join(sys.argv[1:])
    else:
        print("Agent Federation System")
        print("=" * 40)
        print("\nEnter your request (or 'quit' to exit):\n")
        user_message = input("> ").strip()
        if user_message.lower() == "quit":
            return

    print(f"\n{'=' * 40}")
    print("Processing...\n")

    # Run the master agent
    response = master.run(user_message)

    print(f"\n{'=' * 40}")
    print("Final Response:")
    print(response)


def interactive():
    """Run in interactive mode."""
    workspace_path = os.path.join(os.path.dirname(__file__), "workspace")
    os.makedirs(workspace_path, exist_ok=True)

    event_bus = EventBus()
    event_bus.subscribe(console_event_handler)

    master = MasterAgent(workspace_path=workspace_path)
    master.event_bus = event_bus

    worker_runner = WorkerRunner(
        event_bus=event_bus,
        workspace_path=workspace_path,
    )
    master.set_worker_runner(worker_runner)

    print("Agent Federation System - Interactive Mode")
    print("=" * 40)
    print("Type 'quit' to exit\n")

    while True:
        user_message = input("\n> ").strip()
        if user_message.lower() == "quit":
            break
        if not user_message:
            continue

        print(f"\n{'─' * 40}\n")

        try:
            master.run(user_message)
            print(f"\n{'─' * 40}")
            print("Done.")
        except KeyboardInterrupt:
            print("\n\nInterrupted.")
        except Exception as e:
            print(f"\nError: {e}")


if __name__ == "__main__":
    if "--interactive" in sys.argv or "-i" in sys.argv:
        interactive()
    else:
        main()
