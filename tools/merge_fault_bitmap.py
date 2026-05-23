"""
Merge fault_bitmap_map.jsonl into map.jsonl (unified format).

For each fault entry (reg_type, addr, bit) -> {name, severity}:
  - Find matching register in map.jsonl by (reg_type, addr)
  - Add/update the 'bits' field
  - Set unit = 'fault_bitmap' for those registers

Fields taken from fault bitmap:  name, severity  (description is dropped)
"""

import json
import sys
from pathlib import Path
from collections import defaultdict, Counter

MAP_FILE   = Path(r"C:\Users\folis\source\repos\telemetry2\devices\pcc\map.jsonl")
FAULT_FILE = Path(r"C:\Users\folis\Downloads\fault_bitmap_map (3)_fixed.jsonl")


def main():
    if not MAP_FILE.exists():
        print(f"ERROR: {MAP_FILE} not found", file=sys.stderr)
        sys.exit(1)
    if not FAULT_FILE.exists():
        print(f"ERROR: {FAULT_FILE} not found", file=sys.stderr)
        sys.exit(1)

    # ── Load fault bitmap ──────────────────────────────────────────────────
    # Structure: {(reg_type, addr): {bit_int: {name, severity}}}
    fault_data: dict[tuple, dict[int, dict]] = defaultdict(dict)
    fault_count = 0
    unknown_addrs = set()

    with open(FAULT_FILE, 'r', encoding='utf-8-sig') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError as ex:
                print(f"  FAULT WARN line {line_num}: {ex}")
                continue

            reg_type = e.get('reg_type', 'holding')
            addr = e.get('addr')
            bit = e.get('bit')
            name = e.get('name', '')
            severity = e.get('severity', 'none')

            if addr is None or bit is None:
                print(f"  FAULT WARN line {line_num}: missing addr or bit")
                continue

            bit_def = {'name': name}
            if severity and severity != 'none':
                bit_def['severity'] = severity

            fault_data[(reg_type, int(addr))][int(bit)] = bit_def
            fault_count += 1

    print(f"Loaded {fault_count} fault bits across {len(fault_data)} addresses from {FAULT_FILE.name}")

    # ── Load map.jsonl ─────────────────────────────────────────────────────
    map_entries = []
    map_index: dict[tuple, int] = {}   # (reg_type, addr) -> index

    with open(MAP_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            idx = len(map_entries)
            map_entries.append(e)
            map_index[(e['reg_type'], e['addr'])] = idx

    print(f"Loaded {len(map_entries)} entries from {MAP_FILE.name}")

    # ── Merge ──────────────────────────────────────────────────────────────
    merged_count = 0
    not_found = []

    for (reg_type, addr), bits in fault_data.items():
        key = (reg_type, addr)
        if key in map_index:
            idx = map_index[key]
            e = map_entries[idx]
            # Sort bits by bit number
            e['bits'] = {str(b): bits[b] for b in sorted(bits)}
            e['unit'] = 'fault_bitmap'
            map_entries[idx] = e
            merged_count += 1
        else:
            not_found.append((reg_type, addr))
            unknown_addrs.add(addr)

    print(f"\nMerged fault bits into {merged_count} register entries")

    if not_found:
        print(f"\n!!! {len(not_found)} fault addresses NOT found in map.jsonl:")
        for reg_type, addr in sorted(not_found, key=lambda x: x[1]):
            print(f"  {reg_type}:{addr}")

    # ── Write output ───────────────────────────────────────────────────────
    with open(MAP_FILE, 'w', encoding='utf-8', newline='\n') as f:
        for e in map_entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')

    print(f"\nWritten {len(map_entries)} entries to {MAP_FILE}")

    # ── Stats ──────────────────────────────────────────────────────────────
    fault_entries = [e for e in map_entries if e.get('unit') == 'fault_bitmap']
    total_bits = sum(len(e.get('bits', {})) for e in fault_entries)
    sev_counter = Counter()
    for e in fault_entries:
        for bit_def in e.get('bits', {}).values():
            sev = bit_def.get('severity', 'none')
            sev_counter[sev] += 1

    print(f"\nFault bitmap registers: {len(fault_entries)}")
    print(f"Total bits defined:     {total_bits}")
    print(f"Severity distribution:  {dict(sorted(sev_counter.items()))}")

    # Show sample
    print("\nSample fault register:")
    for e in fault_entries[:1]:
        print(f"  addr={e['addr']}, name={e['name']}")
        for bit_str, bd in list(e['bits'].items())[:4]:
            print(f"    bit {bit_str}: {bd}")


if __name__ == '__main__':
    main()
