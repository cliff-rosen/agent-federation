  Flow for your test case:
  1. User asks master something requiring delegation
  2. Master calls spawn_agent(template_name="general") → gets agent ID
  3. Master calls delegate(agent_id, task, intention="return_to_user")
  4. delegate tool synchronously runs the worker loop (with streaming events)
  5. Worker completes → result returned to master
  6. Master receives result in tool response → formulates final response

  To test:
  pip install -r requirements.txt
  python main.py "Spawn a general worker and ask it to explain what 2+2 equals"

  Or interactive mode:
  python main.py -i

  The streaming events will show status throughout - master thinking, tool calls, worker spawned, worker
  thinking, etc.