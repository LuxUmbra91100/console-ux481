"""Sortie audio : HDMI (la TV) par défaut, volume, détection de lecture en cours."""
import json
import os
import re

from .config import STATE_DIR
from .util import log, read_json, run, write_json

KNOWN_PATH = os.path.join(STATE_DIR, "audio.json")


def _pactl_json(*args):
    code, out, _ = run(["pactl", "-f", "json", *args], timeout=5)
    if code != 0 or not out.strip():
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def _is_hdmi(text):
    t = (text or "").lower()
    return "hdmi" in t or "displayport" in t


def choose_sink(sinks):
    """Choisit le meilleur récepteur HDMI. Renvoie (sink, port à activer ou None)."""
    best = None
    for s in sinks or []:
        ports = s.get("ports") or []
        hdmi_ports = [p for p in ports if _is_hdmi(p.get("name")) or _is_hdmi(p.get("description"))]
        if not hdmi_ports and not (_is_hdmi(s.get("name")) or _is_hdmi(s.get("description"))):
            continue
        usable = [p for p in hdmi_ports if p.get("availability") != "not available"]
        if hdmi_ports and not usable:
            continue
        plugged = [p for p in usable if p.get("availability") == "available"]
        score = (2 if plugged else 0) + (1 if s.get("active_port") in {p["name"] for p in usable} else 0)
        port = None
        if usable and s.get("active_port") not in {p["name"] for p in usable}:
            port = (plugged or usable)[0]["name"]
        if best is None or score > best[0]:
            best = (score, s, port)
    return (best[1], best[2]) if best else (None, None)


class Audio:
    def __init__(self):
        self.known = set(read_json(KNOWN_PATH, []) or [])
        self._profile_tried = False

    def select_hdmi(self):
        sink, port = choose_sink(_pactl_json("list", "sinks"))
        if sink is None:
            if not self._profile_tried and self._switch_card_profile():
                self._profile_tried = True
                return self.select_hdmi()
            return None
        name = sink["name"]
        if port:
            run(["pactl", "set-sink-port", name, port])
        _, current, _ = run(["pactl", "get-default-sink"])
        if current.strip() != name:
            run(["pactl", "set-default-sink", name])
            log.info("sortie audio : %s", sink.get("description", name))
        if name not in self.known:
            # 1re fois : volume à 100 % (c'est la TV qui règle le volume)
            run(["pactl", "set-sink-volume", name, "100%"])
            run(["pactl", "set-sink-mute", name, "0"])
            self.known.add(name)
            write_json(KNOWN_PATH, sorted(self.known))
        return name

    def _switch_card_profile(self):
        for card in _pactl_json("list", "cards") or []:
            if _is_hdmi(card.get("active_profile")):
                continue
            profiles = card.get("profiles") or {}
            candidates = [(n, p) for n, p in profiles.items()
                          if _is_hdmi(n) and p.get("available", True) and p.get("sinks", 1)]
            if not candidates:
                continue
            # le profil HDMI le plus prioritaire, sans entrée micro si possible
            name, _ = max(candidates, key=lambda np: (np[1].get("sources", 0) == 0, np[1].get("priority", 0)))
            log.info("profil audio %s → %s", card.get("name"), name)
            run(["pactl", "set-card-profile", card["name"], name])
            return True
        return False

    def volume(self, arg):
        if arg == "mute":
            run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
        else:
            try:
                delta = int(arg)
            except (TypeError, ValueError):
                delta = 0
            if delta:
                run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
                run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{delta:+d}%"])
        return self.get_volume()

    def set_volume(self, percent):
        percent = max(0, min(100, int(percent)))
        run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"])
        return self.get_volume()

    def get_volume(self):
        _, out, _ = run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
        m = re.search(r"(\d+)%", out)
        _, mute, _ = run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
        return {"volume": min(150, int(m.group(1))) if m else None, "muted": "yes" in mute.lower()}

    def playing(self):
        """Vrai si un son est en cours (musique, vidéo…) : on ne met pas en veille."""
        for s in _pactl_json("list", "sink-inputs") or []:
            if not s.get("corked", False):
                props = s.get("properties") or {}
                if props.get("application.name") in ("console-shell", "WebKit"):
                    continue
                return True
        return False
