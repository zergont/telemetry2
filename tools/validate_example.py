# Copyright (c) 2026 ООО «НГ-ЭНЕРГОСЕРВИС». Все права защищены.
# Программный комплекс «Честная Генерация»
# Модуль декодирования Modbus-телеметрии
# Автор: Саввиди Александр Анатольевич | ИНН 4725009270
#
# Данное программное обеспечение является конфиденциальным.
# Несанкционированное копирование, распространение или использование
# без письменного разрешения правообладателя запрещено.

import sys
sys.path.insert(0, ".")
import maps_loader as ml

ml.load_device_maps("pcc_example", "maps.example/pcc")
loader = ml.get_loader("pcc_example")

types = {}
for reg in loader._register_map.values():
    u = reg.get("unit", "—")
    types[u] = types.get(u, 0) + 1

for t, n in sorted(types.items()):
    sys.stdout.buffer.write(f"  {t:15s}: {n}\n".encode("utf-8"))
sys.stdout.buffer.write(f"  {'ИТОГО':15s}: {sum(types.values())}\n".encode("utf-8"))
