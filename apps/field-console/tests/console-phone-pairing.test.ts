/**
 * M5-L03: "Sign in your phone". The console's server asks the SCMTIPS core for a pairing code with the person's core
 * token (contract §4) and answers only the code, its end and the App Link; the browser half words the countdown.
 * Every call runs with an injected fetch (no network); the core is a scripted test double built from the contract.
 */
import { NextRequest } from "next/server";
import { afterEach, describe, expect, test, vi } from "vitest";
import { POST as pairingRoute } from "../app/api/console-auth/pairing/route";
import { handlePairing, type HandlerDeps } from "../lib/consoleAuthHandlers";
import { CORE_COOKIE, FIELD_COOKIE } from "../lib/coreSignIn";
import { appLinkBase, DEFAULT_APP_LINK_BASE, pairLink, PAIRING_COPY } from "../lib/phonePairing";
import { countdownText, newPhonePairing, PairingError, PAIRING_PATH, PHONE_STEPS, secondsLeft, spacedCode } from "../lib/phonePairingClient";
import { NOW, scriptedFetch, type Reply } from "./helpers";

const HOST = "https://hud.scmtips.com";
const ENV = { FIELD_CONSOLE_CORE_URL: "https://api.scmtips.com/", NODE_ENV: "production" };
const NOW_S = Math.floor(NOW / 1000);
const CORE_TOKEN = "eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiJ1LWFwcHJvdmVyIn0.core-token-signature";
const EXPIRES_AT = new Date(NOW + 10 * 60_000).toISOString();
const CORE_OK: Reply = { status: 201, body: { code: "K7Q2M9XW", expires_at: EXPIRES_AT } };

function deps(replies: Reply[] | ((c: { url: string }) => Reply), env: Record<string, string | undefined> = ENV) {
  const f = scriptedFetch(replies);
  const d: HandlerDeps = { fetch: f.fetchImpl, env, nowS: () => NOW_S, newId: () => "unused" };
  return { d, calls: f.calls };
}

function req(opts: { cookies?: Record<string, string>; headers?: Record<string, string> } = {}) {
  const headers: Record<string, string> = { "sec-fetch-site": "same-origin", origin: HOST, ...(opts.headers ?? {}) };
  if (opts.cookies) headers.cookie = Object.entries(opts.cookies).map(([k, v]) => `${k}=${v}`).join("; ");
  return new NextRequest(`${HOST}/api/console-auth/pairing`, { method: "POST", headers });
}

const signedIn = () => req({ cookies: { [CORE_COOKIE]: CORE_TOKEN } });

