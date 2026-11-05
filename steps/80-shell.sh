#!/usr/bin/env bash
# 80 — Installe le « système » de la console (écran d'accueil, manette, overlay) dans /opt/console.
source "$REPO_DIR/lib/common.sh"; step_init

install -d "$PREFIX" "$PREFIX/bin" "$PREFIX/share/icons"
rsync -a --delete "$SHELL_SRC/consoleshell/" "$PREFIX/consoleshell/"
rsync -a --delete --exclude 'mock.js' "$SHELL_SRC/ui/" "$PREFIX/ui/"
for f in "$SHELL_SRC"/bin/*; do install -m 0755 "$f" "$PREFIX/bin/"; done
chown -R root:root "$PREFIX"
chmod -R a+rX "$PREFIX"
python3 -m compileall -q "$PREFIX/consoleshell" || true
# Outils utiles en SSH, sans taper le chemin complet
for tool in console-ctl console-pc-setup; do ln -sfn "$PREFIX/bin/$tool" "/usr/local/bin/$tool"; done
ok "Shell installé dans $PREFIX"

# Valeurs par défaut choisies à l'installation (l'utilisateur peut les changer dans les réglages).
case "$XKB_LAYOUT" in fr|be) osk=azerty ;; *) osk=qwerty ;; esac
install -d /etc/console
printf 'CONSOLE_USER=%s\nCONSOLE_REPO=%s\n' "$CONSOLE_USER" "$REPO_DIR" > /etc/console/install.env
cat > /etc/console/defaults.json <<EOF
{
  "console_name": "${CONSOLE_NAME}",
  "standby_mode": "${OPT_SLEEP}",
  "osk_layout": "${osk}"
}
EOF

# --- Services utilisateur (lancés par sway au démarrage de la session) ----------
install -d /etc/systemd/user
cat > /etc/systemd/user/console-session.target <<'EOF'
[Unit]
Description=Session console (sway)
Documentation=file:///opt/console
BindsTo=graphical-session.target
Wants=graphical-session-pre.target
After=graphical-session-pre.target
EOF
cat > /etc/systemd/user/console-shell.service <<EOF
[Unit]
Description=Console — écran d'accueil, manettes, superposition
PartOf=graphical-session.target
After=graphical-session.target pipewire.service wireplumber.service
StartLimitIntervalSec=60
StartLimitBurst=10

[Service]
Type=simple
ExecStart=${PREFIX}/bin/console-shell
Restart=always
RestartSec=1
Environment=PYTHONUNBUFFERED=1
Environment=WEBKIT_DISABLE_COMPOSITING_MODE=0

[Install]
WantedBy=console-session.target
EOF
systemctl --global enable console-shell.service >/dev/null
ok "Service utilisateur console-shell activé"

# --- Dossiers de l'utilisateur ------------------------------------------------------
declare -A SYSNAMES=([gba]="Game Boy Advance" [nds]="Nintendo DS" [n3ds]="Nintendo 3DS" \
  [gc]="GameCube" [wii]="Wii" [psx]="PlayStation" [ps2]="PlayStation 2" [nes]="NES" [snes]="Super Nintendo" \
  [n64]="Nintendo 64" [gb]="Game Boy" [gbc]="Game Boy Color" [mastersystem]="Master System" \
  [megadrive]="Mega Drive" [gamegear]="Game Gear")
declare -A SYSHINT=(
  [nes]=".nes (ou .zip)"
  [snes]=".sfc ou .smc (ou .zip)"
  [n64]=".z64, .n64 ou .v64 (ou .zip)"
  [gb]=".gb (ou .zip)"
  [gbc]=".gbc (ou .zip)"
  [mastersystem]=".sms (ou .zip)"
  [megadrive]=".md, .gen, .smd ou .bin (ou .zip)"
  [gamegear]=".gg (ou .zip)"
  [gba]=".gba (ou .zip)"
  [nds]=".nds (ou .zip)"
  [n3ds]=".3ds / .cci DÉCRYPTÉS (GodMode9 sur ta 3DS), ou .zcci ; les .cia doivent d'abord être installés dans Azahar"
  [gc]=".rvz (recommandé), .iso, .gcz, .ciso"
  [wii]=".rvz (recommandé), .wbfs, .iso, .wad"
  [psx]=".chd (recommandé), .cue+.bin, .pbp, .m3u pour les multi-CD ; BIOS requis (scph5501.bin…)"
  [ps2]=".chd ou .iso ; BIOS PS2 requis"
)
user_install_dir "$CONSOLE_HOME/ROMs"
user_install_dir "$CONSOLE_HOME/BIOS"
user_install_dir "$CONSOLE_HOME/Captures"
for s in "${!SYSNAMES[@]}"; do
  user_install_dir "$CONSOLE_HOME/ROMs/$s"
  user_write "$CONSOLE_HOME/ROMs/$s/_LISEZMOI.txt" <<EOF
Dossier ${SYSNAMES[$s]}
Dépose ici tes sauvegardes de jeux ${SYSNAMES[$s]} : ${SYSHINT[$s]}
Après la copie, ouvre « Jeux » sur la console : les jeux apparaissent tout seuls.
EOF
done
user_write "$CONSOLE_HOME/BIOS/_LISEZMOI.txt" <<'EOF'
Dépose ici les BIOS extraits de TES consoles (tous dans ce même dossier) :
  - PlayStation : scph5500.bin, scph5501.bin, scph5502.bin (au moins celui de ta région)
  - PlayStation 2 : le fichier BIOS de ta PS2 (ex. SCPH-70004_BIOS_V12_EUR_200.BIN)
  - Nintendo DS (facultatif) : bios7.bin, bios9.bin, firmware.bin
Les noms et sommes de contrôle attendus sont détaillés dans le README de console-ux481.
EOF
ok "Dossiers ~/ROMs (une console par dossier), ~/BIOS et ~/Captures prêts"
