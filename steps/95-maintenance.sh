#!/usr/bin/env bash
# 95 — Mises à jour automatiques et discrètes (sécurité Debian, Brave, Flatpaks).
source "$REPO_DIR/lib/common.sh"; step_init

apt_install_available unattended-upgrades apt-listchanges
cat > /etc/apt/apt.conf.d/52console-unattended <<'EOF'
// console-ux481 : sécurité Debian + Brave, installés en arrière-plan
Unattended-Upgrade::Origins-Pattern {
        "origin=Debian,codename=${distro_codename},label=Debian-Security";
        "origin=Debian,codename=${distro_codename}-security,label=Debian-Security";
        "origin=Debian,codename=${distro_codename}-updates";
        "origin=Brave Software";
};
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
EOF
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

# Flatpaks (Moonlight, émulateurs) : tous les 3 jours d'utilisation, en basse priorité.
cat > /etc/systemd/system/console-flatpak-update.service <<'EOF'
[Unit]
Description=Console — mise à jour des applications Flatpak
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
Nice=19
IOSchedulingClass=idle
CPUQuota=60%
ExecStart=/usr/bin/flatpak update --system -y --noninteractive
ExecStart=/usr/bin/flatpak uninstall --system -y --noninteractive --unused
EOF
cat > /etc/systemd/system/console-flatpak-update.timer <<'EOF'
[Unit]
Description=Console — mise à jour périodique des Flatpaks

[Timer]
OnBootSec=20min
OnUnitActiveSec=3d
RandomizedDelaySec=30min

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable console-flatpak-update.timer >/dev/null
systemctl enable fstrim.timer >/dev/null 2>&1 || true

# Journal système limité (petit disque, pas d'écritures inutiles).
install -d /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/50-console.conf <<'EOF'
[Journal]
SystemMaxUse=200M
EOF
ok "Mises à jour automatiques : sécurité, Brave, Flatpaks"
