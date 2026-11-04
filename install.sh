#!/usr/bin/env bash
# =============================================================================
#  Console UX481 — transforme une Debian 13 fraîchement installée en console
#  de salon : écran d'accueil à la manette, Moonlight, émulation (ES-DE),
#  Brave pilotable à la manette, veille/réveil par la manette.
#
#  Usage :  sudo ./install.sh [options]     (ou, en root via « su - » :  ./install.sh [options])
#     --user NOM            utilisateur de la console (défaut : celui qui lance sudo, sinon UID 1000)
#     --name NOM            nom affiché de la console (défaut : Nova)
#     --smb-password MDP    mot de passe du partage réseau « Jeux » (sinon demandé)
#     --no-samba            pas de partage réseau Windows/Mac pour copier les jeux
#     --no-xpadneo          pas de pilote xpadneo (manettes Xbox)
#     --sleep deep|light    mode de veille par défaut (défaut : deep)
#     --only ETAPE[,ETAPE]  ne lance que certaines étapes (ex : --only 80,85)
#     --skip ETAPE[,ETAPE]  saute certaines étapes
#     --yes                 répond « oui » à toutes les questions
#     --no-reboot           ne propose pas de redémarrer à la fin
#
#  Le script est idempotent : on peut le relancer pour réparer ou mettre à jour.
# =============================================================================
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
export REPO_DIR
# shellcheck source=lib/common.sh
source "$REPO_DIR/lib/common.sh"

usage() { sed -n '2,22p' "$0" | sed 's/^#  \{0,1\}//'; exit "${1:-0}"; }

OPT_USER="" OPT_NAME="Nova" OPT_SMB_PASSWORD="" OPT_SAMBA=1 OPT_XPADNEO=1
OPT_SLEEP="deep" OPT_ONLY="" OPT_SKIP="" ASSUME_YES=0 OPT_REBOOT=1
while (($#)); do
  case "$1" in
    --user) OPT_USER=${2:?}; shift ;;
    --name) OPT_NAME=${2:?}; shift ;;
    --smb-password) OPT_SMB_PASSWORD=${2:?}; shift ;;
    --no-samba) OPT_SAMBA=0 ;;
    --no-xpadneo) OPT_XPADNEO=0 ;;
    --sleep) OPT_SLEEP=${2:?}; shift
             [[ $OPT_SLEEP == deep || $OPT_SLEEP == light ]] || die "--sleep attend deep ou light" ;;
    --only) OPT_ONLY=${2:?}; shift ;;
    --skip) OPT_SKIP=${2:?}; shift ;;
    --yes|-y) ASSUME_YES=1 ;;
    --no-reboot) OPT_REBOOT=0 ;;
    -h|--help) usage 0 ;;
    *) warn "Option inconnue : $1"; usage 1 ;;
  esac
  shift
done

[[ $EUID -eq 0 ]] || die "Lance ce script en root :  sudo $0 $*   (ou « su - » puis $0 $*)"

# --- Utilisateur de la console ------------------------------------------------
if [[ -z $OPT_USER ]]; then
  if [[ -n ${SUDO_USER:-} && ${SUDO_USER} != root ]]; then
    OPT_USER=$SUDO_USER
  else
    OPT_USER=$(getent passwd 1000 | cut -d: -f1 || true)
  fi
fi
[[ -n $OPT_USER ]] || die "Impossible de deviner l'utilisateur de la console : utilise --user NOM."
getent passwd "$OPT_USER" >/dev/null || die "L'utilisateur « $OPT_USER » n'existe pas."
[[ $OPT_USER != root ]] || die "La console ne doit pas tourner en root : crée un utilisateur normal (--user NOM)."

CONSOLE_USER=$OPT_USER
CONSOLE_UID=$(id -u "$CONSOLE_USER")
CONSOLE_GROUP=$(id -gn "$CONSOLE_USER")
CONSOLE_HOME=$(getent passwd "$CONSOLE_USER" | cut -d: -f6)
CONSOLE_NAME=$OPT_NAME

# --- Clavier (pour sway et le clavier virtuel) --------------------------------
XKB_LAYOUT=fr XKB_VARIANT="" XKB_OPTIONS=""
if [[ -r /etc/default/keyboard ]]; then
  # shellcheck disable=SC1091
  XKB_LAYOUT=$(. /etc/default/keyboard; echo "${XKBLAYOUT:-fr}" | cut -d, -f1)
  XKB_VARIANT=$(. /etc/default/keyboard; echo "${XKBVARIANT:-}" | cut -d, -f1)
  XKB_OPTIONS=$(. /etc/default/keyboard; echo "${XKBOPTIONS:-}")
fi

export CONSOLE_USER CONSOLE_UID CONSOLE_GROUP CONSOLE_HOME CONSOLE_NAME
export XKB_LAYOUT XKB_VARIANT XKB_OPTIONS
export OPT_SMB_PASSWORD OPT_SAMBA OPT_XPADNEO OPT_SLEEP ASSUME_YES
export PREFIX=/opt/console FILES_DIR="$REPO_DIR/files" SHELL_SRC="$REPO_DIR/shell"
export DEBIAN_FRONTEND=noninteractive

# --- Journal ------------------------------------------------------------------
mkdir -p "$(dirname "$CONSOLE_LOG")"
exec > >(tee -a "$CONSOLE_LOG") 2>&1
banner
log "Journal complet : $CONSOLE_LOG"
log "Utilisateur : $CONSOLE_USER (uid $CONSOLE_UID, $CONSOLE_HOME) · clavier : $XKB_LAYOUT${XKB_VARIANT:+/$XKB_VARIANT}"

selected() { # selected "80-shell.sh" -> 0 si l'étape doit tourner
  local num=${1%%-*}
  if [[ -n $OPT_ONLY ]]; then [[ ",$OPT_ONLY," == *",$num,"* ]] || return 1; fi
  if [[ -n $OPT_SKIP ]]; then [[ ",$OPT_SKIP," != *",$num,"* ]] || return 1; fi
  return 0
}

START=$SECONDS
for step in "$REPO_DIR"/steps/[0-9][0-9]-*.sh; do
  name=$(basename "$step")
  selected "$name" || { log "Étape $name ignorée"; continue; }
  run_step "$step"
done

ok "Installation terminée en $(( (SECONDS - START) / 60 )) min $(( (SECONDS - START) % 60 )) s."
if [[ -f /run/console-install/notes ]]; then
  echo; info "À retenir :"; cat /run/console-install/notes; echo
fi
if (( OPT_REBOOT )) && [[ -z $OPT_ONLY ]]; then
  if confirm "Redémarrer maintenant pour démarrer la console ?"; then
    log "Redémarrage…"; sleep 2; systemctl reboot
  else
    log "Redémarre quand tu veux :  sudo systemctl reboot"
  fi
fi
