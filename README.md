# Универсальный Modbus-декодер и Web UI

Серверное приложение, которое:
- Принимает raw Modbus-телеметрию через MQTT
- Декодирует данные по внешним картам регистров (без хардкода)
- Публикует decoded-данные в отдельный MQTT-топик
- Отображает данные через простой Web UI
- Работает in-memory (без БД)

Ориентировано на Cummins PCC, но архитектура универсальна.

## Возможности

- **Динамическое обнаружение панелей** — панели определяются автоматически из входящих сообщений
- **Пакетная обработка** — поддержка одиночных и батчевых payload (массив пакетов в одном сообщении)
- **GPS** — отображение координат, скорости, спутников роутера
- **Мониторинг состояния** — панели помечаются как `stale` (>30с) или `offline` (>120с)
- **Автопереподключение MQTT** — автоматическое восстановление соединения
- **Внешние карты регистров** — вся логика декодирования из JSONL/JSON файлов
- **Web UI** — просмотр роутеров, панелей и декодированных регистров
- **Очистка in-memory** — кнопка в Web UI для сброса данных из памяти
- **Режим отладки** — подробное логирование для диагностики

## Требования

- Python 3.10+
- MQTT-брокер (например Mosquitto)

## Установка на Ubuntu

Рекомендуемый способ — установочный скрипт `install.sh`.

### 1. Клонировать репозиторий в `/opt/cg-telemetry`

```bash
sudo mkdir -p /opt
cd /opt
sudo git clone https://github.com/zergont/telemetry2.git cg-telemetry
sudo chown -R $USER:$USER /opt/cg-telemetry
cd /opt/cg-telemetry
```

### 2. Запустить установочный скрипт

```bash
chmod +x install.sh
sudo ./install.sh
```

> В прод-сценарии рабочий каталог приложения — `/opt/cg-telemetry`.

Скрипт автоматически:
- устанавливает приложение в `/opt/cg-telemetry`
- создаёт `venv` и ставит зависимости
- создаёт `config.yaml` из `config.example.yaml` (если отсутствует)
- создаёт `systemd`-службу `cg-telemetry`
- включает службу в автозапуск и запускает её (`enable --now`)
- показывает статус службы в конце установки

### 3. Проверить и отредактировать конфиг

```bash
sudo nano /opt/cg-telemetry/config.yaml
```

Основные параметры:

- `mqtt.host` — адрес MQTT-брокера
- `mqtt.port` — порт (по умолчанию: 1883)
- `mqtt.username` и `mqtt.password` — если требуется авторизация
- `web.port` — порт Web UI (по умолчанию: 8080)
- `mode` — `debug` для подробного логирования

### 4. Перезапустить после изменения конфига

```bash
sudo systemctl restart cg-telemetry
```

### 5. Проверка статуса службы

```bash
sudo systemctl status cg-telemetry
sudo systemctl is-enabled cg-telemetry
```

### Ручная установка (если без скрипта)

### 1. Установить приложение в `/opt/cg-telemetry`

```bash
sudo mkdir -p /opt
cd /opt
sudo git clone https://github.com/zergont/telemetry2.git cg-telemetry
sudo chown -R $USER:$USER /opt/cg-telemetry
cd /opt/cg-telemetry
```

### 2. Создать виртуальное окружение

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Установить зависимости

```bash
pip install -r requirements.txt
```

### 4. Настроить конфигурацию

```bash
cp config.example.yaml config.yaml
nano config.yaml
```

### 5. Настроить службу `systemd` (ниже) и запустить

## Автозапуск при перезагрузке (systemd)

### Создать файл сервиса

```bash
sudo nano /etc/systemd/system/cg-telemetry.service
```

Содержимое:

