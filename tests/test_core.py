"""Tests des fonctions « pures » du shell (sans GTK, sans sway).

Lancer :  python3 -m unittest discover -s tests -v
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_HOME = tempfile.mkdtemp(prefix="console-home-")
os.environ["HOME"] = TMP_HOME
for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ.pop(var, None)
sys.path.insert(0, os.path.join(ROOT, "shell"))

from consoleshell import audio, display, emucfg, library, moonlight, network, sites  # noqa: E402


def mode(w, h, r):
    return {"width": w, "height": h, "refresh": r}


class DisplayTests(unittest.TestCase):
    def outputs(self):
        return [
            {"name": "eDP-1", "active": True, "modes": [mode(1920, 1080, 60000)], "current_mode": mode(1920, 1080, 60000), "scale": 1},
            {"name": "DP-1", "active": True, "modes": [mode(1920, 515, 60000)], "current_mode": mode(1920, 515, 60000), "scale": 1},
            {"name": "HDMI-A-1", "active": True, "scale": 1, "current_mode": mode(3840, 2160, 30000),
             "modes": [mode(3840, 2160, 30000), mode(3840, 2160, 24000), mode(1920, 1080, 60000), mode(1920, 1080, 59940),
                       mode(1920, 1080, 50000), mode(1280, 720, 60000)]},
        ]

    def test_screenpad_detected(self):
        self.assertTrue(display.is_screenpad(self.outputs()[1]))
        self.assertTrue(display.is_internal(self.outputs()[1]))
        self.assertFalse(display.is_internal(self.outputs()[2]))

    def test_tv_gets_1080p60_and_internal_off(self):
        cmds, has_tv = display.plan(self.outputs(), "1080p")
        self.assertTrue(has_tv)
        self.assertIn('output "HDMI-A-1" enable mode 1920x1080@60.000Hz scale 1 position 0 0', cmds)
        self.assertIn('output "eDP-1" disable', cmds)
        self.assertIn('output "DP-1" disable', cmds)

    def test_max_policy_avoids_30hz(self):
        m = display.pick_mode(self.outputs()[2], "max")
        self.assertEqual((m["width"], m["height"], m["refresh"]), (1920, 1080, 60000))

    def test_no_tv_falls_back_to_panel(self):
        outs = self.outputs()[:2]
        outs[0]["active"] = False
        cmds, has_tv = display.plan(outs, "1080p")
        self.assertFalse(has_tv)
        self.assertEqual(cmds, ['output "eDP-1" enable', 'output "DP-1" disable'])

    def test_no_redundant_commands(self):
        outs = self.outputs()
        outs[2]["current_mode"] = mode(1920, 1080, 60000)
        outs[0]["active"] = outs[1]["active"] = False
        cmds, _ = display.plan(outs, "1080p")
        self.assertEqual(cmds, [])


class AudioTests(unittest.TestCase):
    def test_choose_plugged_hdmi(self):
        sinks = [
            {"name": "alsa_output.pci.analog-stereo", "description": "Haut-parleurs", "active_port": "analog-output-speaker",
             "ports": [{"name": "analog-output-speaker", "description": "Speakers", "availability": "availability unknown"}]},
            {"name": "alsa_output.pci.hdmi-stereo", "description": "HDMI / DisplayPort", "active_port": "hdmi-output-0",
             "ports": [{"name": "hdmi-output-0", "description": "HDMI / DisplayPort", "availability": "available"}]},
            {"name": "alsa_output.pci.hdmi-stereo-extra1", "description": "HDMI / DisplayPort 2", "active_port": "hdmi-output-1",
             "ports": [{"name": "hdmi-output-1", "description": "HDMI / DisplayPort 2", "availability": "not available"}]},
        ]
        sink, port = audio.choose_sink(sinks)
        self.assertEqual(sink["name"], "alsa_output.pci.hdmi-stereo")
        self.assertIsNone(port)

    def test_ucm_sink_named_without_hdmi(self):
        sinks = [{"name": "alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__hw_sofhdadsp_3__sink",
                  "description": "HDMI1", "active_port": "[Out] HDMI1",
                  "ports": [{"name": "[Out] HDMI1", "description": "HDMI1", "availability": "available"}]}]
        sink, _ = audio.choose_sink(sinks)
        self.assertIsNotNone(sink)

    def test_none_when_no_hdmi(self):
        self.assertEqual(audio.choose_sink([{"name": "x", "description": "Speakers", "ports": []}]), (None, None))


class MoonlightTests(unittest.TestCase):
    def test_qs_unescape(self):
        self.assertEqual(moonlight.qs_unescape(r'@ByteArray(\0\x11\"3DU)'), b'\x00\x11"3DU')
        self.assertEqual(moonlight.qs_unescape(r'"Halo, the game"'), "Halo, the game")
        self.assertEqual(moonlight.qs_unescape(r"caf\xe9"), "café")

    def test_load_hosts(self):
        conf = r"""[General]
width=1920

