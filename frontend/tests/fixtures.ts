import type { AcousticDetails, BuildingRooms } from "../src/api";

// Deliberately synthetic contract fixtures; no licensed demo data is committed.
export const details: AcousticDetails = {
  bands_hz: ["125", "500", "2000"],
  voice_url: null,
  material_options: {
    wood_floor: "Wood floor",
    carpet_on_pad: "Carpet on pad",
    drywall: "Drywall",
    acoustic_tile: "Acoustic ceiling tile",
    exposed_concrete: "Exposed concrete deck",
  },
  furnishing_options: ["empty", "furnished"],
  room: {
    id: "r1",
    type: "Meeting room",
    floor: "wood_floor",
    ceiling: "acoustic_tile",
    walls: "drywall",
    furnishing: "furnished",
    glass_m2: 2,
    rt60: [0.8, 0.6, 0.4],
    rt60_range_500: [0.5, 0.7],
    verdict: "Good for calls",
    absorption_500: 12,
  },
};
export const second: AcousticDetails = {
  ...details,
  room: {
    ...details.room,
    id: "r2",
    type: "Quiet office",
    rt60: [0.5, 0.3, 0.2],
    rt60_range_500: [0.2, 0.4],
    verdict: "Excellent for calls",
  },
};
export const plan: BuildingRooms = {
  floorplan: { url: "/data/office/plan.png", width: 1000, height: 800 },
  rooms: [
    {
      id: "r1",
      label: "Meeting room",
      polygon_px: [
        [0, 0],
        [100, 0],
        [100, 100],
      ],
      area_m2: 16,
      height_m: 3,
      volume_m3: 48,
    },
    {
      id: "r2",
      label: "Quiet office",
      polygon_px: [
        [100, 0],
        [200, 0],
        [200, 100],
      ],
      area_m2: 12,
      height_m: 3,
      volume_m3: 36,
    },
  ],
};
