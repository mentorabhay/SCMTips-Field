/**
 * Live work board (T3.056): GET /v1/tasks -> five columns.
 *
 * Column rules (contract §2 statuses):
 *   open                          -> Open
 *   in_progress                   -> In progress (Blocked when a line is flagged)
 *   failed, awaiting_approval     -> Blocked, with the reason
 *   awaiting_posting              -> Waiting for SAP
 *   done                          -> Done today (finished today when the API reports a finish time)
 */
import type { Task } from "../api";
import { parseTime, plural, sameLocalDay, taskTypeLabel } from "./format";

export type ColumnId = "open" | "in_progress" | "blocked" | "waiting_sap" | "done";

export const COLUMN_ORDER: readonly ColumnId[] = ["open", "in_progress", "blocked", "waiting_sap", "done"];

export interface BoardCard {
  id: string;
  type: string;
  title: string;
  subtitle: string | null;
  progress: string | null;
  why: string | null;
}

export interface BoardColumn {
  id: ColumnId;
  name: string;
  count: number;
  cards: BoardCard[];
  note: string | null;
}

const LINE_DONE = new Set(["counted", "confirmed", "done"]);

const PROGRESS_NOUN: Record<string, [string, string]> = {
  receive: ["item", "items"],
  putaway: ["item", "items"],
  pick: ["stop", "stops"],
  count: ["bin", "bins"],
  audit: ["unit", "units"],
  swap: ["unit", "units"],
};

export function taskRef(t: Task): string {
  return t.title || t.ref_doc_no || t.erp_ref || "Untitled job";
}

export function progressText(t: Task): string | null {
  const total = t.lines.length;
  if (!total) return null;
  const done = t.lines.filter((l) => LINE_DONE.has(l.status)).length;
  const [one, many] = PROGRESS_NOUN[t.type] ?? ["line", "lines"];
  return `${done} of ${total} ${total === 1 ? one : many}`;
}

export function placeOf(t: Task): { column: ColumnId; why: string | null } {
  switch (t.status) {
    case "done":
      return { column: "done", why: null };
    case "awaiting_posting":
      return { column: "waiting_sap", why: null };
    case "failed":
      return { column: "blocked", why: t.reason || "Posting to SAP failed. See Postings to SAP." };
    case "awaiting_approval":
      return { column: "blocked", why: "Waiting for a decision. See Decisions." };
    case "in_progress":
    case "open": {
      const flagged = t.lines.find((l) => l.status === "flagged");
      if (flagged) {
        const where = flagged.bin ? `Bin ${flagged.bin}` : flagged.position ? flagged.position : `Line ${flagged.line_no}`;
        return { column: "blocked", why: `${where}: flagged by the operator` };
      }
      return { column: t.status === "open" ? "open" : "in_progress", why: null };
    }
    default:
      return { column: "open", why: `Status "${t.status}" is not known to the console yet` };
  }
}

export function finishedAt(t: Task): number | null {
  return parseTime(t.completed_at) ?? parseTime(t.updated_at);
}

export function buildBoard(tasks: readonly Task[], nowMs: number): BoardColumn[] {
  const cols: Record<ColumnId, BoardCard[]> = { open: [], in_progress: [], blocked: [], waiting_sap: [], done: [] };
  let doneWithoutTime = 0;
  for (const t of tasks) {
    const { column, why } = placeOf(t);
    if (column === "done") {
      const f = finishedAt(t);
      if (f === null) doneWithoutTime++;
      else if (!sameLocalDay(f, nowMs)) continue;
    }
    cols[column].push({
      id: t.id,
      type: t.type,
      title: `${taskTypeLabel(t.type)} · ${taskRef(t)}`,
      subtitle: t.subtitle || null,
      progress: progressText(t),
      why,
    });
  }
  const names: Record<ColumnId, string> = {
    open: "Open",
    in_progress: "In progress",
    blocked: "Blocked",
    waiting_sap: "Waiting for SAP",
    done: doneWithoutTime ? "Done" : "Done today",
  };
  return COLUMN_ORDER.map((id) => ({
    id,
    name: names[id],
    count: cols[id].length,
    cards: cols[id],
    note:
      id === "done" && doneWithoutTime
        ? "field-api does not report when jobs finished, so this shows every finished job it returns."
        : null,
  }));
}

/** Not done, i.e. still in someone's hands or waiting. */
export function isActive(t: Task): boolean {
  return t.status !== "done";
}

const TYPE_PLURAL: Record<string, [string, string]> = {
  receive: ["receipt", "receipts"],
  putaway: ["put-away", "put-aways"],
  pick: ["pick", "picks"],
  count: ["count", "counts"],
  audit: ["tower audit", "tower audits"],
  swap: ["swap", "swaps"],
};

/** "3 receipts · 6 picks · 5 counts" in a fixed type order. */
export function typeBreakdown(tasks: readonly Task[]): string {
  const counts = new Map<string, number>();
  for (const t of tasks) counts.set(t.type, (counts.get(t.type) ?? 0) + 1);
  const order = ["receive", "putaway", "pick", "count", "audit", "swap"];
  const keys = [...order.filter((k) => counts.has(k)), ...[...counts.keys()].filter((k) => !order.includes(k)).sort()];
  return keys
    .map((k) => {
      const n = counts.get(k) ?? 0;
      const [one, many] = TYPE_PLURAL[k] ?? [k, k];
      return plural(n, one, many);
    })
    .join(" · ");
}
