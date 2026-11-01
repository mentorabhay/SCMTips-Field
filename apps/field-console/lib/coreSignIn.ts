/**
 * Hosted sign-in through the SCMTIPS core (M5-J01), run only on the console's own server (route handlers under
 * app/api/console-auth). The browser sends e-mail + password to this server; the server signs in at the core
 * (`POST {core}/v1/auth/app/token`, `X-Requested-With: lr`, the same call as the phone's CoreSignIn), exchanges the
 * core token at field-api (`POST /v1/auth/exchange`, `client_id: field-console`, no device id) and keeps both
 * tokens in httpOnly cookies. No token is ever put in a response body, so neither reaches browser JavaScript, and
 * the browser never calls the core (no CORS needed).
 *
 * Settings (server-only, read at request time; names only, A-02):
 *   FIELD_CONSOLE_CORE_URL       the core, e.g. https://api.scmtips.com or http://api:8000 on the host. Set = shown.
 *   FIELD_CONSOLE_FIELD_API_URL  field-api for the exchange; default NEXT_PUBLIC_FIELD_API_URL (the /v1 rewrite
 *                                target), else http://127.0.0.1:8020.
 *   FIELD_CONSOLE_COOKIE_SECURE  "0" drops the Secure flag (plain-http test hosts only). Default: Secure in a
 *                                production build, and whenever the request came over https.
 *
 * Every dependency is injected (fetch, env, clock, id source) so tests run with no network.
 */

// ------------------------------------------------------------------ names

/** The field token (600 s at most). Path /v1: the browser sends it only to the field-api proxy. */
export const FIELD_COOKIE = "scmtips_field_token";
/** The core token, kept only to re-exchange before the field token expires. Never leaves /api/console-auth. */
export const CORE_COOKIE = "scmtips_core_token";
/** The stable per-browser device id the core binds its token to. Not a secret. */
export const DEVICE_COOKIE = "scmtips_console_device";

export const FIELD_COOKIE_PATH = "/v1";
export const AUTH_COOKIE_PATH = "/api/console-auth";

/** The core binds its token to this id; field-api exchanges such a token without a field device (M5-J01). */
export const WEB_CONSOLE_DEVICE_PREFIX = "web-console:";
export const DEVICE_MODEL = "WEB_CONSOLE";
/** The only client value the core accepts (`client: Literal["scmtips-field"]`). */
export const CORE_CLIENT = "scmtips-field";
export const FIELD_CLIENT_ID = "field-console";

const DEVICE_ID_RE = /^[A-Za-z0-9._:-]{8,64}$/;
const DEVICE_COOKIE_MAX_AGE_S = 400 * 24 * 3600; // the longest lifetime browsers keep
const TIMEOUT_MS = 10_000;

// ------------------------------------------------------------------ config

export interface CoreSignInConfig {
  coreUrl: string;
  fieldApiUrl: string;
}

export type Env = Record<string, string | undefined>;

const trim = (v: string | undefined) => (v && v.trim() ? v.trim().replace(/\/+$/, "") : "");

/** null when FIELD_CONSOLE_CORE_URL is not set: the login page then does not offer this sign-in. */
export function coreSignInConfig(env: Env): CoreSignInConfig | null {
  const coreUrl = trim(env.FIELD_CONSOLE_CORE_URL);
  if (!coreUrl) return null;
  const fieldApiUrl = trim(env.FIELD_CONSOLE_FIELD_API_URL) || trim(env.NEXT_PUBLIC_FIELD_API_URL) || "http://127.0.0.1:8020";
  return { coreUrl, fieldApiUrl };
}

// ------------------------------------------------------------------ results

/** What the browser keeps about the session: everything but the tokens. */
export interface SessionInfo {
  principalId: string;
  tenantId: string;
  displayName: string;
  email: string | null;
  roles: string[];
  permissions: string[];
  siteIds: string[];
  /** Seconds the field token (cookie) is valid; the browser refreshes before it ends. */
  expiresIn: number;
  /** Seconds the core token is valid; after it the person signs in again. */
  coreExpiresIn: number;
}

export interface Refusal {
  status: number;
  code: string;
  message: string;
  retryAfter?: string;
}

export type SignInResult =
  | { ok: true; info: SessionInfo; fieldToken: string; coreToken: string }
  | { ok: false; refusal: Refusal };

