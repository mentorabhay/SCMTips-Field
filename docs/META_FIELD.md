# Meta Field Feasibility & Model API Status Matrix (Task T1.066 / FR1.058)

**Revised:** 2026-10-30 (C0 correction, see the internal review of 30 Oct 2026 §3.14, §3.16)
**Rule:** 2.4. A row is **VERIFIED** only when a committed artefact (CI log, device log, measurement file) proves it. Otherwise it is **UNVERIFIED** (not yet tried, or tried without proof) or **BLOCKED** (tried, refused, with evidence).

> **Retraction.** The 2026-10-27 version of this file contained VERIFIED rows, HTTP results and latency/throughput figures with no committed evidence. Among them were "Pixel 8 CameraX fallback VERIFIED", "JVM engine VERIFIED", Model API 403s with p50/p95 values, and Llama-3.2 CPU/GPU benchmarks. The Android app had never been compiled and no measurement artefacts exist, so all of those claims are withdrawn. The old text remains in git history (`dfea392`).

## 1. Wearables SDK (Meta Wearables Device Access Toolkit, "DAT")

Facts from Meta's public docs, checked 2026-10-30:
- Supported glasses: Ray-Ban Meta (Gen 1 and Gen 2), Ray-Ban Meta Optics, Meta Ray-Ban Display.
- Phones: Android 10+, with the Meta AI app and glasses firmware v20+ (Ray-Ban Meta).
- Distribution (updated 2026-10-30): **Maven Central**, group `com.meta.wearable`, no token needed
  (facebook/meta-wearables-dat-android README and getting-started skill, commit `f4371bc`, 2026-10-09).
  The earlier GitHub Packages + PAT route is obsolete.
- Artifacts used by the M1 app: `mwdat-core`, `mwdat-camera`, `mwdat-speech` (experimental), `mwdat-inputs` (experimental).
- Version **1.0.1** is in `apps/field-android/gradle/libs.versions.toml`. Its POMs and AARs exist on Maven Central
  (HTTP 200, checked 2026-10-30); the public API used by the app was read from the 1.0.1 class files with `javap`.
  **No Gradle build has resolved it yet**, so row 1 stays UNVERIFIED. (Owner note: rule 2.4 forbids writing an
  unresolved version; it is written so a build *can* resolve it, and is marked here until one does.)
- 1.0.1 needs Kotlin metadata 2.2 (Kotlin 2.2.x) and compileSdk 36; the project toolchain was raised to AGP 8.11.1 / Kotlin 2.2.21.
- Developer Mode in the Meta AI app lets an unpublished app register with `com.meta.wearable.mwdat.APPLICATION_ID = "0"`.
- Speech, Inputs and standalone Photo are **experimental**: allowed for development, may need Wearables Developer
  Center enablement, not publishable yet. The app falls back to phone buttons and the phone microphone.

Owner hardware for field test: **Ray-Ban Meta Gen 2** (camera, microphones, open-ear speakers; **no display**).

