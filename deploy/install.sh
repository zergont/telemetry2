#!/bin/bash
# Первичная установка cg-decoder на сервере.
# Запускать: sudo bash deploy/install.sh
set -e

APP_DIR=/opt/cg-decoder
APP_USER=folist
REPO=https://github.com/zergont/telemetry2.git
SERVICE=telemetry2

echo "=== Установка cg-decoder ==="

# 1. Зависимости
apt-get install -y python3 python3-pip mosquitto git
pip3 install flask paho-mqtt pyyaml

# 2. Клонирование от имени пользователя
if [ -d "$APP_DIR/.git" ]; then
    echo "Репозиторий уже существует, обновляем..."
    git -C "$APP_DIR" pull
else
    git clone "$REPO" "$APP_DIR"
fi

# 3. Права — всё принадлежит APP_USER
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# 4. Конфиг — если нет, создать из примера
if [ ! -f "$APP_DIR/config.yaml" ]; then
    cp "$APP_DIR/config.example.yaml" "$APP_DIR/config.yaml"
    chown "$APP_USER:$APP_USER" "$APP_DIR/config.yaml"
    echo "Создан config.yaml из примера — отредактируйте перед запуском."
fi

# 5. Systemd service
cp "$APP_DIR/deploy/$SERVICE.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl start "$SERVICE"

echo "=== Готово. Статус: ==="
systemctl status "$SERVICE" --no-pager
