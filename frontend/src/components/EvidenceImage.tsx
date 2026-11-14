import type { Detection } from "../api";

export type EvidenceBox = Detection & {
  color?: string;        // group colour; boxes of one object share a colour across views
  selected?: boolean;    // chosen for merging
  tag?: string;          // short text drawn above the box
};

export default function EvidenceImage({ src, width, height, label, boxes, viewport, activeBox, onBoxPreview, onBoxSelect }: {
  src: string;
  width: number;
  height: number;
  label: string;
  boxes: EvidenceBox[];
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
  const [vx, vy, vw] = viewport ?? [0, 0, width, height];
  const fontSize = vw / 26;
  return (
    <svg className="evidence-image" role={onBoxSelect ? "group" : "img"} aria-label={label}
      viewBox={(viewport ?? [0, 0, width, height]).join(" ")}>
      <image href={src} width={width} height={height} />
      {entries.map(({ box: { label, confidence, needs_review, color, selected, tag, box_px: [left, top, right, bottom] }, index }) => {
        const classes = ["evidence-box", onBoxSelect && "interactive", needs_review && "uncertain",
          index === activeBox && "active", selected && "selected"].filter(Boolean).join(" ");
        return (
          <g key={index}>
            <rect x={left} y={top} width={right - left} height={bottom - top} className={classes}
              style={color ? { stroke: color } : undefined}
              role={onBoxSelect ? "button" : undefined} tabIndex={onBoxSelect ? 0 : undefined}
              aria-pressed={onBoxSelect ? Boolean(selected) : undefined}
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
            {tag && (index === activeBox || selected) && (
              <text x={Math.max(left, vx + 2)} y={Math.max(top - fontSize * 0.35, vy + fontSize)} className="evidence-tag"
                style={{ fontSize, fill: color }} pointerEvents="none">{tag}</text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
