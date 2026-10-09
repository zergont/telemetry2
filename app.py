#!/usr/bin/env python3
# Copyright (c) 2026 ООО «НГ-ЭНЕРГОСЕРВИС». Все права защищены.
# Программный комплекс «Честная Генерация»
# Модуль декодирования Modbus-телеметрии
# Автор: Саввиди Александр Анатольевич | ИНН 4725009270
#
# Данное программное обеспечение является конфиденциальным.
# Несанкционированное копирование, распространение или использование
# без письменного разрешения правообладателя запрещено.

"""
Универсальный Modbus-декодер и Web UI

Точка входа приложения.
Запускает все компоненты: MQTT-клиент, декодер, монитор состояния, Web UI.

Использование:
    python app.py [--config config.yaml]
"""

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path

import yaml

from maps_loader import load_device_maps
from panel_store import init_store
from clock_guard import init_clock_guard, get_clock_guard, is_off_value
from mqtt_client import init_mqtt_client
from health_monitor import init_health_monitor
from web_ui import run_web_ui
from version import __version__

def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    path = Path(config_path)
    if not path.exists():
        print(f"[ОШИБКА] Файл конфигурации не найден: {config_path}")
        print(f"[ИНФО] Скопируйте config.example.yaml в config.yaml и настройте параметры")
        sys.exit(1)

    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def setup_logging(config: dict):
    """Setup logging based on config."""
    log_config = config.get('logging', {})

    level_str = log_config.get('level', 'INFO').upper()
    level = getattr(logging, level_str, logging.INFO)

    format_str = log_config.get('format', '%(asctime)s [%(levelname)s] %(name)s: %(message)s')

    handlers = [logging.StreamHandler(sys.stdout)]

    log_file = log_config.get('file')
    if log_file:
        # Create logs directory if needed
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=level,
        format=format_str,
        handlers=handlers
    )

    # Reduce noise from libraries (in debug mode, keep their default levels)
    if level > logging.DEBUG:
        logging.getLogger('werkzeug').setLevel(logging.WARNING)
        logging.getLogger('apscheduler').setLevel(logging.WARNING)


def print_status(ok: bool, message: str):
    """Print status message."""
    status = "[OK]" if ok else "[FAIL]"
    print(f"{status} {message}")


def load_maps_from_config(config: dict) -> tuple:
    """
    Load register maps from config.

    Supports two modes:
    - New: 'devices' section with per-device map directories
    - Legacy: 'maps' section with individual file paths (backward compatible)

    Returns (success: bool, payload_key_map: dict)
    """
    payload_key_map = {}

    devices_config = config.get('devices')
    if not devices_config:
        print("[ОШИБКА] Секция 'devices' не найдена в конфиге")
        return False, {}

    loaded = 0
    for device_type, device_cfg in devices_config.items():
        maps_dir = device_cfg.get('maps_dir', f'maps/{device_type}')
        ok = load_device_maps(device_type, maps_dir)
        print_status(ok, f"карты '{device_type}' из {maps_dir}")
        if not ok:
            logging.getLogger(__name__).error(
                f"Карты устройства '{device_type}' не загружены — "
                f"устройство будет пропущено. Проверьте {maps_dir}/"
            )
            continue

        # Build payload_key -> device_type mapping only for loaded devices
        for key in device_cfg.get('payload_keys', []):
            payload_key_map[key] = device_type
        loaded += 1

    if loaded == 0:
        return False, {}

    return True, payload_key_map


def init_clock_guard_from_config(config: dict):
    """
    Инициализация контроля метки времени из секции clock_guard.

    Секции нет — значения по умолчанию (clock_guard.DEFAULTS).
    `clock_guard: false` (off, no, …) — короткая форма выключения.
    Ошибка в значениях — сообщение в лог и значения по умолчанию, но явное
    выключение (enabled: false) соблюдается: в DEFAULTS модуль включён, и
    выключатель, которым оператор возвращает прежнее поведение на время
    инцидента, иначе молча превращался бы во включение.

    Returns (guard, config_ok: bool)
    """
    logger = logging.getLogger(__name__)
    section = config.get('clock_guard')
    if section is None:
        section = {}
    if not isinstance(section, dict):
        if is_off_value(section):
            return init_clock_guard({'enabled': False}), True
        logger.error("Секция clock_guard должна быть словарём — используются значения по умолчанию")
        return init_clock_guard({}), False

    try:
        return init_clock_guard(section), True
    except Exception as e:
        if is_off_value(section.get('enabled')):
            logger.error(f"Ошибка в секции clock_guard: {e} — контроль выключен "
                         f"(clock_guard.enabled: false), остальные значения не применяются")
            return init_clock_guard({'enabled': False}), False
        logger.error(f"Ошибка в секции clock_guard: {e} — используются значения по умолчанию")
        return init_clock_guard({}), False


