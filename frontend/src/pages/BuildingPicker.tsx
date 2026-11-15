import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type BuildingSummary } from "../api";
import { useRequest } from "../useRequest";
import BannerWaves from "../components/BannerWaves";
import { LoadingBlock } from "../components/Spinner";

const PAGE_SIZE = 24;
const loadBuildings = () => api.buildings();

// ---------------------------------------------------------------- catalog state

function useCatalog(buildings: BuildingSummary[]) {
  const [query, setQuery] = useState("");
  const [readyOnly, setReadyOnly] = useState(true);
  const [kind, setKind] = useState("");
  const [city, setCity] = useState("");
  const [limit, setLimit] = useState(PAGE_SIZE);
  const search = query.trim().toLowerCase();
  const matches = buildings.filter((building) =>
    (!readyOnly || building.analysed) && (!kind || building.kind === kind) && (!city || building.city === city) &&
    [building.name, building.address, building.city, building.state, building.sid]
      .some((value) => value?.toLowerCase().includes(search)),
  );
  const reset = <T,>(set: (value: T) => void) => (value: T) => { set(value); setLimit(PAGE_SIZE); };
  return {
    query, setQuery: reset(setQuery), readyOnly, setReadyOnly: reset(setReadyOnly),
    kind, setKind: reset(setKind), city, setCity: reset(setCity),
    matches, shown: matches.slice(0, limit), more: limit < matches.length, showMore: () => setLimit(limit + PAGE_SIZE),
  };
}
type Catalog = ReturnType<typeof useCatalog>;

function describe(building: BuildingSummary) {
  const title = building.name || building.address || building.sid;
  const city = [building.city, building.state].filter(Boolean).join(", ");
  const location = [building.address !== title && building.address, city].filter(Boolean).join(" · ");
  return { title, location, kind: building.type || building.kind };
}

// ---------------------------------------------------------------- banner

