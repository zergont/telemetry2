# Copyright (c) 2026 ООО «НГ-ЭНЕРГОСЕРВИС». Все права защищены.
# Программный комплекс «Честная Генерация»
# Модуль декодирования Modbus-телеметрии
# Автор: Саввиди Александр Анатольевич | ИНН 4725009270
#
# Данное программное обеспечение является конфиденциальным.
# Несанкционированное копирование, распространение или использование
# без письменного разрешения правообладателя запрещено.

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
from flask import Flask, render_template_string, jsonify, abort, request, send_file

from panel_store import get_store, PanelStatus
from mqtt_client import get_mqtt_client
from maps_loader import (get_registered_device_types, get_device_stats, load_device_maps, remove_device,
                         add_to_ignore, remove_from_ignore, get_all_ignore_lists, clear_ignore_list,
                         get_label_translations, save_label_translations,
                         get_bit_translations, save_bit_translations,
                         get_map_editor_data, save_notes_ru,
                         get_device_maps_dir)
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
                <a href="/translations" style="font-size:0.85rem;margin-left:20px">🌐 Переводы</a>
                <a href="/map-editor" style="font-size:0.85rem;margin-left:20px">📋 Карта</a>
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


RAW_TEMPLATE = '''
<div class="card">
    <h2>⚠️ Необработанные сообщения <span style="font-size:0.85rem;font-weight:normal;color:#999">(последние {{ messages|length }} из 10)</span></h2>
    <div style="margin-bottom:15px">
        <a href="/" class="btn">← Главная</a>
        <button class="btn btn-danger" onclick="clearRaw()">🗑️ Очистить все</button>
    </div>
    {% if messages %}
    {% for msg in messages|reverse %}
    <details style="margin-bottom:8px;border:1px solid #ffeeba;border-radius:4px;background:#fffef8">
        <summary style="cursor:pointer;padding:10px;font-size:0.9rem;list-style:none;display:flex;align-items:center;gap:8px">
            <span style="display:inline-block;padding:2px 8px;border-radius:3px;font-size:0.78rem;white-space:nowrap;
                {%- if msg.reason in ('json_error', 'missing_fields', 'exception') %} background:#e74c3c;color:white
                {%- elif msg.reason == 'no_registers' %} background:#f39c12;color:white
                {%- else %} background:#95a5a6;color:white{%- endif %}">{{ msg.reason }}</span>
            <strong>{{ msg.ts }}</strong>
            <code style="color:#555;font-size:0.82rem">{{ msg.topic }}</code>
            {% if msg.key %}<code style="color:#888;font-size:0.82rem">{{ msg.key }}</code>{% endif %}
        </summary>
        <pre style="margin:0;padding:12px;background:#f8f9fa;border-top:1px solid #eee;font-size:0.8rem;white-space:pre-wrap;word-break:break-all;max-height:500px;overflow-y:auto">{{ msg.payload }}</pre>
    </details>
    {% endfor %}
    {% else %}
    <p style="color:#27ae60">✅ Необработанных сообщений нет.</p>
    {% endif %}
</div>
'''

RAW_SCRIPT = '''<script>
async function clearRaw() {
    if (!confirm('Очистить все необработанные сообщения?')) return;
    try {
        const resp = await fetch('/api/raw', {method: 'DELETE'});
        const json = await resp.json();
        if (json.ok) location.reload();
        else alert('Ошибка: ' + json.error);
    } catch(e) { alert('Ошибка: ' + e); }
}
</script>'''


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

{% if raw_undecoded_count > 0 %}
<div class="card" style="border-left:4px solid #e74c3c">
    <h2 style="color:#e74c3c">⚠️ Необработанные сообщения: {{ raw_undecoded_count }}</h2>
    <p style="color:#666;margin-bottom:10px">Последние поступившие сообщения, которые не удалось декодировать.</p>
    <a href="/raw" class="btn btn-danger">Посмотреть →</a>
