"""
Normalize dirty unit values in map.jsonl.
Artifacts: "gallons hasdifferentmultipliervalue." -> "gallons"
Also normalize case inconsistencies: "Hours" -> "hours", "RPM" canonical, etc.
"""

import json
import re
from pathlib import Path
from collections import Counter

MAP_FILE = Path(r"C:\Users\folis\source\repos\telemetry2\devices\pcc\map.jsonl")

# Known multi-word units (keep as-is if matched)
MULTI_WORD_UNITS = {'gal/hr', '%/Hz', 'RPM/Hz', '°C/s', 'Poundsperhour'}

# Case-normalization map: lowercase -> canonical
CASE_MAP = {
    'hours': 'hours',
    'minutes': 'minutes',
    'seconds': 'seconds',
    'sec': 'seconds',
    'msec': 'ms',
    'rpm': 'RPM',
    'percentage': '%',
    'amp': 'A',
    'na': '',
    'n/a': '',
    'none': '',
    '-': '',
    'faultcode': '',
    '28onpage488).': '',   # garbled — unit unknown, clear it
}

# Additional address-specific overrides
ADDR_UNIT_OVERRIDE = {
    # psig -> psi
}


def clean_unit(unit: str) -> str:
    if not unit:
        return ''

    stripped = unit.strip()

    # Check multi-word known units first
    if stripped in MULTI_WORD_UNITS:
        return stripped

    # Check exact known case variants
    lower = stripped.lower()
    if lower in CASE_MAP:
        return CASE_MAP[lower]

    # If unit contains space + garbage text, take only first token
    # e.g. "gallons hasdifferentmultipliervalue." -> "gallons"
    # e.g. "Hours stoppedgensetwillbe" -> "hours" (via CASE_MAP after split)
    if ' ' in stripped:
        first = stripped.split(' ')[0].strip()
        lower_first = first.lower()
        if lower_first in CASE_MAP:
            return CASE_MAP[lower_first]
        return first

    # Normalize case for known units (single-word)
    if lower in CASE_MAP:
        return CASE_MAP[lower]

    return stripped


def main():
    entries = []
    with open(MAP_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))

    changed = 0
    unit_changes = []
    for e in entries:
        old_unit = e.get('unit', '')
        new_unit = clean_unit(old_unit)
        if old_unit != new_unit:
            unit_changes.append((e['addr'], old_unit, new_unit))
            e['unit'] = new_unit
            changed += 1

    print(f"Changed {changed} unit values:")
    for addr, old, new in sorted(unit_changes, key=lambda x: x[0]):
        print(f"  addr={addr}: {old!r:45s} -> {new!r}")

    with open(MAP_FILE, 'w', encoding='utf-8', newline='\n') as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')

    print(f"\nWritten {len(entries)} entries")

    # Final unit distribution
    unit_c = Counter(e.get('unit') or '(empty)' for e in entries)
    print(f"\nFinal unit distribution (unique: {len(unit_c)}):")
    for u, cnt in sorted(unit_c.items(), key=lambda x: -x[1]):
        print(f"  {u:20s} {cnt}")


if __name__ == '__main__':
    main()
