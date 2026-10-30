"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { POLL_MS } from "@/lib/config";

export type PollState<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ok"; data: T; at: number }
  /** data/at: the last good answer, kept on screen with the error. */
  | { status: "error"; error: ApiError; data?: T; at?: number };

function asApiError(e: unknown): ApiError {
  if (e instanceof ApiError) return e;
  return new ApiError("unexpected", null, null, e instanceof Error ? e.message : "Something went wrong.", null);
}

/**
 * Runs `load` now and every `intervalMs` while `enabled`; never two at once; skips ticks while the
 * tab is hidden. `key` restarts polling when it changes.
 */
export function usePoll<T>(load: () => Promise<T>, opts: { enabled: boolean; key?: string; intervalMs?: number }) {
  const { enabled, key = "", intervalMs = POLL_MS } = opts;
  const [state, setState] = useState<PollState<T>>(enabled ? { status: "loading" } : { status: "idle" });
  const loadRef = useRef(load);
  loadRef.current = load;
  const busy = useRef(false);
  /** Bumped on every (re)start, so an answer from an earlier key or an unmounted view is dropped. */
  const gen = useRef(0);

  const run = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    const mine = gen.current;
    try {
      const data = await loadRef.current();
      if (mine === gen.current) setState({ status: "ok", data, at: Date.now() });
    } catch (e) {
      if (mine === gen.current) {
        const error = asApiError(e);
        setState((prev) =>
          prev.status === "ok" || prev.status === "error"
            ? { status: "error", error, data: prev.data, at: prev.at }
            : { status: "error", error },
        );
      }
    } finally {
      busy.current = false;
    }
  }, []);

  useEffect(() => {
    gen.current++;
    busy.current = false;
    if (!enabled) {
      setState({ status: "idle" });
      return;
    }
    setState({ status: "loading" });
    void run();
    const t = setInterval(() => {
      if (typeof document === "undefined" || document.visibilityState !== "hidden") void run();
    }, intervalMs);
    return () => {
      gen.current++;
      clearInterval(t);
    };
  }, [enabled, key, intervalMs, run]);

  return { state, refresh: run };
}

export function dataOf<T>(s: PollState<T>): T | undefined {
  return s.status === "ok" ? s.data : s.status === "error" ? s.data : undefined;
}

/** PollState -> the summary-card input: data (also the last good data on error), loading, or a reason. */
export function toAvail<T>(s: PollState<T>, role: string): { data: T } | { error: string } | { loading: true } {
  if (s.status === "ok") return { data: s.data };
  if (s.status === "loading") return { loading: true };
  if (s.status === "idle") return { error: `Needs the ${role} role` };
  if (s.error.kind === "forbidden") return { error: `Needs the ${role} role` };
  if (s.data !== undefined) return { data: s.data };
  return { error: s.error.title };
}

/** Current time, refreshed every `everyMs` (for "3 min ago" texts and timers). */
export function useNow(everyMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), everyMs);
    return () => clearInterval(t);
  }, [everyMs]);
  return now;
}
