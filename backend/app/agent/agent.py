"""Main agent: the acoustic investigator.

Answers questions like "find the best room for client calls in this building" or
"what's the cheapest fix for the break room?".

TODO (check the deepagents README for current parameter names):
- create_deep_agent(tools=..., subagents=SUBAGENTS, system_prompt=prompts.MAIN, ...)
- working files under data/<sid>/agent/ (so the UI can read them)
- interrupt_on for the human-approval tool, with a checkpointer
- planning (write_todos) streamed to the frontend through api/agent.py
"""
