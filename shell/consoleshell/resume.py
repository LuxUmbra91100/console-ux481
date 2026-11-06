"""Reprendre les jeux là où on s'est arrêté.

Chaque émulateur à sa façon :
- RetroArch (GBA, DS, PS1) le fait lui-même : état sauvegardé en quittant, rechargé au lancement
  (savestate_auto_save / savestate_auto_load, réglés avant chaque lancement selon le réglage).
- PCSX2 (PS2) enregistre un état de reprise en quittant (SaveStateOnShutdown) : on le lui redonne
  au lancement suivant (-statefile).
- Dolphin (GameCube, Wii) ne sauvegarde pas seul : la console lui fait enregistrer l'emplacement 8
  (Maj+F8) avant de le fermer, puis le lui redonne au lancement (-s).
- Azahar (3DS) non plus, et ne sait pas charger un état au lancement : la console lui fait
  enregistrer un état (Ctrl+C) avant de le fermer et le recharge (Ctrl+V) peu après le lancement.

Tous les lancements passent par console-emu (accueil, et ES-DE grâce à ses règles de recherche
d'émulateurs) : il ajoute l'état à charger et note, à la fermeture, quel fichier d'état correspond à
quel jeu. Les Flatpak se mettent à jour tout seuls : Dolphin et Azahar ignorent sans dommage un
état d'une version incompatible, mais PCSX2 refuserait alors de démarrer le jeu, donc pour lui un état
n'est rechargé qu'avec la version qui l'a écrit.
"""
import glob
import os
import re
import time

from .config import HOME, RUNTIME_DIR, SETTINGS_PATH, STATE_DIR
from .util import atomic_write, read_json, write_json

VAR = os.path.join(HOME, ".var", "app")
FLATPAKS = {"retroarch": "org.libretro.RetroArch", "dolphin": "org.DolphinEmu.dolphin-emu",
            "pcsx2": "net.pcsx2.PCSX2", "azahar": "org.azahar_emu.Azahar"}
# Émulateurs qui refusent de démarrer avec un état d'une autre version.
STRICT_BUILD = {"pcsx2"}
# Où chaque émulateur range l'état qui sert à la reprise.
STATE_GLOBS = {
    "dolphin": [os.path.join(VAR, FLATPAKS["dolphin"], "data/dolphin-emu/StateSaves/*.s08")],
    "pcsx2": [os.path.join(VAR, FLATPAKS["pcsx2"], "config/PCSX2/sstates/*.resume.p2s")],
    "azahar": [os.path.join(VAR, FLATPAKS["azahar"], "data/azahar-emu/states/*.cst")],
}
SAVE_KEYS = {"dolphin": ["KEY_LEFTSHIFT", "KEY_F8"], "azahar": ["KEY_LEFTCTRL", "KEY_C"]}
LOAD_KEYS = {"azahar": ["KEY_LEFTCTRL", "KEY_V"], "retroarch": ["KEY_F4"]}
# Cœurs RetroArch qui ratent le chargement automatique au démarrage (Mupen64Plus-Next : écran noir) :
# l'état « auto » leur est redonné par la touche « charger » une fois le jeu lancé. Nom du fichier du
# cœur → nom du cœur pour RetroArch (dossier de ses réglages propres et de ses états).
DEFERRED_CORES = {"mupen64plus_next": "Mupen64Plus-Next"}
RESUME_PATH = os.path.join(STATE_DIR, "resume.json")
CURRENT_PATH = os.path.join(RUNTIME_DIR, "console-emu-current.json")   # jeu lancé par console-emu
FRESH_PATH = os.path.join(RUNTIME_DIR, "console-emu-fresh")            # « recommencer » demandé
RA_DIR = os.path.join(VAR, FLATPAKS["retroarch"], "config/retroarch")
RA_CFG = os.path.join(RA_DIR, "retroarch.cfg")
FLATPAK_ROOTS = ("/var/lib/flatpak/app", os.path.join(HOME, ".local/share/flatpak/app"))
KEEP = 300


PCSX2_INI = os.path.join(VAR, FLATPAKS["pcsx2"], "config/PCSX2/inis/PCSX2.ini")


def _settings():
    return read_json(SETTINGS_PATH, {}) or {}


def enabled():
    return _settings().get("resume_games", True) is not False