[hosts]
1\apps\1\hdr=false
1\apps\1\hidden=false
1\apps\1\id=881448767
1\apps\1\name=Desktop
1\apps\2\hidden=true
1\apps\2\id=12
1\apps\2\name=Cach\xe9
1\apps\3\id=1093255277
1\apps\3\name="Steam Big Picture, Beta"
1\apps\size=3
1\customname=
1\hostname=PC-SALON
1\localaddress=192.168.1.10
1\localport=47989
1\mac=@ByteArray(\0\x11\"3DU)
1\manualaddress=
1\uuid=7C3B0D2A-0000-1111-2222-333344445555
size=1
"""
        path = os.path.join(TMP_HOME, "Moonlight.conf")
        with open(path, "w", encoding="utf-8") as f:
            f.write(conf)
        hosts = moonlight.load_hosts(path)
        self.assertEqual(len(hosts), 1)
        h = hosts[0]
        self.assertEqual(h["name"], "PC-SALON")
        self.assertEqual(h["mac"], "00:11:22:33:44:55")
        self.assertEqual(h["addresses"], [("192.168.1.10", 47989)])
        self.assertEqual([a["name"] for a in h["apps"]], ["Desktop", "Steam Big Picture, Beta"])
        self.assertEqual(moonlight.stream_cmd(h["uuid"], "Desktop")[-3:], ["stream", h["uuid"], "Desktop"])


class MoonlightLaunchTests(unittest.TestCase):
    HOST = {"uuid": "u1", "name": "PC", "mac": "00:11:22:33:44:55", "addresses": [("192.168.1.10", 47989)],
            "apps": [{"id": 1, "name": "Desktop"}, {"id": 2, "name": "Steam Big Picture (Beta)"}]}

    def test_find_app(self):
        self.assertEqual(moonlight.find_app(self.HOST, "desktop")["id"], 1)
        self.assertEqual(moonlight.find_app(self.HOST, "Steam Big Picture")["id"], 2)
        self.assertIsNone(moonlight.find_app(self.HOST, "Cyberpunk"))
        self.assertIsNone(moonlight.find_app(None, "Desktop"))

    def test_magic_packet(self):
        pkt = moonlight.magic_packet("00:11:22:33:44:55")
        self.assertEqual(len(pkt), 102)
        self.assertEqual(pkt[:6], b"\xff" * 6)
        self.assertEqual(pkt[6:12], bytes.fromhex("001122334455"))
        with self.assertRaises(ValueError):
            moonlight.magic_packet("00:11")

    def test_wake_does_not_raise(self):
        self.assertTrue(moonlight.wake(self.HOST))
        self.assertFalse(moonlight.wake({"name": "x", "mac": ""}))


class SecretsTests(unittest.TestCase):
    def test_secret_file_is_private(self):
        from consoleshell import config
        config.set_secret("moonlight_pin:u1", "123456")
        self.assertEqual(config.get_secret("moonlight_pin:u1"), "123456")
        self.assertEqual(os.stat(config.SECRETS_PATH).st_mode & 0o777, 0o600)
        self.assertIn("moonlight_pin:u1", config.secret_keys())
        config.set_secret("moonlight_pin:u1", None)
        self.assertIsNone(config.get_secret("moonlight_pin:u1"))


class LibraryTests(unittest.TestCase):
    def test_recent_from_gamelist(self):
        roms = os.path.join(TMP_HOME, "ROMs", "gc")
        os.makedirs(roms, exist_ok=True)
        open(os.path.join(roms, "Metroid Prime.rvz"), "w").close()
        open(os.path.join(roms, "_LISEZMOI.txt"), "w").close()
        gl = os.path.join(TMP_HOME, "ES-DE", "gamelists", "gc")
        os.makedirs(gl, exist_ok=True)
        with open(os.path.join(gl, "gamelist.xml"), "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0"?>\n<alternativeEmulator>\n\t<label>Dolphin (Standalone)</label>\n'
                    '</alternativeEmulator>\n<gameList>\n<game><path>./Metroid Prime.rvz</path><name>Metroid Prime</name>'
                    '<playcount>3</playcount><lastplayed>20261102T203015</lastplayed></game>\n</gameList>\n')
        self.assertEqual(library.count_games("gc"), 1)
        rec = library.recent()
        self.assertEqual(rec[0]["name"], "Metroid Prime")
        self.assertTrue(rec[0]["direct"])
        cmd = library.command("gc", rec[0]["path"])
        self.assertTrue(cmd[0].endswith("/bin/console-emu"))                 # reprise des parties
        self.assertEqual(cmd[1:], ["dolphin", "-b", "-e", rec[0]["path"]])

    def test_directory_shown_as_one_game(self):
        """« Jeu.m3u/ » contenant « Jeu.m3u » et ses disques : un seul jeu, comme dans ES-DE."""
        from consoleshell import covers
        d = os.path.join(TMP_HOME, "ROMs", "wii", "Xenoblade.m3u")
        os.makedirs(d, exist_ok=True)
        for f in ("Xenoblade.m3u", "Xenoblade (Disc 1).rvz", "Xenoblade (Disc 2).rvz"):
            open(os.path.join(d, f), "w").close()
        self.assertEqual(library.count_games("wii"), 1)
        self.assertEqual(covers.games("wii"), [d])
        self.assertTrue(covers.media_path("wii", d, "covers").endswith(os.path.join("wii", "covers", "Xenoblade.m3u.png")))
        self.assertEqual(library.command("wii", d)[-1], os.path.join(d, "Xenoblade.m3u"))

    def test_find_game(self):
        """console-ctl jeu TEXTE : trouver un jeu par une partie de son nom, sans accents ni casse."""
        n64 = os.path.join(TMP_HOME, "ROMs", "n64")
        os.makedirs(os.path.join(n64, "Europe"), exist_ok=True)
        sm64 = os.path.join(n64, "Super Mario 64 (Europe) (En,Fr,De).z64")
        open(sm64, "w").close()
        open(os.path.join(n64, "_LISEZMOI.txt"), "w").close()
        rayman = os.path.join(n64, "Europe", "Rayman 2 - The Great Escape (Europe).z64")
        open(rayman, "w").close()
        self.assertEqual(library.find_game("mario 64"), ("n64", sm64, "Super Mario 64 (Europe) (En,Fr,De)"))
        self.assertEqual(library.find_game("RAYMAN great")[1], rayman)          # un sous-dossier
        xeno = os.path.join(TMP_HOME, "ROMs", "wii", "Xenoblade.m3u")              # dossier vu comme un jeu
        os.makedirs(xeno, exist_ok=True)
        open(os.path.join(xeno, "Xenoblade.m3u"), "w").close()
        self.assertEqual(library.find_game("Xénoblade")[1], xeno)
        self.assertIsNone(library.find_game("lisezmoi"))
        self.assertIsNone(library.find_game("   "))

    def test_game_of(self):
        """Fichier passé à l'émulateur → système, chemin dans la bibliothèque, nom du jeu."""
        roms = os.path.join(TMP_HOME, "ROMs")
        sm64 = os.path.join(roms, "n64", "Super Mario 64 (Europe).z64")
        self.assertEqual(library.game_of(sm64), ("n64", sm64, "Super Mario 64 (Europe)"))
        ff = os.path.join(roms, "psx", "FF7.m3u")
        os.makedirs(ff, exist_ok=True)
        open(os.path.join(ff, "FF7.m3u"), "w").close()
        self.assertEqual(library.game_of(os.path.join(ff, "FF7.m3u")), ("psx", ff, "FF7"))
        self.assertEqual(library.game_of("/ailleurs/jeu.gb"), (None, "/ailleurs/jeu.gb", "jeu"))
        self.assertEqual(library.game_of(None), (None, None, None))

    def test_set_startup(self):
        library.set_startup("ps2")
        with open(library.SETTINGS_XML, encoding="utf-8") as f:
            text = f.read()
        self.assertIn('<string name="StartupSystem" value="ps2" />', text)
        library.set_startup(None)
        with open(library.SETTINGS_XML, encoding="utf-8") as f:
            text = f.read()
        self.assertIn('<string name="StartupView" value="system" />', text)
        self.assertEqual(text.count("StartupSystem"), 1)


class NetworkTests(unittest.TestCase):
    def test_split_terse(self):
        self.assertEqual(network.split_terse(r"*:Box\:5G:82:WPA2"), ["*", "Box:5G", "82", "WPA2"])
        self.assertEqual(network.split_terse(r"wifi:connected:Ma\\Box:wlan0"), ["wifi", "connected", "Ma\\Box", "wlan0"])


class SitesTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(sites.normalize_url("youtube.com"), "https://youtube.com")
        self.assertEqual(sites.normalize_url("http://x.fr/a?b=1"), "http://x.fr/a?b=1")
        self.assertIsNone(sites.normalize_url("pas une adresse"))
        self.assertIsNone(sites.normalize_url("javascript:alert(1)"))

    def test_best_icon(self):
        icons = [{"href": "/favicon.ico", "rel": "icon", "sizes": ""},
                 {"href": "/apple.png", "rel": "apple-touch-icon", "sizes": ""},
                 {"href": "/icon-512.png", "rel": "icon", "sizes": "512x512"}]
        self.assertEqual(sites.best_icon(icons, "https://ex.com/page")[0], "https://ex.com/icon-512.png")


class EmuCfgTests(unittest.TestCase):
    def test_dolphin_device_update(self):
        d = emucfg.DOLPHIN_CFG
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "GCPadNew.ini"), "w", encoding="utf-8") as f:
            f.write("[GCPad1]\nDevice = SDL/0/Xbox Series X Controller\nButtons/A = `Button S`\n[GCPad2]\nDevice = XInput2/0/Virtual core pointer\n")
        with open(os.path.join(d, "WiimoteNew.ini"), "w", encoding="utf-8") as f:
            f.write("[Wiimote1]\nDevice = SDL/0/Xbox Series X Controller\n")
        emucfg.dolphin_set_controller("Xbox One S Controller")
        text = open(os.path.join(d, "GCPadNew.ini"), encoding="utf-8").read()
        self.assertIn("Device = SDL/0/Xbox One S Controller", text)
        self.assertIn("Device = XInput2/0/Virtual core pointer", text)


class IniSetTests(unittest.TestCase):
    def test_iniset(self):
        path = os.path.join(TMP_HOME, "main.conf")
        with open(path, "w", encoding="utf-8") as f:
            f.write("[General]\n#FastConnectable = false\nName = BlueZ\n\n[Policy]\nAutoEnable=false\n")
        subprocess.run([sys.executable, os.path.join(ROOT, "lib", "iniset.py"), path, "General", "FastConnectable", "true",
                        "Privacy", "device"], check=True)
        subprocess.run([sys.executable, os.path.join(ROOT, "lib", "iniset.py"), path, "Policy", "AutoEnable", "true"], check=True)
        subprocess.run([sys.executable, os.path.join(ROOT, "lib", "iniset.py"), path, "LE", "MinConnectionInterval", "7"], check=True)
        text = open(path, encoding="utf-8").read()
        self.assertIn("#FastConnectable = false\nFastConnectable = true\n", text)
        self.assertIn("Privacy = device", text)
        self.assertIn("AutoEnable = true", text)
        self.assertNotIn("AutoEnable=false", text)
        self.assertTrue(text.rstrip().endswith("[LE]\nMinConnectionInterval = 7"))


class HealthTests(unittest.TestCase):
    def _tree(self, files):
        root = tempfile.mkdtemp()
        for rel, content in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
        return root

    def test_temperatures_memory_readonly(self):
        from consoleshell import health
        sysfs = self._tree({"class/hwmon/hwmon0/name": "acpitz\n", "class/hwmon/hwmon1/name": "coretemp\n",
                            "class/hwmon/hwmon1/temp1_input": "61000\n", "class/hwmon/hwmon2/name": "nvme\n",
                            "class/hwmon/hwmon2/temp1_input": "43850\n"})
        self.assertEqual(health.temperatures(sysfs), {"cpu": 61.0, "ssd": 43.9})
        fallback = self._tree({"class/thermal/thermal_zone0/type": "x86_pkg_temp", "class/thermal/thermal_zone0/temp": "72000"})
        self.assertEqual(health.temperatures(fallback)["cpu"], 72.0)
        proc = self._tree({"meminfo": "MemTotal:        7864320 kB\nMemFree: 100 kB\nMemAvailable:    2097152 kB\n",
                           "mounts": "/dev/nvme0n1p2 / ext4 ro,relatime,errors=remount-ro 0 0\n"})
        self.assertEqual(health.memory(proc), {"total": 7864320 * 1024, "available": 2097152 * 1024})
        self.assertTrue(health.root_readonly(proc))

    def test_smart_and_warnings(self):
        from consoleshell import health
        smart = {"model_name": "INTEL SSDPEKNW512G8", "smart_status": {"passed": True},
                 "nvme_smart_health_information_log": {"critical_warning": 0, "temperature": 41, "available_spare": 100,
                                                       "percentage_used": 1, "media_errors": 0, "unsafe_shutdowns": 82,
                                                       "power_on_hours": 437}}
        s = health.smart_summary(smart)
        self.assertEqual((s["model"], s["percentage_used"], s["unsafe_shutdowns"]), ("INTEL SSDPEKNW512G8", 1, 82))
        ok = {"ssd": s, "io_errors": 0, "disk": {"free": 200e9}, "temps": {"cpu": 55}, "memory": {"available": 3e9},
              "tailscale": {"running": True}}
        self.assertEqual(health.warnings(ok), [])
        bad = dict(ok, io_errors=7, readonly=True, tailscale={"running": False}, disk={"free": 4e9})
        levels = [w["level"] for w in health.warnings(bad, pcs=[{"name": "PC", "online": True, "sunshine": "half"}],
                                                      pads=[{"name": "Manette", "battery": 15}])]
        self.assertEqual(levels, ["bad", "bad", "warn", "warn", "warn", "warn"])


