**Agent Federation System - Specification Sheet**

---

## Overview

A multi-agent orchestration system where a Master Agent coordinates work across specialized worker agents, with all activity grounded in a shared workspace filesystem. Users interact through a unified interface that provides both conversation with the Master Agent and visibility into the full federation's activity.

---

## Core Components

### Master Agent

The central orchestrator that:
- Receives and interprets user requests
- Decides whether to handle directly or delegate
- Manages worker agent lifecycle (spawn, delegate, clear, terminate)
- Tracks delegations with intentions (what happens when work completes)
- Monitors agent completions and executes next steps
- Maintains awareness of shared workspace state

### Worker Agents

Specialized Claude Code instances, each with:
- System prompt / instructions (from template or custom)
- Tool subset (assembled from master registry)
- Conversation state (accumulated context)
- Status (idle / busy / has_result)
- Read/write access to shared workspace

### Agent Types (Templates)

Predefined configurations specifying:
- Name and description (so master knows when to use)
- System prompt
- Tool list

Master can instantiate from templates or assemble custom agents ad-hoc.

### Tool Registry

Master list of all available tools. Agents receive subsets appropriate to their role. Master has full visibility and assembles tool lists when spawning agents.

### Shared Workspace

Common filesystem accessible by master, all agents, and user:
- Persists outputs and artifacts
- Enables handoff between agents via files
- Accumulates work-in-progress over time
- Serves as long-term project memory
- User can drop in files or read outputs directly

### Delegation Model

Each delegation specifies:
- Target agent
- Task prompt (may reference workspace files)
- Output location (where to write results)
- Intention / next step:
  - `return_to_user` - deliver result to user
  - `pass_to_agent` - forward to another agent (with transform instructions)
  - `review_by_master` - master evaluates and decides next action

Delegations can be chained to form workflows.

---

## Master Agent Interface

### System Prompt Summary

- Identity as federation orchestrator
- Decision framework: handle directly vs. delegate
- Delegation requires specifying intention
- Awareness of agent states, workspace, and pending tasks
- Can operate synchronously or background
- Keeps user informed on progress

### Master Agent Tools

| Tool | Purpose |
|------|---------|
| *Baseline tools* | Direct capabilities (search, file ops, etc.) |
| `list_agent_types` | View available templates |
| `list_running_agents` | View all instances and their status |
| `list_tool_registry` | View all tools available for assignment |
| `get_agent_detail` | Deep view of specific agent |
| `spawn_agent` | Create instance from template or custom config |
| `delegate` | Assign task with intention |
| `clear_agent_context` | Reset agent conversation state |
| `terminate_agent` | Shut down agent instance |
| `get_delegation_status` | View active delegations and intentions |
| `get_pending_results` | View completed work awaiting processing |
| `message_user` | Send interim update (for background work) |
| `list_workspace` | View workspace contents |
| `read_file` | Read from workspace |
| `write_file` | Write to workspace |

---

## User Experience

### Primary Interface: Chat Panel

- Direct conversation with Master Agent
- Send requests, ask questions, provide guidance
- Receive responses, updates, and deliverables
- Master may respond immediately or acknowledge and work in background

### Secondary Interface: Federation Dashboard

Real-time visualization of system state:

**Agent Status View**
- All running agents displayed
- For each: id, type, status (idle/busy/has_result)
- Current task description (if busy)
- Context indicator (depth/summary of conversation state)

**Delegation / Workflow View**
- Active delegations listed
- Shows: task → agent → intention (what happens next)
- Chains visualized (A → B → C → user)
- Blocked tasks shown with dependencies

**Workspace View**
- File browser for shared workspace
- See recent changes / outputs
- Preview or open files
- Drag-and-drop to add files

**Activity Log**
- Chronological feed of events
- User messages, delegations, completions, handoffs
- Filterable by agent or task

### User Actions

| Action | Method |
|--------|--------|
| Send message to master | Chat input |
| View agent activity | Dashboard |
| Browse workspace | File panel |
| Add files to workspace | Drag-drop or upload |
| Read agent outputs | Click file in workspace |
| Interrupt / redirect | Message master |

---

## Operational Flows

### Simple Request
1. User sends request
2. Master handles directly or delegates
3. Result returned to user

### Delegated Task
1. User sends request
2. Master delegates to agent with intention
3. Agent works, writes to workspace
4. Master notified of completion
5. Master executes intention (return to user, chain, or review)

### Parallel Workflow
1. User sends complex request
2. Master decomposes, delegates to multiple agents
3. Agents work concurrently, write to workspace
4. As each completes, master executes intentions
5. Final agent synthesizes, returns to user

### Long-Running / Background
1. User sends large task
2. Master acknowledges, begins background work
3. Master sends interim updates via `message_user`
4. User can check dashboard or continue conversation
5. Master delivers final result when complete

### Multi-Session Project
1. Work accumulates in workspace over time
2. User returns, references prior work
3. Master surveys workspace, resumes context
4. New agents can be pointed at existing artifacts

---

## Technical Notes

- Each worker agent is a Claude Code SDK session listening on a port
- Master polls agents for completion (or event-driven via callbacks)
- Workspace is a mounted filesystem volume shared across all containers/processes
- Agent types stored as configuration (JSON/YAML)
- Tool registry is master config, tools implemented as Claude Code compatible definitions

---

## Summary

The system enables a user to interact conversationally with a Master Agent that can orchestrate complex work across multiple specialized agents, all coordinated through explicit intentions and grounded in a persistent shared workspace. The UX provides both direct chat and a dashboard view into the federation's activity.