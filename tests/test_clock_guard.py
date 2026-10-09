# Copyright (c) 2026 ООО «НГ-ЭНЕРГОСЕРВИС». Все права защищены.
# Программный комплекс «Честная Генерация»
# Модуль декодирования Modbus-телеметрии
# Автор: Саввиди Александр Анатольевич | ИНН 4725009270
#
# Данное программное обеспечение является конфиденциальным.
# Несанкционированное копирование, распространение или использование
# без письменного разрешения правообладателя запрещено.

"""
Юнит-тесты контроля метки времени (clock_guard.py).

Таблица приёмки — раздел 7 задачи «Контроль метки времени в cg-decoder»,
плюс границы порогов, подтверждаемые статусы (tz_shift k<0, offset_jump),
приоритет статусов, эпизоды, сигнал о молчании, счётчики, конфигурация,
карантин, сброс, снимок состояния и потокобезопасность.

Время приёма (t_recv) везде задаётся явно от BASE; метки роутера —
в его формате '%Y-%m-%dT%H:%M:%S%z' (+0300, как у живых роутеров).

Запуск из корня репозитория:
    python -m pytest tests/test_clock_guard.py -q
"""

import json
import logging
import math
import os
import re
import threading
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest

import clock_guard as cg
from clock_guard import (
    ACTION_PUBLISH, ACTION_QUARANTINE, DEFAULT_QUARANTINE, DEFAULTS,
    MODE_CORRECT, MODE_FLAG, MODES,
    TS_CORRECTED, TS_FORMAT, TS_FUTURE, TS_INVALID, TS_LATE, TS_OFFSET_JUMP,
    TS_OK, TS_TZ_SHIFT,
    ClockGuard, ClockGuardConfig, TsVerdict,
    format_router_ts, get_clock_guard, init_clock_guard, parse_router_ts,
    passthrough_verdict, utc_iso_ms,
)


# ============================================================
# Данные и помощники
# ============================================================

# 2026-10-09 10:00:00 UTC = 13:00:00+0300
BASE = 1791540000.0
MSK = timezone(timedelta(hours=3))
UTC = timezone.utc

SN_DES3 = '1126246373'      # ДЭС №3 — эпизоды +2 ч
SN_6003 = '6003790403'      # 10 записей, 3 метки, 2 панели

BASE_KEYS = {'received_at', 'ts_status', 'ts_offset_sec'}
SHIFT_KEYS = BASE_KEYS | {'ts_shift_hours', 'ts_original'}
INVALID_KEYS = BASE_KEYS | {'ts_original'}

ROUTER_VIEW_KEYS = {
    'router_sn', 'mode', 'clock_state', 'clock_label', 'last_status',
    'last_offset_sec', 'last_ts', 'last_recv', 'last_recv_local',
    'episodes_24h', 'episode', 'silence',
}
EPISODE_VIEW_KEYS = {
    'id', 'router_sn', 'status', 'k', 'action', 'start', 'end', 'last_recv',
    'count', 'first_ts', 'last_ts', 'last_offset', 'min_offset', 'max_offset',
    'close_reason', 'open', 'duration_sec', 'start_local', 'end_local',
}
SILENCE_KEYS = {'since', 'since_local', 'k', 'wait_until', 'wait_until_ts', 'message'}

RECEIVED_AT_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+00:00$')
ROUTER_TS_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}$')

OPEN_MARK = 'начало эпизода'
CLOSE_MARK = 'конец эпизода'
SILENCE_MARK = 'Роутер молчит после tz_shift'
RESUME_MARK = 'возобновил передачу'


def ts(epoch, tz=MSK):
    """Метка роутера для момента epoch (дробная часть секунды отбрасывается)."""
    return datetime.fromtimestamp(epoch, tz=tz).strftime(TS_FORMAT)


def stamp_at(t_recv, offset, tz=MSK):
    """Метка, у которой offset ≈ offset относительно t_recv (с точностью до секунды)."""
    return ts(math.floor(t_recv + offset + 0.5), tz)


def epoch_of(stamp):
    dt = parse_router_ts(stamp)
    assert dt is not None, stamp
    return dt.timestamp()


def classify_at(guard, sn, t_recv, offset, tz=MSK):
    """Одна запись с заданным offset. Возвращает (метка, вердикт)."""
    stamp = stamp_at(t_recv, offset, tz)
    return stamp, guard.classify(sn, stamp, t_recv)


def live_stream(guard, sn, t0, count, step=10.0, offset=-5.0):
    """Живой поток: запись каждые step с, offset ≈ offset. Возвращает вердикты."""
    return [classify_at(guard, sn, t0 + i * step, offset)[1] for i in range(count)]