class BatteryTests(unittest.TestCase):
    def test_low_battery_thresholds(self):
        from consoleshell.util import battery_alert
        seq, last, alerts = [80, 35, 21, 19, 18, 12, 9, 6, 4, 3, 40, 15], None, []
        for pct in seq:
            if pct >= 30:
                last = None
            lvl = battery_alert(pct, last)
            if lvl:
                last = lvl
                alerts.append((pct, lvl))
        self.assertEqual(alerts, [(19, 20), (9, 10), (4, 5), (15, 20)])
        self.assertIsNone(battery_alert(None, None))


class PcRemoteTests(unittest.TestCase):
    """PC distant : santé de Sunshine (demi-plantage), relance, réveil par relais."""

    def _server(self, behaviour):
        """Serveur TCP local : « close » répond en fermant (comme un refus TLS), « silent » accepte et se tait."""
        import socket
        import threading
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)
        conns = []

        def loop():
            while True:
                try:
                    c, _ = srv.accept()
                except OSError:
                    return
                conns.append(c)
                if behaviour == "close":
                    c.close()
        threading.Thread(target=loop, daemon=True).start()
        self.addCleanup(lambda: ([c.close() for c in conns], srv.close()))
        return srv.getsockname()[1]

    def _serverinfo(self, https_port):
        import http.server
        import threading
        xml = (f'<root status_code="200"><hostname>PC-SALON</hostname><HttpsPort>{https_port}</HttpsPort>'
               f'<state>SUNSHINE_SERVER_FREE</state></root>').encode()

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(xml)

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return srv.server_address[1]

    def test_https_alive(self):
        from consoleshell import pcremote
        self.assertTrue(pcremote.https_alive("127.0.0.1", self._server("close"), timeout=1))
        self.assertFalse(pcremote.https_alive("127.0.0.1", self._server("silent"), timeout=0.5))
        self.assertFalse(pcremote.https_alive("127.0.0.1", 9, timeout=0.5))      # rien n'écoute

    def test_check_detects_half_crash(self):
        from consoleshell import pcremote
        for behaviour, expected in (("close", "ok"), ("silent", "half")):
            https = self._server(behaviour)
            host = {"uuid": "u", "addresses": [("127.0.0.1", self._serverinfo(https))]}
            orig = pcremote.https_alive
            pcremote.https_alive = lambda a, p, timeout=3.0: orig(a, p, timeout=0.5)
            try:
                st = pcremote.check(host)
            finally:
                pcremote.https_alive = orig
            self.assertEqual((st["online"], st["https_port"], st["sunshine"]), (True, https, expected))

    def test_restart_outcomes(self):
        from consoleshell import pcremote
        st = {"address": "127.0.0.1", "port": 47989, "https_port": 47984}
        creds = {"user": "u", "password": "p"}
        saved = pcremote.api, pcremote.https_alive, pcremote.time.sleep
        pcremote.time.sleep = lambda s: None
        try:
            for api_result, alive, expected in (((401, ""), True, "auth"), ((None, "Connection refused"), True, "unreachable"),
                                                ((0, "connexion coupée"), True, "ok"), ((None, "timed out"), True, "ok"),
                                                ((200, "{}"), False, "stuck")):
                pcremote.api = lambda *a, r=api_result, **k: r
                pcremote.https_alive = lambda *a, v=alive, **k: v
                self.assertEqual(pcremote.restart_sunshine(st, creds, wait=0.05), expected, api_result)
        finally:
            pcremote.api, pcremote.https_alive, pcremote.time.sleep = saved

    def test_relay_wake_command(self):
        import shlex
        from consoleshell import pcremote
        parts = shlex.split(pcremote.relay_wake_command("AA:BB:CC:DD:EE:0F"))
        self.assertEqual(parts[:2], ["python3", "-c"])
        compile(parts[2], "wol", "exec")                     # Python valide côté relais
        self.assertIn("bytes.fromhex('aabbccddee0f')", parts[2])
        self.assertEqual(parts[3:], ["||", "wakeonlan", "aa:bb:cc:dd:ee:0f"])
        with self.assertRaises(ValueError):
            pcremote.relay_wake_command("")

    def test_credentials_are_secret(self):
        from consoleshell import config, pcremote
        pcremote.save_credentials("pc1", "joueur", "s3cret")
        self.assertEqual(pcremote.credentials("pc1"), {"user": "joueur", "password": "s3cret"})
        self.assertEqual(os.stat(config.SECRETS_PATH).st_mode & 0o777, 0o600)
        pcremote.save_credentials("pc1", "", "")
        self.assertIsNone(pcremote.credentials("pc1"))


class ThreadTests(unittest.TestCase):
    def test_threads_dont_shadow_thread_internals(self):
        # Python 3.13 range un objet dans Thread._handle : une méthode « _handle » le masquait
        # et la lecture des manettes plantait au premier évènement (Debian 13).
        import threading
        from consoleshell.control import ControlServer
        from consoleshell.gamepad import GamepadThread
        from consoleshell.swayipc import SwayEvents
        internals = set(vars(threading.Thread())) | {"_handle", "_started", "_stop", "_bootstrap"}
        internals |= {n for n in vars(threading.Thread) if n.startswith("_") and not n.startswith("__")}
        for cls in (GamepadThread, SwayEvents, ControlServer):
            clash = internals & set(vars(cls))
            self.assertFalse(clash, f"{cls.__name__} masque des attributs internes de Thread : {clash}")
        self.assertTrue(callable(GamepadThread(lambda ev: None)._handle_event))


class ExclusivePadTests(unittest.TestCase):
    """Menu de la console au-dessus d'une appli : manette réservée (EVIOCGRAB), lue en evdev brut."""

    def setUp(self):
        import collections
        import types
        from consoleshell import gamepad
        self.gp = gamepad
        Ev = collections.namedtuple("Ev", "type code value")
        self.Ev = Ev
        Abs = collections.namedtuple("Abs", "value min max fuzz flat resolution")
        test = self

        class FakeDevice:
            abs_codes = {0: (-32768, 32767), 1: (-32768, 32767), 3: (-32768, 32767), 4: (-32768, 32767),
                         2: (0, 1023), 5: (0, 1023), 16: (-1, 1), 17: (-1, 1)}

            def __init__(self, path):
                self.path, self.grabbed, self.closed, self.queue = path, False, False, []
                test.devices.append(self)

            def grab(self):
                self.grabbed = True

            def ungrab(self):
                self.grabbed = False

            def close(self):
                self.closed = True

            def capabilities(self):
                return {3: [(c, Abs(0, lo, hi, 0, 0, 0)) for c, (lo, hi) in self.abs_codes.items()]}

            def read(self):
                if self.queue == "gone":
                    raise OSError(19, "No such device")
                if not self.queue:
                    raise BlockingIOError
                out, self.queue = self.queue, []
                return out

        self.devices = []
        self.FakeDevice = FakeDevice
        self._saved = sys.modules.get("evdev")
        sys.modules["evdev"] = types.SimpleNamespace(InputDevice=FakeDevice)
        self._on_main = gamepad.on_main
        gamepad.on_main = lambda fn, *a, **k: fn(*a, **k)
        self.events = []
        self.t = gamepad.GamepadThread(self.events.append)
        self.pad = gamepad.Pad(None, 7, {"id": 7, "name": "Xbox Wireless Controller", "kind": "xbox"})
        self.pad.path = "/dev/input/event23"
        self.t.pads[7] = self.pad

    def tearDown(self):
        self.gp.on_main = self._on_main
        if self._saved is None:
            sys.modules.pop("evdev", None)
        else:
            sys.modules["evdev"] = self._saved

    def step(self, *events):
        if events:
            self.devices[-1].queue = list(events)
        self.t._process_requests()
        if self.t.exclusive:
            self.t._exclusive_tick()
        self.t._tick(__import__("time").monotonic(), 0.01)

    def names(self):
        out = [(e["type"], e.get("button")) for e in self.events if e["type"] in ("button", "button-up", "guide")]
        self.events.clear()
        return out

    def test_waits_for_release_then_reads_raw_and_releases_cleanly(self):
        Ev = self.Ev
        self.t._button(self.pad, "guide", True)          # appui long en cours (vu par SDL)
        self.t.set_exclusive(True)
        self.step()
        self.assertEqual(self.devices, [], "pas de saisie tant que le bouton Xbox est enfoncé")
        self.t._button(self.pad, "guide", False)          # relâché : Moonlight a vu appui + relâchement
        self.step()
        self.assertTrue(self.devices and self.devices[-1].grabbed)
        self.names()
        self.step(Ev(3, 17, 1), Ev(3, 17, 0), Ev(1, 0x130, 1), Ev(1, 0x130, 0), Ev(1, 0x133, 1))
        self.assertEqual(self.names(), [("button", "down"), ("button-up", "down"), ("button", "a"),
                                        ("button-up", "a"), ("button", "x")])
        self.step(Ev(3, 1, 32767))                        # stick gauche vers le bas → navigation
        self.assertIn(("button", "down"), self.names())
        self.step(Ev(1, 172, 1), Ev(1, 172, 0))           # bouton Xbox des manettes BLE (KEY_HOMEPAGE)
        self.assertIn(("guide", None), self.names())
        self.t.set_exclusive(False)                       # menu fermé (X et stick encore tenus)
        self.step()
        dev = self.devices[-1]
        self.assertTrue(dev.closed and not dev.grabbed)
        self.assertEqual((self.pad.held, self.pad.stick_dir, self.pad.axes), ({}, None, [0.0] * 6))

    def test_controller_switched_off_during_menu(self):
        self.t.set_exclusive(True)
        self.step()
        self.devices[-1].queue = "gone"
        self.step()
        self.assertTrue(self.devices[-1].closed)
        self.assertIsNone(self.pad.dev)

    def test_wakes_up_immediately_on_controller_event(self):
        import time
        r, w = os.pipe()
        os.set_blocking(r, False)
        self.pad.wake_fd = r                  # tient lieu du nœud evdev de la manette
        try:
            t0 = time.monotonic()
            threading = __import__("threading")
            threading.Timer(0.05, lambda: os.write(w, b"x" * 24)).start()
            self.t._wait(2.0)
            woke = time.monotonic() - t0
            self.assertLess(woke, 0.5, "le thread doit se réveiller dès l'évènement, pas à l'échéance")
            t1 = time.monotonic()
            self.t._wait(0.15)                # évènement consommé : on attend bien l'échéance
            self.assertGreater(time.monotonic() - t1, 0.12)
        finally:
            os.close(w)
            self.t._close_wake(self.pad)

    def test_layouts(self):
        lay = self.gp.raw_layout(self.FakeDevice("/x"), "xbox")
        self.assertEqual((lay["buttons"][0x133], lay["axes"][2][1], lay["axes"][3][0]), ("x", "trigger", 2))
        self.assertEqual(self.gp.raw_layout(self.FakeDevice("/x"), "playstation")["buttons"][0x133], "y")
        self.FakeDevice.abs_codes = {0: (0, 65535), 1: (0, 65535), 2: (0, 65535), 5: (0, 65535),
                                     9: (0, 1023), 10: (0, 1023)}
        ble = self.gp.raw_layout(self.FakeDevice("/x"), "xbox")["axes"]   # Xbox BLE, pilote générique
        self.assertEqual((ble[10][0], ble[9][0], ble[2][0], ble[5][0]), (4, 5, 2, 3))


