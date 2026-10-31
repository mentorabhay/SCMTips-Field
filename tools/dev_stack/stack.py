"""Field-test stack for the owner's PC (Windows or Linux), one command.

    uv run python -m tools.dev_stack.stack up       # .env.local, DB roles, migrations, sample ERP data, services
    uv run python -m tools.dev_stack.stack pair     # demo site + QR code the phone app scans
    uv run python -m tools.dev_stack.stack status
    uv run python -m tools.dev_stack.stack down
    uv run python -m tools.dev_stack.stack delivery   # inbound delivery -> receive task
    uv run python -m tools.dev_stack.stack outbound   # outbound delivery -> pick task
    uv run python -m tools.dev_stack.stack count [BIN]  # blind count task for a bin
    uv run python -m tools.dev_stack.stack tower      # SAMPLE-TWR-0001: sector A audit + swap task
    uv run python -m tools.dev_stack.stack smoke --all  # every job type over HTTP as the phone would
    uv run python -m tools.dev_stack.stack home [--simulate-differences]  # sandbox site "Home (sandbox)" (M3)
    uv run python -m tools.dev_stack.stack pair --home  # pair the phone to the home sandbox site
    uv run python -m tools.dev_stack.stack smoke --home # sandbox receipt + count end to end, production refusal
    uv run python -m tools.dev_stack.stack labels       # printable QR labels for every open job
    uv run python -m tools.dev_stack.stack assistant-check  # one real Field Assistant model call (track A's hook)

Services (logs in var/log, pids in var/run):
  fake-core  :8011  dev identity provider (EdDSA tokens + JWKS); stands in for SCMTips core
                    (not 8001: SCMTips core itself often runs there; FIELD_STACK_CORE_PORT overrides)
  erp-sim    :8002  S/4-shaped OData simulator with SAMPLE master data (FIELD_STACK_ERPSIM_PORT)
  field-api  :8000  bound to 0.0.0.0 so the phone on the same Wi-Fi can reach it (FIELD_STACK_API_PORT)

The stack owns these ports: before starting it checks that each is free (or already ours), and a
service only counts as up when its own process is alive AND its port answers. (On the owner's PC
another program held 8001; fake-core died on bind while the health probe got an answer from the
other program.)
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


PORTS = {"fake-core": ("FIELD_STACK_CORE_PORT", 8011), "erp-sim": ("FIELD_STACK_ERPSIM_PORT", 8002),
         "field-api": ("FIELD_STACK_API_PORT", 8000)}
HEALTH = {"fake-core": "/.well-known/jwks.json", "erp-sim": "/_sim/health", "field-api": "/v1/health"}


PORTS_FILE = ROOT / "var" / "dev_stack_ports.json"


def _chosen() -> dict[str, int]:
    try:
        return {k: int(v) for k, v in json.loads(PORTS_FILE.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        return {}


def port(name: str) -> int:
    """Explicit FIELD_STACK_*_PORT, else the port `up` chose last time, else the default."""
    var, default = PORTS[name]
    return int(os.environ.get(var) or _chosen().get(name) or default)


def owner_of_port(p: int) -> str:
    """Best effort 'pid N (program)' of whatever listens on 127.0.0.1:p (Windows netstat/tasklist)."""
    if os.name != "nt":
        return "another program"
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=10).stdout
        pid = next((ln.split()[-1] for ln in out.splitlines() if f":{p} " in ln and "LISTENING" in ln), None)
        if not pid:
            return "another program"
        img = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, timeout=10).stdout.split(",")[0].strip('"')
        return f"pid {pid} ({img or 'unknown'})"
    except (OSError, subprocess.SubprocessError):
        return "another program"


def choose_ports() -> dict[str, int]:
    """Pick each service's port before starting: keep ours if running, honour an explicit setting, else
    the default if free, else the next free one (owner's PC, 2026-10-31: 8001, later 8000, were taken).
    The choice is saved so pair/smoke/delivery and the phone's QR code use the same ports."""
    chosen: dict[str, int] = {}
    for name, (var, default) in PORTS.items():
        if os.environ.get(var) or running(name) is not None:
            chosen[name] = port(name)
            continue
        for cand in range(default, default + 40):
            if cand not in chosen.values() and not port_in_use(cand):
                if cand != default:
                    print(f"{name}: port {default} is used by {owner_of_port(default)}; using {cand}")
                chosen[name] = cand
                break
        else:
            raise SystemExit(f"FAIL: no free port for {name} in {default}-{default + 39}")
    PORTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PORTS_FILE.write_text(json.dumps(chosen, indent=2), encoding="utf-8")
    return chosen


def local(name: str) -> str:
    return f"http://127.0.0.1:{port(name)}"


def apply_ports() -> None:
    """The stack decides where its services listen, so it also tells every service where the others are."""
    os.environ["FIELD_CORE_JWKS_URL"] = f"{local('fake-core')}/.well-known/jwks.json"
    os.environ["FIELD_ERP_SIM_URL"] = local("erp-sim")


def port_in_use(p: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", p)) == 0


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
        "fake-core": [py, "-m", "uvicorn", "fake_core.app:app", "--host", "127.0.0.1", "--port", str(port("fake-core"))],
        "erp-sim": [py, "-m", "uvicorn", "erp_sim.app:app", "--host", "127.0.0.1", "--port", str(port("erp-sim"))],
        "field-api": [py, "-m", "uvicorn", "field_api.app:app", "--host", host_ip, "--port", str(port("field-api"))],
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


def running(name: str) -> int | None:
    pf = _pidfile(name)
    if pf.exists() and _alive(int(pf.read_text())):
        return int(pf.read_text())
    return None


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
    choose_ports()
    apply_ports()
    bind = "127.0.0.1" if a.local_only else "0.0.0.0"
    taken = [n for n in PORTS if running(n) is None and port_in_use(port(n))]
    if taken:  # only an explicit FIELD_STACK_*_PORT can still collide
        for n in taken:
            print(f"FAIL: port {port(n)} for {n} is used by {owner_of_port(port(n))}. Stop it, or set "
                  f"{PORTS[n][0]}=<free port> in .env.local and run again.")
        return 1
    ensure_database()
    migrate()
    seed_erp_sim()
    for name, cmd in services(bind).items():
        print(f"{name}: pid {start(name, cmd)}")
    ok = {n: wait_http(local(n) + HEALTH[n]) and running(n) is not None for n in HEALTH}
    for k, v in ok.items():
        print(f"{k} :{port(k)}: {'up' if v else 'NOT RUNNING - see var/log/' + k + '.log'}")
    if running("field-worker") is None:
        print("field-worker: NOT RUNNING - see var/log/field-worker.log")
        ok["field-worker"] = False
    if all(ok.values()):
        print(f"\nPhone URL: http://{lan_ip()}:{port('field-api')}   next: `uv run python -m tools.dev_stack.stack pair`")
    return 0 if all(ok.values()) else 1


STACK_PROCESS = r"fake_core\.app:app|erp_sim\.app:app|field_api\.app:app|-m field_worker"


def stop_leftovers() -> int:
    """Stop stack processes this tool lost track of (owner's PC, 2026-10-31: a field-api from an earlier
    run kept port 8000 after its pid file was gone). Matched by our own module names, which nothing
    else uses."""
    if os.name == "nt":
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | "
            f"Where-Object {{ $_.CommandLine -match '{STACK_PROCESS}' }} | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $_.ProcessId }"
        )
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout
    else:
        out = subprocess.run(["pkill", "-f", "-e", STACK_PROCESS.replace("\\", "")], capture_output=True, text=True).stdout
    return len([ln for ln in out.splitlines() if ln.strip()])


def cmd_down(_a: argparse.Namespace) -> int:
    for name in reversed(list(services("127.0.0.1"))):
        print(f"{name}: {'stopped' if stop(name) else 'not running'}")
    n = stop_leftovers()
    if n:
        print(f"stopped {n} leftover stack process(es) from earlier runs")
    return 0


def cmd_status(_a: argparse.Namespace) -> int:
    for name in services("127.0.0.1"):
        pf = _pidfile(name)
        alive = pf.exists() and _alive(int(pf.read_text()))
        print(f"{name}: {'running' if alive else 'stopped'}")
    return 0


def _core_token(principal: str, tenant: str, site: str, ttl_s: int) -> str:
    r = httpx.post(local("fake-core") + "/api/v1/auth/token", json={
        "principal_id": principal, "tenant_id": tenant, "roles": list(PAIRING_ROLES), "site_ids": [site],
        "ttl_seconds": ttl_s,
    }, timeout=5)
    r.raise_for_status()
    return str(r.json()["access_token"])


def _field_token(core_token: str) -> str:
    r = httpx.post(local("field-api") + "/v1/auth/exchange", json={"device_token": core_token}, timeout=5)
    r.raise_for_status()
    return str(r.json()["access_token"])


def site_exists(site_id: str) -> bool:
    import psycopg

    with psycopg.connect(_admin_url("field")) as c, c.cursor() as cur:
        cur.execute("SELECT 1 FROM field.site WHERE id::text = %s", (site_id,))
        return cur.fetchone() is not None


def ensure_demo_site(state: dict[str, Any]) -> dict[str, Any]:
    """One tenant + one warehouse site on the SAMPLE plant, created through the real API.

    A saved site is reused only if it still exists: a recreated database (new Postgres volume, a fresh
    machine) otherwise left var/dev_stack.json pointing at a site the worker never polls.
    """
    if state.get("tenant") and state.get("site") and site_exists(state["site"]):
        return state
    state = {k: v for k, v in state.items() if k not in ("site", "site_name")}
    tenant = state.get("tenant") or str(uuid.uuid4())
    admin_core = httpx.post(local("fake-core") + "/api/v1/auth/token", json={
        "principal_id": "dev-admin", "tenant_id": tenant, "roles": ["field.admin"], "ttl_seconds": 600,
    }, timeout=5).raise_for_status().json()["access_token"]
    admin = _field_token(admin_core)
    r = httpx.post(local("field-api") + "/v1/sites", json={
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
    apply_ports()
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    state = ensure_demo_site(state)
    site, site_name = state["site"], state["site_name"]
    home = bool(getattr(a, "home", False))
    if a.tower:
        state = ensure_tower_site(state)
        site, site_name = state["tower_site"], TOWER_SITE_NAME
    elif home:
        state = ensure_home(state)
        site, site_name = state["home_site"], HOME_SITE_NAME
    token = _core_token(a.user, state["tenant"], site, a.hours * 3600)
    api = a.api or f"http://{lan_ip()}:{port('field-api')}"
    payload = pairing_payload(api, token, state["tenant"], site, site_name)
    import qrcode

    qr = qrcode.QRCode(border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    from qrcode.image.svg import SvgPathImage

    png = ROOT / "var" / ("pairing-qr-tower.svg" if a.tower else "pairing-qr-home.svg" if home else "pairing-qr.svg")
    png.parent.mkdir(parents=True, exist_ok=True)
    with png.open("wb") as fh:
        qr.make_image(image_factory=SvgPathImage).save(fh)
    if not a.no_ascii:
        try:
            qr.print_ascii(invert=True)
        except UnicodeEncodeError:
            # Owner's PC, 2026-10-31: the Windows console code page (cp1252) has no block characters.
            print("(This console cannot draw the QR code; use the image that opens now.)")
    if sys.platform == "win32" and not a.no_open:
        with contextlib.suppress(OSError):
            os.startfile(png)  # show the QR in the default image viewer / browser
    print(f"\nScan it in the app: SCMTips Field > Scan pairing QR. Image: {png} (open it in a browser).")
    print(f"API {api} | site {site_name} | user {a.user} | valid {a.hours} h")
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
        cur.execute("SELECT material_no FROM erpsim.material WHERE material_no LIKE 'SAMPLE-MAT-%%'"
                    " ORDER BY random() LIMIT %s", (lines,))
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
    apply_ports()
    print(f"inbound delivery {create_inbound_delivery(a.lines)} created; field-worker imports it within FIELD_IBD_POLL_S")
    return 0


class Phone:
    """The HTTP calls the phone app makes, in order (used by `smoke` to prove the backend path).

    Every call is the real field-api over HTTP with the device's own field token, as the app makes it.
    """

    def __init__(self, api: str, core_token: str) -> None:
        self.api = api.rstrip("/")
        self.core_token = core_token
        self.token = ""
        self.device_id = ""
        self._seen: set[str] = set()

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

    def pair(self, serial: str) -> Phone:
        self.exchange()
        self.register(serial)
        self.exchange(self.device_id)
        return self

    def tasks(self, site: str, type_: str | None = None, status: str | None = "open,in_progress") -> list[dict[str, Any]]:
        """GET /v1/tasks?site_id=&status=open,in_progress, as the app sends it (type filtered here)."""
        params = {"site_id": site, "limit": "200"}
        if status:
            params["status"] = status
        items: list[dict[str, Any]] = []
        cursor = None
        while True:
            if cursor:
                params["cursor"] = cursor
            r = httpx.get(f"{self.api}/v1/tasks", params=params, headers=self._h(), timeout=10)
            r.raise_for_status()
            items += [t for t in r.json()["items"] if type_ is None or t["type"] == type_]
            cursor = r.json().get("next_cursor")
            if not cursor:
                return items

    def task(self, site: str, type_: str, task_id: str) -> dict[str, Any] | None:
        return next((t for t in self.tasks(site, type_, status=None) if t["id"] == task_id), None)

    def voice(self, task_id: str, intent: str, transcript: str, conf: float = 0.93) -> str:
        r = httpx.post(f"{self.api}/v1/voice-events", json={
            "device_id": self.device_id, "task_id": task_id, "transcript": transcript, "confidence": conf,
            "intent": intent, "is_accepted": True,
        }, headers=self._h(True), timeout=10)
        r.raise_for_status()
        return str(r.json()["id"])

    def count(self, line: dict[str, Any], qty: float, voice_id: str | None = None) -> httpx.Response:
        body: dict[str, Any] = {"task_line_id": line["id"], "value": qty, "unit": line.get("uom") or "EA",
                                "source": "voice" if voice_id else "manual"}
        if voice_id:
            body["voice_event_id"] = voice_id
        return httpx.post(f"{self.api}/v1/count-records", json=body, headers=self._h(True), timeout=10)

    def confirm(self, task_id: str, line_id: str, kind: str, code: str, role: str | None = None,
                reason: str | None = None) -> httpx.Response:
        body: dict[str, Any] = {"kind": kind, "code": code, "source": "scan"}
        if role:
            body["role"] = role
        if reason:
            body["reason"] = reason
        return httpx.post(f"{self.api}/v1/tasks/{task_id}/lines/{line_id}/confirmations", json=body,
                          headers=self._h(True), timeout=10)

    def flag(self, task_id: str, line_id: str, flag: str, reason: str | None = None) -> httpx.Response:
        return httpx.post(f"{self.api}/v1/tasks/{task_id}/lines/{line_id}/flags",
                          json={"flag": flag, "reason": reason}, headers=self._h(True), timeout=10)

    @staticmethod
    def staged_hash(lines: list[tuple[str, float]]) -> str:
        import hashlib

        return hashlib.sha256("|".join(sorted(f"{lid}:{q:.3f}" for lid, q in lines)).encode()).hexdigest()

    def finish(self, task_id: str, lines: list[tuple[str, float]], post_id: str | None = None,
               confirm_id: str | None = None) -> httpx.Response:
        """POST post-requests exactly as the app sends it. Voice: the turn ids both inside ``confirm`` and
        at the top level; touch ("Yes, post it"): ``confirm: {method: touch}`` only."""
        body: dict[str, Any] = {"operation": "post", "lines": [lid for lid, _ in lines],
                                "staged_hash": self.staged_hash(lines)}
        if post_id and confirm_id:
            body["confirm"] = {"method": "voice", "post_voice_event_id": post_id, "confirm_voice_event_id": confirm_id}
            body.update(post_voice_event_id=post_id, confirm_voice_event_id=confirm_id)
        else:
            body["confirm"] = {"method": "touch"}
        return httpx.post(f"{self.api}/v1/tasks/{task_id}/post-requests", json=body, headers=self._h(True), timeout=15)

    @staticmethod
    def listed(task: dict[str, Any]) -> list[tuple[str, float]]:
        """The app's staged lines for scanned jobs (putaway / audit / swap): the counted_qty the list reported, 0 if absent."""
        return [(ln["id"], float(ln.get("counted_qty") or 0)) for ln in task["lines"]]

    @staticmethod
    def counted(resp: httpx.Response, sent: float) -> float:
        """The app's hash quantity after a count: picked_qty, else counted_qty, else the value sent."""
        body = resp.json()
        return float(body.get("picked_qty", body.get("counted_qty", sent)))

    def post(self, task_id: str, lines: list[tuple[str, float]], post_id: str, confirm_id: str) -> dict[str, Any]:
        """Pre-M2 shape (top-level voice turn ids), still accepted by the API."""
        r = httpx.post(f"{self.api}/v1/tasks/{task_id}/post-requests", json={
            "lines": [lid for lid, _ in lines], "staged_hash": self.staged_hash(lines),
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

    def wait_event(self, kinds: tuple[str, ...], task_id: str | None, timeout_s: float,
                   pred: Any = None) -> dict[str, Any]:
        """The next live event of one of ``kinds`` for ``task_id`` (or matching ``pred``); erp.failed ends the wait."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for t in self.ticks():
                if t["id"] in self._seen:
                    continue
                payload = t.get("payload") or {}
                if (pred(payload) if pred else payload.get("task_id")) != (True if pred else task_id):
                    continue
                self._seen.add(t["id"])
                if t.get("kind") in kinds or t.get("kind") == "erp.failed":
                    return {"kind": t.get("kind"), **payload}
            time.sleep(1)
        raise SmokeFailure(f"no {'/'.join(kinds)} event for task {task_id} within {timeout_s:.0f} s")


class Console:
    """The supervisor console's calls (dev sign-in: fake-core supervisor token, exchanged)."""

    def __init__(self, api: str, tenant: str, principal: str = "smoke-sup") -> None:
        self.api = api.rstrip("/")
        r = httpx.post(local("fake-core") + "/api/v1/auth/token", json={
            "principal_id": principal, "tenant_id": tenant, "roles": ["field.supervisor"], "site_ids": ["*"],
            "ttl_seconds": 1800}, timeout=5)
        r.raise_for_status()
        self.token = _field_token(str(r.json()["access_token"]))

    def _h(self, idem: bool = False) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self.token}"}
        if idem:
            h["Idempotency-Key"] = str(uuid.uuid4())
        return h

    def get(self, path: str, **params: str) -> Any:
        r = httpx.get(f"{self.api}{path}", params=params, headers=self._h(), timeout=10)
        if r.status_code != 200:
            raise SmokeFailure(f"GET {path}: HTTP {r.status_code} {r.text[:300]}")
        return r.json()

    def post(self, path: str, body: dict[str, Any] | None = None) -> httpx.Response:
        return httpx.post(f"{self.api}{path}", json=body or {}, headers=self._h(True), timeout=10)


class SmokeFailure(Exception):
    pass


def _expect(cond: bool, what: str) -> None:
    if not cond:
        raise SmokeFailure(what)


# --- erp-sim reads (the SAP side of every check) ----------------------------------------------------

def erp_document(doc: str, year: str) -> dict[str, Any]:
    r = httpx.get(local("erp-sim") + "/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/"
                  f"A_MaterialDocumentHeader(MaterialDocument='{doc}',MaterialDocumentYear='{year}')",
                  params={"$expand": "to_MaterialDocumentItem"}, headers={"sap-client": "100"}, timeout=10)
    if r.status_code != 200:
        raise SmokeFailure(f"erp-sim has no material document {doc}/{year} (HTTP {r.status_code})")
    return dict(r.json()["d"])


def erp_movements(doc: str, year: str) -> list[tuple[str, str, float]]:
    """[(material, movement type, quantity)] of a material document in erp-sim."""
    items = erp_document(doc, year).get("to_MaterialDocumentItem", {}).get("results", [])
    return [(i["Material"], i["GoodsMovementType"], float(i["QuantityInEntryUnit"])) for i in items]


def erp_equipment(serial: str) -> dict[str, Any] | None:
    r = httpx.get(local("erp-sim") + "/sap/opu/odata/sap/API_EQUIPMENT/A_Equipment",
                  params={"$filter": f"SerialNumber eq '{serial}'"}, headers={"sap-client": "100"}, timeout=10)
    r.raise_for_status()
    res = r.json()["d"]["results"]
    return dict(res[0]) if res else None


def erp_stock(material: str, plant: str = SAMPLE_PLANT, sloc: str = "101A") -> float:
    import psycopg

    with psycopg.connect(_admin_url("erpsim")) as c, c.cursor() as cur:
        cur.execute("SELECT quantity FROM erpsim.stock WHERE client = '100' AND plant = %s AND storage_location = %s"
                    " AND material_no = %s", (plant, sloc, material))
        row = cur.fetchone()
        return float(row[0]) if row else 0.0


# --- SAMPLE warehouse: bin tree and opening bin stock ----------------------------------------------

BIN_TREE: dict[str, tuple[str, ...]] = {
    "02": ("02-01-01", "02-01-02", "02-02-01", "02-02-02", "02-03-04", "02-03-05"),
    "03": ("03-05-01", "03-05-02", "03-05-03", "03-06-01", "03-06-02", "03-07-01"),
}
# Opening balance: SAP IM stock of these materials sits in these bins (field side; SAP has no bins).
OPENING_STOCK = {"02-01-01": "SAMPLE-MAT-0001", "02-03-04": "SAMPLE-MAT-0002",
                 "03-05-01": "SAMPLE-MAT-0003", "03-05-02": "SAMPLE-MAT-0004"}


def _admin(tenant: str) -> str:
    r = httpx.post(local("fake-core") + "/api/v1/auth/token", json={
        "principal_id": "dev-admin", "tenant_id": tenant, "roles": ["field.admin"], "ttl_seconds": 600}, timeout=5)
    r.raise_for_status()
    return _field_token(str(r.json()["access_token"]))


def ensure_bin_tree(state: dict[str, Any]) -> int:
    """Zones 02 and 03 with their storage bins, created through POST /v1/locations. Returns bins created."""
    import psycopg

    with psycopg.connect(_admin_url("field")) as c, c.cursor() as cur:
        cur.execute("SELECT code, id FROM field.location WHERE site_id = %s", (state["site"],))
        have = {str(r[0]): str(r[1]) for r in cur.fetchall()}
    if all(b in have for bins in BIN_TREE.values() for b in bins):
        return 0
    token = _admin(state["tenant"])
    h = {"Authorization": f"Bearer {token}"}
    made = 0
    for zone, bins in BIN_TREE.items():
        if zone not in have:
            r = httpx.post(local("field-api") + "/v1/locations", json={
                "site_id": state["site"], "kind": "zone", "code": zone},
                headers={**h, "Idempotency-Key": str(uuid.uuid4())}, timeout=10)
            if r.status_code != 201:
                raise SystemExit(f"could not create zone {zone}: HTTP {r.status_code} {r.text[:200]}")
            have[zone] = r.json()["id"]
        for b in bins:
            if b in have:
                continue
            r = httpx.post(local("field-api") + "/v1/locations", json={
                "site_id": state["site"], "parent_id": have[zone], "kind": "position", "code": b,
                "erp_ref": f"{SAMPLE_PLANT}/101A/{b}", "erp_ref_type": "storage_bin"},
                headers={**h, "Idempotency-Key": str(uuid.uuid4())}, timeout=10)
            if r.status_code != 201:
                raise SystemExit(f"could not create bin {b}: HTTP {r.status_code} {r.text[:200]}")
            have[b] = r.json()["id"]
            made += 1
    return made


def seed_opening_stock(state: dict[str, Any]) -> int:
    """Once per site: the bins in OPENING_STOCK hold today's SAP stock of their material (dev seed)."""
    import psycopg

    with psycopg.connect(_admin_url("field")) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, true), set_config('app.site_ids', '*', true)",
                    (state["tenant"],))
        cur.execute("SELECT 1 FROM field.bin_stock WHERE site_id = %s LIMIT 1", (state["site"],))
        if cur.fetchone():
            return 0
        for b, mat in OPENING_STOCK.items():
            cur.execute("INSERT INTO field.bin_stock (tenant_id, site_id, storage_bin, material_no, quantity)"
                        " VALUES (%s, %s, %s, %s, %s)", (state["tenant"], state["site"], b, mat, erp_stock(mat)))
        c.commit()
    return len(OPENING_STOCK)


def ensure_warehouse(state: dict[str, Any]) -> dict[str, Any]:
    state = ensure_demo_site(state)
    ensure_bin_tree(state)
    seed_opening_stock(state)
    return state


def bins_with_stock(state: dict[str, Any]) -> list[tuple[str, str, float]]:
    """[(bin, material, qty)] the field holds for the SAMPLE site (not under an open count)."""
    import psycopg

    with psycopg.connect(_admin_url("field")) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, true), set_config('app.site_ids', '*', true)",
                    (state["tenant"],))
        cur.execute(
            """
            SELECT s.storage_bin, s.material_no, s.quantity FROM field.bin_stock s
             WHERE s.site_id = %s AND s.quantity > 0
               AND NOT EXISTS (SELECT 1 FROM field.pi_book b JOIN field.pi_document d ON d.id = b.pi_document_id
                                 JOIN field.task_line l ON l.id = b.task_line_id
                                WHERE d.status IN ('open', 'counted', 'recount') AND l.storage_bin = s.storage_bin)
             ORDER BY s.storage_bin, s.material_no
            """,
            (state["site"],),
        )
        return [(str(r[0]), str(r[1]), float(r[2])) for r in cur.fetchall()]


def _new_outbound_no(cur: Any) -> str:
    for _ in range(50):
        cand = f"80{int(time.time() * 10) % 10**8:08d}"
        cur.execute("SELECT 1 FROM erpsim.outbound_delivery WHERE delivery_document = %s", (cand,))
        if cur.fetchone() is None:
            return cand
        time.sleep(0.1)
    raise SystemExit("could not allocate a free delivery number")


def create_outbound_delivery(items: list[tuple[str, float]], plant: str = SAMPLE_PLANT, sloc: str = "101A") -> str:
    """A fresh open outbound delivery in erp-sim (stands in for a sales order's delivery)."""
    import psycopg

    with psycopg.connect(_admin_url("erpsim"), autocommit=True) as c, c.cursor() as cur:
        deliv = _new_outbound_no(cur)
        cur.execute("INSERT INTO erpsim.outbound_delivery (client, delivery_document, plant, storage_location, status,"
                    " header_data) VALUES ('100', %s, %s, %s, 'open', %s)",
                    (deliv, plant, sloc, json.dumps({"ShipTo": "SAMPLE-CUSTOMER-01"})))
        for i, (mat, qty) in enumerate(items, start=1):
            cur.execute("INSERT INTO erpsim.outbound_delivery_item (client, delivery_document, item_no, material_no,"
                        " delivery_qty, picked_qty, uom, status) VALUES ('100', %s, %s, %s, %s, 0, 'EA', 'open')",
                        (deliv, f"{i * 10:06d}", mat, qty))
    return deliv


def cmd_outbound(a: argparse.Namespace) -> int:
    load_env()
    apply_ports()
    state = ensure_warehouse(json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {})
    stock = bins_with_stock(state)[: a.lines]
    if not stock:
        print("FAIL: no bin of the SAMPLE site holds stock; receive and put away first")
        return 1
    deliv = create_outbound_delivery([(m, min(2.0, q)) for _b, m, q in stock])
    print(f"outbound delivery {deliv} created ({', '.join(f'{m} from {b}' for b, m, _q in stock)});"
          " field-worker imports it as a pick task within FIELD_IBD_POLL_S")
    return 0


def create_count_task(state: dict[str, Any], bin_: str | None = None) -> dict[str, Any]:
    """A count (field PI document) for every material in one bin, through POST /v1/pi-documents.

    The book snapshot is taken server-side from the field bin stock (never passes through a client).
    """
    stock = bins_with_stock(state)
    if bin_ is None:
        if not stock:
            raise SystemExit("no bin of the SAMPLE site holds stock")
        bin_ = stock[-1][0]
    mats = [m for b, m, _q in stock if b == bin_]
    if not mats:
        raise SystemExit(f"bin {bin_} holds nothing the field knows of (or is already being counted)")
    r = httpx.post(local("fake-core") + "/api/v1/auth/token", json={
        "principal_id": "dev-planner", "tenant_id": state["tenant"], "roles": ["inventory.controller"],
        "site_ids": [state["site"]], "ttl_seconds": 600}, timeout=5)
    r.raise_for_status()
    planner = _field_token(str(r.json()["access_token"]))
    r = httpx.post(local("field-api") + "/v1/pi-documents", json={
        "site_id": state["site"], "plant": SAMPLE_PLANT, "storage_location": "101A",
        "items": [{"bin": bin_, "material": m} for m in mats]},
        headers={"Authorization": f"Bearer {planner}", "Idempotency-Key": str(uuid.uuid4())}, timeout=10)
    if r.status_code != 201:
        raise SystemExit(f"could not create the count: HTTP {r.status_code} {r.text[:300]}")
    return {**r.json(), "bin": bin_, "materials": mats}


def cmd_count(a: argparse.Namespace) -> int:
    load_env()
    apply_ports()
    state = ensure_warehouse(json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {})
    out = create_count_task(state, a.bin)
    print(f"count task {out['task_id']} for bin {out['bin']} ({len(out['materials'])} item(s)), PI {out['doc_number']}")
    return 0


# --- SAMPLE tower ------------------------------------------------------------------------------------

TOWER_FL = "SAMPLE-TWR-0001"
TOWER_LAT, TOWER_LON = 12.9716, 77.5946
TOWER_SITE_NAME = "SAMPLE tower 0001 (field test)"
TOWER_SLOTS = (("A", "S1", 30.0), ("A", "S2", 32.0), ("A", "S3", 34.0), ("B", "S1", 30.0))


def ensure_erp_tower() -> dict[str, Any]:
    """In erp-sim: SAMPLE-TWR-0001 with sectors A and B, four slots, an RRU installed in each slot and one
    spare RRU in store (created when none is left). Idempotent; a swapped unit stays swapped."""
    import psycopg

    with psycopg.connect(_admin_url("erpsim"), autocommit=True) as c, c.cursor() as cur:
        def fl(code: str, name: str, parent: str | None, kind: str, sector: str | None, h: float | None) -> None:
            cur.execute(
                "INSERT INTO erpsim.functional_location (client, func_loc, description, superior_func_loc, kind,"
                " sector_code, height_m, plant) VALUES ('100', %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (client, func_loc) DO UPDATE SET description = EXCLUDED.description,"
                " superior_func_loc = EXCLUDED.superior_func_loc, kind = EXCLUDED.kind,"
                " sector_code = EXCLUDED.sector_code, height_m = EXCLUDED.height_m, plant = EXCLUDED.plant",
                (code, name, parent, kind, sector, h, SAMPLE_PLANT))

        def new_equipment(serial: str, floc: str | None) -> None:
            cur.execute("SELECT COALESCE(MAX(equipment_no::bigint), 19100000) + 1 FROM erpsim.equipment"
                        " WHERE equipment_no ~ '^191[0-9]{5}$'")
            row = cur.fetchone()
            no = str(row[0]) if row else "19100001"
            cur.execute("INSERT INTO erpsim.equipment (client, equipment_no, material_no, serial_no, func_loc, status)"
                        " VALUES ('100', %s, 'MAT-RRU-01', %s, %s, %s)",
                        (no, serial, floc, "installed" if floc else "available"))
            if floc:
                cur.execute("INSERT INTO erpsim.equipment_install (client, equipment_no, func_loc, action)"
                            " VALUES ('100', %s, %s, 'install')", (no, floc))

        fl(TOWER_FL, "SAMPLE tower 0001", None, "tower_site", None, None)
        for sector in sorted({s for s, _c, _h in TOWER_SLOTS}):
            fl(f"{TOWER_FL}-{sector}", f"Sector {sector}", TOWER_FL, "sector", sector, None)
        for sector, slot, h in TOWER_SLOTS:
            floc = f"{TOWER_FL}-{sector}-{slot}"
            fl(floc, f"Sector {sector} slot {slot[1:]}", f"{TOWER_FL}-{sector}", "rack_slot", sector, h)
            cur.execute("SELECT 1 FROM erpsim.equipment WHERE func_loc = %s", (floc,))
            if cur.fetchone() is None:
                new_equipment(f"RRU-SN-{uuid.uuid4().hex[:6].upper()}", floc)
        cur.execute("SELECT serial_no FROM erpsim.equipment WHERE func_loc IS NULL AND material_no = 'MAT-RRU-01'"
                    " AND equipment_no ~ '^191[0-9]{5}$' ORDER BY equipment_no LIMIT 1")
        row = cur.fetchone()
        if row is None:
            spare = f"RRU-SN-{uuid.uuid4().hex[:6].upper()}"
            new_equipment(spare, None)
        else:
            spare = str(row[0])
        cur.execute("SELECT func_loc, serial_no FROM erpsim.equipment WHERE func_loc LIKE %s ORDER BY func_loc",
                    (f"{TOWER_FL}-%",))
        installed = {str(r[0]): str(r[1]) for r in cur.fetchall()}
    return {"spare": spare, "installed": installed}


def parse_lat_lon(text: str) -> tuple[float, float]:
    """"12.9716, 77.5946" (as Google Maps copies it) -> (lat, lon); refuses anything off the globe."""
    parts = [p.strip() for p in text.replace(";", ",").split(",")]
    if len(parts) != 2:
        raise ValueError(f"expected 'LAT,LON', got {text!r}")
    lat, lon = float(parts[0]), float(parts[1])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"not a place on Earth: {lat}, {lon}")
    return lat, lon


