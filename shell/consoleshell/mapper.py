"""Souris + clavier virtuels (uinput) pilotés par la manette, pour le navigateur.

Mode « pointer » (navigation web classique) :
  stick gauche = pointeur · stick droit = défilement · A = clic (ou Entrée si on
  navigue à la croix) · B = page précédente · X = clavier virtuel · Y = adresse ·
  LB/RB = onglet précédent/suivant · LT/RT = zoom − / + · L3 = clic droit ·
  R3 = zoom 100 % · Vue = Échap · Menu = menu du navigateur.
Mode « tv » (sites conçus pour la télé, ex. YouTube TV) :
  croix/stick = flèches · A = Entrée · B = Échap (retour) · X/Y = clavier/adresse.
Les raccourcis n'utilisent que des touches indépendantes de la disposition
(AZERTY/QWERTY) : flèches, Entrée, F-keys, pavé numérique…
"""
import math
import threading
import time

from .util import log

try:
    from evdev import UInput, ecodes as E
except Exception as exc:  # noqa: BLE001
    UInput = None
    E = None
    log.error("python3-evdev indisponible : %s", exc)

REL_WHEEL_HI_RES = 0x0B
REL_HWHEEL_HI_RES = 0x0C


def _keys():
    names = [
        "KEY_LEFTCTRL", "KEY_RIGHTCTRL", "KEY_LEFTSHIFT", "KEY_RIGHTSHIFT", "KEY_LEFTALT",
        "KEY_RIGHTALT", "KEY_LEFTMETA", "KEY_ESC", "KEY_ENTER", "KEY_TAB", "KEY_BACKSPACE",
        "KEY_SPACE", "KEY_DELETE", "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT", "KEY_HOME",
        "KEY_END", "KEY_PAGEUP", "KEY_PAGEDOWN", "KEY_KPPLUS", "KEY_KPMINUS", "KEY_KP0",
        "KEY_KPENTER", "KEY_BACK", "KEY_FORWARD", "KEY_REFRESH", "KEY_PAUSE", "KEY_SYSRQ",
    ]
    names += [f"KEY_F{i}" for i in range(1, 13)]
    names += [f"KEY_{c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    names += [f"KEY_{d}" for d in "0123456789"]
    return [getattr(E, n) for n in names if hasattr(E, n)]


class Mapper:
    def __init__(self):
        self.lock = threading.Lock()
        self.mouse = None
        self.kbd = None
        self.frac = [0.0, 0.0, 0.0, 0.0]   # restes sub-pixel : x, y, molette v, molette h
        self.wheel_acc = [0, 0]
        self.held_buttons = set()
        self.last_nav = "stick"           # « stick » ou « dpad » : décide de A = clic ou Entrée
        self.last_click = 0.0
        self.speed = 1500.0               # px/s stick à fond
        self.scroll_speed = 2600.0        # unités haute résolution/s (120 = 1 cran)
        if UInput is None:
            return
        try:
            self.mouse = UInput(
                {E.EV_KEY: [E.BTN_LEFT, E.BTN_RIGHT, E.BTN_MIDDLE, E.BTN_SIDE, E.BTN_EXTRA],
                 E.EV_REL: [E.REL_X, E.REL_Y, E.REL_WHEEL, E.REL_HWHEEL,
                            REL_WHEEL_HI_RES, REL_HWHEEL_HI_RES]},
                name="Console Virtual Mouse", vendor=0x1D6B, product=0x0104, version=1)
            self.kbd = UInput({E.EV_KEY: _keys()}, name="Console Virtual Keyboard",
                              vendor=0x1D6B, product=0x0105, version=1)
            log.info("souris/clavier virtuels prêts")
        except Exception as exc:  # noqa: BLE001
            log.error("uinput indisponible (%s) : le navigateur ne sera pas pilotable", exc)
            self.mouse = self.kbd = None

    @property
    def ok(self):
        return self.mouse is not None

    # --------------------------------------------------------- primitives --
    def key(self, *combo):
        """Appuie puis relâche une combinaison, ex : key('KEY_LEFTCTRL', 'KEY_TAB')."""
        if not self.kbd:
            return
        codes = [getattr(E, k) if isinstance(k, str) else k for k in combo]
        with self.lock:
            for c in codes:
                self.kbd.write(E.EV_KEY, c, 1)
                self.kbd.syn()
            for c in reversed(codes):
                self.kbd.write(E.EV_KEY, c, 0)
                self.kbd.syn()

    def button(self, btn, pressed):
        if not self.mouse:
            return
        code = getattr(E, btn)
        with self.lock:
            self.mouse.write(E.EV_KEY, code, 1 if pressed else 0)
            self.mouse.syn()
        if pressed:
            self.held_buttons.add(btn)
            self.last_click = time.monotonic()
        else:
            self.held_buttons.discard(btn)

    def release_all(self):
        for btn in list(self.held_buttons):
            self.button(btn, False)

    def nudge(self):
        """Petit mouvement aller-retour : fait réapparaître le pointeur caché."""
        if not self.mouse:
            return
        with self.lock:
            self.mouse.write(E.EV_REL, E.REL_X, 1)
            self.mouse.syn()
            self.mouse.write(E.EV_REL, E.REL_X, -1)
            self.mouse.syn()

    # ------------------------------------------------------------- boucle --
    @staticmethod
    def _curve(v, dead=0.14):
        a = abs(v)
        if a < dead:
            return 0.0
        a = (a - dead) / (1.0 - dead)
        return math.copysign(0.15 * a + 0.85 * a ** 2.4, v)

    def tick(self, dt, axes, mode):
        if not self.mouse or mode != "pointer" or dt <= 0 or dt > 0.2:
            return
        lx, ly, rx, ry = (self._curve(a) for a in axes[:4])
        dx = lx * self.speed * dt + self.frac[0]
        dy = ly * self.speed * dt + self.frac[1]
        ix, iy = int(dx), int(dy)
        self.frac[0], self.frac[1] = dx - ix, dy - iy
        if lx or ly:
            self.last_nav = "stick"
        sv = -ry * self.scroll_speed * dt + self.frac[2]
        sh = rx * self.scroll_speed * 0.6 * dt + self.frac[3]
        iv, ih = int(sv), int(sh)
        self.frac[2], self.frac[3] = sv - iv, sh - ih
        if not (ix or iy or iv or ih):
            return
        with self.lock:
            if ix:
                self.mouse.write(E.EV_REL, E.REL_X, ix)
            if iy:
                self.mouse.write(E.EV_REL, E.REL_Y, iy)
            if iv:
                self.mouse.write(E.EV_REL, REL_WHEEL_HI_RES, iv)
                self.wheel_acc[0] += iv
                notches = int(self.wheel_acc[0] / 120)
                if notches:
                    self.wheel_acc[0] -= notches * 120
                    self.mouse.write(E.EV_REL, E.REL_WHEEL, notches)
            if ih:
                self.mouse.write(E.EV_REL, REL_HWHEEL_HI_RES, ih)
                self.wheel_acc[1] += ih
                notches = int(self.wheel_acc[1] / 120)
                if notches:
                    self.wheel_acc[1] -= notches * 120
                    self.mouse.write(E.EV_REL, E.REL_HWHEEL, notches)
            self.mouse.syn()

    # ------------------------------------------------------------ boutons --
    def on_button(self, name, pressed, mode, repeat=False):
        """Renvoie une « action » à traiter par le shell (menu, clavier…) ou None."""
        if not self.ok:
            return None
        arrows = {"up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT"}
        if name in arrows:
            if pressed:
                self.last_nav = "dpad"
                self.key(arrows[name])
            return None
        if mode == "tv":
            if not pressed:
                return None
            return {"a": lambda: self.key("KEY_ENTER"),
                    "b": lambda: self.key("KEY_ESC"),
                    "back": lambda: self.key("KEY_ESC"),
                    "x": lambda: "osk", "y": lambda: "url", "start": lambda: "menu",
                    "lb": lambda: self.key("KEY_LEFTCTRL", "KEY_PAGEUP"),
                    "rb": lambda: self.key("KEY_LEFTCTRL", "KEY_PAGEDOWN"),
                    }.get(name, lambda: None)()
        # mode « pointer »
        if name == "a":
            if self.last_nav == "dpad":
                if pressed:
                    self.key("KEY_ENTER")
                    self.last_click = time.monotonic()
            else:
                self.button("BTN_LEFT", pressed)
            return None
        if name == "ls":
            self.button("BTN_RIGHT", pressed)
            return None
        if not pressed:
            return None
        if name == "b":
            self.key("KEY_LEFTALT", "KEY_LEFT")
        elif name == "back":
            self.key("KEY_ESC")
        elif name == "lb":
            self.key("KEY_LEFTCTRL", "KEY_PAGEUP")
        elif name == "rb":
            self.key("KEY_LEFTCTRL", "KEY_PAGEDOWN")
        elif name == "lt":
            self.key("KEY_LEFTCTRL", "KEY_KPMINUS")
        elif name == "rt":
            self.key("KEY_LEFTCTRL", "KEY_KPPLUS")
        elif name == "rs":
            self.key("KEY_LEFTCTRL", "KEY_KP0")
        elif name == "x":
            return "osk"
        elif name == "y":
            return "url"
        elif name == "start":
            return "menu"
        return None
