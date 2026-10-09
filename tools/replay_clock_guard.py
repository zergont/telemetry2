# Copyright (c) 2026 ООО «НГ-ЭНЕРГОСЕРВИС». Все права защищены.
# Программный комплекс «Честная Генерация»
# Модуль декодирования Modbus-телеметрии
# Автор: Саввиди Александр Анатольевич | ИНН 4725009270
#
# Данное программное обеспечение является конфиденциальным.
# Несанкционированное копирование, распространение или использование
# без письменного разрешения правообладателя запрещено.

r"""
Реплей контроля метки времени (clock_guard) по выгрузке history db-writer

Приёмка задачи «контроль метки времени в cg-decoder» (§7): реплей делается
из history. Метка записи — decoded 'timestamp', время приёма — received_at
(время вставки строки, DEFAULT now()). Каждая запись подаётся в свежий
ClockGuard с t_recv = received_at в порядке received_at. Тик монитора
состояния (раз в 5 с) имитируется, в том числе в паузах приёма, поэтому
эпизоды закрываются по молчанию и сигнал о молчании публикатора поднимается
в то же время, что и в декодере.

ВЫГРУЗИТЬ ДАННЫЕ НУЖНО СЕЙЧАС: history хранится 30 дней, эпизоды
07.09–09.10 скоро уйдут по сроку хранения. Сырые MQTT-пакеты нигде не
хранятся — другого источника для реплея нет.

Пример выгрузки (имена таблицы и колонок в <...> заменить на фактические;
\copy пишется одной строкой; ORDER BY по received_at и id сохраняет порядок
вставки внутри одной секунды):

    psql -h <db_host> -U <db_user> -d <db_name> -c "\copy (SELECT <sn_col> AS router_sn, <panel_col> AS bserver_id, <ts_col> AS timestamp, received_at FROM <history_table> WHERE received_at >= now() - interval '31 days' ORDER BY received_at, <id_col>) TO 'history_ts.csv' WITH (FORMAT csv, HEADER)"

    gzip history_ts.csv        # необязательно: файл .gz читается напрямую

Метки из timestamptz выгружаются в поясе сессии psql ('2026-10-09 15:20:28+03');
понимаются также '2026-10-09T15:20:28+03:00' и формат роутера
'2026-10-09T15:20:28+0300'. Неразобранные метки подаются как есть и
получают invalid, как в декодере.

Что делает реплей:
  - исключает строки пульса db-writer (миллисекунды в метке и offset ≈ 0);
  - объединяет дубли (строка на регистр): одна запись на
    (router_sn, bserver_id, timestamp, received_at) — отключается --no-dedupe;
  - считает статусы по роутерам (записи и строки истории), строит таблицу
    эпизодов, для tz_shift k>0 — диапазон offset после исправления
    (offset − k·3600), список залежалых пачек late и случаи молчания
    публикатора после tz_shift k>0;
  - по --out пишет CSV со статусом, k, offset и исправленной меткой
    по каждой записи.

Использование:
    python tools/replay_clock_guard.py history_ts.csv.gz --config config.yaml
    python tools/replay_clock_guard.py history_ts.csv --mode correct --out replay.csv
    python tools/replay_clock_guard.py history.jsonl --format jsonl --router 1126246373 -v
"""

import argparse
import csv
import gzip
import hashlib
import heapq
import json
import logging
import math
import re
import sys
import zlib
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from operator import attrgetter
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import clock_guard as cg  # noqa: E402

# Норма после исправления tz_shift k>0 (приёмка §7)
ACCEPT_CORRECTED_MIN = -120.0
ACCEPT_CORRECTED_MAX = 0.0

# Поля счётчиков по роутеру: статусы классификации + что сделано с записью
COUNTER_FIELDS = cg.ALL_STATUSES + ('corrected', 'quarantined', 'replaced')

# received_at — UTC ISO с миллисекундами (как в decoded); timestamp — метка,
# поданная в ClockGuard (формат роутера; неразобранная — исходный текст);
# timestamp_out — что декодер поставил бы в timestamp; rows — строк истории
OUT_COLUMNS = (
    'router_sn', 'bserver_id', 'received_at', 'timestamp',
    'status', 'ts_status', 'action', 'offset_sec', 'shift_hours',
    'corrected_offset_sec', 'ts_corrected', 'timestamp_out', 'episode_id',
    'rows', 'note',
)

CLOSE_REASON_TEXT = {
    'normal': 'метки в норме',
    'silence': 'молчание',
    'changed': 'смена статуса',
    'reset': 'сброс',
    None: 'открыт',
}

ACTION_TEXT = {
    cg.EP_ACTION_FLAGGED: 'флаг',
    cg.EP_ACTION_CORRECTED: 'исправление',
    cg.EP_ACTION_QUARANTINED: 'карантин',
    cg.EP_ACTION_REPLACED: 'время приёма',
}

STAMP_PROBLEM_TEXT = {
    'empty': 'пустая',
    'naive': 'без пояса',
    'unparsed': 'не разобрана',
}


class ReplayError(Exception):
    """Ошибка входных данных или параметров (код выхода 2)."""


# Ошибки чтения выгрузки: обрыв gzip (EOFError), не gzip (BadGzipFile — OSError),
# повреждённый поток (zlib.error), не UTF-8, битый CSV
_READ_ERRORS = (OSError, EOFError, zlib.error, UnicodeDecodeError, csv.Error)


# ============================================================
# Разбор меток
# ============================================================

# 2026-10-09 15:20:28+03 | 2026-10-09T15:20:28.123+03:00 | 2026-10-09T15:20:28+0300 | ...Z
_STAMP_RE = re.compile(
    r'^(?P<date>\d{4}-\d{2}-\d{2})[T ]+(?P<time>\d{2}:\d{2}(?::\d{2})?)(?P<frac>[.,]\d+)?'
    r'\s*(?P<tz>[Zz]|UTC|GMT|[+-]\d{1,2}(?::?\d{2}){0,2})?$')
