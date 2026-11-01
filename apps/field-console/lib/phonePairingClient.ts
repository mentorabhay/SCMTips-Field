/**
 * "Sign in your phone" (M5-L03), browser half: asks only this console's server (POST /api/console-auth/pairing,
 * which holds the core token in an httpOnly cookie) for a code, and words the countdown.
 */
export const PAIRING_PATH = "/api/console-auth/pairing";

/** The three steps the page shows next to the code (contract §8, the app's "Scan a code from your computer"). */
export const PHONE_STEPS = [
  "Open SCMTips Field on your phone.",
  "Tap Scan a code from your computer.",
  "Point the camera at this code.",
] as const;

type FetchFn = (input: string, init?: RequestInit) => Promise<Response>;

export interface PhonePairing {
  code: string;
  link: string;
  /** When the code ends, by this browser's clock (from the server's `expires_in`, so a wrong clock does not matter). */
  expiresAtMs: number;
}

export class PairingError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message);
  }
}

export async function newPhonePairing(fetchImpl: FetchFn, nowMs: number): Promise<PhonePairing> {
  let res: Response;
  try {
    res = await fetchImpl(PAIRING_PATH, {
      method: "POST",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new PairingError(0, "network", "We could not reach this console's server. Check your connection and try again.");
  }
  let body: unknown = null;
  try {
    body = JSON.parse(await res.text());
  } catch {
    body = null;
  }
  const o = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
  if (!res.ok) {
    const message = typeof o.message === "string" && o.message ? o.message : `No code was made (HTTP ${res.status}).`;
    throw new PairingError(res.status, typeof o.code === "string" ? o.code : "error", message);
  }
  const { code, link, expires_in: expiresIn, expires_at: expiresAt } = o;
  if (typeof code !== "string" || !code || typeof link !== "string" || !link.startsWith("http")) {
    throw new PairingError(502, "unexpected", "The console's server answered in an unexpected shape.");
  }
  const fromServer = typeof expiresIn === "number" && Number.isFinite(expiresIn) ? nowMs + expiresIn * 1000 : NaN;
  const fromStamp = typeof expiresAt === "string" ? Date.parse(expiresAt) : NaN;
  const expiresAtMs = Number.isFinite(fromServer) ? fromServer : fromStamp;
  if (!Number.isFinite(expiresAtMs)) throw new PairingError(502, "unexpected", "The console's server answered in an unexpected shape.");
  return { code, link, expiresAtMs };
}

/** Whole seconds left, never below 0. */
export function secondsLeft(expiresAtMs: number, nowMs: number): number {
  return Math.max(0, Math.ceil((expiresAtMs - nowMs) / 1000));
}

/** "Works for 9:05 more" / "Works for 45 seconds more" / "This code has ended. Get a new code." */
export function countdownText(expiresAtMs: number, nowMs: number): string {
  const s = secondsLeft(expiresAtMs, nowMs);
  if (s <= 0) return "This code has ended. Get a new code.";
  if (s < 60) return `Works for ${s} ${s === 1 ? "second" : "seconds"} more`;
  const m = Math.floor(s / 60);
  return `Works for ${m}:${String(s % 60).padStart(2, "0")} more`;
}

/** The code split for reading aloud or typing: "AB12 CD34". */
export function spacedCode(code: string): string {
  return code.length > 4 ? code.replace(/(.{4})(?=.)/g, "$1 ") : code;
}
