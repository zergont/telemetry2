#!/usr/bin/env bash
#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="cg-telemetry"
APP_DIR="/opt/cg-telemetry"

if [[ "${EUID}" -ne 0 ]]; then
  echo "[ОШИБКА] Запустите скрипт с sudo или от root."
  exit 1
fi

if [[ ! -d "${APP_DIR}" ]]; then
  echo "[ОШИБКА] Каталог ${APP_DIR} не найден. Сначала выполните установку."
  exit 1
fi

if [[ ! -d "${APP_DIR}/.git" ]]; then
  echo "[ОШИБКА] ${APP_DIR} не является git-репозиторием."
  exit 1
fi

if [[ ! -x "${APP_DIR}/venv/bin/pip" ]]; then
  echo "[ОШИБКА] Виртуальное окружение не найдено: ${APP_DIR}/venv"
  exit 1
fi

echo "[1/5] Определение текущей ветки..."
BRANCH="$(git -C "${APP_DIR}" rev-parse --abbrev-ref HEAD)"
echo "[INFO] Текущая ветка: ${BRANCH}"

echo "[2/5] Обновление кода из origin/${BRANCH}..."
git -C "${APP_DIR}" fetch origin
PREV_COMMIT="$(git -C "${APP_DIR}" rev-parse --short HEAD)"
git -C "${APP_DIR}" pull --ff-only origin "${BRANCH}"
NEW_COMMIT="$(git -C "${APP_DIR}" rev-parse --short HEAD)"

echo "[3/5] Обновление зависимостей..."
"${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo "[4/5] Перезапуск сервиса ${SERVICE_NAME}..."
systemctl restart "${SERVICE_NAME}"

echo "[5/5] Проверка статуса сервиса..."
systemctl status "${SERVICE_NAME}" --no-pager

echo
echo "[OK] Обновление завершено: ${PREV_COMMIT} -> ${NEW_COMMIT}"
echo "Логи: sudo journalctl -u ${SERVICE_NAME} -f"
