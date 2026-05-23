"""
Fix remaining fault bitmap registers in map.jsonl:

1. 40757  Customer Faults (Modlon) — add unit='fault_bitmap', bits (16 bits, PC 3.x)
2. 41401  FaultStatus Bitmap33     → Diesel Fault Bitmap 33  + unit='fault_bitmap'
3. 41402  FaultStatus Bitmap34     → Diesel Fault Bitmap 34  + unit='fault_bitmap'
4. 41403-41409  ATFault StatusBitmap N → AT Fault Status Bitmap N + unit='fault_bitmap'
5. 41416  FaultStatus Bitmap35     → Diesel Fault Bitmap 35  + unit='fault_bitmap'
6. 41417  FaultStatus Bitmap36     → Diesel Fault Bitmap 36  + unit='fault_bitmap'
7. 41418  FaultStatus Bitmap37     → Diesel Fault Bitmap 37  + unit='fault_bitmap'

Bit definitions for 41401-41418 are left empty (bits: {}) — fill from PDF pages 390-399.
"""

import json
from pathlib import Path

MAP_FILE = Path(r"C:\Users\folis\source\repos\telemetry2\devices\pcc\map.jsonl")

# ---------------------------------------------------------------------------
# Bit definitions from PDF (PC 3.x documentation, PCC3300)
# ---------------------------------------------------------------------------

BITS_40757 = {
    # Customer Faults (Modlon) — PDF pages 388-389
    # Configurable inputs on Modlon I/O module + AUX 1010/1011 module faults
    "0":  {"name": "ConfigurableInput1Fault",    "severity": "none"},
    "1":  {"name": "ConfigurableInput2Fault",    "severity": "none"},
    "2":  {"name": "ConfigurableInput13Fault",   "severity": "none"},
    "3":  {"name": "ConfigurableInput14Fault",   "severity": "none"},
    "4":  {"name": "AUX1010Input1Fault",         "severity": "warning"},
    "5":  {"name": "AUX1010Input2Fault",         "severity": "warning"},
    "6":  {"name": "AUX1010Input3Fault",         "severity": "warning"},
    "7":  {"name": "AUX1010Input4Fault",         "severity": "warning"},
    "8":  {"name": "AUX1010Input5Fault",         "severity": "warning"},
    "9":  {"name": "AUX1010Input6Fault",         "severity": "warning"},
    "10": {"name": "AUX1010Input7Fault",         "severity": "warning"},
    "11": {"name": "AUX1010Input8Fault",         "severity": "warning"},
    "12": {"name": "AUX1011Input1Fault",         "severity": "warning"},
    "13": {"name": "AUX1011Input2Fault",         "severity": "warning"},
    "14": {"name": "AUX1011Input3Fault",         "severity": "warning"},
    "15": {"name": "AUX1011Input4Fault",         "severity": "warning"},
}

# 41401-41418 bits: TODO — fill from PDF pages 390-399 (PCC3300 Diesel/AT fault bitmaps)
# 41401: turbocharger, VGT, air filter, fuel filter, EGR, fan speed faults
# 41402: NOx limits, HPCR fuel pressure, fuel pump intake, fan speed errors
# 41403-41409: aftertreatment DEF/SCR/DOC faults (PCC3300 only)
# 41416-41418: water in fuel, battery, DPF, intake throttle, memory, ASO solenoid,
#              throttle driver, fail-to-stop, primary starting system faults

# ---------------------------------------------------------------------------
# Register update table
# ---------------------------------------------------------------------------

