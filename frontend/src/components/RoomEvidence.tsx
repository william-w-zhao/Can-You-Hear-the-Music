import type { AcousticDetails, RoomOutline } from "../api";

// The room interior (photos, objects, merging) lives in RoomInterior.tsx.
export function Dimensions({
  dimensions,
  outline,
  floorplanUrl,
  sourceUrl,
}: {
  dimensions: AcousticDetails["dimensions"];
  outline?: RoomOutline;
  floorplanUrl?: string;
  sourceUrl: string;
}) {
  if (!dimensions && !outline) return null;
  const area = dimensions?.area_m2 ?? outline?.area_m2;
  const metrics = [
    ["Floor area", area, "m²"],
    ["Length", dimensions?.length_m, "m"],
    ["Width", dimensions?.width_m, "m"],
    ["Ceiling height", dimensions?.height_m ?? outline?.height_m, "m"],
    ["Room volume", dimensions?.volume_m3 ?? outline?.volume_m3, "m³"],
  ] as const;
  const heightNotes = {
    matterport: "Ceiling height comes from Matterport's scan dimensions.",
    assumed: "Ceiling height is assumed; the volume uses that assumption.",
    point_cloud_estimate: "Ceiling height is estimated from the point cloud.",
    floor_point_cloud_estimate:
      "Ceiling height uses the floor-wide point cloud estimate.",
  };
  return (
    <div className="room-dimensions">
      <dl aria-label="Room dimensions">
        {metrics.map(
          ([label, value, unit]) =>
            value != null && (
              <div key={label}>
                <dt>{label}</dt>
                <dd>
                  {value.toFixed(1)} {unit}
                  {label === "Floor area" && <small>{Math.round(value * 10.7639104)} ft²</small>}
                </dd>
              </div>
            ),
        )}
      </dl>
      <details>
        <summary>Measurement details</summary>
        {dimensions && (
          <p>
            {dimensions.footprint_source === "matterport" ? "Matterport" : "The point cloud"} provides the room outline.
            Floor area is estimated from the scan. {heightNotes[dimensions.height_source]}
          </p>
        )}
        <p>
          {floorplanUrl && <><a className="source-link" href={floorplanUrl} target="_blank" rel="noreferrer">Scan floor plan</a>{" · "}</>}
          <a className="source-link" href={sourceUrl} target="_blank" rel="noreferrer">Room geometry (JSON)</a>{" · "}
          <a className="source-link" href="https://matterport.github.io/showcase-sdk/modelapi_property_intelligence.html"
            target="_blank" rel="noreferrer">Matterport Model API</a>
        </p>
      </details>
    </div>
  );
}
