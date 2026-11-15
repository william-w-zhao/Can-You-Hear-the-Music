"""Main agent: the acoustic investigator for one building."""
from app.agent import prompts
from app.agent.subagents import subagents
from app.agent.tools import APPROVAL_TOOL, building_tools


def create_investigator(sid, model, checkpointer):
    """A Deep Agent with planning, two sub-agents and a human-approval pause before saving a material change."""
    from deepagents import create_deep_agent

    tools = building_tools(sid)
    return create_deep_agent(
        model=model,
        tools=[tools[name] for name in ("list_rooms", "room_details", "what_if", "building_facts", "view_room",
                                        APPROVAL_TOOL)],
        subagents=subagents(tools),
        system_prompt=prompts.MAIN,
        interrupt_on={APPROVAL_TOOL: {"allowed_decisions": ["approve", "reject"]}},
        checkpointer=checkpointer,
    )
