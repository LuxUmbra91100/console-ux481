#!/usr/bin/env bash
# 50 — Session console : connexion automatique (greetd) → sway en mode kiosque.
source "$REPO_DIR/lib/common.sh"; step_init

apt_install_available sway swayidle xwayland greetd wtype wl-clipboard grim foot wlr-randr \
  xdg-desktop-portal xdg-desktop-portal-wlr xdg-desktop-portal-gtk \
  power-profiles-daemon policykit-1 polkitd

# Un éventuel gestionnaire de connexion graphique (installation avec bureau) est désactivé.
for dm in gdm3 gdm sddm lightdm lxdm xdm; do
  if systemctl list-unit-files "$dm.service" >/dev/null 2>&1 && systemctl is-enabled "$dm.service" >/dev/null 2>&1; then
    systemctl disable "$dm.service" >/dev/null 2>&1 || true
    warn "Gestionnaire de connexion $dm désactivé (remplacé par la session console)."
  fi
done

# --- Groupes : manettes, clavier/souris virtuels, GPU, Bluetooth, réseau -------
for g in input video render audio bluetooth netdev plugdev; do
  getent group "$g" >/dev/null && usermod -aG "$g" "$CONSOLE_USER"
done
ok "$CONSOLE_USER ajouté aux groupes input/video/render/audio/bluetooth/netdev"

cat > /etc/udev/rules.d/60-console-uinput.rules <<'EOF'
# console-ux481 : clavier/souris virtuels de la manette (navigateur, clavier virtuel)
KERNEL=="uinput", SUBSYSTEM=="misc", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput", TAG+="uaccess"
EOF

# --- sway -------------------------------------------------------------------
render "$FILES_DIR/sway.conf" /etc/console/sway.conf
ok "Configuration sway : /etc/console/sway.conf"

# --- greetd : connexion automatique, relance si la session s'arrête -------------
install -d /etc/greetd
backup_once /etc/greetd/config.toml
cat > /etc/greetd/config.toml <<EOF
# Généré par console-ux481 : la console démarre directement, sans écran de connexion.
[terminal]
vt = 1
switch = true

[initial_session]
command = "${PREFIX}/bin/console-session"
user = "${CONSOLE_USER}"

# Si la session se termine (plantage), elle est relancée automatiquement.
[default_session]
command = "${PREFIX}/bin/console-session"
user = "${CONSOLE_USER}"
EOF
# greetd occupe le tty1 : plus d'invite de connexion texte qui s'affiche entre
# l'écran de démarrage et l'interface (les autres tty restent disponibles).
systemctl disable getty@tty1.service >/dev/null 2>&1 || true
systemctl mask getty@tty1.service >/dev/null 2>&1 || true
install -d /etc/systemd/system/greetd.service.d
cat > /etc/systemd/system/greetd.service.d/console.conf <<'EOF'
[Unit]
Conflicts=getty@tty1.service
After=getty@tty1.service
[Service]
Restart=always
RestartSec=2
EOF
systemctl enable greetd.service >/dev/null 2>&1 || true
systemctl set-default graphical.target >/dev/null

# --- Capot fermé, bouton d'alimentation, veille -------------------------------
install -d /etc/systemd/logind.conf.d /etc/systemd/sleep.conf.d
cat > /etc/systemd/logind.conf.d/50-console.conf <<'EOF'
# console-ux481 : la console fonctionne capot fermé. Le bouton d'alimentation et
# la veille sont gérés par l'interface (veille propre, manettes éteintes…).
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandlePowerKey=ignore
HandlePowerKeyLongPress=poweroff
HandleSuspendKey=ignore
HandleHibernateKey=ignore
IdleAction=ignore
EOF
cat > /etc/systemd/sleep.conf.d/50-console.conf <<'EOF'
# console-ux481 : veille RAM uniquement (pas d'hibernation).
[Sleep]
AllowSuspend=yes
AllowHibernation=no
AllowHybridSleep=no
AllowSuspendThenHibernate=no
EOF

# --- Droits : veille/arrêt, réseau, profils d'énergie, mises à jour Flatpak ---
install -d -m 0755 /etc/polkit-1/rules.d
cat > /etc/polkit-1/rules.d/50-console.rules <<EOF
// console-ux481 : la console gère réseau, énergie et mises à jour sans mot de passe.
polkit.addRule(function (action, subject) {
  if (subject.user !== "${CONSOLE_USER}") return polkit.Result.NOT_HANDLED;
  var id = action.id;
  if (id.indexOf("org.freedesktop.NetworkManager.") === 0 ||
      id.indexOf("org.freedesktop.Flatpak.") === 0 ||
      id.indexOf("net.hadess.PowerProfiles.") === 0 ||
      id.indexOf("org.freedesktop.UPower.PowerProfiles.") === 0 ||
      /^org\.freedesktop\.login1\.(suspend|reboot|power-off|set-wall-message)(-multiple-sessions|-ignore-inhibit)?$/.test(id) ||
      id === "org.freedesktop.timedate1.set-timezone") {
    return polkit.Result.YES;
  }
  return polkit.Result.NOT_HANDLED;
});
EOF
cat > /etc/sudoers.d/console-ux481 <<EOF
# console-ux481 : petites actions matérielles (réveil RTC, ScreenPad, mode veille)
${CONSOLE_USER} ALL=(root) NOPASSWD: ${PREFIX}/bin/console-root
EOF
chmod 0440 /etc/sudoers.d/console-ux481
visudo -cf /etc/sudoers.d/console-ux481 >/dev/null || die "sudoers invalide"

# --- Service matériel au démarrage + crochet de mise en veille ----------------
cat > /etc/systemd/system/console-hw.service <<EOF
[Unit]
Description=Console UX481 — réglages matériels (ScreenPad éteint, réveil Bluetooth)
After=bluetooth.service systemd-udev-settle.service
Wants=bluetooth.service

[Service]
Type=oneshot
ExecStart=${PREFIX}/bin/console-root hw-init
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
install -d /usr/lib/systemd/system-sleep
cat > /usr/lib/systemd/system-sleep/console-ux481 <<EOF
#!/bin/sh
# console-ux481 : avant/après la veille
case "\$1" in
  pre)  ${PREFIX}/bin/console-root pre-sleep ;;
  post) ${PREFIX}/bin/console-root post-resume ;;
esac
exit 0
EOF
chmod 0755 /usr/lib/systemd/system-sleep/console-ux481
systemctl daemon-reload
systemctl enable console-hw.service >/dev/null
enable_now power-profiles-daemon.service
ok "Session console configurée (greetd → sway → console-shell)"
