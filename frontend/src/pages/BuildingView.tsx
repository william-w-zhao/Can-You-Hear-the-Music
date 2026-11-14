// One building: CoStar summary, floor plan with rooms colored by echo time, "Analyse" button if needed.
// TODO: port renderRooms() from frontend/prototypes/explorer/index.html and the plan from frontend/prototypes/acoustics/index.html.
import { useParams } from "react-router-dom";
export default function BuildingView() {
  const { sid } = useParams();
  return <main><h1>Building {sid}</h1><p>TODO: FloorPlan, rooms list, AgentPanel</p></main>;
}
