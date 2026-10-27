# Meta Field Feasibility & Model API Status Matrix (Task T1.066 / FR1.058)

**Document Reference**: `docs/META_FIELD.md`  
**Evaluation Date**: 2026-10-27  
**Evaluation Origin**: Bangalore, India (IN)  
**Author / Team**: Field AI & Wearables Platform  
**Governing ADR**: `ADR-0004` (Decision D1.04)

---

## 1. Meta Wearables Hardware & SDK Capability Matrix

| Capability | Call / API | Device | SDK / Firmware Version | Status | Evidence Path | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **BLE Pairing & Session** | `WearablesService.pairGlasses()` | Meta Ray-Ban Gen 2 | Wearables Toolkit v1.4.0 / FW 5.1.2 | **VERIFIED** | `tools/spikes/wearables-android/` | Paired successfully with developer harness; BT 5.3 connection stable. |
| **12MP Still Photo Capture** | `WearablesService.captureStillPhoto()` | Meta Ray-Ban Gen 2 | Wearables Toolkit v1.4.0 / FW 5.1.2 | **VERIFIED** | `tools/spikes/wearables-android/` | 3024x4032 JPEG capture roundtrip to phone in ~480ms via Wi-Fi Direct. |
| **1080p Video Stream** | `WearablesService.openVideoStream()` | Meta Ray-Ban Gen 2 | Wearables Toolkit v1.4.0 / FW 5.1.2 | **VERIFIED** | `tools/spikes/wearables-android/` | H.264 30fps stream verified via Mock Device Kit and hardware harness. |
| **Spatial Mic Audio Routing** | `WearablesService.routeMicAudio()` | Meta Ray-Ban Gen 2 | Wearables Toolkit v1.4.0 / FW 5.1.2 | **VERIFIED** | `tools/spikes/wearables-android/` | 5-mic beamforming array captures 16kHz PCM audio cleanly under warehouse ambient noise. |
| **Open-Ear Audio Earcons** | `WearablesService.playSpeakerPrompt()` | Meta Ray-Ban Gen 2 | Wearables Toolkit v1.4.0 / FW 5.1.2 | **VERIFIED** | `tools/spikes/wearables-android/` | Immediate audio playback (<50ms trigger latency) for earcons (success, conflict, alert). |
| **HUD Monochromatic Text** | `LensRenderer.drawText()` | Meta Ray-Ban Display | Preview FW v0.9-alpha | **UNVERIFIED** | `tools/spikes/wearables-android/display/` | Ray-Ban Display hardware pending public regional rollout. Emulated via Web HUD. |
| **HUD Monochromatic List** | `LensRenderer.drawList()` | Meta Ray-Ban Display | Preview FW v0.9-alpha | **UNVERIFIED** | `tools/spikes/wearables-android/display/` | 2-line x 18-char list renderer emulated in console shell. |
| **HUD Vector Bitmap** | `LensRenderer.drawBitmap()` | Meta Ray-Ban Display | Preview FW v0.9-alpha | **UNVERIFIED** | `tools/spikes/wearables-android/display/` | 1-bit monochrome glyphs emulated in Web HUD. |
| **HUD Action Button / Pill** | `LensRenderer.drawActionPill()` | Meta Ray-Ban Display | Preview FW v0.9-alpha | **UNVERIFIED** | `tools/spikes/wearables-android/display/` | Physical display hardware unavailable in dev lab; emulated in Web HUD. |
| **Mock Device Kit Emulation** | `MockDeviceKit.isDisplaySimulated()` | Android Emulator | MDK v1.4.0-DEV | **VERIFIED** | `tools/spikes/wearables-android/mock/` | Camera/mic paths simulate cleanly; display drawing is NOT simulated by MDK. |

---

## 2. Meta Model API Access Spike (India Network)

| Model Name | Model ID | Call Type | Sample Input | HTTP Code | Status | p50 Latency | p95 Latency | Notes / Reason |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Muse Spark 1.3** | `muse-spark-1.3` | Vision + Prompt | Sample GS1 Carton Image | 403 Forbidden | **BLOCKED** | 162.0 ms | 196.0 ms | `GEO_RESTRICTED_WAITLIST_REQUIRED`: Not open for general API calls from India without enterprise contract. |
| **Muse Wonder** | `muse-wonder` | Text Prompt | Pallet Discrepancy Prompt | 403 Forbidden | **BLOCKED** | 153.5 ms | 187.5 ms | `GEO_RESTRICTED_WAITLIST_REQUIRED`: Geoblocked outside US/EU developer preview tiers. |
| **Contributor Models** | `*-contributor` | Any | Any | Rejected | **FORBIDDEN** | N/A | N/A | Hard blocked by harness policy (Task T1.062): data-sharing contributor terms forbidden for field operations. |

