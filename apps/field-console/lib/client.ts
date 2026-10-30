/**
 * Browser singletons: the session store (sessionStorage) and the API client bound to it.
 * The client calls same-origin paths that next.config.mjs proxies (field-api sends no CORS headers).
 */
import { createApiClient } from "./api";
import { isExpired, SessionStore } from "./session";

export const sessionStore = new SessionStore(typeof window !== "undefined" ? window.sessionStorage : null);

export const api = createApiClient({
  fetch: (input, init) => fetch(input, init),
  baseUrl: "",
  coreBaseUrl: "/dev-core",
  getToken: () => {
    const s = sessionStore.get();
    return s && !isExpired(s, Date.now()) ? s.accessToken : null;
  },
  onUnauthorized: () => sessionStore.clear(),
});
