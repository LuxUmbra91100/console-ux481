"""Moonlight : PC appairés et leurs applications (lus dans la config de moonlight-qt),
état en ligne des PC (Sunshine/GameStream), jaquettes, lancement direct d'un stream."""
import os
import re
import socket
import subprocess
import xml.etree.ElementTree as ET
import urllib.request

from .config import HOME
from .util import log

FLATPAK_ID = "com.moonlight_stream.Moonlight"
ORG_APP = os.path.join("Moonlight Game Streaming Project")
CONF_CANDIDATES = [
    os.path.join(HOME, ".var/app", FLATPAK_ID, "config", ORG_APP, "Moonlight.conf"),
    os.path.join(HOME, ".config", ORG_APP, "Moonlight.conf"),
]
BOXART_CANDIDATES = [
    os.path.join(HOME, ".var/app", FLATPAK_ID, "cache", ORG_APP, "Moonlight", "boxart"),
    os.path.join(HOME, ".cache", ORG_APP, "Moonlight", "boxart"),
]
DEFAULT_PORT = 47989
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_ESCAPES = {"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v",
            "\\": "\\", '"': '"', "'": "'", "?": "?", "0": "\0", ";": ";", ",": ",", "=": "="}
HEX = "0123456789abcdefABCDEF"


def qs_unescape(raw):
    """Décode une valeur QSettings (guillemets, \\xhh, @ByteArray(...))."""
    raw = raw.strip()
    out, i, quoted = [], 0, False
    while i < len(raw):
        ch = raw[i]
        if ch == '"':
            quoted = not quoted
            i += 1
        elif ch == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt == "x":
                j = i + 2
                while j < len(raw) and raw[j] in HEX:
                    j += 1
                if j > i + 2:
                    out.append(chr(int(raw[i + 2:j], 16) & 0xFFFF))
                i = j
            else:
                out.append(_ESCAPES.get(nxt, nxt))
                i += 2
        else:
            out.append(ch)
            i += 1
    value = "".join(out)
    if value.startswith("@ByteArray(") and value.endswith(")"):
        return value[11:-1].encode("latin-1", errors="replace")
    return value


def parse_ini(text):
    current = {}
    sections = {"General": current}
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], {})
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            current[key.strip()] = qs_unescape(value)
    return sections


def config_path():
    for path in CONF_CANDIDATES:
        if os.path.exists(path):
            return path
    return CONF_CANDIDATES[0]


def _bool(v):
    return str(v).lower() == "true"


def load_hosts(path=None):
    path = path or config_path()
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            sections = parse_ini(f.read())
    except OSError:
        return []
    raw = sections.get("hosts", {})
    try:
        count = int(raw.get("size", "0"))
    except ValueError:
        count = 0
    hosts = []
    for i in range(1, count + 1):
        g = lambda k, i=i: raw.get(f"{i}\\{k}", "")  # noqa: E731
        uuid = g("uuid")
        if not uuid:
            continue
        mac = g("mac")
        mac_str = ":".join(f"{b:02X}" for b in mac) if isinstance(mac, bytes) and len(mac) == 6 else ""
        addresses = []
        for key in ("manualaddress", "localaddress", "remoteaddress", "ipv6address"):
            addr = g(key)
            if isinstance(addr, str) and addr:
                port_key = key.replace("address", "port")
                try:
                    port = int(g(port_key) or DEFAULT_PORT)
                except ValueError:
                    port = DEFAULT_PORT
                addresses.append((addr, port or DEFAULT_PORT))
        apps = []
        try:
            app_count = int(g("apps\\size") or 0)
        except ValueError:
            app_count = 0
        for j in range(1, app_count + 1):
            name = g(f"apps\\{j}\\name")
            if not name or _bool(g(f"apps\\{j}\\hidden")):
                continue
            try:
                app_id = int(g(f"apps\\{j}\\id") or 0)
            except ValueError:
                app_id = 0
            apps.append({"id": app_id, "name": name, "hdr": _bool(g(f"apps\\{j}\\hdr")),
                         "boxart": boxart(uuid, app_id)})
        hosts.append({"uuid": uuid, "name": g("customname") or g("hostname") or "PC", "mac": mac_str,
                      "addresses": addresses, "apps": apps})
    return hosts


def boxart(uuid, app_id):
    for base in BOXART_CANDIDATES:
        p = os.path.join(base, uuid, f"{app_id}.png")
        if os.path.exists(p):
            return p
    return None


