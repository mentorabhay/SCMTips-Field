/**
 * Console configuration from NEXT_PUBLIC_* environment variables (inlined by Next at build time).
 *
 * field-api and fake-core send no CORS headers, so the browser never calls them directly: it calls
 * same-origin paths that next.config.mjs rewrites to these URLs (`/v1/*` -> field-api,
 * `/dev-core/auth/token` -> fake-core). The URLs below are the rewrite targets.
 */
export const DEFAULT_FIELD_API_URL = "http://127.0.0.1:8020"; // the SCMTIPS core API keeps 8000
export const DEFAULT_FAKE_CORE_URL = "http://127.0.0.1:8011";

/** How often live views refresh (contract §7: polling, no WebSocket). */
export const POLL_MS = 5000;

export interface ConsoleConfig {
  fieldApiUrl: string;
  fakeCoreUrl: string;
  devSignIn: boolean;
}

export function readConfig(env: Record<string, string | undefined>): ConsoleConfig {
  const trim = (v: string | undefined, d: string) => (v && v.trim() ? v.trim().replace(/\/+$/, "") : d);
  return {
    fieldApiUrl: trim(env.NEXT_PUBLIC_FIELD_API_URL, DEFAULT_FIELD_API_URL),
    fakeCoreUrl: trim(env.NEXT_PUBLIC_FAKE_CORE_URL, DEFAULT_FAKE_CORE_URL),
    devSignIn: env.NEXT_PUBLIC_DEV_SIGNIN === "1",
  };
}

/** Values as Next inlined them. Each variable must be referenced literally for inlining to work. */
export const config: ConsoleConfig = readConfig({
  NEXT_PUBLIC_FIELD_API_URL: process.env.NEXT_PUBLIC_FIELD_API_URL,
  NEXT_PUBLIC_FAKE_CORE_URL: process.env.NEXT_PUBLIC_FAKE_CORE_URL,
  NEXT_PUBLIC_DEV_SIGNIN: process.env.NEXT_PUBLIC_DEV_SIGNIN,
});
