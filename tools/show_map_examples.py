# Copyright (c) 2026 ООО «НГ-ЭНЕРГОСЕРВИС». Все права защищены.
# Программный комплекс «Честная Генерация»
# Модуль декодирования Modbus-телеметрии
# Автор: Саввиди Александр Анатольевич | ИНН 4725009270
#
# Данное программное обеспечение является конфиденциальным.
# Несанкционированное копирование, распространение или использование
# без письменного разрешения правообладателя запрещено.

import sys, json
sys.path.insert(0, '.')
import maps_loader as ml

ml.load_device_maps('pcc', 'devices/pcc')
loader = ml.get_loader('pcc')
payload = loader.build_metadata_payload('pcc')
regs = payload['registers']

# Найдём enum-регистр с labels_ru
enum_ex = next(((k, v) for k, v in regs.items() if 'labels_ru' in v), None)
# Найдём fault-регистр с хотя бы одним name_ru
fault_ex = next(((k, v) for k, v in regs.items()
                 if 'bits' in v and any('name_ru' in b for b in v['bits'].values())), None)

out = []

out.append('=== 1. RETAINED MAP (cg/v1/maps/pcc) — enum-регистр ===')
if enum_ex:
    k, v = enum_ex
    sample = {fld: v[fld] for fld in ('name','unit','labels','labels_ru') if fld in v}
    out.append(f'ключ: "{k}"')
    out.append(json.dumps(sample, ensure_ascii=False, indent=2))

out.append('')
out.append('=== 2. RETAINED MAP (cg/v1/maps/pcc) — fault-регистр (первые 3 бита) ===')
if fault_ex:
    k, v = fault_ex
    bits3 = {bk: v['bits'][bk] for bk in sorted(v['bits'], key=int)[:3]}
    sample = {'name': v.get('name'), 'unit': v.get('unit'), 'bits': bits3}
    out.append(f'ключ: "{k}"')
    out.append(json.dumps(sample, ensure_ascii=False, indent=2))

out.append('')
out.append('=== 3. DECODED MESSAGE (cg/v1/decoded/SN/...) — enum ===')
out.append(json.dumps({
    "addr": int(enum_ex[0]) if enum_ex else 40010,
    "name": enum_ex[1].get('name','') if enum_ex else '',
    "value": 1,
    "raw": 1
}, ensure_ascii=False, indent=2))

out.append('')
out.append('=== 4. DECODED MESSAGE (cg/v1/decoded/SN/...) — fault ===')
out.append(json.dumps({
    "addr": int(fault_ex[0]) if fault_ex else 40400,
    "name": fault_ex[1].get('name','') if fault_ex else '',
    "value": {"faults": [{"bit": 0, "name": "...", "severity": "shutdown"}], "unknown_bits": []},
    "raw": 1
}, ensure_ascii=False, indent=2))

sys.stdout.buffer.write('\n'.join(out).encode('utf-8'))
