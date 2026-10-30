/** Small, pure formatting helpers shared by the view mappers. */

export function parseTime(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : null;
}

/** "Just now", "3 min ago", "2 hours ago", "4 days ago"; "Never" when there is no time. */
export function relativeTime(iso: string | null | undefined, nowMs: number): string {
  const t = parseTime(iso);
  if (t === null) return "Never";
  const s = Math.max(0, Math.round((nowMs - t) / 1000));
  if (s < 60) return "Just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} ${h === 1 ? "hour" : "hours"} ago`;
  const d = Math.floor(h / 24);
  return `${d} days ago`;
}

export function minutesSince(iso: string | null | undefined, nowMs: number): number | null {
  const t = parseTime(iso);
  return t === null ? null : Math.max(0, Math.floor((nowMs - t) / 60000));
}

/** "4:05" for 245 seconds; never negative. */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function plural(n: number, one: string, many: string = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function toNumber(v: number | string | null | undefined): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

/** 12 -> "12", 12.5 -> "12.5", 1.0004 -> "1". */
export function qty(n: number): string {
  return String(Math.round(n * 1000) / 1000);
}

export function sameLocalDay(aMs: number, bMs: number): boolean {
  const a = new Date(aMs);
  const b = new Date(bMs);
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

export const TASK_TYPE_LABEL: Record<string, string> = {
  receive: "Receive",
  putaway: "Put away",
  pick: "Pick",
  count: "Count",
  audit: "Tower audit",
  swap: "Swap unit",
};

export function taskTypeLabel(type: string): string {
  return TASK_TYPE_LABEL[type] ?? type.charAt(0).toUpperCase() + type.slice(1);
}