_EPOCH_RE = re.compile(r'^\d{9,}(?:\.\d+)?$')
# Допустимый received_at, секунды epoch: 1970-01-01 .. 2286-11-20. Больше —
# скорее миллисекунды; такие значения (и даты до 1970) datetime.fromtimestamp
# на Windows не принимает — реплей упал бы на снимке состояния
_EPOCH_MIN = 0.0
_EPOCH_MAX = 1e10


def _norm_tz(tz: str) -> Optional[str]:
    """'+03' / '+0300' / '+03:00' / 'Z' → '+03:00' (None — не разобрать)."""
    if tz in ('Z', 'z', 'UTC', 'GMT'):
        return '+00:00'
    if not tz or tz[0] not in '+-':
        return None
    sign, digits = tz[0], tz[1:].replace(':', '')
    if not digits.isdigit():
        return None
    if len(digits) in (1, 2):
        hh, mm, ss = digits.zfill(2), '00', '00'
    elif len(digits) == 4:
        hh, mm, ss = digits[:2], digits[2:], '00'
    elif len(digits) == 6:
        hh, mm, ss = digits[:2], digits[2:4], digits[4:]
    else:
        return None
    if int(hh) > 23 or int(mm) > 59 or int(ss) > 59:
        return None
    return f"{sign}{hh}:{mm}" + (f":{ss}" if ss != '00' else '')


def parse_tz_arg(value: str):
    """Значение --naive-tz: '+03:00', '+03', 'UTC' или 'local'."""
    s = (value or '').strip()
    if s.lower() == 'local':
        return 'local'
    iso = _norm_tz(s.upper() if s.upper() in ('UTC', 'GMT', 'Z') else s)
    if iso is None:
        raise argparse.ArgumentTypeError(
            f"не понял пояс '{value}': нужно +03:00, +03, UTC или local")
    sign = -1 if iso[0] == '-' else 1
    delta = timedelta(hours=int(iso[1:3]), minutes=int(iso[4:6]),
                      seconds=int(iso[7:9]) if len(iso) > 6 else 0)
    return timezone(sign * delta)


def parse_stamp(value: Any, naive_tz=None) -> Tuple[Optional[datetime], bool, Optional[str]]:
    """
    Разбор метки из выгрузки.

    Возвращает (aware datetime | None, есть ли доли секунды, проблема), где
    проблема — None, 'empty', 'naive' (нет пояса и не задан naive_tz) или
    'unparsed'.
    """
    if value is None:
        return None, False, 'empty'
    s = str(value).strip()
    if not s:
        return None, False, 'empty'
    return _parse_stamp_cached(s, naive_tz)


@lru_cache(maxsize=1 << 16)
def _parse_stamp_cached(s: str, naive_tz) -> Tuple[Optional[datetime], bool, Optional[str]]:
    m = _STAMP_RE.match(s)
    if m:
        frac = (m.group('frac') or '').replace(',', '.')
        has_frac = bool(frac)
        tz = m.group('tz')
        tz_iso = ''
        if tz:
            tz_iso = _norm_tz(tz)
            if tz_iso is None:
                return None, has_frac, 'unparsed'
        try:
            dt = datetime.fromisoformat(f"{m.group('date')}T{m.group('time')}{frac}{tz_iso}")
        except ValueError:
            return None, has_frac, 'unparsed'
    else:
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None, False, 'unparsed'
        has_frac = dt.microsecond != 0
    if dt.tzinfo is None or dt.utcoffset() is None:
        if naive_tz is None:
            return None, has_frac, 'naive'
        dt = dt.astimezone() if naive_tz == 'local' else dt.replace(tzinfo=naive_tz)
    return dt, has_frac, None