def move_tower_site(state: dict[str, Any], lat: float, lon: float) -> None:
    """Dev only: put the SAMPLE tower where the tester stands, so the real geofence check passes there."""
    import psycopg

    with psycopg.connect(_admin_url("field"), autocommit=True) as c, c.cursor() as cur:
        cur.execute("UPDATE field.site SET lat = %s, lon = %s WHERE id = %s::uuid", (lat, lon, state["tower_site"]))
    state["tower_at"] = [lat, lon]
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def ensure_tower_site(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("tower_site") and site_exists(state["tower_site"]):
        return state
    token = _admin(state["tenant"])
    r = httpx.post(local("field-api") + "/v1/sites", json={
        "code": TOWER_FL, "name": TOWER_SITE_NAME, "kind": "tower",
        "lat": (state.get("tower_at") or [TOWER_LAT, TOWER_LON])[0],
        "lon": (state.get("tower_at") or [TOWER_LAT, TOWER_LON])[1], "geofence_radius_m": 150},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}, timeout=10)
    if r.status_code != 201:
        raise SystemExit(f"could not create the tower site: HTTP {r.status_code} {r.text[:300]}")
    state["tower_site"] = r.json()["id"]
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def create_tower_jobs(state: dict[str, Any]) -> dict[str, Any]:
    """erp-sim tower -> field installed base (read through the SAP readers) -> sector A audit + one swap."""
    from field_api.audit.generate import generate_audit_task
    from field_api.jobs.tower_tasks import create_swap_task
    from field_worker.tower.installed_base import sync_tower_installed_base

    erp = ensure_erp_tower()
    state = ensure_tower_site(state)
    worker_db = os.environ.get("FIELD_WORKER_DATABASE_URL", "postgresql://field_worker:devpassword@127.0.0.1:5450/field")
    synced = sync_tower_installed_base(state["tenant"], state["tower_site"], TOWER_FL, local("erp-sim"), worker_db)
    audit = generate_audit_task(state["tenant"], state["tower_site"], sector_code="A")
    swap_serial = erp["installed"][f"{TOWER_FL}-A-S3"]
    swap = create_swap_task(state["tenant"], state["tower_site"], swap_serial)
    return {"state": state, "synced": synced, "audit": audit, "swap": swap, "spare": erp["spare"],
            "installed": erp["installed"]}


