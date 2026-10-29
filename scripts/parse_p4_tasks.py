import json
import re
from pathlib import Path

ROOT = Path("<repo>")
SPEC = ROOT / "Plan" / "scmtips-field-spec.html"
OUT = ROOT / "docs" / "reports" / "phase4_tasks.json"

with open(SPEC, encoding="utf-8") as f:
    text = f.read()

tasks = []

# Scan for all T4.001 through T4.075
for i in range(1, 100):
    t_id = f"T4.{i:03d}"
    needle = f'id="id-{t_id}"'
    pos = text.find(needle)
    if pos == -1:
        continue
    end_pos = text.find('</tr>', pos)
    row_html = text[pos:end_pos]

    # Extract data-ws and data-role
    ws_m = re.search(r'data-ws="([^"]+)"', row_html)
    role_m = re.search(r'data-role="([^"]+)"', row_html)
    ws = ws_m.group(1) if ws_m else ""
    role = role_m.group(1) if role_m else ""

    # Split td elements
    td_matches = re.findall(r'<td[^>]*>([\s\S]*?)</td>', row_html)
    if len(td_matches) >= 6:
        # td 0: id
        # td 1: ws
        # td 2: title + desc
        # td 3: role
        # td 4: days
        # td 5: deliverables
        # td 6: done when
        title_desc = td_matches[2]
        title_m = re.search(r'<b>([\s\S]*?)</b>', title_desc)
        desc_m = re.search(r'<span class="muted">([\s\S]*?)</span>', title_desc)
        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ""
        desc = re.sub(r'<[^>]+>', '', desc_m.group(1)).strip() if desc_m else ""

        effort = re.sub(r'<[^>]+>', '', td_matches[4]).strip()
        deliverables = re.sub(r'<[^>]+>', '', td_matches[5]).strip()
        acceptance = re.sub(r'<[^>]+>', '', td_matches[6]).strip() if len(td_matches) > 6 else ""

        tasks.append({
            "id": t_id,
            "ws": ws,
            "title": title,
            "desc": desc,
            "role": role,
            "effort": effort,
            "deliverables": deliverables,
            "acceptance": acceptance,
        })

print(f"Extracted {len(tasks)} tasks.")
if tasks:
    print(f"First: {tasks[0]['id']} - {tasks[0]['title']} ({tasks[0]['ws']})")
    print(f"Last: {tasks[-1]['id']} - {tasks[-1]['title']} ({tasks[-1]['ws']})")
    with open(OUT, "w", encoding="utf-8") as out_f:
        json.dump(tasks, out_f, indent=2)
    print(f"Saved to {OUT}")
