#!/usr/bin/env bash
# 85 — Préréglages des applications : tout marche à la manette, en plein écran, sur la TV.
#      Les fichiers existants sont mis à jour clé par clé (tes réglages perso sont conservés).
source "$REPO_DIR/lib/common.sh"; step_init

H=$CONSOLE_HOME
VAR=$H/.var/app

# =========================================================== ES-DE =============
ESDE=$H/ES-DE
install -d -o "$CONSOLE_USER" -g "$CONSOLE_GROUP" "$ESDE" "$ESDE/settings" "$ESDE/gamelists"
python3 - "$ESDE/settings/es_settings.xml" <<'PY'
import os, re, sys
path = sys.argv[1]
want = [("string", "ApplicationLanguage", "fr_FR"), ("string", "Theme", "linear-es-de"),
        ("string", "ThemeAspectRatio", "16:9"), ("string", "CollectionSystemsAuto", "all,favorites,recent"),
        ("string", "ApplicationUpdaterFrequency", "never"), ("bool", "ShowQuitMenu", "false"),
        ("bool", "RunInBackground", "false"), ("string", "ScreensaverType", "dim"),
        ("int", "ScreensaverTimer", "600000"), ("bool", "NavigationSounds", "true"),
        ("string", "StartupView", "system"), ("string", "StartupSystem", "")]
text = open(path, encoding="utf-8").read() if os.path.exists(path) else '<?xml version="1.0"?>\n'
for kind, name, value in want:
    line = f'<{kind} name="{name}" value="{value}" />'
    pat = re.compile(rf'<\w+ name="{re.escape(name)}" value="[^"]*" />')
    text = pat.sub(line, text) if pat.search(text) else text.rstrip("\n") + "\n" + line + "\n"
open(path, "w", encoding="utf-8").write(text)
PY
# Émulateur choisi par système (les autres systèmes gardent le défaut d'ES-DE).
declare -A ALT=([gc]="Dolphin (Standalone)" [wii]="Dolphin (Standalone)" [ps2]="PCSX2 (Standalone)"
                [n3ds]="Azahar (Standalone)" [psx]="Beetle PSX HW")
for sys in "${!ALT[@]}"; do
  gl="$ESDE/gamelists/$sys/gamelist.xml"
  install -d -o "$CONSOLE_USER" -g "$CONSOLE_GROUP" "$(dirname "$gl")"
  if [[ ! -f $gl ]]; then
    printf '<?xml version="1.0"?>\n<alternativeEmulator>\n\t<label>%s</label>\n</alternativeEmulator>\n<gameList>\n</gameList>\n' "${ALT[$sys]}" > "$gl"
  elif ! grep -q '<alternativeEmulator>' "$gl"; then
    python3 - "$gl" "${ALT[$sys]}" <<'PY'
import re, sys
path, label = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()
block = f"<alternativeEmulator>\n\t<label>{label}</label>\n</alternativeEmulator>\n"
m = re.search(r"<\?xml[^>]*\?>\s*", text)
text = text[:m.end()] + block + text[m.end():] if m else block + text
open(path, "w", encoding="utf-8").write(text)
PY
  fi
done
chown -R "$CONSOLE_USER:$CONSOLE_GROUP" "$ESDE"
ok "ES-DE : français, thème Linear, Dolphin/PCSX2/Azahar/Beetle PSX HW"

# ========================================================= RetroArch ===========
RA=$VAR/org.libretro.RetroArch/config/retroarch
install -d "$RA"
python3 - "$RA/retroarch.cfg" "$H/BIOS" <<'PY'
import os, re, sys
path, bios = sys.argv[1], sys.argv[2]
want = {
    # Indispensable quand on pré-crée le fichier (sinon l'autoconfig manette est vide) :
    "joypad_autoconfig_dir": "/app/share/libretro/autoconfig",
    "assets_directory": "/app/share/libretro/assets/",
    "libretro_info_path": "/app/share/libretro/info",
    "system_directory": bios,
    "video_fullscreen": "true",
    "pause_nonactive": "true",            # le jeu se met en pause sous le menu de la console
    "menu_driver": "ozone",
    "input_menu_toggle_gamepad_combo": "7",  # maintenir Start 2 s = menu RetroArch
    "quit_press_twice": "false",
    "confirm_quit": "false",
    "config_save_on_exit": "true",
    "savestate_auto_index": "false",
    "video_vsync": "true",
    "notification_show_autoconfig": "false",
    "menu_show_core_updater": "true",
    "user_language": "2",                 # français
}
lines = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else []
seen = set()
for i, line in enumerate(lines):
    m = re.match(r'^\s*([A-Za-z0-9_]+)\s*=', line)
    if m and m.group(1) in want:
        lines[i] = f'{m.group(1)} = "{want[m.group(1)]}"'
        seen.add(m.group(1))
lines += [f'{k} = "{v}"' for k, v in want.items() if k not in seen]
open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
PY
chown -R "$CONSOLE_USER:$CONSOLE_GROUP" "$VAR/org.libretro.RetroArch"
ok "RetroArch : plein écran, pause hors focus, BIOS dans ~/BIOS"