| # | Capability | Call / API | Device | Status | Tried / evidence |
|---|---|---|---|---|---|
| 1 | Resolve DAT 1.0.1 in a real Gradle build | Gradle | CI / owner PC | **UNVERIFIED** | Artifacts exist on Maven Central (HTTP check). No build yet: CI is blocked by a GitHub billing hold, and the agent's environment has no Android SDK until the owner accepts its licence. Partial evidence (2026-10-30): `tools/android_check/compile_check.py` compiles the whole slice (Kotlin 2.2.21 + Compose plugin) against the real DAT 1.0.1, AndroidX, ML Kit and android-all class files with zero errors; that is a type check, not a build. |
| 2 | SDK init + device discovery | `Wearables.initialize`, `Wearables.devices` | Gen 2 | **UNVERIFIED** | Not tried. |
| 3 | App registration via Meta AI (Developer Mode) | registration flow | Gen 2 + phone | **UNVERIFIED** | Not tried. |
| 4 | Camera permission flow | `checkPermissionStatus(CAMERA)` | Gen 2 | **UNVERIFIED** | Not tried. |
| 5 | Still photo capture | `camera.stream.capturePhoto()` while a 720x1280 @ 2 fps stream is open | Gen 2 | **UNVERIFIED** | Implemented in `DatGlasses.kt`; never run. |
| 6 | Live video stream | DAT camera stream | Gen 2 | **UNVERIFIED** | Not tried. |
| 7 | Speech from the glasses mics | `session.addSpeech()` → `transcriptions` (experimental) | Gen 2 | **UNVERIFIED** | Implemented in `app/.../glasses/DatGlasses.kt`; never run. Fallback: phone `SpeechRecognizer` (hold-to-talk). |
| 8 | Spoken prompts / earcons to glasses speakers | Android TTS / `AudioTrack` over Bluetooth | Gen 2 + phone | **UNVERIFIED** | Not tried. |
| 9 | Capture-button events to app | `session.addInputs()` → `InputEvent.Capture` (experimental) | Gen 2 | **UNVERIFIED** | Implemented in `DatGlasses.kt`; never run. Fallback: on-screen Capture button and the spoken "capture". |
| 10 | Privacy LED behaviour during capture | firmware | Gen 2 | **UNVERIFIED** | Not tried. Controlled by firmware, not the app. |
| 11 | Mock Device Kit (Meta's) | `mwdat-mockdevice` | CI / phone | **UNVERIFIED** | Not tried. The repo's own `MockWearablesKit` is a project test double, not Meta's kit. |
| 12 | Lens display rendering | `mwdat-display` | Ray-Ban **Display** only | **BLOCKED (hardware)** | The owner's Gen 2 has no display. Display features are out of scope for the field test; prompts are spoken instead. |
| 13 | Phone-camera fallback (no glasses) | CameraX | phone | **UNVERIFIED** | Not in the M1 app (CameraX dependency removed; capture is glasses-only). |
| 14 | On-device barcode (GS1/SSCC) | ML Kit barcode | phone | **UNVERIFIED** | The app has never been built. |
| 15 | On-device text (labels/nameplates) | ML Kit text recognition | phone | **UNVERIFIED** | Not in the M1 app; core-ocr parses OCR lines but has no ML Kit binding. |
| 16 | On-device object detector `detector_v1.tflite` | MediaPipe | phone | **UNVERIFIED (no model)** | No model exists. The former 67-byte placeholder and its invented metrics were removed (C0). |

## 2. Cloud model APIs

| # | Service | Use | Status | Tried / evidence |
|---|---|---|---|---|
| 17 | Meta Llama API (if the owner's $150 credit is for it) | Fallback vision read of hard labels | **UNVERIFIED** | Not tried. The owner is confirming which product the credit is for. Key stays in owner-only `.env.local`; calls are capped by the budget guard. |
| 18 | Baseten (owner has $100 credit) | Field Assistant fallback provider (M3) | **UNVERIFIED** | Not tried. Only per-token or scale-to-zero use is allowed. M3 (2026-10-31): wired as the OpenAI-compatible fallback in `services/field-api/src/field_api/assistant/model.py`, used only when BASETEN_BASE_URL, BASETEN_MODEL_ID and BASETEN_API_KEY are set and the model has a price in `config/ai_pricing.yaml` (none yet); never called for real. |
| 19 | Meta Model API from India: chat completions at api.meta.ai/v1 with a Bearer key, models muse-spark-1.3 and muse-spark-1.2 (Standard tier) | M3 Field Assistant, M4 brief router | **VERIFIED** | 2026-10-31, owner's PC in India: HTTP 200 for both models, OpenAI-style answer with usage.prompt_tokens_details.cached_tokens and usage.completion_tokens_details.reasoning_tokens; with max_tokens 20 both spent 18 on reasoning and returned no text (finish_reason length). Evidence: `docs/evidence/2026-10-31-muse-model-api-india.txt`. Consequence: assistant output cap 1024, and a cut-off empty reply falls back to rules (test_reply_cut_off_by_reasoning_falls_back_and_is_still_billed). M4 (2026-10-31): muse-spark-1.3 is the default of the assistant, the brief router and `stack assistant-check` (all through `meta_config`), and it is priced in config/ai_pricing.yaml (test_default_model_is_muse_spark_1_3_and_priced). |
| 20 | Meta Model API beyond access: tool calling, image input, standard price of muse-spark-1.3, latency of a Field Assistant turn through the budget guard | M3 Field Assistant, M4 brief router | **UNVERIFIED** | 2026-10-31: only the access call in row 19 has run; the assistant's tool-call and image requests are tested against an HTTP test double in test code only. The owner chose muse-spark-1.3 as the default (A-04); its Standard price in config/ai_pricing.yaml is set equal to 1.2's published Standard rates until the owner confirms it on the console. Next: the owner runs the launcher (stack assistant-check) and one spoken session. M4 (2026-10-31): the owner's field-api log showed every turn timing out at 6 s (AI_TIMEOUT, once AI_TRANSPORT); the assistant now answers rules first and gives the model at most ASSISTANT_MODEL_DEADLINE_S (default 3.5 s) per turn, and the brief router 4 s. Whether Muse answers a Field Assistant turn or a brief rewrite within those deadlines from India is not measured. |
| 22 | Muse Voice Transcribe (`muse-voice-transcribe-1.0`) | Optional transcription instead of the phone recogniser (handover F3) | **UNVERIFIED (not built)** | 2026-10-31: not tried, no endpoint built. The model has no price in config/ai_pricing.yaml, so the budget guard would refuse it (AI_PRICE_UNKNOWN), and the request shape of Meta's transcription API was not checked (the build sandbox has no key and no route to the provider; no call was attempted). The phone's recogniser stays the only speech-to-text. To turn it on: the owner records one real call (status, latency, no key) and its price. |
| 23 | SAM 3.1 (`sam-3.1`) outline on receipt and damage photos | Capture attachment (handover F3) | **UNVERIFIED (not built)** | 2026-10-31: not tried, no endpoint built, for the same reasons as row 22 (no price, API shape not checked, no call attempted). Captures carry no outline. |
| 24 | Muse Image | Never used (prohibited in India, A-04) | **REFUSED BY DESIGN** | Any model id containing "image" is refused by the model client (`validate_model_id`), by the router (the provider is skipped) and by the budget guard (`AI_MODEL_PROHIBITED`, even with a price); config/ai_pricing.yaml lists none. Test: test_image_models_can_never_be_configured_or_called. |

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
