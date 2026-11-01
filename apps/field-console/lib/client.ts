/**
 * Browser singletons: the session store (sessionStorage) and the API client bound to it.
 * The client calls same-origin paths that next.config.mjs proxies (field-api sends no CORS headers).
 * A core sign-in session (M5-J01) has no token here: middleware.ts adds it from the httpOnly cookie.
 */
import { createApiClient } from "./api";
import { coreSignOut } from "./coreSignInClient";
import { isExpired, SessionStore } from "./session";

export const sessionStore = new SessionStore(typeof window !== "undefined" ? window.sessionStorage : null);

export const api = createApiClient({
  fetch: (input, init) => fetch(input, init),
  baseUrl: "",
  coreBaseUrl: "/dev-core",
  getToken: () => {
    const s = sessionStore.get();
    return s && s.transport !== "cookie" && !isExpired(s, Date.now()) ? s.accessToken : null;
  },
  onUnauthorized: () => {
    if (sessionStore.get()?.transport === "cookie") void coreSignOut((input, init) => fetch(input, init));
    sessionStore.clear();
  },
});
