#!/usr/bin/env bash
# 90 — Démarrage silencieux : GRUB caché, écran de démarrage (Plymouth) aux couleurs de la console.
source "$REPO_DIR/lib/common.sh"; step_init

apt_install_available plymouth plymouth-themes librsvg2-bin

# --- Thème Plymouth « console » : logo + animation de chargement ---------------------
theme=/usr/share/plymouth/themes/console
install -d "$theme"
if [[ -d /usr/share/plymouth/themes/spinner ]]; then
  cp -a /usr/share/plymouth/themes/spinner/*.png "$theme/" 2>/dev/null || true
fi
cat > "$theme/logo.svg" <<EOF
<svg xmlns="http://www.w3.org/2000/svg" width="360" height="300" viewBox="0 0 360 300">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#7a4cff"/><stop offset="1" stop-color="#1f4fff"/>
    </linearGradient>
    <filter id="s" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="14"/></filter>
  </defs>
  <rect x="110" y="40" width="140" height="140" rx="40" fill="#5b45ff" opacity=".45" filter="url(#s)"/>
  <rect x="110" y="30" width="140" height="140" rx="40" fill="url(#g)"/>
  <g fill="none" stroke="#fff" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" transform="translate(130 50) scale(4.2)">
    <path d="M7.5 9.5v4M5.5 11.5h4"/><path d="M15.5 10.5h.01M18 12.5h.01"/>
    <path d="M7.2 5.5h9.6a4 4 0 0 1 3.94 3.3l1.04 5.9a2.9 2.9 0 0 1-5.1 2.3L15.3 15.5H8.7l-1.4 1.5a2.9 2.9 0 0 1-5.1-2.3l1.04-5.9A4 4 0 0 1 7.2 5.5z" stroke-width="1.6"/>
  </g>
  <text x="180" y="245" text-anchor="middle" font-family="Inter, Noto Sans, sans-serif" font-size="40" font-weight="700"
        letter-spacing="8" fill="#f3f5fb">$(printf '%s' "$CONSOLE_NAME" | tr '[:lower:]' '[:upper:]' | sed 's/[<>&]//g')</text>
</svg>
EOF
if command -v rsvg-convert >/dev/null; then
  rsvg-convert -w 360 -h 300 "$theme/logo.svg" -o "$theme/watermark.png"
else
  warn "rsvg-convert absent : thème de démarrage sans logo"
fi
cat > "$theme/console.plymouth" <<EOF
[Plymouth Theme]
Name=Console
Description=Écran de démarrage de la console ${CONSOLE_NAME}
ModuleName=two-step

[two-step]
Font=Inter 12
TitleFont=Inter Light 30
ImageDir=${theme}
DialogHorizontalAlignment=.5
DialogVerticalAlignment=.382
TitleHorizontalAlignment=.5
TitleVerticalAlignment=.382
HorizontalAlignment=.5
VerticalAlignment=.78
WatermarkHorizontalAlignment=.5
WatermarkVerticalAlignment=.42
Transition=none
TransitionDuration=0.0
BackgroundStartColor=0x05070d
BackgroundEndColor=0x05070d
ProgressBarBackgroundColor=0x202436
ProgressBarForegroundColor=0xffffff
MessageBelowAnimation=true

[boot-up]
UseEndAnimation=false
UseFirmwareBackground=false

[shutdown]
UseEndAnimation=false
UseFirmwareBackground=false

[reboot]
UseEndAnimation=false
UseFirmwareBackground=false

[updates]
SuppressMessages=true
ProgressBarShowPercentComplete=true
UseProgressBar=true
Title=Mise à jour…
SubTitle=Ne pas éteindre la console
EOF

# Écran de démarrage dès le début (pilote graphique Intel chargé tôt).
grep -qxF i915 /etc/initramfs-tools/modules 2>/dev/null || echo i915 >> /etc/initramfs-tools/modules
if command -v plymouth-set-default-theme >/dev/null; then
  plymouth-set-default-theme console
fi
log "Reconstruction de l'initramfs…"
update-initramfs -u >/dev/null
ok "Écran de démarrage « ${CONSOLE_NAME} » installé"

# --- GRUB : menu caché, démarrage silencieux ---------------------------------------
if command -v update-grub >/dev/null; then
  install -d /etc/default/grub.d
  cat > /etc/default/grub.d/console-ux481.cfg <<'EOF'
# console-ux481 : démarrage direct et silencieux.
# Pour afficher le menu GRUB (dépannage) : maintenir Échap ou Maj au démarrage.
GRUB_TIMEOUT=0
GRUB_TIMEOUT_STYLE=hidden
GRUB_RECORDFAIL_TIMEOUT=3
GRUB_DISABLE_OS_PROBER=true
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash loglevel=3 rd.udev.log_level=3 udev.log_level=3 vt.global_cursor_default=0 systemd.show_status=auto rd.systemd.show_status=auto"
EOF
  update-grub >/dev/null 2>&1 || warn "update-grub a renvoyé une erreur (voir le journal)."
  ok "GRUB : menu caché, démarrage silencieux"
else
  warn "GRUB absent : réglage du démarrage silencieux ignoré."
fi
