# Copyright (c) 2026 ООО «НГ-ЭНЕРГОСЕРВИС». Все права защищены.
# Программный комплекс «Честная Генерация»
# Модуль декодирования Modbus-телеметрии
# Автор: Саввиди Александр Анатольевич | ИНН 4725009270
#
# Данное программное обеспечение является конфиденциальным.
# Несанкционированное копирование, распространение или использование
# без письменного разрешения правообладателя запрещено.

"""
Merge enum_map.json labels into map.jsonl.
Key format in enum_map.json: "holding:40010" -> {value_str: label}
"""

import json
import sys
from pathlib import Path

MAP_FILE  = Path(r"C:\Users\folis\source\repos\telemetry2\devices\pcc\map.jsonl")
ENUM_FILE = Path(r"C:\Users\folis\Downloads\enum_map.json")


def main():
    # Load enum map: {(reg_type, addr): {value_str: label}}
    with open(ENUM_FILE, 'r', encoding='utf-8-sig') as f:
        raw = json.load(f)

    enum_data = {}
    for key, labels in raw.items():
        parts = key.split(':')
        if len(parts) == 2:
            reg_type, addr_str = parts
            enum_data[(reg_type, int(addr_str))] = labels

    print(f"Loaded {len(enum_data)} enum definitions from {ENUM_FILE.name}")

    # Load and update map entries
    map_entries = []
    with open(MAP_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            map_entries.append(json.loads(line))

    merged = 0
    not_found = []

    for e in map_entries:
        key = (e['reg_type'], e['addr'])
        labels = enum_data.get(key)
        if labels:
            e['labels'] = labels
            merged += 1
        elif e.get('unit') == 'enum':
            not_found.append((e['reg_type'], e['addr'], e.get('name', '')))

    print(f"Merged labels into {merged} entries")

    if not_found:
        print(f"\n!!! {len(not_found)} unit='enum' entries with no labels:")
        for reg_type, addr, name in not_found[:20]:
            print(f"  {reg_type}:{addr} — {name}")

    # Write
    with open(MAP_FILE, 'w', encoding='utf-8', newline='\n') as f:
        for e in map_entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')

    print(f"\nWritten {len(map_entries)} entries to {MAP_FILE}")

    # Show sample
    print("\nSample enum entry:")
    for e in map_entries:
        if e.get('labels'):
            print(f"  addr={e['addr']}, name={e['name']}")
            for k, v in list(e['labels'].items())[:5]:
                print(f"    {k}: {v}")
            break


if __name__ == '__main__':
    main()
