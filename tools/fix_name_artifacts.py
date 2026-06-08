# Copyright (c) 2026 ООО «НГ-ЭНЕРГОСЕРВИС». Все права защищены.
# Программный комплекс «Честная Генерация»
# Модуль декодирования Modbus-телеметрии
# Автор: Саввиди Александр Анатольевич | ИНН 4725009270
#
# Данное программное обеспечение является конфиденциальным.
# Несанкционированное копирование, распространение или использование
# без письменного разрешения правообладателя запрещено.

"""
Исправление артефактов переноса из PDF в поле name (и notes_ru где нужно).

Три вида проблем:
1. Описание из PDF слилось с именем регистра (32 записи, name > 55 символов)
2. Пропущены пробелы: "TotalkW", "PowerFactor", "L1NVoltage", "NegativekWh" и т.п.
3. notes_ru сгенерировано из гарблед-name — также исправляем

Источник правильных имён: Modbus 3.3.pdf (400 стр., таблица регистров).
"""

import json
import re
from pathlib import Path

MAP_FILE = Path(r"C:\Users\folis\source\repos\telemetry2\devices\pcc\map.jsonl")

# ---------------------------------------------------------------------------
# 1. Прямые замены имён (артефакты: description слился с name)
# ---------------------------------------------------------------------------
NAME_FIXES = {
    40226: "Speed Bias Output",
    40227: "Voltage Bias Output",
    40583: "Dead Battery Prevention Counter",
    40709: "Device Type (Modlon)",
    40714: "Genset % Standby Total kW (Modlon)",
    40773: "Genset ID",
    41004: "Load Demand Start Threshold (kW)",
    41007: "Load Demand Run Hours Differential",
    41012: "Clear Lost Gensets Local",
    41030: "Synchronize System Settings",
    41300: "AmpSentry Maintenance Mode Status",
    41301: "AMMPC Tool Detected",
    43220: "Genset Serial Number",
    43313: "Overload Shutdown",
    43666: "Cycle/Cont Crank Select",
    43672: "Frequency Adjust",
    43681: "Idle Warmup Time",
    43682: "Load Dump Activation Method",
    43767: "Load Govern kVAR Target",
    43805: "Time Delay to Stop",
    43806: "Voltage Adjust",
    43807: "Voltage Ramp Time",
    43817: "Genset Circuit Breaker Inhibit",
    43825: "Transfer Delay (TDNE)",
    43841: "Transfer Inhibit",
    43849: "Genset kVAR Setpoint",
    43864: "Utility kVAR Setpoint Percent",
    43866: "Utility kW Constraint Percent",
    43869: "Utility Power Factor Setpoint",
    43910: "Save Trims",
    43916: "V/Hz Knee Frequency 50 Hz",
    43917: "V/Hz Knee Frequency 60 Hz",
}