```ini
[Unit]
Description=CG Telemetry Modbus Decoder
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/opt/cg-telemetry
Environment="PATH=/opt/cg-telemetry/venv/bin"
ExecStart=/opt/cg-telemetry/venv/bin/python app.py --config /opt/cg-telemetry/config.yaml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

> Замените `youruser` на имя пользователя, под которым запускается сервис.

### Активировать и запустить

```bash
sudo systemctl daemon-reload
sudo systemctl enable cg-telemetry
sudo systemctl start cg-telemetry
```

### Полезные команды

```bash
# Статус сервиса
sudo systemctl status cg-telemetry

# Логи в реальном времени
sudo journalctl -u cg-telemetry -f

# Перезапустить после изменений
sudo systemctl restart cg-telemetry

# Отключить автозапуск
sudo systemctl disable cg-telemetry
```

После `systemctl enable` сервис будет **автоматически запускаться при каждой перезагрузке** системы.

## Обновление на сервере через Git

Рекомендуемый способ — скрипт `update.sh`.

```bash
cd /opt/cg-telemetry
chmod +x update.sh
sudo ./update.sh
```

Скрипт автоматически:
- подтягивает код из текущей git-ветки (`pull --ff-only`)
- обновляет зависимости (`pip install -r requirements.txt`)
- перезапускает службу `cg-telemetry`
- показывает статус службы

### Ручное обновление (если без скрипта)

Если проект уже установлен как `systemd`-сервис:

```bash
# 1) Перейти в каталог проекта
cd /opt/cg-telemetry

# 2) Подтянуть изменения из репозитория
git pull origin master

# 3) Обновить зависимости (на случай изменений в requirements.txt)
source venv/bin/activate
pip install -r requirements.txt

# 4) Перезапустить сервис
sudo systemctl restart cg-telemetry

# 5) Проверить статус и логи
sudo systemctl status cg-telemetry
sudo journalctl -u cg-telemetry -f
```

Если у вас основная ветка называется `main`, используйте:

```bash
git pull origin main
```

## Удаление с сервера

Полное удаление `cg-telemetry`:

```bash
sudo systemctl stop cg-telemetry
sudo systemctl disable cg-telemetry
sudo rm -f /etc/systemd/system/cg-telemetry.service
sudo systemctl daemon-reload
sudo systemctl reset-failed

sudo rm -rf /opt/cg-telemetry
```

Удаление старого сервиса `telemetry2` (если остался):

```bash
sudo systemctl stop telemetry2 2>/dev/null || true
sudo systemctl disable telemetry2 2>/dev/null || true
sudo rm -f /etc/systemd/system/telemetry2.service
sudo systemctl daemon-reload
sudo systemctl reset-failed

