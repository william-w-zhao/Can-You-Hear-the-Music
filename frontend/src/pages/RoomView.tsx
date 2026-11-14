import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type AcousticDetails, type RoomAcoustics } from "../api";
import { useData } from "../useData";
import LoadState from "../components/LoadState";
import EchoChart from "../components/EchoChart";
import Listen from "../components/Listen";
import WhatIf from "../components/WhatIf";
import RoomComparison from "../components/RoomComparison";
import RoomImages from "../components/RoomImages";
import "../room.css";
import { Dimensions, RoomInterior } from "../components/RoomEvidence";
import RoomReview from "../components/RoomReview";

export default function RoomView() {
  const { sid = "", rid = "" } = useParams();
  return <RoomWorkspace key={`${sid}/${rid}`} sid={sid} rid={rid} />;
}

function RoomWorkspace({ sid, rid }: { sid: string; rid: string }) {
  const { data, error, retry } = useData(`${sid}/${rid}`, async (signal) => {
    const [details, plan] = await Promise.all([
      api.acoustics(sid, rid, signal),
      api.rooms(sid, signal),
    ]);
    return { details, plan };
  });
  const [reviewed, setReviewed] = useState<AcousticDetails>();
  const [reviewCount, setReviewCount] = useState(0);
  const details = reviewed ?? data?.details;
  const [scenario, setScenario] = useState<RoomAcoustics>();
  const [compare, setCompare] = useState("");
  const comparison = useData(`${sid}/${compare}`, (signal) =>
    compare ? api.acoustics(sid, compare, signal) : Promise.resolve(null),
  );
  const choices = useMemo(
    () =>
      details
        ? [
            {
              label: `As scanned / ${details.room.type}`,
              room: details.room,
            },
            ...(scenario
              ? [{ label: "Material what-if", room: scenario }]
              : []),
            ...(comparison.data
              ? [
                  {
                    label: `Other room / ${comparison.data.room.type} (${compare})`,
                    room: comparison.data.room,
                  },
                ]
              : []),
          ]
        : [],
    [details, scenario, comparison.data, compare],
  );
  const base = details?.room;
  const geometry = data?.plan.rooms.find((room) => room.id === rid);
  return (
    <div className="room-page">
      <main>
        <Link className="back" to={`/b/${encodeURIComponent(sid)}`}>
          ← Back to floor plan
        </Link>
        <div className="eyebrow">LISTEN / 03</div>
        <h1>{base?.type || `Room ${rid}`}</h1>
        {!data || !details || !base ? (
          <LoadState error={error} retry={retry} />
        ) : (
          <>
            <div className="summary">
              <div>
                <span className="badge ready">{base.verdict}</span>
                <p>
                  {rid} / {sid}
                </p>
              </div>
              <div className="metric">
                <strong>
                  {base.rt60[1].toFixed(2)}
                  <small> s</small>
                </strong>
                <span>echo at 500 Hz</span>
              </div>
              {scenario && (
                <div className="metric">
                  <strong>
                    {scenario.rt60[1].toFixed(2)}
                    <small> s</small>
                  </strong>
                  <span>what-if · {scenario.verdict}</span>
                </div>
              )}
            </div>
            {geometry && (
              <div className="dimensions">
                <span>
                  <b>{geometry.area_m2.toFixed(1)} m²</b> floor area
                </span>
                <span>
                  <b>{geometry.height_m.toFixed(1)} m</b> ceiling height
                </span>
                <span>
                  <b>{geometry.volume_m3.toFixed(1)} m³</b> room volume
                </span>
              </div>
            )}
            {details.object_evidence?.views?.length ? (
              <RoomInterior
                key={reviewCount}
                sid={sid}
                roomId={rid}
                evidence={details.object_evidence}
              />
            ) : (
              <RoomImages
                sid={sid}
                rid={rid}
                name={base.type}
                plan={data.plan}
              />
            )}
            {details.object_evidence && (
              <RoomReview
                sid={sid}
                roomId={rid}
                details={details}
                onSave={(result) => {
                  setReviewed(result);
                  setScenario(undefined);
                  setReviewCount((n) => n + 1);
                }}
              />
            )}
            {details.dimensions && (
              <Dimensions dimensions={details.dimensions} />
            )}
            <RoomComparison
              baseline={details}
              other={comparison.data}
              plan={data.plan}
              rid={rid}
              selected={compare}
              onSelect={setCompare}
              error={comparison.error}
              retry={comparison.retry}
            />
            <Listen choices={choices} voiceUrl={details.voice_url} />
            <div className="workspace">
              <EchoChart
                baseline={base}
                scenario={scenario}
                bands={details.bands_hz}
              />
              <WhatIf
                key={reviewCount}
                sid={sid}
                rid={rid}
                details={details}
                onResult={setScenario}
              />
            </div>
          </>
        )}
      </main>
      <footer>
        CAN YOU HEAR THE MUSIC? <span>Acoustic estimates / CoStar track</span>
      </footer>
    </div>
  );
}
