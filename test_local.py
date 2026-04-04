#!/usr/bin/env python3
"""
Локальный тест

Симулирует поток данных без MQTT.
Заполняет хранилище тестовыми данными и запускает Web UI.

Использование:
    python test_local.py
"""

import logging
import threading
import time
import json

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Import modules
from maps_loader import load_all_maps
from decoder import get_decoder
from panel_store import init_store, get_store
from health_monitor import init_health_monitor
from web_ui import run_web_ui


def simulate_telemetry():
    """Simulate telemetry data."""
    store = get_store()
    decoder = get_decoder(debug_mode=True)
    
    # Test data
    test_packets = [
        # Router 1, Panel 2
        ("ROUTER-001", 2, "400061", [123]),        # Battery 12.3V
        ("ROUTER-001", 2, "406109", [4]),          # Engine Running
        ("ROUTER-001", 2, "400010", [1]),          # Control: Auto
        ("ROUTER-001", 2, "400034", [150]),        # Total kW
        ("ROUTER-001", 2, "400400", [5]),          # Faults (bits 0,2)
        ("ROUTER-001", 2, "400044", [6000]),       # Frequency 60.00 Hz
        ("ROUTER-001", 2, "400018", [120, 121, 122, 121]),  # L1N-L3N voltages
        
        # Router 1, Panel 3
        ("ROUTER-001", 3, "400061", [245]),        # Battery 24.5V
        ("ROUTER-001", 3, "406109", [0]),          # Engine Stopped
        
        # Router 2, Panel 1
        ("ROUTER-002", 1, "400061", [120]),        # Battery 12.0V
        ("ROUTER-002", 1, "406109", [4]),          # Engine Running
        ("ROUTER-002", 1, "400034", [75]),         # 75 kW
    ]
    
    logger.info("Запуск симуляции телеметрии...")
    
    while True:
        for router_sn, bserver_id, full_addr, data in test_packets:
            # Decode
            decoded = decoder.decode_packet(full_addr, data)
            
            # Update store
            store.update_panel(
                router_sn=router_sn,
                bserver_id=bserver_id,
                decoded_registers=decoded
            )
        
        # Simulate GPS updates for routers
        store.update_router_gps("ROUTER-001", {
            'latitude': 59.851780,
            'longitude': 30.480843,
            'altitude': 23.2,
            'speed': 10.37,
            'angle': 63.2,
            'accuracy': 6.8,
            'satellites': 4,
            'fix_status': 1,
            'date_iso_8601': '2026-02-16T20:54:47+0300'
        })
        store.update_router_gps("ROUTER-002", {
            'latitude': 55.755800,
            'longitude': 37.617300,
            'altitude': 156.0,
            'speed': 0.0,
            'satellites': 8,
            'fix_status': 1,
            'date_iso_8601': '2026-02-16T21:00:00+0300'
        })
        
        logger.info(f"Симулировано {len(test_packets)} пакетов")
        time.sleep(5)


def main():
    print("=" * 60)
    print("Универсальный Modbus-декодер — Локальный тест")
    print("=" * 60)
    
    # Load maps
    ok = load_all_maps(
        'maps/register_map.jsonl',
        'maps/enum_map.json',
        'maps/fault_bitmap_map.jsonl'
    )
    if not ok:
        print("[ОШИБКА] Не удалось загрузить карты")
        return
    print("[OK] Карты загружены")
    
    # Init store
    store = init_store(stale_threshold_sec=10, offline_threshold_sec=30)
    print("[OK] Хранилище инициализировано")
    
    # Init health monitor
    health = init_health_monitor(check_interval_sec=5)
    health.start()
    print("[OK] Монитор состояния запущен")
    
    # Start telemetry simulation in background
    sim_thread = threading.Thread(target=simulate_telemetry, daemon=True)
    sim_thread.start()
    print("[OK] Симуляция телеметрии запущена")
    
    print("[OK] Web UI запускается на http://localhost:8080")
    print("=" * 60)
    print("Откройте http://localhost:8080 в браузере")
    print("Нажмите Ctrl+C для остановки")
    print("=" * 60)
    
    try:
        run_web_ui(host='127.0.0.1', port=8080, debug=False)
    except KeyboardInterrupt:
        print("\nЗавершение...")
    finally:
        health.stop()


if __name__ == '__main__':
    main()