def cmd_tower(a: argparse.Namespace) -> int:
    load_env()
    apply_ports()
    state = ensure_demo_site(json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {})
    out = create_tower_jobs(state)
    if a.at:
        lat, lon = parse_lat_lon(a.at)
        move_tower_site(out["state"], lat, lon)
        print(f"tower site moved to {lat:.6f}, {lon:.6f}: check in within 150 m of that point")
    print(f"tower {TOWER_FL}: {out['synced']['locations']} locations, {out['synced']['equipment']} units mirrored")
    print(f"audit task {out['audit']['id']} ({out['audit']['line_count']} units in sector A)")
    print(f"swap task {out['swap']['id']}: remove {out['swap']['expected_serial']} at {out['swap']['position']};"
          f" spare in store: {out['spare']}")
    return 0


# --- Home (sandbox) site, M3 contract section 3 -----------------------------------------------------

HOME_PLANT = "HOME"
HOME_SLOC = "HM01"
HOME_SITE_CODE = "HOME-SBX"
HOME_SITE_NAME = "Home (sandbox)"
HOME_BINS = ("HOME-A", "HOME-B")
# --simulate-differences: these SAMPLE materials get a simulated book stock of SIMULATED_QTY in HOME-A
SIMULATED_MATERIALS = ("SAMPLE-MAT-0005", "SAMPLE-MAT-0006")
SIMULATED_QTY = 10