class CoversTests(unittest.TestCase):
    """Jaquettes automatiques : correspondance des noms, choix de la version, téléchargement."""

    NAMES = [
        "Pokemon - Emerald Version (USA, Europe).png", "Pokemon - Emerald Version (USA, Europe) (Alternate).png",
        "Pokemon - Version Emeraude (France).png",
        "Legend of Zelda, The - The Minish Cap (Europe) (En,Fr,De,Es,It).png",
        "Legend of Zelda, The - The Minish Cap (USA).png",
        "Legend of Zelda, The - The Minish Cap (USA) (Demo) (Kiosk).png",
        "Legend of Zelda, The - A Link to the Past _ Four Swords (Europe) (En,Fr,De,Es,It).png",
        "Advance Wars (Europe) (En,Fr,De,Es).png", "Advance Wars 2 - Black Hole Rising (Europe) (En,Fr,De,Es,It).png",
        "Top Spin 2 (Europe) (En,Fr,De,Es,It).png", "Fire Pro Wrestling A (Japan).png",
        "Final Fantasy VII (Europe) (Disc 1).png", "Final Fantasy VII (France) (Disc 1).png",
        "Final Fantasy VII (France) (Disc 2).png", "Final Fantasy VII (USA) (Disc 1).png",
        "Golden Sun (Europe).png", "Golden Sun (France).png", "Golden Sun (USA).png",
        "Spider-Man 2 (Europe).png", "1080° Avalanche (Europe).png",
    ]

    def setUp(self):
        from consoleshell import covers
        self.covers = covers
        self.index = covers.Index(self.NAMES)

    def test_title_key(self):
        k = self.covers.title_key
        self.assertEqual(k("Legend of Zelda, The - The Minish Cap (Europe) (En,Fr,De)"), "legend zelda minish cap")
        self.assertEqual(k("The Legend of Zelda: The Minish Cap [!]"), "legend zelda minish cap")
        self.assertEqual(k("Pokémon Émeraude"), "pokemon emeraude")
        self.assertEqual(k("Final Fantasy VII"), k("Final Fantasy 7"))
        self.assertEqual(k("Kirby's Dream Land"), "kirbys dream land")

    def test_tags(self):
        t = self.covers.tag_info
        self.assertEqual(t("X (USA, Europe)")["regions"], {"us", "eu"})
        self.assertEqual(t("X (UE) [!]")["regions"], {"us", "eu"})
        self.assertEqual(t("X (F)")["regions"], {"fr"})
        self.assertEqual(t("X (Europe) (En,Fr,De)")["langs"], {"en", "fr", "de"})
        self.assertEqual(t("X (France) (Disc 2)")["disc"], 2)
        self.assertTrue(t("X (USA) (Rev 1)")["rev"])
        self.assertEqual(t("X (USA) (Demo) (Kiosk)")["bad"], {"demo", "kiosk"})
        self.assertEqual(t("X (USA) (Alternate)")["bad"], {"alt"})

    def test_match(self):
        m = self.index.match
        self.assertEqual(m("Pokemon - Emerald Version (USA, Europe).gba"), "Pokemon - Emerald Version (USA, Europe).png")
        self.assertEqual(m("Pokemon Emerald (U) [!].gba"), "Pokemon - Emerald Version (USA, Europe).png")   # pas « Alternate »
        self.assertEqual(m("pokemon_emerald.gba"), "Pokemon - Emerald Version (USA, Europe).png")
        self.assertEqual(m("1986 - Pokemon Emerald (U)(TrashMan).gba"), "Pokemon - Emerald Version (USA, Europe).png")
        self.assertEqual(m("Pokémon Émeraude.gba"), "Pokemon - Version Emeraude (France).png")
        self.assertEqual(m("The Legend of Zelda - The Minish Cap (U).gba"), "Legend of Zelda, The - The Minish Cap (USA).png")
        self.assertEqual(m("Zelda Minish Cap.gba"), "Legend of Zelda, The - The Minish Cap (Europe) (En,Fr,De,Es,It).png")
        self.assertEqual(m("Legend of Zelda, The - A Link to the Past & Four Swords (Europe) (En,Fr,De,Es,It).gba"),
                         "Legend of Zelda, The - A Link to the Past _ Four Swords (Europe) (En,Fr,De,Es,It).png")
        self.assertEqual(m("Advance Wars 2.gba"), "Advance Wars 2 - Black Hole Rising (Europe) (En,Fr,De,Es,It).png")
        self.assertEqual(m("Advance Wars.gba"), "Advance Wars (Europe) (En,Fr,De,Es).png")
        self.assertEqual(m("Golden Sun.gba"), "Golden Sun (France).png")                    # console française
        self.assertEqual(m("Golden Sun (USA).gba"), "Golden Sun (USA).png")                 # sa propre région d'abord
        self.assertEqual(m("Final Fantasy VII (France).m3u"), "Final Fantasy VII (France) (Disc 1).png")
        self.assertEqual(m("Final Fantasy VII (France) (Disc 2).chd"), "Final Fantasy VII (France) (Disc 2).png")
        self.assertEqual(m("Final Fantasy 7 - Disc 2.chd"), "Final Fantasy VII (France) (Disc 2).png")
        self.assertEqual(m("Spiderman 2.iso"), "Spider-Man 2 (Europe).png")
        self.assertEqual(m("1080 Avalanche.rvz"), "1080° Avalanche (Europe).png")
        # Jamais une autre suite ni un autre jeu au nom voisin
        self.assertIsNone(m("Top Spin.iso"))
        self.assertIsNone(m("Fire Pro Wrestling Z.iso"))
        self.assertIsNone(m("Pokemon.gba"))

    def test_parse_index(self):
        page = ('<html><body><h1>Index of /Nintendo - Game Boy Advance/Named_Boxarts/</h1><a href="../">../</a>\n'
                '<a href="?C=N;O=D">Name</a>\n'
                '<a href="Advance%20Wars%20%28Europe%29%20%28En%2CFr%2CDe%2CEs%29.png">Advance Wars (Europe)...</a>\n'
                '<a href="/Nintendo%20-%20Game%20Boy%20Advance/Named_Boxarts/Golden%20Sun%20%28France%29.png">x</a>\n'
                '<a href="Tom%20%26amp%3B%20Jerry.jpg">y</a></body></html>')
        self.assertEqual(self.covers.parse_index(page),
                         ["Advance Wars (Europe) (En,Fr,De,Es).png", "Golden Sun (France).png", "Tom &amp; Jerry.jpg"])

    def test_run_downloads_where_esde_looks(self):
        import urllib.parse
        from unittest import mock
        covers = self.covers
        roms = os.path.join(TMP_HOME, "ROMs")
        for rel in ("gba/Golden Sun.gba", "gba/Inconnu du tout.gba", "psx/Final Fantasy VII (France)/FF7 - Disc 1.cue",
                    "psx/Final Fantasy VII (France)/FF7 - Disc 1 (Track 2).bin", "psx/Crash.chd"):
            os.makedirs(os.path.dirname(os.path.join(roms, rel)), exist_ok=True)
            open(os.path.join(roms, rel), "w").close()
        # Une jaquette existe déjà (scrapée par ES-DE) : on n'y touche pas.
        done = os.path.join(library.MEDIA_DIR, "psx", "covers", "Crash.png")
        os.makedirs(os.path.dirname(done), exist_ok=True)
        with open(done, "wb") as f:
            f.write(b"scrapee")
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 3000
        listings = {("gba", "Named_Boxarts"): ["Golden Sun (France).png", "Golden Sun (USA).png"],
                    ("gba", "Named_Snaps"): ["Golden Sun (USA).png"],
                    ("psx", "Named_Boxarts"): ["Final Fantasy VII (France) (Disc 1).png", "Crash Bandicoot (Europe).png"],
                    ("psx", "Named_Snaps"): ["Crash Bandicoot (Europe).png"]}
        calls = []

        def fake_get(url, timeout=25):
            calls.append(url)
            path = urllib.parse.unquote(url.split("://", 1)[1].split("/", 1)[1])
            for (system, folder), names in listings.items():
                base = f"{covers.SYSTEM_NAMES[system]}/{folder}/"
                if path == base:
                    return "".join(f'<a href="{urllib.parse.quote(n)}">{n}</a>' for n in names).encode()
                if path.startswith(base) and path[len(base):] in names:
                    return png
            raise OSError("404")
        with mock.patch.object(covers, "_get", fake_get), mock.patch.object(covers.time, "sleep", lambda s: None):
            stats = covers.run()
        self.assertEqual(stats["added"], 2)
        self.assertEqual(stats["missing"], 1)                                   # « Inconnu du tout »
        self.assertFalse(stats["offline"])
        self.assertTrue(os.path.exists(os.path.join(library.MEDIA_DIR, "gba", "covers", "Golden Sun.png")))
        self.assertTrue(os.path.exists(os.path.join(library.MEDIA_DIR, "gba", "screenshots", "Golden Sun.png")))
        ff7 = os.path.join(library.MEDIA_DIR, "psx", "covers", "Final Fantasy VII (France)", "FF7 - Disc 1.png")
        self.assertTrue(os.path.exists(ff7))
        self.assertFalse(os.path.exists(os.path.join(library.MEDIA_DIR, "psx", "covers", "Final Fantasy VII (France)",
                                                     "FF7 - Disc 1 (Track 2).png")))
        with open(done, "rb") as f:
            self.assertEqual(f.read(), b"scrapee")
        self.assertEqual(library.media("psx", os.path.join(roms, "psx", "Final Fantasy VII (France)", "FF7 - Disc 1.cue")), ff7)
        # Deuxième passage : rien à retélécharger, et l'introuvable n'est pas recherché de nouveau.
        calls.clear()
        with mock.patch.object(covers, "_get", fake_get):
            again = covers.run()
        self.assertEqual((again["added"], again["missing"]), (0, 1))
        self.assertEqual(calls, [])