/** Everything the browser receives: status line, headers and body. */
async function everything(res: Response): Promise<string> {
  const headers = [...res.headers.entries()].map(([k, v]) => `${k}: ${v}`).join("\n");
  return `${res.status}\n${headers}\n${await res.clone().text()}`;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("M5-L03 pairing route: the core's code as an App Link, never the token", () => {
  test("core 201: calls the core's pairing-codes with the bearer and X-Requested-With, answers code, expiry and link only", async () => {
    const { d, calls } = deps([CORE_OK]);
    const res = await handlePairing(signedIn(), d);
    expect(res.status).toBe(200);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("https://api.scmtips.com/v1/wearable/pairing-codes");
    expect(calls[0].method).toBe("POST");
    expect(calls[0].headers.Authorization).toBe(`Bearer ${CORE_TOKEN}`);
    expect(calls[0].headers["X-Requested-With"]).toBe("lr");
    expect(await res.clone().json()).toEqual({
      code: "K7Q2M9XW",
      expires_at: EXPIRES_AT,
      expires_in: 600,
      link: "https://app.scmtips.com/pair?code=K7Q2M9XW",
    });
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(res.headers.getSetCookie()).toEqual([]);
    expect(await everything(res)).not.toContain(CORE_TOKEN);
  });

  test("no core sign-in cookie: 401, the core is not called", async () => {
    const { d, calls } = deps([]);
    const res = await handlePairing(req(), d);
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ code: "not_signed_in", message: PAIRING_COPY.notSignedIn });
    expect(calls).toHaveLength(0);
  });

  test("only the field token cookie (no core token) is still 401", async () => {
    const { d, calls } = deps([]);
    const res = await handlePairing(req({ cookies: { [FIELD_COOKIE]: "field.jwt" } }), d);
    expect(res.status).toBe(401);
    expect(calls).toHaveLength(0);
  });

  test("core 403: Your account can't sign in phones", async () => {
    const { d } = deps([{ status: 403, body: { type: "about:blank", code: "forbidden", detail: "Pairing glasses needs voice.approve." } }]);
    const res = await handlePairing(signedIn(), d);
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ code: "forbidden", message: "Your account can't sign in phones." });
  });

  test("core 5xx: a plain message, the core's body is not passed on", async () => {
    for (const status of [500, 502, 504]) {
      const { d } = deps([{ status, text: `Traceback: token=${CORE_TOKEN}` }]);
      const res = await handlePairing(signedIn(), d);
      expect(res.status).toBe(502);
      const all = await everything(res);
      expect(all).not.toContain(CORE_TOKEN);
      expect(all).not.toContain("Traceback");
      expect(await res.json()).toEqual({ code: "core_error", message: PAIRING_COPY.coreError });
    }
    const { d } = deps([{ status: 503, body: { code: "maintenance" } }]);
    const res = await handlePairing(signedIn(), d);
    expect(res.status).toBe(503);
    expect((await res.json()).message).toBe(PAIRING_COPY.coreUnavailable);
  });

  test("core 401: the sign-in has ended, the token cookies are cleared", async () => {
    const { d } = deps([{ status: 401, body: { code: "unauthenticated" } }]);
    const res = await handlePairing(signedIn(), d);
    expect(res.status).toBe(401);
    expect((await res.json()).code).toBe("session_ended");
    const cookies = res.headers.getSetCookie();
    expect(cookies.find((c) => c.startsWith(`${CORE_COOKIE}=;`))).toMatch(/Max-Age=0/);
    expect(cookies.find((c) => c.startsWith(`${FIELD_COOKIE}=;`))).toMatch(/Max-Age=0/);
  });

  test("core 429: too many codes, Retry-After passed on", async () => {
    const d: HandlerDeps = {
      fetch: async () => new Response(JSON.stringify({ code: "rate_limited" }), { status: 429, headers: { "Retry-After": "42" } }),
      env: ENV, nowS: () => NOW_S, newId: () => "unused",
    };
    const res = await handlePairing(signedIn(), d);
    expect(res.status).toBe(429);
    expect(res.headers.get("retry-after")).toBe("42");
    expect((await res.json()).message).toBe(PAIRING_COPY.tooMany);
  });

  test("core unreachable or an answer without a code: plain messages", async () => {
    const down = deps([new Error(`connect ECONNREFUSED, Authorization: Bearer ${CORE_TOKEN}`)]);
    const r1 = await handlePairing(signedIn(), down.d);
    expect(r1.status).toBe(502);
    expect(await everything(r1)).not.toContain(CORE_TOKEN);
    expect((await r1.json()).code).toBe("core_unreachable");
    for (const body of [{}, { code: "", expires_at: EXPIRES_AT }, { code: "K7Q2M9XW" }, { code: "bad code!", expires_at: EXPIRES_AT }, { code: "K7Q2M9XW", expires_at: "soon" }]) {
      const { d } = deps([{ status: 201, body }]);
      const res = await handlePairing(signedIn(), d);
      expect(res.status).toBe(502);
      expect((await res.json()).code).toBe("core_unexpected");
    }
  });

  test("never follows a redirect with the bearer token", async () => {
    let init: RequestInit | undefined;
    const d: HandlerDeps = {
      fetch: async (_url, i) => {
        init = i;
        return new Response(JSON.stringify({ code: "K7Q2M9XW", expires_at: EXPIRES_AT }), { status: 201 });
      },
      env: ENV, nowS: () => NOW_S, newId: () => "unused",
    };
    await handlePairing(signedIn(), d);
    expect(init?.redirect).toBe("error");
    expect(init?.cache).toBe("no-store");
  });

  test("a cross-site request is refused before the core is called", async () => {
    const { d, calls } = deps([CORE_OK]);
    const res = await handlePairing(req({ cookies: { [CORE_COOKIE]: CORE_TOKEN }, headers: { "sec-fetch-site": "cross-site", origin: "https://evil.example" } }), d);
    expect(res.status).toBe(403);
    expect((await res.json()).code).toBe("cross_site");
    expect(calls).toHaveLength(0);
  });

  test("without FIELD_CONSOLE_CORE_URL the route is not offered (404)", async () => {
    const { d, calls } = deps([CORE_OK], { NODE_ENV: "production" });
    const res = await handlePairing(signedIn(), d);
    expect(res.status).toBe(404);
    expect((await res.json()).code).toBe("not_configured");
    expect(calls).toHaveLength(0);
  });

  test("FIELD_CONSOLE_APP_LINK_BASE sets the link's host; a bad value falls back to app.scmtips.com", async () => {
    expect(appLinkBase({})).toBe(DEFAULT_APP_LINK_BASE);
    expect(DEFAULT_APP_LINK_BASE).toBe("https://app.scmtips.com");
    expect(appLinkBase({ FIELD_CONSOLE_APP_LINK_BASE: "https://staging.scmtips.com/" })).toBe("https://staging.scmtips.com");
    for (const bad of ["javascript:alert(1)", "app.scmtips.com", "https://a.test/?x=1", "https://u:p@a.test"]) {
      expect(appLinkBase({ FIELD_CONSOLE_APP_LINK_BASE: bad })).toBe(DEFAULT_APP_LINK_BASE);
    }
    expect(pairLink("https://app.scmtips.com", "AB 12&x")).toBe("https://app.scmtips.com/pair?code=AB%2012%26x");
    const { d } = deps([CORE_OK], { ...ENV, FIELD_CONSOLE_APP_LINK_BASE: "https://staging.scmtips.com" });
    expect((await (await handlePairing(signedIn(), d)).json()).link).toBe("https://staging.scmtips.com/pair?code=K7Q2M9XW");
  });

  test("the pairing route module is wired to the server's fetch and environment", async () => {
    const f = scriptedFetch([CORE_OK]);
    vi.stubGlobal("fetch", f.fetchImpl);
    vi.stubEnv("FIELD_CONSOLE_CORE_URL", "http://api:8000");
    const res = await pairingRoute(signedIn());
    expect(res.status).toBe(200);
    expect(f.calls[0].url).toBe("http://api:8000/v1/wearable/pairing-codes");
    expect((await res.json()).link).toBe("https://app.scmtips.com/pair?code=K7Q2M9XW");
  });
});

