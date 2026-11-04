# shellcheck shell=bash
# lib/common.sh — fonctions partagées par install.sh et steps/*.sh

: "${CONSOLE_LOG:=/var/log/console-install.log}"

if [[ -t 1 || -n ${FORCE_COLOR:-} ]]; then
  C_RESET=$'\e[0m' C_BOLD=$'\e[1m' C_DIM=$'\e[2m' C_RED=$'\e[31m'
  C_GREEN=$'\e[32m' C_YELLOW=$'\e[33m' C_BLUE=$'\e[34m' C_MAGENTA=$'\e[35m'
else
  C_RESET='' C_BOLD='' C_DIM='' C_RED='' C_GREEN='' C_YELLOW='' C_BLUE='' C_MAGENTA=''
fi

log()  { printf '%s %s\n' "${C_DIM}[$(date +%H:%M:%S)]${C_RESET}" "$*"; }
info() { printf '\n%s %s\n' "${C_BLUE}==>${C_RESET}" "${C_BOLD}$*${C_RESET}"; }
ok()   { printf '%s %s\n' "${C_GREEN}  ✓${C_RESET}" "$*"; }
warn() { printf '%s %s\n' "${C_YELLOW}  !${C_RESET}" "$*" >&2; }
die()  { printf '%s %s\n' "${C_RED}  ✗${C_RESET}" "${C_RED}$*${C_RESET}" >&2; exit 1; }

banner() {
  printf '%s\n' "${C_MAGENTA}${C_BOLD}"
  cat <<'EOF'
   ┌───────────────────────────────────────────────┐
   │   Console UX481 — installation                │
   │   Debian 13  →  console de salon à la manette │
   └───────────────────────────────────────────────┘
EOF
  printf '%s' "${C_RESET}"
}

# Note affichée en fin d'installation (ex : actions manuelles à faire).
note() { mkdir -p /run/console-install; printf ' • %s\n' "$*" >> /run/console-install/notes; }

confirm() { # confirm "Question ?" -> 0 si oui
  if [[ ${ASSUME_YES:-0} == 1 ]]; then return 0; fi
  if [[ ! -t 0 ]]; then return 1; fi
  local reply
  read -r -p "$(printf '%s ' "${C_YELLOW}?${C_RESET} $1 [O/n]")" reply || return 1
  [[ -z $reply || $reply =~ ^[OoYy] ]]
}

run_step() { # run_step /chemin/NN-nom.sh
  local step=$1 name
  name=$(basename "$step" .sh)
  info "Étape ${name}"
  if ! bash "$step"; then
    die "L'étape ${name} a échoué. Détails : ${CONSOLE_LOG}. Corrige le problème puis relance la même commande (ex. sudo ./install.sh) : les étapes déjà faites passent vite."
  fi
}

# Trace l'erreur exacte dans les étapes (set -E + trap ERR).
step_init() {
  set -Eeuo pipefail
  trap 'warn "Erreur ligne $LINENO : $BASH_COMMAND"' ERR
}

# ---------------------------------------------------------------- APT --------
apt_q() { apt-get -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold "$@"; }

apt_update() {
  local i
  for i in 1 2 3; do apt_q -q update && return 0; warn "apt update a échoué (essai $i/3)"; sleep $((i * 3)); done
  return 1
}

apt_install() { # paquets obligatoires
  local i
  for i in 1 2 3; do
    apt_q -y -q install --no-install-recommends "$@" && return 0
    warn "apt install a échoué (essai $i/3), nouvelle tentative…"; sleep $((i * 4)); apt_update || true
  done
  return 1
}

pkg_available() { # pkg_available NOM -> 0 si installable
  local cand
  cand=$(apt-cache policy "$1" 2>/dev/null | awk '/Candidate:/ {print $2; exit}')
  [[ -n $cand && $cand != "(none)" ]]
}

