"""End-to-End Application Simulation & Comprehensive Screenshot Generator.

Automates:
1. Generation of dev JWT tokens with full supervisor/admin permissions.
2. Launch of headless Chromium browser via Playwright.
3. Injection of authentication session into localStorage.
4. Navigation and high-resolution rendering of every Console screen across Phases 1-4.
5. Navigation and rendering of simulated Mobile Phone and Smart Glasses Wearable HUDs in the interactive companion prototype.
6. Saving PNG screenshots to docs/screenshots/ and mirroring to the artifacts directory.
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

from field_api.auth.jwt import create_dev_token
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = ROOT / "docs" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

ARTIFACT_DIR = Path("<home>/.gemini/antigravity/brain/0edb3cb2-fb9c-4e1e-ab66-265563e8b9d7")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

TENANT_ID = "e8eb2a80-d529-4bdd-b669-d21fe847cb74"
SITE_1_ID = "018f4a10-0001-7000-8000-000000000001"
MODEL_ID = "018f4a10-0004-7000-8000-000000000004"
TASK_ID = "018f4a10-0005-7000-8000-000000000005"

# Create token with full permissions
TOKEN = create_dev_token(
    principal_id="supervisor-lead-01",
    tenant_id=TENANT_ID,
    roles=["field.technician", "field.supervisor", "field.lead", "supervisor", "technician", "lead"],
    site_ids=["*"],
)


def run_simulation_and_capture() -> None:
    print("=" * 70)
    print("Starting SCMTIPS Field End-to-End Simulation & Screenshot Capture")
    print(f"Output directory: {SCREENSHOTS_DIR}")
    print(f"Artifact directory: {ARTIFACT_DIR}")
    print("=" * 70)

    captured_files = []

    with sync_playwright() as p:
        print("\nLaunching headless Chromium (msedge channel)...")
        browser = p.chromium.launch(channel="msedge", headless=True)

        # ----------------------------------------------------------------------
        # Part A: Web Console Desktop Screens (1920x1080)
        # ----------------------------------------------------------------------
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1.0,
        )
        page = context.new_page()
        page.set_default_navigation_timeout(60000)
        page.set_default_timeout(60000)

        # Set localStorage token before loading
        page.goto("http://localhost:3000/", timeout=60000)
        page.evaluate(
            """([token, tid]) => {
                localStorage.setItem("token", token);
                localStorage.setItem("tenant_id", tid);
                localStorage.setItem("auth_token", token);
            }""",
            [TOKEN, TENANT_ID],
        )

        console_screens = [
            ("01_console_dashboard_home.png", "http://localhost:3000/", "Dashboard & Operations Mission Control (SCR1.01)"),
            ("02_console_site_explorer.png", "http://localhost:3000/sites", "Site & Tower Catalog Explorer (SCR4.08)"),
            ("03_console_tower_hierarchy_tree.png", f"http://localhost:3000/sites/{SITE_1_ID}/towers", "Structure Hierarchy & Position Detail Panel (SCR4.08)"),
            ("04_console_3d_site_lattice_graph.png", f"http://localhost:3000/sites/{SITE_1_ID}/graph", "3D Site Lattice Graph & Serial Trail Replay (SCR4.08 / SCR4.12)"),
            ("05_console_audit_progress_board.png", "http://localhost:3000/audits", "Live Audit Progress Board & Completeness (SCR4.09)"),
            ("06_console_audit_task_details.png", f"http://localhost:3000/audits/{TASK_ID}", "Audit Session Findings & Location Reconciliation (SCR4.09)"),
            ("07_console_mismatch_decision_queue.png", "http://localhost:3000/mismatches", "Mismatch Exception Queue & Side-by-Side Verification (SCR4.10)"),
            ("08_console_climb_safe_lone_worker.png", "http://localhost:3000/safety", "Climb-Safe Velocity Guard & Lone-Worker Safety (SCR4.11)"),
            ("09_console_3d_model_exploded_view.png", f"http://localhost:3000/models/{MODEL_ID}", "Asset 3D glTF Model Viewer & Exploded Slider Stage (SCR4.09)"),
            ("10_console_warehouse_documents.png", "http://localhost:3000/documents", "Inbound Warehouse PO & ASN Receipts (SCR2.03)"),
            ("11_console_warehouse_stock.png", "http://localhost:3000/stock", "Inventory Stock & Materials Master (SCR2.01)"),
            ("12_console_warehouse_bins_locations.png", "http://localhost:3000/locations", "Storage Bins & Warehouse Locations (SCR3.01)"),
            ("13_console_posting_queues_jobs.png", "http://localhost:3000/jobs", "Per-Tower Equipment Posting Queue & ERP Jobs (SCR2.02)"),
            ("14_console_system_status.png", "http://localhost:3000/status", "System Status & Distributed Queue Telemetry (SCR3.02)"),
            ("15_console_connected_devices.png", "http://localhost:3000/devices", "Wearable Smart Glasses & Phone Fleet (SCR1.02)"),
            ("16_console_live_camera_captures.png", "http://localhost:3000/captures", "Live Camera Frames & OCR Ingestion Stream (SCR1.03)"),
        ]

        def save_screenshot(img_bytes: bytes, filename: str, label: str) -> None:
            out_path = SCREENSHOTS_DIR / filename
            for _attempt in range(5):
                try:
                    if out_path.exists():
                        with contextlib.suppress(Exception):
                            out_path.unlink()
                    out_path.write_bytes(img_bytes)
                    break
                except Exception:
                    time.sleep(0.3)

            artifact_copy = ARTIFACT_DIR / filename
            for _attempt in range(5):
                try:
                    if artifact_copy.exists():
                        with contextlib.suppress(Exception):
                            artifact_copy.unlink()
                    artifact_copy.write_bytes(img_bytes)
                    break
                except Exception:
                    time.sleep(0.3)

            captured_files.append((filename, label, str(out_path), str(artifact_copy)))
            print(f"  [SAVED] {filename} ({round(len(img_bytes) / 1024, 1)} KB)")

        print("\n--- Capturing Web Console Screens (Desktop 1920x1080) ---")
        for filename, url, label in console_screens:
            try:
                print(f"Loading {url} -> {filename} ({label})...")
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                # Extra pause for API data fetches, animations and 3D canvas rendering
                time.sleep(2.0)
                img = page.screenshot(full_page=False)
                save_screenshot(img, filename, label)
            except Exception as e:
                print(f"  [WARN] Failed to capture {url}: {e}")
                try:
                    img = page.screenshot()
                    save_screenshot(img, filename, label)
                except Exception:
                    pass

        # ----------------------------------------------------------------------
        # Part B: Interactive Control Room Prototype & Mobile/Wearable Simulations
        # ----------------------------------------------------------------------
        print("\n--- Capturing Interactive Field Simulation & Wearable Stages ---")
        proto_url = f"file:///{ROOT.as_posix()}/Plan/scmtips-field-prototype.html"

        # 1. Desktop control room view of prototype
        page.goto(proto_url, wait_until="load")
        time.sleep(1.0)

        proto_sections = [
            ("17_simulation_control_room_hero.png", "#hero", "Field Operations Control Room & Core Use Cases Overview"),
            ("18_simulation_first_person_pov_glasses_lens.png", "#pov", "First-Person Operator POV (Smart Glasses Lens HUD + Phone Display)"),
            ("19_simulation_voice_grammar_engine.png", "#voice", "Voice Grammar State Machine & Real-Time Audio Transcription"),
            ("20_simulation_spatial_3d_stage.png", "#spatial", "Spatial 3D Site Navigation & Tower Structure Map"),
            ("21_simulation_3d_exploded_cad_stage.png", "#explode", "Interactive 3D CAD Exploded Stage with Balloon Annotations"),
            ("22_simulation_architecture_outbox.png", "#arch", "Distributed Outbox Architecture & Core P13/P14 Seams"),
        ]

        for filename, selector, label in proto_sections:
            try:
                elem = page.locator(selector)
                if elem.count() > 0:
                    elem.scroll_into_view_if_needed()
                    time.sleep(0.8)
                    img = elem.screenshot()
                else:
                    img = page.screenshot()
                save_screenshot(img, filename, label)
            except Exception as e:
                print(f"  [WARN] Failed on section {selector}: {e}")

        # 2. Mobile Phone Viewport Simulation (412x915 - Pixel 7 Pro)
        print("\n--- Capturing Mobile Phone Viewport Simulation (412x915) ---")
        phone_context = browser.new_context(
            viewport={"width": 412, "height": 915},
            is_mobile=True,
            has_touch=True,
            device_scale_factor=2.0,
        )
        phone_page = phone_context.new_page()

        # Phone on prototype POV
        phone_page.goto(proto_url)
        time.sleep(1.0)
        phone_img = phone_page.screenshot()
        save_screenshot(phone_img, "23_simulation_mobile_phone_viewport.png", "Technician Mobile Phone Interface (Site Check-In & FL Barcode)")

        # Phone on Console Site Explorer
        phone_page.goto(f"http://localhost:3000/sites/{SITE_1_ID}/towers")
        time.sleep(2.0)
        phone_tower_img = phone_page.screenshot()
        save_screenshot(phone_tower_img, "24_mobile_tower_explorer_responsive.png", "Mobile Responsive Tower Explorer (Field Technician View)")

        # 3. Smart Glasses HUD Viewport (1280x720 16:9 AR display)
        print("\n--- Capturing Smart Glasses HUD Viewport Simulation (1280x720) ---")
        hud_context = browser.new_context(viewport={"width": 1280, "height": 720})
        hud_page = hud_context.new_page()
        hud_page.goto(proto_url)
        hud_elem = hud_page.locator("#pov")
        if hud_elem.count() > 0:
            hud_elem.scroll_into_view_if_needed()
            time.sleep(1.0)
            hud_img = hud_elem.screenshot()
            save_screenshot(hud_img, "25_smart_glasses_lens_hud_reticle.png", "Smart Glasses Lens Augmented Reality Reticle & Speedometer HUD")

        browser.close()

    print("\n" + "=" * 70)
    print(f"SUCCESS: Generated {len(captured_files)} end-to-end simulation screenshots!")
    print("=" * 70)

    # Write summary index markdown
    index_md = ROOT / "docs" / "screenshots" / "README.md"
    lines = [
        "# SCMTIPS Field — End-to-End Screen Simulation Gallery",
        "",
        f"**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}  ",
        f"**Total Screens Captured**: {len(captured_files)}  ",
        "**Browser Channel**: Headless Chromium (msedge)  ",
        "",
        "---",
        "",
        "## Screen Inventory",
        "",
        "| ID | Filename | Description | Resolution |",
        "| :--- | :--- | :--- | :---: |",
    ]
    for idx, (fn, label, _path, _) in enumerate(captured_files, 1):
        res = "1920x1080" if "console" in fn else "412x915" if "mobile" in fn else "1280x720"
        lines.append(f"| {idx:02d} | `{fn}` | {label} | {res} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    for idx, (fn, label, _path, _) in enumerate(captured_files, 1):
        lines.append(f"### {idx:02d}. {label} (`{fn}`)")
        lines.append(f"![{label}]({fn})")
        lines.append("")

    index_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"Gallery Index written to {index_md}")


if __name__ == "__main__":
    run_simulation_and_capture()
