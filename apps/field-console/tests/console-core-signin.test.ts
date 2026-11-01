/**
 * M5-J01: hosted sign-in through the SCMTIPS core. The route handlers run with an injected fetch (no network):
 * core app token -> field-api exchange -> httpOnly cookies; each refusal mapped to words; no token in any body.
 */
import { NextRequest } from "next/server";
import { afterEach, describe, expect, test, vi } from "vitest";
import { POST as signinRoute } from "../app/api/console-auth/signin/route";
import { handleRefresh, handleSignIn, handleSignOut, type HandlerDeps } from "../lib/consoleAuthHandlers";
import { CORE_COOKIE, coreSignInConfig, DEVICE_COOKIE, FIELD_COOKIE, secureCookies } from "../lib/coreSignIn";
import { coreSignIn, CoreSignInError, refreshCoreSession, refreshDelayMs } from "../lib/coreSignInClient";
import { authorizationFor } from "../lib/fieldCookie";
import { parseSession } from "../lib/session";
import { middleware } from "../middleware";
import { NOW, scriptedFetch, type Reply } from "./helpers";

const HOST = "https://hud.scmtips.com";
const TENANT = "1b4e28ba-2fa1-41d2-883f-0016d3cca427";
const ENV = { FIELD_CONSOLE_CORE_URL: "http://api:8000/", FIELD_CONSOLE_FIELD_API_URL: "http://field-api:8020", NODE_ENV: "production" };
const NOW_S = Math.floor(NOW / 1000);

