# Copyright (c) 2026 ООО «НГ-ЭНЕРГОСЕРВИС». Все права защищены.
# Программный комплекс «Честная Генерация»
# Модуль декодирования Modbus-телеметрии
# Автор: Саввиди Александр Анатольевич | ИНН 4725009270
#
# Данное программное обеспечение является конфиденциальным.
# Несанкционированное копирование, распространение или использование
# без письменного разрешения правообладателя запрещено.

"""
Fix remaining unnamed/misnamed fault bitmap registers:

  40422  FaultStatus Bitmap23           → Diesel Fault Bitmap 23
  40423  FaultStatus Bitmap24           → Diesel Fault Bitmap 24
  40424  FaultStatus Bitmap25           → Diesel Fault Bitmap 25
  40425  EventStatus Bitmap2            → Event Status Bitmap 2
  40426  EventStatus Bitmap3            → Event Status Bitmap 3
  40427  FaultStatus Bitmap26           → Diesel Fault Bitmap 26
  40428  FaultStatus Bitmap32 (garbled) → Diesel Fault Bitmap 32
  41400  FaultStatus (wrong notes_ru)   → AT Fault Status Bitmap 1

All set to unit='fault_bitmap' with bits={} (fill from PDF when available).
"""

import json
from pathlib import Path

MAP_FILE = Path(r"C:\Users\folis\source\repos\telemetry2\devices\pcc\map.jsonl")

UPDATES = {
    40422: {
        "name":     "Diesel Fault Bitmap 23",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок дизельного двигателя #23 (PC 3.x); биты см. PDF",
    },
    40423: {
        "name":     "Diesel Fault Bitmap 24",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок дизельного двигателя #24 (PC 3.x); биты см. PDF",
    },
    40424: {
        "name":     "Diesel Fault Bitmap 25",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок дизельного двигателя #25 (PC 3.x); биты см. PDF",
    },
    40425: {
        "name":     "Event Status Bitmap 2",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска событий #2 (PC 3.x); биты см. PDF",
    },
    40426: {
        "name":     "Event Status Bitmap 3",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска событий #3 (PC 3.x); биты см. PDF",
    },
    40427: {
        "name":     "Diesel Fault Bitmap 26",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок дизельного двигателя #26 (PC 3.x); биты см. PDF",
    },
    40428: {
        "name":     "Diesel Fault Bitmap 32",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок дизельного двигателя #32 (16-bit Diesel Fault Bitmap for Modbus interface, PC 3.x); биты см. PDF",
    },
    41400: {
        "name":     "AT Fault Status Bitmap 1",
        "unit":     "fault_bitmap",
        "notes_ru": "16-битная маска ошибок системы нейтрализации выхлопа #1 (PCC3300, PC 3.x); биты см. PDF",
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
        if 'bits' not in e:
            e['bits'] = {}
        updated += 1

    if skipped:
        print(f"WARNING: addresses not found: {skipped}")

    with open(MAP_FILE, 'w', encoding='utf-8', newline='\n') as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')

    print(f"Updated {updated} registers:")
    for addr in sorted(UPDATES):
        print(f"  addr={addr}: {UPDATES[addr]['name']}")

    # Quick stats
    entries_fresh = [json.loads(l) for l in open(MAP_FILE, encoding='utf-8') if l.strip()]
    bitmaps = [e for e in entries_fresh if e.get('unit') == 'fault_bitmap']
    with_bits = sum(1 for e in bitmaps if e.get('bits'))
    no_bits   = sum(1 for e in bitmaps if not e.get('bits'))
    print(f"\nfault_bitmap total: {len(bitmaps)}  with_bits: {with_bits}  no_bits/empty: {no_bits}")


if __name__ == '__main__':
    main()
