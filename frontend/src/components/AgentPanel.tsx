// Ask the investigator agent about this building: its live plan, sub-agent activity, approval requests and answers.
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type AgentEvent, type AgentStatus, type AgentTodo } from "../api";
import Spinner from "./Spinner";

const SUGGESTIONS = [
  "Which room is best for client video calls?",
  "Why does the loudest room echo, and what is the cheapest fix?",
  "Do the saved materials for the living room match its photos?",
];
const AGENT_NAMES: Record<string, string> = {
  main: "Investigator",
  "material-annotator": "Material annotator",
  "acoustic-simulator": "Acoustic simulator",
};
const POLL_MS = 1200;

type Turn = { question: string; events: AgentEvent[] };

function turns(events: AgentEvent[]): Turn[] {
  const out: Turn[] = [];
  for (const event of events) {
    if (event.kind === "user") out.push({ question: event.text, events: [] });
    else out.at(-1)?.events.push(event);
  }
  return out;
}

// Just enough Markdown for the agent's answers: paragraphs, bullet lists, tables, **bold** and `code`.
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? <strong key={index}>{part.slice(2, -2)}</strong>
      : part.startsWith("`") && part.endsWith("`") && part.length > 2 ? <code key={index}>{part.slice(1, -1)}</code>
        : part,
  );
}

