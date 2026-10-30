# Meta Field Feasibility & Model API Status Matrix (Task T1.066 / FR1.058)

**Revised:** 2026-10-30 (C0 correction, see the internal review of 30 Oct 2026 §3.14, §3.16)
**Rule:** 2.4. A row is **VERIFIED** only when a committed artefact (CI log, device log, measurement file) proves it. Otherwise it is **UNVERIFIED** (not yet tried, or tried without proof) or **BLOCKED** (tried, refused, with evidence).

> **Retraction.** The 2026-10-27 version of this file contained VERIFIED rows, HTTP results and latency/throughput figures with no committed evidence. Among them were "Pixel 8 CameraX fallback VERIFIED", "JVM engine VERIFIED", Model API 403s with p50/p95 values, and Llama-3.2 CPU/GPU benchmarks. The Android app had never been compiled and no measurement artefacts exist, so all of those claims are withdrawn. The old text remains in git history (`dfea392`).

## 1. Wearables SDK (Meta Wearables Device Access Toolkit, "DAT")

Facts from Meta's public docs, checked 2026-10-30:
- Supported glasses: Ray-Ban Meta (Gen 1 and Gen 2), Ray-Ban Meta Optics, Meta Ray-Ban Display.
- Phones: Android 10+, with the Meta AI app and glasses firmware v20+ (Ray-Ban Meta).
- Distribution: GitHub Packages `https://maven.pkg.github.com/facebook/meta-wearables-dat-android`. Needs a PAT (classic) with `read:packages`.
- Artifacts: group `com.meta.wearable`, names `mwdat-core`, `mwdat-camera`, `mwdat-display`, `mwdat-mockdevice`.
- Developer Mode in the Meta AI app lets an unpublished app register with `com.meta.wearable.mwdat.APPLICATION_ID = "0"`.

The version is **not written here** until a real build resolves it (rule 2.4).

Owner hardware for field test: **Ray-Ban Meta Gen 2** (camera, microphones, open-ear speakers; **no display**).

| # | Capability | Call / API | Device | Status | Tried / evidence |
|---|---|---|---|---|---|
| 1 | Resolve DAT artifacts in a real Gradle build | Gradle | CI | **UNVERIFIED** | Not tried. Needs the `MWDAT_GITHUB_TOKEN` Actions secret, and Actions is blocked by a GitHub billing hold (2026-10-30). |
| 2 | SDK init + device discovery | `Wearables.initialize`, `Wearables.devices` | Gen 2 | **UNVERIFIED** | Not tried. |
| 3 | App registration via Meta AI (Developer Mode) | registration flow | Gen 2 + phone | **UNVERIFIED** | Not tried. |
| 4 | Camera permission flow | `checkPermissionStatus(CAMERA)` | Gen 2 | **UNVERIFIED** | Not tried. |
| 5 | Still photo capture | DAT camera | Gen 2 | **UNVERIFIED** | Not tried. |
| 6 | Live video stream | DAT camera stream | Gen 2 | **UNVERIFIED** | Not tried. |
| 7 | Mic audio into phone ASR | Bluetooth HFP/SCO + Android `SpeechRecognizer` | Gen 2 + phone | **UNVERIFIED** | Not tried. |
| 8 | Spoken prompts / earcons to glasses speakers | Android TTS / `AudioTrack` over Bluetooth | Gen 2 + phone | **UNVERIFIED** | Not tried. |
| 9 | Capture-button / touch-pad events to app | DAT / AVRCP | Gen 2 | **UNVERIFIED** | Not tried. Availability to third-party apps unknown. |
| 10 | Privacy LED behaviour during capture | firmware | Gen 2 | **UNVERIFIED** | Not tried. Controlled by firmware, not the app. |
| 11 | Mock Device Kit (Meta's) | `mwdat-mockdevice` | CI / phone | **UNVERIFIED** | Not tried. The repo's own `MockWearablesKit` is a project test double, not Meta's kit. |
| 12 | Lens display rendering | `mwdat-display` | Ray-Ban **Display** only | **BLOCKED (hardware)** | The owner's Gen 2 has no display. Display features are out of scope for the field test; prompts are spoken instead. |
| 13 | Phone-camera fallback (no glasses) | CameraX | phone | **UNVERIFIED** | The app has never been built. |
| 14 | On-device barcode (GS1/SSCC) | ML Kit barcode | phone | **UNVERIFIED** | The app has never been built. |
| 15 | On-device text (labels/nameplates) | ML Kit text recognition | phone | **UNVERIFIED** | The app has never been built. |
| 16 | On-device object detector `detector_v1.tflite` | MediaPipe | phone | **UNVERIFIED (no model)** | No model exists. The former 67-byte placeholder and its invented metrics were removed (C0). |

## 2. Cloud model APIs

| # | Service | Use | Status | Tried / evidence |
|---|---|---|---|---|
| 17 | Meta Llama API (if the owner's $150 credit is for it) | Fallback vision read of hard labels | **UNVERIFIED** | Not tried. The owner is confirming which product the credit is for. Key stays in owner-only `.env.local`; calls are capped by the budget guard. |
| 18 | Baseten (owner has $100 credit) | Optional hosted model | **UNVERIFIED** | Not tried. Only per-token or scale-to-zero use is allowed. |
| 19 | "Muse" Meta model API from India | n/a | **UNVERIFIED** | The earlier 403/latency rows had no evidence and were withdrawn. |

## 3. Decision D1.04 (revised)

**Edge-first.** Barcodes, text, speech-to-text and text-to-speech run on the phone at no cost. Cloud vision is an optional fallback that the operator triggers, behind a `ModelRouter` interface with a server-side budget guard. The cloud fallback is off by default (`AI_CLOUD_ENABLED=false`). There are no latency claims until they are measured on the owner's hardware with committed raw data.

## 4. Phase 2 Hardware Session & Toolkit Call Ledger (owner field test)

| Item | Objective | Target | Status |
|---|---|---|---|
| HW-01 | Register app with glasses in Developer Mode | Gen 2 + Android phone | UNVERIFIED |
| HW-02 | Capture photo from glasses into app | Gen 2 | UNVERIFIED |
| HW-03 | Voice "confirm" heard via glasses mic | Gen 2 | UNVERIFIED |
| HW-04 | Spoken prompt audible on glasses speakers | Gen 2 | UNVERIFIED |
| HW-05 | End-to-end goods receipt posted to erp-sim and read back | Gen 2 + phone + PC | UNVERIFIED |
| HW-06 | Phone-only fallback (no glasses) | phone | UNVERIFIED |
