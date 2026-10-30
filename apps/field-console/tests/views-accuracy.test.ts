/** Inventory accuracy view (T3.059): counted lines vs count differences waiting for a decision. */
import fc from "fast-check";
import { describe, expect, test } from "vitest";
import type { ApprovalRequest } from "../lib/api";
import { buildAccuracy, percent } from "../lib/views/accuracy";
import { filterByType } from "../lib/views/board";
import { line, task } from "./helpers";

function approval(p: Partial<ApprovalRequest>): ApprovalRequest {
  return { id: "ap-1", status: "pending", ...p };
}

describe("inventory accuracy (T3.059)", () => {
  test("nothing counted yet has no rate", () => {
    const s = buildAccuracy([task({ type: "count", lines: [line({ bin: "02-01-01" })] })], []);
    expect(s).toMatchObject({ countJobs: 1, linesTotal: 1, linesCounted: 0, matchRate: null });
    expect(percent(s.matchRate)).toBe("Nothing counted yet");
  });

  test("a pending difference on a counted bin lowers the rate and shows the difference", () => {
    const t = task({
      id: "c1",
      type: "count",
      lines: [line({ bin: "03-05-01", counted_qty: 8, uom: "EA" }), line({ bin: "03-05-02", counted_qty: 4 })],
    });
    const s = buildAccuracy([t], [approval({ task_id: "c1", bin: "03-05-01", book_qty: 10, counted_qty: 8 })]);
    expect(s.linesCounted).toBe(2);
    expect(s.differencesWaiting).toBe(1);
    expect(s.matchRate).toBe(0.5);
    expect(percent(s.matchRate)).toBe("50%");
    expect(s.rows.find((r) => r.bin === "03-05-01")).toMatchObject({ state: "difference waiting", difference: -2, uom: "EA" });
    expect(s.rows.find((r) => r.bin === "03-05-02")?.state).toBe("counted");
  });

  test("non-count jobs and decided approvals are ignored", () => {
    const s = buildAccuracy(
      [task({ id: "p1", type: "pick", lines: [line({ status: "done" })] })],
      [approval({ task_id: "p1", status: "approved" })],
    );
    expect(s).toMatchObject({ countJobs: 0, linesTotal: 0, differencesWaiting: 0, matchRate: null });
  });

  test("rate stays within 0..1 for any mix of lines and differences", () => {
    fc.assert(
      fc.property(fc.array(fc.tuple(fc.boolean(), fc.boolean()), { maxLength: 30 }), (spec) => {
        const lines = spec.map(([counted], i) => line({ bin: `B-${i}`, counted_qty: counted ? 1 : null }));
        const aps = spec.flatMap(([, diff], i) => (diff ? [approval({ id: `a${i}`, task_id: "c", bin: `B-${i}` })] : []));
        const s = buildAccuracy([task({ id: "c", type: "count", lines })], aps);
        if (s.matchRate !== null) {
          expect(s.matchRate).toBeGreaterThanOrEqual(0);
          expect(s.matchRate).toBeLessThanOrEqual(1);
        }
        expect(s.linesCounted).toBe(spec.filter(([c]) => c).length);
      }),
    );
  });
});

describe("board type filter (T3.056, T3.058)", () => {
  test("keeps only the asked types, in order; no types keeps all", () => {
    const ts = [task({ id: "a", type: "receive" }), task({ id: "b", type: "audit" }), task({ id: "c", type: "putaway" })];
    expect(filterByType(ts, ["receive", "putaway"]).map((t) => t.id)).toEqual(["a", "c"]);
    expect(filterByType(ts).map((t) => t.id)).toEqual(["a", "b", "c"]);
  });
});
