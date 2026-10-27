import re

html = open("Plan/scmtips-field-prototype.html", encoding="utf-8").read()
print("Total length:", len(html))

# Find title and headers
titles = re.findall(r"<title>(.*?)</title>", html, re.I)
print("Title:", titles)

# Find screen or panel IDs
ids = re.findall(r'id=["\']([a-zA-Z0-9_\-]+)["\']', html)
screen_ids = [i for i in ids if any(k in i.lower() for k in ["screen", "scr", "view", "panel", "tab", "device", "console", "phone", "glass"])]
print(f"Found {len(screen_ids)} screen-related IDs:")
print(screen_ids[:50])

# Find buttons or nav links
navs = re.findall(r'<button[^>]*onclick=["\']([^"\']+)["\'][^>]*>(.*?)</button>', html, re.I)
print(f"Found {len(navs)} interactive buttons:")
for action, label in navs[:20]:
    clean_label = re.sub(r"<[^>]+>", "", label).strip()
    print(f"  {clean_label} -> {action}")
