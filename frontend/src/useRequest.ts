import { useCallback, useEffect, useState } from "react";

type RequestState<T> =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; data: T };

export function useRequest<T>(load: () => Promise<T>) {
  const [state, setState] = useState<RequestState<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    void load().then(
      (data) => { if (active) setState({ status: "ready", data }); },
      () => { if (active) setState({ status: "error" }); },
    );
    return () => { active = false; };
  }, [load, attempt]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  return { state, retry };
}
