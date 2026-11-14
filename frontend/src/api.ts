// The only place that calls the backend. Every page and component goes through these functions.
// Routes are defined in backend/app/api/.

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) {
    const error = await r.json().catch(() => null);
    throw new Error(typeof error?.detail === "string" ? error.detail : `Request failed (${r.status}).`);
  }
  return r.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
  if (!r.ok) {
    const error = await r.json().catch(() => null);
    throw new Error(typeof error?.detail === "string" ? error.detail : `Request failed (${r.status}).`);
  }
  return r.json();
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
    height_source: "matterport" | "assumed" | "point_cloud_estimate" | "floor_point_cloud_estimate";
  } | null;
  object_evidence: ObjectEvidence;
  can_run_room_review?: boolean;
  review_model?: string | null;
  review_model_error?: string | null;
};

export type RoomProposal = { target: string; value: string; view: string; reason: string };
export type RoomReview = { revision: string; proposals: RoomProposal[]; descriptions: Record<string, string>; model?: string };

export type Detection = {
  label: string;
  confidence: number;
  needs_review: boolean;
  box_px: [number, number, number, number];
};

type EvidenceStatus = "pending" | "complete" | "unavailable" | "failed";

export type ObjectPair = [string, string];
export type MatchDecision = "same" | "separate" | "reset";
export type ObjectInventory = {
  groups: { id: string; label: string; detection_ids: string[]; status: "estimated" | "needs_match" | "low_score" }[];
  reviews: { id: string; detection_ids: ObjectPair; decision: "same" | "separate" | null; reason: string }[];
};

export type ObjectEvidence = {
  status: EvidenceStatus;
  objects?: string[];
  candidates?: string[];
  detections?: (Detection & { id: string; view: string; sheet_box_px: Detection["box_px"] })[];
  inventory?: ObjectInventory;
  can_suggest_match?: boolean;
  image_url?: string;
  image_width?: number;
  image_height?: number;
  image_row?: [number, number, number, number];
  views?: { name: string; viewport: [number, number, number, number]; photo_url?: string }[];
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

export const api = {
  buildings: (query = "") => get<BuildingSummary[]>(`/api/buildings${query}`),
  building: (sid: string) => get<BuildingSummary>(`/api/buildings/${encodeURIComponent(sid)}`),
  analyse: (sid: string) => post<{ job_id: string }>(`/api/buildings/${encodeURIComponent(sid)}/analyse`),
  analysisJob: (jobId: string) => get<AnalysisJob>(`/api/jobs/${encodeURIComponent(jobId)}`),
  saveMaterials: (jobId: string, materials: Record<string, RoomMaterials>) =>
    post<{ job_id: string }>(`/api/jobs/${encodeURIComponent(jobId)}/materials`, materials),
  rooms: (sid: string) => get<BuildingRooms>(`/api/buildings/${encodeURIComponent(sid)}/rooms`),
  surroundings: (sid: string) => get<Surroundings>(`/api/buildings/${encodeURIComponent(sid)}/surroundings`),
  acoustics: (sid: string, roomId: string) => get<AcousticDetails>(acousticPath(sid, roomId)),
  reviewRoom: (sid: string, roomId: string) => post<RoomReview>(`${acousticPath(sid, roomId)}/room-review`),
  approveRoomReview: (sid: string, roomId: string, revision: string, proposals: RoomProposal[]) =>
    post<AcousticDetails>(`${acousticPath(sid, roomId)}/room-review/approve`, { revision, proposals }),
  saveObjectMatch: (sid: string, roomId: string, detection_ids: ObjectPair, decision: MatchDecision) =>
    post<ObjectInventory>(`${acousticPath(sid, roomId)}/object-review`, { detection_ids, decision }),
  suggestObjectMatch: (sid: string, roomId: string, detection_ids: ObjectPair) =>
    post<{ decision: "same" | "separate" | "unsure"; reason: string; model?: string }>(
      `${acousticPath(sid, roomId)}/object-review/suggest`, { detection_ids }),
  whatIf: (sid: string, roomId: string, materials: Partial<RoomMaterials>) =>
    post<RoomAcoustics>(`${acousticPath(sid, roomId)}/what-if`, materials),
  newThread: (sid: string) => post<{ thread_id: string }>("/api/agent/threads", { sid }),
  send: (threadId: string, text: string) => post(`/api/agent/threads/${threadId}/messages`, { text }),
  agentEvents: (threadId: string) => new EventSource(`/api/agent/threads/${threadId}/events`),
};
