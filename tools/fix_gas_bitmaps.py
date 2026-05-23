"""
Fix Gas Bitmap registers in map.jsonl:
1. Rename 40431-40439 and 40471-40494: "FaultStatus" -> "Fault Status Gas Bitmap N"
2. Add missing 40440-40470 (Gas Bitmap 10-40)
3. Set unit='fault_bitmap' for all 40431-40494
4. Update notes_ru
"""

import json
from pathlib import Path

MAP_FILE = Path(r"C:\Users\folis\source\repos\telemetry2\devices\pcc\map.jsonl")

GAS_BITMAP_START = 40431
GAS_BITMAP_END   = 40494  # inclusive
GAS_BITMAP_COUNT = GAS_BITMAP_END - GAS_BITMAP_START + 1  # 64

def gas_bitmap_num(addr):
    return addr - GAS_BITMAP_START + 1  # 1-based

def main():
    # Load map
    entries = []
    with open(MAP_FILE, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    existing_addrs = {(e['reg_type'], e['addr']): i for i, e in enumerate(entries)}

    updated = 0
    added = 0

    # 1. Update existing entries 40431-40439 and 40471-40494
    for addr in list(range(40431, 40440)) + list(range(40471, 40495)):
        key = ('holding', addr)
        if key in existing_addrs:
            idx = existing_addrs[key]
            n = gas_bitmap_num(addr)
            entries[idx]['name'] = f"Fault Status Gas Bitmap {n}"
            entries[idx]['unit'] = 'fault_bitmap'
            entries[idx]['notes_ru'] = f"16-битная маска ошибок газового двигателя #{n} (PC 3.x)"
            entries[idx].pop('na_values', None)
            entries[idx]['na_values'] = []
            updated += 1

    # 2. Add missing 40440-40470
    for addr in range(40440, 40471):
        key = ('holding', addr)
        if key not in existing_addrs:
            n = gas_bitmap_num(addr)
            entry = {
                'addr': addr,
                'reg_type': 'holding',
                'name': f"Fault Status Gas Bitmap {n}",
                'data_type': 'u16',
                'word_len': 1,
                'multiplier': 1.0,
                'offset': 0.0,
                'unit': 'fault_bitmap',
                'na_values': [],
                'notes_ru': f"16-битная маска ошибок газового двигателя #{n} (PC 3.x)",
            }
            entries.append(entry)
            added += 1

    # Sort by (reg_type, addr)
    entries.sort(key=lambda e: (0 if e['reg_type'] == 'holding' else 1, e['addr']))

    # Write
    with open(MAP_FILE, 'w', encoding='utf-8', newline='\n') as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')

    print(f"Updated:  {updated} existing Gas Bitmap entries")
    print(f"Added:    {added} new Gas Bitmap entries (40440-40470)")
    print(f"Total:    {len(entries)} entries in map.jsonl")

    # Verify
    gas = [e for e in entries if GAS_BITMAP_START <= e['addr'] <= GAS_BITMAP_END]
    print(f"\nGas Bitmap range 40431-40494: {len(gas)} entries")
    print(f"  unit='fault_bitmap': {sum(1 for e in gas if e['unit']=='fault_bitmap')}")
    print(f"  Missing: {sorted(set(range(GAS_BITMAP_START, GAS_BITMAP_END+1)) - {e['addr'] for e in gas})}")

    # Show sample
    print("\nSample (first 3 + last 3):")
    for e in gas[:3] + gas[-3:]:
        print(f"  addr={e['addr']}, name={e['name']}, unit={e['unit']}")

if __name__ == '__main__':
    main()
