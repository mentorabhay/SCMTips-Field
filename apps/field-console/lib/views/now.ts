/**
 * Right now (home): four summary cards built from the same lists the other views use.
 * Each input is either data or the plain-English reason it is not available (error, no permission).
 */
import type { Device, QueueSummary, Task } from "../api";
import { isActive, typeBreakdown } from "./board";
import type { DecisionCase } from "./decisions";
import { plural } from "./format";

export type Avail<T> = { data: T } | { error: string } | { loading: true };

export type CardTone = "ink" | "warn" | "ok" | "muted";

export interface SummaryCard {
  id: "work" | "decide" | "post" | "devices";
  label: string;
  value: string;
  note: string;
  tone: CardTone;
  href: string;
}

function unavailable(id: SummaryCard["id"], label: string, href: string, a: { error: string } | { loading: true }): SummaryCard {
  return "loading" in a
    ? { id, label, value: "…", note: "Loading…", tone: "muted", href }
    : { id, label, value: "—", note: a.error, tone: "muted", href };
}

export function workCard(tasks: Avail<readonly Task[]>): SummaryCard {
  const label = "Work in progress";
  if (!("data" in tasks)) return unavailable("work", label, "/work", tasks);
  const active = tasks.data.filter(isActive);
  return {
    id: "work",
    label,
    value: String(active.length),
    note: active.length ? typeBreakdown(active) : "No open jobs",
    tone: "ink",
    href: "/work",
  };
}

export function decideCard(cases: Avail<readonly DecisionCase[]>, nowMs: number): SummaryCard {
  const label = "Needs a decision";
  if (!("data" in cases)) return unavailable("decide", label, "/decisions", cases);
  const n = cases.data.length;
  if (!n) return { id: "decide", label, value: "0", note: "Nothing waiting", tone: "ok", href: "/decisions" };
  const oldest = Math.min(...cases.data.map((c) => c.createdMs ?? nowMs));
  const hours = Math.floor(Math.max(0, nowMs - oldest) / 3600000);
  const high = cases.data.filter((c) => c.severity === "High").length;
  const parts = [high ? `${high} high` : null, hours >= 1 ? `oldest waiting ${plural(hours, "hour")}` : null].filter(Boolean);
  return { id: "decide", label, value: String(n), note: parts.join(" · ") || "All new in the last hour", tone: "warn", href: "/decisions" };
}

export function postCard(queues: Avail<readonly QueueSummary[]>): SummaryCard {
  const label = "Blocked postings";
  if (!("data" in queues)) return unavailable("post", label, "/postings", queues);
  const blocked = queues.data.filter((q) => q.is_blocked).length;
  const waiting = queues.data.reduce((s, q) => s + q.pending_count + q.running_count, 0);
  if (!blocked) {
    return { id: "post", label, value: "0", note: waiting ? `All queues moving · ${waiting} waiting to post` : "All queues clear", tone: "ok", href: "/postings" };
  }
  return { id: "post", label, value: String(blocked), note: `${plural(blocked, "queue")} waiting for you; the others keep going`, tone: "warn", href: "/postings" };
}

export function devicesCard(devices: Avail<readonly Device[]>): SummaryCard {
  const label = "Devices";
  if (!("data" in devices)) return unavailable("devices", label, "/devices", devices);
  const active = devices.data.filter((d) => d.status !== "revoked" && !d.revoked_at);
  const stale = active.filter((d) => d.is_stale).length;
  return {
    id: "devices",
    label,
    value: String(active.length),
    note: !active.length ? "No devices registered" : stale ? `${stale} not seen for 15 min or more` : "All seen in the last 15 min",
    tone: "ink",
    href: "/devices",
  };
}
