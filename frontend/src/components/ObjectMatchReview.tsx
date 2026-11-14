import { useState } from "react";
import { api, type MatchDecision, type ObjectEvidence, type ObjectInventory, type ObjectPair } from "../api";
import EvidenceImage from "./EvidenceImage";

type Hit = NonNullable<ObjectEvidence["detections"]>[number];

export default function ObjectMatchReview({ sid, roomId, evidence, inventory, onChange }: {
  sid: string;
  roomId: string;
  evidence: ObjectEvidence;
  inventory: ObjectInventory;
  onChange: (inventory: ObjectInventory) => void;
}) {
  const [selected, setSelected] = useState("");
  const [manualPair, setManualPair] = useState<ObjectPair>(["", ""]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [suggestion, setSuggestion] = useState<Awaited<ReturnType<typeof api.suggestObjectMatch>>>();
  const detections = evidence.detections ?? [];
  const pending = inventory.reviews.filter((item) => !item.decision).length;
  const review = inventory.reviews.find((item) => item.id === selected) ?? inventory.reviews[0];
  const pair = selected === "manual" ? manualPair : review?.detection_ids;
  const [first, second] = (pair ?? []).map((id) => detections.find((hit) => hit.id === id));
  const validPair = pair && first && second && first.id !== second.id;
  const decision = selected === "manual"
    ? inventory.reviews.find((item) => pair?.every((id) => item.detection_ids.includes(id)))?.decision
    : review?.decision;

  function clearFeedback() {
    setError("");
    setSuggestion(undefined);
  }

  async function submit(value?: MatchDecision) {
    if (!pair || !validPair || busy) return;
    setBusy(true);
    clearFeedback();
    try {
      if (value) {
        const updated = await api.saveObjectMatch(sid, roomId, pair, value);
        setSelected(updated.reviews.find((item) => item.detection_ids.every((id) => pair.includes(id)))?.id
          ?? updated.reviews[0]?.id ?? "manual");
        onChange(updated);
      } else {
        setSuggestion(await api.suggestObjectMatch(sid, roomId, pair));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t review this match.");
    } finally {
      setBusy(false);
    }
  }

  function describe(hit?: Hit) {
    return hit ? `${hit.label} · ${hit.view} · ${Math.round(hit.confidence * 100)}%` : "Detection unavailable";
  }

  function preview(hit: Hit) {
    const view = evidence.views?.find((item) => item.name === hit.view);
    return (
      <div>
        <strong>{describe(hit)}</strong>
        {view && evidence.image_url && evidence.image_width && evidence.image_height && (
          <EvidenceImage src={evidence.image_url} width={evidence.image_width} height={evidence.image_height}
            viewport={view.viewport} label={describe(hit)} boxes={[{ ...hit, box_px: hit.sheet_box_px }]} />
        )}
      </div>
    );
  }

  return (
    <details className="object-match-review">
      <summary>{pending ? `Review possible duplicates (${pending})` : "Review object matches"}</summary>
      <label>Detections to compare{" "}
        <select value={selected === "manual" ? "manual" : review?.id ?? "manual"} disabled={busy}
          onChange={(event) => { setSelected(event.target.value); clearFeedback(); }}>
          {inventory.reviews.map((item) => (
            <option key={item.id} value={item.id}>
              {item.detection_ids.map((id) => describe(detections.find((hit) => hit.id === id))).join(" / ")}
              {item.decision ? ` (${item.decision === "same" ? "same object" : "separate objects"})` : ""}
            </option>
          ))}
          <option value="manual">Choose two detections</option>
        </select>
      </label>
      {(selected === "manual" || !review) && [0, 1].map((slot) => (
        <label key={slot}>Detection {slot + 1}{" "}
          <select value={manualPair[slot]} disabled={busy} onChange={(event) => {
            const next: ObjectPair = [...manualPair];
            next[slot] = event.target.value;
            setSelected("manual");
            setManualPair(next);
            clearFeedback();
          }}>
            <option value="">Choose a detection</option>
            {detections.map((hit) => <option key={hit.id} value={hit.id}>{describe(hit)}</option>)}
          </select>
        </label>
      ))}
      {validPair && (
        <>
          <div className="object-match-images">{preview(first)}{preview(second)}</div>
          {decision && <p>Saved as {decision === "same" ? "the same object" : "separate objects"}.</p>}
          <div className="interior-controls">
            <button disabled={busy} onClick={() => void submit("same")}>Same object</button>
            <button disabled={busy} onClick={() => void submit("separate")}>Separate objects</button>
            {decision && <button disabled={busy} onClick={() => void submit("reset")}>Undo decision</button>}
            {evidence.can_suggest_match && !decision && (
              <button disabled={busy} onClick={() => void submit()}>Ask model to compare crops</button>
            )}
          </div>
          {busy && <p role="status">Working…</p>}
          {suggestion && <p role="status">{suggestion.model ?? "The model"} suggests {suggestion.decision === "same" ? "same object" :
            suggestion.decision === "separate" ? "separate objects" : "unsure"}. {suggestion.reason}</p>}
          {error && <p role="alert">{error}</p>}
        </>
      )}
    </details>
  );
}