</div>
{% endif %}

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
    raw_undecoded_count = len(mqtt.get_raw_undecoded()) if mqtt else 0

    # Render content first
    content = render_template_string(
        INDEX_TEMPLATE,
        stats=stats,
        routers=routers_data,
        mqtt_stats=mqtt_stats,
        store_decode_errors=store_decode_errors,
        raw_undecoded_count=raw_undecoded_count,
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
# Raw Undecoded Messages
# ============================================================

@app.route('/raw')
def raw_page():
    """Raw undecoded messages page."""
    mqtt = get_mqtt_client()
    messages = mqtt.get_raw_undecoded() if mqtt else []
    content = render_template_string(RAW_TEMPLATE, messages=messages)
    html = wrap_content('Необработанные', content, auto_reload=False)
    return html.replace('</body>', RAW_SCRIPT + '\n</body>')


@app.route('/api/raw')
def api_get_raw():
    """API endpoint for undecoded messages."""
    mqtt = get_mqtt_client()
    if not mqtt:
        return jsonify([])
    return jsonify(mqtt.get_raw_undecoded())


@app.route('/api/raw', methods=['DELETE'])
def api_clear_raw():
    """Clear undecoded messages buffer."""
    mqtt = get_mqtt_client()
    if not mqtt:
        return jsonify({'ok': False, 'error': 'MQTT не инициализирован'}), 500
    count = mqtt.clear_raw_undecoded()
    return jsonify({'ok': True, 'cleared': count})


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
                    <button class="btn" style="padding:4px 10px;font-size:0.8rem"
                        onclick="editKeys('{{ d.device_type }}', '{{ d.payload_keys|join(', ') }}')">✏️ Ключи</button>
                    <a class="btn" style="padding:4px 10px;font-size:0.8rem;background:#27ae60"
                        href="/api/devices/{{ d.device_type }}/maps/map.jsonl" download>📥 map.jsonl</a>
                    <button class="btn" style="padding:4px 10px;font-size:0.8rem;background:#8e44ad"
                        onclick="openUpdateMaps('{{ d.device_type }}')">📂 Обновить</button>
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
                <td><strong>map.jsonl</strong> <small>(обязательно)</small></td>
                <td><input type="file" name="map" accept=".jsonl" required></td>
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
        <li>На выходе получите файл <code>map.jsonl</code></li>
        <li>Загрузите файлы через форму выше</li>
    </ol>
    <details style="margin-top:15px">
        <summary style="cursor:pointer;font-weight:600;color:#3498db">📋 Показать промпт для ИИ</summary>
        <pre id="ai-prompt" style="margin-top:10px;background:#f8f9fa;padding:15px;border-radius:4px;font-size:0.85rem;white-space:pre-wrap;border:1px solid #ddd;max-height:400px;overflow-y:auto">Преобразуй документацию Modbus-регистров в единый файл map.jsonl для декодера.
Каждая строка — отдельный JSON-объект (один регистр).

БАЗОВЫЙ ФОРМАТ (числовой регистр):
{"addr": 40018, "reg_type": "holding", "name": "GensetL1N Voltage", "data_type": "u16", "word_len": 1, "multiplier": 1.0, "offset": 0.0, "unit": "Vac", "na_values": [65535], "notes_ru": "Напряжение генератора фаза L1-нейтраль"}

ENUM-регистр (добавляется поле labels):
{"addr": 40010, "reg_type": "holding", "name": "Control Switch Position", "data_type": "u16", "word_len": 1, "multiplier": 1.0, "offset": 0.0, "unit": "enum", "na_values": [65535], "notes_ru": "Положение переключателя режимов", "labels": {"0": "Off", "1": "Auto", "2": "Manual"}}

FAULT BITMAP регистр (добавляется поле bits):
{"addr": 40400, "reg_type": "holding", "name": "Engine Faults 1", "data_type": "u16", "word_len": 1, "multiplier": 1.0, "offset": 0.0, "unit": "fault_bitmap", "na_values": [], "notes_ru": "Ошибки двигателя 1", "bits": {"0": {"name": "Low Oil Pressure", "severity": "shutdown"}, "1": {"name": "High Coolant Temp", "severity": "warning"}}}

Допустимые data_type:
  u16      — 16-бит беззнаковое, word_len=1
  s16      — 16-бит знаковое, word_len=1
  u32      — 32-бит беззнаковое, big-endian (ABCD), word_len=2
  u32_le   — 32-бит беззнаковое, little-endian (DCBA), word_len=2
  s32      — 32-бит знаковое, big-endian, word_len=2
  f32      — IEEE 754 float, word_len=2
  raw, char, bitfield — специальные типы, word_len=1

Для u32 — одна запись на регистр с word_len=2. Hi/Lo Word не разделять.

Поле addr_stride (опционально):
  Используется когда роутер отдаёт уже декодированные 32-бит значения
  (одно число на регистр вместо двух 16-битных слов).
  В этом случае: word_len=1, addr_stride=2, data_type=u32.
  Адреса в карте — как в документации (шаг 2).
  Пример: {"addr": 30013, "data_type": "u32", "word_len": 1, "addr_stride": 2, ...}

Допустимые severity для bits: warning, shutdown, shutdown_cooldown, derate, none

Преобразование единиц через multiplier и offset:
  Декодер вычисляет: value = raw * multiplier + offset
  Примеры:
  - Значение в тысячных (raw=36600 → 36.6):     multiplier=0.001, offset=0.0
  - Температура °F → °C (raw в °F):              multiplier=0.5556, offset=-17.778, unit="°C"
  - Температура °F → °C с масштабом /10:         multiplier=0.05556, offset=-17.778, unit="°C"
  Всегда указывай unit в системе СИ (°C, не °F).

Правила адресации:
  - holding-регистры: addr = 40000 + смещение из документации
  - input-регистры (FC04): addr = 30000 + смещение из документации
  - Если данные через Teltonika RUT (Modbus TCP → MQTT): смещение +1 к адресу
    (Teltonika нумерует с 1, не с 0)

Правила оформления:
  - name — оригинальное название на английском (из документации)
  - notes_ru — перевод названия и описания на русский язык
  - labels — ключи строкой (числовое значение), значение — строка на языке оригинала
  - Каждая строка JSONL — валидный JSON, кодировка UTF-8
  - Числа без кавычек, строки в кавычках</pre>
        <button class="btn" style="margin-top:5px;font-size:0.8rem" onclick="copyPrompt()">📋 Копировать промпт</button>
    </details>
</div>

<!-- Модальное окно обновления карт -->
<div id="update-maps-modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:1000;align-items:center;justify-content:center">
    <div style="background:white;border-radius:8px;padding:25px;max-width:500px;width:90%;box-shadow:0 4px 20px rgba(0,0,0,0.3)">
        <h2 style="margin-bottom:15px;color:#2c3e50">📂 Обновить карты: <span id="modal-device-name" style="color:#8e44ad"></span></h2>
        <p style="color:#666;font-size:0.9rem;margin-bottom:10px">Payload keys и настройки устройства не изменятся.</p>
        <div id="modal-downloads" style="margin-bottom:15px;padding:10px;background:#f8f9fa;border-radius:4px;font-size:0.88rem">
            <strong>Текущие файлы:</strong><br>
            <span id="modal-dl-links" style="color:#666">загрузка...</span>
        </div>
        <form id="update-maps-form" enctype="multipart/form-data">
            <input type="hidden" name="device_type" id="modal-device-type">
            <table style="width:100%">
                <tr>
                    <td style="padding:6px 0"><strong>map.jsonl</strong> <small>(обязательно)</small></td>
                    <td><input type="file" name="map" accept=".jsonl" required style="font-size:0.85rem"></td>
                </tr>
            </table>
            <div style="margin-top:15px">
                <button type="button" class="btn" onclick="validateUpdateMaps()">✅ Проверить</button>
                <button type="button" id="btn-update-save" class="btn" style="background:#999;cursor:not-allowed" disabled onclick="submitUpdateMaps()">💾 Сохранить</button>
                <button type="button" class="btn btn-danger" onclick="closeUpdateMaps()">Отмена</button>
            </div>
            <div id="update-maps-result" style="margin-top:10px"></div>
        </form>
    </div>
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
            var cnt = (json.map || json.register_map || {}).count || 0;
            result.innerHTML = '<span style="color:#27ae60;font-weight:bold">✅ Карты валидны! Регистров: ' + cnt + '</span>';
            btnSave.disabled = false;
            btnSave.style.background = '#27ae60';
            btnSave.style.cursor = 'pointer';
        } else {
            var html = '<span style="color:#e74c3c;font-weight:bold">❌ Найдены ошибки (' + json.total_errors + '):</span><ul>';
            var allErrors = ((json.map || json.register_map || {}).errors || [])
                .concat((json.enum_map || {}).errors || [])
                .concat((json.fault_bitmap_map || {}).errors || []);
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

async function openUpdateMaps(deviceType) {
    document.getElementById('modal-device-type').value = deviceType;
    document.getElementById('modal-device-name').textContent = deviceType.toUpperCase();
    document.getElementById('update-maps-result').innerHTML = '';
    document.getElementById('update-maps-form').reset();
    document.getElementById('modal-device-type').value = deviceType;
    var btn = document.getElementById('btn-update-save');
    btn.disabled = true; btn.style.background = '#999'; btn.style.cursor = 'not-allowed';
    document.getElementById('modal-dl-links').innerHTML = 'загрузка...';
    document.getElementById('update-maps-modal').style.display = 'flex';
    try {
        var resp = await fetch('/api/devices/' + deviceType + '/maps');
        var json = await resp.json();
        var hasMap = json.files && json.files.indexOf('map.jsonl') >= 0;
        document.getElementById('modal-dl-links').innerHTML = hasMap
            ? '<a href="/api/devices/' + deviceType + '/maps/map.jsonl" download style="color:#3498db">📥 map.jsonl</a>'
            : '<span style="color:#bbb">map.jsonl (нет)</span>';
    } catch(e) {
        document.getElementById('modal-dl-links').innerHTML = '<span style="color:#e74c3c">Ошибка загрузки списка файлов</span>';
    }
}

function closeUpdateMaps() {
    document.getElementById('update-maps-modal').style.display = 'none';
}

async function validateUpdateMaps() {
    var form = document.getElementById('update-maps-form');
    var data = new FormData(form);
    var result = document.getElementById('update-maps-result');
    var btn = document.getElementById('btn-update-save');
    btn.disabled = true; btn.style.background = '#999'; btn.style.cursor = 'not-allowed';
    result.innerHTML = 'Проверка...';
    try {
        var resp = await fetch('/api/devices/validate', {method: 'POST', body: data});
        if (!resp.ok) { result.innerHTML = '<span style="color:#e74c3c">Ошибка сервера: HTTP ' + resp.status + '</span>'; return; }
        var json = await resp.json();
        if (json.valid) {
            var cnt2 = (json.map || json.register_map || {}).count || 0;
            result.innerHTML = '<span style="color:#27ae60;font-weight:bold">✅ Валидно! Регистров: ' + cnt2 + '</span>';
            btn.disabled = false; btn.style.background = '#27ae60'; btn.style.cursor = 'pointer';
        } else {
            var html = '<span style="color:#e74c3c;font-weight:bold">❌ Ошибки (' + json.total_errors + '):</span><ul>';
            var allErrors = ((json.map||json.register_map||{}).errors||[]).concat((json.enum_map||{}).errors||[]).concat((json.fault_bitmap_map||{}).errors||[]);
            allErrors.slice(0,10).forEach(function(e){ html += '<li style="color:#e74c3c;font-size:0.85rem">' + e + '</li>'; });
            html += '</ul>';
            result.innerHTML = html;
        }
    } catch(e) { result.innerHTML = '<span style="color:#e74c3c">Ошибка: ' + e + '</span>'; }
}

async function submitUpdateMaps() {
    var form = document.getElementById('update-maps-form');
    var deviceType = document.getElementById('modal-device-type').value;
    var data = new FormData(form);
    var result = document.getElementById('update-maps-result');
    result.innerHTML = 'Сохранение...';
    try {
        var resp = await fetch('/api/devices/' + deviceType + '/maps', {method: 'PUT', body: data});
        var text = await resp.text();
        var json;
        try { json = JSON.parse(text); } catch(pe) {
            result.innerHTML = '<span style="color:#e74c3c">Ошибка сервера: ' + text.substring(0,200) + '</span>'; return;
        }
        if (json.ok) {
            result.innerHTML = '<span style="color:#27ae60;font-weight:bold">✅ ' + json.message + '</span>';
            setTimeout(function(){ closeUpdateMaps(); location.reload(); }, 1200);
        } else {
            result.innerHTML = '<span style="color:#e74c3c;font-weight:bold">❌ ' + json.error + '</span>';
        }
    } catch(e) { result.innerHTML = '<span style="color:#e74c3c">Ошибка: ' + e + '</span>'; }
}

async function editKeys(deviceType, currentKeys) {
    var newKeys = prompt('Payload keys для "' + deviceType + '" (через запятую). Пример: PCC_3_3, PCC, Modbus_PCC', currentKeys);
    if (newKeys === null) return;
    var keys = newKeys.split(',').map(function(k) { return k.trim(); }).filter(function(k) { return k; });
    if (keys.length === 0) { alert('Укажите хотя бы один ключ'); return; }
    try {
        const resp = await fetch('/api/devices/' + deviceType + '/keys', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({payload_keys: keys})
        });
        const json = await resp.json();
        if (json.ok) location.reload();
        else alert('Ошибка: ' + json.error);
    } catch(e) { alert('Ошибка: ' + e); }
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

    # Save uploaded file to temp dir for validation
    tmpdir = tempfile.mkdtemp()
    try:
        map_file = request.files.get('map')
        if map_file and map_file.filename:
            map_file.save(os.path.join(tmpdir, 'map.jsonl'))
        else:
            # Fallback: старый формат
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

        map_file = request.files.get('map')
        if not map_file or not map_file.filename:
            return jsonify({'ok': False, 'error': 'map.jsonl обязателен'}), 400

        # Save to temp first, validate, then move
        tmpdir = tempfile.mkdtemp()
        try:
            map_file.save(os.path.join(tmpdir, 'map.jsonl'))

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

        # Update MQTT client payload key mapping + публикуем метаданные
        mqtt = get_mqtt_client()
        if mqtt:
            new_map = {key: device_type for key in payload_keys}
            mqtt.update_payload_key_map(new_map)
            mqtt.publish_metadata(device_type)

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


@app.route('/api/devices/<device_type>/maps')
def api_list_map_files(device_type: str):
    """List available map files for a device."""
    if device_type not in get_registered_device_types():
        return jsonify({'ok': False, 'error': 'Не найдено'}), 404
    maps_dir_str = get_device_maps_dir(device_type)
    if not maps_dir_str:
        return jsonify({'ok': False, 'error': 'Директория не найдена'}), 404
    maps_dir = Path(maps_dir_str)
    known = ['map.jsonl', 'register_map.jsonl', 'enum_map.json', 'fault_bitmap_map.jsonl', 'ignore_registers.json']
    files = [f for f in known if (maps_dir / f).exists()]
    return jsonify({'ok': True, 'files': files})


@app.route('/api/devices/<device_type>/maps/<filename>')
def api_download_map_file(device_type: str, filename: str):
    """Download a single map file."""
    allowed = {'map.jsonl', 'register_map.jsonl', 'enum_map.json', 'fault_bitmap_map.jsonl', 'ignore_registers.json'}
    if filename not in allowed:
        abort(404)
    maps_dir_str = get_device_maps_dir(device_type)
    if not maps_dir_str:
        abort(404)
    filepath = Path(maps_dir_str) / filename
    if not filepath.exists():
        abort(404)
    return send_file(str(filepath.resolve()), as_attachment=True, download_name=filename)


@app.route('/api/devices/<device_type>/maps', methods=['PUT'])
def api_update_device_maps(device_type: str):
    """Replace map files for an existing device. Payload keys are preserved."""
    import tempfile
    import shutil

    try:
        if device_type not in get_registered_device_types():
            return jsonify({'ok': False, 'error': f"Устройство '{device_type}' не найдено"}), 404

        map_file = request.files.get('map')
        if not map_file or not map_file.filename:
            return jsonify({'ok': False, 'error': 'map.jsonl обязателен'}), 400

        tmpdir = tempfile.mkdtemp()
        try:
            map_file.save(os.path.join(tmpdir, 'map.jsonl'))

            # Validate before overwriting
            validation = validate_device_maps(tmpdir)
            if not validation['valid']:
                return jsonify({'ok': False, 'error': f"Карты невалидны ({validation['total_errors']} ошибок)"}), 400

            # Overwrite files in maps/<device_type>/
            maps_dir = os.path.join('maps', device_type)
            os.makedirs(maps_dir, exist_ok=True)
            for filename in os.listdir(tmpdir):
                shutil.copy2(os.path.join(tmpdir, filename), os.path.join(maps_dir, filename))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        # Hot-reload maps
        ok = load_device_maps(device_type, maps_dir)
        if not ok:
            return jsonify({'ok': False, 'error': 'Файлы сохранены, но загрузка не удалась'}), 500

        # Публикуем обновлённые метаданные в retained-топик
        mqtt = get_mqtt_client()
        if mqtt:
            mqtt.publish_metadata(device_type)

        stats = get_device_stats(device_type)
        logger.info(f"Карты устройства '{device_type}' обновлены: {stats}")
        return jsonify({
            'ok': True,
            'message': f"Карты '{device_type}' обновлены: {stats['register_count']} регистров"
        })
    except Exception as e:
        logger.exception(f"Ошибка обновления карт '{device_type}': {e}")
        return jsonify({'ok': False, 'error': f"Внутренняя ошибка: {str(e)}"}), 500


@app.route('/api/devices/<device_type>/keys', methods=['PUT'])
def api_update_device_keys(device_type: str):
    """Update payload keys for an existing device (hot reload, no map re-upload)."""
    data = request.get_json()
    if not data:
        return jsonify({'ok': False, 'error': 'No JSON body'}), 400

    payload_keys = data.get('payload_keys', [])
    if not payload_keys:
        return jsonify({'ok': False, 'error': 'payload_keys не может быть пустым'}), 400

    if device_type not in get_registered_device_types():
        return jsonify({'ok': False, 'error': f"Устройство '{device_type}' не найдено"}), 404

    # Update MQTT client: remove old keys for this device, add new ones
    mqtt = get_mqtt_client()
    if mqtt:
        with mqtt._lock:
            # Remove all old keys pointing to this device
            old_keys = [k for k, v in mqtt._payload_key_map.items() if v == device_type]
            for k in old_keys:
                del mqtt._payload_key_map[k]
            # Add new keys
            for key in payload_keys:
                mqtt._payload_key_map[key] = device_type
            # Clear matched unknown keys
            for key in list(mqtt._unknown_keys):
                if key in mqtt._payload_key_map:
                    del mqtt._unknown_keys[key]

    # Update config.yaml
    _update_config_payload_keys(device_type, payload_keys)

    logger.info(f"Payload keys для '{device_type}' обновлены: {payload_keys}")
    return jsonify({'ok': True, 'payload_keys': payload_keys})


def _update_config_payload_keys(device_type: str, payload_keys: list):
    """Update only payload_keys for an existing device in config.yaml."""
    import yaml

    config_path = Path('config.yaml')
    if not config_path.exists():
        return

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}

        if 'devices' not in config or device_type not in config['devices']:
            return

        config['devices'][device_type]['payload_keys'] = payload_keys

        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        logger.info(f"config.yaml обновлён: payload_keys для '{device_type}' = {payload_keys}")
    except Exception as e:
        logger.error(f"Ошибка обновления config.yaml: {e}")


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


