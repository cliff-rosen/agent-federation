Entities

  1. Master Agent
  - The orchestrator - there's only one
  - Talks directly to the user
  - Decides: "Can I handle this myself, or should I delegate?"
  - Has special tools for managing workers (spawn, delegate, terminate)
  - Runs its own agentic loop (call LLM → execute tools → repeat)

  2. Worker Agents
  - Spawned by the master on demand
  - Each has: an ID, a type (from template), a system prompt, allowed tools
  - Do actual work (read files, write files, etc.)
  - Run their own agentic loop when delegated to
  - Report results back to master

  3. State Manager
  - Tracks all workers (who exists, their status: idle/busy/done)
  - Tracks delegations (what task, which worker, what to do when done)
  - Holds agent templates (predefined configs like "researcher", "coder")

  4. Event Bus
  - Broadcasts events as things happen (master speaking, worker spawned, tool called)
  - UI subscribes to these events to show real-time updates

  5. UI (FederationApp)
  - Displays chat and agent status
  - Takes user input, sends to master
  - Listens to event bus, updates display

  ---
  Rules of Engagement

  ┌─────────────────────────────────────────────────────────┐
  │  USER                                                   │
  │    │                                                    │
  │    ▼                                                    │
  │  ┌─────────────┐                                        │
  │  │   UI        │ ◄─────── Event Bus (status updates)   │
  │  └─────────────┘                                        │
  │    │                                                    │
  │    ▼ sends message                                      │
  │  ┌─────────────────────────────────────┐                │
  │  │         MASTER AGENT                │                │
  │  │  - receives user request            │                │
  │  │  - calls LLM with MASTER_TOOLS      │                │
  │  │  - executes orchestration tools     │                │
  │  └─────────────────────────────────────┘                │
  │    │                                                    │
  │    │ spawn_agent / delegate                             │
  │    ▼                                                    │
  │  ┌─────────────────────────────────────┐                │
  │  │         WORKER AGENT(s)             │                │
  │  │  - receives task from master        │                │
  │  │  - calls LLM with WORKER_TOOLS      │                │
  │  │  - executes file/search tools       │                │
  │  │  - returns result to master         │                │
  │  └─────────────────────────────────────┘                │
  │    │                                                    │
  │    ▼ reads/writes                                       │
  │  ┌─────────────┐                                        │
  │  │  WORKSPACE  │  (shared filesystem)                   │
  │  └─────────────┘                                        │
  └─────────────────────────────────────────────────────────┘

  ---
  The Two Tool Sets

  Master's tools (orchestration):
  ┌─────────────────────┬─────────────────────────────────────────────┐
  │        Tool         │                    Does                     │
  ├─────────────────────┼─────────────────────────────────────────────┤
  │ spawn_agent         │ Create a new worker                         │
  ├─────────────────────┼─────────────────────────────────────────────┤
  │ delegate            │ Give a task to a worker, run it, get result │
  ├─────────────────────┼─────────────────────────────────────────────┤
  │ terminate_agent     │ Kill a worker                               │
  ├─────────────────────┼─────────────────────────────────────────────┤
  │ list_agent_types    │ See available templates                     │
  ├─────────────────────┼─────────────────────────────────────────────┤
  │ list_running_agents │ See active workers                          │
  └─────────────────────┴─────────────────────────────────────────────┘
  Worker's tools (actual work):
  ┌──────────────┬───────────────────────┐
  │     Tool     │         Does          │
  ├──────────────┼───────────────────────┤
  │ read_file    │ Read from workspace   │
  ├──────────────┼───────────────────────┤
  │ write_file   │ Write to workspace    │
  ├──────────────┼───────────────────────┤
  │ search_files │ Find files by pattern │
  └──────────────┴───────────────────────┘
  ---
  Typical Flow

  1. User: "Write a haiku about coding to poem.txt"
  2. Master LLM decides: "I should delegate this"
  3. Master calls spawn_agent("general") → gets worker abc123
  4. Master calls delegate(agent_id="abc123", task="Write a haiku...", intention="return_to_user")
  5. Inside delegate:
    - Worker abc123 runs its own loop
    - Worker LLM decides to call write_file
    - Worker writes to workspace
    - Worker returns "Done, wrote haiku to poem.txt"
  6. Delegate tool returns result to master
  7. Master responds to user: "I've written a haiku to poem.txt"