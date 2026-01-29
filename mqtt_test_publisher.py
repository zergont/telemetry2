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
import random
from datetime import datetime

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("paho-mqtt not installed. Run: pip install paho-mqtt")
    exit(1)


def create_payload(bserver_id: int, full_addr: str, data: list) -> dict:
    """Create a Modbus_PCC payload."""
    return {
        "Modbus_PCC": {
            "date_iso_8601": datetime.now().isoformat(),
            "bserver_id": bserver_id,
            "full_addr": full_addr,
            "data": json.dumps(data)
        },
        "gps_lat": 55.7558 + random.uniform(-0.001, 0.001),
        "gps_lon": 37.6173 + random.uniform(-0.001, 0.001)
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
    
    # Test data scenarios
    test_data = [
        # Battery Voltage (40061) - 12.3V
        (2, "400061", [123]),
        
        # Engine Operating State (46109) - Running
        (2, "406109", [4]),
        
        # Control Switch Position (40010) - Auto
        (2, "400010", [1]),
        
        # Genset Total kW (40034) - 150 kW
        (2, "400034", [150]),
        
        # Fault Bitmap (40400) - bit 0 set (Engine Magnetic Crankshaft)
        (2, "400400", [1]),
        
        # Engine Running Time (40070-40071) - 36000 * 0.1 = 3600 sec
        (2, "400070", [0, 36000]),
        
        # Multiple registers in one packet
        (2, "400018", [120, 121, 122]),  # L1N, L2N, L3N voltages
        
        # Panel 3 (different bserver_id)
        (3, "400061", [245]),  # 24.5V
        (3, "406109", [0]),    # Stopped
    ]
    
    print(f"\nPublishing test data to {topic}...")
    print("Press Ctrl+C to stop\n")
    
    try:
        cycle = 0
        while True:
            cycle += 1
            print(f"--- Cycle {cycle} ---")
            
            for bserver_id, full_addr, data in test_data:
                payload = create_payload(bserver_id, full_addr, data)
                msg = json.dumps(payload)
                
                result = client.publish(topic, msg)
                status = "OK" if result.rc == 0 else f"ERROR {result.rc}"
                
                print(f"  [{status}] bserver={bserver_id}, addr={full_addr}, data={data}")
                
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
