"""Applications : lancement, un espace de travail sway par application, retour à l'accueil.

Chaque application lancée par la console vit sur l'espace de travail « app-<id> » ;
l'accueil vit sur « home ». Les fenêtres sont rattachées à leur application par
filiation de processus (pid), sinon à l'application en cours de lancement.
"""
import os
import re
import shutil
import signal
import subprocess
import time

from gi.repository import GLib

from .config import HOME, LOG_DIR
from .util import is_descendant, later, log, run_async

# Profils des fenêtres au premier plan : raccourcis clavier des émulateurs
# (touches indépendantes de la disposition AZERTY/QWERTY) et comportement du bouton Xbox.
PROFILES = [
    ("dolphin", re.compile(r"dolphin", re.I), {
        "title": "Dolphin", "heavy": True,
        "save": ["KEY_LEFTSHIFT", "KEY_F1"], "load": ["KEY_F1"]}),
    ("pcsx2", re.compile(r"pcsx2", re.I), {
        "title": "PCSX2", "heavy": True, "save": ["KEY_F1"], "load": ["KEY_F3"]}),
    ("azahar", re.compile(r"azahar|citra|lime3ds", re.I), {
        "title": "Azahar", "heavy": True,
        "save": ["KEY_LEFTCTRL", "KEY_C"], "load": ["KEY_LEFTCTRL", "KEY_V"]}),
    ("retroarch", re.compile(r"retroarch", re.I), {
        "title": "RetroArch", "save": ["KEY_F2"], "load": ["KEY_F4"], "emu_menu": ["KEY_F1"]}),
    ("moonlight", re.compile(r"moonlight", re.I), {"title": "Moonlight", "guide": "passthrough"}),
    ("esde", re.compile(r"es-de|emulationstation", re.I), {"title": "Bibliothèque"}),
    ("brave", re.compile(r"brave", re.I), {"title": "Brave"}),
]


def window_class(con):
    return con.get("app_id") or (con.get("window_properties") or {}).get("class") or ""


def profile_for(con):
    cls = window_class(con)
    for key, rx, prof in PROFILES:
        if rx.search(cls):
            return key, prof
    return None, {}


class App:
    def __init__(self, app_id, title, cmd, kind, guide="menu", mapper=None, env=None, meta=None):
        self.id = app_id
        self.title = title
        self.cmd = cmd
        self.kind = kind
        self.guide = guide
        self.mapper = mapper
        self.env = env or {}
        self.meta = meta or {}
        self.workspace = f"app-{app_id}"
        self.unit = None
        self.adopted = False
        self.proc = None
        self.pid = None
        self.windows = set()
        self.started = time.monotonic()
        self.closing = False
        self.seen_window = False

    def public(self):
        return {"id": self.id, "title": self.title, "kind": self.kind, "meta": self.meta}


