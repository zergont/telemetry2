# Copyright (c) 2026 ООО «НГ-ЭНЕРГОСЕРВИС». Все права защищены.
# Программный комплекс «Честная Генерация»
# Модуль декодирования Modbus-телеметрии
# Автор: Саввиди Александр Анатольевич | ИНН 4725009270
#
# Данное программное обеспечение является конфиденциальным.
# Несанкционированное копирование, распространение или использование
# без письменного разрешения правообладателя запрещено.

"""
Тесты инструмента приёмки tools/replay_clock_guard.py (реплей из history).

Синтетическая выгрузка history в tmp_path: живой поток, эпизод +2 ч,
залежалые пачки, строки пульса db-writer, дубли «строка на регистр»,
метки в форматах psql ('+03'), ISO ('+03:00') и роутера ('+0300').
tools — не пакет, поэтому модуль грузится через spec_from_file_location.
"""

import csv
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOL_PATH = REPO / 'tools' / 'replay_clock_guard.py'


def _load_tool():
    name = 'replay_clock_guard'
    module = sys.modules.get(name)
    if module is not None and getattr(module, '__file__', None) == str(TOOL_PATH):
        return module
    spec = importlib.util.spec_from_file_location(name, TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()

MSK = timezone(timedelta(hours=3))
BASE = datetime(2026, 10, 1, 12, 0, 0, tzinfo=MSK).timestamp()

SN_DES3 = '1126246373'
SN_B = '6003790403'
SN_C = '7000000001'
STYLES = ('pg', 'iso', 'router')


def ts_str(epoch: float, style: str = 'pg') -> str:
    """Метка как в выгрузке: psql '+03', ISO '+03:00' или роутер '+0300'."""
    dt = datetime.fromtimestamp(epoch, MSK)
    text = dt.strftime('%Y-%m-%d %H:%M:%S')
    if dt.microsecond:
        text += ('.' + f'{dt.microsecond:06d}').rstrip('0')
    if style == 'pg':
        return text + '+03'
    text = text.replace(' ', 'T')
    if style == 'iso':
        return text + '+03:00'
    return text + '+0300'


class History:
    """Построитель синтетической выгрузки history."""

    def __init__(self):
        self.rows = []

    def add(self, sn, panel, stamp, recv, copies=1, recv_style='pg'):
        recv_text = ts_str(recv, recv_style) if isinstance(recv, float) else recv
        for _ in range(copies):
            self.rows.append({'router_sn': sn, 'bserver_id': panel,
                              'timestamp': stamp, 'received_at': recv_text})

    def write_csv(self, path: Path) -> Path:
        with open(path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['router_sn', 'bserver_id',
                                                   'timestamp', 'received_at'])
            writer.writeheader()
            writer.writerows(self.rows)
        return path


# ДЭС №3: в history строка на регистр — каждая запись повторена 3 раза
DES3_COPIES = 3
SHIFT_OFFSETS = [7134, 7150, 7176, 7160, 7142, 7171, 7139, 7165, 7155, 7148]
STALE_OFFSET = -52919


def build_main_history() -> History:
    h = History()
    n = 0

    def des3(t, offset_int):
        nonlocal n
        recv = BASE + t + 0.25
        stamp = ts_str(BASE + t + offset_int, STYLES[n % 3])
        n += 1
        h.add(SN_DES3, '1', stamp, recv, copies=DES3_COPIES)

    # Живой поток ДЭС №3, offset ≈ −15 с
    for t in range(0, 600, 10):
        des3(t, -15)
    # Эпизод +2 ч: offset 7134..7176 с, одиночная пачка в каждом сообщении
    for i, t in enumerate(range(600, 700, 10)):
        des3(t, SHIFT_OFFSETS[i])
    for t in range(700, 1000, 10):
        des3(t, -15)
    # Залежалая пачка −52 919 с: 3 записи за 0,4 с, 2 метки (одна — по двум панелям)
    stale = BASE + 1000 + STALE_OFFSET
    h.add(SN_DES3, '1', ts_str(stale, 'pg'), BASE + 1000.25, copies=DES3_COPIES)
    h.add(SN_DES3, '2', ts_str(stale, 'pg'), BASE + 1000.45, copies=DES3_COPIES)
    h.add(SN_DES3, '1', ts_str(stale + 10, 'pg'), BASE + 1000.65, copies=DES3_COPIES)
    for t in range(1010, 1210, 10):
        des3(t, -15)

    # 6003790403: 2 панели, 2 метки на сообщение, только ok; одна залежалая
    # пачка ровно −3 ч − 30 с (кандидат tz_shift k<0 без подтверждения — late)
    for t in range(0, 1200, 10):
        recv = BASE + t + 0.5
        for panel in ('1', '2'):
            h.add(SN_B, panel, ts_str(BASE + t - 6, 'pg'), recv)
            h.add(SN_B, panel, ts_str(BASE + t - 5, 'pg'), recv)
        if t == 800:
            h.add(SN_B, '1', ts_str(BASE + t - 3 * 3600 - 30, 'pg'), BASE + t + 0.7)
            h.add(SN_B, '2', ts_str(BASE + t - 3 * 3600 - 29, 'pg'), BASE + t + 0.8)

    # Третий роутер: неразборчивая метка → invalid
    for t in range(0, 100, 10):
        h.add(SN_C, '1', ts_str(BASE + t - 3, 'iso'), BASE + t + 0.1)
    h.add(SN_C, '1', 'garbage', BASE + 105.1)

    # Пульс db-writer: доли секунды в метке и offset ≈ 0 (−3 мс)
    for t in range(30, 1200, 60):
        recv = BASE + t + 0.125
        h.add(SN_DES3, '1', ts_str(recv - 0.003, 'pg'), recv)
    return h


HEARTBEAT_ROWS = len(range(30, 1200, 60))
DES3_RECORDS = 60 + 10 + 30 + 3 + 20
B_RECORDS = 120 * 4 + 2
C_RECORDS = 11


def read_out(path: Path):
    with open(path, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def run_result(argv):
    return tool.run(tool.build_parser().parse_args(argv))


@pytest.fixture
def history_csv(tmp_path):
    return build_main_history().write_csv(tmp_path / 'history.csv')


# ------------------------------------------------------------
# Разбор меток
# ------------------------------------------------------------

@pytest.mark.parametrize('text', [
    '2026-10-09 15:20:28+03',
    '2026-10-09T15:20:28+03:00',
    '2026-10-09T15:20:28+0300',
    '2026-10-09 15:20:28 +03',
    '2026-10-09T12:20:28Z',
    '2026-10-09T12:20:28+00',
])
def test_parse_stamp_formats(text):
    dt, has_frac, problem = tool.parse_stamp(text)
    assert problem is None
    assert not has_frac
    assert dt == datetime(2026, 10, 9, 12, 20, 28, tzinfo=timezone.utc)


def test_parse_stamp_fraction_naive_and_garbage():
    dt, has_frac, problem = tool.parse_stamp('2026-10-09 15:20:28.123456+03')
    assert problem is None and has_frac and dt.microsecond == 123456

    assert tool.parse_stamp('2026-10-09T15:20:28') == (None, False, 'naive')
    assert tool.parse_stamp('garbage')[2] == 'unparsed'
    assert tool.parse_stamp('')[2] == 'empty'
    assert tool.parse_stamp(None)[2] == 'empty'

    msk = tool.parse_tz_arg('+03')
    dt, _, problem = tool.parse_stamp('2026-10-09 15:20:28', msk)
    assert problem is None and dt.utcoffset() == timedelta(hours=3)


def test_parse_recv_epoch_and_router_stamp():
    epoch = datetime(2026, 10, 9, 12, 20, 28, tzinfo=timezone.utc).timestamp()
    assert tool.parse_recv(epoch) == (epoch, None)
    assert tool.parse_recv(str(epoch)) == (epoch, None)
    assert tool.parse_recv('2026-10-09 15:20:28+03') == (epoch, None)
    assert tool.parse_recv('2026-10-09 15:20:28')[0] is None

    dt, _, _ = tool.parse_stamp('2026-10-09 15:20:28+03')
    assert tool.router_stamp(dt) == '2026-10-09T15:20:28+0300'


@pytest.mark.parametrize('value', [
    1757289600123, '1757289600123', 1757289600123.5,     # epoch в миллисекундах
    -1.0, float('nan'), float('inf'), '9999-12-31 23:59:59+00',
])
def test_parse_recv_rejects_out_of_range_epoch(value):
    """Миллисекунды и даты вне 1970..2286 роняли реплей на снимке (fromtimestamp)."""
    assert tool.parse_recv(value) == (None, 'range')


# ------------------------------------------------------------
# Реплей
# ------------------------------------------------------------

def test_replay_main_report_and_out(history_csv, tmp_path, capsys):
    out_csv = tmp_path / 'out' / 'replay.csv'
    rc = tool.main([str(history_csv), '--out', str(out_csv)])
    assert rc == 0
    stdout = capsys.readouterr().out

    # Пульс исключён, дубли объединены
    assert f'исключено строк пульса db-writer: {HEARTBEAT_ROWS}' in stdout
    assert f'объединено дублей: {DES3_RECORDS * (DES3_COPIES - 1)} строк' in stdout
    assert f'Записей в реплее: {DES3_RECORDS + B_RECORDS + C_RECORDS}' in stdout

    # Приёмка: эпизод +2 ч, исправленный offset в норме
    assert 'tz_shift k>0: записей 10 (строк 30); k=+2: 10' in stdout
    assert 'вне [-120; 0]: 0 записей' in stdout
    assert 'Залежалые пачки late' in stdout

    # --out: по строке на запись, без пульса
    rows = read_out(out_csv)
    assert len(rows) == DES3_RECORDS + B_RECORDS + C_RECORDS
    assert set(rows[0]) == set(tool.OUT_COLUMNS)
    assert not any('.' in r['timestamp'] for r in rows), 'строки пульса не исключены'

    des3 = [r for r in rows if r['router_sn'] == SN_DES3]
    assert len(des3) == DES3_RECORDS
    assert all(r['rows'] == str(DES3_COPIES) for r in des3)

    shifted = [r for r in des3 if r['status'] == 'tz_shift']
    assert len(shifted) == 10
    for r in shifted:
        assert r['shift_hours'] == '2'
        assert r['ts_status'] == 'tz_shift'          # режим flag: только флаг
        assert r['timestamp_out'] == r['timestamp']
        corrected = float(r['corrected_offset_sec'])
        assert -120 <= corrected <= 0
        dt = datetime.fromisoformat(r['timestamp'])
        assert datetime.fromisoformat(r['ts_corrected']) == dt - timedelta(hours=2)
        assert r['episode_id']
    corrected = sorted(float(r['corrected_offset_sec']) for r in shifted)
    assert corrected[0] == pytest.approx(min(SHIFT_OFFSETS) - 7200 - 0.25)
    assert corrected[-1] == pytest.approx(max(SHIFT_OFFSETS) - 7200 - 0.25)

    late = [r for r in des3 if r['status'] == 'late']
    assert len(late) == 3
    assert all(STALE_OFFSET - 1 <= float(r['offset_sec']) <= STALE_OFFSET + 10
               for r in late)
    assert {r['status'] for r in des3} == {'ok', 'tz_shift', 'late'}

    # 6003790403: только ok и late, панели не склеены
    b = [r for r in rows if r['router_sn'] == SN_B]
    assert len(b) == B_RECORDS
    assert {r['status'] for r in b} == {'ok', 'late'}
    assert sum(r['status'] == 'late' for r in b) == 2

    # '+03' (psql) и '+0300' / '+03:00' разобраны и поданы в формате роутера,
    # неразборчивая метка — invalid
    parsed = [r for r in rows if r['timestamp'] != 'garbage']
    assert all(r['note'] == '' for r in parsed)
    assert all(r['status'] != 'invalid' for r in parsed)
    assert all(r['timestamp'].endswith('+0300') for r in parsed)
    garbage = [r for r in rows if r['timestamp'] == 'garbage']
    assert len(garbage) == 1
    assert garbage[0]['status'] == 'invalid' and garbage[0]['note'] == 'unparsed'
    assert garbage[0]['timestamp_out']  # подставлено время приёма


def test_replay_structured_episodes_and_batches(history_csv):
    res = run_result([str(history_csv)])

    episodes = [e for e in res.episodes if e['router_sn'] == SN_DES3]
    assert len(episodes) == 1
    ep = episodes[0]
    assert ep['status'] == 'tz_shift' and ep['k'] == 2
    assert ep['count'] == 10
    assert ep['close_reason'] == 'normal'
    assert ep['start'] == pytest.approx(BASE + 600.25)
    assert ep['end'] == pytest.approx(BASE + 690.25)
    lo, hi = res.episode_corrected[ep['id']]
    assert -120 <= lo <= hi <= 0

    # Ни offset_jump, ни tz_shift k<0 у живых роутеров
    for sn in (SN_DES3, SN_B):
        counts = res.recs_by_router[sn]
        assert counts['offset_jump'] == 0
        assert counts['future'] == 0
        assert counts['invalid'] == 0
    assert res.recs_by_router[SN_DES3]['tz_shift'] == 10
    assert res.rows_by_router[SN_DES3]['tz_shift'] == 10 * DES3_COPIES
    assert res.recs_by_router[SN_C]['invalid'] == 1

    batches = {b['router_sn']: b for b in res.late_batches}
    assert set(batches) == {SN_DES3, SN_B}
    assert len(res.late_batches) == 2
    des3_batch = batches[SN_DES3]
    assert des3_batch['records'] == 3
    assert des3_batch['rows'] == 3 * DES3_COPIES
    assert len(des3_batch['stamps']) == 2
    assert des3_batch['max_offset'] < -52000
    assert batches[SN_B]['records'] == 2
    assert batches[SN_B]['max_offset'] == pytest.approx(-3 * 3600 - 29.5, abs=1)

    assert res.silences == []


def test_no_dedupe_keeps_every_row(history_csv, tmp_path, capsys):
    out_csv = tmp_path / 'replay_nodedupe.csv'
    assert tool.main([str(history_csv), '--no-dedupe', '--out', str(out_csv)]) == 0
    stdout = capsys.readouterr().out
    assert 'дубли не объединяются (--no-dedupe)' in stdout
    rows = read_out(out_csv)
    assert len(rows) == DES3_RECORDS * DES3_COPIES + B_RECORDS + C_RECORDS
    shifted = [r for r in rows if r['status'] == 'tz_shift']
    assert len(shifted) == 10 * DES3_COPIES
    assert all(r['shift_hours'] == '2' for r in shifted)


def test_keep_heartbeat(history_csv, tmp_path, capsys):
    out_csv = tmp_path / 'replay_hb.csv'
    assert tool.main([str(history_csv), '--keep-heartbeat', '--out', str(out_csv)]) == 0
    rows = read_out(out_csv)
    assert sum('.' in r['timestamp'] for r in rows) == HEARTBEAT_ROWS


def test_correct_mode_rewrites_timestamp(history_csv, tmp_path, capsys):
    out_csv = tmp_path / 'replay_correct.csv'
    assert tool.main([str(history_csv), '--mode', 'correct', '--out', str(out_csv)]) == 0
    stdout = capsys.readouterr().out
    assert 'Режим: correct' in stdout
    shifted = [r for r in read_out(out_csv) if r['status'] == 'tz_shift']
    assert len(shifted) == 10
    for r in shifted:
        assert r['ts_status'] == 'corrected'
        assert r['timestamp_out'] == r['ts_corrected'] != r['timestamp']


def test_config_section_and_mode_override(history_csv, tmp_path):
    config = tmp_path / 'config.yaml'
    config.write_text(
        'clock_guard:\n'
        '  enabled: false\n'
        '  mode: flag\n'
        '  routers:\n'
        f'    "{SN_DES3}": correct\n'
        '  quarantine:\n'
        '    file: should_not_be_written.jsonl\n',
        encoding='utf-8')
    res = run_result([str(history_csv), '--config', str(config)])
    assert res.mode == 'flag'
    assert res.router_modes == {SN_DES3: 'correct'}
    assert res.recs_by_router[SN_DES3]['corrected'] == 10
    assert any('enabled: false' in note for note in res.notes)
    assert res.guard_cfg['quarantine']['file'] == ''
    assert not (tmp_path / 'should_not_be_written.jsonl').exists()

    res = run_result([str(history_csv), '--config', str(config), '--mode', 'flag'])
    assert res.router_modes == {}
    assert res.recs_by_router[SN_DES3]['corrected'] == 0


def test_silence_after_shift_closes_episode_by_tick(tmp_path, capsys):
    """+2 ч, затем 2 ч молчания: эпизод закрыт тиком по молчанию, сигнал поднят."""
    h = History()
    for t in range(0, 300, 10):
        h.add(SN_DES3, '1', ts_str(BASE + t - 12), BASE + t + 0.5)
    for t in range(300, 330, 10):
        h.add(SN_DES3, '1', ts_str(BASE + t + 7180), BASE + t + 0.5)
    resume = 330 + 2 * 3600
    for t in range(resume, resume + 60, 10):
        h.add(SN_DES3, '1', ts_str(BASE + t - 12), BASE + t + 0.5)
    path = h.write_csv(tmp_path / 'silence.csv')

    res = run_result([str(path)])
    assert len(res.episodes) == 1
    ep = res.episodes[0]
    assert ep['status'] == 'tz_shift' and ep['k'] == 2 and ep['count'] == 3
    assert ep['close_reason'] == 'silence'
    assert ep['end'] == pytest.approx(BASE + 320.5)

    assert len(res.silences) == 1
    silence = res.silences[0]
    assert silence['router_sn'] == SN_DES3 and silence['k'] == 2
    assert silence['since'] == pytest.approx(BASE + 320.5)
    # Сигнал — на первом тике после silence_alert_sec (60 с), а не при возобновлении
    assert BASE + 380.5 < silence['detected'] <= BASE + 385.5
    assert silence['resumed'] == pytest.approx(BASE + resume + 0.5)
    assert silence['wait_until_ts'] == ts_str(BASE + 320 + 7180, 'router')
    # Долгая пауза не прошагивается тиками по 5 с
    assert res.ticks < 200

    assert tool.main([str(path)]) == 0
    stdout = capsys.readouterr().out
    assert 'Молчание после tz_shift k>0' in stdout
    assert 'молчание' in stdout


def test_jsonl_input_and_custom_columns(tmp_path):
    path = tmp_path / 'history.jsonl'
    with open(path, 'w', encoding='utf-8') as f:
        for t in range(0, 200, 10):
            f.write(json.dumps({'sn': int(SN_DES3), 'ts': ts_str(BASE + t - 10, 'router'),
                                'ins': BASE + t + 0.5}) + '\n')
        f.write(json.dumps({'sn': int(SN_DES3), 'ts': ts_str(BASE + 205 + 7170, 'router'),
                            'ins': BASE + 205.5}) + '\n')
        f.write('not json\n')
    res = run_result([str(path), '--col-router', 'sn', '--col-ts', 'ts', '--col-recv', 'ins'])
    assert res.load.format == 'jsonl'
    assert res.load.stats['bad_lines'] == 1
    assert len(res.records) == 21
    assert res.recs_by_router[SN_DES3]['ok'] == 20
    assert res.recs_by_router[SN_DES3]['tz_shift'] == 1


def test_missing_column_returns_error(history_csv, capsys):
    rc = tool.main([str(history_csv), '--col-ts', 'date_iso'])
    assert rc == 2
    assert 'date_iso' in capsys.readouterr().err


@pytest.mark.parametrize('text, expected', [
    ('clock_guard:\n  epsilon_sec: abc\n', "'abc'"),
    ('clock_guard:\n  min_valid_date: garbage\n', 'garbage'),
    ('clock_guard:\n  quarantine:\n    max_bytes: 10MB\n', '10MB'),
    ('clock_guard:\n  min_valid_date: 2024-13-01\n', 'ошибка разбора'),   # ValueError в YAML
    ('clock_guard:\n  quarantine: off\n  late_sec: x\n', "'x'"),
], ids=['epsilon', 'date', 'max_bytes', 'yaml-date', 'quarantine-scalar'])
def test_bad_config_fails_before_reading_export(tmp_path, capsys, monkeypatch, text, expected):
    """Ошибка в clock_guard — [ОШИБКА] и код 2 сразу, до загрузки выгрузки."""
    config = tmp_path / 'config.yaml'
    config.write_text(text, encoding='utf-8')
    loaded = []
    monkeypatch.setattr(tool, 'load_records', lambda args: loaded.append(args))
    rc = tool.main([str(tmp_path / 'history.csv'), '--config', str(config)])
    assert rc == 2
    err = capsys.readouterr().err
    assert err.startswith('[ОШИБКА]') and expected in err
    assert 'Traceback' not in err
    assert loaded == []


def test_config_short_form_disabled(history_csv, tmp_path):
    """clock_guard: false (как в декодере) — для реплея модуль всё равно включён."""
    config = tmp_path / 'config.yaml'
    config.write_text('clock_guard: false\n', encoding='utf-8')
    res = run_result([str(history_csv), '--config', str(config)])
    assert any('enabled: false' in note for note in res.notes)
    assert res.recs_by_router[SN_DES3]['tz_shift'] == 10


def _long_history_csv(tmp_path) -> Path:
    h = History()
    for t in range(0, 30000, 10):
        h.add(SN_DES3, '1', ts_str(BASE + t - 10), BASE + t + 0.5)
    return h.write_csv(tmp_path / 'long.csv')


@pytest.mark.parametrize('case', ['truncated-gz', 'not-gz', 'bad-utf8'])
def test_unreadable_export_returns_error(tmp_path, capsys, case):
    """Обрыв gzip, не gzip, не UTF-8 — [ОШИБКА] и код 2, а не трассировка."""
    import gzip
    plain = _long_history_csv(tmp_path).read_bytes()
    if case == 'truncated-gz':
        data = gzip.compress(plain)
        path = tmp_path / 'trunc.csv.gz'
        path.write_bytes(data[:len(data) // 2])
    elif case == 'not-gz':
        path = tmp_path / 'plain.csv.gz'
        path.write_bytes(plain)
    else:
        path = tmp_path / 'badenc.csv'
        path.write_bytes(plain + f'{SN_DES3},1,'.encode() + b'\xff\xfe,x\r\n')
    rc = tool.main([str(path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert err.startswith('[ОШИБКА]') and 'ошибка чтения' in err and str(path) in err
    assert 'Traceback' not in err


def test_epoch_milliseconds_skipped_with_hint(tmp_path, capsys):
    path = tmp_path / 'ms.jsonl'
    with open(path, 'w', encoding='utf-8') as f:
        for t in range(0, 100, 10):
            f.write(json.dumps({'router_sn': SN_DES3, 'timestamp': ts_str(BASE + t - 10, 'router'),
                                'received_at': int((BASE + t) * 1000)}) + '\n')
        f.write(json.dumps({'router_sn': SN_DES3, 'timestamp': ts_str(BASE + 190, 'router'),
                            'received_at': BASE + 200.5}) + '\n')        # секунды — принимается
    res = run_result([str(path)])
    assert len(res.records) == 1
    assert len(res.load.bad_recv) == 10
    assert all(r.note == 'range' for r in res.load.bad_recv)

    assert tool.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert 'пропущено строк без разобранного received_at: 10' in out
    assert 'вне диапазона 1970..2286' in out


def test_router_filter(history_csv):
    res = run_result([str(history_csv), '--router', SN_B])
    assert set(res.recs_by_router) == {SN_B}
    assert res.load.stats['filtered'] > 0


def test_gzip_input_and_naive_tz(tmp_path):
    """Выгрузка без пояса (timestamp without time zone) в .gz: нужен --naive-tz."""
    import gzip
    path = tmp_path / 'history_naive.csv.gz'
    with gzip.open(path, 'wt', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['router_sn', 'bserver_id', 'timestamp', 'received_at'])
        for t in range(0, 100, 10):
            writer.writerow([SN_DES3, '1', ts_str(BASE + t - 10)[:-3],
                             ts_str(BASE + t + 0.5)[:-3]])

    res = run_result([str(path)])
    assert res.records == []
    assert len(res.load.bad_recv) == 10

    res = run_result([str(path), '--naive-tz', '+03:00'])
    assert len(res.records) == 10
    assert res.recs_by_router[SN_DES3]['ok'] == 10
    assert all(r.offset == pytest.approx(-10.5) for r in res.records)


def test_future_goes_to_quarantine_file(tmp_path):
    h = History()
    for t in range(0, 100, 10):
        h.add(SN_DES3, '1', ts_str(BASE + t - 10), BASE + t + 0.5)
    h.add(SN_DES3, '1', ts_str(BASE + 100 + 300), BASE + 100.5)   # +5 мин — future
    path = h.write_csv(tmp_path / 'future.csv')
    quarantine = tmp_path / 'q' / 'quarantine.jsonl'

    res = run_result([str(path), '--quarantine-file', str(quarantine)])
    assert res.recs_by_router[SN_DES3]['future'] == 1
    assert res.recs_by_router[SN_DES3]['quarantined'] == 1
    lines = quarantine.read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry['router_sn'] == SN_DES3 and entry['ts_status'] == 'future'
