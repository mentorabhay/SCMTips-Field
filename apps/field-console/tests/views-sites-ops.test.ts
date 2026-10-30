/**
 * Sites and towers (T4.065/T4.066), lone-worker banners (T4.046), postings (T3.060), devices (T2.061/T2.062),
 * system status (T1.076): pure mapping from the field-api responses.
 */
import fc from "fast-check";
import { describe, expect, test } from "vitest";
import type { ActiveVisit, AuditProgress, Device, PostingJob, QueueSummary, Site, SystemStatus } from "../lib/api";
import { buildDeviceRows, deviceRow, MSG2_19 } from "../lib/views/devices";
import { clock, relativeTime } from "../lib/views/format";
import { buildQueueRows, describeQueue, headJob, queueRow } from "../lib/views/postings";
import { safetyBanner, safetyBanners } from "../lib/views/safety";
import { buildSiteRows, sectorBars } from "../lib/views/sites";
import { aiChecks, statusChecks, summaryLine } from "../lib/views/system";
import { iso, MIN, NOW, task } from "./helpers";

const visit = (p: Partial<ActiveVisit> = {}): ActiveVisit => ({
  visit_id: "v-1", site_id: "s-1", site_code: "SAMPLE-TWR-0001", user_id: "ravi", status: "on_structure",
  last_heartbeat_at: iso(3 * MIN), last_altitude_m: 42.5, timer_remaining_s: 245, tower_fl: "T01", ...p,
});

describe("safety banners (SCR4.13, MSG4.10)", () => {
  test("unacknowledged escalation -> alert with MSG4.10 copy and an acknowledge", () => {
    const b = safetyBanner(visit({ status: "escalated", is_escalated: true, is_acknowledged: false, last_heartbeat_at: iso(25 * MIN) }), NOW);
    expect(b).toMatchObject({ tone: "alert", headline: "Overdue check-in at SAMPLE-TWR-0001", needsAck: true });
    expect(b?.body).toBe("ravi at SAMPLE-TWR-0001 has not checked in for 25 min. Last altitude 42.5 m. Follow the site emergency procedure.");
  });

  test("on the structure -> warning with last check-in and timer", () => {
    const b = safetyBanner(visit(), NOW);
    expect(b).toMatchObject({ tone: "warn", headline: "ravi is on SAMPLE-TWR-0001", needsAck: false });
    expect(b?.body).toBe("Last check-in 3 min ago at 42.5 m · T01 · next check-in due in 4:05");
  });

  test("checked in on the ground is not a structure banner; alerts sort first", () => {
    expect(safetyBanner(visit({ status: "checked_in" }), NOW)).toBeNull();
    const bs = safetyBanners([visit({ visit_id: "a" }), visit({ visit_id: "b", status: "escalated" }), visit({ visit_id: "c", status: "checked_in" })], NOW);
    expect(bs.map((b) => b.visitId)).toEqual(["b", "a"]);
    expect(safetyBanner(visit({ status: "escalated", is_acknowledged: true }), NOW)?.tone).toBe("warn");
  });

  test("format helpers", () => {
    expect(clock(-5)).toBe("0:00");
    expect(clock(3599)).toBe("59:59");
    expect(relativeTime(null, NOW)).toBe("Never");
    expect(relativeTime(iso(30_000), NOW)).toBe("Just now");
    expect(relativeTime(iso(3 * 60 * MIN), NOW)).toBe("3 hours ago");
  });
});

