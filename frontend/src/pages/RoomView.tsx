import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type AcousticDetails } from "../api";
import EvidenceImage from "../components/EvidenceImage";
import ObjectMatchReview from "../components/ObjectMatchReview";
import RoomReview from "../components/RoomReview";
import RoomSound from "../components/RoomSound";
import { useRequest } from "../useRequest";

function Dimensions({ dimensions }: { dimensions: NonNullable<AcousticDetails["dimensions"]> }) {
  const metrics = [
    ["Length", dimensions.length_m, "m"], ["Width", dimensions.width_m, "m"],
    ["Ceiling height", dimensions.height_m, "m"], ["Floor area", dimensions.area_m2 === null ? null : Math.round(dimensions.area_m2 * 10.7639104), "ft²"],
    ["Volume", dimensions.volume_m3, "m³"],
  ] as const;
  const heightNotes = {
    matterport: "Ceiling height comes from Matterport's scan dimensions.",
    assumed: "Ceiling height is assumed; the volume uses that assumption.",
    point_cloud_estimate: "Ceiling height is estimated from the point cloud.",
    floor_point_cloud_estimate: "Ceiling height uses the floor-wide point cloud estimate.",
  };
  return (
    <section className="details-panel" aria-labelledby="dimensions-title">
      <h2 id="dimensions-title">Room dimensions</h2>
      <dl className="metrics">
        {metrics.map(([label, value, unit]) => value !== null && (
          <div key={label}><dt>{label}</dt><dd>{value} <span>{unit}</span></dd></div>
        ))}
      </dl>
      <p>Length and width span the outline from {dimensions.footprint_source === "matterport" ? "Matterport" : "the point cloud"}.
        {" "}Floor area is an estimate from the scan. {heightNotes[dimensions.height_source]}</p>
    </section>
  );
}

function PanoramaFace({ evidence, view, boxes, activeBox, onBoxPreview, onBoxSelect }: {
  evidence: AcousticDetails["object_evidence"];
  view: NonNullable<AcousticDetails["object_evidence"]["views"]>[number];
  boxes: NonNullable<AcousticDetails["object_evidence"]["detections"]>;
  activeBox: number;
  onBoxPreview: (index?: number) => void;
  onBoxSelect: (index: number) => void;
}) {
  const [photoStatus, setPhotoStatus] = useState<"loading" | "ready" | "unavailable">("loading");
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
    <>
      <EvidenceImage src={original || evidence.image_url!}
        width={original ? size : evidence.image_width!} height={original ? size : evidence.image_height!}
        viewport={original ? undefined : view.viewport} label={`Matterport panorama · ${view.name}`}
        boxes={boxes.map((hit) => ({ ...hit, box_px: original ? hit.box_px : hit.sheet_box_px }))}
        activeBox={activeBox} onBoxPreview={onBoxPreview} onBoxSelect={onBoxSelect} />
      {view.photo_url && photoStatus === "loading" && <p role="status">Loading full-resolution photo…</p>}
      {original && <p><a href={original} target="_blank" rel="noreferrer">Open original photo ↗</a></p>}
      {photoStatus === "unavailable" && <p>Full-resolution photo unavailable. Showing the thumbnail.</p>}
    </>
  );
}

