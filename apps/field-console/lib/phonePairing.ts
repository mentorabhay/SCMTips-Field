/**
 * "Sign in your phone" (M5-L03, contract docs/design/M5_SIGNIN_CONTRACT.md §4 and §8), server half. The console's
 * server takes the signed-in person's core access token from the httpOnly cookie `scmtips_core_token`, asks the
 * core for a single-use pairing code (`POST {FIELD_CONSOLE_CORE_URL}/v1/wearable/pairing-codes`,
 * `Authorization: Bearer <core token>`, `X-Requested-With: lr`) and answers only `{code, expires_at, expires_in,
 * link}`. The token never leaves the server; the browser never calls the core.
 *
 * The phone redeems the code at the core's app token (`pairing_code`, §1), so the code is the only secret the page
 * shows, and it is single use and short-lived (`LR_WEARABLE_PAIRING_MINUTES` on the core).
 *
 * Settings (server-only, read at request time; names only, A-02):
 *   FIELD_CONSOLE_CORE_URL       the core (see lib/coreSignIn.ts); unset = 404 not_configured.
 *   FIELD_CONSOLE_APP_LINK_BASE  the App Link host the QR opens; default https://app.scmtips.com (contract §4).
 */
import { COPY as SIGNIN_COPY, type Deps, type Env, type Refusal } from "./coreSignIn";

export const PAIRING_ROUTE = "/v1/wearable/pairing-codes";
export const DEFAULT_APP_LINK_BASE = "https://app.scmtips.com";

const TIMEOUT_MS = 10_000;
/** The core's codes are 8 characters; this accepts a little more so a longer core code still works. */
const CODE_RE = /^[A-Za-z0-9-]{4,32}$/;

export const PAIRING_COPY = {
  notSignedIn: "Sign in with your SCMTIPS account first. A phone can be signed in only from a SCMTIPS sign-in.",
  sessionEnded: SIGNIN_COPY.sessionEnded,
  forbidden: "Your account can't sign in phones.",
  tooMany: "Too many new codes. Wait a minute, then try again.",
  coreUnavailable: "SCMTIPS cannot make a code right now. Try again later.",
  coreUnreachable: "We could not reach SCMTIPS. Try again in a moment.",
  coreUnexpected: "SCMTIPS answered something this console cannot read. Try again later.",
  coreError: "SCMTIPS did not make a code. Try again later.",
} as const;

export interface PhonePairingBody {
  code: string;
  /** As the core sent it (ISO 8601). */
  expires_at: string;
  /** Seconds left by this server's clock, so a browser with a wrong clock still counts down right. */
  expires_in: number;
  /** The App Link the QR holds: `<base>/pair?code=<code>`. */
  link: string;
}

export type PairingResult = { ok: true; body: PhonePairingBody } | { ok: false; refusal: Refusal };

const refuse = (status: number, code: string, message: string, retryAfter?: string): { ok: false; refusal: Refusal } => ({
  ok: false,
  refusal: retryAfter ? { status, code, message, retryAfter } : { status, code, message },
});

/** FIELD_CONSOLE_APP_LINK_BASE when it is an http(s) origin (with an optional path), else the default. */
export function appLinkBase(env: Env): string {
  const raw = (env.FIELD_CONSOLE_APP_LINK_BASE ?? "").trim().replace(/\/+$/, "");
  if (!raw) return DEFAULT_APP_LINK_BASE;
  try {
    const u = new URL(raw);
    if ((u.protocol === "https:" || u.protocol === "http:") && !u.search && !u.hash && !u.username && !u.password) return raw;
  } catch {
    // fall through
  }
  return DEFAULT_APP_LINK_BASE;
}

export function pairLink(base: string, code: string): string {
  return `${base}/pair?code=${encodeURIComponent(code)}`;
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

/** The core's refusals of a pairing code, in words. 401: the core token is no longer good -> sign in again. */
export function pairingRefusal(status: number, retryAfter: string | null): { ok: false; refusal: Refusal } {
  if (status === 401) return refuse(401, "session_ended", PAIRING_COPY.sessionEnded);
  if (status === 403) return refuse(403, "forbidden", PAIRING_COPY.forbidden);
  if (status === 429) return refuse(429, "too_many_attempts", PAIRING_COPY.tooMany, retryAfter ?? undefined);
  if (status === 503) return refuse(503, "core_unavailable", PAIRING_COPY.coreUnavailable);
  if (status >= 500) return refuse(502, "core_error", PAIRING_COPY.coreError);
  return refuse(502, "core_error", `${PAIRING_COPY.coreError} (HTTP ${status})`);
}

/** Asks the core for a pairing code with the person's core token. */
export async function requestPairingCode(deps: Deps, coreToken: string | undefined, env: Env, nowMs: number): Promise<PairingResult> {
  if (!coreToken) return refuse(401, "not_signed_in", PAIRING_COPY.notSignedIn);
  let res: Response;
  try {
    res = await deps.fetch(`${deps.config.coreUrl}${PAIRING_ROUTE}`, {
      method: "POST",
      headers: { Accept: "application/json", Authorization: `Bearer ${coreToken}`, "X-Requested-With": "lr" },
      cache: "no-store",
      // never follow a redirect: it would carry the bearer token to another address
      redirect: "error",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    return refuse(502, "core_unreachable", PAIRING_COPY.coreUnreachable);
  }
  if (!res.ok) return pairingRefusal(res.status, res.headers.get("Retry-After"));
  const body = await readJson(res);
  const code = typeof body?.code === "string" ? body.code.trim() : "";
  const expiresAt = typeof body?.expires_at === "string" ? body.expires_at : "";
  const expiresMs = Date.parse(expiresAt);
  if (!CODE_RE.test(code) || !Number.isFinite(expiresMs)) return refuse(502, "core_unexpected", PAIRING_COPY.coreUnexpected);
  return {
    ok: true,
    body: {
      code,
      expires_at: expiresAt,
      expires_in: Math.max(0, Math.floor((expiresMs - nowMs) / 1000)),
      link: pairLink(appLinkBase(env), code),
    },
  };
}