describe("sites and towers", () => {
  const progress = (sectors: Array<[string, number, number]>, tower = "T01"): AuditProgress => ({
    site: 0, towers: [{ code: tower, value: 0, sectors: sectors.map(([code, m, n]) => ({ code, value: 0, expected_count: m, captured_count: n })) }],
  });
  const site = (p: Partial<Site> = {}): Site => ({ id: "s-1", code: "SAMPLE-TWR-0001", name: "Tower 1", kind: "tower", ...p });

  test("sector bars: SCR4.09 copy, percent, complete; tower prefix only with several towers", () => {
    expect(sectorBars(progress([["A", 5, 4], ["B", 5, 5], ["C", 0, 0]]))).toEqual([
      { label: "Sector A", text: "4 of 5 captured", pct: 80, complete: false },
      { label: "Sector B", text: "5 of 5 captured", pct: 100, complete: true },
      { label: "Sector C", text: "0 of 0 captured", pct: 0, complete: false },
    ]);
    const two: AuditProgress = { site: 0, towers: [...progress([["A", 1, 1]], "T01").towers, ...progress([["A", 2, 0]], "T02").towers] };
    expect(sectorBars(two).map((b) => b.label)).toEqual(["T01 · Sector A", "T02 · Sector A"]);
  });

  test("property: captured never shows above expected and pct stays in 0..100", () => {
    fc.assert(
      fc.property(fc.array(fc.tuple(fc.string({ minLength: 1, maxLength: 3 }), fc.integer({ min: -3, max: 50 }), fc.integer({ min: -3, max: 80 })), { maxLength: 8 }), (secs) => {
        for (const b of sectorBars(progress(secs))) {
          expect(b.pct).toBeGreaterThanOrEqual(0);
          expect(b.pct).toBeLessThanOrEqual(100);
          const [n, m] = b.text.split(" of ").map((x) => parseInt(x, 10));
          expect(n).toBeLessThanOrEqual(m);
        }
      }),
    );
  });

  test("rows: escalation first, climbing tag, complete audit, empty audit note, unknown site still shown", () => {
    const audit = task({ type: "audit", status: "in_progress", site_id: "s-2" });
    const done = task({ type: "audit", status: "done", site_id: "s-3" });
    const empty = task({ type: "audit", status: "open", site_id: "s-4" });
    const rows = buildSiteRows(
      [site(), site({ id: "s-2", code: "SAMPLE-TWR-0002" }), site({ id: "s-3", code: "SAMPLE-TWR-0003" }), site({ id: "s-4", code: "SAMPLE-TWR-0004" }), site({ id: "s-5", code: "SAMPLE-WH-01", kind: "warehouse" })],
      [
        { task: audit, progress: progress([["A", 5, 2]]) },
        { task: done, progress: progress([["A", 2, 2]]) },
        { task: empty, progress: { site: 1, empty_scope: true, towers: [{ code: "T01", value: 1, empty_scope: true, sectors: [] }] } },
      ],
      [visit({ site_id: "s-1" }), visit({ visit_id: "v-9", site_id: "s-9", site_code: "SAMPLE-TWR-0009", status: "escalated" })],
      NOW,
    );
    const by = Object.fromEntries(rows.map((r) => [r.code, r]));
    expect(rows[0].code).toBe("SAMPLE-TWR-0009");
    expect(by["SAMPLE-TWR-0009"].tag).toEqual({ text: "Overdue check-in", tone: "alert" });
    expect(by["SAMPLE-TWR-0001"].tag.text).toBe("Climbing");
    expect(by["SAMPLE-TWR-0001"].who).toBe("ravi on the structure · last check-in 3 min ago");
    expect(by["SAMPLE-TWR-0002"].tag.text).toBe("Audit in progress");
    expect(by["SAMPLE-TWR-0003"].tag.text).toBe("Audit complete");
    expect(by["SAMPLE-TWR-0003"].who).toBe("Audit finished · nobody on site");
    // field-api answers an audit without lines with a T01 tower at 100 %: the console must not call that complete.
    expect(by["SAMPLE-TWR-0004"].tag.text).toBe("Audit planned");
    expect(by["SAMPLE-TWR-0004"].auditNote).toBe("This audit has no expected units yet.");
    expect(by["SAMPLE-WH-01"].tag.text).toBe("No audit open");
  });

  test("an audit whose progress call failed says so", () => {
    const rows = buildSiteRows([site()], [{ task: task({ type: "audit", site_id: "s-1" }), progress: null }], [], NOW);
    expect(rows[0].auditNote).toBe("Audit progress is not available right now.");
  });
});

