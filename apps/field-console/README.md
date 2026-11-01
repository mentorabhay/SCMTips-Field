# SCMTips Field console (`apps/field-console`)

The supervisor's web console (Next.js 15, App Router). The browser only ever talks to this console's own host:
`next.config.mjs` rewrites `/v1/*` to field-api (field-api sends no CORS headers).

```
pnpm --dir apps/field-console dev            # http://127.0.0.1:3000
pnpm --dir apps/field-console exec tsc --noEmit
pnpm exec vitest run                         # from the repository root
```

## Sign-in

The login page offers what is configured; it decides on the server at request time.

| Setting | Where | Effect |
|---|---|---|
| `FIELD_CONSOLE_CORE_URL` | console server, run time | Sign-in through SCMTIPS: e-mail + password. Example `https://api.scmtips.com`, or `http://api:8000` next to the core. |
| `FIELD_CONSOLE_FIELD_API_URL` | console server, run time | field-api for the sign-in exchange. Default: `NEXT_PUBLIC_FIELD_API_URL`, else `http://127.0.0.1:8020`. |
| `FIELD_CONSOLE_APP_LINK_BASE` | console server, run time | The App Link host in the "Sign in your phone" QR (M5-L03). Default `https://app.scmtips.com`. |
| `FIELD_CONSOLE_COOKIE_SECURE` | console server, run time | `0` drops the cookies' Secure flag, for a plain-http test host only. A production build sets Secure by default. |
| `NEXT_PUBLIC_DEV_SIGNIN=1` | build time | The development sign-in (fake-core issues a token for a chosen role). For the dev stack on one PC only. |
| `NEXT_PUBLIC_FIELD_API_URL`, `NEXT_PUBLIC_FAKE_CORE_URL` | build time | The rewrite targets for `/v1/*` and the development sign-in. |

With neither `FIELD_CONSOLE_CORE_URL` nor `NEXT_PUBLIC_DEV_SIGNIN=1`, the page says that core sign-in is not
connected. With both, the SCMTIPS sign-in is shown and the development sign-in sits below it.

### Sign-in through SCMTIPS (M5-J01)

1. The browser posts `{email, password}` to `POST /api/console-auth/signin` (a route handler on this server).
2. The server calls the core: `POST {FIELD_CONSOLE_CORE_URL}/v1/auth/app/token` with `X-Requested-With: lr`,
   `device_id` = this browser's id (`web-console:<uuid>`, kept in an httpOnly cookie for 400 days),
   `device_model` `WEB_CONSOLE`, `display_capable: true`, `client: scmtips-field`.
3. The server exchanges the core token at field-api: `POST /v1/auth/exchange {device_token, client_id: "field-console"}`.
   field-api answers a field token (at most 600 s) without a device binding; the core's role keys are mapped to
   Field roles there (`approver` -> `field.supervisor`, ...).
4. The server sets two httpOnly cookies and answers only who signed in, the roles, permissions and expiry:
   - `scmtips_field_token` (SameSite=Lax, Path=/v1, Secure): `middleware.ts` turns it into
     `Authorization: Bearer` on the console's own `/v1` calls (only when `Sec-Fetch-Site: same-origin`);
   - `scmtips_core_token` (SameSite=Strict, Path=/api/console-auth, Secure): used only by
     `POST /api/console-auth/refresh`, which the page calls a minute before the field token ends. When the core
     token ends (60 minutes on the core by default) the person signs in again.
5. Sign out (`POST /api/console-auth/signout`) clears both cookies.

No token is ever in a response body, sessionStorage or localStorage, and the browser never calls the core.
Refusals are shown in words: wrong e-mail or password (401), pairing code needed (403 `pairing_required`; on the
hosted demo only members of the SAMPLE organisation sign in with a password, while the core runs in demo mode),
too many tries (429), no Field role (field-api's 403 `FIELD-AUTH-403-NO-FIELD-ROLE` sentence), SCMTIPS or
SCMTips Field unreachable.

### Sign in your phone (M5-L03)

"Sign in your phone" (`/phone`, in the header, and the page a SCMTIPS sign-in lands on as `/phone?signedin=1`)
shows a QR code the phone app scans with "Scan a code from your computer":

1. The page posts to `POST /api/console-auth/pairing` (a route handler on this server, same-origin only).
2. The server reads the core token cookie and calls `POST {FIELD_CONSOLE_CORE_URL}/v1/wearable/pairing-codes`
   with `Authorization: Bearer <core token>` and `X-Requested-With: lr` (contract `docs/design/M5_SIGNIN_CONTRACT.md`
   §4; redirects are not followed, so the token goes nowhere else).
3. It answers `{code, expires_at, expires_in, link}`, `link` = `{FIELD_CONSOLE_APP_LINK_BASE}/pair?code=<code>`. No
   token is in the answer. Refusals in words: not signed in through SCMTIPS (401), the core token has ended (401,
   cookies cleared), "Your account can't sign in phones" (core 403), too many codes (429), SCMTIPS unavailable (5xx).
4. The page draws the QR itself (`lib/qr.ts`, byte mode, level M, versions 1-10, no library), with the code in text
   under it, a countdown and "New code". The phone redeems the code at the core's `/v1/auth/app/token`
   (`pairing_code`); the code is single use and short-lived.

With the development sign-in (fake-core) there is no core token: the page says it needs SCMTIPS sign-in.

The development sign-in keeps working as before: its field token stays in the tab's sessionStorage and is sent as a
bearer header, which the middleware leaves alone.