def ini_value(path, section, key, value):
    """Écrit « clé = valeur » dans une section d'un .ini (PCSX2) ; True si le fichier a changé."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return False
    out, in_section, done, changed = [], False, False, False
    wanted = f"{key} = {value}"
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if in_section and not done:
                out.append(wanted)
                done = changed = True
            in_section = s[1:-1] == section
        elif in_section and not done and re.match(rf"\s*{re.escape(key)}\s*=", line):
            changed |= s != wanted
            out.append(wanted)
            done = True
            continue
        out.append(line)
    if not done:
        if not in_section:
            out += ["", f"[{section}]"]
        out.append(wanted)
        changed = True
    if changed:
        atomic_write(path, "\n".join(out) + "\n")
    return changed


def display_args(emu, settings=None):
    """Format d'image (Réglages › Jeux) : « auto » = 16:9 quand le jeu le permet (la Wii est mise en
    16:9), « fill » = image étirée sur tout l'écran."""
    fill = (settings or _settings()).get("emu_aspect") == "fill"
    if emu == "dolphin":
        # Plein écran laissé à sway (comme pour toutes les applis) : le plein écran propre à Dolphin
        # se calait mal sous XWayland (image décalée d'une demi-largeur).
        return ["-C", "SYSCONF.IPL.AR=True", "-C", f"Graphics.Settings.AspectRatio={3 if fill else 0}",
                "-C", "Dolphin.Display.Fullscreen=False"]
    if emu == "pcsx2":
        ini_value(PCSX2_INI, "EmuCore/GS", "AspectRatio", "Stretch" if fill else "Auto 4:3/3:2")
    return []


def build(emu):
    """Version installée de l'émulateur (commit Flatpak déployé), pour ne pas recharger un état
    d'une autre version."""
    for root in FLATPAK_ROOTS:
        try:
            return os.path.basename(os.readlink(os.path.join(root, FLATPAKS[emu], "current", "active")))
        except OSError:
            continue
    return None


def newest_state(emu, since=0.0):
    best = None
    for pattern in STATE_GLOBS.get(emu, ()):
        for path in glob.glob(pattern):
            try:
                mtime = os.stat(path).st_mtime
            except OSError:
                continue
            if mtime >= since and (best is None or mtime > best[0]):
                best = (mtime, path)
    return best[1] if best else None


def wait_for_state(emu, since, timeout=8.0, poll=0.25):
    """Attend qu'un état tout juste demandé soit entièrement écrit ; son chemin, ou None."""
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        path = newest_state(emu, since)
        if path:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            if size and last == (path, size):
                return path
            last = (path, size)
        time.sleep(poll)
    return None


def _load():
    return read_json(RESUME_PATH, {}) or {}


def record(rom, emu, state):
    data = _load()
    data[rom] = {"emu": emu, "state": state, "build": build(emu), "ts": time.time()}
    if len(data) > KEEP:
        for key, _ in sorted(data.items(), key=lambda kv: kv[1].get("ts", 0))[:len(data) - KEEP]:
            data.pop(key)
    write_json(RESUME_PATH, data)


def state_for(rom, emu):
    """État à recharger pour ce jeu : même émulateur, fichier toujours là (et même version pour PCSX2)."""
    item = _load().get(rom) or {}
    state = item.get("state")
    if item.get("emu") != emu or not state or not os.path.exists(state):
        return None
    if emu in STRICT_BUILD and item.get("build") != build(emu):
        return None
    return state


def has_resume(rom):
    """Une reprise est prévue pour ce jeu (n'importe quel émulateur, RetroArch compris)."""
    item = _load().get(rom) or {}
    return bool(item and state_for(rom, item.get("emu"))) or bool(_retroarch_auto_states(rom))


def _retroarch_auto_states(rom):
    stem = glob.escape(os.path.splitext(os.path.basename(rom))[0])
    return glob.glob(os.path.join(RA_DIR, "states", stem + ".state.auto")) + \
        glob.glob(os.path.join(RA_DIR, "states", "*", stem + ".state.auto"))


def _drop(rom):
    data = _load()
    if data.pop(rom, None) is not None:
        write_json(RESUME_PATH, data)


def forget(rom):
    """« Recommencer depuis le début » : plus de reprise pour ce jeu (l'état de RetroArch est gardé
    de côté en .old, au cas où)."""
    _drop(rom)
    for path in _retroarch_auto_states(rom):
        try:
            os.replace(path, path + ".old")
        except OSError:
            pass


def set_current(emu, rom, pid):
    write_json(CURRENT_PATH, {"emu": emu, "rom": rom, "pid": pid})


def clear_current(pid):
    cur = read_json(CURRENT_PATH, {}) or {}
    if cur.get("pid") == pid:
        try:
            os.unlink(CURRENT_PATH)
        except OSError:
            pass


def current_game():
    """Jeu en cours lancé par console-emu ({emu, rom, pid}), ou None."""
    cur = read_json(CURRENT_PATH, {}) or {}
    pid = cur.get("pid")
    if not pid or not cur.get("rom"):
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return cur


def request_fresh(pid):
    """Le lanceur de ce jeu le relancera depuis le début quand l'émulateur se fermera."""
    atomic_write(FRESH_PATH, str(pid))


def take_fresh(pid):
    """Une relance « depuis le début » a-t-elle été demandée pour ce lanceur ? (la demande est consommée)"""
    try:
        with open(FRESH_PATH, encoding="utf-8") as f:
            wanted = f.read().strip() == str(pid)
    except OSError:
        return False
    if wanted:
        try:
            os.unlink(FRESH_PATH)
        except OSError:
            pass
    return wanted


def find_rom(args):
    """Le jeu dans une ligne de commande d'émulateur : le dernier argument qui est un fichier."""
    for arg in reversed(args):
        if not arg.startswith("-") and os.path.isfile(arg):
            return os.path.normpath(os.path.abspath(arg))
    return None


