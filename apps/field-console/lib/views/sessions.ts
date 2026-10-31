/**
 * Field Assistant sessions (M3 contract §4/§5, console track P): GET /v1/assistant/sessions and
 * GET /v1/assistant/sessions/{id} -> list rows and a turn-by-turn transcript; site mode -> sandbox badges.
 *
 * Heard / said text and photos are purged by the worker after 30 days, so missing text is normal and shown
 * as such, never as an error.
 */
import type { AssistantSession, AssistantSessionWithTurns, AssistantTurnRecord, Site, Task } from "../api";
import { parseTime, relativeTime, toNumber } from "./format";

// ------------------------------------------------------------------ site mode

export function isSandbox(site: Pick<Site, "mode"> | null | undefined): boolean {
  return site?.mode === "sandbox";
}

/** Ids of the sandbox sites in the list (for badges on tasks and sessions). */
export function sandboxSiteIds(sites: readonly Site[] | null | undefined): Set<string> {
  return new Set((sites ?? []).filter(isSandbox).map((s) => s.id));
}

/** True when the task's site is a sandbox site. */
export function taskIsSandbox(t: Pick<Task, "site_id">, sandbox: ReadonlySet<string>): boolean {
  return sandbox.has(t.site_id);
}

// ------------------------------------------------------------------ formatting