export const COPY = {
  notConfigured: "Sign-in through SCMTIPS is not set up on this console.",
  badRequest: "Enter your e-mail address and password.",
  email: "Enter your work e-mail address.",
  password: "Enter your password.",
  invalidCredentials: "The e-mail or password is not right.",
  pairingRequired:
    "Your organisation signs in to SCMTIPS with a pairing code, which this console does not take. On the hosted demo, e-mail and password work for the SAMPLE organisation's members.",
  ssoRequired: "Your organisation signs in to SCMTIPS with single sign-on, which this console does not offer yet.",
  tooManyAttempts: "Too many tries. Wait a few minutes, then try again.",
  coreUnavailable: "SCMTIPS cannot sign anyone in right now. Try again later.",
  coreUnreachable: "We could not reach SCMTIPS sign-in. Try again in a moment.",
  coreUnexpected: "SCMTIPS answered something this console cannot read. Try again later.",
  fieldUnreachable: "We could not reach SCMTips Field. Try again in a moment.",
  exchangeRejected: "SCMTips Field did not accept the SCMTIPS sign-in. Try again; if it keeps happening, tell your administrator.",
  deviceRevoked: "SCMTips Field refused this sign-in for this browser. Tell your administrator.",
  noFieldRole: "Your SCMTIPS account has no role that SCMTips Field can use. Ask your administrator for one.",
  sessionEnded: "Your sign-in has ended. Sign in again.",
  crossSite: "This sign-in must come from the console's own page.",
} as const;

const refuse = (status: number, code: string, message: string, retryAfter?: string): { ok: false; refusal: Refusal } => ({
  ok: false,
  refusal: retryAfter ? { status, code, message, retryAfter } : { status, code, message },
});

// ------------------------------------------------------------------ helpers

export interface Deps {
  fetch: (input: string, init?: RequestInit) => Promise<Response>;
  config: CoreSignInConfig;
}

type Json = Record<string, unknown>;

async function readJson(res: Response): Promise<Json | null> {
  try {
    const v: unknown = JSON.parse(await res.text());
    return v && typeof v === "object" && !Array.isArray(v) ? (v as Json) : null;
  } catch {
    return null;
  }
}

/** The machine code of a core or field problem body: `code`, or a snake_case `detail` (the phone reads it the same way). */
function problemCode(body: Json | null): string | null {
  if (!body) return null;
  if (typeof body.code === "string" && body.code) return body.code;
  if (typeof body.detail === "string" && /^[a-z_]+$/.test(body.detail)) return body.detail;
  return null;
}

const strings = (v: unknown): string[] | null =>
  Array.isArray(v) && v.every((x) => typeof x === "string") ? (v as string[]) : null;