def parse_recv(value: Any, naive_tz=None) -> Tuple[Optional[float], Optional[str]]:
    """
    received_at → epoch (или None и проблема). Понимает и число секунд epoch.
    Проблема 'range' — вне 1970..2286 (например, epoch в миллисекундах).
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        epoch = float(value)
    else:
        s = '' if value is None else str(value).strip()
        if _EPOCH_RE.match(s):
            epoch = float(s)
        else:
            dt, _, problem = parse_stamp(s, naive_tz)
            if dt is None:
                return None, problem
            epoch = dt.timestamp()
    if not _EPOCH_MIN <= epoch < _EPOCH_MAX:      # и NaN
        return None, 'range'
    return epoch, None


def router_stamp(dt: datetime) -> str:
    """Метка для подачи в ClockGuard: формат роутера, доли секунды — ISO."""
    if dt.microsecond:
        return dt.isoformat()
    return cg.format_router_ts(dt)


# ============================================================
# Чтение выгрузки
# ============================================================

class Rec:
    """
    Запись реплея (после объединения дублей) и её результат.

    Исходные строки выгрузки не хранятся (память: выгрузка — миллионы строк):
    stamp — метка в формате роутера, как она подаётся в ClockGuard, а для
    неразобранной метки — исходный текст.
    """
    __slots__ = ('sn', 'panel', 'stamp', 'note', 'recv', 'rows',
                 'status', 'ts_status', 'action', 'offset', 'k', 'ts_out', 'ts_corr',
                 'ep_id')

    def __init__(self, sn: str, panel: str):
        self.sn = sn
        self.panel = panel
        self.stamp: Optional[str] = None
        self.note: str = ''
        self.recv: Optional[float] = None
        self.rows = 1
        self.status: Optional[str] = None
        self.ts_status: Optional[str] = None
        self.action: Optional[str] = None
        self.offset: Optional[float] = None
        self.k: Optional[int] = None
        self.ts_out: Optional[str] = None
        self.ts_corr: Optional[str] = None
        self.ep_id: Optional[int] = None

    @property
    def corrected_offset(self) -> Optional[float]:
        if self.status == cg.TS_TZ_SHIFT and self.k and self.k > 0 and self.offset is not None:
            return self.offset - self.k * 3600
        return None


def _cell(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _open_text(path: str):
    if path.lower().endswith('.gz'):
        return gzip.open(path, 'rt', encoding='utf-8-sig', newline='')
    return open(path, 'r', encoding='utf-8-sig', newline='')


def _detect_format(path: str, fmt: str) -> str:
    if fmt != 'auto':
        return fmt
    name = path.lower()
    if name.endswith('.gz'):
        name = name[:-3]
    return 'jsonl' if name.endswith(('.jsonl', '.ndjson', '.json')) else 'csv'


def _iter_jsonl(f, stats: Counter) -> Iterator[dict]:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            stats['bad_lines'] += 1
            continue
        if isinstance(obj, dict):
            yield obj
        else:
            stats['bad_lines'] += 1


class LoadResult:
    def __init__(self):
        self.stats: Counter = Counter()
        self.records: List[Rec] = []
        self.heartbeat: List[Rec] = []
        self.bad_recv: List[Rec] = []
        self.columns: Dict[str, Optional[str]] = {}
        self.format = 'csv'


def load_records(args) -> LoadResult:
    """Прочитать выгрузку, отбросить пульс и строки без received_at, объединить дубли."""
    res = LoadResult()
    stats = res.stats
    path = str(args.input)
    fmt = _detect_format(path, args.format)
    res.format = fmt
    naive_tz = args.naive_tz
    router_filter = {str(sn).strip() for sn in (args.router or [])}

    col_router, col_ts, col_recv = args.col_router, args.col_ts, args.col_recv
    panel_explicit = args.col_panel is not None and args.col_panel not in ('', '-')
    if args.col_panel in ('', '-'):
        col_panel = None
    else:
        col_panel = args.col_panel or 'bserver_id'
    key_cols = list(args.key_col or [])

    try:
        f = _open_text(path)
    except OSError as e:
        raise ReplayError(f"не удалось открыть {path}: {e}")

    try:
        with f:
            if fmt == 'csv':
                reader = csv.DictReader(f, delimiter=args.delimiter)
                fields = [name.strip() for name in (reader.fieldnames or [])]
                reader.fieldnames = fields
                if not fields:
                    raise ReplayError(f"{path}: пустой файл или нет строки заголовка")
                required = [col_router, col_ts, col_recv] + key_cols
                if panel_explicit:
                    required.append(col_panel)
                missing = [c for c in required if c not in fields]
                if missing:
                    raise ReplayError(
                        f"{path}: нет колонок {', '.join(missing)} (есть: {', '.join(fields)}); "
                        f"укажите --col-router / --col-ts / --col-recv / --col-panel")
                if col_panel and col_panel not in fields:
                    col_panel = None
                rows: Iterable[dict] = reader
            else:
                rows = _iter_jsonl(f, stats)

            res.columns = {'router': col_router, 'ts': col_ts, 'recv': col_recv,
                           'panel': col_panel}
            seen: Dict[bytes, Rec] = {}
            hb_max = float(args.heartbeat_max_offset)
            drop_heartbeat = not args.keep_heartbeat

            for row in rows:
                stats['rows'] += 1
                sn = _cell(row.get(col_router))
                if not sn:
                    stats['no_router'] += 1
                    continue
                if router_filter and sn not in router_filter:
                    stats['filtered'] += 1
                    continue
                panel = _cell(row.get(col_panel)) if col_panel else ''
                ts_raw = _cell(row.get(col_ts))
                recv_raw = row.get(col_recv)
                recv_key = _cell(recv_raw)

                if not args.no_dedupe:
                    key = _dedupe_key([sn, panel, ts_raw, recv_key]
                                      + [_cell(row.get(c)) for c in key_cols])
                    rec = seen.get(key)
                    if rec is not None:
                        rec.rows += 1
                        stats['dup_rows'] += 1
                        continue

                rec = Rec(sys.intern(sn), sys.intern(panel))
                if not args.no_dedupe:
                    seen[key] = rec

                recv, recv_problem = parse_recv(
                    recv_raw if not isinstance(recv_raw, str) else recv_key, naive_tz)
                dt, has_frac, problem = parse_stamp(ts_raw, naive_tz)
                if recv is None:
                    # note у пропущенных записей — проблема received_at (для отчёта)
                    rec.note = recv_problem or ''
                    res.bad_recv.append(rec)
                    continue
                rec.recv = recv
                if (drop_heartbeat and dt is not None and has_frac
                        and abs(dt.timestamp() - recv) <= hb_max):
                    res.heartbeat.append(rec)
                    continue
                if dt is not None:
                    rec.stamp = router_stamp(dt)
                else:
                    # Подаётся как есть — ClockGuard поставит invalid, как в декодере
                    rec.stamp = ts_raw
                    rec.note = problem or ''
                res.records.append(rec)
            seen.clear()
    except _READ_ERRORS as e:
        # Обрыв gzip, не gzip, не UTF-8, битый CSV — сообщение вместо трассировки
        raise ReplayError(f"{path}: ошибка чтения (прочитано строк данных: "
                          f"{stats['rows']}): {e}")

    # Порядок приёма; внутри одной received_at — порядок файла (стабильная сортировка)
    res.records.sort(key=attrgetter('recv'))
    return res


def _dedupe_key(parts: List[str]) -> bytes:
    """
    Компактный ключ дубля: 128-битный blake2b вместо кортежа строк —
    иначе на миллионах строк словарь держит все исходные тексты меток.
    """
    return hashlib.blake2b('\x1f'.join(parts).encode('utf-8'), digest_size=16).digest()


# ============================================================
# Конфиг ClockGuard для реплея
# ============================================================

def build_guard_config(args) -> Tuple[dict, List[str]]:
    """Секция clock_guard из --config (или значения по умолчанию) + переопределения реплея."""
    notes: List[str] = []
    raw: dict = {}
    if args.config:
        try:
            import yaml
        except ImportError:
            raise ReplayError("для --config нужен pyyaml (pip install pyyaml)")
        try:
            with open(args.config, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
        except OSError as e:
            raise ReplayError(f"не удалось прочитать {args.config}: {e}")
        except (yaml.YAMLError, ValueError) as e:
            # ValueError — например, невозможная дата 2024-13-01 в YAML
            raise ReplayError(f"ошибка разбора {args.config}: {e}")
        section = data.get('clock_guard') if isinstance(data, dict) else None
        if section is None:
            notes.append(f"в {args.config} нет секции clock_guard — значения по умолчанию")
        elif cg.is_off_value(section):
            # clock_guard: false — короткая форма выключения (как в декодере)
            raw = {'enabled': False}
        elif not isinstance(section, dict):
            raise ReplayError(f"{args.config}: clock_guard должен быть словарём")
        else:
            raw = dict(section)
    if 'enabled' in raw and cg.is_off_value(raw['enabled']):
        notes.append("clock_guard.enabled: false в конфиге — для реплея модуль включён")
    raw['enabled'] = True
    if args.mode:
        if raw.get('routers'):
            notes.append(f"--mode {args.mode}: переопределения routers из конфига отброшены")
        raw['mode'] = args.mode
        raw['routers'] = {}
    q_raw = raw.get('quarantine')
    quarantine = dict(q_raw) if isinstance(q_raw, dict) else {}
    quarantine['file'] = args.quarantine_file or ''
    quarantine['topic_base'] = ''
    raw['quarantine'] = quarantine
    # Журнал эпизодов не обрезаем: нужен весь период выгрузки
    try:
        keep = int(raw.get('episodes_keep') or 0)
    except (TypeError, ValueError):
        keep = 0
    raw['episodes_keep'] = max(keep, 1_000_000)

    # Проверка значений до чтения выгрузки: иначе ошибка в конфиге всплыла бы
    # трассировкой только после загрузки миллионов строк. Предупреждения
    # модуля здесь не нужны — они будут при создании ClockGuard в run()
    where = args.config or 'значения по умолчанию'
    old_level = cg.logger.level
    cg.logger.setLevel(logging.ERROR)
    try:
        cg.ClockGuardConfig(raw)
    except (ValueError, TypeError, OverflowError) as e:
        raise ReplayError(f"ошибка в секции clock_guard ({where}): {e}")
    finally:
        cg.logger.setLevel(old_level)
    return raw, notes


# ============================================================
# Реплей
# ============================================================

class _ReplayClock:
    now: Optional[float] = None


class _ReplayFormatter(logging.Formatter):
    """WARNING clock_guard с временем реплея вместо настенного."""

    def __init__(self, clock: _ReplayClock):
        super().__init__()
        self.clock = clock

    def format(self, record: logging.LogRecord) -> str:
        when = _lt(self.clock.now) if self.clock.now is not None else '-'
        return f"  [{when}] {record.levelname}: {record.getMessage()}"


class ReplayResult:
    def __init__(self):
        self.load: Optional[LoadResult] = None
        self.records: List[Rec] = []
        self.guard_cfg: dict = {}
        self.notes: List[str] = []
        self.mode = cg.MODE_FLAG
        self.router_modes: Dict[str, str] = {}
        self.recs_by_router: Dict[str, Counter] = defaultdict(Counter)
        self.rows_by_router: Dict[str, Counter] = defaultdict(Counter)
        self.episodes: List[dict] = []
        self.episode_corrected: Dict[int, Tuple[float, float]] = {}
        self.late_batches: List[dict] = []
        self.silences: List[dict] = []
        self.router_views: List[dict] = []
        self.counters: Dict[str, int] = {}
        self.ticks = 0
        self.t_first: Optional[float] = None
        self.t_last: Optional[float] = None


class Replayer:
    """Подаёт записи в ClockGuard по received_at и имитирует тик монитора."""

    def __init__(self, guard: cg.ClockGuard, tick_sec: float = 5.0,
                 batch_window: float = 1.0, write_quarantine: bool = False,
                 clock: Optional[_ReplayClock] = None):
        self.guard = guard
        self.step = float(tick_sec)
        self.batch_window = float(batch_window)
        self.write_quarantine = write_quarantine
        self.clock = clock or _ReplayClock()
        # Пороги тика, после которых меняется состояние роутера
        self.thresholds = (guard.cfg.silence_alert_sec, guard.cfg.silence_close_sec)
        self.last_tick: Optional[float] = None
        self.router_last: Dict[str, float] = {}
        self.events: List[Tuple[float, str, float]] = []
        self.ticks = 0
        self.late_open: Dict[str, dict] = {}
        self.late_batches: List[dict] = []
        self.silence_open: Dict[str, dict] = {}
        self.silences: List[dict] = []

    # ------------------------------------------------------------
    # Тик монитора состояния
    # ------------------------------------------------------------

    def _grid_after(self, t: float) -> float:
        """Первый тик строго после t (тики — на кратных step секундах epoch)."""
        return (math.floor(t / self.step) + 1) * self.step

    def advance(self, t: float):
        """
        Тики до момента t включительно.

        Состояние ClockGuard между записями меняет только tick(), а его
        эффект зависит лишь от того, перешло ли молчание роутера порог
        (silence_alert_sec, episode_silence_close_min). Поэтому в паузе
        достаточно тиков на первой отметке сетки после каждого порога
        плюс последнего тика перед записью — это то же, что тикать
        каждые 5 с, но без сотен тысяч пустых вызовов в долгих паузах.
        """
        g_last = math.floor(t / self.step) * self.step
        if self.last_tick is None:
            self.last_tick = g_last
            return
        if g_last <= self.last_tick:
            return
        ticks = {g_last}
        checks: Dict[float, set] = defaultdict(set)
        while self.events and self.events[0][0] <= g_last:
            g, sn, r = heapq.heappop(self.events)
            if self.router_last.get(sn) == r:
                ticks.add(g)
                checks[g].add(sn)
        for g in sorted(ticks):
            self.clock.now = g
            self.guard.tick(now=g)
            self.ticks += 1
            for sn in sorted(checks.get(g, ())):
                self._check_silence(sn, g)
        self.last_tick = g_last

    def _schedule(self, sn: str, t: float):
        for thr in self.thresholds:
            heapq.heappush(self.events, (self._grid_after(t + thr), sn, t))

    def _check_silence(self, sn: str, now: float):
        if sn in self.silence_open:
            return
        view = self.guard.router_status(sn, now=now)
        silence = view.get('silence') if view else None
        if not silence:
            return
        event = {
            'router_sn': sn,
            'since': silence.get('since'),
            'detected': now,
            'k': silence.get('k'),
            'wait_until': silence.get('wait_until'),
            'wait_until_ts': silence.get('wait_until_ts'),
            'resumed': None,
        }
        self.silence_open[sn] = event
        self.silences.append(event)

    # ------------------------------------------------------------
    # Записи
    # ------------------------------------------------------------

    def feed(self, rec: Rec):
        t = rec.recv
        self.advance(t)
        self.clock.now = t

        event = self.silence_open.pop(rec.sn, None)
        if event is not None:
            event['resumed'] = t

        verdict = self.guard.classify(rec.sn, rec.stamp, t)
        if verdict is None:  # модуль выключен — для реплея не бывает
            verdict = cg.passthrough_verdict(rec.stamp, t)
        rec.status = verdict.status
        rec.ts_status = verdict.ts_status
        rec.action = verdict.action
        rec.offset = verdict.offset_sec
        rec.k = verdict.shift_hours
        rec.ts_out = verdict.timestamp

        if rec.status == cg.TS_TZ_SHIFT and rec.k and rec.k > 0:
            dt = cg.parse_router_ts(rec.stamp)
            if dt is not None:
                rec.ts_corr = router_stamp(dt - timedelta(hours=rec.k))

        if rec.status in cg.EPISODE_STATUSES:
            view = self.guard.router_status(rec.sn, now=t)
            episode = view.get('episode') if view else None
            if episode is not None:
                rec.ep_id = episode['id']

        if verdict.action == cg.ACTION_QUARANTINE and self.write_quarantine:
            self.guard.quarantine({
                'source': 'replay_clock_guard',
                'router_sn': rec.sn,
                'bserver_id': rec.panel or None,
                'timestamp': rec.stamp,
                'received_at': verdict.received_at,
                'ts_status': verdict.ts_status,
                'ts_offset_sec': verdict.offset_sec,
                'rows': rec.rows,
            })

        self._track_late(rec, t)
        self.router_last[rec.sn] = t
        self._schedule(rec.sn, t)

    def _track_late(self, rec: Rec, t: float):
        if rec.status != cg.TS_LATE:
            return
        batch = self.late_open.get(rec.sn)
        if batch is not None and t - batch['t0'] <= self.batch_window:
            batch['t1'] = t
            batch['records'] += 1
            batch['rows'] += rec.rows
            batch['stamps'].add(rec.stamp)
            batch['min_offset'] = min(batch['min_offset'], rec.offset)
            batch['max_offset'] = max(batch['max_offset'], rec.offset)
            return
        batch = {'router_sn': rec.sn, 't0': t, 't1': t, 'records': 1, 'rows': rec.rows,
                 'stamps': {rec.stamp}, 'min_offset': rec.offset, 'max_offset': rec.offset}
        self.late_open[rec.sn] = batch
        self.late_batches.append(batch)


def run(args) -> ReplayResult:
    """Прочитать выгрузку, прогнать через ClockGuard, записать --out."""
    if args.tick_sec <= 0:
        raise ReplayError("--tick-sec должен быть больше 0")
    result = ReplayResult()
    guard_cfg, notes = build_guard_config(args)
    result.guard_cfg = guard_cfg
    result.notes = notes
    load = load_records(args)
    result.load = load
    result.records = load.records

    clock = _ReplayClock()
    cg_logger = cg.logger
    old_level, old_propagate = cg_logger.level, cg_logger.propagate
    handler: Optional[logging.Handler] = None
    if args.verbose:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_ReplayFormatter(clock))
        cg_logger.addHandler(handler)
        cg_logger.setLevel(logging.WARNING)
        cg_logger.propagate = False
    else:
        cg_logger.setLevel(logging.ERROR)

    guard = cg.ClockGuard(guard_cfg)
    try:
        result.mode = guard.cfg.mode
        result.router_modes = dict(guard.cfg.router_modes)
        replayer = Replayer(guard, tick_sec=args.tick_sec, batch_window=args.batch_window,
                            write_quarantine=bool(args.quarantine_file), clock=clock)
        if args.verbose and load.records:
            print("Журнал clock_guard (время реплея, местное):")
        for rec in load.records:
            replayer.feed(rec)

        if load.records:
            result.t_first = load.records[0].recv
            result.t_last = load.records[-1].recv
        now = result.t_last if result.t_last is not None else 0.0
        snap = guard.snapshot(now=now)
        result.counters = snap['counters']
        result.router_views = snap['routers']
        result.episodes = sorted(snap['episodes'], key=lambda e: (e['start'], e['id']))
        result.late_batches = replayer.late_batches
        result.silences = replayer.silences
        result.ticks = replayer.ticks
    finally:
        guard.close()
        if handler is not None:
            cg_logger.removeHandler(handler)
        cg_logger.setLevel(old_level)
        cg_logger.propagate = old_propagate

    for rec in load.records:
        recs = result.recs_by_router[rec.sn]
        rows = result.rows_by_router[rec.sn]
        extras = [rec.status]
        if rec.ts_status == cg.TS_CORRECTED:
            extras.append('corrected')
        if rec.action == cg.ACTION_QUARANTINE:
            extras.append('quarantined')
        if rec.status == cg.TS_INVALID:
            extras.append('replaced')
        for name in extras:
            recs[name] += 1
            rows[name] += rec.rows
        recs['total'] += 1
        rows['total'] += rec.rows
        corrected = rec.corrected_offset
        if corrected is not None and rec.ep_id is not None:
            lo, hi = result.episode_corrected.get(rec.ep_id, (corrected, corrected))
            result.episode_corrected[rec.ep_id] = (min(lo, corrected), max(hi, corrected))

    if args.out:
        write_out(args.out, load.records)
    return result


def write_out(path: str, records: List[Rec]):
    """CSV с результатом по каждой записи (в порядке реплея)."""
    try:
        out_path = Path(path)
        if out_path.parent and not out_path.parent.exists():
            out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(OUT_COLUMNS)
            for rec in records:
                corrected = rec.corrected_offset
                writer.writerow([
                    rec.sn, rec.panel, cg.utc_iso_ms(rec.recv), rec.stamp,
                    rec.status, rec.ts_status, rec.action,
                    _num(rec.offset), '' if rec.k is None else rec.k,
                    _num(corrected), rec.ts_corr or '', rec.ts_out or '',
                    '' if rec.ep_id is None else rec.ep_id, rec.rows, rec.note,
                ])
    except OSError as e:
        raise ReplayError(f"не удалось записать {path}: {e}")


# ============================================================
# Отчёт
# ============================================================

def _lt(epoch: Optional[float]) -> str:
    if epoch is None:
        return '-'
    return datetime.fromtimestamp(epoch).strftime('%Y-%m-%d %H:%M:%S')


def _num(value: Optional[float], digits: int = 3) -> str:
    if value is None:
        return ''
    text = f"{value:.{digits}f}".rstrip('0').rstrip('.')
    return '0' if text in ('-0', '') else text


def _off(value: Optional[float]) -> str:
    return '-' if value is None else f"{value:+.1f}"


def _range(lo: Optional[float], hi: Optional[float], fmt=_off) -> str:
    if lo is None and hi is None:
        return '-'
    lo_text, hi_text = fmt(lo), fmt(hi)
    return lo_text if lo_text == hi_text else f"{lo_text}..{hi_text}"


def _dur(sec: Optional[float]) -> str:
    if sec is None:
        return '-'
    sec = int(round(sec))
    if sec < 60:
        return f"{sec} с"
    minutes, s = divmod(sec, 60)
    if minutes < 60:
        return f"{minutes} мин {s:02d} с"
    hours, m = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} ч {m:02d} мин"
    days, h = divmod(hours, 24)
    return f"{days} сут {h:02d} ч"


def _table(headers: List[str], rows: List[List[Any]], out, limit: int = 0, indent: str = '  '):
    shown = rows if limit <= 0 else rows[:limit]
    cells = [[str(c) for c in row] for row in shown]
    widths = [len(h) for h in headers]
    for row in cells:
        for i, c in enumerate(row):
            widths[i] = max(widths[i], len(c))
    numeric = [all(_is_num(row[i]) for row in cells) and bool(cells) for i in range(len(headers))]

    def line(values):
        parts = [v.rjust(widths[i]) if numeric[i] else v.ljust(widths[i])
                 for i, v in enumerate(values)]
        return (indent + '  '.join(parts)).rstrip()

    print(line(headers), file=out)
    print(indent + '  '.join('-' * w for w in widths), file=out)
    for row in cells:
        print(line(row), file=out)
    if len(rows) > len(shown):
        print(f"{indent}... ещё {len(rows) - len(shown)} (показать все: --max-rows 0)", file=out)


def _is_num(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def print_report(res: ReplayResult, args, out=None):
    out = out or sys.stdout
    load = res.load
    st = load.stats
    limit = args.max_rows

    def p(text: str = ''):
        print(text, file=out)

    p('=' * 72)
    p('Реплей контроля метки времени (clock_guard)')
    p('=' * 72)
    cols = load.columns
    p(f"Файл: {args.input} ({load.format}); колонки: router={cols['router']}, "
      f"timestamp={cols['ts']}, received_at={cols['recv']}, панель={cols['panel'] or 'нет'}")
    p(f"Строк прочитано: {st['rows']}")
    hb_rows = sum(r.rows for r in load.heartbeat)
    recv_rows = sum(r.rows for r in load.bad_recv)
    if args.keep_heartbeat:
        p("  пульс db-writer не исключается (--keep-heartbeat)")
    else:
        p(f"  исключено строк пульса db-writer: {hb_rows} "
          f"(доли секунды в метке и |offset| <= {_num(args.heartbeat_max_offset)} с)")
    if recv_rows:
        hint = '' if args.naive_tz else '; если received_at выгружен без пояса — укажите --naive-tz'
        p(f"  пропущено строк без разобранного received_at: {recv_rows}{hint}")
        range_rows = sum(r.rows for r in load.bad_recv if r.note == 'range')
        if range_rows:
            p(f"    из них вне диапазона 1970..2286 (epoch в миллисекундах не поддерживается — "
              f"нужны секунды): {range_rows}")
    if st['no_router']:
        p(f"  пропущено строк без {cols['router']}: {st['no_router']}")
    if st['filtered']:
        p(f"  отброшено фильтром --router: {st['filtered']}")
    if st['bad_lines']:
        p(f"  неразобранных строк JSONL: {st['bad_lines']}")
    if args.no_dedupe:
        p("  дубли не объединяются (--no-dedupe)")
    else:
        key = ', '.join([cols['router']] + ([cols['panel']] if cols['panel'] else [])
                        + [cols['ts'], cols['recv']] + list(args.key_col or []))
        p(f"  объединено дублей: {st['dup_rows']} строк (ключ: {key})")
    bad_ts = Counter()
    for rec in res.records:
        if rec.note:
            bad_ts[rec.note] += 1
    if bad_ts:
        parts = ', '.join(f"{STAMP_PROBLEM_TEXT.get(k, k)} — {v}" for k, v in sorted(bad_ts.items()))
        p(f"  метка не разобрана (подана как есть, invalid): {parts}")
    p(f"Записей в реплее: {len(res.records)} (строк истории: {sum(r.rows for r in res.records)})")
    if res.t_first is not None:
        tz_name = datetime.now().astimezone().strftime('%z')
        p(f"Период по received_at: {_lt(res.t_first)} .. {_lt(res.t_last)} "
          f"(местное время, {tz_name}); тиков монитора: {res.ticks}")
    modes = ', '.join(f"{sn}: {m}" for sn, m in sorted(res.router_modes.items()))
    p(f"Режим: {res.mode}" + (f"; по роутерам: {modes}" if modes else ''))
    for note in res.notes:
        p(f"  {note}")
    if res.counters.get('errors'):
        p(f"  ВНИМАНИЕ: внутренних ошибок clock_guard: {res.counters['errors']} "
          f"(записи прошли как ok; подробности: --verbose)")

    if not res.records:
        p()
        p('Нет записей для реплея.')
        return

    # --- статусы по роутерам ---
    _print_counts(p, 'Статусы по роутерам (записи)', res.recs_by_router, out)
    if not args.no_dedupe and st['dup_rows']:
        _print_counts(p, 'То же в строках истории', res.rows_by_router, out)

    # --- состояние часов на конец выгрузки ---
    p()
    p('Состояние часов на конец выгрузки')
    rows = []
    for view in res.router_views:
        rows.append([view['router_sn'], view['mode'], view['clock_label'],
                     view['last_status'] or '-', _off(view['last_offset_sec']),
                     view['episodes_24h']])
    _table(['роутер', 'режим', 'часы', 'последний статус', 'offset, с', 'эпизодов за 24 ч'],
           rows, out, limit)

    # --- эпизоды ---
    p()
    p(f"Эпизоды: {len(res.episodes)}")
    if res.episodes:
        rows = []
        for i, ep in enumerate(res.episodes, 1):
            corrected = res.episode_corrected.get(ep['id'])
            rows.append([
                i, _lt(ep['start']), _lt(ep['end']) if ep['end'] is not None else 'открыт',
                ep['router_sn'], ep['status'], '-' if ep['k'] is None else f"{ep['k']:+d}",
                ep['count'], _range(ep['min_offset'], ep['max_offset']),
                _range(*corrected) if corrected else '-',
                ACTION_TEXT.get(ep['action'], ep['action']),
                _dur(ep['duration_sec']), CLOSE_REASON_TEXT.get(ep['close_reason'], ep['close_reason']),
            ])
        _table(['№', 'начало', 'конец', 'роутер', 'статус', 'k', 'записей', 'offset, с',
                'испр. offset, с', 'действие', 'длит.', 'закрыт'], rows, out, limit)

    # --- приёмка ---
    p()
    p('Приёмка')
    _print_shift_summary(p, res)
    _print_late_batches(p, res, args, out, limit)
    _print_silences(p, res, out, limit)


def _print_counts(p, title: str, by_router: Dict[str, Counter], out):
    p()
    p(title)
    headers = ['роутер', 'всего'] + list(COUNTER_FIELDS)
    rows = []
    total = Counter()
    for sn in sorted(by_router):
        c = by_router[sn]
        total.update(c)
        rows.append([sn, c['total']] + [c[name] for name in COUNTER_FIELDS])
    if len(by_router) > 1:
        rows.append(['ИТОГО', total['total']] + [total[name] for name in COUNTER_FIELDS])
    # Роутеров немного — показываем все, вместе с итогом
    _table(headers, rows, out)


def _print_shift_summary(p, res: ReplayResult):
    shifted = [r for r in res.records if r.corrected_offset is not None]
    if not shifted:
        p('  tz_shift k>0: нет')
    else:
        by_k = Counter(r.k for r in shifted)
        ks = ', '.join(f"k={k:+d}: {n}" for k, n in sorted(by_k.items()))
        p(f"  tz_shift k>0: записей {len(shifted)} (строк {sum(r.rows for r in shifted)}); {ks}")
        corrected = [r.corrected_offset for r in shifted]
        outside = [r for r in shifted
                   if not ACCEPT_CORRECTED_MIN <= r.corrected_offset <= ACCEPT_CORRECTED_MAX]
        p(f"    offset после исправления (offset - k*3600): от {min(corrected):+.1f} "
          f"до {max(corrected):+.1f} с; вне [{ACCEPT_CORRECTED_MIN:.0f}; "
          f"{ACCEPT_CORRECTED_MAX:.0f}]: {len(outside)} записей "
          f"({sum(r.rows for r in outside)} строк)")
        by_router: Dict[str, List[float]] = defaultdict(list)
        for r in shifted:
            by_router[r.sn].append(r.corrected_offset)
        if len(by_router) > 1:
            for sn in sorted(by_router):
                vals = by_router[sn]
                p(f"    {sn}: записей {len(vals)}, от {min(vals):+.1f} до {max(vals):+.1f} с")
    neg = [r for r in res.records if r.status == cg.TS_TZ_SHIFT and r.k is not None and r.k < 0]
    others = Counter(r.status for r in res.records
                     if r.status in (cg.TS_FUTURE, cg.TS_OFFSET_JUMP, cg.TS_INVALID))
    p(f"  tz_shift k<0: {len(neg)}; future: {others[cg.TS_FUTURE]}; "
      f"offset_jump: {others[cg.TS_OFFSET_JUMP]}; invalid: {others[cg.TS_INVALID]} (записей)")


def _print_late_batches(p, res: ReplayResult, args, out, limit: int):
    batches = res.late_batches
    p()
    p(f"  Залежалые пачки late (записи late одного роутера в пределах "
      f"{_num(args.batch_window)} с): {len(batches)}")
    if not batches:
        return
    per_router = Counter(b['router_sn'] for b in batches)
    p('    по роутерам: ' + ', '.join(f"{sn}: {n}" for sn, n in sorted(per_router.items())))
    rows = []
    for b in batches:
        rows.append([
            b['router_sn'], _lt(b['t0']), b['records'], b['rows'], len(b['stamps']),
            _range(b['min_offset'], b['max_offset']),
            _range(b['min_offset'] / 3600.0, b['max_offset'] / 3600.0,
                   fmt=lambda v: f"{v:+.2f}"),
        ])
    _table(['роутер', 'приём', 'записей', 'строк', 'меток', 'offset, с', 'offset, ч'],
           rows, out, limit, indent='    ')


def _print_silences(p, res: ReplayResult, out, limit: int):
    silences = res.silences
    p()
    p(f"  Молчание после tz_shift k>0 (сигнал «перезапустите сервис опроса»): {len(silences)}")
    if not silences:
        return
    rows = []
    for s in silences:
        resumed = s['resumed']
        pause = None if resumed is None else resumed - s['since']
        vs_wait = '-'
        if resumed is not None and s['wait_until'] is not None:
            vs_wait = f"{(resumed - s['wait_until']) / 60.0:+.0f}"
        rows.append([
            s['router_sn'], _lt(s['since']),
            _lt(resumed) if resumed is not None else 'до конца выгрузки',
            _dur(pause), f"{s['k']:+d}" if s['k'] is not None else '-',
            s['wait_until_ts'] or '-', vs_wait,
        ])
    _table(['роутер', 'молчит с', 'возобновил', 'пауза', 'k', 'ждёт до (метка роутера)',
            'возобн. - ждёт до, мин'], rows, out, limit, indent='    ')


# ============================================================
# CLI
# ============================================================

EPILOG = r"""
Пример выгрузки из history (имена в <...> — фактические; выгружать сейчас,
history хранится 30 дней):

  psql -h <db_host> -U <db_user> -d <db_name> -c "\copy (SELECT <sn_col> AS router_sn, <panel_col> AS bserver_id, <ts_col> AS timestamp, received_at FROM <history_table> WHERE received_at >= now() - interval '31 days' ORDER BY received_at, <id_col>) TO 'history_ts.csv' WITH (FORMAT csv, HEADER)"