/** AI costs are fractions of a cent per turn: "$0.0021" below a dollar, "$1.25" above; "—" when unknown. */
export function costText(v: number | string | null | undefined): string {
  const n = toNumber(v);
  if (n === null) return "—";
  if (n === 0) return "$0";
  return n < 1 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`;
}

/** "4 min", "1 h 05 min", "running" when not ended. */
export function durationText(startIso: string, endIso: string | null | undefined, nowMs: number): string {
  const a = parseTime(startIso);
  const b = endIso ? parseTime(endIso) : null;
  if (a === null) return "—";
  if (!endIso) return `running · ${Math.max(0, Math.floor((nowMs - a) / 60000))} min so far`;
  if (b === null) return "—";
  const m = Math.max(0, Math.round((b - a) / 60000));
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}

const EVENT_LABEL: Record<string, string> = {
  session_start: "Session start",
  utterance: "Heard",
  scan: "Scan",
  unknown_code: "Unknown code",
  photo: "Photo",
  step_done: "Step done",
  pause: "Paused",
  resume: "Resumed",
  session_end: "Session end",
};

export function eventLabel(e: string): string {
  return EVENT_LABEL[e] ?? e;
}

/** The phone-side actions of a turn, in words: "open task t-1 · command post · listen free". */
export function actionSummary(actions: unknown): string {
  if (!Array.isArray(actions) || actions.length === 0) return "";
  return actions
    .map((a) => {
      if (!a || typeof a !== "object") return null;
      const o = a as Record<string, unknown>;
      const str = (k: string) => (typeof o[k] === "string" || typeof o[k] === "number" ? String(o[k]) : "");
      switch (o.type) {
        case "open_task":
          return `open task ${str("task_id")}`.trim();
        case "command":
          return `command ${str("command")}${o.value !== undefined && o.value !== null ? ` ${str("value")}` : ""}`.trim();
        case "refresh_task":
          return `refresh task ${str("task_id")}${o.focus_code ? ` (code ${str("focus_code")})` : ""}`.trim();
        case "listen":
          return `listen ${str("mode")}`.trim();
        default:
          return typeof o.type === "string" ? o.type : null;
      }
    })
    .filter((x): x is string => Boolean(x))
    .join(" · ");
}

// ------------------------------------------------------------------ list

export interface SessionRow {
  id: string;
  siteId: string;
  siteLabel: string;
  sandbox: boolean;
  who: string;
  started: string;
  startedMs: number;
  duration: string;
  active: boolean;
  turns: number;
  documents: string[];
  cost: string;
  csvPath: string;
}

export function sessionCsvPath(id: string): string {
  return `/v1/assistant/sessions/${encodeURIComponent(id)}/export.csv`;
}

/** One row per session, newest first. A site the list does not know is shown by its id. */
export function buildSessionRows(sessions: readonly AssistantSession[], sites: readonly Site[], nowMs: number): SessionRow[] {
  const byId = new Map(sites.map((s) => [s.id, s]));
  return sessions
    .map((s) => {
      const site = byId.get(s.site_id);
      const startedMs = parseTime(s.started_at) ?? 0;
      return {
        id: s.id,
        siteId: s.site_id,
        siteLabel: site ? (site.name && site.name !== site.code ? `${site.code} · ${site.name}` : site.code) : s.site_id,
        sandbox: isSandbox(site) || s.mode === "sandbox",
        who: s.principal_id,
        started: relativeTime(s.started_at, nowMs),
        startedMs,
        duration: durationText(s.started_at, s.ended_at, nowMs),
        active: !s.ended_at,
        turns: typeof s.turns === "number" ? s.turns : 0,
        documents: Array.isArray(s.documents) ? s.documents.filter((d) => typeof d === "string" && d) : [],
        cost: costText(s.cost_usd),
        csvPath: sessionCsvPath(s.id),
      };
    })
    .sort((a, b) => b.startedMs - a.startedMs || a.id.localeCompare(b.id));
}

/** "3 sessions · 2 sandbox · $0.0123 AI cost" */
export function sessionsSummary(rows: readonly SessionRow[], sessions: readonly AssistantSession[]): string {
  const sandbox = rows.filter((r) => r.sandbox).length;
  const total = sessions.reduce((sum, s) => sum + (toNumber(s.cost_usd) ?? 0), 0);
  return [`${rows.length} ${rows.length === 1 ? "session" : "sessions"}`, sandbox ? `${sandbox} sandbox` : null, `${costText(total)} AI cost`]
    .filter(Boolean)
    .join(" · ");
}

// ------------------------------------------------------------------ detail

export interface PhotoLink {
  /** A field-api path the console downloads with the sign-in token; null when the ref is not a path. */
  path: string | null;
  ref: string;
}

export interface TurnRow {
  id: string;
  at: string;
  atMs: number;
  event: string;
  eventLabel: string;
  heard: string | null;
  said: string | null;
  actions: string;
  code: string | null;
  photo: PhotoLink | null;
  ai: "AI" | "Rules" | null;
  cost: string;
  latency: string | null;
  /** Heard/said gone (30-day purge) on a turn that would have had text. */
  purged: boolean;
}

const HAS_TEXT = new Set(["utterance", "session_start", "unknown_code", "photo", "scan", "resume", "step_done"]);

export function photoLink(ref: string | null | undefined): PhotoLink | null {
  if (!ref) return null;
  return { path: ref.startsWith("/v1/") ? ref : null, ref };
}

export function turnRows(turns: readonly AssistantTurnRecord[]): TurnRow[] {
  return turns
    .map((t) => {
      const heard = t.heard?.trim() || null;
      const said = t.said?.trim() || null;
      return {
        id: t.id,
        at: t.at,
        atMs: parseTime(t.at) ?? 0,
        event: t.event,
        eventLabel: eventLabel(t.event),
        heard,
        said,
        actions: actionSummary(t.actions),
        code: t.code || null,
        photo: photoLink(t.photo_ref),
        ai: t.ai === "model" ? ("AI" as const) : t.ai === "rules" ? ("Rules" as const) : null,
        cost: costText(t.cost_usd),
        latency: typeof t.latency_ms === "number" ? `${t.latency_ms} ms` : null,
        purged: !heard && !said && HAS_TEXT.has(t.event),
      };
    })
    .sort((a, b) => a.atMs - b.atMs || a.id.localeCompare(b.id));
}

export interface SessionDetailView {
  id: string;
  title: string;
  sandbox: boolean;
  documents: string[];
  turns: TurnRow[];
  aiTurns: number;
  rulesTurns: number;
  cost: string;
  csvPath: string;
}

export function sessionDetail(s: AssistantSessionWithTurns, sites: readonly Site[], nowMs: number): SessionDetailView {
  const site = sites.find((x) => x.id === s.site_id);
  const rows = turnRows(s.turns);
  const label = site?.code ?? s.site_id;
  return {
    id: s.id,
    title: `${s.principal_id} at ${label} · ${durationText(s.started_at, s.ended_at, nowMs)}`,
    sandbox: isSandbox(site) || s.mode === "sandbox",
    documents: Array.isArray(s.documents) ? s.documents.filter((d) => typeof d === "string" && d) : [],
    turns: rows,
    aiTurns: rows.filter((r) => r.ai === "AI").length,
    rulesTurns: rows.filter((r) => r.ai === "Rules").length,
    cost: costText(s.cost_usd ?? s.turns.reduce((sum, t) => sum + (toNumber(t.cost_usd) ?? 0), 0)),
    csvPath: sessionCsvPath(s.id),
  };
}
