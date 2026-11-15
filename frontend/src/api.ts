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
  state?: string;
  kind?: string;
  preview_url?: string;
  type?: string;
  analysis_job_id?: string;
  vision_pending?: boolean;
};

export type RoomOutline = {
  id: string;
  label: string;
  polygon_px: [number, number][];
  center_px?: [number, number];
  area_m2: number;
  height_m: number;
  volume_m3: number;
};

export type BuildingRooms = {
  floorplan: { url: string; width: number; height: number } | null;
  rooms: RoomOutline[];
};

export type RoomMaterials = {
  type: string;
  floor: string;
  ceiling: string;
  walls: string;
  glass_m2: number;
  furnishing: string;
};

export type RoomAcoustics = RoomMaterials & {
  id: string;
  rt60: [number, number, number];
  rt60_range_500: [number, number];
  absorption_500: number;
  verdict: string;
};

export type AcousticDetails = {
  bands_hz: string[];
  voice_url: string | null;
  material_options: Record<string, string>;
  furnishing_options: string[];
  room: RoomAcoustics;
  dimensions: {
    length_m: number | null;
    width_m: number | null;
    height_m: number | null;
    area_m2: number | null;
    volume_m3: number | null;
    footprint_source: "matterport" | "point_cloud";
    height_source:
      | "matterport"
      | "assumed"
      | "point_cloud_estimate"
      | "floor_point_cloud_estimate";
  } | null;
  object_evidence: ObjectEvidence;
  can_run_room_review?: boolean;
  review_model?: string | null;
  review_model_error?: string | null;
};

export type RoomProposal = {
  target: string;
  value: string;
  view: string;
  reason: string;
};
export type RoomReview = {
  revision: string;
  proposals: RoomProposal[];
  descriptions: Record<string, string>;
  model?: string;
  applied: RoomProposal[];
  details: AcousticDetails | null;
};

export type Detection = {
  label: string;
  confidence: number;
  needs_review: boolean;
  box_px: [number, number, number, number];
};

type EvidenceStatus = "pending" | "complete" | "unavailable" | "failed";

export type ObjectPair = [string, string];
export type MatchDecision = "same" | "separate" | "reset";
export type ObjectGroup = {
  id: string;
  label: string;
  detection_ids: string[];
  views: string[];
  confidence: number;
  status: "estimated" | "needs_match" | "low_score";
};
export type ObjectInventory = {
  groups: ObjectGroup[];
  reviews: {
    id: string;
    detection_ids: ObjectPair;
    decision: "same" | "separate" | null;
    reason: string;
  }[];
};

export type ObjectEvidence = {
  status: EvidenceStatus;
  objects?: string[];
  candidates?: string[];
  detections?: (Detection & {
    id: string;
    view: string;
    sheet_box_px: Detection["box_px"];
  })[];
  inventory?: ObjectInventory;
  can_suggest_match?: boolean;
  image_url?: string;
  image_width?: number;
  image_height?: number;
  image_row?: [number, number, number, number];
  views?: {
    name: string;
    viewport: [number, number, number, number];
    photo_url?: string;
  }[];
};

export type Surroundings = {
  status: EvidenceStatus;
  detections?: Detection[];
  image_url: string | null;
  width?: number;
  height?: number;
  mapped_buildings: number | null;
};

export type AnalysisJob = {
  job_id: string;
  status: "running" | "needs_materials" | "complete" | "failed";
  message: string;
  review: {
    rooms: (RoomOutline & { matterport_label?: string })[];
    suggestions: Record<string, RoomMaterials & { confidence: number }>;
    object_hints?: Record<string, { objects: string[]; candidates: string[] }>;
    has_room_sheet: boolean;
    material_options: Record<string, string>;
    furnishing_options: string[];
  } | null;
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

export type AgentTodo = { content: string; status: "pending" | "in_progress" | "completed" };
export type AgentEvent =
  | { kind: "user"; text: string }
  | { kind: "plan"; todos: AgentTodo[] }
  | { kind: "delegate"; agent: string; task: string }
  | { kind: "delegate_done"; agent: string }
  | { kind: "tool"; agent: string; name: string; label: string; args: Record<string, string | number> }
  | {
      kind: "approval";
      room_id: string;
      surface: string;
      value: string;
      reason: string;
      current: string | null;
      photo_url: string;
    }
  | { kind: "decision"; approved: boolean }
  | { kind: "answer"; text: string }
  | { kind: "error"; text: string };
export type AgentStatus = "idle" | "running" | "awaiting_approval" | "error";
export type AgentEvents = { status: AgentStatus; events: AgentEvent[]; next: number };

export const api = {
  agentThread: (sid: string) =>
    post<{ thread_id: string; model: string }>("/api/agent/threads", { sid }),
  agentAsk: (threadId: string, text: string) =>
    post<{ status: AgentStatus }>(`/api/agent/threads/${encodeURIComponent(threadId)}/messages`, { text }),
  agentEvents: (threadId: string, after: number, signal?: AbortSignal) =>
    get<AgentEvents>(`/api/agent/threads/${encodeURIComponent(threadId)}/events?after=${after}`, signal),
  agentDecide: (threadId: string, approve: boolean) =>
    post<{ status: AgentStatus }>(`/api/agent/threads/${encodeURIComponent(threadId)}/approve`, { approve }),
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
    post<{ job_id: string }>(
      `/api/buildings/${encodeURIComponent(sid)}/analyse`,
    ),
  analysisJob: (jobId: string) =>
    get<AnalysisJob>(`/api/jobs/${encodeURIComponent(jobId)}`),
  saveMaterials: (sid: string, materials: Record<string, RoomMaterials>) =>
    post<{ job_id: string }>(
      `/api/buildings/${encodeURIComponent(sid)}/materials`,
      materials,
    ),
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
  surroundings: (sid: string) =>
    get<Surroundings>(`/api/buildings/${encodeURIComponent(sid)}/surroundings`),
  reviewRoom: (sid: string, roomId: string) =>
    post<RoomReview>(`${acousticPath(sid, roomId)}/room-review`),
  approveRoomReview: (
    sid: string,
    roomId: string,
    revision: string,
    proposals: RoomProposal[],
  ) =>
    post<AcousticDetails>(`${acousticPath(sid, roomId)}/room-review/approve`, {
      revision,
      proposals,
    }),
  saveObjectMatch: (
    sid: string,
    roomId: string,
    detection_ids: ObjectPair,
    decision: MatchDecision,
  ) =>
    post<ObjectInventory>(`${acousticPath(sid, roomId)}/object-review`, {
      detection_ids,
      decision,
    }),
  mergeObjects: (sid: string, roomId: string, detection_ids: string[]) =>
    post<ObjectInventory>(`${acousticPath(sid, roomId)}/object-review/merge`, {
      detection_ids,
    }),
  splitObjects: (sid: string, roomId: string, detection_ids: string[]) =>
    post<ObjectInventory>(`${acousticPath(sid, roomId)}/object-review/split`, {
      detection_ids,
    }),
  // A room view with these detections outlined and tagged A, B, ... (an <img> source, not a fetch).
  objectViewUrl: (sid: string, roomId: string, detection_ids: string[]) =>
    `${acousticPath(sid, roomId)}/object-review/view.jpg?ids=${detection_ids
      .map(encodeURIComponent)
      .join(",")}`,
  suggestObjectMatch: (
    sid: string,
    roomId: string,
    detection_ids: ObjectPair,
  ) =>
    post<{
      decision: "same" | "separate" | "unsure";
      reason: string;
      model?: string;
    }>(`${acousticPath(sid, roomId)}/object-review/suggest`, { detection_ids }),
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
};
