"""
Универсальный Modbus-декодер — Web UI

Простой веб-интерфейс на Flask для просмотра декодированных данных.
UI не знает ничего о Modbus — только отображает декодированные данные.
"""

import os
import logging
import time
from pathlib import Path
from typing import Optional
from flask import Flask, render_template_string, jsonify, abort, request

from panel_store import get_store, PanelStatus
from mqtt_client import get_mqtt_client
from maps_loader import (get_registered_device_types, get_device_stats, load_device_maps, remove_device,
                         add_to_ignore, remove_from_ignore, get_all_ignore_lists, clear_ignore_list)
from map_validator import validate_device_maps
from version import __version__

logger = logging.getLogger(__name__)

app = Flask(__name__)

# ============================================================
# HTML Templates (embedded for single-file simplicity)
# ============================================================

# Base HTML wrapper function
def wrap_content(title: str, content: str, auto_reload: bool = True) -> str:
    """Wrap content in base HTML template."""
    reload_script = "setTimeout(function() { location.reload(); }, 5000);" if auto_reload else ""
    return f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Modbus-декодер</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        header {{
            background: #2c3e50;
            color: white;
            padding: 15px 20px;
            margin-bottom: 20px;
        }}
        header h1 {{ font-size: 1.5rem; }}
        header a {{ color: #3498db; text-decoration: none; }}
        header a:hover {{ text-decoration: underline; }}
        .card {{
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            padding: 20px;
        }}
        .card h2 {{ 
            color: #2c3e50;
            margin-bottom: 15px;
            font-size: 1.2rem;
            border-bottom: 2px solid #3498db;
            padding-bottom: 10px;
        }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ 
            padding: 10px 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{ 
            background: #f8f9fa;
            font-weight: 600;
            color: #555;
        }}
        tr:hover {{ background: #f8f9fa; }}
        .status {{
            display: inline-block;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 500;
        }}
        .status-online {{ background: #27ae60; color: white; }}
        .status-stale {{ background: #f39c12; color: white; }}
        .status-offline {{ background: #e74c3c; color: white; }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .stat-box {{
            background: #3498db;
            color: white;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }}
        .stat-box.warning {{ background: #f39c12; }}
        .stat-box.error {{ background: #e74c3c; }}
        .stat-box.success {{ background: #27ae60; }}
        .stat-value {{ font-size: 2rem; font-weight: bold; }}
        .stat-label {{ font-size: 0.85rem; opacity: 0.9; }}
        .gps {{ color: #666; font-size: 0.9rem; }}
        .value-null {{ color: #999; font-style: italic; }}
        .value-fault {{ color: #e74c3c; }}
        .refresh-info {{ 
            text-align: right;
            color: #999;
            font-size: 0.85rem;
            margin-top: 10px;
        }}
        a.btn {{
            display: inline-block;
            padding: 8px 16px;
            background: #3498db;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            margin-right: 10px;
            margin-bottom: 5px;
        }}
        a.btn:hover {{ background: #2980b9; }}
        button.btn {{
            display: inline-block;
            padding: 8px 16px;
            background: #3498db;
            color: white;
            border: 0;
            border-radius: 4px;
            cursor: pointer;
            margin-right: 10px;
            margin-bottom: 5px;
            font-size: 0.95rem;
        }}
        button.btn:hover {{ background: #2980b9; }}
        button.btn-danger {{ background: #e74c3c; }}
        button.btn-danger:hover {{ background: #c0392b; }}
        .raw-value {{ color: #888; font-size: 0.85rem; }}
    </style>
</head>
<body>
    <header>
        <div class="container">
            <h1>
                <a href="/" style="color:white;text-decoration:none">🔌 Modbus-декодер</a>
                <a href="/devices" style="font-size:0.85rem;margin-left:20px">⚙️ Устройства</a>
                <span style="font-size:0.7rem;opacity:0.6;margin-left:15px">v{__version__}</span>
            </h1>
        </div>
    </header>
    <div class="container">
        {content}
    </div>
    <script>
        // Автообновление страницы каждые 5 секунд
        {reload_script}

        async function clearMemory() {{
            if (!confirm('Очистить все in-memory данные (роутеры, панели, регистры)?')) return;
            try {{
                const response = await fetch('/api/admin/clear-memory', {{ method: 'POST' }});
                if (!response.ok) throw new Error('HTTP ' + response.status);
                location.reload();
            }} catch (e) {{
                alert('Не удалось очистить память: ' + e);
            }}
        }}
    </script>
</body>
</html>
'''


INDEX_TEMPLATE = '''
<div class="stats">
    <div class="stat-box success">
        <div class="stat-value">{{ stats.routers }}</div>
        <div class="stat-label">Роутеры</div>
    </div>
    <div class="stat-box">
        <div class="stat-value">{{ stats.panels }}</div>
        <div class="stat-label">Панели</div>
    </div>
    <div class="stat-box success">
        <div class="stat-value">{{ stats.online }}</div>
        <div class="stat-label">Онлайн</div>
    </div>
    <div class="stat-box warning">
        <div class="stat-value">{{ stats.stale }}</div>
        <div class="stat-label">Нет данных</div>
    </div>
    <div class="stat-box error">
        <div class="stat-value">{{ stats.offline }}</div>
        <div class="stat-label">Офлайн</div>
    </div>
</div>

{% if mqtt_stats %}
<div class="card">
    <h2>📡 Статус MQTT</h2>
    <table>
        <tr>
            <td>Соединение</td>
            <td><span class="status {% if mqtt_stats.connected %}status-online{% else %}status-offline{% endif %}">
                {{ 'Подключен' if mqtt_stats.connected else 'Отключен' }}
            </span></td>
        </tr>
        <tr><td>Получено сообщений</td><td>{{ mqtt_stats.messages_received }}</td></tr>
        <tr><td>Декодировано</td><td>{{ mqtt_stats.messages_decoded }}</td></tr>
        <tr><td>Опубликовано</td><td>{{ mqtt_stats.messages_published }}</td></tr>
        <tr><td>Ошибки MQTT</td><td>{{ mqtt_stats.decode_errors }}</td></tr>
        <tr><td>Ошибки декодирования</td><td>{{ store_decode_errors }} <a href="/devices" style="font-size:0.8rem">(подробнее)</a></td></tr>
    </table>
</div>
{% endif %}

<div class="card">
    <h2>🏭 Роутеры и панели</h2>
    {% if routers %}
    <table>
        <thead>
            <tr>
                <th>Роутер SN</th>
                <th>GPS</th>
                <th>Панели</th>
                <th>Статус</th>
            </tr>
        </thead>
        <tbody>
        {% for router in routers %}
            <tr>
                <td><strong>{{ router.sn }}</strong></td>
                <td class="gps">
                    {% if router.gps_lat and router.gps_lon %}
                        📍 {{ "%.6f"|format(router.gps_lat) }}, {{ "%.6f"|format(router.gps_lon) }}
                        {% if router.gps_alt is not none %} | Alt: {{ "%.1f"|format(router.gps_alt) }}m{% endif %}
                        {% if router.gps_speed is not none %}<br>🚗 {{ "%.1f"|format(router.gps_speed) }} km/h{% endif %}
                        {% if router.gps_satellites is not none %} | 🛰️ {{ router.gps_satellites }} sat{% endif %}
                        {% if router.gps_time %}<br>🕐 {{ router.gps_time }}{% endif %}
                    {% else %}
                        <span class="value-null">Нет GPS</span>
                    {% endif %}
                </td>
                <td>
                    {% for panel in router.panels %}
                        <a href="/router/{{ router.sn }}/panel/{{ panel.bserver_id }}" class="btn">
                            {{ panel.device_type|upper }} #{{ panel.bserver_id }}
                            <span class="status status-{{ panel.status.value }}">{{ panel.status.value }}</span>
                        </a>
                    {% endfor %}
                </td>
                <td>
                    {{ router.panels|length }} панел(ь/ей)
                </td>
            </tr>
        {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p>Роутеры ещё не обнаружены. Ожидание телеметрии...</p>
    {% endif %}
</div>

<div class="card">
    <h2>🧹 Обслуживание</h2>
    <button class="btn btn-danger" onclick="clearMemory()">Очистить in-memory</button>
    <p class="gps">Удаляет все роутеры/панели/регистры из памяти. Новые данные появятся после следующих MQTT-сообщений.</p>
</div>

<div class="refresh-info">Автообновление каждые 5 секунд</div>
'''

PANEL_TEMPLATE = '''
<div class="card">
    <h2>
        <a href="/">← Назад</a> |
        Роутер: {{ router_sn }} | {{ panel.device_type|upper }} #{{ bserver_id }}
        <span class="status status-{{ panel.status.value }}">{{ panel.status.value }}</span>
    </h2>
    
    {% if router and router.gps_lat and router.gps_lon %}
    <p class="gps">
        📍 {{ "%.6f"|format(router.gps_lat) }}, {{ "%.6f"|format(router.gps_lon) }}
        {% if router.gps_speed is not none %} | 🚗 {{ "%.1f"|format(router.gps_speed) }} km/h{% endif %}
        {% if router.gps_satellites is not none %} | 🛰️ {{ router.gps_satellites }} sat{% endif %}
        {% if router.gps_time %} | 🕐 {{ router.gps_time }}{% endif %}
    </p>
    {% endif %}
    
    <p>Сообщений: {{ panel.message_count }} | Ошибок: {{ panel.decode_error_count }}</p>
</div>

<div class="card">
    <h2>📊 Регистры ({{ registers|length }})</h2>
    {% if registers %}
    <table>
        <thead>
            <tr>
                <th>Адрес</th>
                <th>Имя</th>
                <th>Значение</th>
                <th>Ед.изм.</th>
                <th>Raw</th>
            </tr>
        </thead>
        <tbody>
        {% for reg in registers %}
            <tr>
                <td>{{ reg.addr }}</td>
                <td>{{ reg.name or '-' }}</td>
                <td>
                    {% if reg.value is none %}
                        <span class="value-null">null</span>
                        {% if reg.reason %}<br><small>({{ reg.reason }})</small>{% endif %}
                    {% elif reg.unit == 'fault_bitmap' %}
                        {% if reg.value.faults %}
                            <span class="value-fault">
                            {% for fault in reg.value.faults %}
                                ⚠️ [Bit {{ fault.bit }}] {{ fault.name }} ({{ fault.severity }})<br>
                            {% endfor %}
                            </span>
                        {% endif %}
                        {% if reg.value.unknown_bits %}
                        <span class="raw-value">Неизвестные биты: {{ reg.value.unknown_bits|join(', ') }}</span>
                        {% endif %}
                        {% if not reg.value.faults and not reg.value.unknown_bits %}
                            <span class="value-null">Нет активных ошибок</span>
                        {% endif %}
                    {% elif reg.unit == 'bitfield' %}
                        {{ reg.value.hex }} (bits: {{ reg.value.active_bits|join(', ') or 'none' }})
                    {% elif reg.text %}
                        {{ reg.value }} <span class="raw-value">({{ reg.text }})</span>
                    {% elif reg.value is mapping %}
                        {{ reg.value }}
                    {% else %}
                        {{ reg.value }}
                    {% endif %}
                </td>
                <td>{{ reg.unit or '-' }}</td>
                <td class="raw-value">{{ reg.raw if reg.raw is not none else '-' }}</td>
            </tr>
        {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p>Регистры ещё не получены.</p>
    {% endif %}
</div>

<div class="refresh-info">Автообновление каждые 5 секунд</div>
'''


# ============================================================
# Routes
# ============================================================

@app.route('/')
def index():
    """Main page - show all routers and their panels."""
    store = get_store()
    mqtt = get_mqtt_client()
    
    stats = store.get_stats()
    
    # Get router data with panels
    routers_data = []
    for router in store.get_all_routers():
        panels = store.get_router_panels(router.sn)
        routers_data.append({
            'sn': router.sn,
            'gps_lat': router.gps_lat,
            'gps_lon': router.gps_lon,
            'gps_alt': router.gps_alt,
            'gps_speed': router.gps_speed,
            'gps_satellites': router.gps_satellites,
            'gps_time': router.gps_time,
            'panels': panels
        })
    
    # Sort by SN
    routers_data.sort(key=lambda r: r['sn'])
    
    mqtt_stats = mqtt.get_stats() if mqtt else None
    store_decode_errors = len(store.get_decode_errors())

    # Render content first
    content = render_template_string(
        INDEX_TEMPLATE,
        stats=stats,
        routers=routers_data,
        mqtt_stats=mqtt_stats,
        store_decode_errors=store_decode_errors
    )
    
    # Wrap in base template
    return wrap_content('Dashboard', content)


@app.route('/router/<router_sn>/panel/<int:bserver_id>')
def panel_view(router_sn: str, bserver_id: int):
    """Panel detail page - show all registers."""
    store = get_store()
    
    panel = store.get_panel(router_sn, bserver_id)
    if not panel:
        abort(404, f"Panel not found: {router_sn}:{bserver_id}")
    
    router = store.get_router(router_sn)
    registers = store.get_panel_registers(router_sn, bserver_id)
    
    # Render content first
    content = render_template_string(
        PANEL_TEMPLATE,
        router_sn=router_sn,
        bserver_id=bserver_id,
        panel=panel,
        router=router,
        registers=registers
    )
    
    # Wrap in base template
    return wrap_content(f'Panel {bserver_id}', content)


@app.route('/api/stats')
def api_stats():
    """API endpoint for stats."""
    store = get_store()
    mqtt = get_mqtt_client()
    
    return jsonify({
        'store': store.get_stats(),
        'mqtt': mqtt.get_stats() if mqtt else None
    })


@app.route('/api/routers')
def api_routers():
    """API endpoint for routers list."""
    store = get_store()
    
    routers = []
    for router in store.get_all_routers():
        panels = store.get_router_panels(router.sn)
        routers.append({
            'sn': router.sn,
            'gps_lat': router.gps_lat,
            'gps_lon': router.gps_lon,
            'gps_time': router.gps_time,
            'panel_count': len(panels),
            'panels': [
                {
                    'bserver_id': p.bserver_id,
                    'device_type': p.device_type,
                    'status': p.status.value,
                    'message_count': p.message_count
                }
                for p in panels
            ]
        })
    
    return jsonify(routers)


@app.route('/api/router/<router_sn>/panel/<int:bserver_id>/registers')
def api_panel_registers(router_sn: str, bserver_id: int):
    """API endpoint for panel registers."""
    store = get_store()
    
    panel = store.get_panel(router_sn, bserver_id)
    if not panel:
        abort(404)
    
    registers = store.get_panel_registers(router_sn, bserver_id)
    
    return jsonify({
        'router_sn': router_sn,
        'bserver_id': bserver_id,
        'device_type': panel.device_type,
        'status': panel.status.value,
        'registers': registers
    })


@app.route('/api/admin/clear-memory', methods=['POST'])
def api_clear_memory():
    """API endpoint to clear in-memory store."""
    store = get_store()
    cleared = store.clear()
    logger.warning(f"Выполнена очистка in-memory: routers={cleared['routers']}, panels={cleared['panels']}")
    return jsonify({
        'ok': True,
        'cleared': cleared
    })


@app.route('/api/version')
def api_version():
    """API endpoint for application version."""
    return jsonify({'version': __version__})


# ============================================================
# Device Management
# ============================================================

DEVICES_TEMPLATE = '''
<div class="card">
    <h2>📋 Подключённые устройства</h2>
    {% if devices %}
    <table>
        <thead>
            <tr>
                <th>Тип</th>
                <th>Регистры</th>
                <th>Enum</th>
                <th>Faults</th>
                <th>Payload keys</th>
                <th>Действия</th>
            </tr>
        </thead>
        <tbody>
        {% for d in devices %}
            <tr>
                <td><strong>{{ d.device_type|upper }}</strong></td>
                <td>{{ d.register_count }}</td>
                <td>{{ d.enum_count }}</td>
                <td>{{ d.fault_count }}</td>
                <td>{{ d.payload_keys|join(', ') or '—' }}</td>
                <td>
                    <button class="btn btn-danger" style="padding:4px 10px;font-size:0.8rem"
                        onclick="removeDevice('{{ d.device_type }}')">Удалить</button>
                </td>
            </tr>
        {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p>Нет подключённых устройств.</p>
    {% endif %}
</div>

<div class="card">
    <h2>🔍 Обнаружены, но не настроены</h2>
    {% if unknown_keys %}
    <table>
        <thead>
            <tr><th>Ключ payload</th><th>Сообщений</th><th>Последнее</th><th></th></tr>
        </thead>
        <tbody>
        {% for key, info in unknown_keys.items() %}
            <tr>
                <td><strong>{{ key }}</strong></td>
                <td>{{ info.count }}</td>
                <td>{{ info.last_seen_ago }}</td>
                <td><button type="button" class="btn btn-danger" style="padding:2px 8px;font-size:0.75rem"
                    onclick="clearUnknownKey('{{ key }}')">✕</button></td>
            </tr>
        {% endfor %}
        </tbody>
    </table>
    <div style="margin-top:10px">
        <button type="button" class="btn btn-danger" onclick="clearAllUnknownKeys()">Сбросить все</button>
    </div>
    {% else %}
    <p style="color:#999">Нет неопознанных ключей</p>
    {% endif %}
</div>

<div class="card" id="decode-errors-card">
    <h2>⚠️ Ошибки декодирования <span id="errors-count">({{ decode_errors|length }})</span></h2>
    <div id="decode-errors-body">
    {% if decode_errors %}
    <table>
        <thead>
            <tr><th>Время</th><th>Роутер</th><th>Панель</th><th>Тип</th><th>Адрес</th><th>Причина</th><th>Raw</th><th></th></tr>
        </thead>
        <tbody>
        {% for e in decode_errors %}
            <tr>
                <td style="font-size:0.8rem">{{ e.time_ago }}</td>
                <td>{{ e.router_sn }}</td>
                <td>{{ e.bserver_id }}</td>
                <td>{{ e.device_type }}</td>
                <td>{{ e.addr }}</td>
                <td>{{ e.reason }}</td>
                <td class="raw-value">{{ e.raw_data or '—' }}</td>
                <td><button class="btn" style="padding:2px 8px;font-size:0.75rem"
                    onclick="ignoreRegister('{{ e.device_type }}', '{{ e.addr }}')">Игнор</button></td>
            </tr>
        {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p style="color:#999">Нет ошибок</p>
    {% endif %}
    </div>
    <div style="margin-top:10px">
        <button class="btn" onclick="refreshErrors()">🔄 Обновить</button>
        <button class="btn btn-danger" onclick="clearErrors()">Очистить ошибки</button>
    </div>
</div>

{% if ignore_lists %}
<div class="card">
    <h2>🔇 Игнорируемые регистры</h2>
    {% for device_type, registers in ignore_lists.items() %}
    <h3 style="margin:10px 0 5px;font-size:0.95rem">{{ device_type|upper }} ({{ registers|length }})</h3>
    <table>
        <thead>
            <tr><th>Регистр</th><th>Комментарий</th><th></th></tr>
        </thead>
        <tbody>
        {% for key, comment in registers.items() %}
            <tr>
                <td><strong>{{ key }}</strong></td>
                <td style="color:#666;font-size:0.9rem">{{ comment }}</td>
                <td><button class="btn btn-danger" style="padding:2px 8px;font-size:0.75rem"
                    onclick="unignoreRegister('{{ device_type }}', '{{ key }}')">Вернуть</button></td>
            </tr>
        {% endfor %}
        </tbody>
    </table>
    <button class="btn btn-danger" style="margin-top:5px;font-size:0.8rem"
        onclick="clearIgnoreList('{{ device_type }}')">Сбросить все для {{ device_type|upper }}</button>
    {% endfor %}
</div>
{% endif %}

<div class="card">
    <h2>➕ Добавить устройство</h2>
    <form id="add-device-form" enctype="multipart/form-data">
        <table>
            <tr>
                <td><strong>Имя устройства</strong> <small>(латиница, без пробелов)</small></td>
                <td><input type="text" name="device_type" placeholder="dse" required
                    style="padding:6px;width:200px;border:1px solid #ccc;border-radius:4px"></td>
            </tr>
            <tr>
                <td><strong>Payload keys</strong> <small>(через запятую)</small></td>
                <td><input type="text" name="payload_keys" placeholder="DSE_8610,Modbus_DSE" required
                    style="padding:6px;width:300px;border:1px solid #ccc;border-radius:4px"></td>
            </tr>
            <tr>
                <td><strong>register_map.jsonl</strong> <small>(обязательно)</small></td>
                <td><input type="file" name="register_map" accept=".jsonl" required></td>
            </tr>
            <tr>
                <td><strong>enum_map.json</strong> <small>(опционально)</small></td>
                <td><input type="file" name="enum_map" accept=".json"></td>
            </tr>
            <tr>
                <td><strong>fault_bitmap_map.jsonl</strong> <small>(опционально)</small></td>
                <td><input type="file" name="fault_bitmap_map" accept=".jsonl"></td>
            </tr>
        </table>
        <div style="margin-top:15px">
            <button type="button" class="btn" onclick="validateDevice()">✅ Проверить</button>
            <button type="button" id="btn-save" class="btn" style="background:#999;cursor:not-allowed" onclick="addDevice()" disabled>💾 Сохранить и запустить</button>
        </div>
        <div id="form-result" style="margin-top:10px"></div>
    </form>
</div>

<div class="card">
    <h2>📝 Как подготовить карты регистров</h2>
    <ol style="padding-left:20px;line-height:2">
        <li>Возьмите документацию на устройство (PDF с описанием Modbus-регистров)</li>
        <li>Скопируйте промпт ниже и отправьте его вместе с документацией в любой ИИ (ChatGPT, Claude и т.д.)</li>
        <li>На выходе получите файлы <code>register_map.jsonl</code>, <code>enum_map.json</code>, <code>fault_bitmap_map.jsonl</code></li>
        <li>Загрузите файлы через форму выше</li>
    </ol>
    <details style="margin-top:15px">
        <summary style="cursor:pointer;font-weight:600;color:#3498db">📋 Показать промпт для ИИ</summary>
        <pre id="ai-prompt" style="margin-top:10px;background:#f8f9fa;padding:15px;border-radius:4px;font-size:0.85rem;white-space:pre-wrap;border:1px solid #ddd;max-height:400px;overflow-y:auto">Преобразуй документацию Modbus-регистров в три файла для декодера.

ФОРМАТ 1: register_map.jsonl (каждая строка — отдельный JSON-объект)
{"addr": 40010, "reg_type": "holding", "name": "Engine Speed", "data_type": "u16", "word_len": 1, "multiplier": 1.0, "offset": 0.0, "unit": "rpm", "na_values": [65535], "description": "Обороты двигателя"}

Допустимые data_type: u16, s16, u32, s32, f32, raw, char, bitfield
Допустимые reg_type: holding, input
Для enum-регистров: unit = "enum"
word_len: 1 для 16-бит, 2 для 32-бит типов

ФОРМАТ 2: enum_map.json (один JSON-объект)
{
  "holding:40010": {"0": "Off", "1": "On", "2": "Error"},
  "holding:40011": {"0": "Stop", "1": "Run"}
}
Ключ = "reg_type:addr", значения = {"числовое_значение_строкой": "текстовая_метка"}

ФОРМАТ 3: fault_bitmap_map.jsonl (каждая строка — отдельный JSON-объект)
{"addr": 40400, "reg_type": "holding", "bit": 0, "name": "Low Oil Pressure", "severity": "warning", "description": "Низкое давление масла"}

bit: от 0 до 15 (позиция бита в 16-битном регистре)
severity: info, warning, critical

Правила:
- Адрес addr = 40000 + смещение из документации
- Каждая строка JSONL — валидный JSON
- Кодировка UTF-8
- Числа без кавычек, строки в кавычках</pre>
        <button class="btn" style="margin-top:5px;font-size:0.8rem" onclick="copyPrompt()">📋 Копировать промпт</button>
    </details>
</div>

'''

DEVICES_SCRIPT = '''<script>
async function validateDevice() {
    const form = document.getElementById('add-device-form');
    const data = new FormData(form);
    const result = document.getElementById('form-result');
    const btnSave = document.getElementById('btn-save');
    btnSave.disabled = true;
    btnSave.style.background = '#999';
    btnSave.style.cursor = 'not-allowed';
    result.innerHTML = 'Проверка...';
    try {
        const resp = await fetch('/api/devices/validate', {method: 'POST', body: data});
        if (!resp.ok) { result.innerHTML = '<span style="color:#e74c3c">Ошибка сервера: HTTP ' + resp.status + '</span>'; return; }
        const json = await resp.json();
        if (json.valid) {
            result.innerHTML = '<span style="color:#27ae60;font-weight:bold">✅ Карты валидны! ' +
                'Регистры: ' + json.register_map.count +
                ', Enum: ' + json.enum_map.count +
                ', Faults: ' + json.fault_bitmap_map.count + '</span>';
            btnSave.disabled = false;
            btnSave.style.background = '#27ae60';
            btnSave.style.cursor = 'pointer';
        } else {
            var html = '<span style="color:#e74c3c;font-weight:bold">❌ Найдены ошибки (' + json.total_errors + '):</span><ul>';
            var allErrors = (json.register_map.errors || [])
                .concat(json.enum_map.errors || [])
                .concat(json.fault_bitmap_map.errors || []);
            allErrors.slice(0, 20).forEach(function(e) { html += '<li style="color:#e74c3c;font-size:0.9rem">' + e + '</li>'; });
            if (allErrors.length > 20) html += '<li>...ещё ' + (allErrors.length - 20) + ' ошибок</li>';
            html += '</ul>';
            result.innerHTML = html;
        }
    } catch (e) { result.innerHTML = '<span style="color:#e74c3c">Ошибка: ' + e + '</span>'; }
}

async function addDevice() {
    const form = document.getElementById('add-device-form');
    const data = new FormData(form);
    const result = document.getElementById('form-result');
    result.innerHTML = 'Сохранение...';
    try {
        const resp = await fetch('/api/devices/add', {method: 'POST', body: data});
        var text = await resp.text();
        var json;
        try { json = JSON.parse(text); } catch(pe) {
            result.innerHTML = '<span style="color:#e74c3c">Ошибка сервера (HTTP ' + resp.status + '): ' + text.substring(0, 200) + '</span>';
            return;
        }
        if (json.ok) {
            result.innerHTML = '<span style="color:#27ae60;font-weight:bold">✅ ' + json.message + '</span>';
            setTimeout(function() { location.reload(); }, 1500);
        } else {
            result.innerHTML = '<span style="color:#e74c3c;font-weight:bold">❌ ' + json.error + '</span>';
        }
    } catch (e) { result.innerHTML = '<span style="color:#e74c3c">Ошибка: ' + e + '</span>'; }
}

async function removeDevice(deviceType) {
    if (!confirm('Удалить устройство "' + deviceType + '"? Файлы карт НЕ удаляются.')) return;
    try {
        const resp = await fetch('/api/devices/' + deviceType, {method: 'DELETE'});
        const json = await resp.json();
        if (json.ok) location.reload();
        else alert('Ошибка: ' + json.error);
    } catch (e) { alert('Ошибка: ' + e); }
}

async function clearErrors() {
    try {
        await fetch('/api/decode-errors', {method: 'DELETE'});
        refreshErrors();
    } catch (e) { alert('Ошибка: ' + e); }
}

function formatAge(ts) {
    const age = (Date.now() / 1000) - ts;
    if (age < 60) return Math.floor(age) + 'с назад';
    if (age < 3600) return Math.floor(age / 60) + 'м назад';
    return Math.floor(age / 3600) + 'ч назад';
}

async function refreshErrors() {
    try {
        const resp = await fetch('/api/decode-errors', {cache: 'no-store'});
        const errors = await resp.json();
        const body = document.getElementById('decode-errors-body');
        const count = document.getElementById('errors-count');
        count.textContent = '(' + errors.length + ')';
        if (errors.length === 0) {
            body.innerHTML = '<p style="color:#999">Нет ошибок</p>';
            return;
        }
        let html = '<table><thead><tr><th>Время</th><th>Роутер</th><th>Панель</th><th>Тип</th><th>Адрес</th><th>Причина</th><th>Raw</th><th></th></tr></thead><tbody>';
        errors.forEach(function(e) {
            html += '<tr><td style="font-size:0.8rem">' + formatAge(e.timestamp) + '</td>'
                + '<td>' + e.router_sn + '</td>'
                + '<td>' + e.bserver_id + '</td>'
                + '<td>' + e.device_type + '</td>'
                + '<td>' + e.addr + '</td>'
                + '<td>' + e.reason + '</td>'
                + '<td class="raw-value">' + (e.raw_data || '—') + '</td>'
                + '<td><button type="button" class="btn" style="padding:2px 8px;font-size:0.75rem" onclick="ignoreRegister(\\'' + e.device_type + '\\', \\'' + e.addr + '\\')">Игнор</button></td></tr>';
        });
        html += '</tbody></table>';
        body.innerHTML = html;
    } catch (e) { alert('Ошибка загрузки: ' + e); }
}

async function ignoreRegister(deviceType, addr) {
    var comment = prompt('Комментарий (необязательно):', 'Не используется по документации');
    if (comment === null) return;
    try {
        const resp = await fetch('/api/ignore', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({device_type: deviceType, addr: parseInt(addr), comment: comment})
        });
        const json = await resp.json();
        if (json.ok) location.reload();
        else alert('Ошибка: ' + json.error);
    } catch (e) { alert('Ошибка: ' + e); }
}

async function unignoreRegister(deviceType, key) {
    try {
        const resp = await fetch('/api/ignore', {
            method: 'DELETE',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({device_type: deviceType, key: key})
        });
        const json = await resp.json();
        if (json.ok) location.reload();
        else alert('Ошибка: ' + json.error);
    } catch (e) { alert('Ошибка: ' + e); }
}

async function clearUnknownKey(key) {
    try {
        const resp = await fetch('/api/discovery/' + encodeURIComponent(key), {method: 'DELETE'});
        const json = await resp.json();
        if (json.ok) location.reload();
        else alert('Ошибка: ' + json.error);
    } catch (e) { alert('Ошибка: ' + e); }
}

async function clearAllUnknownKeys() {
    if (!confirm('Сбросить все неопознанные ключи?')) return;
    try {
        const resp = await fetch('/api/discovery', {method: 'DELETE'});
        const json = await resp.json();
        if (json.ok) location.reload();
        else alert('Ошибка: ' + json.error);
    } catch (e) { alert('Ошибка: ' + e); }
}

async function clearIgnoreList(deviceType) {
    if (!confirm('Сбросить весь ignore-list для "' + deviceType + '"?')) return;
    try {
        const resp = await fetch('/api/ignore/' + deviceType, {method: 'DELETE'});
        const json = await resp.json();
        if (json.ok) location.reload();
        else alert('Ошибка: ' + json.error);
    } catch (e) { alert('Ошибка: ' + e); }
}

function copyPrompt() {
    var text = document.getElementById('ai-prompt').textContent;
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function() { alert('Промпт скопирован!'); }).catch(function() { fallbackCopy(text); });
    } else {
        fallbackCopy(text);
    }
}

function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); alert('Промпт скопирован!'); }
    catch(e) { alert('Не удалось скопировать. Выделите текст вручную.'); }
    document.body.removeChild(ta);
}

document.addEventListener('DOMContentLoaded', function() {
    var details = document.querySelectorAll('details');
    for (var i = 0; i < details.length; i++) {
        (function(el, idx) {
            var key = 'details_state_' + idx;
            if (sessionStorage.getItem(key) === 'open') el.open = true;
            el.addEventListener('toggle', function() {
                sessionStorage.setItem(key, el.open ? 'open' : 'closed');
            });
        })(details[i], i);
    }
});
</script>'''


@app.route('/devices')
def devices_page():
    """Device management page."""
    mqtt = get_mqtt_client()
    store = get_store()

    # Configured devices
    devices = []
    device_types = get_registered_device_types()
    # Get payload key map from mqtt client
    key_map = mqtt._payload_key_map if mqtt else {}

    for dt in device_types:
        stats = get_device_stats(dt)
        payload_keys = [k for k, v in key_map.items() if v == dt]
        devices.append({
            'device_type': dt,
            'register_count': stats['register_count'] if stats else 0,
            'enum_count': stats['enum_count'] if stats else 0,
            'fault_count': stats['fault_count'] if stats else 0,
            'payload_keys': payload_keys,
        })

    # Unknown keys from auto-discovery
    unknown_keys = {}
    if mqtt:
        raw_unknown = mqtt.get_unknown_keys()
        now = time.time()
        for key, info in raw_unknown.items():
            age = now - info['last_seen']
            if age < 60:
                ago = f"{int(age)}с назад"
            elif age < 3600:
                ago = f"{int(age/60)}м назад"
            else:
                ago = f"{int(age/3600)}ч назад"
            unknown_keys[key] = {
                'count': info['count'],
                'last_seen_ago': ago
            }

    # Decode errors
    raw_errors = store.get_decode_errors(30)
    now = time.time()
    decode_errors = []
    for e in raw_errors:
        age = now - e['timestamp']
        if age < 60:
            ago = f"{int(age)}с назад"
        elif age < 3600:
            ago = f"{int(age/60)}м назад"
        else:
            ago = f"{int(age/3600)}ч назад"
        decode_errors.append({**e, 'time_ago': ago})

    # Ignore lists
    ignore_lists = get_all_ignore_lists()

    content = render_template_string(
        DEVICES_TEMPLATE,
        devices=devices,
        unknown_keys=unknown_keys,
        decode_errors=decode_errors,
        ignore_lists=ignore_lists
    )
    html = wrap_content('Устройства', content, auto_reload=False)
    # Вставляем скрипт устройств перед </body>, вне контейнера
    return html.replace('</body>', DEVICES_SCRIPT + '\n</body>')


@app.route('/api/devices/validate', methods=['POST'])
def api_validate_device():
    """Validate uploaded map files without saving."""
    import tempfile
    import shutil

    device_type = request.form.get('device_type', '').strip().lower()
    if not device_type:
        return jsonify({'valid': False, 'error': 'Не указано имя устройства'}), 400

    # Save uploaded files to temp dir for validation
    tmpdir = tempfile.mkdtemp()
    try:
        reg_file = request.files.get('register_map')
        if reg_file and reg_file.filename:
            reg_file.save(os.path.join(tmpdir, 'register_map.jsonl'))

        enum_file = request.files.get('enum_map')
        if enum_file and enum_file.filename:
            enum_file.save(os.path.join(tmpdir, 'enum_map.json'))

        fault_file = request.files.get('fault_bitmap_map')
        if fault_file and fault_file.filename:
            fault_file.save(os.path.join(tmpdir, 'fault_bitmap_map.jsonl'))

        result = validate_device_maps(tmpdir)
        return jsonify(result)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.route('/api/devices/add', methods=['POST'])
def api_add_device():
    """Add a new device: save maps, update config, hot reload."""
    import tempfile
    import shutil

    try:
        device_type = request.form.get('device_type', '').strip().lower()
        payload_keys_str = request.form.get('payload_keys', '').strip()

        if not device_type:
            return jsonify({'ok': False, 'error': 'Не указано имя устройства'}), 400
        if not device_type.isalnum():
            return jsonify({'ok': False, 'error': 'Имя устройства: только латиница и цифры'}), 400
        if not payload_keys_str:
            return jsonify({'ok': False, 'error': 'Не указаны payload keys'}), 400

        payload_keys = [k.strip() for k in payload_keys_str.split(',') if k.strip()]

        # Save files to maps/<device_type>/
        maps_dir = os.path.join('maps', device_type)
        os.makedirs(maps_dir, exist_ok=True)

        reg_file = request.files.get('register_map')
        if not reg_file or not reg_file.filename:
            return jsonify({'ok': False, 'error': 'register_map.jsonl обязателен'}), 400

        # Save to temp first, validate, then move
        tmpdir = tempfile.mkdtemp()
        try:
            reg_file.save(os.path.join(tmpdir, 'register_map.jsonl'))

            enum_file = request.files.get('enum_map')
            if enum_file and enum_file.filename:
                enum_file.save(os.path.join(tmpdir, 'enum_map.json'))

            fault_file = request.files.get('fault_bitmap_map')
            if fault_file and fault_file.filename:
                fault_file.save(os.path.join(tmpdir, 'fault_bitmap_map.jsonl'))

            # Validate
            validation = validate_device_maps(tmpdir)
            if not validation['valid']:
                return jsonify({'ok': False, 'error': f"Карты невалидны ({validation['total_errors']} ошибок). Проверьте сначала."}), 400

            # Move only uploaded files to final location
            for filename in os.listdir(tmpdir):
                shutil.copy2(os.path.join(tmpdir, filename), os.path.join(maps_dir, filename))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        # Load maps (hot reload)
        ok = load_device_maps(device_type, maps_dir)
        if not ok:
            return jsonify({'ok': False, 'error': 'Не удалось загрузить карты'}), 500

        # Update MQTT client payload key mapping
        mqtt = get_mqtt_client()
        if mqtt:
            new_map = {key: device_type for key in payload_keys}
            mqtt.update_payload_key_map(new_map)

        # Update config.yaml
        _update_config_devices(device_type, maps_dir, payload_keys)

        logger.info(f"Устройство '{device_type}' добавлено: keys={payload_keys}, maps={maps_dir}")
        return jsonify({
            'ok': True,
            'message': f"Устройство '{device_type}' добавлено и запущено"
        })
    except Exception as e:
        logger.exception(f"Ошибка при добавлении устройства: {e}")
        return jsonify({'ok': False, 'error': f"Внутренняя ошибка: {str(e)}"}), 500


@app.route('/api/devices/<device_type>', methods=['DELETE'])
def api_remove_device(device_type: str):
    """Remove a device type from runtime (files are kept)."""
    removed = remove_device(device_type)
    if not removed:
        return jsonify({'ok': False, 'error': f"Устройство '{device_type}' не найдено"}), 404

    # Remove payload keys from MQTT client
    mqtt = get_mqtt_client()
    if mqtt:
        with mqtt._lock:
            keys_to_remove = [k for k, v in mqtt._payload_key_map.items() if v == device_type]
            for k in keys_to_remove:
                del mqtt._payload_key_map[k]

    logger.info(f"Устройство '{device_type}' удалено из runtime")
    return jsonify({'ok': True})


@app.route('/api/discovery')
def api_discovery():
    """API endpoint for auto-discovered unknown keys."""
    mqtt = get_mqtt_client()
    if not mqtt:
        return jsonify({})
    return jsonify(mqtt.get_unknown_keys())


@app.route('/api/discovery', methods=['DELETE'])
def api_clear_all_discovery():
    """Clear all unknown keys."""
    mqtt = get_mqtt_client()
    if not mqtt:
        return jsonify({'ok': False, 'error': 'MQTT не инициализирован'}), 500
    count = mqtt.clear_all_unknown_keys()
    return jsonify({'ok': True, 'cleared': count})


@app.route('/api/discovery/<path:key>', methods=['DELETE'])
def api_clear_discovery_key(key: str):
    """Remove a single unknown key."""
    mqtt = get_mqtt_client()
    if not mqtt:
        return jsonify({'ok': False, 'error': 'MQTT не инициализирован'}), 500
    found = mqtt.clear_unknown_key(key)
    if found:
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': f"Ключ '{key}' не найден"}), 404


@app.route('/api/decode-errors')
def api_decode_errors():
    """API endpoint for recent decode errors."""
    store = get_store()
    return jsonify(store.get_decode_errors())


@app.route('/api/decode-errors', methods=['DELETE'])
def api_clear_decode_errors():
    """Clear decode error log."""
    store = get_store()
    count = store.clear_decode_errors()
    return jsonify({'ok': True, 'cleared': count})


# ============================================================
# Ignore List API
# ============================================================

@app.route('/api/ignore', methods=['GET'])
def api_get_ignore():
    """Get all ignore lists."""
    return jsonify(get_all_ignore_lists())


@app.route('/api/ignore', methods=['POST'])
def api_add_ignore():
    """Add a register to ignore list."""
    data = request.get_json()
    if not data:
        return jsonify({'ok': False, 'error': 'No JSON body'}), 400

    device_type = data.get('device_type', '')
    addr = data.get('addr')
    comment = data.get('comment', '')

    if not device_type or addr is None:
        return jsonify({'ok': False, 'error': 'device_type и addr обязательны'}), 400

    ok, err = add_to_ignore(device_type, 'holding', int(addr), comment)
    if ok:
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': err}), 400


@app.route('/api/ignore', methods=['DELETE'])
def api_remove_ignore():
    """Remove a register from ignore list."""
    data = request.get_json()
    if not data:
        return jsonify({'ok': False, 'error': 'No JSON body'}), 400

    device_type = data.get('device_type', '')
    key = data.get('key', '')  # format "holding:40585"

    if not device_type or not key:
        return jsonify({'ok': False, 'error': 'device_type и key обязательны'}), 400

    parts = key.split(':')
    if len(parts) != 2:
        return jsonify({'ok': False, 'error': 'Неверный формат ключа (ожидается reg_type:addr)'}), 400

    ok = remove_from_ignore(device_type, parts[0], int(parts[1]))
    if ok:
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Регистр не найден в ignore-list'}), 404


@app.route('/api/ignore/<device_type>', methods=['DELETE'])
def api_clear_ignore(device_type: str):
    """Clear entire ignore list for a device type."""
    count = clear_ignore_list(device_type)
    return jsonify({'ok': True, 'cleared': count})


def _update_config_devices(device_type: str, maps_dir: str, payload_keys: list):
    """Update config.yaml with new device entry."""
    import yaml

    config_path = Path('config.yaml')
    if not config_path.exists():
        return

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}

        if 'devices' not in config:
            config['devices'] = {}

        config['devices'][device_type] = {
            'maps_dir': maps_dir,
            'payload_keys': payload_keys
        }

        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        logger.info(f"config.yaml обновлён: добавлено устройство '{device_type}'")
    except Exception as e:
        logger.error(f"Ошибка обновления config.yaml: {e}")


def run_web_ui(host: str = '0.0.0.0', port: int = 8080, debug: bool = False):
    """Run the web UI server."""
    logger.info(f"Web UI запущен на http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, use_reloader=False, threaded=True)