sudo rm -rf /opt/telemetry2
```

## MQTT-топики

### RAW (вход)

```
cg/v1/telemetry/SN/<router_sn>
```

Формат payload (одиночный пакет):
```json
{
  "PCC_3_3": {
    "date_iso_8601": "2026-01-27T21:59:49+0300",
    "server_id": 1,
    "addr": 6109,
    "data": "[0]"
  }
}
```

Формат payload (батч — несколько пакетов):
```json
{
  "PCC_3_3": [
    {"date_iso_8601": "2026-02-17T14:23:10+0300", "server_id": 1, "addr": 290, "data": "[65,53267]"},
    {"date_iso_8601": "2026-02-17T14:23:10+0300", "server_id": 2, "addr": 290, "data": "[352,35616]"}
  ]
}
```

GPS-сообщение:
```json
{
  "GPS": {
    "latitude": 59.851780,
    "longitude": 30.480843,
    "altitude": 23.2,
    "speed": 10.37,
    "satellites": 4,
    "date_iso_8601": "2026-02-16T20:54:47+0300"
  }
}
```

### DECODED (выход)

```
cg/v1/decoded/SN/<router_sn>/pcc/<server_id>
```

Формат payload:
```json
{
  "timestamp": "2026-01-27T21:59:49+0300",
  "router_sn": "6003790403",
  "bserver_id": 1,
  "registers": [
    {
      "addr": 46109,
      "name": "Engine Operating State",
      "value": 4,
      "text": "Running",
      "unit": null,
      "raw": 4
    }
  ]
}
```

> **Правило декодирования:** если регистр не удалось декодировать → `value = null`, `raw = <число>`.

## Карты регистров

Вся логика декодирования во внешних файлах (хардкод регистров запрещён):

| Файл | Формат | Описание |
|------|--------|----------|
| `maps/register_map.jsonl` | JSONL | Определения регистров (адрес, тип, множитель и т.д.) |
| `maps/enum_map.json` | JSON | Маппинг enum: значение → текст |
| `maps/fault_bitmap_map.jsonl` | JSONL | Определения битов fault bitmap |

### Декодирование адреса

Из `full_addr` (строка) или `addr` (число):
- Строка `"406109"`: первый символ — тип области (`4` = holding, `3` = input), последние 5 цифр — смещение
- Число `6109`: смещение напрямую, тип holding по умолчанию
- Итоговый адрес = 40000 + смещение

Примеры:
- `"406109"` → смещение `06109` → адрес `46109`
- `addr: 6109` → адрес `46109`
- `"403560"` → смещение `03560` → адрес `43560`

### Типы данных

| Тип | Описание | Слов |
|-----|----------|------|
| `u16` | Беззнаковое 16-бит | 1 |
| `s16` | Знаковое 16-бит | 1 |
| `u32` | Беззнаковое 32-бит (big-endian) | 2 |
| `s32` | Знаковое 32-бит | 2 |
| `f32` | IEEE754 float | 2 |
| `enum` | Перечисление | 1 |
| `bitfield` | Битовая маска | 1 |

### Многословные регистры (вариант B)

- 32-битные значения публикуются одной записью по базовому адресу
- Хвостовые регистры не публикуются

## Режимы работы

### Production (по умолчанию)

```yaml
mode: "production"
logging:
  level: "INFO"
```

- Минимальное логирование
- Без отладочной информации

### Debug

```yaml
mode: "debug"
logging:
  level: "DEBUG"
```

- Подробное логирование
- RAW вход/выход в логах
- Причины `value=null`

## Web UI

Доступен по адресу `http://localhost:8080` (или настроенный порт).

### Страницы

- **Главная** (`/`) — список роутеров, панелей, статистика MQTT
- **Панель** (`/router/<sn>/panel/<id>`) — таблица регистров панели

### API

- `GET /api/stats` — системная статистика
- `GET /api/routers` — список роутеров
- `GET /api/router/<sn>/panel/<id>/registers` — регистры панели (JSON)
- `POST /api/admin/clear-memory` — очистка in-memory хранилища
- `GET /api/version` — версия приложения

## Мониторинг состояния

| Статус | Условие |
|--------|---------|
| `online` | Сообщение получено в пределах stale-порога |
| `stale` | Нет сообщений дольше stale-порога |
| `offline` | Нет сообщений дольше offline-порога |

Пороги настраиваются в `config.yaml` (секция `health`).

## Структура проекта

```
cg-telemetry/
├── app.py              # Точка входа
├── version.py          # Версия приложения
├── decoder.py          # Логика декодирования Modbus
├── maps_loader.py      # Загрузчик карт регистров
├── mqtt_client.py      # MQTT-клиент + нормализатор
├── panel_store.py      # In-memory хранилище панелей
├── health_monitor.py   # Мониторинг состояния
├── web_ui.py           # Web UI (Flask)
├── config.yaml         # Конфигурация (не в git)
├── config.example.yaml # Пример конфигурации
├── requirements.txt    # Python-зависимости
├── .gitignore          # Правила Git
├── test_local.py       # Локальный тест без MQTT
├── mqtt_test_publisher.py # Тестовый MQTT-публикатор
└── maps/
    ├── register_map.jsonl
    ├── enum_map.json
    └── fault_bitmap_map.jsonl
```

## Версионирование

Приложение использует SemVer. Текущая стартовая версия: `0.1.1` (см. `version.py`).

## Лицензия

MIT

## Поддержка

По вопросам и проблемам — создайте Issue на GitHub.
