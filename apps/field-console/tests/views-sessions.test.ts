/**
 * M3 console (track P): Field Assistant sessions page and sandbox badges, pure mapping from the
 * GET /v1/assistant/sessions[/{id}] answers (docs/design/M3_CONTRACT.md §4) and GET /v1/sites `mode` (§2).
 */
import { describe, expect, test } from "vitest";
import type { AssistantSession, AssistantSessionWithTurns, Site } from "../lib/api";
import { createApiClient } from "../lib/api";
import { buildBoard } from "../lib/views/board";
import {
  actionSummary,
  buildSessionRows,
  costText,
  durationText,
  isSandbox,
  photoLink,
  sandboxSiteIds,
  sessionCsvPath,
  sessionDetail,
  sessionsSummary,
  turnRows,
} from "../lib/views/sessions";
import { iso, MIN, NOW, scriptedFetch, task } from "./helpers";

const sites: Site[] = [
  { id: "wh", code: "SAMPLE-WH-01", name: "Sample warehouse", kind: "warehouse", mode: "production" },
  { id: "home", code: "HOME", name: "Home (sandbox)", kind: "warehouse", mode: "sandbox" },
  { id: "old", code: "OLD", name: "OLD", kind: "warehouse" },
];

const session = (p: Partial<AssistantSession> = {}): AssistantSession => ({
  id: "s-1", site_id: "wh", principal_id: "asha.sharma", mode: "production", started_at: iso(30 * MIN), ended_at: iso(5 * MIN),
  turns: 12, documents: ["5000000123"], cost_usd: 0.0123, ...p,
});

describe("site mode and sandbox badges", () => {
  test("only mode sandbox is a sandbox; an older field-api without mode is production", () => {
    expect(sites.map(isSandbox)).toEqual([false, true, false]);
    expect([...sandboxSiteIds(sites)]).toEqual(["home"]);
    expect(sandboxSiteIds(undefined).size).toBe(0);
  });

  test("work board cards at a sandbox site carry the badge flag", () => {
    const cols = buildBoard([task({ site_id: "home", status: "open" }), task({ site_id: "wh", status: "open" })], NOW, sandboxSiteIds(sites));
    expect(cols.find((c) => c.id === "open")!.cards.map((c) => c.sandbox)).toEqual([true, false]);
    expect(buildBoard([task({ site_id: "home" })], NOW)[0].cards[0].sandbox).toBe(false);
  });
});

describe("sessions list", () => {
  test("rows: newest first, site label, sandbox, running, documents, cost and CSV path", () => {
    const rows = buildSessionRows(
      [
        session(),
        session({ id: "s-2", site_id: "home", mode: "sandbox", started_at: iso(2 * MIN), ended_at: null, documents: null, cost_usd: "0" }),
        session({ id: "s/3", site_id: "gone", started_at: iso(90 * MIN), ended_at: iso(15 * MIN), cost_usd: null }),
      ],
      sites,
      NOW,
    );
    expect(rows.map((r) => r.id)).toEqual(["s-2", "s-1", "s/3"]);
    expect(rows[0]).toMatchObject({ siteLabel: "HOME · Home (sandbox)", sandbox: true, active: true, documents: [], cost: "$0", duration: "running · 2 min so far" });
    expect(rows[1]).toMatchObject({ siteLabel: "SAMPLE-WH-01 · Sample warehouse", sandbox: false, who: "asha.sharma", started: "30 min ago", duration: "25 min", turns: 12, documents: ["5000000123"], cost: "$0.0123" });
    expect(rows[2]).toMatchObject({ siteLabel: "gone", duration: "1 h 15 min", cost: "—", csvPath: "/v1/assistant/sessions/s%2F3/export.csv" });
    expect(sessionsSummary(rows, [session(), session({ cost_usd: 0.5 })])).toBe("3 sessions · 1 sandbox · $0.5123 AI cost");
  });

  test("format helpers", () => {
    expect(costText(0.0021)).toBe("$0.0021");
    expect(costText("1.5")).toBe("$1.50");
    expect(costText(undefined)).toBe("—");
    expect(durationText("not a time", null, NOW)).toBe("—");
    expect(sessionCsvPath("a b")).toBe("/v1/assistant/sessions/a%20b/export.csv");
  });
});

