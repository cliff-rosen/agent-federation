  Before (awkward wiring)

  # run.py - 5 objects manually wired together
  event_bus = EventBus()
  state_manager = StateManager(workspace_path=workspace_path)
  master = MasterAgent(workspace_path, state_manager, event_bus)
  worker_runner = WorkerRunner(state_manager, event_bus, workspace_path)
  master.set_worker_runner(worker_runner)  # Post-construction setter
  app = FederationApp(master, worker_runner, state_manager)  # worker_runner unused!

  After (clean coordinator pattern)

  # run.py - 2 lines
  federation = Federation(workspace_path=workspace_path)
  app = FederationApp(federation)

  New Architecture

  Federation (coordinator)
  ├── event_bus: EventBus        # Communication channel
  ├── state: StateManager        # Shared state
  ├── workspace_path: str        # Shared filesystem location
  ├── master: MasterAgent        # Lazy-created, references federation
  └── worker_runner: WorkerRunner # Lazy-created, references federation

  Key improvements:
  ┌────────────────────────────────────────────┬─────────────────────────────────────────┐
  │                   Before                   │                  After                  │
  ├────────────────────────────────────────────┼─────────────────────────────────────────┤
  │ 5 separate objects passed around           │ 1 coordinator owns everything           │
  ├────────────────────────────────────────────┼─────────────────────────────────────────┤
  │ set_worker_runner() post-construction hack │ Lazy properties, no circular dependency │
  ├────────────────────────────────────────────┼─────────────────────────────────────────┤
  │ worker_runner passed to UI but unused      │ UI only takes what it needs             │
  ├────────────────────────────────────────────┼─────────────────────────────────────────┤
  │ workspace_path passed to 3 places          │ Single source of truth                  │
  ├────────────────────────────────────────────┼─────────────────────────────────────────┤
  │ Components reference each other directly   │ Components reference Federation         │
  └────────────────────────────────────────────┴─────────────────────────────────────────┘
  Each component now accesses shared resources via self.federation:
  - self.federation.event_bus
  - self.federation.state
  - self.federation.workspace_path
  - self.federation.worker_runner
