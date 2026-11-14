import { useEffect, useState } from "react";

// Keyed state prevents a prior room/scan flashing while the next request starts.
export function useData<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{ key: string; data?: T; error?: string }>(
    { key },
  );
  useEffect(() => {
    const controller = new AbortController();
    setState({ key });
    load(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ key, data });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setState({
            key,
            error: error instanceof Error ? error.message : String(error),
          });
      });
    return () => controller.abort();
    // The caller's key identifies all request inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);
  return {
    ...(state.key === key ? state : {}),
    retry: () => setAttempt((n) => n + 1),
  };
}
