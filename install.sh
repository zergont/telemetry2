#!/usr/bin/env bash
#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="cg-decoder"
APP_DIR="/opt/cg-decoder"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "[ОШИБКА] Запустите скрипт с sudo или от root."
  exit 1
fi

INSTALL_USER="${SUDO_USER:-${USER:-root}}"
if ! id -u "${INSTALL_USER}" >/dev/null 2>&1; then
  echo "[ОШИБКА] Пользователь '${INSTALL_USER}' не найден."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[1/7] Подготовка каталога ${APP_DIR}..."
mkdir -p /opt
mkdir -p "${APP_DIR}"

if [[ "${SCRIPT_DIR}" != "${APP_DIR}" ]]; then
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete --exclude ".venv" --exclude "venv" "${SCRIPT_DIR}/" "${APP_DIR}/"
  else
    cp -a "${SCRIPT_DIR}/." "${APP_DIR}/"
  fi
fi

chown -R "${INSTALL_USER}:${INSTALL_USER}" "${APP_DIR}"

echo "[2/7] Создание виртуального окружения..."
if [[ ! -d "${APP_DIR}/venv" ]]; then
  sudo -u "${INSTALL_USER}" python3 -m venv "${APP_DIR}/venv"
fi

echo "[3/7] Установка зависимостей..."
sudo -u "${INSTALL_USER}" "${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo "[4/7] Подготовка config.yaml..."
if [[ ! -f "${APP_DIR}/config.yaml" ]]; then
  cp "${APP_DIR}/config.example.yaml" "${APP_DIR}/config.yaml"
  chown "${INSTALL_USER}:${INSTALL_USER}" "${APP_DIR}/config.yaml"
  echo "[INFO] Создан ${APP_DIR}/config.yaml. Проверьте настройки MQTT/Web."
fi

echo "[5/7] Создание systemd-сервиса ${SERVICE_NAME}..."
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=CG Telemetry Modbus Decoder
After=network.target

[Service]
Type=simple
User=${INSTALL_USER}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/venv/bin"
ExecStart=${APP_DIR}/venv/bin/python app.py --config ${APP_DIR}/config.yaml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "[6/7] Включение автозапуска и запуск сервиса..."
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"

echo "[7/7] Проверка статуса сервиса..."
systemctl status "${SERVICE_NAME}" --no-pager

echo
echo "[OK] Установка завершена."
echo "Сервис: ${SERVICE_NAME}"
echo "Путь: ${APP_DIR}"
echo "Пользователь: ${INSTALL_USER}"
echo "Логи: sudo journalctl -u ${SERVICE_NAME} -f"