UPDATES = {
    40757: {
        "name":     "Customer Faults (Modlon)",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок клиентских входов и модулей AUX 1010/1011 (Modlon, PC 3.x)",
        "bits":     BITS_40757,
    },
    # Diesel Fault Bitmaps 33-34 (PCC3300, PDF pages 390-392)
    41401: {
        "name":     "Diesel Fault Bitmap 33",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок дизельного двигателя #33 (PCC3300, PC 3.x); биты см. PDF стр. 390-391",
        "bits":     {},
    },
    41402: {
        "name":     "Diesel Fault Bitmap 34",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок дизельного двигателя #34 (PCC3300, PC 3.x); биты см. PDF стр. 391-392",
        "bits":     {},
    },
    # AT (Aftertreatment) Fault Status Bitmaps 2-8 (PCC3300, PDF pages 392-396)
    41403: {
        "name":     "AT Fault Status Bitmap 2",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок системы нейтрализации выхлопа #2 (PCC3300, PC 3.x); биты см. PDF стр. 392-393",
        "bits":     {},
    },
    41404: {
        "name":     "AT Fault Status Bitmap 3",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок системы нейтрализации выхлопа #3 (PCC3300, PC 3.x); биты см. PDF стр. 393",
        "bits":     {},
    },
    41405: {
        "name":     "AT Fault Status Bitmap 4",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок системы нейтрализации выхлопа #4 (PCC3300, PC 3.x); биты см. PDF стр. 393-394",
        "bits":     {},
    },
    41406: {
        "name":     "AT Fault Status Bitmap 5",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок системы нейтрализации выхлопа #5 (PCC3300, PC 3.x); биты см. PDF стр. 394",
        "bits":     {},
    },
    41407: {
        "name":     "AT Fault Status Bitmap 6",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок системы нейтрализации выхлопа #6 (PCC3300, PC 3.x); биты см. PDF стр. 394-395",
        "bits":     {},
    },
    41408: {
        "name":     "AT Fault Status Bitmap 7",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок системы нейтрализации выхлопа #7 (PCC3300, PC 3.x); биты см. PDF стр. 395",
        "bits":     {},
    },
    41409: {
        "name":     "AT Fault Status Bitmap 8",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок системы нейтрализации выхлопа #8 (PCC3300, PC 3.x); биты см. PDF стр. 395-396",
        "bits":     {},
    },
    # Diesel Fault Bitmaps 35-37 (PCC3300, PDF pages 397-399)
    41416: {
        "name":     "Diesel Fault Bitmap 35",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок дизельного двигателя #35 (PCC3300, PC 3.x); биты см. PDF стр. 397",
        "bits":     {},
    },
    41417: {
        "name":     "Diesel Fault Bitmap 36",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок дизельного двигателя #36 (PCC3300, PC 3.x); биты см. PDF стр. 398",
        "bits":     {},
    },
    41418: {
        "name":     "Diesel Fault Bitmap 37",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок дизельного двигателя #37 (PCC3300, PC 3.x); биты см. PDF стр. 398-399",
        "bits":     {},
    },
}


def main():
    entries = []
    with open(MAP_FILE, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    idx_by_addr = {(e['reg_type'], e['addr']): i for i, e in enumerate(entries)}

    updated = 0
    skipped = []

    for addr, upd in UPDATES.items():
        key = ('holding', addr)
        if key not in idx_by_addr:
            skipped.append(addr)
            continue
        i = idx_by_addr[key]
        e = entries[i]
        e['name']     = upd['name']
        e['unit']     = upd['unit']
        e['notes_ru'] = upd['notes_ru']
        if upd['bits']:
            e['bits'] = upd['bits']
        elif 'bits' not in e:
            # Add empty bits dict so validator knows it's a bitmap
            e['bits'] = {}
        updated += 1

    if skipped:
        print(f"WARNING: addresses not found in map.jsonl: {skipped}")

    # Write back (preserve sort order: entries are already sorted by addr)
    with open(MAP_FILE, 'w', encoding='utf-8', newline='\n') as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')

    print(f"Updated {updated} registers:")
    for addr in sorted(UPDATES):
        bits_count = len(UPDATES[addr]['bits'])
        print(f"  addr={addr}: {UPDATES[addr]['name']}  (bits={bits_count})")

    # Verify
    addrs = set(UPDATES.keys())
    gas_entries = [e for e in entries if e['addr'] in addrs]
    print(f"\nVerification:")
    for e in gas_entries:
        print(f"  addr={e['addr']} unit={e.get('unit','')!r} bits={len(e.get('bits',{}))} name={e['name']}")


if __name__ == '__main__':
    main()
