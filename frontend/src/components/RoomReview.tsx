import { useEffect, useState } from "react";
import { api, type AcousticDetails, type RoomReview as Review } from "../api";
import EvidenceImage from "./EvidenceImage";
import Spinner from "./Spinner";

// Seconds since `active` became true, for long-running work.
function useElapsed(active: boolean) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) return;
    setSeconds(0);
    const timer = window.setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return seconds;
}

export default function RoomReview({ sid, roomId, details, onSave }: {
  sid: string;
  roomId: string;
  details: AcousticDetails;
  onSave: (details: AcousticDetails) => void;
}) {
  const [draft, setDraft] = useState<Review>();
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState<"review" | "save">();
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const elapsed = useElapsed(busy === "review");
  const evidence = details.object_evidence;
  if (!evidence.views?.length) return null;

  async function run() {
    setBusy("review");
    setError("");
    setSaved(false);
    setDraft(undefined);
    setSelected([]);
    try {
      const result = await api.reviewRoom(sid, roomId);
      if (result.details) onSave(result.details);
      setDraft(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t review this room.");
    } finally {
      setBusy(undefined);
    }
  }

  async function approve() {
    if (!draft || !selected.length) return;
    setBusy("save");
    setError("");
    try {
      const result = await api.approveRoomReview(sid, roomId, draft.revision,
        draft.proposals.filter((item) => selected.includes(item.target)));
      onSave(result);
      setDraft(undefined);
      setSelected([]);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t save the review.");
    } finally {
      setBusy(undefined);
    }
  }

  const choices: Record<string, string> = {
    same: "Same object", separate: "Separate objects", keep: "Keep label", dismiss: "Dismiss box", unsure: "Unsure",
  };
  return (
    <section className="details-panel room-agent-review" aria-labelledby="room-review-title">
      <h2 id="room-review-title">Room review</h2>
      <p>Floor · {details.material_options[details.room.floor]} · Walls · {details.material_options[details.room.walls]}
        {" · "}Ceiling · {details.material_options[details.room.ceiling]}</p>
      {details.can_run_room_review ? (
        <>
          <p>The model checks uncertain detections and duplicates using the room photos. Clear object decisions are applied automatically. Material changes need your approval.</p>
          {details.review_model && <p>Review model · {details.review_model}</p>}
          <button className="show-more" type="button" onClick={() => void run()} disabled={Boolean(busy)}>Review this room</button>
        </>
      ) : <p>{details.review_model_error ?? "Model review is unavailable."}</p>}
      {busy === "review" && <Spinner label={`The agent is inspecting the room photos · ${elapsed}s`} />}
      {busy === "save" && <Spinner size="small" label="Saving approved changes" />}
      {saved && <p role="status">Review saved. The room reflects your approved changes.</p>}
      {error && <p role="alert">{error}</p>}
      {draft && (
        <p role="status">
          {draft.applied.length > 0 ? `Applied ${draft.applied.length} object decisions automatically.` : "No clear object decisions to apply automatically."}
          {draft.proposals.length > 0 ? ` ${draft.proposals.length} suggestions are available below.` : ""}
        </p>
      )}
      {draft && draft.proposals.length > 0 && (
        <>
          <p>Select the proposals you want to apply.{draft.model && ` Reviewed by ${draft.model}.`}</p>
          <ul className="room-proposals">
            {draft.proposals.map((item) => {
              const view = evidence.views?.find((entry) => entry.name === item.view);
              const ids = item.target.split(":").slice(1);
              const boxes = (evidence.detections ?? []).filter((hit) => ids.includes(hit.id));
              return (
                <li key={item.target}>
                  <label>
                    <input type="checkbox" disabled={Boolean(busy) || item.value === "unsure"}
                      checked={selected.includes(item.target)} onChange={(event) => {
                        const checked = event.target.checked;
                        setSelected((current) => checked ? [...current, item.target] : current.filter((id) => id !== item.target));
                      }} />
                    <strong>{details.material_options[item.value] ?? choices[item.value] ?? item.value}</strong>
                  </label>
                  <p>{draft.descriptions[item.target]}</p>
                  <p>{item.reason}</p>
                  {boxes.length > 0 ? (
                    <img className="proposal-view" loading="lazy" src={api.objectViewUrl(sid, roomId, ids)}
                      alt={boxes.map((hit, i) => `${"AB"[i]}: ${hit.label} in ${hit.view}`).join(", ")} />
                  ) : view && evidence.image_url && evidence.image_width && evidence.image_height && (
                    <div className="object-match-images">
                      <EvidenceImage src={evidence.image_url} width={evidence.image_width}
                        height={evidence.image_height} viewport={view.viewport} label={item.view}
                        boxes={boxes.map((hit) => ({ ...hit, box_px: hit.sheet_box_px }))} />
                    </div>
                  )}
                  {view?.photo_url && <a href={view.photo_url} target="_blank" rel="noreferrer">Open {item.view.toLowerCase()} photo ↗</a>}
                </li>
              );
            })}
          </ul>
          <button className="show-more" type="button" onClick={() => void approve()}
            disabled={!selected.length || Boolean(busy)}>Apply selected suggestions</button>
        </>
      )}
    </section>
  );
}
