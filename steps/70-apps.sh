#!/usr/bin/env bash
# 70 — Applications : Moonlight + émulateurs (Flatpak), cœurs RetroArch, ES-DE, Brave.
source "$REPO_DIR/lib/common.sh"; step_init

FLATPAKS=(
  com.moonlight_stream.Moonlight   # streaming depuis le PC (Sunshine/GeForce)
  org.libretro.RetroArch           # GBA, DS, PS1 (cœurs mGBA, melonDS DS, Beetle PSX HW)
  org.DolphinEmu.dolphin-emu       # GameCube, Wii
  net.pcsx2.PCSX2                  # PlayStation 2
  org.azahar_emu.Azahar            # Nintendo 3DS
)

# --- Flatpak + Flathub --------------------------------------------------------
apt_install flatpak
flatpak remote-add --system --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
log "Installation des applications Flatpak (plusieurs Go, patience)…"
for app in "${FLATPAKS[@]}"; do
  for i in 1 2 3; do
    if flatpak install --system -y --noninteractive --or-update flathub "$app" >/dev/null; then
      ok "$app"; break
    fi
    warn "$app : échec (essai $i/3)"; sleep $((i * 5))
    [[ $i == 3 ]] && die "Impossible d'installer $app depuis Flathub."
  done
done

# Accès aux dossiers de jeux et de BIOS (PCSX2 n'a aucun accès par défaut).
# (le « ~ » est interprété par Flatpak : dossier personnel de l'utilisateur qui lance l'appli)
for app in org.libretro.RetroArch org.DolphinEmu.dolphin-emu net.pcsx2.PCSX2 org.azahar_emu.Azahar; do
  # shellcheck disable=SC2088
  flatpak override --system "$app" '--filesystem=~/ROMs:ro' '--filesystem=~/BIOS'
done
ok "Accès des émulateurs à ~/ROMs et ~/BIOS"

# --- Cœurs RetroArch (le Flatpak n'en contient aucun) ---------------------------
cores_dir="$CONSOLE_HOME/.var/app/org.libretro.RetroArch/config/retroarch/cores"
as_user mkdir -p "$cores_dir"
tmp=$(mktemp -d)
for core in mgba melondsds mednafen_psx_hw swanstation; do
  url="https://buildbot.libretro.com/nightly/linux/x86_64/latest/${core}_libretro.so.zip"
  if download "$url" "$tmp/$core.zip" && unzip -o -q "$tmp/$core.zip" -d "$tmp"; then
    install -o "$CONSOLE_USER" -g "$CONSOLE_GROUP" -m 0644 "$tmp/${core}_libretro.so" "$cores_dir/"
    ok "cœur RetroArch : $core"
  else
    warn "cœur $core non téléchargé (tu pourras l'installer depuis RetroArch › Mise à jour en ligne)"
  fi
done
rm -rf "$tmp"

