import sys, json
import maps_loader as ml

n = ml.load_label_translations()
ml.load_device_maps('pcc', 'devices/pcc')
loader = ml.get_loader('pcc')
payload = loader.build_metadata_payload('pcc')
regs = payload['registers']

with_ru    = {k: v for k, v in regs.items() if 'labels_ru' in v}
without_ru = {k: v for k, v in regs.items() if 'labels' in v and 'labels_ru' not in v}

out = []
out.append(f"Translations loaded    : {n}")
out.append(f"Regs with labels_ru    : {len(with_ru)}")
out.append(f"Regs without labels_ru : {len(without_ru)}")
out.append("")
out.append("Examples with labels_ru:")
for k, v in list(with_ru.items())[:3]:
    out.append(f"  [{k}] {v.get('name', '')}")
    out.append(f"    EN: {v['labels']}")
    out.append(f"    RU: {v['labels_ru']}")
if without_ru:
    out.append("")
    out.append("Labels missing translation (first 10 unique values):")
    missing_vals = set()
    for v in without_ru.values():
        missing_vals.update(v['labels'].values())
    for mv in sorted(missing_vals)[:10]:
        out.append(f"  '{mv}'")

sys.stdout.buffer.write("\n".join(out).encode("utf-8"))
