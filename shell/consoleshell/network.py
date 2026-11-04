"""Réseau via nmcli : état, Wi-Fi (recherche, connexion, oubli), adresse IP."""
import socket

from .util import run


def split_terse(line):
    """Découpe une ligne « nmcli -t » (les ':' et '\\' sont échappés par '\\')."""
    fields, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    fields.append("".join(cur))
    return fields


def _nmcli(*args, timeout=15):
    return run(["nmcli", "-t", *args], timeout=timeout)


def status():
    code, out, _ = _nmcli("-f", "TYPE,STATE,CONNECTION,DEVICE", "device")
    if code != 0:
        return {"kind": "unknown", "connected": False}
    best = {"kind": "none", "connected": False}
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) < 4:
            continue
        kind, state, conn, dev = f
        if state != "connected" or kind not in ("ethernet", "wifi"):
            continue
        info = {"kind": kind, "connected": True, "name": conn, "device": dev}
        if kind == "wifi":
            info["signal"] = wifi_signal()
        info["ip"] = ip_of(dev)
        if kind == "ethernet" or best["kind"] != "ethernet":
            best = info
    best["hostname"] = socket.gethostname()
    return best


def ip_of(dev):
    code, out, _ = run(["nmcli", "-g", "IP4.ADDRESS", "device", "show", dev])
    if code == 0 and out.strip():
        return out.strip().split("|")[0].split("/")[0].strip()
    return None


def wifi_signal():
    code, out, _ = _nmcli("-f", "IN-USE,SIGNAL", "device", "wifi", "list", "--rescan", "no")
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) >= 2 and f[0] == "*":
            try:
                return int(f[1])
            except ValueError:
                return None
    return None


def scan(rescan=True):
    if rescan:
        _nmcli("device", "wifi", "rescan", timeout=20)
    code, out, _ = _nmcli("-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "no")
    nets = {}
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) < 4 or not f[1]:
            continue
        in_use, ssid, signal, security = f[0] == "*", f[1], f[2], f[3]
        try:
            signal = int(signal)
        except ValueError:
            signal = 0
        prev = nets.get(ssid)
        if prev is None or signal > prev["signal"] or in_use:
            nets[ssid] = {"ssid": ssid, "signal": signal, "secure": bool(security and security != "--"),
                          "active": in_use or (prev or {}).get("active", False)}
    known = set(saved())
    for n in nets.values():
        n["known"] = n["ssid"] in known
    return sorted(nets.values(), key=lambda n: (not n["active"], -n["signal"]))


def saved():
    code, out, _ = _nmcli("-f", "NAME,TYPE", "connection", "show")
    return [split_terse(l)[0] for l in out.splitlines() if l.endswith(":802-11-wireless")]


def connect(ssid, password=None):
    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if password:
        cmd += ["password", password]
    code, out, err = run(cmd, timeout=60)
    if code == 0:
        return True, None
    msg = (err or out).strip().splitlines()
    return False, (msg[-1] if msg else "échec de la connexion")


def forget(ssid):
    code, _, err = run(["nmcli", "connection", "delete", "id", ssid])
    return code == 0, err.strip() or None
