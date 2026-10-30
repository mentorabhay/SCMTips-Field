/**
 * Inventory accuracy (T3.059, SCR3.04): pure mapping from GET /v1/tasks (count jobs) and
 * GET /v1/approval-requests?status=pending (count differences beyond tolerance).
 *
 * Honest scope: counts are blind, so the console never sees book quantities for a line.
 * A difference is only visible here when it went to a decision. Differences inside
 * tolerance post 701/702 straight to SAP and are not counted as mismatches on this page.
 */
import type { ApprovalRequest, Task, TaskLine } from "../api";
import { countDifference } from "./decisions";

export interface AccuracyRow {
  taskId: string;
  bin: string;
  material: string;
  state: "not counted" | "counted" | "difference waiting" | "flagged";
  difference: number | null;
  uom: string | null;
}

export interface AccuracySummary {
  countJobs: number;
  linesTotal: number;
  linesCounted: number;
  differencesWaiting: number;
  /** Counted lines with no open difference, 0..1. Null when nothing has been counted yet. */
  matchRate: number | null;
  rows: AccuracyRow[];
}

function isCounted(l: TaskLine): boolean {
  return (l.counted_qty !== null && l.counted_qty !== undefined) || l.status === "counted" || l.status === "done";
}

function isCountApproval(a: ApprovalRequest, countTaskIds: ReadonlySet<string>): boolean {
  if (a.status !== "pending") return false;
  if (a.task_id && countTaskIds.has(a.task_id)) return true;
  return /count|inventory|physical/i.test(a.approval_type ?? "");
}

export function buildAccuracy(tasks: readonly Task[], approvals: readonly ApprovalRequest[]): AccuracySummary {
  const counts = tasks.filter((t) => t.type === "count");
  const ids = new Set(counts.map((t) => t.id));
  const waiting = approvals.filter((a) => isCountApproval(a, ids));
  const waitingByBin = new Map<string, ApprovalRequest>();
  for (const a of waiting) waitingByBin.set(`${a.task_id ?? ""}|${a.bin ?? ""}`, a);

  const rows: AccuracyRow[] = [];
  let linesCounted = 0;
  let countedWithDiff = 0;
  for (const t of counts) {
    for (const l of t.lines) {
      const bin = l.bin ?? "?";
      const a = waitingByBin.get(`${t.id}|${bin}`);
      const counted = isCounted(l);
      if (counted) linesCounted++;
      if (counted && a) countedWithDiff++;
      const state: AccuracyRow["state"] =
        l.status === "flagged" ? "flagged" : a ? "difference waiting" : counted ? "counted" : "not counted";
      rows.push({
        taskId: t.id,
        bin,
        material: [l.material, l.description].filter(Boolean).join(" · ") || "?",
        state,
        difference: a ? countDifference(a) : null,
        uom: l.uom ?? a?.uom ?? null,
      });
    }
  }
  rows.sort((x, y) => x.bin.localeCompare(y.bin) || x.material.localeCompare(y.material));
  return {
    countJobs: counts.length,
    linesTotal: rows.length,
    linesCounted,
    differencesWaiting: waiting.length,
    matchRate: linesCounted === 0 ? null : (linesCounted - countedWithDiff) / linesCounted,
    rows,
  };
}

export function percent(rate: number | null): string {
  return rate === null ? "Nothing counted yet" : `${Math.round(rate * 1000) / 10}%`;
}