async function call(deps: Deps, url: string, body: unknown, headers: Record<string, string> = {}): Promise<Response> {
  return deps.fetch(url, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
}

/** The core's refusals in words (401, 403 pairing_required / sso_required, 429, 503), as the phone shows them. */
export function coreRefusal(status: number, body: Json | null, retryAfter: string | null): { ok: false; refusal: Refusal } {
  const code = problemCode(body);
  if (status === 401) return refuse(401, "invalid_credentials", COPY.invalidCredentials);
  if (status === 403 && code === "pairing_required") return refuse(403, "pairing_required", COPY.pairingRequired);
  if (status === 403 && code === "sso_required") return refuse(403, "sso_required", COPY.ssoRequired);
  if (status === 429) return refuse(429, "too_many_attempts", COPY.tooManyAttempts, retryAfter ?? undefined);
  if (status === 503) return refuse(503, code ?? "core_unavailable", COPY.coreUnavailable);
  if (status === 403) return refuse(403, code ?? "core_forbidden", `SCMTIPS does not allow this sign-in (${code ?? "403"}).`);
  return refuse(502, "core_error", `SCMTIPS refused the sign-in (HTTP ${status}${code ? ` ${code}` : ""}).`);
}

/** field-api's refusals of the exchange; its FIELD-AUTH-403-NO-FIELD-ROLE detail is the sentence to show. */
export function fieldRefusal(status: number, body: Json | null): { ok: false; refusal: Refusal } {
  const code = problemCode(body);
  if (status === 403 && code === "FIELD-AUTH-403-NO-FIELD-ROLE") {
    const detail = body && typeof body.detail === "string" && body.detail.trim() ? body.detail.trim() : COPY.noFieldRole;
    return refuse(403, code, detail);
  }
  if (status === 403 && code === "FIELD-AUTH-403-DEVICE-REVOKED") return refuse(403, code, COPY.deviceRevoked);
  if (status === 401) return refuse(502, "exchange_rejected", COPY.exchangeRejected);
  return refuse(502, "field_error", `SCMTips Field could not finish the sign-in (HTTP ${status}${code ? ` ${code}` : ""}).`);
}

// ------------------------------------------------------------------ device id

export function isDeviceId(v: string | undefined | null): v is string {
  return Boolean(v && v.startsWith(WEB_CONSOLE_DEVICE_PREFIX) && DEVICE_ID_RE.test(v));
}

/** The browser's device id from its cookie, or a new one (`web-console:<uuid>`, 48 characters). */
export function deviceIdFor(cookieValue: string | undefined, newId: () => string): { id: string; isNew: boolean } {
  if (isDeviceId(cookieValue)) return { id: cookieValue, isNew: false };
  return { id: `${WEB_CONSOLE_DEVICE_PREFIX}${newId()}`, isNew: true };
}

// ------------------------------------------------------------------ input

export interface Credentials {
  email: string;
  password: string;
}

export function parseCredentials(body: unknown): { ok: true; creds: Credentials } | { ok: false; refusal: Refusal } {
  if (!body || typeof body !== "object") return refuse(400, "bad_request", COPY.badRequest);
  const o = body as Json;
  const email = typeof o.email === "string" ? o.email.trim() : "";
  const password = typeof o.password === "string" ? o.password : "";
  if (!email || !email.includes("@") || email.length > 320) return refuse(400, "email", COPY.email);
  if (!password || password.length > 1024) return refuse(400, "password", COPY.password);
  return { ok: true, creds: { email, password } };
}

// ------------------------------------------------------------------ the two calls

interface CoreToken {
  accessToken: string;
  expiresIn: number;
  principalId: string;
  displayName: string;
  email: string | null;
}

async function coreAppToken(deps: Deps, creds: Credentials, deviceId: string): Promise<{ ok: true; core: CoreToken } | { ok: false; refusal: Refusal }> {
  let res: Response;
  try {
    res = await call(deps, `${deps.config.coreUrl}/v1/auth/app/token`, {
      email: creds.email,
      password: creds.password,
      device_id: deviceId,
      device_model: DEVICE_MODEL,
      display_capable: true,
      client: CORE_CLIENT,
    }, { "X-Requested-With": "lr" });
  } catch {
    return refuse(502, "core_unreachable", COPY.coreUnreachable);
  }
  const body = await readJson(res);
  if (!res.ok) return coreRefusal(res.status, body, res.headers.get("Retry-After"));
  const access = body && typeof body.access_token === "string" ? body.access_token : "";
  if (!access) return refuse(502, "core_unexpected", COPY.coreUnexpected);
  const user = body && body.user && typeof body.user === "object" ? (body.user as Json) : {};
  const claims = body && body.claims && typeof body.claims === "object" ? (body.claims as Json) : {};
  const expiresIn = typeof body?.expires_in === "number" && body.expires_in > 0 ? Math.floor(body.expires_in) : 3600;
  const email = typeof user.email === "string" && user.email ? user.email : null;
  return {
    ok: true,
    core: {
      accessToken: access,
      expiresIn,
      principalId: String(user.id ?? claims.sub ?? ""),
      displayName: (typeof user.display_name === "string" && user.display_name) || email || "Signed in",
      email,
    },
  };
}

interface FieldToken {
  accessToken: string;
  expiresIn: number;
  tenantId: string;
  roles: string[];
  permissions: string[];
  siteIds: string[];
}

async function fieldExchange(deps: Deps, coreToken: string): Promise<{ ok: true; field: FieldToken } | { ok: false; refusal: Refusal }> {
  let res: Response;
  try {
    res = await call(deps, `${deps.config.fieldApiUrl}/v1/auth/exchange`, { device_token: coreToken, client_id: FIELD_CLIENT_ID });
  } catch {
    return refuse(502, "field_unreachable", COPY.fieldUnreachable);
  }
  const body = await readJson(res);
  if (!res.ok) return fieldRefusal(res.status, body);
  const roles = strings(body?.roles);
  const permissions = strings(body?.permissions);
  const siteIds = strings(body?.site_ids);
  const access = typeof body?.access_token === "string" ? body.access_token : "";
  const expiresIn = typeof body?.expires_in === "number" ? Math.floor(body.expires_in) : 0;
  const tenantId = typeof body?.tenant_id === "string" ? body.tenant_id : "";
  if (!access || expiresIn < 1 || !tenantId || !roles || !permissions || !siteIds) {
    return refuse(502, "field_unexpected", "SCMTips Field answered the sign-in in a shape this console cannot read.");
  }
  return { ok: true, field: { accessToken: access, expiresIn, tenantId, roles, permissions, siteIds } };
}

function info(core: Omit<CoreToken, "accessToken">, field: FieldToken, coreExpiresIn: number): SessionInfo {
  return {
    principalId: core.principalId,
    tenantId: field.tenantId,
    displayName: core.displayName,
    email: core.email,
    roles: field.roles,
    permissions: field.permissions,
    siteIds: field.siteIds,
    expiresIn: field.expiresIn,
    coreExpiresIn,
  };
}

/** E-mail + password -> core app token -> field token. */
export async function signInWithCore(deps: Deps, creds: Credentials, deviceId: string): Promise<SignInResult> {
  const c = await coreAppToken(deps, creds, deviceId);
  if (!c.ok) return c;
  const f = await fieldExchange(deps, c.core.accessToken);
  if (!f.ok) return f;
  return { ok: true, info: info(c.core, f.field, c.core.expiresIn), fieldToken: f.field.accessToken, coreToken: c.core.accessToken };
}

/** The core token's payload (no signature check: field-api verifies the token; this only reads its claims). */
export function jwtPayload(token: string): Json | null {
  const part = token.split(".")[1];
  if (!part) return null;
  try {
    const b64 = part.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(part.length / 4) * 4, "=");
    const bytes = Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
    const v: unknown = JSON.parse(new TextDecoder().decode(bytes));
    return v && typeof v === "object" ? (v as Json) : null;
  } catch {
    return null;
  }
}

