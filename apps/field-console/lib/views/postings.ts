/**
 * Postings to SAP (T3.060): GET /v1/posting-queues, and for each blocked queue
 * GET /v1/posting-queues/{key}/jobs to find the head job and retry it (POST /v1/posting-jobs/{id}/retry).
 *
 * Queue keys come from field-api staging: IBD:<delivery> (goods receipt), OBD:<delivery> (goods issue),
 * PID:<doc> (inventory difference), REV:<matdoc> (reversal), QM:<hu> (quality release).
 */
import type { PostingJob, QueueSummary } from "../api";
import { plural, relativeTime } from "./format";

export type QueueTone = "ok" | "blocked" | "busy";

export interface QueueRow {
  key: string;
  name: string;
  detail: string;
  message: string;
  tone: QueueTone;
  blocked: boolean;
  headJobId: string | null;
}

const PREFIX: Record<string, { name: string; doc: string }> = {
  IBD: { name: "Inbound delivery", doc: "Goods receipt" },
  OBD: { name: "Outbound delivery", doc: "Goods issue" },
  PID: { name: "Count document", doc: "Inventory difference" },
  REV: { name: "Reversal of material document", doc: "Reversal" },
  QM: { name: "Quality release, handling unit", doc: "Stock release" },
  TWR: { name: "Tower", doc: "Equipment changes" },
  EQ: { name: "Equipment", doc: "Equipment changes" },
};

export function describeQueue(key: string): { name: string; doc: string } {
  const i = key.indexOf(":");
  if (i > 0) {
    const p = PREFIX[key.slice(0, i)];
    if (p) return { name: `${p.name} ${key.slice(i + 1)}`, doc: p.doc };
  }
  return { name: key, doc: "Postings" };
}

const OPEN = new Set(["pending", "running", "failed"]);

/** The job the queue is waiting on: lowest seq that is not completed or cancelled. */
export function headJob(jobs: readonly PostingJob[]): PostingJob | null {
  const open = jobs.filter((j) => OPEN.has(j.status)).sort((a, b) => a.seq - b.seq);
  return open[0] ?? null;
}

export function sapMessage(j: PostingJob): string | null {
  const p = j.payload ?? {};
  const fromPayload = typeof p.last_error === "string" ? p.last_error : typeof p.sap_message === "string" ? p.sap_message : null;
  return j.sap_message || j.last_error || fromPayload || null;
}

export function queueRow(q: QueueSummary, jobs: readonly PostingJob[] | null, nowMs: number): QueueRow {
  const { name, doc } = describeQueue(q.queue_key);
  const head = jobs ? headJob(jobs) : null;
  const counts = [plural(q.completed_count, "document") + " posted"];
  if (q.pending_count) counts.push(`${q.pending_count} waiting`);
  if (q.failed_count) counts.push(`${q.failed_count} failed`);
  let detail = `${doc} · ${counts.join(" · ")}`;
  if (q.is_blocked) {
    if (head) detail += ` · head of queue, ${plural(head.attempts, "attempt")}`;
    let message: string;
    if (!jobs) message = "This queue is blocked. The failed job could not be loaded.";
    else if (!head) message = "This queue is blocked, but no failed job was returned.";
    else {
      const sap = sapMessage(head);
      const ref = head.ref_doc_no ? `document ${head.ref_doc_no}` : "the head document";
      message = sap
        ? `SAP: ${sap}`
        : `SAP did not accept ${ref} after ${head.attempts} of ${head.max_attempts} attempts. field-api does not record the SAP message yet; check the worker log.`;
    }
    return { key: q.queue_key, name, detail, message, tone: "blocked", blocked: true, headJobId: head?.status === "failed" ? head.id : null };
  }
  if (q.running_count) {
    return { key: q.queue_key, name, detail, message: "Posting now…", tone: "busy", blocked: false, headJobId: null };
  }
  if (q.pending_count) {
    const since = q.oldest_pending_at ? ` · oldest queued ${relativeTime(q.oldest_pending_at, nowMs).toLowerCase()}` : "";
    return { key: q.queue_key, name, detail, message: `Waiting to post${since}`, tone: "busy", blocked: false, headJobId: null };
  }
  return { key: q.queue_key, name, detail, message: "All clear", tone: "ok", blocked: false, headJobId: null };
}

export function buildQueueRows(
  queues: readonly QueueSummary[],
  jobsByQueue: Readonly<Record<string, readonly PostingJob[] | null>>,
  nowMs: number,
): QueueRow[] {
  const rank: Record<QueueTone, number> = { blocked: 0, busy: 1, ok: 2 };
  return queues
    .map((q) => queueRow(q, jobsByQueue[q.queue_key] ?? null, nowMs))
    .sort((a, b) => rank[a.tone] - rank[b.tone] || a.key.localeCompare(b.key));
}
