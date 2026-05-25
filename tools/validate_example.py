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
