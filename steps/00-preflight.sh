#!/usr/bin/env bash
# 00 — Vérifications préalables et outils minimum.
source "$REPO_DIR/lib/common.sh"; step_init

# shellcheck disable=SC1091
. /etc/os-release
[[ ${ID:-} == debian ]] || die "Ce script cible Debian (système détecté : ${PRETTY_NAME:-inconnu})."
if [[ ${VERSION_CODENAME:-} != trixie ]]; then
  warn "Système détecté : ${PRETTY_NAME:-?}. Le script est prévu pour Debian 13 « trixie »."
  confirm "Continuer quand même ?" || die "Abandon."
fi
[[ $(dpkg --print-architecture) == amd64 ]] || die "Architecture amd64 requise."
ok "${PRETTY_NAME}"

# Une installation depuis une clé/DVD laisse souvent une source « cdrom » qui casse apt.
for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do
  [[ -f $f ]] || continue
  if grep -Eq '^\s*deb\s+cdrom:' "$f"; then
    backup_once "$f"
    sed -i -E 's/^(\s*deb\s+cdrom:)/# \1/' "$f"
    ok "Source APT « cdrom » désactivée dans $f"
  fi
done

if ! getent hosts deb.debian.org >/dev/null; then
  die "Pas de réseau (deb.debian.org introuvable). Connecte la machine à Internet puis relance."
fi

log "Outils de base…"
apt_update
apt_install ca-certificates curl pciutils usbutils python3 sudo kmod

curl -fsS --max-time 15 -o /dev/null https://deb.debian.org/debian/ \
  || die "Accès HTTPS impossible vers deb.debian.org."

avail=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
if (( avail < 25 )); then
  warn "Seulement ${avail} Go libres sur / : prévois au moins 25 Go (Flatpaks + émulateurs + jeux)."
  confirm "Continuer ?" || die "Abandon."
fi

mkdir -p /run/console-install
: > /run/console-install/notes
model=$(cat /sys/class/dmi/id/product_name 2>/dev/null || echo inconnu)
vendor=$(cat /sys/class/dmi/id/sys_vendor 2>/dev/null || echo inconnu)
sb=0
for sbvar in /sys/firmware/efi/efivars/SecureBoot-*; do
  [[ -e $sbvar ]] || continue
  [[ $(od -An -t u1 "$sbvar" 2>/dev/null | awk '{print $NF}') == 1 ]] && sb=1
done
nv=0; has_nvidia_gpu && nv=1
{
  echo "MODEL=\"$model\""
  echo "VENDOR=\"$vendor\""
  echo "SECURE_BOOT=$sb"
  echo "HAS_NVIDIA=$nv"
} > /run/console-install/facts

log "Machine : $vendor $model"
lspci -nn | grep -Ei 'vga|3d controller|display' | sed 's/^/      /' || true
if [[ $model != *UX481* ]]; then
  warn "Ce n'est pas un Zenbook Duo UX481 : le script devrait fonctionner, mais rien n'est garanti."
fi
if (( sb )); then
  warn "Secure Boot est ACTIVÉ : le pilote xpadneo (manettes Xbox) devra être signé."
  warn "Le plus simple : désactive Secure Boot dans le BIOS (F2 › Security › Secure Boot)."
fi
ok "Utilisateur de la console : $CONSOLE_USER"
