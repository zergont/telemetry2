# Copyright (c) 2026 ООО «НГ-ЭНЕРГОСЕРВИС». Все права защищены.
# Программный комплекс «Честная Генерация»
# Модуль декодирования Modbus-телеметрии
# Автор: Саввиди Александр Анатольевич | ИНН 4725009270
#
# Данное программное обеспечение является конфиденциальным.
# Несанкционированное копирование, распространение или использование
# без письменного разрешения правообладателя запрещено.

"""
Тесты Web UI контроля метки времени (clock_guard): главная, /api/routers,
/api/clock, раздел «Метка времени» на /devices, clear-memory.

Запуск из корня репозитория:
    PYTHONIOENCODING=utf-8 env/Scripts/python.exe -m pytest tests/test_web_ui_clock.py -q
"""

import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import clock_guard
import mqtt_client
import panel_store
import web_ui

TZ = timezone(timedelta(hours=3))

SN_SHIFT = '1126246373'          # закрытый эпизод +2 ч, затем открытый +2 ч и молчание; свой режим correct
SN_OK = '6003790403'             # только нормальные метки
SN_INVALID = '7000000001'        # метка без пояса
SN_AHEAD = '7000000002'          # открытый эпизод +2 ч без молчания (режим flag)
SN_EVIL = '<script>x</script>'   # HTML-инъекция в router_sn: +2 ч и молчание
SN_STORE_ONLY = '7000000003'     # есть в store, у clock_guard данных нет

EVIL_ESCAPED = '&lt;script&gt;x&lt;/script&gt;'
SHIFT_OFFSET = 7190              # +2 ч, живая доставка ~10 с


def stamp(epoch: float) -> str:
    """Метка роутера: 2026-10-09T13:20:28+0300."""
    return datetime.fromtimestamp(epoch, tz=TZ).strftime('%Y-%m-%dT%H:%M:%S%z')


def feed(guard, sn: str, t_recv: float, offset: float):
    return guard.classify(sn, stamp(t_recv + offset), t_recv)


def build_scenario(guard, store, now: float):
    """
    Состояние модуля для страниц. t_recv — около time.time(), потому что
    snapshot()/router_status() считают «за 24 ч» и молчание от текущего времени.
    """
    # SN_SHIFT: эпизод +2 ч, закрытый двумя нормальными метками...
    for i in range(3):
        feed(guard, SN_SHIFT, now - 600 + i, SHIFT_OFFSET)
    feed(guard, SN_SHIFT, now - 500, -5)
    feed(guard, SN_SHIFT, now - 490, -5)
    # ...и второй эпизод +2 ч, после которого роутер замолчал
    for i in range(3):
        feed(guard, SN_SHIFT, now - 100 + i, SHIFT_OFFSET)

    for i in range(5):
        feed(guard, SN_OK, now - 50 + 10 * i, -5)

    guard.classify(SN_INVALID, '2026-10-09T13:20:28', now - 20)

    for i in range(2):
        feed(guard, SN_EVIL, now - 90 + i, SHIFT_OFFSET)

    # Тик монитора через 2 мин: сигнал о молчании для SN_SHIFT и SN_EVIL,
    # эпизоды ещё не закрыты (закрытие по молчанию — через 10 мин)
    guard.tick(now + 120)

    for i in range(2):
        feed(guard, SN_AHEAD, now - 5 + i, SHIFT_OFFSET)

    for sn in (SN_SHIFT, SN_OK, SN_INVALID, SN_AHEAD, SN_EVIL, SN_STORE_ONLY):
        store.update_panel(sn, 1, [], device_type='pcc')


class FakeMqtt:
    """Минимальная замена MqttClient для страниц Web UI."""

    _payload_key_map: dict = {}

    def __init__(self):
        self.with_clock = True

    def get_stats(self) -> dict:
        stats = {
            'connected': True,
            'messages_received': 20,
            'messages_decoded': 20,
            'messages_published': 18,
            'decode_errors': 0,
            'raw_undecoded': 0,
            'gzip_received': 0,
            'gzip_bytes_in': 0,
            'gzip_bytes_out': 0,
        }
        if self.with_clock:
            guard = clock_guard.get_clock_guard()
            stats['clock_guard'] = guard.get_counters() if guard is not None else None
        return stats

    def get_raw_undecoded(self) -> list:
        return []

    def get_unknown_keys(self) -> dict:
        return {}


