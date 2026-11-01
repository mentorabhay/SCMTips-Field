/**
 * The browser's half of the core sign-in (M5-J01): it calls only the console's own server
 * (/api/console-auth/*), which talks to the core and field-api and keeps the tokens in httpOnly cookies.
 * Nothing the browser receives here is a token; the session it builds has `accessToken: ""`.
 */
import type { FieldSession } from "./session";

export const SIGNIN_PATH = "/api/console-auth/signin";
export const REFRESH_PATH = "/api/console-auth/refresh";
export const SIGNOUT_PATH = "/api/console-auth/signout";

/** Refresh the 600 s field token this long before it ends. */
export const REFRESH_LEAD_MS = 60_000;

type FetchFn = (input: string, init?: RequestInit) => Promise<Response>;

export class CoreSignInError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message);
  }
}

interface SessionBody {
  principalId: string;
  tenantId: string;
  displayName: string;
  email: string | null;
  roles: string[];
  permissions: string[];
  siteIds: string[];
  expiresIn: number;
  coreExpiresIn: number;
}

const strs = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === "string");

function parseBody(v: unknown): SessionBody | null {
  if (!v || typeof v !== "object") return null;
  const s = (v as { session?: unknown }).session;
  if (!s || typeof s !== "object") return null;
  const o = s as Record<string, unknown>;
  if (
    typeof o.principalId !== "string" || typeof o.tenantId !== "string" || typeof o.displayName !== "string" ||
    !strs(o.roles) || !strs(o.permissions) || !strs(o.siteIds) ||
    typeof o.expiresIn !== "number" || typeof o.coreExpiresIn !== "number"
  ) {
    return null;
  }
  return o as unknown as SessionBody;
}

async function post(fetchImpl: FetchFn, path: string, body?: unknown): Promise<unknown> {
  let res: Response;
  try {
    res = await fetchImpl(path, {
      method: "POST",
      headers: { Accept: "application/json", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new CoreSignInError(0, "network", "We could not reach this console's server. Check your connection and try again.");
  }
  let parsed: unknown = null;
  try {
    parsed = JSON.parse(await res.text());
  } catch {
    parsed = null;
  }
  if (!res.ok) {
    const p = (parsed ?? {}) as { code?: unknown; message?: unknown };
    const message = typeof p.message === "string" && p.message ? p.message : `Sign-in did not complete (HTTP ${res.status}).`;
    throw new CoreSignInError(res.status, typeof p.code === "string" ? p.code : "error", message);
  }
  return parsed;
}

function toSession(b: SessionBody, nowMs: number, prev?: FieldSession): FieldSession {
  return {
    accessToken: "",
    transport: "cookie",
    expiresAt: nowMs + b.expiresIn * 1000,
    signInEndsAt: nowMs + b.coreExpiresIn * 1000,
    principalId: b.principalId || prev?.principalId || "",
    tenantId: b.tenantId,
    roles: b.roles,
    permissions: b.permissions,
    siteIds: b.siteIds,
    displayName: prev?.displayName ?? b.displayName,
  };
}

/** E-mail + password through the console's server. Throws CoreSignInError with the sentence to show. */
export async function coreSignIn(fetchImpl: FetchFn, email: string, password: string, nowMs: number): Promise<FieldSession> {
  const b = parseBody(await post(fetchImpl, SIGNIN_PATH, { email: email.trim(), password }));
  if (!b) throw new CoreSignInError(502, "unexpected", "The console's server answered the sign-in in an unexpected shape.");
  return toSession(b, nowMs);
}

/** A fresh field token cookie; the same person, new roles and expiry. */
export async function refreshCoreSession(fetchImpl: FetchFn, prev: FieldSession, nowMs: number): Promise<FieldSession> {
  const b = parseBody(await post(fetchImpl, REFRESH_PATH));
  if (!b) throw new CoreSignInError(502, "unexpected", "The console's server answered the refresh in an unexpected shape.");
  return toSession(b, nowMs, prev);
}

/** Clears the token cookies on the server. Never throws: signing out locally must always work. */
export async function coreSignOut(fetchImpl: FetchFn): Promise<void> {
  try {
    await fetchImpl(SIGNOUT_PATH, { method: "POST", credentials: "same-origin", cache: "no-store" });
  } catch {
    // the cookie still ends with the field token's 600 s
  }
}

/** When to refresh a cookie session: a minute before the field token ends, never in the past. */
export function refreshDelayMs(s: FieldSession, nowMs: number): number {
  return Math.max(5_000, s.expiresAt - REFRESH_LEAD_MS - nowMs);
}
