import { it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AgentPanel, { Answer } from "../src/components/AgentPanel";

it("asks a question, shows sub-agent steps, and sends an approval decision", async () => {
  let polls = 0;
  const fetcher = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === "/api/agent/threads") return Response.json({ thread_id: "t1", model: "openai:test" });
    if (path.endsWith("/messages")) return Response.json({ status: "running" }, { status: 202 });
    if (path.endsWith("/approve")) return Response.json({ status: "running" }, { status: 202 });
    if (path.includes("/events")) {
      polls += 1;
      if (polls === 1)
        return Response.json({
          status: "awaiting_approval",
          next: 4,
          events: [
            { kind: "user", text: "Check the kitchen floor" },
            { kind: "delegate", agent: "material-annotator", task: "Check r6 floor" },
            { kind: "tool", agent: "material-annotator", name: "view_room", label: "Looking at a room photo", args: { room_id: "r6", view: "Floor" } },
            { kind: "approval", room_id: "r6", surface: "floor", value: "ceramic_tile", reason: "Glazed tile", current: "vinyl_tile", photo_url: "/photo.jpg" },
          ],
        });
      return Response.json({
        status: "idle",
        next: 6,
        events: [{ kind: "decision", approved: true }, { kind: "answer", text: "Saved **ceramic tile** for `r6`." }],
      });
    }
    throw new Error(`Unexpected ${path} ${init?.method}`);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<AgentPanel sid="scan1" />);
  await userEvent.type(screen.getByPlaceholderText("Ask about echo, rooms or fixes"), "Check the kitchen floor");
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));
  expect(await screen.findByText(/Asked the material annotator/, {}, { timeout: 3000 })).toBeInTheDocument();
  expect(screen.getByText("room_id: r6, view: Floor")).toBeInTheDocument();
  expect(screen.getByRole("alertdialog", { name: "Approve a material change" })).toHaveTextContent("vinyl_tile");
  expect(screen.getByPlaceholderText("Answer the approval request above first")).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Approve and save" }));
  expect(await screen.findByText("ceramic tile", {}, { timeout: 3000 })).toContainHTML("strong");
  expect(screen.queryByRole("button", { name: "Approve and save" })).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith("/api/agent/threads/t1/approve", expect.objectContaining({ body: JSON.stringify({ approve: true }) }));
});

it("renders answer tables and lists from the agent's Markdown", () => {
  render(<Answer text={"Options:\n\n| Option | 500 Hz |\n|---|---|\n| Carpet | **0.39 s** |\n\n- one\n- two"} />);
  expect(screen.getByRole("columnheader", { name: "500 Hz" })).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "0.39 s" })).toBeInTheDocument();
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
});
