#!/usr/bin/env bash
# 40 — Bluetooth pour manettes Xbox : BlueZ réglé, pilote xpadneo, réveil par Bluetooth.
source "$REPO_DIR/lib/common.sh"; step_init
# Relevé ici (et non lu dans /run, effacé au redémarrage) : l'étape peut tourner seule (--only 40).
SECURE_BOOT=0; secure_boot_enabled && SECURE_BOOT=1

apt_install_available bluez rfkill
install -d /etc/bluetooth
[[ -f /etc/bluetooth/main.conf ]] || : > /etc/bluetooth/main.conf
backup_once /etc/bluetooth/main.conf

# Réglages recommandés par xpadneo pour les manettes Xbox (BLE, firmware 5.x) :
#  - Privacy=device + JustWorksRepairing : appairage/ré-appairage fiable
#  - intervalles LE 7..9 (8,75–11,25 ms) : latence minimale de la manette
#  - FastConnectable : reconnexion rapide quand on allume la manette
ini_set /etc/bluetooth/main.conf General \
  ControllerMode dual \
  FastConnectable true \
  JustWorksRepairing always \
  Privacy device
ini_set /etc/bluetooth/main.conf Policy \
  AutoEnable true \
  ReconnectAttempts 7 \
  ReconnectIntervals 1,2,4,8,16,32,64
ini_set /etc/bluetooth/main.conf LE \
  MinConnectionInterval 7 \
  MaxConnectionInterval 9 \
  ConnectionLatency 0
ok "BlueZ configuré pour les manettes Xbox"

# uhid : indispensable aux manettes Bluetooth LE (Xbox Series, One S récentes).
cat > /etc/modules-load.d/console-input.conf <<'EOF'
# console-ux481
uhid
uinput
EOF

# Autorise l'adaptateur Bluetooth à sortir la machine de veille (bouton Xbox).
cat > /etc/udev/rules.d/81-console-bt-wake.rules <<'EOF'
# console-ux481 : l'adaptateur Bluetooth peut réveiller la console (manette)
ACTION=="bind", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_interface", DRIVER=="btusb", RUN+="/bin/sh -c 'echo enabled > /sys%p/../power/wakeup'"
EOF

# --- xpadneo (bouton Xbox reconnu, vibrations, batterie, mapping correct) -----
if [[ ${OPT_XPADNEO:-1} == 1 ]]; then
  apt_install dkms linux-headers-amd64 git
  apt_install_available "linux-headers-$(uname -r)" mokutil openssl
  # Dernière version STABLE : les étiquettes de test (ex. « v0.11-pre ») sont écartées.
  tag=$(git ls-remote --tags --refs https://github.com/atar-axis/xpadneo.git 'v*' 2>/dev/null \
          | awk -F/ '{print $NF}' | grep -E '^v[0-9]+(\.[0-9]+)*$' | sort -V | tail -n1 || true)
  src=/usr/local/src/xpadneo
  rm -rf "$src.new"
  if [[ -n $tag ]]; then
    git clone -q --depth 1 --branch "$tag" https://github.com/atar-axis/xpadneo.git "$src.new"
  else
    warn "Impossible de lister les versions de xpadneo : utilisation de la branche principale."
    git clone -q --depth 1 https://github.com/atar-axis/xpadneo.git "$src.new"
  fi
  newver=$(cat "$src.new/VERSION" 2>/dev/null || echo "$tag")
  # Version réellement installée pour le noyau en cours (« added » ou « built » ne suffisent pas).
  curver=$(dkms status -m hid-xpadneo -k "$(uname -r)" 2>/dev/null | grep -m1 ': installed' \
             | sed -E 's#^hid-xpadneo/([^,:]+).*#\1#' || true)
  if [[ -n $curver && ${curver#v} == "${newver#v}" ]]; then
    ok "xpadneo ${curver} déjà installé"
    rm -rf "$src.new"
  else
    # Retire toute version précédente, y compris une installation ratée.
    for old in $(dkms status -m hid-xpadneo 2>/dev/null | sed -E 's#^hid-xpadneo/([^,:]+).*#\1#' | sort -u); do
      dkms remove "hid-xpadneo/$old" --all >/dev/null 2>&1 || true
    done
    if [[ -d $src ]]; then (cd "$src" && ./uninstall.sh) >/dev/null 2>&1 || true; fi
    rm -rf "$src"; mv "$src.new" "$src"
    if (cd "$src" && ./install.sh); then
      ok "xpadneo ${newver} installé (DKMS)"
    else
      warn "Installation de xpadneo échouée : la manette marchera avec le pilote du noyau (sans bouton Xbox dédié)."
      note "xpadneo n'a pas pu être installé (voir le journal). La manette Xbox reste utilisable."
    fi
  fi
  # Construit aussi le module pour les noyaux installés mais pas encore démarrés.
  ver=$(dkms status -m hid-xpadneo 2>/dev/null | grep -m1 ': installed' | sed -E 's#^hid-xpadneo/([^,:]+).*#\1#' || true)
  if [[ -n $ver ]]; then
    for kdir in /lib/modules/*; do
      [[ -d $kdir/build ]] || continue
      dkms install "hid-xpadneo/$ver" -k "$(basename "$kdir")" >/dev/null 2>&1 || true
    done
    echo hid_xpadneo > /etc/modules-load.d/xpadneo.conf
    # Chargé tout de suite : pas besoin de redémarrer après une mise à jour.
    if modprobe hid_xpadneo 2>/dev/null; then
      ok "Pilote xpadneo ${ver} actif (éteins puis rallume la manette pour qu'elle l'utilise)"
    else
      warn "xpadneo ${ver} installé mais pas encore chargé : il le sera au prochain démarrage."
    fi
  fi
  if [[ ${SECURE_BOOT:-0} == 1 && -f /var/lib/dkms/mok.pub ]]; then
    if mokutil --test-key /var/lib/dkms/mok.pub 2>/dev/null | grep -qi 'already enrolled'; then
      ok "Clé de signature DKMS déjà enrôlée (Secure Boot)"
    elif [[ -t 0 ]]; then
      warn "Secure Boot actif : il faut enrôler la clé qui signe xpadneo."
      warn "Choisis un mot de passe temporaire ; au redémarrage, un écran bleu « MOK » s'affiche :"
      warn "  Enroll MOK › Continue › Yes › tape ce mot de passe › Reboot (clavier nécessaire)."
      mokutil --import /var/lib/dkms/mok.pub || true
      note "Secure Boot : au prochain démarrage, valide « Enroll MOK » (écran bleu) avec le mot de passe choisi."
    else
      note "Secure Boot actif : lance « sudo mokutil --import /var/lib/dkms/mok.pub » puis redémarre, ou désactive Secure Boot."
    fi
  fi
fi

enable_now bluetooth.service
ok "Bluetooth prêt"