function RoomInterior({ sid, roomId, evidence }: { sid: string; roomId: string; evidence: AcousticDetails["object_evidence"] }) {
  const [selectedView, setSelectedView] = useState<string>();
  const [selectedDetection, setSelectedDetection] = useState<number>();
  const [previewDetection, setPreviewDetection] = useState<number>();
  const [showBoxes, setShowBoxes] = useState(true);
  const [inventory, setInventory] = useState(evidence.inventory);
  const listRef = useRef<HTMLUListElement>(null);
  const views = evidence.views ?? [];
  const detections = evidence.detections ?? [];
  const firstWallWithDetection = detections.find((hit) => !hit.needs_review && hit.view.startsWith("Wall"))?.view;
  const view = views.find((item) => item.name === (selectedView ?? firstWallWithDetection ?? "Wall 1")) ?? views[0];
  const visibleHits = detections.map((hit, index) => ({ hit, index }))
    .filter(({ hit }) => hit.view === view?.name);
  const activeDetection = previewDetection ?? selectedDetection;
  const detectionIndices = new Map(detections.map((hit, index) => [hit.id, index]));
  const groupedRows = inventory?.groups.map((group) => ({
    ...group, indices: group.detection_ids.flatMap((id) => {
      const index = detectionIndices.get(id);
      return index === undefined ? [] : [index];
    }),
  }));
  const unresolved = groupedRows?.some((group) => group.status === "needs_match");
  const estimated = groupedRows?.filter((group) => group.status === "estimated").length;

  function revealDetection(index: number) {
    const list = listRef.current;
    const row = list?.querySelector(`[data-detection-index="${index}"]`);
    if (!list || !(row instanceof HTMLElement)) return;
    const bounds = list.getBoundingClientRect();
    const item = row.getBoundingClientRect();
    if (item.top < bounds.top) list.scrollTop += item.top - bounds.top;
    if (item.bottom > bounds.bottom) list.scrollTop += item.bottom - bounds.bottom;
  }

  function detectionButton(index: number) {
    const hit = detections[index];
    return (
      <button key={index} type="button" data-detection-index={index} aria-pressed={selectedDetection === index}
        className={activeDetection === index ? "detection-current" : undefined} onClick={() => {
          setSelectedView(hit.view);
          setSelectedDetection(index);
          setPreviewDetection(undefined);
          setShowBoxes(true);
        }}>
        <strong>{hit.label}</strong>
        <span>{hit.view} · {Math.round(hit.confidence * 100)}% model score{hit.needs_review && " · review"}</span>
      </button>
    );
  }

  return (
    <section className="details-panel room-interior" aria-labelledby="interior-title">
      <h2 id="interior-title">Room interior</h2>
      {view && evidence.image_url && evidence.image_width && evidence.image_height ? (
        <div className="interior-layout">
          <div>
            <div className="interior-controls" role="group" aria-label="Panorama views">
              {views.map(({ name }) => (
                <button key={name} type="button" aria-pressed={view.name === name} onClick={() => {
                  setSelectedView(name);
                  setSelectedDetection(undefined);
                  setPreviewDetection(undefined);
                }}>{name}</button>
              ))}
            </div>
            <PanoramaFace key={view.name} evidence={evidence} view={view}
              boxes={showBoxes ? visibleHits.map(({ hit }) => hit) : []}
              activeBox={visibleHits.findIndex(({ index }) => index === activeDetection)}
              onBoxPreview={(index) => {
                const detection = index === undefined ? undefined : visibleHits[index]?.index;
                setPreviewDetection(detection);
                if (detection !== undefined) revealDetection(detection);
              }}
              onBoxSelect={(index) => {
                const detection = visibleHits[index].index;
                setSelectedDetection(detection);
                revealDetection(detection);
              }} />
            {detections.length > 0 && (
              <label className="interior-overlay">
                <input type="checkbox" checked={showBoxes} onChange={(event) => {
                  setShowBoxes(event.target.checked);
                  setPreviewDetection(undefined);
                }} />
                Show detection boxes
              </label>
            )}
          </div>
          <div>
            <h3>Detected objects</h3>
            {detections.length > 0 ? (
              <>
                {inventory && <p>{unresolved
                  ? `${estimated} estimated objects outside matches that need review. Resolve the matches to see a room estimate.`
                  : `${estimated} estimated objects. Groups with only low scores are excluded.`}</p>}
                <p>Hover over a box or select a detection to match it with its label.</p>
                <ul className="object-detections" ref={listRef}>
                  {groupedRows ? groupedRows.map(({ id, label, status, indices }) => (
                    <li className="object-group" key={id}>
                      <div><strong>{label}</strong> · {new Set(indices.map((i) => detections[i].view)).size} view(s)
                        {status === "needs_match" ? " · possible duplicate" : status === "low_score" ? " · low score" : ""}</div>
                      {indices.map(detectionButton)}
                    </li>
                  )) : detections.map((_, index) => <li key={index}>{detectionButton(index)}</li>)}
                </ul>
              </>
            ) : <p>{{
              complete: "YOLO found no detections above the minimum score.",
              pending: "Run image analysis from the building page to look for objects.",
              unavailable: "Object detection is unavailable for this room.",
              failed: "Object detection could not run. You can retry from the building page.",
            }[evidence.status]}</p>}
            <p>These six views come from one camera position. Objects can be hidden or appear in more than one view.</p>
          </div>
        </div>
      ) : <p>No interior photos are available for this room.</p>}
      {inventory && detections.length > 1 && (
        <ObjectMatchReview sid={sid} roomId={roomId} evidence={evidence} inventory={inventory} onChange={setInventory} />
      )}
    </section>
  );
}

function Room({ sid, roomId }: { sid: string; roomId: string }) {
  const load = useCallback(() => api.acoustics(sid, roomId), [sid, roomId]);
  const { state, retry } = useRequest(load);
  const [reviewed, setReviewed] = useState<AcousticDetails>();
  const [reviewCount, setReviewCount] = useState(0);
  const details = state.status === "ready" ? reviewed ?? state.data : undefined;

  return (
    <main>
      <Link className="back-link" to={`/b/${encodeURIComponent(sid)}`}>← Back to floor plan</Link>
      {state.status === "loading" && <p role="status">Loading room…</p>}
      {state.status === "error" && <p role="alert">Couldn’t load the room. <button onClick={retry}>Try again</button></p>}
      {details && (
        <>
          <h1>{details.room.type || roomId.toUpperCase()}</h1>
          <p className="intro">{details.room.verdict}</p>
          <RoomInterior key={reviewCount} sid={sid} roomId={roomId} evidence={details.object_evidence} />
          <RoomReview sid={sid} roomId={roomId} details={details} onSave={(result) => {
            setReviewed(result);
            setReviewCount((count) => count + 1);
          }} />
          {details.dimensions && <Dimensions dimensions={details.dimensions} />}
          <RoomSound key={reviewCount} sid={sid} roomId={roomId} details={details} />
        </>
      )}
    </main>
  );
}

export default function RoomView() {
  const { sid = "", rid = "" } = useParams();
  return <Room key={`${sid}/${rid}`} sid={sid} roomId={rid} />;
}
