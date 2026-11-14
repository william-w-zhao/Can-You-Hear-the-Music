import { Link, Route, Routes } from "react-router-dom";
import BuildingPicker from "./pages/BuildingPicker";
import BuildingView from "./pages/BuildingView";
import RoomView from "./pages/RoomView";

// The product flow: pick a building -> pick a room -> hear it (and ask the agent).
export default function App() {
  return (
    <>
      <header className="site-header">
        <div className="header-inner">
          <Link className="brand" to="/">
            Can You Hear the Music<span>?</span>
          </Link>
        </div>
      </header>
      <Routes>
        <Route path="/" element={<BuildingPicker />} />
        <Route path="/b/:sid" element={<BuildingView />} />
        <Route path="/b/:sid/r/:rid" element={<RoomView />} />
        <Route path="*" element={<main><h1>Page unavailable</h1><Link to="/">Back to buildings</Link></main>} />
      </Routes>
    </>
  );
}
