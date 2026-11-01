/**
 * The Authorization header the /v1 middleware adds from the field token cookie (M5-J01), or null to leave the
 * request unchanged: when there is no cookie, when the request already carries a bearer token (the development
 * sign-in), or when it does not come from the console's own pages.
 */
import { sameOrigin } from "./coreSignIn";

export function authorizationFor(headers: { get(name: string): string | null }, url: string, cookie: string | undefined): string | null {
  if (!cookie) return null;
  const current = (headers.get("authorization") ?? "").trim();
  if (/^Bearer\s+\S+/i.test(current) && !/^Bearer\s+(null|undefined)$/i.test(current)) return null;
  if (!sameOrigin(headers, url)) return null;
  return `Bearer ${cookie}`;
}
