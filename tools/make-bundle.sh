#!/usr/bin/env bash
# Fabrique un installateur autonome en un seul fichier : dist/console-ux481-installer.sh
# Usage sur la console :  sudo bash console-ux481-installer.sh [options de install.sh]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$ROOT/dist/console-ux481-installer.sh
mkdir -p "$ROOT/dist"
payload=$(mktemp)
tar -C "$(dirname "$ROOT")" --exclude='.git' --exclude='dist' --exclude='__pycache__' \
    -czf "$payload" "$(basename "$ROOT")"
{
  cat <<'HEADER'
#!/usr/bin/env bash
# Console UX481 — installateur autonome (archive intégrée).
# Usage :  sudo bash console-ux481-installer.sh [--name Nova] [--sleep deep|light] [--only 70] ...
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Lance-moi avec sudo : sudo bash $0 $*" >&2; exit 1; }
dest=/var/lib/console-ux481/src
rm -rf "$dest" && mkdir -p "$dest"
sed '1,/^__ARCHIVE__$/d' "$0" | base64 -d | tar -xz -C "$dest"
exec bash "$dest/console-ux481/install.sh" "$@"
__ARCHIVE__
HEADER
  base64 -w 76 "$payload"
} > "$OUT"
rm -f "$payload"
chmod +x "$OUT"
echo "$OUT ($(du -h "$OUT" | cut -f1))"
