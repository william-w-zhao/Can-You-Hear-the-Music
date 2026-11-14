import { Route, Routes } from "react-router-dom";
import BuildingPicker from "./pages/BuildingPicker";
import BuildingView from "./pages/BuildingView";
import RoomView from "./pages/RoomView";

// The product flow: pick a building -> pick a room -> hear it (and ask the agent).
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<BuildingPicker />} />
      <Route path="/b/:sid" element={<BuildingView />} />
      <Route path="/b/:sid/r/:rid" element={<RoomView />} />
    </Routes>
  );
}
