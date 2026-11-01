/**
 * Core sign-in (M5-J01): the field token lives in an httpOnly cookie that browser JavaScript cannot read, so the
 * console's /v1 calls carry no Authorization header. This middleware adds `Authorization: Bearer <cookie>` before
 * next.config.mjs rewrites /v1/* to field-api. A request that already carries a token (the development sign-in
 * keeps its token in sessionStorage and sends it) is left as it is. Only the console's own pages get the cookie
 * applied (Sec-Fetch-Site same-origin), so another site cannot act with it.
 */
import { NextResponse, type NextRequest } from "next/server";
import { FIELD_COOKIE } from "./lib/coreSignIn";
import { authorizationFor } from "./lib/fieldCookie";

export function middleware(req: NextRequest) {
  const auth = authorizationFor(req.headers, req.url, req.cookies.get(FIELD_COOKIE)?.value);
  if (!auth) return NextResponse.next();
  const headers = new Headers(req.headers);
  headers.set("authorization", auth);
  return NextResponse.next({ request: { headers } });
}

export const config = { matcher: "/v1/:path*" };
