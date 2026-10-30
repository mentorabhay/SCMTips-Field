/**
 * Development sign-in (T1.075 interim), session store, permissions, uuid7 and config.
 */
import fc from "fast-check";
import { describe, expect, test } from "vitest";
import { createApiClient, MSG } from "../lib/api";
import { readConfig } from "../lib/config";
import { hasPermission, isExpired, parseSession, roleLabel, SESSION_KEY, SessionStore, type FieldSession, type KeyValueStore } from "../lib/session";
import { DEV_ROLES, devSignIn, validateSignIn } from "../lib/signin";
import { uuid7, UUID7_RE } from "../lib/uuid7";
import { NOW, scriptedFetch, type Reply } from "./helpers";

const TENANT = "1b4e28ba-2fa1-41d2-883f-0016d3cca427";

function api(replies: Reply[]) {
  const f = scriptedFetch(replies);
  return { api: createApiClient({ fetch: f.fetchImpl, baseUrl: "", coreBaseUrl: "/dev-core", getToken: () => null }), calls: f.calls };
}

describe("dev sign-in", () => {
  test("fake-core token for the chosen role, then exchange; session from the exchange answer", async () => {
    const { api: a, calls } = api([
      { status: 200, body: { access_token: "core-jwt", token_type: "Bearer", expires_in: 28800 } },
      {
        status: 200,
        body: {
          access_token: "field-jwt", expires_in: 3600, roles: ["field.supervisor"], permissions: ["field.queue.read"],
          tenant_id: TENANT, site_ids: ["*"],
        },
      },
    ]);
    const s = await devSignIn(a, { role: "supervisor", principalId: " meera ", tenantId: TENANT.toUpperCase() }, NOW);
    expect(calls[0].body).toEqual({ principal_id: "meera", tenant_id: TENANT, roles: ["field.supervisor"], ttl_seconds: 8 * 3600 });
    expect(calls[1].body).toEqual({ device_token: "core-jwt", client_id: "field-console" });
    expect(s).toEqual({
      accessToken: "field-jwt", expiresAt: NOW + 3600_000, principalId: "meera", tenantId: TENANT,
      roles: ["field.supervisor"], permissions: ["field.queue.read"], siteIds: ["*"],
    });
  });

  test("each offered role maps to a field-api role", () => {
    expect(DEV_ROLES.map((r) => r.roles[0])).toEqual(["field.supervisor", "inventory.controller", "field.admin"]);
  });

  test("fake-core unreachable -> MSG1.13", async () => {
    const { api: a } = api([new TypeError("fetch failed")]);
    await expect(devSignIn(a, { role: "admin", principalId: "dev-admin", tenantId: TENANT }, NOW)).rejects.toMatchObject({ title: MSG.signInUnreachable });
  });

  test("exchange rejected -> MSG1.14", async () => {
    const { api: a } = api([
      { status: 200, body: { access_token: "core-jwt", expires_in: 60 } },
      { status: 401, body: { code: "FIELD-AUTH-401-UNAUTHORIZED", title: "Unauthorized" } },
    ]);
    await expect(devSignIn(a, { role: "supervisor", principalId: "x", tenantId: TENANT }, NOW)).rejects.toMatchObject({ title: MSG.exchangeRejected });
  });

  test("input validation", () => {
    expect(validateSignIn({ role: "supervisor", principalId: "dev-supervisor", tenantId: TENANT })).toEqual({});
    expect(validateSignIn({ role: "supervisor", principalId: "", tenantId: "" })).toHaveProperty("principalId");
    expect(validateSignIn({ role: "supervisor", principalId: "a b", tenantId: "SAMPLE" })).toEqual({
      principalId: expect.any(String),
      tenantId: expect.stringContaining("UUID"),
    });
  });
});

describe("session", () => {
  const s: FieldSession = {
    accessToken: "t", expiresAt: NOW + 1000, principalId: "p", tenantId: TENANT, roles: ["field.supervisor"], permissions: ["field.task.read"], siteIds: ["*"],
  };

  function memory(): KeyValueStore & { data: Map<string, string> } {
    const data = new Map<string, string>();
    return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v), removeItem: (k) => void data.delete(k) };
  }

  test("set / reload / clear round-trips through storage and notifies", () => {
    const m = memory();
    const store = new SessionStore(m);
    let n = 0;
    const off = store.subscribe(() => n++);
    store.set(s);
    expect(new SessionStore(m).get()).toEqual(s);
    store.clear();
    expect(m.data.has(SESSION_KEY)).toBe(false);
    expect(n).toBe(2);
    off();
    store.set(s);
    expect(n).toBe(2);
  });

  test("corrupt or partial storage is ignored", () => {
    expect(parseSession("{not json")).toBeNull();
    expect(parseSession(JSON.stringify({ ...s, roles: "field.supervisor" }))).toBeNull();
    expect(parseSession(JSON.stringify({ ...s, accessToken: "" }))).toBeNull();
    expect(parseSession(null)).toBeNull();
  });

  test("expiry and permissions (field.* wildcard as on field-api)", () => {
    expect(isExpired(s, NOW)).toBe(false);
    expect(isExpired(s, NOW + 1000)).toBe(true);
    expect(hasPermission(["field.*"], "field.device.revoke")).toBe(true);
    expect(hasPermission(["field.task.read"], "field.device.revoke")).toBe(false);
    expect(roleLabel(["field.supervisor"])).toBe("Supervisor");
    expect(roleLabel([])).toBe("No Field role");
  });
});

describe("uuid7 (contract §1 Idempotency-Key)", () => {
  test("property: format, version 7, variant 10, and the timestamp is the given millisecond", () => {
    fc.assert(
      fc.property(fc.integer({ min: 0, max: 2 ** 48 - 1 }), fc.uint8Array({ minLength: 16, maxLength: 16 }), (ms, bytes) => {
        const id = uuid7(ms, (b) => {
          b.set(bytes);
          return b;
        });
        expect(id).toMatch(UUID7_RE);
        expect(parseInt(id.replace(/-/g, "").slice(0, 12), 16)).toBe(ms);
      }),
      { numRuns: 500 },
    );
  });

  test("property: a later millisecond sorts after an earlier one", () => {
    fc.assert(
      fc.property(fc.integer({ min: 0, max: 2 ** 47 }), fc.integer({ min: 1, max: 2 ** 40 }), (a, d) => {
        expect(uuid7(a) < uuid7(a + d)).toBe(true);
      }),
      { numRuns: 300 },
    );
  });
});

describe("config", () => {
  test("defaults and trimming", () => {
    expect(readConfig({})).toEqual({ fieldApiUrl: "http://127.0.0.1:8000", fakeCoreUrl: "http://127.0.0.1:8011", devSignIn: false });
    expect(readConfig({ NEXT_PUBLIC_FIELD_API_URL: " http://10.0.0.5:8100/ ", NEXT_PUBLIC_DEV_SIGNIN: "1" })).toMatchObject({
      fieldApiUrl: "http://10.0.0.5:8100",
      devSignIn: true,
    });
    expect(readConfig({ NEXT_PUBLIC_DEV_SIGNIN: "true" }).devSignIn).toBe(false);
  });
});
