import { it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import StreetNoise from "../src/components/StreetNoise";
import type { TrafficReport } from "../src/api";

const hours = (base: number) => Array.from({ length: 24 }, (_, h) => base + (h >= 7 && h < 22 ? 8 : 0));
const report: TrafficReport = {
  outdoor: {
    hourly_db: hours(68), dnl: 77.6, day_leq: 75.5, night_leq: 69.7,
    roads: [{ name: "Ventura Freeway", class: "motorway", distance_m: 134, adt: 186000, speed_kmh: 105, day_leq: 75.3,
      osm_way_id: 134, adt_source: { kind: "hpms", detail: "FHWA HPMS 2024 AADT, route 134",
        url: "https://geo.dot.gov/server/rest/services/Hosted/HPMS_FULL_CA_2024/FeatureServer/0" } }],
  },
  rooms: {
    r1: { type: "Living room", hourly_db: hours(38), hourly_db_window_open: hours(50), dnl: 47.2, dnl_window_open: 59.1,
      night_leq: 39.3, day_leq: 45.5, quietest_hour: 2, loudest_hour: 17, verdict: "Noticeable traffic at night",
      meets_indoor_limit: false,
      facade: { exposure: "Has windows", glazing: "single", insulation_db: 28, insulation_open_db: 16,
        window_scenario_available: true } },
  },
  year_built: 1937, indoor_limit_dnl: 45, assumptions: ["Estimates."], sources: ["Caltrans"], notes: [],
};
const sourceUrl = "/api/buildings/s1/traffic";

it("explains the room's street noise and switches between closed and open windows", async () => {
  render(<div className="room-page"><StreetNoise traffic={{ data: report, retry: () => {} }} rid="r1" sourceUrl={sourceUrl} /></div>);
  expect(await screen.findByText("Noticeable traffic at night.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "45 dB DNL HUD interior goal" })).toHaveAttribute("href", expect.stringContaining("ecfr.gov"));
  expect(screen.getByText("Ventura Freeway", { selector: "strong" })).toBeInTheDocument();
  expect(screen.getByText(/At 8 a.m.:/)).toHaveTextContent("46 dB in this room");
  await userEvent.click(screen.getByRole("button", { name: "Window open" }));
  expect(screen.getByText(/At 8 a.m.:/)).toHaveTextContent("58 dB in this room");
  expect(screen.queryByRole("button", { name: /hear.*traffic|voice over traffic/i })).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("Road data, sources and assumptions"));
  expect(screen.getByRole("link", { name: "Ventura Freeway" })).toHaveAttribute("href", "https://www.openstreetmap.org/way/134");
  expect(screen.getAllByRole("link", { name: /FHWA HPMS 2024/ })[0]).toHaveAttribute("href", expect.stringContaining("geo.dot.gov"));
  expect(screen.getByRole("link", { name: "Traffic inputs and results (JSON)" })).toHaveAttribute("href", sourceUrl);
});

it("keeps the indoor estimate and hides the window controls and series when scan evidence is missing", () => {
  const baseline = report.rooms.r1;
  const withoutWindow: TrafficReport = { ...report, rooms: { r1: {
    ...baseline, hourly_db_window_open: null, dnl_window_open: null,
    facade: { ...baseline.facade, window_scenario_available: false, insulation_open_db: null },
  } } };
  const { container } = render(<StreetNoise traffic={{ data: withoutWindow, retry: () => {} }} rid="r1" sourceUrl={sourceUrl} />);
  expect(screen.queryByRole("group", { name: "Windows" })).not.toBeInTheDocument();
  expect(screen.queryByText(/windows closed/i)).not.toBeInTheDocument();
  expect(container.querySelector(".noise-open")).toBeNull();
  expect(screen.getByText(/At 8 a.m.:/)).toHaveTextContent("46 dB in this room");
});