@pytest.fixture
def env(tmp_path, monkeypatch):
    # Глобальные синглтоны: monkeypatch вернёт исходные значения после теста
    monkeypatch.setattr(panel_store, '_store', None)
    monkeypatch.setattr(clock_guard, '_clock_guard', None)
    fake = FakeMqtt()
    monkeypatch.setattr(mqtt_client, '_mqtt_client', fake)

    store = panel_store.init_store()
    guard = clock_guard.init_clock_guard({
        'mode': 'flag',
        'routers': {SN_SHIFT: 'correct'},
        'quarantine': {'file': str(tmp_path / 'clock_quarantine.jsonl')},
    })
    now = time.time()
    build_scenario(guard, store, now)

    web_ui.app.config['TESTING'] = True
    yield SimpleNamespace(client=web_ui.app.test_client(), guard=guard, store=store,
                          mqtt=fake, now=now)
    guard.close()


def _html(client, url: str) -> str:
    resp = client.get(url)
    assert resp.status_code == 200, url
    return resp.get_data(as_text=True)


# ============================================================
# Главная
# ============================================================

def test_index_clock_column(env):
    html = _html(env.client, '/')

    assert '<th>Часы</th>' in html
    assert 'спешат на 2 ч' in html                     # SN_AHEAD
    assert 'в норме' in html                           # SN_OK
    assert 'метка неразборчива' in html                # SN_INVALID
    assert 'молчит после сдвига на +2 ч' in html       # SN_SHIFT, SN_EVIL
    assert 'нет данных' in html                        # SN_STORE_ONLY
    for cls in ('clock-ok', 'clock-warn', 'clock-bad', 'clock-unknown'):
        assert f'status {cls}' in html, cls

    # Последний offset и эпизоды за 24 ч
    assert re.search(r'offset −[56],\d с', html), 'offset SN_OK'
    assert 'эпизодов за 24 ч: 2' in html               # SN_SHIFT
    # Свой режим роутера
    assert 'режим: correct' in html


def test_index_silence_alert(env):
    html = _html(env.client, '/')

    assert html.count('class="card clock-alert"') == 2  # SN_SHIFT и SN_EVIL
    assert 'Роутер молчит после tz_shift k=+2' in html
    assert 'перезапустите сервис опроса на роутере' in html
    wait_until_ts = env.guard.router_status(SN_SHIFT)['silence']['wait_until_ts']
    assert wait_until_ts and wait_until_ts in html
    # Сигнал — в самом начале страницы, до плиток статистики
    assert html.index('clock-alert') < html.index('class="stats"')


def test_index_mqtt_counters_row(env):
    html = _html(env.client, '/')

    assert '<td>Метки времени</td>' in html
    for label in ('tz_shift', 'invalid', 'исправлено', 'карантин', 'время приёма', 'ошибки модуля'):
        assert label in html, label
    counters = env.guard.get_counters()
    assert f"tz_shift&nbsp;{counters['tz_shift']}" in html
    assert 'режим: <strong>flag</strong>' in html
    assert '/devices#clock-episodes' in html


def test_index_counters_fall_back_to_guard(env):
    """В get_stats() нет ключа clock_guard — счётчики берутся из модуля."""
    env.mqtt.with_clock = False
    html = _html(env.client, '/')
    assert '<td>Метки времени</td>' in html
    assert f"tz_shift&nbsp;{env.guard.get_counters()['tz_shift']}" in html


def test_index_escapes_router_sn(env):
    html = _html(env.client, '/')
    assert SN_EVIL not in html
    assert EVIL_ESCAPED in html


# ============================================================
# API
# ============================================================

def test_api_routers_clock(env):
    resp = env.client.get('/api/routers')
    assert resp.status_code == 200
    routers = {r['sn']: r for r in resp.get_json()}

    assert set(routers) == {SN_SHIFT, SN_OK, SN_INVALID, SN_AHEAD, SN_EVIL, SN_STORE_ONLY}
    for r in routers.values():
        assert 'clock' in r
        # Прежние ключи на месте
        for key in ('gps_lat', 'gps_lon', 'gps_time', 'panel_count', 'panels'):
            assert key in r

    shift = routers[SN_SHIFT]['clock']
    assert shift['clock_state'] == 'silent'
    assert shift['silence']['k'] == 2
    assert shift['mode'] == 'correct'
    assert shift['episodes_24h'] == 2
    assert routers[SN_AHEAD]['clock']['clock_label'] == 'спешат на 2 ч'
    assert routers[SN_OK]['clock']['clock_state'] == 'ok'
    assert routers[SN_INVALID]['clock']['clock_state'] == 'invalid'
    assert routers[SN_STORE_ONLY]['clock'] is None


