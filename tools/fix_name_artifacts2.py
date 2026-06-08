# Copyright (c) 2026 ООО «НГ-ЭНЕРГОСЕРВИС». Все права защищены.
# Программный комплекс «Честная Генерация»
# Модуль декодирования Modbus-телеметрии
# Автор: Саввиди Александр Анатольевич | ИНН 4725009270
#
# Данное программное обеспечение является конфиденциальным.
# Несанкционированное копирование, распространение или использование
# без письменного разрешения правообладателя запрещено.

"""
Второй проход: оставшиеся артефакты PDF в полях name и notes_ru.

Источник: Modbus 3.3.pdf (таблица регистров, колонка Name).
"""

import json
import re
from pathlib import Path

MAP_FILE = Path(r"C:\Users\folis\source\repos\telemetry2\devices\pcc\map.jsonl")

# ---------------------------------------------------------------------------
# Прямые замены имён (второй batch)
# ---------------------------------------------------------------------------
NAME_FIXES2 = {
    # kVAR/kW Load регистры (spacing)
    40214: "kVAR Load Setpoint",
    40217: "kVAR Load Share Level",
    40224: "kVAR Load Share Output Predictor",
    40225: "kW Load Share Output Predictor",
    # Amber Warning Lamp Status
    40228: "Amber Warning Lamp Status",
    # Barometric (убрать "'AmbientPressure'inthe")
    40229: "Barometric Absolute Pressure",
    # AT Fault Status Bitmap 1 (40495 — отдельный регистр, не 41400)
    40495: "AT Fault Status Bitmap 1",
    # Fault Type (Modlon)
    40713: "Fault Type (Modlon)",
    # NFPA110 Logical Status (убрать "NFPA110logical.See")
    40716: "NFPA110 Logical Status",
    40717: "NFPA110 Logical Status",
    # Genset Frequency Modlon (убрать "FrequencyOP.Modbushas different")
    40718: "Genset Frequency (Modlon)",
    # Genset % Standby Lx (spacing)
    40732: "Genset % Standby L1",
    40733: "Genset % Standby L2",
    40734: "Genset % Standby L3",
    # Oil Pressure / Oil Temperature (убрать мусорный суффикс)
    40736: "Oil Pressure (Modlon)",
    40737: "Oil Temperature",
    # Fuel Temperature / Fuel Rate (убрать повтор имени + Modbus desc)
    40740: "Fuel Temperature",
    40741: "Fuel Rate (Modlon)",
    # Engine Running Time (убрать "time.Modbushasdifferent")
    40744: "Engine Running Time",
    40745: "Engine Running Time",
    # Remote Start Switch (Modlon)
    40766: "Remote Start Switch (Modlon)",
    # Load Demand (spacing + удалить "Sequence.Availableon" и т.п.)
    41005: "Load Demand Stop Threshold %",
    41006: "Load Demand Stop Threshold (kW)",
    41008: "Load Demand Genset Fail Delay",
    41009: "Load Demand Initial Delay",
    41010: "Load Demand Start Delay",
    41011: "Load Demand Stop Delay",
    41013: "Load Demand Fixed Priority 1",
    41014: "Load Demand Fixed Priority 2",
    41015: "Load Demand Fixed Priority 3",
    41016: "Load Demand Fixed Priority 4",
    41017: "Load Demand Fixed Priority 5",
    41018: "Load Demand Fixed Priority 6",
    41019: "Load Demand Fixed Priority 7",
    41020: "Load Demand Fixed Priority 8",
    41021: "Load Demand Fixed Priority 9",
    41022: "Load Demand Fixed Priority 10",
    41023: "Load Demand Fixed Priority 11",
    41024: "Load Demand Fixed Priority 12",
    41025: "Load Demand Fixed Priority 13",
    41026: "Load Demand Fixed Priority 14",
    41027: "Load Demand Fixed Priority 15",
    41028: "Load Demand Fixed Priority 16",
    # Battery Charger N Failed Switch
    41031: "Battery Charger 2 Failed Switch",
    41032: "Battery Charger 3 Failed Switch",
    41033: "Battery Charger 4 Failed Switch",
    # Intake Air Restriction N (4 indicator switches)
    41034: "Intake Air Restriction 1",
    41035: "Intake Air Restriction 2",
    41036: "Intake Air Restriction 3",
    41037: "Intake Air Restriction 4",
    # Starter Air Supply
    41038: "Starter Air Supply Pressure Low Fault Switch",
    # Genset % StandbyLx kVA/kW (43xxx)
    43011: "Genset % Standby L1 kVA",
    43012: "Genset % Standby L3 kVA",
    43013: "Genset % Standby L2 kVA",
    43014: "Genset % Standby L1 kW",
    43015: "Genset % Standby L2 kW",
    43016: "Genset % Standby L3 kW",
    # Прочие spacing
    40720: "Genset Total kVA (Modlon)",
    40721: "Genset Total kW (Modlon)",
    40715: "Genset Total kW (Modlon) Lo",
}

