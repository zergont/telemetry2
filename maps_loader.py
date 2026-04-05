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


def load_device_maps(device_type: str, maps_dir: str) -> bool:
    """
    Load all map files for a device type from a directory.

    Expected files in maps_dir:
        register_map.jsonl
        enum_map.json
        fault_bitmap_map.jsonl

    Returns True if register map loaded successfully.
    """
    global _loaders

    loader = RegisterMapLoader()
    base = Path(maps_dir)

    reg_count = loader.load_register_map(str(base / 'register_map.jsonl'))
    loader.load_enum_map(str(base / 'enum_map.json'))
    loader.load_fault_bitmap_map(str(base / 'fault_bitmap_map.jsonl'))

    if reg_count == 0:
        logger.error(f"Ни один регистр не загружен для устройства '{device_type}' из {maps_dir}")
        return False

    _loaders[device_type] = loader
    _device_dirs[device_type] = maps_dir

    # Load ignore list if exists
    _load_ignore_list(device_type, maps_dir)

    logger.info(f"Карты для устройства '{device_type}' загружены из {maps_dir}")
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


def _save_ignore_list(device_type: str):
    """Save ignore_registers.json for a device type. Must be called under _ignore_lock."""
    maps_dir = _device_dirs.get(device_type)
    if not maps_dir:
        return
    path = Path(maps_dir) / 'ignore_registers.json'
    try:
        data = _ignore_lists.get(device_type, {})
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"Ошибка сохранения ignore_registers.json для '{device_type}': {e}")


def is_ignored(device_type: str, reg_type: str, addr: int) -> bool:
    """Check if a register is in the ignore list."""
    key = f"{reg_type}:{addr}"
    with _ignore_lock:
        return key in _ignore_lists.get(device_type, {})


def add_to_ignore(device_type: str, reg_type: str, addr: int, comment: str = "") -> bool:
    """Add a register to the ignore list. Returns True on success."""
    if device_type not in _loaders:
        return False
    key = f"{reg_type}:{addr}"
    with _ignore_lock:
        if device_type not in _ignore_lists:
            _ignore_lists[device_type] = {}
        _ignore_lists[device_type][key] = comment or f"Игнорируется с UI"
        _save_ignore_list(device_type)
    logger.info(f"Регистр {key} добавлен в ignore-list '{device_type}': {comment}")
    return True


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