# ---------------------------------------------------------------------------
# 2. Нормализация пробелов в именах (regex-замены, применяются ко всем именам)
# ---------------------------------------------------------------------------
SPACING_RULES = [
    # Пробел перед единицами мощности/энергии (если слипшиеся)
    (re.compile(r'(Total|Negative|Positive|Net)(kWh)'),    r'\1 \2'),
    (re.compile(r'(Total|Negative|Positive|Net)(kVARh)'),  r'\1 \2'),
    (re.compile(r'(Total|Bus|L1|L2|L3)(kW)(?!h)'),        r'\1 \2'),
    (re.compile(r'(Total|Bus|L1|L2|L3)(kVAR)(?!h)'),      r'\1 \2'),
    (re.compile(r'(Total|Bus|L1|L2|L3)(kVA)(?!R)'),       r'\1 \2'),
    # PowerFactor → Power Factor
    (re.compile(r'PowerFactor'),                            r'Power Factor'),
    # L1NVoltage / L2NVoltage / L3NVoltage → L1N Voltage
    (re.compile(r'(L[123]N)(Voltage)'),                    r'\1 \2'),
    (re.compile(r'(LL)(Average)'),                         r'\1 \2'),
    (re.compile(r'(LN)(Average)'),                         r'\1 \2'),
    # RunsReset → Runs Reset
    (re.compile(r'RunsReset'),                              r'Runs Reset'),
    # SyncSpeedControlMethod → Sync Speed Control Method
    (re.compile(r'SyncSpeedControlMethod'),                 r'Sync Speed Control Method'),
    # IdleWarmup (если где-то осталось)
    (re.compile(r'IdleWarmup'),                             r'Idle Warmup'),
    # LoadDump → Load Dump
    (re.compile(r'LoadDump'),                               r'Load Dump'),
    # LoadGovern → Load Govern
    (re.compile(r'LoadGovern'),                             r'Load Govern'),
    # TimeDelayto → Time Delay to
    (re.compile(r'TimeDelayto'),                            r'Time Delay to'),
    # ClearLost → Clear Lost
    (re.compile(r'ClearLost'),                              r'Clear Lost'),
    # SaveTrims → Save Trims
    (re.compile(r'SaveTrims'),                              r'Save Trims'),
    # AmpSentry ModeStatus → Mode Status
    (re.compile(r'ModeStatus'),                             r'Mode Status'),
    # ToolDetected → Tool Detected
    (re.compile(r'ToolDetected'),                           r'Tool Detected'),
    # V/HzKnee → V/Hz Knee
    (re.compile(r'V/HzKnee'),                               r'V/Hz Knee'),
    # GensetBus → Genset Bus
    (re.compile(r'GensetBus'),                              r'Genset Bus'),
    # GensetTotal → Genset Total
    (re.compile(r'GensetTotal'),                            r'Genset Total'),
    # UtilityTotal → Utility Total
    (re.compile(r'UtilityTotal'),                           r'Utility Total'),
    # UtilityL1/L2/L3 → Utility L1/L2/L3
    (re.compile(r'UtilityL([123])'),                        r'Utility L\1'),
    # GensetL1/L2/L3 → Genset L1/L2/L3
    (re.compile(r'GensetL([123])'),                         r'Genset L\1'),
    # GensetSerial → Genset Serial
    (re.compile(r'GensetSerial'),                           r'Genset Serial'),
    # VoltageBias → Voltage Bias
    (re.compile(r'VoltageBias'),                            r'Voltage Bias'),
    # SpeedBias → Speed Bias
    (re.compile(r'SpeedBias'),                              r'Speed Bias'),
    # DeviceType → Device Type
    (re.compile(r'DeviceType'),                             r'Device Type'),
    # GensetID → Genset ID
    (re.compile(r'GensetID'),                               r'Genset ID'),
    # Genset% → Genset %
    (re.compile(r'Genset%'),                                r'Genset %'),
    # kVAR и kW setpoints (UtilitykVAR, GensetkVAR, etc.)
    (re.compile(r'(Genset|Utility)(kVAR)'),                 r'\1 \2'),
    (re.compile(r'(Genset|Utility)(kW)(?!h)'),              r'\1 \2'),
    (re.compile(r'(Utility)(Power)'),                       r'\1 \2'),
    # FuelRate → Fuel Rate (если где-то осталось)
    (re.compile(r'FuelRate'),                               r'Fuel Rate'),
    # FuelTemp → Fuel Temperature
    (re.compile(r'FuelTemperature(?=\b)'),                  r'Fuel Temperature'),
    # TotalNumber → Total Number
    (re.compile(r'TotalNumber'),                            r'Total Number'),
    # Engine RunningTime → Engine Running Time
    (re.compile(r'RunningTime'),                            r'Running Time'),
    # TotalFuel → Total Fuel
    (re.compile(r'TotalFuel'),                              r'Total Fuel'),
    # RemoteStart → Remote Start
    (re.compile(r'RemoteStart'),                            r'Remote Start'),
    # FaultReset → Fault Reset
    (re.compile(r'FaultReset'),                             r'Fault Reset'),
    # WarmupTime → Warmup Time
    (re.compile(r'WarmupTime'),                             r'Warmup Time'),
    # RampTime → Ramp Time
    (re.compile(r'RampTime'),                               r'Ramp Time'),
    # DemandStart/Stop/Run → Demand Start/Stop/Run
    (re.compile(r'DemandStart'),                            r'Demand Start'),
    (re.compile(r'DemandStop'),                             r'Demand Stop'),
    (re.compile(r'DemandRun'),                              r'Demand Run'),
    # Лишние пробелы
    (re.compile(r'  +'),                                    r' '),
]


def normalize_name(name: str) -> str:
    for pat, repl in SPACING_RULES:
        name = pat.sub(repl, name)
    return name.strip()


def main():
    entries = []
    with open(MAP_FILE, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    idx = {(e['reg_type'], e['addr']): i for i, e in enumerate(entries)}

    direct_fixed = 0
    spacing_fixed = 0
    notes_fixed   = 0

    for i, e in enumerate(entries):
        addr = e['addr']
        old_name = e.get('name', '')

        # 1. Прямые замены
        if addr in NAME_FIXES:
            new_name = NAME_FIXES[addr]
            if e['name'] != new_name:
                # Если notes_ru был производным от старого имени — обновим
                notes = e.get('notes_ru', '')
                if notes.startswith(old_name[:30]):
                    suffix = notes[len(old_name):]
                    e['notes_ru'] = new_name + suffix
                    notes_fixed += 1
                e['name'] = new_name
                direct_fixed += 1
            continue  # spacing уже вшит в правильное имя

        # 2. Нормализация пробелов
        new_name = normalize_name(old_name)
        if new_name != old_name:
            notes = e.get('notes_ru', '')
            if notes.startswith(old_name[:30]):
                suffix = notes[len(old_name):]
                e['notes_ru'] = new_name + suffix
                notes_fixed += 1
            e['name'] = new_name
            spacing_fixed += 1

    with open(MAP_FILE, 'w', encoding='utf-8', newline='\n') as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')

    print(f"Прямые замены     : {direct_fixed}")
    print(f"Правка пробелов   : {spacing_fixed}")
    print(f"notes_ru обновлено: {notes_fixed}")

    # Проверим: остались ли >55 символов имена
    entries2 = [json.loads(l) for l in open(MAP_FILE, encoding='utf-8') if l.strip()]
    long_left = [(e['addr'], e['name']) for e in entries2 if len(e.get('name','')) > 55]
    if long_left:
        print(f"\nВсё ещё длинные имена ({len(long_left)}):")
        for addr, n in long_left:
            print(f"  {addr}: {n}")
    else:
        print("\nДлинных имён (>55 символов) не осталось.")


if __name__ == '__main__':
    main()
