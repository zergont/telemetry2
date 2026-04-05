"""
Универсальный Modbus-декодер — Валидатор карт регистров

Проверяет файлы карт на корректность перед загрузкой.
Возвращает список ошибок с номерами строк.
"""

import json
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

# Допустимые значения
VALID_DATA_TYPES = {'u16', 'u32', 's16', 's32', 'f32', 'raw', 'char', 'bitfield'}
VALID_REG_TYPES = {'holding', 'input'}


def validate_register_map(filepath: str) -> List[str]:
    """
    Validate register_map.jsonl file.

    Returns list of error strings. Empty list = valid.
    """
    errors = []
    path = Path(filepath)

    if not path.exists():
        return [f"Файл не найден: {filepath}"]

    if path.stat().st_size == 0:
        return [f"Файл пуст: {filepath}"]

    count = 0
    seen_addrs = {}  # (reg_type, addr) -> line_num for duplicate detection

    with open(path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            # Parse JSON
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"Строка {line_num}: невалидный JSON — {e}")
                continue

            if not isinstance(entry, dict):
                errors.append(f"Строка {line_num}: ожидается объект, получен {type(entry).__name__}")
                continue

            # Required fields
            addr = entry.get('addr')
            if addr is None:
                errors.append(f"Строка {line_num}: отсутствует обязательное поле 'addr'")
                continue

            if not isinstance(addr, (int, float)) or addr != int(addr):
                errors.append(f"Строка {line_num}: 'addr' должен быть целым числом, получено {addr!r}")
                continue

            addr = int(addr)

            # reg_type
            reg_type = entry.get('reg_type', 'holding')
            if reg_type not in VALID_REG_TYPES:
                errors.append(f"Строка {line_num}: недопустимый reg_type '{reg_type}', "
                              f"допустимые: {', '.join(sorted(VALID_REG_TYPES))}")

            # data_type
            data_type = entry.get('data_type', 'u16')
            if data_type not in VALID_DATA_TYPES:
                errors.append(f"Строка {line_num}: недопустимый data_type '{data_type}', "
                              f"допустимые: {', '.join(sorted(VALID_DATA_TYPES))}")

            # word_len
            word_len = entry.get('word_len', 1)
            if not isinstance(word_len, (int, float)) or word_len < 1:
                errors.append(f"Строка {line_num}: word_len должен быть >= 1, получено {word_len!r}")

            # multiplier
            multiplier = entry.get('multiplier', 1.0)
            if not isinstance(multiplier, (int, float)):
                errors.append(f"Строка {line_num}: multiplier должен быть числом, получено {multiplier!r}")

            # offset
            offset = entry.get('offset', 0.0)
            if not isinstance(offset, (int, float)):
                errors.append(f"Строка {line_num}: offset должен быть числом, получено {offset!r}")

            # na_values
            na_values = entry.get('na_values', [])
            if not isinstance(na_values, list):
                errors.append(f"Строка {line_num}: na_values должен быть массивом, получено {type(na_values).__name__}")

            # Duplicate check
            key = (reg_type, addr)
            if key in seen_addrs:
                errors.append(f"Строка {line_num}: дубликат адреса {reg_type}:{addr} "
                              f"(первое вхождение: строка {seen_addrs[key]})")
            else:
                seen_addrs[key] = line_num

            count += 1

    if count == 0 and not errors:
        errors.append("Файл не содержит ни одного определения регистра")

    return errors


