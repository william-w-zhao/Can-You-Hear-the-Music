// The only place that calls the backend. Every page and component goes through these functions.
// Routes are defined in backend/app/api/.

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  init.signal?.addEventListener("abort", abort, { once: true });
  if (init.signal?.aborted) controller.abort();
  const timer = setTimeout(abort, 30_000);
  try {
    const r = await fetch(path, { ...init, signal: controller.signal });
    if (!r.ok) {
      let detail = "";
      try {
        const data = await r.json();
        detail =
          typeof data.detail === "string"
            ? data.detail
            : Array.isArray(data.detail)
              ? data.detail
                  .map(
                    (item: { loc?: string[]; msg?: string }) =>
                      `${item.loc?.join(".") ?? "Input"}: ${item.msg ?? "Invalid value"}`,
                  )
                  .join("; ")
              : "";
      } catch {
        /* The development proxy can return a non-JSON error. */
      }
      throw new ApiError(
        detail ||
          (r.status === 501
            ? "This feature is not available yet."
            : `Unable to load data (HTTP ${r.status}). Check that the backend is running.`),
        r.status,
      );
    }
    return r;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (init.signal?.aborted)
      throw new DOMException("Request cancelled", "AbortError");
    if (controller.signal.aborted)
      throw new Error("The request timed out. Please try again.");
    throw new Error(
      "Cannot reach the backend. Check your connection and try again.",
    );
  } finally {
    clearTimeout(timer);
    init.signal?.removeEventListener("abort", abort);
  }
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await request(path, { signal });
  try {
    return await r.json();
  } catch {
    throw new Error("The backend returned invalid JSON.");
  }
}

async function post<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const r = await request(path, {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  try {
    return await r.json();
  } catch {
    throw new Error("The backend returned invalid JSON.");
  }
}

export type BuildingSummary = {
  sid: string;
  analysed: boolean;
  name?: string;
  address?: string;
  city?: string;
  kind?: string;
};

export type RoomOutline = {
  id: string;
  label: string;
  polygon_px: [number, number][];
  area_m2: number;
  height_m: number;
  volume_m3: number;
};

export type BuildingRooms = {
  floorplan: { url: string; width: number; height: number } | null;
  rooms: RoomOutline[];
};

export type RoomMaterials = {
  floor: string;
  ceiling: string;
  walls: string;
  glass_m2: number;
  furnishing: string;
};

export type RoomAcoustics = RoomMaterials & {
  id: string;
  type: string;
  rt60: [number, number, number];
  rt60_range_500: [number, number];
  verdict: string;
  absorption_500: number;
};

export type AcousticDetails = {
  bands_hz: string[];
  voice_url: string | null;
  material_options: Record<string, string>;
  furnishing_options: string[];
  room: RoomAcoustics;
};

const acousticPath = (sid: string, roomId: string) =>
  `/api/buildings/${encodeURIComponent(sid)}/rooms/${encodeURIComponent(roomId)}/acoustics`;

function checkedRoom(room: RoomAcoustics): RoomAcoustics {
  if (
    !room ||
    !Array.isArray(room.rt60) ||
    room.rt60.length !== 3 ||
    !room.rt60.every((n) => Number.isFinite(n) && n > 0) ||
    !Array.isArray(room.rt60_range_500) ||
    room.rt60_range_500.length !== 2 ||
    !room.rt60_range_500.every((n) => Number.isFinite(n) && n >= 0) ||
    !Number.isFinite(room.absorption_500) ||
    room.absorption_500 <= 0 ||
    typeof room.verdict !== "string" ||
    !["id", "type", "floor", "ceiling", "walls", "furnishing"].every(
      (key) => typeof room[key as keyof RoomAcoustics] === "string",
    ) ||
    !Number.isFinite(room.glass_m2) ||
    room.glass_m2 < 0
  ) {
    throw new Error("The backend returned incomplete acoustic results.");
  }
  return room;
}

export const api = {
  roomImageSheet: async (sid: string, signal?: AbortSignal) =>
    (
      await request(`/data/${encodeURIComponent(sid)}/room_sheet.jpg`, {
        signal,
      })
    ).blob(),
  buildings: (query = "") => get<BuildingSummary[]>(`/api/buildings${query}`),
  building: (sid: string) =>
    get<BuildingSummary>(`/api/buildings/${encodeURIComponent(sid)}`),
  analyse: (sid: string) =>
    post<{ job_id: string }>(`/api/buildings/${sid}/analyse`),
  rooms: async (sid: string, signal?: AbortSignal) => {
    const data = await get<BuildingRooms>(
      `/api/buildings/${encodeURIComponent(sid)}/rooms`,
      signal,
    );
    if (
      !data ||
      !Array.isArray(data.rooms) ||
      data.rooms.some(
        (room) =>
          typeof room.id !== "string" ||
          typeof room.label !== "string" ||
          ![room.area_m2, room.height_m, room.volume_m3].every(
            (n) => Number.isFinite(n) && n > 0,
          ),
      )
    )
      throw new Error("The backend returned an invalid room list.");
    return data;
  },
  acoustics: async (sid: string, roomId: string, signal?: AbortSignal) => {
    const data = await get<AcousticDetails>(acousticPath(sid, roomId), signal);
    checkedRoom(data?.room);
    if (
      !Array.isArray(data.bands_hz) ||
      data.bands_hz.length !== 3 ||
      !data.material_options ||
      !Array.isArray(data.furnishing_options)
    )
      throw new Error("The backend returned incomplete material choices.");
    return data;
  },
  whatIf: async (
    sid: string,
    roomId: string,
    materials: Partial<RoomMaterials>,
    signal?: AbortSignal,
  ) => {
    if (
      materials.glass_m2 !== undefined &&
      (!Number.isFinite(materials.glass_m2) || materials.glass_m2 < 0)
    )
      throw new Error("Glass area must be a non-negative number.");
    return checkedRoom(
      await post<RoomAcoustics>(
        `${acousticPath(sid, roomId)}/what-if`,
        materials,
        signal,
      ),
    );
  },
  voice: async (url: string, signal?: AbortSignal) => {
    if (!url.startsWith("/audio/") || url.startsWith("//"))
      throw new Error("Invalid voice clip location.");
    return (await request(url, { signal })).arrayBuffer();
  },
  newThread: (sid: string) =>
    post<{ thread_id: string }>("/api/agent/threads", { sid }),
  send: (threadId: string, text: string) =>
    post(`/api/agent/threads/${threadId}/messages`, { text }),
  agentEvents: (threadId: string) =>
    new EventSource(`/api/agent/threads/${threadId}/events`),
};