def retroarch_config(on, path=RA_CFG):
    """Sauvegarde et rechargement automatiques de RetroArch selon le réglage."""
    value = "true" if on else "false"
    want = {"savestate_auto_save": value, "savestate_auto_load": value}
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return False
    seen, changed = set(), False
    for i, line in enumerate(lines):
        m = re.match(r"\s*([A-Za-z0-9_]+)\s*=", line)
        if m and m.group(1) in want:
            new = f'{m.group(1)} = "{want[m.group(1)]}"'
            changed |= line != new
            lines[i] = new
            seen.add(m.group(1))
    for key in want:
        if key not in seen:
            lines.append(f'{key} = "{want[key]}"')
            changed = True
    if changed:
        atomic_write(path, "\n".join(lines) + "\n")
    return changed


def _core_of(args):
    """Nom du fichier du cœur dans « -L …/xxx_libretro.so »."""
    for i, a in enumerate(args[:-1]):
        if a in ("-L", "--libretro"):
            return os.path.basename(args[i + 1]).replace("_libretro.so", "")
    return None


# Affichage N64 (Réglages › Jeux › Image) → pilote vidéo de RetroArch, RDP et RSP de Mupen64Plus-Next.
# GLideN64 (OpenGL) reste noir sur cette machine ; ParaLLEl passe par Vulkan, qui marche (Dolphin
# l'utilise) ; Angrylion dessine sur le processeur : le plus sûr, mais le plus lent.
N64_VIDEO = {
    "parallel": ("vulkan", "parallel", "parallel"),
    "gliden64": ("glcore", "gliden64", "hle"),
    "angrylion": ("glcore", "angrylion", "parallel"),
}


def deferred_core_setup(core, settings=None):
    """Réglages propres au cœur : pas de chargement automatique au démarrage, emplacement « auto » pour
    la touche « charger » (envoyée par la console après le lancement) ; pour la N64, le moteur
    d'affichage choisi."""
    name = DEFERRED_CORES[core]
    base = os.path.join(RA_DIR, "config", name)
    cfg = {"savestate_auto_load": '"false"', "state_slot": '"-1"'}
    if core == "mupen64plus_next":
        driver, rdp, rsp = N64_VIDEO.get((settings or {}).get("n64_video"), N64_VIDEO["parallel"])
        cfg["video_driver"] = f'"{driver}"'
        _cfg_lines(os.path.join(base, name + ".opt"),
                   {"mupen64plus-rdp-plugin": f'"{rdp}"', "mupen64plus-rsp-plugin": f'"{rsp}"'})
    _cfg_lines(os.path.join(base, name + ".cfg"), cfg)
    return name


def _cfg_lines(path, values):
    """Écrit des « clé = valeur » dans un fichier de réglages RetroArch, sans toucher au reste."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        atomic_write(path, "")
    for key, value in values.items():
        _cfg_line(path, key, value)


def _cfg_line(path, key, value):
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    wanted = f"{key} = {value}"
    found = [i for i, ln in enumerate(lines) if re.match(rf"\s*{re.escape(key)}\s*=", ln)]
    if found and lines[found[0]] == wanted:
        return
    if found:
        lines[found[0]] = wanted
    else:
        lines.append(wanted)
    atomic_write(path, "\n".join(lines) + "\n")


def command(emu, args, on=None):
    """(commande à lancer, jeu, état rechargé, recharger par raccourci après le lancement)."""
    settings = _settings()
    on = (settings.get("resume_games", True) is not False) if on is None else on
    rom = find_rom(args)
    extra, state, hotkey = [], None, False
    display = display_args(emu, settings) + (["--verbose"] if emu == "retroarch" else [])
    if emu == "retroarch":
        retroarch_config(on)
        core = _core_of(args)
        if core in DEFERRED_CORES:
            deferred_core_setup(core, settings)
            if on and rom and _retroarch_auto_states(rom):
                hotkey = True                  # la console envoie « charger » une fois le jeu à l'écran
    elif on and rom:
        state = state_for(rom, emu)
        if state and emu == "dolphin":
            extra = ["-s", state]
        elif state and emu == "pcsx2":
            extra = ["-statefile", state]
        elif state and emu == "azahar":
            hotkey = True
    return ["flatpak", "run", FLATPAKS[emu]] + display + extra + list(args), rom, state, hotkey


def after_exit(emu, rom, started, loaded_state, ran_for):
    """À la fermeture : retient l'état écrit pendant la partie. Sinon (plantage, coupure, jeu quitté
    autrement que par la console), l'ancien état est oublié : il daterait d'avant cette partie, et
    le reprendre ferait perdre ce qui vient d'être joué ou sauvegardé dans le jeu. De même pour un
    état qui a empêché PCSX2 de démarrer."""
    if not rom or emu == "retroarch":
        return None
    state = newest_state(emu, started - 1)
    if state:
        record(rom, emu, state)
        return state
    if ran_for > 60 or (loaded_state and emu == "pcsx2"):
        _drop(rom)
    return None