# ============================================================
# Translations page
# ============================================================

TRANSLATIONS_TEMPLATE = '''
<div class="card">
  <!-- Вкладки -->
  <div style="display:flex;gap:4px;margin-bottom:20px;border-bottom:2px solid #3498db">
    <button id="tab-labels" onclick="switchTab('labels')"
        style="padding:9px 20px;border:none;background:#3498db;color:white;cursor:pointer;border-radius:4px 4px 0 0;font-size:.9rem;font-weight:600">
      🏷️ Метки enum
      <span id="badge-labels" style="font-size:.8rem;opacity:.85;margin-left:4px"></span>
    </button>
    <button id="tab-bits" onclick="switchTab('bits')"
        style="padding:9px 20px;border:none;background:#ecf0f1;color:#555;cursor:pointer;border-radius:4px 4px 0 0;font-size:.9rem;font-weight:400">
      🔴 Биты ошибок
      <span id="badge-bits" style="font-size:.8rem;opacity:.85;margin-left:4px"></span>
    </button>
  </div>

  <!-- Панель управления -->
  <div style="display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap;align-items:center">
    <input id="search" type="text" placeholder="Поиск по EN или RU..." autocomplete="off"
           style="flex:1;min-width:200px;padding:7px 10px;border:1px solid #ddd;border-radius:4px;font-size:.9rem">
    <label style="display:flex;align-items:center;gap:6px;font-size:.9rem;cursor:pointer">
      <input type="checkbox" id="onlyEmpty"> Только без перевода
    </label>
    <button id="saveBtn" onclick="saveAll()"
            style="padding:7px 18px;background:#27ae60;color:white;border:none;border-radius:4px;cursor:pointer;font-size:.9rem">
      💾 Сохранить все
    </button>
    <a id="downloadBtn" href="/api/translations/export" download
       style="padding:7px 14px;background:#3498db;color:white;text-decoration:none;border-radius:4px;font-size:.9rem">
      📥 Скачать
    </a>
    <label style="padding:7px 14px;background:#8e44ad;color:white;border-radius:4px;font-size:.9rem;cursor:pointer">
      📤 Загрузить<input type="file" id="uploadFile" accept=".json" style="display:none" onchange="uploadFile(this)">
    </label>
    <span id="saveStatus" style="font-size:.85rem;color:#666"></span>
  </div>

  <table>
    <thead>
      <tr>
        <th style="width:42%">Оригинал (EN)</th>
        <th style="width:40%">Перевод (RU)</th>
        <th style="width:18%;text-align:center">Статус</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
  <p id="noResults" style="display:none;color:#999;padding:20px;text-align:center">Ничего не найдено</p>
</div>

<script>
const LABELS_DATA = {{ labels_json }};
const BITS_DATA   = {{ bits_json }};

let labelsArr = Object.entries(LABELS_DATA).map(([en,ru]) => ({en, ru}));
let bitsArr   = Object.entries(BITS_DATA  ).map(([en,ru]) => ({en, ru}));
labelsArr.sort((a,b) => a.en.localeCompare(b.en));
bitsArr.sort((a,b)   => a.en.localeCompare(b.en));

let currentTab = 'labels';

function getArr() { return currentTab === 'labels' ? labelsArr : bitsArr; }

function switchTab(tab) {
  currentTab = tab;
  var isLab = tab === 'labels';
  var tl = document.getElementById('tab-labels');
  var tb = document.getElementById('tab-bits');
  tl.style.background   = isLab  ? '#3498db' : '#ecf0f1';
  tl.style.color        = isLab  ? 'white'   : '#555';
  tl.style.fontWeight   = isLab  ? '600'     : '400';
  tb.style.background   = !isLab ? '#3498db' : '#ecf0f1';
  tb.style.color        = !isLab ? 'white'   : '#555';
  tb.style.fontWeight   = !isLab ? '600'     : '400';
  document.getElementById('downloadBtn').href =
    isLab ? '/api/translations/export' : '/api/bit-translations/export';
  document.getElementById('search').value = '';
  document.getElementById('onlyEmpty').checked = false;
  render();
}

async function uploadFile(input) {
  if (!input.files || !input.files[0]) return;
  var file = input.files[0];
  input.value = '';
  var saveStatus = document.getElementById('saveStatus');
  saveStatus.textContent = 'Загрузка...';
  try {
    var text = await file.text();
    var data = JSON.parse(text);
    var url = currentTab === 'labels' ? '/api/translations' : '/api/bit-translations';
    var resp = await fetch(url, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    var j = await resp.json();
    if (j.ok) {
      // Обновляем данные в памяти
      var arr = currentTab === 'labels' ? labelsArr : bitsArr;
      arr.forEach(function(item) { item.ru = data[item.en] || item.ru; });
      saveStatus.textContent = '✓ Загружено (' + j.count + ' записей)';
      document.getElementById('saveBtn').style.background = '#27ae60';
      updateBadges(); render();
    } else {
      saveStatus.textContent = '✗ ' + (j.error || '?');
    }
  } catch(e) {
    saveStatus.textContent = '✗ ' + e;
  }
  setTimeout(function(){ saveStatus.textContent = ''; }, 4000);
}

const tbody = document.getElementById('tbody');
const noRes = document.getElementById('noResults');

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function tabKey(s) {
  try { return btoa(unescape(encodeURIComponent(s))).replace(/[^a-zA-Z0-9]/g,'_'); }
  catch(e) { return Math.abs(s.split('').reduce((a,c)=>a+c.charCodeAt(0),0)).toString(); }
}

function render() {
  var q     = document.getElementById('search').value.toLowerCase();
  var onlyE = document.getElementById('onlyEmpty').checked;
  var arr   = getArr();
  var shown = 0;
  tbody.innerHTML = '';
  arr.forEach(function(item) {
    var matchQ = !q || item.en.toLowerCase().includes(q) || item.ru.toLowerCase().includes(q);
    var matchE = !onlyE || !item.ru;
    if (!matchQ || !matchE) return;
    shown++;
    var tr = document.createElement('tr');
    var key = tabKey(item.en);
    tr.innerHTML =
      '<td style="font-family:monospace;font-size:.85rem;word-break:break-word">' + escHtml(item.en) + '</td>' +
      '<td><input type="text" value="' + escHtml(item.ru) + '" data-en="' + escHtml(item.en) + '"' +
      ' style="width:100%;padding:4px 6px;border:1px solid #ddd;border-radius:3px;font-size:.9rem"' +
      ' onchange="onChange(this)" oninput="markDirty()"></td>' +
      '<td style="text-align:center" id="st_' + key + '">' +
        (item.ru ? '✓' : '<span style="color:#e74c3c">—</span>') + '</td>';
    tbody.appendChild(tr);
  });
  noRes.style.display = shown ? 'none' : 'block';
  updateBadges();
}

function updateBadges() {
  ['labels','bits'].forEach(function(tab) {
    var arr    = tab === 'labels' ? labelsArr : bitsArr;
    var filled = arr.filter(function(d){ return d.ru; }).length;
    var total  = arr.length;
    var miss   = total - filled;
    document.getElementById('badge-' + tab).textContent =
      '(' + filled + '/' + total + (miss ? ' ⚠️' + miss : '') + ')';
  });
}

function markDirty() {
  document.getElementById('saveBtn').style.background = '#e67e22';
}

function onChange(input) {
  var en   = input.dataset.en;
  var ru   = input.value.trim();
  var arr  = getArr();
  var item = arr.find(function(d){ return d.en === en; });
  if (item) item.ru = ru;
  var cell = document.getElementById('st_' + tabKey(en));
  if (cell) cell.innerHTML = ru ? '✓' : '<span style="color:#e74c3c">—</span>';
  updateBadges();
  markDirty();
}

async function saveAll() {
  var labelsPayload = {};
  labelsArr.forEach(function(d){ labelsPayload[d.en] = d.ru; });
  var bitsPayload = {};
  bitsArr.forEach(function(d){ bitsPayload[d.en] = d.ru; });

  var saveStatus = document.getElementById('saveStatus');
  var saveBtn    = document.getElementById('saveBtn');
  saveStatus.textContent = 'Сохранение...';

  try {
    var results = await Promise.all([
      fetch('/api/translations',     {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(labelsPayload)}),
      fetch('/api/bit-translations', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(bitsPayload)})
    ]);
    var j1 = await results[0].json();
    var j2 = await results[1].json();
    if (j1.ok && j2.ok) {
      saveStatus.textContent = '✓ Сохранено';
      saveBtn.style.background = '#27ae60';
    } else {
      saveStatus.textContent = '✗ Ошибка: ' + (!j1.ok ? j1.error : j2.error);
    }
  } catch(e) {
    saveStatus.textContent = '✗ ' + e;
  }
  setTimeout(function(){ saveStatus.textContent = ''; }, 3000);
}

document.getElementById('search').addEventListener('input', render);
document.getElementById('onlyEmpty').addEventListener('change', render);
render();
updateBadges();
</script>
'''


