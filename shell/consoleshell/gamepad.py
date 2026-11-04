"""Lecture des manettes via SDL2 (API GameController), dans un thread dédié.

- Ne prend jamais le contrôle exclusif des manettes : les jeux et émulateurs les
  lisent en parallèle (HIDAPI désactivé, simple lecture evdev).
- Produit des évènements « UI » (boutons avec répétition, stick → croix,
  appui court/long sur le bouton Xbox) envoyés à la boucle principale.
- En mode « navigateur », pilote directement la souris/clavier virtuels
  (latence minimale) via Mapper.
- Pendant un menu de la console ouvert au-dessus d'une appli, lecture EXCLUSIVE
  (EVIOCGRAB) : Moonlight, émulateurs et pages web ne reçoivent plus les appuis
  qui servent à naviguer dans le menu.
"""
import ctypes
import os
import queue
import threading
import time

from .util import log, on_main

os.environ.setdefault("SDL_JOYSTICK_HIDAPI", "0")
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
os.environ.setdefault("SDL_NO_SIGNAL_HANDLERS", "1")

try:
    import sdl2  # python3-sdl2
except Exception as exc:  # noqa: BLE001
    sdl2 = None
    log.error("python3-sdl2 indisponible : %s", exc)

BUTTONS = {
    0: "a", 1: "b", 2: "x", 3: "y", 4: "back", 5: "guide", 6: "start",
    7: "ls", 8: "rs", 9: "lb", 10: "rb", 11: "up", 12: "down", 13: "left",
    14: "right", 15: "share",
}
TYPES = {
    1: "xbox", 2: "xbox", 3: "playstation", 4: "playstation", 5: "nintendo",
    7: "playstation", 11: "nintendo", 12: "nintendo", 13: "nintendo",
}
NAV = ("up", "down", "left", "right")
AXIS_MAX = 32767.0
STICK_ON, STICK_OFF = 0.55, 0.35
TRIGGER_ON, TRIGGER_OFF = 0.6, 0.3
REPEAT_DELAY, REPEAT_RATE, REPEAT_FAST = 0.38, 0.11, 0.06

# Codes evdev (linux/input-event-codes.h) pour la lecture exclusive.
EV_KEY, EV_ABS = 1, 3
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ, ABS_GAS, ABS_BRAKE = 0, 1, 2, 3, 4, 5, 9, 10
ABS_HAT0X, ABS_HAT0Y = 16, 17
RAW_BUTTONS = {
    0x130: "a", 0x131: "b",                       # BTN_SOUTH, BTN_EAST
    0x136: "lb", 0x137: "rb",                     # BTN_TL, BTN_TR
    0x13a: "back", 0x13b: "start", 0x13c: "guide",  # BTN_SELECT, BTN_START, BTN_MODE
    0x13d: "ls", 0x13e: "rs",                     # BTN_THUMBL, BTN_THUMBR
    0x220: "up", 0x221: "down", 0x222: "left", 0x223: "right",  # BTN_DPAD_*
    172: "guide", 158: "back", 167: "share",      # KEY_HOMEPAGE, KEY_BACK, KEY_RECORD (Xbox BLE sans xpadneo)
}


def raw_layout(dev, kind=None):
    """Codes evdev d'une manette → boutons et axes de la console (spécification « gamepad » du noyau)."""
    buttons = dict(RAW_BUTTONS)
    # Xbox (xpad, xpadneo, pilote générique) : BTN_X/BTN_Y = X/Y. PlayStation : nord = Y, ouest = X.
    buttons.update({0x133: "y", 0x134: "x"} if kind == "playstation" else {0x133: "x", 0x134: "y"})
    absinfo = dict(dev.capabilities().get(EV_ABS, []))
    if ABS_BRAKE in absinfo or ABS_GAS in absinfo:      # Xbox Bluetooth LE avec le pilote générique
        triggers, right = (ABS_BRAKE, ABS_GAS), (ABS_Z, ABS_RZ)
    else:                                                # xpadneo, xpad, PlayStation…
        triggers, right = (ABS_Z, ABS_RZ), (ABS_RX, ABS_RY)
    wanted = {ABS_X: (0, "stick"), ABS_Y: (1, "stick"), right[0]: (2, "stick"), right[1]: (3, "stick"),
              triggers[0]: (4, "trigger"), triggers[1]: (5, "trigger")}
    axes = {}
    for code, (idx, kind_) in wanted.items():
        info = absinfo.get(code)
        if info is not None and info.max > info.min:
            axes[code] = (idx, kind_, info.min, info.max)
    return {"buttons": buttons, "axes": axes}