export function Answer({ text }: { text: string }) {
  const blocks = text.trim().split(/\n\s*\n/);
  return (
    <div className="agent-answer">
      {blocks.map((block, index) => {
        const lines = block.split("\n").filter((line) => line.trim());
        if (lines.every((line) => line.trim().startsWith("|"))) {
          const rows = lines
            .filter((line) => !/^\s*\|[\s:|-]+\|\s*$/.test(line))
            .map((line) => line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim()));
          return (
            <div className="agent-table" key={index}>
              <table>
                <thead><tr>{rows[0].map((cell, column) => <th key={column}>{inline(cell)}</th>)}</tr></thead>
                <tbody>
                  {rows.slice(1).map((row, rowIndex) => (
                    <tr key={rowIndex}>{row.map((cell, column) => <td key={column}>{inline(cell)}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (lines.every((line) => /^\s*([-*]|\d+\.)\s/.test(line))) {
          return <ul key={index}>{lines.map((line, item) => <li key={item}>{inline(line.replace(/^\s*([-*]|\d+\.)\s/, ""))}</li>)}</ul>;
        }
        return <p key={index}>{lines.map((line, item) => <Fragment key={item}>{item > 0 && <br />}{inline(line)}</Fragment>)}</p>;
      })}
    </div>
  );
}

function Plan({ todos }: { todos: AgentTodo[] }) {
  return (
    <ol className="agent-plan" aria-label="Agent plan">
      {todos.map((todo, index) => (
        <li key={index} className={`todo-${todo.status}`}>
          <span aria-hidden="true">{todo.status === "completed" ? "✓" : todo.status === "in_progress" ? "●" : "○"}</span>
          {todo.content}
          <span className="visually-hidden"> ({todo.status.replace("_", " ")})</span>
        </li>
      ))}
    </ol>
  );
}

function Activity({ events, working }: { events: AgentEvent[]; working: boolean }) {
  const steps = events.filter((event) => event.kind === "tool" || event.kind === "delegate");
  if (!steps.length && !working) return null;
  return (
    <details className="agent-activity" open={working}>
      <summary>
        {working && <Spinner size="small" />}
        {working ? "Working" : "Steps"} · {steps.length} {steps.length === 1 ? "step" : "steps"}
      </summary>
      <ul>
        {steps.map((event, index) => event.kind === "delegate" ? (
          <li key={index} className="agent-delegate">
            <strong>Asked the {AGENT_NAMES[event.agent]?.toLowerCase() ?? event.agent}</strong>
            <span>{event.task}</span>
          </li>
        ) : event.kind === "tool" ? (
          <li key={index} className={event.agent === "main" ? undefined : "agent-sub"}>
            <span className="agent-who">{AGENT_NAMES[event.agent] ?? event.agent}</span>
            {event.label}
            {Object.keys(event.args).length > 0 && (
              <code>{Object.entries(event.args).map(([key, value]) => `${key}: ${value}`).join(", ")}</code>
            )}
          </li>
        ) : null)}
      </ul>
    </details>
  );
}

function Approval({ event, pending, onDecide }: {
  event: Extract<AgentEvent, { kind: "approval" }>;
  pending: boolean;
  onDecide?: (approve: boolean) => void;
}) {
  return (
    <div className="agent-approval" role={pending ? "alertdialog" : undefined} aria-label="Approve a material change">
      <img src={event.photo_url} alt={`${event.room_id.toUpperCase()} ${event.surface} photo`} loading="lazy" />
      <div>
        <p className="agent-approval-title">
          Change <strong>{event.room_id.toUpperCase()}</strong> {event.surface} from{" "}
          <strong>{event.current ?? "unknown"}</strong> to <strong>{event.value}</strong>?
        </p>
        <p>{event.reason}</p>
        {pending && onDecide && (
          <div className="agent-approval-actions">
            <button type="button" className="agent-approve" onClick={() => onDecide(true)}>Approve and save</button>
            <button type="button" onClick={() => onDecide(false)}>Keep current label</button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function AgentPanel({ sid }: { sid: string }) {
  const [threadId, setThreadId] = useState<string>();
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [status, setStatus] = useState<AgentStatus>("idle");
  const [text, setText] = useState("");
  const [error, setError] = useState<string>();
  const [sending, setSending] = useState(false);
  const next = useRef(0);

  // Poll for new events while the agent is running.
  useEffect(() => {
    if (!threadId || status !== "running") return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const data = await api.agentEvents(threadId, next.current, controller.signal);
        next.current = data.next;
        if (data.events.length) setEvents((old) => [...old, ...data.events]);
        setStatus(data.status);
        if (data.status === "running") timer = setTimeout(poll, POLL_MS);
      } catch (caught) {
        if (controller.signal.aborted) return;
        setError(caught instanceof Error ? caught.message : "Lost contact with the agent.");
        setStatus("error");
      }
    };
    timer = setTimeout(poll, POLL_MS);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [threadId, status]);

  const ask = async (question: string) => {
    if (!question.trim() || sending) return;
    setSending(true);
    setError(undefined);
    try {
      let id = threadId;
      if (!id) {
        id = (await api.agentThread(sid)).thread_id;
        next.current = 0;
        setThreadId(id);
      }
      await api.agentAsk(id, question.trim());
      setText("");
      setStatus("running");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Couldn’t reach the agent.");
    } finally {
      setSending(false);
    }
  };

  const decide = async (approve: boolean) => {
    if (!threadId) return;
    try {
      await api.agentDecide(threadId, approve);
      setStatus("running");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Couldn’t send your decision.");
    }
  };

  const conversation = turns(events);
  const busy = sending || status === "running" || status === "awaiting_approval";

  return (
    <section className="details-panel agent-panel" aria-labelledby="agent-title">
      <h2 id="agent-title">Ask the acoustic investigator</h2>
      <p className="agent-intro">
        A Deep Agent that plans, hands work to sub-agents for photo checks and treatment comparisons, and asks you
        before it saves any change. Every number comes from the same engine as this dashboard.
      </p>
      {conversation.map((turn, index) => {
        const last = index === conversation.length - 1;
        const plan = [...turn.events].reverse().find((event) => event.kind === "plan");
        return (
          <article key={index} className="agent-turn">
            <p className="agent-question">{turn.question}</p>
            {plan?.kind === "plan" && plan.todos.length > 0 && <Plan todos={plan.todos} />}
            <Activity events={turn.events} working={last && status === "running"} />
            {turn.events.map((event, eventIndex) => {
              if (event.kind === "approval") {
                const answered = turn.events.slice(eventIndex + 1).some((later) => later.kind === "decision");
                return <Approval key={eventIndex} event={event} pending={last && !answered && status === "awaiting_approval"}
                  onDecide={decide} />;
              }
              if (event.kind === "decision")
                return <p key={eventIndex} className="agent-note">{event.approved ? "You approved the change." : "You kept the current label."}</p>;
              if (event.kind === "answer") return <Answer key={eventIndex} text={event.text} />;
              if (event.kind === "error") return <p key={eventIndex} role="alert">{event.text}</p>;
              return null;
            })}
          </article>
        );
      })}
      {conversation.length === 0 && (
        <div className="agent-suggestions">
          {SUGGESTIONS.map((suggestion) => (
            <button key={suggestion} type="button" disabled={busy} onClick={() => ask(suggestion)}>{suggestion}</button>
          ))}
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      <form className="agent-form" onSubmit={(event) => { event.preventDefault(); ask(text); }}>
        <label className="visually-hidden" htmlFor="agent-input">Question for the agent</label>
        <input id="agent-input" value={text} maxLength={2000} disabled={busy} onChange={(event) => setText(event.target.value)}
          placeholder={status === "awaiting_approval" ? "Answer the approval request above first" : "Ask about echo, rooms or fixes"} />
        <button type="submit" disabled={busy || !text.trim()}>{sending ? "Sending…" : "Ask"}</button>
      </form>
    </section>
  );
}
