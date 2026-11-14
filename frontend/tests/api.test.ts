import { describe, it, expect, vi } from "vitest";
import { api, ApiError } from "../src/api";
import { details, plan, second } from "./fixtures";

describe("documented room API fetching", () => {
  it("fetches the cached room contact sheet through the same-origin API module", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(new Uint8Array([1, 2, 3]), {
          headers: { "Content-Type": "image/jpeg" },
        }),
      );
    vi.stubGlobal("fetch", fetcher);
    const image = await api.roomImageSheet("office");
    expect(image.type).toBe("image/jpeg");
    expect(fetcher).toHaveBeenCalledWith(
      "/data/office/room_sheet.jpg",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });
  it("keeps identical room IDs scoped to their scans and decodes responses", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(Response.json(details))
      .mockResolvedValueOnce(Response.json(second));
    vi.stubGlobal("fetch", fetcher);
    expect((await api.acoustics("office", "r1")).room.type).toBe(
      "Meeting room",
    );
    expect((await api.acoustics("house", "r1")).room.type).toBe("Quiet office");
    expect(fetcher.mock.calls.map((c) => c[0])).toEqual([
      "/api/buildings/office/rooms/r1/acoustics",
      "/api/buildings/house/rooms/r1/acoustics",
    ]);
    expect(fetcher.mock.calls[0][1].headers).toBeUndefined(); // No third-party service keys in the browser.
  });
  it("encodes scan/room identifiers and reads floor-plan metadata", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(Response.json(plan))
      .mockResolvedValueOnce(Response.json(details));
    vi.stubGlobal("fetch", fetcher);
    expect(await api.rooms("office/a")).toEqual(plan);
    await api.acoustics("office/a", "room #1");
    expect(fetcher.mock.calls[0][0]).toBe("/api/buildings/office%2Fa/rooms");
    expect(fetcher.mock.calls[1][0]).toBe(
      "/api/buildings/office%2Fa/rooms/room%20%231/acoustics",
    );
  });
  it("posts only requested material overrides as JSON and leaves the baseline unchanged", async () => {
    const original = structuredClone(details);
    const fetcher = vi.fn().mockResolvedValue(Response.json(second.room));
    vi.stubGlobal("fetch", fetcher);
    const result = await api.whatIf("office", "r1", {
      floor: "carpet_on_pad",
      glass_m2: 0,
    });
    expect(result.rt60).toEqual(second.room.rt60);
    expect(details).toEqual(original);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/buildings/office/rooms/r1/acoustics/what-if",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: '{"floor":"carpet_on_pad","glass_m2":0}',
      }),
    );
  });
  it.each([404, 422, 501])(
    "surfaces HTTP %i backend explanations",
    async (status) => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            Response.json({ detail: "Room analysis unavailable" }, { status }),
          ),
      );
      await expect(api.acoustics("office", "r1")).rejects.toMatchObject({
        message: "Room analysis unavailable",
        status,
      });
    },
  );
  it("formats field validation errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json(
          {
            detail: [
              { loc: ["body", "glass_m2"], msg: "Must be non-negative" },
            ],
          },
          { status: 422 },
        ),
      ),
    );
    await expect(api.whatIf("office", "r1", { glass_m2: 2 })).rejects.toThrow(
      "body.glass_m2: Must be non-negative",
    );
  });
  it("handles proxy HTML, malformed JSON, network failure, and malformed acoustic data", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response("proxy failure", { status: 502 }))
      .mockResolvedValueOnce(new Response("not json"))
      .mockRejectedValueOnce(new TypeError("network"))
      .mockResolvedValueOnce(
        Response.json({ ...details, room: { ...details.room, rt60: [1] } }),
      );
    vi.stubGlobal("fetch", fetcher);
    await expect(api.rooms("office")).rejects.toBeInstanceOf(ApiError);
    await expect(api.rooms("office")).rejects.toThrow("invalid JSON");
    await expect(api.rooms("office")).rejects.toThrow("Cannot reach");
    await expect(api.acoustics("office", "r1")).rejects.toThrow(
      "incomplete acoustic",
    );
  });
  it("propagates caller cancellation and times out stalled requests", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_path, options) =>
          new Promise((_resolve, reject) => {
            if (options.signal.aborted)
              reject(new DOMException("cancelled", "AbortError"));
            else
              options.signal.addEventListener("abort", () =>
                reject(new DOMException("cancelled", "AbortError")),
              );
          }),
      ),
    );
    try {
      const controller = new AbortController();
      const cancelled = api.rooms("office", controller.signal);
      controller.abort();
      await expect(cancelled).rejects.toMatchObject({ name: "AbortError" });
      const stalled = api.rooms("office");
      const assertion = expect(stalled).rejects.toThrow("timed out");
      await vi.advanceTimersByTimeAsync(30_000);
      await assertion;
    } finally {
      vi.useRealTimers();
    }
  });
  it.each([-1, NaN, Infinity])(
    "rejects invalid glass area %s before fetching",
    async (glass_m2) => {
      const fetcher = vi.fn();
      vi.stubGlobal("fetch", fetcher);
      await expect(api.whatIf("office", "r1", { glass_m2 })).rejects.toThrow(
        "non-negative",
      );
      expect(fetcher).not.toHaveBeenCalled();
    },
  );
  it("loads the voice as binary and reports a missing clip", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response(new Uint8Array([1, 2, 3])))
      .mockResolvedValueOnce(
        Response.json({ detail: "Not found" }, { status: 404 }),
      );
    vi.stubGlobal("fetch", fetcher);
    expect(new Uint8Array(await api.voice("/audio/voice.wav"))).toEqual(
      new Uint8Array([1, 2, 3]),
    );
    await expect(api.voice("/audio/voice.wav")).rejects.toThrow("Not found");
    await expect(api.voice("https://example.com/voice.wav")).rejects.toThrow(
      "Invalid voice",
    );
  });
});
