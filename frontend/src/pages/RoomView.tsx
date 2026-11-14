import { useCallback } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useRequest } from "../useRequest";

function Room({ sid, roomId }: { sid: string; roomId: string }) {
  const load = useCallback(() => api.acoustics(sid, roomId), [sid, roomId]);
  const { state, retry } = useRequest(load);

  return (
    <main>
      <Link className="back-link" to={`/b/${encodeURIComponent(sid)}`}>← Back to floor plan</Link>
      {state.status === "loading" && <p role="status">Loading room…</p>}
      {state.status === "error" && <p role="alert">Couldn’t load the room. <button onClick={retry}>Try again</button></p>}
      {state.status === "ready" && (
        <>
          <h1>{state.data.room.type || roomId.toUpperCase()}</h1>
          <p className="intro">{state.data.room.verdict}</p>
          <section className="details-panel" aria-labelledby="echo-title">
            <h2 id="echo-title">Estimated echo time</h2>
            <dl className="metrics">
              {state.data.bands_hz.map((band, index) => (
                <div key={band}>
                  <dt>{Number(band) >= 1000 ? `${Number(band) / 1000} kHz` : `${band} Hz`}</dt>
                  <dd>{state.data.room.rt60[index].toFixed(2)} <span>s</span></dd>
                </div>
              ))}
            </dl>
          </section>
        </>
      )}
    </main>
  );
}

export default function RoomView() {
  const { sid = "", rid = "" } = useParams();
  return <Room key={`${sid}/${rid}`} sid={sid} roomId={rid} />;
}
