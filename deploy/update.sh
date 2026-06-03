#!/bin/bash
# Обновление cg-decoder.
# Использование: sudo bash deploy/update.sh [пользователь] [директория]
set -e

APP_USER="${1:-${SUDO_USER:-$(logname 2>/dev/null || whoami)}}"
APP_DIR="${2:-/opt/cg-decoder}"
SERVICE=telemetry2

echo "=== Обновление cg-decoder ==="
echo "    Пользователь : $APP_USER"
echo "    Директория   : $APP_DIR"

git -C "$APP_DIR" pull

# Права на новые файлы после pull
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

systemctl restart "$SERVICE"

echo ""
echo "=== Готово. Версия: ==="
grep __version__ "$APP_DIR/version.py"
