#!/usr/bin/env python3
"""
MQTT Test Publisher

Simulates raw Modbus telemetry for testing the decoder.
Publishes to cg/v1/telemetry/SN/<router_sn>

Usage:
    python mqtt_test_publisher.py [--host localhost] [--port 1883]
"""

import argparse
import json
import time
from datetime import datetime

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("paho-mqtt not installed. Run: pip install paho-mqtt")
    exit(1)


def create_payload(server_id: int, addr: int, data: list) -> dict:
    """Create a payload in real broker format (input2)."""
    return {
        "input2": {
            "date_iso_8601": datetime.now().isoformat(),
            "server_id": server_id,
            "addr": addr,
            "data": json.dumps(data)
        }
    }


def main():
    parser = argparse.ArgumentParser(description='MQTT Test Publisher')
    parser.add_argument('--host', default='localhost', help='MQTT broker host')
    parser.add_argument('--port', type=int, default=1883, help='MQTT broker port')
    parser.add_argument('--router', default='TEST-ROUTER-001', help='Router SN')
    args = parser.parse_args()
    
    client = mqtt.Client(client_id="test-publisher", protocol=mqtt.MQTTv5)
    
    try:
        print(f"Connecting to {args.host}:{args.port}...")
        client.connect(args.host, args.port)
        client.loop_start()
        print("Connected!")
    except Exception as e:
        print(f"Failed to connect: {e}")
        return
    
    topic = f"cg/v1/telemetry/SN/{args.router}"
    
    # Test data scenarios: (server_id, addr_offset, data_words)
    test_data = [
        # Battery Voltage (40061) - 26.2V
        (1, 61, [262]),
        
        # Engine Operating State (46109) - Running
        (1, 6109, [4]),
        
        # Control Switch Position (40010) - Auto
        (1, 10, [1]),
        
        # Genset Total kW (40034) - 150 kW
        (1, 34, [150]),
        
        # Engine Running Time (40070-40071) - multiword u32
        (1, 70, [0, 36000]),
        
        # Genset registers (40025-40044)
        (1, 25, [0, 0, 0, 0, 0, 65535, 0, 0, 0, 0, 0, 0, 0, 0, 100, 0, 0, 0, 0, 0]),
        
        # Panel registers (40563+)
        (1, 563, [1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 50000, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 65535, 0, 0, 65535, 0, 0]),
    ]
    
    print(f"\nPublishing test data to {topic}...")
    print("Press Ctrl+C to stop\n")
    
    try:
        cycle = 0
        while True:
            cycle += 1
            print(f"--- Cycle {cycle} ---")
            
            for server_id, addr, data in test_data:
                payload = create_payload(server_id, addr, data)
                msg = json.dumps(payload)
                
                result = client.publish(topic, msg)
                status = "OK" if result.rc == 0 else f"ERROR {result.rc}"
                
                print(f"  [{status}] server={server_id}, addr={addr}, words={len(data)}")
                
                time.sleep(0.5)
            
            print(f"\nWaiting 5 seconds before next cycle...\n")
            time.sleep(5)
            
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == '__main__':
    main()
