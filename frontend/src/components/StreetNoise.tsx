import { useState } from "react";
import type { TrafficReport, TrafficRoad } from "../api";
import Spinner from "./Spinner";

const SLEEP_GUIDE = 30; // WHO guideline for a bedroom at night, LAeq dB(A)
const HUD = "https://www.ecfr.gov/current/title-24/subtitle-A/part-51/subpart-B/section-51.101#p-51.101(a)(9)";
const WHO = "https://www.who.int/Europe/news-room/fact-sheets/item/noise";
const PLACEMENT = {
  aligned: "Wall directions come from lining the floor plan up with the building outline in OpenStreetMap.",
  ambiguous: "The floor plan fits the building outline more than one way, so each wall uses the louder case.",
  unknown: "Wall directions are unknown, so every outside wall is assumed to face the traffic.",
};

const hourLabel = (hour: number) => `${hour % 12 || 12} ${hour < 12 ? "a.m." : "p.m."}`;

function roadMap(road: TrafficRoad) {
  if (road.osm_way_id) return `https://www.openstreetmap.org/way/${road.osm_way_id}`;
  const point = road.lines?.[0]?.[0];
  return point ? `https://www.openstreetmap.org/#map=18/${point[0]}/${point[1]}` : undefined;
}

function CountSource({ road }: { road: TrafficRoad }) {
  const { kind, detail, date, url } = road.adt_source;
  return kind === "typical" ? <span>App estimate · {detail}</span> : (
    <>
      {url ? <a className="source-link" href={url} target="_blank" rel="noreferrer">{detail}</a> : detail}
      {date && !detail.includes(date) && ` · ${date}`}
    </>
  );
}

function Chart({ outdoor, baseline, open, level, hour, onHour }: {
  outdoor: number[]; baseline: number[]; open: number[] | null; level: number; hour: number; onHour: (hour: number) => void;
}) {
  const width = 640, height = 220, left = 38, right = 12, top = 12, bottom = 28;
  const low = 10, high = Math.max(90, Math.ceil(Math.max(...outdoor) / 10) * 10);
  const x = (h: number) => left + (h / 23) * (width - left - right);
  const y = (db: number) => top + ((high - Math.max(low, db)) / (high - low)) * (height - top - bottom);
  const line = (values: number[]) => values.map((v, h) => `${h ? "L" : "M"}${x(h).toFixed(1)},${y(v).toFixed(1)}`).join("");
  return (
    <svg className="noise-chart" viewBox={`0 0 ${width} ${height}`} role="img"
      aria-label={`Street noise by hour: outdoors ${Math.round(Math.min(...outdoor))} to ${Math.round(Math.max(...outdoor))} dB, indoor baseline ${Math.round(Math.min(...baseline))} to ${Math.round(Math.max(...baseline))} dB`}
      onClick={(event) => {
        const box = event.currentTarget.getBoundingClientRect();
        const h = Math.round(((event.clientX - box.left) / box.width * width - left) / (width - left - right) * 23);
        onHour(Math.max(0, Math.min(23, h)));
      }}>
      <rect x={x(0)} y={top} width={x(7) - x(0)} height={height - top - bottom} className="noise-night" />
      <rect x={x(22)} y={top} width={x(23) - x(22)} height={height - top - bottom} className="noise-night" />
      {Array.from({ length: (high - low) / 10 + 1 }, (_, i) => low + i * 10).map((db) => (
        <g key={db}><line x1={left} x2={width - right} y1={y(db)} y2={y(db)} className="noise-grid" />
          <text x={left - 6} y={y(db) + 4} textAnchor="end">{db}</text></g>
      ))}
      {[0, 6, 12, 18, 23].map((h) => <text key={h} x={x(h)} y={height - 8} textAnchor={h === 0 ? "start" : h === 23 ? "end" : "middle"}>{hourLabel(h)}</text>)}
      <line x1={left} x2={width - right} y1={y(SLEEP_GUIDE)} y2={y(SLEEP_GUIDE)} className="noise-guide" />
      <text x={width - right} y={y(SLEEP_GUIDE) - 5} textAnchor="end" className="noise-guide-label">30 dB sleep guideline</text>
      <path d={line(outdoor)} className="noise-outdoor" />
      {open && <path d={line(open)} className="noise-open" />}
      <path d={line(baseline)} className="noise-closed" />
      <line x1={x(hour)} x2={x(hour)} y1={top} y2={height - bottom} className="noise-cursor" />
      <circle cx={x(hour)} cy={y(level)} r={4} className="noise-dot" />
    </svg>
  );
}

