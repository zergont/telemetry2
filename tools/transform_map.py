"""
Transform register_map.jsonl -> map.jsonl (unified format)

Rules:
- Skip "Lo Word" entries (dedup for u32/s32 pairs)
- data_type: sign=C -> cNNN (size_bits from PDF); otherwise keep existing; raw -> u16
- word_len: u32/s32/f32/u32_le -> 2; cNNN -> count actual consecutive same-name regs; else 1
- Remove: access, size_bits, sign, group, description, notes, source
- Clean name: strip " Hi Word", " (Hi Word)", " High Register" suffixes
  (strip char index suffix from notes_ru for the first char entry)
- Keep: addr, reg_type, name, data_type, word_len, multiplier, offset, unit, na_values, notes_ru, labels, bits
"""

import json
import re
import sys
from pathlib import Path
from collections import Counter

INPUT = Path(r"C:\Users\folis\Downloads\JSON\register_map.jsonl")
OUTPUT = Path(r"C:\Users\folis\source\repos\telemetry2\devices\pcc\map.jsonl")

NAME_SUFFIX_RE = re.compile(
    r'\s+(?:Hi\s*Word|High\s+Register|Hi\s+Register)\s*$',
    re.IGNORECASE
)

SKIP_NAME_RE = re.compile(
    r'\b(?:Lo\s*Word|Low\s+Register|Lo\s+Register)\b',
    re.IGNORECASE
)

# Strip "символ N/M" and "char N/M" artifacts from notes_ru for string first entry
CHAR_IDX_RE = re.compile(r'\s*[—–-]\s*символ\s+\d+/\d+\b.*', re.IGNORECASE)

UNIT_NORMALIZE = {
    'na': '', 'n/a': '', 'none': '', '-': '',
    'seconds': 'seconds',  # keep lowercase canonical
    'degrees': 'deg',
}


def normalize_unit(unit: str) -> str:
    if unit is None:
        return ''
    u = unit.strip()
    lower = u.lower()
    if lower in UNIT_NORMALIZE:
        return UNIT_NORMALIZE[lower]
    return u


def make_data_type(entry: dict) -> str:
    sign = entry.get('sign', 'U')
    size_bits = entry.get('size_bits', 16)
    data_type = entry.get('data_type', 'u16')

    if sign == 'C' or data_type in ('char', 'string'):
        return f"c{size_bits}" if size_bits else 'c168'

    if data_type == 'raw':
        return 'u16'

    return data_type


def is_string_type(data_type: str) -> bool:
    return data_type.startswith('c') and data_type[1:].isdigit()


def word_len_for_type(data_type: str) -> int:
    if data_type in ('u32', 's32', 'f32', 'u32_le'):
        return 2
    # string: determined by collapsing (set later)
    return 1


def build_entry(raw: dict, data_type: str, word_len: int, notes_ru_override: str = None) -> dict:
    clean_name = NAME_SUFFIX_RE.sub('', raw.get('name', '')).strip()
    unit = normalize_unit(raw.get('unit', ''))

    notes_ru = notes_ru_override if notes_ru_override is not None else raw.get('notes_ru', '')
    # Clean char index from notes_ru
    if notes_ru:
        notes_ru = CHAR_IDX_RE.sub('', notes_ru).strip()
        notes_ru = notes_ru.rstrip('.')  # strip trailing dot left after removal

    out = {
        'addr': raw['addr'],
        'reg_type': raw.get('reg_type', 'holding'),
        'name': clean_name,
        'data_type': data_type,
        'word_len': word_len,
        'multiplier': raw.get('multiplier', 1.0),
        'offset': raw.get('offset', 0.0),
        'unit': unit,
        'na_values': raw.get('na_values', []),
    }

    if notes_ru:
        out['notes_ru'] = notes_ru

    labels = raw.get('labels')
    if labels:
        out['labels'] = labels

    bits_def = raw.get('bits')
    if bits_def:
        out['bits'] = bits_def

    return out


# Expected word_len per string data_type (from Cummins PDF register groups)
EXPECTED_STR_WORD_LEN = {
    'c168': 20,
    'c144': 17,
    'c136': 16,
}


def merge_adjacent_strings(entries: list) -> tuple[list, int]:
    """
    Second pass: merge adjacent string fragments of the same data_type
    if their total word_len exactly matches EXPECTED_STR_WORD_LEN.
    Uses name from the first fragment.
    Returns (merged_entries, count_absorbed).
    """
    merged = []
    i = 0
    absorbed = 0

    while i < len(entries):
        e = entries[i]
        dt = e['data_type']
        expected = EXPECTED_STR_WORD_LEN.get(dt)

        if expected and 0 < e['word_len'] < expected:
            # Try absorbing consecutive same-type fragments
            group = [e]
            total_wl = e['word_len']
            j = i + 1

            while j < len(entries) and total_wl < expected:
                nxt = entries[j]
                expected_addr = group[-1]['addr'] + group[-1]['word_len']
                if (nxt['data_type'] == dt
                        and nxt['reg_type'] == e['reg_type']
                        and nxt['addr'] == expected_addr):
                    group.append(nxt)
                    total_wl += nxt['word_len']
                    j += 1
                else:
                    break

            if total_wl == expected:
                # Merge into one entry using first fragment's data
                e_merged = dict(e)
                e_merged['word_len'] = expected
                merged.append(e_merged)
                absorbed += (len(group) - 1)
                i = j
            else:
                # Can't cleanly merge — keep as-is
                merged.append(e)
                i += 1
        else:
            merged.append(e)
            i += 1

    return merged, absorbed


