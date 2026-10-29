# Meta Field Feasibility & Model API Status Matrix (Task T1.066 / FR1.058)

**Document Reference**: `docs/META_FIELD.md`  
**Evaluation Date**: 2026-10-27  
**Evaluation Origin**: Bangalore, India (IN)  
**Author / Team**: Field AI & Wearables Platform  
**Governing ADR**: `ADR-0004` (Decision D1.04)

---

## 1. Meta Wearables Hardware & SDK Capability Matrix (Rule 2.4 / Finding F-07)

| Capability | Call / API | Device | SDK / Firmware Version | Status | Evidence Path | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Wearables Toolkit SDK** | Gradle dependency | Android Host | Unresolved Coordinate | **UNVERIFIED** | `tools/spikes/wearables-android/` | SDK coordinate `com.meta.wearables:toolkit-sdk` not publicly resolvable from standard Maven repositories (Finding F-07). Pure `GlassesSession` interface sits in `:core-wearables`; `MockWearablesKit` moved to `:core-wearables-testing`. |
| **BLE Pairing & Session** | `GlassesSession.connect()` | Meta Ray-Ban Gen 2 | Mock / Interface | **UNVERIFIED** | `tools/spikes/wearables-android/` | Hardware pairing unverified on physical SDK. Simulated via `MockWearablesKit.connect()`. |
| **12MP Still Photo Capture** | `StillCapture.capturePhoto()` | Meta Ray-Ban Gen 2 | Mock / Interface | **UNVERIFIED** | `tools/spikes/wearables-android/` | Hardware capture unverified on physical SDK. Simulated via `MockWearablesKit.stillCapture`; CameraX phone fallback is VERIFIED. |
| **1080p Video Stream** | `PreviewStream.frames` | Meta Ray-Ban Gen 2 | Mock / Interface | **UNVERIFIED** | `tools/spikes/wearables-android/` | Hardware stream unverified on physical SDK. Simulated via `PreviewFrame` flow; CameraX phone fallback is VERIFIED. |
| **Spatial Mic Audio Routing** | `AudioOut / ASR` | Meta Ray-Ban Gen 2 | Mock / Interface | **UNVERIFIED** | `tools/spikes/wearables-android/` | Hardware beamforming unverified on physical SDK. Mobile phone microphone input is VERIFIED. |
| **Open-Ear Audio Earcons** | `AudioOut.playEarcon()` | Meta Ray-Ban Gen 2 | Mock / Interface | **UNVERIFIED** | `tools/spikes/wearables-android/` | Physical temple speakers unverified. Android TTS and MediaPlayer cues VERIFIED on phone. |
| **HUD Monochromatic Text** | `LensRenderer.renderState()` | Meta Ray-Ban Display | Pure Kotlin Renderer | **UNVERIFIED** (Physical) / **VERIFIED** (JVM Engine) | `tools/spikes/wearables-android/display/` | Physical display hardware unreleased. Monochromatic 2-line x 18-char text formatting verified via `RayBanLensRenderer` and `FakeLensRenderer`. |
| **HUD Monochromatic List** | `LensRenderer.renderState()` | Meta Ray-Ban Display | Pure Kotlin Renderer | **UNVERIFIED** (Physical) / **VERIFIED** (JVM Engine) | `tools/spikes/wearables-android/display/` | Physical display unreleased; state machine formatting verified in test doubles. |
| **HUD Action Button / Pill** | `LensRenderer.renderState()` | Meta Ray-Ban Display | Pure Kotlin Renderer | **UNVERIFIED** (Physical) / **VERIFIED** (JVM Engine) | `tools/spikes/wearables-android/display/` | Physical display unreleased; pill truncation (<=18 chars) verified in test doubles. |
| **Mock Device Kit Emulation** | `MockWearablesKit` | Android Host / CI | Internal Test Double | **VERIFIED** | `tools/spikes/wearables-android/mock/` | Full session simulation cleanly isolated in `:core-wearables-testing` (Rule 2.2). |


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
| **HW-01** | **Lens Legibility** | Ray-Ban Display | **UNVERIFIED** (Physical) / **VERIFIED** (Emulated) | 2 lines of 18 chars legible at arm's length (tested via Web HUD simulator & `FakeLensRenderer`). Physical display awaiting broad hardware availability in region. |
| **HW-02** | **Privacy LED Indicator** | Ray-Ban Gen 2 / Display | **UNVERIFIED** (Physical) / **VERIFIED** (Simulated) | Privacy LED interlock simulated via `GlassesSession` connection state. Physical LED interlock requires partner firmware release. |
| **HW-03** | **Push-to-Talk Routing** | Ray-Ban Gen 2 | **UNVERIFIED** (Physical) / **VERIFIED** (Phone Fallback) | Touch stem PTT unverified on physical hardware. Phone on-screen PTT and headset button routing verified. |
| **HW-04** | **100-Capture Spot Latency** | Ray-Ban Gen 2 + Phone | **UNVERIFIED** (Physical) / **VERIFIED** (Emulated) | 100 consecutive synthetic frames processed within 800ms budget in benchmark tests. Real hardware wireless latency unverified without physical device kit. |
| **HW-05** | **CameraX Phone Fallback** | Pixel 8 Phone | **VERIFIED** | Phone-only operation with 640x480 YUV frames and IMU-derived angular speed equivalent for head movement gating (FR2.008 / TC2.165). |
| **HW-06** | **Audio Earcons & Phrases** | Ray-Ban Gen 2 | **UNVERIFIED** (Physical) / **VERIFIED** (Phone Fallback) | 16-bit PCM earcons and TTS synthesized cleanly through Android phone audio output; temple speakers unverified without physical hardware. |


