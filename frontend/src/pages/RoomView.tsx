import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type AcousticDetails } from "../api";
import RoomInterior from "../components/RoomInterior";
import RoomReview from "../components/RoomReview";
import RoomSound from "../components/RoomSound";
import { LoadingBlock } from "../components/Spinner";
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

function Room({ sid, roomId }: { sid: string; roomId: string }) {
  const load = useCallback(() => api.acoustics(sid, roomId), [sid, roomId]);
  const { state, retry } = useRequest(load);
  const [reviewed, setReviewed] = useState<AcousticDetails>();
  const [reviewCount, setReviewCount] = useState(0);
  const details = state.status === "ready" ? reviewed ?? state.data : undefined;

  return (
    <main className="room-page">
      <Link className="back-link" to={`/b/${encodeURIComponent(sid)}`}>← Back to floor plan</Link>
      {state.status === "loading" && <LoadingBlock label="Loading room" />}
      {state.status === "error" && <p role="alert">Couldn’t load the room. <button onClick={retry}>Try again</button></p>}
      {details && (
        <>
          <h1>{details.room.type || roomId.toUpperCase()}</h1>
          <p className="intro">{details.room.verdict}</p>
          <div className="room-panels">
            <RoomInterior key={reviewCount} sid={sid} roomId={roomId} evidence={details.object_evidence} />
            <RoomReview sid={sid} roomId={roomId} details={details} onSave={(result) => {
              setReviewed(result);
              setReviewCount((count) => count + 1);
            }} />
            {details.dimensions && <Dimensions dimensions={details.dimensions} />}
            <RoomSound key={`${details.room.floor}/${details.room.walls}/${details.room.ceiling}`}
              sid={sid} roomId={roomId} details={details} />
          </div>
        </>
      )}
    </main>
  );
}

export default function RoomView() {
  const { sid = "", rid = "" } = useParams();
  return <Room key={`${sid}/${rid}`} sid={sid} roomId={rid} />;
}
