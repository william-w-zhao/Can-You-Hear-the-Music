import type { AcousticDetails, BuildingRooms, RoomAcoustics } from "../api";
import EchoChart from "./EchoChart";
import LoadState from "./LoadState";

function RoomCard({
  room,
  details,
  label,
}: {
  room: RoomAcoustics;
  details: AcousticDetails;
  label: string;
}) {
  return (
    <div className="comparison-card">
      <div className="eyebrow">{label}</div>
      <h3>{room.type}</h3>
      <span className="badge ready">{room.verdict}</span>
      <p className="comparison-value">
        {room.rt60[1].toFixed(2)} <small>s RT60</small>
      </p>
      <p className="muted">
        500 Hz · range {room.rt60_range_500.map((n) => n.toFixed(2)).join("–")}{" "}
        s
      </p>
      <dl>
        {(["floor", "ceiling", "walls"] as const).map((field) => (
          <div key={field}>
            <dt>{field}</dt>
            <dd>{details.material_options[room[field]] ?? room[field]}</dd>
          </div>
        ))}
        <div>
          <dt>Furnishing</dt>
          <dd>{room.furnishing.replaceAll("_", " ")}</dd>
        </div>
      </dl>
    </div>
  );
}

export default function RoomComparison({
  baseline,
  other,
  plan,
  rid,
  selected,
  onSelect,
  error,
  retry,
}: {
  baseline: AcousticDetails;
  other?: AcousticDetails | null;
  plan: BuildingRooms;
  rid: string;
  selected: string;
  onSelect: (value: string) => void;
  error?: string;
  retry: () => void;
}) {
  const delta = other ? other.room.rt60[1] - baseline.room.rt60[1] : 0;
  return (
    <section
      className="panel room-comparison"
      aria-labelledby="comparison-title"
    >
      <div className="eyebrow">ROOM TO ROOM</div>
      <div className="comparison-heading">
        <div>
          <h2 id="comparison-title">A better space for the conversation?</h2>
          <p>
            Compare the original scan of this room with another room in the same
            building.
          </p>
        </div>
        <label>
          Compare with another room
          <select value={selected} onChange={(e) => onSelect(e.target.value)}>
            <option value="">Choose a second room</option>
            {plan.rooms
              .filter((r) => r.id !== rid)
              .map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label} ({r.id})
                </option>
              ))}
          </select>
        </label>
      </div>
      {!selected ? (
        <div className="comparison-empty">
          <span aria-hidden="true">↔</span>
          <p>
            {plan.rooms.length > 1
              ? "Choose a second room to see echo, material and listening comparisons."
              : "This scan has one room. Room-to-room comparison needs another analysed room."}
          </p>
        </div>
      ) : !other ? (
        <LoadState error={error} retry={retry} />
      ) : (
        <>
          <div className="comparison-pair">
            <RoomCard
              room={baseline.room}
              details={baseline}
              label="A / SELECTED ROOM"
            />
            <RoomCard
              room={other.room}
              details={other}
              label="B / COMPARISON ROOM"
            />
          </div>
          <div className="difference" role="status">
            <strong>
              {Math.abs(delta).toFixed(2)} s{" "}
              {delta < 0 ? "less" : delta > 0 ? "more" : "difference in"} echo
              at 500 Hz
            </strong>
            <p>
              {delta === 0
                ? "These rooms have the same nominal mid-band echo time."
                : `${other.room.type} has ${Math.abs((delta / baseline.room.rt60[1]) * 100).toFixed(0)}% ${delta < 0 ? "shorter" : "longer"} nominal decay than ${baseline.room.type}.`}{" "}
              This compares modeled echo, not background noise or sound
              isolation.
            </p>
          </div>
          <EchoChart
            baseline={baseline.room}
            scenario={other.room}
            bands={baseline.bands_hz}
          />
        </>
      )}
    </section>
  );
}