def ensure_erp_home_plant() -> None:
    """Plant HOME with storage location HM01 in erp-sim (the ERP side of the home site). Idempotent."""
    import psycopg

    with psycopg.connect(_admin_url("erpsim"), autocommit=True) as c, c.cursor() as cur:
        cur.execute("INSERT INTO erpsim.plant (client, plant, name) VALUES ('100', %s, 'Home (sandbox)')"
                    " ON CONFLICT DO NOTHING", (HOME_PLANT,))
        cur.execute("INSERT INTO erpsim.storage_location (client, plant, storage_location, name)"
                    " VALUES ('100', %s, %s, 'Home shelf') ON CONFLICT DO NOTHING", (HOME_PLANT, HOME_SLOC))


def _site_by_code(tenant: str, code: str) -> str | None:
    import psycopg

    with psycopg.connect(_admin_url("field")) as c, c.cursor() as cur:
        cur.execute("SELECT id FROM field.site WHERE tenant_id = %s AND code = %s", (tenant, code))
        row = cur.fetchone()
        return str(row[0]) if row else None


def ensure_home_site(state: dict[str, Any]) -> dict[str, Any]:
    """The sandbox site "Home (sandbox)" on plant HOME, created by field.admin through the real API."""
    if state.get("home_site") and site_exists(state["home_site"]):
        return state
    site = _site_by_code(state["tenant"], HOME_SITE_CODE)
    if site is None:
        token = _admin(state["tenant"])
        r = httpx.post(local("field-api") + "/v1/sites", json={
            "code": HOME_SITE_CODE, "name": HOME_SITE_NAME, "kind": "warehouse", "erp_plant": HOME_PLANT,
            "erp_storage_locations": [HOME_SLOC], "mode": "sandbox"},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}, timeout=10)
        if r.status_code != 201:
            raise SystemExit(f"could not create the home site: HTTP {r.status_code} {r.text[:300]}")
        site = str(r.json()["id"])
    state["home_site"] = site
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def ensure_home_bins(state: dict[str, Any]) -> int:
    """Zone HOME with bins HOME-A and HOME-B through POST /v1/locations. Returns bins created."""
    import psycopg

    with psycopg.connect(_admin_url("field")) as c, c.cursor() as cur:
        cur.execute("SELECT code, id FROM field.location WHERE site_id = %s", (state["home_site"],))
        have = {str(r[0]): str(r[1]) for r in cur.fetchall()}
    if all(b in have for b in HOME_BINS):
        return 0
    h = {"Authorization": f"Bearer {_admin(state['tenant'])}"}
    if "HOME" not in have:
        r = httpx.post(local("field-api") + "/v1/locations", json={"site_id": state["home_site"], "kind": "zone",
                                                                   "code": "HOME"},
                       headers={**h, "Idempotency-Key": str(uuid.uuid4())}, timeout=10)
        if r.status_code != 201:
            raise SystemExit(f"could not create the home zone: HTTP {r.status_code} {r.text[:200]}")
        have["HOME"] = r.json()["id"]
    made = 0
    for b in HOME_BINS:
        if b in have:
            continue
        r = httpx.post(local("field-api") + "/v1/locations", json={
            "site_id": state["home_site"], "parent_id": have["HOME"], "kind": "position", "code": b,
            "erp_ref": f"{HOME_PLANT}/{HOME_SLOC}/{b}", "erp_ref_type": "storage_bin"},
            headers={**h, "Idempotency-Key": str(uuid.uuid4())}, timeout=10)
        if r.status_code != 201:
            raise SystemExit(f"could not create bin {b}: HTTP {r.status_code} {r.text[:200]}")
        made += 1
    return made


