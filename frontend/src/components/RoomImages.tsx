import { useEffect, useState } from "react";
import { api, type BuildingRooms } from "../api";

const views = ["Ceiling", "Floor", "Wall 1", "Wall 2", "Wall 3", "Wall 4"];

export default function RoomImages({
  sid,
  rid,
  name,
  plan,
}: {
  sid: string;
  rid: string;
  name: string;
  plan: BuildingRooms;
}) {
  const [face, setFace] = useState(2);
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const index = plan.rooms.findIndex((room) => room.id === rid);
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl = "";
    setUrl("");
    setError("");
    void (async () => {
      try {
        const blob = await api.roomImageSheet(sid, controller.signal);
        const bitmap = await createImageBitmap(blob);
        const matches =
          bitmap.width === 1270 && bitmap.height === plan.rooms.length * 200;
        bitmap.close();
        if (!matches || index < 0)
          throw new Error("The room images do not match this room directory.");
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      } catch (e) {
        if (!controller.signal.aborted)
          setError(
            e instanceof Error ? e.message : "Room images are unavailable.",
          );
      }
    })();
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [sid, rid, plan.rooms.length, index, attempt]);
  function photo(column: number, hidden = false) {
    return (
      <svg
        viewBox={`${70 + column * 200} ${index * 200} 200 200`}
        role={hidden ? undefined : "img"}
        aria-hidden={hidden || undefined}
        aria-label={
          hidden ? undefined : `${name} — ${views[column]} scan image`
        }
      >
        <image href={url} width="1270" height={plan.rooms.length * 200} />
      </svg>
    );
  }
  return (
    <section className="room-visuals" aria-labelledby="room-images-title">
      <div className="visual-heading">
        <div>
          <div className="eyebrow">LOOK AROUND</div>
          <h2 id="room-images-title">Inside {name.toLowerCase()}</h2>
        </div>
        <span className="badge">
          {url ? "Images from the scan" : "Room preview"}
        </span>
      </div>
      <div className="room-visual-layout">
        <div className="photo-stage">
          {url ? photo(face) : <RoomIllustration name={name} />}
          <span className="image-caption">
            {url
              ? `${views[face]} / ${name}`
              : "Illustration only · not a photograph of this room"}
          </span>
        </div>
        <aside className="image-details">
          <h3>{url ? "Six views. One room." : "See the space"}</h3>
          <p>
            {url
              ? "Explore the ceiling, floor and four wall views used to label this room’s acoustic surfaces."
              : "Real room images will appear here when the team’s cached scan images are available."}
          </p>
          {url ? (
            <div className="room-thumbnails">
              {views.map((view, i) => (
                <button
                  key={view}
                  aria-pressed={face === i}
                  aria-label={`Show ${view.toLowerCase()}`}
                  onClick={() => setFace(i)}
                >
                  {photo(i, true)}
                  <span>{view}</span>
                </button>
              ))}
            </div>
          ) : (
            <>
              <p className="muted" role="status">
                {error
                  ? "Scan images unavailable. Showing a room illustration."
                  : "Loading scan images..."}
              </p>
              {error && (
                <button
                  className="secondary"
                  onClick={() => setAttempt((n) => n + 1)}
                >
                  Retry room images
                </button>
              )}
            </>
          )}
          <p className="muted">
            Images describe visible surfaces. Echo values come from the acoustic
            model.
          </p>
        </aside>
      </div>
    </section>
  );
}

function RoomIllustration({ name }: { name: string }) {
  return (
    <svg
      className="room-illustration"
      viewBox="0 0 900 560"
      role="img"
      aria-label={`Illustrative interior for ${name}; not a scan photograph`}
    >
      <defs>
        <linearGradient id="room-wall" x2="1" y2="1">
          <stop stopColor="#e5e7da" />
          <stop offset="1" stopColor="#b6c5b0" />
        </linearGradient>
        <linearGradient id="room-floor" x2="0" y2="1">
          <stop stopColor="#c9b494" />
          <stop offset="1" stopColor="#e7d5b4" />
        </linearGradient>
      </defs>
      <rect width="900" height="560" fill="#eef0e6" />
      <path d="M0 60L570 30 900 100 900 560H0Z" fill="url(#room-wall)" />
      <path d="M570 30V350L0 560H900L900 430 570 350" fill="url(#room-floor)" />
      <path d="M570 30V350L900 430V100Z" fill="#b3c2ae" />
      <path
        d="M70 120L390 98V300L70 380Z"
        fill="#658c80"
        stroke="#f5f6eb"
        strokeWidth="14"
      />
      <path d="M80 155L380 135V280L80 350Z" fill="#b4d1c5" />
      <path d="M225 113V333M77 252L386 194" stroke="#f5f6eb" strokeWidth="9" />
      <path
        d="M80 350L120 280 190 300 270 205 380 253V280Z"
        fill="#71966e"
        opacity=".7"
      />
      <path d="M260 400L510 325 700 390 450 485Z" fill="#4e6c56" />
      <path
        d="M275 403V485M680 395V475M451 480V548"
        stroke="#345140"
        strokeWidth="14"
      />
      <path d="M260 400L450 485 700 390V405L450 500 260 414Z" fill="#365641" />
      <path d="M353 300L412 285 442 349 378 370Z" fill="#d6ac7b" />
      <path d="M530 425L590 405 605 468 547 495Z" fill="#d6ac7b" />
      <path d="M748 364L790 370 780 450 756 444Z" fill="#a47852" />
      <path
        d="M769 370V239M769 310Q700 275 710 245Q765 250 769 310M770 290Q820 250 831 275Q813 315 770 320M770 260Q742 217 768 193Q799 220 770 260"
        fill="#52794f"
        stroke="#52794f"
        strokeWidth="5"
      />
      <path d="M450 0V80" stroke="#63745c" strokeWidth="3" />
      <ellipse cx="450" cy="87" rx="55" ry="18" fill="#f7f4dd" />
      <text x="35" y="525" fill="#5a6a4d" fontSize="12" letterSpacing="3">
        ILLUSTRATIVE ROOM PREVIEW
      </text>
    </svg>
  );
}