@app.route('/translations')
def translations_page():
    """Страница редактирования переводов enum-меток и имён битов."""
    import json as _json
    labels_json = _json.dumps(get_label_translations(), ensure_ascii=False)
    bits_json   = _json.dumps(get_bit_translations(),   ensure_ascii=False)
    content = (TRANSLATIONS_TEMPLATE
               .replace('{{ labels_json }}', labels_json)
               .replace('{{ bits_json }}',   bits_json))
    return wrap_content('Переводы', content, auto_reload=False)


@app.route('/api/translations/export')
def api_export_translations():
    """GET /api/translations/export — скачать label_translations.json."""
    from maps_loader import _TRANSLATIONS_FILE
    path = _TRANSLATIONS_FILE
    if not path.exists():
        abort(404)
    return send_file(str(path.resolve()), as_attachment=True,
                     download_name='label_translations.json', mimetype='application/json')


@app.route('/api/bit-translations/export')
def api_export_bit_translations():
    """GET /api/bit-translations/export — скачать bit_translations.json."""
    from maps_loader import _BIT_TRANSLATIONS_FILE
    path = _BIT_TRANSLATIONS_FILE
    if not path.exists():
        abort(404)
    return send_file(str(path.resolve()), as_attachment=True,
                     download_name='bit_translations.json', mimetype='application/json')


