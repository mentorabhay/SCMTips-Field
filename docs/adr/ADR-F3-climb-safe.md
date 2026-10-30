# ADR-F3: Climb-Safe Mode, Hands-Free Distraction Gate & Lone-Worker Safety Architecture

**Status**: Proposed — **not signed** (corrected 2026-10-30, C2 audit: no safety review or sign-off has taken place)  
**Date**: 2026-10-28  
**Scope**: SCMTIPS Field Android, Smart Glasses HUD, API & Lone-Worker Console (Phase 4 / WS4.5)  
**Safety Review Authority**: Tenant Safety Officer (EHS Committee) & Principal Systems Architect  

---

## 1. Context and Problem Statement

Technicians servicing telecommunication tower infrastructure operate in hazardous vertical environments (heights exceeding 60 meters). Cognitive distraction, hands-off-ladder requirements, and lone-worker medical emergencies present critical life-safety hazards.

The mobile and smart-glasses field application must enforce rigorous, fail-safe digital mechanisms to:
1. Prevent visual, audio, or haptic distractions while a technician is actively ascending, descending, or in an unconfirmed vertical motion state.
2. Prevent bypass of PPE harness attachment when performing equipment scanning or staging tasks on the structure.
3. Provide robust lone-worker countdown timers with non-intrusive deferred warnings during climbs and prompt supervisor escalation.

---

## 2. Core Architectural Decisions

### 2.1 Sensor Fusion and Fail-Safe Classification (`FR4.038`)
- Fuses vertical gravity-aligned accelerometer and barometric altitude at 25 Hz.
- Classifies technician state into `GROUND`, `CLIMBING`, `STATIONARY`, or `UNKNOWN`.
- **Fail-Safe Heuristic**: Any state ambiguity or sensor data gap $> 1.0$ s immediately defaults to `UNKNOWN`, which is treated identically to `CLIMBING`. Under no circumstances may an unconfirmed state be classified as stationary.

### 2.2 Distraction-Free Prompt Gate (`FR4.039` / `PR4.04`)
- All audio cues, smart glasses lens card popups, and haptic buzzes pass through a unified `PromptGate`.
- While state is `CLIMBING` or `UNKNOWN`, zero prompts are emitted. Prompts are held in a bounded FIFO queue.
- Prompts are released ONLY after the technician has remained continuously `STATIONARY` for at least 3.0 seconds.
- Upon release, at most the 3 newest prompts are delivered; older held prompts are discarded with an aggregated summary notice (`MSG4.25`).

### 2.3 Dual-Factor Harness Confirmation (`FR4.040`, `FR4.041` / `PR4.05`)
- Equipment scanning and BOM checklist staging on structure are blocked until harness clipping is confirmed.
- Requires two independent actions within a 10.0-second sliding window:
  1. Spoken verbal phrase `"harness clipped"` (confidence $\ge 0.80$).
  2. Physical button tap on smart glasses touchpad or phone side button.
- Confirmation is immediately revoked upon any detected climb motion or vertical altitude displacement $> 1.5$ meters.

### 2.4 Lone-Worker Timer & Deferred Warnings (`FR4.043`, `FR4.044` / `PR4.19`)
- Runs a 20-minute countdown timer (configurable 10–60 min per tenant policy).
- Timer is restarted on demand via verbal `"check in"` or touch tap.
- 2-minute pre-expiry warning is deferred if the technician is climbing, emitting at the first stationary window.
- If interval + 5-minute grace period elapses without check-in, the system escalates:
  - Transitions site visit to `escalated`.
  - Emits `field.visit.escalated` outbox event.
  - Broadcasts high-priority push notification and supervisor console banner (`SCR4.13`) with site, tower, last recorded altitude, and last check-in timestamp.

---

## 3. Legal and Regulatory Safety Disclaimer

> [!CAUTION]
> **SAFETY SYSTEM BOUNDARY NOTICE**  
> SCMTIPS Field software mechanisms (Climb-Safe Mode, Prompt Gate, Harness Dual Confirmation, and Lone-Worker Heartbeat Monitoring) are designed strictly as secondary digital supplements to workplace safety procedures.  
> The software does NOT replace, supersede, or waive certified personal protective equipment (PPE), physical 100% tie-off fall arrest systems, manual work permits, climbing buddy protocols, or statutory Occupational Safety and Health Administration (OSHA) regulations.

---

## 4. Formal Sign-Off

- **Lead Safety Architect**: *not yet reviewed*
- **Tenant EHS Representative**: *not yet reviewed* (the earlier "Signed & Approved" line was not true and is withdrawn)
- **Open Items Log**: open — climb detection, prompt gating and the lone-worker timer are unit-tested in
  Kotlin only (apps/field-android/core-safety); nothing has run on a device, on a real climb, or been reviewed
  by a safety officer. Climb-safe features must not be relied on for worker safety until then.
