"""
Универсальный Modbus-декодер — Модуль декодирования

Декодирует raw Modbus-данные по картам регистров.
Поддерживает несколько типов устройств через device_type.
Хардкод регистров запрещён.
"""

import struct
import logging
from typing import List, Optional, Any, Tuple

from maps_loader import get_loader, RegisterMapLoader

logger = logging.getLogger(__name__)


class ModbusDecoder:
    """
    Decodes raw Modbus register data into human-readable values.
    Uses external map files - no hardcoded registers.
    Stateless regarding maps — device_type selects the correct map set per call.
    """

    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode

    def parse_full_addr(self, full_addr: str) -> Tuple[str, int]:
        """
        Parse full_addr string into (reg_type, addr).

        Example: "406109" -> ("holding", 46109)
        - First char: region type (4 = holding, 3 = input)
        - Last 5 digits: offset from base
        - addr = 40000 + offset
        """
        if len(full_addr) < 6:
            raise ValueError(f"Invalid full_addr format: {full_addr}")

        region_code = full_addr[0]
        offset_str = full_addr[1:]
        offset = int(offset_str)

        # Determine register type and base address
        if region_code == '4':
            reg_type = 'holding'
            addr = 40000 + offset
        elif region_code == '3':
            reg_type = 'input'
            addr = 30000 + offset
        else:
            reg_type = 'holding'
            addr = 40000 + offset
            if self.debug_mode:
                logger.warning(f"Неизвестный код области '{region_code}', используется holding")

        return reg_type, addr

    def decode_value(self, reg_def: dict, words: List[int], word_idx: int = 0) -> Tuple[Any, Any, Optional[str]]:
        """
        Decode a value from word(s) based on register definition.

        Returns: (decoded_value, raw_value, failure_reason)
        - decoded_value: scaled/converted value or None if failed
        - raw_value: raw numeric value
        - failure_reason: None if success, string describing failure
        """
        data_type = reg_def.get('data_type', 'u16')
        word_len = reg_def.get('word_len', 1)
        multiplier = reg_def.get('multiplier', 1.0)
        offset = reg_def.get('offset', 0.0)
        na_values = reg_def.get('na_values', [])

        # Check if we have enough words
        if word_idx + word_len > len(words):
            return None, None, f"Недостаточно слов: нужно {word_len}, есть {len(words) - word_idx}"

        raw_value = None
        decoded_value = None

        try:
            # Pre-decoded float values (e.g., Teltonika router sends already-converted floats)
            # If the word is a float, treat it as already decoded — apply multiplier/offset only
            first_word = words[word_idx]
            if isinstance(first_word, float):
                raw_value = first_word
                if raw_value in na_values:
                    return None, raw_value, "Значение NA"
                decoded_value = raw_value * multiplier + offset
                return decoded_value, raw_value, None

            if data_type in ('u16', 'raw'):
                # Single 16-bit unsigned
                raw_value = words[word_idx]
                if raw_value in na_values:
                    return None, raw_value, "Значение NA"
                decoded_value = raw_value * multiplier + offset

            elif data_type == 's16':
                # Single 16-bit signed
                raw_value = words[word_idx]
                # Convert to signed
                if raw_value >= 0x8000:
                    raw_value = raw_value - 0x10000
                if raw_value in na_values:
                    return None, raw_value, "Значение NA"
                decoded_value = raw_value * multiplier + offset

            elif data_type == 'u32':
                # Two 16-bit words, big-endian (AB order: hi, lo)
                hi = words[word_idx]
                lo = words[word_idx + 1] if word_idx + 1 < len(words) else 0
                raw_value = (hi << 16) | lo
                if raw_value in na_values:
                    return None, raw_value, "Значение NA"
                decoded_value = raw_value * multiplier + offset

            elif data_type == 's32':
                # Two 16-bit words, big-endian, signed
                hi = words[word_idx]
                lo = words[word_idx + 1] if word_idx + 1 < len(words) else 0
                raw_value = (hi << 16) | lo
                # Convert to signed 32-bit
                if raw_value >= 0x80000000:
                    raw_value = raw_value - 0x100000000
                if raw_value in na_values:
                    return None, raw_value, "Значение NA"
                decoded_value = raw_value * multiplier + offset

            elif data_type == 'f32':
                # Two 16-bit words as IEEE754 float
                hi = words[word_idx]
                lo = words[word_idx + 1] if word_idx + 1 < len(words) else 0
                raw_value = (hi << 16) | lo
                # Convert to float
                try:
                    decoded_value = struct.unpack('>f', struct.pack('>I', raw_value))[0]
                except (struct.error, ValueError, OverflowError):
                    return None, raw_value, "Ошибка конвертации float"

            elif data_type == 'char':
                # Character string - return raw words
                raw_value = words[word_idx]
                decoded_value = raw_value

            elif data_type == 'bitfield':
                # Bitfield - return raw for now, decode elsewhere if needed
                raw_value = words[word_idx]
                decoded_value = raw_value

            else:
                # Unknown type - treat as u16
                raw_value = words[word_idx]
                decoded_value = raw_value
                if self.debug_mode:
                    logger.warning(f"Неизвестный data_type '{data_type}', обработка как u16")

        except Exception as e:
            return None, raw_value, f"Ошибка декодирования: {str(e)}"

        return decoded_value, raw_value, None

    def decode_enum(self, loader: RegisterMapLoader, reg_type: str, addr: int, raw_value: int) -> Optional[str]:
        """Try to decode an enum value."""
        return loader.get_enum(reg_type, addr, raw_value)

    def decode_fault_bitmap(self, loader: RegisterMapLoader, reg_type: str, addr: int, raw_value: int) -> dict:
        """
        Decode a fault bitmap register.

        Returns dict with:
        - raw: the raw value
        - hex: hex representation
        - active_bits: list of active bit numbers
        - faults: list of decoded faults (if known)
        - unknown_bits: list of active bits with no definition
        """
        result = {
            'raw': raw_value,
            'hex': f"0x{raw_value:04X}",
            'active_bits': [],
            'faults': [],
            'unknown_bits': []
        }

        # Find all active bits
        for bit in range(16):
            if (raw_value >> bit) & 1:
                result['active_bits'].append(bit)

                # Try to find fault definition
                fault_def = loader.get_fault_bit(reg_type, addr, bit)
                if fault_def:
                    result['faults'].append({
                        'bit': bit,
                        'name': fault_def.get('name', f'Bit {bit}'),
                        'description': fault_def.get('description', ''),
                        'severity': fault_def.get('severity', 'unknown')
                    })
                else:
                    result['unknown_bits'].append(bit)

        return result

    def decode_register(self, loader: RegisterMapLoader, reg_type: str, addr: int, words: List[int]) -> dict:
        """
        Decode a single register (possibly multi-word).

        Returns dict with:
        - addr: register address
        - name: register name (if known)
        - value: decoded value or None
        - unit: unit string
        - raw: raw value
        - reason: failure reason (if value is None)
        """
        result = {
            'addr': addr,
            'name': None,
            'value': None,
            'text': None,
            'unit': None,
            'raw': None,
            'reason': None
        }

        # Get register definition
        reg_def = loader.get_register(reg_type, addr)

        if reg_def is None:
            # Check if it's a known fault bitmap address (not in register_map but in fault_bitmap_map)
            if words and loader.is_fault_address(reg_type, addr):
                raw_value = words[0]
                result['raw'] = raw_value
                result['name'] = f"Fault Bitmap {addr}"
                result['unit'] = 'fault_bitmap'
                result['value'] = self.decode_fault_bitmap(loader, reg_type, addr, raw_value)
                return result

            # Unknown register
            if words:
                result['raw'] = words[0]
            result['reason'] = "Неизвестный регистр"
            if self.debug_mode:
                logger.debug(f"Неизвестный регистр {reg_type}:{addr}")
            return result

        # Fill in known fields
        result['name'] = reg_def.get('name', f'Register {addr}')
        result['unit'] = reg_def.get('unit', '')

        # Decode value
        decoded, raw, reason = self.decode_value(reg_def, words)
        result['raw'] = raw

        if reason:
            result['reason'] = reason
            if self.debug_mode:
                logger.debug(f"Ошибка декодирования {addr}: {reason}")
            return result

        # Handle special types
        unit = reg_def.get('unit', '')
        data_type = reg_def.get('data_type', 'u16')

        if unit == 'enum':
            # For enum: value is numeric, text is label
            result['value'] = int(raw)
            result['unit'] = None  # enum has no unit
            enum_label = self.decode_enum(loader, reg_type, addr, int(raw))
            if enum_label:
                result['text'] = enum_label
            elif self.debug_mode:
                logger.debug(f"Нет определения enum для {addr}={raw}")

        elif data_type == 'bitfield':
            # Check if this is a fault bitmap
            if loader.is_fault_address(reg_type, addr):
                fault_data = self.decode_fault_bitmap(loader, reg_type, addr, int(raw))
                result['value'] = fault_data
                result['unit'] = 'fault_bitmap'
            else:
                # Unknown bitfield - return raw with bit info
                result['value'] = {
                    'raw': raw,
                    'hex': f"0x{int(raw):04X}",
                    'active_bits': [b for b in range(16) if (int(raw) >> b) & 1]
                }
                result['unit'] = 'bitfield'
        else:
            result['value'] = decoded

        return result

    def decode_packet(self, full_addr: str, data: List[int], device_type: str = 'pcc') -> List[dict]:
        """
        Decode a complete packet (may contain multiple registers).

        Args:
            full_addr: Full address string (e.g., "406109")
            data: List of 16-bit word values
            device_type: Device type to select correct register maps

        Returns:
            List of decoded register dicts, sorted by addr
        """
        loader = get_loader(device_type)
        if not loader:
            logger.error(f"Нет карт для типа устройства '{device_type}'")
            return []

        try:
            reg_type, base_addr = self.parse_full_addr(full_addr)
        except ValueError as e:
            logger.error(f"Ошибка разбора full_addr '{full_addr}': {e}")
            return []

        results = []

        # Track which word indices we've processed (for multi-word registers)
        processed_indices = set()

        for i, word in enumerate(data):
            if i in processed_indices:
                continue

            addr = base_addr + i

            # Get register definition to check word length
            reg_def = loader.get_register(reg_type, addr)
            word_len = 1
            if reg_def:
                word_len = reg_def.get('word_len', 1)

            # Get the words for this register
            reg_words = data[i:i + word_len]

            # Decode
            result = self.decode_register(loader, reg_type, addr, reg_words)
            results.append(result)

            # Mark processed indices (for multi-word, don't output tail registers)
            for j in range(word_len):
                processed_indices.add(i + j)

        # Sort by address
        results.sort(key=lambda x: x['addr'])

        return results


# Global decoder instance
_decoder: Optional[ModbusDecoder] = None


def get_decoder(debug_mode: bool = False) -> ModbusDecoder:
    """Get the global ModbusDecoder instance."""
    global _decoder
    if _decoder is None:
        _decoder = ModbusDecoder(debug_mode=debug_mode)
    return _decoder
