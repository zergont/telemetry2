"""
Универсальный Modbus-декодер — Загрузчик карт регистров

Загружает карты регистров, enum и fault bitmap из внешних файлов.
Хардкод регистров запрещён — все данные из файлов.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class RegisterMapLoader:
    """
    Loads register definitions from external JSONL/JSON files.
    Provides lookup methods for decoding.
    """
    
    def __init__(self):
        # register_map: key = "holding:40010" -> register definition dict
        self._register_map: Dict[str, dict] = {}
        
        # enum_map: key = "holding:40010" -> {value_str: label}
        self._enum_map: Dict[str, Dict[str, str]] = {}
        
        # fault_bitmap_map: key = "holding:40400:0" (addr:bit) -> fault definition
        self._fault_bitmap_map: Dict[str, dict] = {}
        
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
                        key = f"{reg_type}:{addr}"
                        self._register_map[key] = entry
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
            logger.error(f"Файл enum не найден: {filepath}")
            return 0
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self._enum_map = json.load(f)
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
            logger.error(f"Файл fault bitmap не найден: {filepath}")
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
                        key = f"{reg_type}:{addr}:{bit}"
                        self._fault_bitmap_map[key] = entry
                        self._fault_addresses.add(f"{reg_type}:{addr}")
                        count += 1
                except json.JSONDecodeError as e:
                    logger.warning(f"Невалидный JSON в строке {line_num} файла {filepath}: {e}")
        
        logger.info(f"Загружено {count} определений fault bitmap из {filepath}")
        return count
    
    def get_register(self, reg_type: str, addr: int) -> Optional[dict]:
        """Get register definition by type and address."""
        key = f"{reg_type}:{addr}"
        return self._register_map.get(key)
    
    def get_enum(self, reg_type: str, addr: int, value: int) -> Optional[str]:
        """Get enum label for a register value."""
        key = f"{reg_type}:{addr}"
        enum_def = self._enum_map.get(key)
        if enum_def:
            return enum_def.get(str(value))
        return None
    
    def get_fault_bit(self, reg_type: str, addr: int, bit: int) -> Optional[dict]:
        """Get fault bit definition."""
        key = f"{reg_type}:{addr}:{bit}"
        return self._fault_bitmap_map.get(key)
    
    def is_fault_address(self, reg_type: str, addr: int) -> bool:
        """Check if address is a known fault bitmap address."""
        key = f"{reg_type}:{addr}"
        return key in self._fault_addresses
    
    def get_all_registers(self) -> Dict[str, dict]:
        """Get all register definitions."""
        return self._register_map.copy()


# Global instance
_loader: Optional[RegisterMapLoader] = None


def get_loader() -> RegisterMapLoader:
    """Get the global RegisterMapLoader instance."""
    global _loader
    if _loader is None:
        _loader = RegisterMapLoader()
    return _loader


def load_all_maps(register_map_path: str, enum_map_path: str, fault_bitmap_path: str) -> bool:
    """
    Load all map files. Returns True if all loaded successfully.
    """
    loader = get_loader()
    
    reg_count = loader.load_register_map(register_map_path)
    enum_count = loader.load_enum_map(enum_map_path)
    fault_count = loader.load_fault_bitmap_map(fault_bitmap_path)
    
    if reg_count == 0:
        logger.error("Ни один регистр не загружен — декодер не будет работать")
        return False
    
    return True
