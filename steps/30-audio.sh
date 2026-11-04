#!/usr/bin/env bash
# 30 — Audio : PipeWire + WirePlumber, sortie HDMI privilégiée (le shell choisit la sortie).
source "$REPO_DIR/lib/common.sh"; step_init

# Si PulseAudio est présent (installation avec bureau), PipeWire le remplace.
if pkg_installed pulseaudio; then
  apt_q -y -q purge pulseaudio pulseaudio-module-bluetooth || true
fi
apt_install_available pipewire pipewire-audio pipewire-pulse pipewire-alsa wireplumber \
  pulseaudio-utils alsa-utils alsa-ucm-conf rtkit

# Les sorties HDMI ne se mettent jamais en veille : sinon le téléviseur coupe
# le début de chaque son (bruitages de l'interface, début des vidéos).
install -d /etc/wireplumber/wireplumber.conf.d
cat > /etc/wireplumber/wireplumber.conf.d/50-console.conf <<'EOF'
# console-ux481
monitor.alsa.rules = [
  {
    matches = [ { node.name = "~alsa_output.*" } ]
    actions = { update-props = { session.suspend-timeout-seconds = 0 } }
  }
]
EOF
systemctl --global enable pipewire.socket pipewire-pulse.socket wireplumber.service >/dev/null 2>&1 || true
ok "PipeWire configuré (sortie HDMI choisie automatiquement par la console)"
