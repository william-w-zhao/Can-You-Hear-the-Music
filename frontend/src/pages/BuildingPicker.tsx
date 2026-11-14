import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type BuildingSummary } from "../api";
import { useRequest } from "../useRequest";
import { LoadingBlock } from "../components/Spinner";

const PAGE_SIZE = 24;
const loadBuildings = () => api.buildings();

function BuildingCard({ building }: { building: BuildingSummary }) {
  const [imageFailed, setImageFailed] = useState(false);
  const title = building.name || building.address || building.sid;
  const city = [building.city, building.state].filter(Boolean).join(", ");
  const location = [building.address !== title && building.address, city].filter(Boolean).join(" · ");

  return (
    <li>
      <Link className="building-card" to={`/b/${encodeURIComponent(building.sid)}`}>
        <div className="card-media">
          {building.preview_url && !imageFailed && (
            <img src={building.preview_url} alt="" loading="lazy" onError={() => setImageFailed(true)} />
          )}
          <span className={building.analysed ? "scan-status ready" : "scan-status"}>
            {building.analysed ? "Rooms available" : "Awaiting analysis"}
          </span>
        </div>
        <div className="card-body">
          <div>
            {building.kind && <p className="property-kind">{building.type || building.kind}</p>}
            <h2>{title}</h2>
            {location && <p className="card-location">{location}</p>}
          </div>
          <span className="card-arrow" aria-hidden="true">↗</span>
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

  return (
    <main>
      <h1>Choose a building</h1>
      <p className="intro">Open a building to explore its floor plan and room acoustics.</p>
      {state.status === "loading" && <LoadingBlock label="Loading buildings" />}
      {state.status === "error" && (
        <p role="alert">Couldn’t load buildings. <button onClick={retry}>Try again</button></p>
      )}
      {state.status === "ready" && (
        <>
          <div className="catalog-controls">
            <label className="search-label">
              Search buildings
              <input type="search" value={query} placeholder="Name, address, or city" onChange={(event) => {
                setQuery(event.target.value);
                setLimit(PAGE_SIZE);
              }} />
            </label>
            <label className="filter-label">
              <input type="checkbox" checked={availableOnly} onChange={(event) => {
                setAvailableOnly(event.target.checked);
                setLimit(PAGE_SIZE);
              }} />
              Rooms available only
            </label>
          </div>
          {matches.length === 0 && <p role="status">No buildings match these filters.</p>}
          <ul className="building-grid">
            {matches.slice(0, limit).map((building) => <BuildingCard key={building.sid} building={building} />)}
          </ul>
          {limit < matches.length && (
            <button className="show-more" onClick={() => setLimit(limit + PAGE_SIZE)}>Show more buildings</button>
          )}
        </>
      )}
    </main>
  );
}