function Banner({ catalog }: { catalog: Catalog }) {
  const toResults = () => document.getElementById("catalog-title")?.scrollIntoView({ behavior: "smooth" });
  return (
    <section className="sound-hero">
      <BannerWaves />
      <div className="sound-hero-inner">
        <h1>Every room has a <span className="rainbow-text">sound.</span></h1>
        <figure className="hero-quote">
          <blockquote>
            <p>“The important thing isn’t if you can read… it’s can you hear it. <em className="rainbow-text">Can you hear the music…?</em>”</p>
          </blockquote>
          <figcaption>Niels Bohr to J. Robert Oppenheimer, in <cite>Oppenheimer</cite> (2023)</figcaption>
        </figure>
        <form className="sound-search" role="search" onSubmit={(event) => { event.preventDefault(); toResults(); }}>
          <label className="search-field">
            <span className="visually-hidden">Search buildings</span>
            <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" /><path d="m13 13 4 4" /></svg>
            <input type="search" value={catalog.query} placeholder="Try “La Mirada” or “Los Angeles”"
              onChange={(event) => catalog.setQuery(event.target.value)} />
          </label>
          <button type="submit" className="cta-primary">Find rooms</button>
        </form>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- catalog

function Placeholder() {
  return (
    <svg className="card-placeholder" viewBox="0 0 120 80" aria-hidden="true">
      <path d="M22 66V36l26-18 26 18v30z" />
      <path d="M40 66V48h16v18" />
      <path className="wave" d="M84 30c6 6 6 18 0 24M92 24c10 10 10 26 0 36M100 18c14 14 14 34 0 48" />
    </svg>
  );
}

function Thumb({ building }: { building: BuildingSummary }) {
  const [failed, setFailed] = useState(false);
  const photo = building.preview_url && !failed;
  return (
    <span className={`row-thumb${photo ? "" : " no-image"}`}>
      {photo ? <img src={building.preview_url} alt="" loading="lazy" onError={() => setFailed(true)} /> : <Placeholder />}
    </span>
  );
}

function CatalogSection({ buildings, catalog }: { buildings: BuildingSummary[]; catalog: Catalog }) {
  const count = (field: "kind" | "city", value: string) => buildings.filter((building) =>
    building[field] === value && (!catalog.readyOnly || building.analysed)).length;
  const kinds = [...new Set(buildings.map((building) => building.kind).filter(Boolean))] as string[];
  const cities = [...new Set(buildings.map((building) => building.city).filter(Boolean))] as string[];
  const ready = buildings.filter((building) => building.analysed).length;

  return (
    <main className="home-main catalog-layout">
      <aside className="filter-panel" aria-label="Filters">
        <label className="toggle-chip">
          <input type="checkbox" checked={catalog.readyOnly} onChange={(event) => catalog.setReadyOnly(event.target.checked)} />
          <span>Ready to listen only</span>
        </label>
        <fieldset>
          <legend>Type</legend>
          {["", ...kinds].map((value) => (
            <label key={value || "all"} className="radio-row">
              <input type="radio" name="kind" checked={catalog.kind === value} onChange={() => catalog.setKind(value)} />
              <span>{value ? value.charAt(0).toUpperCase() + value.slice(1) : "All types"}</span>
              {value && <em>{count("kind", value).toLocaleString()}</em>}
            </label>
          ))}
        </fieldset>
        <fieldset>
          <legend>City</legend>
          {["", ...cities].map((value) => (
            <label key={value || "all"} className="radio-row">
              <input type="radio" name="city" checked={catalog.city === value} onChange={() => catalog.setCity(value)} />
              <span>{value || "All cities"}</span>
              {value && <em>{count("city", value).toLocaleString()}</em>}
            </label>
          ))}
        </fieldset>
      </aside>
      <section aria-labelledby="catalog-title">
        <div className="section-title">
          <div>
            <h2 id="catalog-title">Find a room to listen to</h2>
            <p className="catalog-count">
              {catalog.matches.length.toLocaleString()} {catalog.matches.length === 1 ? "scan" : "scans"}
              {catalog.query && <> matching “{catalog.query}”</>} · {ready} ready to listen
            </p>
          </div>
        </div>
        {catalog.matches.length === 0 ? (
          <div className="empty-state" role="status">
            <p>No buildings match these filters.</p>
            {catalog.readyOnly && <button type="button" onClick={() => catalog.setReadyOnly(false)}>Show all scans</button>}
          </div>
        ) : (
          <ul className="result-rows">
            {catalog.shown.map((building) => {
              const { title, location, kind } = describe(building);
              return (
                <li key={building.sid}>
                  <Link to={`/b/${encodeURIComponent(building.sid)}`} className="result-row">
                    <Thumb building={building} />
                    <span className="row-main">
                      <strong>{title}</strong>
                      <span>{[kind, location].filter(Boolean).join(" · ")}</span>
                    </span>
                    <span className={building.analysed ? "row-status ready" : "row-status"}>
                      {building.analysed && <span className="live-dot" aria-hidden="true" />}
                      {building.analysed ? "Ready to listen" : "Not analysed"}
                    </span>
                    <span className="row-arrow" aria-hidden="true">→</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
        {catalog.more && <button className="show-more" onClick={catalog.showMore}>Show more</button>}
      </section>
    </main>
  );
}

// ---------------------------------------------------------------- page

function Home({ buildings }: { buildings: BuildingSummary[] }) {
  const catalog = useCatalog(buildings);
  return (
    <>
      <Banner catalog={catalog} />
      <CatalogSection buildings={buildings} catalog={catalog} />
    </>
  );
}

export default function BuildingPicker() {
  const { state, retry } = useRequest(loadBuildings);
  return (
    <div className="home">
      {state.status === "loading" && <main className="home-main"><LoadingBlock label="Loading buildings" /></main>}
      {state.status === "error" && (
        <main className="home-main"><p role="alert">Couldn’t load buildings. <button onClick={retry}>Try again</button></p></main>
      )}
      {state.status === "ready" && <Home buildings={state.data} />}
    </div>
  );
}
