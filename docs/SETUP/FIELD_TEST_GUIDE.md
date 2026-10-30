# Field-test setup guide — Ray-Ban Meta Gen 2 + Android + your PC

**Audience:** the owner (owner). **Goal:** test SCMTips-Field on real Ray-Ban Meta Gen 2 glasses, with the backend on your Windows PC, without the agent ever seeing a real credential.

**The secrets rule (owner amendment A-02).** You paste secrets in exactly two places, and the agent never reads either:

1. **GitHub → repo Settings → Secrets and variables → Actions.** CI injects these at build time and GitHub masks them in logs. The agent can only *use* them by triggering a build.
2. **Git-ignored files on your PC:** `<repo>\.env.local` and `apps\field-android\local.properties`. The agent never opens these files; code refers to them only by variable name.

What you send back to the agent is only **non-secret facts** (versions, pass/fail lines). Never paste a token into chat. If you do by accident, revoke it and create a new one.

---

## Step 0 — Unblock GitHub Actions (blocking everything else) ⏱ 5 min

**Why:** every CI job on your account is refused with *"recent account payments have failed or your spending limit needs to be increased."* Without CI, no Android APK can be built for you, because the agent's own environment can't reach Gradle or Maven.

1. Open github.com and sign in as **mentorabhay**.
2. Click your avatar → **Settings** → **Billing and plans**.
3. Fix whichever is flagged: update or retry the **payment method** (a failed card charge, often from Copilot or another subscription), or raise the **Actions spending limit** from $0.
4. Cost note: private repos on the Free plan include 2,000 Linux minutes per month. An Android build is about 6–12 minutes, so roughly 150+ builds a month for free. You can leave the Actions spending limit at **$0** once the payment problem is cleared; it then just stops at the free quota.
5. Tell the agent: **"Step 0 done."** It will re-run CI and read the results.

---

## Step 1 — Read-only token for Meta's SDK feed ⏱ 5 min

Meta distributes the Wearables Device Access Toolkit (DAT) through GitHub Packages, which requires a token even for read access.

1. github.com → avatar → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)**.
2. Note: `scmtips-field DAT read`. Expiration: **90 days**.
3. Tick **only** `read:packages`. Nothing else.
4. **Generate token** and copy it. Don't paste it anywhere except the next step.
5. Open the repo **mentorabhay/SCMTips-Field** → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
   - Name: `MWDAT_GITHUB_TOKEN`
   - Secret: paste the token → **Add secret**.
6. *(Optional, only if you also build in Android Studio on your PC)*: in `<repo>\apps\field-android\local.properties` (git-ignored) add the line `github_token=<paste>`.
7. Tell the agent: **"Step 1 done."** The next CI run resolves `com.meta.wearable:mwdat-*`. The resolved version is then recorded as VERIFIED in `docs/META_FIELD.md` (rule 2.4).

The token is read-only on packages. It cannot touch your code or account. Revoke it any time on the same page.

---

## Step 2 — Prepare the glasses and Meta AI app ⏱ 10 min

1. On the Android phone, install or update the **Meta AI** app and pair your Ray-Ban Meta Gen 2.
2. Check glasses firmware: Meta AI app → **Devices** tab (glasses icon) → your glasses → gear icon → **General → About → Version**. Meta's docs require **v20 or newer** for Ray-Ban Meta; update if lower.
3. Enable **Developer Mode**: Meta AI app → **Settings → App Info** → tap the **App version** number **five times** → turn on the **Developer Mode** toggle.
   With Developer Mode on, our unpublished app can register with your glasses without a Meta app ID or client token. Our manifest uses Meta's developer-mode value `APPLICATION_ID = 0`. No Meta Developer Center registration is needed for this test stage.
4. Send the agent: **phone model, Android version, Meta AI app version, glasses firmware version.**

> **Gen 2 has no display.** Everything the spec shows on a "lens HUD" will be delivered as **short spoken prompts and earcons through the glasses' open-ear speakers**, with voice confirmation through the glasses' microphones. Display features are only for Meta Ray-Ban Display glasses and are out of scope for your test.

---

## Step 3 — Install the test APK on the phone ⏱ 10 min (after the agent says a build is green)

1. Repo → **Actions** → workflow **android** → the newest green run → **Artifacts** → download **field-debug-apk** (a zip) on your PC and unzip it to get `app-debug.apk`.
2. Install it with either option:
   - **USB (recommended):** on the phone, enable Developer options (Settings → About phone → tap **Build number** 7 times) → **USB debugging** on. On the PC, run `adb install -r app-debug.apk` (adb ships with Android Studio, in `platform-tools`).
   - **No cable:** copy the APK to Google Drive, open it on the phone, and allow "Install unknown apps" for Drive when asked.
