#!/usr/bin/env bash
# 10 — Sources APT (contrib/non-free), mise à jour, firmwares, outils de base.
source "$REPO_DIR/lib/common.sh"; step_init

# --- Sources APT au format deb822 avec tous les composants ---------------------
mirror="http://deb.debian.org/debian"
existing=$(grep -hEo '^\s*deb\s+(\[[^]]*\]\s+)?https?://[^ ]+/debian/?\s+trixie\b' \
             /etc/apt/sources.list 2>/dev/null | head -n1 | grep -Eo 'https?://[^ ]+' || true)
[[ -z $existing ]] && existing=$(awk '/^URIs:/ && $2 ~ /\/debian\/?$/ && $2 !~ /security/ {print $2; exit}' \
             /etc/apt/sources.list.d/debian.sources 2>/dev/null || true)
[[ -n $existing ]] && mirror=${existing%/}
log "Miroir Debian : $mirror"

if [[ -f /etc/apt/sources.list ]] && grep -Eq '^\s*deb(-src)?\s' /etc/apt/sources.list; then
  backup_once /etc/apt/sources.list
  sed -i -E 's/^(\s*deb(-src)?\s)/# (console-ux481) \1/' /etc/apt/sources.list
fi
backup_once /etc/apt/sources.list.d/debian.sources
cat > /etc/apt/sources.list.d/debian.sources <<EOF
# Généré par console-ux481 (sauvegarde de l'original : *.console-orig)
Types: deb
URIs: ${mirror}
Suites: trixie trixie-updates
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://security.debian.org/debian-security
Suites: trixie-security
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
EOF
ok "Sources APT : main contrib non-free non-free-firmware"

apt_update
log "Mise à jour du système (peut prendre quelques minutes)…"
apt_q -y -q full-upgrade

# --- Firmwares & microcode (Wi-Fi/BT Intel AX201, audio SOF, GPU Intel) ------
apt_install_available \
  firmware-linux-free firmware-misc-nonfree firmware-intel-graphics firmware-iwlwifi \
  firmware-sof-signed firmware-realtek intel-microcode

# --- Outils de base ----------------------------------------------------------
apt_install_available \
  sudo curl wget ca-certificates gnupg jq unzip xz-utils zstd rsync git file \
  pciutils usbutils lshw dbus dbus-user-session polkitd pkexec xdg-user-dirs \
  locales less nano htop bash-completion util-linux-extra \
  python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1 \
  gir1.2-gtklayershell-0.1 python3-sdl2 python3-evdev python3-websocket \
  libsdl2-2.0-0 fonts-noto-core fonts-noto-color-emoji fonts-inter fonts-inter-variable \
  librsvg2-bin

# Ajout de jeux : QR code de l'écran « Ajouter des jeux », archives .7z, clés USB formatées en NTFS
apt_install_available qrencode ntfs-3g
if pkg_available 7zip; then apt_install 7zip; else apt_install_available p7zip-full; fi

# Locale française disponible (l'interface est en français ; la langue système reste la tienne).
if ! locale -a 2>/dev/null | grep -qi '^fr_FR\.utf-\?8$'; then
  if sed -i -E 's/^#\s*(fr_FR\.UTF-8 UTF-8)/\1/' /etc/locale.gen; then locale-gen >/dev/null || true; fi
fi
ok "Système à jour, firmwares et outils installés"
