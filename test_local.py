#!/usr/bin/env python3
"""
Local Test Script

Simulates data flow without MQTT for local testing.
Populates the panel store with test data and starts web UI.

Usage:
    python test_local.py
"""

import logging
import threading
import time
import json
import sys

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
    
    logger.info("Starting telemetry simulation...")
    
    while True:
        for router_sn, bserver_id, full_addr, data in test_packets:
            # Decode
            decoded = decoder.decode_packet(full_addr, data)
            
            # Update store
            store.update_panel(
                router_sn=router_sn,
                bserver_id=bserver_id,
                decoded_registers=decoded,
                gps_lat=55.7558 + (hash(router_sn) % 100) / 10000,
                gps_lon=37.6173 + (hash(router_sn) % 100) / 10000,
                gps_time="2026-01-27T22:00:00+0300"
            )
        
        logger.info(f"Simulated {len(test_packets)} packets")
        time.sleep(5)


def main():
    print("=" * 60)
    print("Universal Modbus Decoder - Local Test Mode")
    print("=" * 60)
    
    # Load maps
    ok = load_all_maps(
        'maps/register_map.jsonl',
        'maps/enum_map.json',
        'maps/fault_bitmap_map.jsonl'
    )
    if not ok:
        print("[FAIL] Failed to load maps")
        return
    print("[OK] Maps loaded")
    
    # Init store
    store = init_store(stale_threshold_sec=10, offline_threshold_sec=30)
    print("[OK] Store initialized")
    
    # Init health monitor
    health = init_health_monitor(check_interval_sec=5)
    health.start()
    print("[OK] Health monitor started")
    
    # Start telemetry simulation in background
    sim_thread = threading.Thread(target=simulate_telemetry, daemon=True)
    sim_thread.start()
    print("[OK] Telemetry simulation started")
    
    print("[OK] Starting web UI on http://localhost:8080")
    print("=" * 60)
    print("Open http://localhost:8080 in your browser")
    print("Press Ctrl+C to stop")
    print("=" * 60)
    
    try:
        run_web_ui(host='127.0.0.1', port=8080, debug=False)
    except KeyboardInterrupt:
        print("\nShutdown...")
    finally:
        health.stop()


if __name__ == '__main__':
    main()