describe("session detail", () => {
  const detail: AssistantSessionWithTurns = {
    ...session({ site_id: "home", mode: "sandbox", documents: ["5000000124", "4900000101"] }),
    turns: [
      { id: "t2", at: iso(20 * MIN), event: "utterance", heard: "start the home receipt", said: "Starting. Look at a box.", ai: "model", cost_usd: 0.002, latency_ms: 840,
        actions: [{ type: "open_task", task_id: "t-rcv" }, { type: "listen", mode: "command" }] },
      { id: "t1", at: iso(29 * MIN), event: "session_start", heard: null, said: "Good morning. One home receipt.", ai: "rules", cost_usd: 0 },
      { id: "t3", at: iso(15 * MIN), event: "unknown_code", code: "8901234567890", photo_ref: "/v1/assistant/photos/p-1", heard: null, said: null, ai: "model",
        actions: [{ type: "refresh_task", task_id: "t-rcv", focus_code: "8901234567890" }, { type: "command", command: "count", value: 4 }] },
      { id: "t4", at: iso(10 * MIN), event: "pause", ai: null, photo_ref: "s3://bucket/x" },
    ],
  };

  test("turns in time order with event labels, AI or rules, actions in words, photos and purge notes", () => {
    const rows = turnRows(detail.turns);
    expect(rows.map((r) => r.eventLabel)).toEqual(["Session start", "Heard", "Unknown code", "Paused"]);
    expect(rows[1]).toMatchObject({ heard: "start the home receipt", said: "Starting. Look at a box.", ai: "AI", cost: "$0.0020", latency: "840 ms", actions: "open task t-rcv · listen command", purged: false });
    expect(rows[0]).toMatchObject({ ai: "Rules", cost: "$0", purged: false });
    expect(rows[2]).toMatchObject({ code: "8901234567890", photo: { path: "/v1/assistant/photos/p-1", ref: "/v1/assistant/photos/p-1" }, purged: true,
      actions: "refresh task t-rcv (code 8901234567890) · command count 4" });
    expect(rows[3]).toMatchObject({ ai: null, purged: false, photo: { path: null, ref: "s3://bucket/x" } });
  });

  test("detail view: title, sandbox, documents, AI/rules counts, cost", () => {
    const v = sessionDetail(detail, sites, NOW);
    expect(v).toMatchObject({ title: "asha.sharma at HOME · 25 min", sandbox: true, documents: ["5000000124", "4900000101"], aiTurns: 2, rulesTurns: 1, cost: "$0.0123" });
    expect(sessionDetail({ ...detail, cost_usd: null }, [], NOW).cost).toBe("$0.0020");
  });

  test("action summary tolerates anything the server stores", () => {
    expect(actionSummary(null)).toBe("");
    expect(actionSummary("x")).toBe("");
    expect(actionSummary([null, 3, { type: "speak" }, { type: "command", command: "post" }])).toBe("speak · command post");
    expect(photoLink("")).toBeNull();
  });
});

describe("client calls", () => {
  function client(replies: Parameters<typeof scriptedFetch>[0]) {
    const f = scriptedFetch(replies);
    return { api: createApiClient({ fetch: f.fetchImpl, baseUrl: "", coreBaseUrl: "/dev-core", getToken: () => "tok" }), calls: f.calls };
  }

  test("list and detail: paths, query, shapes", async () => {
    const { api, calls } = client([
      { status: 200, body: { items: [session()], next_cursor: null } },
      { status: 200, body: [session()] },
      { status: 200, body: { ...session(), turns: [] } },
      { status: 200, body: { ...session(), turns: 3 } },
    ]);
    expect((await api.listAssistantSessions({ site_id: "home", limit: 20 })).length).toBe(1);
    expect(calls[0].url).toBe("/v1/assistant/sessions?site_id=home&limit=20");
    expect((await api.listAssistantSessions()).length).toBe(1);
    expect(calls[1].url).toBe("/v1/assistant/sessions?limit=100");
    expect((await api.getAssistantSession("s/1")).turns).toEqual([]);
    expect(calls[2].url).toBe("/v1/assistant/sessions/s%2F1");
    await expect(api.getAssistantSession("s-1")).rejects.toMatchObject({ kind: "unexpected" });
  });

  test("CSV export is fetched with the bearer token; errors keep the plain-English title", async () => {
    const { api, calls } = client([
      { status: 200, text: "at,event,heard\n2026-10-31T10:00:00Z,utterance,start\n" },
      { status: 403, body: { code: "FIELD-AUTH-403-PERMISSION", title: "Forbidden" } },
      { status: 404, body: { detail: "Not Found" } },
    ]);
    const blob = await api.exportAssistantSessionCsv("s-1");
    expect(await blob.text()).toContain("utterance,start");
    expect(calls[0]).toMatchObject({ url: "/v1/assistant/sessions/s-1/export.csv", method: "GET" });
    expect(calls[0].headers.Authorization).toBe("Bearer tok");
    expect(calls[0].headers["Idempotency-Key"]).toBeUndefined();
    await expect(api.exportAssistantSessionCsv("s-1")).rejects.toMatchObject({ kind: "forbidden" });
    await expect(api.downloadPath("/v1/assistant/photos/x")).rejects.toMatchObject({ kind: "not_found" });
  });
});
