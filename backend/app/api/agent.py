"""The investigator agent: chat threads, a live event log, and human approval.

Threads live in memory (a restart clears them). The agent runs in a background thread; the page polls
GET /threads/{id}/events?after=N for new events: the plan, delegations to sub-agents, tool calls, approval
requests and the final answer.
"""
import logging
import threading
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agent.tools import APPROVAL_TOOL, approval_view, photo_url
from app.sources.review_model import resolve_review_model

router = APIRouter()
logger = logging.getLogger(__name__)
THREADS: dict[str, "Thread"] = {}
TOOL_LABELS = {"list_rooms": "Listing rooms", "room_details": "Reading room details", "what_if": "Trying a what-if",
               "building_facts": "Reading listing facts", "view_room": "Looking at a room photo",
               "read_file": "Reading notes", "write_file": "Writing notes", "edit_file": "Editing notes",
               "ls": "Listing notes"}


class NewThread(BaseModel):
    sid: str = Field(min_length=1, max_length=64)


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class Decision(BaseModel):
    approve: bool
    message: str | None = Field(default=None, max_length=500)


def text_of(content):
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content or [] if isinstance(block, dict)
                   and block.get("type") in ("text", "output_text"))


class Thread:
    def __init__(self, sid, agent):
        self.id = uuid.uuid4().hex
        self.sid = sid
        self.agent = agent
        self.events: list[dict] = []
        self.status = "idle"            # idle, running, awaiting_approval, error
        self.lock = threading.Lock()
        self.delegations: dict[str, str] = {}

    def emit(self, kind, **data):
        with self.lock:
            self.events.append({"kind": kind, **data})

    def start(self, payload, event=None):
        with self.lock:
            if self.status in ("running", "awaiting_approval"):
                raise HTTPException(409, "The agent is busy. Wait for it, or answer its approval request.")
            self.status = "running"
            if event:
                self.events.append(event)
        threading.Thread(target=self.run, args=(payload,), daemon=True).start()

    def run(self, payload):
        config = {"configurable": {"thread_id": self.id}, "recursion_limit": 80}
        try:
            for namespace, update in self.agent.stream(payload, config, stream_mode="updates", subgraphs=True):
                self.record(namespace, update)
                if "__interrupt__" in update:
                    self.ask(update["__interrupt__"])
                    return
            messages = self.agent.get_state(config).values.get("messages", [])
            answer = next((text_of(m.content) for m in reversed(messages) if m.type == "ai" and text_of(m.content)), "")
            self.emit("answer", text=answer or "The agent finished without an answer.")
            with self.lock:
                self.status = "idle"
        except Exception as exc:
            logger.exception("Agent run failed for %s", self.sid)
            self.emit("error", text=f"The agent stopped: {type(exc).__name__}. Try asking again.")
            with self.lock:
                self.status = "error"

    def record(self, namespace, update):
        """Turn one graph update into events the page can show."""
        agent = "main"
        if namespace:
            open_tasks = list(self.delegations.values())
            agent = open_tasks[-1] if open_tasks else "sub-agent"
        for node in update.values():
            if not isinstance(node, dict):
                continue
            if "todos" in node and not namespace:
                todos = node["todos"] or []
                self.emit("plan", todos=[{"content": t.get("content", ""), "status": t.get("status", "pending")}
                                         for t in todos])
            messages = node.get("messages")
            messages = getattr(messages, "value", messages)
            for message in messages if isinstance(messages, list) else []:
                if getattr(message, "type", "") == "tool" and message.tool_call_id in self.delegations:
                    self.emit("delegate_done", agent=self.delegations.pop(message.tool_call_id))
                for call in getattr(message, "tool_calls", None) or []:
                    name, args = call["name"], call.get("args", {})
                    if name == "task":
                        self.delegations[call["id"]] = args.get("subagent_type", "sub-agent")
                        self.emit("delegate", agent=args.get("subagent_type", "sub-agent"),
                                  task=str(args.get("description", ""))[:400])
                    elif name in TOOL_LABELS:
                        shown = {k: v for k, v in args.items() if v is not None and k in (
                            "room_id", "view", "floor", "ceiling", "walls", "glass_m2", "furnishing")}
                        self.emit("tool", agent=agent, name=name, label=TOOL_LABELS[name], args=shown)

    def ask(self, interrupts):
        request = interrupts[0].value
        action = next(a for a in request["action_requests"] if a["name"] == APPROVAL_TOOL)
        args = action["args"]
        try:
            from app.api.acoustics import cached_room
            current = cached_room(self.sid, args["room_id"])[1].get(args["surface"])
        except Exception:
            current = None
        self.emit("approval", room_id=args.get("room_id"), surface=args.get("surface"), value=args.get("value"),
                  reason=args.get("reason", ""), current=current,
                  photo_url=photo_url(self.sid, args.get("room_id"), approval_view(args.get("surface"))))
        with self.lock:
            self.status = "awaiting_approval"


def get_thread(thread_id):
    thread = THREADS.get(thread_id)
    if thread is None:
        raise HTTPException(404, "Unknown conversation. Start a new one.")
    return thread


@router.post("/threads")
def new_thread(body: NewThread):
    """Start a conversation about one analysed building; returns a thread id."""
    from langgraph.checkpoint.memory import InMemorySaver

    from app.agent.agent import create_investigator
    from app.api.cache import scan_directory

    if not (scan_directory(body.sid) / "acoustics.json").is_file():
        raise HTTPException(409, "Analyse this building before asking the agent about it.")
    settings, error = resolve_review_model()
    if settings is None:
        raise HTTPException(503, error)
    model = settings.chat(max_tokens=4000, timeout=120, max_retries=1)
    thread = Thread(body.sid, create_investigator(body.sid, model, InMemorySaver()))
    THREADS[thread.id] = thread
    return {"thread_id": thread.id, "model": settings.identifier}


@router.post("/threads/{thread_id}/messages", status_code=202)
def send_message(thread_id: str, body: Message):
    """Send a question; the agent runs in the background."""
    thread = get_thread(thread_id)
    thread.start({"messages": [{"role": "user", "content": body.text}]}, {"kind": "user", "text": body.text})
    return {"status": thread.status}


@router.get("/threads/{thread_id}/events")
def agent_events(thread_id: str, after: int = 0):
    """Events since index `after`, and the thread's status."""
    thread = get_thread(thread_id)
    with thread.lock:
        return {"status": thread.status, "events": thread.events[max(after, 0):], "next": len(thread.events)}


@router.post("/threads/{thread_id}/approve", status_code=202)
def approve(thread_id: str, decision: Decision):
    """Approve or reject the material change the agent asked about, then let it continue."""
    from langgraph.types import Command

    thread = get_thread(thread_id)
    with thread.lock:
        if thread.status != "awaiting_approval":
            raise HTTPException(409, "The agent is not waiting for approval.")
        thread.status = "idle"
    choice = {"type": "approve"} if decision.approve else {
        "type": "reject", "message": decision.message or "The person rejected this change. Keep the saved label."}
    thread.start(Command(resume={"decisions": [choice]}), {"kind": "decision", "approved": decision.approve})
    return {"status": thread.status}