describe("postings to SAP", () => {
  const q = (p: Partial<QueueSummary> = {}): QueueSummary => ({
    queue_key: "OBD:7700000011", pending_count: 0, running_count: 0, failed_count: 0, completed_count: 0, cancelled_count: 0, is_blocked: false, ...p,
  });
  const job = (p: Partial<PostingJob> = {}): PostingJob => ({ id: "j", queue_key: "OBD:7700000011", seq: 1, status: "completed", attempts: 1, max_attempts: 5, ...p });

  test("queue names from staging keys", () => {
    expect(describeQueue("IBD:1800000022")).toEqual({ name: "Inbound delivery 1800000022", doc: "Goods receipt" });
    expect(describeQueue("PID:100000001")).toEqual({ name: "Count document 100000001", doc: "Inventory difference" });
    expect(describeQueue("odd-key")).toEqual({ name: "odd-key", doc: "Postings" });
  });

  test("head job is the lowest open seq", () => {
    expect(headJob([job({ id: "a", seq: 1 }), job({ id: "b", seq: 3, status: "pending" }), job({ id: "c", seq: 2, status: "failed" })])?.id).toBe("c");
    expect(headJob([job({ status: "cancelled" })])).toBeNull();
  });

  test("blocked queue: SAP message when recorded, honest text when not; retry targets the failed head", () => {
    const blocked = q({ is_blocked: true, failed_count: 1, completed_count: 2 });
    const withMsg = queueRow(blocked, [job({ id: "h", seq: 3, status: "failed", attempts: 3, sap_message: "Posting period 010 2026 is not open" })], NOW);
    expect(withMsg).toMatchObject({ blocked: true, headJobId: "h", message: "SAP: Posting period 010 2026 is not open", tone: "blocked" });
    expect(withMsg.detail).toBe("Goods issue · 2 documents posted · 1 failed · head of queue, 3 attempts");
    const noMsg = queueRow(blocked, [job({ id: "h", status: "failed", attempts: 5, ref_doc_no: "7700000011" })], NOW);
    expect(noMsg.message).toBe("SAP did not accept document 7700000011 after 5 of 5 attempts. field-api does not record the SAP message yet; check the worker log.");
    expect(queueRow(blocked, null, NOW)).toMatchObject({ headJobId: null, message: "This queue is blocked. The failed job could not be loaded." });
    expect(queueRow(blocked, [job({ status: "pending" })], NOW).headJobId).toBeNull();
  });

  test("moving and clear queues; blocked sorted first", () => {
    expect(queueRow(q({ running_count: 1 }), null, NOW).message).toBe("Posting now…");
    expect(queueRow(q({ pending_count: 1, oldest_pending_at: iso(2 * MIN) }), null, NOW).message).toBe("Waiting to post · oldest queued 2 min ago");
    expect(queueRow(q({ completed_count: 1 }), null, NOW)).toMatchObject({ message: "All clear", tone: "ok", detail: "Goods issue · 1 document posted" });
    const rows = buildQueueRows([q({ queue_key: "IBD:1" }), q({ queue_key: "OBD:2", is_blocked: true }), q({ queue_key: "IBD:3", pending_count: 1 })], {}, NOW);
    expect(rows.map((r) => r.key)).toEqual(["OBD:2", "IBD:3", "IBD:1"]);
  });
});

