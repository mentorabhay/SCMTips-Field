/** Test-only helpers: an injected fetch that records calls and answers from a script. No network. */
import type { Task, TaskLine } from "../lib/api";

export interface Call {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

export type Reply = { status: number; body?: unknown; text?: string } | Error;

export function scriptedFetch(replies: Reply[] | ((c: Call) => Reply)) {
  const calls: Call[] = [];
  const queue = Array.isArray(replies) ? [...replies] : null;
  const fetchImpl = async (url: string, init?: RequestInit): Promise<Response> => {
    const headers = { ...((init?.headers ?? {}) as Record<string, string>) };
    const call: Call = {
      url,
      method: init?.method ?? "GET",
      headers,
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
    };
    calls.push(call);
    const r = queue ? queue.shift() : (replies as (c: Call) => Reply)(call);
    if (!r) throw new Error(`no scripted reply for ${call.method} ${url}`);
    if (r instanceof Error) throw r;
    const text = r.text ?? (r.body === undefined ? "" : JSON.stringify(r.body));
    return new Response(text === "" ? null : text, { status: r.status, headers: { "Content-Type": "application/json" } });
  };
  return { fetchImpl, calls };
}

let n = 0;
export function line(p: Partial<TaskLine> = {}): TaskLine {
  n++;
  return { id: `line-${n}`, line_no: n * 10, status: "open", ...p };
}

export function task(p: Partial<Task> = {}): Task {
  n++;
  return { id: `task-${n}`, type: "receive", status: "open", title: `Delivery 18000000${n}`, site_id: "site-1", lines: [], ...p };
}

export const NOW = Date.parse("2026-10-31T12:00:00Z");
export const iso = (msAgo: number) => new Date(NOW - msAgo).toISOString();
export const MIN = 60_000;
export const HOUR = 60 * MIN;