function jwt(claims: Record<string, unknown>): string {
  const b = (o: unknown) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b({ alg: "EdDSA", kid: "scmtips-core-ed25519-1" })}.${b(claims)}.c2ln`;
}

const CORE_JWT = jwt({ sub: "u-approver", tenant_id: TENANT, roles: ["approver"], email: "approver@sample.test", exp: NOW_S + 3600 });
const FIELD_JWT = "field.jwt.value";

const CORE_OK: Reply = {
  status: 200,
  body: {
    access_token: CORE_JWT, token_type: "Bearer", expires_in: 3600, claims: { sub: "u-approver", tenant_id: TENANT },
    wearable: { session_id: "s1", token: "wearable-secret", expires_at: "2026-11-02T00:00:00Z", device_id: "x" },
    user: { id: "u-approver", display_name: "Asha Approver", email: "approver@sample.test" },
    capabilities: { approve_decisions: true, field_operator: false },
  },
};
const FIELD_OK: Reply = {
  status: 200,
  body: {
    access_token: FIELD_JWT, token_type: "Bearer", expires_in: 600, roles: ["field.supervisor"], permissions: ["field.task.read"],
    tenant_id: TENANT, site_ids: ["*"], device_id: null, core_permissions: ["voice.approve"], core_roles: ["approver"],
  },
};

function deps(replies: Reply[], env: Record<string, string | undefined> = ENV) {
  const f = scriptedFetch(replies);
  const d: HandlerDeps = { fetch: f.fetchImpl, env, nowS: () => NOW_S, newId: () => "0f8fad5b-d9cb-469f-a165-70867728950e" };
  return { d, calls: f.calls };
}

function req(path: string, opts: { body?: unknown; headers?: Record<string, string>; cookies?: Record<string, string> } = {}) {
  const headers: Record<string, string> = {
    "content-type": "application/json", "sec-fetch-site": "same-origin", origin: HOST, ...(opts.headers ?? {}),
  };
  if (opts.cookies) headers.cookie = Object.entries(opts.cookies).map(([k, v]) => `${k}=${v}`).join("; ");
  return new NextRequest(`${HOST}${path}`, {
    method: "POST", headers, body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  });
}

const signin = (body: unknown = { email: " approver@sample.test ", password: "pw" }, extra = {}) => req("/api/console-auth/signin", { body, ...extra });

function setCookies(res: Response): string[] {
  return res.headers.getSetCookie();
}

function cookie(res: Response, name: string): string | undefined {
  return setCookies(res).find((c) => c.startsWith(`${name}=`));
}

async function bodyText(res: Response): Promise<string> {
  return res.clone().text();
}

describe("M5-J01 sign-in route: core OK -> exchange OK -> cookies", () => {
  test("calls the core's app token and field-api's exchange, sets httpOnly cookies, answers no token", async () => {
    const { d, calls } = deps([CORE_OK, FIELD_OK]);
    const res = await handleSignIn(signin(), d);
    expect(res.status).toBe(200);

    expect(calls[0].url).toBe("http://api:8000/v1/auth/app/token");
    expect(calls[0].method).toBe("POST");
    expect(calls[0].headers["X-Requested-With"]).toBe("lr");
    expect(calls[0].body).toEqual({
      email: "approver@sample.test", password: "pw", device_id: "web-console:0f8fad5b-d9cb-469f-a165-70867728950e",
      device_model: "WEB_CONSOLE", display_capable: true, client: "scmtips-field",
    });
    expect((calls[0].body as { device_model: string }).device_model).toMatch(/^[A-Z0-9_]{1,40}$/);
    expect(calls[1].url).toBe("http://field-api:8020/v1/auth/exchange");
    expect(calls[1].body).toEqual({ device_token: CORE_JWT, client_id: "field-console" });

    const text = await bodyText(res);
    expect(text).not.toContain(CORE_JWT);
    expect(text).not.toContain(FIELD_JWT);
    expect(text).not.toContain("wearable-secret");
    expect(JSON.parse(text)).toEqual({
      session: {
        principalId: "u-approver", tenantId: TENANT, displayName: "Asha Approver", email: "approver@sample.test",
        roles: ["field.supervisor"], permissions: ["field.task.read"], siteIds: ["*"], expiresIn: 600, coreExpiresIn: 3600,
      },
    });

    const field = cookie(res, FIELD_COOKIE) ?? "";
    expect(field).toContain(`${FIELD_COOKIE}=${FIELD_JWT}`);
    expect(field).toMatch(/HttpOnly/i);
    expect(field).toMatch(/Secure/i);
    expect(field).toMatch(/SameSite=Lax/i);
    expect(field).toMatch(/Path=\/v1/);
    expect(field).toMatch(/Max-Age=600/);
    const core = cookie(res, CORE_COOKIE) ?? "";
    expect(core).toMatch(/HttpOnly/i);
    expect(core).toMatch(/SameSite=Strict/i);
    expect(core).toMatch(/Path=\/api\/console-auth/);
    expect(core).toMatch(/Max-Age=3600/);
    expect(cookie(res, DEVICE_COOKIE)).toMatch(/web-console%3A0f8fad5b|web-console:0f8fad5b/);
  });

  test("the browser's device id is reused from its cookie, and not set again", async () => {
    const { d, calls } = deps([CORE_OK, FIELD_OK]);
    const id = "web-console:11111111-2222-4333-8444-555555555555";
    const res = await handleSignIn(signin(undefined, { cookies: { [DEVICE_COOKIE]: id } }), d);
    expect(res.status).toBe(200);
    expect((calls[0].body as { device_id: string }).device_id).toBe(id);
    expect(cookie(res, DEVICE_COOKIE)).toBeUndefined();
  });

  test("a device cookie that is not a console id is replaced", async () => {
    const { d, calls } = deps([CORE_OK, FIELD_OK]);
    await handleSignIn(signin(undefined, { cookies: { [DEVICE_COOKIE]: "phone-123456789" } }), d);
    expect((calls[0].body as { device_id: string }).device_id).toMatch(/^web-console:/);
  });

  test("the route module is wired to the server's fetch and environment", async () => {
    const f = scriptedFetch([CORE_OK, FIELD_OK]);
    vi.stubGlobal("fetch", f.fetchImpl);
    vi.stubEnv("FIELD_CONSOLE_CORE_URL", "https://api.scmtips.com");
    vi.stubEnv("FIELD_CONSOLE_FIELD_API_URL", "http://field-api:8020");
    const res = await signinRoute(signin());
    expect(res.status).toBe(200);
    expect(f.calls.map((c) => c.url)).toEqual(["https://api.scmtips.com/v1/auth/app/token", "http://field-api:8020/v1/auth/exchange"]);
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("M5-J01 sign-in route: each refusal in words, no cookie, no token", () => {
  const cases: Array<{ name: string; replies: Reply[]; status: number; code: string; text: RegExp }> = [
    { name: "wrong password (core 401)", replies: [{ status: 401, body: { detail: "Incorrect email or password." } }], status: 401, code: "invalid_credentials", text: /e-mail or password is not right/ },
    { name: "pairing required (core 403 problem code)", replies: [{ status: 403, body: { code: "pairing_required", title: "Forbidden" } }], status: 403, code: "pairing_required", text: /pairing code/ },
    { name: "pairing required (core 403 detail)", replies: [{ status: 403, body: { detail: "pairing_required" } }], status: 403, code: "pairing_required", text: /pairing code/ },
    { name: "single sign-on required", replies: [{ status: 403, body: { code: "sso_required" } }], status: 403, code: "sso_required", text: /single sign-on/ },
    { name: "too many attempts (core 429)", replies: [{ status: 429, body: { detail: "Too many attempts." } }], status: 429, code: "too_many_attempts", text: /Too many tries/ },
    { name: "core cannot issue tokens (503)", replies: [{ status: 503, body: { code: "core_tokens_unavailable" } }], status: 503, code: "core_tokens_unavailable", text: /cannot sign anyone in/ },
    { name: "core refuses the request shape (422)", replies: [{ status: 422, body: { detail: [{ msg: "bad" }] } }], status: 502, code: "core_error", text: /HTTP 422/ },
    { name: "core unreachable", replies: [new TypeError("fetch failed")], status: 502, code: "core_unreachable", text: /could not reach SCMTIPS/ },
    { name: "core answers without a token", replies: [{ status: 200, body: { token_type: "Bearer" } }], status: 502, code: "core_unexpected", text: /cannot read/ },
    {
      name: "no Field role (field 403, its detail shown)",
      replies: [CORE_OK, { status: 403, body: { code: "FIELD-AUTH-403-NO-FIELD-ROLE", title: "No SCMTips Field role", detail: "Your SCMTIPS account has no role that SCMTips Field can use (your roles: viewer). Ask your administrator." } }],
      status: 403, code: "FIELD-AUTH-403-NO-FIELD-ROLE", text: /your roles: viewer/,
    },
    { name: "device refused by field", replies: [CORE_OK, { status: 403, body: { code: "FIELD-AUTH-403-DEVICE-REVOKED" } }], status: 403, code: "FIELD-AUTH-403-DEVICE-REVOKED", text: /refused this sign-in for this browser/ },
    { name: "exchange rejected (field 401)", replies: [CORE_OK, { status: 401, body: { code: "FIELD-AUTH-401-UNAUTHORIZED" } }], status: 502, code: "exchange_rejected", text: /did not accept/ },
    { name: "field-api unreachable", replies: [CORE_OK, new TypeError("fetch failed")], status: 502, code: "field_unreachable", text: /could not reach SCMTips Field/ },
    { name: "field-api answers an odd shape", replies: [CORE_OK, { status: 200, body: { access_token: "x" } }], status: 502, code: "field_unexpected", text: /shape/ },
  ];

  for (const c of cases) {
    test(c.name, async () => {
      const { d } = deps(c.replies);
      const res = await handleSignIn(signin(), d);
      expect(res.status).toBe(c.status);
      const text = await bodyText(res);
      const body = JSON.parse(text) as { code: string; message: string };
      expect(body.code).toBe(c.code);
      expect(body.message).toMatch(c.text);
      expect(text).not.toContain(CORE_JWT);
      expect(text).not.toContain("wearable-secret");
      expect(cookie(res, FIELD_COOKIE)).toBeUndefined();
      expect(cookie(res, CORE_COOKIE)).toBeUndefined();
    });
  }

  test("429 passes the core's Retry-After on", async () => {
    const f = scriptedFetch([{ status: 429, body: {} }]);
    const fetchImpl = async (u: string, i?: RequestInit) => {
      const r = await f.fetchImpl(u, i);
      return new Response(await r.text(), { status: 429, headers: { "Retry-After": "300" } });
    };
    const res = await handleSignIn(signin(), { fetch: fetchImpl, env: ENV, nowS: () => NOW_S, newId: () => "id-0000-0000" });
    expect(res.status).toBe(429);
    expect(res.headers.get("Retry-After")).toBe("300");
  });

  test("not configured, cross-site, bad input and non-JSON never reach the core", async () => {
    for (const [r, env, status, code] of [
      [signin(), {}, 404, "not_configured"],
      [signin(undefined, { headers: { "sec-fetch-site": "cross-site", origin: "https://evil.example" } }), ENV, 403, "cross_site"],
      [signin({ email: "nobody", password: "pw" }), ENV, 400, "email"],
      [signin({ email: "a@b.c", password: "" }), ENV, 400, "password"],
      [req("/api/console-auth/signin", { body: { email: "a@b.c", password: "x" }, headers: { "content-type": "text/plain" } }), ENV, 415, "bad_request"],
    ] as const) {
      const { d, calls } = deps([], env);
      const res = await handleSignIn(r, d);
      expect(res.status).toBe(status);
      expect(((await res.json()) as { code: string }).code).toBe(code);
      expect(calls).toHaveLength(0);
    }
  });

  test("an older browser without Sec-Fetch-Site is accepted only with this host's Origin", async () => {
    const ok = new NextRequest(`${HOST}/api/console-auth/signin`, {
      method: "POST", headers: { "content-type": "application/json", origin: HOST, host: "hud.scmtips.com" },
      body: JSON.stringify({ email: "a@b.c", password: "x" }),
    });
    expect((await handleSignIn(ok, deps([CORE_OK, FIELD_OK]).d)).status).toBe(200);
    const bad = new NextRequest(`${HOST}/api/console-auth/signin`, {
      method: "POST", headers: { "content-type": "application/json", origin: "https://evil.example", host: "hud.scmtips.com" },
      body: JSON.stringify({ email: "a@b.c", password: "x" }),
    });
    expect((await handleSignIn(bad, deps([]).d)).status).toBe(403);
  });
});

describe("M5-J01 refresh and sign-out", () => {
  test("refresh re-exchanges the core token from its cookie and sets a new field cookie", async () => {
    const { d, calls } = deps([FIELD_OK]);
    const res = await handleRefresh(req("/api/console-auth/refresh", { cookies: { [CORE_COOKIE]: CORE_JWT } }), d);
    expect(res.status).toBe(200);
    expect(calls[0].body).toEqual({ device_token: CORE_JWT, client_id: "field-console" });
    const text = await bodyText(res);
    expect(text).not.toContain(CORE_JWT);
    expect(text).not.toContain(FIELD_JWT);
    expect(JSON.parse(text).session).toMatchObject({ principalId: "u-approver", email: "approver@sample.test", expiresIn: 600, coreExpiresIn: 3600 });
    expect(cookie(res, FIELD_COOKIE)).toContain(FIELD_JWT);
  });

  test("no core cookie, an expired one, or an exchange 401 ends the session and clears the cookies", async () => {
    const expired = jwt({ sub: "u", exp: NOW_S - 1 });
    for (const [cookies, replies] of [
      [{}, []],
      [{ [CORE_COOKIE]: expired }, []],
      [{ [CORE_COOKIE]: "not-a-jwt" }, []],
      [{ [CORE_COOKIE]: CORE_JWT }, [{ status: 401, body: {} }]],
    ] as Array<[Record<string, string>, Reply[]]>) {
      const { d } = deps(replies);
      const res = await handleRefresh(req("/api/console-auth/refresh", { cookies }), d);
      expect(res.status).toBe(401);
      expect(((await res.json()) as { code: string }).code).toBe("session_ended");
      expect(cookie(res, FIELD_COOKIE)).toMatch(/Max-Age=0/);
      expect(cookie(res, CORE_COOKIE)).toMatch(/Max-Age=0/);
    }
  });

  test("sign-out clears both token cookies and keeps the device id", async () => {
    const res = await handleSignOut(req("/api/console-auth/signout"), { env: ENV });
    expect(res.status).toBe(204);
    expect(cookie(res, FIELD_COOKIE)).toMatch(/Max-Age=0/);
    expect(cookie(res, CORE_COOKIE)).toMatch(/Max-Age=0/);
    expect(cookie(res, DEVICE_COOKIE)).toBeUndefined();
    expect((await handleSignOut(req("/api/console-auth/signout", { headers: { "sec-fetch-site": "cross-site" } }), { env: ENV })).status).toBe(403);
  });
});

describe("M5-J01 settings and cookie flags", () => {
  test("core sign-in is offered only with FIELD_CONSOLE_CORE_URL; field-api falls back to the rewrite target", () => {
    expect(coreSignInConfig({})).toBeNull();
    expect(coreSignInConfig({ FIELD_CONSOLE_CORE_URL: "  " })).toBeNull();
    expect(coreSignInConfig({ FIELD_CONSOLE_CORE_URL: "https://api.scmtips.com/" })).toEqual({ coreUrl: "https://api.scmtips.com", fieldApiUrl: "http://127.0.0.1:8020" });
    expect(coreSignInConfig({ FIELD_CONSOLE_CORE_URL: "http://api:8000", NEXT_PUBLIC_FIELD_API_URL: "http://field-api:8020/" })?.fieldApiUrl).toBe("http://field-api:8020");
  });

  test("Secure in production and over https; off only by FIELD_CONSOLE_COOKIE_SECURE=0", () => {
    expect(secureCookies({ NODE_ENV: "production" }, "http://console:3000/x", null)).toBe(true);
    expect(secureCookies({ NODE_ENV: "production", FIELD_CONSOLE_COOKIE_SECURE: "0" }, "http://x/", null)).toBe(false);
    expect(secureCookies({ NODE_ENV: "development" }, "http://127.0.0.1:3000/x", null)).toBe(false);
    expect(secureCookies({ NODE_ENV: "development" }, "http://127.0.0.1:3000/x", "https")).toBe(true);
    expect(secureCookies({}, "https://hud.scmtips.com/x", null)).toBe(true);
  });
});

describe("M5-J01 /v1 middleware: the cookie becomes the bearer token", () => {
  const same = (h: Record<string, string> = {}) => new Headers({ "sec-fetch-site": "same-origin", ...h });

  test("added for the console's own calls with no token, or the empty one the older pages send", () => {
    expect(authorizationFor(same(), `${HOST}/v1/tasks`, "tok")).toBe("Bearer tok");
    expect(authorizationFor(same({ authorization: "Bearer " }), `${HOST}/v1/sites/1`, "tok")).toBe("Bearer tok");
    expect(authorizationFor(same({ authorization: "Bearer undefined" }), `${HOST}/v1/sites/1`, "tok")).toBe("Bearer tok");
  });

  test("left alone for the development sign-in's bearer, without a cookie, and from other sites", () => {
    expect(authorizationFor(same({ authorization: "Bearer dev-token" }), `${HOST}/v1/tasks`, "tok")).toBeNull();
    expect(authorizationFor(same(), `${HOST}/v1/tasks`, undefined)).toBeNull();
    expect(authorizationFor(new Headers({ "sec-fetch-site": "cross-site" }), `${HOST}/v1/tasks`, "tok")).toBeNull();
    expect(authorizationFor(new Headers({ "sec-fetch-site": "none" }), `${HOST}/v1/tasks`, "tok")).toBeNull();
    expect(authorizationFor(new Headers(), `${HOST}/v1/tasks`, "tok")).toBeNull();
  });

  test("middleware forwards the header to the /v1 rewrite", () => {
    const r = new NextRequest(`${HOST}/v1/tasks`, { headers: { "sec-fetch-site": "same-origin", cookie: `${FIELD_COOKIE}=tok` } });
    const res = middleware(r);
    expect(res.headers.get("x-middleware-request-authorization")).toBe("Bearer tok");
    const none = middleware(new NextRequest(`${HOST}/v1/tasks`, { headers: { "sec-fetch-site": "same-origin" } }));
    expect(none.headers.get("x-middleware-request-authorization")).toBeNull();
  });
});

describe("M5-J01 browser half", () => {
  const SESSION_BODY = {
    session: {
      principalId: "u-approver", tenantId: TENANT, displayName: "Asha Approver", email: "approver@sample.test",
      roles: ["field.supervisor"], permissions: ["field.task.read"], siteIds: ["*"], expiresIn: 600, coreExpiresIn: 3600,
    },
  };

  test("sign-in posts only to the console's server and keeps a cookie session with no token", async () => {
    const f = scriptedFetch([{ status: 200, body: SESSION_BODY }]);
    const s = await coreSignIn(f.fetchImpl, " approver@sample.test ", "pw", NOW);
    expect(f.calls[0].url).toBe("/api/console-auth/signin");
    expect(f.calls[0].body).toEqual({ email: "approver@sample.test", password: "pw" });
    expect(s).toEqual({
      accessToken: "", transport: "cookie", expiresAt: NOW + 600_000, signInEndsAt: NOW + 3_600_000, principalId: "u-approver",
      tenantId: TENANT, roles: ["field.supervisor"], permissions: ["field.task.read"], siteIds: ["*"], displayName: "Asha Approver",
    });
    expect(parseSession(JSON.stringify(s))).toEqual(s);
    expect(parseSession(JSON.stringify({ ...s, accessToken: "leaked" }))).toBeNull();
    expect(refreshDelayMs(s, NOW)).toBe(540_000);
    expect(refreshDelayMs(s, NOW + 599_000)).toBe(5_000);
  });

  test("the server's sentence is what the person sees", async () => {
    const f = scriptedFetch([{ status: 401, body: { code: "invalid_credentials", message: "The e-mail or password is not right." } }]);
    await expect(coreSignIn(f.fetchImpl, "a@b.c", "x", NOW)).rejects.toMatchObject({ status: 401, code: "invalid_credentials", message: "The e-mail or password is not right." });
    const down = scriptedFetch([new TypeError("offline")]);
    await expect(coreSignIn(down.fetchImpl, "a@b.c", "x", NOW)).rejects.toBeInstanceOf(CoreSignInError);
  });

  test("refresh keeps the person's name and renews the expiry", async () => {
    const f = scriptedFetch([{ status: 200, body: { session: { ...SESSION_BODY.session, displayName: "approver@sample.test", coreExpiresIn: 3000 } } }]);
    const prev = await coreSignIn(scriptedFetch([{ status: 200, body: SESSION_BODY }]).fetchImpl, "a@b.c", "x", NOW);
    const next = await refreshCoreSession(f.fetchImpl, prev, NOW + 540_000);
    expect(f.calls[0].url).toBe("/api/console-auth/refresh");
    expect(next).toMatchObject({ displayName: "Asha Approver", expiresAt: NOW + 1_140_000, signInEndsAt: NOW + 540_000 + 3_000_000, accessToken: "" });
  });
});
