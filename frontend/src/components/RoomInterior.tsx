import { useEffect, useMemo, useState } from "react";
import { api, type AcousticDetails, type ObjectGroup } from "../api";
import DuplicateReview from "./DuplicateReview";
import EvidenceImage, { type EvidenceBox } from "./EvidenceImage";
import Spinner from "./Spinner";

type Evidence = AcousticDetails["object_evidence"];
type View = NonNullable<Evidence["views"]>[number];
type FaceBox = EvidenceBox & { sheet_box_px: EvidenceBox["box_px"] };   // box_px on the face, sheet_box_px on the contact sheet

// One colour per object, so the same object is easy to follow from one view to the next.
const COLORS = ["#e8590c", "#1c7ed6", "#2f9e44", "#c2255c", "#7048e8", "#f08c00", "#0c8599", "#5c940d"];

function PanoramaFace({ evidence, view, boxes, activeBox, onBoxPreview, onBoxSelect }: {
  evidence: Evidence;
  view: View;
  boxes: FaceBox[];
  activeBox: number;
  onBoxPreview: (index?: number) => void;
  onBoxSelect: (index: number) => void;
}) {
  const [photoStatus, setPhotoStatus] = useState<"loading" | "ready" | "unavailable">(view.photo_url ? "loading" : "unavailable");
  useEffect(() => {
    if (!view.photo_url) return;
    const image = new Image();
    image.onload = () => setPhotoStatus("ready");
    image.onerror = () => setPhotoStatus("unavailable");
    image.src = view.photo_url;
    return () => { image.onload = null; image.onerror = null; };
  }, [view.photo_url]);

  const size = view.viewport[2];
  const original = photoStatus === "ready" && view.photo_url;
  return (
    <div className="face-frame">
      <EvidenceImage src={original || evidence.image_url!}
        width={original ? size : evidence.image_width!} height={original ? size : evidence.image_height!}
        viewport={original ? undefined : view.viewport} label={`Matterport panorama · ${view.name}`}
        boxes={boxes.map((box) => ({ ...box, box_px: original ? box.box_px : box.sheet_box_px }))}
        activeBox={activeBox} onBoxPreview={onBoxPreview} onBoxSelect={onBoxSelect} />
      {photoStatus === "loading" && <Spinner overlay size="small" label="Loading full-resolution photo" />}
      <p className="face-caption">
        {original ? <a href={original} target="_blank" rel="noreferrer">Open original photo ↗</a>
          : photoStatus === "unavailable" ? "Showing the thumbnail." : " "}
      </p>
    </div>
  );
}

