"""
Add missing fault bitmap registers (40400-40415, 40420) to map.jsonl.
These registers exist in fault_bitmap_map but were absent from register_map.jsonl.
They are "Active Fault Bitmap" registers in Cummins PCC3.3 Modbus.
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

MAP_FILE   = Path(r"C:\Users\folis\source\repos\telemetry2\devices\pcc\map.jsonl")
FAULT_FILE = Path(r"C:\Users\folis\Downloads\fault_bitmap_map (3)_fixed.jsonl")

# Missing registers: (addr, name)
MISSING_REGS = [
    (40400, "Active Fault Bitmap 1"),
    (40401, "Active Fault Bitmap 2"),
    (40402, "Active Fault Bitmap 3"),
    (40403, "Active Fault Bitmap 4"),
    (40404, "Active Fault Bitmap 5"),
    (40405, "Active Fault Bitmap 6"),
    (40406, "Active Fault Bitmap 7"),
    (40407, "Active Fault Bitmap 8"),
    (40408, "Active Fault Bitmap 9"),
    (40409, "Active Fault Bitmap 10"),
    (40410, "Active Fault Bitmap 11"),
    (40411, "Active Fault Bitmap 12"),
    (40412, "Active Fault Bitmap 13"),
    (40413, "Active Fault Bitmap 14"),
    (40414, "Active Fault Bitmap 15"),
    (40415, "Active Fault Bitmap 16"),
    (40420, "Customer Input Fault Status"),
]

def main():
    # Load fault bitmap data for missing addresses
    missing_addrs = {addr for addr, _ in MISSING_REGS}
    fault_data: dict[int, dict] = defaultdict(dict)

    with open(FAULT_FILE, 'r', encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                addr = e.get('addr')
                if addr in missing_addrs:
                    bit = int(e.get('bit', 0))
                    name = e.get('name', '')
                    severity = e.get('severity', 'none')
                    bit_def = {'name': name}
                    if severity and severity != 'none':
                        bit_def['severity'] = severity
                    fault_data[addr][bit] = bit_def
            except Exception as ex:
                pass

    # Load existing map
    map_entries = []
    map_addrs = set()
    with open(MAP_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            map_entries.append(e)
            map_addrs.add((e['reg_type'], e['addr']))

    print(f"Loaded {len(map_entries)} existing entries")

    # Build new entries
    new_entries = []
    for addr, name in MISSING_REGS:
        if ('holding', addr) in map_addrs:
            print(f"  SKIP (already exists): {addr}")
            continue

        bits = fault_data.get(addr, {})
        entry = {
            'addr': addr,
            'reg_type': 'holding',
            'name': name,
            'data_type': 'u16',
            'word_len': 1,
            'multiplier': 1.0,
            'offset': 0.0,
            'unit': 'fault_bitmap',
            'na_values': [],
        }
        if bits:
            entry['bits'] = {str(b): bits[b] for b in sorted(bits)}

        new_entries.append(entry)
        print(f"  Adding: addr={addr}, name={name}, bits={len(bits)}")

    # Merge and sort
    all_entries = map_entries + new_entries
    all_entries.sort(key=lambda e: (0 if e['reg_type'] == 'holding' else 1, e['addr']))

    # Write
    with open(MAP_FILE, 'w', encoding='utf-8', newline='\n') as f:
        for e in all_entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')

    print(f"\nAdded {len(new_entries)} new registers")
    print(f"Total entries: {len(all_entries)}")


if __name__ == '__main__':
    main()
