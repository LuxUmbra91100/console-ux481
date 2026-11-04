#!/usr/bin/env bash
# =============================================================================
#  Console UX481 — mise à jour depuis GitHub.
#  Récupère la dernière version du projet puis réapplique l'installation.
#  Tes réglages, jeux, sauvegardes et manettes associées sont conservés.
#
#  Usage :  sudo ./update.sh   (ou en root via « su - »)   — options de install.sh acceptées, ex. --only 80
# =============================================================================
set -Eeuo pipefail
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
[[ $EUID -eq 0 ]] || { echo "Lance la mise à jour en root :  sudo $0 $*   (ou « su - » puis $0 $*)" >&2; exit 1; }

owner=$(stat -c %U "$HERE")
if [[ -d $HERE/.git ]]; then
  echo "==> Récupération de la dernière version depuis GitHub…"
  before=$(runuser -u "$owner" -- git -C "$HERE" rev-parse --short HEAD)
  runuser -u "$owner" -- git -C "$HERE" pull --ff-only
  after=$(runuser -u "$owner" -- git -C "$HERE" rev-parse --short HEAD)
  if [[ $before == "$after" ]]; then
    echo "    Déjà à jour ($after) : l'installation est quand même réappliquée."
  else
    echo "    $before → $after :"
    runuser -u "$owner" -- git -C "$HERE" log --oneline "$before..$after" | sed 's/^/      /'
  fi
else
  echo "(Pas un dépôt git : on réapplique simplement la version présente.)"
fi

"$HERE/install.sh" --yes --no-reboot "$@"

# Relance de l'interface de la console pour charger le nouveau code (les jeux restent ouverts).
if [[ -r /etc/console/install.env ]]; then
  # shellcheck disable=SC1091
  . /etc/console/install.env
  uid=$(id -u "$CONSOLE_USER" 2>/dev/null || true)
  if [[ -n $uid && -S /run/user/$uid/bus ]]; then
    runuser -u "$CONSOLE_USER" -- env XDG_RUNTIME_DIR="/run/user/$uid" \
      systemctl --user try-restart console-shell.service 2>/dev/null || true
  fi
fi
echo
echo "Mise à jour terminée. Pour appliquer aussi les changements système (session, démarrage),"
echo "redémarre la console :  sudo systemctl reboot"