class Pad:
    def __init__(self, gc, instance_id, info):
        self.gc = gc
        self.id = instance_id
        self.info = info
        self.axes = [0.0] * 6
        self.held = {}          # bouton → instant d'appui (pour la répétition)
        self.repeats = {}       # bouton → (prochain instant, nombre de répétitions)
        self.stick_dir = None
        self.triggers = {"lt": False, "rt": False}
        self.guide_down = None
        self.guide_long_sent = False
        self.last_input = time.monotonic()
        self.power = None
        self.path = None        # nœud evdev (/dev/input/eventN), pour la lecture exclusive
        self.dev = None         # périphérique evdev « saisi » pendant un menu de la console
        self.raw = None         # correspondance codes evdev → boutons/axes
        self.hat = [0, 0]
        self.grab_failed = False


class GamepadThread(threading.Thread):
    def __init__(self, on_event, mapper=None):
        super().__init__(name="gamepad", daemon=True)
        self.on_event = on_event        # appelé dans la boucle principale
        self.mapper = mapper
        self.mapper_mode = None         # None | "pointer" | "tv"
        self.guide_hold = 0.7
        self.pads = {}
        self.running = True
        self.requests = queue.Queue()
        self._last_activity_emit = 0.0
        self._last_power_check = 0.0
        self.exclusive = False

    # ------------------------------------------------------------- API ----
    def rumble(self, strength=0.35, ms=180, pad_id=None):
        self.requests.put(("rumble", strength, ms, pad_id))

    def set_exclusive(self, on):
        """Menu de la console ouvert au-dessus d'une appli : la manette n'est plus lue que par la console."""
        self.requests.put(("exclusive", bool(on)))

    def connected(self):
        return [dict(p.info, power=p.power) for p in self.pads.values()]

    # ----------------------------------------------------------- thread ----
    def emit(self, kind, **data):
        data["type"] = kind
        on_main(self.on_event, data)

    def run(self):
        if sdl2 is None:
            return
        for hint, value in ((b"SDL_JOYSTICK_HIDAPI", b"0"),
                            (b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1"),
                            (b"SDL_NO_SIGNAL_HANDLERS", b"1"),
                            (b"SDL_GAMECONTROLLER_USE_BUTTON_LABELS", b"0")):
            sdl2.SDL_SetHint(hint, value)
        if sdl2.SDL_Init(sdl2.SDL_INIT_GAMECONTROLLER | sdl2.SDL_INIT_EVENTS) != 0:
            log.error("SDL_Init : %s", sdl2.SDL_GetError().decode(errors="replace"))
            return
        db = "/opt/console/share/gamecontrollerdb.txt"
        if os.path.exists(db):
            try:
                n = sdl2.SDL_GameControllerAddMappingsFromFile(db.encode())
                log.info("%s mappings de manettes chargés", n)
            except Exception:  # noqa: BLE001
                pass
        event = sdl2.SDL_Event()
        last = time.monotonic()
        while self.running:
            sdl2.SDL_PumpEvents()
            while sdl2.SDL_PollEvent(ctypes.byref(event)):
                self._handle_event(event)
            self._process_requests()
            if self.exclusive:
                self._exclusive_tick()
            now = time.monotonic()
            dt, last = now - last, now
            self._tick(now, dt)
            busy = self.mapper_mode or self.exclusive or any(
                p.held or p.stick_dir or abs(p.axes[0]) > 0.1 or abs(p.axes[1]) > 0.1
                or abs(p.axes[2]) > 0.1 or abs(p.axes[3]) > 0.1 or p.guide_down
                for p in self.pads.values())
            time.sleep(0.008 if busy else 0.025)

    def _process_requests(self):
        while True:
            try:
                req = self.requests.get_nowait()
            except queue.Empty:
                return
            if req[0] == "rumble":
                _, strength, ms, pad_id = req
                level = int(max(0.0, min(1.0, strength)) * 0xFFFF)
                for pad in self.pads.values():
                    if pad_id is None or pad.id == pad_id:
                        try:
                            sdl2.SDL_GameControllerRumble(pad.gc, level, level, ms)
                        except Exception:  # noqa: BLE001
                            pass
            elif req[0] == "exclusive":
                self.exclusive = req[1]
                if not self.exclusive:
                    for pad in self.pads.values():
                        self._ungrab(pad)

    # ------------------------------------------------------- lecture exclusive ----
    # EVIOCGRAB réserve les évènements de la manette à la console : ni l'appli (SDL de Moonlight…),
    # ni le SDL de la console ne les voient ; on les lit donc directement (evdev) le temps du menu.
    def _exclusive_tick(self):
        for pad in list(self.pads.values()):
            if pad.dev is None:
                # On attend que tout soit relâché (bouton Xbox de l'appui long compris) : sinon l'appli
                # dessous garderait un bouton « enfoncé » ou un stick penché pendant tout le menu.
                if pad.grab_failed or not self._idle(pad):
                    continue
                self._grab(pad)
            if pad.dev is not None:
                self._read_raw(pad)

    @staticmethod
    def _idle(pad):
        return (not pad.held and pad.guide_down is None and pad.stick_dir is None
                and not any(pad.triggers.values()) and all(abs(v) < 0.25 for v in pad.axes[:4]))

    def _grab(self, pad):
        try:
            from evdev import InputDevice  # python3-evdev
            if not pad.path:
                raise OSError("nœud evdev inconnu")
            dev = InputDevice(pad.path)
            try:
                dev.grab()
            except OSError:
                dev.close()
                raise
            pad.raw = raw_layout(dev, pad.info.get("kind"))
        except Exception as exc:  # noqa: BLE001
            pad.grab_failed = True
            log.warning("manette %s : lecture exclusive impossible (%s)", pad.info["name"], exc)
            return
        pad.dev, pad.hat = dev, [0, 0]
        log.info("manette %s : réservée à la console pendant le menu", pad.info["name"])

    def _ungrab(self, pad):
        pad.grab_failed = False
        if pad.dev is None:
            return
        for fn in (pad.dev.ungrab, pad.dev.close):
            try:
                fn()
            except OSError:
                pass
        pad.dev = None
        # Ce qui a été appuyé pendant le menu n'a jamais existé pour SDL : on repart d'un état neutre,
        # sans évènement (sinon un bouton resterait « enfoncé » et se répéterait tout seul).
        pad.held.clear()
        pad.repeats.clear()
        pad.stick_dir = None
        pad.triggers = {"lt": False, "rt": False}
        pad.axes = [0.0] * 6
        pad.hat = [0, 0]
        pad.guide_down, pad.guide_long_sent = None, False

    def _read_raw(self, pad):
        try:
            events = list(pad.dev.read())
        except BlockingIOError:
            return
        except OSError:                         # manette éteinte pendant le menu
            self._ungrab(pad)
            return
        for ev in events:
            if ev.type == EV_KEY and ev.value in (0, 1):
                name = pad.raw["buttons"].get(ev.code)
                if name:
                    self._button(pad, name, ev.value == 1)
            elif ev.type == EV_ABS:
                if ev.code in (ABS_HAT0X, ABS_HAT0Y):
                    self._hat(pad, ev.code - ABS_HAT0X, ev.value)
                    continue
                axis = pad.raw["axes"].get(ev.code)
                if axis:
                    idx, kind, lo, hi = axis
                    v = (ev.value - lo) / (hi - lo)
                    pad.axes[idx] = max(-1.0, min(1.0, v if kind == "trigger" else 2 * v - 1))
                    if abs(pad.axes[idx]) > 0.3:
                        self._activity(pad)

    def _hat(self, pad, axis, value):
        neg, pos = ("left", "right") if axis == 0 else ("up", "down")
        value = (value > 0) - (value < 0)
        old = pad.hat[axis]
        if value == old:
            return
        if old:
            self._button(pad, neg if old < 0 else pos, False)
        pad.hat[axis] = value
        if value:
            self._button(pad, neg if value < 0 else pos, True)

    # ------------------------------------------------------------ events ----
    # Surtout pas « _handle » : depuis Python 3.13, threading.Thread range son propre objet dans
    # self._handle, qui masquait cette méthode (la lecture des manettes plantait au 1er évènement).
    def _handle_event(self, ev):
        t = ev.type
        if t == sdl2.SDL_CONTROLLERDEVICEADDED:
            self._open(ev.cdevice.which)
        elif t == sdl2.SDL_JOYDEVICEADDED and not sdl2.SDL_IsGameController(ev.jdevice.which):
            self._unrecognized(ev.jdevice.which)
        elif t == sdl2.SDL_CONTROLLERDEVICEREMOVED:
            pad = self.pads.pop(ev.cdevice.which, None)
            if pad:
                self._ungrab(pad)
                sdl2.SDL_GameControllerClose(pad.gc)
                log.info("manette déconnectée : %s", pad.info["name"])
                if self.mapper:
                    self.mapper.release_all()
                self.emit("device-removed", pad=pad.info)
        elif t in (sdl2.SDL_CONTROLLERBUTTONDOWN, sdl2.SDL_CONTROLLERBUTTONUP):
            pad = self.pads.get(ev.cbutton.which)
            name = BUTTONS.get(ev.cbutton.button)
            if pad and name:
                self._button(pad, name, t == sdl2.SDL_CONTROLLERBUTTONDOWN)
        elif t == sdl2.SDL_CONTROLLERAXISMOTION:
            pad = self.pads.get(ev.caxis.which)
            if pad and ev.caxis.axis < 6:
                pad.axes[ev.caxis.axis] = max(-1.0, min(1.0, ev.caxis.value / AXIS_MAX))
                if abs(pad.axes[ev.caxis.axis]) > 0.3:
                    self._activity(pad)

    def _unrecognized(self, index):
        """Manette vue par SDL mais sans correspondance des boutons : noté pour le dépannage."""
        try:
            name = (sdl2.SDL_JoystickNameForIndex(index) or b"?").decode(errors="replace")
            guid = ctypes.create_string_buffer(33)
            sdl2.SDL_JoystickGetGUIDString(sdl2.SDL_JoystickGetDeviceGUID(index), guid, 33)
            log.warning("manette non reconnue par SDL (boutons inconnus) : %s, %s", name, guid.value.decode())
        except Exception:  # noqa: BLE001
            pass

    def _open(self, index):
        if not sdl2.SDL_IsGameController(index):
            return
        gc = sdl2.SDL_GameControllerOpen(index)
        if not gc:
            return
        joy = sdl2.SDL_GameControllerGetJoystick(gc)
        instance = sdl2.SDL_JoystickInstanceID(joy)
        if instance in self.pads:
            return
        name = (sdl2.SDL_GameControllerName(gc) or b"Manette").decode(errors="replace")
        guid_buf = ctypes.create_string_buffer(33)
        sdl2.SDL_JoystickGetGUIDString(sdl2.SDL_JoystickGetGUID(joy), guid_buf, 33)
        try:
            ctype = TYPES.get(sdl2.SDL_GameControllerGetType(gc), "generic")
        except Exception:  # noqa: BLE001
            ctype = "generic"
        jname = (sdl2.SDL_JoystickName(joy) or b"").decode(errors="replace")
        if ctype == "generic" and "xbox" in (name + jname).lower():
            ctype = "xbox"
        info = {"id": instance, "name": name, "joystick_name": jname,
                "guid": guid_buf.value.decode(), "kind": ctype}
        pad = Pad(gc, instance, info)
        try:
            raw_path = sdl2.SDL_JoystickPath(joy) if hasattr(sdl2, "SDL_JoystickPath") else None
            pad.path = raw_path.decode() if raw_path else None
        except Exception:  # noqa: BLE001
            pad.path = None
        self.pads[instance] = pad
        pad.power = self._power(pad)
        log.info("manette connectée : %s (%s, %s)", name, ctype, info["guid"])
        self.emit("device-added", pad=info)

    def _power(self, pad):
        try:
            level = sdl2.SDL_JoystickCurrentPowerLevel(sdl2.SDL_GameControllerGetJoystick(pad.gc))
        except Exception:  # noqa: BLE001
            return None
        return {-1: None, 0: 5, 1: 20, 2: 55, 3: 90, 4: "wired", 5: 100}.get(level)

    def _activity(self, pad):
        now = time.monotonic()
        pad.last_input = now
        if now - self._last_activity_emit > 1.0:
            self._last_activity_emit = now
            self.emit("activity", pad=pad.id)

    def _button(self, pad, name, pressed, synthetic=False):
        now = time.monotonic()
        if not synthetic:
            self._activity(pad)
        if name == "guide":
            if pressed:
                pad.guide_down, pad.guide_long_sent = now, False
            elif pad.guide_down is not None:
                if not pad.guide_long_sent:
                    self.emit("guide", long=False, pad=pad.id)
                pad.guide_down = None
            return
        mapper_used = False
        if self.mapper_mode and self.mapper:
            action = self.mapper.on_button(name, pressed, self.mapper_mode)
            mapper_used = True
            if action:
                self.emit("mapper-action", action=action, pad=pad.id)
        if pressed:
            pad.held[name] = now
            pad.repeats[name] = (now + REPEAT_DELAY, 0)
            if not mapper_used:
                self.emit("button", button=name, repeat=False, pad=pad.id)
        else:
            pad.held.pop(name, None)
            pad.repeats.pop(name, None)
            if not mapper_used:
                self.emit("button-up", button=name, pad=pad.id)

    def _tick(self, now, dt):
        for pad in list(self.pads.values()):
            # Bouton Xbox maintenu → menu rapide de la console
            if pad.guide_down is not None and not pad.guide_long_sent and now - pad.guide_down >= self.guide_hold:
                pad.guide_long_sent = True
                self.emit("guide", long=True, pad=pad.id)
            # Gâchettes analogiques → boutons lt/rt
            for name, axis in (("lt", 4), ("rt", 5)):
                v = pad.axes[axis]
                if not pad.triggers[name] and v > TRIGGER_ON:
                    pad.triggers[name] = True
                    self._button(pad, name, True, synthetic=True)
                elif pad.triggers[name] and v < TRIGGER_OFF:
                    pad.triggers[name] = False
                    self._button(pad, name, False, synthetic=True)
            # Stick gauche → croix directionnelle (navigation), sauf en mode souris
            if self.mapper_mode != "pointer":
                self._stick_nav(pad)
            # Répétition des directions maintenues
            for name, (due, count) in list(pad.repeats.items()):
                if name in NAV and now >= due and name in pad.held:
                    rate = REPEAT_FAST if count >= 6 else REPEAT_RATE
                    pad.repeats[name] = (now + rate, count + 1)
                    if self.mapper_mode and self.mapper:
                        self.mapper.on_button(name, True, self.mapper_mode, repeat=True)
                    else:
                        self.emit("button", button=name, repeat=True, pad=pad.id)
        if self.mapper_mode and self.mapper and self.pads:
            pad = max(self.pads.values(), key=lambda p: p.last_input)
            self.mapper.tick(dt, pad.axes, self.mapper_mode)
        if now - self._last_power_check > 60:
            self._last_power_check = now
            for pad in self.pads.values():
                level = self._power(pad)
                if level != pad.power:
                    pad.power = level
                    self.emit("power", pad=pad.id, level=level)

    def _stick_nav(self, pad):
        x, y = pad.axes[0], pad.axes[1]
        mag = max(abs(x), abs(y))
        direction = pad.stick_dir
        if direction is None and mag > STICK_ON:
            direction = ("right" if x > 0 else "left") if abs(x) > abs(y) else ("down" if y > 0 else "up")
        elif direction is not None and mag < STICK_OFF:
            direction = None
        elif direction is not None and mag > STICK_ON:
            new = ("right" if x > 0 else "left") if abs(x) > abs(y) * 1.4 else \
                  ("down" if y > 0 else "up") if abs(y) > abs(x) * 1.4 else direction
            direction = new
        if direction != pad.stick_dir:
            if pad.stick_dir:
                self._button(pad, pad.stick_dir, False, synthetic=True)
            pad.stick_dir = direction
            if direction:
                self._button(pad, direction, True, synthetic=True)