# ---------------------------------------------------------------------------
# Regex-замены для очистки notes_ru (те же что и для имён + очистка мусора)
# ---------------------------------------------------------------------------
NOTES_CLEANUP = [
    # Убрать "ThisModbusregisteris createdforModlonregister mapping.*" и т.п.
    (re.compile(r'\s+ThisModbus[a-zA-Z\s]+$'),          ''),
    (re.compile(r'\s+[Cc]reatedfor[Mm]odlon[a-zA-Z\s]+$'), ''),
    (re.compile(r'\s+"AmbientPressure"inthe\s*$'),       ''),
    (re.compile(r'\s+NFPA110logical\..*$'),              ''),
    (re.compile(r'\s+FrequencyOP\.Modbushas.*$'),        ''),
    (re.compile(r'\s+OilPressure\.Modbusand.*$'),        ''),
    (re.compile(r'\s+OilTemperature\.Modbusand.*$'),     ''),
    (re.compile(r'\s+Fuel\s*Temperature\.Modbus.*$'),    ''),
    (re.compile(r'\s+Fuel\s*Rate\.Modbusand.*$'),        ''),
    (re.compile(r'\s+time\.Modbushasdifferent.*$'),      ''),
    (re.compile(r'\s+mapping\.Modbus.*$'),               ''),
    (re.compile(r'\s+mapping\.This.*$'),                 ''),
    (re.compile(r'\s+Sequence\.Availableon.*$'),         ''),
    (re.compile(r'\s+start\.Availableon.*$'),            ''),
    (re.compile(r'\s+stop\.Availableon.*$'),             ''),
    (re.compile(r'\s+orderto[a-z].*$'),                  ''),
    (re.compile(r'\s+bebroadcastedand.*$'),              ''),
    (re.compile(r'\s+BusFrequency[a-z].*$'),             ''),
    (re.compile(r'\s+netkWhaccumulation.*$'),            ''),
    (re.compile(r'\s+generatorsetstandby.*$'),           ''),
    (re.compile(r'\s+[a-z]{4,}[A-Z][a-z]{2,}.*$'),      ''),  # generic: оборвать на первом garbled-слове
]

