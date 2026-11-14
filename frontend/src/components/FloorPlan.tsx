import { useState } from "react";
import { Link } from "react-router-dom";
import type { BuildingRooms, RoomOutline } from "../api";

type Props = {
  floorplan: NonNullable<BuildingRooms["floorplan"]>;
  rooms: RoomOutline[];
  roomPath: (roomId: string) => string;
  activeRoom?: string;
  onRoomPreview: (roomId?: string) => void;
};

function labelPosition(points: RoomOutline["polygon_px"], center?: RoomOutline["center_px"]) {
  const minY = Math.min(...points.map(([, y]) => y));
  const maxY = Math.max(...points.map(([, y]) => y));
  let best = { width: 0, point: points[0] };
  // Try horizontal slices so labels stay inside rooms with corners or narrow wings.
  const scanlines = Array.from({ length: 9 }, (_, i) => minY + (maxY - minY) * (i + 1) / 10);
  if (center) scanlines.unshift(center[1]);
  for (const y of scanlines) {
    const cuts: number[] = [];
    for (let i = 0; i < points.length; i++) {
      const [x1, y1] = points[i];
      const [x2, y2] = points[(i + 1) % points.length];
      if ((y1 > y) !== (y2 > y)) cuts.push(x1 + (x2 - x1) * (y - y1) / (y2 - y1));
    }
    cuts.sort((a, b) => a - b);
    for (let i = 0; i + 1 < cuts.length; i += 2) {
      const [left, right] = [cuts[i], cuts[i + 1]];
      if (center && y === center[1] && center[0] > left && center[0] < right) return center;
      if (right - left > best.width) best = { width: right - left, point: [(left + right) / 2, y] };
    }
  }
  return best.point;
}

export default function FloorPlan({ floorplan, rooms, roomPath, activeRoom, onRoomPreview }: Props) {
  const [imageFailed, setImageFailed] = useState(false);
  if (imageFailed) return <p role="status">The floor plan image couldn’t load. Choose a room from the list.</p>;
  const regions = rooms.filter((room) => room.polygon_px?.length >= 3);
  const active = regions.find((room) => room.id === activeRoom);
  const polygon = (room: RoomOutline) => room.polygon_px.map(([x, y]) => `${x},${y}`).join(" ");

  return (
    <div className="floor-plan">
      <img src={floorplan.url} alt="Floor plan" width={floorplan.width} height={floorplan.height}
        onError={() => setImageFailed(true)} />
      <svg viewBox={`0 0 ${floorplan.width} ${floorplan.height}`} aria-label="Clickable room outlines">
        {regions.map((room) => (
          <Link key={room.id} to={roomPath(room.id)} aria-label={`${room.label} (${room.id.toUpperCase()}) on the floor plan`}
            onPointerEnter={() => onRoomPreview(room.id)} onPointerLeave={() => onRoomPreview()}
            onFocus={() => onRoomPreview(room.id)} onBlur={() => onRoomPreview()}>
            <polygon className="room-region" points={polygon(room)} vectorEffect="non-scaling-stroke" />
          </Link>
        ))}
        {active && <polygon className="room-region room-region-active" points={polygon(active)}
          vectorEffect="non-scaling-stroke" aria-hidden="true" />}
      </svg>
      {regions.map((room) => {
        const [x, y] = labelPosition(room.polygon_px, room.center_px);
        return (
          <span key={room.id} className={`room-marker${room.id === activeRoom ? " active" : ""}`} aria-hidden="true"
            style={{ left: `${x * 100 / floorplan.width}%`, top: `${y * 100 / floorplan.height}%` }}>
            {room.id.toUpperCase()}
          </span>
        );
      })}
    </div>
  );
}