def test_api_clock(env):
    resp = env.client.get('/api/clock')
    assert resp.status_code == 200
    snap = resp.get_json()

    assert snap['enabled'] is True
    assert snap['mode'] == 'flag'
    assert snap['router_modes'] == {SN_SHIFT: 'correct'}
    assert {r['router_sn'] for r in snap['routers']} == {SN_SHIFT, SN_OK, SN_INVALID, SN_AHEAD, SN_EVIL}

    episodes = snap['episodes']
    assert len(episodes) == 5
    starts = [e['start'] for e in episodes]
    assert starts == sorted(starts, reverse=True)

    closed = [e for e in episodes if not e['open']]
    assert len(closed) == 1
    assert closed[0]['router_sn'] == SN_SHIFT
    assert closed[0]['close_reason'] == 'normal'
    assert closed[0]['action'] == 'corrected'
    assert (closed[0]['status'], closed[0]['k'], closed[0]['count']) == ('tz_shift', 2, 3)

    by_sn = {e['router_sn']: e for e in episodes if e['open']}
    assert by_sn[SN_SHIFT]['action'] == 'corrected'
    assert by_sn[SN_AHEAD]['action'] == 'flagged'
    assert by_sn[SN_INVALID]['status'] == 'invalid'
    assert by_sn[SN_INVALID]['action'] == 'replaced'

    counters = snap['counters']
    assert counters['tz_shift'] == 10
    assert counters['corrected'] == 6
    assert counters['invalid'] == 1
    assert counters['replaced'] == 1


# ============================================================
# /devices — раздел «Метка времени»
# ============================================================

def test_devices_clock_episodes(env):
    html = _html(env.client, '/devices')

    assert 'id="clock-episodes"' in html
    # Карточка — сразу после «Ошибки декодирования»
    after_errors = html.index('class="card"', html.index('id="decode-errors-card"') + 1)
    assert html.index('id="clock-episodes"') == after_errors + len('class="card" ')
    assert '⏱ Ошибки декодирования — метка времени' in html
    assert 'id="clock-episodes-count">(5)<' in html

    # Режим и свой режим роутера
    assert 'Режим: <strong>flag</strong>' in html
    assert f'<code>{SN_SHIFT}</code> → <strong>correct</strong>' in html

    body = html[html.index('id="clock-episodes-body"'):]
    body = body[:body.index('</table>')]
    assert body.count('<tr') == 1 + 5                     # заголовок + 5 эпизодов
    assert body.count('<tr class="clock-open">') == 4
    assert body.count('<code>tz_shift k=+2</code>') == 4
    assert 'часы спешат на 2 ч' in body
    assert body.count('>идёт<') == 4
    assert 'метки в норме' in body
    assert 'исправлено' in body
    assert 'флаг' in body
    assert 'время приёма' in body
    assert 'метка неразборчива' in body
    assert re.search(r'\+7 1\d\d…\+7 1\d\d с|\+7 1\d\d с', body), 'offset +2 ч'

    # Обновление через /api/clock с экранированием
    assert 'function escapeHtml' in html
    assert 'onclick="refreshClockEpisodes()"' in html
    assert 'var CLOCK_TEXT = ' in html


def test_devices_escapes_router_sn(env):
    html = _html(env.client, '/devices')
    assert SN_EVIL not in html
    assert EVIL_ESCAPED in html


def test_devices_unknown_key_not_injected_into_onclick(env, monkeypatch):
    """
    Неопознанный ключ payload приходит из MQTT. В onclick="clearUnknownKey('…')"
    экранирование &#39; браузер раскодирует до запуска JS — строка разрывалась
    и выполнялся произвольный код. Теперь ключ только в data-атрибуте.
    """
    evil = "x');alert(document.domain);//"
    monkeypatch.setattr(env.mqtt, 'get_unknown_keys',
                        lambda: {evil: {'count': 1, 'last_seen': time.time()}})
    html = _html(env.client, '/devices')
    assert evil not in html
    assert 'data-key="x&#39;);alert(document.domain);//"' in html
    assert 'onclick="clearUnknownKey(this.dataset.key)"' in html
    assert "clearUnknownKey('" not in html


