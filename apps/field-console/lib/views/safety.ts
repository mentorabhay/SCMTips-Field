/**
 * Who is on a structure (T4.046 / SCR4.13): GET /v1/safety/active-visits -> banners.
 *
 * Copy: SCR4.13 "Overdue check-in at {site}", MSG4.10 "{who} at {site} has not checked in for {n} min.
 * Last altitude {h} m. Follow the site emergency procedure." The API gives a user id, not a name, so
 * the id is shown as is.
 */
import type { ActiveVisit } from "../api";
import { clock, minutesSince, qty, relativeTime } from "./format";

export type BannerTone = "alert" | "warn";

export interface SafetyBanner {
  visitId: string;
  siteId: string;
  tone: BannerTone;
  headline: string;
  body: string;
  /** True when a supervisor acknowledgement is still needed (POST /v1/safety/visits/{id}/ack). */
  needsAck: boolean;
}

const ON_STRUCTURE = new Set(["on_structure", "overdue", "escalated"]);

export function siteLabel(v: ActiveVisit): string {
  return v.site_code || v.site_name || "a site";
}

export function safetyBanner(v: ActiveVisit, nowMs: number): SafetyBanner | null {
  if (!ON_STRUCTURE.has(v.status)) return null;
  const site = siteLabel(v);
  const who = v.user_id;
  const mins = minutesSince(v.last_heartbeat_at, nowMs);
  const alt = typeof v.last_altitude_m === "number" ? qty(v.last_altitude_m) : null;
  const escalated = v.status === "escalated" || v.is_escalated === true;
  if (escalated && !v.is_acknowledged) {
    return {
      visitId: v.visit_id,
      siteId: v.site_id,
      tone: "alert",
      headline: `Overdue check-in at ${site}`,
      body:
        `${who} at ${site} has not checked in for ${mins ?? "?"} min.` +
        (alt !== null ? ` Last altitude ${alt} m.` : "") +
        " Follow the site emergency procedure.",
      needsAck: true,
    };
  }
  if (escalated) {
    return {
      visitId: v.visit_id,
      siteId: v.site_id,
      tone: "warn",
      headline: `${who} at ${site}: escalation acknowledged`,
      body: `Last check-in ${relativeTime(v.last_heartbeat_at, nowMs).toLowerCase()}. Keep following the site procedure until they check in.`,
      needsAck: false,
    };
  }
  if (v.status === "overdue") {
    return {
      visitId: v.visit_id,
      siteId: v.site_id,
      tone: "warn",
      headline: `${who} is overdue on ${site}`,
      body: `No check-in for ${mins ?? "?"} min. If there is still no check-in, this escalates to you.`,
      needsAck: false,
    };
  }
  const due = typeof v.timer_remaining_s === "number" ? ` · next check-in due in ${clock(v.timer_remaining_s)}` : "";
  return {
    visitId: v.visit_id,
    siteId: v.site_id,
    tone: "warn",
    headline: `${who} is on ${site}`,
    body:
      `Last check-in ${relativeTime(v.last_heartbeat_at, nowMs).toLowerCase()}` +
      (alt !== null ? ` at ${alt} m` : "") +
      (v.tower_fl ? ` · ${v.tower_fl}` : "") +
      due,
    needsAck: false,
  };
}

/** Alerts first, then the rest, keeping API order inside each group. */
export function safetyBanners(visits: readonly ActiveVisit[], nowMs: number): SafetyBanner[] {
  const out = visits.map((v) => safetyBanner(v, nowMs)).filter((b): b is SafetyBanner => b !== null);
  return [...out.filter((b) => b.tone === "alert"), ...out.filter((b) => b.tone !== "alert")];
}
