"""
Универсальный Modbus-декодер — Web UI

Простой веб-интерфейс на Flask для просмотра декодированных данных.
UI не знает ничего о Modbus — только отображает декодированные данные.
"""

import logging
from typing import Optional
from flask import Flask, render_template_string, jsonify, abort

from panel_store import get_store, PanelStatus
from mqtt_client import get_mqtt_client

logger = logging.getLogger(__name__)

app = Flask(__name__)

# ============================================================
# HTML Templates (embedded for single-file simplicity)
# ============================================================

# Base HTML wrapper function
def wrap_content(title: str, content: str) -> str:
    """Wrap content in base HTML template."""
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
        .raw-value {{ color: #888; font-size: 0.85rem; }}
    </style>
</head>
<body>
    <header>
        <div class="container">
            <h1>🔌 Универсальный Modbus-декодер</h1>
        </div>
    </header>
    <div class="container">
        {content}
    </div>
    <script>
        // Автообновление каждые 5 секунд
        setTimeout(function() {{ location.reload(); }}, 5000);
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
        <tr><td>Ошибки декодирования</td><td>{{ mqtt_stats.decode_errors }}</td></tr>
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
                            Панель {{ panel.bserver_id }}
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

<div class="refresh-info">Автообновление через 5 секунд</div>
'''

PANEL_TEMPLATE = '''
<div class="card">
    <h2>
        <a href="/">← Назад</a> | 
        Роутер: {{ router_sn }} | Панель: {{ bserver_id }}
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

<div class="refresh-info">Автообновление через 5 секунд</div>
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
    
    # Render content first
    content = render_template_string(
        INDEX_TEMPLATE,
        stats=stats,
        routers=routers_data,
        mqtt_stats=mqtt_stats
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
        'status': panel.status.value,
        'registers': registers
    })


def run_web_ui(host: str = '0.0.0.0', port: int = 8080, debug: bool = False):
    """Run the web UI server."""
    logger.info(f"Web UI запущен на http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, use_reloader=False, threaded=True)
