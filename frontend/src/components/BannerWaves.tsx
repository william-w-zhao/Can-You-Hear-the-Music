import { useEffect, useRef } from "react";

const EMIT_EVERY = 0.4;
const EMIT_FOR = 3.2;
const SPEED = 170;
const FADE = 420;
const START_ALPHA = 0.55;
const MAX_ORDER = 3;
const CYCLE = EMIT_FOR + FADE * Math.log(START_ALPHA / 0.02) / SPEED + 0.8;
const COLOR_NAMES = ["--t-red", "--t-yellow", "--t-green", "--t-blue", "--t-red"];

// Each reflection looks like a wave from a mirrored source beyond the banner edge.
function reflectedSources(x: number, y: number, width: number, height: number) {
  function axis(position: number, size: number) {
    const images = [];
    for (let k = -2; k <= 2; k++) {
      images.push({ position: 2 * k * size + position, order: Math.abs(2 * k) });
      images.push({ position: 2 * k * size - position, order: Math.abs(2 * k - 1) });
    }
    return images;
  }
  const horizontal = axis(x, width);
  const vertical = axis(y, height);
  const sources = [];
  for (const sx of horizontal) {
    for (const sy of vertical) {
      const order = sx.order + sy.order;
      if (order > MAX_ORDER) continue;
      const dx = sx.position - Math.max(0, Math.min(width, sx.position));
      const dy = sy.position - Math.max(0, Math.min(height, sy.position));
      sources.push({ x: sx.position, y: sy.position, strength: 0.62 ** order, distance: Math.hypot(dx, dy) });
    }
  }
  return sources;
}

export default function BannerWaves() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dotRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const dot = dotRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !dot || !context) return;

    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const style = getComputedStyle(canvas);
    const colors = COLOR_NAMES.map(name => style.getPropertyValue(name).trim());
    let width = 0;
    let height = 0;
    let sources: ReturnType<typeof reflectedSources> = [];

    const draw = (elapsed: number) => {
      context.clearRect(0, 0, width, height);
      const time = elapsed % CYCLE;
      const angle = (elapsed % 8) / 8 * Math.PI * 2;
      for (const source of sources) {
        const gradient = context.createConicGradient(angle, source.x, source.y);
        colors.forEach((color, index) => gradient.addColorStop(index / (colors.length - 1), color));
        context.strokeStyle = gradient;

        for (let emission = 0; emission <= EMIT_FOR / EMIT_EVERY; emission++) {
          const radius = (time - emission * EMIT_EVERY) * SPEED;
          if (radius <= 0 || radius + 4 < source.distance) continue;
          const alpha = START_ALPHA * Math.exp(-radius / FADE) * source.strength;
          if (alpha < 0.01) continue;
          context.beginPath();
          context.arc(source.x, source.y, radius, 0, Math.PI * 2);
          context.globalAlpha = alpha * 0.55;
          context.lineWidth = 7;
          context.stroke();
          context.globalAlpha = alpha;
          context.lineWidth = 2;
          context.stroke();
        }
      }
    };

    const resize = () => {
      const box = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      width = box.width;
      height = box.height;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      sources = reflectedSources(dot.offsetLeft, dot.offsetTop, width, height);
      if (motion.matches) draw(EMIT_FOR + 1.5);
    };

    let frame = 0;
    const began = performance.now();
    const tick = (now: number) => {
      draw((now - began) / 1000);
      frame = requestAnimationFrame(tick);
    };
    const updateMotion = () => {
      cancelAnimationFrame(frame);
      if (motion.matches) draw(EMIT_FOR + 1.5);
      else frame = requestAnimationFrame(tick);
    };

    resize();
    updateMotion();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    motion.addEventListener("change", updateMotion);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      motion.removeEventListener("change", updateMotion);
    };
  }, []);

  return <>
    <canvas ref={canvasRef} className="banner-waves" aria-hidden="true" />
    <span ref={dotRef} className="banner-dot" aria-hidden="true" />
  </>;
}
