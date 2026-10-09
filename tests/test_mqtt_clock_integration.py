# Copyright (c) 2026 ООО «НГ-ЭНЕРГОСЕРВИС». Все права защищены.
# Программный комплекс «Честная Генерация»
# Модуль декодирования Modbus-телеметрии
# Автор: Саввиди Александр Анатольевич | ИНН 4725009270
#
# Данное программное обеспечение является конфиденциальным.
# Несанкционированное копирование, распространение или использование
# без письменного разрешения правообладателя запрещено.

"""
Интеграционные тесты: контроль метки времени в конвейере MQTT-клиента.

Сообщение проходит MqttClient._process_message целиком (нормализация,
декодирование по maps.example/pcc, хранилище панелей, clock_guard) и
публикуется в поддельный paho-клиент, который запоминает publish().
"""

import gzip
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import clock_guard
import maps_loader
import panel_store
from clock_guard import init_clock_guard, parse_router_ts, utc_iso_ms
from health_monitor import HealthMonitor
from maps_loader import load_device_maps
from mqtt_client import MqttClient
from panel_store import get_store, init_store

REPO = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO / 'maps.example' / 'pcc'

SN = '1126246373'
TOPIC = f'cg/v1/telemetry/SN/{SN}'
DECODED_BASE = 'cg/v1/decoded/SN'
QUARANTINE_BASE = 'cg/v1/quarantine/SN'

MSK = timezone(timedelta(hours=3))
# Время приёма: 2026-10-09 13:20:30 MSK (целые секунды — offset без дробей)
T0 = datetime(2026, 10, 9, 10, 20, 30, tzinfo=timezone.utc).timestamp()

BASE_KEYS = ['timestamp', 'router_sn', 'bserver_id', 'device_type', 'registers']
CLOCK_KEYS = {'received_at', 'ts_status', 'ts_offset_sec', 'ts_shift_hours', 'ts_original'}


# ============================================================
# Вспомогательное
# ============================================================

def stamp(offset: float, tz=MSK) -> str:
    """Метка роутера на offset секунд от T0: 2026-10-09T13:20:30+0300."""
    return datetime.fromtimestamp(T0 + offset, tz).strftime('%Y-%m-%dT%H:%M:%S%z')


def record(date_iso, addr: int = 18, data=(230,), server_id: int = 1) -> dict:
    """Запись старого формата PCC_3_3 (addr 18 → 40018 GensetL1N Voltage)."""
    return {'date_iso_8601': date_iso, 'server_id': server_id,
            'addr': addr, 'data': json.dumps(list(data))}


def message(*records, compress: bool = False) -> bytes:
    body = {'PCC_3_3': records[0] if len(records) == 1 else list(records)}
    raw = json.dumps(body).encode('utf-8')
    return gzip.compress(raw) if compress else raw


class FakePaho:
    """Поддельный paho-клиент: запоминает publish()."""

    def __init__(self):
        self.published = []

    def publish(self, topic, payload=None, qos=0, retain=False, properties=None):
        self.published.append(SimpleNamespace(topic=topic, payload=payload,
                                              qos=qos, retain=retain))
        return SimpleNamespace(rc=0)


def published(client, prefix: str) -> list:
    """[(topic, payload dict, publish call)] для топиков с префиксом."""
    return [(p.topic, json.loads(p.payload), p)
            for p in client._client.published if p.topic.startswith(prefix + '/')]


def decoded(client) -> list:
    return [(topic, payload) for topic, payload, _ in published(client, 'cg/v1/decoded')]


