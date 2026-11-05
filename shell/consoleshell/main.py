"""console-shell : l'écran d'accueil et le « système » de la console."""
import datetime
import os
import queue
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import health, library, moonlight, network, pcremote  # noqa: E402
from .apps import AppManager, profile_for  # noqa: E402
from .audio import Audio  # noqa: E402
from .bluetooth import Bluetooth  # noqa: E402
from .brave import BraveCDP  # noqa: E402
from .config import (BRAVE_PROFILE, CAPTURES_DIR, CONTROL_SOCKET, PREFIX, Settings,  # noqa: E402
                     ensure_dirs, get_secret, secret_keys, set_secret)
from .control import ControlServer  # noqa: E402
from .display import Display  # noqa: E402
from .emucfg import dolphin_fix_from_log, dolphin_set_controller  # noqa: E402
from .gamepad import GamepadThread  # noqa: E402
from .mapper import Mapper  # noqa: E402
from .power import Power, mem_sleep_modes  # noqa: E402
from .sites import PRESETS, Sites, normalize_url  # noqa: E402
from .swayipc import Sway, SwayEvents  # noqa: E402
from .ui import HomeWindow, LayerWindow  # noqa: E402
from .util import battery_alert, every, later, log, on_main, run, run_async, setup_logging, thread  # noqa: E402

VERSION = "1.0"
ROOT_HELPER = ["sudo", "-n", f"{PREFIX}/bin/console-root"]
ICON_CANDIDATES = {
    "moonlight": ["/var/lib/flatpak/exports/share/icons/hicolor/scalable/apps/com.moonlight_stream.Moonlight.svg",
                  "/var/lib/flatpak/exports/share/icons/hicolor/256x256/apps/com.moonlight_stream.Moonlight.png",
                  "/usr/share/icons/hicolor/scalable/apps/moonlight.svg"],
    "brave": ["/usr/share/icons/hicolor/256x256/apps/brave-browser.png",
              "/opt/brave.com/brave/product_logo_256.png"],
    "games": [f"{PREFIX}/share/icons/es-de.svg", "/opt/es-de/org.es_de.frontend.svg",
              "/opt/es-de/usr/share/icons/hicolor/scalable/apps/org.es_de.frontend.svg"],
}
HEAVY_PROFILES = {"dolphin", "pcsx2", "azahar"}


def first_existing(paths):
    return next((p for p in paths if p and os.path.exists(p)), None)


