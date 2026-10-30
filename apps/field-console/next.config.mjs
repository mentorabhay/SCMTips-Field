/**
 * field-api and fake-core send no CORS headers, so the browser talks only to this Next server and
 * these rewrites forward the calls:
 *   /v1/*                         -> NEXT_PUBLIC_FIELD_API_URL (default http://127.0.0.1:8000)
 *   /dev-core/api/v1/auth/token   -> NEXT_PUBLIC_FAKE_CORE_URL (default http://127.0.0.1:8011),
 *                                    only when NEXT_PUBLIC_DEV_SIGNIN=1 (development sign-in)
 * Rewrites are fixed when `next dev` / `next build` starts: restart after changing these variables.
 */
const trim = (v, d) => (v && v.trim() ? v.trim().replace(/\/+$/, "") : d);
const fieldApi = trim(process.env.NEXT_PUBLIC_FIELD_API_URL, "http://127.0.0.1:8000");
const fakeCore = trim(process.env.NEXT_PUBLIC_FAKE_CORE_URL, "http://127.0.0.1:8011");
const devSignIn = process.env.NEXT_PUBLIC_DEV_SIGNIN === "1";

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      { source: "/v1/:path*", destination: `${fieldApi}/v1/:path*` },
      ...(devSignIn ? [{ source: "/dev-core/api/v1/auth/token", destination: `${fakeCore}/api/v1/auth/token` }] : []),
    ];
  },
  async redirects() {
    // Pages of the pre-M2 console that the M2 views replace.
    return [
      ["/warehouse/board", "/work"],
      ["/warehouse/discrepancies", "/decisions"],
      ["/warehouse/approvals", "/decisions"],
      ["/mismatches", "/decisions"],
      ["/warehouse/queues", "/postings"],
      ["/safety", "/sites"],
      ["/audits", "/sites"],
      ["/devices/:id", "/devices"],
    ].map(([source, destination]) => ({ source, destination, permanent: false }));
  },
};

export default nextConfig;
