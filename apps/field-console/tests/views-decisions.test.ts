/**
 * Decisions (T3.057 / T3.060 / T4.067): count differences + tower findings -> cases, rule-based
 * suggestions, separation-of-duties notes, ordering.
 */
import fc from "fast-check";
import { describe, expect, test } from "vitest";
import type { ApprovalRequest, Mismatch } from "../lib/api";
import {
  approvalCase,
  approvalOutcome,
  buildCases,
  countDifference,
  mismatchCase,
  mismatchOutcome,
  sodForApproval,
  sodForMismatch,
  suggestForCount,
  suggestForMismatch,
  waitingText,
} from "../lib/views/decisions";
import { HOUR, iso, NOW } from "./helpers";

const apr = (p: Partial<ApprovalRequest> = {}): ApprovalRequest => ({ id: "apr-1", status: "pending", ...p });
const mm = (p: Partial<Mismatch> = {}): Mismatch => ({ id: "f-1", site_id: "s-1", class: "serial_mismatch", status: "open", ...p });

describe("count differences", () => {
  test("difference from the API, else counted minus books", () => {
    expect(countDifference(apr({ difference_qty: "-6" }))).toBe(-6);
    expect(countDifference(apr({ book_qty: 54, counted_qty: "48" }))).toBe(-6);
    expect(countDifference(apr({ book_qty: 54 }))).toBeNull();
  });

  test("case title, facts and task link", () => {
    const c = approvalCase(
      apr({ bin: "03-05-02", book_qty: 54, counted_qty: 48, uom: "EA", value_abs: "1234.5", currency: "EUR", band: "B2", material: "SAMPLE-MAT-0001", task_id: "t-9", created_at: iso(3 * HOUR) }),
      "me",
      NOW,
    );
    expect(c.title).toBe("Bin 03-05-02 · 6 fewer than the books");
    expect(c.sub).toBe("SAMPLE-MAT-0001");
    expect(c.facts).toEqual([
      { k: "Books say", v: "54 EA" },
      { k: "Counted", v: "48 EA" },
      { k: "Difference", v: "-6 EA" },
      { k: "Value", v: "1234.50 EUR" },
      { k: "Approval band", v: "B2" },
    ]);
    expect(c.severity).toBe("Medium");
    expect(c.taskId).toBe("t-9");
    expect(c.waiting).toBe("Waiting 3 hours");
  });

  test("suggestion: recount first, approve once recounted; never claims to be AI", () => {
    expect(suggestForCount(apr({ recount_count: 0 })).action).toBe("recount");
    expect(suggestForCount(apr({ recount_count: 2 })).action).toBe("approve");
    const unknown = suggestForCount(apr());
    expect(unknown.action).toBe("recount");
    expect(unknown.why).toContain("did not say whether this was recounted");
    for (const s of [suggestForCount(apr({ recount_count: 1, band: "B3" })), unknown]) {
      expect(`${s.headline} ${s.why} ${s.basis}`).not.toMatch(/\bAI\b/);
      expect(s.basis).toMatch(/^Fixed rule/);
    }
  });

  test("separation of duties: API note wins; else excluded list; else unknown", () => {
    expect(sodForApproval(apr({ sod_note: "You did not count this bin, so you may decide.", can_decide: true }), "me")).toEqual({
      text: "You did not count this bin, so you may decide.",
      mayDecide: true,
    });
    expect(sodForApproval(apr({ excluded_principals: ["me", "asha"] }), "me").mayDecide).toBe(false);
    expect(sodForApproval(apr({ excluded_principals: ["asha"] }), "me").mayDecide).toBe(true);
    expect(sodForApproval(apr({ requested_by: "me" }), "me").mayDecide).toBe(false);
    expect(sodForApproval(apr(), "me")).toMatchObject({ mayDecide: null });
    expect(sodForApproval(apr({ can_decide: false }), "me").mayDecide).toBe(false);
  });
});

