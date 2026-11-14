export default function LoadState({
  error,
  retry,
}: {
  error?: string;
  retry: () => void;
}) {
  return error ? (
    <div className="state error" role="alert">
      <h2>We couldn't load this space</h2>
      <p>{error}</p>
      <button onClick={retry}>Try again</button>
    </div>
  ) : (
    <div className="state" role="status">
      <span className="pulse" /> Loading your space...
    </div>
  );
}
