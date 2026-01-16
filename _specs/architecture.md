# Agent Federation Architecture

## Overview

The Agent Federation is a multi-agent orchestration system where a Master Agent coordinates work across specialized worker agents. This document describes the implementation architecture.

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Federation                                 │
│  (Central coordinator - owns all shared resources)                  │
│                                                                      │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────────┐ │
│  │  EventBus   │  │ StateManager │  │      workspace_path         │ │
│  │             │  │              │  │                             │ │
│  │ - handlers  │  │ - workers    │  │  "./workspace"              │ │
│  │ - emit()    │  │ - configs    │  │                             │ │
│  │             │  │ - completed  │  │                             │ │
│  └─────────────┘  └──────────────┘  └─────────────────────────────┘ │
│         │                │                        │                  │
│         └────────────────┼────────────────────────┘                  │
│                          │                                           │
│              ┌───────────┴───────────┐                              │
│              │                       │                              │
│              ▼                       ▼                              │
│  ┌─────────────────────┐  ┌─────────────────────┐                   │
│  │    MasterAgent      │  │   WorkerRunner      │                   │
│  │                     │  │                     │                   │
│  │ - client (Anthropic)│  │ - _threads          │                   │
│  │ - tool_executor     │  │ - start_worker()    │                   │
│  │ - conversation      │  │                     │                   │
│  │ - run()             │  │                     │                   │
│  └─────────────────────┘  └─────────────────────┘                   │
│              │                       │                              │
│              ▼                       │                              │
│  ┌─────────────────────┐             │                              │
│  │   ToolExecutor      │─────────────┘                              │
│  │                     │  (calls worker_runner.start_worker)        │
│  │ - execute()         │                                            │
│  │ - _tool_spawn_*     │                                            │
│  │ - _tool_delegate    │                                            │
│  └─────────────────────┘                                            │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ events
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        FederationApp (UI)                           │
│                                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────────┐  │
│  │  ChatLog    │  │ MasterPanel │  │      WorkersPanel           │  │
│  │             │  │             │  │                             │  │
│  │ - messages  │  │ - status    │  │  - worker_data              │  │
│  │ - streaming │  │ - tool      │  │  - selected_id              │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────────┘  │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │                    WorkerOutputPanel                            ││
│  │                                                                  ││
│  │  - Streaming output from selected worker                        ││
│  └─────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

## Core Components

### Federation (`src/federation.py`)

The central coordinator that owns all shared resources. Components access resources through their federation reference rather than holding direct references to each other.

```python
class Federation:
    def __init__(self, workspace_path: str | None = None):
        self.workspace_path = workspace_path
        self.event_bus = EventBus()
        self.state = StateManager(workspace_path)

    @property
    def master(self) -> MasterAgent:
        # Lazy creation
        if self._master is None:
            self._master = MasterAgent(self)
        return self._master

    @property
    def worker_runner(self) -> WorkerRunner:
        # Lazy creation
        if self._worker_runner is None:
            self._worker_runner = WorkerRunner(self)
        return self._worker_runner

    def run(self, message: str) -> str:
        return self.master.run(message)
```

**Key design decisions:**
- Lazy properties for `master` and `worker_runner` avoid circular dependency issues
- Single source of truth for `workspace_path`
- All components can access any shared resource via `self.federation`

### EventBus (`src/shared/events.py`)

Pub/sub system for streaming events throughout the federation.

**Event Types:**
| Event | Source | Data |
|-------|--------|------|
| `MASTER_TEXT` | MasterAgent | `{text: str}` |
| `MASTER_TOOL_CALL` | ToolExecutor | `{tool_name: str, tool_input: dict}` |
| `MASTER_TOOL_RESULT` | ToolExecutor | `{tool_name: str, result: Any}` |
| `MASTER_DONE` | MasterAgent | `{}` |
| `WORKER_SPAWNED` | ToolExecutor | `{agent_type: str}` + `agent_id` |
| `WORKER_STARTED` | WorkerRunner | `{task: str}` + `agent_id` |
| `WORKER_TEXT` | WorkerRunner | `{text: str}` + `agent_id` |
| `WORKER_DONE` | WorkerRunner | `{result: str}` + `agent_id` |

### StateManager (`src/master/state.py`)

Manages all federation state:
- Worker configurations (templates)
- Active workers and their status
- Task assignments and results
- Completion queue

**State Structure:**
```python
FederationState:
    workspace_path: str
    master: MasterState
    workers: dict[str, Worker]
    worker_configs: dict[str, WorkerConfig]
    completed_queue: list[str]
```

### MasterAgent (`src/master/loop.py`)