@app.route('/api/translations')
def api_get_translations():
    """GET /api/translations — получить весь словарь переводов."""
    return jsonify(get_label_translations())


@app.route('/api/translations', methods=['PUT'])
def api_save_translations():
    """PUT /api/translations — сохранить весь словарь целиком.
    Body: {"EN label": "RU label", ...}
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'ok': False, 'error': 'Ожидается JSON-объект'}), 400

    # Отфильтровываем не-строковые значения
    cleaned = {str(k): str(v) for k, v in data.items()
               if isinstance(k, str) and isinstance(v, str)}

    err = save_label_translations(cleaned)
    if err:
        return jsonify({'ok': False, 'error': err}), 500

    # Переиздаём метаданные в MQTT (все устройства), чтобы labels_ru обновились
    mqtt = get_mqtt_client()
    if mqtt and mqtt.is_connected():
        for dt in get_registered_device_types():
            mqtt.publish_metadata(dt)
        logger.info("MQTT metadata republished after translations update")

    return jsonify({'ok': True, 'count': len(cleaned)})


@app.route('/api/translations/<path:label>', methods=['PUT'])
def api_update_one_translation(label: str):
    """PUT /api/translations/<label> — обновить один перевод.
    Body: {"ru": "Русский текст"}
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or 'ru' not in data:
        return jsonify({'ok': False, 'error': 'Ожидается {"ru": "..."}'}), 400

    translations = get_label_translations()
    translations[label] = str(data['ru'])
    err = save_label_translations(translations)
    if err:
        return jsonify({'ok': False, 'error': err}), 500

    mqtt = get_mqtt_client()
    if mqtt and mqtt.is_connected():
        for dt in get_registered_device_types():
            mqtt.publish_metadata(dt)

    return jsonify({'ok': True, 'label': label, 'ru': data['ru']})