@pytest.mark.skipif(shutil.which('node') is None, reason='нет node — JS не проверяется')
def test_devices_js_render_escapes(env, tmp_path):
    """renderClockEpisodes() из DEVICES_SCRIPT экранирует router_sn и метки."""
    snap = env.client.get('/api/clock').get_json()
    evil_ts = '"><img src=x onerror=alert(1)>'
    snap['episodes'][0]['first_ts'] = evil_ts
    snap['router_modes'][SN_EVIL] = 'correct'

    script = web_ui.DEVICES_SCRIPT.strip()
    assert script.startswith('<script>') and script.endswith('</script>')
    script = script[len('<script>'):-len('</script>')]

    harness = (
        "const elements = {};\n"
        "global.window = global;\n"
        "global.document = {\n"
        "  getElementById: id => (elements[id] = elements[id] || {innerHTML: '', textContent: ''}),\n"
        "  addEventListener: () => {},\n"
        "  querySelectorAll: () => [],\n"
        "};\n"
        f"global.CLOCK_TEXT = {json.dumps(web_ui.CLOCK_TEXT)};\n"
        f"{script}\n"
        f"renderClockEpisodes({json.dumps(snap)});\n"
        "process.stdout.write(JSON.stringify(elements));\n"
    )
    js_file = tmp_path / 'render.js'
    js_file.write_text(harness, encoding='utf-8')
    proc = subprocess.run(['node', str(js_file)], capture_output=True, timeout=60)
    assert proc.returncode == 0, proc.stderr.decode('utf-8', 'replace')
    out = json.loads(proc.stdout.decode('utf-8'))

    body = out['clock-episodes-body']['innerHTML']
    mode = out['clock-episodes-mode']['innerHTML']
    assert out['clock-episodes-count']['textContent'] == '(5)'
    assert SN_EVIL not in body and EVIL_ESCAPED in body
    assert SN_EVIL not in mode and EVIL_ESCAPED in mode
    assert evil_ts not in body
    assert '&quot;&gt;&lt;img src=x onerror=alert(1)&gt;' in body
    assert body.count('<tr class="clock-open">') == 4
    assert body.count('<code>tz_shift k=+2</code>') == 4
    for text in ('идёт', 'метки в норме', 'исправлено', 'флаг', 'время приёма', 'метка неразборчива'):
        assert text in body, text

    # Offset в JS совпадает с серверной отрисовкой (с точностью до вида пробела)
    def norm(s):
        return s.replace(' ', ' ').replace(' ', ' ')
    for ep in snap['episodes']:
        expected = web_ui._clock_offset_range(ep['min_offset'], ep['max_offset'])
        assert norm(expected) in norm(body), expected


@pytest.mark.skipif(shutil.which('node') is None, reason='нет node — JS не проверяется')
def test_devices_js_refresh_errors_escapes(tmp_path):
    """refreshErrors() экранирует router_sn и raw из сети, аргументы onclick — JSON-строки."""
    evil_type = "pcc');alert(1);//"
    errors = [{
        'timestamp': time.time() - 5,
        'router_sn': SN_EVIL,
        'bserver_id': 1,
        'device_type': evil_type,
        'addr': '40018',
        'reason': 'Ошибка <b>декодирования</b>',
        'raw_data': '<img src=x onerror=alert(2)>',
    }]

    script = web_ui.DEVICES_SCRIPT.strip()
    script = script[len('<script>'):-len('</script>')]
    harness = (
        "const elements = {};\n"
        "global.window = global;\n"
        "global.document = {\n"
        "  getElementById: id => (elements[id] = elements[id] || {innerHTML: '', textContent: ''}),\n"
        "  addEventListener: () => {},\n"
        "  querySelectorAll: () => [],\n"
        "};\n"
        "global.alert = msg => { throw new Error('alert: ' + msg); };\n"
        f"global.fetch = async () => ({{ ok: true, json: async () => {json.dumps(errors)} }});\n"
        f"{script}\n"
        "refreshErrors().then(() => process.stdout.write(JSON.stringify(elements)));\n"
    )
    js_file = tmp_path / 'errors.js'
    js_file.write_text(harness, encoding='utf-8')
    proc = subprocess.run(['node', str(js_file)], capture_output=True, timeout=60)
    assert proc.returncode == 0, proc.stderr.decode('utf-8', 'replace')
    body = json.loads(proc.stdout.decode('utf-8'))['decode-errors-body']['innerHTML']

    assert SN_EVIL not in body and EVIL_ESCAPED in body
    assert '<img' not in body and '&lt;img src=x onerror=alert(2)&gt;' in body
    assert '<b>' not in body and '&lt;b&gt;декодирования&lt;/b&gt;' in body
    # onclick: атрибут в двойных кавычках, внутри — JSON-строки, кавычки экранированы
    onclick = re.search(r'onclick="ignoreRegister\(([^"]*)\)"', body)
    assert onclick, body
    args = onclick.group(1).replace('&quot;', '"').replace('&#39;', "'").replace('&amp;', '&')
    assert json.loads(f'[{args}]') == [evil_type, '40018']


# ============================================================
# clear-memory
# ============================================================

