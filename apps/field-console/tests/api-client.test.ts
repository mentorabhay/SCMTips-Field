/**
 * lib/api.ts with an injected fetch (no network): URLs, headers, bodies, paging and error copy.
 * Console tasks T1.074 (typed client), T1.075 (sign-in exchange), contract §1 (Idempotency-Key, problem+json).
 */
import { describe, expect, test } from "vitest";
import { ApiError, createApiClient, errorFromResponse, MAX_PAGES, MSG, parseErrorBody } from "../lib/api";
import { UUID7_RE } from "../lib/uuid7";
import { scriptedFetch, type Reply } from "./helpers";

function client(replies: Reply[] | ((c: import("./helpers").Call) => Reply), token: string | null = "tok-1") {
  const f = scriptedFetch(replies);
  let unauthorized = 0;
  const api = createApiClient({
    fetch: f.fetchImpl,
    baseUrl: "",
    coreBaseUrl: "/dev-core",
    getToken: () => token,
    onUnauthorized: () => {
      unauthorized++;
    },
  });
  return { api, calls: f.calls, unauthorized: () => unauthorized };
}

describe("requests", () => {
  test("GETs carry the bearer token and no Idempotency-Key", async () => {
    const { api, calls } = client([{ status: 200, body: [] }]);
    await api.listPostingQueues();
    expect(calls[0].url).toBe("/v1/posting-queues");
    expect(calls[0].method).toBe("GET");
    expect(calls[0].headers.Authorization).toBe("Bearer tok-1");
    expect(calls[0].headers["Idempotency-Key"]).toBeUndefined();
  });

  test("every write carries a UUIDv7 Idempotency-Key, a fresh one per call", async () => {
    const { api, calls } = client(() => ({ status: 200, body: {} }));
    await api.retryPostingJob("job-1");
    await api.revokeDevice("dev/1", "lost");
    await api.acknowledgeVisit("v-1", "seen");
    await api.decideApproval("apr-1", "approve", "matches recount");
    await api.requestRecount("task-9", "count differed");
    await api.decideMismatch("f-1", "update_erp", "photo verified", "tech-7");
    const keys = calls.map((c) => c.headers["Idempotency-Key"]);
    for (const k of keys) expect(k).toMatch(UUID7_RE);
    expect(new Set(keys).size).toBe(keys.length);
    expect(calls.map((c) => [c.method, c.url])).toEqual([
      ["POST", "/v1/posting-jobs/job-1/retry"],
      ["POST", "/v1/devices/dev%2F1/revoke"],
      ["POST", "/v1/safety/visits/v-1/ack"],
      ["POST", "/v1/approval-requests/apr-1/decide"],
      ["POST", "/v1/tasks/task-9/recount"],
      ["POST", "/v1/mismatches/f-1/decision"],
    ]);
    expect(calls[1].body).toEqual({ reason: "lost" });
    expect(calls[2].body).toEqual({ notes: "seen" });
    expect(calls[3].body).toEqual({ decision: "approve", reason: "matches recount" });
    expect(calls[4].body).toEqual({ reason: "count differed" });
    expect(calls[5].body).toEqual({ decision: "update_erp", note: "photo verified", capturing_technician_id: "tech-7" });
  });

  test("decideMismatch leaves capturing_technician_id out when unknown", async () => {
    const { api, calls } = client([{ status: 200, body: { finding_id: "f", decision: "re_capture", status: "resolved" } }]);
    await api.decideMismatch("f", "re_capture", "blurry", null);
    expect(calls[0].body).toEqual({ decision: "re_capture", note: "blurry" });
  });

  test("listTasks sends comma lists and follows next_cursor", async () => {
    const { api, calls } = client([
      { status: 200, body: { items: [{ id: "a" }], next_cursor: "c1" } },
      { status: 200, body: { items: [{ id: "b" }], next_cursor: null } },
    ]);
    const tasks = await api.listTasks({ status: ["open", "in_progress"], type: ["pick", "count"], site_id: "s 1" });
    expect(tasks.map((t) => t.id)).toEqual(["a", "b"]);
    expect(calls[0].url).toBe("/v1/tasks?site_id=s+1&status=open%2Cin_progress&type=pick%2Ccount&limit=200");
    expect(calls[1].url).toBe(`${calls[0].url}&cursor=c1`);
  });

  test("paging stops after MAX_PAGES even if the server keeps sending cursors", async () => {
    const { api, calls } = client(() => ({ status: 200, body: { items: [{ id: "x" }], next_cursor: "again" } }));
    const sites = await api.listSites();
    expect(calls).toHaveLength(MAX_PAGES);
    expect(sites).toHaveLength(MAX_PAGES);
  });

  test("approval requests accept {items} or a bare array; anything else is an error", async () => {
    const a = client([{ status: 200, body: { items: [{ id: "1", status: "pending" }] } }]);
    expect(await a.api.listPendingApprovals()).toHaveLength(1);
    expect(a.calls[0].url).toBe("/v1/approval-requests?status=pending");
    const b = client([{ status: 200, body: [{ id: "2", status: "pending" }] }]);
    expect(await b.api.listPendingApprovals()).toHaveLength(1);
    const c = client([{ status: 200, body: { nope: true } }]);
    await expect(c.api.listPendingApprovals()).rejects.toBeInstanceOf(ApiError);
  });

  test("active visits must have a visits array", async () => {
    const { api } = client([{ status: 200, body: { total_active: 0 } }]);
    await expect(api.listActiveVisits()).rejects.toMatchObject({ kind: "unexpected" });
  });

  test("exchange and dev core token are sent without a bearer token", async () => {
    const { api, calls } = client([
      { status: 200, body: { access_token: "core", expires_in: 60 } },
      { status: 200, body: { access_token: "field", expires_in: 60, roles: [], permissions: [], tenant_id: "t", site_ids: [] } },
    ]);
    await api.issueDevCoreToken({ principal_id: "p", tenant_id: "t", roles: ["field.supervisor"], ttl_seconds: 60 });
    await api.exchange("core");
    expect(calls[0].url).toBe("/dev-core/api/v1/auth/token");
    expect(calls[1].url).toBe("/v1/auth/exchange");
    expect(calls[1].body).toEqual({ device_token: "core", client_id: "field-console" });
    expect(calls[0].headers.Authorization).toBeUndefined();
    expect(calls[1].headers.Authorization).toBeUndefined();
  });

  test("no token means no Authorization header", async () => {
    const { api, calls } = client([{ status: 200, body: [] }], null);
    await api.listDevices();
    expect(calls[0].headers.Authorization).toBeUndefined();
    expect(calls[0].url).toBe("/v1/devices?limit=200");
  });
});

