# M5 device test: look, receive with a flag, claim, evidence (one page)

For the owner. Two cases on the **Home (sandbox)** site with real products, the Ray-Ban Meta Gen 2 glasses and the
phone app **0.6.0-m5** (APK from the newest green CI run of `slice/m5-look`, job android, artifact field-debug-apk).
What the build proved without you: both cases end to end with a local model stand-in, not Meta
(`docs/evidence/runs/2026-11-01-m5-integration.txt`). This test is the first run on the real Meta API, your
phone and the glasses.

| Case | Lay out (one layer, labels up, nothing stacked) | Field checks |
|---|---|---|
| **C1 grocery** | 8–20 identical packs of one product (biscuits, noodles). One or two dented or opened is good. | count, damaged packs, pack size on each label ("pack of 6", "12 x 50 g") vs 12 pieces expected |
| **C2 pharmacy** | 5–15 boxes of one medicine. An expired or soon-expiring box (within 90 days) and a dented box if you have them. | count, damaged boxes, batch and expiry on each box, mixed batches |

**Photo size:** a look photo is at most **1600 px** on its long side (raised from 640 on 1 Nov 2026, M5-P01), JPEG
quality about 85; faces are blurred on the phone on that full photo before it is sent, and each label crop the model
reads is cut from it (at most 768 px). Labels are much more readable than at 640 px, but with many items each label
is still small: **start with 8 packs (C1) and 5 boxes (C2)**, filling the view from about 40–50 cm. If you hear
*"Some labels are too small to read: take a close look at one label"*, hold one item with its label 15–20 cm from the
glasses and say **"look again"**. That close look is a new look of one item: it reads that label, but its count is 1
and it does **not** update the first look; post and claim then use the close look. So for the claim test, prefer
fewer items so that no close look is needed, and always say your own numbers (step 5). The bigger photo takes longer
to upload on a slow Wi-Fi; the app says "Sending the photo…" meanwhile.

## 1. PC side
1. Double-click **`<workspace>\field-test\START FIELD TEST.cmd`**; it starts the stack and runs `smoke --all` (must end
   with `PASS`). The stack must be on `slice/m5-look`; if the launcher switches to an older branch, run
   `git switch slice/m5-look` in `<repo>` and start with the commands below.
2. In PowerShell at `<repo>`:
   ```powershell
   .\scripts\dev\run-field-stack.ps1 m5-cases --reset --c1-units 8 --c1-pieces 6 --c2-units 5
   #   C1 + C2 receipts on Home (sandbox) expecting what is on your table (8 packs of 6 pieces, 5 boxes; defaults
   #   20 packs of 12, 10 boxes); --reset cancels the open ones; labels in var\m5_cases.html
   .\scripts\dev\run-field-stack.ps1 pair --home       # pairing QR for the home site; scan it in the app
   ```
3. Real models: `.env.local` needs `MODEL_API_KEY` (yours, never send it) and `AI_CLOUD_ENABLED=true`. Without them,
   or when a price is refused, the look answers in rules mode: *"say the count"*.

## 2. Gate 0 (before the phone, 5 min)
1. Take one photo of the C1 layout with the phone, copy it to the PC, then:
   ```powershell
   uv run python tools/probes/m5_gate0.py --photo C:\path\to\c1.jpg --prompt pack --case grocery --allow-unconfirmed-prices
   uv run python tools/probes/m5_gate0.py --photo C:\path\to\c2.jpg --prompt box --case pharmacy --allow-unconfirmed-prices
   ```
   G0-1 (Muse Spark 1.3 label read) and G0-2 (SAM 3.1 instances) each print a status. The key is never printed. Each
   run writes a redacted file `docs\evidence\<date>-m5-gate0-<time>.txt`.
2. On the Meta console, check the two prices and enter them in **`config/ai_pricing.yaml`**: `sam-3.1` `per_image_usd`
   and `muse-spark-1.3` `image_input` (`tokens_per_image`), each with `confirmed: true`. Until then the phone's looks
   are refused by the budget guard unless `.env.local` has `AI_ALLOW_UNCONFIRMED_PRICES=true` (the placeholder price
   is then what is recorded).

## 3. Glasses camera test (G0-5)
Wake the glasses, then in the app **Me → Test glasses camera**. It takes one photo through the Meta toolkit and shows
its **size and delay**; nothing leaves the phone unless you tap **Upload**. If it says unavailable, the looks use the
phone camera; the look screen always says which camera was used.

