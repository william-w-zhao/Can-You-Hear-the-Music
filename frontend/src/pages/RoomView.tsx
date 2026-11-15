import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type AcousticDetails, type RoomAcoustics } from "../api";
import { useData } from "../useData";
import LoadState from "../components/LoadState";
import EchoChart from "../components/EchoChart";
import Listen from "../components/Listen";
import StreetNoise from "../components/StreetNoise";
import WhatIf from "../components/WhatIf";
import RoomComparison from "../components/RoomComparison";
import RoomImages from "../components/RoomImages";
import "../room.css";
import { Dimensions } from "../components/RoomEvidence";
import RoomInterior from "../components/RoomInterior";
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
  const traffic = useData(`traffic/${sid}/${Boolean(data)}`, (signal) =>
    data ? api.traffic(sid, signal) : Promise.resolve(undefined),
  );
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
  const roomTraffic = traffic.data?.rooms?.[rid];
  const buildingApi = `/api/buildings/${encodeURIComponent(sid)}`;
  const roomSource = `${buildingApi}/rooms/${encodeURIComponent(rid)}/acoustics`;
  return (
    <div className="room-page">
      <main>
        <Link className="back" to={`/b/${encodeURIComponent(sid)}`}>
          ← Back to floor plan
        </Link>
        <header className="room-overview">
          <div className="room-overview-top">
            <div className="room-heading">
              <h1>{base?.type || `Room ${rid}`}</h1>
              {base && (
                <div className="room-badges">
                  <span className="badge ready">{base.verdict}</span>
                  {roomTraffic && Number.isFinite(roomTraffic.dnl) ? (
                    <a className={`badge traffic-badge${roomTraffic.meets_indoor_limit ? "" : " elevated"}`}
                      href="#street-noise-title" title={roomTraffic.facade?.window_scenario_available
                        ? "Estimated indoor day-night average with windows closed" : "Estimated indoor day-night average"}>
                      Traffic · {roomTraffic.dnl.toFixed(1)} dB DNL
                    </a>
                  ) : (traffic.data || traffic.error) && (
                    <span className="badge">Traffic estimate unavailable</span>
                  )}
                </div>
              )}
            </div>
            {base && (
              <dl className="room-echo" aria-label="Echo times at 500 Hz">
                <div>
                  <dt>Echo at 500 Hz</dt>
                  <dd>{base.rt60[1].toFixed(2)} <small>s</small></dd>
                </div>
                {scenario && (
                  <div>
                    <dt>What-if echo</dt>
                    <dd>{scenario.rt60[1].toFixed(2)} <small>s</small></dd>
                  </div>
                )}
              </dl>
            )}
          </div>
          {details && <Dimensions dimensions={details.dimensions} outline={geometry}
            floorplanUrl={data?.plan.floorplan?.url} sourceUrl={`${buildingApi}/rooms`} />}
        </header>
        {!data || !details || !base ? (
          <LoadState error={error} retry={retry} />
        ) : (
          <>
            {details.object_evidence?.views?.length ? (
              <RoomInterior
                key={reviewCount}
                sid={sid}
                roomId={rid}
                evidence={details.object_evidence}
                onWindowReview={traffic.retry}
              />
            ) : (
              <RoomImages
                sid={sid}
                rid={rid}
                name={base.type}
                plan={data.plan}
              />
            )}
            <Listen choices={choices} voiceUrl={details.voice_url} />
            <StreetNoise traffic={traffic} rid={rid} sourceUrl={`${buildingApi}/traffic`} />
            <div className="workspace">
              <EchoChart
                baseline={base}
                scenario={scenario}
                bands={details.bands_hz}
                sourceUrl={roomSource}
              />
              <WhatIf
                key={reviewCount}
                sid={sid}
                rid={rid}
                details={details}
                onResult={setScenario}
              />
            </div>
            {details.object_evidence && (
              <RoomReview
                sid={sid}
                roomId={rid}
                details={details}
                onSave={(result) => {
                  setReviewed(result);
                  setScenario(undefined);
                  setReviewCount((n) => n + 1);
                  traffic.retry();
                }}
              />
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
          </>
        )}
      </main>
      <footer>
        CAN YOU HEAR THE MUSIC? <span>Acoustic estimates / CoStar track</span>
      </footer>
    </div>
  );
}
