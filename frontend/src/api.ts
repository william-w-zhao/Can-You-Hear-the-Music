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

export const api = {
  buildings: (query = "") => get<unknown[]>(`/api/buildings${query}`),
  building: (sid: string) => get<unknown>(`/api/buildings/${sid}`),
  analyse: (sid: string) => post<{ job_id: string }>(`/api/buildings/${sid}/analyse`),
  rooms: (sid: string) => get<unknown[]>(`/api/buildings/${sid}/rooms`),
  acoustics: (roomId: string) => get<unknown>(`/api/acoustics/${roomId}`),
  whatIf: (roomId: string, materials: unknown) => post<unknown>(`/api/acoustics/${roomId}/what-if`, materials),
  newThread: (sid: string) => post<{ thread_id: string }>("/api/agent/threads", { sid }),
  send: (threadId: string, text: string) => post(`/api/agent/threads/${threadId}/messages`, { text }),
  agentEvents: (threadId: string) => new EventSource(`/api/agent/threads/${threadId}/events`),
};
