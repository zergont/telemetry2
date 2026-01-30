# Universal Modbus Decoder & Web UI

A server application that:
- Receives raw Modbus telemetry via MQTT
- Decodes data using external register maps (no hardcoded registers)
- Publishes decoded data to a separate MQTT topic
- Displays data through a simple Web UI
- Works in-memory (no database)

Designed for Cummins PCC but architecture is universal.

## Features

- **Dynamic panel discovery** - panels are discovered from incoming messages
- **Health monitoring** - panels marked as `stale` (>10s) or `offline` (>60s)
- **MQTT auto-reconnect** - automatic reconnection on connection loss
- **External register maps** - all decoding logic from JSONL/JSON files
- **Simple Web UI** - view routers, panels, and decoded registers
- **Debug mode** - verbose logging for troubleshooting

## Requirements

- Python 3.10+
- MQTT broker (e.g., Mosquitto)

## Installation on Ubuntu

### 1. Clone the repository

```bash
git clone https://github.com/zergont/telemetry2.git
cd telemetry2
```

### 2. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure

```bash
cp config.example.yaml config.yaml
nano config.yaml
```

Edit the configuration file:

- Set `mqtt.host` to your MQTT broker address
- Set `mqtt.port` (default: 1883)
- Set `mqtt.username` and `mqtt.password` if authentication is required
- Set `web.port` for the Web UI (default: 8080)
- Set `mode` to `debug` for verbose logging

### 5. Run

```bash
python app.py
```

Or with a custom config file:

```bash
python app.py --config /path/to/config.yaml
```

## Running as a Service (systemd)

Create `/etc/systemd/system/telemetry2.service`:

```ini
[Unit]
Description=Universal Modbus Decoder (telemetry2)
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/opt/telemetry2
Environment="PATH=/opt/telemetry2/venv/bin"
ExecStart=/opt/telemetry2/venv/bin/python app.py --config /opt/telemetry2/config.yaml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable telemetry2
sudo systemctl start telemetry2
```

## MQTT Topics

### RAW (input)

```
cg/v1/telemetry/SN/<router_sn>
```

Payload format:
```json
{
  "Modbus_PCC": {
    "date_iso_8601": "2026-01-27T21:59:49+0300",
    "bserver_id": 2,
    "full_addr": "406109",
    "data": "[0]"
  }
}
```

### DECODED (output)

```
cg/v1/decoded/SN/<router_sn>/pcc/<bserver_id>
```

Payload format:
```json
{
  "timestamp": "2026-01-27T21:59:49+0300",
  "router_sn": "SN123456",
  "bserver_id": 2,
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

> **Decoding rule:** If a register cannot be decoded → `value = null`, `raw = <number>`.

## Register Maps

All decoding logic is in external files (no hardcoded registers):

| File | Format | Description |
|------|--------|-------------|
| `maps/register_map.jsonl` | JSONL | Register definitions (address, type, multiplier, etc.) |
| `maps/enum_map.json` | JSON | Enum value-to-label mappings |
| `maps/fault_bitmap_map.jsonl` | JSONL | Fault bitmap bit definitions |

### Address Decoding

From `full_addr`:
- First character: region type (`4` = holding, `3` = input)
- Last 5 digits: offset (leading zeros preserved, e.g., `03560` → `3560`)
- Address = 40000 + offset

Examples:
- `"406109"` → offset `06109` → address `46109`
- `"403560"` → offset `03560` → address `43560`

### Data Types

| Type | Description | Words |
|------|-------------|-------|
| `u16` | Unsigned 16-bit | 1 |
| `s16` | Signed 16-bit | 1 |
| `u32` | Unsigned 32-bit (big-endian) | 2 |
| `s32` | Signed 32-bit | 2 |
| `f32` | IEEE754 float | 2 |
| `enum` | Enum value | 1 |
| `bitfield` | Bitmap | 1 |

### Multiword Registers (Variant B)

- 32-bit values published as single entry at base address
- Tail registers not published

## Operating Modes

### Production (default)

```yaml
mode: "production"
logging:
  level: "INFO"
```

- Minimal logging
- No debug information in decoded output

### Debug

```yaml
mode: "debug"
logging:
  level: "DEBUG"
```

- Verbose logging
- Raw input/output in logs
- Decode failure reasons included

## Web UI

Access at `http://localhost:8080` (or configured port).

### Pages

- **Dashboard** (`/`) - List of routers, panels, MQTT stats
- **Panel** (`/router/<sn>/panel/<id>`) - Register table for a panel

### API Endpoints

- `GET /api/stats` - System statistics
- `GET /api/routers` - List of routers
- `GET /api/router/<sn>/panel/<id>/registers` - Panel registers as JSON

## Health Monitoring

| Status | Condition |
|--------|-----------|
| `online` | Message within last 10 seconds |
| `stale` | No message for 10-60 seconds |
| `offline` | No message for 60+ seconds |

Thresholds are configurable in `config.yaml`.

## Project Structure

```
telemetry2/
├── app.py              # Main entry point
├── decoder.py          # Modbus decoder logic
├── maps_loader.py      # Register map loader
├── mqtt_client.py      # MQTT client
├── panel_store.py      # In-memory panel store
├── health_monitor.py   # Health monitoring
├── web_ui.py           # Flask web UI
├── config.yaml         # Configuration (not in git)
├── config.example.yaml # Example configuration
├── requirements.txt    # Python dependencies
├── .gitignore          # Git ignore rules
├── test_local.py       # Local test without MQTT
├── mqtt_test_publisher.py # Test MQTT publisher
└── maps/
    ├── register_map.jsonl
    ├── enum_map.json
    └── fault_bitmap_map.jsonl
```

## License

MIT

## Support

For issues or questions, please open a GitHub issue.
