# M5-L sign-in contract (A-08, 2 Nov 2026)

Binding for three parallel builders: the SCMTIPS core (repo SCMTips, branch the core's integration branch), the Field app
(`apps/field-android`) and the Field console (`apps/field-console`). Plan: "SCMTips Field: Sign-in and Accounts Plan".
All core routes are under the core API base (hosted `https://api.scmtips.com`), public routes send
`X-Requested-With: lr` (the core's CSRF rule for non-browser clients, as `/v1/auth/app/token` already requires).
Errors are the core's problem+json. Every message the person sees is neutral (never says whether an e-mail exists).

## 1. Core: the app token gets two more ways in
`POST /v1/auth/app/token` keeps its response (`access_token`, `expires_in`, `wearable`, `capabilities`, `permissions`,
`tenant_id`, `sites`, `user`) and accepts exactly one of:
| Way | Body fields | Rule |
|---|---|---|
| password (today) | `email`, `password` | unchanged |
| pairing code (today) | `pairing_code` | unchanged; the code may come from the console QR (§4) |
| **e-mail code (new)** | `email`, `email_code` (6 digits) | code from §2; same strict-sign-in rule as password (strict on: 403 `pairing_required`, except SAMPLE members in demo mode) |
| **demo (new)** | `demo: true` | only when `LR_DEMO_MODE` is on, else 403 `demo_off`; signs in the SAMPLE organisation's guest member (§3) |
Always `device_id`, `device_model`, `display_capable`, `client` as today. Wrong or expired code: 401 `invalid_code`
(neutral); 5 wrong tries for one code: the code is dead, 429 `locked`; rate limits as `AUTH_RATE`.

## 2. Core: e-mail code request
`POST /v1/auth/app/code/request` `{email, device_id}` → **202** `{"status":"accepted"}` always (also when unknown,
inactive or rate-limited). For an active member: a random 6-digit code, stored as a hash only, single use, 10 minutes,
newest code replaces older ones for that e-mail+device; e-mailed through the core's outbox (`outbound_email`, sent by
the worker over SMTP) from `LR_MAIL_FROM`: subject "Your SCMTIPS sign-in code", body the code, its 10-minute life and
"If you did not ask for this, ignore this e-mail". Audited (`auth.email_code.requested` / `.used`), never logging the
code. Limits: per e-mail and per IP (reuse the password-reset limits).

## 3. Core: demo guest (demo mode only)
On first use the core creates (and keeps) one guest member in the SAMPLE demo organisation,
`demo-guest@sample-drone-oem.example`, roles `procurement` + `approver`, no usable password. `demo: true` signs it in;
rate limit 10 per IP per hour; audited `wearable.paired` with `method: "demo"`. The nightly demo reset keeps it.
Field maps it like the judges: field.operator + field.supervisor.

## 4. Core: pairing codes for the console QR
The Field console's server, holding the signed-in person's core access token, calls
`POST /v1/wearable/pairing-codes` with `Authorization: Bearer <core access token>` and gets `{code, expires_at}`. If
the route accepts only web sessions today, the core accepts the core app token there too (same permission check:
`PAIRING`). The QR's text is the App Link `https://app.scmtips.com/pair?code=<code>`.

## 5. Core: password reset e-mail and links
`POST /v1/auth/password/reset/request` (unchanged API) now really e-mails each issued token through the outbox:
link `https://app.scmtips.com/reset/confirm?token=<43-char token>` (the web page already exists). Invites already
e-mail `https://app.scmtips.com/invite/<token>`. `GET /v1/invites/{token}` (public) and
`POST /v1/invites/{token}/accept` `{password, name?, consent_terms, consent_dpdp, terms_version?, dpdp_version?}` are
unchanged; after accept by a new account the app signs in with `email` + `password` (§1). If a new account's e-mail
is unverified at that point and that blocks the app token, the core treats a used invite link as proof of the e-mail
(the invite went to that address) — the core builder decides and documents it.

## 6. Core web: Android App Links
`https://app.scmtips.com/.well-known/assetlinks.json` (served by the core web app, `application/json`, no redirect)
lists `android_app` targets for `com.scmtips.field.debug` and `com.scmtips.field` with the SHA-256 signing-certificate
fingerprints from the build/run setting `FIELD_APP_CERT_SHA256` (comma-separated; public, not secret).

## 7. Field app (apps/field-android)
Sign-in screen with five ways: "Continue with e-mail" (then **Use my password** or **E-mail me a code**), "Scan a code
from your computer" (QR → `pairing_code`), "I have an invite" (paste a link or code, or opened by the link), "Try the
SAMPLE demo" (one tap, shown only when the server is the hosted demo or says demo is on), and "Forgot password?".
In-app screens: code entry (6 boxes, paste, resend after 30 s), invite (org and role from `GET /v1/invites/{token}`,
name, password, consents, accept, then sign in), reset (e-mail → "check your e-mail" → the link opens "Set a new
password" → confirm → sign in), "Create account" without an invite explains and offers the demo. App Links
(`autoVerify`) for `https://app.scmtips.com/reset/confirm`, `/invite/*`, `/pair`; the browser is never opened.
Neutral errors: wrong details, locked (429), no Field role (with "Try the SAMPLE demo"), single sign-on only, demo
off, offline.

## 8. Field console (apps/field-console)
"Sign in your phone" in the console header menu and on the sign-in success page: a QR (drawn in the page, no new
dependency unless one is already in the lockfile) of the §4 App Link, the code in text under it, a countdown to
`expires_at`, refreshed on request.

## 9. Hosting
Google Workspace mailbox `support@scmtips.com` (owner), with 2-Step Verification and an app password; kit:
`LR_SMTP_HOST=smtp.gmail.com`, `LR_SMTP_PORT=587`, `LR_SMTP_STARTTLS=true`, `LR_SMTP_USER=support@scmtips.com`,
`LR_SMTP_PASSWORD` from a secret, `LR_MAIL_FROM=SCMTIPS <support@scmtips.com>`; `FIELD_APP_CERT_SHA256` for §6;
Workspace SPF/DKIM records on scmtips.com for delivery.
