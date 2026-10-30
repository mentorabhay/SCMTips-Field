"""Field-test stack for the owner's PC (Windows or Linux), one command.

    uv run python -m tools.dev_stack.stack up       # .env.local, DB roles, migrations, sample ERP data, services
    uv run python -m tools.dev_stack.stack pair     # demo site + QR code the phone app scans
    uv run python -m tools.dev_stack.stack status
    uv run python -m tools.dev_stack.stack down

Services (logs in var/log, pids in var/run):
  fake-core  :8001  dev identity provider (EdDSA tokens + JWKS); stands in for SCMTips core
  erp-sim    :8002  S/4-shaped OData simulator with SAMPLE master data
  field-api  :8000  bound to 0.0.0.0 so the phone on the same Wi-Fi can reach it
  field-worker      posts confirmed documents to erp-sim, imports inbound deliveries

Secrets (A-02): .env.local is created from .env.example on first run with freshly generated signing
keys. This tool never prints a secret value; it reports variable names only.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
ENV_LOCAL = ROOT / ".env.local"
ENV_EXAMPLE = ROOT / ".env.example"
RUN = ROOT / "var" / "run"
LOG = ROOT / "var" / "log"
STATE = ROOT / "var" / "dev_stack.json"
GENERATED_SECRETS = ("FIELD_JWT_SECRET", "FIELD_CURSOR_HMAC_SECRET", "FIELD_P13F_WEBHOOK_SECRET", "FIELD_EVIDENCE_SECRET")
PAIRING_ROLES = ("field.operator", "field.supervisor")
SAMPLE_PLANT = "1010"


def parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def ensure_env_local(example: Path = ENV_EXAMPLE, target: Path = ENV_LOCAL) -> list[str]:
    """Create/complete .env.local: copy the example, fill empty signing keys. Returns names filled."""
    lines = (target if target.exists() else example).read_text(encoding="utf-8").splitlines()
    filled: list[str] = []
    out: list[str] = []
    for line in lines:
        k, sep, v = line.partition("=")
        if sep and k.strip() in GENERATED_SECRETS and not v.strip():
            line = f"{k.strip()}={secrets.token_hex(32)}"
            filled.append(k.strip())
        out.append(line)
    present = {ln.partition("=")[0].strip() for ln in out}
    for name in GENERATED_SECRETS:
        if name not in present:
            out.append(f"{name}={secrets.token_hex(32)}")
            filled.append(name)
    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    return filled


def load_env() -> dict[str, str]:
    env = parse_env(ENV_LOCAL.read_text(encoding="utf-8")) if ENV_LOCAL.exists() else {}
    os.environ.update({k: v for k, v in env.items() if v})
    return env


def lan_ip() -> str:
    """The address other devices on this Wi-Fi use to reach this PC (no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return str(s.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def pairing_payload(api_url: str, core_token: str, tenant_id: str, site_id: str, site_name: str) -> str:
    """JSON the phone app scans (apps/field-android PairingPayload must accept exactly this)."""
    return json.dumps(
        {"v": 1, "api": api_url.rstrip("/"), "token": core_token, "tenant": tenant_id, "site": site_id,
         "site_name": site_name},
        separators=(",", ":"),
    )


# --- database -------------------------------------------------------------------------------------

def _admin_url(db: str) -> str:
    base = os.environ.get("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
    return base.rsplit("/", 1)[0] + "/" + db


def ensure_database() -> None:
    import psycopg

    try:
        psycopg.connect(_admin_url("postgres"), connect_timeout=5).close()
    except psycopg.OperationalError as e:
        raise SystemExit(
            "PostgreSQL is not reachable with FIELD_ADMIN_DATABASE_URL from .env.local.\n"
            "Start it (e.g. `docker compose -f docker-compose.dev.yml up -d postgres`) and make the\n"
            f"password in .env.local match the server. ({type(e).__name__})"
        ) from None
    with psycopg.connect(_admin_url("postgres"), autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT datname FROM pg_database WHERE datname IN ('field', 'erpsim')")
        have = {r[0] for r in cur.fetchall()}
        for db in ("field", "erpsim"):
            if db not in have:
                cur.execute(f"CREATE DATABASE {db}")
        for role in ("field_migrator", "field_app", "field_worker"):
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if cur.fetchone() is None:
                extra = "CREATEDB" if role == "field_migrator" else "NOSUPERUSER NOCREATEDB NOBYPASSRLS"
                cur.execute(f"CREATE ROLE {role} WITH LOGIN PASSWORD 'devpassword' {extra}")
    with psycopg.connect(_admin_url("field"), autocommit=True) as c, c.cursor() as cur:
        cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; CREATE EXTENSION IF NOT EXISTS pgcrypto;'
                    " CREATE SCHEMA IF NOT EXISTS field;"
                    " GRANT USAGE ON SCHEMA field TO field_app, field_worker;"
                    " ALTER DEFAULT PRIVILEGES IN SCHEMA field GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO field_app, field_worker;"
                    " ALTER DEFAULT PRIVILEGES IN SCHEMA field GRANT USAGE, SELECT ON SEQUENCES TO field_app, field_worker;")
    with psycopg.connect(_admin_url("erpsim"), autocommit=True) as c, c.cursor() as cur:
        cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; CREATE EXTENSION IF NOT EXISTS pgcrypto;'
                    " CREATE SCHEMA IF NOT EXISTS erpsim;")


def migrate() -> None:
    env = {**os.environ, "FIELD_DATABASE_URL": _admin_url("field"), "ERPSIM_DATABASE_URL": _admin_url("erpsim")}
    for svc in ("field-api", "erp-sim"):
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT / "services" / svc,
                       env=env, check=True)


def seed_erp_sim() -> None:
    import psycopg

    with psycopg.connect(_admin_url("erpsim")) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM erpsim.material")
        row = cur.fetchone()
    if row and row[0] > 0:
        return
    env = {**os.environ, "ERPSIM_DATABASE_URL": _admin_url("erpsim")}
    subprocess.run([sys.executable, "-m", "erp_sim.seed"], cwd=ROOT, env=env, check=True)


# --- processes ------------------------------------------------------------------------------------

def services(host_ip: str) -> dict[str, list[str]]:
    py = sys.executable
    return {
        "fake-core": [py, "-m", "uvicorn", "fake_core.app:app", "--host", "127.0.0.1", "--port", "8001"],
        "erp-sim": [py, "-m", "uvicorn", "erp_sim.app:app", "--host", "127.0.0.1", "--port", "8002"],
        "field-api": [py, "-m", "uvicorn", "field_api.app:app", "--host", host_ip, "--port", "8000"],
        "field-worker": [py, "-m", "field_worker"],
    }


def _pidfile(name: str) -> Path:
    return RUN / f"{name}.pid"


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start(name: str, cmd: list[str]) -> int:
    RUN.mkdir(parents=True, exist_ok=True)
    LOG.mkdir(parents=True, exist_ok=True)
    pf = _pidfile(name)
    if pf.exists() and _alive(int(pf.read_text())):
        return int(pf.read_text())
    log = (LOG / f"{name}.log").open("ab")
    kw: dict[str, Any] = {"cwd": ROOT, "stdout": log, "stderr": subprocess.STDOUT, "env": dict(os.environ)}
    if os.name == "nt":
        kw["creationflags"] = 0x00000200 | 0x00000008  # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS (Windows)
    else:
        kw["start_new_session"] = True
    p = subprocess.Popen(cmd, **kw)
    pf.write_text(str(p.pid))
    return p.pid


def stop(name: str) -> bool:
    pf = _pidfile(name)
    if not pf.exists():
        return False
    pid = int(pf.read_text())
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        with contextlib.suppress(OSError):
            os.killpg(pid, signal.SIGTERM)
    pf.unlink(missing_ok=True)
    return True


def wait_http(url: str, timeout_s: float = 30) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


# --- commands -------------------------------------------------------------------------------------

def cmd_up(a: argparse.Namespace) -> int:
    filled = ensure_env_local()
    if filled:
        print(f"generated in .env.local: {', '.join(filled)}")
    load_env()
    ensure_database()
    migrate()
    seed_erp_sim()
    bind = "127.0.0.1" if a.local_only else "0.0.0.0"
    for name, cmd in services(bind).items():
        print(f"{name}: pid {start(name, cmd)}")
    ok = {
        "fake-core": wait_http("http://127.0.0.1:8001/.well-known/jwks.json"),
        "erp-sim": wait_http("http://127.0.0.1:8002/_sim/health"),
        "field-api": wait_http("http://127.0.0.1:8000/v1/health"),
    }
    for k, v in ok.items():
        print(f"{k}: {'up' if v else 'NOT RESPONDING - see var/log/' + k + '.log'}")
    if all(ok.values()):
        print(f"\nPhone URL: http://{lan_ip()}:8000   next: `uv run python -m tools.dev_stack.stack pair`")
    return 0 if all(ok.values()) else 1


def cmd_down(_a: argparse.Namespace) -> int:
    for name in reversed(list(services("127.0.0.1"))):
        print(f"{name}: {'stopped' if stop(name) else 'not running'}")
    return 0


def cmd_status(_a: argparse.Namespace) -> int:
    for name in services("127.0.0.1"):
        pf = _pidfile(name)
        alive = pf.exists() and _alive(int(pf.read_text()))
        print(f"{name}: {'running' if alive else 'stopped'}")
    return 0


def _core_token(principal: str, tenant: str, site: str, ttl_s: int) -> str:
    r = httpx.post("http://127.0.0.1:8001/api/v1/auth/token", json={
        "principal_id": principal, "tenant_id": tenant, "roles": list(PAIRING_ROLES), "site_ids": [site],
        "ttl_seconds": ttl_s,
    }, timeout=5)
    r.raise_for_status()
    return str(r.json()["access_token"])


def _field_token(core_token: str) -> str:
    r = httpx.post("http://127.0.0.1:8000/v1/auth/exchange", json={"device_token": core_token}, timeout=5)
    r.raise_for_status()
    return str(r.json()["access_token"])


def ensure_demo_site(state: dict[str, Any]) -> dict[str, Any]:
    """One tenant + one warehouse site on the SAMPLE plant, created through the real API."""
    if state.get("tenant") and state.get("site"):
        return state
    tenant = state.get("tenant") or str(uuid.uuid4())
    admin_core = httpx.post("http://127.0.0.1:8001/api/v1/auth/token", json={
        "principal_id": "dev-admin", "tenant_id": tenant, "roles": ["field.admin"], "ttl_seconds": 600,
    }, timeout=5).raise_for_status().json()["access_token"]
    admin = _field_token(admin_core)
    r = httpx.post("http://127.0.0.1:8000/v1/sites", json={
        "code": "SAMPLE-WH-01", "name": "SAMPLE warehouse (field test)", "kind": "warehouse",
        "erp_plant": SAMPLE_PLANT, "erp_storage_locations": ["101A"],
    }, headers={"Authorization": f"Bearer {admin}", "Idempotency-Key": str(uuid.uuid4())}, timeout=10)
    if r.status_code != 201:
        raise SystemExit(f"could not create the demo site: HTTP {r.status_code} {r.text[:300]}")
    state.update({"tenant": tenant, "site": r.json()["id"], "site_name": r.json()["name"]})
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def cmd_pair(a: argparse.Namespace) -> int:
    load_env()
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    state = ensure_demo_site(state)
    token = _core_token(a.user, state["tenant"], state["site"], a.hours * 3600)
    api = a.api or f"http://{lan_ip()}:8000"
    payload = pairing_payload(api, token, state["tenant"], state["site"], state["site_name"])
    import qrcode

    qr = qrcode.QRCode(border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    from qrcode.image.svg import SvgPathImage

    png = ROOT / "var" / "pairing-qr.svg"
    with png.open("wb") as fh:
        qr.make_image(image_factory=SvgPathImage).save(fh)
    if not a.no_ascii:
        qr.print_ascii(invert=True)
    print(f"\nScan this in the app (Settings > Pair with PC). Also saved as {png.relative_to(ROOT)} (open it in a browser).")
    print(f"API {api} | site {state['site_name']} | user {a.user} | valid {a.hours} h")
    print("The QR holds a dev login token for this PC's fake-core only; it stops working when fake-core restarts.")
    return 0


def create_inbound_delivery(lines: int = 3, plant: str = SAMPLE_PLANT, sloc: str = "101A") -> str:
    """A fresh open inbound delivery in erp-sim (stands in for a supplier ASN), with SAMPLE materials."""
    import psycopg

    with psycopg.connect(_admin_url("erpsim"), autocommit=True) as c, c.cursor() as cur:
        # Time-based so it never collides with seeded or earlier numbers (erp-sim resets reuse 180000001+)
        deliv = None
        for _ in range(20):
            cand = f"18{int(time.time() * 10) % 10**8:08d}"
            cur.execute("SELECT 1 FROM erpsim.inbound_delivery WHERE delivery_document = %s", (cand,))
            if cur.fetchone() is None:
                deliv = cand
                break
            time.sleep(0.1)
        if deliv is None:
            raise SystemExit("could not allocate a free delivery number")
        cur.execute("SELECT material_no FROM erpsim.material ORDER BY random() LIMIT %s", (lines,))
        mats = [r[0] for r in cur.fetchall()]
        if not mats:
            raise SystemExit("erp-sim has no materials; run `stack up` first")
        cur.execute("INSERT INTO erpsim.inbound_delivery (client, delivery_document, plant, storage_location, status)"
                    " VALUES ('100', %s, %s, %s, 'open')", (deliv, plant, sloc))
        for i, mat in enumerate(mats, start=1):
            cur.execute(
                "INSERT INTO erpsim.inbound_delivery_item (client, delivery_document, item_no, material_no, delivery_qty,"
                " actual_qty, uom, status) VALUES ('100', %s, %s, %s, %s, 0, 'EA', 'open')",
                (deliv, f"{i * 10:06d}", mat, 2 + secrets.randbelow(23)),
            )
    return deliv


def cmd_delivery(a: argparse.Namespace) -> int:
    load_env()
    print(f"inbound delivery {create_inbound_delivery(a.lines)} created; field-worker imports it within FIELD_IBD_POLL_S")
    return 0


class Phone:
    """The HTTP calls the phone app makes, in order (used by `smoke` to prove the backend path)."""

    def __init__(self, api: str, core_token: str) -> None:
        self.api = api.rstrip("/")
        self.core_token = core_token
        self.token = ""
        self.device_id = ""

    def _h(self, idem: bool = False) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self.token}"}
        if idem:
            h["Idempotency-Key"] = str(uuid.uuid4())
        return h

    def exchange(self, device_id: str | None = None) -> None:
        body: dict[str, Any] = {"device_token": self.core_token}
        if device_id:
            body["device_id"] = device_id
        r = httpx.post(f"{self.api}/v1/auth/exchange", json=body, timeout=10)
        r.raise_for_status()
        self.token = r.json()["access_token"]

    def register(self, serial: str) -> str:
        r = httpx.post(f"{self.api}/v1/devices", json={"kind": "phone", "serial_no": serial, "model": "smoke"},
                       headers=self._h(True), timeout=10)
        r.raise_for_status()
        self.device_id = r.json()["id"]
        return self.device_id

    def tasks(self, site: str) -> list[dict[str, Any]]:
        r = httpx.get(f"{self.api}/v1/tasks", params={"site_id": site, "type": "receive"}, headers=self._h(), timeout=10)
        r.raise_for_status()
        return list(r.json()["items"])

    def voice(self, task_id: str, intent: str, transcript: str, conf: float = 0.93) -> str:
        r = httpx.post(f"{self.api}/v1/voice-events", json={
            "device_id": self.device_id, "task_id": task_id, "transcript": transcript, "confidence": conf,
            "intent": intent, "is_accepted": True,
        }, headers=self._h(True), timeout=10)
        r.raise_for_status()
        return str(r.json()["id"])

    def count(self, line: dict[str, Any], qty: float, voice_id: str) -> None:
        r = httpx.post(f"{self.api}/v1/count-records", json={
            "task_line_id": line["id"], "value": qty, "unit": line.get("uom") or "EA", "voice_event_id": voice_id,
        }, headers=self._h(True), timeout=10)
        r.raise_for_status()

    def post(self, task_id: str, lines: list[tuple[str, float]], post_id: str, confirm_id: str) -> dict[str, Any]:
        import hashlib

        staged = hashlib.sha256("|".join(sorted(f"{lid}:{q:.3f}" for lid, q in lines)).encode()).hexdigest()
        r = httpx.post(f"{self.api}/v1/tasks/{task_id}/post-requests", json={
            "lines": [lid for lid, _ in lines], "staged_hash": staged,
            "post_voice_event_id": post_id, "confirm_voice_event_id": confirm_id,
        }, headers=self._h(True), timeout=10)
        if r.status_code != 202:
            raise SystemExit(f"post-request refused: HTTP {r.status_code} {r.text[:300]}")
        return dict(r.json())

    def ticks(self) -> list[dict[str, Any]]:
        r = httpx.get(f"{self.api}/v1/devices/{self.device_id}/events", params={"once": "true"},
                      headers=self._h(), timeout=10)
        r.raise_for_status()
        return [json.loads(ln[6:]) for ln in r.text.splitlines() if ln.startswith("data: ")]


def cmd_smoke(a: argparse.Namespace) -> int:
    """Receive one inbound delivery by 'voice' exactly as the app does, and wait for the ERP posting."""
    load_env()
    state = ensure_demo_site(json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {})
    phone = Phone(a.api or "http://127.0.0.1:8000", _core_token("smoke-op", state["tenant"], state["site"], 900))
    phone.exchange()
    phone.register(f"smoke-{uuid.uuid4().hex[:8]}")
    phone.exchange(phone.device_id)
    print(f"1 paired: device {phone.device_id}")
    deliv = create_inbound_delivery(2)
    print(f"  new inbound delivery {deliv} in erp-sim")
    deadline = time.monotonic() + a.wait
    tasks: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        tasks = [t for t in phone.tasks(state["site"]) if t.get("erp_ref") == deliv and t.get("lines")]
        if tasks:
            break
        time.sleep(2)
    if not tasks:
        print("FAIL: no receive task appeared; is field-worker running (var/log/field-worker.log)?")
        return 1
    task = tasks[0]
    print(f"2 task {task["erp_ref"]} with {len(task['lines'])} lines")
    staged: list[tuple[str, float]] = []
    for ln in task["lines"]:
        qty = float(ln.get("expected_qty") or 1)
        phone.count(ln, qty, phone.voice(task["id"], "count", f"count {int(qty)}"))
        staged.append((ln["id"], qty))
    post_id = phone.voice(task["id"], "post", "post")
    confirm_id = phone.voice(task["id"], "confirm", "confirm")
    out = phone.post(task["id"], staged, post_id, confirm_id)
    print(f"3 post requested: {out['posting_request_id']} ({out['queue_key']})")
    while time.monotonic() < deadline:
        for t in phone.ticks():
            if t.get("kind") == "erp.posted" or t.get("tick_type") == "erp.posted":
                data = t.get("payload") or t
                print(f"4 PASS: ERP material document {data.get('doc_number')} / {data.get('fiscal_year')}")
                return 0
            if t.get("kind") == "erp.failed" or t.get("tick_type") == "erp.failed":
                print(f"FAIL: posting failed: {t}")
                return 1
        time.sleep(2)
    print("FAIL: no erp.posted tick before the deadline")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stack")
    sub = ap.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("up")
    up.add_argument("--local-only", action="store_true", help="bind field-api to 127.0.0.1 (no phone access)")
    sub.add_parser("down")
    sub.add_parser("status")
    pr = sub.add_parser("pair")
    pr.add_argument("--user", default="op-1")
    pr.add_argument("--hours", type=int, default=12)
    pr.add_argument("--api", help="override the URL the phone uses (e.g. a tunnel URL)")
    pr.add_argument("--no-ascii", action="store_true")
    dl = sub.add_parser("delivery")
    dl.add_argument("--lines", type=int, default=3)
    sm = sub.add_parser("smoke")
    sm.add_argument("--api")
    sm.add_argument("--wait", type=float, default=90)
    a = ap.parse_args(argv)
    return {"up": cmd_up, "down": cmd_down, "status": cmd_status, "pair": cmd_pair, "smoke": cmd_smoke,
            "delivery": cmd_delivery}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
