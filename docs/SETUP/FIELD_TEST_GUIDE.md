# Field-test guide: Ray-Ban Meta Gen 2, Android phone, your PC

**For:** the owner (owner). **Branch:** `slice/m2-integration` in **the private build mirror**.
**What you can test:** six jobs end to end against a simulated SAP on your PC: receive, put away, pick, count (with recount and approval), tower audit, and equipment swap.

**Secrets rule (A-02):** real credentials go only in git-ignored files on your PC (`.env.local`, `apps\field-android\local.properties`) or in GitHub Actions secrets. Never paste a key into chat; if you do, revoke it.

---

## How it fits together

```
 Ray-Ban Meta Gen 2            Android phone (SCMTips Field)             Your Windows PC (same Wi-Fi)
 ──────────────────            ─────────────────────────────            ──────────────────────────────
 camera  ── photo ──────────►  reads the barcode / QR on the phone  ─┐   field-api  :8020  (the real product API)
 button  ── "capture" ──────►  (nothing is sent to the cloud)        │      │  every scan is checked here: wrong bin,
 mic     ── your voice ─────►  speech → commands ("post", "12")     ├─►    │  wrong product, wrong serial → refused
 speaker ◄── spoken prompts ── text-to-speech over Bluetooth         │   field-worker      (posts to "SAP" in order)
                               shows the same step on screen         │      │
                                                                     │   erp-sim   :8002  (the simulated SAP)
                                                                     │      stock, deliveries, documents 101/601/701/702,
                                                                     │      towers, equipment, change documents
                                                                     └─► fake-core :8011  (sign-in tokens for the dev PC)
                                                                         console   :3000  (supervisor web pages, optional)
```

**The glasses are the hands-free scanner and headset.** Meta's toolkit (DAT 1.0.1, through the Meta AI app) gives the phone the glasses camera, button and microphone:
- You look at a label and **press the capture button on the glasses**. The phone gets the photo and reads the barcode or QR code on the phone itself.
- The phone **speaks every step into the glasses** ("Go to bin 02-01-01", "Pick 3"). You answer by voice ("all here", "twelve", "post", "confirm").
- Without glasses, the same jobs work with the phone camera, a handheld scanner, or by typing the code. **Me → Scanning with → Change** switches between them.

**The ERP is simulated, not mocked.** `erp-sim` is a separate service with its own database. It behaves like SAP S/4 for what we use: inbound and outbound deliveries, stock per material, material documents, physical-inventory documents, functional locations and equipment. field-api never writes to it directly. Each finished job becomes a posting request, and the worker sends it through the same `ErpPort` adapter that will later talk to real SAP. That is why you see "Waiting for SAP" for a moment and then a document number. You can watch it happen at **http://127.0.0.1:8002/_sim/ui** on the PC: documents, stock, and a **faults** page that makes SAP fail on purpose.

| Job | What you do on the phone | What "SAP" gets |
|---|---|---|
| Receive | scan each product label on the delivery, say the count, "post" + "confirm" | goods receipt **101**, then a **put-away job** appears |
| Put away | scan the product, walk to the bin shown, scan the bin label | field-side only (SAP stock has no bins) |
| Pick | per stop: scan bin, scan product, say "all here" or the number | goods issue **601** |
| Count | scan the bin, scan a product, say what you see (you are never shown the book quantity) | **701/702** if the difference is small; otherwise an approval in the console |
| Tower audit | check in (permit + GPS), harness check, scan each unit's serial label | mismatches go to the console's Decisions page |
| Swap | scan the old unit, scan the new unit from store | SAP change document (install/dismantle) |

---

## Step 0: Get the APK
1. Open **SCMTips-build** on GitHub → **Actions**, then the newest **ci** run on `slice/m2-integration` with a green **android** job.
2. Under **Artifacts**, download **field-debug-apk** and unzip it. You get `app-debug.apk`.

The same run also starts the app on an Android 14 emulator and fails if it crashes (job **android-launch**). Every step's log is on the `ci-logs` branch, so the agent can diagnose a build without you.

