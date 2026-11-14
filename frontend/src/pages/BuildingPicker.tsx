import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type BuildingSummary } from "../api";
import { useRequest } from "../useRequest";
import { LoadingBlock } from "../components/Spinner";

const PAGE_SIZE = 24;
const loadBuildings = () => api.buildings();

// Sound filling a room: a source with echo rings spreading out, and a level meter below.
function HeroArt() {
  return (
    <div className="hero-art" aria-hidden="true">
      <div className="room-sketch">
        <span className="ring" />
        <span className="ring" />
        <span className="ring" />
        <span className="source" />
      </div>
      <div className="meter">
        {Array.from({ length: 18 }, (_, index) => <span key={index} style={{ animationDelay: `${(index % 6) * -0.17}s` }} />)}
      </div>
    </div>
  );
}

function Waveform() {
  return (
    <span className="mini-wave" aria-hidden="true">
      {[0.4, 0.8, 0.55, 1, 0.65, 0.35, 0.75].map((height, index) => (
        <span key={index} style={{ height: `${height * 100}%`, animationDelay: `${index * -0.12}s` }} />
      ))}
    </span>
  );
}

function BuildingCard({ building }: { building: BuildingSummary }) {
  const [imageFailed, setImageFailed] = useState(false);
  const title = building.name || building.address || building.sid;
  const city = [building.city, building.state].filter(Boolean).join(", ");
  const location = [building.address !== title && building.address, city].filter(Boolean).join(" · ");
  const hasImage = building.preview_url && !imageFailed;

  return (
    <li>
      <Link className="building-card" to={`/b/${encodeURIComponent(building.sid)}`}>
        <div className={`card-media${hasImage ? "" : " no-image"}`}>
          {hasImage ? (
            <img src={building.preview_url} alt="" loading="lazy" onError={() => setImageFailed(true)} />
          ) : (
            <svg className="card-placeholder" viewBox="0 0 120 80" aria-hidden="true">
              <path d="M22 66V36l26-18 26 18v30z" />
              <path d="M40 66V48h16v18" />
              <path className="wave" d="M84 30c6 6 6 18 0 24M92 24c10 10 10 26 0 36M100 18c14 14 14 34 0 48" />
            </svg>
          )}
          {building.kind && <span className="kind-chip">{building.type || building.kind}</span>}
          <span className={building.analysed ? "scan-status ready" : "scan-status"}>
            {building.analysed && <span className="live-dot" aria-hidden="true" />}
            {building.analysed ? "Ready to listen" : "Not analysed yet"}
          </span>
        </div>
        <div className="card-body">
          <h3>{title}</h3>
          {location && <p className="card-location">{location}</p>}
          <div className="card-footer">
            <Waveform />
            <span className="card-cta">{building.analysed ? "Explore rooms" : "Open building"} <span aria-hidden="true">→</span></span>
          </div>
        </div>
      </Link>
    </li>
  );
}

export default function BuildingPicker() {
  const { state, retry } = useRequest(loadBuildings);
  const [query, setQuery] = useState("");
  const [availableOnly, setAvailableOnly] = useState(true);
  const [limit, setLimit] = useState(PAGE_SIZE);

  const buildings = state.status === "ready" ? state.data : [];
  const search = query.trim().toLowerCase();
  const matches = buildings.filter((building) =>
    (!availableOnly || building.analysed) &&
    [building.name, building.address, building.city, building.state, building.sid]
      .some((value) => value?.toLowerCase().includes(search)),
  );
  const ready = buildings.filter((building) => building.analysed).length;
  const cities = new Set(buildings.map((building) => building.city).filter(Boolean)).size;

  return (
    <div className="home">
      <section className="hero">
        <div className="hero-inner">
          <div className="hero-copy">
            <p className="hero-eyebrow">Room acoustics from 3D scans</p>
            <h1>Hear a room <em>before</em> you walk in.</h1>
            <p className="hero-lede">
              Pick a scanned building, open any room, and listen to how a voice carries in it. Then try carpet,
              panels or an exposed ceiling and hear the difference.
            </p>
            {state.status === "ready" && (
              <dl className="hero-stats">
                <div><dt>Ready to listen</dt><dd>{ready.toLocaleString()}</dd></div>
                <div><dt>Matterport scans</dt><dd>{buildings.length.toLocaleString()}</dd></div>
                {cities > 0 && <div><dt>Cities</dt><dd>{cities.toLocaleString()}</dd></div>}
              </dl>
            )}
          </div>
          <HeroArt />
        </div>
      </section>

      <main className="home-main">
        <ol className="steps" aria-label="How it works">
          <li><span className="step-number">1</span><div><strong>Pick a building</strong><p>Matterport scans with CoStar records and Vexcel aerials.</p></div></li>
          <li><span className="step-number">2</span><div><strong>Open a room</strong><p>See its shape, materials and the objects in it.</p></div></li>
          <li><span className="step-number">3</span><div><strong>Listen and tweak</strong><p>Hear the echo, compare rooms, try a treatment.</p></div></li>
        </ol>

        <section aria-labelledby="catalog-title">
          <div className="catalog-head">
            <div>
              <h2 id="catalog-title">Buildings</h2>
              {state.status === "ready" && (
                <p className="catalog-count">{matches.length.toLocaleString()} {matches.length === 1 ? "scan" : "scans"}</p>
              )}
            </div>
            {state.status === "ready" && (
              <div className="catalog-controls">
                <label className="search-field">
                  <span className="visually-hidden">Search buildings</span>
                  <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" /><path d="m13 13 4 4" /></svg>
                  <input type="search" value={query} placeholder="Search by name, address or city" onChange={(event) => {
                    setQuery(event.target.value);
                    setLimit(PAGE_SIZE);
                  }} />
                </label>
                <label className="toggle-chip">
                  <input type="checkbox" checked={availableOnly} onChange={(event) => {
                    setAvailableOnly(event.target.checked);
                    setLimit(PAGE_SIZE);
                  }} />
                  <span>Ready to listen only</span>
                </label>
              </div>
            )}
          </div>
          {state.status === "loading" && <LoadingBlock label="Loading buildings" />}
          {state.status === "error" && (
            <p role="alert">Couldn’t load buildings. <button onClick={retry}>Try again</button></p>
          )}
          {state.status === "ready" && (
            <>
              {matches.length === 0 && (
                <div className="empty-state" role="status">
                  <p>No buildings match these filters.</p>
                  {availableOnly && <button type="button" onClick={() => setAvailableOnly(false)}>Show all scanned buildings</button>}
                </div>
              )}
              <ul className="building-grid">
                {matches.slice(0, limit).map((building) => <BuildingCard key={building.sid} building={building} />)}
              </ul>
              {limit < matches.length && (
                <button className="show-more" onClick={() => setLimit(limit + PAGE_SIZE)}>Show more buildings</button>
              )}
            </>
          )}
        </section>
      </main>
    </div>
  );
}
