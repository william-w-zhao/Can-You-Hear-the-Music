import { it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route, Link } from "react-router-dom";
import RoomView from "../src/pages/RoomView";
import { details, plan, second } from "./fixtures";

function mount() {
  return render(
    <MemoryRouter initialEntries={["/b/office/r/r1"]}>
      <Link to="/b/house/r/r1">House room</Link>
      <Routes>
        <Route path="/b/:sid/r/:rid" element={<RoomView />} />
      </Routes>
    </MemoryRouter>,
  );
}
function responses(path: string) {
  return Response.json(
    path.endsWith("/rooms") ? plan : path.includes("/r2/") ? second : details,
  );
}

it("loads a specific room, compares a second room, and preserves the selected baseline", async () => {
  const fetcher = vi.fn(async (path: string) => responses(path));
  vi.stubGlobal("fetch", fetcher);
  mount();
  expect(screen.getByText("Loading your space...")).toBeInTheDocument();
  await screen.findByRole("heading", { name: "Meeting room", level: 1 });
  expect(screen.getByText("16.0 m²")).toBeInTheDocument();
  expect(
    screen.getByText(
      "Choose a second room to see echo, material and listening comparisons.",
    ),
  ).toBeInTheDocument();
  await userEvent.selectOptions(
    screen.getByLabelText("Compare with another room"),
    "r2",
  );
  await screen.findByText("0.30 s less echo at 500 Hz");
  expect(screen.getByText(/50% shorter nominal decay/)).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Meeting room", level: 1 }),
  ).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "▶ Clap" })).toHaveLength(2);
  expect(fetcher).toHaveBeenCalledWith(
    "/api/buildings/office/rooms/r2/acoustics",
    expect.anything(),
  );
});

it("submits a material what-if and resets it without replacing the baseline", async () => {
  const fetcher = vi.fn(async (path: string) =>
    path.endsWith("/what-if") ? Response.json(second.room) : responses(path),
  );
  vi.stubGlobal("fetch", fetcher);
  mount();
  await screen.findByRole("heading", { name: "Meeting room", level: 1 });
  await userEvent.selectOptions(
    screen.getByLabelText("floor"),
    "carpet_on_pad",
  );
  await userEvent.click(screen.getByRole("button", { name: "Apply what-if" }));
  await screen.findByText("Material what-if");
  expect(fetcher).toHaveBeenCalledWith(
    "/api/buildings/office/rooms/r1/acoustics/what-if",
    expect.objectContaining({
      method: "POST",
      body: expect.stringContaining("carpet_on_pad"),
    }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Reset to baseline" }),
  );
  expect(screen.queryByText("Material what-if")).not.toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Meeting room", level: 1 }),
  ).toBeInTheDocument();
});

it("shows an actionable fetch error and retries successfully", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(
      Response.json({ detail: "Analysis unavailable" }, { status: 404 }),
    )
    .mockImplementation(async (path: string) => responses(path));
  vi.stubGlobal("fetch", fetcher);
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Analysis unavailable",
  );
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByRole("heading", { name: "Meeting room", level: 1 });
});

it("rejects blank glass area and does not submit", async () => {
  const fetcher = vi.fn(async (path: string) => responses(path));
  vi.stubGlobal("fetch", fetcher);
  mount();
  await screen.findByRole("heading", { name: "Meeting room", level: 1 });
  await userEvent.clear(screen.getByLabelText("Glass area (m²)"));
  expect(screen.getByRole("button", { name: "Apply what-if" })).toBeDisabled();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "non-negative glass area",
  );
  expect(fetcher.mock.calls.some((c) => c[0].endsWith("/what-if"))).toBe(false);
});

it("cancels an old scan request so its r1 cannot replace another scan's r1", async () => {
  let resolveOld: ((value: Response) => void) | undefined;
  let oldSignal: AbortSignal | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, options: RequestInit) => {
      if (path === "/api/buildings/office/rooms/r1/acoustics") {
        oldSignal = options.signal as AbortSignal;
        return new Promise<Response>((resolve) => {
          resolveOld = resolve;
        });
      }
      return Promise.resolve(
        Response.json(path.endsWith("/rooms") ? plan : second),
      );
    }),
  );
  mount();
  await userEvent.click(screen.getByRole("link", { name: "House room" }));
  await screen.findByRole("heading", { name: "Quiet office", level: 1 });
  expect(oldSignal?.aborted).toBe(true);
  resolveOld?.(Response.json(details));
  await waitFor(() =>
    expect(
      screen.queryByRole("heading", { name: "Meeting room", level: 1 }),
    ).not.toBeInTheDocument(),
  );
});

it("keeps baseline available when the second room fails and lets the listener retry", async () => {
  let attempts = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => {
      if (path.includes("/r2/") && attempts++ === 0)
        return Response.json({ detail: "Room cache missing" }, { status: 404 });
      return responses(path);
    }),
  );
  mount();
  await screen.findByRole("heading", { name: "Meeting room", level: 1 });
  await userEvent.selectOptions(
    screen.getByLabelText("Compare with another room"),
    "r2",
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Room cache missing",
  );
  expect(
    screen.getByRole("heading", { name: "Meeting room", level: 1 }),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByText("0.30 s less echo at 500 Hz");
});
