"""Tests des fonctions « pures » du shell (sans GTK, sans sway).

Lancer :  python3 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
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
        self.assertEqual(cmd[:3], ["flatpak", "run", "org.DolphinEmu.dolphin-emu"])

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

    def test_layouts(self):
        lay = self.gp.raw_layout(self.FakeDevice("/x"), "xbox")
        self.assertEqual((lay["buttons"][0x133], lay["axes"][2][1], lay["axes"][3][0]), ("x", "trigger", 2))
        self.assertEqual(self.gp.raw_layout(self.FakeDevice("/x"), "playstation")["buttons"][0x133], "y")
        self.FakeDevice.abs_codes = {0: (0, 65535), 1: (0, 65535), 2: (0, 65535), 5: (0, 65535),
                                     9: (0, 1023), 10: (0, 1023)}
        ble = self.gp.raw_layout(self.FakeDevice("/x"), "xbox")["axes"]   # Xbox BLE, pilote générique
        self.assertEqual((ble[10][0], ble[9][0], ble[2][0], ble[5][0]), (4, 5, 2, 3))


if __name__ == "__main__":
    unittest.main(verbosity=2)
