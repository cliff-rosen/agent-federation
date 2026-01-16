# Agent Federation Flow Walkthrough

This document traces the complete flow when a user types:
> "Let's use the research agent to check the weather in Boulder, Colorado"

## Phase 1: User Input → Master Agent

### Step 1.1: Input Widget Captures Text
**File:** `src/ui/app.py:396-405`

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
**File:** `src/ui/app.py:407-417`

```python
@work(thread=True, exclusive=True)
def run_master(self, message: str) -> None:
    try:
        self.master.run(message)
    except Exception as e:
        self.call_from_thread(self.chat.add_error, str(e))
    finally:
        self.call_from_thread(setattr, self.master_panel, "status", MasterStatus.IDLE)
```

The `@work(thread=True)` decorator runs this in a background thread so the UI stays responsive. It calls `self.master.run(message)` where `self.master` is the `MasterAgent` instance.

---

## Phase 2: Master Agent Agentic Loop

### Step 2.1: Add Message to Conversation
**File:** `src/master/loop.py:60-66`

```python
def run(self, user_message: str) -> str:
    self.state_manager.set_master_status(MasterStatus.THINKING)
    self.conversation.append({"role": "user", "content": user_message})

    final_response = ""

    while True:
        response_text, tool_calls = self._call_llm_streaming()
```

The master agent maintains a `conversation` list (standard Anthropic messages format). It appends the user message and enters the agentic loop.

### Step 2.2: Call LLM with Streaming
**File:** `src/master/loop.py:108-154`

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
                self.event_bus.master_text(text_chunk)  # ← Streams to UI
            # Handle tool use blocks
            elif hasattr(event.delta, "partial_json"):
                # Accumulate tool input JSON
```

Key points:
- Uses Anthropic's streaming API (`client.messages.stream`)
- The `MASTER_SYSTEM_PROMPT` tells the LLM it can spawn workers and delegate tasks
- The `MASTER_TOOLS` define what tools are available (spawn_worker, delegate, etc.)
- Text chunks are emitted via `event_bus.master_text()` for real-time display

### Step 2.3: LLM Decides to Use Tools
The LLM sees the user wants to use a "research agent" and decides to:
1. Call `spawn_worker` with `agent_type="researcher"`
2. Call `delegate` to assign the weather task

The streaming response might look like:
> "I'll spawn a researcher agent and have it check the weather in Boulder."
> [tool_use: spawn_worker {agent_type: "researcher"}]
> [tool_use: delegate {agent_id: "abc123", task: "Check the weather in Boulder, Colorado"}]

### Step 2.4: Execute Tools
**File:** `src/master/loop.py:85-96`

```python
# Execute tools
tool_results = []
for tc in tool_calls:
    self.state_manager.set_master_status(MasterStatus.CALLING_TOOL, tc["name"])
    result = self.tool_executor.execute(tc["name"], tc["input"])
    tool_results.append({
        "type": "tool_result",
        "tool_use_id": tc["id"],
        "content": result,
    })
```

For each tool call, the `ToolExecutor` runs the corresponding function.

---

## Phase 3: Spawning the Worker

### Step 3.1: spawn_worker Tool
**File:** `src/master/tools.py` (spawn_worker handler)

```python
def _spawn_worker(self, agent_type: str) -> str:
    config = self.state.get_agent_config(agent_type)
    if not config:
        return f"Unknown agent type: {agent_type}"

    worker_id = self.state.spawn_worker(agent_type, config)
    self.events.worker_spawned(worker_id, agent_type)  # ← Event emitted
    return f"Spawned {agent_type} worker: {worker_id}"
```

This:
1. Gets the worker config (system prompt, allowed tools) from `StateManager`
2. Creates a `Worker` object in state
3. Emits `WORKER_SPAWNED` event

### Step 3.2: Worker Created in State
**File:** `src/master/state.py`

```python
def spawn_worker(self, agent_type: str, config: WorkerConfig) -> str:
    worker_id = str(uuid.uuid4())
    worker = Worker(
        id=worker_id,
        type=agent_type,
        config=config,
        status=WorkerStatus.IDLE,
    )
    self.state.workers[worker_id] = worker
    return worker_id
```

The worker now exists in state with status `IDLE`.

---

## Phase 4: Delegating the Task

### Step 4.1: delegate Tool
**File:** `src/master/tools.py` (delegate handler)

```python
def _delegate(self, agent_id: str, task: str, intention: str = "return_to_user") -> str:
    worker = self.state.get_worker(agent_id)
    if not worker:
        return f"Worker not found: {agent_id}"

    # Assign task to worker
    self.state.assign_task(agent_id, task, Intention(intention))

    # Start the worker in background (non-blocking!)
    if self.worker_runner:
        self.worker_runner.start_worker(agent_id, task)

    return f"Delegated to {agent_id}: {task}"
```

Critical: `start_worker` is **non-blocking**. The master doesn't wait for the worker to complete.

### Step 4.2: Start Worker in Background Thread
**File:** `src/workers/runner.py:32-45`

```python
def start_worker(self, worker_id: str, task: str) -> None:
    worker = self.state.get_worker(worker_id)
    if not worker:
        return

    # Run in background thread
    thread = threading.Thread(
        target=self._run_worker_sync,
        args=(worker_id, task, worker.config.system_prompt, worker.config.allowed_tools),
        daemon=True,
    )
    self._threads[worker_id] = thread
    thread.start()  # ← Returns immediately