export default function StreetNoise({ traffic, rid, sourceUrl }: {
  traffic: { data?: TrafficReport; error?: string; retry: () => void };
  rid: string; sourceUrl: string;
}) {
  const [hour, setHour] = useState(8);
  const [windowOpen, setWindowOpen] = useState(false);
  if (traffic.error)
    return <section className="panel street-noise"><h2>Street noise</h2><p role="alert">Couldn’t look up traffic for this building. The map or count services may be busy.</p><button onClick={traffic.retry}>Try again</button></section>;
  if (!traffic.data) return <section className="panel street-noise"><Spinner label="Looking up nearby traffic" /></section>;

  const report = traffic.data;
  const indoor = report.rooms?.[rid];
  if (!indoor || !report.outdoor?.hourly_db) return null;
  const openLevels = indoor.facade.window_scenario_available && indoor.dnl_window_open != null
    ? indoor.hourly_db_window_open : null;
  const useOpenWindow = windowOpen && openLevels !== null;
  const hourly = useOpenWindow ? openLevels : indoor.hourly_db;
  const level = hourly[hour];
  const top = report.outdoor.roads[0];

  return (
    <section className="panel street-noise" aria-labelledby="street-noise-title">
      <div className="eyebrow">THE STREET</div>
      <h2 id="street-noise-title">How much traffic gets in?</h2>
      <p>
        <strong>{indoor.verdict}.</strong> The model estimates {indoor.night_leq} dB at night and {indoor.dnl} dB day-night (DNL)
        {openLevels && " with windows closed"}. That is {indoor.meets_indoor_limit ? "within" : "above"} the{" "}
        <a className="source-link" href={HUD} target="_blank" rel="noreferrer">{report.indoor_limit_dnl} dB DNL HUD interior goal</a>.
        {" "}
        {openLevels
          ? `If the detected window can open, the model estimates ${indoor.dnl_window_open} dB DNL in that scenario.`
          : "An open-window estimate needs scan evidence of an exterior window."}
      </p>
      {top && <p className="noise-source">Loudest nearby: <strong>{top.name}</strong>, {Math.round(top.distance_m)} m away,{" "}
        {top.adt.toLocaleString()} vehicles a day. <CountSource road={top} /></p>}

      <div className="noise-controls">
        <label className="noise-hour">
          <span>{hourLabel(hour)}</span>
          <input type="range" min={0} max={23} value={hour} onChange={(event) => setHour(Number(event.target.value))}
            aria-label="Hour of the day" aria-valuetext={`${hourLabel(hour)}, ${level} dB in this room`} />
        </label>
        {openLevels && (
          <div className="noise-toggle" role="group" aria-label="Windows">
            <button type="button" aria-pressed={!useOpenWindow} onClick={() => setWindowOpen(false)}>Windows closed</button>
            <button type="button" aria-pressed={useOpenWindow} onClick={() => setWindowOpen(true)}>Window open</button>
          </div>
        )}
      </div>
      <p className="noise-readout" aria-live="polite">
        At {hourLabel(hour)}: <strong>{level} dB</strong> in this room · {report.outdoor.hourly_db[hour]} dB outside
      </p>
      <Chart outdoor={report.outdoor.hourly_db} baseline={indoor.hourly_db} open={openLevels}
        level={level} hour={hour} onHour={setHour} />
      <div className="legend noise-legend">
        <span className="key-outdoor">Outside</span>
        <span className="key-closed">{openLevels ? "This room, windows closed" : "This room"}</span>
        {openLevels && <span className="key-open">This room, window open</span>}
      </div>

      <details className="noise-details">
        <summary>Road data, sources and assumptions</summary>
        <div className="noise-table"><table>
          <thead><tr><th>Road</th><th>Distance</th><th>Speed</th><th>Vehicles/day</th><th>Volume source</th><th>Estimated daytime level</th></tr></thead>
          <tbody>
            {report.outdoor.roads.map((road) => {
              const map = roadMap(road);
              return <tr key={`${road.name}-${road.class}`}>
                <td>{map ? <a className="source-link" href={map} target="_blank" rel="noreferrer">{road.name}</a> : road.name}</td>
                <td>{Math.round(road.distance_m)} m</td>
                <td>{road.speed_kmh} km/h{road.speed_source && <small>{road.speed_source}</small>}</td>
                <td>{road.adt.toLocaleString()}</td>
                <td><CountSource road={road} /></td>
                <td>{road.day_leq} dB</td>
              </tr>;
            })}
          </tbody>
        </table></div>
        {indoor.facade.note && <p className="noise-check">{indoor.facade.note}</p>}
        {report.placement && <p>{PLACEMENT[report.placement.status]}{report.placement.reason ? ` ${report.placement.reason}` : ""}</p>}
        <p>{indoor.facade.exposure}. Facade insulation {indoor.facade.insulation_db} dB
          {indoor.facade.glazing && !report.exterior ? ` (assumes ${indoor.facade.glazing} glazing${report.year_built ? ` based on the CoStar build year, ${report.year_built}` : ""})` : ""}.</p>
        {report.exterior && (
          <p className="noise-exterior">
            Outside walls: <strong>{report.exterior.wall_label}</strong> ({report.exterior.wall_insulation_db} dB);
            windows: <strong>{report.exterior.window_label}</strong> ({report.exterior.window_insulation_db} dB).
            Read from {report.exterior.basis}, {Math.round(report.exterior.confidence * 100)}% confidence: {report.exterior.evidence}
          </p>
        )}
        <ul>{[...report.assumptions, ...report.notes].map((item) => <li key={item}>{item}</li>)}</ul>
        <ul className="source-list">
          <li>Road geometry and building outlines. <a className="source-link" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors (ODbL)</a></li>
          <li>Vehicle emission equations. <a className="source-link" href="https://trid.trb.org/View/168779" target="_blank" rel="noreferrer">FHWA report RD-77-108</a></li>
          <li>Hourly traffic pattern reference. <a className="source-link" href="https://www.fhwa.dot.gov/policyinformation/tmguide/tmg_2022/traffic-monitoring-program.cfm" target="_blank" rel="noreferrer">FHWA Traffic Monitoring Guide</a></li>
          <li>Reference for the app’s simplified façade calculation. <a className="source-link" href="https://www.iso.org/standard/70244.html" target="_blank" rel="noreferrer">ISO 12354-3</a></li>
          <li>HUD interior goal. <q>The interior auditory environment shall not exceed a day-night average sound level of 45 decibels</q>.{" "}
            <a className="source-link" href={HUD} target="_blank" rel="noreferrer">24 CFR 51.101(a)(9)</a></li>
          <li>Nighttime bedroom reference. <q>Less than 30 A-weighted decibels (dB(A)) in bedrooms during the night</q>.{" "}
            <a className="source-link" href={WHO} target="_blank" rel="noreferrer">WHO community noise guidance</a></li>
        </ul>
        <p className="noise-sources">
          <a className="source-link" href={sourceUrl} target="_blank" rel="noreferrer">Traffic inputs and results (JSON)</a>
          {report.fetched_at && ` · Data fetched ${report.fetched_at.slice(0, 10)}`}
        </p>
      </details>
    </section>
  );
}
