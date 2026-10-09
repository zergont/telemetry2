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
- **Контроль метки времени** — проверка `date_iso_8601` каждой записи относительно времени приёма: сдвиг пояса, «будущие» и неразборчивые метки, залежалая доставка (см. [Контроль метки времени](#контроль-метки-времени-clock_guard))
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

### 1. Клонировать репозиторий в `/opt/cg-decoder`

```bash
sudo mkdir -p /opt
cd /opt
sudo git clone https://github.com/zergont/telemetry2.git cg-decoder
sudo chown -R $USER:$USER /opt/cg-decoder
cd /opt/cg-decoder
```

### 2. Запустить установочный скрипт

```bash
chmod +x install.sh
sudo ./install.sh
```

> В прод-сценарии рабочий каталог приложения — `/opt/cg-decoder`.

Скрипт автоматически:
- устанавливает приложение в `/opt/cg-decoder`
- создаёт `venv` и ставит зависимости
- создаёт `config.yaml` из `config.example.yaml` (если отсутствует)
- создаёт `systemd`-службу `cg-decoder`
- включает службу в автозапуск и запускает её (`enable --now`)
- показывает статус службы в конце установки

### 3. Проверить и отредактировать конфиг

```bash
sudo nano /opt/cg-decoder/config.yaml
```

Основные параметры:

- `mqtt.host` — адрес MQTT-брокера
- `mqtt.port` — порт (по умолчанию: 1883)
- `mqtt.username` и `mqtt.password` — если требуется авторизация
- `web.port` — порт Web UI (по умолчанию: 8080)
- `mode` — `debug` для подробного логирования
- `clock_guard` — контроль метки времени (если секции нет — значения по умолчанию, режим `flag`)

### 4. Перезапустить после изменения конфига

```bash
sudo systemctl restart cg-decoder
```

### 5. Проверка статуса службы

```bash
sudo systemctl status cg-decoder
sudo systemctl is-enabled cg-decoder
```

### Ручная установка (если без скрипта)

#### 1. Установить приложение в `/opt/cg-decoder`

```bash
sudo mkdir -p /opt
cd /opt
sudo git clone https://github.com/zergont/telemetry2.git cg-decoder
sudo chown -R $USER:$USER /opt/cg-decoder
cd /opt/cg-decoder
```

#### 2. Создать виртуальное окружение

```bash
python3 -m venv venv
source venv/bin/activate
```

#### 3. Установить зависимости

```bash
pip install -r requirements.txt
```

#### 4. Настроить конфигурацию

```bash
cp config.example.yaml config.yaml
nano config.yaml
```

#### 5. Настроить службу `systemd` (ниже) и запустить

## Автозапуск при перезагрузке (systemd)

> Этот раздел нужен для ручной установки. При запуске `install.sh` служба создаётся автоматически.

### Создать файл сервиса

```bash
sudo nano /etc/systemd/system/cg-decoder.service
```

Содержимое:

```ini
[Unit]
Description=CG Telemetry Modbus Decoder
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/opt/cg-decoder
Environment="PATH=/opt/cg-decoder/venv/bin"
ExecStart=/opt/cg-decoder/venv/bin/python app.py --config /opt/cg-decoder/config.yaml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

> Замените `youruser` на имя пользователя, под которым запускается сервис.

### Активировать и запустить

```bash
sudo systemctl daemon-reload
sudo systemctl enable cg-decoder
sudo systemctl start cg-decoder
```

### Полезные команды

```bash
# Статус сервиса
sudo systemctl status cg-decoder

# Логи в реальном времени
sudo journalctl -u cg-decoder -f

# Перезапустить после изменений
sudo systemctl restart cg-decoder

# Отключить автозапуск
sudo systemctl disable cg-decoder
```

После `systemctl enable` сервис будет **автоматически запускаться при каждой перезагрузке** системы.

## Обновление на сервере через Git

Рекомендуемый способ — скрипт `update.sh`.

```bash
cd /opt/cg-decoder
chmod +x update.sh
sudo ./update.sh
```

Скрипт автоматически:
- подтягивает код из текущей git-ветки (`pull --ff-only`)
- обновляет зависимости (`pip install -r requirements.txt`)
- перезапускает службу `cg-decoder`
- показывает статус службы

### Ручное обновление (если без скрипта)

Если проект уже установлен как `systemd`-сервис:

```bash
# 1) Перейти в каталог проекта
cd /opt/cg-decoder

# 2) Подтянуть изменения из репозитория
git pull origin master

# 3) Обновить зависимости (на случай изменений в requirements.txt)
source venv/bin/activate
pip install -r requirements.txt

# 4) Перезапустить сервис
sudo systemctl restart cg-decoder

# 5) Проверить статус и логи
sudo systemctl status cg-decoder
sudo journalctl -u cg-decoder -f
```

Если у вас основная ветка называется `main`, используйте:

```bash
git pull origin main
```

## Удаление с сервера

Полное удаление `cg-decoder`:

```bash
sudo systemctl stop cg-decoder
sudo systemctl disable cg-decoder
sudo rm -f /etc/systemd/system/cg-decoder.service
sudo systemctl daemon-reload
sudo systemctl reset-failed

sudo rm -rf /opt/cg-decoder
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
  "device_type": "pcc",
  "registers": [
    {
      "addr": 46109,
      "name": "Engine Operating State",
      "value": 4,
      "text": "Running",
      "unit": null,
      "raw": 4
    }
  ],
  "received_at": "2026-01-27T18:59:56.412+00:00",
  "ts_status": "ok",
  "ts_offset_sec": -7.412
}
```

> **Правило декодирования:** если регистр не удалось декодировать → `value = null`, `raw = <число>`.

Поля `received_at`, `ts_status`, `ts_offset_sec` (и при сдвиге — `ts_shift_hours`, `ts_original`)
добавляет контроль метки времени, см. [ниже](#поля-в-decoded). Основные поля и их порядок не меняются;
если `clock_guard.enabled: false`, новых полей нет.

### QUARANTINE (выход, только для наблюдения)

```
cg/v1/quarantine/SN/<router_sn>/<device_type>/<server_id>
```

Записи с «будущей» меткой (`future`), которые не попали в decoded. QoS 0, без retain.
Подробнее — в разделе [Карантин](#карантин).

## Карты регистров

Вся логика декодирования во внешних файлах (хардкод регистров запрещён).

### Формат файла

Каждое устройство — одна директория `devices/<device_type>/` с единым файлом:

| Файл | Формат | Описание |
|------|--------|----------|
| `devices/<type>/map.jsonl` | JSONL | Все регистры: числа, enum, fault bitmap, строки |

Каждая строка — JSON-объект одного регистра.

> **Обратная совместимость:** если `map.jsonl` отсутствует, загрузчик использует старый трёхфайловый формат (`register_map.jsonl` + `enum_map.json` + `fault_bitmap_map.jsonl`).

---

### Структура записи

**Числовой регистр:**
```json
{
  "addr": 40018,
  "reg_type": "holding",
  "name": "GensetL1N Voltage",
  "data_type": "u16",
  "word_len": 1,
  "multiplier": 1.0,
  "offset": 0.0,
  "unit": "Vac",
  "na_values": [65535],
  "notes_ru": "Напряжение генератора фаза L1-нейтраль"
}
```

**Enum-регистр** — добавляется поле `labels`:
```json
{
  "addr": 40010,
  "reg_type": "holding",
  "name": "Control Switch Position",
  "data_type": "u16",
  "word_len": 1,
  "multiplier": 1.0,
  "offset": 0.0,
  "unit": "enum",
  "na_values": [65535],
  "labels": {"0": "Off", "1": "Auto", "2": "Manual"},
  "notes_ru": "Положение переключателя режимов"
}
```

**Fault bitmap регистр** — добавляется поле `bits`:
```json
{
  "addr": 40400,
  "reg_type": "holding",
  "name": "Active Fault Bitmap 1",
  "data_type": "u16",
  "word_len": 1,
  "multiplier": 1.0,
  "offset": 0.0,
  "unit": "fault_bitmap",
  "na_values": [],
  "bits": {
    "0": {"name": "Low Oil Pressure",    "severity": "shutdown"},
    "1": {"name": "High Coolant Temp",   "severity": "warning"},
    "2": {"name": "Engine Derate Active","severity": "derate"}
  }
}
```

**Строковый регистр** (тип `cNNN`, где NNN — длина в битах из документации):
```json
{
  "addr": 40320,
  "reg_type": "holding",
  "name": "StartInhibit No1 Fault Text",
  "data_type": "c168",
  "word_len": 20,
  "multiplier": 1.0,
  "offset": 0.0,
  "unit": "",
  "na_values": [],
  "notes_ru": "Текст первого запрета пуска (20 символов ASCII)"
}
```

---

### Поля записи

| Поле | Обязательное | Описание |
|------|:---:|---------|
| `addr` | ✓ | Полный Modbus-адрес (например 40018) |
| `reg_type` | — | `"holding"` (по умолчанию) или `"input"` |
| `name` | — | Имя регистра на английском |
| `data_type` | — | Тип данных (см. ниже) |
| `word_len` | — | Число Modbus-регистров (16-бит слов) |
| `multiplier` | — | Множитель (по умолчанию `1.0`) |
| `offset` | — | Смещение (по умолчанию `0.0`) |
| `unit` | — | Единица измерения, `"enum"`, `"fault_bitmap"` или `""` |
| `na_values` | — | Список значений, означающих «нет данных» |
| `notes_ru` | — | Описание на русском |
| `labels` | только enum | `{"value_str": "label"}` |
| `bits` | только fault_bitmap | `{"bit_num": {"name": ..., "severity": ...}}` |

---

### Типы данных (`data_type`)

| Тип | Описание | `word_len` |
|-----|----------|:---:|
| `u8` | Беззнаковое 8-бит | 1 |
| `s8` | Знаковое 8-бит | 1 |
| `u16` | Беззнаковое 16-бит | 1 |
| `s16` | Знаковое 16-бит | 1 |
| `u32` | Беззнаковое 32-бит, Hi Word first | 2 |
| `u32_le` | Беззнаковое 32-бит, Lo Word first | 2 |
| `s32` | Знаковое 32-бит | 2 |
| `f32` | IEEE 754 float | 2 |
| `bitfield` | 16-битная маска (NFPA и т.п.) | 1 |
| `cNNN` | ASCII-строка, NNN бит (c168, c144, c136…) | NNN/8 |

### Допустимые значения `severity` (для `bits`)

`warning` · `shutdown` · `shutdown_cooldown` · `derate` · `none`

---

### Декодирование адреса

Из `full_addr` (строка) или `addr` (число):
- Строка `"406109"`: первый символ — тип области (`4` = holding, `3` = input), последние 5 цифр — смещение
- Число `6109`: смещение напрямую, тип holding по умолчанию
- Итоговый адрес = 40000 + смещение

Примеры:
- `"406109"` → смещение `06109` → адрес `46109`
- `addr: 6109` → адрес `46109`
- `"403560"` → смещение `03560` → адрес `43560`

### Многословные регистры

- 32-битные значения публикуются одной записью по базовому адресу (`word_len = 2`)
- Строки читаются как N последовательных регистров (`word_len = cNNN / 8`)
- Хвостовые регистры не публикуются отдельно

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

- **Главная** (`/`) — список роутеров, панелей, статистика MQTT; у каждого роутера — статус часов
  («в норме / спешат на N ч / отстают на N ч / метка неразборчива»), последний offset и число эпизодов за 24 ч
- **Панель** (`/router/<sn>/panel/<id>`) — таблица регистров панели
- **Устройства** (`/devices`) — в разделе ошибок категория «Метка времени»: эпизоды по роутерам
  (начало, конец, статус, k, число записей), а не каждая запись

### API

- `GET /api/stats` — системная статистика (в `mqtt.clock_guard` — счётчики контроля метки времени)
- `GET /api/routers` — список роутеров, у каждого в `clock` — статус часов (`null`, если данных ещё нет)
- `GET /api/clock` — состояние контроля метки времени: режим, счётчики, роутеры, эпизоды (новые первыми)
- `GET /api/router/<sn>/panel/<id>/registers` — регистры панели (JSON)
- `POST /api/admin/clear-memory` — очистка in-memory хранилища (сбрасывает и состояние роутеров
  и журнал эпизодов контроля метки времени; счётчики остаются)
- `GET /api/version` — версия приложения

## Мониторинг состояния

| Статус | Условие |
|--------|---------|
| `online` | Сообщение получено в пределах stale-порога |
| `stale` | Нет сообщений дольше stale-порога |
| `offline` | Нет сообщений дольше offline-порога |

Пороги настраиваются в `config.yaml` (секция `health`).

Тот же монитор раз в `check_interval_sec` вызывает `tick()` контроля метки времени:
закрывает эпизоды по молчанию роутера и поднимает сигнал о молчании публикатора.

## Контроль метки времени (clock_guard)

Роутер может взять время от сотовой сети с неверным поясом — тогда `date_iso_8601`
уходит на целое число часов вперёд (у ДЭС №3 — ровно на +2 ч). Без проверки такие данные
встают «в будущее», перемешиваются с настоящими и ломают ниже по цепочке разрывы,
`latest_state` и периоды состояний. Модуль `clock_guard.py` проверяет метку каждой
Modbus-записи до публикации.

- **t_recv** — время приёма: `time.time()` в начале `MqttClient._on_message`, одно значение
  на MQTT-сообщение (`msg.timestamp` у paho монотонный — не используется). Часы сервера — по NTP.
- **offset** = метка − t_recv. У живой доставки offset от −18,5 до −0,6 с.
- Статус считается **по каждой записи отдельно** — пачки бывают смешанными.
- GPS-сообщения не проверяются.
- При внутренней ошибке модуля запись публикуется как есть с `ts_status=ok`, сообщение не теряется.

### Статусы и действия

Если подходят несколько статусов, побеждает первый: `invalid > tz_shift > future > offset_jump > late > ok`.

| Статус | Условие | Что делается |
|--------|---------|--------------|
| `ok` | живая доставка | публикуется как есть |
| `late` | offset < −60 с (залежалая пачка после обрыва) | как есть, только флаг; никогда не правится и не идёт в карантин |
| `tz_shift`, k > 0 | offset > 120 с и offset ∈ [k·3600 − 1800; k·3600 + 120], k = 1…14 — сразу, с первой записи | `correct`: `timestamp` = метка − k ч в исходном поясе, `ts_status=corrected`; `flag`: как есть, с флагом |
| `future` | offset > 120 с, но не на целые часы | **в decoded не публикуется** → карантин (в обоих режимах) |
| `tz_shift`, k < 0 | offset ≈ k·3600 ±120 с держится ≥120 с, ≥3 разных метки, разброс ≤30 с; до подтверждения — `late` | как есть, только флаг |
| `offset_jump` | отход от базового offset роутера (медиана живых записей) > 600 с держится ≥3 метки и ≥60 с | как есть, с флагом |
| `invalid` | метка не разобралась, без пояса или раньше `min_valid_date` | `timestamp` = время приёма (в последнем известном поясе роутера, иначе в поясе сервера), исходная — в `ts_original` |

Режим `flag | correct` задаётся в секции `clock_guard` и переопределяется на отдельный роутер.
**Рекомендация:** первые 1–2 недели работать в `flag` и смотреть категорию «Метка времени»
на `/devices`, затем переключить на `correct`.

### Настройка

```yaml
clock_guard:
  enabled: true
  mode: "flag"                 # flag | correct
  routers:                     # SN — строка в кавычках
    "1126246373": "correct"    # или "1126246373": {mode: "correct"}
  quarantine:
    file: "logs/clock_quarantine.jsonl"   # "" — не писать
    max_bytes: 10485760                   # не меньше 1
    backup_count: 5                       # не меньше 1
    topic_base: "cg/v1/quarantine/SN"     # "" — не публиковать
```

Все ключи с пояснениями и значениями по умолчанию (пороги классификации, подтверждение
`tz_shift` k < 0 и `offset_jump`, закрытие эпизодов, сигнал о молчании) — в `config.example.yaml`.

- Если секции нет, действуют значения по умолчанию (модуль включён, режим `flag`).
- Выключить модуль: `enabled: false` или короче `clock_guard: false`.
- При ошибке в значениях в лог пишется ошибка и берутся значения по умолчанию. Явное
  `enabled: false` при этом соблюдается: модуль остаётся выключенным, а не включается
  значениями по умолчанию.
- Ключ без значения (`file:`, `topic_base:`, `epsilon_sec:` …) в YAML — это `null`, то есть
  значение по умолчанию. Чтобы выключить файл или топик карантина, нужна пустая строка `""`.
- `quarantine.max_bytes` и `quarantine.backup_count` не меньше 1: при 0 `RotatingFileHandler`
  не ротирует вовсе и файл растёт без предела. Такие значения заменяются (10 МБ и 1)
  с предупреждением в лог.

> **Внимание:** Web UI перезаписывает `config.yaml` через `yaml.safe_dump` — комментарии в нём
> пропадают. Документация по ключам — в `config.example.yaml` и здесь.

### Поля в decoded

| Поле | Когда | Описание |
|------|-------|----------|
| `received_at` | всегда | время приёма, UTC ISO с миллисекундами |
| `ts_status` | всегда | `ok`, `late`, `tz_shift`, `corrected`, `offset_jump`, `invalid` |
| `ts_offset_sec` | всегда | offset = метка − время приёма, с (`null` для `invalid`) |
| `ts_shift_hours` | `tz_shift` / `corrected` | k — сдвиг пояса, ч |
| `ts_original` | `tz_shift` / `corrected` / `invalid` | исходная метка роутера |

db-writer и UI-telemetry читают только `timestamp` и `registers` — новые поля им не мешают.

Пример: ДЭС №3 прислала метку на +2 ч, режим `correct`:

```json
{
  "timestamp": "2026-10-09T13:20:00+0300",
  "router_sn": "1126246373",
  "bserver_id": 1,
  "device_type": "pcc",
  "registers": [ ... ],
  "received_at": "2026-10-09T10:20:30.000+00:00",
  "ts_status": "corrected",
  "ts_offset_sec": 7170.0,
  "ts_shift_hours": 2,
  "ts_original": "2026-10-09T15:20:00+0300"
}
```

В режиме `flag` та же запись уйдёт с `"timestamp": "2026-10-09T15:20:00+0300"` и `"ts_status": "tz_shift"`.

### Карантин

Записи `future` в decoded не публикуются:

- **JSONL-файл** `quarantine.file` (по умолчанию `logs/clock_quarantine.jsonl`), ротация по
  `max_bytes` / `backup_count`. Строка: `received_at`, `router_sn`, `bserver_id`, `device_type`,
  `timestamp` (исходная метка), `ts_status`, `ts_offset_sec`, `full_addr`, `data` (слова),
  `registers` (декодированные).
- **Топик** `<topic_base>/<router_sn>/<device_type>/<bserver_id>` — только для наблюдения
  (QoS 0, без retain). Топик под decoded-топиком (`cg/v1/decoded/...`) блокируется.
- **Повторная публикация из карантина в `cg/v1/decoded` запрещена**: она ломает в db-writer
  обнаружение разрывов, `latest_state` и периоды состояний и неисправностей. Восстановление
  из карантина — отдельный инструмент.
- Хранилище панелей (Web UI) обновляется и для записей карантина: значения регистров живые.
- Побочный эффект: на время карантина db-writer покажет панель stale/offline и разрыв.

### Эпизоды и сигналы

- **Эпизод** — подряд идущие записи роутера с одним статусом (`tz_shift`, `future`,
  `offset_jump`, `invalid`). Закрывается после 2 разных нормальных меток или при молчании
  роутера дольше `episode_silence_close_min` минут. В лог — один WARNING на начало и один на конец.
- **Сигнал о молчании.** После `tz_shift` k > 0 публикатор на роутере обычно молчит, пока часы
  не догонят последнюю «будущую» метку. Если роутер молчит дольше `silence_alert_sec` после такого
  эпизода, в лог и в статус роутера (Web UI, `/api/routers`, `/api/clock`) выводится:
  «Роутер молчит после tz_shift k=+N — публикатор, вероятно, ждёт, пока часы роутера дойдут
  до последней «будущей» метки …; перезапустите сервис опроса на роутере».
  Декодером это не лечится.
- **Счётчики** по статусам (`total`, `ok`, `late`, `tz_shift`, `future`, `offset_jump`, `invalid`,
  `corrected`, `quarantined`, `replaced`, `errors`) — в `GET /api/stats` (`mqtt.clock_guard`).
  `quarantined` — записи, не опубликованные в decoded и ушедшие в карантин (считаются и при
  выключенном файле карантина; ошибка открытия, записи или ротации файла — нет прав, диск
  заполнен — добавляется в `errors` и пишется в лог ERROR не чаще раза в минуту; такая запись
  потеряна: файл — её единственная копия). Он может быть меньше
  `future`: запись без декодированных регистров не публикуется вовсе и в карантин не попадает.
- **Очистка памяти** (`POST /api/admin/clear-memory`) сбрасывает состояние роутеров и журнал
  эпизодов; счётчики сохраняются.

### Реплей истории

`tools/replay_clock_guard.py` — прогон выгрузки `history` через `ClockGuard` для проверки правил
на реальных данных (см. описание в самом скрипте).

## Тесты

```bash
pip install -r requirements-dev.txt
python -m pytest
```

`pytest.ini` ограничивает сбор каталогом `tests/` (`test_local.py` в корне — ручной симулятор,
не pytest-тест):

- `tests/test_clock_guard.py` — правила классификации `clock_guard`
- `tests/test_mqtt_clock_integration.py` — конвейер MQTT-клиента целиком: decoded-поля,
  исправление, карантин, отказоустойчивость, GPS, смешанные gzip-пачки
- `tests/test_web_ui_clock.py` — Web UI: статус часов роутеров, `/api/clock`, очистка памяти
- `tests/test_app_clock_config.py` — секция `clock_guard` при запуске (`app.py`): выключение,
  ошибки в значениях
- `tests/test_replay_clock_guard.py` — реплей выгрузки `history` (`tools/replay_clock_guard.py`)

## Структура проекта

```
cg-decoder/
├── app.py              # Точка входа
├── version.py          # Версия приложения
├── decoder.py          # Логика декодирования Modbus
├── maps_loader.py      # Загрузчик карт регистров
├── mqtt_client.py      # MQTT-клиент + нормализатор
├── clock_guard.py      # Контроль метки времени (сдвиг пояса, карантин, эпизоды)
├── panel_store.py      # In-memory хранилище панелей
├── health_monitor.py   # Мониторинг состояния
├── web_ui.py           # Web UI (Flask)
├── config.yaml         # Конфигурация (не в git)
├── config.example.yaml # Пример конфигурации
├── requirements.txt    # Python-зависимости
├── requirements-dev.txt # Зависимости для разработки (pytest)
├── pytest.ini          # Настройки pytest (тесты из tests/)
├── .gitignore          # Правила Git
├── test_local.py       # Локальный тест без MQTT (ручной симулятор)
├── mqtt_test_publisher.py # Тестовый MQTT-публикатор
├── map_validator.py    # Валидатор карт регистров
├── devices/
│   └── pcc/
│       └── map.jsonl   # Карта регистров Cummins PCC (1353 регистра)
├── tests/              # pytest-тесты
│   ├── test_clock_guard.py             # Правила контроля метки времени
│   ├── test_mqtt_clock_integration.py  # Конвейер MQTT-клиента с clock_guard
│   ├── test_web_ui_clock.py            # Web UI: статус часов, /api/clock, clear-memory
│   ├── test_app_clock_config.py        # Секция clock_guard при запуске (app.py)
│   └── test_replay_clock_guard.py      # Реплей истории через clock_guard
└── tools/              # Вспомогательные скрипты (трансформация, слияние карт)
    └── replay_clock_guard.py  # Реплей истории через clock_guard
```

## Версионирование

Приложение использует SemVer. Текущая версия: `2.3.0` (см. `version.py`).

## Лицензия

MIT

## Поддержка

По вопросам и проблемам — создайте Issue на GitHub.