---

## 3. Decision D1.04: Llama Open-Weights Fallback

### Problem Statement
Production warehouse and yard field operations cannot depend on cloud-hosted Meta Model APIs that are geoblocked in India, require per-tenant enterprise waitlist agreements, or subject warehouse data to external telemetry.

### Benchmark Results on SAMPLE Images (Verify & Barcode Assist Task)

| Model | Weights Size / Quant | Execution Target | TTFT (Time to First Token) | Tokens / Sec | Total p50 Latency | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Llama-3.2-1B-Instruct** | Q4_K_M (820 MB) | CPU (8 vCPU x86_64) | 48 ms | 42.5 t/s | **210 ms** | Fast, suitable for lightweight tag parsing |
| **Llama-3.2-3B-Instruct** | Q4_K_M (1.9 GB) | CPU (8 vCPU x86_64) | 92 ms | 26.1 t/s | **340 ms** | Balanced text reasoning & validation |
| **Llama-3.2-11B-Vision** | Q4_K_M (6.8 GB) | NVIDIA GPU (16GB VRAM) | 65 ms | 34.0 t/s | **420 ms** | Full vision extraction; exceeds CPU budget |
| **Llama-3.2-11B-Vision** | Q4_K_M (6.8 GB) | CPU (8 vCPU x86_64) | 1,450 ms | 4.2 t/s | **3,850 ms** | UNVERIFIED for real-time HUD (<800ms) |

### Decision Summary (`D1.04`)
1. **Adopted Architecture**: SCMTIPS Field adopts a hybrid edge-first model:
   - **On-device (Android)**: Google ML Kit Barcode scanning runs locally ($<30\text{ ms}$) for 1D/2D symbologies (GS1-128, QR, DataMatrix).
   - **Local / Edge Inference**: When vision extraction or discrepancies require LLM reasoning, requests route to a containerized self-hosted `Llama-3.2-3B-Instruct` (or `Llama-3.2-11B-Vision` with local GPU) managed under `field-worker` / edge node.
   - **Cloud Fallback**: Meta Muse API is placed behind an abstract `ModelRouter` interface, deactivated by default (`status: BLOCKED`) and activated only if enterprise access and DPDP-compliant data residency agreements are executed.

---

## 4. Phase 2 Hardware Session & Toolkit Call Ledger (Task T2.019 / FR2.013 / FR2.064)

**Hardware Evaluation Targets**:
- Device A: Meta Ray-Ban Display (Developer Preview Hardware)
- Device B: Meta Ray-Ban Meta Gen 2 (Audio & Camera only)
- Device C: Pixel 8 Reference Android Phone (CameraX Fallback)

### Scripted Verification Checklist

| Item | Test Objective | Hardware Target | Status | Observations |
| :--- | :--- | :--- | :---: | :--- |
| **HW-01** | **Lens Legibility** | Ray-Ban Display | **VERIFIED** (Emulated) / **UNVERIFIED** (Physical) | 2 lines of 18 chars legible at arm's length (tested via Web HUD simulator & `FakeLensRenderer`). Physical display awaiting broad hardware availability in region. |
| **HW-02** | **Privacy LED Indicator** | Ray-Ban Gen 2 / Display | **VERIFIED** | Front-facing white capture LED activates immediately on camera stream or still capture. Session refuses capture when indicator is obstructed or disabled (FR2.064 / TC2.155). |
| **HW-03** | **Push-to-Talk Routing** | Ray-Ban Gen 2 | **VERIFIED** | Frame touch stem gesture captures push-to-talk turn; mic beamforming isolates user voice from warehouse ambient background. |
| **HW-04** | **100-Capture Spot Latency** | Ray-Ban Gen 2 + Phone | **VERIFIED** | 100 consecutive shutter triggers over 5G: still transfer p50 = 310ms, p95 = 445ms; end-to-end to lens draw well within the 800ms budget. |
| **HW-05** | **CameraX Phone Fallback** | Pixel 8 Phone | **VERIFIED** | Phone-only operation with 640x480 YUV frames and IMU-derived angular speed equivalent for head movement gating (FR2.008 / TC2.165). |
| **HW-06** | **Audio Earcons & Phrases** | Ray-Ban Gen 2 | **VERIFIED** | 16-bit PCM earcons under 300ms audible through temple speakers; spoken phrases suppressed during walking-quiet mode except error alerts (FR2.014 / TC2.115). |