def describe_clock_guard(guard) -> str:
    """Строка статуса контроля метки времени для консоли."""
    cfg = guard.cfg
    if not cfg.enabled:
        return "контроль метки времени выключен"
    text = f"контроль метки времени: режим {cfg.mode}"
    if cfg.router_modes:
        overrides = ', '.join(f"{sn}={mode}" for sn, mode in sorted(cfg.router_modes.items()))
        text += f", роутеры: {overrides}"
    text += f", карантин: {cfg.quarantine_file or 'файл выключен'}"
    return text


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Универсальный Modbus-декодер и Web UI'
    )
    parser.add_argument(
        '--config', '-c',
        default='config.yaml',
        help='Путь к файлу конфигурации (по умолчанию: config.yaml)'
    )
    parser.add_argument(
        '--version', '-v',
        action='version',
        version=f'%(prog)s {__version__}'
    )

    args = parser.parse_args()

    # Load config
    config = load_config(args.config)

    # Setup logging
    setup_logging(config)
    logger = logging.getLogger(__name__)

    # Get mode
    debug_mode = config.get('mode', 'production') == 'debug'
    if debug_mode:
        logging.getLogger().setLevel(logging.DEBUG)

    print("=" * 60)
    print("Универсальный Modbus-декодер и Web UI")
    print(f"Версия: {__version__}")
    print(f"Режим: {'ОТЛАДКА' if debug_mode else 'ПРОДАКШН'}")
    print("=" * 60)

    # ================================================================
    # Load register maps
    # ================================================================
    maps_ok, payload_key_map = load_maps_from_config(config)

    if not maps_ok:
        logger.error("Ни одно устройство не загружено — выход")
        sys.exit(1)

    logger.info(f"Маппинг payload ключей: {payload_key_map}")

    # ================================================================
    # Initialize panel store
    # ================================================================
    health_config = config.get('health', {})

    store = init_store(
        stale_threshold_sec=health_config.get('stale_threshold_sec', 10),
        offline_threshold_sec=health_config.get('offline_threshold_sec', 60)
    )

    print_status(True, "хранилище панелей инициализировано")

    # ================================================================
    # Initialize clock guard (контроль метки времени)
    # ================================================================
    # До запуска монитора состояния: он вызывает clock_guard.tick()
    clock_guard, clock_config_ok = init_clock_guard_from_config(config)
    if clock_config_ok:
        print_status(True, describe_clock_guard(clock_guard))
    else:
        fallback = ("значения по умолчанию" if clock_guard.enabled
                    else "выключатель enabled соблюдён, остальные ключи не применяются")
        print_status(False, f"секция clock_guard с ошибкой, {describe_clock_guard(clock_guard)} "
                            f"({fallback})")

    # ================================================================
    # Initialize health monitor
    # ================================================================
    health_monitor = init_health_monitor(
        check_interval_sec=health_config.get('check_interval_sec', 5)
    )
    health_monitor.start()

    print_status(True, "монитор состояния запущен")

    # ================================================================
    # Initialize and connect MQTT client
    # ================================================================
    mqtt_config = config.get('mqtt', {})

    mqtt_client = init_mqtt_client(
        host=mqtt_config.get('host', 'localhost'),
        port=mqtt_config.get('port', 1883),
        client_id=mqtt_config.get('client_id', 'modbus-decoder'),
        username=mqtt_config.get('username', ''),
        password=mqtt_config.get('password', ''),
        reconnect_delay=mqtt_config.get('reconnect_delay_sec', 5),
        raw_topic_pattern=mqtt_config.get('raw_topic_pattern', 'cg/v1/telemetry/SN/+'),
        decoded_topic_base=mqtt_config.get('decoded_topic_base', 'cg/v1/decoded/SN'),
        payload_key_map=payload_key_map,
        debug_mode=debug_mode
    )

    mqtt_connected = mqtt_client.connect()
    print_status(mqtt_connected, "MQTT подключен" if mqtt_connected else "MQTT не подключен (будет повторять)")

    # Всегда запускаем loop — paho сам переподключится, если брокер недоступен при старте
    mqtt_client.start()
    print_status(True, "декодер запущен")

    # ================================================================
    # Start Web UI
    # ================================================================
    web_config = config.get('web', {})

    # Run web UI in separate thread
    web_thread = threading.Thread(
        target=run_web_ui,
        kwargs={
            'host': web_config.get('host', '0.0.0.0'),
            'port': web_config.get('port', 8080),
            'debug': web_config.get('debug', False)
        },
        daemon=True
    )
    web_thread.start()

    print_status(True, f"Web UI запущен на http://{web_config.get('host', '0.0.0.0')}:{web_config.get('port', 8080)}")

    print("=" * 60)
    print("Система запущена. Нажмите Ctrl+C для остановки.")
    print("=" * 60)

    # ================================================================
    # Graceful shutdown
    # ================================================================
    shutdown_event = threading.Event()

    def signal_handler(signum, frame):
        logger.info("Получен сигнал остановки")
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Wait for shutdown
    try:
        while not shutdown_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    # Cleanup
    logger.info("Завершение работы...")

    mqtt_client.stop()
    health_monitor.stop()

    try:
        # Текущий экземпляр (мог быть переинициализирован после старта)
        guard = get_clock_guard()
        if guard is not None:
            guard.close()
    except Exception as e:
        logger.error(f"Ошибка закрытия контроля метки времени: {e}")

    logger.info("Работа завершена")
    print("\nДо свидания!")


if __name__ == '__main__':
    main()
