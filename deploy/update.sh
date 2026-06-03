#!/bin/bash
# Обновление cg-decoder на сервере.
# Запускать: sudo bash deploy/update.sh
set -e

APP_DIR=/opt/cg-decoder
APP_USER=folist
SERVICE=telemetry2

echo "=== Обновление cg-decoder ==="

git -C "$APP_DIR" pull

# Права на новые файлы после pull
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

systemctl restart "$SERVICE"

echo "=== Готово. Версия: ==="
grep __version__ "$APP_DIR/version.py"