describe("errors", () => {
  test("network failure -> plain message", async () => {
    const { api } = client([new TypeError("fetch failed")]);
    await expect(api.getSystemStatus()).rejects.toMatchObject({ kind: "network", title: MSG.network });
  });

  test("401 -> expired copy and onUnauthorized", async () => {
    const t = client([{ status: 401, body: { code: "FIELD-AUTH-401-UNAUTHORIZED", title: "Unauthorized" } }]);
    await expect(t.api.listDevices()).rejects.toMatchObject({ kind: "unauthorized", title: MSG.expired });
    expect(t.unauthorized()).toBe(1);
  });

  test("problem+json title is shown as is", () => {
    const e = errorFromResponse(409, { code: "FIELD-TASK-409-WRONG-CODE", title: "That is bin 03-05-01. Go to 03-05-02.", status: 409 });
    expect(e.kind).toBe("conflict");
    expect(e.code).toBe("FIELD-TASK-409-WRONG-CODE");
    expect(e.title).toBe("That is bin 03-05-01. Go to 03-05-02.");
  });

  test("generic 403 -> MSG1.10; flag disabled -> MSG1.15; no role -> MSG1.11; SoD keeps its own text", () => {
    expect(errorFromResponse(403, { code: "FIELD-AUTH-403-FORBIDDEN", title: "Forbidden" }).title).toBe(MSG.permission);
    expect(errorFromResponse(403, { detail: "Not enough permissions" }).title).toBe(MSG.permission);
    expect(errorFromResponse(403, { code: "FIELD-FLAG-403-DISABLED", title: "Feature disabled" }).title).toBe(MSG.addonDisabled);
    expect(errorFromResponse(403, { code: "FIELD-AUTH-403-NO-ROLE", title: "x" }).title).toBe(MSG.noRole);
    const sod = errorFromResponse(403, { code: "FIELD-APR-403-SOD", title: "Approver excluded (requester or counter)" });
    expect(sod.title).toBe("Approver excluded (requester or counter)");
  });

  test("FastAPI detail shapes are read and the code prefix is stripped", () => {
    expect(parseErrorBody(403, { detail: { error_code: "FIELD-EXC-403-SOD", message: "FIELD-EXC-403-SOD: decider cannot be the capturing technician" } })).toEqual({
      code: "FIELD-EXC-403-SOD",
      title: "decider cannot be the capturing technician",
      detail: null,
    });
    expect(parseErrorBody(404, { detail: "Posting job not found" })).toEqual({ code: null, title: "Posting job not found", detail: null });
    expect(parseErrorBody(400, { detail: "FIELD-EXC-404: Finding x not found" }).code).toBe("FIELD-EXC-404");
    expect(parseErrorBody(422, { detail: [{ loc: ["body", "reason"], msg: "Field required" }] }).title).toBe("The request was not valid: Field required");
    expect(parseErrorBody(500, null)).toEqual({ code: null, title: null, detail: null });
  });

  test("a body-less 500 gets a plain title", () => {
    const e = errorFromResponse(502, null);
    expect(e.kind).toBe("server");
    expect(e.title).toContain("HTTP 502");
  });

  test("a 200 that is not JSON is an error, not data", async () => {
    const { api } = client([{ status: 200, text: "<html>proxy</html>" }]);
    await expect(api.getSystemStatus()).rejects.toMatchObject({ kind: "unexpected" });
  });
});