def main():
    if not INPUT.exists():
        print(f"ERROR: Input file not found: {INPUT}", file=sys.stderr)
        sys.exit(1)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    # ── Phase 1: read & pre-transform all entries ──────────────────────────
    raw_entries = []
    total_in = 0

    with open(INPUT, 'r', encoding='utf-8-sig') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            total_in += 1
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  WARN line {line_num}: JSON error: {e}")
                continue

            if SKIP_NAME_RE.search(entry.get('name', '')):
                continue  # skip Lo Word

            entry['_data_type'] = make_data_type(entry)
            raw_entries.append(entry)

    # Sort by (reg_type, addr) — holding first
    raw_entries.sort(key=lambda e: (0 if e.get('reg_type', 'holding') == 'holding' else 1, e['addr']))

    # ── Phase 2: collapse string runs ──────────────────────────────────────
    results = []
    skipped_lo = total_in - len(raw_entries)  # already counted above
    skipped_string_chars = 0

    i = 0
    while i < len(raw_entries):
        e = raw_entries[i]
        dt = e['_data_type']

        if is_string_type(dt):
            # Collect consecutive registers with same name, reg_type, data_type
            reg_type = e.get('reg_type', 'holding')
            name = e.get('name', '')
            group = [e]
            j = i + 1
            while j < len(raw_entries):
                nxt = raw_entries[j]
                if (nxt.get('reg_type', 'holding') == reg_type
                        and nxt.get('name', '') == name
                        and nxt['_data_type'] == dt
                        and nxt['addr'] == group[-1]['addr'] + 1):
                    group.append(nxt)
                    j += 1
                else:
                    break

            word_len = len(group)
            # Use notes_ru from first entry (with char index stripped)
            entry_out = build_entry(e, dt, word_len)
            results.append(entry_out)
            skipped_string_chars += (word_len - 1)
            i = j  # skip the rest of the group
        else:
            wl = word_len_for_type(dt)
            results.append(build_entry(e, dt, wl))
            i += 1

    # Sort final by (reg_type, addr)
    results.sort(key=lambda e: (0 if e['reg_type'] == 'holding' else 1, e['addr']))

    # Phase 3: merge adjacent undersized string fragments
    results, str_absorbed = merge_adjacent_strings(results)
    skipped_string_chars += str_absorbed

    # Check duplicates
    seen = {}
    dupes = []
    for idx, e in enumerate(results):
        k = (e['reg_type'], e['addr'])
        if k in seen:
            dupes.append((k, e['name'], results[seen[k]]['name']))
        else:
            seen[k] = idx

    # ── Write output ───────────────────────────────────────────────────────
    with open(OUTPUT, 'w', encoding='utf-8', newline='\n') as f:
        for e in results:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')

    # ── Stats ──────────────────────────────────────────────────────────────
    dtype_counter = Counter(e['data_type'] for e in results)
    unit_counter = Counter(e['unit'] or '(empty)' for e in results)

    print(f"\n=== Transform complete ===")
    print(f"Input total lines:      {total_in}")
    print(f"Skipped Lo Word:        {skipped_lo}")
    print(f"Collapsed string chars: {skipped_string_chars}")
    print(f"Output registers:       {len(results)} -> {OUTPUT}")

    print(f"\n--- data_type distribution ---")
    for dt, cnt in sorted(dtype_counter.items(), key=lambda x: -x[1]):
        print(f"  {dt:15s} {cnt}")

    print(f"\n--- unit distribution (top 25) ---")
    for u, cnt in sorted(unit_counter.items(), key=lambda x: -x[1])[:25]:
        print(f"  {u:20s} {cnt}")

    if dupes:
        print(f"\n!!! {len(dupes)} DUPLICATES:")
        for k, name, prev in dupes[:20]:
            print(f"  {k}: '{name}' vs '{prev}'")
    else:
        print(f"\nNo duplicates.")

    # Show sample string entries
    print(f"\n--- Sample string entries ---")
    for e in results:
        if e['data_type'].startswith('c'):
            print(f"  addr={e['addr']}, dt={e['data_type']}, word_len={e['word_len']}, "
                  f"name={e['name'][:50]}")
            # only first 3
            count_shown = getattr(main, '_str_shown', 0) + 1
            main._str_shown = count_shown
            if count_shown >= 5:
                break


if __name__ == '__main__':
    main()
