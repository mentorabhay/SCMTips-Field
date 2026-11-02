"""Generate erp-sim tower fixtures (Task T4.009 / FR4.005 / TC4.101-TC4.103).

Seeds 3 SAMPLE sites (IN01-TWR-0042, IN01-TWR-0057, IN01-TWR-0103) with:
- 2 towers, 3 sectors, 4 levels per tower
- 1 shelter, 2 racks, 2 slots per shelter
- 48 installed equipment records with 3 deliberate mismatches.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT1 = ROOT / "services/erp-sim/src/erp_sim/fixtures/towers.json"
OUT2 = ROOT / "services/erp-sim/fixtures/towers.json"

SITES_CONFIG = [
    {
        "code": "IN01-TWR-0042",
        "name": "SAMPLE Tower Site 0042 - North Ridge",
        "plant": "1010",
        "lat": 12.9716,
        "lon": 77.5946,
        "radius_m": 150,
    },
    {
        "code": "IN01-TWR-0057",
        "name": "SAMPLE Tower Site 0057 - South Valley",
        "plant": "1010",
        "lat": 12.9352,
        "lon": 77.6245,
        "radius_m": 150,
    },
    {
        "code": "IN01-TWR-0103",
        "name": "SAMPLE Tower Site 0103 - West Hills",
        "plant": "1010",
        "lat": 12.9850,
        "lon": 77.5350,
        "radius_m": 150,
    },
]

# Generate Functional Locations
functional_locations = []
equipment_list = []
eq_id_counter = 10001001

for _site_idx, site in enumerate(SITES_CONFIG):
    s_code = site["code"]
    # Site Root
    functional_locations.append({
        "FunctionalLocation": s_code,
        "SuperiorFunctionalLocation": "",
        "FunctionalLocationName": site["name"],
        "MaintenancePlant": site["plant"],
        "Kind": "tower_site",
        "LastChangeDateTime": "2026-10-01T08:00:00Z",
    })

    # Shelter Branch
    sh_code = f"{s_code}-SH"
    functional_locations.append({
        "FunctionalLocation": sh_code,
        "SuperiorFunctionalLocation": s_code,
        "FunctionalLocationName": f"Equipment Shelter - {s_code}",
        "MaintenancePlant": site["plant"],
        "Kind": "shelter",
        "LastChangeDateTime": "2026-10-01T08:00:00Z",
    })

    # 2 Racks in Shelter
    for r_idx in ["R01", "R02"]:
        rack_code = f"{sh_code}-{r_idx}"
        functional_locations.append({
            "FunctionalLocation": rack_code,
            "SuperiorFunctionalLocation": sh_code,
            "FunctionalLocationName": f"Rack {r_idx}",
            "MaintenancePlant": site["plant"],
            "Kind": "rack",
            "LastChangeDateTime": "2026-10-01T08:00:00Z",
        })
        # 2 Slots in each rack
        for slot_idx in ["S01", "S02"]:
            slot_code = f"{rack_code}-{slot_idx}"
            functional_locations.append({
                "FunctionalLocation": slot_code,
                "SuperiorFunctionalLocation": rack_code,
                "FunctionalLocationName": f"Rack {r_idx} Slot {slot_idx}",
                "MaintenancePlant": site["plant"],
                "Kind": "rack_slot",
                "LastChangeDateTime": "2026-10-01T08:00:00Z",
            })
            # Add ground equipment (BBU or Rectifier)
            eq_no = str(eq_id_counter)
            eq_id_counter += 1
            equipment_list.append({
                "Equipment": eq_no,
                "SerialNumber": f"BBU-SN-{eq_no[-4:]}",
                "Material": "MAT-BBU-02",
                "ManufacturerPartNmbr": "HW-BBU-5900",
                "FunctionalLocation": slot_code,
                "EquipInstallationDate": "2026-01-15",
                "DeliberateMismatch": None,
            })

    # 2 Towers per site
    for t_idx in ["T01", "T02"]:
        t_code = f"{s_code}-{t_idx}"
        functional_locations.append({
            "FunctionalLocation": t_code,
            "SuperiorFunctionalLocation": s_code,
            "FunctionalLocationName": f"Tower {t_idx} - {s_code}",
            "MaintenancePlant": site["plant"],
            "Kind": "tower",
            "LastChangeDateTime": "2026-10-01T08:00:00Z",
        })

        # 3 Sectors per tower (SA, SB, SC)
        for s_char in ["SA", "SB", "SC"]:
            sec_code = f"{t_code}-{s_char}"
            functional_locations.append({
                "FunctionalLocation": sec_code,
                "SuperiorFunctionalLocation": t_code,
                "FunctionalLocationName": f"Sector {s_char[-1]}",
                "MaintenancePlant": site["plant"],
                "Kind": "sector",
                "SectorCode": s_char[-1],
                "LastChangeDateTime": "2026-10-01T08:00:00Z",
            })

            # 4 Levels per sector (L01: 10m, L02: 20m, L03: 30m, L04: 40m)
            for l_num, height in [("L01", 10.0), ("L02", 20.0), ("L03", 30.0), ("L04", 40.0)]:
                lvl_code = f"{sec_code}-{l_num}"
                functional_locations.append({
                    "FunctionalLocation": lvl_code,
                    "SuperiorFunctionalLocation": sec_code,
                    "FunctionalLocationName": f"Level {l_num[-2:]} ({height}m)",
                    "MaintenancePlant": site["plant"],
                    "Kind": "level",
                    "SectorCode": s_char[-1],
                    "HeightM": height,
                    "LastChangeDateTime": "2026-10-01T08:00:00Z",
                })

                # Positions on level: add equipment at select levels
                if l_num in ["L02", "L03"] and len(equipment_list) < 48:
                    pos_code = f"{lvl_code}-P01"
                    functional_locations.append({
                        "FunctionalLocation": pos_code,
                        "SuperiorFunctionalLocation": lvl_code,
                        "FunctionalLocationName": "Position P01",
                        "MaintenancePlant": site["plant"],
                        "Kind": "position",
                        "SectorCode": s_char[-1],
                        "HeightM": height,
                        "LastChangeDateTime": "2026-10-01T08:00:00Z",
                    })

                    eq_no = str(eq_id_counter)
                    eq_id_counter += 1

                    # Inject deliberate mismatches
                    mismatch = None
                    serial_num = f"RRU-SN-{eq_no[-4:]}"

                    # Deliberate mismatch 1: Serial mismatch on site 0042 (RRU-SN-7781-2201 vs physical)
                    if s_code == "IN01-TWR-0042" and sec_code.endswith("SB") and l_num == "L02":
                        eq_no = "10004567"
                        serial_num = "RRU-SN-7781-2201"
                        mismatch = {
                            "type": "serial_mismatch",
                            "expected_serial": "RRU-SN-7781-2201",
                            "actual_physical_serial": "RRU-SN-7781-9999",
                            "description": "ERP record has serial RRU-SN-7781-2201 but physical nameplate shows RRU-SN-7781-9999",
                        }

                    # Deliberate mismatch 2: Misplaced equipment on site 0042 (Sector A vs Sector C)
                    elif s_code == "IN01-TWR-0042" and sec_code.endswith("SA") and l_num == "L03":
                        mismatch = {
                            "type": "misplaced",
                            "expected_fl": pos_code,
                            "actual_physical_fl": f"{s_code}-T01-SC-L03-P01",
                            "description": "Equipment registered at Sector A Level 3 but physically mounted on Sector C",
                        }

                    # Deliberate mismatch 3: Missing equipment on site 0057
                    elif s_code == "IN01-TWR-0057" and sec_code.endswith("SC") and l_num == "L03":
                        mismatch = {
                            "type": "missing_equipment",
                            "expected_fl": pos_code,
                            "description": "Equipment registered in ERP but absent on the tower structure",
                        }

                    equipment_list.append({
                        "Equipment": eq_no,
                        "SerialNumber": serial_num,
                        "Material": "MAT-RRU-01",
                        "ManufacturerPartNmbr": "ERIC-RRU-4415",
                        "FunctionalLocation": pos_code,
                        "EquipInstallationDate": "2026-02-10",
                        "DeliberateMismatch": mismatch,
                    })

# Ensure exactly 48 equipment items
equipment_list = equipment_list[:48]

# Ensure exactly 3 deliberate mismatches
mismatch_count = 0
for eq in equipment_list:
    if eq.get("DeliberateMismatch"):
        if mismatch_count < 3:
            mismatch_count += 1
        else:
            eq["DeliberateMismatch"] = None

fixture_data = {
    "metadata": {
        "version": "1.0",
        "description": "SAMPLE tower fixtures for Phase 4 (IN01-TWR-0042, IN01-TWR-0057, IN01-TWR-0103)",
        "total_sites": len(SITES_CONFIG),
        "total_functional_locations": len(functional_locations),
        "total_equipment": len(equipment_list),
        "deliberate_mismatches_count": sum(1 for e in equipment_list if e.get("DeliberateMismatch")),
    },
    "sites": SITES_CONFIG,
    "functional_locations": functional_locations,
    "equipment": equipment_list,
}

for path in [OUT1, OUT2]:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fixture_data, f, indent=2)
    print(f"Wrote fixture to {path}")

print(f"Summary: {len(SITES_CONFIG)} sites, {len(functional_locations)} FLs, {len(equipment_list)} equipment, "
      f"{fixture_data['metadata']['deliberate_mismatches_count']} mismatches.")