# --- ES-DE (bibliothèque d'émulation) : AppImage extraite dans /opt/es-de -----
esde_json=$(curl -fsSL --retry 3 https://gitlab.com/es-de/emulationstation-de/-/raw/master/latest_release.json || true)
esde_url=$(jq -r '.stable.packages[] | select(.name=="LinuxAppImage") | .url' <<<"$esde_json" 2>/dev/null || true)
esde_md5=$(jq -r '.stable.packages[] | select(.name=="LinuxAppImage") | .md5' <<<"$esde_json" 2>/dev/null || true)
esde_ver=$(jq -r '.stable.version' <<<"$esde_json" 2>/dev/null || true)
installed_ver=$(cat /opt/es-de/.console-version 2>/dev/null || true)
if [[ -n $esde_url && $esde_ver == "$installed_ver" && -x /opt/es-de/AppRun ]]; then
  ok "ES-DE $esde_ver déjà installé"
elif [[ -n $esde_url ]]; then
  tmp=$(mktemp -d)
  log "Téléchargement d'ES-DE $esde_ver…"
  if download "$esde_url" "$tmp/ES-DE.AppImage"; then
    if [[ -n $esde_md5 && $(md5sum "$tmp/ES-DE.AppImage" | cut -d' ' -f1) != "$esde_md5" ]]; then
      die "ES-DE : somme de contrôle invalide (téléchargement corrompu). Relance l'étape 70."
    fi
    chmod +x "$tmp/ES-DE.AppImage"
    (cd "$tmp" && ./ES-DE.AppImage --appimage-extract >/dev/null)
    # Selon l'AppImage, l'extraction donne squashfs-root/, AppDir/, ou squashfs-root -> AppDir (lien
    # relatif, depuis ES-DE 3.5.0) : on déplace le vrai dossier, sinon le lien pointerait dans le vide.
    extracted=""
    for d in "$tmp/squashfs-root" "$tmp/AppDir"; do
      if [[ -e $d/AppRun ]]; then extracted=$(readlink -f "$d"); break; fi
    done
    [[ -n $extracted ]] || die "ES-DE : contenu de l'AppImage inattendu (pas d'AppRun). Relance l'étape 70."
    rm -rf /opt/es-de.new && mv "$extracted" /opt/es-de.new
    chmod -R a+rX /opt/es-de.new
    rm -rf /opt/es-de && mv /opt/es-de.new /opt/es-de
    echo "$esde_ver" > /opt/es-de/.console-version
    ok "ES-DE $esde_ver installé dans /opt/es-de"
  else
    warn "Téléchargement d'ES-DE impossible : la tuile Jeux ne fonctionnera pas avant une nouvelle tentative (sudo ./install.sh --only 70)."
    note "ES-DE n'a pas pu être téléchargé : relance « sudo ./install.sh --only 70 »."
  fi
  rm -rf "$tmp"
else
  warn "Version d'ES-DE introuvable (gitlab.com injoignable ?)."
  note "ES-DE n'a pas pu être installé : relance « sudo ./install.sh --only 70 »."
fi
install -d "$PREFIX/share/icons"
esde_icon=$(find /opt/es-de -maxdepth 6 \( -name 'org.es_de.frontend.svg' -o -name 'es-de.svg' \) 2>/dev/null | head -n1 || true)
[[ -n $esde_icon ]] && cp -f "$esde_icon" "$PREFIX/share/icons/es-de.svg"

# --- Brave ----------------------------------------------------------------------
if ! pkg_installed brave-browser; then
  download https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg \
    /usr/share/keyrings/brave-browser-archive-keyring.gpg
  chmod 0644 /usr/share/keyrings/brave-browser-archive-keyring.gpg
  rm -f /etc/apt/sources.list.d/brave-browser-*.list
  if ! download https://brave-browser-apt-release.s3.brave.com/brave-browser.sources \
         /etc/apt/sources.list.d/brave-browser-release.sources; then
    cat > /etc/apt/sources.list.d/brave-browser-release.sources <<'EOF'
Types: deb
URIs: https://brave-browser-apt-release.s3.brave.com
Suites: stable
Components: main
Architectures: amd64 arm64
Signed-By: /usr/share/keyrings/brave-browser-archive-keyring.gpg
EOF
  fi
  apt_update
  apt_install brave-browser
fi
install -d /etc/brave/policies/managed
cat > /etc/brave/policies/managed/console-ux481.json <<'EOF'
{
  "BraveRewardsDisabled": true,
  "BraveWalletDisabled": true,
  "BraveVPNDisabled": true,
  "BraveAIChatEnabled": false,
  "BraveNewsDisabled": true,
  "BraveTalkDisabled": true,
  "BravePlaylistEnabled": false,
  "BraveP3AEnabled": false,
  "BraveStatsPingEnabled": false,
  "BraveWebDiscoveryEnabled": false,
  "TorDisabled": true,
  "DefaultBrowserSettingEnabled": false,
  "MetricsReportingEnabled": false,
  "PromotionalTabsEnabled": false,
  "BackgroundModeEnabled": false,
  "RestoreOnStartup": 1,
  "HardwareAccelerationModeEnabled": true
}
EOF
ok "Brave installé (version épurée pour la TV)"

# --- Extras : HDMI-CEC (adaptateur Pulse-Eight), base de manettes SDL --------------
apt_install_available cec-utils
download https://raw.githubusercontent.com/mdqinc/SDL_GameControllerDB/master/gamecontrollerdb.txt \
  "$PREFIX/share/gamecontrollerdb.txt" || warn "Base de manettes SDL non téléchargée (facultatif)."
ok "Applications installées"
