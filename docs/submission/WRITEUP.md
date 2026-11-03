# SCMTIPS Field: submission write-up (draft for the owner's review, plan item M18 / Q15)

Status: **draft**, written 1 Nov 2026 from the ledgers (`docs/STATUS/m3.yaml`, `m4.yaml`, `phase1..4.yaml`), the
feasibility register `docs/META_FIELD.md` and the run logs in `docs/evidence/runs/`. Nothing here is a completion
claim: every M3 and M4 ledger row is `partial` (one `missing`), and **nothing has been proven on the glasses yet**.
Placeholders in angle brackets are for the owner: `<hosted URL>`, `<video URL>`, `<judge accounts>`.

All data shown is **SAMPLE** (a made-up drone maker, "SAMPLE drone OEM"). Every disruption is a **SIMULATED**
scenario file. Both are labelled as such on every screen and in every file.

## 1. The problem

A manufacturer already runs a market-intelligence feed, a planning system, a work and PMO tool, an ERP and a shop
floor. When a disruption hits, such as rare-earth magnet export curbs, the information is spread across all of them.
The decision is taken on a laptop, far from the people who see the physical goods. The loop only closes when someone
types the receipt into the ERP days later.

SCMTIPS connects those systems instead of replacing them. It detects the threat, drafts a decision with proof and
gets the approval by voice. It then closes the loop on physical evidence: the warehouse operator captures the goods
receipt in the field and the ERP posts it. **SCMTIPS Field** is the part that lives in the field. It is the phone
app for Ray-Ban Meta glasses, its server (field-api and field-worker), an S/4-shaped ERP simulator, and the
server-side Meta model router.

## 2. What was built, and when (dates from git, per the owner's rule T1)

The event started on **26 Oct 2026, 12:00 PM ET (21:30 IST)**. The deadline is **4 Nov 2026, 9:00 PM ET (5 Nov,
07:30 IST)**.

Framing, in T1's words: the core is **"our platform, built 22–26 Oct during the application period, disclosed; the
hackathon project is Field, the Meta layer and the integration built 27 Oct – 4 Nov"**. NaradCue, a planning system and
Heartbeat are presented as **the customer's existing systems**.

The exact dates in git (author dates, IST):