apt_install_available() { # installe ce qui existe, signale le reste
  local p want=() missing=()
  for p in "$@"; do
    if pkg_available "$p"; then want+=("$p"); else missing+=("$p"); fi
  done
  ((${#missing[@]})) && warn "Paquets indisponibles ignorés : ${missing[*]}"
  ((${#want[@]})) && apt_install "${want[@]}"
  return 0
}

pkg_installed() { dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'install ok installed'; }

# ------------------------------------------------------------- Fichiers -----
backup_once() { # sauvegarde un fichier système avant la 1re modification
  [[ -e $1 && ! -e $1.console-orig ]] && cp -a "$1" "$1.console-orig"
  return 0
}

# render SRC DEST [MODE] — copie un modèle en remplaçant les @@VARIABLES@@.
render() {
  local src=$1 dest=$2 mode=${3:-0644} content var
  content=$(<"$src")
  for var in CONSOLE_USER CONSOLE_UID CONSOLE_GROUP CONSOLE_HOME CONSOLE_NAME \
             XKB_LAYOUT XKB_VARIANT XKB_OPTIONS PREFIX; do
    content=${content//@@${var}@@/${!var-}}
  done
  install -d "$(dirname "$dest")"
  printf '%s\n' "$content" > "$dest.console-tmp"
  chmod "$mode" "$dest.console-tmp"
  mv -f "$dest.console-tmp" "$dest"
}

put() { # put SRC DEST [MODE] — copie simple
  install -D -m "${3:-0644}" "$1" "$2"
}

# ini_set FICHIER SECTION CLE VALEUR — modifie un .ini/.conf en préservant le reste.
ini_set() { python3 "$REPO_DIR/lib/iniset.py" "$@"; }

# Exécute une commande en tant qu'utilisateur de la console.
as_user() {
  runuser -u "$CONSOLE_USER" -- env HOME="$CONSOLE_HOME" USER="$CONSOLE_USER" \
    LOGNAME="$CONSOLE_USER" XDG_RUNTIME_DIR="/run/user/$CONSOLE_UID" \
    XDG_CONFIG_HOME="$CONSOLE_HOME/.config" XDG_DATA_HOME="$CONSOLE_HOME/.local/share" \
    XDG_CACHE_HOME="$CONSOLE_HOME/.cache" XDG_STATE_HOME="$CONSOLE_HOME/.local/state" \
    PATH=/usr/local/bin:/usr/bin:/bin "$@"
}

user_install_dir() { install -d -o "$CONSOLE_USER" -g "$CONSOLE_GROUP" -m "${2:-0755}" "$1"; }

# Écrit stdin dans un fichier appartenant à l'utilisateur (crée les dossiers).
user_write() { # user_write DEST [MODE] < contenu
  local dest=$1 mode=${2:-0644} dir
  dir=$(dirname "$dest")
  as_user mkdir -p "$dir"
  cat > "$dest.console-tmp"
  chown "$CONSOLE_USER:$CONSOLE_GROUP" "$dest.console-tmp"
  chmod "$mode" "$dest.console-tmp"
  mv -f "$dest.console-tmp" "$dest"
}

download() { # download URL DEST
  curl -fL --retry 4 --retry-delay 3 --connect-timeout 20 -o "$2.part" "$1" && mv -f "$2.part" "$2"
}

# ---------------------------------------------------------------- systemd ---
enable_now() { systemctl enable --now "$@" >/dev/null 2>&1 || systemctl enable "$@"; }
user_unit_enable() { systemctl --global enable "$@"; }

has_nvidia_gpu() { lspci -n 2>/dev/null | awk '{print $2, $3}' | grep -Eq '^03[0-9]{2}: 10de:'; }
secure_boot_enabled() { # 0 si le Secure Boot de l'UEFI est actif
  local v
  for v in /sys/firmware/efi/efivars/SecureBoot-*; do
    [[ -e $v ]] || continue
    [[ $(od -An -t u1 "$v" 2>/dev/null | awk '{print $NF}') == 1 ]] && return 0
  done
  return 1
}
