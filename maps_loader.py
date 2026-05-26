"""
Универсальный Modbus-декодер — Загрузчик карт регистров

Загружает карты регистров, enum и fault bitmap из внешних файлов.
Поддерживает несколько типов устройств, каждый со своим набором карт.
Хардкод регистров запрещён — все данные из файлов.
"""

import json
import logging
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple, List

logger = logging.getLogger(__name__)

# ================================================================
# Label translations (EN → RU), общий для всех device_type
# ================================================================
_TRANSLATIONS_FILE = Path("devices/label_translations.json")
_label_translations: Dict[str, str] = {}
_translations_lock = threading.Lock()


def load_label_translations(filepath: Optional[str] = None) -> int:
    """Загрузить словарь переводов enum-меток из JSON-файла.
    Возвращает количество загруженных переводов."""
    global _label_translations
    path = Path(filepath) if filepath else _TRANSLATIONS_FILE
    if not path.exists():
        logger.warning(f"Файл переводов не найден: {path}")
        return 0
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        # Фильтруем служебный ключ _comment
        translations = {k: v for k, v in data.items() if not k.startswith('_')}
        with _translations_lock:
            _label_translations = translations
        logger.info(f"Загружено {len(translations)} переводов меток из {path}")
        return len(translations)
    except Exception as e:
        logger.error(f"Ошибка загрузки переводов: {e}")
        return 0


def get_label_translations() -> Dict[str, str]:
    """Получить копию словаря переводов."""
    with _translations_lock:
        return dict(_label_translations)


def save_label_translations(translations: Dict[str, str],
                             filepath: Optional[str] = None) -> str:
    """Сохранить словарь переводов в файл.
    Возвращает пустую строку при успехе или сообщение об ошибке."""
    global _label_translations
    path = Path(filepath) if filepath else _TRANSLATIONS_FILE
    try:
        # Читаем текущий файл чтобы сохранить _comment
        existing = {}
        if path.exists():
            with open(path, encoding='utf-8') as f:
                existing = json.load(f)
        comment = existing.get('_comment', '')

        out: Dict[str, str] = {}
        if comment:
            out['_comment'] = comment
        # Сортируем по ключу для читаемости
        out.update(sorted(translations.items()))

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

        with _translations_lock:
            _label_translations = dict(translations)
        logger.info(f"Словарь переводов сохранён: {len(translations)} записей → {path}")
        return ""
    except Exception as e:
        err = f"Ошибка сохранения переводов: {e}"
        logger.error(err)
        return err


# ================================================================
# Bit name translations (EN → RU), общий для всех device_type
# ================================================================
_BIT_TRANSLATIONS_FILE = Path("devices/bit_translations.json")
_bit_translations: Dict[str, str] = {}
_bit_translations_lock = threading.Lock()


def load_bit_translations(filepath: Optional[str] = None) -> int:
    """Загрузить словарь переводов имён битов из JSON-файла.
    Возвращает количество загруженных переводов."""
    global _bit_translations
    path = Path(filepath) if filepath else _BIT_TRANSLATIONS_FILE
    if not path.exists():
        logger.warning(f"Файл переводов битов не найден: {path}")
        return 0
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        translations = {k: v for k, v in data.items() if not k.startswith('_')}
        with _bit_translations_lock:
            _bit_translations = translations
        logger.info(f"Загружено {len(translations)} переводов имён битов из {path}")
        return len(translations)
    except Exception as e:
        logger.error(f"Ошибка загрузки переводов битов: {e}")
        return 0


def get_bit_translations() -> Dict[str, str]:
    """Получить копию словаря переводов имён битов."""
    with _bit_translations_lock:
        return dict(_bit_translations)


def save_bit_translations(translations: Dict[str, str],
                          filepath: Optional[str] = None) -> str:
    """Сохранить словарь переводов битов в файл.
    Возвращает пустую строку при успехе или сообщение об ошибке."""
    global _bit_translations
    path = Path(filepath) if filepath else _BIT_TRANSLATIONS_FILE
    try:
        existing = {}
        if path.exists():
            with open(path, encoding='utf-8') as f:
                existing = json.load(f)
        comment = existing.get('_comment', '')

        out: Dict[str, str] = {}
        if comment:
            out['_comment'] = comment
        out.update(sorted(translations.items()))

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

        with _bit_translations_lock:
            _bit_translations = dict(translations)
        logger.info(f"Словарь переводов битов сохранён: {len(translations)} записей → {path}")
        return ""
    except Exception as e:
        err = f"Ошибка сохранения переводов битов: {e}"
        logger.error(err)
        return err