3. First launch: grant Bluetooth, camera, microphone and notification permissions. Then tap **Connect glasses**. The Meta AI app opens to approve the connection; approve it.

---

## Step 4 — Run the backend on your PC (same Wi-Fi as the phone) ⏱ 15 min first time

*The agent will add a one-command script `scripts\dev\run-field-stack.ps1`. Until then, these are the manual steps.*

1. Requirements: Python via **uv** (you already use it), and PostgreSQL 16 on port **5450** (your existing `.dev_pgdata` setup, or Docker Desktop with `docker compose -f docker-compose.dev.yml up -d postgres`).
2. In PowerShell at `<repo>`:
   ```powershell
   uv sync
   uv run python scripts/jobs/alembic.py          # migrations up
   uv run uvicorn field_api.app:app --host 0.0.0.0 --port 8000
   ```
3. When Windows Firewall asks, allow it on **Private networks** only.
4. Find your PC's address with `ipconfig` and look for the **IPv4 Address** of your Wi-Fi adapter (e.g. `192.168.1.23`).
5. In the app → **Settings → Server**, enter `http://192.168.1.23:8000`. Debug builds allow plain HTTP only to private LAN addresses.
6. *(Optional, for testing away from home)*: a free Cloudflare quick tunnel (`cloudflared tunnel --url http://localhost:8000`) gives an `https://…trycloudflare.com` URL that needs no account. Use that URL in the app instead.

---

## Step 5 — AI credits (optional; the slice works without them) ⏱ 10 min

**Default design: no paid AI calls.** Barcodes (GS1/SSCC), label and nameplate text, and speech run **on the phone for free** (Google ML Kit, Android speech recognizer and text-to-speech). Cloud AI is only a **fallback you trigger** when on-device reading fails, and every call passes a hard budget guard.

### 5a. Identify the "$150 Meta API credits"
- Sign in at **llama.developer.meta.com**. If you see **API keys** and a credit balance there, it's the **Llama API**, which we can use for vision reading of hard labels.
- If not, check **developers.facebook.com → your app → Billing**. Graph or Ads credits can't be used for AI inference; tell the agent which you found.

### 5b. Create the keys and store them locally only
1. Llama API → **API keys** → create key `scmtips-field-dev`.
2. Baseten → **app.baseten.co → Settings → API keys** → create key `scmtips-field-dev`.
3. Create `<repo>\.env.local` (it is git-ignored by the `.env*` rule) by copying `.env.example` and filling in:
   ```
   LLAMA_API_KEY=<paste>
   BASETEN_API_KEY=<paste>
   AI_CLOUD_ENABLED=false            # flip to true only when you want the fallback
   AI_BUDGET_LLAMA_USD=40            # hard stop for this project (of your $150)
   AI_BUDGET_BASETEN_USD=25          # hard stop (of your $100)
   ```
4. **Baseten safety:** don't deploy any dedicated model yourself. Dedicated deployments bill per GPU-minute even when idle unless they scale to zero. The agent will use only per-token Model APIs, or a scale-to-zero deployment it tells you about first, with its cost.

### 5c. Verify without revealing anything
Run `uv run python scripts/dev/smoke_ai.py` (added by the agent). It prints only lines like `llama: OK (model …, est. $0.0003)` or `baseten: SKIPPED (AI_CLOUD_ENABLED=false)`. Paste **that output** to the agent.

### Budget guard (enforced in code)
- Every paid call is pre-priced from token and image counts. The call is **refused** if the month-to-date spend (stored in Postgres) plus the estimate would exceed the cap.
- Caps default to **$40 Llama and $25 Baseten** for development, leaving about $110 and $75 in reserve.
- A daily cap of **$3 per provider**, and at most 1 cloud call per capture.
- Spend is visible at `GET /v1/system/ai-usage` and shown in the app.

---

## What to send the agent (no secrets)
| When | Send |
|---|---|
| After Step 0 | "Step 0 done" |
| After Step 1 | "Step 1 done" |
| After Step 2 | phone model + Android version, Meta AI app version, glasses firmware |
| After Step 3 | does the app open; does "Connect glasses" reach the Meta AI approval screen |
| After Step 4 | the PC's server URL works from the phone's browser (`http://<ip>:8000/v1/health` shows JSON) |
| After Step 5 | the output of `smoke_ai.py` and which product the Meta credits are |