# ============================================================
# Bit-translations API
# ============================================================

@app.route('/api/bit-translations')
def api_get_bit_translations():
    """GET /api/bit-translations — получить словарь переводов имён битов."""
    return jsonify(get_bit_translations())


@app.route('/api/bit-translations', methods=['PUT'])
def api_save_bit_translations():
    """PUT /api/bit-translations — сохранить весь словарь целиком.
    Body: {"EN bit name": "RU bit name", ...}
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'ok': False, 'error': 'Ожидается JSON-объект'}), 400

    cleaned = {str(k): str(v) for k, v in data.items()
               if isinstance(k, str) and isinstance(v, str)}

    err = save_bit_translations(cleaned)
    if err:
        return jsonify({'ok': False, 'error': err}), 500

    # Переиздаём метаданные в MQTT, чтобы name_ru обновились
    mqtt = get_mqtt_client()
    if mqtt and mqtt.is_connected():
        for dt in get_registered_device_types():
            mqtt.publish_metadata(dt)
        logger.info("MQTT metadata republished after bit-translations update")

    return jsonify({'ok': True, 'count': len(cleaned)})


@app.route('/api/bit-translations/<path:name>', methods=['PUT'])
def api_update_one_bit_translation(name: str):
    """PUT /api/bit-translations/<name> — обновить один перевод имени бита.
    Body: {"ru": "Русский текст"}
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or 'ru' not in data:
        return jsonify({'ok': False, 'error': 'Ожидается {"ru": "..."}'}), 400

    translations = get_bit_translations()
    translations[name] = str(data['ru'])
    err = save_bit_translations(translations)
    if err:
        return jsonify({'ok': False, 'error': err}), 500

    mqtt = get_mqtt_client()
    if mqtt and mqtt.is_connected():
        for dt in get_registered_device_types():
            mqtt.publish_metadata(dt)

    return jsonify({'ok': True, 'name': name, 'ru': data['ru']})


# ============================================================
# Map Editor page
# ============================================================

