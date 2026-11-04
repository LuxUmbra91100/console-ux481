"""Configuration manette des émulateurs qui identifient la manette par son nom (Dolphin).

PCSX2 (« SDL-0 ») et Azahar (« toutes les manettes ») sont configurés une fois pour
toutes par l'installateur ; RetroArch se configure tout seul (autoconfig).
Dolphin, lui, attend le nom exact de la manette (« SDL/0/<nom> ») : on l'écrit à la
connexion de la manette, puis on le corrige d'après le journal de Dolphin si besoin.
"""
import os
import re

from .config import HOME
from .util import atomic_write, log

DOLPHIN_DIR = os.path.join(HOME, ".var/app/org.DolphinEmu.dolphin-emu")
DOLPHIN_CFG = os.path.join(DOLPHIN_DIR, "config/dolphin-emu")
DOLPHIN_LOG = os.path.join(DOLPHIN_DIR, "data/dolphin-emu/Logs/dolphin.log")
ADDED_RE = re.compile(r"Added device:\s*(SDL/\d+/.+?)\s*$")


def _set_device(path, section, device):
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return False
    out, in_section, changed = [], False, False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped[1:-1] == section
        elif in_section and re.match(r"^Device\s*=", stripped):
            current = stripped.split("=", 1)[1].strip()
            # on ne touche qu'aux réglages « manette SDL » (pas à un clavier choisi à la main)
            if (current.startswith("SDL/") or not current) and current != device:
                line = f"Device = {device}"
                changed = True
        out.append(line)
    if changed:
        atomic_write(path, "\n".join(out) + "\n")
    return changed


def dolphin_set_controller(sdl_name):
    if not sdl_name or not os.path.isdir(DOLPHIN_CFG):
        return
    device = f"SDL/0/{sdl_name}"
    changed = False
    for fname, section in (("GCPadNew.ini", "GCPad1"), ("WiimoteNew.ini", "Wiimote1")):
        changed |= _set_device(os.path.join(DOLPHIN_CFG, fname), section, device)
    if changed:
        log.info("Dolphin : manette réglée sur « %s »", device)


def dolphin_fix_from_log():
    """Après une partie : si Dolphin a vu une manette SDL sous un autre nom, on l'adopte."""
    try:
        with open(DOLPHIN_LOG, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-400:]
    except OSError:
        return
    seen = [m.group(1) for m in (ADDED_RE.search(l) for l in lines) if m]
    if not seen:
        return
    device = seen[-1]
    for fname, section in (("GCPadNew.ini", "GCPad1"), ("WiimoteNew.ini", "Wiimote1")):
        path = os.path.join(DOLPHIN_CFG, fname)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        m = re.search(rf"\[{section}\][^\[]*?^Device\s*=\s*(.*)$", text, re.M | re.S)
        current = m.group(1).strip() if m else ""
        if current not in seen and (current.startswith("SDL/") or not current):
            _set_device(path, section, device)
            log.info("Dolphin : nom de manette corrigé d'après le journal → %s", device)
