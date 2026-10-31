# Video shot list (draft for the owner, plan items M19, M20)

For the 3-minute script in `RUN_SCRIPT_3MIN.md`. The owner decides how to film the glasses (M19): the Meta AI app's
capture, or a second phone filming over his shoulder. Every core screen keeps the SAMPLE banner in frame. Every file-mode
screen and the disruption keep their SIMULATED label. Add an on-screen caption "SAMPLE data · SIMULATED
disruption" for the whole video.

Preparation: `scripts/dev/demo-run.ps1 <core>` (both sides reset and consistent; `docs/DEMO_RUN.md`). Screen capture:
OBS or similar at 1080p. Core web: `http://app.localhost:3100` (kit) or `<hosted URL>`. erp-sim:
`http://127.0.0.1:8002/_sim/ui`.

| # | Time | Length | Source | What is on screen | Caption / label | Fallback shot |
|---|---|---|---|---|---|---|
| 1 | 0:00 | 15 s | screen | the core's dashboard (`/home`), SAMPLE banner | "SAMPLE drone OEM" | a still of the same page |
| 2 | 0:15 | 20 s | screen | `/signals`: the magnet export-curbs signal (HIGH), its SIMULATED source | "SIMULATED disruption (file mode)" | the scenario's CSV opened next to the signal |
| 3 | 0:35 | 20 s | screen | `/exposure`: CP-204 -> SA-120 -> FG-100, FG-200; the starvation clock | - | the demo run's beat 4 lines (cascade and clock) |
| 4 | 0:55 | 15 s | screen (optional) | the planning system's screen, file mode | "file mode · SIMULATED" | cut; beat 4 gets the time |
| 5 | 1:10 | 15 s | glasses POV + voice | the approver in the office; the brief plays (audio) | "Ray-Ban Meta Gen 2" | phone screen recording of the approval card, audio from the phone |
| 6 | 1:25 | 15 s | glasses POV + phone | "approve option two", the read-back, "confirm"; the phone shows the card | - | the core's phone approval page (`/decisions/<id>`) on the phone |
| 7 | 1:40 | 10 s | screen | `/decisions/<id>`: EXECUTING; the audit entry (approver, voice, step-up waiver) | "audit chain" | `/settings/audit` |
| 8 | 1:50 | 15 s | screen (optional) | the PMO tool's and the shop floor's own screens, file mode | "file mode · SIMULATED" | cut; beat 6 gets the time |
| 9 | 2:05 | 15 s | glasses POV | the warehouse: the delivery of motors (labels from the site pack's `labels.csv`), the receive job | "warehouse, PLANT-GOA (SAMPLE)" | second phone filming the operator; or the phone's receive screen |
| 10 | 2:20 | 10 s | phone + screen | the count confirmed by voice; erp-sim's material document (GR 101 against PO-26-1002) | "ERP simulator (S/4-shaped)" | erp-sim's document page after the scripted run |
| 11 | 2:30 | 10 s | screen | `/data/open-supply` (PO-26-1002 received), `/data/inventory` (CP-204 1680 -> 3280), `/data/pipeline` (the two signed rows) | - | the demo run's beat 6 lines |
| 12 | 2:40 | 15 s | screen | `/data/systems`: Connected systems, one link switched from live to file | - | a still with the mode switch highlighted |
| 13 | 2:55 | 5 s | screen | the Field repository page | "open source" | the README |

Not available today, so do not plan a shot on it: the HUD simulator (F5, not built), a Muse-written brief (not yet
run with the key), and the glasses reading a label (UNVERIFIED in `docs/META_FIELD.md`). Shots 5, 6, 9 and 10 depend
on the owner's glasses session (plan item M14). Until it passes, use their fallback shots.