def ensure_home(state: dict[str, Any]) -> dict[str, Any]:
    """Tenant (demo site), plant HOME in erp-sim, the home sandbox site and its two bins."""
    state = ensure_demo_site(state)
    ensure_erp_home_plant()
    state = ensure_home_site(state)
    ensure_home_bins(state)
    return state


def _operator(state: dict[str, Any], site: str, principal: str = "dev-home") -> str:
    """A field operator token for one site (fake-core token, exchanged), for the stack's own API calls."""
    r = httpx.post(local("fake-core") + "/api/v1/auth/token", json={
        "principal_id": principal, "tenant_id": state["tenant"], "roles": ["field.operator"], "site_ids": [site],
        "ttl_seconds": 600}, timeout=5)
    r.raise_for_status()
    return _field_token(str(r.json()["access_token"]))


def _sandbox_post(token: str, path: str, body: dict[str, Any]) -> httpx.Response:
    return httpx.post(local("field-api") + path, json=body,
                      headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}, timeout=15)


def simulate_book_stock(state: dict[str, Any]) -> list[str]:
    """--simulate-differences (opt-in): SIMULATED_MATERIALS get a book stock in erp-sim (561 marked sandbox and
    simulated, through the simulator adapter) and the same quantity in field bin HOME-A, once per site."""
    import asyncio

    import psycopg
    from field_sap.ports.erp_port import ErpPostingRequest
    from field_sap.sim.adapter import SimAdapter

    with psycopg.connect(_admin_url("field")) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, true), set_config('app.site_ids', '*', true)",
                    (state["tenant"],))
        cur.execute("SELECT material_no FROM field.bin_stock WHERE site_id = %s AND storage_bin = 'HOME-A'",
                    (state["home_site"],))
        have = {str(r[0]) for r in cur.fetchall()}
        todo = [m for m in SIMULATED_MATERIALS if m not in have]
        if todo:
            asyncio.run(SimAdapter(base_url=local("erp-sim")).post_initial_stock_entry(ErpPostingRequest(
                idempotency_key=f"stack-home-simulated:{state['home_site']}", doc_family="InitialStockEntry",
                site_id=state["home_site"], plant=HOME_PLANT, posting_date=time.strftime("%Y-%m-%d"),
                header_data={"StorageLocation": HOME_SLOC, "Sandbox": True, "Simulated": True},
                items=tuple({"Material": m, "QuantityInEntryUnit": f"{SIMULATED_QTY}.000", "EntryUnit": "EA"}
                            for m in todo))))
            for m in todo:
                cur.execute("INSERT INTO field.bin_stock (tenant_id, site_id, storage_bin, material_no, quantity)"
                            " VALUES (%s, %s, 'HOME-A', %s, %s)", (state["tenant"], state["home_site"], m, SIMULATED_QTY))
        c.commit()
    return list(SIMULATED_MATERIALS)


def create_home_jobs(state: dict[str, Any], simulate: bool = False) -> dict[str, Any]:
    """One empty home receipt and one count task for HOME-A, through the sandbox API as the operator."""
    token = _operator(state, state["home_site"])
    r = _sandbox_post(token, "/v1/sandbox/receipts", {"site_id": state["home_site"]})
    if r.status_code != 201:
        raise SystemExit(f"could not create the home receipt: HTTP {r.status_code} {r.text[:300]}")
    receipt = r.json()
    r = _sandbox_post(token, "/v1/sandbox/counts", {"site_id": state["home_site"], "bin": "HOME-A",
                                                     "simulated": simulate})
    if r.status_code != 201:
        raise SystemExit(f"could not create the home count: HTTP {r.status_code} {r.text[:300]}")
    count = r.json()
    simulated: list[str] = []
    if simulate:
        simulated = simulate_book_stock(state)
        for m in simulated:
            r = _sandbox_post(token, f"/v1/sandbox/tasks/{count['task_id']}/items", {"code": m, "description": m})
            if r.status_code != 201:
                raise SystemExit(f"could not add {m} to the count: HTTP {r.status_code} {r.text[:300]}")
    return {"receipt": receipt, "count": count, "simulated": simulated}


def cmd_home(a: argparse.Namespace) -> int:
    load_env()
    apply_ports()
    state = ensure_home(json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {})
    jobs = create_home_jobs(state, a.simulate_differences)
    print(f"site {HOME_SITE_NAME!r} ({state['home_site']}), mode sandbox, plant {HOME_PLANT}, bins {', '.join(HOME_BINS)}")
    print(f"home receipt: delivery {jobs['receipt']['ref_doc_no']} (task {jobs['receipt']['task_id']}), no items yet;"
          " scan any box to add it")
    print(f"count of HOME-A: {jobs['count']['ref_doc_no']} (task {jobs['count']['task_id']}); a new box posts 561"
          " (opening stock)")
    if jobs["simulated"]:
        print(f"simulated differences (opt-in): {', '.join(jobs['simulated'])} hold {SIMULATED_QTY} in HOME-A by the"
              " books; their documents are marked simulated")
    print("Pair the phone to it: `uv run python -m tools.dev_stack.stack pair --home`")
    return 0


def cmd_assistant_check(a: argparse.Namespace) -> int:
    """Track A's hook (M3 contract section 4): tools/dev_stack/assistant_check.py, imported only when asked for."""
    import importlib

    try:
        mod = importlib.import_module("tools.dev_stack.assistant_check")
    except ModuleNotFoundError as e:
        if e.name != "tools.dev_stack.assistant_check":
            raise
        print("assistant-check is not installed in this build (tools/dev_stack/assistant_check.py is missing)")
        return 1
    load_env()
    return int(mod.run([]))


# --- smoke ----------------------------------------------------------------------------------------