class RegisterMapLoader:
    """
    Loads register definitions from external JSONL/JSON files.
    Provides lookup methods for decoding.
    One instance per device type.
    """

    def __init__(self):
        # register_map: key = (reg_type, addr) -> register definition dict
        self._register_map: Dict[Tuple[str, int], dict] = {}

        # enum_map: key = (reg_type, addr) -> {value_str: label}
        self._enum_map: Dict[Tuple[str, int], Dict[str, str]] = {}

        # fault_bitmap_map: key = (reg_type, addr, bit) -> fault definition
        self._fault_bitmap_map: Dict[Tuple[str, int, int], dict] = {}

        # All fault addresses (for quick lookup)
        self._fault_addresses: set = set()

    def load_map(self, filepath: str) -> int:
        """
        Load unified map.jsonl (новый формат).
        Каждая строка — регистр, может содержать:
          labels: {...}  — inline enum-метки (unit=enum)
          bits: {"0": {"name": ..., "severity": ...}}  — fault bitmap (unit=fault_bitmap)
        """
        path = Path(filepath)
        if not path.exists():
            logger.error(f"Файл карты не найден: {filepath}")
            return 0

        count = 0
        with open(path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    reg_type = entry.get('reg_type', 'holding')
                    addr = entry.get('addr')
                    if addr is None:
                        logger.warning(f"Строка {line_num}: отсутствует 'addr', пропущено")
                        continue
                    addr = int(addr)

                    # Сохраняем определение регистра
                    self._register_map[(reg_type, addr)] = entry

                    # Inline enum labels
                    labels = entry.get('labels')
                    if labels and isinstance(labels, dict):
                        self._enum_map[(reg_type, addr)] = labels

                    # Inline fault bits
                    bits = entry.get('bits')
                    if bits and isinstance(bits, dict):
                        self._fault_addresses.add((reg_type, addr))
                        for bit_str, bit_def in bits.items():
                            try:
                                self._fault_bitmap_map[(reg_type, addr, int(bit_str))] = bit_def
                            except ValueError:
                                logger.warning(f"Строка {line_num}: некорректный номер бита '{bit_str}'")

                    count += 1
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Ошибка в строке {line_num} файла {filepath}: {e}")

        logger.info(f"Загружено {count} регистров из {filepath}")
        return count

    def build_metadata_payload(self, device_type: str) -> dict:
        """
        Собирает компактный payload метаданных для публикации в MQTT (retain).
        Содержит только поля нужные потребителям: name, unit, notes_ru, labels, bits.
        """
        registers = {}
        for (reg_type, addr), reg_def in self._register_map.items():
            entry = {}

            for field in ('name', 'unit', 'notes_ru'):
                val = reg_def.get(field)
                if val is not None and val != '':
                    entry[field] = val

            # Enum labels + перевод
            labels = self._enum_map.get((reg_type, addr))
            if labels:
                entry['labels'] = labels
                # Добавляем labels_ru если есть хотя бы один перевод
                with _translations_lock:
                    tr = _label_translations
                labels_ru = {k: tr[v] for k, v in labels.items() if v in tr}
                if labels_ru:
                    entry['labels_ru'] = labels_ru

            # Fault bits
            if (reg_type, addr) in self._fault_addresses:
                bits = {}
                with _bit_translations_lock:
                    bt = _bit_translations
                for (rt, a, bit), bit_def in self._fault_bitmap_map.items():
                    if rt == reg_type and a == addr:
                        bd: Dict[str, str] = {k: v for k, v in bit_def.items()
                                              if k in ('name', 'severity')}
                        name = bd.get('name', '')
                        if name and name in bt:
                            bd['name_ru'] = bt[name]
                        bits[str(bit)] = bd
                if bits:
                    entry['bits'] = bits

            # Ключ: для input-регистров добавляем префикс
            key = f"input:{addr}" if reg_type == 'input' else str(addr)
            registers[key] = entry

        return {
            'device_type': device_type,
            'registers': registers
        }

    def load_register_map(self, filepath: str) -> int:
        """
        Load register definitions from JSONL file.
        Returns count of loaded registers.
        """
        path = Path(filepath)
        if not path.exists():
            logger.error(f"Файл карты регистров не найден: {filepath}")
            return 0

        count = 0
        with open(path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    reg_type = entry.get('reg_type', 'holding')
                    addr = entry.get('addr')
                    if addr is not None:
                        self._register_map[(reg_type, int(addr))] = entry
                        count += 1
                except json.JSONDecodeError as e:
                    logger.warning(f"Невалидный JSON в строке {line_num} файла {filepath}: {e}")

        logger.info(f"Загружено {count} определений регистров из {filepath}")
        return count

    def load_enum_map(self, filepath: str) -> int:
        """
        Load enum definitions from JSON file.
        Returns count of loaded enum sets.
        """
        path = Path(filepath)
        if not path.exists():
            logger.debug(f"Файл enum не найден (опционально): {filepath}")
            return 0

        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            # Конвертируем строковые ключи "holding:40010" в tuple (reg_type, addr)
            for key_str, values in raw.items():
                parts = key_str.split(':')
                if len(parts) == 2:
                    self._enum_map[(parts[0], int(parts[1]))] = values
            count = len(self._enum_map)
            logger.info(f"Загружено {count} определений enum из {filepath}")
            return count
        except json.JSONDecodeError as e:
            logger.error(f"Невалидный JSON в {filepath}: {e}")
            return 0

    def load_fault_bitmap_map(self, filepath: str) -> int:
        """
        Load fault bitmap definitions from JSONL file.
        Returns count of loaded fault bits.
        """
        path = Path(filepath)
        if not path.exists():
            logger.debug(f"Файл fault bitmap не найден (опционально): {filepath}")
            return 0

        count = 0
        with open(path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    reg_type = entry.get('reg_type', 'holding')
                    addr = entry.get('addr')
                    bit = entry.get('bit')
                    if addr is not None and bit is not None:
                        self._fault_bitmap_map[(reg_type, int(addr), int(bit))] = entry
                        self._fault_addresses.add((reg_type, int(addr)))
                        count += 1
                except json.JSONDecodeError as e:
                    logger.warning(f"Невалидный JSON в строке {line_num} файла {filepath}: {e}")

        logger.info(f"Загружено {count} определений fault bitmap из {filepath}")
        return count

    def get_register(self, reg_type: str, addr: int) -> Optional[dict]:
        """Get register definition by type and address."""
        return self._register_map.get((reg_type, addr))

    def get_enum(self, reg_type: str, addr: int, value: int) -> Optional[str]:
        """Get enum label for a register value."""
        enum_def = self._enum_map.get((reg_type, addr))
        if enum_def:
            return enum_def.get(str(value))
        return None

    def get_fault_bit(self, reg_type: str, addr: int, bit: int) -> Optional[dict]:
        """Get fault bit definition."""
        return self._fault_bitmap_map.get((reg_type, addr, bit))

    def is_fault_address(self, reg_type: str, addr: int) -> bool:
        """Check if address is a known fault bitmap address."""
        return (reg_type, addr) in self._fault_addresses

    def get_all_registers(self) -> Dict[Tuple[str, int], dict]:
        """Get all register definitions."""
        return self._register_map.copy()


# ================================================================
# Global registry: device_type -> RegisterMapLoader
# ================================================================
_loaders: Dict[str, RegisterMapLoader] = {}

# ================================================================
# Ignore list: device_type -> {"reg_type:addr": "comment"}
# ================================================================
_ignore_lists: Dict[str, Dict[str, str]] = {}
_ignore_lock = threading.Lock()
_device_dirs: Dict[str, str] = {}  # device_type -> maps_dir path


def get_loader(device_type: str = 'pcc') -> Optional[RegisterMapLoader]:
    """Get the RegisterMapLoader for a specific device type."""
    return _loaders.get(device_type)


def get_map_editor_data(device_type: str) -> Optional[List[dict]]:
    """Возвращает список регистров для редактора карты.
    Каждая запись содержит: key, addr, reg_type, name, unit, notes_ru,
    и опционально labels/labels_ru (enum) или bits с name_ru (fault_bitmap).
    Отсортировано по адресу."""
    loader = _loaders.get(device_type)
    if not loader:
        return None

    with _translations_lock:
        lt = _label_translations
    with _bit_translations_lock:
        bt = _bit_translations

    result = []
    for (reg_type, addr), reg_def in sorted(loader._register_map.items(),
                                            key=lambda x: (x[0][0] != 'holding', x[0][1])):
        entry: dict = {
            'key':      f"input:{addr}" if reg_type == 'input' else str(addr),
            'addr':     addr,
            'reg_type': reg_type,
            'name':     reg_def.get('name', ''),
            'unit':     reg_def.get('unit', ''),
            'notes_ru': reg_def.get('notes_ru', ''),
        }

        labels = loader._enum_map.get((reg_type, addr))
        if labels:
            entry['labels'] = labels
            entry['labels_ru'] = {k: lt[v] for k, v in labels.items() if v in lt}

        if (reg_type, addr) in loader._fault_addresses:
            bits: dict = {}
            for (rt, a, bit), bit_def in loader._fault_bitmap_map.items():
                if rt == reg_type and a == addr:
                    bd: dict = {k: v for k, v in bit_def.items() if k in ('name', 'severity')}
                    nm = bd.get('name', '')
                    if nm and nm in bt:
                        bd['name_ru'] = bt[nm]
                    bits[str(bit)] = bd
            if bits:
                entry['bits'] = bits

        result.append(entry)

    return result


def save_notes_ru(device_type: str, updates: Dict[str, str]) -> str:
    """Обновить поля notes_ru в map.jsonl для указанных регистров.
    updates: {"holding:40010": "новый текст", ...}
    Пустая строка удаляет поле.
    Возвращает '' при успехе или сообщение об ошибке."""
    maps_dir = _device_dirs.get(device_type)
    if not maps_dir:
        return f"Устройство '{device_type}' не зарегистрировано"

    map_path = Path(maps_dir) / 'map.jsonl'
    if not map_path.exists():
        return f"map.jsonl не найден: {map_path}"

    try:
        new_lines: List[str] = []
        changed = 0
        with open(map_path, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.rstrip('\n\r')
                if not stripped.strip():
                    new_lines.append(stripped)
                    continue
                try:
                    obj = json.loads(stripped)
                    reg_type = obj.get('reg_type', 'holding')
                    addr = obj.get('addr')
                    key = f"{reg_type}:{addr}"
                    if key in updates:
                        new_val = updates[key].strip()
                        if new_val:
                            obj['notes_ru'] = new_val
                        elif 'notes_ru' in obj:
                            del obj['notes_ru']
                        changed += 1
                        new_lines.append(json.dumps(obj, ensure_ascii=False, separators=(',', ':')))
                    else:
                        new_lines.append(stripped)
                except json.JSONDecodeError:
                    new_lines.append(stripped)

        with open(map_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(new_lines))

        # Перезагружаем карту в памяти
        loader = _loaders.get(device_type)
        if loader:
            loader._register_map.clear()
            loader._enum_map.clear()
            loader._fault_bitmap_map.clear()
            loader._fault_addresses.clear()
            loader.load_map(str(map_path))

        logger.info(f"notes_ru обновлены для '{device_type}': {changed} регистров изменено")
        return ""
    except Exception as e:
        err = f"Ошибка обновления map.jsonl: {e}"
        logger.error(err)
        return err


def load_device_maps(device_type: str, maps_dir: str) -> bool:
    """
    Load map files for a device type from a directory.

    Новый формат (приоритет):
        map.jsonl  — единый файл с регистрами, enum и fault bitmap

    Старый формат (fallback для обратной совместимости):
        register_map.jsonl
        enum_map.json          (опционально)
        fault_bitmap_map.jsonl (опционально)

    Returns True if at least one register loaded successfully.
    """
    global _loaders

    loader = RegisterMapLoader()
    base = Path(maps_dir)

    # Новый единый формат
    if (base / 'map.jsonl').exists():
        count = loader.load_map(str(base / 'map.jsonl'))
    else:
        # Fallback: старый трёхфайловый формат
        logger.info(f"map.jsonl не найден для '{device_type}', используется старый формат (3 файла)")
        count = loader.load_register_map(str(base / 'register_map.jsonl'))
        loader.load_enum_map(str(base / 'enum_map.json'))
        loader.load_fault_bitmap_map(str(base / 'fault_bitmap_map.jsonl'))

    if count == 0:
        logger.error(f"Ни один регистр не загружен для устройства '{device_type}' из {maps_dir}")
        return False

    _loaders[device_type] = loader
    _device_dirs[device_type] = maps_dir

    # Load ignore list if exists
    _load_ignore_list(device_type, maps_dir)

    # Загружаем переводы меток и битов (один раз, при первом устройстве)
    if not _label_translations:
        load_label_translations()
    if not _bit_translations:
        load_bit_translations()

    logger.info(f"Карты для устройства '{device_type}' загружены из {maps_dir}: {count} регистров")
    return True


def get_registered_device_types() -> list:
    """Get list of all registered device types."""
    return list(_loaders.keys())


def remove_device(device_type: str) -> bool:
    """Remove a device type from the registry."""
    global _loaders
    if device_type in _loaders:
        del _loaders[device_type]
        logger.info(f"Устройство '{device_type}' удалено из реестра")
        return True
    return False


def get_device_stats(device_type: str) -> Optional[dict]:
    """Get stats for a loaded device type."""
    loader = _loaders.get(device_type)
    if not loader:
        return None
    with _ignore_lock:
        ignore_count = len(_ignore_lists.get(device_type, {}))
    return {
        'register_count': len(loader._register_map),
        'enum_count': len(loader._enum_map),
        'fault_count': len(loader._fault_bitmap_map),
        'ignore_count': ignore_count,
    }


# ================================================================
# Ignore list management
# ================================================================

def _load_ignore_list(device_type: str, maps_dir: str):
    """Load ignore_registers.json for a device type."""
    path = Path(maps_dir) / 'ignore_registers.json'
    with _ignore_lock:
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    _ignore_lists[device_type] = json.load(f)
                logger.info(f"Загружен ignore-list для '{device_type}': {len(_ignore_lists[device_type])} регистров")
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"Ошибка загрузки ignore_registers.json для '{device_type}': {e}")
                _ignore_lists[device_type] = {}
        else:
            _ignore_lists[device_type] = {}


def _save_ignore_list(device_type: str) -> str:
    """Save ignore_registers.json for a device type. Must be called under _ignore_lock.
    Returns empty string on success, error message on failure."""
    maps_dir = _device_dirs.get(device_type)
    if not maps_dir:
        return f"maps_dir не найден для '{device_type}'"
    path = Path(maps_dir) / 'ignore_registers.json'
    try:
        data = _ignore_lists.get(device_type, {})
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return ""
    except OSError as e:
        err = f"Не удалось сохранить ignore-list: {e}"
        logger.error(err)
        return err


def is_ignored(device_type: str, reg_type: str, addr: int) -> bool:
    """Check if a register is in the ignore list."""
    key = f"{reg_type}:{addr}"
    with _ignore_lock:
        return key in _ignore_lists.get(device_type, {})


def add_to_ignore(device_type: str, reg_type: str, addr: int, comment: str = "") -> tuple:
    """Add a register to the ignore list.
    Returns (True, '') on success, (False, error_message) on failure."""
    if device_type not in _loaders:
        return False, f"Устройство '{device_type}' не найдено"
    key = f"{reg_type}:{addr}"
    with _ignore_lock:
        if device_type not in _ignore_lists:
            _ignore_lists[device_type] = {}
        _ignore_lists[device_type][key] = comment or "Игнорируется с UI"
        save_err = _save_ignore_list(device_type)
    if save_err:
        return False, save_err
    logger.info(f"Регистр {key} добавлен в ignore-list '{device_type}': {comment}")
    return True, ""


def remove_from_ignore(device_type: str, reg_type: str, addr: int) -> bool:
    """Remove a register from the ignore list."""
    key = f"{reg_type}:{addr}"
    with _ignore_lock:
        ignore = _ignore_lists.get(device_type, {})
        if key in ignore:
            del ignore[key]
            _save_ignore_list(device_type)
            logger.info(f"Регистр {key} убран из ignore-list '{device_type}'")
            return True
    return False


def get_ignore_list(device_type: str) -> Dict[str, str]:
    """Get ignore list for a device type. Returns {\"reg_type:addr\": \"comment\"}."""
    with _ignore_lock:
        return dict(_ignore_lists.get(device_type, {}))


def get_all_ignore_lists() -> Dict[str, Dict[str, str]]:
    """Get all ignore lists. Returns {device_type: {\"reg_type:addr\": \"comment\"}}."""
    with _ignore_lock:
        return {dt: dict(il) for dt, il in _ignore_lists.items() if il}


def clear_ignore_list(device_type: str) -> int:
    """Clear ignore list for a device type. Returns count of removed entries."""
    with _ignore_lock:
        ignore = _ignore_lists.get(device_type, {})
        count = len(ignore)
        _ignore_lists[device_type] = {}
        _save_ignore_list(device_type)
    if count:
        logger.info(f"Ignore-list для '{device_type}' очищен ({count} записей)")
    return count
