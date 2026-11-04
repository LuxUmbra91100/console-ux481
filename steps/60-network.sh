#!/usr/bin/env bash
# 60 — Réseau : NetworkManager (Wi-Fi réglable à la manette), Wi-Fi sans économie
#      d'énergie (latence Moonlight), nom .local, partage « Jeux » pour copier les ROMs.
source "$REPO_DIR/lib/common.sh"; step_init

apt_install_available network-manager avahi-daemon libnss-mdns iw

install -d /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/50-console.conf <<'EOF'
# console-ux481
[connection]
# Économie d'énergie Wi-Fi désactivée : indispensable pour un streaming Moonlight fluide.
wifi.powersave = 2
[device]
wifi.scan-rand-mac-address = no
EOF
# Ne pas attendre le réseau pour démarrer (démarrage plus rapide).
systemctl disable NetworkManager-wait-online.service >/dev/null 2>&1 || true
systemctl disable systemd-networkd-wait-online.service >/dev/null 2>&1 || true
enable_now NetworkManager.service avahi-daemon.service
# La reprise des connexions configurées par l'installateur Debian (ifupdown) se fait
# à la toute fin (étape 99) pour ne pas couper le réseau pendant l'installation.

# --- Partage réseau pour déposer jeux et BIOS depuis un PC ---------------------
if [[ ${OPT_SAMBA:-1} == 1 ]]; then
  apt_install_available samba wsdd2 wsdd
  user_install_dir "$CONSOLE_HOME/ROMs"
  user_install_dir "$CONSOLE_HOME/BIOS"
  user_install_dir "$CONSOLE_HOME/Captures"
  backup_once /etc/samba/smb.conf
  cat > /etc/samba/smb.conf <<EOF
# Généré par console-ux481
[global]
   workgroup = WORKGROUP
   server string = ${CONSOLE_NAME}
   server role = standalone server
   map to guest = never
   server min protocol = SMB2_10
   disable netbios = yes
   smb ports = 445
   load printers = no
   printing = bsd
   printcap name = /dev/null
   disable spoolss = yes
   log file = /var/log/samba/log.%m
   max log size = 1000
   logging = file

[Jeux]
   comment = ROMs (un dossier par console : gba, nds, n3ds, gc, wii, psx, ps2)
   path = ${CONSOLE_HOME}/ROMs
   valid users = ${CONSOLE_USER}
   force user = ${CONSOLE_USER}
   read only = no
   create mask = 0644
   directory mask = 0755

[BIOS]
   comment = BIOS des consoles (PS1, PS2…)
   path = ${CONSOLE_HOME}/BIOS
   valid users = ${CONSOLE_USER}
   force user = ${CONSOLE_USER}
   read only = no
   create mask = 0644
   directory mask = 0755

[Captures]
   comment = Captures d'écran
   path = ${CONSOLE_HOME}/Captures
   valid users = ${CONSOLE_USER}
   force user = ${CONSOLE_USER}
   read only = yes
EOF
  pw=${OPT_SMB_PASSWORD:-}
  if [[ -z $pw ]] && pdbedit -L 2>/dev/null | grep -q "^${CONSOLE_USER}:"; then
    ok "Compte Samba existant conservé pour ${CONSOLE_USER}"
  else
    if [[ -z $pw && -t 0 && ${ASSUME_YES:-0} != 1 ]]; then
      echo
      log "Mot de passe du partage réseau « Jeux » (utilisé depuis ton PC pour copier les jeux)."
      while :; do
        read -r -s -p "  Mot de passe : " pw; echo
        read -r -s -p "  Confirmation : " pw2; echo
        [[ -n $pw && $pw == "$pw2" ]] && break
        warn "Les mots de passe ne correspondent pas (ou sont vides), recommence."
      done
    fi
    if [[ -n $pw ]]; then
      printf '%s\n%s\n' "$pw" "$pw" | smbpasswd -s -a "$CONSOLE_USER" >/dev/null
      ok "Compte Samba créé pour ${CONSOLE_USER}"
    else
      warn "Pas de mot de passe Samba fourni : partage créé mais inaccessible."
      note "Partage réseau : définis un mot de passe avec « sudo smbpasswd -a ${CONSOLE_USER} »."
    fi
  fi
  enable_now smbd.service
  systemctl disable --now nmbd.service >/dev/null 2>&1 || true
  for s in wsdd2.service wsdd.service; do
    systemctl list-unit-files "$s" >/dev/null 2>&1 && enable_now "$s" && break
  done
  host=$(hostname)
  note "Copie tes jeux depuis un PC : \\\\${host}\\Jeux (Windows) ou smb://${host}.local/Jeux (Mac/Linux), utilisateur ${CONSOLE_USER}."
  ok "Partages réseau Jeux / BIOS / Captures prêts"
fi