## 4.–7. On the phone, per case
| Step | Say (or tap) | Look for |
|---|---|---|
| 4. Start | open the receipt `m5-cases` printed (it expects your numbers); Today → **New grocery delivery** / **New pharmacy delivery** (or saying it) makes one with the defaults | a receive job with one line; fewer items than expected show as short |
| 5. Look | **"look"** (or the Look button) | two answers (M5-S01): first, within a few seconds, the count and outlines, *"8 of 8 packs. Reading the labels."*; then, when the labels are read (up to about 40 s), the rest, e.g. *"1 damaged. … Receive 7, flag 1?"*, and the outlines turn green good / red damaged. If the labels cannot be read you hear *"I couldn't read the labels. Say your numbers."*. Note both delays. Wrong count or missed damage: note it, say **"count again"** |
| 6. Claim | **"make a claim"** (after the second answer; while the labels are read the app says to wait) | the draft read out with its lines (damaged, short, pack size, expired, near expiry) |
| 7. Approve | **"claims"** or **"next claim"**, then **"approve"** (or "reject, wrong product"), then **"confirm"** within 10 s | the read-back, then *"Claim approved. Sending it to the supplier is simulated in this build."* |
| 8. Post | your own numbers **"receive 7, flag 1"**, then **"post"**, then **"confirm"** within 10 s | *"Posted. Document 49…"*; the evidence page opens: SAMPLE banner, photo with outlines, the check, the claim, two hashes |

Good units post 101 to **101A**, flagged ones 101 to **101Q** (quality), in one goods receipt in erp-sim. What posts is
always what you said, never the proposal. Then do the other case.

## 8. Send back (no secrets: never `.env.local`, never the key)
- The two Gate 0 files from `docs\evidence\` (already redacted) and what the glasses camera test showed (size, delay).
- Per case: the document number you heard, what you said, what you heard back, a screenshot of the look screen and of
  the evidence page, and whether the counts, flags and expiry were right.
- `Me → Send feedback` text from the app, and the last 50 lines of `var\log\field-api.log` and
  `<workspace>\field-test\stack-output.log`.

## Hosted (scmtips.com): the Home (sandbox) site (M5-H01)
On the hosted deployment the tenant is the real core's SAMPLE organisation; the dev stack's `m5-cases` / `home`
commands (fake-core tokens, direct database writes) do not apply there. Once per deployment, inside the **field-api
container** (its environment already holds `FIELD_CORE_BASE_URL`, `FIELD_ERP_SIM_URL`, `ERPSIM_ADMIN_TOKEN`):
```sh
SEED_ADMIN_PASSWORD='<the org admin password, from the secret store>' \
  python -m field_api.tools.seed_sandbox --admin-email <the SAMPLE org_admin e-mail>
```
It signs in at the core as that org admin (core role `org_admin` -> `field.admin`), exchanges at field-api like the
console's server, and through the APIs only ensures plant **HOME** with storage locations HM01, **101A** and
**101Q** in erp-sim, the site **HOME-SBX "Home (sandbox)"** (mode sandbox) and its zone/bins. Safe to re-run: the
second run creates nothing and prints what exists; exit 1 with the reason on any failure. Options: `--core-url`,
`--field-url` (default `FIELD_SEED_FIELD_API_URL`, else `http://127.0.0.1:8020`), `--erp-sim-url`, `--password-env`
(the NAME of the password variable; the value is never printed). Who can then start a case: core tokens carry
`sites: ["*"]`, so every Field role with `field.task.execute` sees the site: core `procurement` (-> field.operator)
and `org_admin`; `approver` (-> field.supervisor) cannot. **Check its `phone:` line**: the app opens the *first*
site field-api lists (oldest first) and has no site switch, so if the tenant already had sites it prints a
`WARNING phone:` naming the site the phone will open instead, and Today shows no grocery / pharmacy starters there.

**Hosted APK (M5-H02):** CI's android job also uploads **field-hosted-apk** (`app-hosted.apk`, version `0.6.0-m5-hosted`):
the same debug build, whose sign-in screen offers SCMTIPS `https://api.scmtips.com` and Field
`https://field.scmtips.com` on a fresh install (field-debug-apk keeps the dev stack's addresses). Same application id
and signing key, so it installs over the debug APK; addresses typed earlier still win, edit them on the sign-in screen.