def held_offset(guard, sn, t0, offset, duration, step=10.0, jitter=(0,)):
    """
    Устойчивый поток с offset ≈ offset (+ jitter по кругу) от t0 в течение
    duration с, по записи каждые step с. Возвращает [(t_recv, метка, вердикт)].
    """
    rows = []
    for i in range(int(duration // step) + 1):
        t = t0 + i * step
        stamp, verdict = classify_at(guard, sn, t, offset + jitter[i % len(jitter)])
        rows.append((t, stamp, verdict))
    return rows


def statuses_of(rows):
    return [v.status for _, _, v in rows]


def guard_logs(caplog, marker, level=logging.WARNING):
    return [r for r in caplog.records
            if r.name == cg.logger.name and r.levelno == level and marker in r.getMessage()]


def stream_6003(guard, t_start, cycles, tick=True):
    """
    Поток роутера 6003790403: раз в 10 с сообщение из 10 записей по двум
    панелям, 3 разные метки за 3–4 с, offset от −18,5 до −0,6 с.
    Возвращает вердикты всех записей.
    """
    verdicts = []
    for cycle in range(cycles):
        frac = 0.6 if cycle % 2 == 0 else 0.5
        t = math.floor(t_start) + 10 * cycle + frac
        lag = (0, 3, 6, 9, 12, 14)[cycle % 6]        # задержка доставки, с
        spread = 3 if cycle % 2 == 0 else 4          # 3 метки за 3–4 с
        newest = math.floor(t) - lag
        s0, s1, s2 = ts(newest - spread), ts(newest - 1), ts(newest)
        panel_1 = [s0, s1, s2, s2, s2]
        panel_2 = [s0, s0, s1, s1, s2]
        for stamp in panel_1 + panel_2:
            verdicts.append(guard.classify(SN_6003, stamp, t))
        if tick:
            guard.tick(t + 5)                        # монитор состояния раз в 5 с
    return verdicts


@pytest.fixture
def make_guard(tmp_path):
    """Фабрика ClockGuard с карантином во временном каталоге; закрывается после теста."""
    guards = []

    def _make(**overrides):
        quarantine = {'file': str(tmp_path / f'q{len(guards)}' / 'clock_quarantine.jsonl')}
        quarantine.update(overrides.pop('quarantine', None) or {})
        guard = ClockGuard({**overrides, 'quarantine': quarantine})
        guards.append(guard)
        return guard

    yield _make
    for guard in guards:
        guard.close()


@pytest.fixture
def guard(make_guard):
    return make_guard()


# ============================================================
# Утилиты
# ============================================================

@pytest.mark.parametrize('value, hours', [
    ('2026-10-09T13:20:28+0300', 3),
    ('2026-10-09T10:20:28+0000', 0),
    ('2026-10-09T13:20:28+03:00', 3),
    ('2026-10-09T10:20:28+00:00', 0),
    ('2026-10-09T10:20:28Z', 0),
    ('  2026-10-09T13:20:28+0300\n', 3),
])
def test_parse_router_ts_aware(value, hours):
    dt = parse_router_ts(value)
    assert dt is not None
    assert dt.utcoffset() == timedelta(hours=hours)
    assert dt.timestamp() == datetime(2026, 10, 9, 10, 20, 28, tzinfo=UTC).timestamp()


@pytest.mark.parametrize('value', [
    '2026-10-09T13:20:28',              # без пояса
    '2026-10-09',                       # только дата
    'garbage', '', '   ',
    '2026-13-45T25:61:61+0300',
    None, 1791540000, 1791540000.0, b'2026-10-09T13:20:28+0300',
])
def test_parse_router_ts_rejects(value):
    assert parse_router_ts(value) is None


def test_format_router_ts_keeps_zone_without_colon():
    assert format_router_ts(datetime(2026, 10, 9, 13, 20, 28, tzinfo=MSK)) == '2026-10-09T13:20:28+0300'
    assert format_router_ts(datetime(2026, 10, 9, 10, 20, 28, tzinfo=UTC)) == '2026-10-09T10:20:28+0000'
    stamp = '2026-10-09T13:20:28+0300'
    assert format_router_ts(parse_router_ts(stamp)) == stamp


def test_utc_iso_ms():
    assert utc_iso_ms(BASE) == '2026-10-09T10:00:00.000+00:00'
    assert utc_iso_ms(BASE + 0.25) == '2026-10-09T10:00:00.250+00:00'
    assert RECEIVED_AT_RE.match(utc_iso_ms(BASE + 0.123456))


def test_passthrough_verdict():
    stamp = '2026-10-09T15:00:00+0300'
    v = passthrough_verdict(stamp, BASE)
    assert (v.status, v.ts_status, v.action, v.timestamp) == (TS_OK, TS_OK, ACTION_PUBLISH, stamp)
    assert v.received_at == utc_iso_ms(BASE)
    assert v.payload_fields() == {'received_at': utc_iso_ms(BASE), 'ts_status': TS_OK,
                                  'ts_offset_sec': None}
    # Даже с неразборчивым временем приёма — без исключения
    assert passthrough_verdict(None, 'bad').received_at is None


def test_base_epoch_is_13_00_msk():
    assert ts(BASE) == '2026-10-09T13:00:00+0300'
    assert ts(BASE, UTC) == '2026-10-09T10:00:00+0000'


# ============================================================
# Таблица приёмки (раздел 7)
# ============================================================

@pytest.mark.parametrize('mode', MODES)
def test_plus_5_min_is_future_quarantined(make_guard, mode):
    guard = make_guard(mode=mode)
    stamp, v = classify_at(guard, SN_DES3, BASE, 300)
    assert v.status == TS_FUTURE
    assert v.ts_status == TS_FUTURE
    assert v.action == ACTION_QUARANTINE          # в обоих режимах
    assert v.timestamp == stamp
    assert v.offset_sec == 300
    assert v.shift_hours is None
    assert v.received_at == utc_iso_ms(BASE)
    counters = guard.get_counters()
    assert counters['future'] == 1
    # quarantined растёт только при отправке в карантин (вызов quarantine()), не в classify
    assert counters['quarantined'] == 0


@pytest.mark.parametrize('tz', [MSK, UTC], ids=['+0300', '+0000'])
@pytest.mark.parametrize('mode', MODES)
def test_single_batch_80_records_plus_2h(make_guard, mode, tz):
    guard = make_guard(mode=mode)
    suffix = ts(BASE, tz)[-5:]
    rows = []
    for i in range(80):
        t = BASE + 0.025 * i                            # вся пачка за ≤2 с
        # своя метка у каждой записи, offset растёт от 7134 до ≈7175 с
        stamp = ts(math.ceil(t) + 7134 + (41 * i) // 79, tz)
        rows.append((t, stamp, guard.classify(SN_DES3, stamp, t)))

    offsets = [v.offset_sec for _, _, v in rows]
    assert 7134 <= min(offsets) and max(offsets) <= 7176
    assert rows[0][2].status == TS_TZ_SHIFT              # сразу, с первой записи
    for t, stamp, v in rows:
        assert (v.status, v.shift_hours) == (TS_TZ_SHIFT, 2)
        assert v.action == ACTION_PUBLISH
        assert v.original == stamp
        assert set(v.payload_fields()) == SHIFT_KEYS
        if mode == MODE_CORRECT:
            assert v.ts_status == TS_CORRECTED
            assert v.timestamp == ts(epoch_of(stamp) - 7200, tz)
            assert ROUTER_TS_RE.match(v.timestamp)
            assert v.timestamp.endswith(suffix)          # формат и пояс сохранены
            assert -120 <= epoch_of(v.timestamp) - t <= 0
        else:
            assert v.ts_status == TS_TZ_SHIFT
            assert v.timestamp == stamp

    counters = guard.get_counters()
    assert counters['total'] == counters['tz_shift'] == 80
    assert counters['corrected'] == (80 if mode == MODE_CORRECT else 0)
    episodes = guard.snapshot(now=BASE + 2)['episodes']
    assert len(episodes) == 1
    ep = episodes[0]
    assert (ep['status'], ep['k'], ep['count'], ep['open']) == (TS_TZ_SHIFT, 2, 80, True)
    assert ep['first_ts'] == rows[0][1]
    assert ep['action'] == ('corrected' if mode == MODE_CORRECT else 'flagged')


@pytest.mark.parametrize('mode', MODES)
def test_plus_2h_delivered_10_min_late(make_guard, mode):
    guard = make_guard(mode=mode)
    stamp, v = classify_at(guard, SN_DES3, BASE, 6600)
    assert (v.status, v.shift_hours, v.offset_sec) == (TS_TZ_SHIFT, 2, 6600)
    assert v.action == ACTION_PUBLISH
    if mode == MODE_CORRECT:
        assert v.ts_status == TS_CORRECTED
        assert v.timestamp == ts(epoch_of(stamp) - 7200)
    else:
        assert v.timestamp == stamp


def test_correction_crosses_midnight(make_guard):
    guard = make_guard(mode=MODE_CORRECT)
    stamp = '2026-10-10T01:30:00+0300'
    v = guard.classify(SN_DES3, stamp, epoch_of(stamp) - 7220)
    assert v.ts_status == TS_CORRECTED
    assert v.timestamp == '2026-10-09T23:30:00+0300'
    assert v.original == stamp


@pytest.mark.parametrize('mode', MODES)
def test_mixed_batch_only_shifted_records_corrected(make_guard, mode):
    guard = make_guard(mode=mode)
    pattern = 'SNSSNSNNSSN'                 # S — +2 ч, N — нормальная метка
    for j, kind in enumerate(pattern):
        t = BASE + 0.02 * j
        stamp = ts(BASE + 7160 + j) if kind == 'S' else ts(BASE - 15 + j)
        v = guard.classify(SN_DES3, stamp, t)
        assert v.action == ACTION_PUBLISH
        if kind == 'S':
            assert (v.status, v.shift_hours) == (TS_TZ_SHIFT, 2)
            assert set(v.payload_fields()) == SHIFT_KEYS
            if mode == MODE_CORRECT:
                assert v.ts_status == TS_CORRECTED
                assert v.timestamp == ts(BASE + 7160 + j - 7200)
            else:
                assert v.ts_status == TS_TZ_SHIFT
                assert v.timestamp == stamp
        else:
            assert (v.status, v.ts_status) == (TS_OK, TS_OK)
            assert v.timestamp == stamp                  # нормальные — без изменений
            assert v.shift_hours is None and v.original is None
            assert set(v.payload_fields()) == BASE_KEYS
    counters = guard.get_counters()
    assert counters['tz_shift'] == pattern.count('S')
    assert counters['ok'] == pattern.count('N')
    assert counters['corrected'] == (pattern.count('S') if mode == MODE_CORRECT else 0)


STALE_OFFSETS = [-63, -1000, -52919, -12.3 * 3600, -100.2 * 3600, -4.2 * 86400]


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('offset', STALE_OFFSETS,
                         ids=['-63s', '-1000s', '-52919s', '-12.3h', '-100.2h', '-4.2d'])
def test_stale_batch_then_live_is_late(make_guard, mode, offset):
    guard = make_guard(mode=mode)
    assert all(v.status == TS_OK for v in live_stream(guard, SN_DES3, BASE, 20))
    t0 = BASE + 200 + 1800                               # связь вернулась через 30 мин
    batch = []
    for j in range(3):                                   # 1–3 метки за ≤1 с
        stamp = ts(math.floor(t0 + offset) - 2 * j)
        batch.append((stamp, guard.classify(SN_DES3, stamp, t0 + 0.4 * j)))
    live = live_stream(guard, SN_DES3, t0 + 1, 30)       # сразу за ней — живой поток

    for stamp, v in batch:
        assert (v.status, v.ts_status, v.action) == (TS_LATE, TS_LATE, ACTION_PUBLISH)
        assert v.timestamp == stamp                      # late никогда не исправляется
        assert set(v.payload_fields()) == BASE_KEYS
    assert all(v.status == TS_OK for v in live)
    counters = guard.get_counters()
    assert counters['late'] == 3
    assert counters['tz_shift'] == counters['offset_jump'] == counters['future'] == 0
    assert counters['corrected'] == 0
    snap = guard.snapshot(now=t0 + 300)
    assert snap['episodes'] == []
    assert snap['routers'][0]['clock_state'] == 'ok'


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('deltas', [(-60, 0, 60), (0, 0, 0), (60, 60), (-60,)], ids=str)
@pytest.mark.parametrize('history', [True, False], ids=['after-live', 'fresh-router'])
def test_stale_batch_exactly_minus_3h_then_live_is_late(make_guard, mode, deltas, history):
    guard = make_guard(mode=mode)
    if history:
        live_stream(guard, SN_DES3, BASE, 20)
    t0 = BASE + 200 + 1800
    batch = []
    for j, d in enumerate(deltas):                       # −3 ч ±60 с, пачка за ≤1 с
        stamp = ts(t0 - 10800 + d - j)
        batch.append(guard.classify(SN_DES3, stamp, t0 + 0.4 * j))
    live = live_stream(guard, SN_DES3, t0 + 1, 30)

    assert all(-10800 - 62 <= v.offset_sec <= -10800 + 60 for v in batch)
    assert [v.status for v in batch] == [TS_LATE] * len(deltas)
    assert all(v.status == TS_OK for v in live)
    counters = guard.get_counters()
    assert counters['tz_shift'] == counters['offset_jump'] == 0
    assert guard.snapshot(now=t0 + 300)['episodes'] == []


@pytest.mark.parametrize('mode', MODES)
def test_minus_3h_held_2_min_is_tz_shift_flag_only(make_guard, mode, caplog):
    caplog.set_level(logging.WARNING, logger=cg.logger.name)
    guard = make_guard(mode=mode)
    live_stream(guard, SN_DES3, BASE, 20)
    t0 = BASE + 200
    rows = held_offset(guard, SN_DES3, t0, -10800 - 6, duration=180,
                       jitter=(0, -3, 2, -1, 4))
    for t, stamp, v in rows:
        assert v.action == ACTION_PUBLISH
        assert v.timestamp == stamp                      # без исправления даже в correct
        if t - t0 < 120:
            assert (v.status, v.ts_status, v.shift_hours) == (TS_LATE, TS_LATE, None)
        else:
            assert (v.status, v.ts_status, v.shift_hours) == (TS_TZ_SHIFT, TS_TZ_SHIFT, -3)
            fields = v.payload_fields()
            assert set(fields) == SHIFT_KEYS
            assert fields['ts_shift_hours'] == -3
            assert fields['ts_original'] == stamp
    assert [t - t0 for t, _, v in rows if v.status == TS_TZ_SHIFT][0] == 120

    counters = guard.get_counters()
    assert counters['tz_shift'] == 7 and counters['late'] == 12
    assert counters['corrected'] == 0
    view = guard.router_status(SN_DES3, now=rows[-1][0])
    assert (view['clock_state'], view['clock_label']) == ('behind', 'отстают на 3 ч')
    assert view['episode']['k'] == -3 and view['episode']['action'] == 'flagged'
    assert len(guard_logs(caplog, OPEN_MARK)) == 1
    assert guard_logs(caplog, CLOSE_MARK) == []


def test_stamp_without_tz_is_invalid_with_receive_time(guard):
    classify_at(guard, SN_DES3, BASE, -5)                # роутер шлёт +0300
    t = BASE + 10.75
    naive = '2026-10-09T13:00:05'
    v = guard.classify(SN_DES3, naive, t)
    assert (v.status, v.ts_status, v.action) == (TS_INVALID, TS_INVALID, ACTION_PUBLISH)
    assert v.timestamp == ts(t) == '2026-10-09T13:00:10+0300'   # время приёма, пояс роутера
    assert v.original == naive
    assert v.offset_sec is None and v.shift_hours is None
    fields = v.payload_fields()
    assert set(fields) == INVALID_KEYS
    assert fields['ts_original'] == naive
    assert fields['ts_offset_sec'] is None
    assert fields['received_at'] == utc_iso_ms(t)
    counters = guard.get_counters()
    assert counters['invalid'] == counters['replaced'] == 1


def test_invalid_on_fresh_router_uses_receive_time(guard):
    t = BASE + 3
    v = guard.classify('fresh', '2026-10-09T13:00:00', t)
    assert v.status == TS_INVALID
    assert ROUTER_TS_RE.match(v.timestamp)               # с поясом (сервера)
    assert epoch_of(v.timestamp) == t


def test_invalid_uses_utc_zone_of_router(guard):
    classify_at(guard, SN_DES3, BASE, -5, tz=UTC)
    v = guard.classify(SN_DES3, '2000-01-01T00:00:00+0000', BASE + 1)
    assert v.timestamp == '2026-10-09T10:00:01+0000'


@pytest.mark.parametrize('value', [
    '2000-01-01T03:00:00+0300',
    '2000-01-01T00:00:00+0000',
    '2023-12-31T23:59:59+0000',
    '2024-01-01T02:59:59+0300',         # = 2023-12-31T23:59:59Z
    '2026-10-09T13:00:00',
    'garbage', '', '2026-10-09', None, 1791540000,
])
def test_invalid_stamps(guard, value):
    classify_at(guard, SN_DES3, BASE, -5)
    t = BASE + 1
    v = guard.classify(SN_DES3, value, t)
    assert (v.status, v.ts_status, v.action) == (TS_INVALID, TS_INVALID, ACTION_PUBLISH)
    assert v.timestamp == ts(t)
    assert v.original == (None if value is None else str(value))
    assert v.received_at == utc_iso_ms(t)


def test_min_valid_date_inclusive(guard):
    v = guard.classify(SN_DES3, '2024-01-01T00:00:00+0000', BASE)
    assert v.status != TS_INVALID
    assert v.status == TS_LATE


def test_6003790403_stream_all_ok(guard):
    verdicts = stream_6003(guard, BASE, 180)             # 30 минут
    assert len(verdicts) == 1800
    offsets = [v.offset_sec for v in verdicts]
    assert min(offsets) == pytest.approx(-18.5)
    assert max(offsets) == pytest.approx(-0.6)
    assert Counter(v.status for v in verdicts) == {TS_OK: 1800}
    assert all(v.ts_status == TS_OK and v.action == ACTION_PUBLISH for v in verdicts)
    snap = guard.snapshot(now=BASE + 1800)
    assert snap['episodes'] == []
    view = snap['routers'][0]
    assert (view['clock_state'], view['clock_label']) == ('ok', 'в норме')
    assert view['silence'] is None and view['episodes_24h'] == 0
    assert snap['counters']['ok'] == 1800


def test_6003790403_stale_batches_after_outages_are_late(guard):
    verdicts = stream_6003(guard, BASE, 60)              # 10 минут
    # обрыв 20 мин, монитор тикает
    for now in range(int(BASE + 600), int(BASE + 1800), 5):
        guard.tick(now)
    t1 = BASE + 1800.3
    for j in range(2):                                   # залежалая пачка: 2 метки за ≤1 с
        verdicts.append(guard.classify(SN_6003, ts(math.floor(t1) - 900 - j), t1 + 0.5 * j))
    verdicts += stream_6003(guard, t1 + 1, 60)
    # второй обрыв 40 мин
    t2 = t1 + 600 + 2400
    guard.tick(t2 - 1)
    for j in range(3):
        verdicts.append(guard.classify(SN_6003, ts(math.floor(t2) - 63 - j), t2 + 0.3 * j))
    verdicts += stream_6003(guard, t2 + 1, 60)

    statuses = Counter(v.status for v in verdicts)
    assert set(statuses) == {TS_OK, TS_LATE}
    assert statuses[TS_LATE] == 5
    assert guard.snapshot(now=t2 + 700)['episodes'] == []


# ============================================================
# Границы порогов
# ============================================================

@pytest.mark.parametrize('k', range(1, 15))
def test_tz_shift_window_bounds(guard, k):
    for i, offset in enumerate((k * 3600 - 1800, k * 3600, k * 3600 + 120)):
        _, v = classify_at(guard, SN_DES3, BASE + i, offset)
        assert (v.status, v.shift_hours) == (TS_TZ_SHIFT, k), offset
        assert v.action == ACTION_PUBLISH
    for i, offset in enumerate((k * 3600 - 1801, k * 3600 + 121)):
        _, v = classify_at(guard, SN_DES3, BASE + 10 + i, offset)
        assert (v.status, v.action) == (TS_FUTURE, ACTION_QUARANTINE), offset


@pytest.mark.parametrize('offset', [
    121, 300, 1799, 3721, 5399, 7321, 8999,
    14 * 3600 + 121, 15 * 3600 - 1800, 15 * 3600, 15 * 3600 + 120, 86400,
])
def test_future_offsets(guard, offset):
    _, v = classify_at(guard, SN_DES3, BASE, offset)
    assert (v.status, v.action, v.shift_hours) == (TS_FUTURE, ACTION_QUARANTINE, None)


@pytest.mark.parametrize('offset, expected', [
    (120, TS_OK),           # ε строгое: ровно 120 — не future
    (120.5, TS_FUTURE),
    (121, TS_FUTURE),
    (0, TS_OK),
    (-60, TS_OK),
    (-60.5, TS_LATE),
    (-61, TS_LATE),
])
def test_epsilon_and_late_bounds(guard, offset, expected):
    stamp_epoch = BASE + math.ceil(offset)
    t = stamp_epoch - offset                             # метка — целые секунды
    v = guard.classify(SN_DES3, ts(stamp_epoch), t)
    assert v.offset_sec == offset
    assert v.status == expected


@pytest.mark.parametrize('mode', MODES)
def test_late_never_corrected_or_quarantined(make_guard, mode):
    guard = make_guard(mode=mode)
    for i, offset in enumerate((-61, -1000, -7230, -10800, -52919, -360720)):
        stamp, v = classify_at(guard, f'R{i}', BASE, offset)
        assert (v.status, v.ts_status, v.action) == (TS_LATE, TS_LATE, ACTION_PUBLISH)
        assert v.timestamp == stamp
    counters = guard.get_counters()
    assert counters['corrected'] == counters['quarantined'] == 0


# ============================================================
# tz_shift k<0 — только с подтверждением
# ============================================================

@pytest.mark.parametrize('hours', [-1, -3, -14])
def test_negative_shift_confirmed_for_whole_hours(guard, hours):
    rows = held_offset(guard, SN_DES3, BASE, hours * 3600, duration=150)
    assert statuses_of(rows[:12]) == [TS_LATE] * 12
    assert all((v.status, v.shift_hours) == (TS_TZ_SHIFT, hours) for _, _, v in rows[12:])


def test_negative_shift_tolerance_boundary(guard):
    inside = held_offset(guard, 'inside', BASE, -10800 - 120, duration=150)
    assert inside[-1][2].status == TS_TZ_SHIFT
    # Вне допуска это уже не целые часы: устойчивый отход — offset_jump, не tz_shift
    outside = held_offset(guard, 'outside', BASE, -10800 - 121, duration=150)
    statuses = statuses_of(outside)
    assert TS_TZ_SHIFT not in statuses
    assert statuses == [TS_LATE] * 6 + [TS_OFFSET_JUMP] * (len(statuses) - 6)


@pytest.mark.parametrize('step', [31, 40, 60])
def test_negative_shift_not_confirmed_with_reception_gaps(guard, step):
    rows = held_offset(guard, SN_DES3, BASE, -10800, duration=900, step=step)
    assert set(statuses_of(rows)) == {TS_LATE}


def test_negative_shift_reset_by_live_record(guard):
    first = held_offset(guard, SN_DES3, BASE, -10800, duration=110)
    assert set(statuses_of(first)) == {TS_LATE}
    assert classify_at(guard, SN_DES3, BASE + 115, -5)[1].status == TS_OK
    second = held_offset(guard, SN_DES3, BASE + 120, -10800, duration=150)
    # отсчёт 120 с начинается заново после живой записи
    assert statuses_of(second) == [TS_LATE] * 12 + [TS_TZ_SHIFT] * 4


def test_negative_shift_not_confirmed_when_spread_too_wide(guard):
    rows = held_offset(guard, SN_DES3, BASE, -10800, duration=300, jitter=(0, -40))
    assert set(statuses_of(rows)) == {TS_LATE}


def test_negative_shift_needs_min_distinct_stamps(make_guard):
    guard = make_guard(neg_shift_min_stamps=20)
    rows = held_offset(guard, SN_DES3, BASE, -10800, duration=250)
    statuses = statuses_of(rows)
    assert statuses.index(TS_TZ_SHIFT) == 19              # 20 разных меток, 190 с
    assert set(statuses[:19]) == {TS_LATE}


# ============================================================
# offset_jump
# ============================================================

def test_offset_jump_confirmed_after_60_s(guard, caplog):
    caplog.set_level(logging.WARNING, logger=cg.logger.name)
    assert all(v.status == TS_OK for v in live_stream(guard, SN_DES3, BASE, 20))  # база ≈ −5 с
    t0 = BASE + 200
    rows = held_offset(guard, SN_DES3, t0, -1000, duration=120)
    assert statuses_of(rows) == [TS_LATE] * 6 + [TS_OFFSET_JUMP] * 7
    for _, stamp, v in rows:
        assert v.action == ACTION_PUBLISH and v.timestamp == stamp
        assert set(v.payload_fields()) == BASE_KEYS
    view = guard.router_status(SN_DES3, now=t0 + 120)
    assert (view['clock_state'], view['clock_label']) == ('jump', 'скачок смещения: -17 мин')
    assert view['episode']['status'] == TS_OFFSET_JUMP
    assert view['episode']['action'] == 'flagged'
    assert len(guard_logs(caplog, OPEN_MARK)) == 1
    assert guard.get_counters()['offset_jump'] == 7

    # Смещение вернулось: живые записи — ok, эпизод закрыт после 2 разных меток
    assert all(v.status == TS_OK for v in live_stream(guard, SN_DES3, t0 + 130, 2))
    assert guard.router_status(SN_DES3, now=t0 + 150)['episode'] is None
    ep = guard.snapshot(now=t0 + 150)['episodes'][0]
    assert (ep['status'], ep['close_reason'], ep['count']) == (TS_OFFSET_JUMP, 'normal', 7)
    assert len(guard_logs(caplog, CLOSE_MARK)) == 1


@pytest.mark.parametrize('step', [31, 40, 60])
def test_offset_jump_not_confirmed_with_reception_gaps(guard, step):
    live_stream(guard, SN_DES3, BASE, 20)
    rows = held_offset(guard, SN_DES3, BASE + 200, -1000, duration=900, step=step)
    assert set(statuses_of(rows)) == {TS_LATE}


def test_offset_jump_not_confirmed_when_spread_too_wide(guard):
    live_stream(guard, SN_DES3, BASE, 20)
    rows = held_offset(guard, SN_DES3, BASE + 200, -1000, duration=300, jitter=(0, -100))
    assert set(statuses_of(rows)) == {TS_LATE}


def test_offset_jump_needs_distinct_stamps(guard):
    live_stream(guard, SN_DES3, BASE, 20)
    stamp = stamp_at(BASE + 200, -1000)
    for i in range(7):                                    # одна и та же метка 60 с
        v = guard.classify(SN_DES3, stamp, BASE + 200 + 10 * i)
        assert v.status == TS_LATE


def test_offset_jump_baseline_is_median_of_live_offsets(guard):
    live_stream(guard, 'slow', BASE, 20, offset=-50)      # база −50 с
    live_stream(guard, 'fast', BASE, 20, offset=50)       # база +50 с
    slow = held_offset(guard, 'slow', BASE + 200, -640, duration=180)
    fast = held_offset(guard, 'fast', BASE + 200, -640, duration=180)
    assert set(statuses_of(slow)) == {TS_LATE}            # отход −590 с — не скачок
    assert statuses_of(fast) == [TS_LATE] * 6 + [TS_OFFSET_JUMP] * 13   # отход −690 с


@pytest.mark.parametrize('kind', ['neg', 'jump'])
def test_confirmed_tracker_does_not_keep_stamps(guard, kind):
    """
    После подтверждения tz_shift k<0 / offset_jump трекер не перезапускается,
    пока смещение держится, а метки ему уже не нужны. Раньше множество меток
    росло на каждую запись: роутер с часами на −3 ч (или отставшими на
    >10 мин) неделями копил память без предела.
    """
    if kind == 'neg':
        offset, expected = -10800, TS_TZ_SHIFT
    else:
        live_stream(guard, SN_DES3, BASE, 20)             # база ≈ −5 с
        offset, expected = -1000, TS_OFFSET_JUMP
    t0 = BASE + 200
    rows = held_offset(guard, SN_DES3, t0, offset, duration=3600, step=2)   # 1801 разная метка
    assert rows[-1][2].status == expected
    assert len({stamp for _, stamp, _ in rows}) == len(rows)
    tracker = getattr(guard._routers[SN_DES3], kind)
    assert tracker.confirmed
    assert len(tracker.stamps) == 0

    # Живая запись сбрасывает трекер; новое подтверждение снова считает метки
    t1 = t0 + 3610
    assert classify_at(guard, SN_DES3, t1, -5)[1].status == TS_OK
    again = held_offset(guard, SN_DES3, t1 + 10, offset, duration=150)
    statuses = statuses_of(again)
    assert statuses[0] == TS_LATE and statuses[-1] == expected


# ============================================================
# Приоритет: invalid > tz_shift > future > offset_jump > late > ok
# ============================================================

def test_status_priority(guard):
    # invalid: по offset метка 2000 года была бы late, а без пояса +2 ч — tz_shift
    assert guard.classify('P1', '2000-01-01T03:00:00+0300', BASE).status == TS_INVALID
    naive_plus_2h = datetime.fromtimestamp(BASE + 7200, MSK).strftime('%Y-%m-%dT%H:%M:%S')
    assert guard.classify('P1', naive_plus_2h, BASE + 1).status == TS_INVALID

    # tz_shift > future: +2 ч тоже «впереди больше ε»
    assert classify_at(guard, 'P2', BASE, 7200)[1].status == TS_TZ_SHIFT

    # Подтверждённый скачок −1000 с
    live_stream(guard, 'P3', BASE, 20)
    rows = held_offset(guard, 'P3', BASE + 200, -1000, duration=70)
    assert rows[-1][2].status == TS_OFFSET_JUMP
    t = rows[-1][0] + 10
    # future > offset_jump: +700 с отходит от базы на >600 с, но это future
    assert classify_at(guard, 'P3', t, 700)[1].status == TS_FUTURE
    # tz_shift > offset_jump
    assert classify_at(guard, 'P3', t + 1, 7200)[1].status == TS_TZ_SHIFT
    # offset_jump > late: offset −1000 < −60, но это скачок
    assert classify_at(guard, 'P3', t + 2, -1000)[1].status == TS_OFFSET_JUMP

    # tz_shift (k<0, подтверждён) > late
    neg = held_offset(guard, 'P4', BASE, -7200, duration=120)
    assert neg[-1][2].status == TS_TZ_SHIFT and neg[-1][2].offset_sec < -60

    # late > ok
    assert classify_at(guard, 'P5', BASE, -61)[1].status == TS_LATE


# ============================================================
# Эпизоды
# ============================================================

def test_episode_lifecycle_open_and_close_after_two_normal_stamps(guard, caplog):
    caplog.set_level(logging.WARNING, logger=cg.logger.name)
    live_stream(guard, SN_DES3, BASE, 3)
    assert guard.router_status(SN_DES3, now=BASE + 20)['episode'] is None
    assert guard_logs(caplog, OPEN_MARK) == []

    t = BASE + 100
    first, _ = classify_at(guard, SN_DES3, t, 7190)       # открывает эпизод
    classify_at(guard, SN_DES3, t + 1, 7190)
    classify_at(guard, SN_DES3, t + 2, 7190)
    assert len(guard_logs(caplog, OPEN_MARK)) == 1        # один WARNING на начало
    ep = guard.router_status(SN_DES3, now=t + 2)['episode']
    assert ep['open'] and (ep['status'], ep['k'], ep['count']) == (TS_TZ_SHIFT, 2, 3)
    assert ep['first_ts'] == first and ep['action'] == 'flagged'

    def is_open():
        return guard.router_status(SN_DES3, now=t + 60)['episode'] is not None

    # Одна нормальная метка — эпизод ещё открыт
    assert classify_at(guard, SN_DES3, t + 10, -5)[1].status == TS_OK
    assert is_open()
    # Аномальная запись сбрасывает счётчик нормальных меток
    last_shift, _ = classify_at(guard, SN_DES3, t + 11, 7190)
    stamp_b, v = classify_at(guard, SN_DES3, t + 20, -5)
    assert v.status == TS_OK and is_open()
    # late эпизод не закрывает
    assert classify_at(guard, SN_DES3, t + 21, -500)[1].status == TS_LATE
    assert is_open()
    # Повтор той же метки — не новая нормальная метка
    assert guard.classify(SN_DES3, stamp_b, t + 22).status == TS_OK
    assert is_open()
    # Вторая разная нормальная метка закрывает эпизод
    assert classify_at(guard, SN_DES3, t + 30, -5)[1].status == TS_OK
    assert not is_open()

    assert len(guard_logs(caplog, OPEN_MARK)) == 1
    assert len(guard_logs(caplog, CLOSE_MARK)) == 1      # один WARNING на конец
    episodes = guard.snapshot(now=t + 60)['episodes']
    assert len(episodes) == 1
    ep = episodes[0]
    assert not ep['open'] and ep['close_reason'] == 'normal'
    assert ep['count'] == 4
    assert ep['start'] == t and ep['end'] == t + 11      # конец — последняя аномальная запись
    assert ep['last_ts'] == last_shift
    assert ep['duration_sec'] == 11.0
    assert 7188 <= ep['min_offset'] <= ep['max_offset'] <= 7191
    view = guard.router_status(SN_DES3, now=t + 60)
    assert (view['clock_state'], view['episodes_24h']) == ('ok', 1)


def test_late_stream_neither_opens_nor_closes_episode(guard):
    held_offset(guard, 'A', BASE, -500, duration=300)
    assert guard.snapshot(now=BASE + 300)['episodes'] == []

    classify_at(guard, 'B', BASE, 300)
    held_offset(guard, 'B', BASE + 10, -500, duration=300)
    assert guard.router_status('B', now=BASE + 320)['episode'] is not None


def test_episode_closes_on_silence(guard, caplog):
    caplog.set_level(logging.WARNING, logger=cg.logger.name)
    classify_at(guard, SN_DES3, BASE, 300)
    classify_at(guard, SN_DES3, BASE + 10, 300)
    last = BASE + 10
    guard.tick(last + 600)                                # ровно 10 мин — ещё открыт
    assert guard.router_status(SN_DES3, now=last + 600)['episode'] is not None
    guard.tick(last + 601)
    assert guard.router_status(SN_DES3, now=last + 601)['episode'] is None
    ep = guard.snapshot(now=last + 601)['episodes'][0]
    assert (ep['close_reason'], ep['open'], ep['end'], ep['count']) == ('silence', False, last, 2)
    assert len(guard_logs(caplog, CLOSE_MARK)) == 1
    guard.tick(last + 700)                                # повторный тик ничего не меняет
    assert len(guard_logs(caplog, CLOSE_MARK)) == 1
    assert len(guard.snapshot(now=last + 700)['episodes']) == 1


def test_episode_silence_close_configurable(make_guard):
    guard = make_guard(episode_silence_close_min=1)
    classify_at(guard, SN_DES3, BASE, 300)
    guard.tick(BASE + 60)
    assert guard.router_status(SN_DES3, now=BASE + 60)['episode'] is not None
    guard.tick(BASE + 61)
    assert guard.router_status(SN_DES3, now=BASE + 61)['episode'] is None


def test_episode_changed_when_status_or_k_changes(guard, caplog):
    caplog.set_level(logging.WARNING, logger=cg.logger.name)
    classify_at(guard, SN_DES3, BASE, 7200)                        # tz_shift k=2
    classify_at(guard, SN_DES3, BASE + 1, 3600)                    # tz_shift k=1
    classify_at(guard, SN_DES3, BASE + 2, 300)                     # future
    guard.classify(SN_DES3, '2026-10-09T13:00:03', BASE + 3)       # invalid
    episodes = guard.snapshot(now=BASE + 4)['episodes']            # новые первыми
    assert [(e['status'], e['k'], e['close_reason'], e['open']) for e in episodes] == [
        (TS_INVALID, None, None, True),
        (TS_FUTURE, None, 'changed', False),
        (TS_TZ_SHIFT, 1, 'changed', False),
        (TS_TZ_SHIFT, 2, 'changed', False),
    ]
    assert [e['action'] for e in episodes] == ['replaced', 'quarantined', 'flagged', 'flagged']
    assert len(guard_logs(caplog, OPEN_MARK)) == 4
    assert len(guard_logs(caplog, CLOSE_MARK)) == 3
    view = guard.router_status(SN_DES3, now=BASE + 4)
    assert (view['clock_state'], view['clock_label']) == ('invalid', 'метка неразборчива')


def test_alternating_mixed_batch_keeps_one_episode(guard):
    for j in range(20):
        stamp = ts(BASE + 7180 + j) if j % 2 == 0 else ts(BASE - 10 + j)
        guard.classify(SN_DES3, stamp, BASE + 0.02 * j)
    episodes = guard.snapshot(now=BASE + 1)['episodes']
    assert len(episodes) == 1
    assert episodes[0]['open'] and episodes[0]['count'] == 10


def test_episode_log_keeps_last_n(make_guard):
    guard = make_guard(episodes_keep=3)
    t = BASE
    for _ in range(5):
        classify_at(guard, SN_DES3, t, 300)
        classify_at(guard, SN_DES3, t + 1, -5)
        classify_at(guard, SN_DES3, t + 2, -5)
        t += 10
    episodes = guard.snapshot(now=t)['episodes']
    assert [e['id'] for e in episodes] == [5, 4, 3]


def test_episodes_24h_counter(guard):
    classify_at(guard, SN_DES3, BASE, 300)
    assert guard.router_status(SN_DES3, now=BASE + 3600)['episodes_24h'] == 1
    assert guard.router_status(SN_DES3, now=BASE + 86401)['episodes_24h'] == 0


@pytest.mark.parametrize('offset, state, label', [
    (-5, 'ok', 'в норме'),
    (7200, 'ahead', 'спешат на 2 ч'),
    (3 * 3600 + 30, 'ahead', 'спешат на 3 ч'),
    (300, 'future', 'спешат на 5 мин'),
])
def test_clock_labels(guard, offset, state, label):
    classify_at(guard, SN_DES3, BASE, offset)
    view = guard.router_status(SN_DES3, now=BASE)
    assert (view['clock_state'], view['clock_label']) == (state, label)


def test_router_status_unknown_router(guard):
    assert guard.router_status('nope', now=BASE) is None


# ============================================================
# Сигнал о молчании после tz_shift k>0
# ============================================================

def test_silence_signal_after_positive_shift(guard, caplog):
    caplog.set_level(logging.WARNING, logger=cg.logger.name)
    live_stream(guard, SN_DES3, BASE, 5)
    t0 = BASE + 50
    stamps = []
    for j in range(6):                                    # пачка ДЭС №3: 6 сообщений за 0,2 с
        stamp = ts(t0 + 7180 + j)
        stamps.append(stamp)
        assert guard.classify(SN_DES3, stamp, t0 + 0.04 * j).status == TS_TZ_SHIFT
    last = t0 + 0.04 * 5                                  # время приёма последней записи
    max_stamp = stamps[-1]

    guard.tick(last + 30)
    assert guard.router_status(SN_DES3, now=last + 30)['silence'] is None
    guard.tick(last + 60)                                 # ровно silence_alert_sec — ещё нет
    assert guard.router_status(SN_DES3, now=last + 60)['silence'] is None

    guard.tick(last + 61)
    view = guard.router_status(SN_DES3, now=last + 61)
    silence = view['silence']
    assert silence is not None and set(silence) == SILENCE_KEYS
    assert silence['since'] == last
    assert silence['k'] == 2
    assert silence['wait_until'] == epoch_of(max_stamp)  # эпоха максимальной «будущей» метки
    assert silence['wait_until_ts'] == max_stamp
    assert isinstance(silence['since_local'], str)
    assert max_stamp in silence['message']
    assert 'k=+2' in silence['message'] and 'перезапустите' in silence['message']
    assert (view['clock_state'], view['clock_label']) == ('silent', 'молчит после сдвига на +2 ч')
    assert len(guard_logs(caplog, SILENCE_MARK)) == 1

    guard.tick(last + 120)                                # сигнал поднимается один раз
    assert len(guard_logs(caplog, SILENCE_MARK)) == 1

    guard.tick(last + 601)                                # эпизод закрыт по молчанию, сигнал остаётся
    view = guard.router_status(SN_DES3, now=last + 601)
    assert view['episode'] is None and view['silence'] is not None
    assert guard.snapshot(now=last + 601)['episodes'][0]['close_reason'] == 'silence'

    # Новая запись снимает сигнал
    t2 = last + 7200
    assert classify_at(guard, SN_DES3, t2, -5)[1].status == TS_OK
    view = guard.router_status(SN_DES3, now=t2)
    assert view['silence'] is None and view['clock_state'] == 'ok'
    assert len(guard_logs(caplog, RESUME_MARK)) == 1
    guard.tick(t2 + 1000)
    assert guard.router_status(SN_DES3, now=t2 + 1000)['silence'] is None


def test_no_silence_signal_when_shift_was_long_ago(guard):
    classify_at(guard, SN_DES3, BASE, 7200)
    live_stream(guard, SN_DES3, BASE + 10, 40)            # 400 с нормы после сдвига
    last = BASE + 400
    guard.tick(last + 120)
    assert guard.router_status(SN_DES3, now=last + 120)['silence'] is None


@pytest.mark.parametrize('offset', [-5, 300, -1000])
def test_no_silence_signal_without_positive_shift(guard, offset):
    held_offset(guard, SN_DES3, BASE, offset, duration=100)
    guard.tick(BASE + 100 + 3600)
    assert guard.router_status(SN_DES3, now=BASE + 3700)['silence'] is None


def test_no_silence_signal_after_negative_shift(guard):
    rows = held_offset(guard, SN_DES3, BASE, -10800, duration=150)
    assert rows[-1][2].status == TS_TZ_SHIFT
    guard.tick(BASE + 150 + 120)
    assert guard.router_status(SN_DES3, now=BASE + 270)['silence'] is None


# ============================================================
# Счётчики
# ============================================================

def test_counters(make_guard):
    guard = make_guard(routers={'777': MODE_CORRECT})
    live_stream(guard, SN_DES3, BASE, 3)                          # ok ×3
    classify_at(guard, SN_DES3, BASE + 40, -500)                  # late
    classify_at(guard, SN_DES3, BASE + 41, 7200)                  # tz_shift (flag)
    classify_at(guard, '777', BASE + 42, 7200)                    # tz_shift → corrected
    classify_at(guard, SN_DES3, BASE + 43, 300)                   # future
    guard.classify(SN_DES3, '2026-10-09T13:00:00', BASE + 44)     # invalid → replaced
    assert guard.quarantine({'router_sn': SN_DES3}) is True       # quarantined
    counters = guard.get_counters()
    assert counters == {
        'ok': 3, 'late': 1, 'tz_shift': 2, 'future': 1, 'offset_jump': 0, 'invalid': 1,
        'total': 8, 'corrected': 1, 'quarantined': 1, 'replaced': 1, 'errors': 0,
    }
    counters['ok'] = 999                                          # копия, не состояние
    assert guard.get_counters()['ok'] == 3
    assert guard.snapshot(now=BASE + 50)['counters'] == guard.get_counters()


# ============================================================
# Режимы
# ============================================================

@pytest.mark.parametrize('routers', [
    {'123': 'correct'},
    {'123': {'mode': 'correct'}},
    {123: 'correct'},                       # ключ-число из YAML
    {123: {'mode': ' Correct '}},
])
def test_router_mode_override(make_guard, routers):
    guard = make_guard(mode=MODE_FLAG, routers=routers)
    assert guard.mode_for('123') == guard.mode_for(123) == MODE_CORRECT
    assert guard.mode_for('456') == MODE_FLAG
    stamp, v = classify_at(guard, 123, BASE, 7200)
    assert v.ts_status == TS_CORRECTED and v.timestamp == ts(epoch_of(stamp) - 7200)
    stamp, v = classify_at(guard, '456', BASE, 7200)
    assert v.ts_status == TS_TZ_SHIFT and v.timestamp == stamp
    snap = guard.snapshot(now=BASE)
    assert snap['router_modes'] == {'123': MODE_CORRECT}
    assert {r['router_sn']: r['mode'] for r in snap['routers']} == {'123': MODE_CORRECT,
                                                                   '456': MODE_FLAG}


def test_router_mode_override_to_flag(make_guard):
    guard = make_guard(mode=MODE_CORRECT, routers={SN_6003: {'mode': 'flag'}})
    assert classify_at(guard, SN_6003, BASE, 7200)[1].ts_status == TS_TZ_SHIFT
    assert classify_at(guard, SN_DES3, BASE, 7200)[1].ts_status == TS_CORRECTED


# ============================================================
# Конфигурация
# ============================================================

def test_config_defaults():
    for raw in (None, {}, {'mode': None, 'epsilon_sec': None, 'routers': None, 'quarantine': None}):
        cfg = ClockGuardConfig(raw)
        assert cfg.enabled is True
        assert cfg.mode == MODE_FLAG
        assert cfg.router_modes == {}
        assert cfg.epsilon_sec == DEFAULTS['epsilon_sec'] == 120
        assert cfg.late_sec == 60
        assert cfg.min_valid == datetime(2024, 1, 1, tzinfo=UTC)
        assert cfg.max_shift_hours == 14
        assert cfg.silence_close_sec == 600
        assert cfg.quarantine_file == DEFAULT_QUARANTINE['file']
        assert cfg.quarantine_topic_base == 'cg/v1/quarantine/SN'


def test_config_invalid_mode_falls_back_to_flag(make_guard, caplog):
    caplog.set_level(logging.WARNING, logger=cg.logger.name)
    guard = make_guard(mode='fix')
    assert guard.cfg.mode == MODE_FLAG
    assert any("'fix'" in r.getMessage() for r in guard_logs(caplog, 'clock_guard.mode'))
    stamp, v = classify_at(guard, SN_DES3, BASE, 7200)
    assert v.ts_status == TS_TZ_SHIFT and v.timestamp == stamp


def test_config_router_invalid_mode_falls_back_to_global(make_guard, caplog):
    caplog.set_level(logging.WARNING, logger=cg.logger.name)
    guard = make_guard(mode=MODE_CORRECT,
                       routers={'123': 'bogus', '456': {'mode': 'flag'}, '789': None, '999': {}})
    assert guard.cfg.router_modes == {'123': MODE_CORRECT, '456': MODE_FLAG}
    assert guard_logs(caplog, 'clock_guard.routers.123')


def test_config_routers_not_dict(make_guard, caplog):
    caplog.set_level(logging.WARNING, logger=cg.logger.name)
    guard = make_guard(routers=['123'])
    assert guard.cfg.router_modes == {}
    assert guard_logs(caplog, 'clock_guard.routers')


@pytest.mark.parametrize('value', [
    date(2025, 1, 1),                       # так YAML разбирает min_valid_date: 2025-01-01
    '2025-01-01',
    datetime(2025, 1, 1),
    datetime(2025, 1, 1, tzinfo=UTC),
], ids=['date', 'str', 'naive-datetime', 'aware-datetime'])
def test_config_min_valid_date_types(make_guard, value):
    guard = make_guard(min_valid_date=value)
    assert guard.cfg.min_valid == datetime(2025, 1, 1, tzinfo=UTC)
    assert guard.classify(SN_DES3, '2024-12-31T23:59:59+0000', BASE).status == TS_INVALID
    assert guard.classify(SN_DES3, '2025-01-01T00:00:00+0000', BASE + 1).status == TS_LATE


YAML_SECTION = '''
clock_guard:
  enabled: true
  mode: flag
  min_valid_date: 2025-01-01
  routers:
    123: correct
    "1126246373":
      mode: correct
    "6003790403":
  thresholds_note: ignored
'''


def test_config_from_yaml_document(make_guard):
    yaml = pytest.importorskip('yaml')
    section = yaml.safe_load(YAML_SECTION)['clock_guard']
    assert isinstance(section['min_valid_date'], date)
    assert 123 in section['routers']
    # Web UI перезаписывает config.yaml через safe_dump — после этого всё то же
    for raw in (section, yaml.safe_load(yaml.safe_dump(section, allow_unicode=True))):
        guard = make_guard(**raw)
        assert guard.cfg.router_modes == {'123': MODE_CORRECT, SN_DES3: MODE_CORRECT}
        assert guard.mode_for(SN_6003) == MODE_FLAG
        assert guard.cfg.min_valid == datetime(2025, 1, 1, tzinfo=UTC)
        assert guard.classify(SN_6003, '2024-12-31T23:59:59+0000', BASE).status == TS_INVALID
        assert classify_at(guard, 123, BASE + 1, 7200)[1].ts_status == TS_CORRECTED


def test_config_quarantine_null_keys_mean_default():
    """
    `file:` / `topic_base:` без значения в YAML — это null, то есть значение
    по умолчанию (как у остальных ключей); выключает только пустая строка "".
    """
    yaml = pytest.importorskip('yaml')
    section = yaml.safe_load('quarantine:\n  file:\n  topic_base:\n')
    assert section['quarantine'] == {'file': None, 'topic_base': None}
    cfg = ClockGuardConfig(section)
    assert cfg.quarantine_file == DEFAULT_QUARANTINE['file']
    assert cfg.quarantine_topic_base == 'cg/v1/quarantine/SN'

    off = ClockGuardConfig(yaml.safe_load('quarantine:\n  file: ""\n  topic_base: ""\n'))
    assert off.quarantine_file == '' and off.quarantine_topic_base == ''


def test_config_example_yaml_section():
    """Секция clock_guard из config.example.yaml разбирается и совпадает с DEFAULTS."""
    yaml = pytest.importorskip('yaml')
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'config.example.yaml')
    with open(path, encoding='utf-8') as f:
        section = yaml.safe_load(f)['clock_guard']
    assert set(section) == set(DEFAULTS)
    for key, value in DEFAULTS.items():
        if key != 'min_valid_date':
            assert section[key] == value, key
    cfg = ClockGuardConfig(section)
    assert cfg.min_valid == datetime(2024, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize('value, off', [
    (False, True), (0, True), ('false', True), (' Off ', True), ('no', True), ('нет', True),
    ('', True), (True, False), (1, False), ('yes', False), ('maybe', False), (None, False),
    ({}, False), ([], False),
])
def test_is_off_value(value, off):
    assert cg.is_off_value(value) is off


@pytest.mark.parametrize('enabled', [False, 0, 'false', ' False ', 'no', 'off', '0', 'нет'])
def test_disabled(make_guard, enabled):
    guard = make_guard(enabled=enabled)
    assert guard.enabled is False
    for value in (stamp_at(BASE, 7200), stamp_at(BASE, 300), 'garbage', None):
        assert guard.classify(SN_DES3, value, BASE) is None
    guard.tick(BASE + 10000)
    assert guard.get_counters()['total'] == 0
    snap = guard.snapshot(now=BASE)
    assert snap['enabled'] is False
    assert snap['routers'] == [] and snap['episodes'] == []
    assert guard.router_status(SN_DES3, now=BASE) is None


@pytest.mark.parametrize('enabled', [True, 1, 'true', 'Yes', 'on', '1', 'да'])
def test_enabled_values(make_guard, enabled):
    assert make_guard(enabled=enabled).enabled is True


def test_enabled_unknown_value_keeps_default(make_guard, caplog):
    caplog.set_level(logging.WARNING, logger=cg.logger.name)
    assert make_guard(enabled='maybe').enabled is True
    assert any('clock_guard.enabled' in r.getMessage() for r in caplog.records)


# ============================================================
# Отказоустойчивость
# ============================================================

def test_internal_error_returns_passthrough_ok(guard, monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger=cg.logger.name)

    def boom(*args, **kwargs):
        raise RuntimeError('boom')

    monkeypatch.setattr(guard, '_status_for', boom)
    stamp = stamp_at(BASE, 7200)
    v = guard.classify(SN_DES3, stamp, BASE)
    assert isinstance(v, TsVerdict)
    assert (v.status, v.ts_status, v.action) == (TS_OK, TS_OK, ACTION_PUBLISH)
    assert v.timestamp == stamp                           # как есть
    assert v.received_at == utc_iso_ms(BASE)
    assert v.payload_fields() == {'received_at': utc_iso_ms(BASE), 'ts_status': TS_OK,
                                  'ts_offset_sec': None}
    assert guard.classify(SN_DES3, stamp, BASE + 1).status == TS_OK
    counters = guard.get_counters()
    assert counters['errors'] == 2 and counters['total'] == 0
    assert len(guard_logs(caplog, 'Внутренняя ошибка', logging.ERROR)) == 1   # не чаще раза в минуту

    # Замок не остался захваченным: после устранения ошибки всё работает
    monkeypatch.undo()
    assert classify_at(guard, SN_DES3, BASE + 2, 7200)[1].status == TS_TZ_SHIFT


def test_bad_receive_time_does_not_raise(guard):
    stamp = stamp_at(BASE, -5)
    v = guard.classify(SN_DES3, stamp, 'not-a-number')
    assert (v.status, v.action, v.timestamp) == (TS_OK, ACTION_PUBLISH, stamp)
    assert guard.get_counters()['errors'] == 1


def test_tick_internal_error_is_counted(guard, monkeypatch):
    classify_at(guard, SN_DES3, BASE, -5)

    def boom(*args, **kwargs):
        raise RuntimeError('boom')

    monkeypatch.setattr(guard, '_tick_router', boom)
    guard.tick(BASE + 10)                                 # не пробрасывает
    assert guard.get_counters()['errors'] == 1


def test_quarantine_internal_error_is_counted(guard, monkeypatch):
    def boom(entry):
        raise OSError('disk full')

    monkeypatch.setattr(guard._quarantine, 'write', boom)
    assert guard.quarantine({'router_sn': SN_DES3}) is False
    counters = guard.get_counters()
    # Запись в decoded не ушла — она в карантине, хоть файл и не записан
    assert counters['errors'] == 1 and counters['quarantined'] == 1


def test_quarantine_real_file_error_is_counted(make_guard, tmp_path, capsys, caplog):
    """
    Настоящая ошибка файла, без подмены write(): RotatingFileHandler глотал
    её в handleError() — quarantine() возвращал True, errors оставался 0,
    а в stderr на каждую запись шла трассировка «--- Logging error ---».
    """
    caplog.set_level(logging.ERROR, logger=cg.logger.name)
    path = tmp_path / 'q.jsonl'
    path.mkdir()                                          # на месте файла каталог — не открыть
    guard = make_guard(quarantine={'file': str(path)})

    assert [guard.quarantine({'router_sn': SN_DES3, 'seq': i}) for i in range(3)] == [False] * 3
    counters = guard.get_counters()
    assert counters['quarantined'] == 3 and counters['errors'] == 3
    assert '--- Logging error ---' not in capsys.readouterr().err
    logs = guard_logs(caplog, 'Ошибка записи в файл карантина', logging.ERROR)
    assert len(logs) == 1                                 # не чаще раза в минуту
    assert str(path) in logs[0].getMessage()

    # Причина устранена — запись снова идёт в файл
    path.rmdir()
    assert guard.quarantine({'router_sn': SN_DES3, 'seq': 3}) is True
    guard.close()
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    assert [r['seq'] for r in rows] == [3]
    assert guard.get_counters()['errors'] == 3


def test_classify_without_receive_time_uses_wall_clock(guard):
    v = guard.classify(SN_DES3, datetime.now(MSK).strftime(TS_FORMAT))
    assert v.status == TS_OK
    assert abs(v.offset_sec) < 5


# ============================================================
# Поля decoded-сообщения
# ============================================================

def test_payload_fields_per_status(make_guard):
    flag = make_guard()
    correct = make_guard(mode=MODE_CORRECT)
    cases = {}
    cases['ok'] = classify_at(flag, 'A', BASE, -5)
    cases['late'] = classify_at(flag, 'A', BASE + 10, -500)
    cases['future'] = classify_at(flag, 'B', BASE, 300)
    cases['tz_shift+'] = classify_at(flag, 'C', BASE, 7200)
    cases['corrected'] = classify_at(correct, 'C', BASE, 7200)
    cases['tz_shift-'] = held_offset(flag, 'D', BASE, -10800, duration=120)[-1][1:]
    live_stream(flag, 'E', BASE, 20)
    cases['offset_jump'] = held_offset(flag, 'E', BASE + 200, -1000, duration=60)[-1][1:]
    invalid = '2000-01-01T03:00:00+0300'
    cases['invalid'] = (invalid, flag.classify('F', invalid, BASE))

    expected = {
        'ok': (TS_OK, BASE_KEYS), 'late': (TS_LATE, BASE_KEYS),
        'future': (TS_FUTURE, BASE_KEYS), 'offset_jump': (TS_OFFSET_JUMP, BASE_KEYS),
        'tz_shift+': (TS_TZ_SHIFT, SHIFT_KEYS), 'corrected': (TS_CORRECTED, SHIFT_KEYS),
        'tz_shift-': (TS_TZ_SHIFT, SHIFT_KEYS), 'invalid': (TS_INVALID, INVALID_KEYS),
    }
    for name, (stamp, v) in cases.items():
        ts_status, keys = expected[name]
        fields = v.payload_fields()
        assert set(fields) == keys, name
        assert fields['ts_status'] == ts_status, name
        assert RECEIVED_AT_RE.match(fields['received_at']), name
        if 'ts_original' in fields:
            assert fields['ts_original'] == stamp, name
        if name != 'invalid':
            assert fields['ts_offset_sec'] == pytest.approx(epoch_of(stamp) - _recv_of(v)), name
        json.dumps(fields)
    assert cases['tz_shift+'][1].payload_fields()['ts_shift_hours'] == 2
    assert cases['corrected'][1].payload_fields()['ts_shift_hours'] == 2
    assert cases['tz_shift-'][1].payload_fields()['ts_shift_hours'] == -3
    assert cases['invalid'][1].payload_fields()['ts_offset_sec'] is None


def _recv_of(verdict):
    return datetime.fromisoformat(verdict.received_at).timestamp()


# ============================================================
# Карантин
# ============================================================

def test_quarantine_writes_jsonl(guard):
    path = guard.cfg.quarantine_file
    stamp = stamp_at(BASE, 300)
    entry = {'router_sn': SN_DES3, 'device_type': 'PCC_3_3', 'bserver_id': 1,
             'timestamp': stamp, 'ts_status': TS_FUTURE, 'note': 'карантин: метка впереди',
             'when': datetime(2026, 10, 9, 13, 0, tzinfo=MSK)}
    assert guard.quarantine(entry) is True
    assert guard.quarantine({**entry, 'bserver_id': 2}) is True
    guard.close()
    assert guard.quarantine({**entry, 'bserver_id': 3}) is True     # после close файл открывается снова
    guard.close()
    guard.close()                                                    # повторный close безопасен

    with open(path, encoding='utf-8') as f:
        text = f.read()
    assert 'карантин: метка впереди' in text                         # utf-8, без \u-экранирования
    lines = text.splitlines()
    assert len(lines) == 3
    rows = [json.loads(line) for line in lines]
    assert [r['bserver_id'] for r in rows] == [1, 2, 3]
    assert rows[0]['timestamp'] == stamp
    assert rows[0]['when'] == str(entry['when'])                     # не-JSON — через str
    assert guard.get_counters()['quarantined'] == 3


def test_quarantine_rotates(make_guard):
    guard = make_guard(quarantine={'max_bytes': 400, 'backup_count': 2})
    path = guard.cfg.quarantine_file
    for seq in range(30):
        assert guard.quarantine({'seq': seq, 'router_sn': SN_DES3, 'pad': 'x' * 60}) is True
    guard.close()

    files = [path, path + '.1', path + '.2']
    assert all(os.path.exists(p) for p in files)
    assert not os.path.exists(path + '.3')
    seqs = []
    for p in reversed(files):                                        # от старых к новым
        assert os.path.getsize(p) <= 400
        with open(p, encoding='utf-8') as f:
            seqs += [json.loads(line)['seq'] for line in f.read().splitlines()]
    assert seqs == sorted(seqs) and seqs[-1] == 29
    assert len(seqs) < 30                                            # старые ушли с ротацией
    assert guard.get_counters()['quarantined'] == 30


def test_quarantine_file_disabled(make_guard):
    guard = make_guard(quarantine={'file': ''})
    assert guard.quarantine({'router_sn': SN_DES3}) is False
    # Файл выключен, но запись всё равно не опубликована в decoded — считается
    counters = guard.get_counters()
    assert counters['quarantined'] == 1 and counters['errors'] == 0


@pytest.mark.parametrize('max_bytes, backup_count', [(0, 5), (400, 0), (-1, -1)])
def test_quarantine_rotation_values_below_1_replaced(make_guard, caplog, max_bytes, backup_count):
    """0 в max_bytes или backup_count отключил бы ротацию: файл рос бы без предела."""
    caplog.set_level(logging.WARNING, logger=cg.logger.name)
    guard = make_guard(quarantine={'max_bytes': max_bytes, 'backup_count': backup_count})
    cfg = guard.cfg
    assert cfg.quarantine_max_bytes == (max_bytes if max_bytes > 0 else DEFAULT_QUARANTINE['max_bytes'])
    assert cfg.quarantine_backup_count == (backup_count if backup_count > 0 else 1)
    assert bool(guard_logs(caplog, 'clock_guard.quarantine.max_bytes')) == (max_bytes <= 0)
    assert bool(guard_logs(caplog, 'clock_guard.quarantine.backup_count')) == (backup_count <= 0)


def test_quarantine_backup_count_0_still_rotates(make_guard):
    guard = make_guard(quarantine={'max_bytes': 400, 'backup_count': 0})
    path = guard.cfg.quarantine_file
    for seq in range(30):
        assert guard.quarantine({'seq': seq, 'router_sn': SN_DES3, 'pad': 'x' * 60}) is True
    guard.close()
    assert os.path.getsize(path) <= 400
    assert os.path.exists(path + '.1') and not os.path.exists(path + '.2')


def test_quarantine_topic(make_guard):
    guard = make_guard()
    topic = guard.quarantine_topic(SN_DES3, 'PCC_3_3', 1)
    assert topic == f'cg/v1/quarantine/SN/{SN_DES3}/PCC_3_3/1'
    assert not topic.startswith('cg/v1/decoded')
    assert make_guard(quarantine={'topic_base': 'obs/q/'}).quarantine_topic('1', 'T', 2) == 'obs/q/1/T/2'
    assert make_guard(quarantine={'topic_base': ''}).quarantine_topic('1', 'T', 2) is None


# ============================================================
# Сброс и снимок состояния
# ============================================================

def test_reset_clears_state_keeps_counters(guard):
    live_stream(guard, 'A', BASE, 3)
    classify_at(guard, 'A', BASE + 30, 300)                # эпизод future
    classify_at(guard, 'A', BASE + 40, -5)
    classify_at(guard, 'A', BASE + 50, -5)                 # закрыт
    classify_at(guard, 'B', BASE, 7200)                    # открыт
    guard.tick(BASE + 100)                                 # у B сигнал о молчании
    assert guard.router_status('B', now=BASE + 100)['silence'] is not None
    counters = guard.get_counters()

    assert guard.reset() == {'routers': 2, 'episodes': 2}
    snap = guard.snapshot(now=BASE + 100)
    assert snap['routers'] == [] and snap['episodes'] == []
    assert snap['counters'] == counters                    # счётчики остаются
    assert guard.router_status('A', now=BASE + 100) is None
    assert guard.router_status('B', now=BASE + 100) is None

    # После сброса всё работает с чистого листа
    assert classify_at(guard, 'B', BASE + 200, 7200)[1].status == TS_TZ_SHIFT
    view = guard.router_status('B', now=BASE + 200)
    assert view['silence'] is None and view['episode']['count'] == 1
    assert guard.reset() == {'routers': 1, 'episodes': 1}


def test_reset_logs_end_of_open_episodes(guard, caplog):
    caplog.set_level(logging.WARNING, logger=cg.logger.name)
    classify_at(guard, 'A', BASE, 7200)                    # открыт tz_shift
    classify_at(guard, 'B', BASE, 300)                     # открыт future
    classify_at(guard, 'C', BASE, -5)                      # без эпизода
    assert len(guard_logs(caplog, OPEN_MARK)) == 2
    assert guard_logs(caplog, CLOSE_MARK) == []

    assert guard.reset() == {'routers': 3, 'episodes': 2}
    closes = guard_logs(caplog, CLOSE_MARK)
    assert len(closes) == 2                                # у каждого эпизода есть и конец
    assert all('(сброс)' in r.getMessage() for r in closes)
    snap = guard.snapshot(now=BASE + 10)
    assert snap['routers'] == [] and snap['episodes'] == []


def test_snapshot_structure(make_guard):
    guard = make_guard(mode=MODE_CORRECT, routers={'222': 'flag'})
    live_stream(guard, '333', BASE, 3)
    classify_at(guard, '222', BASE, 7200)                  # открыт (flag)
    classify_at(guard, '111', BASE + 1, 300)               # future
    classify_at(guard, '111', BASE + 2, -5)
    classify_at(guard, '111', BASE + 3, -5)                # future закрыт
    classify_at(guard, '111', BASE + 4, 7200)              # открыт (correct)
    snap = guard.snapshot(now=BASE + 10)

    assert set(snap) == {'enabled', 'mode', 'router_modes', 'counters', 'routers', 'episodes'}
    assert snap['enabled'] is True and snap['mode'] == MODE_CORRECT
    assert snap['router_modes'] == {'222': MODE_FLAG}
    assert snap['counters'] == guard.get_counters()

    routers = snap['routers']
    assert [r['router_sn'] for r in routers] == ['111', '222', '333']
    for r in routers:
        assert set(r) == ROUTER_VIEW_KEYS
    assert [r['mode'] for r in routers] == [MODE_CORRECT, MODE_FLAG, MODE_CORRECT]
    assert [r['clock_state'] for r in routers] == ['ahead', 'ahead', 'ok']
    assert set(routers[0]['episode']) == EPISODE_VIEW_KEYS and routers[2]['episode'] is None
    assert routers[0]['last_ts'] == stamp_at(BASE + 4, 7200)
    assert routers[0]['last_offset_sec'] == 7200.0
    assert routers[0]['last_recv'] == BASE + 4 and isinstance(routers[0]['last_recv_local'], str)

    episodes = snap['episodes']
    for e in episodes:
        assert set(e) == EPISODE_VIEW_KEYS
    assert [e['start'] for e in episodes] == [BASE + 4, BASE + 1, BASE]      # новые первыми
    assert [(e['router_sn'], e['status'], e['open'], e['action']) for e in episodes] == [
        ('111', TS_TZ_SHIFT, True, 'corrected'),
        ('111', TS_FUTURE, False, 'quarantined'),
        ('222', TS_TZ_SHIFT, True, 'flagged'),
    ]
    assert episodes[0]['end'] is None and episodes[0]['end_local'] is None
    assert episodes[1]['close_reason'] == 'normal' and isinstance(episodes[1]['end_local'], str)
    json.dumps(snap, ensure_ascii=False)                    # для /api


# ============================================================
# Глобальный экземпляр
# ============================================================

def test_global_init_and_get(monkeypatch, tmp_path):
    monkeypatch.setattr(cg, '_clock_guard', None)
    assert get_clock_guard() is None
    first = init_clock_guard({'quarantine': {'file': str(tmp_path / 'a.jsonl')}})
    assert get_clock_guard() is first
    assert first.quarantine({'a': 1}) is True               # файл открыт
    second = init_clock_guard({'mode': 'correct', 'quarantine': {'file': str(tmp_path / 'b.jsonl')}})
    try:
        assert get_clock_guard() is second and second is not first
        assert second.cfg.mode == MODE_CORRECT
        assert first._quarantine._handler is None           # прежний экземпляр закрыт
    finally:
        second.close()


# ============================================================
# Потокобезопасность
# ============================================================

def test_thread_safety_smoke(guard):
    errors = []
    stop = threading.Event()
    offsets = (-5, 7200, 300, -1000, -10800, -8)

    def producer(idx):
        try:
            sn = f'R{idx % 2}'                              # по два потока на роутер
            for i in range(400):
                t = BASE + i * 0.5 + idx * 0.01
                stamp = 'garbage' if i % 17 == 0 else stamp_at(t, offsets[i % len(offsets)])
                v = guard.classify(sn, stamp, t)
                assert v is not None and v.received_at
                if v.action == ACTION_QUARANTINE:
                    guard.quarantine({'router_sn': sn, 'timestamp': stamp})
        except Exception as e:      # noqa: BLE001 — собрать для проверки
            errors.append(e)

    def observer():
        try:
            now = BASE
            while not stop.is_set():
                now += 50
                guard.tick(now)
                json.dumps(guard.snapshot(now=now))
                guard.router_status('R0', now=now)
                guard.get_counters()
        except Exception as e:      # noqa: BLE001
            errors.append(e)

    watchers = [threading.Thread(target=observer) for _ in range(2)]
    workers = [threading.Thread(target=producer, args=(i,)) for i in range(4)]
    for th in watchers + workers:
        th.start()
    for th in workers:
        th.join(timeout=60)
    stop.set()
    for th in watchers:
        th.join(timeout=60)

    assert errors == []
    assert not any(th.is_alive() for th in watchers + workers)
    counters = guard.get_counters()
    assert counters['total'] == 1600
    assert counters['errors'] == 0
    assert sum(counters[s] for s in cg.ALL_STATUSES) == 1600
    assert counters['quarantined'] == counters['future']
