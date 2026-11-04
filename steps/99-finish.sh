#!/usr/bin/env bash
# 99 — Finalisation : reprise du réseau par NetworkManager, récapitulatif.
source "$REPO_DIR/lib/common.sh"; step_init

# --- Connexions créées par l'installateur Debian (ifupdown) → NetworkManager ----------
# Le réseau actuel reste actif jusqu'au redémarrage ; ensuite NetworkManager prend le relais
# (et le Wi-Fi devient réglable à la manette).
migrate_ifupdown() {
  local file=$1 ssid="" psk="" line
  [[ -f $file ]] || return 0
  while IFS= read -r line || [[ -n $line ]]; do
    if [[ $line =~ ^[[:space:]]*wpa-ssid[[:space:]]+(.+)$ ]]; then ssid=${BASH_REMATCH[1]}; ssid=${ssid%\"}; ssid=${ssid#\"}; fi
    if [[ $line =~ ^[[:space:]]*wpa-psk[[:space:]]+(.+)$ ]]; then psk=${BASH_REMATCH[1]}; psk=${psk%\"}; psk=${psk#\"}; fi
  done < "$file"
  if [[ -n $ssid ]] && ! nmcli -t -f NAME connection show 2>/dev/null | grep -qxF "$ssid"; then
    if [[ -n $psk ]]; then
      nmcli connection add type wifi ifname '*' con-name "$ssid" ssid "$ssid" \
        wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$psk" connection.autoconnect yes >/dev/null
    else
      nmcli connection add type wifi ifname '*' con-name "$ssid" ssid "$ssid" connection.autoconnect yes >/dev/null
    fi
    ok "Wi-Fi « $ssid » repris par NetworkManager"
  fi
  # Toutes les interfaces sauf « lo » passent à NetworkManager.
  if grep -Eq '^[[:space:]]*(auto|allow-hotplug|iface)[[:space:]]+[^l]' "$file"; then
    backup_once "$file"
    python3 - "$file" <<'PY'
import re, sys
path = sys.argv[1]
out, skip = [], False
for line in open(path, encoding="utf-8").read().splitlines():
    s = line.strip()
    m = re.match(r"^(auto|allow-hotplug|iface|mapping)\s+(\S+)", s)
    if m:
        skip = m.group(2) not in ("lo",) and not m.group(2).startswith("lo ")
    elif s and not line[:1].isspace() and not s.startswith("#"):
        skip = False
    out.append(("# (console-ux481 → NetworkManager) " + line) if skip and s and not s.startswith("#") else line)
open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
PY
  fi
  return 0
}
if command -v nmcli >/dev/null; then
  migrate_ifupdown /etc/network/interfaces
  for f in /etc/network/interfaces.d/*; do [[ -f $f ]] && migrate_ifupdown "$f"; done
  ini_set /etc/NetworkManager/NetworkManager.conf ifupdown managed false
fi

# --- Version installée ---------------------------------------------------------------
install -d /etc/console
date '+%Y-%m-%d %H:%M' > /etc/console/installed
git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null > /etc/console/version || echo "1.0" > /etc/console/version

host=$(hostname)
note "Au prochain démarrage : la console s'ouvre sur l'accueil, sur la TV (HDMI). Un assistant te guide (manette, réseau, test de veille)."
note "Associer la manette Xbox : allume-la, puis maintiens 3 s le bouton d'appairage (sur le dessus) quand l'assistant le demande."
note "Jeux et BIOS : depuis un PC, \\\\${host}\\Jeux et \\\\${host}\\BIOS (ou smb://${host}.local/…). Dossiers : gba nds n3ds gc wii psx ps2."
note "Moonlight : installe Sunshine (ou Apollo) sur ton PC, ouvre la tuile Moonlight et saisis le code PIN dans l'interface web de Sunshine."
note "Dépannage : Ctrl+Alt+Entrée ouvre un terminal sur la console ; journaux : journalctl --user -u console-shell."
ok "Installation finalisée"