/** A new field token from the core token in the cookie, before the field token's 600 s end. */
export async function refreshWithCore(deps: Deps, coreToken: string | undefined, nowS: number): Promise<SignInResult> {
  const claims = coreToken ? jwtPayload(coreToken) : null;
  const exp = claims && typeof claims.exp === "number" ? claims.exp : 0;
  if (!coreToken || !claims || exp - nowS < 5) return refuse(401, "session_ended", COPY.sessionEnded);
  const f = await fieldExchange(deps, coreToken);
  if (!f.ok) {
    return f.refusal.code === "exchange_rejected" ? refuse(401, "session_ended", COPY.sessionEnded) : f;
  }
  const email = typeof claims.email === "string" && claims.email ? claims.email : null;
  const core = { principalId: String(claims.sub ?? ""), displayName: email ?? "Signed in", email, expiresIn: exp - nowS };
  return { ok: true, info: info(core, f.field, exp - nowS), fieldToken: f.field.accessToken, coreToken };
}

// ------------------------------------------------------------------ cookies and request checks

export interface CookieSpec {
  name: string;
  value: string;
  httpOnly: true;
  secure: boolean;
  sameSite: "lax" | "strict";
  path: string;
  maxAge: number;
}

/** Secure unless FIELD_CONSOLE_COOKIE_SECURE=0; outside a production build only when the request came over https. */
export function secureCookies(env: Env, url: string, forwardedProto: string | null): boolean {
  if (env.FIELD_CONSOLE_COOKIE_SECURE === "0") return false;
  if (env.FIELD_CONSOLE_COOKIE_SECURE === "1" || env.NODE_ENV === "production") return true;
  return url.startsWith("https:") || (forwardedProto ?? "").split(",")[0]?.trim() === "https";
}

export function sessionCookies(fieldToken: string, fieldTtl: number, coreToken: string, coreTtl: number, secure: boolean): CookieSpec[] {
  return [
    { name: FIELD_COOKIE, value: fieldToken, httpOnly: true, secure, sameSite: "lax", path: FIELD_COOKIE_PATH, maxAge: fieldTtl },
    { name: CORE_COOKIE, value: coreToken, httpOnly: true, secure, sameSite: "strict", path: AUTH_COOKIE_PATH, maxAge: Math.max(1, coreTtl) },
  ];
}

export function deviceCookie(id: string, secure: boolean): CookieSpec {
  return { name: DEVICE_COOKIE, value: id, httpOnly: true, secure, sameSite: "strict", path: AUTH_COOKIE_PATH, maxAge: DEVICE_COOKIE_MAX_AGE_S };
}

export function clearedCookies(secure: boolean): CookieSpec[] {
  return [
    { name: FIELD_COOKIE, value: "", httpOnly: true, secure, sameSite: "lax", path: FIELD_COOKIE_PATH, maxAge: 0 },
    { name: CORE_COOKIE, value: "", httpOnly: true, secure, sameSite: "strict", path: AUTH_COOKIE_PATH, maxAge: 0 },
  ];
}

/**
 * Only the console's own pages may call these routes or use the cookie (no CORS, no cross-site use): a browser's
 * Sec-Fetch-Site must be same-origin; without it (older browsers) the Origin, when sent, must be this host.
 */
export function sameOrigin(headers: { get(name: string): string | null }, url: string): boolean {
  const site = headers.get("sec-fetch-site");
  if (site) return site === "same-origin";
  const origin = headers.get("origin");
  if (!origin) return false;
  const host = headers.get("x-forwarded-host") ?? headers.get("host");
  try {
    return new URL(origin).host === (host ?? new URL(url).host);
  } catch {
    return false;
  }
}
