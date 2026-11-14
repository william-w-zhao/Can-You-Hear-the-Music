import { useEffect, useRef, useState } from "react";
import { api, type RoomAcoustics } from "../api";
import { clap, impulse } from "../audio";

export default function Listen({
  choices,
  voiceUrl,
}: {
  choices: { label: string; room: RoomAcoustics }[];
  voiceUrl: string | null;
}) {
  const context = useRef<AudioContext>();
  const stopRef = useRef<() => void>(() => {});
  const controller = useRef<AbortController>();
  const generation = useRef(0);
  const clip = useRef<{ url: string; buffer: AudioBuffer }>();
  const clapBuffer = useRef<AudioBuffer>();
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  function stop() {
    generation.current++;
    controller.current?.abort();
    stopRef.current();
    setLoading(false);
    setStatus("Stopped");
  }
  useEffect(() => {
    setStatus("");
    setLoading(false);
    setError("");
    return () => {
      generation.current++;
      controller.current?.abort();
      stopRef.current();
      void context.current?.close();
    };
  }, [choices]);
  async function play(
    room: RoomAcoustics,
    label: string,
    kind: "voice" | "clap",
  ) {
    stop();
    const run = ++generation.current;
    setLoading(true);
    setError("");
    setStatus("Preparing audio...");
    const request = new AbortController();
    controller.current = request;
    try {
      const c =
        context.current?.state === "closed" || !context.current
          ? new AudioContext()
          : context.current;
      context.current = c;
      await c.resume();
      if (run !== generation.current) return;
      let buffer: AudioBuffer;
      if (kind === "voice") {
        if (!voiceUrl)
          throw new Error(
            "No voice clip is available for this scan. Try the clap.",
          );
        if (clip.current?.url !== voiceUrl)
          clip.current = {
            url: voiceUrl,
            buffer: await c.decodeAudioData(
              await api.voice(voiceUrl, request.signal),
            ),
          };
        buffer = clip.current.buffer;
      } else {
        clapBuffer.current ??= clap(c);
        buffer = clapBuffer.current;
      }
      if (run !== generation.current) return;
      const source = c.createBufferSource(),
        convolver = c.createConvolver(),
        gain = c.createGain(),
        compressor = c.createDynamicsCompressor();
      source.buffer = buffer;
      convolver.normalize = false;
      convolver.buffer = impulse(c, room.rt60, room.absorption_500);
      gain.gain.value = 0.35;
      source
        .connect(convolver)
        .connect(gain)
        .connect(compressor)
        .connect(c.destination);
      const cleanup = () => {
        try {
          source.stop();
        } catch {
          /* already ended */
        }
        source.disconnect();
        convolver.disconnect();
        gain.disconnect();
        compressor.disconnect();
        clearTimeout(timer);
      };
      const timer = window.setTimeout(
        () => {
          cleanup();
          if (run === generation.current)
            setStatus("Finished. Choose another room or treatment.");
        },
        (buffer.duration + convolver.buffer.duration) * 1000 + 100,
      );
      stopRef.current = cleanup;
      source.start();
      setStatus(`Playing ${kind} / ${label}`);
    } catch (e) {
      if (run === generation.current) {
        setError(
          e instanceof Error
            ? e.message
            : "Audio is unavailable in this browser.",
        );
        setStatus("");
        stopRef.current();
      }
    } finally {
      if (run === generation.current) setLoading(false);
    }
  }
  return (
    <section className="panel listen">
      <div className="eyebrow">PUT ON YOUR HEADPHONES</div>
      <h2>Hear the difference.</h2>
      <p>The same clip, the same gain. Switch between spaces and treatments.</p>
      <div className="listen-options">
        {choices.map(({ label, room }) => (
          <div key={label}>
            <strong>{label}</strong>
            <span>{room.rt60[1].toFixed(2)} s at 500 Hz</span>
            <div className="actions">
              <button
                disabled={loading || !voiceUrl}
                onClick={() => void play(room, label, "voice")}
              >
                ▶ Voice
              </button>
              <button
                disabled={loading}
                className="secondary"
                onClick={() => void play(room, label, "clap")}
              >
                ▶ Clap
              </button>
            </div>
          </div>
        ))}
      </div>
      <button className="secondary" onClick={stop}>
        Stop audio
      </button>
      <p role="status" aria-live="polite">
        {status}
      </p>
      {!voiceUrl && (
        <p className="muted">
          The team's voice clip is not available. Clap playback still works.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <p className="muted">
        Synthetic reverberation from three-band echo times; not a room
        recording. Tail length is capped at 3.5 seconds, following the
        prototype.
      </p>
    </section>
  );
}