describe("phones and glasses", () => {
  const dev = (p: Partial<Device> = {}): Device => ({ id: "d1", kind: "phone", serial_no: "R5CT", model: "Pixel 8", status: "active", last_seen_at: iso(MIN / 2), battery_pct: 78, queue_depth: 0, ...p });

  test("row fields, pairing by id, stale and revoked", () => {
    const glasses = dev({ id: "g1", kind: "glasses", model: "Ray-Ban Meta Gen 2", battery_pct: null, queue_depth: null, paired_with: "d1" });
    const rows = buildDeviceRows([dev({ paired_with: "g1", app_version: "0.4.1" }), glasses, dev({ id: "d2", is_stale: true, last_seen_at: iso(120 * MIN) }), dev({ id: "d3", status: "revoked", revoked_at: iso(5 * MIN) })], NOW);
    expect(rows.map((r) => r.id)).toEqual(["g1", "d1", "d2", "d3"]);
    const by = Object.fromEntries(rows.map((r) => [r.id, r]));
    expect(by.d1).toMatchObject({ name: "Phone · Pixel 8", paired: "Glasses · Ray-Ban Meta Gen 2", seen: "Just now", seenTone: "ok", battery: "78%", queue: "0", versions: "app 0.4.1" });
    expect(by.g1).toMatchObject({ battery: "Not reported", queue: "Not reported", paired: "Phone · Pixel 8" });
    expect(by.d2).toMatchObject({ seen: "2 hours ago", seenTone: "stale" });
    expect(by.d3).toMatchObject({ revoked: true, seen: "Revoked 5 min ago", seenTone: "off" });
    expect(deviceRow(dev({ paired_with: "elsewhere" }), new Map(), NOW).paired).toBe("Paired (device not in this list)");
    expect(MSG2_19).toBe("Device revoked. It stops capturing within a minute. Unsent items stay locked on the device for 72 hours.");
  });
});

describe("system status (SCR1.05)", () => {
  const status = (p: Partial<SystemStatus> = {}): SystemStatus => ({
    ready: true,
    compat: { "core-p13": "PASS", "core-p14": "UNVERIFIED" },
    erp: { system: "erp-sim", reachable: true, probe_ms: 12.4 },
    checks: [
      { name: "postgres", ok: true, probe_ms: 1.2 },
      { name: "field-worker", ok: true, detail: "last heartbeat 4s ago" },
      { name: "erp", ok: true, probe_ms: 12.4 },
    ],
    ...p,
  });

  test("all good", () => {
    const cards = statusChecks(status());
    expect(cards).toEqual([
      { name: "Database", state: "Connected · 1 ms", tone: "ok" },
      { name: "Background worker", state: "Running · last heartbeat 4s ago", tone: "ok" },
      { name: "SAP (ERP simulator)", state: "ERP simulator reachable · 12 ms", tone: "ok" },
      { name: "Core P13 compatibility", state: "Tested and passing", tone: "ok" },
      { name: "Core P14 compatibility", state: "Not tested yet", tone: "unknown" },
    ]);
    expect(summaryLine(cards)).toBe("All checks passed");
  });

  test("ERP down and worker down use the SCR1.05 copy and count as attention", () => {
    const cards = statusChecks(
      status({
        ready: false,
        erp: { system: "erp-sim", reachable: false },
        checks: [{ name: "postgres", ok: true }, { name: "field-worker", ok: false, detail: "no heartbeat recorded" }, { name: "erp", ok: false }],
      }),
    );
    expect(cards).toContainEqual({ name: "SAP (ERP simulator)", state: "ERP simulator not reachable. Postings will wait in the queue.", tone: "bad" });
    expect(cards).toContainEqual({ name: "Background worker", state: "Not running · no heartbeat recorded", tone: "bad" });
    expect(summaryLine(cards)).toBe("2 checks need attention");
  });

  test("AI budget: off, uncapped, near the cap", () => {
    expect(aiChecks({ providers: {}, cloud_enabled: false })).toEqual([{ name: "AI budget", state: "Cloud AI is switched off", tone: "unknown" }]);
    const cards = aiChecks({ cloud_enabled: true, providers: { llama: { spent_usd: "8.50", cap_usd: "10" }, baseten: { spent_usd: "0", cap_usd: null } } });
    expect(cards).toEqual([
      { name: "AI budget · baseten", state: "$0.00 spent · no cap set, so paid calls are refused", tone: "warn" },
      { name: "AI budget · llama", state: "$8.50 of $10.00 cap used so far", tone: "warn" },
    ]);
  });
});