export default function RoomInterior({ sid, roomId, evidence, onWindowReview }: {
  sid: string; roomId: string; evidence: Evidence; onWindowReview: () => void;
}) {
  const [inventory, setInventory] = useState(evidence.inventory);
  const [selectedView, setSelectedView] = useState<string>();
  const [picked, setPicked] = useState<string[]>([]);
  const [focused, setFocused] = useState<string>();
  const [hovered, setHovered] = useState<string>();
  const [showBoxes, setShowBoxes] = useState(true);
  const [showLow, setShowLow] = useState(false);
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const views = evidence.views ?? [];
  const detections = evidence.detections ?? [];
  const groups = inventory?.groups ?? [];
  const groupOf = useMemo(() => new Map(groups.flatMap((group) => group.detection_ids.map((id) => [id, group] as const))), [groups]);
  const colorOf = useMemo(() => new Map(groups.map((group, index) => [group.id, COLORS[index % COLORS.length]])), [groups]);
  const confident = groups.filter((group) => group.status !== "low_score");
  const lowScore = groups.filter((group) => group.status === "low_score");

  const firstView = confident[0]?.views.find((name) => name.startsWith("Wall")) ?? confident[0]?.views[0] ?? "Wall 1";
  const view = views.find((item) => item.name === (selectedView ?? firstView)) ?? views[0];
  const activeGroup = hovered ?? focused;
  const boxes = detections
    .filter((hit) => hit.view === view?.name)
    .filter((hit) => {
      const group = groupOf.get(hit.id);
      return showLow || !group || group.status !== "low_score" || picked.includes(group.id) || focused === group.id;
    })
    .map((hit) => {
      const group = groupOf.get(hit.id);
      return { ...hit, color: group && colorOf.get(group.id), selected: Boolean(group && picked.includes(group.id)), tag: group?.label };
    });

  function togglePick(groupId: string) {
    setPicked((current) => current.includes(groupId) ? current.filter((id) => id !== groupId) : [...current, groupId]);
  }

  async function change(action: "keep" | "merge" | "split", ids: string[]) {
    const updates = { keep: api.keepObjects, merge: api.mergeObjects, split: api.splitObjects };
    setBusy("Updating objects");
    setError("");
    setNotice("");
    try {
      const updated = await updates[action](sid, roomId, ids);
      setInventory(updated);
      setPicked([]);
      setFocused(updated.groups.find((group) => group.detection_ids.includes(ids[0]))?.id);
      setNotice({ keep: "Added to the object list.", merge: "Merged into one object.", split: "Detections split." }[action]);
      if (detections.some((hit) => hit.label.toLowerCase() === "window" && hit.needs_review && ids.includes(hit.id))) {
        onWindowReview();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t update the objects.");
    } finally {
      setBusy(undefined);
    }
  }

  function row(group: ObjectGroup) {
    const isPicked = picked.includes(group.id);
    const boxCount = group.detection_ids.length;
    return (
      <li key={group.id} className={`object-row${isPicked ? " picked" : ""}${activeGroup === group.id ? " active" : ""}`}
        onMouseEnter={() => setHovered(group.id)} onMouseLeave={() => setHovered(undefined)}>
        <input type="checkbox" checked={isPicked} disabled={Boolean(busy)} onChange={() => togglePick(group.id)}
          aria-label={`Select ${group.label}`} />
        <span className="object-dot" style={{ background: colorOf.get(group.id) }} aria-hidden="true" />
        <button type="button" className="object-main" onClick={() => {
          setFocused(group.id);
          if (!group.views.includes(view?.name ?? "")) setSelectedView(group.views[0]);
        }}>
          <strong>{group.label}</strong>
          <span>{group.views.join(" + ")} · {Math.round(group.confidence * 100)}%
            {boxCount > 1 && ` · ${boxCount} boxes`}{group.confirmed && " · confirmed"}
            {group.status === "needs_match" && " · possible duplicate"}</span>
        </button>
        {boxCount > 1 && (
          <button type="button" className="text-button" disabled={Boolean(busy)}
            onClick={() => void change("split", group.detection_ids)}>Split</button>
        )}
      </li>
    );
  }

  if (!view || !evidence.image_url || !evidence.image_width || !evidence.image_height) {
    return (
      <section className="details-panel room-interior" aria-labelledby="interior-title">
        <h2 id="interior-title">Room interior</h2>
        <p>No interior photos are available for this room.</p>
      </section>
    );
  }

  const pickedDetections = picked.flatMap((id) => groups.find((group) => group.id === id)?.detection_ids ?? []);
  const pickedLow = lowScore.filter((group) => picked.includes(group.id));
  return (
    <section className="details-panel room-interior" aria-labelledby="interior-title">
      <h2 id="interior-title">Room interior</h2>
      <p className="panel-note">Matterport panorama faces from one scan position. Boxes come from{" "}
        <a className="source-link" href="https://docs.ultralytics.com/models/yolo-world/" target="_blank" rel="noreferrer">YOLO-World</a>
        {evidence.model && ` (${evidence.model})`}. One object can appear in two neighbouring photos.</p>
      <div className="interior-layout">
        <div>
          <div className="interior-controls view-tabs" role="group" aria-label="Panorama views">
            {views.map(({ name }) => {
              const count = confident.filter((group) => group.views.includes(name)).length;
              return (
                <button key={name} type="button" aria-pressed={view.name === name} onClick={() => {
                  setSelectedView(name);
                  setFocused(undefined);
                }}>{name}{count > 0 && <span className="tab-count">{count}</span>}</button>
              );
            })}
          </div>
          <PanoramaFace key={view.name} evidence={evidence} view={view} boxes={showBoxes ? boxes : []}
            activeBox={showBoxes ? boxes.findIndex((box) => groupOf.get(box.id)?.id === activeGroup) : -1}
            onBoxPreview={(index) => setHovered(index === undefined ? undefined : groupOf.get(boxes[index].id)?.id)}
            onBoxSelect={(index) => {
              const group = groupOf.get(boxes[index].id);
              if (group && !busy) togglePick(group.id);
            }} />
          {detections.length > 0 && (
            <div className="viewer-options">
              <label><input type="checkbox" checked={showBoxes} onChange={(event) => setShowBoxes(event.target.checked)} /> Show boxes</label>
              {lowScore.length > 0 && (
                <label><input type="checkbox" checked={showLow} onChange={(event) => setShowLow(event.target.checked)} /> Show low-score boxes</label>
              )}
            </div>
          )}
        </div>
        <div className="object-panel">
          <h3>Objects{inventory && ` (${confident.length})`}</h3>
          {detections.length === 0 ? (
            <p>{{
              complete: "YOLO found no detections above the minimum score.",
              pending: "Run image analysis from the building page to look for objects.",
              unavailable: "Object detection is unavailable for this room.",
              failed: "Object detection could not run. You can retry from the building page.",
            }[evidence.status]}</p>
          ) : (
            <>
              <p className="panel-note">Select boxes or list entries to merge detections of the same object.</p>
              {picked.length > 0 && (
                <div className="merge-bar">
                  <span>{picked.length} selected</span>
                  {pickedLow.length > 0 && (
                    <button type="button" disabled={Boolean(busy)}
                      onClick={() => void change("keep", pickedLow.flatMap((group) => group.detection_ids))}>
                      {pickedLow.length === 1 ? "Keep as an object" : "Keep as separate objects"}
                    </button>
                  )}
                  <button type="button" className="primary" disabled={picked.length < 2 || Boolean(busy)}
                    onClick={() => void change("merge", pickedDetections)}>Merge into one object</button>
                  <button type="button" disabled={Boolean(busy)} onClick={() => setPicked([])}>Clear</button>
                </div>
              )}
              {busy && <Spinner size="small" label={busy} />}
              {error && <p role="alert">{error}</p>}
              {notice && <p role="status">{notice}</p>}
              <ul className="object-list">{confident.map(row)}</ul>
              {lowScore.length > 0 && (
                <details className="low-score">
                  <summary>Low-score detections ({lowScore.length})</summary>
                  <p className="panel-note">Select valid detections to add them to the object list or merge duplicate boxes.</p>
                  <ul className="object-list">{lowScore.map(row)}</ul>
                </details>
              )}
            </>
          )}
        </div>
      </div>
      {inventory && <DuplicateReview sid={sid} roomId={roomId} evidence={evidence} inventory={inventory} onChange={setInventory} />}
    </section>
  );
}
