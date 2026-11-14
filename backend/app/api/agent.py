"""The deepagents agent: chat, live plan, human approval."""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/threads")
def new_thread():
    """Start a conversation about one building; returns a thread id."""
    raise HTTPException(501, "Not implemented yet: new_thread")


@router.post("/threads/{thread_id}/messages")
def send_message(thread_id: str):
    """User message in; the agent runs (see app/agent)."""
    raise HTTPException(501, "Not implemented yet: send_message")


@router.get("/threads/{thread_id}/events")
def agent_events(thread_id: str):
    """Server-sent events: to-dos, sub-agent activity, tool calls, final answer."""
    raise HTTPException(501, "Not implemented yet: agent_events")


@router.post("/threads/{thread_id}/approve")
def approve(thread_id: str):
    """Resume after a human-approval pause (e.g. 'glass or glossy paint?')."""
    raise HTTPException(501, "Not implemented yet: approve")