Примеры:
  python tools/replay_clock_guard.py history_ts.csv --config config.yaml
  python tools/replay_clock_guard.py history_ts.csv.gz --mode correct --out replay.csv
  python tools/replay_clock_guard.py history_ts.csv --router 1126246373 --verbose
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='replay_clock_guard.py',
        description='Реплей контроля метки времени (clock_guard) по выгрузке history db-writer',
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('input', help='Выгрузка history: CSV с заголовком или JSONL (можно .gz)')
    parser.add_argument('--format', choices=('auto', 'csv', 'jsonl'), default='auto',
                        help='Формат файла (по умолчанию — по расширению: .jsonl/.ndjson/.json — '
                             'jsonl, иначе csv)')
    parser.add_argument('--delimiter', default=',', help='Разделитель CSV (по умолчанию: ,)')
    parser.add_argument('--config', '-c',
                        help='config.yaml декодера: берётся секция clock_guard '
                             '(без него — значения по умолчанию)')
    parser.add_argument('--mode', choices=cg.MODES,
                        help='Режим для всех роутеров (переопределения routers из конфига '
                             'отбрасываются)')
    parser.add_argument('--col-router', default='router_sn',
                        help='Колонка SN роутера (по умолчанию: router_sn)')
    parser.add_argument('--col-ts', default='timestamp',
                        help='Колонка метки записи (по умолчанию: timestamp)')
    parser.add_argument('--col-recv', default='received_at',
                        help='Колонка времени вставки (по умолчанию: received_at)')
    parser.add_argument('--col-panel', default=None,
                        help="Колонка панели (по умолчанию bserver_id, если она есть; "
                             "'-' — не использовать)")
    parser.add_argument('--key-col', action='append', default=[], metavar='COL',
                        help='Дополнительная колонка ключа объединения дублей '
                             '(можно несколько раз), например addr')
    parser.add_argument('--no-dedupe', action='store_true',
                        help='Не объединять строки с одинаковыми router_sn, панелью, '
                             'timestamp и received_at')
    parser.add_argument('--keep-heartbeat', action='store_true',
                        help='Не исключать строки пульса db-writer')
    parser.add_argument('--heartbeat-max-offset', type=float, default=5.0, metavar='SEC',
                        help='Пульс: метка с долями секунды и |offset| не больше SEC '
                             '(по умолчанию: 5)')
    parser.add_argument('--naive-tz', type=parse_tz_arg, default=None, metavar='TZ',
                        help='Пояс для значений без пояса (+03:00, UTC, local) — если колонки '
                             'выгружены как timestamp without time zone. По умолчанию метка '
                             'без пояса — invalid, received_at без пояса — строка пропускается')
    parser.add_argument('--router', action='append', default=[], metavar='SN',
                        help='Только этот роутер (можно несколько раз)')
    parser.add_argument('--tick-sec', type=float, default=5.0, metavar='SEC',
                        help='Период тика монитора состояния (по умолчанию: 5)')
    parser.add_argument('--batch-window', type=float, default=1.0, metavar='SEC',
                        help='Окно группировки залежалых пачек late (по умолчанию: 1)')
    parser.add_argument('--out', metavar='CSV',
                        help='Записать результат по каждой записи (статус, k, offset, '
                             'исправленная метка)')
    parser.add_argument('--quarantine-file', metavar='JSONL',
                        help='Писать карантин (future) в этот файл (по умолчанию не пишется)')
    parser.add_argument('--max-rows', type=int, default=100, metavar='N',
                        help='Строк в каждой таблице отчёта (0 — все; по умолчанию: 100)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Показывать WARNING clock_guard (эпизоды, молчание) '
                             'со временем реплея')
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except ReplayError as e:
        print(f"[ОШИБКА] {e}", file=sys.stderr)
        return 2
    print_report(result, args)
    if args.out:
        print()
        print(f"Результат по записям: {args.out}")
    return 0


if __name__ == '__main__':
    try:
        # Консоль Windows (cp866/cp1251): не падать на символах вне кодировки
        sys.stdout.reconfigure(errors='replace')
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
