"""Santé de la console (Réglages › Santé) : SSD, températures, mémoire, stockage, réseau.

Tout est lu sans droits particuliers, sauf l'état SMART du SSD et le décompte des erreurs d'accès
au disque relevées par le noyau depuis le démarrage : « console-root health » (lecture seule).
"""
import glob
import json
import os
import shutil
import socket
import time

from .config import HOME, PREFIX
from .util import run


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return None


def _milli(path):
    v = _read(path)
    try:
        return round(int(v) / 1000, 1) if v else None
    except ValueError:
        return None


def temperatures(sys_root="/sys"):
    cpu = ssd = None
    for d in sorted(glob.glob(os.path.join(sys_root, "class/hwmon/hwmon*"))):
        name = _read(os.path.join(d, "name"))
        if name == "coretemp" and cpu is None:
            cpu = _milli(os.path.join(d, "temp1_input"))        # « Package id 0 »
        elif name == "nvme" and ssd is None:
            ssd = _milli(os.path.join(d, "temp1_input"))        # « Composite »
    if cpu is None:
        for zone in glob.glob(os.path.join(sys_root, "class/thermal/thermal_zone*")):
            if _read(os.path.join(zone, "type")) in ("x86_pkg_temp", "TCPU", "acpitz"):
                t = _milli(os.path.join(zone, "temp"))
                if t is not None:
                    cpu = max(cpu or t, t)
    return {"cpu": cpu, "ssd": ssd}


def memory(proc="/proc"):
    info = {}
    for line in (_read(os.path.join(proc, "meminfo")) or "").splitlines():
        key, _, val = line.partition(":")
        if val.strip().endswith("kB"):
            info[key] = int(val.split()[0]) * 1024
    return {"total": info.get("MemTotal"), "available": info.get("MemAvailable")}


def root_readonly(proc="/proc"):
    """Après un décrochage du SSD, ext4 se remet en lecture seule : tout échoue ensuite."""
    for line in (_read(os.path.join(proc, "mounts")) or "").splitlines():
        parts = line.split()
        if len(parts) > 3 and parts[1] == "/":
            return parts[3].split(",")[0] == "ro"
    return False


def tailscale():
    code, out, _ = run(["tailscale", "status", "--json"], timeout=5)
    if code == 127:
        return None                                         # pas installé
    try:
        st = json.loads(out)
    except ValueError:
        return {"running": False}
    me = st.get("Self") or {}
    return {"running": st.get("BackendState") == "Running", "ip": (me.get("TailscaleIPs") or [None])[0]}


def latency(addr, port, tries=3):
    """Temps d'ouverture d'une connexion vers Sunshine, en ms (meilleur de quelques essais)."""
    if not addr or not port:
        return None
    best = None
    for _ in range(tries):
        t0 = time.monotonic()
        try:
            socket.create_connection((addr.strip("[]"), int(port)), timeout=2).close()
        except OSError:
            continue
        ms = (time.monotonic() - t0) * 1000
        best = ms if best is None else min(best, ms)
    return round(best) if best is not None else None


def privileged():
    code, out, _ = run(["sudo", "-n", os.path.join(PREFIX, "bin", "console-root"), "health"], timeout=25)
    try:
        return json.loads(out) if code == 0 else None
    except ValueError:
        return None


def smart_summary(smart):
    """Résumé lisible du JSON de smartctl (NVMe, ou SATA à défaut)."""
    if not isinstance(smart, dict):
        return None
    out = {"model": smart.get("model_name"), "passed": (smart.get("smart_status") or {}).get("passed")}
    log = smart.get("nvme_smart_health_information_log")
    if log:
        for key in ("critical_warning", "temperature", "available_spare", "available_spare_threshold",
                    "percentage_used", "media_errors", "unsafe_shutdowns", "power_on_hours"):
            out[key] = log.get(key)
    else:
        out["temperature"] = (smart.get("temperature") or {}).get("current")
        out["power_on_hours"] = (smart.get("power_on_time") or {}).get("hours")
    return out


def collect(full=True):
    total, _used, free = shutil.disk_usage(HOME)
    data = {"time": time.time(), "temps": temperatures(), "memory": memory(),
            "disk": {"total": total, "free": free}, "readonly": root_readonly(),
            "uptime": float((_read("/proc/uptime") or "0").split()[0]), "load": round(os.getloadavg()[0], 2),
            "tailscale": tailscale()}
    if full:
        p = privileged()
        data["privileged"] = p is not None
        data["ssd"] = smart_summary((p or {}).get("smart"))
        data["io_errors"] = (p or {}).get("kernel_io_errors")
    return data


def warnings(data, pcs=(), pads=()):
    """Alertes à afficher en tête de la page : [{"level": "bad"|"warn", "text": …}]."""
    w = []
    ssd = data.get("ssd") or {}
    if data.get("readonly"):
        w.append(("bad", "Le disque est passé en lecture seule (le SSD a décroché) : redémarre la console."))
    if data.get("io_errors"):
        w.append(("bad", f"Le SSD a eu {data['io_errors']} erreur(s) d'accès depuis le démarrage : "
                         "sauvegarde ce qui compte."))
    if ssd.get("critical_warning"):
        w.append(("bad", "Le SSD signale un avertissement critique (SMART)."))
    if ssd.get("media_errors"):
        w.append(("bad", f"Le SSD a enregistré {ssd['media_errors']} erreur(s) de données."))
    if ssd.get("passed") is False:
        w.append(("bad", "Le test de santé SMART du SSD a échoué."))
    if (ssd.get("percentage_used") or 0) >= 90:
        w.append(("warn", f"SSD usé à {ssd['percentage_used']} % : pense à le remplacer."))
    free = (data.get("disk") or {}).get("free")
    if free is not None and free < 10e9:
        w.append(("warn", f"Plus que {free / 1e9:.1f} Go libres."))
    temps = data.get("temps") or {}
    if (temps.get("cpu") or 0) >= 90:
        w.append(("warn", f"Processeur très chaud ({temps['cpu']:.0f} °C) : vérifie l'aération sous le capot."))
    if (temps.get("ssd") or 0) >= 70:
        w.append(("warn", f"SSD très chaud ({temps['ssd']:.0f} °C)."))
    mem = data.get("memory") or {}
    if mem.get("available") is not None and mem["available"] < 300e6:
        w.append(("warn", "Mémoire presque pleine : ferme les applications que tu n'utilises plus."))
    ts = data.get("tailscale")
    if ts is not None and not ts.get("running"):
        w.append(("warn", "Tailscale est déconnecté : le PC distant est injoignable."))
    for pc in pcs:
        if pc.get("online") and pc.get("sunshine") == "half":
            w.append(("warn", f"Sunshine est bloqué sur {pc['name']}."))
    for pad in pads:
        if isinstance(pad.get("battery"), (int, float)) and pad["battery"] <= 20:
            w.append(("warn", f"Batterie de {pad['name']} : {int(pad['battery'])} %."))
    return [{"level": lv, "text": tx} for lv, tx in w]
