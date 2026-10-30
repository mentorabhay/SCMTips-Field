/**
 * Live work board (T3.056) and the Right now summary cards: pure mapping from GET /v1/tasks etc.
 */
import fc from "fast-check";
import { describe, expect, test } from "vitest";
import type { Device, QueueSummary, Task } from "../lib/api";
import { buildBoard, COLUMN_ORDER, placeOf, progressText, typeBreakdown } from "../lib/views/board";
import { decideCard, devicesCard, postCard, workCard } from "../lib/views/now";
import { buildCases } from "../lib/views/decisions";
import { HOUR, iso, line, NOW, task } from "./helpers";

describe("board placement", () => {
  test.each([
    ["open", "open", null],
    ["in_progress", "in_progress", null],
    ["awaiting_posting", "waiting_sap", null],
    ["awaiting_approval", "blocked", "Waiting for a decision. See Decisions."],
    ["failed", "blocked", "Posting to SAP failed. See Postings to SAP."],
    ["done", "done", null],
  ])("status %s -> %s", (status, column, why) => {
    expect(placeOf(task({ status }))).toEqual({ column, why });
  });

  test("a flagged line blocks an in-progress job and says where", () => {
    const t = task({ status: "in_progress", lines: [line({ status: "done" }), line({ status: "flagged", bin: "02-04-01" })] });
    expect(placeOf(t)).toEqual({ column: "blocked", why: "Bin 02-04-01: flagged by the operator" });
  });

  test("a failed job shows the API reason when there is one", () => {
    expect(placeOf(task({ status: "failed", reason: "SAP period closed" })).why).toBe("SAP period closed");
  });

  test("unknown status is shown, not dropped", () => {
    expect(placeOf(task({ status: "paused" }))).toEqual({ column: "open", why: 'Status "paused" is not known to the console yet' });
  });

  test("progress counts finished lines with a noun per job type", () => {
    expect(progressText(task({ type: "pick", lines: [line({ status: "done" }), line(), line()] }))).toBe("1 of 3 stops");
    expect(progressText(task({ type: "receive", lines: [line({ status: "counted" })] }))).toBe("1 of 1 item");
    expect(progressText(task({ lines: [] }))).toBeNull();
  });
});

describe("buildBoard", () => {
  test("titles use the type label and ref; done keeps only today when finish times exist", () => {
    const cols = buildBoard(
      [
        task({ type: "receive", status: "in_progress", title: "Delivery 1800000022", subtitle: "From SAMPLE-VENDOR-01 · 2 items" }),
        task({ type: "pick", status: "done", title: "Order 7700000011", completed_at: iso(HOUR) }),
        task({ type: "pick", status: "done", title: "Order 7700000010", completed_at: iso(48 * HOUR) }),
        task({ type: "count", status: "open", title: null, ref_doc_no: null, erp_ref: "PID-1" }),
      ],
      NOW,
    );
    expect(cols.map((c) => c.id)).toEqual([...COLUMN_ORDER]);
    const by = Object.fromEntries(cols.map((c) => [c.id, c]));
    expect(by.in_progress.cards[0]).toMatchObject({ title: "Receive · Delivery 1800000022", subtitle: "From SAMPLE-VENDOR-01 · 2 items" });
    expect(by.open.cards[0].title).toBe("Count · PID-1");
    expect(by.done.name).toBe("Done today");
    expect(by.done.cards.map((c) => c.title)).toEqual(["Pick · Order 7700000011"]);
    expect(by.done.note).toBeNull();
  });

  test("done jobs without a finish time are all shown, and the column says so", () => {
    const by = Object.fromEntries(buildBoard([task({ status: "done" }), task({ status: "done" })], NOW).map((c) => [c.id, c]));
    expect(by.done.name).toBe("Done");
    expect(by.done.count).toBe(2);
    expect(by.done.note).toContain("does not report when jobs finished");
  });

  const statusArb = fc.constantFrom("open", "in_progress", "awaiting_posting", "awaiting_approval", "done", "failed", "weird");
  const lineArb = fc.record({ status: fc.constantFrom("open", "counted", "confirmed", "flagged", "done") });
  const taskArb = fc.record({
    status: statusArb,
    type: fc.constantFrom("receive", "putaway", "pick", "count", "audit", "swap"),
    lines: fc.array(lineArb, { maxLength: 5 }),
    doneAgoH: fc.option(fc.integer({ min: 0, max: 200 }), { nil: undefined }),
  });

  test("property: every job lands in exactly one column; only done jobs from other days are left out", () => {
    fc.assert(
      fc.property(fc.array(taskArb, { maxLength: 40 }), (specs) => {
        const tasks: Task[] = specs.map((s) =>
          task({ status: s.status, type: s.type, lines: s.lines.map((l) => line(l)), completed_at: s.doneAgoH === undefined ? undefined : iso(s.doneAgoH * HOUR) }),
        );
        const cols = buildBoard(tasks, NOW);
        const ids = cols.flatMap((c) => c.cards.map((k) => k.id));
        expect(new Set(ids).size).toBe(ids.length);
        for (const c of cols) expect(c.count).toBe(c.cards.length);
        const today = new Date(NOW);
        const left = tasks.filter((t) => {
          if (t.status !== "done" || !t.completed_at) return false;
          const d = new Date(t.completed_at);
          return d.getFullYear() !== today.getFullYear() || d.getMonth() !== today.getMonth() || d.getDate() !== today.getDate();
        });
        expect(ids.length).toBe(tasks.length - left.length);
        for (const t of left) expect(ids).not.toContain(t.id);
      }),
      { numRuns: 300 },
    );
  });
});