## Step 1: Glasses and the Meta AI app (once, 10 min)
1. On the phone, install or update **Meta AI** and pair your Ray-Ban Meta Gen 2.
2. Firmware must be **v20 or newer**: Meta AI → Devices → your glasses → gear icon → General → About.
3. **Developer Mode:** Meta AI → Settings → App info → tap **App version** 5 times → turn **Developer Mode** on. This lets our unpublished app connect.
4. **Glasses camera permission** (after Step 3): in SCMTips Field, Profile › Settings › Advanced › **Connections** › **Glasses camera** › run the test. When the Meta AI app asks, **allow** the camera, come back and run it again. Without this every glasses photo fails: the automatic connection never asks for it (owner's test, 4 Nov 2026). The app log (Diagnostics › App log) shows `glasses permission CAMERA: Granted` and the `glasses:` camera-link lines.

### Settings that change what happens (app 0.6.1-m5 or later)
| Setting (Profile › Settings) | Effect |
|---|---|
| **Audio only** | On: the photo, outlines, count and buttons are not shown, only spoken (the consent button stays). Keep it off while testing. |
| **Attention word** | On: during a work session only words starting with "Field" are acted on ("Field, look"). Off: everything is, and a leading "Field" is ignored. |
| **Glasses microphone** | On: the glasses listen during a work session. Off: the phone's recogniser does. |
| **Scanning with** | Glasses, Phone camera or Handheld: the barcode scanner and, since 0.6.1, the look camera (Phone camera = the phone takes the look photo even with the glasses connected). |
| **Classic layout** (Diagnostics) | The old three tabs. Keep it off. |

Other conditions: a look needs a **delivery job open** (New grocery delivery / New pharmacy delivery); hold-to-talk works without a work session; an **unknown barcode** is offered as a new item only on a sandbox site, with a receipt or count job open, **during a work session**; a SCMTIPS sign-in lasts **8 hours** (the app says "Your sign-in has expired"); set the app's Android battery use to **Unrestricted**.

## Step 2: Start everything on your PC (one double-click)
Double-click **`<workspace>\field-test\START FIELD TEST.cmd`**. It:
1. Fetches `slice/m2-integration` from SCMTips-build and switches to it. Untracked files that would block it are moved to `field-test\untracked-backup`.
2. Stops only our own leftover stack processes (other Python programs are left alone).
3. Starts fake-core, erp-sim, field-api and the worker, and applies database migrations.
4. Runs **`smoke --all`**: a robot phone does all six jobs over HTTP. It must end with **`PASS: 6 job types end to end`**.
5. Creates fresh jobs for you: a delivery, an outbound pick, a count and the tower jobs.
6. Opens **`labels.html`**, a page of QR labels for those jobs (see Step 4).
7. Shows the **pairing QR** for the warehouse.

Everything is logged to `<workspace>\field-test\field-test.log` and `stack-output.log`. If Windows Firewall asks about Python, allow **Private networks** only.

**Ports (31 Oct, agreed with the SCMTIPS core session):** the SCMTIPS core API keeps **8000** on your PC (its kit also uses 8001 and 8790, its web 3100), so **field-api now listens on 8020**; the stand-in core stays on **8011** and erp-sim on **8002**. The pairing QR and the app's default field address use 8020. `FIELD_STACK_API_PORT` in `.env.local` still overrides it, and if a port is taken anyway `up` moves that service to the next free port, prints it and saves it in `var\dev_stack_ports.json`. When you switch to the real core (`FIELD_CORE_TARGET=core`), its base URL is **your PC's LAN address on port 8000** (e.g. `http://192.168.x.y:8000`), so the phone on the same Wi-Fi reaches it too; see `.env.example`.

The same commands, one by one, in PowerShell at `<repo>`:
```powershell
.\scripts\dev\run-field-stack.ps1 up                 # start (first run creates .env.local with fresh signing keys)
.\scripts\dev\run-field-stack.ps1 smoke --all        # all six jobs without a phone
.\scripts\dev\run-field-stack.ps1 delivery           # new inbound delivery   -> Receive job
.\scripts\dev\run-field-stack.ps1 outbound           # new outbound delivery  -> Pick job
.\scripts\dev\run-field-stack.ps1 count              # new blind count        -> Count job (or: count 03-05-02)
.\scripts\dev\run-field-stack.ps1 tower              # tower audit + swap jobs on SAMPLE-TWR-0001
.\scripts\dev\run-field-stack.ps1 labels             # QR labels for the newest open jobs (var\labels.html)
.\scripts\dev\run-field-stack.ps1 pair               # pairing QR, warehouse
.\scripts\dev\run-field-stack.ps1 pair --tower       # pairing QR, tower site
.\scripts\dev\run-field-stack.ps1 down               # stop everything
```

## Step 3: Install the app and pair (5 min)
1. Install `app-debug.apk`: copy it to the phone (Drive, USB or a cable with `adb install -r app-debug.apk`) and open it. If Android says "App not installed", uninstall the old SCMTips Field first (the signing key changed once, on 2026-10-30).
2. Open **SCMTips Field** and allow camera, microphone, Bluetooth, location and notifications.
3. On **Connect this phone**, tap **Scan the code** and scan the QR the launcher opened (`var\pairing-qr.svg`), holding the phone 20–30 cm from the screen. The phone must be on the **same Wi-Fi** as the PC.
4. **Today** lists your jobs. New jobs appear by themselves within a few seconds.

**Connect the glasses:** **Me → Smart glasses**. The Meta AI app opens; approve SCMTips Field, then allow camera and microphone. **Put the glasses on and wake them**: "No eligible device" means they are asleep, folded or in the case. Then set **Me → Scanning with** to **Glasses**.

## Step 4: Labels to scan
The launcher opens **labels.html** in your browser. It holds a QR label for every code the newest jobs ask for (products, bins, tower serials, the spare unit). Dashed labels are **wrong on purpose**, so you can see the app refuse them. Print the page, or show it on a laptop or second screen and look at it with the glasses.

If a code will not scan, tap **Type the code instead** under the scan box and type the text under the QR.

## Step 5: The warehouse jobs
Start each from **Today**. Every step is spoken in the glasses and shown on the phone. Say **"repeat"** at any time to hear the step again.

**Receive** (*"Check in this delivery"*)
1. Look at a product label from the delivery's section and press the glasses button. You hear the product and expected quantity.
2. Say the number you counted, e.g. **"twelve"** (or **"all here"**). Repeat for each product.
3. Say **"post"**. You hear the total. Within **10 seconds** say **"confirm"** (or tap the button).
4. You hear *"Posted. Document 4900…"*. A **Put away** job appears on Today.
- Try the dashed `SAMPLE-MAT-9999`: *"Not on this delivery."*

**Put away**
1. Scan a product from the receipt. The app tells you the bin.
2. Scan that **bin label**. A dashed wrong bin is refused with *"That is bin … Go to …"*.
3. *"Stored"*. When the last pallet is stored, finish the job.

**Pick** (stops in walking order)
1. *"Stop 1 of 2. Bin 02-01-01."* Scan the bin, then the product.
2. Say **"all here"**, or a smaller number to record a short pick.
3. After the last stop, post and confirm. You hear the goods-issue number (601).

**Count** (blind: you never see the system quantity)
1. *"Go to bin 03-05-02."* Scan the bin, then each product in it.
2. Say what you see. A small difference posts 701/702 by itself (*"Posted"*). A large one goes to a supervisor (*"Count saved. The office reviews the difference."*).
3. **Recount:** in the console (Step 7), open **Decisions** and choose **Ask for a recount**. A recount must be done by **a different person**. With one phone, run `run-field-stack.ps1 pair --user op-2`, then on the phone go to **Me → Connected to → Change** and scan the new QR. The recount job appears on Today. After it, approve the difference in the console and you see a 702 document in erp-sim.

## Step 6: The tower jobs
The tower jobs live on a separate site, **SAMPLE tower 0001**, with a real geofence (150 m) for check-in. To test where you stand:
1. In Google Maps on the phone, long-press your blue dot and copy the coordinates (e.g. `19.0760, 72.8777`).
2. On the PC: `.\scripts\dev\run-field-stack.ps1 tower --at "19.0760, 72.8777"`. This moves the test tower to that point; the geofence is not switched off.
3. `.\scripts\dev\run-field-stack.ps1 pair --tower` and `.\scripts\dev\run-field-stack.ps1 labels`. On the phone: **Me → Connected to → Change**, then scan `var\pairing-qr-tower.svg`.

**Tower audit** (*"Sector A audit"*)
1. **Check in:** type any permit number (4+ characters) and wait for a GPS fix (accuracy 50 m or better), then tap **Check in**.
2. **Harness:** say **"harness clipped"** **and** tap **I am clipped in** within 10 seconds. Both are required before any climb prompt.
3. At each slot, look at the serial label and press the glasses button. *"Matches."* or *"Different serial. Recorded."* Use the dashed `RRU-SN-TEST01` once to create a finding.
4. Climb down: say **"clipped"** at each rest platform. Then check out.
5. In the console, **Decisions** now lists the mismatch with the SAP serial against the one you scanned.

**Swap** (*"Swap RRU at Sector A · slot 3"*)
1. Scan the **old unit** (a dashed wrong unit is refused), then the **new unit from store**.
2. Post and confirm. You hear the SAP change-document number; erp-sim shows the old unit dismantled and the new one installed.

## Step 7: Watch from the PC
**The simulated SAP:** open **http://127.0.0.1:8002/_sim/ui** (Documents, Stock, Faults, Locks). After each job you see the new document and the stock change. On **Faults** you can make the next posting fail and watch the job turn **Blocked** in the console, then retry it from **Postings to SAP**.

**The supervisor console:**
- **Once:** install **Node.js 22 LTS**, then in PowerShell run `corepack enable`, and in `<repo>` run `pnpm install`.
- **Each time:** in `<repo>` run:
  ```powershell
  $env:NEXT_PUBLIC_DEV_SIGNIN = "1"
  pnpm --dir apps\field-console dev
  ```
  To skip the first line, put `NEXT_PUBLIC_DEV_SIGNIN=1` in `apps\field-console\.env.local`.
- **Sign in:** open **http://localhost:3000**, choose **Development sign-in → Supervisor**, and keep the id `dev-supervisor`. It must differ from the phone user, or separation of duties stops you approving their counts. For **Tenant id**, copy `"tenant"` from `var\dev_stack.json`.
- **Busy ports:** if the stack moved to other ports (see `var\dev_stack_ports.json`), set `NEXT_PUBLIC_FIELD_API_URL` and `NEXT_PUBLIC_FAKE_CORE_URL` before starting.
- **Pages** (all refresh every 5 seconds from field-api):
  - **Live work**
  - **Warehouse**: board, receiving, counts, discrepancies, accuracy, posting queues
  - **Decisions**: count approvals and tower findings
  - **Sites and towers**: who is on a tower, audit progress
  - **Postings to SAP**
  - **Phones and glasses**
  - Recalls and Industry packs are placeholders for later phases.

## Step 8: AI credits (optional; nothing here uses them)
Barcodes, speech and spoken prompts run on the phone and glasses for free. Cloud AI is off (`AI_CLOUD_ENABLED=false`). If you enable it later, keys go in `.env.local` only. Hard caps are enforced in Postgres (`AI_BUDGET_LLAMA_USD=40`, `AI_BUDGET_BASETEN_USD=25`, `AI_DAILY_CAP_USD=3`), and spend shows at `GET /v1/system/ai-usage`. Don't deploy dedicated Baseten models; they bill while idle. The M3 Field Assistant uses the Meta Model API (`MODEL_API_KEY`, cap `AI_BUDGET_META_USD`, prices in `config/ai_pricing.yaml`); `uv run python -m tools.dev_stack.assistant_check` makes one capped call and prints `OK` or `BLOCKED <reason>`. Without AI the assistant still answers in rules mode.

M5 vision look (SAM 3.1 instances, Muse Spark 1.3 label reads): both prices in `config/ai_pricing.yaml` are placeholders marked `confirmed: false` (SAM 3.1 per image; Muse image input per image), and the budget guard refuses a placeholder price (`AI_PRICE_UNCONFIRMED`) unless `AI_ALLOW_UNCONFIRMED_PRICES=true`. Until then a look answers in rules mode ("say the count"). Gate 0: `uv run python tools/probes/m5_gate0.py --photo <photo> --allow-unconfirmed-prices` makes one call of each (the flag applies to that run only) and writes a redacted evidence file under `docs/evidence/`. Then check both prices on the Meta console, correct them in `config/ai_pricing.yaml` and set `confirmed: true`; the flag is then not needed. To try the look without any model: `stack up --model-standin` (a local dev double, never Meta) and `stack smoke --m5-look`.

---

## Known limits of this build
- **Put away** stores stock on the field side only, with no SAP posting. Pick order is bin-code order (there is no site graph for the sample site).
- **Short picks** are recorded but don't open an exception case. Batch and serial capture on picks is not built.
- **Count approval:** after the console approves or asks for a recount, the phone sees it in the job list; there is no spoken alert.
- **Glasses:** the camera, button and microphone come from Meta's toolkit (DAT 1.0.1) and are marked experimental. If one says "unavailable", use the phone camera and **Hold to talk**. A failed glasses barcode photo opens the phone's scanner when the app is on screen.
- **Folding the glasses during a work session** pauses it and may restart it by itself (clicks from the phone). Tap **Stop work** before you fold them.
- **Speech** is Android's recogniser in US English, offline. Phones that give no confidence score (the owner's scored every result 0.00) are taken at the 0.80 floor since 0.6.1; before that every spoken command was dropped.
- **Real SAP (S/4 adapter)** is still UNVERIFIED. Everything here runs against erp-sim.

## What to send the agent (no secrets)
| After | Send |
|---|---|
| Step 2 | the last 10 lines of `stack-output.log` (or just "launcher finished") |
| Steps 3–6 | what you heard and saw per job, and the app's error card or the text of `Me → Send feedback` |
| Step 7 | a screenshot of any console page that looks wrong, and any red error text |
