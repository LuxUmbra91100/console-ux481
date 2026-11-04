"""Lecture des manettes via SDL2 (API GameController), dans un thread dédié.

- Ne prend jamais le contrôle exclusif des manettes : les jeux et émulateurs les
  lisent en parallèle (HIDAPI désactivé, simple lecture evdev).
- Produit des évènements « UI » (boutons avec répétition, stick → croix,
  appui court/long sur le bouton Xbox) envoyés à la boucle principale.
- En mode « navigateur », pilote directement la souris/clavier virtuels
  (latence minimale) via Mapper.
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

    # ------------------------------------------------------------- API ----
    def rumble(self, strength=0.35, ms=180, pad_id=None):
        self.requests.put(("rumble", strength, ms, pad_id))

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
                self._handle(event)
            self._process_requests()
            now = time.monotonic()
            dt, last = now - last, now
            self._tick(now, dt)
            busy = self.mapper_mode or any(
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

    # ------------------------------------------------------------ events ----
    def _handle(self, ev):
        t = ev.type
        if t == sdl2.SDL_CONTROLLERDEVICEADDED:
            self._open(ev.cdevice.which)
        elif t == sdl2.SDL_CONTROLLERDEVICEREMOVED:
            pad = self.pads.pop(ev.cdevice.which, None)
            if pad:
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
