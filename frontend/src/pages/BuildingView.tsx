import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Surroundings as SurroundingsEvidence } from "../api";
import BuildingAnalysis from "../components/BuildingAnalysis";
import EvidenceImage from "../components/EvidenceImage";
import FloorPlan from "../components/FloorPlan";
import { useRequest } from "../useRequest";

function Surroundings({ evidence }: { evidence: SurroundingsEvidence }) {
  const boxes = evidence.detections ?? [];
  const review = boxes.filter((hit) => hit.needs_review).length;
  return (
    <section className="details-panel evidence-panel" aria-labelledby="surroundings-title">
      <h2 id="surroundings-title">Buildings in the aerial image</h2>
      {evidence.status === "complete" && (
        <p>YOLO found {boxes.length - review} possible roofs
          {review ? ` and ${review} lower confidence candidates` : ""} in the Vexcel image. These are preliminary detections.</p>
      )}
      {evidence.status === "unavailable" && <p>Vexcel aerial imagery is unavailable for this scan.</p>}
      {evidence.status === "failed" && <p>Aerial detection could not run. You can retry image analysis.</p>}
      {evidence.mapped_buildings !== null && <p>OpenStreetMap lists {evidence.mapped_buildings} building outlines in this area.</p>}
      {evidence.image_url && evidence.width && evidence.height && (
        <details>
          <summary>Show aerial image and roof candidates</summary>
          <EvidenceImage src={evidence.image_url} width={evidence.width} height={evidence.height}
            label="Vexcel aerial image with solid boxes for roof candidates and dashed boxes for lower scores"
            boxes={boxes} />
        </details>
      )}
    </section>
  );
}

function Building({ sid }: { sid: string }) {
  const [activeRoom, setActiveRoom] = useState<string>();
  const load = useCallback(async () => {
    const building = await api.building(sid);
    const [geometry, surroundings] = building.analysed
      ? await Promise.all([api.rooms(sid), api.surroundings(sid)])
      : [null, null];
    return { building, geometry, surroundings };
  }, [sid]);
  const { state, retry } = useRequest(load);
  const roomPath = (roomId: string) => `/b/${encodeURIComponent(sid)}/r/${encodeURIComponent(roomId)}`;

  return (
    <main>
      <Link className="back-link" to="/">← All buildings</Link>
      {state.status === "loading" && <p role="status">Loading building…</p>}
      {state.status === "error" && <p role="alert">Couldn’t load the building. <button onClick={retry}>Try again</button></p>}
      {state.status === "ready" && (() => {
        const { building, geometry, surroundings } = state.data;
        return (
          <>
            <h1>{building.name || building.address || sid}</h1>
            {building.name && building.address && building.name !== building.address && (
              <p className="intro">{building.address}</p>
            )}
            {geometry && geometry.rooms.length > 0 ? (
              <div className="room-layout">
                <section className="plan-panel" aria-labelledby="plan-title">
                  <h2 id="plan-title">Floor plan</h2>
                  {geometry.floorplan ? (
                    <FloorPlan floorplan={geometry.floorplan} rooms={geometry.rooms} roomPath={roomPath}
                      activeRoom={activeRoom} onRoomPreview={setActiveRoom} />
                  ) : <p>Floor plan unavailable. Choose a room from the list.</p>}
                </section>
                <section className="rooms-panel" aria-labelledby="rooms-title">
                  <h2 id="rooms-title">Choose a room</h2>
                  <ul className="room-list">
                    {geometry.rooms.map((room) => (
                      <li key={room.id}>
                        <Link to={roomPath(room.id)} className={activeRoom === room.id ? "room-current" : undefined}
                          onPointerEnter={() => setActiveRoom(room.id)} onPointerLeave={() => setActiveRoom(undefined)}
                          onFocus={() => setActiveRoom(room.id)} onBlur={() => setActiveRoom(undefined)}>
                          <span className="room-list-marker" aria-label={`Room ${room.id.toUpperCase()}`}>{room.id.toUpperCase()}</span>
                          <span className="room-list-info"><strong>{room.label}</strong><small>{room.area_m2} m²</small></span>
                          <span aria-hidden="true">→</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </section>
              </div>
            ) : (
              <BuildingAnalysis sid={sid} initialJobId={building.analysis_job_id} onReady={retry} />
            )}
            {geometry && building.vision_pending && (
              <BuildingAnalysis sid={sid} initialJobId={building.analysis_job_id} onReady={retry} visionOnly />
            )}
            {surroundings && surroundings.status !== "pending" && <Surroundings evidence={surroundings} />}
          </>
        );
      })()}
    </main>
  );
}

export default function BuildingView() {
  const { sid = "" } = useParams();
  return <Building key={sid} sid={sid} />;
}