describe("Right now cards", () => {
  test("work in progress counts not-done jobs with a type breakdown", () => {
    const ts = [task({ type: "receive" }), task({ type: "pick" }), task({ type: "pick", status: "in_progress" }), task({ type: "count", status: "done" })];
    expect(workCard({ data: ts })).toMatchObject({ value: "3", note: "1 receipt · 2 picks" });
    expect(typeBreakdown([task({ type: "count" }), task({ type: "receive" })])).toBe("1 receipt · 1 count");
    expect(workCard({ data: [] }).note).toBe("No open jobs");
  });

  test("unavailable and loading inputs say so instead of showing 0", () => {
    expect(workCard({ error: "Needs the Supervisor role" })).toMatchObject({ value: "—", note: "Needs the Supervisor role", tone: "muted" });
    expect(postCard({ loading: true })).toMatchObject({ value: "…", note: "Loading…" });
  });

  test("blocked postings", () => {
    const q = (p: Partial<QueueSummary>): QueueSummary => ({
      queue_key: "IBD:1", pending_count: 0, running_count: 0, failed_count: 0, completed_count: 1, cancelled_count: 0, is_blocked: false, ...p,
    });
    expect(postCard({ data: [q({})] })).toMatchObject({ value: "0", note: "All queues clear", tone: "ok" });
    expect(postCard({ data: [q({ pending_count: 2 })] }).note).toBe("All queues moving · 2 waiting to post");
    expect(postCard({ data: [q({ is_blocked: true, failed_count: 1 }), q({})] })).toMatchObject({ value: "1", tone: "warn" });
  });

  test("devices: revoked are not counted; stale are called out", () => {
    const d = (p: Partial<Device>): Device => ({ id: Math.random().toString(), kind: "phone", serial_no: "S", model: "Pixel", status: "active", ...p });
    expect(devicesCard({ data: [d({}), d({ is_stale: true }), d({ status: "revoked" })] })).toMatchObject({ value: "2", note: "1 not seen for 15 min or more" });
    expect(devicesCard({ data: [] }).note).toBe("No devices registered");
  });

  test("needs a decision: count, high ones and oldest age", () => {
    const cases = buildCases(
      [{ id: "a", status: "pending", band: "B3", created_at: iso(5 * HOUR) }],
      [{ id: "m", site_id: "s", class: "misplaced", status: "open", created_at: iso(HOUR / 2) }],
      "me",
      NOW,
    );
    expect(decideCard({ data: cases }, NOW)).toMatchObject({ value: "2", note: "1 high · oldest waiting 5 hours", tone: "warn" });
    expect(decideCard({ data: [] }, NOW)).toMatchObject({ value: "0", note: "Nothing waiting" });
  });
});