MAP_EDITOR_TEMPLATE = '''
<div class="card">
  <!-- Выбор устройства -->
  <div style="margin-bottom:16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap">
    <strong>Устройство:</strong>
    {% for dt in device_types %}
    <a href="/map-editor?device={{ dt }}"
       style="padding:5px 14px;border-radius:4px;text-decoration:none;font-size:.9rem;
              {% if dt == current_device %}background:#3498db;color:white{% else %}background:#ecf0f1;color:#555{% endif %}">
      {{ dt|upper }}
    </a>
    {% endfor %}
  </div>

  <!-- Вкладки -->
  <div style="display:flex;gap:4px;margin-bottom:20px;border-bottom:2px solid #3498db">
    <button id="tab-notes" onclick="switchTab('notes')"
        style="padding:9px 20px;border:none;background:#3498db;color:white;cursor:pointer;border-radius:4px 4px 0 0;font-size:.9rem;font-weight:600">
      📝 Описания <span id="badge-notes" style="font-size:.8rem;opacity:.85;margin-left:4px"></span>
    </button>
    <button id="tab-labels" onclick="switchTab('labels')"
        style="padding:9px 20px;border:none;background:#ecf0f1;color:#555;cursor:pointer;border-radius:4px 4px 0 0;font-size:.9rem">
      🏷️ Метки <span id="badge-labels" style="font-size:.8rem;opacity:.85;margin-left:4px"></span>
    </button>
    <button id="tab-bits" onclick="switchTab('bits')"
        style="padding:9px 20px;border:none;background:#ecf0f1;color:#555;cursor:pointer;border-radius:4px 4px 0 0;font-size:.9rem">
      🔴 Биты <span id="badge-bits" style="font-size:.8rem;opacity:.85;margin-left:4px"></span>
    </button>
  </div>

  <!-- Панель управления -->
  <div style="display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap;align-items:center">
    <input id="search" type="text" placeholder="Поиск..." autocomplete="off"
           style="flex:1;min-width:200px;padding:7px 10px;border:1px solid #ddd;border-radius:4px;font-size:.9rem">
    <label style="display:flex;align-items:center;gap:6px;font-size:.9rem;cursor:pointer">
      <input type="checkbox" id="onlyEmpty"> Только без перевода
    </label>
    <button id="saveBtn" onclick="saveAll()"
            style="padding:7px 18px;background:#27ae60;color:white;border:none;border-radius:4px;cursor:pointer;font-size:.9rem">
      💾 Сохранить все
    </button>
    <span id="saveStatus" style="font-size:.85rem;color:#666"></span>
  </div>

  <table style="table-layout:fixed;width:100%">
    <thead id="thead"><tr>
      <th style="width:7%">Адрес</th>
      <th style="width:26%">Название</th>
      <th style="width:7%;text-align:center">Тип</th>
      <th>notes_ru</th>
      <th style="width:5%;text-align:center">✓</th>
    </tr></thead>
    <tbody id="tbody"></tbody>
  </table>
  <p id="noResults" style="display:none;color:#999;padding:20px;text-align:center">Ничего не найдено</p>
</div>

<script>
var DEVICE = "{{ current_device }}";
var REGS   = {{ registers_json|safe }};

// --- Преобразуем в плоские массивы для каждой вкладки ---
var notesArr  = REGS.map(function(r) {
  return {key: r.reg_type+':'+r.addr, addr: r.addr, name: r.name, unit: r.unit, notes_ru: r.notes_ru||''};
});

var labelsArr = [];
REGS.forEach(function(r) {
  if (!r.labels) return;
  Object.keys(r.labels).sort(function(a,b){return +a - +b;}).forEach(function(val) {
    labelsArr.push({
      addr: r.addr, regName: r.name, val: val,
      en: r.labels[val],
      ru: (r.labels_ru && r.labels_ru[val]) || ''
    });
  });
});

var bitsArr = [];
REGS.forEach(function(r) {
  if (!r.bits) return;
  Object.keys(r.bits).sort(function(a,b){return +a - +b;}).forEach(function(bit) {
    var b = r.bits[bit];
    bitsArr.push({
      addr: r.addr, regName: r.name, bit: bit,
      en: b.name||'', ru: b.name_ru||'', severity: b.severity||''
    });
  });
});

var currentTab = 'notes';

var SEV_COLORS = {
  shutdown:          '#e74c3c',
  shutdown_cooldown: '#e67e22',
  derate:            '#f39c12',
  warning:           '#3498db',
  none:              '#95a5a6'
};

function getArr() {
  if (currentTab === 'notes')  return notesArr;
  if (currentTab === 'labels') return labelsArr;
  return bitsArr;
}

var THEADS = {
  notes:  '<tr><th style="width:7%">Адрес</th><th style="width:26%">Название</th><th style="width:7%;text-align:center">Тип</th><th>notes_ru</th><th style="width:5%;text-align:center">✓</th></tr>',
  labels: '<tr><th style="width:7%">Адрес</th><th style="width:26%">Регистр</th><th style="width:30%">Оригинал (EN)</th><th>Перевод (RU)</th><th style="width:5%;text-align:center">✓</th></tr>',
  bits:   '<tr><th style="width:7%">Адрес</th><th style="width:20%">Регистр</th><th style="width:8%;text-align:center">Severity</th><th style="width:26%">Оригинал (EN)</th><th>Перевод (RU)</th><th style="width:5%;text-align:center">✓</th></tr>'
};

function switchTab(tab) {
  currentTab = tab;
  ['notes','labels','bits'].forEach(function(t) {
    var btn = document.getElementById('tab-'+t);
    var isActive = t === tab;
    btn.style.background  = isActive ? '#3498db' : '#ecf0f1';
    btn.style.color       = isActive ? 'white'   : '#555';
    btn.style.fontWeight  = isActive ? '600'     : '400';
  });
  document.getElementById('thead').innerHTML = THEADS[tab];
  document.getElementById('search').value = '';
  document.getElementById('onlyEmpty').checked = false;
  render();
}

var tbody = document.getElementById('tbody');
var noRes  = document.getElementById('noResults');

function escHtml(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function tabKey(s) {
  try { return btoa(unescape(encodeURIComponent(String(s)))).replace(/[^a-zA-Z0-9]/g,'_'); }
  catch(e) { return 'k'+Math.abs(String(s).split('').reduce(function(a,c){return a+c.charCodeAt(0);},0)); }
}

function unitBadge(unit) {
  var color = unit==='enum'?'#8e44ad': unit==='fault_bitmap'?'#e74c3c': '#7f8c8d';
  return '<span style="display:inline-block;padding:1px 7px;border-radius:3px;font-size:.75rem;color:white;background:'+color+'">'+escHtml(unit||'—')+'</span>';
}

function render() {
  var q      = document.getElementById('search').value.toLowerCase();
  var onlyE  = document.getElementById('onlyEmpty').checked;
  var arr    = getArr();
  var shown  = 0;
  tbody.innerHTML = '';

  arr.forEach(function(item) {
    var ru = item.notes_ru !== undefined ? item.notes_ru : item.ru;
    if (onlyE && ru) return;

    var searchStr;
    if (currentTab === 'notes') {
      searchStr = (item.addr+' '+item.name+' '+item.notes_ru).toLowerCase();
    } else if (currentTab === 'labels') {
      searchStr = (item.addr+' '+item.regName+' '+item.en+' '+item.ru).toLowerCase();
    } else {
      searchStr = (item.addr+' '+item.regName+' '+item.en+' '+item.ru).toLowerCase();
    }
    if (q && !searchStr.includes(q)) return;

    shown++;
    var tr = document.createElement('tr');
    var key = tabKey(currentTab+':'+item.addr+':'+(item.val||item.bit||''));
    var statusId = 'st_'+key;
    var statusHtml = ru ? '✓' : '<span style="color:#e74c3c">—</span>';

    if (currentTab === 'notes') {
      tr.innerHTML =
        '<td style="font-size:.85rem;color:#888">'+item.addr+'</td>'+
        '<td style="font-size:.88rem">'+escHtml(item.name)+'</td>'+
        '<td style="text-align:center">'+unitBadge(item.unit)+'</td>'+
        '<td><input type="text" value="'+escHtml(item.notes_ru)+'" data-key="'+escHtml(item.key)+'"'+
        ' style="width:100%;padding:4px 6px;border:1px solid #ddd;border-radius:3px;font-size:.88rem"'+
        ' onchange="onChangeNotes(this)" oninput="markDirty()"></td>'+
        '<td style="text-align:center" id="'+statusId+'">'+statusHtml+'</td>';

    } else if (currentTab === 'labels') {
      tr.innerHTML =
        '<td style="font-size:.85rem;color:#888">'+item.addr+'</td>'+
        '<td style="font-size:.85rem;color:#555">'+escHtml(item.regName)+'</td>'+
        '<td style="font-family:monospace;font-size:.88rem">'+escHtml(item.en)+'</td>'+
        '<td><input type="text" value="'+escHtml(item.ru)+'" data-en="'+escHtml(item.en)+'"'+
        ' style="width:100%;padding:4px 6px;border:1px solid #ddd;border-radius:3px;font-size:.9rem"'+
        ' onchange="onChangeLabel(this)" oninput="markDirty()"></td>'+
        '<td style="text-align:center" id="'+statusId+'">'+statusHtml+'</td>';

    } else {
      var sevColor = SEV_COLORS[item.severity] || '#95a5a6';
      tr.innerHTML =
        '<td style="font-size:.85rem;color:#888">'+item.addr+'</td>'+
        '<td style="font-size:.85rem;color:#555">'+escHtml(item.regName)+'</td>'+
        '<td style="text-align:center"><span style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:.75rem;color:white;background:'+sevColor+'">'+escHtml(item.severity)+'</span></td>'+
        '<td style="font-size:.85rem;word-break:break-word">'+escHtml(item.en)+'</td>'+
        '<td><input type="text" value="'+escHtml(item.ru)+'" data-en="'+escHtml(item.en)+'"'+
        ' style="width:100%;padding:4px 6px;border:1px solid #ddd;border-radius:3px;font-size:.88rem"'+
        ' onchange="onChangeBit(this)" oninput="markDirty()"></td>'+
        '<td style="text-align:center" id="'+statusId+'">'+statusHtml+'</td>';
    }
    tbody.appendChild(tr);
  });

  noRes.style.display = shown ? 'none' : 'block';
  updateBadges();
}

function updateBadges() {
  var nFilled = notesArr.filter(function(d){return d.notes_ru;}).length;
  var lFilled = labelsArr.filter(function(d){return d.ru;}).length;
  var bFilled = bitsArr.filter(function(d){return d.ru;}).length;
  document.getElementById('badge-notes').textContent  =
    '('+nFilled+'/'+notesArr.length+(notesArr.length-nFilled?' ⚠️'+(notesArr.length-nFilled):'')+')';
  document.getElementById('badge-labels').textContent =
    '('+lFilled+'/'+labelsArr.length+(labelsArr.length-lFilled?' ⚠️'+(labelsArr.length-lFilled):'')+')';
  document.getElementById('badge-bits').textContent   =
    '('+bFilled+'/'+bitsArr.length+(bitsArr.length-bFilled?' ⚠️'+(bitsArr.length-bFilled):'')+')';
}

function markDirty() {
  document.getElementById('saveBtn').style.background = '#e67e22';
}

function onChangeNotes(input) {
  var key  = input.dataset.key;
  var val  = input.value.trim();
  var item = notesArr.find(function(d){ return d.key===key; });
  if (item) item.notes_ru = val;
  var cell = document.getElementById('st_'+tabKey('notes:'+input.closest('tr').querySelector('td').textContent+':'));
  updateBadges(); markDirty();
}

function onChangeLabel(input) {
  var en  = input.dataset.en;
  var ru  = input.value.trim();
  labelsArr.forEach(function(d){ if (d.en===en) d.ru = ru; });
  updateBadges(); markDirty();
}

function onChangeBit(input) {
  var en  = input.dataset.en;
  var ru  = input.value.trim();
  bitsArr.forEach(function(d){ if (d.en===en) d.ru = ru; });
  updateBadges(); markDirty();
}

async function saveAll() {
  var notes = {};
  notesArr.forEach(function(d){ notes[d.key] = d.notes_ru; });

  var labels = {};
  labelsArr.forEach(function(d){ labels[d.en] = d.ru; });

  var bits = {};
  bitsArr.forEach(function(d){ bits[d.en] = d.ru; });

  var saveStatus = document.getElementById('saveStatus');
  var saveBtn    = document.getElementById('saveBtn');
  saveStatus.textContent = 'Сохранение...';

  try {
    var resp = await fetch('/api/map-editor', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({device_type: DEVICE, notes: notes, labels: labels, bits: bits})
    });
    var j = await resp.json();
    if (j.ok) {
      saveStatus.textContent = '✓ Сохранено';
      saveBtn.style.background = '#27ae60';
    } else {
      saveStatus.textContent = '✗ ' + (j.error||'?');
    }
  } catch(e) {
    saveStatus.textContent = '✗ ' + e;
  }
  setTimeout(function(){ saveStatus.textContent = ''; }, 3000);
}

document.getElementById('search').addEventListener('input', render);
document.getElementById('onlyEmpty').addEventListener('change', render);
render();
</script>
'''


