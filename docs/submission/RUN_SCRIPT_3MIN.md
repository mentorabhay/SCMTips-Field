# The 3-minute run: spoken script (draft for the owner, plan items M17, M19)

Matches section 1 of the hackathon plan (beats 1 to 7) and the demo run (`docs/DEMO_RUN.md`, whose beats 4 to 6 are
the machine side of plan beats 1, 2, 4 and 6). About 400 words at about 140 words a minute. Every screen shows
SAMPLE data, and the disruption is a SIMULATED scenario file: keep the SAMPLE banner and the SIMULATED labels in
frame.

**Before recording:** run `scripts/dev/demo-run.ps1 <core>` once. It resets both sides, and its beats 4 to 6 are
then already done, so the screens are ready. For a live take, run it, stop after beat 3 (prepared), and do beats 4
to 6 on camera. Today only the scripted path (Python smokes) is proven. The glasses take needs plan item M14 first.

| Time | Plan beat | On screen | Spoken |
|---|---|---|---|
| 0:00 to 0:15 | intro | the core's dashboard with the SAMPLE banner | "This is a drone maker's plant. SAMPLE data, made up. It already runs a market-intelligence feed, a planning system, a PMO tool, an ERP and a shop floor. SCMTIPS doesn't replace them. It connects them, and its field app closes the loop on the shop floor, through Ray-Ban Meta glasses." |
| 0:15 to 0:35 | 1 | `/signals`: the magnet-curbs signal, labelled SIMULATED | "A disruption arrives: export licence checks on rare-earth magnets. In this video it comes from a simulated signals file, through the same contract a live feed would use." |
| 0:35 to 0:55 | 2 | `/exposure`: CP-204 brushless motor -> SA-120 -> FG-100, FG-200; the starvation clock (CP-206 about 87 days, CP-204 about 129 days) | "Only events that touch our own suppliers and parts become decisions. This one hits supplier S-02's motors, and through them every drone model. The clock shows when each plant runs short." |
| 0:55 to 1:10 | 3 | the planning system's own screen in file mode, labelled SIMULATED (only if recorded; otherwise cut and give this time to beat 4) | "The constraints go to the planning system as a planning-request workbook, today in file mode." |
| 1:10 to 1:50 | 4 | glasses POV: the approver hears the brief; the phone shows the card; then `/decisions/<id>` (EXECUTING, audit entry) | "The approver gets a twenty-second brief on the glasses. Before it is spoken, the core checks every number in it against its own results." (pause for the brief) "Approve option two." (read-back) "Confirm." "The core commits the plan, and the audit chain records who approved, how, and the step-up waiver of this demo mode." |
| 1:50 to 2:05 | 5 | the PMO tool's and the shop floor's own screens, file mode, labelled SIMULATED (only if recorded) | "The recovery tasks and the shop-floor orders go out the same way, and progress comes back." |
| 2:05 to 2:40 | 6 | warehouse: glasses POV of the receive job, the phone's count; then erp-sim's material document; then `/data/open-supply` (PO-26-1002 received) and `/data/inventory` (CP-204 1680 -> 3280) | "The expedited motors arrive. The operator looks at the delivery and confirms the count by voice. The app posts the goods receipt to the ERP. A signed message tells the core, the purchase order closes, stock rises, and the core re-plans on that physical evidence." |
| 2:40 to 2:55 | 7 | `/data/systems`: Connected systems, then one link switched to file mode | "Every system has a live mode and a file mode on the same contract. Switch one to file, and the run keeps going." |
| 2:55 to 3:00 | close | the Field repository page | "SCMTIPS Field is open source. Everything you saw is in the repository, with its tests." |

Words to avoid, because they are not proven: "real customer", "in production", "the clock resets", "the glasses
read the label", "Muse wrote this brief". Only say the last one if a run with the Meta key shows `source: model`.
Only say "on the glasses" for a take that really used them.

Fallbacks, if a live part fails on the day (see `SHOT_LIST.md`):

- beat 4: the core's phone approval page (`/decisions/<id>`). The HUD simulator is not built.
- beat 6: the receive job on the phone with the phone camera, or erp-sim's document page after the scripted run.
- beats 3 and 5: drop them and lengthen beats 4 and 6.
