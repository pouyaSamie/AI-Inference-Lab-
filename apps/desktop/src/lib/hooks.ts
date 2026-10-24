import { useCallback, useEffect, useRef, useState } from "react";

export interface Polled<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  lastSuccessAt: string | null;
  refresh: () => void;
}

export function usePolling<T>(load: () => Promise<T>, intervalMs: number, enabled = true, sourceKey?: unknown): Polled<T> {
  const [snapshot, setSnapshot] = useState<{ source: unknown; data: T | null; error: unknown; lastSuccessAt: string | null }>({ source: sourceKey, data: null, error: null, lastSuccessAt: null });
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;
  usePageRefresh(() => setNonce(value => value + 1));

  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let first = true;
    const run = async (): Promise<void> => {
      if (first) setLoading(true);
      try {
        const next = await loadRef.current();
        if (!stopped) setSnapshot({ source: sourceKey, data: next, error: null, lastSuccessAt: new Date().toISOString() });
      } catch (error) {
        if (!stopped) setSnapshot(previous => ({ source: sourceKey, data: Object.is(previous.source, sourceKey) ? previous.data : null, lastSuccessAt: Object.is(previous.source, sourceKey) ? previous.lastSuccessAt : null, error }));
      } finally {
        if (!stopped) { first = false; setLoading(false); timer = setTimeout(run, intervalMs); }
      }
    };
    void run();
    return () => { stopped = true; if (timer) clearTimeout(timer); };
  }, [enabled, intervalMs, nonce, sourceKey]);

  const sameSource = Object.is(snapshot.source, sourceKey);
  return {
    data: sameSource ? snapshot.data : null,
    error: sameSource ? snapshot.error : null,
    lastSuccessAt: sameSource ? snapshot.lastSuccessAt : null,
    loading: enabled && (!sameSource || loading),
    refresh: useCallback(() => setNonce(value => value + 1), []),
  };
}

/** Read-only page refresh signal; mutation and planning actions stay explicit. */
export function usePageRefresh(action: () => void) {
  const actionRef = useRef(action); actionRef.current = action;
  useEffect(() => {
    const refresh = () => actionRef.current();
    window.addEventListener("lab:refresh-page", refresh);
    return () => window.removeEventListener("lab:refresh-page", refresh);
  }, []);
}
