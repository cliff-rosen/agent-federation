"""Launch the Agent Federation terminal UI."""

import os
import sys

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.federation import Federation
from src.ui.app import FederationApp


def main():
    workspace_path = os.path.join(os.path.dirname(__file__), "workspace")

    # Create the federation - it owns all components
    federation = Federation(workspace_path=workspace_path)

    # Launch the UI
    app = FederationApp(federation)
    app.run()


if __name__ == "__main__":
    main()