class Shell:
    def __init__(self):
        ensure_dirs()
        self.settings = Settings()
        self.sway = Sway()
        self.display = Display(self.sway, self.settings)
        self.audio = Audio()
        self.mapper = Mapper()
        self.pads = {}
        self.had_pad = False
        self.focus = "home"              # home | app | panel
        self.panel_mode = None           # splash | sleep | menu | osk | dialog
        self.panel_return = "home"
        self.osk_context = None
        self.fg_profile = (None, {})
        self.brave_tv = False
        self.net = {"kind": "unknown", "connected": False}
        self.moon_hosts, self.moon_status = [], {}
        self.library_cache = {"systems": [], "recent": []}
        self.cec_available = False
        self._audio_busy = False
        self._outputs_timer = None
        self._profile_name = None
        self.waking = None               # réveil d'un PC Moonlight en cours
        self._half_seen = {}             # uuid → nombre de sondages « Sunshine à moitié planté » d'affilée
        self._repairing = set()          # uuid des PC dont Sunshine est en cours de relance
        self._battery_warned = {}        # manette → dernier seuil de batterie signalé (20, 10, 5)
        self.ambient = False             # accueil en mode ambiance (interface effacée)
        self.pin_watch = None            # saisie du code PIN Windows en attente

        self.home = HomeWindow(self.on_ui)
        self.panel = LayerWindow("panel", "overlay.html", self.on_ui)
        self.toastw = LayerWindow("toast", "toast.html", self.on_ui, anchors=("top", "right"),
                                  size=(640, 200), margins={"top": 24, "right": 24})
        self.apps = AppManager(self)
        self.brave = BraveCDP(self)
        self.sites = Sites(self.push_tiles)
        self.bt = Bluetooth(self.on_bt)
        self.power = Power(self)
        self.pad = GamepadThread(self.on_pad, self.mapper)
        self.pad.guide_hold = max(0.3, (self.settings["guide_hold_ms"] or 700) / 1000)
        self.pad.start()
        # Commandes audio (pactl) dans un fil dédié, en série : elles prenaient jusqu'à 100 ms par appui
        # sur le fil de l'interface (ouverture du menu, réglage du volume).
        self.volume = None
        self._audio_jobs = queue.Queue()
        thread(self._audio_worker, name="audio-jobs")
        SwayEvents(lambda name, data: on_main(self.on_sway, name, data)).start()
        ControlServer(CONTROL_SOCKET, self.on_ctl).start()
        self.settings.on_change(self.on_setting)
        later(200, self.startup)
        every(20000, self.poll_moonlight)
        every(60000, self.refresh_status)

    # ================================================================ démarrage
    def startup(self):
        log.info("console-shell %s démarré", VERSION)
        self.display.apply()
        self.apps.adopt(self.sway.views())
        self.sway.command("workspace home")
        self.select_audio()
        self.refresh_status()
        self.refresh_library()
        self.poll_moonlight(force=True)
        thread(self._detect_cec, name="cec")
        self.push_all()

    def _detect_cec(self):
        if shutil.which("cec-client"):
            code, out, _ = run(["cec-client", "-l"], timeout=8)
            self.cec_available = code == 0 and "com port:" in out.lower()
            log.info("adaptateur HDMI-CEC : %s", "oui" if self.cec_available else "non")

    def cec(self, action):
        if not self.cec_available:
            return
        script = {"wake": "on 0\nas\n", "standby": "standby 0\n"}.get(action)
        if script:
            run_async(["sh", "-c", f"printf '{script}' | cec-client -s -d 1"], timeout=15)

    def busy(self):
        return (self.bt.pairing or self.panel_mode in ("menu", "osk", "dialog") or self.apps.pending or self.waking
                or self.power.wake_test or not self.settings["first_run_done"])

    # ================================================================ état → UI
    def tiles_public(self):
        out = []
        for t in self.sites.tiles():
            tile = dict(t)
            kind = tile.get("type")
            tile["running"] = self.apps.running(tile["id"]) if kind in ("moonlight", "games", "brave") else False
            if kind in ICON_CANDIDATES:
                tile["appIcon"] = first_existing(ICON_CANDIDATES[kind])
            out.append(tile)
        return out

    def snapshot(self):
        modes, current = mem_sleep_modes()
        return {
            "version": VERSION,
            "name": self.settings["console_name"],
            "settings": self.settings.public(),
            "tiles": self.tiles_public(),
            "apps": self.apps.public(),
            "pads": list(self.pads.values()),
            "bt": {"available": self.bt.available(), "pairing": self.bt.pairing, "gamepads": self.bt.gamepads()},
            "net": self.net,
            "moonlight": moonlight.describe(self.moon_hosts, self.moon_status),
            "library": self.library_cache,
            "presets": PRESETS,
            "sleep": {"modes": modes, "current": current},
            "display": self.display.summary(),
            "moonlight_pins": self.pin_hosts(),
            "pc_remote": self.pc_remote_public(),
            "moonlight_default": (self.default_host() or {}).get("uuid"),
        }

    def push(self, **partial):
        self.home.surface.emit("state", partial)

    def push_all(self):
        self.home.surface.emit("state", self.snapshot())

    def push_tiles(self):
        self.push(tiles=self.tiles_public())

    def on_apps_changed(self):
        self.update_exclusive()
        self.push(apps=self.apps.public(), tiles=self.tiles_public())

    def refresh_status(self):
        def work():
            st = network.status()
            on_main(self._set_net, st)
        thread(work, name="net-status")
        return True

    def _set_net(self, st):
        self.net = st
        self.push(net=st)

    def refresh_library(self):
        def work():
            data = {"systems": library.systems(), "recent": library.recent()}
            on_main(self._set_library, data)
        thread(work, name="library")

    def _set_library(self, data):
        self.library_cache = data
        self.push(library=data)

    def poll_moonlight(self, force=False):
        if not force and (self.focus != "home" or self.power.state != "on"):
            return True
        self.moon_hosts = moonlight.load_hosts()
        hosts = list(self.moon_hosts)

        def work():
            status = {h["uuid"]: pcremote.check(h) for h in hosts}
            on_main(self._set_moon_status, status)
        thread(work, name="moonlight-status")
        self.push(moonlight=moonlight.describe(self.moon_hosts, self.moon_status))
        return True

    def _set_moon_status(self, status):
        self.moon_status = status
        self.push(moonlight=moonlight.describe(self.moon_hosts, self.moon_status))
        # Sunshine à moitié planté deux fois de suite, sans stream en cours : relance discrète.
        for h in self.moon_hosts:
            st = status.get(h["uuid"]) or {}
            half = st.get("sunshine") == "half" and not st.get("busy")
            self._half_seen[h["uuid"]] = self._half_seen.get(h["uuid"], 0) + 1 if half else 0
            if (half and self._half_seen[h["uuid"]] >= 2 and self.settings["sunshine_auto_repair"]
                    and not self.apps.running("moonlight") and not self.waking
                    and h["uuid"] not in self._repairing and pcremote.credentials(h["uuid"])):
                self._repair_sunshine(h, st, quiet=True)

    def _repair_sunshine(self, host, st, quiet=False, then=None):
        """Relance Sunshine par son API (identifiant enregistré). then(résultat) dans la boucle principale."""
        uuid = host["uuid"]
        creds = pcremote.credentials(uuid)
        if not creds or uuid in self._repairing:
            if then:
                then("auth" if not creds else "busy")
            return
        self._repairing.add(uuid)
        log.info("Sunshine de %s : port appairé muet, relance par son API", host["name"])

        def work():
            res = pcremote.restart_sunshine(st, creds)
            on_main(done, res)

        def done(res):
            self._repairing.discard(uuid)
            self._half_seen[uuid] = 0
            log.info("relance de Sunshine (%s) : %s", host["name"], res)
            if quiet:
                if res == "ok":
                    self.toast("Sunshine relancé", sub=f"Il ne répondait plus correctement sur {host['name']}", icon="check")
                else:
                    self.toast(*self._repair_message(host, res), icon="warning", ms=8000)
            self.poll_moonlight(force=True)
            if then:
                then(res)
        thread(work, name="sunshine-repair")

    @staticmethod
    def _repair_message(host, res):
        return {
            "auth": ("Identifiant Sunshine refusé", "Vérifie-le dans Réglages › Moonlight"),
            "unreachable": ("Sunshine injoignable", f"{host['name']} ne répond plus du tout"),
            "stuck": ("Sunshine ne redémarre pas", f"Redémarre {host['name']} (menu du PC sur l'étagère Moonlight)"),
        }.get(res, ("Sunshine ne répond pas", ""))

    def select_audio(self, delay=0):
        if self._audio_busy:
            return

        def work():
            if delay:
                time.sleep(delay)
            try:
                self.audio.select_hdmi()
            finally:
                self._audio_busy = False
        self._audio_busy = True
        thread(work, name="audio")

    # ================================================================== focus
    def set_focus(self, focus):
        self.focus = focus
        self.update_mapper()
        self.update_exclusive()
        if focus == "home":
            self.home.surface.emit("shown")
        elif focus == "app":
            self.home.surface.emit("hidden")      # met en pause le fond animé de l'accueil
        elif focus == "panel":
            self.home.surface.emit("covered")     # menu ou clavier par-dessus : pas de mode ambiance

    def update_exclusive(self):
        """Manette réservée à la console (lecture exclusive) quand son interface est devant (accueil ou
        menu) et qu'une appli tourne derrière : Moonlight, par exemple, lit la manette même sans le focus
        et piloterait le PC en même temps que l'accueil. Libérée dès qu'une appli repasse devant."""
        self.pad.set_exclusive(self.focus in ("home", "panel") and bool(self.apps.apps))

    def update_mapper(self):
        mode = None
        if self.focus == "app":
            app = self.apps.current()
            if app and app.kind == "brave" and self.fg_profile[0] in ("brave", None):
                mode = "tv" if self.brave_tv else "pointer"
        if mode != self.pad.mapper_mode:
            self.mapper.release_all()
            self.pad.mapper_mode = mode
            if mode == "pointer":
                self.mapper.nudge()

    def show_home(self):
        self.apps.show_home()
        if self.focus != "panel":
            self.set_focus("home")
        else:
            self.panel_return = "home"
        self.refresh_library()
        self.poll_moonlight(force=True)
        self.push(apps=self.apps.public(), tiles=self.tiles_public())

    def resume(self, app_id):
        if self.apps.show(app_id):
            self.set_focus("app")

    def on_window_focus(self, con):
        key, prof = profile_for(con)
        if (con.get("app_id") or "") == "console-home":
            key, prof = None, {}
        self.fg_profile = (key, prof)
        self.update_mapper()
        wanted = "performance" if key in HEAVY_PROFILES else "balanced"
        if wanted != self._profile_name and self.power.state == "on":
            self._profile_name = wanted
            run_async(["powerprofilesctl", "set", wanted])

    # ================================================================ manette
    def on_pad(self, ev):
        kind = ev["type"]
        if kind == "device-added":
            info = ev["pad"]
            self.pads[info["id"]] = info
            self.had_pad = True
            self.power.controllers(len(self.pads), True)
            self.pad.rumble(0.45, 180, info["id"])
            if self.power.state == "light":
                self.power.wake("manette")
            elif self.settings["first_run_done"]:
                self.toast("Manette connectée", sub=info["name"], icon="gamepad")
            if not self.apps.running("games"):
                dolphin_set_controller(info["name"])
            self.push(pads=list(self.pads.values()), bt=self.bt_state())
        elif kind == "device-removed":
            self.pads.pop(ev["pad"]["id"], None)
            self.power.controllers(len(self.pads), self.had_pad)
            if self.power.state == "on":
                self.toast("Manette déconnectée", sub=ev["pad"]["name"], icon="gamepad")
            self.push(pads=list(self.pads.values()), bt=self.bt_state())
        elif kind == "power":
            if ev["pad"] in self.pads:
                self.pads[ev["pad"]]["power"] = ev["level"]
                self.push(pads=list(self.pads.values()))
        elif kind == "activity":
            self.power.activity()
        elif kind == "guide":
            self.on_guide(ev["long"])
        elif kind == "mapper-action":
            self.on_mapper_action(ev["action"])
        elif kind in ("button", "button-up"):
            if self.waking:
                if kind == "button" and ev["button"] in ("b", "back"):
                    self.cancel_waking()
                return
            if self.power.state == "light":
                if kind == "button":
                    self.power.wake("bouton")
                return
            target = self.panel if self.focus == "panel" else self.home if self.focus == "home" else None
            if target is not None:
                target.surface.emit("pad" if kind == "button" else "pad-up",
                                    {"button": ev["button"], "repeat": ev.get("repeat", False)})

    def on_guide(self, long):
        if self.power.state == "light":
            self.power.wake("bouton Xbox")
            return
        if self.waking:
            self.cancel_waking()
            return
        if self.focus == "panel":
            if self.panel_mode in ("menu", "osk", "dialog"):
                self.close_panel()
            return
        if self.focus == "home":
            if self.ambient:                  # le bouton Xbox réveille d'abord l'interface
                self.ambient = False              # (même si l'accueil ne confirme pas, l'appui suivant marche)
                self.home.surface.emit("wake-ui")
                return
            if long:
                self.home.surface.emit("power-menu")
            elif self.apps.last_app and self.apps.running(self.apps.last_app):
                self.resume(self.apps.last_app)
            return
        _, prof = self.fg_profile
        if prof.get("guide") == "passthrough" and not long:
            return
        self.open_quick_menu()

    def on_mapper_action(self, action):
        if action == "menu":
            self.open_quick_menu()
        elif action == "osk":
            def got(field):
                if field:
                    self.open_osk(field, "brave")
                else:
                    self.open_url_prompt()
            self.brave.focused_field(got)
        elif action == "url":
            self.open_url_prompt()

    # =============================================================== panneau
    def open_panel(self, mode, data=None):
        interactive = mode in ("menu", "osk", "dialog")
        if interactive and self.focus != "panel":
            self.panel_return = self.focus
        self.panel_mode = mode
        if interactive:
            self.focus = "panel"
            self.update_mapper()
            self.update_exclusive()            # la manette ne sert plus qu'au menu, pas à l'appli dessous
        self.panel.show(interactive)
        self.panel.surface.emit("open", {"mode": mode, "data": data or {},
                                         "settings": {"osk_layout": self.settings["osk_layout"],
                                                      "ui_sounds": self.settings["ui_sounds"]}})

    def close_panel(self, then=None):
        if self.panel_mode is None:
            if then:
                then()
            return
        was_interactive = self.panel_mode in ("menu", "osk", "dialog")
        self.panel_mode = None
        self.panel.release()                  # clavier et clics rendus tout de suite à l'appli
        self.panel.surface.emit("close")
        if then:
            later(160, then)
        # La page garée doit avoir affiché une image vide (accusé « panel-closed » après son fondu),
        # sinon la prochaine ouverture montrerait une image de l'ancien menu. Filet : 700 ms.
        later(700, self._park_panel)
        if was_interactive:
            self.focus = self.panel_return if self.panel_return != "panel" else "home"
            if self.focus == "app" and not self.apps.current():
                self.focus = "home"
            self.update_mapper()
            self.update_exclusive()
            if self.focus == "home":
                self.home.surface.emit("shown")

    def _park_panel(self):
        if self.panel_mode is None:
            self.panel.hide()

    def ui_panel_closed(self, args, src):
        self._park_panel()

    # ================================================================== audio
    def _audio_worker(self):
        while True:
            fn, done = self._audio_jobs.get()
            try:
                result = fn()
            except Exception:  # noqa: BLE001
                log.exception("commande audio")
                result = None
            on_main(self._audio_done, result, done)

    def _audio_done(self, result, done):
        if isinstance(result, dict) and "volume" in result:
            self.volume = result
        if done:
            done(result)

    def audio_job(self, fn, done=None):
        self._audio_jobs.put((fn, done))

    def splash(self, data):
        if self.panel_mode in ("menu", "osk", "dialog"):
            return
        self.open_panel("splash", data)

    def splash_hide(self):
        if self.panel_mode == "splash":
            self.close_panel()

    def splash_update(self, data):
        if self.panel_mode == "splash":
            self.panel.surface.emit("splash-update", data)

    def show_sleep_curtain(self):
        if self.panel_mode in ("menu", "osk", "dialog"):
            self.close_panel()
        later(180, self.open_panel, "sleep", {})

    def open_quick_menu(self):
        app = self.apps.current()
        key, prof = self.fg_profile
        data = {
            "app": app.public() if app else None,
            "profile": key, "title": prof.get("title") or (app.title if app else ""),
            "can_save": "save" in prof, "can_load": "load" in prof, "emu_menu": "emu_menu" in prof,
            "in_game": key in ("dolphin", "pcsx2", "azahar", "retroarch"),
            "is_brave": bool(app and app.kind == "brave"),
            "is_moonlight": bool(app and app.kind == "moonlight"),
            "can_pin": bool(app and app.kind == "moonlight" and self.pin_for(app)),
            "tabs": self.brave.tabs() if app and app.kind == "brave" else [],
            "volume": self.volume or {},
            "pads": list(self.pads.values()),
            "batteries": [{"name": g["name"], "battery": g["battery"]} for g in self.bt.gamepads() if g["connected"]],
            "standby_mode": self.settings["standby_mode"],
        }
        self.open_panel("menu", data)
        self.audio_job(self.audio.get_volume,
                       lambda v: self.panel_mode == "menu" and v and self.panel.surface.emit("volume", v))

    def open_osk(self, field, target):
        self.osk_context = {"target": target}
        self.open_panel("osk", {"field": field, "target": target})

    def open_url_prompt(self):
        info = self.brave.active_info() or {}
        self.open_osk({"label": "Adresse ou recherche", "value": info.get("url", ""), "type": "url",
                       "selectAll": True}, "brave-url")

    def on_brave_field_focus(self, field):
        app = self.apps.current()
        if self.focus != "app" or not app or app.kind != "brave" or field.get("type") in ("number",):
            return
        if time.monotonic() - self.mapper.last_click < 1.2:
            self.open_osk(field, "brave")

    def on_brave_active(self, url):
        tv = self.is_tv_url(url)
        if tv != self.brave_tv:
            self.brave_tv = tv
            self.brave.fullscreen(tv)
            self.update_mapper()

    def is_tv_url(self, url):
        if not url:
            return False
        p = urllib.parse.urlparse(url)
        for t in self.sites.sites():
            if t.get("tv"):
                q = urllib.parse.urlparse(t["url"])
                if p.netloc.removeprefix("www.") == q.netloc.removeprefix("www.") and \
                        p.path.startswith(q.path.rstrip("/") or "/"):
                    return True
        return False

    def toast(self, text, sub=None, icon="info", ms=3200):
        if self.power.state != "on" or self.panel_mode == "sleep":
            return
        self.toastw.show(False)
        self.toastw.surface.emit("toast", {"text": text, "sub": sub, "icon": icon, "ms": ms})

    # ============================================================ lancements
    def launch_tile(self, tile_id):
        tile = self.sites.get(tile_id)
        if tile is None:
            return False
        kind = tile.get("type")
        if kind == "games":
            return self.launch_games()
        if kind == "moonlight":
            return self.moonlight_tile()
        if kind == "brave":
            return self.launch_brave()
        if kind == "site":
            return self.open_site(tile)
        return False

    def launch_games(self, system=None):
        if self.apps.running("games"):
            self.resume("games")
            return True
        library.set_startup(system)
        self.apps.launch("games", "Jeux", [f"{PREFIX}/bin/es-de", "--no-splash", "--no-update-check"], "esde",
                         splash={"title": "Jeux", "kind": "games", "icon": first_existing(ICON_CANDIDATES["games"])})
        return True

    def launch_game(self, system, path, name):
        cmd = library.command(system, path)
        if not cmd:
            return self.launch_games(system)
        for other in ("games", "game"):
            if self.apps.running(other):
                self.home.surface.emit("dialog", {"kind": "close-first", "app": other, "next": {
                    "cmd": "game-launch", "args": {"system": system, "path": path, "name": name}}})
                return False
        library.remember(system, path, name)
        cover = library.media(system, path)
        self.apps.launch("game", name, cmd, "game", meta={"art": cover, "system": system},
                         splash={"title": name, "kind": "game", "art": cover, "sub": library.SYSTEM_INDEX[system][1]})
        return True

    def launch_moonlight(self):
        if self.apps.running("moonlight"):
            self.resume("moonlight")
            return True
        self.apps.launch("moonlight", "Moonlight", moonlight.gui_cmd(), "moonlight", guide="passthrough",
                         splash={"title": "Moonlight", "kind": "moonlight",
                                 "icon": first_existing(ICON_CANDIDATES["moonlight"])})
        return True

    # ------------------------------------------------------------ Moonlight
    def default_host(self):
        hosts = self.moon_hosts or moonlight.load_hosts()
        want = self.settings["moonlight_host"]
        return next((h for h in hosts if h["uuid"] == want), hosts[0] if hosts else None)

    def pc_remote_public(self):
        """Ce que l'interface doit savoir du PC distant (aucun secret)."""
        return {"relay": self.settings["wake_relay"], "ssh": self.settings["pc_ssh"],
                "auth": [h["uuid"] for h in (self.moon_hosts or []) if pcremote.credentials(h["uuid"])]}

    def pin_hosts(self):
        return [k.split(":", 1)[1] for k in secret_keys() if k.startswith("moonlight_pin:")]

    def pin_for(self, app):
        uuid = (app.meta.get("stream") or [None])[0]
        return uuid if uuid and get_secret(f"moonlight_pin:{uuid}") else None

    def moonlight_tile(self):
        """La tuile lance directement l'appli choisie (Steam Big Picture par défaut) sur le PC par défaut."""
        if self.apps.running("moonlight"):
            self.resume("moonlight")
            return True
        host = self.default_host()
        target = self.settings["moonlight_tile_app"] or "gui"
        if not host or target == "gui":
            return self.launch_moonlight()
        app = moonlight.find_app(host, target)
        return self.moonlight_stream(host["uuid"], app["name"] if app else target)

    def moonlight_stream(self, uuid, app_name):
        hosts = self.moon_hosts or moonlight.load_hosts()
        host = next((h for h in hosts if h["uuid"] == uuid), None)
        app = moonlight.find_app(host, app_name)
        app_name = app["name"] if app else app_name
        current = self.apps.apps.get("moonlight")
        if current:
            if current.meta.get("stream") == [uuid, app_name]:
                self.resume("moonlight")
                return True
            self.apps.terminate("moonlight")
            later(1500, self.moonlight_stream, uuid, app_name)
            return True
        if self.waking:
            return True
        art = (app or {}).get("boxart")
        pc = (host or {}).get("name", "PC")
        splash = {"title": app_name, "sub": f"Connexion à {pc}…", "kind": "moonlight", "art": art}
        token = {"uuid": uuid, "cancel": False, "start": time.monotonic()}
        self.waking = token
        self.splash(splash)

        def start(woke):
            if self.waking is not token or token["cancel"]:
                return
            self.waking = None
            mode = self.settings["moonlight_pin_mode"]
            if get_secret(f"moonlight_pin:{uuid}") and (mode == "always" or (mode == "wake" and woke)):
                watch = {"uuid": uuid, "fired": False}
                self.pin_watch = watch
                later(150000, self._expire_pin_watch, watch)
            self.apps.launch("moonlight", app_name, moonlight.stream_cmd(uuid, app_name), "moonlight",
                             guide="passthrough", meta={"stream": [uuid, app_name], "art": art},
                             splash=dict(splash, sub=pc))

        def check():
            st = pcremote.check(host) if host else {"online": True}
            on_main(after_check, st)

        def after_check(st):
            if self.waking is not token or token["cancel"]:
                return
            if st.get("online") and st.get("sunshine") == "half":
                self._repair_before_stream(host, st, token, start)
            elif st.get("online"):
                start(False)
            elif host and host.get("mac"):
                self._wake_and_wait(host, token, start)
            else:
                start(True)          # adresse MAC inconnue : Moonlight tentera lui-même de joindre le PC
        thread(check, name="moonlight-check")
        return True

    def _repair_before_stream(self, host, st, token, start):
        """Sunshine répond à moitié (Moonlight dirait « injoignable ») : on le relance d'abord."""
        if not pcremote.credentials(host["uuid"]):
            if self.waking is token:
                self.waking = None
            self.splash_hide()
            self.toast("Sunshine est bloqué sur le PC", icon="warning", ms=9000,
                       sub="Enregistre ton identifiant Sunshine (Réglages › Moonlight) : la console le relancera seule")
            return
        self.splash_update({"sub": "Sunshine ne répond plus correctement : redémarrage…"})

        def done(res):
            if self.waking is not token or token["cancel"]:
                return
            if res == "ok":
                self.toast("Sunshine relancé", icon="check")
                start(False)
                return
            self.waking = None
            self.splash_hide()
            self.toast(*self._repair_message(host, res), icon="warning", ms=9000)
        self._repair_sunshine(host, st, then=done)

    def _wake_and_wait(self, host, token, start):
        """Réveille le PC (Wake-on-LAN) et attend qu'il réponde, avec un écran d'attente."""
        log.info("réveil de %s (Wake-on-LAN)", host["name"])
        self.wake_pc(host)
        self.splash_update({"sub": f"Réveil de {host['name']}…"})

        def poll():
            last = time.monotonic()
            while not token["cancel"] and time.monotonic() - token["start"] < 150:
                st = pcremote.check(host)
                if st.get("online"):
                    if st.get("sunshine") == "half":
                        on_main(self._repair_before_stream, host, st, token, lambda _woke: start(True))
                    else:
                        on_main(start, True)
                    return
                if time.monotonic() - last > 10:
                    self.wake_pc(host, in_thread=False)
                    last = time.monotonic()
                elapsed = int(time.monotonic() - token["start"])
                on_main(self.splash_update, {"sub": f"Réveil de {host['name']}… {elapsed} s — Ⓑ pour annuler"})
                time.sleep(2)
            if not token["cancel"]:
                on_main(self._wake_failed, host, token)
        thread(poll, name="moonlight-wake")

    def wake_pc(self, host, in_thread=True):
        """Wake-on-LAN local + par le relais du réseau du PC s'il est configuré (Raspberry…)."""
        moonlight.wake(host)
        relay = self.settings["wake_relay"]
        if relay and host.get("mac"):
            if in_thread:
                thread(pcremote.relay_wake, relay, host["mac"], name="wake-relay")
            else:
                pcremote.relay_wake(relay, host["mac"])

    def _wake_failed(self, host, token):
        if self.waking is token:
            self.waking = None
        self.splash_hide()
        self.toast(f"{host['name']} ne répond pas", sub="PC branché ? Wake-on-LAN activé ?", icon="warning", ms=6000)

    def cancel_waking(self):
        token, self.waking = self.waking, None
        if token:
            token["cancel"] = True
            self.splash_hide()
            self.toast("Connexion annulée", icon="info")

    def _expire_pin_watch(self, watch):
        if self.pin_watch is watch:
            self.pin_watch = None

    def on_app_window(self, app, con):
        """Fenêtre du stream Moonlight (titre = nom du PC) : l'image arrive, on tape le code PIN."""
        watch = self.pin_watch
        if not watch or watch["fired"] or app.kind != "moonlight":
            return
        title = (con.get("name") or "").strip()
        if title and title.lower() != "moonlight":
            watch["fired"] = True
            log.info("stream Moonlight affiché (« %s ») : saisie du code PIN Windows", title)
            later(4000, self.type_pin, watch["uuid"], True)

    def set_clipboard(self, text):
        if not shutil.which("wl-copy"):
            return False
        try:
            p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            p.communicate(text.encode("utf-8"), timeout=5)
            return p.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def type_pin(self, uuid, auto=False, attempt=0):
        """Tape le code PIN Windows sur l'écran de verrouillage du PC, à travers Moonlight.

        Le texte passe par le raccourci « taper le presse-papiers » de Moonlight
        (Ctrl+Alt+Maj+V) : il est envoyé en Unicode, donc juste quelle que soit la
        disposition du clavier du PC (AZERTY, QWERTY…)."""
        self.pin_watch = None
        pin = get_secret(f"moonlight_pin:{uuid}") if uuid else None
        if not pin:
            if not auto:
                self.toast("Aucun code PIN enregistré", sub="Réglages › Moonlight", icon="warning")
            return
        app = self.apps.current()
        ready = bool(app and app.kind == "moonlight" and self.focus == "app"
                     and self.panel_mode in (None, "splash"))
        if not ready:
            if auto and attempt < 6:
                later(1500, self.type_pin, uuid, True, attempt + 1)
            return
        if not self.set_clipboard(pin):
            self.toast("Saisie du code impossible", sub="wl-copy est introuvable", icon="warning")
            return
        self.splash_hide()
        self.mapper.key("KEY_SPACE")                     # fait apparaître la zone du code PIN
        later(1400, self.mapper.key, "KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_LEFTSHIFT", "KEY_V")
        if not pin.isdigit():                            # un PIN numérique se valide tout seul
            later(2300, self.mapper.key, "KEY_ENTER")
        later(5000, run_async, ["wl-copy", "--clear"])

    def brave_cmd(self, url=None):
        scale = self.settings["browser_scale"] or 1.5
        cmd = ["brave-browser", f"--user-data-dir={BRAVE_PROFILE}", "--remote-debugging-port=9222",
               "--remote-allow-origins=http://127.0.0.1:9222", "--ozone-platform=wayland",
               f"--force-device-scale-factor={scale}", "--no-first-run", "--no-default-browser-check",
               "--password-store=basic", "--enable-spatial-navigation", "--hide-crash-restore-bubble"]
        if url:
            cmd.append(url)
        return cmd

    def launch_brave(self, url=None, tv=False):
        if self.apps.running("brave"):
            if url:
                self.brave.open(url, tv)
            self.resume("brave")
            return True
        self.apps.launch("brave", "Brave", self.brave_cmd(url), "brave", mapper="pointer",
                         splash={"title": "Brave", "kind": "brave", "icon": first_existing(ICON_CANDIDATES["brave"])})
        self.brave.start()
        return True

    def open_site(self, tile):
        return self.launch_brave(tile["url"], bool(tile.get("tv")))

    def on_app_exit(self, app):
        if app.kind == "brave":
            self.brave.stop()
            self.brave_tv = False
        if app.kind in ("esde", "game"):
            dolphin_fix_from_log()
            self.refresh_library()
        if app.kind == "moonlight":
            self.poll_moonlight(force=True)
        if self._profile_name != "balanced":
            self._profile_name = "balanced"
            run_async(["powerprofilesctl", "set", "balanced"])

    # ========================================================= veille / réveil
    def prepare_standby(self):
        self.close_panel()
        app = self.apps.current()
        if app and app.kind == "moonlight":
            self.apps.terminate("moonlight")
        self.show_home()

    def after_wake(self, reason):
        if self.panel_mode == "sleep":
            self.close_panel()
        later(700, self.display.apply)
        self.select_audio(delay=1.5)
        self.set_focus("home")
        self.home.surface.emit("wake", {"reason": reason})
        self.refresh_status()
        later(2500, self.poll_moonlight, True)
        self.refresh_library()

    def on_wake_test_result(self, result):
        self.home.surface.emit("wake-test", result)
        self.push(settings=self.settings.public())

    # =============================================================== évènements
    def on_sway(self, name, data):
        if name == "window":
            self.apps.on_window(data.get("change"), data.get("container"))
        elif name == "output":
            if self._outputs_timer:
                GLib.source_remove(self._outputs_timer)
            self._outputs_timer = later(700, self._outputs_changed)
        elif name == "shutdown":
            Gtk.main_quit()

    def _outputs_changed(self):
        self._outputs_timer = None
        if self.power.state == "on":
            self.display.apply()
            self.select_audio(delay=1.0)
            self.push(display=self.display.summary())

    def bt_state(self):
        return {"available": self.bt.available(), "pairing": self.bt.pairing, "gamepads": self.bt.gamepads()}

    def on_bt(self, kind, data):
        if kind == "pairing":
            self.home.surface.emit("pairing", data)
            if data.get("state") == "paired":
                self.toast("Manette associée", sub=data.get("name"), icon="gamepad")
        self.push(bt=self.bt_state())
        self._check_pad_batteries()

    def _check_pad_batteries(self):
        """Batterie faible : prévenir à 20, 10 puis 5 % (une fois chacun ; oublié après une recharge)."""
        for g in self.bt.gamepads():
            pct = g.get("battery")
            if not g.get("connected") or not isinstance(pct, (int, float)):
                continue
            if pct >= 30:
                self._battery_warned.pop(g["path"], None)
                continue
            level = battery_alert(pct, self._battery_warned.get(g["path"]))
            if level:
                self._battery_warned[g["path"]] = level
                self.toast("Manette : batterie faible", icon="battery", ms=7000,
                           sub=f"{g['name']} · {int(pct)} %" + (" — à recharger vite" if level <= 5 else ""))
                self.pad.rumble(0.5, 260)

    def pads_off(self):
        """Éteint les manettes (comme sur une console) ; la veille suit si le réglage le prévoit."""
        n = sum(1 for g in self.bt.gamepads() if g["connected"])
        self.bt.disconnect_gamepads()
        if n:
            self.toast("Manette éteinte" if n == 1 else "Manettes éteintes", icon="gamepad",
                       sub="Appuie sur son bouton Xbox pour la rallumer")

    def on_setting(self, key, value):
        if key == "guide_hold_ms":
            self.pad.guide_hold = max(0.3, (value or 700) / 1000)
        if key == "resolution":
            self.display.apply()
        self.push(settings=self.settings.public())

    # ============================================================ commandes UI
    def on_ui(self, surface, cmd, args):
        name = surface.name
        handler = getattr(self, "ui_" + cmd.replace("-", "_"), None)
        if handler is None:
            raise ValueError(f"commande inconnue : {cmd}")
        return handler(args, name)

    def ui_state(self, args, src):
        return self.snapshot()

    def ui_log(self, args, src):
        log.info("[%s] %s", src, args.get("msg"))

    def ui_launch(self, args, src):
        return self.launch_tile(args.get("id"))

    def ui_resume(self, args, src):
        self.resume(args.get("app"))

    def ui_close_app(self, args, src):
        self.apps.close(args.get("app"))

    def ui_go_home(self, args, src):
        self.show_home()

    def ui_moonlight_stream(self, args, src):
        return self.moonlight_stream(args["uuid"], args["app"])

    def ui_moonlight_open(self, args, src):
        return self.launch_moonlight()

    def ui_moonlight_pin(self, args, src):
        uuid, pin = args.get("uuid"), (args.get("pin") or "").strip()
        if not uuid:
            raise ValueError("PC inconnu")
        set_secret(f"moonlight_pin:{uuid}", pin or None)
        self.push(moonlight_pins=self.pin_hosts())
        return {"ok": True, "set": bool(pin)}

    def ui_sunshine_auth(self, args, src):
        """Enregistre l'identifiant de la page web de Sunshine (vérifié si le PC répond)."""
        uuid, user, password = args.get("uuid"), (args.get("user") or "").strip(), args.get("password") or ""
        host = next((h for h in (self.moon_hosts or moonlight.load_hosts()) if h["uuid"] == uuid), None)
        if not host:
            raise ValueError("PC inconnu")

        def go(reply):
            def work():
                if not user:
                    pcremote.save_credentials(uuid, None, None)
                    result = {"ok": True, "cleared": True}
                else:
                    st = pcremote.check(host)
                    res = (pcremote.verify_credentials(st, {"user": user, "password": password})
                           if st.get("online") else "offline")
                    if res != "auth":
                        pcremote.save_credentials(uuid, user, password)
                    result = {"ok": res != "auth", "result": res}
                on_main(finish, result)

            def finish(result):
                self.push(pc_remote=self.pc_remote_public())
                reply(result)
            thread(work, name="sunshine-auth")
        return go

    def ui_pc_action(self, args, src):
        """Actions du menu « PC » : wake | restart-sunshine | sleep | reboot | shutdown."""
        uuid, action = args.get("uuid"), args.get("action")
        host = next((h for h in (self.moon_hosts or moonlight.load_hosts()) if h["uuid"] == uuid), None)
        if not host:
            raise ValueError("PC inconnu")
        name = host["name"]

        def go(reply):
            if action == "wake":
                self.wake_pc(host)
                self.toast(f"Réveil de {name} demandé", sub="via le relais" if self.settings["wake_relay"] else None, icon="power")
                later(8000, self.poll_moonlight, True)
                reply({"ok": True})
            elif action == "restart-sunshine":
                st = (self.moon_status or {}).get(uuid) or {}
                if not st.get("online"):
                    reply({"ok": False, "error": f"{name} ne répond pas"})
                    return
                self.toast("Redémarrage de Sunshine…", icon="restart")

                def done(res):
                    if res == "ok":
                        self.toast("Sunshine relancé", icon="check")
                    else:
                        self.toast(*self._repair_message(host, res), icon="warning", ms=8000)
                    reply({"ok": res == "ok", "result": res})
                self._repair_sunshine(host, st, then=done)
            elif action in pcremote.PC_COMMANDS:
                target = self.settings["pc_ssh"]
                if not target:
                    reply({"ok": False, "error": "SSH du PC non configuré"})
                    return
                label = {"sleep": "Mise en veille", "reboot": "Redémarrage", "shutdown": "Arrêt"}[action]

                def work():
                    ok, err = pcremote.pc_power(target, action)
                    on_main(done, ok, err)

                def done(ok, err):
                    if ok:
                        self.toast(f"{label} de {name} demandé", icon="power")
                        later(10000, self.poll_moonlight, True)
                    else:
                        self.toast(f"{label} impossible", sub=err[:80] or "SSH refusé", icon="warning", ms=8000)
                    reply({"ok": ok, "error": err})
                thread(work, name=f"pc-{action}")
            else:
                reply({"ok": False, "error": "action inconnue"})
        return go

    def ui_health(self, args, src):
        """Réglages › Santé. full=True : aussi l'état SMART du SSD (plus lent, droits root en lecture)."""
        full = bool(args.get("full"))
        hosts, status = list(self.moon_hosts or []), dict(self.moon_status or {})
        pads = [{"name": g["name"], "battery": g["battery"]} for g in self.bt.gamepads() if g["connected"]]

        def go(reply):
            def work():
                data = health.collect(full=full)
                pcs = []
                for h in hosts:
                    st = status.get(h["uuid"]) or {}
                    pcs.append({"name": h["name"], "online": st.get("online"), "sunshine": st.get("sunshine"),
                                "latency": health.latency(st.get("address"), st.get("port")) if st.get("online") else None})
                data.update(pcs=pcs, pads=pads)
                data["warnings"] = health.warnings(data, pcs, pads)
                on_main(reply, data)
            thread(work, name="health")
        return go

    def ui_ambient(self, args, src):
        self.ambient = bool(args.get("on"))

    def ui_pads_off(self, args, src):
        self.pads_off()

    def ui_game_launch(self, args, src):
        return self.launch_game(args["system"], args["path"], args.get("name") or "")

    def ui_library_open(self, args, src):
        return self.launch_games(args.get("system"))

    def ui_site_add(self, args, src):
        try:
            tile = self.sites.add(args.get("url"), args.get("title"), args.get("color"),
                                  args.get("control") or "pointer", args.get("tv", False))
        except ValueError as exc:
            return {"error": str(exc)}
        return {"tile": tile}

    def ui_site_remove(self, args, src):
        return self.sites.remove(args.get("id"))

    def ui_tile_move(self, args, src):
        self.sites.move(args.get("id"), int(args.get("delta", 0)))

    def ui_site_update(self, args, src):
        return self.sites.update(args.get("id"), title=args.get("title"), control=args.get("control"),
                                 tv=args.get("tv"))

    def ui_bt_pair_start(self, args, src):
        return self.bt.start_pairing(int(args.get("seconds", 120)))

    def ui_bt_pair_stop(self, args, src):
        self.bt.stop_pairing()

    def ui_bt_forget(self, args, src):
        self.bt.forget(args.get("path"))

    def ui_net_scan(self, args, src):
        def run_scan(reply):
            def work():
                nets = network.scan()
                on_main(reply, nets)
            thread(work, name="wifi-scan")
        return run_scan

    def ui_net_connect(self, args, src):
        ssid, pw = args.get("ssid"), args.get("password") or None

        def connect(reply):
            def work():
                ok, err = network.connect(ssid, pw)
                on_main(reply, {"ok": ok, "error": err})
                on_main(self.refresh_status)
            thread(work, name="wifi-connect")
        return connect

    def ui_net_forget(self, args, src):
        ok, err = network.forget(args.get("ssid"))
        self.refresh_status()
        return {"ok": ok, "error": err}

    def ui_settings_set(self, args, src):
        key = args.get("key")
        if key not in self.settings.public() and key not in ("first_run_done",):
            raise ValueError(f"réglage inconnu : {key}")
        self.settings.set(key, args.get("value"))
        return self.settings.public()

    def ui_power(self, args, src):
        action = args.get("action")
        if action == "standby":
            later(150, self.power.standby, "menu")
        elif action == "reboot":
            run_async(["systemctl", "reboot"])
        elif action == "poweroff":
            run_async(["systemctl", "poweroff"])
        elif action == "restart-ui":
            later(200, Gtk.main_quit)

    def ui_wake_test(self, args, src):
        return self.power.start_wake_test()

    def ui_mem_sleep(self, args, src):
        mode = args.get("mode")
        if mode not in ("s2idle", "deep"):
            raise ValueError("mode invalide")
        code, _, err = run(ROOT_HELPER + ["mem-sleep", mode])
        self.push(sleep=dict(zip(("modes", "current"), mem_sleep_modes())))
        return {"ok": code == 0, "error": err.strip() or None}

    def ui_volume(self, args, src):
        if "set" in args:
            job = lambda: self.audio.set_volume(args["set"])  # noqa: E731
        else:
            job = lambda: self.audio.volume(args.get("delta", 0))  # noqa: E731
        return lambda reply: self.audio_job(job, reply)

    def ui_info(self, args, src):
        disk = shutil.disk_usage(os.path.expanduser("~"))
        return {"version": VERSION, "net": self.net, "display": self.display.summary(),
                "disk": {"free": disk.free, "total": disk.total},
                "hostname": os.uname().nodename, "kernel": os.uname().release}

    def ui_sound(self, args, src):
        return None

    # --- panneau (menu rapide, clavier virtuel) ---
    def ui_panel_close(self, args, src):
        self.close_panel()

    def ui_menu_action(self, args, src):
        action = args.get("action")
        app = self.apps.current()
        _, prof = self.fg_profile

        def keys(combo):
            later(260, self.mapper.key, *combo)
        if action == "resume":
            self.close_panel()
        elif action == "home":
            self.close_panel(self.show_home)
        elif action == "close-app" and app:
            self.close_panel()
            self.apps.close(app.id)
        elif action == "save-state" and prof.get("save"):
            self.close_panel()
            keys(prof["save"])
            later(700, self.toast, "État sauvegardé", None, "save")
        elif action == "load-state" and prof.get("load"):
            self.close_panel()
            keys(prof["load"])
        elif action == "emu-menu" and prof.get("emu_menu"):
            self.close_panel()
            keys(prof["emu_menu"])
        elif action == "quit-game":
            self.close_panel()
            con = self.sway.focused_view()
            if con:
                self.apps.close_window(con["id"])
        elif action == "type-pin" and app:
            uuid = self.pin_for(app)
            self.close_panel()
            later(700, self.type_pin, uuid, False)
        elif action == "quit-stream" and app:
            self.close_panel()
            self.apps.terminate(app.id)
        elif action == "quit-host-app" and app:
            self.close_panel()
            keys(["KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_LEFTSHIFT", "KEY_E"])
        elif action == "standby":
            self.close_panel()
            later(300, self.power.standby, "menu")
        elif action == "pads-off":
            self.close_panel()
            later(300, self.pads_off)
        elif action == "screenshot":
            self.close_panel()
            later(450, self.screenshot)
        elif action == "brave-pin":
            self.close_panel()
            self.pin_current_page()
        elif action == "brave-url":
            self.close_panel(self.open_url_prompt)
        elif action == "brave-osk":
            self.close_panel(lambda: self.on_mapper_action("osk"))
        elif action == "brave-newtab":
            self.close_panel()
            self.brave.new_tab()
        elif action == "brave-closetab":
            self.close_panel()
            self.brave.close_tab()
        elif action == "brave-reload":
            self.close_panel()
            self.brave.reload()
        elif action == "brave-tab":
            self.close_panel()
            self.brave.activate(args.get("id"))
        elif action == "brave-tv":
            self.close_panel()
            self.brave_tv = not self.brave_tv
            self.brave.fullscreen(self.brave_tv)
            self.update_mapper()
        return True

    def ui_osk_commit(self, args, src):
        text, submit = args.get("text", ""), bool(args.get("submit"))
        ctx = self.osk_context or {}
        self.osk_context = None
        target = ctx.get("target")
        if src == "home":
            return True
        self.close_panel()
        if target == "brave":
            def done(ok):
                if not ok:
                    self.type_text(text, submit)
            later(200, self.brave.commit_text, text, submit, done)
        elif target == "brave-url":
            url = normalize_url(text) if "." in text and " " not in text.strip() else None
            url = url or "https://search.brave.com/search?q=" + urllib.parse.quote(text.strip())
            later(150, self.brave.navigate, url)
        else:
            later(200, self.type_text, text, submit)
        return True

    def ui_osk_cancel(self, args, src):
        self.osk_context = None
        if src != "home":
            self.close_panel()

    def ui_toast_done(self, args, src):
        self.toastw.hide()

    def type_text(self, text, submit=False):
        if text:
            run_async(["wtype", "--", text])
        if submit:
            later(150, run_async, ["wtype", "-k", "Return"])

    def screenshot(self):
        os.makedirs(CAPTURES_DIR, exist_ok=True)
        path = os.path.join(CAPTURES_DIR, datetime.datetime.now().strftime("Capture_%Y-%m-%d_%H-%M-%S.png"))

        def done(code, out, err):
            if code == 0:
                self.toast("Capture d'écran enregistrée", sub="Dossier Captures", icon="camera")
        run_async(["grim", path], done)

    def pin_current_page(self):
        def got(info):
            if not info or not info.get("url", "").startswith("http"):
                self.toast("Impossible d'épingler cette page", icon="warning")
                return
            icons = [i.get("href") for i in sorted(info.get("icons", []), key=lambda i: -_size(i.get("sizes", "")))]
            try:
                self.sites.add(info["url"], (info.get("siteName") or info.get("title") or "")[:40] or None,
                               info.get("theme") or None, "tv" if self.brave_tv else "pointer",
                               self.brave_tv, icons=[i for i in icons if i])
                self.toast("Ajouté à l'accueil", sub=info.get("title"), icon="pin")
            except ValueError:
                self.toast("Impossible d'épingler cette page", icon="warning")
        self.brave.site_info(got)

    # ======================================================= console-ctl
    def on_ctl(self, cmd, args):
        if cmd == "guide":
            self.on_guide(False)
        elif cmd == "guide-long":
            self.on_guide(True)
        elif cmd == "power-button":
            if self.power.state == "light":
                self.power.wake("bouton d'alimentation")
            else:
                self.power.standby("bouton d'alimentation")
        elif cmd == "home":
            self.close_panel(self.show_home)
        elif cmd == "volume":
            arg = args[0] if args else 0

            def shown(vol):
                if vol:
                    self.toast("Volume", sub=("muet" if vol.get("muted") else f"{vol.get('volume')} %"),
                               icon="volume", ms=1400)
            self.audio_job(lambda: self.audio.volume(arg), shown)
        elif cmd == "seat-idle":
            self.power.seat(True)
        elif cmd == "seat-active":
            self.power.seat(False)
        elif cmd == "wake":
            self.power.wake("commande")
        elif cmd == "standby":
            self.power.standby("commande")
        elif cmd == "notify":
            self.toast(" ".join(args) or "…")
        elif cmd == "reload-ui":
            for w in (self.home.surface, self.panel.surface, self.toastw.surface):
                w.view.reload()
        elif cmd == "state":
            return self.snapshot()
        elif cmd == "pc-config" and len(args) >= 1:
            key = {"relay": "wake_relay", "relais": "wake_relay", "ssh": "pc_ssh", "pc": "pc_ssh"}.get(args[0])
            if not key:
                raise ValueError("pc-config relay|ssh VALEUR")
            self.settings.set(key, args[1] if len(args) > 1 else "")
            self.push(pc_remote=self.pc_remote_public())
        elif cmd == "launch" and args:
            return {"ok": bool(self.launch_tile(args[0]))}
        elif cmd == "run" and args:
            # Dépannage : lance n'importe quelle commande comme une application de la console.
            self.apps.launch("debug", args[0], list(args), "debug")
        elif cmd == "menu":
            if self.apps.current():
                self.open_quick_menu()
            else:
                self.home.surface.emit("power-menu")
        elif cmd == "close" and args:
            self.apps.close(args[0])
        else:
            return {"error": f"commande inconnue : {cmd}"}
        return {"ok": True}


def _size(sizes):
    try:
        return max(int(s.split("x")[0]) for s in sizes.split())
    except ValueError:
        return 0


def main():
    setup_logging()
    GLib.set_prgname("console-home")
    GLib.set_application_name("Console")
    if not os.environ.get("WAYLAND_DISPLAY"):
        log.error("pas de session Wayland : console-shell doit tourner dans sway")
        sys.exit(1)
    Gtk.init(sys.argv)
    Shell()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda *a: (Gtk.main_quit(), False)[1])
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda *a: (Gtk.main_quit(), False)[1])
    Gtk.main()


if __name__ == "__main__":
    main()
