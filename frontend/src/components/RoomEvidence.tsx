import type { AcousticDetails } from "../api";

// The room interior (photos, objects, merging) lives in RoomInterior.tsx.
export function Dimensions({
  dimensions,
}: {
  dimensions: NonNullable<AcousticDetails["dimensions"]>;
}) {
  const metrics = [
    ["Length", dimensions.length_m, "m"],
    ["Width", dimensions.width_m, "m"],
    ["Ceiling height", dimensions.height_m, "m"],
    [
      "Floor area",
      dimensions.area_m2 === null
        ? null
        : Math.round(dimensions.area_m2 * 10.7639104),
      "ft²",
    ],
    ["Volume", dimensions.volume_m3, "m³"],
  ] as const;
  const heightNotes = {
    matterport: "Ceiling height comes from Matterport's scan dimensions.",
    assumed: "Ceiling height is assumed; the volume uses that assumption.",
    point_cloud_estimate: "Ceiling height is estimated from the point cloud.",
    floor_point_cloud_estimate:
      "Ceiling height uses the floor-wide point cloud estimate.",
  };
  return (
    <section className="details-panel" aria-labelledby="dimensions-title">
      <h2 id="dimensions-title">Room dimensions</h2>
      <dl className="metrics">
        {metrics.map(
          ([label, value, unit]) =>
            value !== null && (
              <div key={label}>
                <dt>{label}</dt>
                <dd>
                  {value} <span>{unit}</span>
                </dd>
              </div>
            ),
        )}
      </dl>
      <p>
        Length and width span the outline from{" "}
        {dimensions.footprint_source === "matterport"
          ? "Matterport"
          : "the point cloud"}
        . Floor area is an estimate from the scan.{" "}
        {heightNotes[dimensions.height_source]}
      </p>
    </section>
  );
}
