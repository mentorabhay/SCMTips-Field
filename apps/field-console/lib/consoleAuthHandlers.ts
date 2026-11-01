/**
 * The console's sign-in route handlers (M5-J01), kept here so tests call them with an injected fetch and env.
 * app/api/console-auth/{signin,refresh,signout,pairing}/route.ts bind them to the real fetch and process.env.
 *
 * Responses carry only session information (never a token): `{ session: SessionInfo }` on success,
 * `{ code, message }` on a refusal. The tokens travel only in httpOnly cookies (see lib/coreSignIn.ts).
 */
import { NextResponse, type NextRequest } from "next/server";
import {
  clearedCookies,
  COPY,
  CORE_COOKIE,
  coreSignInConfig,
  DEVICE_COOKIE,
  deviceCookie,
  deviceIdFor,
  parseCredentials,
  refreshWithCore,
  sameOrigin,
  secureCookies,
  sessionCookies,
  signInWithCore,
  type CookieSpec,
  type Env,
  type Refusal,
  type SignInResult,
} from "./coreSignIn";
import { requestPairingCode } from "./phonePairing";

export interface HandlerDeps {
  fetch: (input: string, init?: RequestInit) => Promise<Response>;
  env: Env;
  nowS: () => number;
  newId: () => string;
}

const NO_STORE = { "Cache-Control": "no-store" };

function setCookies(res: NextResponse, cookies: CookieSpec[]): NextResponse {
  for (const c of cookies) res.cookies.set(c);
  return res;
}

function refusal(r: Refusal, cookies: CookieSpec[] = []): NextResponse {
  const res = NextResponse.json({ code: r.code, message: r.message }, { status: r.status, headers: NO_STORE });
  if (r.retryAfter) res.headers.set("Retry-After", r.retryAfter);
  return setCookies(res, cookies);
}

function secure(req: NextRequest, env: Env): boolean {
  return secureCookies(env, req.url, req.headers.get("x-forwarded-proto"));
}

function answer(result: SignInResult, isSecure: boolean, extra: CookieSpec[] = []): NextResponse {
  if (!result.ok) {
    const clear = result.refusal.code === "session_ended" ? clearedCookies(isSecure) : [];
    return refusal(result.refusal, [...extra, ...clear]);
  }
  const res = NextResponse.json({ session: result.info }, { status: 200, headers: NO_STORE });
  return setCookies(res, [
    ...extra,
    ...sessionCookies(result.fieldToken, result.info.expiresIn, result.coreToken, result.info.coreExpiresIn, isSecure),
  ]);
}

/** POST /api/console-auth/signin `{email, password}`. */
export async function handleSignIn(req: NextRequest, deps: HandlerDeps): Promise<NextResponse> {
  const config = coreSignInConfig(deps.env);
  if (!config) return refusal({ status: 404, code: "not_configured", message: COPY.notConfigured });
  if (!sameOrigin(req.headers, req.url)) return refusal({ status: 403, code: "cross_site", message: COPY.crossSite });
  if (!(req.headers.get("content-type") ?? "").toLowerCase().startsWith("application/json")) {
    return refusal({ status: 415, code: "bad_request", message: COPY.badRequest });
  }
  let body: unknown = null;
  try {
    body = await req.json();
  } catch {
    body = null;
  }
  const parsed = parseCredentials(body);
  if (!parsed.ok) return refusal(parsed.refusal);
  const isSecure = secure(req, deps.env);
  const device = deviceIdFor(req.cookies.get(DEVICE_COOKIE)?.value, deps.newId);
  const extra = device.isNew ? [deviceCookie(device.id, isSecure)] : [];
  const result = await signInWithCore({ fetch: deps.fetch, config }, parsed.creds, device.id);
  return answer(result, isSecure, extra);
}

/** POST /api/console-auth/refresh: a new field token from the core token cookie. */
export async function handleRefresh(req: NextRequest, deps: HandlerDeps): Promise<NextResponse> {
  const config = coreSignInConfig(deps.env);
  if (!config) return refusal({ status: 404, code: "not_configured", message: COPY.notConfigured });
  if (!sameOrigin(req.headers, req.url)) return refusal({ status: 403, code: "cross_site", message: COPY.crossSite });
  const result = await refreshWithCore({ fetch: deps.fetch, config }, req.cookies.get(CORE_COOKIE)?.value, deps.nowS());
  return answer(result, secure(req, deps.env));
}

/** POST /api/console-auth/signout: clears the token cookies (the device id stays, so the browser keeps its id). */
export async function handleSignOut(req: NextRequest, deps: Pick<HandlerDeps, "env">): Promise<NextResponse> {
  if (!sameOrigin(req.headers, req.url)) return refusal({ status: 403, code: "cross_site", message: COPY.crossSite });
  const res = new NextResponse(null, { status: 204, headers: NO_STORE });
  return setCookies(res, clearedCookies(secure(req, deps.env)));
}

/**
 * POST /api/console-auth/pairing (M5-L03): a single-use code that signs the person's phone in, from the core token
 * cookie. Answers `{code, expires_at, expires_in, link}`; never a token. 401 without a core sign-in.
 */
export async function handlePairing(req: NextRequest, deps: HandlerDeps): Promise<NextResponse> {
  const config = coreSignInConfig(deps.env);
  if (!config) return refusal({ status: 404, code: "not_configured", message: COPY.notConfigured });
  if (!sameOrigin(req.headers, req.url)) return refusal({ status: 403, code: "cross_site", message: COPY.crossSite });
  const result = await requestPairingCode({ fetch: deps.fetch, config }, req.cookies.get(CORE_COOKIE)?.value, deps.env, deps.nowS() * 1000);
  if (!result.ok) {
    const clear = result.refusal.code === "session_ended" ? clearedCookies(secure(req, deps.env)) : [];
    return refusal(result.refusal, clear);
  }
  return NextResponse.json(result.body, { status: 200, headers: NO_STORE });
}
