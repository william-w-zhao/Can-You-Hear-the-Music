// The only place that calls the backend. Every page and component goes through these functions.
// Routes are defined in backend/app/api/.

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
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

type RoomMaterials = {
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

export const api = {
  buildings: (query = "") => get<BuildingSummary[]>(`/api/buildings${query}`),
  building: (sid: string) => get<BuildingSummary>(`/api/buildings/${encodeURIComponent(sid)}`),
  analyse: (sid: string) => post<{ job_id: string }>(`/api/buildings/${sid}/analyse`),
  rooms: (sid: string) => get<BuildingRooms>(`/api/buildings/${encodeURIComponent(sid)}/rooms`),
  acoustics: (sid: string, roomId: string) => get<AcousticDetails>(acousticPath(sid, roomId)),
  whatIf: (sid: string, roomId: string, materials: Partial<RoomMaterials>) =>
    post<RoomAcoustics>(`${acousticPath(sid, roomId)}/what-if`, materials),
  newThread: (sid: string) => post<{ thread_id: string }>("/api/agent/threads", { sid }),
  send: (threadId: string, text: string) => post(`/api/agent/threads/${threadId}/messages`, { text }),
  agentEvents: (threadId: string) => new EventSource(`/api/agent/threads/${threadId}/events`),
};
