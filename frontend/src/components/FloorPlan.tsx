import { useState } from "react";
import { Link } from "react-router-dom";
import type { BuildingRooms, RoomOutline } from "../api";

type Props = {
  floorplan: NonNullable<BuildingRooms["floorplan"]>;
  rooms: RoomOutline[];
  roomPath: (roomId: string) => string;
};

export default function FloorPlan({ floorplan, rooms, roomPath }: Props) {
  const [imageFailed, setImageFailed] = useState(false);
  if (imageFailed) return <p role="status">The floor plan image couldn’t load. Choose a room from the list.</p>;

  return (
    <div className="floor-plan" style={{ aspectRatio: `${floorplan.width} / ${floorplan.height}` }}>
      <img src={floorplan.url} alt="Floor plan" onError={() => setImageFailed(true)} />
      {rooms.map((room) => {
        if (!room.polygon_px || room.polygon_px.length < 3) return null;
        const points = room.polygon_px.map(([x, y]) =>
          `${x * 100 / floorplan.width}% ${y * 100 / floorplan.height}%`,
        );
        return (
          <Link
            className="room-region"
            key={room.id}
            to={roomPath(room.id)}
            style={{ clipPath: `polygon(${points.join(", ")})` }}
            aria-label={`${room.label} (${room.id}) on the floor plan`}
          />
        );
      })}
    </div>
  );
}
