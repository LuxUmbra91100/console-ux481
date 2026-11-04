"""Politique d'affichage : la TV (HDMI) seule ; écrans internes et ScreenPad éteints.

Sans écran externe branché, l'écran interne principal sert de secours (installation,
dépannage). La résolution par défaut est 1080p à 60 Hz : idéale pour l'UHD 620 et
nette sur n'importe quelle TV.
"""
from .util import log

INTERNAL_PREFIXES = ("eDP", "LVDS", "DSI")
IGNORED_PREFIXES = ("HEADLESS", "FALLBACK", "NOOP")


def _modes(o):
    modes = list(o.get("modes") or [])
    cm = o.get("current_mode")
    if cm and cm not in modes:
        modes.append(cm)
    return [m for m in modes if m.get("width") and m.get("height")]


def is_screenpad(o):
    """Le ScreenPad Plus (1920×515) : un écran très allongé."""
    return any(m["width"] / m["height"] > 3.0 for m in _modes(o))


def is_internal(o):
    return o.get("name", "").startswith(INTERNAL_PREFIXES) or is_screenpad(o)


def pick_mode(o, policy="1080p"):
    modes = _modes(o)
    if not modes:
        return None
    fluid = [m for m in modes if 49000 <= m.get("refresh", 0) <= 61000]
    if policy == "1080p":
        full_hd = [m for m in fluid if m["width"] == 1920 and m["height"] == 1080]
        if full_hd:
            return max(full_hd, key=lambda m: m["refresh"])
        smaller = [m for m in fluid if m["height"] <= 1080]
        if smaller:
            return max(smaller, key=lambda m: (m["width"] * m["height"], m["refresh"]))
    if fluid:
        return max(fluid, key=lambda m: (m["width"] * m["height"], m["refresh"]))
    return max(modes, key=lambda m: (m["width"] * m["height"], m.get("refresh", 0)))


def scale_for(mode):
    h = mode["height"]
    return 2.0 if h >= 2000 else 1.5 if h >= 1400 else 1.0


def plan(outputs, policy="1080p"):
    """Calcule les commandes sway à envoyer (fonction pure, testée)."""
    outs = [o for o in outputs if not o.get("name", "").startswith(IGNORED_PREFIXES)]
    external = [o for o in outs if not is_internal(o)]
    internal = [o for o in outs if is_internal(o)]
    cmds = []
    if external:
        x = 0
        for o in sorted(external, key=lambda o: o["name"]):
            mode = pick_mode(o, policy)
            if not mode:
                continue
            scale = scale_for(mode)
            cur = o.get("current_mode") or {}
            same = (o.get("active") and cur.get("width") == mode["width"]
                    and cur.get("height") == mode["height"]
                    and abs(cur.get("refresh", 0) - mode["refresh"]) < 100
                    and abs(float(o.get("scale") or 1) - scale) < 0.01)
            if not same:
                cmds.append(f'output "{o["name"]}" enable mode {mode["width"]}x{mode["height"]}'
                            f'@{mode["refresh"] / 1000:.3f}Hz scale {scale:g} position {x} 0')
            x += int(mode["width"] / scale)
        for o in internal:
            if o.get("active"):
                cmds.append(f'output "{o["name"]}" disable')
    else:
        panels = [o for o in internal if not is_screenpad(o)]
        for o in internal:
            if panels and o is panels[0]:
                if not o.get("active"):
                    cmds.append(f'output "{o["name"]}" enable')
            elif o.get("active"):
                cmds.append(f'output "{o["name"]}" disable')
    return cmds, bool(external)


class Display:
    def __init__(self, sway, settings):
        self.sway = sway
        self.settings = settings
        self.has_tv = False

    def apply(self):
        outputs = self.sway.outputs()
        cmds, self.has_tv = plan(outputs, self.settings["resolution"])
        for c in cmds:
            log.info("affichage : %s", c)
            self.sway.command(c)
        return self.has_tv

    def power(self, on):
        self.sway.command(f"output * power {'on' if on else 'off'}")

    def summary(self):
        for o in self.sway.outputs():
            if o.get("active") and not is_internal(o):
                m = o.get("current_mode") or {}
                return {"name": o.get("name"), "model": f'{o.get("make", "")} {o.get("model", "")}'.strip(),
                        "width": m.get("width"), "height": m.get("height"),
                        "refresh": round((m.get("refresh") or 0) / 1000)}
        return None
