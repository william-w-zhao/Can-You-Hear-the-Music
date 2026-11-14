import { useCallback, useMemo, useState } from "react";
import { api, type AcousticDetails, type RoomAcoustics } from "../api";
import { useRequest } from "../useRequest";
import Listen from "./Listen";
import WhatIf from "./WhatIf";
import Spinner from "./Spinner";

export default function RoomSound({ sid, roomId, details }: {
  sid: string;
  roomId: string;
  details: AcousticDetails;
}) {
  const [scenario, setScenario] = useState<RoomAcoustics>();
  const [compareId, setCompareId] = useState("");
  const loadRooms = useCallback(() => api.rooms(sid), [sid]);
  const loadComparison = useCallback(() => compareId ? api.acoustics(sid, compareId) : Promise.resolve(null), [sid, compareId]);
  const rooms = useRequest(loadRooms);
  const comparison = useRequest(loadComparison);
  const otherRoom = comparison.state.status === "ready" && comparison.state.data?.room.id === compareId
    ? comparison.state.data.room : undefined;
  const base = details.room;
  const choices = useMemo(() => [
    { label: "Current room", room: base },
    ...(scenario ? [{ label: "Material treatment", room: scenario }] : []),
    ...(otherRoom ? [{ label: `${otherRoom.type || otherRoom.id} · comparison room`, room: otherRoom }] : []),
  ], [base, scenario, otherRoom]);

  return (
    <>
      <section className="details-panel sound-panel" aria-labelledby="echo-title">
        <h2 id="echo-title">Estimated echo time</h2>
        <dl className="metrics">
          {details.bands_hz.map((band, index) => (
            <div key={band}>
              <dt>{Number(band) >= 1000 ? `${Number(band) / 1000} kHz` : `${band} Hz`}</dt>
              <dd>{base.rt60[index].toFixed(2)} <span>s</span></dd>
            </div>
          ))}
        </dl>
        {choices.length > 1 && (
          <table className="echo-comparison">
            <caption>Echo times in seconds</caption>
            <thead>
              <tr><th scope="col">Scenario</th>{details.bands_hz.map((band) => <th scope="col" key={band}>{band} Hz</th>)}</tr>
            </thead>
            <tbody>
              {choices.map(({ label, room }) => (
                <tr key={label}><th scope="row">{label}</th>{room.rt60.map((value, index) => <td key={index}>{value.toFixed(2)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        )}
        {rooms.state.status === "ready" && rooms.state.data.rooms.length > 1 && (
          <label className="sound-room-select">
            Compare with another room
            <select value={compareId} onChange={(event) => setCompareId(event.target.value)}>
              <option value="">Choose a room</option>
              {rooms.state.data.rooms.filter((room) => room.id !== roomId).map((room) => (
                <option key={room.id} value={room.id}>{room.label} ({room.id.toUpperCase()})</option>
              ))}
            </select>
          </label>
        )}
        {rooms.state.status === "error" && (
          <p role="alert">Couldn’t load the comparison rooms. <button onClick={rooms.retry}>Retry</button></p>
        )}
        {compareId && !otherRoom && (
          comparison.state.status === "error"
            ? <p role="alert">Couldn’t load the comparison room. <button onClick={comparison.retry}>Retry</button></p>
            : <Spinner size="small" label="Loading comparison room" />
        )}
      </section>
      <Listen choices={choices} voiceUrl={details.voice_url} />
      <WhatIf sid={sid} rid={roomId} details={details} onResult={setScenario} />
    </>
  );
}