class ResumeTests(unittest.TestCase):
    """Reprise des parties : état ajouté au lancement, état retenu à la fermeture, lanceur console-emu."""

    def setUp(self):
        from consoleshell import resume
        self.resume = resume
        self.rom = os.path.join(TMP_HOME, "Reprise", "ps2", "Okami (Europe).chd")
        os.makedirs(os.path.dirname(self.rom), exist_ok=True)
        open(self.rom, "w").close()
        for path in (resume.RESUME_PATH, os.path.join(TMP_HOME, ".config", "console", "settings.json")):
            if os.path.exists(path):
                os.unlink(path)
        self._build("pcsx2", "aaa111")

    def _build(self, emu, commit):
        """Faux déploiement Flatpak (le « commit » sert de numéro de version)."""
        cur = os.path.join(TMP_HOME, ".local/share/flatpak/app", self.resume.FLATPAKS[emu], "current")
        os.makedirs(cur, exist_ok=True)
        link = os.path.join(cur, "active")
        if os.path.lexists(link):
            os.unlink(link)
        os.symlink(commit, link)

    def _state(self, emu, name):
        folder = os.path.dirname(self.resume.STATE_GLOBS[emu][0])
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "wb") as f:
            f.write(b"etat" * 100)
        return path

    def test_command_adds_state_only_when_known_and_same_version(self):
        r = self.resume
        args = ["-batch", "-fullscreen", "--", self.rom]
        cmd, rom, state, hotkey = r.command("pcsx2", args, on=True)
        self.assertEqual(cmd, ["flatpak", "run", "net.pcsx2.PCSX2"] + args)
        self.assertEqual(rom, self.rom)
        st = self._state("pcsx2", "SLES-54439 (12345678).resume.p2s")
        r.record(self.rom, "pcsx2", st)
        cmd, _, state, _ = r.command("pcsx2", args, on=True)
        self.assertEqual(cmd, ["flatpak", "run", "net.pcsx2.PCSX2", "-statefile", st] + args)
        self.assertEqual(r.command("pcsx2", args, on=False)[0], ["flatpak", "run", "net.pcsx2.PCSX2"] + args)
        self._build("pcsx2", "bbb222")                                # PCSX2 mis à jour : état ignoré
        self.assertIsNone(r.command("pcsx2", args, on=True)[2])

    def test_dolphin_and_azahar(self):
        r = self.resume
        gc = os.path.join(TMP_HOME, "Reprise", "gc", "Wind Waker.rvz")
        os.makedirs(os.path.dirname(gc), exist_ok=True)
        open(gc, "w").close()
        self._build("dolphin", "d1")
        st = self._state("dolphin", "GZLP01.s08")
        r.record(gc, "dolphin", st)
        cmd = r.command("dolphin", ["-b", "-e", gc], on=True)[0]
        self.assertEqual(cmd, ["flatpak", "run", "org.DolphinEmu.dolphin-emu", "-C", "SYSCONF.IPL.AR=True",
                               "-C", "Graphics.Settings.AspectRatio=0", "-C", "Dolphin.Display.Fullscreen=False",
                               "-s", st, "-b", "-e", gc])
        self._build("dolphin", "d2")                     # mis à jour : Dolphin ignorera l'état s'il est trop vieux
        cmd = r.command("dolphin", ["-b", "-e", gc], on=True)[0]
        self.assertEqual(cmd[cmd.index("-s") + 1], st)
        ds = os.path.join(TMP_HOME, "Reprise", "n3ds", "Zelda.3ds")
        os.makedirs(os.path.dirname(ds), exist_ok=True)
        open(ds, "w").close()
        self._build("azahar", "z1")
        r.record(ds, "azahar", self._state("azahar", "0004000000033500.01.cst"))
        cmd, _, _, hotkey = r.command("azahar", ["-f", ds], on=True)
        self.assertEqual(cmd, ["flatpak", "run", "org.azahar_emu.Azahar", "-f", ds])  # pas d'option : raccourci
        self.assertTrue(hotkey)

    def test_n64_resume_is_deferred(self):
        """Mupen64Plus-Next rate le chargement auto au démarrage : la console le fait plus tard (touche)."""
        r = self.resume
        rom = os.path.join(TMP_HOME, "Reprise", "n64", "Super Mario 64 (Europe) (En,Fr,De).z64")
        os.makedirs(os.path.dirname(rom), exist_ok=True)
        open(rom, "w").close()
        core = "/home/x/.var/app/org.libretro.RetroArch/config/retroarch/cores/mupen64plus_next_libretro.so"
        cmd, _, _, hotkey = r.command("retroarch", ["-L", core, rom], on=True)
        self.assertFalse(hotkey)                                            # rien à reprendre encore
        self.assertIn("--verbose", cmd)
        override = os.path.join(r.RA_DIR, "config", "Mupen64Plus-Next", "Mupen64Plus-Next.cfg")
        with open(override, encoding="utf-8") as f:
            self.assertEqual(f.read(), 'savestate_auto_load = "false"\nstate_slot = "-1"\n')
        options = os.path.join(r.RA_DIR, "config", "Mupen64Plus-Next", "Mupen64Plus-Next.opt")
        with open(options, encoding="utf-8") as f:
            self.assertEqual(f.read(), 'mupen64plus-rdp-plugin = "parallel"\nmupen64plus-rsp-plugin = "parallel"\n')
        # Pilote imposé par une version précédente : retiré (RetroArch prend celui que le moteur demande).
        # Options propres à un jeu (créées depuis le menu de RetroArch, qui les préfère) : choix appliqué aussi.
        with open(override, "a", encoding="utf-8") as f:
            f.write('video_driver = "vulkan"\n')
        game_opt = os.path.join(os.path.dirname(options), "Super Mario 64 (Europe) (En,Fr,De).opt")
        with open(game_opt, "w", encoding="utf-8") as f:
            f.write('mupen64plus-43screensize = "640x480"\nmupen64plus-rdp-plugin = "gliden64"\n')
        r.deferred_core_setup("mupen64plus_next", {"n64_video": "angrylion"})      # réglage changé
        with open(options, encoding="utf-8") as f:
            self.assertEqual(f.read(), 'mupen64plus-rdp-plugin = "angrylion"\nmupen64plus-rsp-plugin = "parallel"\n')
        with open(game_opt, encoding="utf-8") as f:
            self.assertEqual(f.read(), 'mupen64plus-43screensize = "640x480"\nmupen64plus-rdp-plugin = "angrylion"\n'
                                       'mupen64plus-rsp-plugin = "parallel"\n')
        with open(override, encoding="utf-8") as f:
            self.assertEqual(f.read(), 'savestate_auto_load = "false"\nstate_slot = "-1"\n')
        r.deferred_core_setup("mupen64plus_next", {"n64_video": "gliden64"})
        with open(options, encoding="utf-8") as f:
            self.assertEqual(f.read(), 'mupen64plus-rdp-plugin = "gliden64"\nmupen64plus-rsp-plugin = "hle"\n')
        os.unlink(game_opt)
        auto = os.path.join(r.RA_DIR, "states", "Mupen64Plus-Next", os.path.basename(rom)[:-4] + ".state.auto")
        os.makedirs(os.path.dirname(auto), exist_ok=True)
        open(auto, "w").close()
        self.assertTrue(r.command("retroarch", ["-L", core, rom], on=True)[3])
        self.assertFalse(r.command("retroarch", ["-L", core, rom], on=False)[3])
        mgba = core.replace("mupen64plus_next", "mgba")
        self.assertFalse(r.command("retroarch", ["-L", mgba, rom], on=True)[3])  # les autres cœurs : RetroArch seul
        self.assertEqual(r.LOAD_KEYS["retroarch"], ["KEY_F4"])

    def test_esde_launch_is_relayed_to_console(self):
        """Lancé par ES-DE, console-emu confie le jeu à la console et attend la fin de son lanceur ;
        console injoignable : il le lance lui-même."""
        runtime, bindir = tempfile.mkdtemp(), tempfile.mkdtemp()
        runs = os.path.join(bindir, "runs.txt")
        with open(os.path.join(bindir, "flatpak"), "w") as f:
            f.write(f'#!/bin/sh\necho "$@" >> "{runs}"\nexit 0\n')
        os.chmod(os.path.join(bindir, "flatpak"), 0o755)
        rom = os.path.join(TMP_HOME, "Reprise", "gb", "Tetris.gb")
        os.makedirs(os.path.dirname(rom), exist_ok=True)
        open(rom, "w").close()
        game = subprocess.Popen(["sleep", "1.5"])                         # le lanceur côté console
        got = []

        def serve():
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(os.path.join(runtime, "console-shell.sock"))
            srv.listen(1)
            conn, _ = srv.accept()
            with conn:
                got.append(json.loads(conn.recv(65536).decode()))
                conn.sendall((json.dumps({"ok": True, "pid": game.pid}) + "\n").encode())
            srv.close()
        th = threading.Thread(target=serve, daemon=True)
        th.start()
        time.sleep(0.2)
        env = dict(os.environ, HOME=TMP_HOME, XDG_RUNTIME_DIR=runtime, CONSOLE_FROM_ESDE="1",
                   PATH=bindir + os.pathsep + os.environ["PATH"])
        cmd = [sys.executable, os.path.join(ROOT, "shell", "bin", "console-emu"), "retroarch", "-L", "/x/gambatte_libretro.so", rom]
        t0 = time.monotonic()
        p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
        game.wait()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertGreaterEqual(time.monotonic() - t0, 1.0)                 # a attendu la fin du jeu
        self.assertEqual(got[0]["cmd"], "esde-game")
        self.assertEqual(json.loads(got[0]["args"][0]), {"emu": "retroarch", "args": ["-L", "/x/gambatte_libretro.so", rom]})
        self.assertFalse(os.path.exists(runs))                              # pas lancé deux fois
        p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)   # plus de console
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(runs) as f:
            self.assertIn(rom, f.read())
        self.assertIn("lancement direct", p.stderr)
        env["CONSOLE_EMU_DIRECT"] = "1"                                     # lanceur côté console
        os.unlink(runs)
        subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
        with open(runs) as f:
            self.assertIn(rom, f.read())

    def test_retroarch_config_dir(self):
        """Dossier des réglages par cœur : celui que RetroArch lit (rgui_config_directory)."""
        r = self.resume
        d = tempfile.mkdtemp()
        cfg = os.path.join(d, "retroarch.cfg")
        self.assertEqual(r.ra_config_dir(cfg), os.path.join(d, "config"))          # pas de fichier
        cases = {'rgui_config_directory = "~/.var/app/org.libretro.RetroArch/config/retroarch/config"\n':
                 os.path.join(r.HOME, ".var/app/org.libretro.RetroArch/config/retroarch/config"),
                 'rgui_config_directory = "default"\n': d,
                 'rgui_config_directory = "/srv/ra/config"\n': "/srv/ra/config",
                 'video_driver = "gl"\n': os.path.join(d, "config")}
        for text, want in cases.items():
            with open(cfg, "w", encoding="utf-8") as f:
                f.write(text)
            self.assertEqual(r.ra_config_dir(cfg), want, text)

    def test_restart_from_scratch(self):
        """Menu du bouton Xbox › Recommencer depuis le début : le lanceur relance le jeu sans la partie
        mise de côté (faux « flatpak » qui joue RetroArch : état auto écrit en quittant)."""
        r = self.resume
        runtime = tempfile.mkdtemp()
        rom = os.path.join(TMP_HOME, "Reprise", "n64", "Rayman 2 (Europe).z64")
        os.makedirs(os.path.dirname(rom), exist_ok=True)
        open(rom, "w").close()
        states = os.path.join(r.RA_DIR, "states", "Mupen64Plus-Next")
        os.makedirs(states, exist_ok=True)
        auto = os.path.join(states, "Rayman 2 (Europe).state.auto")
        bindir = tempfile.mkdtemp()
        log_path = os.path.join(bindir, "runs.txt")
        with open(os.path.join(bindir, "flatpak"), "w") as f:
            f.write("#!/bin/sh\n"
                    f'n=$(cat "{log_path}" 2>/dev/null | wc -l); echo run >> "{log_path}"\n'
                    f'cp "{runtime}/console-emu-current.json" "{bindir}/current-$n.json"\n'
                    f'[ "$n" = 0 ] && printf %s "$PPID" > "{runtime}/console-emu-fresh"\n'   # le shell demande
                    f'echo etat > "{auto}"\n'                                                 # sauvegarde auto
                    "exit 0\n")
        os.chmod(os.path.join(bindir, "flatpak"), 0o755)
        env = dict(os.environ, HOME=TMP_HOME, XDG_RUNTIME_DIR=runtime, PATH=bindir + os.pathsep + os.environ["PATH"])
        core = "/x/cores/mupen64plus_next_libretro.so"
        p = subprocess.run([sys.executable, os.path.join(ROOT, "shell", "bin", "console-emu"), "retroarch", "-L", core, rom],
                           env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(log_path) as f:
            self.assertEqual(len(f.read().splitlines()), 2)                     # relancé une fois
        self.assertTrue(os.path.exists(auto + ".old"))                          # ancien état mis de côté
        with open(os.path.join(bindir, "current-0.json")) as f:
            self.assertEqual(json.load(f)["rom"], rom)                          # jeu en cours connu du shell
        self.assertFalse(os.path.exists(os.path.join(runtime, "console-emu-current.json")))
        self.assertFalse(os.path.exists(os.path.join(runtime, "console-emu-fresh")))

    def test_aspect_setting(self):
        """Réglages › Jeux › Format d'image : Wii toujours en 16:9, « Remplir l'écran » étire (Dolphin, PCSX2)."""
        r = self.resume
        self.assertIn("Graphics.Settings.AspectRatio=3", r.display_args("dolphin", {"emu_aspect": "fill"}))
        self.assertIn("SYSCONF.IPL.AR=True", r.display_args("dolphin", {}))
        os.makedirs(os.path.dirname(r.PCSX2_INI), exist_ok=True)
        with open(r.PCSX2_INI, "w", encoding="utf-8") as f:
            f.write("[UI]\nStartFullscreen = true\n\n[EmuCore/GS]\nRenderer = 14\nAspectRatio = Auto 4:3/3:2\n\n[Pad1]\nType = DualShock2\n")
        r.display_args("pcsx2", {"emu_aspect": "fill"})
        with open(r.PCSX2_INI, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("[EmuCore/GS]\nRenderer = 14\nAspectRatio = Stretch\n", text)
        self.assertIn("[Pad1]\nType = DualShock2", text)
        self.assertFalse(r.ini_value(r.PCSX2_INI, "EmuCore/GS", "AspectRatio", "Stretch"))   # déjà bon : pas réécrit
        r.ini_value(r.PCSX2_INI, "EmuCore", "SaveStateOnShutdown", "true")                  # section absente : ajoutée
        with open(r.PCSX2_INI, encoding="utf-8") as f:
            self.assertTrue(f.read().endswith("[EmuCore]\nSaveStateOnShutdown = true\n"))

    def test_after_exit_records_newest_state_and_forgets_refused_one(self):
        r = self.resume
        started = time.time()
        self.assertIsNone(r.after_exit("pcsx2", self.rom, started, None, 300))     # rien d'écrit
        st = self._state("pcsx2", "SLES-54439 (12345678).resume.p2s")
        self.assertEqual(r.after_exit("pcsx2", self.rom, started, None, 300), st)
        self.assertEqual(r.state_for(self.rom, "pcsx2"), st)
        # PCSX2 a refusé l'état (quitte aussitôt sans rien écrire) : la prochaine fois, partie neuve
        r.after_exit("pcsx2", self.rom, time.time() + 5, st, 3)
        self.assertIsNone(r.state_for(self.rom, "pcsx2"))
        # Partie quittée sans nouvel état (plantage…) : l'ancien, plus vieux que la partie, est oublié
        r.record(self.rom, "pcsx2", st)
        r.after_exit("pcsx2", self.rom, time.time() + 5, None, 600)
        self.assertIsNone(r.state_for(self.rom, "pcsx2"))

    def test_retroarch_config_and_forget(self):
        r = self.resume
        os.makedirs(os.path.dirname(r.RA_CFG), exist_ok=True)
        with open(r.RA_CFG, "w", encoding="utf-8") as f:
            f.write('video_fullscreen = "true"\nsavestate_auto_save = "false"\n')
        self.assertTrue(r.retroarch_config(True))
        self.assertFalse(r.retroarch_config(True))                              # déjà bon : pas réécrit
        with open(r.RA_CFG, encoding="utf-8") as f:
            text = f.read()
        self.assertIn('savestate_auto_save = "true"', text)
        self.assertIn('savestate_auto_load = "true"', text)
        self.assertIn('video_fullscreen = "true"', text)
        gba = os.path.join(TMP_HOME, "Reprise", "gba", "Golden Sun [!].gba")
        auto = os.path.join(r.RA_DIR, "states", "mGBA", "Golden Sun [!].state.auto")
        os.makedirs(os.path.dirname(auto), exist_ok=True)
        open(auto, "w").close()
        self.assertTrue(r.has_resume(gba))
        r.forget(gba)
        self.assertFalse(os.path.exists(auto))
        self.assertTrue(os.path.exists(auto + ".old"))
        self.assertFalse(r.has_resume(gba))

    def test_console_emu_wrapper(self):
        """Lanceur réel, avec un faux « flatpak » qui joue l'émulateur : il note ses arguments et écrit
        un état de reprise, comme PCSX2 en quittant."""
        bindir = tempfile.mkdtemp()
        log_path = os.path.join(bindir, "args.txt")
        state_dir = os.path.dirname(self.resume.STATE_GLOBS["pcsx2"][0])
        with open(os.path.join(bindir, "flatpak"), "w") as f:
            f.write("#!/bin/sh\n"
                    f'printf "%s\\n" "$*" >> "{log_path}"\n'
                    f'mkdir -p "{state_dir}" && printf "%0500d" 0 > "{state_dir}/SLES-1 (0000ABCD).resume.p2s"\n'
                    "exit 3\n")
        os.chmod(os.path.join(bindir, "flatpak"), 0o755)
        env = dict(os.environ, HOME=TMP_HOME, PATH=bindir + os.pathsep + os.environ["PATH"])
        emu = os.path.join(ROOT, "shell", "bin", "console-emu")
        for _ in range(2):
            p = subprocess.run([sys.executable, emu, "pcsx2", "-batch", "--", self.rom], env=env,
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, 3, p.stderr)                  # code de sortie de l'émulateur
        with open(log_path) as f:
            calls = f.read().splitlines()
        state = os.path.join(state_dir, "SLES-1 (0000ABCD).resume.p2s")
        self.assertEqual(calls[0], f"run net.pcsx2.PCSX2 -batch -- {self.rom}")
        self.assertEqual(calls[1], f"run net.pcsx2.PCSX2 -statefile {state} -batch -- {self.rom}")
        with open(os.path.join(TMP_HOME, ".local", "state", "console", "logs", "emu-pcsx2.log"), encoding="utf-8") as f:
            log = f.read()
        self.assertIn("net.pcsx2.PCSX2 -statefile", log)                  # journal de l'émulateur gardé
        self.assertIn("# fin (code 3)", log)


def _iso9660(boot_line, sector=2048, offset=0, system_id=b"PLAYSTATION"):
    """Image ISO 9660 minimale : descripteur (secteur 16), racine (20), SYSTEM.CNF (21)."""
    def user(data):
        data = data.ljust(2048, b"\x00")
        if sector == 2048:
            return data
        return (b"\x00" * offset + data).ljust(sector, b"\x00")
    pvd = bytearray(2048)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[8:8 + len(system_id)] = system_id
    root = bytearray(34)
    root[0] = 34
    root[2:6] = (20).to_bytes(4, "little")
    root[10:14] = (2048).to_bytes(4, "little")
    pvd[156:190] = root
    cnf = boot_line.encode() + b"\r\nVER = 1.00\r\n"
    name = b"SYSTEM.CNF;1"
    rec = bytearray(33 + len(name) + (1 - len(name) % 2))
    rec[0] = len(rec)
    rec[2:6] = (21).to_bytes(4, "little")
    rec[10:14] = len(cnf).to_bytes(4, "little")
    rec[32] = len(name)
    rec[33:33 + len(name)] = name
    sectors = [user(b"")] * 16 + [user(bytes(pvd))] + [user(b"")] * 3 + [user(bytes(rec))] + [user(cnf)]
    return b"".join(sectors)


class ImporterTests(unittest.TestCase):
    """Ajout de jeux et de BIOS : reconnaissance par le contenu, regroupements, rangement."""

    def setUp(self):
        from consoleshell import importer
        self.imp = importer
        self.root = tempfile.mkdtemp(prefix="import-")
        lib = tempfile.mkdtemp(prefix="bibliotheque-")
        self.roms, self.bios = os.path.join(lib, "ROMs"), os.path.join(lib, "BIOS")
        patches = {"ROMS_DIR": self.roms, "BIOS_DIR": self.bios, "TO_SORT": os.path.join(self.roms, "_À trier"),
                   "WORK_DIR": os.path.join(lib, "work")}
        for k, v in patches.items():
            old = getattr(importer, k)
            setattr(importer, k, v)
            self.addCleanup(setattr, importer, k, old)

    def put(self, rel, data=b"x" * 2000):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_disc_systems_by_content(self):
        imp = self.imp
        gc = bytearray(0x40); gc[0x1c:0x20] = b"\xc2\x33\x9f\x3d"
        wii = bytearray(0x40); wii[0x18:0x1c] = b"\x5d\x1c\x9e\xa3"
        rvz = bytearray(0x60); rvz[:4] = b"RVZ\x01"; rvz[0x48:0x4c] = (2).to_bytes(4, "big")
        gcz = b"\x01\xc0\x0b\xb1" + (0).to_bytes(4, "little") + b"\x00" * 40
        cases = {
            "a/Metroid Prime.iso": (bytes(gc), "gc"), "a/Mario Galaxy.iso": (bytes(wii), "wii"),
            "a/Zelda.rvz": (bytes(rvz), "wii"), "a/Pikmin.gcz": (gcz, "gc"), "a/Wii Sports.wbfs": (b"WBFS" + b"\0" * 60, "wii"),
            "a/Okami.iso": (_iso9660("BOOT2 = cdrom0:\\SLES_544.39;1"), "ps2"),
            "a/Spyro.bin": (_iso9660("BOOT = cdrom:\\SCES_009.00;1", 2352, 24), "psx"),
            "a/Golden Sun.gba": (b"\0" * 200, "gba"), "a/Bizarre.iso": (b"\x42" * 70000, None),
        }
        for rel, (data, system) in cases.items():
            self.assertEqual(imp.disc_system(self.put(rel, data)), system, rel)
        head = bytearray(124); head[:8] = b"MComprHD"; head[12:16] = (5).to_bytes(4, "big")
        head[48:56] = (124).to_bytes(8, "big")
        dvd = bytes(head) + b"DVD \x01\x00\x00\x10" + b"\0" * 8
        cd = bytes(head) + b"CHT2\x01\x00\x00\x10" + b"\0" * 8
        self.assertEqual(imp.disc_system(self.put("a/God of War.chd", dvd)), "ps2")
        self.assertEqual(imp.disc_system(self.put("a/Crash.chd", cd)), "psx")

    def test_retro_consoles(self):
        imp = self.imp
        md = bytearray(0x200); md[0x100:0x110] = b"SEGA MEGA DRIVE "
        cases = {"Chrono Trigger (USA).sfc": (b"\0" * 9000, "snes"), "Super Mario 64 (Europe).z64": (b"\x80\x37\x12\x40" + b"\0" * 9000, "n64"),
                 "Rayman 2 (Europe).bin": (b"\x80\x37\x12\x40" + b"\0" * 9000, "n64"), "Sonic (Europe).bin": (bytes(md), "megadrive"),
                 "Zelda (France).nes": (b"NES\x1a" + b"\0" * 9000, "nes"), "Pokemon Jaune (France).gb": (b"\0" * 9000, "gb"),
                 "Wario Land 3.gbc": (b"\0" * 9000, "gbc"), "Alex Kidd.sms": (b"\0" * 9000, "mastersystem")}
        for name, (data, system) in cases.items():
            self.assertEqual(imp.disc_system(self.put("r/" + name, data)), system, name)
        self.put("r/Inconnu.a26", b"\0" * 9000)                            # console pas prise en charge
        self.put("r/Musique.flac", b"\0" * 9000)
        items = {it.label: it for it in imp.plan(os.path.join(self.root, "r"))}
        self.assertEqual(items["Inconnu.a26"].kind, "to_sort")              # gardé de côté, et signalé
        self.assertIn(".a26", items["Inconnu.a26"].note)
        self.assertEqual(items["Musique.flac"].kind, "ignored")

    def test_bios_recognized_whatever_their_name(self):
        imp = self.imp
        ps1 = self.put("BIOS/Ma bios PS1 europe.BIN", bytes(range(256)) * 2048)          # 512 Kio
        data = bytearray(4 << 20)
        entries = [(b"RESET", 0x100), (b"ROMDIR", 0x80), (b"EXTINFO", 0x40), (b"ROMVER", 0x10)]
        for i, (name, size) in enumerate(entries):
            e = 0x100 + 16 * i
            data[e:e + 10] = name.ljust(10, b"\0")
            data[e + 12:e + 16] = size.to_bytes(4, "little")
        data[0x1c0:0x1c0 + 14] = b"0230EC20080220"
        ps2 = self.put("BIOS/SCPH-90004.bin", bytes(data))
        from unittest import mock
        with mock.patch.dict(imp.BIOS_MD5, {imp.md5(ps1): ("psx", "scph5502.bin", "PS1 Europe")}):
            items = {it.label: it for it in imp.plan(self.root)}
            self.assertEqual(items["PS1 Europe"].dest, os.path.join(self.bios, "scph5502.bin"))
            self.assertEqual(items["PS2 Europe v2.30"].dest, os.path.join(self.bios, "SCPH-90004.bin"))
            imp.execute(list(items.values()))
            os.makedirs(os.path.join(self.roms, "psx"))
            for n in ("Spyro (Europe).chd", "Crash (USA).chd"):
                open(os.path.join(self.roms, "psx", n), "w").close()
            st = imp.bios_status()
        self.assertEqual(st["psx"]["have"], {"eu": "scph5502.bin"})
        self.assertEqual(st["psx"]["missing"], ["us"])                      # un jeu américain sans son BIOS
        self.assertEqual(st["ps2"]["have"][0]["zone"], "Europe")
        self.assertEqual(st["ps2"]["have"][0]["date"], "20/02/2008")
        self.assertTrue(os.path.exists(ps1))                                # copie : la source reste

    def test_cue_bin_and_multi_disc_become_single_entries(self):
        imp = self.imp
        track = _iso9660("BOOT = cdrom:\\SCES_123.45;1", 2352, 24)
        self.put("Vrac/Tomba (Europe)/Tomba (Europe) (Track 1).bin", track)
        self.put("Vrac/Tomba (Europe)/Tomba (Europe) (Track 2).bin", b"\0" * 5000)
        self.put("Vrac/Tomba (Europe)/Tomba (Europe).cue",
                 b'FILE "Tomba (Europe) (Track 1).bin" BINARY\n  TRACK 01 MODE2/2352\n'
                 b'FILE "Tomba (Europe) (Track 2).bin" BINARY\n  TRACK 02 AUDIO\n')
        head = bytearray(124); head[:8] = b"MComprHD"; head[12:16] = (5).to_bytes(4, "big")
        head[48:56] = (124).to_bytes(8, "big")
        cd = bytes(head) + b"CHT2\x01\x00\x00\x10" + b"\0" * 8
        self.put("Vrac/Final Fantasy VII (France) (Disc 1).chd", cd)
        self.put("Vrac/Final Fantasy VII (France) (Disc 2).chd", cd + b"2")
        self.put("Vrac/Lisez-moi.txt", b"bonjour")
        self.put("Vrac/Inconnu.iso", b"\x42" * 70000)
        self.put("Vrac/Jeu.rar", b"Rar!")
        results = imp.import_tree(self.root)
        tomba = os.path.join(self.roms, "psx", "Tomba (Europe).cue")
        self.assertTrue(os.path.isfile(os.path.join(tomba, "Tomba (Europe).cue")))
        self.assertTrue(os.path.isfile(os.path.join(tomba, "Tomba (Europe) (Track 2).bin")))
        ff7 = os.path.join(self.roms, "psx", "Final Fantasy VII (France).m3u")
        with open(os.path.join(ff7, "Final Fantasy VII (France).m3u")) as f:
            self.assertEqual(f.read().splitlines(), ["Final Fantasy VII (France) (Disc 1).chd",
                                                     "Final Fantasy VII (France) (Disc 2).chd"])
        self.assertTrue(os.path.isfile(os.path.join(self.roms, "_À trier", "Inconnu.iso")))
        status = {r["label"]: r["status"] for r in results}
        self.assertEqual(status["Lisez-moi.txt"], "new")                    # ignoré, pas copié
        self.assertFalse(os.path.exists(os.path.join(self.roms, "_À trier", "Lisez-moi.txt")))
        kinds = {r["label"]: r["kind"] for r in results}
        self.assertEqual(kinds["Jeu.rar"], "unsupported")
        # Deuxième fois : tout est déjà là, rien n'est copié en double
        again = imp.plan(self.root)
        self.assertTrue(all(it.status == "present" for it in again if it.kind == "game"))
        self.assertEqual(imp.summary(again)["games"], {})

    def test_archives_and_uploaded_files_are_moved(self):
        import zipfile
        imp = self.imp
        z = os.path.join(self.root, "envoi", "Pack GBA.zip")
        os.makedirs(os.path.dirname(z))
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("Golden Sun (France).gba", b"\0" * 4000)
            zf.writestr("../../evasion.gba", b"\0" * 4000)
            zf.writestr("infos.nfo", b"x")
        results = imp.import_tree(os.path.join(self.root, "envoi"), move=True)
        self.assertTrue(os.path.isfile(os.path.join(self.roms, "gba", "Golden Sun (France).gba")))
        self.assertTrue(os.path.isfile(os.path.join(self.roms, "gba", "evasion.gba")))   # pas en dehors
        self.assertFalse(os.path.exists(z))                                 # envoi : l'archive est rangée
        self.assertIn("added", {r["status"] for r in results if r["kind"] == "archive"})


class UploaderTests(unittest.TestCase):
    """Envoi depuis un téléphone ou un PC : code, jeton, envoi, rangement, refus."""

    def setUp(self):
        from consoleshell import importer, uploader
        self.importer, self.uploader = importer, uploader
        lib = tempfile.mkdtemp(prefix="envoi-")
        for k, v in {"ROMS_DIR": os.path.join(lib, "ROMs"), "BIOS_DIR": os.path.join(lib, "BIOS"),
                     "TO_SORT": os.path.join(lib, "ROMs", "_À trier"), "WORK_DIR": os.path.join(lib, "work")}.items():
            old = getattr(importer, k)
            setattr(importer, k, v)
            self.addCleanup(setattr, importer, k, old)
        self.roms = importer.ROMS_DIR
        old_page = uploader.PAGE
        uploader.PAGE = os.path.join(ROOT, "shell", "ui", "upload.html")
        self.addCleanup(setattr, uploader, "PAGE", old_page)
        self.events = []
        self.up = uploader.Uploader(self.events.append, name=lambda: "Nova")
        self.port = self.up.start(port=0)
        self.addCleanup(self.up.stop)

    def call(self, method, path, body=None, token=None):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"X-Token": token} if token else {}
        c.request(method, path, body=body, headers=headers)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, (json.loads(data) if data and r.getheader("Content-Type", "").startswith("application/json") else data)

    def test_code_then_upload_then_sorted(self):
        import urllib.parse
        st, _ = self.call("GET", "/api/auth?code=000000" if self.up.code != "000000" else "/api/auth?code=111111")
        self.assertEqual(st, 403)
        st, d = self.call("GET", f"/api/auth?code={self.up.code}")
        self.assertEqual((st, d["token"]), (200, self.up.token))
        tok = d["token"]
        self.assertEqual(self.call("GET", "/api/info", token=tok)[1]["name"], "Nova")
        q = urllib.parse.quote("Mes jeux/Golden Sun (France).gba")
        self.assertEqual(self.call("PUT", f"/api/upload?batch=essai123&path={q}", b"\0" * 5000)[0], 403)  # sans jeton
        self.assertEqual(self.call("PUT", f"/api/upload?batch=essai123&path={q}", b"\0" * 5000, tok)[0], 200)
        bad = urllib.parse.quote("../../../etc/evil.gba")
        self.assertEqual(self.call("PUT", f"/api/upload?batch=essai123&path={bad}", b"\0" * 10, tok)[0], 200)
        st, d = self.call("POST", "/api/done?batch=essai123", token=tok)
        self.assertEqual(st, 200)
        added = sorted(r["label"] for r in d["results"] if r["status"] == "added")
        self.assertEqual(added, ["Golden Sun (France)", "evil"])
        self.assertTrue(os.path.isfile(os.path.join(self.roms, "gba", "Golden Sun (France).gba")))
        self.assertTrue(os.path.isfile(os.path.join(self.roms, "gba", "evil.gba")))     # pas hors du dossier
        self.assertFalse(os.path.exists(self.up.staging("essai123")))                    # dépôt vidé
        types = [e["type"] for e in self.events]
        self.assertIn("progress", types)
        self.assertEqual(types[-1], "done")

    def test_page_served_and_closed_screen_refuses(self):
        st, page = self.call("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn(b"Glisse ici tes jeux", page)
        self.up.closing = True
        self.assertEqual(self.call("PUT", "/api/upload?batch=essai456&path=a.gba", b"\0" * 10, self.up.token)[0], 503)


if __name__ == "__main__":
    unittest.main(verbosity=2)