The orchestrator with a streaming agentic loop:

```python
def run(self, user_message: str) -> str:
    self.conversation.append({"role": "user", "content": user_message})

    while True:
        response_text, tool_calls = self._call_llm_streaming()

        if tool_calls:
            # Execute tools and continue loop
            for tc in tool_calls:
                result = self.tool_executor.execute(tc["name"], tc["input"])
            # Add results to conversation and loop again
        else:
            # No tool calls = final response
            return response_text
```

**Available Tools:**
| Tool | Purpose |
|------|---------|
| `list_worker_types` | View available worker templates |
| `list_workers` | View all workers and their status |
| `spawn_worker` | Create a new worker instance |
| `delegate` | Assign task to worker (non-blocking) |
| `get_completed` | Check for finished work |
| `terminate_worker` | Shut down a worker |

### WorkerRunner (`src/workers/runner.py`)

Executes workers in background threads:

```python
def start_worker(self, worker_id: str, task: str) -> None:
    # Get worker config
    worker = self.federation.state.get_worker(worker_id)

    # Start in background thread (non-blocking)
    thread = threading.Thread(
        target=self._run_worker_sync,
        args=(worker_id, task, ...),
        daemon=True,
    )
    thread.start()  # Returns immediately
```

Workers use the Claude Agent SDK (when available) or fall back to test mode.

### FederationApp (`src/ui/app.py`)

Textual-based terminal UI with:
- **ChatLog**: Conversation with master agent
- **MasterPanel**: Current master status (idle/thinking/calling tool)
- **WorkersPanel**: List of all workers, clickable to select
- **WorkerOutputPanel**: Streaming output from selected worker

The UI subscribes to `federation.event_bus` and updates reactively.

## Data Flow

### User Message → Response

```
1. User types in Input widget
2. on_input_submitted() called
3. run_master() spawns background thread
4. federation.run(message) → master.run(message)
5. Master calls LLM with streaming
6. Text chunks → event_bus.master_text() → UI updates
7. Tool calls executed via ToolExecutor
8. Loop until no more tool calls
9. Final response returned
```

### Delegation Flow

```
1. Master decides to delegate
2. spawn_worker tool creates Worker in state
3. delegate tool:
   a. Assigns task to worker
   b. Calls worker_runner.start_worker() (non-blocking)
   c. Returns immediately with "Delegated..."
4. Worker thread:
   a. Emits WORKER_STARTED
   b. Runs task (SDK or test mode)
   c. Emits WORKER_TEXT for each chunk
   d. Emits WORKER_DONE when complete
5. Master can call get_completed to retrieve results
```

## Threading Model

```
Main Thread (Textual event loop)
│
├── UI rendering and event handling
│
└── Background workers via @work decorator
    │
    └── run_master() thread
        │
        └── MasterAgent.run() - blocking until complete
            │
            └── May spawn worker threads via delegate tool
                │
                └── Worker threads (daemon)
                    │
                    └── _run_worker_async() in new event loop
```

**Cross-thread communication:**
- Background threads emit events via EventBus
- UI receives events and uses `call_from_thread()` to safely update

## File Structure

```
agent-federation/
├── run.py                    # Entry point
├── src/
│   ├── federation.py         # Central coordinator
│   ├── shared/
│   │   ├── types.py          # Data classes (Worker, WorkerConfig, etc.)
│   │   └── events.py         # EventBus and Event types
│   ├── master/
│   │   ├── loop.py           # MasterAgent with agentic loop
│   │   ├── tools.py          # Tool definitions and ToolExecutor
│   │   └── state.py          # StateManager
│   ├── workers/
│   │   └── runner.py         # WorkerRunner
│   └── ui/
│       └── app.py            # Textual UI
└── _specs/
    ├── agent-federation spec.md  # Original specification
    ├── architecture.md           # This document
    └── flow-walkthrough.md       # Detailed code walkthrough
```

## Configuration

### Worker Types (Templates)

Defined in `StateManager._load_default_configs()`:

| Type | Description | Tools |
|------|-------------|-------|
| `general` | General-purpose worker | Read, Write, Edit, Bash, Glob, Grep |
| `coder` | Coding specialist | Read, Write, Edit, Bash, Glob, Grep |
| `researcher` | Research agent | Read, Glob, Grep, WebFetch, WebSearch |

### Environment Variables

- `ANTHROPIC_API_KEY`: Required for Anthropic API access

## Dependencies

- `anthropic`: Anthropic API client
- `textual`: Terminal UI framework
- `python-dotenv`: Environment variable loading
- `claude-agent-sdk`: (Optional) Claude Agent SDK for workers