def test_clear_memory_resets_clock_guard(env):
    counters_before = env.guard.get_counters()

    resp = env.client.post('/api/admin/clear-memory')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['ok'] is True
    assert data['cleared'] == {'routers': 6, 'panels': 6}
    assert data['clock'] == {'routers': 5, 'episodes': 5}

    snap = env.guard.snapshot()
    assert snap['routers'] == []
    assert snap['episodes'] == []
    assert snap['counters'] == counters_before          # счётчики сохраняются

    html = _html(env.client, '/')
    assert 'clock-alert' not in html
    assert _html(env.client, '/devices').count('id="clock-episodes-count">(0)<') == 1


def test_clear_memory_confirm_mentions_clock(env):
    html = _html(env.client, '/')
    assert 'состояние часов роутеров и журнал эпизодов метки времени' in html


# ============================================================
# Без модуля / без MQTT / модуль выключен
# ============================================================

def test_pages_without_clock_guard(env, monkeypatch):
    monkeypatch.setattr(clock_guard, '_clock_guard', None)

    html = _html(env.client, '/')
    assert 'clock-alert' not in html
    assert '<td>Метки времени</td>' not in html
    assert '<th>Часы</th>' in html

    devices = _html(env.client, '/devices')
    assert 'id="clock-episodes"' in devices
    assert 'Контроль метки времени не инициализирован' in devices
    assert 'Эпизодов нет' in devices

    routers = env.client.get('/api/routers').get_json()
    assert routers and all(r['clock'] is None for r in routers)

    resp = env.client.get('/api/clock')
    assert resp.status_code == 200
    assert resp.get_json() == {'enabled': False, 'routers': [], 'episodes': [], 'counters': {}}

    resp = env.client.post('/api/admin/clear-memory')
    assert resp.status_code == 200
    assert resp.get_json()['clock'] is None


def test_pages_without_mqtt(env, monkeypatch):
    monkeypatch.setattr(mqtt_client, '_mqtt_client', None)

    html = _html(env.client, '/')
    assert 'Статус MQTT' not in html
    assert 'спешат на 2 ч' in html
    assert html.count('class="card clock-alert"') == 2

    devices = _html(env.client, '/devices')
    assert 'id="clock-episodes-count">(5)<' in devices

    assert env.client.get('/api/routers').status_code == 200
    assert env.client.get('/api/clock').status_code == 200


def test_pages_without_clock_guard_and_mqtt(env, monkeypatch):
    monkeypatch.setattr(clock_guard, '_clock_guard', None)
    monkeypatch.setattr(mqtt_client, '_mqtt_client', None)
    for url in ('/', '/devices', '/api/routers', '/api/clock'):
        assert env.client.get(url).status_code == 200, url


def test_pages_with_clock_guard_disabled(env, monkeypatch, tmp_path):
    disabled = clock_guard.ClockGuard({
        'enabled': False,
        'quarantine': {'file': str(tmp_path / 'disabled.jsonl')},
    })
    monkeypatch.setattr(clock_guard, '_clock_guard', disabled)

    html = _html(env.client, '/')
    assert 'контроль метки времени выключен' in html
    assert 'clock-alert' not in html

    devices = _html(env.client, '/devices')
    assert 'Контроль метки времени выключен' in devices

    snap = env.client.get('/api/clock').get_json()
    assert snap['enabled'] is False
    disabled.close()


# ============================================================
# Форматирование
# ============================================================

@pytest.mark.parametrize('value, expected', [
    (-5.0, '−5,0 с'),
    (0.04, '0,0 с'),
    (-0.04, '0,0 с'),
    (12.3, '+12,3 с'),
    (-900, '−900 с (≈ −15 мин)'),
    (7190, '+7 190 с (≈ +2,0 ч)'),
    (-52919, '−52 919 с (≈ −14,7 ч)'),
    (None, '—'),
])
def test_fmt_offset(value, expected):
    assert web_ui._fmt_offset(value) == expected


def test_episode_row_texts():
    row = web_ui._clock_episode_row({
        'router_sn': SN_SHIFT, 'status': 'tz_shift', 'k': -3, 'action': 'flagged',
        'open': False, 'start_local': '2026-10-09 10:00:00', 'end_local': '2026-10-09 10:05:00',
        'duration_sec': 300.0, 'count': 12, 'min_offset': -10805.2, 'max_offset': -10790.0,
        'close_reason': 'silence', 'first_ts': 'a', 'last_ts': 'b',
    })
    assert row['status_code'] == 'tz_shift k=-3'
    assert row['status_text'] == 'часы отстают на 3 ч'
    assert row['action_text'] == 'флаг'
    assert row['close_text'] == 'молчание'
    assert row['duration'] == '5 мин'
    assert row['offset'] == '−10 805…−10 790 с'
