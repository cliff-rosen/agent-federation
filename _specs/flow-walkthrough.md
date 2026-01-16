# Agent Federation Flow Walkthrough

This document traces the complete flow when a user types:
> "Let's use the research agent to check the weather in Boulder, Colorado"

## Architecture Overview

All components are owned by a single `Federation` coordinator:

```
Federation
├── event_bus: EventBus         # Communication channel for streaming events
├── state: StateManager         # Workers, configs, and task state
├── workspace_path: str         # Shared filesystem location
├── master: MasterAgent         # Orchestrator (lazy-created)
└── worker_runner: WorkerRunner # Executes workers (lazy-created)
```

Components access shared resources via `self.federation` rather than holding direct references to each other.

---

## Phase 1: User Input → Master Agent

### Step 1.1: Input Widget Captures Text
**File:** `src/ui/app.py:401-410`

```python
async def on_input_submitted(self, event: Input.Submitted) -> None:
    message = event.value.strip()
    if not message:
        return

    event.input.value = ""
    self.chat.add_user_message(message)
    self.master_panel.status = MasterStatus.THINKING
    self.run_master(message)
```

The Textual `Input` widget fires `Input.Submitted` when the user presses Enter. The handler:
1. Clears the input field
2. Shows the message in the chat log
3. Updates the master panel to show "thinking..."
4. Calls `run_master(message)`

### Step 1.2: Background Thread for Master
**File:** `src/ui/app.py:412-422`

```python
@work(thread=True, exclusive=True)
def run_master(self, message: str) -> None:
    try:
        self.federation.run(message)
    except Exception as e:
        self.call_from_thread(self.chat.add_error, str(e))
    finally:
        self.call_from_thread(setattr, self.master_panel, "status", MasterStatus.IDLE)
```

The `@work(thread=True)` decorator runs this in a background thread so the UI stays responsive. It calls `self.federation.run(message)` which delegates to the master agent.

### Step 1.3: Federation Delegates to Master
**File:** `src/federation.py:53-54`

```python
def run(self, message: str) -> str:
    """Send a message to the master agent and get the response."""
    return self.master.run(message)
```

The Federation's `run()` method is a convenience that forwards to the master agent.

---

## Phase 2: Master Agent Agentic Loop

### Step 2.1: Add Message to Conversation
**File:** `src/master/loop.py:58-66`

```python
def run(self, user_message: str) -> str:
    """Run the agentic loop for a user message. Returns final response."""
    self.federation.state.set_master_status(MasterStatus.THINKING)
    self.conversation.append({"role": "user", "content": user_message})

    final_response = ""

    while True:
        response_text, tool_calls = self._call_llm_streaming()
```

The master agent:
1. Updates status via `self.federation.state`
2. Appends the user message to conversation history
3. Enters the agentic loop

### Step 2.2: Call LLM with Streaming
**File:** `src/master/loop.py:106-152`

```python
def _call_llm_streaming(self) -> tuple[str, list[dict]]:
    with self.client.messages.stream(
        model=self.model,
        max_tokens=4096,
        system=MASTER_SYSTEM_PROMPT,
        messages=self.conversation,
        tools=MASTER_TOOLS,
    ) as stream:
        for event in stream:
            # Handle text deltas - emit to UI
            if hasattr(event.delta, "text"):
                text_chunk = event.delta.text
                collected_text += text_chunk
                self.federation.event_bus.master_text(text_chunk)  # ← Streams to UI
            # Handle tool use blocks...
```

Key points:
- Uses Anthropic's streaming API
- Text chunks are emitted via `self.federation.event_bus` for real-time display
- All shared resources accessed through `self.federation`

### Step 2.3: LLM Decides to Use Tools

The LLM sees the user wants to use a "research agent" and decides to call tools:
1. `spawn_worker` with `worker_type="researcher"`
2. `delegate` to assign the weather task

### Step 2.4: Execute Tools
**File:** `src/master/loop.py:83-94`

```python
# Execute tools
tool_results = []
for tc in tool_calls:
    self.federation.state.set_master_status(MasterStatus.CALLING_TOOL, tc["name"])
    result = self.tool_executor.execute(tc["name"], tc["input"])
    tool_results.append({
        "type": "tool_result",
        "tool_use_id": tc["id"],
        "content": result,
    })
```

The `ToolExecutor` runs each tool, accessing the federation for state and events.

---

## Phase 3: Spawning the Worker

### Step 3.1: spawn_worker Tool
**File:** `src/master/tools.py:139-145`

```python
def _tool_spawn_worker(self, worker_type: str) -> str:
    try:
        worker = self.federation.state.spawn_worker(worker_type)
        self.federation.event_bus.worker_spawned(worker.id, worker.type)
        return f"Spawned {worker_type} worker with ID: {worker.id}"
    except ValueError as e:
        return f"Failed to spawn worker: {e}"
```

This:
1. Creates a `Worker` in state via `self.federation.state`
2. Emits `WORKER_SPAWNED` event via `self.federation.event_bus`

### Step 3.2: Worker Created in State
**File:** `src/master/state.py:73-87`

```python
def spawn_worker(self, worker_type: str) -> Worker:
    config = self.state.worker_configs[worker_type]
    worker_id = str(uuid.uuid4())[:8]

    worker = Worker(
        id=worker_id,
        type=worker_type,
        config=config,
    )
    self.state.workers[worker_id] = worker
    return worker
```

The worker now exists in state with status `IDLE`.

---

## Phase 4: Delegating the Task

### Step 4.1: delegate Tool
**File:** `src/master/tools.py:147-171`