def quarantine_lines(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


# ============================================================
# Фикстуры
# ============================================================

@pytest.fixture(scope='module', autouse=True)
def example_maps():
    """Карта maps.example/pcc; реестр карт восстанавливается после модуля."""
    saved_loaders = dict(maps_loader._loaders)
    saved_dirs = dict(maps_loader._device_dirs)
    assert load_device_maps('pcc', str(MAPS_DIR))
    yield
    maps_loader._loaders.clear()
    maps_loader._loaders.update(saved_loaders)
    maps_loader._device_dirs.clear()
    maps_loader._device_dirs.update(saved_dirs)


@pytest.fixture(autouse=True)
def fresh_globals():
    """Свежее хранилище панелей, clock_guard не инициализирован; глобальные — назад."""
    saved_guard = clock_guard._clock_guard
    saved_store = panel_store._store
    clock_guard._clock_guard = None
    init_store()
    yield
    current = clock_guard._clock_guard
    if current is not None and current is not saved_guard:
        current.close()
    clock_guard._clock_guard = saved_guard
    panel_store._store = saved_store


@pytest.fixture
def qfile(tmp_path) -> Path:
    return tmp_path / 'quarantine' / 'clock_quarantine.jsonl'


@pytest.fixture
def make_guard(qfile):
    """Глобальный ClockGuard с карантином во временном каталоге."""
    def make(mode: str = 'flag', topic_base: str = QUARANTINE_BASE, **extra):
        cfg = {'enabled': True, 'mode': mode,
               'quarantine': {'file': str(qfile), 'topic_base': topic_base}}
        cfg.update(extra)
        return init_clock_guard(cfg)
    return make


@pytest.fixture
def client():
    c = MqttClient(host='localhost', decoded_topic_base=DECODED_BASE,
                   payload_key_map={'PCC_3_3': 'pcc'})
    c._client = FakePaho()
    c._connected = True
    return c


# ============================================================
# Публикация в decoded
# ============================================================

def test_normal_record_published_ok(client, make_guard):
    make_guard()
    ts = stamp(-5)
    client._process_message(TOPIC, message(record(ts)), T0)

    out = decoded(client)
    assert len(out) == 1
    topic, payload = out[0]
    assert topic == f'{DECODED_BASE}/{SN}/pcc/1'
    # Основные ключи — первыми и в прежнем порядке
    assert list(payload)[:5] == BASE_KEYS
    assert payload['timestamp'] == ts
    assert payload['router_sn'] == SN
    assert payload['bserver_id'] == 1
    assert payload['ts_status'] == 'ok'
    assert payload['received_at'] == utc_iso_ms(T0) == '2026-10-09T10:20:30.000+00:00'
    assert payload['ts_offset_sec'] == -5.0
    assert 'ts_shift_hours' not in payload and 'ts_original' not in payload
    regs = {r['addr']: r for r in payload['registers']}
    assert regs[40018]['value'] == 230.0
    assert client.messages_published == 1


def test_plus_two_hours_corrected_in_correct_mode(client, make_guard):
    make_guard(mode='correct')
    original = stamp(7170)                      # 15:20:00+0300 при приёме в 13:20:30
    client._process_message(TOPIC, message(record(original)), T0)

    (_, payload), = decoded(client)
    assert payload['timestamp'] == stamp(7170 - 7200) == '2026-10-09T13:20:00+0300'
    assert payload['ts_status'] == 'corrected'
    assert payload['ts_shift_hours'] == 2
    assert payload['ts_original'] == original
    assert payload['ts_offset_sec'] == 7170.0
    assert client.get_stats()['clock_guard']['corrected'] == 1


def test_plus_two_hours_flag_mode_keeps_original(client, make_guard):
    make_guard(mode='flag')
    original = stamp(7170)
    client._process_message(TOPIC, message(record(original)), T0)

    (_, payload), = decoded(client)
    assert payload['timestamp'] == original
    assert payload['ts_status'] == 'tz_shift'
    assert payload['ts_shift_hours'] == 2
    assert payload['ts_original'] == original


def test_router_override_correct(client, make_guard):
    make_guard(mode='flag', routers={SN: 'correct'})
    client._process_message(TOPIC, message(record(stamp(7170))), T0)

    (_, payload), = decoded(client)
    assert payload['ts_status'] == 'corrected'
    assert payload['timestamp'] == stamp(-30)


# ============================================================
# Карантин (future)
# ============================================================

def test_future_goes_to_quarantine(client, make_guard, qfile):
    guard = make_guard(mode='correct')
    original = stamp(300)                       # +5 мин — не целые часы
    client._process_message(TOPIC, message(record(original)), T0)

    # В decoded — ничего
    assert decoded(client) == []
    assert client.messages_published == 0

    # JSONL-карантин
    lines = quarantine_lines(qfile)
    assert len(lines) == 1
    entry = lines[0]
    assert entry['received_at'] == utc_iso_ms(T0)
    assert entry['router_sn'] == SN
    assert entry['bserver_id'] == 1
    assert entry['device_type'] == 'pcc'
    assert entry['timestamp'] == original
    assert entry['ts_status'] == 'future'
    assert entry['ts_offset_sec'] == 300.0
    assert entry['full_addr'] == '400018'
    assert entry['data'] == [230]
    assert [r['addr'] for r in entry['registers']] == [40018]

    # Топик наблюдения: qos 0, без retain
    obs = published(client, 'cg/v1/quarantine')
    assert len(obs) == 1
    topic, payload, call = obs[0]
    assert topic == f'{QUARANTINE_BASE}/{SN}/pcc/1'
    assert payload == entry
    assert call.qos == 0 and call.retain is False

    # Хранилище панелей обновлено: значения живые
    regs = {r['addr']: r for r in get_store().get_panel_registers(SN, 1)}
    assert regs[40018]['value'] == 230.0

    counters = guard.get_counters()
    assert counters['future'] == 1
    assert counters['quarantined'] == 1


@pytest.mark.parametrize('topic_base', [DECODED_BASE, 'cg/v1/decoded', 'cg/v1/decoded/quarantine', ''])
def test_quarantine_never_published_under_decoded(client, make_guard, qfile, topic_base):
    make_guard(topic_base=topic_base)
    client._process_message(TOPIC, message(record(stamp(300))), T0)

    assert client._client.published == []      # ни decoded, ни «карантин» под decoded
    assert len(quarantine_lines(qfile)) == 1     # файл пишется всё равно


def test_quarantine_not_published_when_disconnected(client, make_guard, qfile):
    make_guard()
    client._connected = False
    client._process_message(TOPIC, message(record(stamp(300))), T0)

    assert client._client.published == []
    assert len(quarantine_lines(qfile)) == 1


def test_quarantine_file_disabled_still_withheld_and_counted(client, qfile):
    guard = init_clock_guard({'quarantine': {'file': '', 'topic_base': QUARANTINE_BASE}})
    client._process_message(TOPIC, message(record(stamp(300))), T0)

    assert decoded(client) == []                 # в decoded — ничего
    assert not qfile.exists()                    # файл выключен
    assert len(published(client, 'cg/v1/quarantine')) == 1
    counters = client.get_stats()['clock_guard']
    # Запись удержана из decoded — это видно в счётчике, хоть файл и не пишется
    assert counters['future'] == 1 and counters['quarantined'] == 1
    assert counters['errors'] == 0
    assert guard is clock_guard.get_clock_guard()


# ============================================================
# invalid: метка заменяется временем приёма
# ============================================================

def test_no_timezone_replaced_with_receive_time(client, make_guard):
    make_guard()
    # Сначала нормальная запись — роутер «запоминает» свой пояс (+0300)
    client._process_message(TOPIC, message(record(stamp(-5))), T0 - 10)
    original = '2026-10-09T13:20:28'
    client._process_message(TOPIC, message(record(original)), T0)

    _, payload = decoded(client)[-1]
    assert payload['ts_status'] == 'invalid'
    assert payload['timestamp'] == stamp(0) == '2026-10-09T13:20:30+0300'
    assert payload['ts_original'] == original
    assert payload['ts_offset_sec'] is None
    assert payload['received_at'] == utc_iso_ms(T0)


@pytest.mark.parametrize('original', ['2026-10-09T13:20:28', '2000-01-01T00:00:00+0300', 'not a date'])
def test_invalid_stamp_gets_receive_time(client, make_guard, original):
    make_guard()
    client._process_message(TOPIC, message(record(original)), T0)

    (_, payload), = decoded(client)
    assert payload['ts_status'] == 'invalid'
    assert payload['ts_original'] == original
    # Пояс — местный сервера, момент — время приёма
    assert parse_router_ts(payload['timestamp']).timestamp() == T0


# ============================================================
# Отказоустойчивость и обратная совместимость
# ============================================================

def test_guard_not_initialized_old_payload(client):
    assert clock_guard.get_clock_guard() is None
    original = stamp(7170)
    client._process_message(TOPIC, message(record(original)), T0)

    (_, payload), = decoded(client)
    assert list(payload) == BASE_KEYS
    assert payload['timestamp'] == original
    assert client.get_stats()['clock_guard'] is None


def test_guard_disabled_old_payload(client, make_guard):
    make_guard(enabled=False)
    original = stamp(300)                       # future, но модуль выключен
    client._process_message(TOPIC, message(record(original)), T0)

    (_, payload), = decoded(client)
    assert list(payload) == BASE_KEYS
    assert payload['timestamp'] == original


def test_classify_raising_publishes_as_ok(client, make_guard, monkeypatch):
    guard = make_guard(mode='correct')

    def boom(*args, **kwargs):
        raise RuntimeError('сбой классификации')

    monkeypatch.setattr(guard, 'classify', boom)
    original = stamp(7170)
    client._process_message(TOPIC, message(record(original), record(stamp(-5), addr=3, data=[500])), T0)

    out = decoded(client)
    assert len(out) == 2                        # исключение не роняет сообщение
    for _, payload in out:
        assert payload['ts_status'] == 'ok'
        assert payload['received_at'] == utc_iso_ms(T0)
    assert out[0][1]['timestamp'] == original   # как есть, без исправления
    assert client.decode_errors == 0


def test_process_message_t_recv_optional(client, make_guard):
    make_guard()
    before = time.time()
    ts = datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')
    client._process_message(TOPIC, message(record(ts)))
    after = time.time()

    (_, payload), = decoded(client)
    assert payload['ts_status'] == 'ok'
    received = datetime.fromisoformat(payload['received_at']).timestamp()
    assert before - 0.001 <= received <= after + 0.001


def test_on_message_captures_wall_clock_t_recv(client, monkeypatch):
    calls = []
    monkeypatch.setattr(client, '_process_message',
                        lambda topic, payload, *args: calls.append((topic, payload, args)))
    msg = SimpleNamespace(topic=TOPIC, payload=b'{}', timestamp=12.345)  # монотонный paho

    before = time.time()
    client._on_message(None, None, msg)
    after = time.time()

    assert len(calls) == 1
    topic, payload, args = calls[0]
    assert (topic, payload) == (TOPIC, b'{}')
    assert len(args) == 1
    t_recv = args[0]
    assert before <= t_recv <= after
    assert t_recv != msg.timestamp
    assert client.messages_received == 1


def test_on_message_end_to_end(client, make_guard):
    make_guard()
    ts = datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')
    msg = SimpleNamespace(topic=TOPIC, payload=message(record(ts)), timestamp=1.0)
    client._on_message(None, None, msg)

    (_, payload), = decoded(client)
    assert payload['ts_status'] == 'ok'
    assert -60 <= payload['ts_offset_sec'] <= 1


# ============================================================
# GPS и пачки
# ============================================================

def test_gps_not_classified(client, make_guard, monkeypatch):
    guard = make_guard()
    calls = []
    original_classify = guard.classify
    monkeypatch.setattr(guard, 'classify',
                        lambda *a, **kw: calls.append(a) or original_classify(*a, **kw))

    gps = {'GPS': {'latitude': 59.85, 'longitude': 30.48, 'satellites': 4,
                   'date_iso_8601': stamp(3 * 3600)}}   # GPS-метка на +3 ч — не трогаем
    client._process_message(TOPIC, json.dumps(gps).encode('utf-8'), T0)

    assert calls == []
    assert client._client.published == []
    assert guard.get_counters()['total'] == 0
    assert get_store().get_router(SN).gps_lat == 59.85


def test_gzip_mixed_batch_corrects_only_shifted(client, make_guard, qfile):
    guard = make_guard(mode='correct')
    batch = [
        record(stamp(7170), addr=18, data=[230]),
        record(stamp(-8), addr=3, data=[500]),
        record(stamp(7171), addr=10, data=[1]),
        record(stamp(-8), addr=1, data=[100]),
    ]
    client._process_message(TOPIC, message(*batch, compress=True), T0)

    assert client.gzip_received == 1
    out = [payload for _, payload in decoded(client)]
    assert [p['registers'][0]['addr'] for p in out] == [40018, 40003, 40010, 40001]

    shifted = [out[0], out[2]]
    normal = [out[1], out[3]]
    for payload, offset in zip(shifted, (7170, 7171)):
        assert payload['ts_status'] == 'corrected'
        assert payload['ts_shift_hours'] == 2
        assert payload['ts_original'] == stamp(offset)
        assert payload['timestamp'] == stamp(offset - 7200)
    for payload in normal:
        assert payload['ts_status'] == 'ok'
        assert payload['timestamp'] == stamp(-8)
        assert 'ts_original' not in payload

    counters = client.get_stats()['clock_guard']
    assert counters['total'] == 4
    assert counters['tz_shift'] == 2
    assert counters['corrected'] == 2
    assert counters['ok'] == 2
    assert quarantine_lines(qfile) == []


# ============================================================
# Монитор состояния
# ============================================================

def test_health_tick_runs_even_if_store_check_fails(make_guard, monkeypatch):
    guard = make_guard()
    ticks = []
    monkeypatch.setattr(guard, 'tick', lambda *a, **kw: ticks.append(a))

    def broken():
        raise RuntimeError('сбой хранилища')

    monkeypatch.setattr(get_store(), 'update_health_status', broken)
    HealthMonitor()._check_health()
    assert len(ticks) == 1


def test_health_tick_failure_does_not_raise(make_guard, monkeypatch):
    guard = make_guard()
    checked = []

    def broken_tick(*a, **kw):
        raise RuntimeError('сбой тика')

    monkeypatch.setattr(guard, 'tick', broken_tick)
    monkeypatch.setattr(get_store(), 'update_health_status', lambda: checked.append(1))
    HealthMonitor()._check_health()             # не бросает
    assert checked == [1]


def test_health_tick_closes_episode_on_silence(client, make_guard):
    guard = make_guard(mode='correct')
    client._process_message(TOPIC, message(record(stamp(7170))), T0)
    assert guard.router_status(SN, now=T0)['episode']['open'] is True

    guard.tick(now=T0 + 11 * 60)                # молчание > episode_silence_close_min
    view = guard.router_status(SN, now=T0 + 11 * 60)
    assert view['episode'] is None
    assert view['silence'] is not None          # сигнал о молчании после tz_shift k>0
    snap = guard.snapshot(now=T0 + 11 * 60)
    assert snap['episodes'][0]['close_reason'] == 'silence'
