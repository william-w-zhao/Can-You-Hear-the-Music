import type { Detection } from "../api";

export default function EvidenceImage({ src, width, height, label, boxes, viewport, activeBox, onBoxPreview, onBoxSelect }: {
  src: string;
  width: number;
  height: number;
  label: string;
  boxes: Detection[];
  viewport?: [number, number, number, number];
  activeBox?: number;
  onBoxPreview?: (index?: number) => void;
  onBoxSelect?: (index: number) => void;
}) {
  const entries = boxes.map((box, index) => ({ box, index }));
  if (onBoxPreview) {
    const area = ({ box_px: [left, top, right, bottom] }: Detection) => (right - left) * (bottom - top);
    // Draw smaller boxes on top so a box inside a larger detection can still be targeted.
    entries.sort((a, b) => area(b.box) - area(a.box));
  }
  return (
    <svg className="evidence-image" role={onBoxSelect ? "group" : "img"} aria-label={label}
      viewBox={(viewport ?? [0, 0, width, height]).join(" ")}>
      <image href={src} width={width} height={height} />
      {entries.map(({ box: { label, confidence, needs_review, box_px: [left, top, right, bottom] }, index }) => (
        <rect key={index} x={left} y={top} width={right - left} height={bottom - top}
          className={`evidence-box${onBoxSelect ? " interactive" : ""}${needs_review ? " uncertain" : ""}${index === activeBox ? " active" : ""}`}
          role={onBoxSelect ? "button" : undefined} tabIndex={onBoxSelect ? 0 : undefined}
          aria-label={onBoxSelect ? `${label}, ${Math.round(confidence * 100)}% model score` : undefined}
          onPointerEnter={() => onBoxPreview?.(index)} onPointerLeave={() => onBoxPreview?.()}
          onFocus={() => onBoxPreview?.(index)} onBlur={() => onBoxPreview?.()}
          onClick={() => onBoxSelect?.(index)}
          onKeyDown={(event) => {
            if (onBoxSelect && (event.key === "Enter" || event.key === " ")) {
              event.preventDefault();
              onBoxSelect(index);
            }
          }}
          vectorEffect="non-scaling-stroke">
          <title>{label} · {Math.round(confidence * 100)}% model score</title>
        </rect>
      ))}
    </svg>
  );
}
