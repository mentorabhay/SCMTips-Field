# Field-test guide: Ray-Ban Meta Gen 2, Android phone, your PC

**For:** the owner (owner). **Goal:** receive an inbound delivery hands-free with your glasses. You look at a carton label, the glasses take a photo, the phone reads the barcode, you count by voice, and you post with "post" … "confirm". You then hear the ERP document number. The backend (field-api, worker, ERP simulator) runs on your Windows PC on the same Wi-Fi.

**Secrets rule (A-02):** real credentials go only in git-ignored files on your PC (`.env.local`, `apps\field-android\local.properties`) or in GitHub Actions secrets. Never paste a key into chat; if you do, revoke it.

**What changed on 2026-10-30:** Meta's glasses toolkit (DAT 1.0.1) is now on **Maven Central**, so **no GitHub token is needed** (the old Step 1 is gone).

---

## Step 0: Get an APK (pick one)

**A. CI builds it.** Fix GitHub billing: github.com → avatar → Settings → **Billing and plans** → fix the failed payment or the spending limit. The free quota is plenty. Tell the agent "Step 0 done". It re-runs CI, and you download the **field-debug-apk** artifact from the newest green run.

**B. Build it on your PC.**
1. Install **Android Studio**. During setup you accept Google's Android SDK licence.
2. In Android Studio, open the folder `<repo>\apps\field-android` and wait for Gradle sync.
3. Choose **Build → Build App Bundle(s)/APK(s) → Build APK(s)**. The APK is written to `app\build\outputs\apk\debug\app-debug.apk`.
4. If sync or the build fails, copy the **first error lines** (no secrets in them) to the agent.

**C. The agent builds it.** Reply "I accept the Android SDK license — install it". The agent can then build and unit-test the APK in its own environment and send you the file.

## Step 1: Glasses and the Meta AI app (10 min)
1. On the phone, install or update **Meta AI** and pair your Ray-Ban Meta Gen 2.
2. Firmware must be **v20 or newer**. To check: Meta AI → Devices → your glasses → gear icon → General → About.
3. **Developer Mode:**
   1. Go to Meta AI → Settings → App info.
   2. Tap the **App version** number **5 times**.
   3. Turn **Developer Mode** on.

   This lets our unpublished app connect, with Meta's developer value `APPLICATION_ID = 0`.
4. Send the agent: phone model, Android version, Meta AI app version, glasses firmware.

## Step 2: Start the backend on your PC (15 min the first time)

You need **uv** and PostgreSQL 16 on port **5450**. For Postgres, either run Docker Desktop with `docker compose -f docker-compose.dev.yml up -d postgres`, or use your existing local Postgres.

In PowerShell at `<repo>`:
```powershell
.\scripts\dev\run-field-stack.ps1            # first run creates .env.local with fresh signing keys
.\scripts\dev\run-field-stack.ps1 smoke      # proves phone -> ERP without a phone; must end with "PASS: ERP material document 49…"
.\scripts\dev\run-field-stack.ps1 delivery   # creates a new inbound delivery to receive
.\scripts\dev\run-field-stack.ps1 pair       # shows the QR code for the phone (also saved as var\pairing-qr.svg)
.\scripts\dev\run-field-stack.ps1 down       # stops everything
```
- If PostgreSQL is not reachable, the script says so. `docker-compose.dev.yml` and `.env.example` both use `dev-postgres-password`. A Docker volume created before 2026-10-30 keeps its old password `devpassword`; in that case, change `FIELD_ADMIN_DATABASE_URL` / `ERPSIM_DATABASE_URL` in `.env.local` to match.
- When Windows Firewall asks about Python, allow it on **Private networks** only. The phone reaches `http://<your-PC-IP>:8000`.
- Logs are in `var\log\*.log`.

## Step 3: Install the app and pair (5 min)
1. Install the APK. Two ways:
   - **USB:** turn on USB debugging (Settings → About phone → tap Build number 7 times → Developer options → USB debugging), then run `adb install -r app-debug.apk`.
   - **No cable:** copy the APK to Drive and open it on the phone.
2. Open **SCMTips Field** and allow Bluetooth, microphone and notifications.
3. Tap **Scan pairing QR** and scan the QR from `run-field-stack.ps1 pair`. The app registers the phone, then lists the open inbound deliveries.

## Step 4: Connect the glasses (5 min)
1. Tap **Register**. The Meta AI app opens; approve SCMTips Field.
2. Tap **Connect**. Meta AI asks for **camera** and **microphone** access to the glasses; allow both.
3. The status should read: session **STARTED**, camera **STREAMING**. The capture button and glasses speech are experimental. If either shows "unavailable" or "refused", use the phone buttons and **Hold to talk**.

## Step 5: Receive a delivery
1. Tap a delivery. You hear: *"Receiving 1800 0002 2. 2 lines. Scan a label or say next."*
2. Look at a label and **press the glasses capture button** (or tap Capture, or say "capture"). The phone reads the barcode and says the line, the material and the expected quantity.
3. Say **"count twelve"**. You hear *"Line 10: 12."*
4. When all lines are counted, say **"post"**. You hear: *"Post 2 lines, 36 items? Say confirm or cancel."* Then, within **10 seconds**, say **"confirm"**.
5. After a few seconds you hear: *"Posted. Document 4900 0000 25."* The goods receipt is now in the ERP simulator.

Other phrases: **next** (next uncounted line, no scan needed), **repeat**, **what is this**, **cancel**.

**Test labels:** SAMPLE materials are named `SAMPLE-MAT-0001`…`0050`. Any Code 128 or QR barcode that contains exactly that text works. You can print one from a free online barcode generator, or show it on a second screen.

**Safety rules built in:**
- Nothing posts on speech alone. "post" must be followed by "confirm" within 10 s.
- Low-confidence or unknown speech changes nothing.
- The server re-checks the post/confirm pair and a hash of exactly the counted lines.

## Step 6: AI credits (optional; the slice does not use them)
Barcodes, speech and voice prompts run on the phone and glasses for free. Cloud AI is off (`AI_CLOUD_ENABLED=false`). If you later want the cloud fallback:
1. Find out which product the "$150 Meta credits" belong to. If **llama.developer.meta.com** shows API keys and a balance, they are Llama API credits.
2. Put `LLAMA_API_KEY=` / `BASETEN_API_KEY=` in `.env.local`. Also add prices to `config\ai_pricing.yaml` from your provider console; unpriced models are refused.
3. Caps are enforced in Postgres: `AI_BUDGET_LLAMA_USD=40`, `AI_BUDGET_BASETEN_USD=25`, `AI_DAILY_CAP_USD=3`. Spend is shown at `GET /v1/system/ai-usage`.
4. Don't deploy dedicated Baseten models; they bill while idle.

---

## What to send the agent (no secrets)
| After | Send |
|---|---|
| Step 0 | "Step 0 done" (A), the first build error lines (B), or the licence sentence (C) |
| Step 1 | phone model + Android version, Meta AI version, glasses firmware |
| Step 2 | the last 5 lines of `run-field-stack.ps1 smoke` |
| Steps 3–5 | what you heard and saw, and the app's log card (screenshot is fine) |
