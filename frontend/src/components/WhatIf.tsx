import { useEffect, useRef, useState } from "react";
import {
  api,
  type AcousticDetails,
  type RoomAcoustics,
  type RoomMaterials,
} from "../api";

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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pending = useRef<AbortController>();
  useEffect(() => () => pending.current?.abort(), []);
  const validGlass =
    glass.trim() !== "" && Number.isFinite(Number(glass)) && Number(glass) >= 0;
  return (
    <section className="details-panel sound-panel" aria-labelledby="treatment-heading">
      <h2 id="treatment-heading">Try a material treatment</h2>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (!validGlass || pending.current) return;
          const controller = new AbortController();
          pending.current = controller;
          setBusy(true);
          setError("");
          setNotice("");
          try {
            const room = await api.whatIf(
              sid,
              rid,
              { ...values, glass_m2: Number(glass) },
              controller.signal,
            );
            if (!controller.signal.aborted) {
              onResult(room);
              setNotice(
                "Treatment ready. Play it in the listening panel.",
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
          <div className="sound-form">
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
          </div>
          {!validGlass && <p role="alert">Enter a non-negative glass area.</p>}
          <div className="sound-actions">
            <button disabled={!validGlass} type="submit">
              {busy ? "Calculating..." : "Apply what-if"}
            </button>
            <button
              type="button"
              onClick={() => {
                setValues(initial);
                setGlass(String(initial.glass_m2));
                onResult(undefined);
                setError("");
                setNotice("Reset to the current room materials.");
              }}
            >
              Reset to baseline
            </button>
          </div>
        </fieldset>
      </form>
      {busy && <p role="status">Recomputing echo times...</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}
