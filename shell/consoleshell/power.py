"""Veille et réveil « comme une console ».

- Veille profonde (défaut) : vraie mise en veille RAM ; la manette Xbox réveille
  la machine par Bluetooth (si le matériel le permet — d'où le test intégré).
- Veille légère : écran coupé, CPU au ralenti, manettes éteintes ; réveil
  instantané dès qu'une manette se reconnecte.
- Mise en veille automatique : inactivité (manette, clavier) sans vidéo ni son
  en cours, ou manette éteinte depuis 2 minutes.
"""
import glob
import os
import time

from gi.repository import Gio, GLib

from .util import later, every, log, run, run_async

ROOT_HELPER = ["sudo", "-n", "/opt/console/bin/console-root"]


def lid_open():
    for path in glob.glob("/proc/acpi/button/lid/*/state"):
        try:
            with open(path, encoding="utf-8") as f:
                return "open" in f.read()
        except OSError:
            pass
    return None


def wakeup_irq_is_usb():
    """Vrai si la dernière sortie de veille vient du contrôleur USB (adaptateur Bluetooth)."""
    try:
        with open("/sys/power/pm_wakeup_irq", encoding="utf-8") as f:
            irq = f.read().strip()
        with open("/proc/interrupts", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith(f"{irq}:"):
                    return "xhci" in line
    except OSError:
        pass
    return None


def mem_sleep_modes():
    try:
        with open("/sys/power/mem_sleep", encoding="utf-8") as f:
            raw = f.read().split()
    except OSError:
        return [], None
    modes = [m.strip("[]") for m in raw]
    current = next((m.strip("[]") for m in raw if m.startswith("[")), None)
    return modes, current


class Power:
    def __init__(self, shell):
        self.shell = shell
        self.state = "on"                  # on | light | sleeping
        self.last_activity = time.monotonic()
        self.seat_idle = False
        self.no_pad_since = None
        self.resumed_at = None
        self.wake_test = None
        self.inhibit_fd = None
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
            self.bus.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Manager",
                                      "PrepareForSleep", "/org/freedesktop/login1", None,
                                      Gio.DBusSignalFlags.NONE, self._on_prepare_for_sleep)
        except GLib.Error as exc:
            log.error("logind indisponible : %s", exc.message)
            self.bus = None
        self._take_delay_lock()
        every(30000, self.check_idle)

    # ------------------------------------------------------------ activité --
    def activity(self):
        self.last_activity = time.monotonic()
        if self.state == "light":
            self.wake("manette")

    def seat(self, idle):
        self.seat_idle = idle
        if not idle:
            self.activity()

    def controllers(self, count, had_any):
        if count == 0 and had_any:
            self.no_pad_since = self.no_pad_since or time.monotonic()
        else:
            self.no_pad_since = None

    def inhibited(self):
        """Une vidéo, un stream ou de la musique en cours empêchent la veille auto."""
        for view in self.shell.sway.views():
            if view.get("inhibit_idle"):
                return True
        return self.shell.audio.playing()

    def check_idle(self):
        if self.state != "on" or self.shell.busy():
            return True
        settings = self.shell.settings
        now = time.monotonic()
        if (settings["controller_off_standby"] and self.no_pad_since
                and now - self.no_pad_since > 120 and not self.inhibited()):
            log.info("manette éteinte depuis 2 min : mise en veille")
            self.standby("manette éteinte")
            return True
        limit = settings["auto_standby_min"] or 0
        idle_min = (now - self.last_activity) / 60
        if limit and idle_min >= limit and self.seat_idle and not self.inhibited():
            log.info("inactif depuis %d min : mise en veille", idle_min)
            self.standby("inactivité")
        return True

    # --------------------------------------------------------------- veille --
    def standby(self, reason="menu"):
        if self.state != "on":
            return
        if self.shell.settings["standby_mode"] == "light":
            self.light_standby(reason)
        else:
            self.deep_sleep(reason)

    def _prepare(self):
        self.shell.prepare_standby()

    def light_standby(self, reason=""):
        log.info("veille légère (%s)", reason)
        self._prepare()
        self.state = "light"
        self.shell.bt.disconnect_gamepads()
        later(400, self.shell.display.power, False)
        self._profile("power-saver")
        self.shell.cec("standby")

    def deep_sleep(self, reason="", test=False):
        log.info("veille profonde (%s)", reason)
        self._prepare()
        self.state = "sleeping"
        self.shell.show_sleep_curtain()
        later(900, self._suspend)

    def _suspend(self):
        if self.bus is None:
            self._suspend_fallback()
            return
        self._release_delay_lock()
        try:
            self.bus.call_sync("org.freedesktop.login1", "/org/freedesktop/login1",
                               "org.freedesktop.login1.Manager", "Suspend",
                               GLib.Variant("(b)", (False,)), None, Gio.DBusCallFlags.NONE, 10000, None)
        except GLib.Error as exc:
            log.error("Suspend refusé : %s", exc.message)
            self._suspend_fallback()

    def _suspend_fallback(self):
        code, _, err = run(["systemctl", "suspend"])
        if code != 0:
            log.error("impossible de mettre en veille : %s", err)
            self.state = "on"
            self.shell.after_wake("erreur")
            self.shell.toast("La mise en veille a échoué", icon="warning")

    def wake(self, reason=""):
        if self.state != "light":
            return
        log.info("réveil (%s)", reason)
        self.state = "on"
        self.last_activity = time.monotonic()
        self.shell.display.power(True)
        self._profile("balanced")
        self.shell.cec("wake")
        self.shell.after_wake(reason)

    def _on_prepare_for_sleep(self, _conn, _sender, _path, _iface, _signal, params, *_):
        going_down = params.unpack()[0]
        if going_down:
            log.info("le système passe en veille")
            if self.state == "on":          # veille déclenchée ailleurs (bouton, systemctl…)
                self.state = "sleeping"
            self._release_delay_lock()
            return
        log.info("sortie de veille")
        self.state = "on"
        self.resumed_at = time.time()
        self.last_activity = time.monotonic()
        self._take_delay_lock()
        self._profile("balanced")
        self.shell.after_wake("reprise")
        if self.wake_test:
            later(12000, self._finish_wake_test)

    # Verrou « delay » : laisse le temps de couper proprement avant une veille
    # déclenchée par un autre moyen (capot ouvert + bouton d'alimentation, etc.).
    def _take_delay_lock(self):
        if self.bus is None or self.inhibit_fd is not None:
            return
        try:
            res, fds = self.bus.call_with_unix_fd_list_sync(
                "org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager",
                "Inhibit", GLib.Variant("(ssss)", ("sleep", "Console", "Préparation de la veille", "delay")),
                GLib.VariantType("(h)"), Gio.DBusCallFlags.NONE, 5000, None, None)
            self.inhibit_fd = fds.steal_fds()[res.unpack()[0]]
        except (GLib.Error, IndexError, TypeError) as exc:
            log.debug("verrou de veille indisponible : %s", exc)

    def _release_delay_lock(self):
        if self.inhibit_fd is not None:
            try:
                os.close(self.inhibit_fd)
            except OSError:
                pass
            self.inhibit_fd = None

    def _profile(self, name):
        run_async(["powerprofilesctl", "set", name])

    # ---------------------------------------------------- test de réveil --
    def start_wake_test(self, seconds=75):
        code, _, err = run(ROOT_HELPER + ["rtc-alarm", str(seconds)])
        if code != 0:
            log.error("alarme RTC impossible : %s", err)
            return False
        modes, current = mem_sleep_modes()
        self.wake_test = {"t0": time.time(), "alarm": seconds, "mode": current}
        later(1500, self.deep_sleep, "test du réveil", True)
        return True

    def _finish_wake_test(self):
        test, self.wake_test = self.wake_test, None
        if not test:
            return
        run(ROOT_HELPER + ["rtc-alarm", "clear"])
        elapsed = (self.resumed_at or time.time()) - test["t0"]
        by_rtc = elapsed >= test["alarm"] - 4
        usb = wakeup_irq_is_usb()
        pad = bool(self.shell.pads)
        lid = lid_open()
        ok = (not by_rtc) and (usb is True or (pad and lid is not True))
        modes, current = mem_sleep_modes()
        result = {"ok": ok, "elapsed": round(elapsed), "by_rtc": by_rtc, "usb": usb, "pad": pad,
                  "lid_open": lid, "mode": current, "other_modes": [m for m in modes if m != current]}
        log.info("test du réveil : %s", result)
        settings = self.shell.settings
        settings.set("deep_sleep_verified", ok)
        if not ok:
            settings.set("standby_mode", "light")
        self.shell.on_wake_test_result(result)