describe("tower findings", () => {
  test.each([
    ["serial_mismatch", "verified", "update_erp"],
    ["serial_mismatch", "pending", "re_capture"],
    ["tower_only", "verified", "update_erp"],
    ["tower_only", null, "re_capture"],
    ["erp_only", "verified", "re_capture"],
    ["misplaced", "verified", "record_move"],
    ["something_new", "verified", "re_capture"],
  ])("%s with photo check %s -> %s", (cls, verify, decision) => {
    expect(suggestForMismatch(mm({ class: cls, verify_status: verify })).action).toBe(decision);
  });

  test("case: facts, suggested decision first and all five decisions offered once", () => {
    const c = mismatchCase(
      mm({ site_code: "SAMPLE-TWR-0001", expected_serial: "SN-A", found_serial: "SN-B", verify_status: "verified", confidence: 0.934, equipment_class: "Radio unit", age_h: 30 }),
      "me",
      NOW,
    );
    expect(c.title).toBe("SAMPLE-TWR-0001 · SN-A");
    expect(c.kind).toBe("Serial mismatch");
    expect(c.facts).toContainEqual({ k: "Found on the tower", v: "SN-B" });
    expect(c.facts).toContainEqual({ k: "Read confidence", v: "93%" });
    expect(c.decisions[0]).toBe("update_erp");
    expect([...c.decisions].sort()).toEqual(["accept_erp", "re_capture", "record_move", "update_erp", "waived"]);
    expect(c.severity).toBe("High");
    expect(c.waiting).toBe("Waiting 30 hours");
  });

  test("SoD: the person who captured it cannot decide", () => {
    expect(sodForMismatch(mm({ captured_by: "me" }), "me").mayDecide).toBe(false);
    expect(sodForMismatch(mm({ captured_by: "ravi" }), "me")).toEqual({ text: "Captured by ravi; you may decide.", mayDecide: true });
    expect(sodForMismatch(mm(), "me").mayDecide).toBeNull();
  });
});

describe("case list", () => {
  test("only pending approvals and unresolved findings; high first, then oldest", () => {
    const cases = buildCases(
      [apr({ id: "a1", band: "B1", created_at: iso(10 * HOUR) }), apr({ id: "a2", status: "approved" }), apr({ id: "a3", band: "B3", created_at: iso(HOUR) })],
      [mm({ id: "m1", status: "resolved" }), mm({ id: "m2", class: "misplaced", created_at: iso(20 * HOUR) })],
      "me",
      NOW,
    );
    // a1 (B1) and m2 (misplaced) are both Low; m2 has waited longer.
    expect(cases.map((c) => c.key)).toEqual(["approval:a3", "mismatch:m2", "approval:a1"]);
  });

  test("property: the order is a permutation of the input, sorted by severity then age", () => {
    const sev = fc.constantFrom("B1", "B2", "B3", undefined);
    fc.assert(
      fc.property(
        fc.array(fc.record({ band: sev, ageH: fc.option(fc.integer({ min: 0, max: 500 }), { nil: undefined }) }), { maxLength: 15 }),
        fc.array(fc.record({ cls: fc.constantFrom("serial_mismatch", "tower_only", "erp_only", "misplaced"), ageH: fc.integer({ min: 0, max: 500 }) }), { maxLength: 15 }),
        (as, ms) => {
          const approvals = as.map((a, i) => apr({ id: `a${i}`, band: a.band, created_at: a.ageH === undefined ? null : iso(a.ageH * HOUR) }));
          const mismatches = ms.map((m, i) => mm({ id: `m${i}`, class: m.cls, age_h: m.ageH }));
          const cases = buildCases(approvals, mismatches, "me", NOW);
          expect(cases).toHaveLength(approvals.length + mismatches.length);
          const rank = { High: 0, Medium: 1, Low: 2 } as const;
          for (let i = 1; i < cases.length; i++) {
            const p = cases[i - 1];
            const c = cases[i];
            expect(rank[p.severity] <= rank[c.severity]).toBe(true);
            if (p.severity === c.severity) expect((p.createdMs ?? Infinity) <= (c.createdMs ?? Infinity)).toBe(true);
          }
        },
      ),
      { numRuns: 300 },
    );
  });

  test("outcome copy", () => {
    expect(approvalOutcome("approve", { status: "approved", erp_document_id: "doc" })).toContain("queued for posting to SAP");
    expect(approvalOutcome("reject", null)).toBe("Rejected. Nothing is posted to SAP.");
    expect(approvalOutcome("recount", null)).toContain("count job on the operator's phone");
    expect(mismatchOutcome("update_erp", { requires_approval: true })).toBe("Update ERP recorded. It now waits for a second approval.");
    expect(mismatchOutcome("re_capture", { requires_approval: false })).toBe("Re-capture recorded. The finding is closed.");
    expect(waitingText(null, NOW)).toBe("Waiting time not reported");
    expect(waitingText(NOW - 10 * 60_000, NOW)).toBe("Waiting less than an hour");
  });
});