def server_status(host):
    """Interroge http://pc:47989/serverinfo.

    Renvoie {"online", "busy", "currentgame"} et, si le PC répond, l'adresse qui a répondu
    ("address", "port") et le port HTTPS des appareils appairés ("https_port").
    """
    for raw_addr, port in host.get("addresses", []):
        addr = raw_addr
        if ":" in addr and not addr.startswith("["):
            addr = f"[{addr}]"
        url = f"http://{addr}:{port}/serverinfo"
        try:
            with _OPENER.open(url, timeout=1.2) as r:
                root = ET.fromstring(r.read())
        except Exception:  # noqa: BLE001
            continue
        if root.get("status_code", "200") != "200":
            continue
        state = (root.findtext("state") or "").upper()
        busy = state.endswith("_SERVER_BUSY")
        game = root.findtext("currentgame") or "0"
        try:
            game = int(game) if busy else 0
        except ValueError:
            game = 0
        try:
            https_port = int(root.findtext("HttpsPort") or 0) or port - 5
        except ValueError:
            https_port = port - 5
        return {"online": True, "busy": busy, "currentgame": game,
                "address": raw_addr.strip("[]"), "port": port, "https_port": https_port}
    return {"online": False, "busy": False, "currentgame": 0}


def find_app(host, wanted):
    """Retrouve une appli du PC par son nom (« Steam Big Picture » reconnu même renommée)."""
    if not host or not wanted:
        return None
    apps = host.get("apps") or []
    w = wanted.strip().lower()
    for a in apps:
        if a["name"].strip().lower() == w:
            return a
    if "big picture" in w or w == "steam":
        for a in apps:
            n = a["name"].lower()
            if "big picture" in n or n == "steam":
                return a
    return None


def magic_packet(mac):
    raw = bytes.fromhex(re.sub(r"[^0-9a-fA-F]", "", mac))
    if len(raw) != 6:
        raise ValueError("adresse MAC invalide")
    return b"\xff" * 6 + raw * 16


def broadcast_addresses():
    out = {"255.255.255.255"}
    try:
        res = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"],
                             capture_output=True, text=True, timeout=3)
        out.update(re.findall(r"\bbrd\s+(\d+\.\d+\.\d+\.\d+)", res.stdout))
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def wake(host):
    """Envoie un paquet Wake-on-LAN (diffusion + dernière adresse connue du PC)."""
    if not host or not host.get("mac"):
        return False
    try:
        pkt = magic_packet(host["mac"])
    except ValueError:
        return False
    targets = broadcast_addresses()
    targets.update(a for a, _ in host.get("addresses", []) if re.match(r"^\d+\.\d+\.\d+\.\d+$", a))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for target in targets:
            for port in (9, 7, 47009):
                try:
                    s.sendto(pkt, (target, port))
                except OSError:
                    pass
    return True


def flatpak_cmd(*args):
    override = os.environ.get("CONSOLE_MOONLIGHT_CMD")   # tests / version de Moonlight personnalisée
    if override:
        import shlex
        return [*shlex.split(override), *args]
    if os.path.exists(f"/var/lib/flatpak/exports/bin/{FLATPAK_ID}") or \
       os.path.exists(os.path.join(HOME, ".local/share/flatpak/exports/bin", FLATPAK_ID)):
        return ["flatpak", "run", FLATPAK_ID, *args]
    return ["moonlight", *args]


def stream_cmd(host_uuid, app_name):
    return flatpak_cmd("stream", host_uuid, app_name)


def gui_cmd():
    return flatpak_cmd()


_SAFE = re.compile(r"[^\w .,'()&!+-]")


def describe(hosts, status):
    """Données prêtes pour l'interface."""
    out = []
    for h in hosts:
        st = status.get(h["uuid"], {"online": None})
        current = next((a["name"] for a in h["apps"] if a["id"] and a["id"] == st.get("currentgame")), None)
        out.append({"uuid": h["uuid"], "name": h["name"], "online": st.get("online"), "busy": st.get("busy"),
                    "current": current, "wol": bool(h["mac"]), "apps": h["apps"],
                    "sunshine": st.get("sunshine")})       # ok | half (port appairé muet) | None
    return out


if __name__ == "__main__":  # diagnostic : python3 -m consoleshell.moonlight
    import json
    hs = load_hosts()
    print(json.dumps(hs, indent=2, default=str))
    for h in hs:
        log.info("%s : %s", h["name"], server_status(h))
