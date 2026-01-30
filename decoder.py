"""
Universal Modbus Decoder - Core Decoder Module

Decodes raw Modbus data using register maps.
No hardcoded register definitions.
"""

import json
import struct
import logging
from typing import Dict, List, Optional, Any, Tuple

from maps_loader import get_loader

logger = logging.getLogger(__name__)


class ModbusDecoder:
    """
    Decodes raw Modbus register data into human-readable values.
    Uses external map files - no hardcoded registers.
    """
    
    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode
        self._loader = get_loader()
    
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
        
        # Determine register type
        if region_code == '4':
            reg_type = 'holding'
        elif region_code == '3':
            reg_type = 'input'
        else:
            reg_type = 'holding'  # Default
            if self.debug_mode:
                logger.warning(f"Unknown region code '{region_code}', defaulting to holding")
        
        # Calculate address: base + offset
        offset = int(offset_str)
        addr = 40000 + offset
        
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
            return None, None, f"Not enough words: need {word_len}, have {len(words) - word_idx}"
        
        raw_value = None
        decoded_value = None
        
        try:
            if data_type in ('u16', 'raw'):
                # Single 16-bit unsigned
                raw_value = words[word_idx]
                if raw_value in na_values:
                    return None, raw_value, "NA value"
                decoded_value = raw_value * multiplier + offset
                
            elif data_type == 's16':
                # Single 16-bit signed
                raw_value = words[word_idx]
                # Convert to signed
                if raw_value >= 0x8000:
                    raw_value = raw_value - 0x10000
                if raw_value in na_values:
                    return None, raw_value, "NA value"
                decoded_value = raw_value * multiplier + offset
                
            elif data_type == 'u32':
                # Two 16-bit words, big-endian (AB order: hi, lo)
                hi = words[word_idx]
                lo = words[word_idx + 1] if word_idx + 1 < len(words) else 0
                raw_value = (hi << 16) | lo
                if raw_value in na_values:
                    return None, raw_value, "NA value"
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
                    return None, raw_value, "NA value"
                decoded_value = raw_value * multiplier + offset
                
            elif data_type == 'f32':
                # Two 16-bit words as IEEE754 float
                hi = words[word_idx]
                lo = words[word_idx + 1] if word_idx + 1 < len(words) else 0
                raw_value = (hi << 16) | lo
                # Convert to float
                try:
                    decoded_value = struct.unpack('>f', struct.pack('>I', raw_value))[0]
                except:
                    return None, raw_value, "Float conversion failed"
                    
            elif data_type == 'char':
                # Character string - return raw words
                raw_value = words[word_idx]
                # For char types, we just return the raw value
                # Full string handling would need multiple registers
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
                    logger.warning(f"Unknown data_type '{data_type}', treating as u16")
        
        except Exception as e:
            return None, raw_value, f"Decode error: {str(e)}"
        
        return decoded_value, raw_value, None
    
    def decode_enum(self, reg_type: str, addr: int, raw_value: int) -> Optional[str]:
        """Try to decode an enum value."""
        return self._loader.get_enum(reg_type, addr, raw_value)
    
    def decode_fault_bitmap(self, reg_type: str, addr: int, raw_value: int) -> dict:
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
                fault_def = self._loader.get_fault_bit(reg_type, addr, bit)
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
    
    def decode_register(self, reg_type: str, addr: int, words: List[int]) -> dict:
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
        reg_def = self._loader.get_register(reg_type, addr)
        
        if reg_def is None:
            # Check if it's a known fault bitmap address (not in register_map but in fault_bitmap_map)
            if words and self._loader.is_fault_address(reg_type, addr):
                raw_value = words[0]
                result['raw'] = raw_value
                result['name'] = f"Fault Bitmap {addr}"
                result['unit'] = 'fault_bitmap'
                result['value'] = self.decode_fault_bitmap(reg_type, addr, raw_value)
                return result
            
            # Unknown register
            if words:
                result['raw'] = words[0]
            result['reason'] = "Unknown register"
            if self.debug_mode:
                logger.debug(f"Unknown register {reg_type}:{addr}")
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
                logger.debug(f"Decode failed for {addr}: {reason}")
            return result
        
        # Handle special types
        unit = reg_def.get('unit', '')
        data_type = reg_def.get('data_type', 'u16')
        
        if unit == 'enum':
            # For enum: value is numeric, text is label
            result['value'] = int(raw)
            result['unit'] = None  # enum has no unit
            enum_label = self.decode_enum(reg_type, addr, int(raw))
            if enum_label:
                result['text'] = enum_label
            elif self.debug_mode:
                logger.debug(f"No enum definition for {addr}={raw}")
                    
        elif data_type == 'bitfield':
            # Check if this is a fault bitmap
            if self._loader.is_fault_address(reg_type, addr):
                fault_data = self.decode_fault_bitmap(reg_type, addr, int(raw))
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
    
    def decode_packet(self, full_addr: str, data: List[int]) -> List[dict]:
        """
        Decode a complete packet (may contain multiple registers).
        
        Args:
            full_addr: Full address string (e.g., "406109")
            data: List of 16-bit word values
        
        Returns:
            List of decoded register dicts, sorted by addr
        """
        try:
            reg_type, base_addr = self.parse_full_addr(full_addr)
        except ValueError as e:
            logger.error(f"Failed to parse full_addr '{full_addr}': {e}")
            return []
        
        results = []
        
        # Track which word indices we've processed (for multi-word registers)
        processed_indices = set()
        
        for i, word in enumerate(data):
            if i in processed_indices:
                continue
                
            addr = base_addr + i
            
            # Get register definition to check word length
            reg_def = self._loader.get_register(reg_type, addr)
            word_len = 1
            if reg_def:
                word_len = reg_def.get('word_len', 1)
            
            # Get the words for this register
            reg_words = data[i:i + word_len]
            
            # Decode
            result = self.decode_register(reg_type, addr, reg_words)
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