def _wait_task(phone: Phone, site: str, type_: str, pred: Any, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        found = [t for t in phone.tasks(site, type_) if pred(t) and t.get("lines")]
        if found:
            return found[0]
        time.sleep(2)
    raise SmokeFailure(f"no {type_} task appeared within {timeout_s:.0f} s; is field-worker running?")


def _wait_status(phone: Phone, site: str, type_: str, task_id: str, status: str, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    t: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        t = phone.task(site, type_, task_id)
        if t and t["status"] == status:
            return t
        time.sleep(1)
    raise SmokeFailure(f"{type_} task {task_id} is {t['status'] if t else 'gone'}, not {status}")


def _accepted(r: httpx.Response, what: str, code: int = 200) -> dict[str, Any]:
    if r.status_code != code:
        raise SmokeFailure(f"{what}: HTTP {r.status_code} {r.text[:300]}")
    return dict(r.json())


def _refused(r: httpx.Response, what: str, code: str) -> str:
    if r.status_code < 400 or code not in r.text:
        raise SmokeFailure(f"{what}: expected {code}, got HTTP {r.status_code} {r.text[:200]}")
    return str(r.json().get("title"))


def smoke_receive(phone: Phone, state: dict[str, Any], wait: float) -> dict[str, Any]:
    deliv = create_inbound_delivery(2)
    task = _wait_task(phone, state["site"], "receive", lambda t: t.get("ref_doc_no") == deliv, wait)
    print(f"receive  task {task['title']!r} ({task['subtitle']}) with {len(task['lines'])} lines")
    staged: list[tuple[str, float]] = []
    for ln in task["lines"]:
        qty = float(ln["expected_qty"])
        r = phone.count(ln, qty, phone.voice(task["id"], "count", f"count {int(qty)}"))
        _accepted(r, "count", 201)
        staged.append((ln["id"], phone.counted(r, qty)))
    out = _accepted(phone.finish(task["id"], staged, phone.voice(task["id"], "post", "post"),
                                 phone.voice(task["id"], "confirm", "confirm")), "post (voice)", 202)
    _expect(out["status"] == "queued", f"receive post status {out['status']}")
    ev = phone.wait_event(("erp.posted",), task["id"], wait)
    _expect(ev["kind"] == "erp.posted", f"receive: {ev}")
    moves = erp_movements(ev["doc_number"], ev["doc_year"])
    want = sorted((ln["material"], "101", float(ln["expected_qty"])) for ln in task["lines"])
    _expect(sorted(moves) == want, f"erp-sim GR {ev['doc_number']} has {moves}, expected {want}")
    print(f"         erp.posted: GR {ev['doc_number']}/{ev['doc_year']} in erp-sim, movements {moves}")
    erp_doc = out["posting_request_id"]
    assigned = phone.wait_event(("task.assigned",), None, wait, pred=lambda p: p.get("erp_document_id") == erp_doc)
    _expect(assigned.get("type") == "putaway", f"after GR: {assigned}")
    print(f"         task.assigned: {assigned['title']!r}")
    return {"gr": ev["doc_number"], "putaway_task": assigned["task_id"], "task": task}


def smoke_putaway(phone: Phone, state: dict[str, Any], gr: str, wait: float) -> None:
    task = _wait_task(phone, state["site"], "putaway", lambda t: t.get("ref_doc_no") == gr, wait)
    print(f"putaway  task {task['title']!r} ({task['subtitle']})")
    other = next(b for bins in BIN_TREE.values() for b in bins if b != task["lines"][0]["bin"])
    title = _refused(phone.confirm(task["id"], task["lines"][0]["id"], "bin", other), "wrong bin",
                     "FIELD-TASK-409-WRONG-CODE")
    print(f"         wrong bin refused: {title!r}")
    for ln in task["lines"]:
        _expect(bool(ln["bin"]), f"put-away line {ln['line_no']} has no suggested bin")
        out = _accepted(phone.confirm(task["id"], ln["id"], "bin", ln["bin"]), "bin scan")
        _expect(out["line_status"] == "confirmed", f"bin scan left line {out}")
    out = _accepted(phone.finish(task["id"], phone.listed(task)), "post (touch)", 202)
    _expect(out["status"] == "completed", f"putaway post {out}")
    phone.wait_event(("task.completed",), task["id"], wait)
    _wait_status(phone, state["site"], "putaway", task["id"], "done", wait)
    print(f"         stored: {', '.join(f'{ln['material']} x{ln['expected_qty']:g} in {ln['bin']}' for ln in task['lines'])}")


def smoke_pick(phone: Phone, state: dict[str, Any], wait: float) -> None:
    stock = [s for s in bins_with_stock(state) if s[2] >= 3][:2]
    _expect(len(stock) == 2, "need two bins with stock for the pick")
    deliv = create_outbound_delivery([(m, 3.0) for _b, m, _q in stock])
    task = _wait_task(phone, state["site"], "pick", lambda t: t.get("ref_doc_no") == deliv, wait)
    print(f"pick     task {task['title']!r} ({task['subtitle']}), stops {[ln['bin'] for ln in task['lines']]}")
    _expect([ln["bin"] for ln in task["lines"]] == sorted(ln["bin"] for ln in task["lines"]), "stops not in bin order")
    first = task["lines"][0]
    _refused(phone.confirm(task["id"], first["id"], "product", first["material"]), "product before bin",
             "FIELD-TASK-409-WRONG-CODE")
    picked: list[tuple[str, float]] = []
    before = {m: erp_stock(m) for _b, m, _q in stock}
    for i, ln in enumerate(task["lines"]):
        _accepted(phone.confirm(task["id"], ln["id"], "bin", ln["bin"]), "pick bin scan")
        _refused(phone.confirm(task["id"], ln["id"], "product", "SAMPLE-MAT-9999"), "wrong product",
                 "FIELD-TASK-409-WRONG-CODE")
        _accepted(phone.confirm(task["id"], ln["id"], "product", ln["material"]), "pick product scan")
        qty = float(ln["expected_qty"]) - (1 if i == 1 else 0)  # second stop is one short
        r = phone.count(ln, qty)
        _accepted(r, "picked quantity", 201)
        if i == 1:
            _accepted(phone.flag(task["id"], ln["id"], "short", f"picked {qty:g} of {ln['expected_qty']:g}"), "short flag")
        picked.append((ln["id"], phone.counted(r, qty)))
    out = _accepted(phone.finish(task["id"], picked), "post (touch)", 202)
    ev = phone.wait_event(("erp.posted",), task["id"], wait)
    _expect(ev["kind"] == "erp.posted", f"pick: {ev}")
    moves = erp_movements(ev["doc_number"], ev["doc_year"])
    want = sorted((ln["material"], "601", q) for ln, (_lid, q) in zip(task["lines"], picked, strict=True))
    _expect(sorted(moves) == want, f"erp-sim GI {ev['doc_number']} has {moves}, expected {want}")
    for ln, (_lid, q) in zip(task["lines"], picked, strict=True):
        _expect(erp_stock(ln["material"]) == before[ln["material"]] - q, f"erp-sim stock of {ln['material']}")
    print(f"         {out['status']} -> erp.posted: GI {ev['doc_number']} (601) {moves}; one stop short")


def _count_blind(phone: Phone, state: dict[str, Any], count: dict[str, Any], delta: float) -> dict[str, Any]:
    task = _wait_task(phone, state["site"], "count", lambda t: t["id"] == count["task_id"], 10)
    _expect(all("expected_qty" not in ln and "counted_qty" not in ln for ln in task["lines"]), "count is not blind")
    staged = []
    for ln in task["lines"]:
        qty = erp_stock(ln["material"]) + delta  # the smoke knows the book from erp-sim; the phone never sees it
        r = phone.count(ln, qty)
        if r.status_code != 201:
            return {"refused": r}
        staged.append((ln["id"], phone.counted(r, qty)))
    return {"task": task, "staged": staged}


def smoke_count(phone: Phone, phone2: Phone, console: Console, state: dict[str, Any], wait: float) -> None:
    # 1. within tolerance: one piece missing -> 702 through the PI document
    stock = bins_with_stock(state)
    by_bin: dict[str, list[str]] = {}
    for b, m, q in stock:
        if q >= 60:
            by_bin.setdefault(b, []).append(m)
    single = [b for b, ms in by_bin.items() if len(ms) == 1]
    _expect(len(single) >= 2, f"need two single-material bins with >= 60 pieces (1 short stays within 2 %), have {by_bin}")
    c1 = create_count_task(state, single[0])
    done = _count_blind(phone, state, c1, -1)
    task, staged = done["task"], done["staged"]
    mat = task["lines"][0]["material"]
    before = erp_stock(mat)
    out = _accepted(phone.finish(task["id"], staged), "count post", 202)
    _expect(out["status"] == "queued", f"count within tolerance: {out}")
    ev = phone.wait_event(("erp.posted",), task["id"], wait)
    _expect(ev["kind"] == "erp.posted", f"count: {ev}")
    moves = erp_movements(ev["doc_number"], ev["doc_year"])
    _expect(moves == [(mat, "702", 1.0)] and erp_stock(mat) == before - 1, f"erp-sim PI difference {moves}")
    print(f"count    {task['title']!r} blind, 1 short (within tolerance) -> erp.posted: {ev['doc_number']} {moves}")

    # 2. beyond tolerance -> approval request -> recount by someone else -> approve -> 702
    c2 = create_count_task(state, single[1])
    done = _count_blind(phone, state, c2, -10)
    task, staged = done["task"], done["staged"]
    out = _accepted(phone.finish(task["id"], staged), "count post", 202)
    _expect(out["status"] == "awaiting_approval", f"count beyond tolerance: {out}")
    phone.wait_event(("count.awaiting_approval",), task["id"], wait)
    pending = console.get("/v1/approval-requests", status="pending")["items"]
    apr = next((a for a in pending if a["task_id"] == task["id"]), None)
    if apr is None:
        raise SmokeFailure("approval request not in the console queue")
    print(f"         10 short (beyond tolerance) -> awaiting_approval; console sees {apr['type']} "
          f"lines {[(x['material'], x['book_qty'], x['counted_qty']) for x in apr['lines']]}")
    rc = _accepted(console.post(f"/v1/tasks/{task['id']}/recount"), "recount", 201)
    recount = {"task_id": rc["task_id"]}
    again = _count_blind(phone, state, recount, -10)
    _expect("refused" in again and "RECOUNT-SAME-OPERATOR" in again["refused"].text, "recount by the first counter")
    rt = _wait_task(phone2, state["site"], "count", lambda t: t["id"] == rc["task_id"], 10)
    _expect(rt["reason"] == rc["reason"], f"recount reason {rt['reason']!r}")
    done = _count_blind(phone2, state, recount, -10)
    out = _accepted(phone2.finish(rc["task_id"], done["staged"]), "recount post", 202)
    _expect(out["status"] == "awaiting_approval", f"recount: {out}")
    apr2 = next(a for a in console.get("/v1/approval-requests")["items"] if a["task_id"] == rc["task_id"])
    mat = done["task"]["lines"][0]["material"]
    before = erp_stock(mat)
    dec = _accepted(console.post(f"/v1/approval-requests/{apr2['id']}/decide",
                                 {"decision": "approve", "reason": "recount confirms the loss"}), "approve")
    _expect(dec["status"] == "approved" and bool(dec["erp_document_id"]), f"decide: {dec}")
    _wait_status(phone2, state["site"], "count", rc["task_id"], "done", wait)
    _expect(erp_stock(mat) == before - 10, f"erp-sim stock of {mat} after the approved difference")
    print(f"         recount by a second operator ({rt['reason']!r}) -> approved -> 702 of 10 posted in erp-sim")


def smoke_visit_in(phone: Phone, site: str, at: tuple[float, float] = (TOWER_LAT, TOWER_LON)) -> str:
    """Check in, harness, climb-safe, a rest platform, and a safety heartbeat: the app's tower visit (§6)."""
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC).astimezone()
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
    r = httpx.post(f"{phone.api}/v1/sites/{site}/visits", json={
        "permit_ref": f"PTW-{uuid.uuid4().hex[:6].upper()}", "permit_valid_until": end_of_day.isoformat(),
        "lat": at[0] + 0.0002, "lon": at[1], "accuracy_m": 8.0, "captured_at": now.isoformat()},
        headers=phone._h(True), timeout=10)
    visit = str(_accepted(r, "check-in", 201)["id"])
    events = [("harness_confirmed", {}), ("climb_safe_activated", {}), ("checkpoint_reached", {"level": 1})]
    r = httpx.post(f"{phone.api}/v1/climb-sessions/{visit}/events", json={"events": [
        {"device_seq": i, "type": t, "occurred_at": (now + timedelta(seconds=i)).isoformat(), "payload": p}
        for i, (t, p) in enumerate(events, start=1)]}, headers=phone._h(True), timeout=10)
    _accepted(r, "climb events")
    _accepted(httpx.post(f"{phone.api}/v1/safety/visits/{visit}/check-in", json={}, headers=phone._h(True), timeout=10),
              "safety check-in")
    print(f"visit    checked in ({visit}); harness, climb-safe, checkpoint level 1, safety heartbeat")
    return visit


def smoke_visit_out(phone: Phone, visit: str) -> None:
    from datetime import UTC, datetime

    r = httpx.post(f"{phone.api}/v1/climb-sessions/{visit}/events", json={"events": [
        {"device_seq": 4, "type": "climb_safe_released", "occurred_at": datetime.now(UTC).isoformat(), "payload": {}}]},
        headers=phone._h(True), timeout=10)
    _accepted(r, "climb released")
    r = httpx.patch(f"{phone.api}/v1/visits/{visit}", json={"unsynced_count": 0}, headers=phone._h(), timeout=10)
    _accepted(r, "check-out")
    print("         climb-safe released, checked out")


def smoke_tower(phone: Phone, console: Console, state: dict[str, Any], wait: float) -> None:
    tw = create_tower_jobs(state)
    site = tw["state"]["tower_site"]
    tower_at = state.get("tower_at") or [TOWER_LAT, TOWER_LON]
    visit = smoke_visit_in(phone, site, (float(tower_at[0]), float(tower_at[1])))
    audit = _wait_task(phone, site, "audit", lambda t: t["id"] == tw["audit"]["id"], 10)
    _expect(len(audit["lines"]) == 3, f"sector A audit has {len(audit['lines'])} lines")
    print(f"audit    {audit['title']!r} ({audit['subtitle']}): {[(ln['position'], ln['expected_serial']) for ln in audit['lines']]}")
    l1, l2, l3 = audit["lines"]
    o1 = _accepted(phone.confirm(audit["id"], l1["id"], "serial", l1["expected_serial"]), "serial scan")
    stranger = f"RRU-SN-{uuid.uuid4().hex[:6].upper()}"
    o2 = _accepted(phone.confirm(audit["id"], l2["id"], "serial", stranger), "unexpected serial")
    _expect(o1["match"] is True and o2["match"] is False, f"match flags {o1} {o2}")
    _accepted(phone.flag(audit["id"], l3["id"], "missing", "inaccessible"), "missing flag")
    audit = phone.task(site, "audit", audit["id"]) or audit
    out = _accepted(phone.finish(audit["id"], phone.listed(audit)), "audit finish", 202)
    rec = out["reconciliation"]
    _expect(out["status"] == "completed" and (rec["matched"], rec["serial_mismatch"], rec["erp_only"]) == (1, 1, 1),
            f"audit reconciliation {out}")
    phone.wait_event(("task.completed",), audit["id"], wait)
    queue = console.get("/v1/mismatches", site_id=site)["items"]
    classes = {(m.get("class") or m.get("finding_class"), m.get("found_serial") or m.get("expected_serial")) for m in queue}
    _expect(("serial_mismatch", stranger) in classes or any(stranger in json.dumps(m) for m in queue),
            f"console mismatch queue lacks {stranger}: {queue}")
    print(f"         completed: {rec}; console mismatch queue has {len(queue)} open finding(s)")
    smoke_visit_out(phone, visit)

    swap = _wait_task(phone, site, "swap", lambda t: t["id"] == tw["swap"]["id"], 10)
    ln = swap["lines"][0]
    print(f"swap     {swap['title']!r}: remove {ln['expected_serial']} at {ln['position']}, install spare {tw['spare']}")
    _refused(phone.confirm(swap["id"], ln["id"], "serial", tw["spare"], role="old"), "wrong old unit",
             "FIELD-TASK-409-WRONG-CODE")
    _accepted(phone.confirm(swap["id"], ln["id"], "serial", ln["expected_serial"], role="old"), "old unit")
    _accepted(phone.confirm(swap["id"], ln["id"], "serial", tw["spare"], role="new"), "new unit")
    out = _accepted(phone.finish(swap["id"], phone.listed(swap)), "swap post", 202)
    _expect(out["status"] == "queued" and out["queue_key"] == f"EQUIP:{TOWER_FL}", f"swap: {out}")
    ev = phone.wait_event(("erp.posted",), swap["id"], wait)
    _expect(ev["kind"] == "erp.posted", f"swap: {ev}")
    old, new = erp_equipment(ln["expected_serial"]) or {}, erp_equipment(tw["spare"]) or {}
    _expect(bool(old) and not old.get("FunctionalLocation"), f"erp-sim old unit {old}")
    _expect(new.get("FunctionalLocation") == f"{TOWER_FL}-A-S3", f"erp-sim new unit {new}")
    _wait_status(phone, site, "swap", swap["id"], "done", wait)
    print(f"         erp.posted: change document {ev['doc_number']}; erp-sim: {ln['expected_serial']} dismantled,"
          f" {tw['spare']} installed at {TOWER_FL}-A-S3")


def new_barcode() -> str:
    """A barcode erp-sim has never seen: EAN-13 shaped, restricted prefix 2 (in-store numbers)."""
    return "2" + "".join(secrets.choice("0123456789") for _ in range(12))


def smoke_home(phone: Phone, wh_phone: Phone, state: dict[str, Any], wait: float) -> None:
    """M3 contract section 6: sandbox receipt with a never-seen barcode -> GR 101 with a HOME material; the
    production warehouse refuses the same code; a sandbox count posts 561."""
    home, api = state["home_site"], phone.api

    def post(p: Phone, path: str, body: dict[str, Any]) -> httpx.Response:
        return httpx.post(f"{api}{path}", json=body, headers=p._h(True), timeout=15)

    def code_of(p: Phone, code: str, site: str) -> dict[str, Any]:
        return _accepted(httpx.get(f"{api}/v1/codes/{code}", params={"site_id": site}, headers=p._h(), timeout=10),
                         "code lookup")

    rec = _accepted(post(phone, "/v1/sandbox/receipts", {"site_id": home}), "sandbox receipt", 201)
    code = new_barcode()
    _expect(code_of(phone, code, home)["kind"] == "unknown", f"{code} should be unknown before it is added")
    item = _accepted(post(phone, f"/v1/sandbox/tasks/{rec['task_id']}/items",
                          {"code": code, "description": "Smoke test box", "qty": 1}), "add item", 201)
    _expect(item["created_material"] and item["material"].startswith("HOME-"), f"new material: {item}")
    print(f"home     receipt {rec['ref_doc_no']}: barcode {code} -> new material {item['material']}")
    task = phone.task(home, "receive", rec["task_id"])
    _expect(task is not None, "the home receipt is not in the task list")
    assert task is not None
    line = next(ln for ln in task["lines"] if ln["id"] == item["line_id"])
    _expect(code in line.get("barcodes", []), f"task line barcodes {line.get('barcodes')}")
    _accepted(phone.confirm(task["id"], line["id"], "product", code), "product scan by barcode")
    r = phone.count(line, 3)
    _accepted(r, "count", 201)
    out = _accepted(phone.finish(task["id"], [(line["id"], phone.counted(r, 3))]), "post (touch)", 202)
    _expect(out["status"] == "queued", f"home receipt post {out}")
    ev = phone.wait_event(("erp.posted",), task["id"], wait)
    _expect(ev["kind"] == "erp.posted", f"home receipt: {ev}")
    doc = erp_document(ev["doc_number"], ev["doc_year"])
    moves = erp_movements(ev["doc_number"], ev["doc_year"])
    _expect(moves == [(item["material"], "101", 3.0)], f"erp-sim GR {ev['doc_number']} has {moves}")
    _expect(doc.get("YY1_FieldSandbox") is True, f"GR {ev['doc_number']} is not marked sandbox")
    print(f"         counted 3 (delivery said 1, soft pegging) -> GR {ev['doc_number']}/{ev['doc_year']}, {moves},"
          " sandbox")

    wh = state["site"]
    seen = code_of(wh_phone, code, wh)
    _expect((seen["kind"], seen["site_mode"]) == ("unknown", "production"), f"production lookup {seen}")
    title = _refused(post(wh_phone, "/v1/sandbox/receipts", {"site_id": wh}), "sandbox receipt on production",
                     "FIELD-SBX-403-PRODUCTION")
    deliv = create_inbound_delivery(1)
    ptask = _wait_task(wh_phone, wh, "receive", lambda t: t.get("ref_doc_no") == deliv, wait)
    pline = ptask["lines"][0]
    _refused(wh_phone.confirm(ptask["id"], pline["id"], "product", code), "barcode on a production line",
             "FIELD-TASK-409-WRONG-CODE")
    _refused(post(wh_phone, f"/v1/sandbox/tasks/{ptask['id']}/items", {"code": code, "description": "box"}),
             "sandbox item on a production receipt", "FIELD-SBX-403-PRODUCTION")
    print(f"         production warehouse: {code} unknown, scan refused on delivery {deliv}, sandbox refused ({title!r})")

    count = _accepted(post(phone, "/v1/sandbox/counts", {"site_id": home, "bin": "HOME-B"}), "sandbox count", 201)
    code2 = new_barcode()
    it2 = _accepted(post(phone, f"/v1/sandbox/tasks/{count['task_id']}/items",
                         {"code": code2, "description": "Smoke count box", "qty": 4}), "add count item", 201)
    ctask = phone.task(home, "count", count["task_id"])
    _expect(ctask is not None and all("expected_qty" not in ln for ln in ctask["lines"]), "count is not blind")
    assert ctask is not None
    out = _accepted(phone.finish(ctask["id"], [(it2["line_id"], 4.0)]), "count post", 202)
    _expect(out["status"] == "queued", f"home count post {out}")
    ev = phone.wait_event(("erp.posted",), ctask["id"], wait)
    _expect(ev["kind"] == "erp.posted", f"home count: {ev}")
    moves = erp_movements(ev["doc_number"], ev["doc_year"])
    _expect(moves == [(it2["material"], "561", 4.0)], f"erp-sim initial entry {ev['doc_number']} has {moves}")
    _expect(erp_document(ev["doc_number"], ev["doc_year"]).get("YY1_FieldSandbox") is True, "561 is not sandbox")
    _expect(erp_stock(it2["material"], HOME_PLANT, HOME_SLOC) == 4.0, "erp-sim stock after 561")
    _wait_status(phone, home, "count", ctask["id"], "done", wait)
    print(f"         count {count['ref_doc_no']} of HOME-B: new box {code2} -> {it2['material']}, 4 counted ->"
          f" 561 {ev['doc_number']} {moves}, sandbox")


def cmd_smoke(a: argparse.Namespace) -> int:
    """Receive one inbound delivery by voice as the app does; with --all, every job type end to end;
    with --home, the sandbox site (M3)."""
    load_env()
    apply_ports()
    state = ensure_warehouse(json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {})
    api = a.api or local("field-api")
    if getattr(a, "home", False):
        state = ensure_home(state)
        phone = Phone(api, _core_token("smoke-home", state["tenant"], state["home_site"], 1800)).pair(
            f"smoke-{uuid.uuid4().hex[:8]}")
        wh_phone = Phone(api, _core_token("smoke-op", state["tenant"], state["site"], 1800)).pair(
            f"smoke-{uuid.uuid4().hex[:8]}")
        print(f"paired: device {phone.device_id} (home), {wh_phone.device_id} (warehouse)")
        try:
            smoke_home(phone, wh_phone, state, a.wait)
        except SmokeFailure as e:
            print(f"FAIL: {e}")
            return 1
        print("PASS: home sandbox (receipt with a new barcode -> GR 101, production refusal, count -> 561)")
        return 0
    site = state["site"]
    phone = Phone(api, _core_token("smoke-op", state["tenant"], site, 1800)).pair(f"smoke-{uuid.uuid4().hex[:8]}")
    print(f"paired: device {phone.device_id}")
    steps = 0
    try:
        rec = smoke_receive(phone, state, a.wait)
        steps += 1
        if not a.all:
            print(f"PASS: receive posted (GR {rec['gr']})")
            return 0
        smoke_putaway(phone, state, rec["gr"], a.wait)
        steps += 1
        smoke_pick(phone, state, a.wait)
        steps += 1
        phone2 = Phone(api, _core_token("smoke-op2", state["tenant"], site, 1800)).pair(f"smoke-{uuid.uuid4().hex[:8]}")
        console = Console(api, state["tenant"])
        smoke_count(phone, phone2, console, state, a.wait)
        steps += 1
        state = ensure_tower_site(state)
        tower_phone = Phone(api, _core_token("smoke-tech", state["tenant"], state["tower_site"], 1800)).pair(
            f"smoke-{uuid.uuid4().hex[:8]}")
        smoke_tower(tower_phone, console, state, a.wait)
        steps += 2
    except SmokeFailure as e:
        print(f"FAIL after {steps} job type(s): {e}")
        return 1
    print(f"PASS: {steps} job types end to end (receive, putaway, pick, count + recount, audit, swap)")
    return 0


# ------------------------------------------------------------------ printable labels
JOB_ORDER = ("receive", "putaway", "pick", "count", "audit", "swap")
JOB_NAME = {
    "receive": "Receive",
    "putaway": "Put away",
    "pick": "Pick",
    "count": "Count",
    "audit": "Tower audit",
    "swap": "Swap",
}
# A serial no tower holds: scan it during an audit to see a mismatch reach the console.
UNEXPECTED_SERIAL = "RRU-SN-TEST01"


def label_sheet(
    tasks: list[dict[str, Any]], spares: list[str], per_type: int = 2
) -> list[tuple[str, list[tuple[str, str]]]]:
    """Open jobs -> sections of (code, caption) to print: every code the phone asks for, per job.

    Receive/count/put-away scan the product code, put-away and pick also the bin, audit and swap the
    serial on the unit; the swap's new unit is a spare in store. Each section ends with one wrong code
    so the refusal can be tried too."""
    out: list[tuple[str, list[tuple[str, str]]]] = []
    # Newest first within a type (task ids are UUIDv7, so they sort by creation time); keep per_type of each.
    newest = sorted((t for t in tasks if t.get("lines")), key=lambda t: str(t["id"]), reverse=True)
    kept: list[dict[str, Any]] = []
    for t in newest:
        if sum(1 for k in kept if k["type"] == t["type"]) < per_type:
            kept.append(t)
    ordered = sorted(kept, key=lambda t: JOB_ORDER.index(t["type"]) if t["type"] in JOB_ORDER else 99)
    for t in ordered:
        codes: list[tuple[str, str]] = []

        def add(code: str | None, caption: str, codes: list[tuple[str, str]] = codes) -> None:
            if code and code not in {c for c, _ in codes}:
                codes.append((code, caption))

        kind = t["type"]
        lines = sorted(t.get("lines") or [], key=lambda ln: ln.get("line_no") or 0)
        for ln in lines:
            item = " · ".join(str(x) for x in (ln.get("description"), ln.get("uom")) if x)
            if kind in ("receive", "count"):
                add(ln.get("material"), f"product{f' · {item}' if item else ''}")
            if kind == "count":
                add(ln.get("bin"), "the bin being counted")
            if kind == "putaway":
                add(ln.get("material"), "pallet / product label")
                add(ln.get("bin"), "bin to put it in")
            if kind == "pick":
                add(ln.get("bin"), f"stop {lines.index(ln) + 1}: bin")
                add(ln.get("material"), f"stop {lines.index(ln) + 1}: product")
            if kind in ("audit", "swap"):
                where = ln.get("position") or "unit"
                add(
                    ln.get("expected_serial"),
                    f"{where}: {'old unit (remove)' if kind == 'swap' else 'serial label'}",
                )
        if kind == "swap":
            for sp in spares[:1]:
                add(sp, "new unit from store (install)")
        if not codes:
            continue
        wrong = {
            "receive": ("SAMPLE-MAT-9999", "wrong product (should be refused)"),
            "count": ("SAMPLE-MAT-9999", "not in this bin (should be refused)"),
            "putaway": ("03-07-01", "wrong bin (should be refused)"),
            "pick": ("03-07-01", "wrong bin (should be refused)"),
            "audit": (UNEXPECTED_SERIAL, "a unit SAP does not expect (shows as a finding)"),
            "swap": (UNEXPECTED_SERIAL, "wrong unit (should be refused)"),
        }.get(kind)
        if wrong and wrong[0] not in {c for c, _ in codes}:
            codes.append(wrong)
        out.append((f"{JOB_NAME.get(kind, kind)}: {t.get('title') or t['id']}", codes))
    return out


def render_labels(sections: list[tuple[str, list[tuple[str, str]]]], when: str) -> str:
    """One printable HTML page; each label is a QR code plus the code in large text (type it if a scan fails)."""
    import html

    import qrcode
    from qrcode.image.svg import SvgPathImage

    def svg(code: str) -> str:
        qr = qrcode.QRCode(border=1, box_size=6)
        qr.add_data(code)
        qr.make(fit=True)
        img: Any = qr.make_image(image_factory=SvgPathImage)
        return str(img.to_string(encoding="unicode"))

    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>SCMTips Field test labels</title><style>",
        "body{font-family:system-ui,sans-serif;margin:16px;color:#1C1E21}h1{font-size:22px}",
        "h2{font-size:17px;margin:20px 0 8px;break-after:avoid}.grid{display:flex;flex-wrap:wrap;gap:10px}",
        ".l{border:1px solid #CED0D4;border-radius:8px;padding:8px;width:190px;text-align:center;break-inside:avoid}",
        ".l svg{width:150px;height:150px}.c{font:700 15px ui-monospace,monospace;word-break:break-all}",
        ".k{font-size:12px;color:#65676B}.wrong{border-style:dashed}p{color:#65676B}</style></head><body>",
        f"<h1>Test labels for the open jobs</h1><p>Made {html.escape(when)}. Print this page, or show it on a second "
        "screen. Point the phone or glasses at a code. Dashed labels are wrong on purpose.</p>",
    ]
    if not sections:
        parts.append(
            "<p><b>No open jobs.</b> Run delivery, outbound, count or tower first, then labels again.</p>"
        )
    for title, codes in sections:
        parts.append(f"<h2>{html.escape(title)}</h2><div class='grid'>")
        for code, caption in codes:
            cls = "l wrong" if "refused" in caption or "does not expect" in caption else "l"
            parts.append(
                f"<div class='{cls}'>{svg(code)}<div class='c'>{html.escape(code)}</div>"
                f"<div class='k'>{html.escape(caption)}</div></div>"
            )
        parts.append("</div>")
    parts.append("</body></html>")
    return "".join(parts)


