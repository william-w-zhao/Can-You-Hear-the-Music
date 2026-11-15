import type { RoomAcoustics } from "../api";

export default function EchoChart({
  baseline,
  scenario,
  bands,
  sourceUrl,
}: {
  baseline: RoomAcoustics;
  scenario?: RoomAcoustics;
  bands: string[];
  sourceUrl?: string;
}) {
  const max = Math.max(...baseline.rt60, ...(scenario?.rt60 ?? []), 1);
  return (
    <section className="panel">
      <div className="eyebrow">THE DECAY</div>
      <h2>How long does sound linger?</h2>
      <p>
        RT60 is the time for sound to decay by 60 dB. Lower values mean less
        echo.
      </p>
      <div className="legend">
        <span>● As scanned</span>
        {scenario && <span>● Comparison</span>}
      </div>
      {baseline.rt60.map((value, i) => (
        <div className="band" key={i}>
          <strong>{bands[i]} Hz</strong>
          <div className="tracks">
            <div className="track">
              <i style={{ width: `${(value / max) * 100}%` }} />
              <span>{value.toFixed(2)} s</span>
            </div>
            {scenario && (
              <div className="track comparison">
                <i style={{ width: `${(scenario.rt60[i] / max) * 100}%` }} />
                <span>{scenario.rt60[i].toFixed(2)} s</span>
              </div>
            )}
          </div>
        </div>
      ))}
      <p className="muted">
        500 Hz range:{" "}
        {baseline.rt60_range_500.map((n) => n.toFixed(2)).join("–")} s as
        scanned
        {scenario &&
          `; ${scenario.rt60_range_500.map((n) => n.toFixed(2)).join("–")} s comparison`}
        . The range varies the app’s material absorption assumptions.
      </p>
      <p className="muted">Method and inputs{" · "}
        <a className="source-link" href="https://physics.byu.edu/docs/publication/2040" target="_blank" rel="noreferrer">Eyring’s reverberation formula</a>
        {sourceUrl && <>{" · "}<a className="source-link" href={sourceUrl} target="_blank" rel="noreferrer">Room analysis and absorption coefficients (JSON)</a></>}
      </p>
    </section>
  );
}
