/**
 * Sites and towers (T4.065 / T4.066 / T4.046): GET /v1/sites + audit tasks from GET /v1/tasks +
 * GET /v1/audits/{task_id}/progress + GET /v1/safety/active-visits -> one row per site.
 *
 * Copy: SCR4.09 "{n} of {m} captured"; SCR1.02 empty "No sites yet".
 */
import type { ActiveVisit, AuditProgress, Site, Task } from "../api";
import { relativeTime } from "./format";
import { safetyBanner, type SafetyBanner } from "./safety";

export type TagTone = "alert" | "climb" | "done" | "progress" | "planned" | "neutral";

export interface SectorBar {
  label: string;
  text: string;
  pct: number;
  complete: boolean;
}

export interface SiteRow {
  siteId: string;
  code: string;
  name: string;
  kind: string;
  who: string;
  sectors: SectorBar[];
  auditNote: string | null;
  tag: { text: string; tone: TagTone };
  banners: SafetyBanner[];
}

export interface AuditInput {
  task: Task;
  /** null when the progress call failed or has not answered yet. */
  progress: AuditProgress | null;
}

export function sectorLabel(code: string, tower: string | null): string {
  const base = /^sector\b/i.test(code) ? code : `Sector ${code}`;
  return tower ? `${tower} · ${base}` : base;
}

export function sectorBars(p: AuditProgress): SectorBar[] {
  const towers = p.towers.filter((t) => t.sectors.length > 0);
  const many = towers.length > 1;
  const out: SectorBar[] = [];
  for (const t of towers) {
    for (const s of t.sectors) {
      const m = Math.max(0, s.expected_count);
      const n = Math.min(Math.max(0, s.captured_count), m);
      out.push({
        label: sectorLabel(s.code, many ? t.code : null),
        text: `${n} of ${m} captured`,
        pct: m === 0 ? 0 : Math.round((n / m) * 100),
        complete: m > 0 && n === m,
      });
    }
  }
  return out;
}

/** Prefer an audit that is not finished; otherwise the first one. */
export function pickAudit(audits: readonly AuditInput[]): AuditInput | null {
  return audits.find((a) => a.task.status !== "done") ?? audits[0] ?? null;
}

const ON_SITE = new Set(["checked_in", "on_structure", "overdue", "escalated"]);

export function buildSiteRows(
  sites: readonly Site[],
  audits: readonly AuditInput[],
  visits: readonly ActiveVisit[],
  nowMs: number,
): SiteRow[] {
  const known = new Map(sites.map((s) => [s.id, s]));
  // A visit or audit for a site the list did not return (scope, paging) still gets a row.
  const ids = new Set<string>([...sites.map((s) => s.id), ...audits.map((a) => a.task.site_id), ...visits.map((v) => v.site_id)]);
  const rows: SiteRow[] = [];
  for (const id of ids) {
    const site = known.get(id);
    const vs = visits.filter((v) => v.site_id === id && ON_SITE.has(v.status));
    const audit = pickAudit(audits.filter((a) => a.task.site_id === id));
    const bars = audit?.progress ? sectorBars(audit.progress) : [];
    const banners = vs.map((v) => safetyBanner(v, nowMs)).filter((b): b is SafetyBanner => b !== null);

    let auditNote: string | null = null;
    if (audit && !audit.progress) auditNote = "Audit progress is not available right now.";
    else if (audit && bars.length === 0) auditNote = "This audit has no expected units yet.";

    const alert = vs.some((v) => (v.status === "escalated" || v.is_escalated) && !v.is_acknowledged);
    const climbing = vs.some((v) => v.status === "on_structure" || v.status === "overdue" || v.status === "escalated");
    const allDone = bars.length > 0 && bars.every((b) => b.complete);
    const anyCaptured = bars.some((b) => b.pct > 0);
    const tag: SiteRow["tag"] = alert
      ? { text: "Overdue check-in", tone: "alert" }
      : climbing
        ? { text: "Climbing", tone: "climb" }
        : vs.length
          ? { text: "On site", tone: "climb" }
          : allDone
            ? { text: "Audit complete", tone: "done" }
            : anyCaptured
              ? { text: "Audit in progress", tone: "progress" }
              : audit
                ? { text: "Audit planned", tone: "planned" }
                : { text: "No audit open", tone: "neutral" };

    let who: string;
    if (vs.length) {
      who = vs
        .map((v) => {
          const where = v.status === "checked_in" ? "on site" : "on the structure";
          return `${v.user_id} ${where} · last check-in ${relativeTime(v.last_heartbeat_at, nowMs).toLowerCase()}`;
        })
        .join("; ");
    } else if (audit?.task.status === "done") {
      who = "Audit finished · nobody on site";
    } else {
      who = "Nobody on site";
    }

    rows.push({
      siteId: id,
      code: site?.code ?? vs[0]?.site_code ?? "Unknown site",
      name: site?.name ?? vs[0]?.site_name ?? "",
      kind: site?.kind ?? "",
      who,
      sectors: bars,
      auditNote,
      tag,
      banners,
    });
  }
  const rank = (r: SiteRow) => (r.tag.tone === "alert" ? 0 : r.tag.tone === "climb" ? 1 : r.sectors.length || r.auditNote ? 2 : 3);
  return rows.sort((a, b) => rank(a) - rank(b) || a.code.localeCompare(b.code));
}
