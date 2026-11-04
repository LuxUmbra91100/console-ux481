"""Client minimal du protocole IPC de sway (compatible i3-ipc)."""
import glob
import json
import os
import socket
import struct
import threading

from .util import log

MAGIC = b"i3-ipc"
HEADER = struct.Struct("=6sII")

RUN_COMMAND, GET_WORKSPACES, SUBSCRIBE, GET_OUTPUTS, GET_TREE = 0, 1, 2, 3, 4
GET_VERSION, GET_INPUTS, GET_SEATS = 7, 100, 101

EVENT_NAMES = {
    0x80000000: "workspace", 0x80000001: "output", 0x80000002: "mode",
    0x80000003: "window", 0x80000004: "barconfig_update", 0x80000005: "binding",
    0x80000006: "shutdown", 0x80000007: "tick", 0x80000014: "bar_state_update",
    0x80000015: "input",
}


def socket_path():
    path = os.environ.get("SWAYSOCK")
    if path and os.path.exists(path):
        return path
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    candidates = sorted(glob.glob(os.path.join(runtime, "sway-ipc.*.sock")), key=os.path.getmtime)
    return candidates[-1] if candidates else None


def _recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("sway IPC fermé")
        buf += chunk
    return bytes(buf)


def _read_message(sock):
    magic, length, msg_type = HEADER.unpack(_recv_exact(sock, HEADER.size))
    if magic != MAGIC:
        raise ConnectionError("réponse IPC invalide")
    payload = _recv_exact(sock, length) if length else b""
    return msg_type, json.loads(payload.decode("utf-8")) if payload else None


class Sway:
    """Connexion synchrone pour les commandes (protégée par un verrou)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sock = None

    def _connect(self):
        path = socket_path()
        if not path:
            raise ConnectionError("socket sway introuvable")
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(path)
        self._sock = s

    def request(self, msg_type, payload=""):
        data = payload.encode("utf-8")
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._sock is None:
                        self._connect()
                    self._sock.sendall(HEADER.pack(MAGIC, len(data), msg_type) + data)
                    _, reply = _read_message(self._sock)
                    return reply
                except (OSError, ConnectionError, ValueError) as exc:
                    if self._sock:
                        self._sock.close()
                    self._sock = None
                    if attempt == 2:
                        log.warning("sway IPC : %s", exc)
                        return None
        return None

    def command(self, cmd):
        log.debug("swaymsg %s", cmd)
        reply = self.request(RUN_COMMAND, cmd)
        if reply:
            for r in reply:
                if not r.get("success", False):
                    log.debug("commande sway refusée (%s) : %s", cmd, r.get("error"))
        return reply

    def tree(self):
        return self.request(GET_TREE) or {}

    def outputs(self):
        return self.request(GET_OUTPUTS) or []

    def workspaces(self):
        return self.request(GET_WORKSPACES) or []

    def focused_workspace(self):
        for ws in self.workspaces():
            if ws.get("focused"):
                return ws.get("name")
        return None

    def views(self):
        """Toutes les fenêtres (conteneurs avec pid), avec le nom de leur espace de travail."""
        found = []

        def walk(node, workspace):
            if node.get("type") == "workspace":
                workspace = node.get("name")
            if node.get("pid") and node.get("type") in ("con", "floating_con"):
                node["_workspace"] = workspace
                found.append(node)
            for child in node.get("nodes", []) + node.get("floating_nodes", []):
                walk(child, workspace)

        walk(self.tree(), None)
        return found

    def focused_view(self):
        for v in self.views():
            if v.get("focused"):
                return v
        return None


class SwayEvents(threading.Thread):
    """Thread qui reçoit les évènements sway et appelle callback(nom, données)."""

    def __init__(self, callback, events=("window", "workspace", "output", "shutdown")):
        super().__init__(name="sway-events", daemon=True)
        self.callback = callback
        self.events = list(events)
        self.running = True

    def run(self):
        import time
        while self.running:
            try:
                path = socket_path()
                if not path:
                    raise ConnectionError("socket sway introuvable")
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(path)
                data = json.dumps(self.events).encode()
                s.sendall(HEADER.pack(MAGIC, len(data), SUBSCRIBE) + data)
                _read_message(s)
                while self.running:
                    msg_type, payload = _read_message(s)
                    name = EVENT_NAMES.get(msg_type)
                    if name:
                        self.callback(name, payload)
            except (OSError, ConnectionError, ValueError) as exc:
                log.warning("évènements sway interrompus : %s", exc)
                time.sleep(1.0)
