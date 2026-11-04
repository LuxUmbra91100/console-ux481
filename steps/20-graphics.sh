#!/usr/bin/env bash
# 20 — GPU Intel (Vulkan, décodage vidéo matériel), MX250 éteinte, ScreenPad éteint.
source "$REPO_DIR/lib/common.sh"; step_init

apt_install_available \
  mesa-vulkan-drivers mesa-va-drivers libgl1-mesa-dri intel-media-va-driver-non-free \
  va-driver-all vainfo vulkan-tools

# --- GeForce MX250 : choix « Intel uniquement » -------------------------------
# On empêche nouveau de se charger (pas de second GPU visible par Vulkan/sway) et
# on laisse le noyau couper l'alimentation de la puce via la gestion d'énergie PCI.
if has_nvidia_gpu; then
  cat > /etc/modprobe.d/console-nvidia-off.conf <<'EOF'
# console-ux481 : MX250 inutilisée (choix « Intel uniquement »)
blacklist nouveau
options nouveau modeset=0
EOF
  cat > /etc/udev/rules.d/80-console-dgpu-pm.rules <<'EOF'
# console-ux481 : laisse le GPU NVIDIA inutilisé passer en D3cold (alimentation coupée)
ACTION=="add|bind", SUBSYSTEM=="pci", ATTR{vendor}=="0x10de", ATTR{class}=="0x03*", TEST=="power/control", ATTR{power/control}="auto"
ACTION=="add|bind", SUBSYSTEM=="pci", ATTR{vendor}=="0x10de", ATTR{class}=="0x04*", TEST=="power/control", ATTR{power/control}="auto"
ACTION=="add|bind", SUBSYSTEM=="pci", ATTR{vendor}=="0x10de", ATTR{class}=="0x0c*", TEST=="power/control", ATTR{power/control}="auto"
EOF
  touch /run/console-install/need-initramfs
  ok "GeForce détectée : désactivée (Intel uniquement, alimentation coupée)"
else
  rm -f /etc/modprobe.d/console-nvidia-off.conf /etc/udev/rules.d/80-console-dgpu-pm.rules
  ok "Pas de GPU NVIDIA : rien à faire"
fi

# --- ScreenPad Plus : rétroéclairage coupé au démarrage -----------------------
# (le compositeur désactive aussi la sortie vidéo ; voir console-hw.service)
ok "Pilotes graphiques Intel installés (VA-API iHD + Vulkan ANV)"