# ========================================================== Dolphin =============
DOL=$VAR/org.DolphinEmu.dolphin-emu/config/dolphin-emu
install -d "$DOL"
ini_set "$DOL/Dolphin.ini" Interface ConfirmStop False PauseOnFocusLost True CursorVisibility 0 UsePanicHandlers False
ini_set "$DOL/Dolphin.ini" Display Fullscreen True
ini_set "$DOL/Dolphin.ini" Analytics PermissionAsked True Enabled False
ini_set "$DOL/Dolphin.ini" Core GFXBackend Vulkan
ini_set "$DOL/Dolphin.ini" General ISOPaths 2 ISOPath0 "$H/ROMs/gc" ISOPath1 "$H/ROMs/wii"
ini_set "$DOL/GFX.ini" Settings InternalResolution 1 ShaderCompilationMode 2 WaitForShadersBeforeStarting True
ini_set "$DOL/Logger.ini" Options WriteToFile True Verbosity 4
ini_set "$DOL/Logger.ini" Logs CI True
DEV="SDL/0/Xbox Series X Controller"   # corrigé automatiquement à la connexion de la manette
if [[ ! -f $DOL/GCPadNew.ini ]]; then
  cat > "$DOL/GCPadNew.ini" <<EOF
[GCPad1]
Device = $DEV
Buttons/A = \`Button S\`
Buttons/B = \`Button E\`
Buttons/X = \`Button W\`
Buttons/Y = \`Button N\`
Buttons/Z = \`Shoulder R\`
Buttons/Start = Start
Main Stick/Up = \`Left Y+\`
Main Stick/Down = \`Left Y-\`
Main Stick/Left = \`Left X-\`
Main Stick/Right = \`Left X+\`
C-Stick/Up = \`Right Y+\`
C-Stick/Down = \`Right Y-\`
C-Stick/Left = \`Right X-\`
C-Stick/Right = \`Right X+\`
Triggers/L = \`Trigger L\`
Triggers/R = \`Trigger R\`
Triggers/L-Analog = \`Trigger L\`
Triggers/R-Analog = \`Trigger R\`
D-Pad/Up = \`Pad N\`
D-Pad/Down = \`Pad S\`
D-Pad/Left = \`Pad W\`
D-Pad/Right = \`Pad E\`
Rumble/Motor = Motor
EOF
fi
if [[ ! -f $DOL/WiimoteNew.ini ]]; then
  cat > "$DOL/WiimoteNew.ini" <<EOF
[Wiimote1]
Device = $DEV
Source = 1
Buttons/A = \`Button S\`
Buttons/B = \`Trigger R\`
Buttons/1 = \`Button W\`
Buttons/2 = \`Button N\`
Buttons/- = Back
Buttons/+ = Start
Buttons/Home = \`Thumb L\`
D-Pad/Up = \`Pad N\`
D-Pad/Down = \`Pad S\`
D-Pad/Left = \`Pad W\`
D-Pad/Right = \`Pad E\`
IR/Up = \`Right Y+\`
IR/Down = \`Right Y-\`
IR/Left = \`Right X-\`
IR/Right = \`Right X+\`
IR/Recenter = \`Thumb R\`
IR/Relative Input = True
Shake/X = \`Button E\`
Shake/Y = \`Button E\`
Shake/Z = \`Button E\`
Rumble/Motor = Motor
Extension = Nunchuk
Nunchuk/Buttons/C = \`Shoulder L\`
Nunchuk/Buttons/Z = \`Trigger L\`
Nunchuk/Stick/Up = \`Left Y+\`
Nunchuk/Stick/Down = \`Left Y-\`
Nunchuk/Stick/Left = \`Left X-\`
Nunchuk/Stick/Right = \`Left X+\`
EOF
fi
chown -R "$CONSOLE_USER:$CONSOLE_GROUP" "$VAR/org.DolphinEmu.dolphin-emu"
ok "Dolphin : Vulkan, plein écran, manette Xbox (GameCube + Wiimote/Nunchuk)"

# =========================================================== PCSX2 ==============
P2=$VAR/net.pcsx2.PCSX2/config/PCSX2/inis
install -d "$P2"
if [[ ! -f $P2/PCSX2.ini ]]; then
  # Fichier complet : PCSX2 n'ajoute les raccourcis et la manette par défaut que
  # lorsqu'il crée lui-même le fichier.
  cat > "$P2/PCSX2.ini" <<EOF
[UI]
SettingsVersion = 1
SetupWizardIncomplete = false
StartFullscreen = true
ConfirmShutdown = false
PauseOnFocusLoss = true
HideMouseCursor = true

[Folders]
Bios = $H/BIOS

[InputSources]
SDL = true
SDLControllerEnhancedMode = false

[EmuCore/GS]
Renderer = 14
upscale_multiplier = 1

[Hotkeys]
ToggleFullscreen = Keyboard/Alt & Keyboard/Return
OpenPauseMenu = Keyboard/Escape
SaveStateToSlot = Keyboard/F1
NextSaveStateSlot = Keyboard/F2
LoadStateFromSlot = Keyboard/F3

[Pad1]
Type = DualShock2
Up = SDL-0/DPadUp
Right = SDL-0/DPadRight
Down = SDL-0/DPadDown
Left = SDL-0/DPadLeft
Triangle = SDL-0/FaceNorth
Circle = SDL-0/FaceEast
Cross = SDL-0/FaceSouth
Square = SDL-0/FaceWest
Select = SDL-0/Back
Start = SDL-0/Start
L1 = SDL-0/LeftShoulder
L2 = SDL-0/+LeftTrigger
R1 = SDL-0/RightShoulder
R2 = SDL-0/+RightTrigger
L3 = SDL-0/LeftStick
R3 = SDL-0/RightStick
LUp = SDL-0/-LeftY
LRight = SDL-0/+LeftX
LDown = SDL-0/+LeftY
LLeft = SDL-0/-LeftX
RUp = SDL-0/-RightY
RRight = SDL-0/+RightX
RDown = SDL-0/+RightY
RLeft = SDL-0/-RightX
LargeMotor = SDL-0/LargeMotor
SmallMotor = SDL-0/SmallMotor
EOF
else
  ini_set "$P2/PCSX2.ini" UI SetupWizardIncomplete false StartFullscreen true ConfirmShutdown false PauseOnFocusLoss true
  ini_set "$P2/PCSX2.ini" Folders Bios "$H/BIOS"
fi
chown -R "$CONSOLE_USER:$CONSOLE_GROUP" "$VAR/net.pcsx2.PCSX2"
ok "PCSX2 : plein écran, manette, BIOS dans ~/BIOS (bouton Xbox libre)"

# =========================================================== Azahar =============
AZ=$VAR/org.azahar_emu.Azahar/config/azahar-emu
install -d "$AZ"
if [[ ! -f $AZ/qt-config.ini ]]; then
  # Mappage « toutes les manettes » (pas d'identifiant propre à une manette).
  btn() { printf '"api:controller,button:%s,engine:sdl,maptype:all"' "$1"; }
  cat > "$AZ/qt-config.ini" <<EOF
[Controls]
controller_hotkey_maptype=0
profile=0
profiles\\size=1
profiles\\1\\name=Default
profiles\\1\\input_maptype=0
profiles\\1\\button_a=$(btn 1)
profiles\\1\\button_b=$(btn 0)
profiles\\1\\button_x=$(btn 3)
profiles\\1\\button_y=$(btn 2)
profiles\\1\\button_up=$(btn 11)
profiles\\1\\button_down=$(btn 12)
profiles\\1\\button_left=$(btn 13)
profiles\\1\\button_right=$(btn 14)
profiles\\1\\button_l=$(btn 9)
profiles\\1\\button_r=$(btn 10)
profiles\\1\\button_start=$(btn 6)
profiles\\1\\button_select=$(btn 4)
profiles\\1\\button_home=$(btn 7)
profiles\\1\\button_zl="api:controller,axis:4,direction:+,engine:sdl,maptype:all,threshold:0.5"
profiles\\1\\button_zr="api:controller,axis:5,direction:+,engine:sdl,maptype:all,threshold:0.5"
profiles\\1\\circle_pad="api:controller,axis_x:0,axis_y:1,deadzone:0.1,engine:sdl,maptype:all"
profiles\\1\\c_stick="api:controller,axis_x:2,axis_y:3,deadzone:0.1,engine:sdl,maptype:all"

[UI]
fullscreen=true
confirmClose=false
pauseWhenInBackground=true
hideInactiveMouse=true
saveStateWarning=false

[Layout]
layout_option=2

[Renderer]
resolution_factor=2
EOF
else
  ini_set --sep "=" "$AZ/qt-config.ini" UI 'fullscreen\default' false fullscreen true \
    'confirmClose\default' false confirmClose false 'pauseWhenInBackground\default' false pauseWhenInBackground true
fi
chown -R "$CONSOLE_USER:$CONSOLE_GROUP" "$VAR/org.azahar_emu.Azahar"
ok "Azahar : plein écran, grand écran du haut, manette (toutes manettes)"

# ========================================================= Moonlight ============
ML="$VAR/com.moonlight_stream.Moonlight/config/Moonlight Game Streaming Project"
install -d "$ML"
if [[ ! -f $ML/Moonlight.conf ]]; then
  cat > "$ML/Moonlight.conf" <<'EOF'
[General]
defaultver=2
width=1920
height=1080
fps=60
bitrate=20000
windowmode=0
uidisplaymode=2
videodec=0
videocfg=0
vsync=true
framepacing=true
gameopts=true
hostaudio=false
muteonfocusloss=false
backgroundgamepad=false
gamepadmouse=true
quitAppAfter=false
showperfoverlay=false
detectnetblocking=true
keepawake=true
capturesyskeys=1
EOF
fi
chown -R "$CONSOLE_USER:$CONSOLE_GROUP" "$VAR/com.moonlight_stream.Moonlight"
ok "Moonlight : 1080p60, plein écran, décodage matériel automatique"
