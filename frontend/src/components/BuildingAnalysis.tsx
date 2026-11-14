import { useEffect, useState, type FormEvent } from "react";
import { api, type AnalysisJob, type RoomMaterials } from "../api";

type Props = { sid: string; initialJobId?: string; onReady: () => void };
type Review = NonNullable<AnalysisJob["review"]>;
const surfaceFields = ["floor", "ceiling", "walls"] as const;

function MaterialReview({ sid, review, onSave, busy }: {
  sid: string;
  review: Review;
  onSave: (materials: Record<string, RoomMaterials>) => void;
  busy: boolean;
}) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const rooms = Object.fromEntries(review.rooms.map((room) => {
      const value = (field: string) => String(values.get(`${room.id}-${field}`) ?? "").trim();
      return [room.id, {
        type: value("type"),
        floor: value("floor"),
        ceiling: value("ceiling"),
        walls: value("walls"),
        furnishing: value("furnishing"),
        glass_m2: Number(value("glass_m2")),
      }];
    }));
    onSave(rooms);
  }

  return (
    <form onSubmit={submit}>
      {review.has_room_sheet && (
        <p><a href={`/data/${encodeURIComponent(sid)}/room_sheet.jpg`} target="_blank" rel="noreferrer">
          Open room panorama views ↗
        </a></p>
      )}
      {review.rooms.map((room) => {
        const suggestion = review.suggestions[room.id];
        return (
          <fieldset className="material-fields" key={room.id} disabled={busy}>
            <legend>{room.id.toUpperCase()} · {room.matterport_label || `${room.area_m2} m²`}</legend>
            {suggestion && <p>Suggested labels · {Math.round(suggestion.confidence * 100)}% model confidence</p>}
            <label>Room name<input required maxLength={100} name={`${room.id}-type`}
              defaultValue={suggestion?.type || room.matterport_label || `Room ${room.id.toUpperCase()}`} /></label>
            {surfaceFields.map((field) => (
              <label key={field}>{field}
                <select required name={`${room.id}-${field}`} defaultValue={suggestion?.[field] ?? ""}>
                  <option value="">Choose material</option>
                  {Object.entries(review.material_options).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                </select>
              </label>
            ))}
            <label>Furnishings
              <select required name={`${room.id}-furnishing`} defaultValue={suggestion?.furnishing ?? ""}>
                <option value="">Choose furnishings</option>
                {review.furnishing_options.map((option) => <option key={option} value={option}>{option.replaceAll("_", " ")}</option>)}
              </select>
            </label>
            <label>Glass area (m²)<input required type="number" step="any" min={0}
              name={`${room.id}-glass_m2`} defaultValue={suggestion?.glass_m2 ?? ""} /></label>
          </fieldset>
        );
      })}
      <button className="show-more" disabled={busy}>Save materials and calculate</button>
    </form>
  );
}

export default function BuildingAnalysis({ sid, initialJobId, onReady }: Props) {
  const [jobId, setJobId] = useState(initialJobId);
  const [pollVersion, setPollVersion] = useState(0);
  const [job, setJob] = useState<AnalysisJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!jobId) return;
    let active = true;
    let timer: number | undefined;
    async function poll(id: string) {
      try {
        const latest = await api.analysisJob(id);
        if (!active) return;
        setJob(latest);
        if (latest.status === "complete") onReady();
        if (latest.status === "running") timer = window.setTimeout(() => void poll(id), 1500);
      } catch {
        if (active) {
          setJob(null);
          setJobId(undefined);
          setError("Couldn’t check analysis progress. Select Analyse building to reconnect.");
        }
      }
    }
    void poll(jobId);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [jobId, onReady, pollVersion]);

  async function start() {
    setError("");
    setBusy(true);
    try {
      const result = await api.analyse(sid);
      setJob(null);
      setJobId(result.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t start analysis.");
    } finally {
      setBusy(false);
    }
  }

  async function save(materials: Record<string, RoomMaterials>) {
    if (!job) return;
    setError("");
    setBusy(true);
    try {
      await api.saveMaterials(job.job_id, materials);
      setJob({ ...job, status: "running", message: "Calculating room echo times", review: null });
      setPollVersion((version) => version + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t save materials.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="details-panel" aria-labelledby="analysis-title">
      <h2 id="analysis-title">Building analysis</h2>
      <p role="status">{job?.message || (jobId ? "Checking analysis progress…" : "Prepare room outlines and estimate echo times for this scan.")}</p>
      {error && <p className="intro" role="alert">{error}</p>}
      {(!jobId || job?.status === "failed") && (
        <button className="show-more" disabled={busy} onClick={() => void start()}>
          {job?.status === "failed" ? "Retry analysis" : "Analyse building"}
        </button>
      )}
      {job?.status === "needs_materials" && job.review && (
        <MaterialReview sid={sid} review={job.review} onSave={(materials) => void save(materials)} busy={busy} />
      )}
    </section>
  );
}
