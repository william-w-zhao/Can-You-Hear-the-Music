import { useEffect, useState } from "react";
import { api, type ObjectEvidence, type ObjectInventory } from "../api";
import Spinner from "./Spinner";

type Suggestion = Awaited<ReturnType<typeof api.suggestObjectMatch>>;

// One possible duplicate at a time, shown as a single view with both boxes outlined (A and B).
export default function DuplicateReview({ sid, roomId, evidence, inventory, onChange }: {
  sid: string;
  roomId: string;
  evidence: ObjectEvidence;
  inventory: ObjectInventory;
  onChange: (inventory: ObjectInventory) => void;
}) {
  const pending = inventory.reviews.filter((item) => !item.decision);
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState<"save" | "suggest">();
  const [imageReady, setImageReady] = useState(false);
  const [imageFailed, setImageFailed] = useState(false);
  const [error, setError] = useState("");
  const [suggestion, setSuggestion] = useState<Suggestion>();
  const current = pending[Math.min(index, pending.length - 1)];
  const key = current?.id;

  useEffect(() => {
    setImageReady(false);
    setImageFailed(false);
    setSuggestion(undefined);
    setError("");
  }, [key]);

  if (!current) return null;
  const hits = current.detection_ids.map((id) => evidence.detections?.find((hit) => hit.id === id));
  const describe = (hit: (typeof hits)[number], tag: string) =>
    hit ? `${tag}: ${hit.label} · ${hit.view} · ${Math.round(hit.confidence * 100)}%` : `${tag}: unavailable`;

  async function decide(decision: "same" | "separate") {
    setBusy("save");
    setError("");
    try {
      onChange(await api.saveObjectMatch(sid, roomId, current.detection_ids, decision));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t save this decision.");
    } finally {
      setBusy(undefined);
    }
  }

  async function suggest() {
    setBusy("suggest");
    setError("");
    try {
      setSuggestion(await api.suggestObjectMatch(sid, roomId, current.detection_ids));
    } catch (err) {
      setError(err instanceof Error ? err.message : "The model couldn’t compare these boxes.");
    } finally {
      setBusy(undefined);
    }
  }

  return (
    <section className="duplicate-review" aria-labelledby="duplicates-title">
      <div className="duplicate-header">
        <h3 id="duplicates-title">Possible duplicates</h3>
        {pending.length > 1 && (
          <div className="pager" role="group" aria-label="Possible duplicates">
            <button type="button" aria-label="Previous" disabled={Boolean(busy)}
              onClick={() => setIndex((value) => (value - 1 + pending.length) % pending.length)}>‹</button>
            <span>{Math.min(index, pending.length - 1) + 1} of {pending.length}</span>
            <button type="button" aria-label="Next" disabled={Boolean(busy)}
              onClick={() => setIndex((value) => (value + 1) % pending.length)}>›</button>
          </div>
        )}
      </div>
      <p>Are A and B the same physical object? The view joins neighbouring photos, so an object split across two of
        them looks continuous. Found because {current.reason}.</p>
      <div className="duplicate-image">
        {!imageFailed && (
          <img key={key} src={api.objectViewUrl(sid, roomId, current.detection_ids)} alt={`${describe(hits[0], "A")}, ${describe(hits[1], "B")}`}
            onLoad={() => setImageReady(true)} onError={() => setImageFailed(true)} />
        )}
        {!imageReady && !imageFailed && <Spinner overlay size="small" label="Drawing the view" />}
        {imageFailed && <p role="alert">The view couldn’t be drawn. Refresh the room and try again.</p>}
      </div>
      <ul className="duplicate-legend">
        <li><span className="swatch swatch-a" aria-hidden="true" />{describe(hits[0], "A")}</li>
        <li><span className="swatch swatch-b" aria-hidden="true" />{describe(hits[1], "B")}</li>
      </ul>
      <div className="interior-controls">
        <button type="button" className="primary" disabled={Boolean(busy)} onClick={() => void decide("same")}>Same object</button>
        <button type="button" disabled={Boolean(busy)} onClick={() => void decide("separate")}>Separate objects</button>
        {evidence.can_suggest_match && (
          <button type="button" disabled={Boolean(busy)} onClick={() => void suggest()}>Ask the model</button>
        )}
      </div>
      {busy && <Spinner size="small" label={busy === "save" ? "Saving" : "The model is comparing the boxes"} />}
      {suggestion && (
        <p role="status" className="suggestion">
          {suggestion.model ?? "The model"} suggests <strong>{suggestion.decision === "same" ? "same object" :
            suggestion.decision === "separate" ? "separate objects" : "unsure"}</strong>. {suggestion.reason}
        </p>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