@app.route('/map-editor')
def map_editor_page():
    """Страница редактирования карты регистров."""
    import json as _json
    device_types = get_registered_device_types()
    if not device_types:
        return wrap_content('Редактор карты', '<div class="card"><p>Нет загруженных устройств.</p></div>', auto_reload=False)

    current_device = request.args.get('device', device_types[0])
    if current_device not in device_types:
        current_device = device_types[0]

    registers = get_map_editor_data(current_device) or []
    regs_json = _json.dumps(registers, ensure_ascii=False)

    content = render_template_string(
        MAP_EDITOR_TEMPLATE,
        device_types=device_types,
        current_device=current_device,
        registers_json=regs_json,
    )
    return wrap_content('Редактор карты', content, auto_reload=False)


@app.route('/api/map-editor', methods=['PUT'])
def api_save_map_editor():
    """PUT /api/map-editor — сохранить изменения из редактора карты.
    Body: {device_type, notes: {key: text}, labels: {en: ru}, bits: {en: ru}}
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'ok': False, 'error': 'Ожидается JSON-объект'}), 400

    device_type = data.get('device_type', '')
    if not device_type or device_type not in get_registered_device_types():
        return jsonify({'ok': False, 'error': f"Устройство '{device_type}' не найдено"}), 400

    errors = []

    # 1. Сохраняем notes_ru в map.jsonl
    notes = {k: v for k, v in (data.get('notes') or {}).items()
             if isinstance(k, str) and isinstance(v, str)}
    if notes:
        err = save_notes_ru(device_type, notes)
        if err:
            errors.append(f"notes: {err}")

    # 2. Сохраняем переводы меток (мержим с существующим словарём)
    new_labels = {k: v for k, v in (data.get('labels') or {}).items()
                  if isinstance(k, str) and isinstance(v, str)}
    if new_labels:
        merged_labels = get_label_translations()
        merged_labels.update(new_labels)
        err = save_label_translations(merged_labels)
        if err:
            errors.append(f"labels: {err}")

    # 3. Сохраняем переводы битов (мержим с существующим словарём)
    new_bits = {k: v for k, v in (data.get('bits') or {}).items()
                if isinstance(k, str) and isinstance(v, str)}
    if new_bits:
        merged_bits = get_bit_translations()
        merged_bits.update(new_bits)
        err = save_bit_translations(merged_bits)
        if err:
            errors.append(f"bits: {err}")

    if errors:
        return jsonify({'ok': False, 'error': '; '.join(errors)}), 500

    # Переиздаём метаданные в MQTT
    mqtt = get_mqtt_client()
    if mqtt and mqtt.is_connected():
        for dt in get_registered_device_types():
            mqtt.publish_metadata(dt)
        logger.info(f"MQTT metadata republished after map editor save ({device_type})")

    return jsonify({'ok': True})


def run_web_ui(host: str = '0.0.0.0', port: int = 8080, debug: bool = False):
    """Run the web UI server."""
    logger.info(f"Web UI запущен на http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, use_reloader=False, threaded=True)
