#!/usr/bin/env python3
"""Bitácula — diário de bordo da VPS e dos bancos.

Escuta só em 127.0.0.1. O nginx publica a porta pública e aceita
apenas os IPs listados na configuração das estações. A senha do
painel fica em auth.json; as senhas dos bancos não saem daqui.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / "panel"
AUTH_FILE = PANEL / "auth.json"
CRED_FILE = PANEL / "CREDENCIAIS.txt"
TLS_DIR = PANEL / "tls"
NGINX_SITE = Path(os.environ.get("BITACULA_NGINX_SITE", "/etc/nginx/sites-available/dbadmin.conf"))
NGINX_LINK = Path(os.environ.get("BITACULA_NGINX_LINK", "/etc/nginx/sites-enabled/dbadmin.conf"))
LAB_STATE = ROOT / "laboratorio.ip"
BACKUP_SCRIPT = ROOT / "backup-databases.sh"
LAB_SCRIPT = ROOT / "atualizar-ip-laboratorio.sh"
BACKUP_ROOT = ROOT / "backups"
BACKUP_LOG = PANEL / "last-backup.log"

BIND = "127.0.0.1"
PORT = 8787
PUBLIC_PORT = 8448
SESSION_TTL = 12 * 60 * 60
MAX_BODY = 16_384
DB_PORTS = (3306, 6379, 5432)
IPV4_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MYSQL_SKIP = {"information_schema", "performance_schema", "sys", "mysql"}

SESSIONS: dict[str, dict] = {}
ATTEMPTS: dict[str, list[float]] = {}
BACKUP_STATE = {"running": False, "started": 0.0, "exit": None}
CACHE: dict[str, tuple[float, object]] = {}
LOCK = threading.Lock()


def valid_ipv4(ip: str) -> bool:
    match = IPV4_RE.fullmatch(ip or "")
    if not match:
        return False
    return all(0 <= int(part) <= 255 for part in match.groups())


def ip_conf_path() -> Path:
    override = os.environ.get("BITACULA_IP_CONF", "").strip()
    if override:
        return Path(override)
    legacy = Path("/etc/artesdosul/workstation-ip.conf")
    if legacy.exists():
        return legacy
    return Path("/etc/bitacula/workstations.conf")


def public_ip() -> str:
    override = os.environ.get("BITACULA_PUBLIC_IP", "").strip()
    if valid_ipv4(override):
        return override
    result = run(["hostname", "-I"], timeout=5)
    for token in (result.stdout or "").split():
        if ":" in token or not valid_ipv4(token):
            continue
        if token.startswith(("10.", "127.", "192.168.")):
            continue
        if token.startswith("172."):
            second = int(token.split(".")[1])
            if 16 <= second <= 31:
                continue
        return token
    return "127.0.0.1"


def allowed_ips() -> list[str]:
    conf = ip_conf_path()
    if not conf.exists():
        return []
    found = []
    for line in conf.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if valid_ipv4(line) and line not in found:
            found.append(line)
    return found


def lab_ip() -> str:
    if LAB_STATE.exists():
        value = LAB_STATE.read_text(encoding="utf-8").strip()
        if valid_ipv4(value):
            return value
    ips = allowed_ips()
    return ips[-1] if ips else ""


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return salt.hex(), digest.hex()


def ensure_auth() -> None:
    if AUTH_FILE.exists():
        return
    username = "laboratorio"
    password = secrets.token_urlsafe(18)
    salt, digest = hash_password(password)
    payload = {"username": username, "salt": salt, "hash": digest}
    AUTH_FILE.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    os.chmod(AUTH_FILE, 0o600)
    CRED_FILE.write_text(
        "Bitácula — credenciais de acesso\n"
        f"Endereço: https://{public_ip()}:{PUBLIC_PORT}\n"
        f"Usuário: {username}\n"
        f"Senha: {password}\n"
        "Guarde este arquivo. Ele fica só neste servidor.\n",
        encoding="utf-8",
    )
    os.chmod(CRED_FILE, 0o600)


def load_auth() -> dict:
    return json.loads(AUTH_FILE.read_text(encoding="utf-8"))


def check_password(password: str) -> bool:
    auth = load_auth()
    salt = bytes.fromhex(auth["salt"])
    _, digest = hash_password(password, salt)
    return hmac.compare_digest(digest, auth["hash"])


def save_password(password: str) -> None:
    auth = load_auth()
    salt, digest = hash_password(password)
    auth["salt"] = salt
    auth["hash"] = digest
    AUTH_FILE.write_text(json.dumps(auth) + "\n", encoding="utf-8")
    os.chmod(AUTH_FILE, 0o600)
    CRED_FILE.write_text(
        "Bitácula — credenciais de acesso\n"
        f"Endereço: https://{public_ip()}:{PUBLIC_PORT}\n"
        f"Usuário: {auth['username']}\n"
        f"Senha: {password}\n"
        "Senha alterada pelo painel.\n",
        encoding="utf-8",
    )
    os.chmod(CRED_FILE, 0o600)


def run(
    cmd: list[str], timeout: int = 25, env: dict | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False, env=env)


def cached(key: str, ttl: float, builder):
    now = time.time()
    with LOCK:
        hit = CACHE.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = builder()
    with LOCK:
        CACHE[key] = (time.time(), value)
    return value


def read_cpu_percent() -> float:
    def snap() -> tuple[int, int]:
        parts = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:9]
        nums = [int(part) for part in parts]
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
        return idle, sum(nums)

    idle_a, total_a = snap()
    time.sleep(0.2)
    idle_b, total_b = snap()
    delta = total_b - total_a
    if delta <= 0:
        return 0.0
    return round(100 * (1 - (idle_b - idle_a) / delta), 1)


def read_mem() -> dict:
    info = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, _, rest = line.partition(":")
        info[key] = int(rest.strip().split()[0]) * 1024
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", 0)
    return {"total": total, "available": available, "used": max(total - available, 0)}


def read_disk() -> dict:
    stat = os.statvfs("/")
    total = stat.f_frsize * stat.f_blocks
    avail = stat.f_frsize * stat.f_bavail
    used = total - avail
    percent = round(100 * used / total, 1) if total else 0
    return {"total": total, "used": used, "avail": avail, "percent": percent}


def uptime_seconds() -> int:
    return int(float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0]))


def docker_ps() -> list[dict]:
    result = run(["docker", "ps", "-a", "--format", "{{json .}}"], timeout=20)
    rows = []
    if result.returncode != 0:
        return rows
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        rows.append(
            {
                "name": item.get("Names", ""),
                "image": item.get("Image", ""),
                "status": item.get("Status", ""),
                "state": item.get("State", ""),
                "ports": item.get("Ports", ""),
            }
        )
    rows.sort(key=lambda row: (row["state"] != "running", row["name"]))
    return rows


def container_env(name: str, key: str) -> str:
    if not NAME_RE.fullmatch(name):
        return ""
    result = run(
        ["docker", "inspect", name, "--format", "{{range .Config.Env}}{{println .}}{{end}}"],
        timeout=15,
    )
    prefix = key + "="
    for line in result.stdout.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    return ""


def published(ports: str, port: int) -> bool:
    return f":{port}->" in (ports or "")


def postgres_instances(containers: list[dict]) -> list[dict]:
    found = []
    for row in containers:
        if row["state"] != "running":
            continue
        image = row["image"].lower()
        if "postgres" not in image:
            continue
        name = row["name"]
        if not NAME_RE.fullmatch(name):
            continue
        user = container_env(name, "POSTGRES_USER") or "postgres"
        if not re.fullmatch(r"[A-Za-z0-9_]+", user):
            user = "postgres"
        query = (
            "SELECT datname, pg_database_size(datname) "
            "FROM pg_database WHERE datistemplate = false ORDER BY 2 DESC"
        )
        result = run(
            ["docker", "exec", name, "psql", "-U", user, "-d", "postgres", "-Atqc", query],
            timeout=25,
        )
        databases = []
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                db_name, _, size = line.partition("|")
                if db_name:
                    databases.append({"name": db_name, "bytes": int(size or 0)})
        found.append(
            {
                "container": name,
                "user": user,
                "host": public_ip() if published(row["ports"], 5432) else "só na rede interna",
                "port": 5432 if published(row["ports"], 5432) else None,
                "open_to_lab": published(row["ports"], 5432),
                "databases": databases,
                "error": "" if result.returncode == 0 else "não foi possível listar os bancos",
            }
        )
    return found


def mysql_instances(containers: list[dict]) -> list[dict]:
    found = []
    query = (
        "SELECT table_schema, COALESCE(SUM(data_length+index_length),0) "
        "FROM information_schema.tables GROUP BY table_schema"
    )
    for row in containers:
        if row["state"] != "running" or "mysql" not in row["image"].lower():
            continue
        name = row["name"]
        if not NAME_RE.fullmatch(name):
            continue
        user = container_env(name, "MYSQL_USER")
        result = run(
            [
                "docker",
                "exec",
                name,
                "sh",
                "-c",
                f'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e "{query}"',
            ],
            timeout=30,
        )
        databases = []
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) < 2 or parts[0] in MYSQL_SKIP:
                    continue
                databases.append({"name": parts[0], "bytes": int(float(parts[1] or 0))})
            databases.sort(key=lambda item: item["bytes"], reverse=True)
        found.append(
            {
                "container": name,
                "user": user,
                "host": public_ip() if published(row["ports"], 3306) else "só na rede interna",
                "port": 3306 if published(row["ports"], 3306) else None,
                "open_to_lab": published(row["ports"], 3306),
                "databases": databases,
                "error": "" if result.returncode == 0 else "não foi possível listar os bancos",
            }
        )
    return found


def redis_instances(containers: list[dict]) -> list[dict]:
    found = []
    for row in containers:
        if row["state"] != "running" or "redis" not in row["image"].lower():
            continue
        name = row["name"]
        if not NAME_RE.fullmatch(name):
            continue
        ping = run(["docker", "exec", name, "redis-cli", "ping"], timeout=10)
        info = run(["docker", "exec", name, "redis-cli", "INFO"], timeout=10)
        memory = ""
        clients = ""
        for line in info.stdout.splitlines():
            if line.startswith("used_memory_human:"):
                memory = line.split(":", 1)[1].strip()
            elif line.startswith("connected_clients:"):
                clients = line.split(":", 1)[1].strip()
        exposed = None
        for port in (6379, 6381):
            if published(row["ports"], port):
                exposed = port
                break
        found.append(
            {
                "container": name,
                "ok": ping.stdout.strip() == "PONG",
                "memory": memory,
                "clients": clients,
                "host": public_ip() if exposed else "só na rede interna",
                "port": exposed,
                "open_to_lab": exposed == 6379,
            }
        )
    return found


def databases_snapshot() -> dict:
    containers = docker_ps()

    def build() -> dict:
        return {
            "public_ip": public_ip(),
            "postgres": postgres_instances(containers),
            "mysql": mysql_instances(containers),
            "redis": redis_instances(containers),
        }

    return cached("databases", 20, build)


def overview() -> dict:
    containers = cached("containers", 8, docker_ps)
    running = sum(1 for row in containers if row["state"] == "running")
    load = os.getloadavg()
    return {
        "hostname": os.uname().nodename,
        "public_ip": public_ip(),
        "uptime_seconds": uptime_seconds(),
        "load": [round(value, 2) for value in load],
        "cpu_percent": read_cpu_percent(),
        "cpu_count": os.cpu_count() or 1,
        "memory": read_mem(),
        "disk": read_disk(),
        "containers_running": running,
        "containers_total": len(containers),
        "lab_ip": lab_ip(),
        "panel_url": f"https://{public_ip()}:{PUBLIC_PORT}",
    }


def ufw_db_rules() -> list[dict]:
    result = run(["ufw", "status"], timeout=15)
    rules = []
    for line in result.stdout.splitlines():
        for port in DB_PORTS:
            if f"{port}/tcp" not in line or "ALLOW" not in line:
                continue
            match = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
            if not match:
                continue
            comment = ""
            if "#" in line:
                comment = line.split("#", 1)[1].strip()
            rules.append({"port": port, "ip": match.group(1), "comment": comment})
    return rules


def access_snapshot() -> dict:
    return {
        "lab_ip": lab_ip(),
        "stations": allowed_ips(),
        "rules": ufw_db_rules(),
        "panel_port": PUBLIC_PORT,
        "panel_url": f"https://{public_ip()}:{PUBLIC_PORT}",
        "db_host": public_ip(),
        "ports": list(DB_PORTS),
    }


def backup_list() -> list[dict]:
    if not BACKUP_ROOT.exists():
        return []
    rows = []
    for path in sorted(BACKUP_ROOT.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        manifest = path / "MANIFEST.txt"
        text = manifest.read_text(encoding="utf-8", errors="replace") if manifest.exists() else ""
        total = 0
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
        title = text.splitlines()[0].strip() if text else ""
        engines = title[7:].strip() if title.startswith("Backup ") else ""
        rows.append(
            {
                "stamp": path.name,
                "bytes": total,
                "ok": "FALHA" not in text and bool(text),
                "engines": engines or "PostgreSQL",
                "when": text.splitlines()[1].replace("Quando: ", "") if "Quando:" in text else path.name,
            }
        )
    return rows[:20]


def backup_status() -> dict:
    tail = ""
    if BACKUP_LOG.exists():
        lines = BACKUP_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(lines[-12:])
    with LOCK:
        state = dict(BACKUP_STATE)
    return {"running": state["running"], "exit": state["exit"], "log": tail, "items": backup_list()}


def start_backup(engines: list[str]) -> tuple[bool, str]:
    chosen = []
    for name in engines:
        if name not in {"postgres", "mysql"} or name in chosen:
            continue
        chosen.append(name)
    if not chosen or len(chosen) != len(engines):
        return False, "Escolha PostgreSQL, MySQL ou os dois."
    labels = {"postgres": "PostgreSQL", "mysql": "MySQL"}
    label = " e ".join(labels[name] for name in chosen)
    with LOCK:
        if BACKUP_STATE["running"]:
            return False, "Já existe um backup em andamento."
        BACKUP_STATE["running"] = True
        BACKUP_STATE["started"] = time.time()
        BACKUP_STATE["exit"] = None

    def work() -> None:
        code = 1
        command = [str(BACKUP_SCRIPT), "--keep", "14"]
        command.extend(f"--{name}" for name in chosen)
        try:
            with BACKUP_LOG.open("w", encoding="utf-8") as handle:
                proc = subprocess.run(
                    command,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    timeout=60 * 30,
                    check=False,
                )
                code = proc.returncode
        except subprocess.TimeoutExpired:
            code = 124
        finally:
            with LOCK:
                BACKUP_STATE["running"] = False
                BACKUP_STATE["exit"] = code
            with LOCK:
                CACHE.pop("backups", None)

    threading.Thread(target=work, daemon=True).start()
    return True, f"Backup de {label} iniciado."


def sync_panel_firewall() -> tuple[bool, str]:
    ips = allowed_ips()
    if not ips:
        return False, "Nenhum IP autorizado no arquivo da estação."
    TLS_DIR.mkdir(parents=True, exist_ok=True)
    cert = TLS_DIR / "fullchain.pem"
    key = TLS_DIR / "privkey.pem"
    if not cert.exists() or not key.exists():
        result = run(
            [
                "openssl",
                "req",
                "-x509",
                "-nodes",
                "-newkey",
                "rsa:2048",
                "-days",
                "825",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-subj",
                f"/CN={public_ip()}",
                "-addext",
                f"subjectAltName=IP:{public_ip()}",
            ],
            timeout=30,
        )
        if result.returncode != 0:
            return False, "Falha ao criar o certificado do painel."
        os.chmod(key, 0o600)
        os.chmod(cert, 0o644)
    allows = "\n".join(f"    allow {ip};" for ip in ips)
    config = f"""# Painel dbadmin. A lista de allow acompanha workstation-ip.conf.