def validate_enum_map(filepath: str) -> List[str]:
    """
    Validate enum_map.json file.

    Returns list of error strings. Empty list = valid.
    """
    errors = []
    path = Path(filepath)

    if not path.exists():
        # enum_map is optional
        return []

    if path.stat().st_size == 0:
        return [f"Файл пуст: {filepath}"]

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return [f"Невалидный JSON: {e}"]

    if not isinstance(data, dict):
        return [f"Ожидается JSON-объект верхнего уровня, получен {type(data).__name__}"]

    for key, values in data.items():
        # Key format: "holding:40010"
        parts = key.split(':')
        if len(parts) != 2:
            errors.append(f"Ключ '{key}': неверный формат, ожидается 'reg_type:addr'")
            continue

        reg_type, addr_str = parts
        if reg_type not in VALID_REG_TYPES:
            errors.append(f"Ключ '{key}': недопустимый reg_type '{reg_type}'")

        try:
            int(addr_str)
        except ValueError:
            errors.append(f"Ключ '{key}': addr должен быть числом")

        if not isinstance(values, dict):
            errors.append(f"Ключ '{key}': значение должно быть объектом {{value: label}}, "
                          f"получен {type(values).__name__}")
            continue

        for val, label in values.items():
            if not isinstance(label, str):
                errors.append(f"Ключ '{key}', значение {val}: метка должна быть строкой")

    return errors


def validate_fault_bitmap_map(filepath: str) -> List[str]:
    """
    Validate fault_bitmap_map.jsonl file.

    Returns list of error strings. Empty list = valid.
    """
    errors = []
    path = Path(filepath)

    if not path.exists():
        # fault_bitmap_map is optional
        return []

    if path.stat().st_size == 0:
        return [f"Файл пуст: {filepath}"]

    count = 0
    with open(path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"Строка {line_num}: невалидный JSON — {e}")
                continue

            if not isinstance(entry, dict):
                errors.append(f"Строка {line_num}: ожидается объект")
                continue

            # Required fields
            addr = entry.get('addr')
            bit = entry.get('bit')

            if addr is None:
                errors.append(f"Строка {line_num}: отсутствует обязательное поле 'addr'")
            elif not isinstance(addr, (int, float)):
                errors.append(f"Строка {line_num}: 'addr' должен быть числом")

            if bit is None:
                errors.append(f"Строка {line_num}: отсутствует обязательное поле 'bit'")
            elif not isinstance(bit, (int, float)):
                errors.append(f"Строка {line_num}: 'bit' должен быть числом")
            elif int(bit) < 0 or int(bit) > 15:
                errors.append(f"Строка {line_num}: 'bit' должен быть от 0 до 15, получено {bit}")

            reg_type = entry.get('reg_type', 'holding')
            if reg_type not in VALID_REG_TYPES:
                errors.append(f"Строка {line_num}: недопустимый reg_type '{reg_type}'")

            count += 1

    return errors


def validate_device_maps(maps_dir: str) -> dict:
    """
    Validate all map files for a device.

    Returns dict:
    {
        'valid': bool,
        'register_map': {'errors': [...], 'count': N},
        'enum_map': {'errors': [...], 'count': N},
        'fault_bitmap_map': {'errors': [...], 'count': N}
    }
    """
    base = Path(maps_dir)

    reg_errors = validate_register_map(str(base / 'register_map.jsonl'))
    enum_errors = validate_enum_map(str(base / 'enum_map.json'))
    fault_errors = validate_fault_bitmap_map(str(base / 'fault_bitmap_map.jsonl'))

    # Count entries
    reg_count = _count_jsonl_entries(str(base / 'register_map.jsonl'))
    enum_count = _count_json_keys(str(base / 'enum_map.json'))
    fault_count = _count_jsonl_entries(str(base / 'fault_bitmap_map.jsonl'))

    all_errors = reg_errors + enum_errors + fault_errors

    return {
        'valid': len(all_errors) == 0,
        'total_errors': len(all_errors),
        'register_map': {'errors': reg_errors, 'count': reg_count},
        'enum_map': {'errors': enum_errors, 'count': enum_count},
        'fault_bitmap_map': {'errors': fault_errors, 'count': fault_count}
    }


def _count_jsonl_entries(filepath: str) -> int:
    """Count valid JSONL entries in file."""
    path = Path(filepath)
    if not path.exists():
        return 0
    count = 0
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    json.loads(line)
                    count += 1
                except json.JSONDecodeError:
                    pass
    return count


def _count_json_keys(filepath: str) -> int:
    """Count top-level keys in JSON file."""
    path = Path(filepath)
    if not path.exists():
        return 0
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return len(data) if isinstance(data, dict) else 0
    except (json.JSONDecodeError, OSError):
        return 0
