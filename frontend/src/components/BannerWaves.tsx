import { useEffect, useRef } from "react";

// Pastel sound waves spreading from a small circle and bouncing off the banner's edges.
//
// Reflections use the image-source method from room acoustics: a wave reflected off a wall looks exactly like a
// wave coming from a mirrored copy of the source behind that wall. So each ring is drawn from the source and its
// mirror images across the four edges (and corners), all with the same radius; the canvas clips them to the
// banner. Every reflection costs some energy, so reflected rings are fainter, and all rings fade as they travel.
// The source plays for a few seconds, the waves bounce and die away, then it plays again.

const COLORS = ["#f2a7a7", "#f5dd9a", "#a8d8b0", "#a9c8ec"];   // pastel red, yellow, green, blue
const EMIT_FOR = 3.2;          // seconds the source plays
const EMIT_EVERY = 0.4;        // seconds between wavefronts
const SPEED = 170;             // px per second
const FADE = 420;              // px over which a ring loses ~63% of its strength
const START_ALPHA = 0.55;      // rings stay translucent so the text reads clearly
const PER_BOUNCE = 0.62;       // energy kept at each reflection
const MAX_ORDER = 3;           // highest reflection order drawn

// sourceX / sourceY: where the circle sits, as a fraction of the banner's width and height.
export default function BannerWaves({ sourceX = 0.78, sourceY = 0.5 }: { sourceX?: number; sourceY?: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    let width = 0, height = 0;
    const resize = () => {
      const box = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      width = box.width;
      height = box.height;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);

    const pulses = Array.from({ length: Math.floor(EMIT_FOR / EMIT_EVERY) + 1 }, (_, index) => ({
      at: index * EMIT_EVERY, color: COLORS[index % COLORS.length],
    }));
    // Rings are gone once even the direct wave has faded below ~2% strength.
    const travel = FADE * Math.log(START_ALPHA / 0.02);
    const cycle = EMIT_FOR + travel / SPEED + 0.8;

    // Mirror images of the source across the banner edges: x positions 2kW ± sx, likewise for y.
    const images = (sx: number, sy: number) => {
      const out: { x: number; y: number; order: number }[] = [];
      const axis = (s: number, size: number) => {
        const list: { v: number; n: number }[] = [];
        for (let k = -2; k <= 2; k++) {
          list.push({ v: 2 * k * size + s, n: Math.abs(2 * k) });
          list.push({ v: 2 * k * size - s, n: Math.abs(2 * k - 1) });
        }
        return list;
      };
      for (const ix of axis(sx, width)) {
        for (const iy of axis(sy, height)) {
          const order = ix.n + iy.n;
          if (order <= MAX_ORDER) out.push({ x: ix.v, y: iy.v, order });
        }
      }
      return out;
    };

    const draw = (t: number) => {
      context.clearRect(0, 0, width, height);
      // On phones the text fills the banner, so the circle moves to the bottom-right corner, clear of it.
      const narrow = width < 640;
      const sx = width * (narrow ? 0.86 : sourceX), sy = height * (narrow ? 0.93 : sourceY);
      for (const pulse of pulses) {
        const radius = (t - pulse.at) * SPEED;
        if (radius <= 0) continue;
        const strength = START_ALPHA * Math.exp(-radius / FADE);
        if (strength < 0.01) continue;
        for (const image of images(sx, sy)) {
          const alpha = strength * PER_BOUNCE ** image.order;
          // Skip rings that cannot reach the banner yet.
          const nearestX = Math.max(0, Math.min(width, image.x)), nearestY = Math.max(0, Math.min(height, image.y));
          if (alpha < 0.01 || Math.hypot(image.x - nearestX, image.y - nearestY) > radius + 4) continue;
          context.beginPath();
          context.arc(image.x, image.y, radius, 0, Math.PI * 2);
          context.strokeStyle = pulse.color;
          context.globalAlpha = alpha;
          context.lineWidth = 7;                 // soft crest
          context.stroke();
          context.globalAlpha = alpha * 0.9;
          context.lineWidth = 2;                 // sharp leading edge
          context.stroke();
        }
      }
      // The source: a small circle that swells while it plays.
      const playing = t < EMIT_FOR;
      const swell = playing ? 1 + 0.18 * Math.sin((t / EMIT_EVERY) * Math.PI * 2) : 1;
      context.globalAlpha = playing ? 0.9 : 0.55;
      context.beginPath();
      context.arc(sx, sy, 11 * swell, 0, Math.PI * 2);
      context.fillStyle = "#fffefa";
      context.fill();
      context.lineWidth = 2;
      context.strokeStyle = "#1e2822";
      context.stroke();
      context.globalAlpha = 1;
    };

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      draw(EMIT_FOR + 1.5);                      // a single still frame with a few rings and reflections
      return () => observer.disconnect();
    }
    let frame = 0;
    const began = performance.now();
    const tick = (now: number) => {
      draw(((now - began) / 1000) % cycle);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); };
  }, [sourceX, sourceY]);

  return <canvas ref={canvasRef} className="banner-waves" aria-hidden="true" />;
}