def _spare_serials() -> list[str]:
    """Read-only: RRU serials in store (no functional location) in erp-sim."""
    import psycopg

    with psycopg.connect(_admin_url("erpsim"), autocommit=True) as c, c.cursor() as cur:
        cur.execute(
            "SELECT serial_no FROM erpsim.equipment WHERE func_loc IS NULL AND material_no = 'MAT-RRU-01'"
            " ORDER BY equipment_no"
        )
        return [str(r[0]) for r in cur.fetchall()]


def cmd_labels(a: argparse.Namespace) -> int:
    """var/labels.html: QR labels for every code the open jobs ask for (opens on Windows)."""
    load_env()
    apply_ports()
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    if not state.get("site"):
        print("No demo site yet: run `stack up`, then delivery / outbound / count / tower.")
        return 1
    api = a.api or local("field-api")
    tasks: list[dict[str, Any]] = []
    for site in [s for s in (state.get("site"), state.get("tower_site"), state.get("home_site")) if s and site_exists(s)]:
        phone = Phone(api, _core_token("labels", state["tenant"], site, 600)).pair(
            f"labels-{uuid.uuid4().hex[:8]}"
        )
        tasks += phone.tasks(site)
    sections = label_sheet(tasks, _spare_serials(), a.per_type)
    out = ROOT / "var" / "labels.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_labels(sections, time.strftime("%Y-%m-%d %H:%M")), encoding="utf-8")
    print(f"{sum(len(c) for _t, c in sections)} labels for the newest {len(sections)} of {len(tasks)} open jobs: {out}")
    if sys.platform == "win32" and not a.no_open:
        with contextlib.suppress(OSError):
            os.startfile(out)
    return 0


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
    pr.add_argument("--no-open", action="store_true", help="do not open the QR image (Windows)")
    pr.add_argument("--tower", action="store_true", help="pair to the SAMPLE tower site (audit and swap jobs)")
    pr.add_argument("--home", action="store_true", help="pair to the home sandbox site (M3)")
    dl = sub.add_parser("delivery")
    dl.add_argument("--lines", type=int, default=3)
    ob = sub.add_parser("outbound", help="outbound delivery in erp-sim -> a pick task")
    ob.add_argument("--lines", type=int, default=2)
    ct = sub.add_parser("count", help="a blind count task for a bin of the SAMPLE site")
    ct.add_argument("bin", nargs="?", help="e.g. 03-05-02 (default: a bin that holds stock)")
    tw = sub.add_parser("tower", help="SAMPLE-TWR-0001 in erp-sim + field: a sector A audit and a swap task")
    tw.add_argument("--at", help="LAT,LON where you will stand (e.g. from Google Maps), so check-in passes there")
    lb = sub.add_parser("labels", help="var/labels.html: printable QR labels for every open job")
    lb.add_argument("--api")
    lb.add_argument("--no-open", action="store_true")
    lb.add_argument("--per-type", type=int, default=2, help="newest jobs of each type to print (default 2)")
    sm = sub.add_parser("smoke")
    sm.add_argument("--api")
    sm.add_argument("--wait", type=float, default=90)
    sm.add_argument("--all", action="store_true", help="every job type: receive, putaway, pick, count, audit, swap")
    sm.add_argument("--home", action="store_true", help="the home sandbox site: new barcode -> GR 101, count -> 561")
    hm = sub.add_parser("home", help="sandbox site 'Home (sandbox)': bins HOME-A/B, an empty receipt, a HOME-A count")
    hm.add_argument("--simulate-differences", action="store_true",
                    help="opt-in: give two SAMPLE materials a simulated book stock in HOME-A (documents marked simulated)")
    sub.add_parser("assistant-check", help="one real Field Assistant model call through the budget guard (track A)")
    a = ap.parse_args(argv)
    return {"up": cmd_up, "down": cmd_down, "status": cmd_status, "pair": cmd_pair, "smoke": cmd_smoke,
            "delivery": cmd_delivery, "outbound": cmd_outbound, "count": cmd_count, "tower": cmd_tower,
            "labels": cmd_labels, "home": cmd_home, "assistant-check": cmd_assistant_check}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