```python
def _tool_delegate(self, worker_id: str, task: str, intention: str) -> str:
    worker = self.federation.state.get_worker(worker_id)
    if not worker:
        return f"Worker not found: {worker_id}"

    # Parse intention and assign task
    intention_enum = Intention(intention)
    self.federation.state.assign_task(worker_id, task, intention_enum)

    # Start the worker in the background (non-blocking!)
    self.federation.worker_runner.start_worker(worker_id, task)
    return f"Delegated task to worker {worker_id}. Use get_completed to check when done."
```

Critical: `start_worker` is **non-blocking**. The master doesn't wait for the worker to complete.

### Step 4.2: Start Worker in Background Thread
**File:** `src/workers/runner.py:28-41`

```python
def start_worker(self, worker_id: str, task: str) -> None:
    """Start a worker in a background thread."""
    worker = self.federation.state.get_worker(worker_id)
    if not worker:
        return

    thread = threading.Thread(
        target=self._run_worker_sync,
        args=(worker_id, task, worker.config.system_prompt, worker.config.allowed_tools),
        daemon=True,
    )
    self._threads[worker_id] = thread
    thread.start()  # ← Returns immediately
```

A daemon thread is spawned. The `delegate` tool returns immediately.

---

## Phase 5: Worker Execution

### Step 5.1: Worker Thread Runs
**File:** `src/workers/runner.py:43-51`

```python
def _run_worker_sync(self, worker_id, task, system_prompt, allowed_tools):
    asyncio.run(self._run_worker_async(worker_id, task, system_prompt, allowed_tools))
```

The thread creates a new asyncio event loop and runs the async worker code.

### Step 5.2: Worker Emits Events
**File:** `src/workers/runner.py:53-76`

```python
async def _run_worker_async(self, worker_id, task, system_prompt, allowed_tools):
    events = self.federation.event_bus
    state = self.federation.state

    # Emit started event so UI can refresh
    events.worker_started(worker_id, task)
    events.worker_text(worker_id, f"Starting task: {task}\n")

    try:
        if not HAS_SDK:
            # Fallback: simple simulation for testing
            events.worker_text(worker_id, "[SDK not installed - running in test mode]\n")
            await asyncio.sleep(2)
            result_text = f"[Test mode] Would have completed task: {task}"
            state.complete_task(worker_id, result_text)
            events.worker_done(worker_id, result_text)
            return
```

The worker accesses shared resources via `self.federation`:
- `self.federation.event_bus` for emitting events
- `self.federation.state` for updating task status
- `self.federation.workspace_path` for file operations

Events emitted:
1. `WORKER_STARTED` - Worker begins execution
2. `WORKER_TEXT` - Streaming text output
3. `WORKER_DONE` - Worker completes

---

## Phase 6: Events Flow to UI

### Step 6.1: EventBus Broadcasts
**File:** `src/shared/events.py:60-62`

```python
def emit(self, event: Event) -> None:
    for handler in self._handlers:
        handler(event)
```

All subscribed handlers receive the event.

### Step 6.2: UI Receives Event
**File:** `src/ui/app.py:312-313`

```python
def on_mount(self) -> None:
    # Subscribe to events
    self.federation.event_bus.subscribe(self.handle_event)
```

The UI subscribed to `self.federation.event_bus` during mount.

### Step 6.3: Cross-Thread Event Handling
**File:** `src/ui/app.py:330-332`

```python
def handle_event(self, event: Event) -> None:
    """Handle events from the federation."""
    self.call_from_thread(self._process_event, event)
```

Events come from background threads. `call_from_thread` safely schedules processing on Textual's main thread.

### Step 6.4: Process Event on Main Thread
**File:** `src/ui/app.py:361-376`

```python
elif event.type == EventType.WORKER_STARTED:
    self._refresh_workers()
    agent_id = event.agent_id or ""
    self.chat.add_status(f"Worker {agent_id} started")
    # Auto-select the started worker
    self.selected_worker_id = agent_id
    self.workers_panel.selected_id = agent_id
    worker = self.federation.state.get_worker(agent_id)
    self.worker_output.set_worker(agent_id, worker)

elif event.type == EventType.WORKER_TEXT:
    agent_id = event.agent_id or ""
    text = event.data.get("text", "")
    if agent_id == self.selected_worker_id:
        self.worker_output.add_text(text)
```

The UI accesses worker data via `self.federation.state`.

---

## Summary: The Complete Chain

```
User types message
       ↓
Input.Submitted event
       ↓
on_input_submitted() → run_master() in background thread
       ↓
federation.run() → master.run()
       ↓
MasterAgent._call_llm_streaming()
       ↓
Anthropic API returns tool calls: spawn_worker, delegate
       ↓
ToolExecutor accesses federation.state to create Worker
       ↓
federation.event_bus.emit(WORKER_SPAWNED) → UI refreshes
       ↓
ToolExecutor calls federation.worker_runner.start_worker()
       ↓
(master continues, delegate returns immediately)
       ↓
Worker thread accesses federation.event_bus
       ↓
WORKER_STARTED → UI auto-selects worker
       ↓
WORKER_TEXT → UI shows text in output panel (repeated)
       ↓
WORKER_DONE → UI shows completion
```

## Key Design Decisions

1. **Federation coordinator**: Single owner of all shared resources eliminates complex wiring.

2. **Lazy component creation**: `master` and `worker_runner` are created on first access, avoiding circular dependencies.

3. **Non-blocking delegation**: Master doesn't wait for workers. Users call `get_completed` to check results.

4. **Event-driven UI**: All updates flow through `federation.event_bus`. Background threads never touch UI directly.

5. **Thread safety via call_from_thread**: Textual's mechanism for safely updating UI from background threads.

6. **Streaming throughout**: Both master and workers stream text chunks for real-time feedback.

7. **Auto-selection**: When a worker starts, it's automatically selected so the user sees its output immediately.