describe("M5-L03 pairing page: the browser half", () => {
  test("asks only the console's own server and counts down from the server's expires_in", async () => {
    const f = scriptedFetch([{ status: 200, body: { code: "K7Q2M9XW", expires_at: "1999-01-01T00:00:00Z", expires_in: 300, link: "https://app.scmtips.com/pair?code=K7Q2M9XW" } }]);
    const p = await newPhonePairing(f.fetchImpl, NOW);
    expect(f.calls[0].url).toBe(PAIRING_PATH);
    expect(f.calls[0].url).toBe("/api/console-auth/pairing");
    expect(f.calls[0].method).toBe("POST");
    expect(f.calls[0].headers.Authorization).toBeUndefined();
    expect(p).toEqual({ code: "K7Q2M9XW", link: "https://app.scmtips.com/pair?code=K7Q2M9XW", expiresAtMs: NOW + 300_000 });
  });

  test("a refusal carries the server's sentence", async () => {
    const f = scriptedFetch([{ status: 403, body: { code: "forbidden", message: "Your account can't sign in phones." } }]);
    const err = await newPhonePairing(f.fetchImpl, NOW).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(PairingError);
    expect((err as PairingError).status).toBe(403);
    expect((err as PairingError).message).toBe("Your account can't sign in phones.");
    const down = await newPhonePairing(async () => Promise.reject(new Error("offline")), NOW).catch((e: unknown) => e);
    expect((down as PairingError).code).toBe("network");
    const odd = await newPhonePairing(scriptedFetch([{ status: 200, body: { code: "X" } }]).fetchImpl, NOW).catch((e: unknown) => e);
    expect((odd as PairingError).code).toBe("unexpected");
  });

  test("countdown text", () => {
    expect(countdownText(NOW + 600_000, NOW)).toBe("Works for 10:00 more");
    expect(countdownText(NOW + 545_000, NOW)).toBe("Works for 9:05 more");
    expect(countdownText(NOW + 60_000, NOW)).toBe("Works for 1:00 more");
    expect(countdownText(NOW + 59_000, NOW)).toBe("Works for 59 seconds more");
    expect(countdownText(NOW + 1_000, NOW)).toBe("Works for 1 second more");
    expect(countdownText(NOW + 400, NOW)).toBe("Works for 1 second more");
    expect(countdownText(NOW, NOW)).toBe("This code has ended. Get a new code.");
    expect(countdownText(NOW - 5_000, NOW)).toBe("This code has ended. Get a new code.");
    expect(secondsLeft(NOW - 5_000, NOW)).toBe(0);
  });

  test("the code is shown in groups of four, and the three steps are the contract's", () => {
    expect(spacedCode("K7Q2M9XW")).toBe("K7Q2 M9XW");
    expect(spacedCode("ABCD")).toBe("ABCD");
    expect(spacedCode("ABCDEFGHIJ")).toBe("ABCD EFGH IJ");
    expect(PHONE_STEPS).toEqual([
      "Open SCMTips Field on your phone.",
      "Tap Scan a code from your computer.",
      "Point the camera at this code.",
    ]);
  });
});
