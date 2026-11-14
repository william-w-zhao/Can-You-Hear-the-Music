import { useCallback } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import BuildingAnalysis from "../components/BuildingAnalysis";
import FloorPlan from "../components/FloorPlan";
import { useRequest } from "../useRequest";

function Building({ sid }: { sid: string }) {
  const load = useCallback(async () => {
    const building = await api.building(sid);
    const geometry = building.analysed ? await api.rooms(sid) : null;
    return { building, geometry };
  }, [sid]);
  const { state, retry } = useRequest(load);
  const roomPath = (roomId: string) => `/b/${encodeURIComponent(sid)}/r/${encodeURIComponent(roomId)}`;

  return (
    <main>
      <Link className="back-link" to="/">← All buildings</Link>
      {state.status === "loading" && <p role="status">Loading building…</p>}
      {state.status === "error" && <p role="alert">Couldn’t load the building. <button onClick={retry}>Try again</button></p>}
      {state.status === "ready" && (() => {
        const { building, geometry } = state.data;
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
                    <FloorPlan floorplan={geometry.floorplan} rooms={geometry.rooms} roomPath={roomPath} />
                  ) : <p>Floor plan unavailable. Choose a room from the list.</p>}
                </section>
                <section className="rooms-panel" aria-labelledby="rooms-title">
                  <h2 id="rooms-title">Choose a room</h2>
                  <ul className="room-list">
                    {geometry.rooms.map((room) => (
                      <li key={room.id}>
                        <Link to={roomPath(room.id)}>
                          <span><strong>{room.label}</strong><small>{room.id.toUpperCase()} · {room.area_m2} m²</small></span>
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
