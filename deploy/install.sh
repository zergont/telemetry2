#!/bin/bash
# Первичная установка cg-decoder.
# Использование: sudo bash deploy/install.sh [пользователь] [директория]
#   пользователь — по умолчанию тот, кто запустил sudo ($SUDO_USER)
#   директория   — по умолчанию /opt/cg-decoder
set -e

APP_USER="${1:-${SUDO_USER:-$(logname 2>/dev/null || whoami)}}"
APP_DIR="${2:-/opt/cg-decoder}"
REPO=https://github.com/zergont/telemetry2.git
SERVICE=telemetry2

echo "=== Установка cg-decoder ==="
echo "    Пользователь : $APP_USER"
echo "    Директория   : $APP_DIR"
echo ""

# 1. Зависимости
apt-get install -y python3 python3-pip mosquitto git
pip3 install flask paho-mqtt pyyaml

# 2. Клонирование
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

# 5. Генерируем service-файл из шаблона
sed -e "s|{{APP_USER}}|$APP_USER|g" \
    -e "s|{{APP_DIR}}|$APP_DIR|g" \
    "$APP_DIR/deploy/$SERVICE.service.template" \
    > "/etc/systemd/system/$SERVICE.service"

echo "Установлен /etc/systemd/system/$SERVICE.service"

# 6. Запуск
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl start "$SERVICE"

echo ""
echo "=== Готово ==="
systemctl status "$SERVICE" --no-pager
