"""Chemins et réglages persistants de la console."""
import os

from .util import read_json, write_json, log

PREFIX = os.environ.get("CONSOLE_PREFIX", "/opt/console")
UI_DIR = os.path.join(PREFIX, "ui")
BIN_DIR = os.path.join(PREFIX, "bin")
SHARE_DIR = os.path.join(PREFIX, "share")

HOME = os.path.expanduser("~")
XDG_CONFIG = os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config"))
XDG_DATA = os.environ.get("XDG_DATA_HOME", os.path.join(HOME, ".local", "share"))
XDG_STATE = os.environ.get("XDG_STATE_HOME", os.path.join(HOME, ".local", "state"))
XDG_CACHE = os.environ.get("XDG_CACHE_HOME", os.path.join(HOME, ".cache"))
RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")

CONFIG_DIR = os.path.join(XDG_CONFIG, "console")
DATA_DIR = os.path.join(XDG_DATA, "console")
STATE_DIR = os.path.join(XDG_STATE, "console")
LOG_DIR = os.path.join(STATE_DIR, "logs")
ICON_DIR = os.path.join(DATA_DIR, "icons")
BRAVE_PROFILE = os.path.join(DATA_DIR, "brave")
CAPTURES_DIR = os.path.join(HOME, "Captures")
ROMS_DIR = os.path.join(HOME, "ROMs")
BIOS_DIR = os.path.join(HOME, "BIOS")

SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")
LAYOUT_PATH = os.path.join(CONFIG_DIR, "home.json")
RECENTS_PATH = os.path.join(STATE_DIR, "recents.json")
CONTROLLERS_PATH = os.path.join(STATE_DIR, "controllers.json")
COVERS_STATE = os.path.join(STATE_DIR, "covers.json")
SECRETS_PATH = os.path.join(CONFIG_DIR, "secrets.json")
SYSTEM_DEFAULTS = "/etc/console/defaults.json"
CONTROL_SOCKET = os.path.join(RUNTIME_DIR, "console-shell.sock")

DEFAULTS = {
    "console_name": "Nova",
    "standby_mode": "deep",          # deep = vraie veille ; light = écran coupé
    "deep_sleep_verified": None,     # résultat du test de réveil manette
    "auto_standby_min": 15,          # 0 = jamais
    "controller_off_standby": True,  # manette éteinte → veille (si rien ne joue)
    "resolution": "1080p",           # 1080p | max
    "ui_sounds": True,
    "osk_layout": "azerty",          # azerty | qwerty
    "browser_scale": 1.5,
    "guide_hold_ms": 700,
    "first_run_done": False,
    "moonlight_host": "",                       # PC par défaut (uuid) ; vide = le premier associé
    "moonlight_tile_app": "Steam Big Picture",  # lancé par la tuile ; "gui" = interface Moonlight
    "moonlight_pin_mode": "wake",               # wake = après réveil du PC | always | off
    "sunshine_auto_repair": True,               # relance Sunshine s'il est à moitié planté
    "wake_relay": "",                           # utilisateur@hôte sur le réseau du PC (réveil par SSH)
    "pc_ssh": "",                               # utilisateur@PC : veille / redémarrage par OpenSSH (Windows)
    "theme": "aurora",                          # thème de l'accueil (voir THEMES dans home.js)
    "bg_motion": "full",                        # full | calm | off
    "ambient_min": 5,                           # mode ambiance après N min sans activité (0 = jamais)
    "covers_auto": True,                        # jaquettes manquantes téléchargées (base libretro)
    "resume_games": True,                       # parties mises de côté en quittant, reprises au lancement
    "usb_import": True,                         # proposer d'importer les jeux d'une clé USB branchée
    "emu_aspect": "auto",                       # auto (16:9 si le jeu le permet) | fill (étirer à l'écran)
}


class Settings:
    def __init__(self):
        self._data = dict(DEFAULTS)
        self._data.update(read_json(SYSTEM_DEFAULTS, {}) or {})
        self._data.update(read_json(SETTINGS_PATH, {}) or {})
        self._listeners = []

    def __getitem__(self, key):
        return self._data.get(key, DEFAULTS.get(key))

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        if self._data.get(key) == value:
            return
        self._data[key] = value
        self.save()
        for fn in list(self._listeners):
            try:
                fn(key, value)
            except Exception:  # noqa: BLE001
                log.exception("listener réglages")

    def on_change(self, fn):
        self._listeners.append(fn)

    def save(self):
        write_json(SETTINGS_PATH, self._data)

    def public(self):
        return dict(self._data)


def get_secret(key):
    """Secrets (code PIN Windows…) : fichier lisible par l'utilisateur seulement, jamais envoyé à l'interface."""
    return (read_json(SECRETS_PATH, {}) or {}).get(key)


def set_secret(key, value):
    from .util import atomic_write
    import json
    data = read_json(SECRETS_PATH, {}) or {}
    if value:
        data[key] = value
    else:
        data.pop(key, None)
    atomic_write(SECRETS_PATH, json.dumps(data, ensure_ascii=False) + "\n", mode=0o600)


def secret_keys():
    return list((read_json(SECRETS_PATH, {}) or {}).keys())


def ensure_dirs():
    for d in (CONFIG_DIR, DATA_DIR, STATE_DIR, LOG_DIR, ICON_DIR, CAPTURES_DIR):
        os.makedirs(d, exist_ok=True)
