// A spinning ring with a short label. Screen readers hear the label as a live status update.
export default function Spinner({ label, size = "medium", overlay = false }: {
  label?: string;
  size?: "small" | "medium" | "large";
  overlay?: boolean;
}) {
  return (
    <span className={`spinner spinner-${size}${overlay ? " spinner-overlay" : ""}`} role="status" aria-live="polite">
      <span className="spinner-ring" aria-hidden="true" />
      {label ? <span className="spinner-label">{label}</span> : <span className="visually-hidden">Loading</span>}
    </span>
  );
}

// Full-width loading state for a page or panel.
export function LoadingBlock({ label }: { label: string }) {
  return <div className="loading-block"><Spinner label={label} size="large" /></div>;
}