```

A daemon thread is spawned. The `delegate` tool returns immediately with "Delegated to abc123: Check the weather..."

---

## Phase 5: Worker Execution

### Step 5.1: Worker Thread Runs
**File:** `src/workers/runner.py:47-55`

```python
def _run_worker_sync(self, worker_id, task, system_prompt, allowed_tools):
    asyncio.run(self._run_worker_async(worker_id, task, system_prompt, allowed_tools))
```

The thread creates a new asyncio event loop and runs the async worker code.

### Step 5.2: Worker Emits Events
**File:** `src/workers/runner.py:57-77`

```python
async def _run_worker_async(self, worker_id, task, system_prompt, allowed_tools):
    # Emit started event so UI can refresh
    self.events.worker_started(worker_id, task)  # ← WORKER_STARTED
    self.events.worker_text(worker_id, f"Starting task: {task}\n")  # ← WORKER_TEXT

    try:
        if not HAS_SDK:
            # Fallback: simple simulation for testing
            self.events.worker_text(worker_id, "[SDK not installed - running in test mode]\n")
            await asyncio.sleep(2)
            result_text = f"[Test mode] Would have completed task: {task}"
            self.state.complete_task(worker_id, result_text)
            self.events.worker_done(worker_id, result_text)  # ← WORKER_DONE
            return
```

Events emitted:
1. `WORKER_STARTED` - Worker begins execution
2. `WORKER_TEXT` - Streaming text output
3. `WORKER_DONE` - Worker completes

### Step 5.3: With Claude Agent SDK (when installed)
```python
async with ClaudeSDKClient(options=options) as client:
    self.events.worker_text(worker_id, "Connected. Sending query...\n")
    await client.query(task)

    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    result_text += block.text
                    self.events.worker_text(worker_id, block.text)  # ← Stream each chunk
```

Each text chunk from the SDK is emitted as a `WORKER_TEXT` event.

---

## Phase 6: Events Flow to UI

### Step 6.1: EventBus Broadcasts
**File:** `src/shared/events.py:60-62`

```python
def emit(self, event: Event) -> None:
    for handler in self._handlers:
        handler(event)
```

When `events.worker_text(worker_id, text)` is called:
1. Creates an `Event` with `type=WORKER_TEXT`, `agent_id=worker_id`, `data={text: ...}`
2. Calls all subscribed handlers

### Step 6.2: UI Receives Event
**File:** `src/ui/app.py:307-308`

```python
def on_mount(self) -> None:
    # Subscribe to events
    self.master.event_bus.subscribe(self.handle_event)
```

The UI subscribed to the EventBus during mount.

### Step 6.3: Cross-Thread Event Handling
**File:** `src/ui/app.py:325-327`

```python
def handle_event(self, event: Event) -> None:
    """Handle events from the federation."""
    self.call_from_thread(self._process_event, event)
```

**Critical:** Events come from background threads (worker thread or master thread). Textual requires UI updates on the main thread. `call_from_thread` safely schedules the event processing on Textual's event loop.

### Step 6.4: Process Event on Main Thread
**File:** `src/ui/app.py:356-371`

```python
def _process_event(self, event: Event) -> None:
    # ...
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
```

For `WORKER_STARTED`:
1. Refreshes the workers list
2. Auto-selects the new worker
3. Sets up the worker output panel

For `WORKER_TEXT`:
1. Checks if this worker is currently selected
2. If yes, adds the text to the output panel

---

## Phase 7: UI Updates

### Step 7.1: Worker Output Panel Displays Text
**File:** `src/ui/app.py:123-128`

```python
def add_text(self, text: str) -> None:
    """Add streaming text."""
    try:
        self.log.write(Text(text, style="white"))
    except Exception:
        pass
```

The `RichLog` widget displays the text with styling.

### Step 7.2: Workers Panel Updates
**File:** `src/ui/app.py:76-89`

```python
def watch_worker_data(self, worker_data: dict) -> None:
    """Update the list when workers change."""
    list_view = self.query_one("#workers-list", ListView)
    list_view.clear()

    for worker_id, worker in worker_data.items():
        item = WorkerItem(worker_id, worker)
        if worker_id == self.selected_id:
            item.highlighted = True
        list_view.append(item)
```

Textual's reactive system automatically calls `watch_worker_data` when `worker_data` changes.

---

## Summary: The Complete Chain

```
User types message
       ↓
Input.Submitted event
       ↓
on_input_submitted() → run_master() in background thread
       ↓
MasterAgent.run() → _call_llm_streaming()
       ↓
Anthropic API returns tool calls: spawn_worker, delegate
       ↓
ToolExecutor.execute("spawn_worker") → StateManager creates Worker
       ↓                                      ↓
       ↓                              EventBus.emit(WORKER_SPAWNED)
       ↓                                      ↓
ToolExecutor.execute("delegate")        UI refreshes worker list
       ↓
WorkerRunner.start_worker() → spawns daemon thread
       ↓
(master continues, delegate returns immediately)
       ↓
Worker thread: _run_worker_async()
       ↓
EventBus.emit(WORKER_STARTED) → UI auto-selects worker
       ↓
EventBus.emit(WORKER_TEXT) → UI shows text in output panel
       ↓ (repeats for each chunk)
EventBus.emit(WORKER_DONE) → UI shows completion
```

## Key Design Decisions

1. **Non-blocking delegation**: Master doesn't wait for workers. Users must call `get_completed` to check results.

2. **Event-driven UI**: All updates flow through EventBus. Background threads never touch UI directly.

3. **Thread safety via call_from_thread**: Textual's mechanism for safely updating UI from background threads.

4. **Streaming throughout**: Both master and workers stream text chunks for real-time feedback.

5. **Auto-selection**: When a worker starts, it's automatically selected so the user sees its output immediately.
