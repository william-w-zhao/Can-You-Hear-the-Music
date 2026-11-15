import { useEffect, useRef, useState } from "react";
import {
  api,
  type AcousticDetails,
  type RoomAcoustics,
  type RoomMaterials,
} from "../api";
import Spinner from "./Spinner";

export default function WhatIf({
  sid,
  rid,
  details,
  onResult,
}: {
  sid: string;
  rid: string;
  details: AcousticDetails;
  onResult: (room?: RoomAcoustics) => void;
}) {
  const base = details.room;
  const initial: Omit<RoomMaterials, "type"> = {
    floor: base.floor,
    ceiling: base.ceiling,
    walls: base.walls,
    furnishing: base.furnishing,
    glass_m2: base.glass_m2,
  };
  const [values, setValues] = useState(initial);
  const [glass, setGlass] = useState(String(initial.glass_m2));
  const [panels, setPanels] = useState("0");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pending = useRef<AbortController>();
  useEffect(() => () => pending.current?.abort(), []);
  const validGlass =
    glass.trim() !== "" && Number.isFinite(Number(glass)) && Number(glass) >= 0;
  const wallArea = base.perimeter_m * base.height_m;
  const panelLimit = wallArea - Math.min(Number(glass), wallArea * 0.9);
  const validPanels =
    panels.trim() !== "" && Number.isFinite(Number(panels)) &&
    Number(panels) >= 0 && Number(panels) <= panelLimit + 1e-9;
  return (
    <section className="panel">
      <div className="eyebrow">CHANGE THE SURFACE</div>
      <h2>What if this room felt softer?</h2>
      <p>Try a treatment. The original scan stays available for comparison.</p>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (!validGlass || !validPanels || pending.current) return;
          const controller = new AbortController();
          pending.current = controller;
          setBusy(true);
          setError("");
          setNotice("");
          try {
            const room = await api.whatIf(
              sid,
              rid,
              { ...values, glass_m2: Number(glass), wall_panel_m2: Number(panels) },
              controller.signal,
            );
            if (!controller.signal.aborted) {
              onResult(room);
              setNotice(
                "Comparison updated. Listen to the baseline and what-if below.",
              );
            }
          } catch (e) {
            if (!controller.signal.aborted)
              setError(e instanceof Error ? e.message : String(e));
          } finally {
            pending.current = undefined;
            if (!controller.signal.aborted) setBusy(false);
          }
        }}
      >
        <fieldset disabled={busy}>
          <div className="form-grid">
            {(["floor", "ceiling", "walls"] as const).map((field) => (
              <label key={field}>
                {field}
                <select
                  value={values[field]}
                  onChange={(e) =>
                    setValues({ ...values, [field]: e.target.value })
                  }
                >
                  {Object.entries(details.material_options).map(
                    ([key, label]) => (
                      <option key={key} value={key}>
                        {label}
                      </option>
                    ),
                  )}
                </select>
              </label>
            ))}
            <label>
              Furnishing
              <select
                value={values.furnishing}
                onChange={(e) =>
                  setValues({ ...values, furnishing: e.target.value })
                }
              >
                {details.furnishing_options.map((key) => (
                  <option key={key} value={key}>
                    {key.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Glass area (m²)
              <input
                type="number"
                required
                min="0"
                step="any"
                value={glass}
                onChange={(e) => setGlass(e.target.value)}
                aria-invalid={!validGlass}
              />
            </label>
            <label>
              Added acoustic wall panels (m²)
              <input type="number" required min="0" step="any" value={panels}
                onChange={(e) => setPanels(e.target.value)} aria-invalid={!validPanels} />
            </label>
          </div>
          {!validGlass && <p role="alert">Enter a non-negative glass area.</p>}
          {validGlass && !validPanels && (
            <p role="alert">Enter a panel area within the available opaque wall area ({panelLimit.toFixed(2)} m²).</p>
          )}
          <div className="actions">
            <button disabled={!validGlass || !validPanels} type="submit">
              {busy ? "Calculating..." : "Apply what-if"}
            </button>
            <button
              className="secondary"
              type="button"
              onClick={() => {
                setValues(initial);
                setGlass(String(initial.glass_m2));
                setPanels("0");
                onResult(undefined);
                setError("");
                setNotice("Reset to the original scan.");
              }}
            >
              Reset to baseline
            </button>
          </div>
        </fieldset>
      </form>
      {busy && <Spinner size="small" label="Recomputing echo times" />}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}