| Repository | First commit | Commits before the start | Commits inside the window |
|---|---|---|---|
| SCMTIPS Field (`mentorabhay/SCMTips-Field`, public at submission) | **27 Oct 2026, 03:46 IST** (`4fcc41a`), 6 h 16 min after the start | none | all: 25 on 27 Oct, 10 on 28 Oct, 1 on 29 Oct, 43 on 30 Oct, 80 on 31 Oct, and from 1 Nov on (165 up to `4ee00dc`, plus this task's) |
| SCMTIPS core (the private SCMTIPS core repository, private) | **21 Oct 2026, 06:57 IST** (`1ab111f`) | 219, from 21 Oct 06:57 to 26 Oct 12:38 IST (`96ee9f0`, "start P14") | 27 on 30 Oct (the core's P14 package: personas, staff console, data feeds per planning view, release to execution, screenshot book), then from 31 Oct 07:28 IST the integration branch the core's integration branch (23 up to `392db14`, plus this task's) |

**For the owner (please confirm before submitting):**

1. git shows the core's first commit on **21 Oct**, 06:57 IST: 26 commits that day. T1 says "built 22–26 Oct". This
   draft keeps T1's wording in the quote above but states 21 Oct in the table. T1's own rule is that a wrong date
   claim is the one thing that can disqualify the entry, so the dates have to agree before this goes out.
2. The core's P14 package (27 commits, **30 Oct**) was committed inside the window. It is core platform work, not
   Field or the integration. T1 counts the core's in-window work only "from today [31 Oct] onward". This draft lists
   P14 as disclosed core work inside the window. It does not claim it as the hackathon project.
3. The organisers' answer to T1's question ("Our submission connects to platforms we built before the event
   (disclosed with dates); the submitted project and code were built in the window. Is that allowed?") belongs here
   once it arrives.

What the hackathon project consists of (all built in the window):

- **Field (this repository):**
  - field-api (FastAPI, forced row-level security, idempotency) and field-worker (posting queue, outbox, the
    core's feeds, the ERP snapshot);
  - erp-sim, an S/4-shaped OData simulator, behind the `ErpPort` connector;
  - the Android app (Compose; glasses through Meta's Wearables Device Access Toolkit 1.0.1), with the warehouse and
    tower jobs, sandbox mode, the glasses-first work session and the approver flow ported from the core's old
    wearable app (F1);
  - sign-in against the core (F2);
  - the Field Assistant and the spoken-brief router on the Meta Model API through a server-side budget guard (F3);
  - the goods-receipt finale to the core's feeds (F4);
  - the exchange-contract page `docs/EXCHANGE_CONTRACT.md` (F6, partly);
  - the 3-minute demo run (`docs/DEMO_RUN.md`).
- **The integration on the core's side** (the core's integration branch, from 31 Oct):
  - the relevance gate;
  - app sign-in and signing keys for Field;
  - exchange contract v1 and the Connected systems page;
  - the NaradCue link and the signals workbook;
  - file modes for goods receipts, ERP extracts and progress;
  - the SAMPLE exports for every system;
  - hosted demo mode;
  - the scenario pack;
  - the clean-up and two security fixes.

## 3. Architecture

```
 Ray-Ban Meta Gen 2 ──Bluetooth── Android phone: SCMTIPS Field app
 (camera, mics, speakers,          (Meta Wearables Device Access Toolkit 1.0.1; phone mic and buttons as fallback)
  capture button)                          │ HTTPS
                                           ▼
                              field-api ── budget guard ── Meta Model API (Muse Spark, muse-spark-1.3)
                              field-worker                  (keys on the server only; Baseten as a fallback, unused)
                                │      │
                     ErpPort    │      │ two signed feeds (HMAC), the ERP snapshot
                                ▼      ▼
                   erp-sim (S/4-shaped OData)        SCMTIPS core (private): signals -> exposure -> decisions ->
                                                     execution, audit chain, Connected systems, sign-in + JWKS
                                                       ▲             ▲              ▲
                                     market intelligence    planning / APS    work and PMO
                                     (NaradCue)              (planning)        (Heartbeat)
                                     the customer's existing systems: live API or file (Excel) mode
```

- **Glasses -> phone -> field-api -> ErpPort -> erp-sim.** The glasses capture (photo, speech, capture button). The
  phone decodes and confirms by voice. field-api records the job. field-worker posts the material document to the
  ERP through `ErpPort`, here erp-sim, the S/4-shaped simulator. No production path imports a mock (rule 2.2).
- **Field <-> core.** Field trusts the core's signed app tokens through its JWKS (`/v1/auth/exchange`) and checks
  the device status at the core. Field reads the next decision and its spoken brief. Voice turns go to the core's
  own wearable API, and the core checks every number of a brief before the glasses speak it. Each goods receipt 101
  becomes two signed feed rows (stock and the PO line). Every 15 minutes the ERP's stock and open POs go to the same
  feeds. Everything follows the exchange contract v1 (`docs/EXCHANGE_CONTRACT.md`).
- **Meta Model API through the budget guard.** Every model call is made by field-api, never by the phone. The guard
  enforces hard caps per provider (`AI_BUDGET_META_USD`); the key stays in the server's git-ignored `.env.local`. With
  no key, over budget, a timeout or a refusal, the template text is spoken: the core's template brief, or the
  assistant's rules mode.
- **The customer's existing systems.** NaradCue (market intelligence), a planning system and Heartbeat (PMO) are
  existing products that play the customer's systems. They are not part of this submission's code. Each connects to
  the core by a live API or by its file template (the same contract, labelled SIMULATED in file mode).

## 4. How Meta technologies are used

| Meta technology | Where | What it does | Proven? (`docs/META_FIELD.md`) |
|---|---|---|---|
| **Ray-Ban Meta Gen 2** through the **Wearables Device Access Toolkit 1.0.1** (`mwdat-core`) | `apps/field-android` (core-wearables, `DatGlasses.kt`) | camera stream and still photo for receipts and labels; speech from the glasses mics (experimental in the toolkit); capture-button events; "Hey Meta, start SCMTips Field" voice invocation | **UNVERIFIED**, rows 1 to 10 and 25, and HW-01 to HW-06: nothing has run on the glasses yet. Row 1: no Gradle build has resolved 1.0.1 yet; a compile check against its class files passes (a type check, not a build) |
| **Muse Spark** (`muse-spark-1.3`) through the **Meta Model API** (`api.meta.ai/v1`, chat completions) | field-api: the Field Assistant (`/v1/assistant/turns`) and the spoken-brief router (`/v1/briefs/spoken`) | rewrites the core's decision brief for the ear (4 s deadline; the core's number check must accept it); answers spoken questions in a work session (rules first, model second) | **VERIFIED access** from India, row 19 (31 Oct 2026, the owner's PC: HTTP 200 for muse-spark-1.3 and 1.2). **UNVERIFIED**, row 20: tool calls, image input, latency within the deadlines, the standard price. Row 21: a model rewrite has not yet reached the core's check (no key in the build container) |
| Muse Voice Transcribe, SAM 3.1 | planned (F3) | transcription; outlines on receipt photos | **not built** (rows 22, 23). The phone's recogniser is the speech-to-text. |
| Muse Image | never used | - | prohibited in India (owner decision, A-04) |

## 5. What is proven and what is not

Strictly from the ledgers and the committed run logs:

| Claim | Status | Evidence |
|---|---|---|
| The approver flow against the **real** core: app sign-in, exchange, next decision, spoken brief, the core's number check (template accepted, a changed number refused), "approve option two", read-back, replay rules, confirm, decision EXECUTING | passed in a **Linux container** (Python smokes over HTTP, not the app) | `docs/evidence/runs/2026-10-31-k1-real-core-smokes.txt`, `2026-11-01-k4-scenario-approver.txt`; M4-C13, M4-C16 (partial) |
| The goods-receipt finale against the real core: GR 101 in erp-sim against the core's own PO, two signed feed rows, PO line received, on-hand equal to erp-sim's, a new base plan run | passed in a Linux container | `2026-10-31-k1-...`, `2026-10-31-k2-erp-export-and-snapshot.txt`; M4-C04, M4-C14, M4-C15 (partial) |
| The whole 3-minute run, reset -> seed -> snapshot -> scenario -> approval -> receipt -> re-plan, **twice in a row** | passed in a Linux container (77 s each) | `docs/evidence/runs/2026-11-01-k5-demo-run.txt`; M4-C17 (partial) |
| Meta Model API access from India | VERIFIED (access only) | META_FIELD row 19, `docs/evidence/2026-10-31-muse-model-api-india.txt` |
| Anything on the **Ray-Ban Meta glasses** | **not proven** | META_FIELD rows 1 to 10, 25, HW-01 to HW-06: UNVERIFIED |
| The Android app on the owner's phone against the real core | **not proven** | M4-B01 to B08: "not run on the owner's phone" |
| The owner's PC kit (`<workspace>\ARO`) and a hosted server | **not proven** | the core's `docs/DEMO_MODE.md` "Not verified yet"; Q14 parked |
| The HUD decision player (F5) for judges without glasses | **not built** | M4-F05 `missing` |

The phase ledgers (phase 1 to 4) hold 298 rows: 13 `done`, 255 `partial`, 11 `stub`, 19 `missing`. No phase is
closed (rule 2.3); they are back-filled after the hackathon (A-01, A-03, A-04).

## 6. SAMPLE and SIMULATED: what is not real

- **All master data and figures:** the SAMPLE drone OEM. Items (`CP-204` brushless motor, ...), plants (`PLANT-GOA`,
  `DC-MIL`), suppliers (`SUP-S02`, ...), POs (`PO-26-1002`, ...) and every quantity and cost are made up.
- **The disruption:** "Export licence checks on rare-earth magnets" is a SIMULATED scenario file. It is sent through
  the core's signals-workbook file mode. In this run it is not a live news item.
- **The ERP:** erp-sim is a simulator shaped like S/4HANA OData. No SAP system is connected (not verified).
- **The planning system and the PMO tool:** file mode with their real templates. The core imports progress files,
  but no planning result yet. Neither is driven in the demo run.
- **The approver and the warehouse operator in the proven runs:** Field's Python smokes making the app's API calls,
  not a person with the glasses.
- **The spoken brief in the proven runs:** the core's template. No Muse rewrite was made in the container.

## 7. Limits

- Nothing has run on the glasses. Speech, inputs and the camera are experimental in Meta's toolkit, and Meta may
  refuse them per user (`CAPABILITY_DENIED`). The app then falls back to the phone mic and buttons.
- Ray-Ban Meta Gen 2 has no display: prompts are spoken. The HUD simulator is not built.
- The starvation clock does not move on the demo receipt. That supply was already in the plan, so the core re-plans,
  but CP-204 stays at about 129 days.
- Hosted demo mode signs the SAMPLE organisation in with a password only (demo-class environment, banner). Production
  refuses this by design.
- A strict sign-in step-up (an authenticator code) was not run against the core. In demo mode it is waived and the
  waiver is recorded.

## 8. How to run

- Field's stack alone (stand-in core, no SCMTIPS core needed): `scripts/dev/run-field-stack.ps1` or `.sh`, see
  `docs/SETUP/FIELD_TEST_GUIDE.md`.
- The whole demo against the core: `scripts/dev/demo-run.ps1 <the core checkout>`, see `docs/DEMO_RUN.md`
  (prerequisites, the beats, live and file paths, recovery).
- How another system plugs in: `docs/EXCHANGE_CONTRACT.md`.
- Links: hosted app `<hosted URL>`, video `<video URL>`, judge accounts `<judge accounts>` (the core's
  `scmtips-demo judges`).
