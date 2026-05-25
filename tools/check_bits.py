import sys, json
sys.path.insert(0, '.')
import maps_loader as ml

ml.load_device_maps('pcc', 'devices/pcc')
loader = ml.get_loader('pcc')
bt = ml.get_bit_translations()

# Все уникальные имена битов из карты (имя -> количество вхождений)
all_bits: dict = {}
for bit_def in loader._fault_bitmap_map.values():
    name = bit_def.get('name', '')
    if name:
        all_bits[name] = all_bits.get(name, 0) + 1

total   = len(all_bits)
transl  = sum(1 for n in all_bits if n in bt)
missing = sorted([(n, c) for n, c in all_bits.items() if n not in bt], key=lambda x: -x[1])

lines = [
    f"Всего уникальных имён битов : {total}",
    f"Переведено                  : {transl}",
    f"Без перевода                : {len(missing)}",
    f"Покрытие                    : {transl*100//total}%",
    "",
    f"Первые 30 без перевода:",
]
for name, cnt in missing[:30]:
    marker = f"[{cnt}x] " if cnt > 1 else "       "
    lines.append(f"  {marker}{name}")

sys.stdout.buffer.write("\n".join(lines).encode("utf-8"))