server {{
    listen {PUBLIC_PORT} ssl;
    listen [::]:{PUBLIC_PORT} ssl;
    server_name {public_ip()};

    ssl_certificate {cert};
    ssl_certificate_key {key};
    ssl_protocols TLSv1.2 TLSv1.3;

    client_max_body_size 1m;

{allows}
    deny all;

    location / {{
        proxy_pass http://{BIND}:{PORT};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 60s;
    }}
}}
"""
    NGINX_SITE.write_text(config, encoding="utf-8")
    if not NGINX_LINK.exists():
        NGINX_LINK.symlink_to(NGINX_SITE)
    test = run(["nginx", "-t"], timeout=20)
    if test.returncode != 0:
        return False, (test.stderr or test.stdout or "nginx -t falhou").strip()
    reload = run(["systemctl", "reload", "nginx"], timeout=20)
    if reload.returncode != 0:
        return False, (reload.stderr or "falha ao recarregar o nginx").strip()

    numbered = run(["ufw", "status", "numbered"], timeout=20)
    remove: list[int] = []
    present: set[str] = set()
    for line in numbered.stdout.splitlines():
        if f"{PUBLIC_PORT}/tcp" not in line:
            continue
        match = re.match(r"\[\s*(\d+)\]", line.strip())
        ip_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
        if not match:
            continue
        ip = ip_match.group(1) if ip_match else ""
        if ip in ips:
            present.add(ip)
        else:
            remove.append(int(match.group(1)))
    for number in sorted(remove, reverse=True):
        run(["ufw", "--force", "delete", str(number)], timeout=20)
    for ip in ips:
        if ip in present:
            continue
        run(
            [
                "ufw",
                "allow",
                "from",
                ip,
                "to",
                "any",
                "port",
                str(PUBLIC_PORT),
                "proto",
                "tcp",
                "comment",
                "Painel dbadmin",
            ],
            timeout=20,
        )
    return True, "Acesso do painel atualizado."


def update_lab_ip(new_ip: str) -> tuple[bool, str]:
    if not valid_ipv4(new_ip):
        return False, "IP inválido."
    env = os.environ.copy()
    env["DBADMIN_FROM_PANEL"] = "1"
    result = run([str(LAB_SCRIPT), new_ip], timeout=60, env=env)
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        tail = "\n".join(output.strip().splitlines()[-8:])
        return False, tail or "Não foi possível atualizar o IP do laboratório."
    ok, message = sync_panel_firewall()
    if not ok:
        return False, "As portas dos bancos foram atualizadas, mas o painel não: " + message
    with LOCK:
        CACHE.clear()
    return True, f"Laboratório liberado em {new_ip}."


class Handler(BaseHTTPRequestHandler):
    server_version = "dbadmin"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def client_ip(self) -> str:
        peer = self.client_address[0]
        if peer not in {"127.0.0.1", "::1"}:
            return peer
        forwarded = (self.headers.get("X-Real-IP") or "").strip()
        if valid_ipv4(forwarded):
            return forwarded
        return peer

    def allowed(self) -> bool:
        ip = self.client_ip()
        if ip in {"127.0.0.1", "::1"}:
            return True
        return ip in allowed_ips()

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > MAX_BODY:
            raise ValueError("corpo grande demais")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("json inválido")
        return data

    def send_bytes(self, code: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code: int, payload: dict, extra: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_bytes(code, body, "application/json; charset=utf-8", extra)

    def send_file(self, name: str, content_type: str) -> None:
        path = PANEL / name
        if not path.exists():
            self.send_json(404, {"error": "não encontrado"})
            return
        self.send_bytes(200, path.read_bytes(), content_type)

    def cookie_token(self) -> str:
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "dbadmin":
                return value
        return ""

    def session(self) -> dict | None:
        token = self.cookie_token()
        if not token:
            return None
        with LOCK:
            row = SESSIONS.get(token)
        if not row:
            return None
        if row["exp"] < time.time():
            with LOCK:
                SESSIONS.pop(token, None)
            return None
        return row

    def require_session(self) -> dict | None:
        row = self.session()
        if row is None:
            self.send_json(401, {"error": "Entre com usuário e senha."})
            return None
        if self.command == "POST":
            csrf = self.headers.get("X-CSRF") or ""
            if not csrf or not hmac.compare_digest(csrf, row["csrf"]):
                self.send_json(403, {"error": "Sessão inválida. Entre de novo."})
                return None
        return row

    def set_session_cookie(self, token: str) -> dict:
        secure = (self.headers.get("X-Forwarded-Proto") or "").lower() == "https"
        flag = "; Secure" if secure else ""
        return {
            "Set-Cookie": (
                f"dbadmin={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}{flag}"
            )
        }

    def clear_cookie(self) -> dict:
        return {"Set-Cookie": "dbadmin=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"}

    def too_many_attempts(self, ip: str) -> bool:
        now = time.time()
        with LOCK:
            recent = [stamp for stamp in ATTEMPTS.get(ip, []) if now - stamp < 600]
            ATTEMPTS[ip] = recent
            return len(recent) >= 8

    def mark_attempt(self, ip: str) -> None:
        with LOCK:
            ATTEMPTS.setdefault(ip, []).append(time.time())

    def do_GET(self) -> None:  # noqa: N802
        if not self.allowed():
            self.send_json(403, {"error": "Este endereço não está liberado."})
            return
        path = urlparse(self.path).path
        if path == "/":
            self.send_file("index.html", "text/html; charset=utf-8")
            return
        if path == "/app.css":
            self.send_file("app.css", "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self.send_file("app.js", "text/javascript; charset=utf-8")
            return
        if path == "/api/health":
            self.send_json(200, {"ok": True})
            return
        if path == "/api/session":
            row = self.session()
            if not row:
                self.send_json(401, {"error": "sem sessão"})
                return
            auth = load_auth()
            self.send_json(200, {"user": auth["username"], "csrf": row["csrf"]})
            return
        row = self.require_session()
        if not row:
            return
        try:
            if path == "/api/overview":
                self.send_json(200, overview())
            elif path == "/api/containers":
                self.send_json(200, {"items": cached("containers", 8, docker_ps)})
            elif path == "/api/databases":
                self.send_json(200, databases_snapshot())
            elif path == "/api/access":
                self.send_json(200, access_snapshot())
            elif path == "/api/backups":
                self.send_json(200, backup_status())
            else:
                self.send_json(404, {"error": "não encontrado"})
        except Exception as exc:  # noqa: BLE001
            self.send_json(500, {"error": f"Falha ao ler os dados: {exc}"})

    def do_POST(self) -> None:  # noqa: N802
        if not self.allowed():
            self.send_json(403, {"error": "Este endereço não está liberado."})
            return
        path = urlparse(self.path).path
        try:
            data = self.read_json()
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "Pedido inválido."})
            return
        if path == "/api/login":
            self.handle_login(data)
            return
        row = self.require_session()
        if not row:
            return
        try:
            if path == "/api/logout":
                with LOCK:
                    SESSIONS.pop(self.cookie_token(), None)
                self.send_json(200, {"ok": True}, self.clear_cookie())
            elif path == "/api/access/lab-ip":
                ok, message = update_lab_ip(str(data.get("ip", "")).strip())
                self.send_json(200 if ok else 400, {"ok": ok, "message": message})
            elif path == "/api/backups/run":
                raw = data.get("engines")
                if not isinstance(raw, list):
                    self.send_json(400, {"ok": False, "message": "Escolha PostgreSQL, MySQL ou os dois."})
                else:
                    ok, message = start_backup([str(item) for item in raw])
                    if ok:
                        status = 200
                    elif "andamento" in message:
                        status = 409
                    else:
                        status = 400
                    self.send_json(status, {"ok": ok, "message": message})
            elif path == "/api/password":
                self.handle_password(data)
            else:
                self.send_json(404, {"error": "não encontrado"})
        except Exception as exc:  # noqa: BLE001
            self.send_json(500, {"error": f"Falha: {exc}"})

    def handle_login(self, data: dict) -> None:
        ip = self.client_ip()
        if self.too_many_attempts(ip):
            self.send_json(429, {"error": "Muitas tentativas. Espere alguns minutos."})
            return
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))[:200]
        auth = load_auth()
        user_ok = hmac.compare_digest(username, auth["username"])
        pass_ok = check_password(password) if user_ok else check_password("x" * 8)
        if not (user_ok and pass_ok):
            self.mark_attempt(ip)
            self.send_json(401, {"error": "Usuário ou senha incorretos."})
            return
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        with LOCK:
            SESSIONS[token] = {"exp": time.time() + SESSION_TTL, "csrf": csrf}
        self.send_json(200, {"ok": True, "user": auth["username"], "csrf": csrf}, self.set_session_cookie(token))

    def handle_password(self, data: dict) -> None:
        current = str(data.get("current", ""))[:200]
        new = str(data.get("new", ""))[:200]
        if not check_password(current):
            self.send_json(401, {"error": "Senha atual incorreta."})
            return
        if len(new) < 12:
            self.send_json(400, {"error": "A nova senha precisa ter pelo menos 12 caracteres."})
            return
        save_password(new)
        token = self.cookie_token()
        with LOCK:
            csrf = SESSIONS.get(token, {}).get("csrf", "")
            SESSIONS.clear()
            if token and csrf:
                SESSIONS[token] = {"exp": time.time() + SESSION_TTL, "csrf": csrf}
        self.send_json(200, {"ok": True, "message": "Senha alterada."})


def main() -> None:
    os.umask(0o077)
    PANEL.mkdir(parents=True, exist_ok=True)
    ensure_auth()
    ok, message = sync_panel_firewall()
    if not ok:
        print(f"aviso firewall/nginx: {message}", flush=True)
    else:
        print(message, flush=True)
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"painel em http://{BIND}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