def _scopes_available():
    """Chaque appli tourne dans son propre « scope » systemd : un redémarrage de
    l'interface ne la tue pas, et on peut fermer d'un coup tous ses processus."""
    if not shutil.which("systemd-run"):
        return False
    try:
        return subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "--collect", "true"],
                              capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class AppManager:
    def __init__(self, shell):
        self.shell = shell
        self.sway = shell.sway
        self.apps = {}
        self.pending = None
        self.foreground = None
        self.last_app = None
        self.use_scopes = _scopes_available()
        if not self.use_scopes:
            log.warning("systemd-run indisponible : les applis dépendent du processus de l'interface")

    # ------------------------------------------------------------ lancement --
    def running(self, app_id):
        return app_id in self.apps

    def launch(self, app_id, title, cmd, kind, guide="menu", mapper=None, env=None, meta=None, splash=None):
        if app_id in self.apps:
            self.show(app_id)
            return self.apps[app_id]
        app = App(app_id, title, cmd, kind, guide, mapper, env, meta)
        os.makedirs(LOG_DIR, exist_ok=True)
        logf = open(os.path.join(LOG_DIR, f"{app_id}.log"), "w", encoding="utf-8")  # noqa: SIM115
        full_env = dict(os.environ)
        full_env.update(app.env)
        log.info("lancement %s : %s", app_id, " ".join(cmd))
        self.shell.splash(splash or {"title": title, "kind": kind})
        self.sway.command(f"workspace {app.workspace}")
        run_cmd = list(cmd)
        if self.use_scopes:
            app.unit = f"console-app-{app_id}-{int(time.time())}"
            run_cmd = ["systemd-run", "--user", "--scope", "--quiet", "--collect", f"--unit={app.unit}", "--"] + run_cmd
        try:
            app.proc = subprocess.Popen(run_cmd, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                                        start_new_session=True, env=full_env, cwd=HOME)
        except OSError as exc:
            logf.close()
            log.error("impossible de lancer %s : %s", app_id, exc)
            self.shell.splash_hide()
            self.sway.command("workspace home")
            self.shell.toast(f"Impossible de lancer {title}", icon="warning")
            return None
        logf.close()
        app.pid = app.proc.pid
        self.apps[app_id] = app
        self.pending = app
        self.foreground = app_id
        self.last_app = app_id
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, app.pid, self._on_exit, app_id)
        later(30000, self._launch_timeout, app)
        self.shell.on_apps_changed()
        self.shell.set_focus("app")
        return app

    def _launch_timeout(self, app):
        if self.pending is app:
            self.pending = None
            self.shell.splash_hide()
            if self.apps.get(app.id) is app and not app.windows:
                self.shell.toast(f"{app.title} met du temps à démarrer…", icon="info")

    def _on_exit(self, pid, status, app_id):
        app = self.apps.get(app_id)
        if not app or app.pid != pid:
            return
        del self.apps[app_id]
        try:
            app.proc.returncode = os.waitstatus_to_exitcode(status)
        except (ValueError, AttributeError):
            pass
        quick = time.monotonic() - app.started < 4 and not app.seen_window
        log.info("%s terminé (statut %s)", app_id, status)
        if self.pending is app:
            self.pending = None
            self.shell.splash_hide()
        if quick and not app.closing and status != 0:
            self.shell.toast(f"{app.title} n'a pas pu démarrer", sub="Journal : ~/.local/state/console/logs",
                             icon="warning")
        if self.last_app == app_id:
            self.last_app = next(iter(self.apps), None)
        if self.foreground == app_id:
            self.foreground = None
            self.shell.show_home()
        self.shell.on_app_exit(app)
        self.shell.on_apps_changed()

    # --------------------------------------------------------------- fenêtres --
    def owner(self, pid):
        if pid:
            for app in self.apps.values():
                if app.pid and is_descendant(pid, app.pid):
                    return app
        return None

    def on_window(self, change, con):
        if not con:
            return
        cls = window_class(con)
        if change == "focus":
            self.shell.on_window_focus(con)
            return
        if cls == "console-home":
            return
        con_id = con.get("id")
        if change == "new":
            app = self.owner(con.get("pid")) or self.pending or self.apps.get(self.foreground) \
                or self.apps.get(self.last_app)
            if app is None:
                log.info("fenêtre inconnue (%s) : laissée telle quelle", cls)
                return
            app.windows.add(con_id)
            app.seen_window = True
            floating = con.get("type") == "floating_con"
            cmd = f"[con_id={con_id}] move container to workspace {app.workspace}"
            if not floating:
                cmd += f"; [con_id={con_id}] fullscreen enable"
            self.sway.command(cmd)
            if self.pending is app:
                self.pending = None
                later(350, self.shell.splash_hide)
            if self.foreground == app.id and self.shell.focus == "app":
                self.sway.command(f"workspace {app.workspace}; [con_id={con_id}] focus")
            self.shell.on_window_focus(con)
            self.shell.on_app_window(app, con)
        elif change == "title":
            for app in self.apps.values():
                if con_id in app.windows:
                    self.shell.on_app_window(app, con)
        elif change == "close":
            for app in list(self.apps.values()):
                app.windows.discard(con_id)
                if app.adopted and not app.windows:
                    later(1500, self._check_adopted, app)

    # --------------------------------------------------------- navigation ---
    def show(self, app_id):
        app = self.apps.get(app_id)
        if not app:
            return False
        self.foreground = app_id
        self.last_app = app_id
        self.sway.command(f"workspace {app.workspace}")
        self.shell.set_focus("app")
        return True

    def show_home(self):
        self.foreground = None
        self.sway.command("workspace home")

    def current(self):
        return self.apps.get(self.foreground) if self.foreground else None

    # -------------------------------------------------------------- fermeture --
    def close(self, app_id, grace_ms=5000):
        app = self.apps.get(app_id)
        if not app:
            return
        app.closing = True
        log.info("fermeture de %s", app_id)
        # 1) demande polie : fermeture des fenêtres (comme un clic sur ✕) ; un émulateur en profite
        #    pour sauvegarder la partie, d'où un délai plus long pour eux
        for con_id in sorted(app.windows, reverse=True):
            self.sway.command(f"[con_id={con_id}] kill")
        # 2) puis signaux si nécessaire
        later(grace_ms, self._escalate, app, signal.SIGTERM)
        later(grace_ms + 4000, self._escalate, app, signal.SIGKILL)

    def _escalate(self, app, sig):
        if self.apps.get(app.id) is not app:
            return
        log.info("%s ne répond pas : %s", app.id, sig.name)
        if app.unit:
            run_async(["systemctl", "--user", "kill", f"--signal={sig.name}", f"{app.unit}.scope"])
        try:
            os.killpg(app.pid, sig)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(app.pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        if sig == signal.SIGTERM and app.cmd[:2] == ["flatpak", "run"]:
            flatpak_id = next((a for a in app.cmd[2:] if not a.startswith("-")), None)
            if flatpak_id:
                run_async(["flatpak", "kill", flatpak_id])

    def close_window(self, con_id):
        self.sway.command(f"[con_id={con_id}] kill")

    def terminate(self, app_id, sig=signal.SIGTERM):
        app = self.apps.get(app_id)
        if app:
            app.closing = True
            app.closing_at = time.monotonic()
            if app.unit:
                run_async(["systemctl", "--user", "kill", f"--signal={sig.name}", f"{app.unit}.scope"])
            try:
                os.killpg(app.pid, sig)
            except (ProcessLookupError, PermissionError):
                try:
                    os.kill(app.pid, sig)
                except (ProcessLookupError, PermissionError):
                    pass
            if app.adopted:
                later(1500, self._check_adopted, app)

    # ------------------------------------------------- reprise après redémarrage
    def adopt(self, views):
        """Après un redémarrage de l'interface : reprend les applis encore ouvertes."""
        kinds = {"brave": "brave", "moonlight": "moonlight", "games": "esde"}
        for v in views:
            ws = v.get("_workspace") or ""
            if window_class(v) == "console-home" or not ws.startswith("app-"):
                continue
            app_id = ws[4:]
            app = self.apps.get(app_id)
            if app is None:
                key, prof = profile_for(v)
                app = App(app_id, prof.get("title") or v.get("name") or app_id, [], kinds.get(app_id, app_id),
                          guide=prof.get("guide", "menu"), mapper="pointer" if app_id == "brave" else None)
                app.pid = v.get("pid")
                app.adopted = True
                app.seen_window = True
                self.apps[app_id] = app
                self.last_app = self.last_app or app_id
                log.info("application reprise après redémarrage : %s", app_id)
            app.windows.add(v.get("id"))
        if any(a.adopted for a in self.apps.values()):
            from .util import every
            every(3000, self._poll_adopted)
            self.shell.on_apps_changed()
            if "brave" in self.apps:
                self.shell.brave.start()

    def _poll_adopted(self):
        adopted = [a for a in self.apps.values() if a.adopted]
        for app in adopted:
            self._check_adopted(app)
        return bool(adopted)

    def _check_adopted(self, app):
        if self.apps.get(app.id) is not app:
            return
        alive = True
        try:
            os.kill(app.pid, 0)
        except ProcessLookupError:
            alive = False
        except PermissionError:
            pass
        if not alive or not app.windows:
            del self.apps[app.id]
            if self.foreground == app.id:
                self.foreground = None
                self.shell.show_home()
            if self.last_app == app.id:
                self.last_app = next(iter(self.apps), None)
            self.shell.on_app_exit(app)
            self.shell.on_apps_changed()

    def public(self):
        return {"running": [a.public() for a in self.apps.values()],
                "foreground": self.foreground, "last": self.last_app}