# Нормализация пробелов (применяем к notes_ru так же как к names)
SPACING_RULES_NOTES = [
    (re.compile(r'ATFault\s+StatusBitmap\s*(\d+)'),  r'AT Fault Status Bitmap \1'),
    (re.compile(r'FaultStatus\s+Bitmap(\d+)'),        r'Fault Status Bitmap \1'),
    (re.compile(r'EventStatus\s+Bitmap(\d+)'),        r'Event Status Bitmap \1'),
    (re.compile(r'kVARLoad'),                         r'kVAR Load'),
    (re.compile(r'KWLoad'),                           r'kW Load'),
    (re.compile(r'LampStatus'),                       r'Lamp Status'),
    (re.compile(r'PowerFactor'),                      r'Power Factor'),
    (re.compile(r'FaultType'),                        r'Fault Type'),
    (re.compile(r'RemoteStart'),                      r'Remote Start'),
    (re.compile(r'FaultReset'),                       r'Fault Reset'),
    (re.compile(r'FailedSwitch'),                     r'Failed Switch'),
    (re.compile(r'IntakeAir'),                        r'Intake Air'),
    (re.compile(r'StarterAir'),                       r'Starter Air'),
    (re.compile(r'GensetFail'),                       r'Genset Fail'),
    (re.compile(r'InitialDelay'),                     r'Initial Delay'),
    (re.compile(r'FixedPriority\s*(\d+)'),            r'Fixed Priority \1'),
    (re.compile(r'StandbyL([123])'),                  r'Standby L\1'),
    (re.compile(r'(Total|Negative|Positive|Net)(kWh)'), r'\1 \2'),
    (re.compile(r'(Total|Negative|Positive|Net)(kVARh)'), r'\1 \2'),
    (re.compile(r'DemandStart'),                      r'Demand Start'),
    (re.compile(r'DemandStop'),                       r'Demand Stop'),
    (re.compile(r'  +'),                              r' '),
]


def clean_notes(n: str) -> str:
    # Применим spacing
    for pat, repl in SPACING_RULES_NOTES:
        n = pat.sub(repl, n)
    # Применим очистку мусора (ищем в части до " — ")
    if ' — ' in n:
        prefix, suffix = n.split(' — ', 1)
        for pat, repl in NOTES_CLEANUP:
            prefix = pat.sub(repl, prefix.strip())
        n = prefix + ' — ' + suffix
    else:
        for pat, repl in NOTES_CLEANUP:
            n = pat.sub(repl, n.strip())
    return n.strip()


def main():
    entries = []
    with open(MAP_FILE, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    name_fixed  = 0
    notes_fixed = 0

    for e in entries:
        addr = e['addr']

        # Прямые замены имён
        if addr in NAME_FIXES2:
            old = e['name']
            new = NAME_FIXES2[addr]
            if old != new:
                e['name'] = new
                name_fixed += 1
                # Синхронизируем notes_ru если он начинается со старого имени
                notes = e.get('notes_ru', '')
                if notes and notes.startswith(old[:20]):
                    suffix = notes[len(old):]
                    e['notes_ru'] = new + suffix
                    # Применим очистку
                    e['notes_ru'] = clean_notes(e['notes_ru'])
                    notes_fixed += 1

        # Очистка notes_ru для всех записей
        old_notes = e.get('notes_ru', '')
        if old_notes:
            new_notes = clean_notes(old_notes)
            if new_notes != old_notes:
                e['notes_ru'] = new_notes
                notes_fixed += 1

    with open(MAP_FILE, 'w', encoding='utf-8', newline='\n') as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')

    print(f"Имён исправлено  : {name_fixed}")
    print(f"notes_ru очищено : {notes_fixed}")

    # Финальная проверка
    entries2 = [json.loads(l) for l in open(MAP_FILE, encoding='utf-8') if l.strip()]
    long_left = [e for e in entries2 if len(e.get('name', '')) > 55]
    if long_left:
        print(f"\nВсё ещё длинные имена ({len(long_left)}):")
        for e in long_left:
            print(f"  {e['addr']}: {e['name']}")
    else:
        print("\nДлинных имён (>55 символов) нет.")

    # Проверка артефактов
    import re as re2
    still_garbled = [e for e in entries2
                     if re2.search(r'\.(Modbus|Available|Sequence)|Modbushas|mapping\.This', e.get('name', ''))]
    print(f"Имён с явным OCR-мусором: {len(still_garbled)}")
    for e in still_garbled:
        print(f"  {e['addr']}: {e['name']}")


if __name__ == '__main__':
    main()
