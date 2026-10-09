# Copyright (c) 2026 ООО «НГ-ЭНЕРГОСЕРВИС». Все права защищены.
# Программный комплекс «Честная Генерация»
# Модуль декодирования Modbus-телеметрии
# Автор: Саввиди Александр Анатольевич | ИНН 4725009270
#
# Данное программное обеспечение является конфиденциальным.
# Несанкционированное копирование, распространение или использование
# без письменного разрешения правообладателя запрещено.

"""
Универсальный Modbus-декодер — Контроль метки времени (clock guard)

Проверяет date_iso_8601 каждой Modbus-записи относительно времени приёма
сообщения (t_recv) и решает, что с записью делать: публиковать как есть,
исправить сдвиг пояса, отправить в карантин или подставить время приёма.

offset = ts − t_recv. Статус считается по собственному offset каждой записи
(пачки бывают смешанными). Если подходят несколько статусов, побеждает первый:

    invalid > tz_shift > future > offset_jump > late > ok

  invalid      метка не разобралась, без пояса или раньше min_valid_date
  tz_shift k>0 offset > ε и offset ∈ [k·3600 − 1800; k·3600 + 120], k = 1…14,
               сразу с первой записи, без подтверждения
  future       offset > ε, но под целые часы не подходит
  tz_shift k<0 offset ≈ k·3600 ± 120 с держится ≥120 с, ≥3 разных метки,
               разброс ≤30 с, без живых записей и пауз приёма >30 с;
               до подтверждения — late. Только флаг, без исправления
  offset_jump  отход от базового offset роутера >600 с держится ≥3 метки
               и ≥60 с; одиночная залежалая пачка — late
  late         offset < −60 с, только пометка

Состояние на роутер нужно только для tz_shift (k<0), offset_jump и границ
эпизода (лог, UI). Эпизод закрывается после 2 разных нормальных меток или
при молчании роутера дольше N минут (tick() из монитора состояния).
"""

import json
import logging
import logging.handlers
import math
import re
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Deque, Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Статусы классификации записи
TS_OK = 'ok'
TS_LATE = 'late'
TS_TZ_SHIFT = 'tz_shift'
TS_FUTURE = 'future'
TS_OFFSET_JUMP = 'offset_jump'
TS_INVALID = 'invalid'
# ts_status в decoded для tz_shift (k>0), исправленного в режиме correct
TS_CORRECTED = 'corrected'

ALL_STATUSES = (TS_OK, TS_LATE, TS_TZ_SHIFT, TS_FUTURE, TS_OFFSET_JUMP, TS_INVALID)
# Статусы, открывающие эпизод (late — штатная залежалая доставка, не эпизод)
EPISODE_STATUSES = (TS_TZ_SHIFT, TS_FUTURE, TS_OFFSET_JUMP, TS_INVALID)

MODE_FLAG = 'flag'
MODE_CORRECT = 'correct'
MODES = (MODE_FLAG, MODE_CORRECT)

ACTION_PUBLISH = 'publish'
ACTION_QUARANTINE = 'quarantine'

# Что сделано с записями эпизода
EP_ACTION_FLAGGED = 'flagged'
EP_ACTION_CORRECTED = 'corrected'
EP_ACTION_QUARANTINED = 'quarantined'
EP_ACTION_REPLACED = 'replaced'

# Формат метки роутера: 2026-10-09T13:20:28+0300
TS_FORMAT = '%Y-%m-%dT%H:%M:%S%z'

_TZ_NO_COLON = re.compile(r'([+-]\d{2})(\d{2})$')

DEFAULT_QUARANTINE = {
    # Пустая строка '' — не писать. Ключ без значения (null) — значение по умолчанию
    'file': 'logs/clock_quarantine.jsonl',
    # max_bytes и backup_count — не меньше 1 (0 отключил бы ротацию)
    'max_bytes': 10 * 1024 * 1024,
    'backup_count': 5,
    # Только для наблюдения. Пустая строка '' — не публиковать
    'topic_base': 'cg/v1/quarantine/SN',
}

DEFAULTS: Dict[str, Any] = {
    'enabled': True,
    'mode': MODE_FLAG,
    'routers': {},
    'epsilon_sec': 120,
    'late_sec': 60,
    'min_valid_date': '2024-01-01',
    'max_shift_hours': 14,
    'shift_early_sec': 1800,
    'shift_late_sec': 120,
    'neg_shift_tolerance_sec': 120,
    'neg_shift_confirm_sec': 120,
    'neg_shift_min_stamps': 3,
    'neg_shift_max_spread_sec': 30,
    'neg_shift_max_gap_sec': 30,
    'jump_threshold_sec': 600,
    'jump_confirm_sec': 60,
    'jump_min_stamps': 3,
    'jump_max_spread_sec': 60,
    'jump_max_gap_sec': 30,
    'baseline_min_samples': 15,
    'baseline_max_samples': 30,
    'episode_close_normal_stamps': 2,
    'episode_silence_close_min': 10,
    'silence_alert_sec': 60,
    'silence_lookback_sec': 300,
    'episodes_keep': 200,
    'quarantine': DEFAULT_QUARANTINE,
}


# ============================================================
# Утилиты
# ============================================================

def parse_router_ts(value: Any) -> Optional[datetime]:
    """
    Разбор метки роутера. Возвращает aware datetime или None,
    если метка не разобралась или у неё нет пояса.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Python < 3.11 не понимает пояс без двоеточия (+0300)
        try:
            dt = datetime.fromisoformat(_TZ_NO_COLON.sub(r'\1:\2', s))
        except ValueError:
            return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt


def format_router_ts(dt: datetime) -> str:
    """Метка в исходном формате роутера: 2026-10-09T13:20:28+0300."""
    return dt.strftime(TS_FORMAT)


def utc_iso_ms(epoch: float) -> str:
    """UTC ISO с миллисекундами: 2026-10-09T10:20:28.123+00:00."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec='milliseconds')


def _local_tz() -> tzinfo:
    return datetime.now().astimezone().tzinfo


def _to_min_valid(value: Any) -> datetime:
    """min_valid_date из конфига (строка или date из YAML) → aware datetime UTC."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        dt = datetime.fromisoformat(str(value).strip())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _local_str(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch).strftime('%Y-%m-%d %H:%M:%S')


_TRUE_WORDS = ('true', 'yes', 'on', '1', 'да')
_FALSE_WORDS = ('false', 'no', 'off', '0', 'нет', '')


def _to_bool(value: Any, default: bool, where: str) -> bool:
    """
    Флаг из конфига. bool() не годится: строка 'false' (ручная правка
    в кавычках) дала бы True и включила бы то, что хотели выключить.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    logger.warning(f"{where}: непонятное значение '{value}', используется {default}")
    return default


def is_off_value(value: Any) -> bool:
    """
    Значение выключателя означает «выключено»: false, 0, 'false', 'off',
    'no', 'нет', '' — те же слова, что понимает _to_bool. None и всё
    непонятное — не выключение. В лог ничего не пишет.
    """
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, str):
        return value.strip().lower() in _FALSE_WORDS
    return False


# ============================================================
# Конфигурация
# ============================================================

class ClockGuardConfig:
    """Параметры секции clock_guard (значения по умолчанию — DEFAULTS)."""

    def __init__(self, raw: Optional[dict] = None):
        raw = dict(raw or {})
        d = dict(DEFAULTS)
        d.update({k: v for k, v in raw.items() if v is not None})

        self.enabled = _to_bool(d['enabled'], True, 'clock_guard.enabled')
        self.mode = self._mode(d['mode'], MODE_FLAG, 'clock_guard.mode')

        # Переопределение режима на роутер: {"<sn>": "correct"} или {"<sn>": {"mode": "correct"}}
        self.router_modes: Dict[str, str] = {}
        routers = d.get('routers') or {}
        if isinstance(routers, dict):
            for sn, value in routers.items():
                mode = value.get('mode') if isinstance(value, dict) else value
                if mode is None:
                    continue
                self.router_modes[str(sn)] = self._mode(mode, self.mode, f'clock_guard.routers.{sn}')
        else:
            logger.warning("clock_guard.routers должен быть словарём — проигнорирован")

        self.epsilon_sec = float(d['epsilon_sec'])
        self.late_sec = float(d['late_sec'])
        self.min_valid = _to_min_valid(d['min_valid_date'])
        self.max_shift_hours = int(d['max_shift_hours'])
        self.shift_early_sec = float(d['shift_early_sec'])
        self.shift_late_sec = float(d['shift_late_sec'])

        self.neg_tolerance_sec = float(d['neg_shift_tolerance_sec'])
        self.neg_confirm_sec = float(d['neg_shift_confirm_sec'])
        self.neg_min_stamps = int(d['neg_shift_min_stamps'])
        self.neg_max_spread_sec = float(d['neg_shift_max_spread_sec'])
        self.neg_max_gap_sec = float(d['neg_shift_max_gap_sec'])

        self.jump_threshold_sec = float(d['jump_threshold_sec'])
        self.jump_confirm_sec = float(d['jump_confirm_sec'])
        self.jump_min_stamps = int(d['jump_min_stamps'])
        self.jump_max_spread_sec = float(d['jump_max_spread_sec'])
        self.jump_max_gap_sec = float(d['jump_max_gap_sec'])

        self.baseline_min_samples = max(1, int(d['baseline_min_samples']))
        self.baseline_max_samples = max(self.baseline_min_samples, int(d['baseline_max_samples']))

        self.close_normal_stamps = max(1, int(d['episode_close_normal_stamps']))
        self.silence_close_sec = float(d['episode_silence_close_min']) * 60.0
        self.silence_alert_sec = float(d['silence_alert_sec'])
        self.silence_lookback_sec = float(d['silence_lookback_sec'])
        self.episodes_keep = max(1, int(d['episodes_keep']))

        q = dict(DEFAULT_QUARANTINE)
        q_raw = raw.get('quarantine')
        if isinstance(q_raw, dict):
            q.update({k: v for k, v in q_raw.items() if v is not None})
        elif q_raw is not None:
            logger.warning("clock_guard.quarantine должен быть словарём — проигнорирован")
        self.quarantine_file = str(q['file'] or '')
        # RotatingFileHandler не ротирует вовсе, если max_bytes или backup_count
        # равны 0, — файл карантина рос бы без предела. Такие значения не принимаются
        self.quarantine_max_bytes = int(q['max_bytes'])
        if self.quarantine_max_bytes <= 0:
            default_bytes = DEFAULT_QUARANTINE['max_bytes']
            logger.warning(f"clock_guard.quarantine.max_bytes: {self.quarantine_max_bytes} — "
                           f"без ротации файл рос бы без предела, используется {default_bytes}")
            self.quarantine_max_bytes = default_bytes
        self.quarantine_backup_count = int(q['backup_count'])
        if self.quarantine_backup_count < 1:
            logger.warning(f"clock_guard.quarantine.backup_count: {self.quarantine_backup_count} — "
                           f"без архивного файла ротации нет и файл рос бы без предела, "
                           f"используется 1")
            self.quarantine_backup_count = 1
        self.quarantine_topic_base = str(q['topic_base'] or '').rstrip('/')

    @staticmethod
    def _mode(value: Any, default: str, where: str) -> str:
        mode = str(value).strip().lower()
        if mode not in MODES:
            logger.warning(f"{where}: неизвестный режим '{value}', используется '{default}'")
            return default
        return mode


# ============================================================
# Вердикт по записи
# ============================================================

@dataclass
class TsVerdict:
    """Результат проверки метки одной записи."""
    status: str                       # классификация: ok/late/tz_shift/future/offset_jump/invalid
    ts_status: str                    # значение ts_status в decoded (tz_shift → corrected при исправлении)
    action: str                       # publish | quarantine
    timestamp: Optional[str]          # что ставить в поле timestamp
    received_at: str                  # UTC ISO с миллисекундами
    offset_sec: Optional[float] = None
    shift_hours: Optional[int] = None
    original: Optional[str] = None    # исходная метка (ts_original)

    def payload_fields(self) -> Dict[str, Any]:
        """Дополнительные поля для decoded-сообщения."""
        fields: Dict[str, Any] = {
            'received_at': self.received_at,
            'ts_status': self.ts_status,
            'ts_offset_sec': self.offset_sec,
        }
        if self.shift_hours is not None:
            fields['ts_shift_hours'] = self.shift_hours
            fields['ts_original'] = self.original
        elif self.status == TS_INVALID:
            fields['ts_original'] = self.original
        return fields


def passthrough_verdict(date_iso: Any, t_recv: float) -> TsVerdict:
    """Вердикт «как есть» — при внутренней ошибке модуля."""
    try:
        received_at = utc_iso_ms(t_recv)
    except Exception:
        received_at = None
    return TsVerdict(status=TS_OK, ts_status=TS_OK, action=ACTION_PUBLISH,
                     timestamp=date_iso, received_at=received_at)


# ============================================================
# Состояние роутера
# ============================================================

@dataclass
class _Tracker:
    """Кандидат на подтверждаемый статус (tz_shift k<0 или offset_jump)."""
    k: Optional[int] = None
    start: Optional[float] = None
    last: Optional[float] = None
    stamps: Set[str] = field(default_factory=set)
    min_offset: float = 0.0
    max_offset: float = 0.0
    confirmed: bool = False

    def active(self) -> bool:
        return self.start is not None

    def reset(self):
        self.k = None
        self.start = None
        self.last = None
        self.stamps = set()
        self.min_offset = 0.0
        self.max_offset = 0.0
        self.confirmed = False

    def begin(self, t: float, stamp: str, offset: float, k: Optional[int] = None):
        self.reset()
        self.k = k
        self.start = t
        self.last = t
        self.stamps.add(stamp)
        self.min_offset = offset
        self.max_offset = offset

    def add(self, t: float, stamp: str, offset: float):
        self.last = t
        # Метки нужны только до подтверждения (счёт разных меток). После него
        # трекер не перезапускается, пока смещение держится, — без этой проверки
        # множество росло бы без предела (неделями, если роутер не исправят)
        if not self.confirmed:
            self.stamps.add(stamp)
        self.min_offset = min(self.min_offset, offset)
        self.max_offset = max(self.max_offset, offset)

    def spread_with(self, offset: float) -> float:
        return max(self.max_offset, offset) - min(self.min_offset, offset)

    def duration(self) -> float:
        return (self.last - self.start) if self.active() else 0.0


@dataclass
class _RouterState:
    sn: str
    baseline: Deque[float]
    last_recv: Optional[float] = None
    last_status: Optional[str] = None
    last_offset: Optional[float] = None
    last_ts: Optional[str] = None
    last_tz: Optional[tzinfo] = None
    neg: _Tracker = field(default_factory=_Tracker)
    jump: _Tracker = field(default_factory=_Tracker)
    episode: Optional[dict] = None
    normal_stamps: Set[str] = field(default_factory=set)
    episode_starts: Deque[float] = field(default_factory=deque)
    # Последние записи tz_shift k>0 — для сигнала о молчании публикатора
    pos_shift_last_recv: Optional[float] = None
    pos_shift_k: Optional[int] = None
    pos_shift_max_epoch: Optional[float] = None
    pos_shift_max_ts: Optional[str] = None
    silence: Optional[dict] = None


# ============================================================
# Карантин
# ============================================================

class _QuarantineFileHandler(logging.handlers.RotatingFileHandler):
    """
    RotatingFileHandler, который не глотает ошибки записи.

    Штатный emit() ловит любое исключение (открытие, запись, ротация) и
    вызывает handleError(): тот лишь печатает трассировку в stderr. Для
    карантина файл — единственная копия записи future (в decoded она не
    публикуется), поэтому ошибка должна дойти до ClockGuard.quarantine()
    и попасть в счётчик errors. handleError() вызывается внутри
    except-блока emit(), так что голый raise пробрасывает исходную ошибку.
    """

    def handleError(self, record):
        raise


class QuarantineWriter:
    """Ротируемый JSONL-файл карантина (по строке на запись)."""

    def __init__(self, path: str, max_bytes: int, backup_count: int):
        self.path = path
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._handler: Optional[logging.handlers.RotatingFileHandler] = None
        self._lock = threading.Lock()

    def write(self, entry: dict) -> bool:
        """
        Дописать строку. False — файл выключен (path пустой).
        Ошибка открытия, записи или ротации пробрасывается.
        """
        if not self.path:
            return False
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock:
            if self._handler is None:
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
                handler = _QuarantineFileHandler(
                    self.path, maxBytes=self.max_bytes, backupCount=self.backup_count,
                    encoding='utf-8', delay=True)
                handler.setFormatter(logging.Formatter('%(message)s'))
                self._handler = handler
            record = logging.LogRecord('clock_quarantine', logging.INFO, __file__, 0,
                                       line, None, None)
            self._handler.handle(record)
        return True

    def close(self):
        with self._lock:
            if self._handler is not None:
                self._handler.close()
                self._handler = None


# ============================================================
# ClockGuard
# ============================================================

class ClockGuard:
    """
    Контроль метки времени Modbus-записей.

    Потокобезопасен: classify() вызывается из потока MQTT, tick() — из
    монитора состояния, snapshot() — из Web UI.
    """

    def __init__(self, config: Optional[dict] = None):
        self.cfg = ClockGuardConfig(config)
        self._lock = threading.Lock()
        self._routers: Dict[str, _RouterState] = {}
        self._episodes: Deque[dict] = deque(maxlen=self.cfg.episodes_keep)
        self._episode_seq = 0
        self._counters: Dict[str, int] = self._empty_counters()
        self._last_error_log = 0.0
        self._quarantine = QuarantineWriter(self.cfg.quarantine_file,
                                            self.cfg.quarantine_max_bytes,
                                            self.cfg.quarantine_backup_count)

    @property
    def enabled(self) -> bool:
        return self.cfg.enabled

    @staticmethod
    def _empty_counters() -> Dict[str, int]:
        counters = {s: 0 for s in ALL_STATUSES}
        counters.update({'total': 0, 'corrected': 0, 'quarantined': 0,
                         'replaced': 0, 'errors': 0})
        return counters

    def mode_for(self, router_sn: str) -> str:
        return self.cfg.router_modes.get(str(router_sn), self.cfg.mode)

    # ----------------------------------------------------------------
    # Классификация
    # ----------------------------------------------------------------

    def classify(self, router_sn: str, date_iso: Any,
                 t_recv: Optional[float] = None) -> Optional[TsVerdict]:
        """
        Проверить метку одной записи. None — модуль выключен.
        При внутренней ошибке — вердикт «ok, как есть».
        """
        if not self.cfg.enabled:
            return None
        if t_recv is None:
            t_recv = time.time()
        try:
            with self._lock:
                return self._classify_locked(str(router_sn), date_iso, float(t_recv))
        except Exception as e:
            self._note_error(e)
            return passthrough_verdict(date_iso, t_recv)

    def _classify_locked(self, router_sn: str, date_iso: Any, t: float) -> TsVerdict:
        cfg = self.cfg
        st = self._router(router_sn)
        self._on_activity(st, t)
        st.last_recv = t

        received_at = utc_iso_ms(t)
        mode = self.mode_for(router_sn)
        dt = parse_router_ts(date_iso)
        if dt is not None and dt < cfg.min_valid:
            dt = None

        # --- invalid: подставляем время приёма ---
        if dt is None:
            tz = st.last_tz or _local_tz()
            verdict = TsVerdict(
                status=TS_INVALID, ts_status=TS_INVALID, action=ACTION_PUBLISH,
                timestamp=format_router_ts(datetime.fromtimestamp(t, tz=tz)),
                received_at=received_at,
                original=None if date_iso is None else str(date_iso))
            self._count(TS_INVALID, 'replaced')
            st.last_status = TS_INVALID
            self._track_episode(st, TS_INVALID, None, verdict.original or '', None, t,
                                EP_ACTION_REPLACED)
            return verdict

        stamp = date_iso.strip()
        st.last_tz = dt.tzinfo
        offset = dt.timestamp() - t
        status, k = self._status_for(st, stamp, offset, t)

        st.last_status = status
        st.last_offset = offset
        st.last_ts = stamp
        offset_r = round(offset, 3)

        if status == TS_TZ_SHIFT and k > 0:
            self._note_pos_shift(st, k, dt.timestamp(), stamp, t)
            if mode == MODE_CORRECT:
                fixed = format_router_ts(dt - timedelta(hours=k))
                verdict = TsVerdict(status, TS_CORRECTED, ACTION_PUBLISH, fixed,
                                    received_at, offset_r, k, stamp)
                self._count(status, 'corrected')
                ep_action = EP_ACTION_CORRECTED
            else:
                verdict = TsVerdict(status, status, ACTION_PUBLISH, stamp,
                                    received_at, offset_r, k, stamp)
                self._count(status)
                ep_action = EP_ACTION_FLAGGED
        elif status == TS_TZ_SHIFT:
            verdict = TsVerdict(status, status, ACTION_PUBLISH, stamp,
                                received_at, offset_r, k, stamp)
            self._count(status)
            ep_action = EP_ACTION_FLAGGED
        elif status == TS_FUTURE:
            verdict = TsVerdict(status, status, ACTION_QUARANTINE, stamp,
                                received_at, offset_r)
            self._count(status)
            ep_action = EP_ACTION_QUARANTINED
        else:
            verdict = TsVerdict(status, status, ACTION_PUBLISH, stamp,
                                received_at, offset_r)
            self._count(status)
            ep_action = EP_ACTION_FLAGGED

        self._track_episode(st, status, k, stamp, offset, t, ep_action)
        return verdict

    def _status_for(self, st: _RouterState, stamp: str, offset: float,
                    t: float) -> Tuple[str, Optional[int]]:
        cfg = self.cfg

        # --- метка впереди: tz_shift (k>0) сразу или future ---
        if offset > cfg.epsilon_sec:
            k = math.floor(offset / 3600.0 + 0.5)
            if (1 <= k <= cfg.max_shift_hours
                    and k * 3600 - cfg.shift_early_sec <= offset <= k * 3600 + cfg.shift_late_sec):
                return TS_TZ_SHIFT, k
            return TS_FUTURE, None

        # --- целые часы назад: tz_shift (k<0) только с подтверждением ---
        # Такие записи ведёт только это правило (не offset_jump): до
        # подтверждения это залежалая доставка — late.
        neg_k = self._neg_hours(offset)
        if neg_k is not None:
            self._track_neg(st, neg_k, stamp, offset, t)
            if st.neg.confirmed:
                return TS_TZ_SHIFT, neg_k
            return TS_LATE, None
        st.neg.reset()

        # --- устойчивый отход от базового offset ---
        deviation = offset - self._baseline(st)
        if abs(deviation) > cfg.jump_threshold_sec:
            self._track_jump(st, stamp, offset, t)
            if st.jump.confirmed:
                return TS_OFFSET_JUMP, None
        else:
            st.jump.reset()

        if offset < -cfg.late_sec:
            return TS_LATE, None

        # --- живая запись ---
        st.jump.reset()
        st.baseline.append(offset)
        return TS_OK, None

    def _neg_hours(self, offset: float) -> Optional[int]:
        k = math.floor(offset / 3600.0 + 0.5)
        if -self.cfg.max_shift_hours <= k <= -1 and abs(offset - k * 3600) <= self.cfg.neg_tolerance_sec:
            return k
        return None

    def _baseline(self, st: _RouterState) -> float:
        """Медиана последних живых offset; пока их мало — номинальный 0."""
        if len(st.baseline) < self.cfg.baseline_min_samples:
            return 0.0
        return statistics.median(st.baseline)

    def _track_neg(self, st: _RouterState, k: int, stamp: str, offset: float, t: float):
        cfg = self.cfg
        n = st.neg
        restart = not n.active() or n.k != k
        if not restart and not n.confirmed:
            restart = (t - n.last > cfg.neg_max_gap_sec
                       or n.spread_with(offset) > cfg.neg_max_spread_sec)
        if restart:
            n.begin(t, stamp, offset, k)
        else:
            n.add(t, stamp, offset)
        if (not n.confirmed
                and len(n.stamps) >= cfg.neg_min_stamps
                and n.duration() >= cfg.neg_confirm_sec
                and n.max_offset - n.min_offset <= cfg.neg_max_spread_sec):
            n.confirmed = True
            n.stamps.clear()

    def _track_jump(self, st: _RouterState, stamp: str, offset: float, t: float):
        cfg = self.cfg
        j = st.jump
        restart = not j.active()
        if not restart and not j.confirmed:
            restart = (t - j.last > cfg.jump_max_gap_sec
                       or j.spread_with(offset) > cfg.jump_max_spread_sec)
        if restart:
            j.begin(t, stamp, offset)
        else:
            j.add(t, stamp, offset)
        if (not j.confirmed
                and len(j.stamps) >= cfg.jump_min_stamps
                and j.duration() >= cfg.jump_confirm_sec
                and j.max_offset - j.min_offset <= cfg.jump_max_spread_sec):
            j.confirmed = True
            j.stamps.clear()

    # ----------------------------------------------------------------
    # Эпизоды
    # ----------------------------------------------------------------

    def _track_episode(self, st: _RouterState, status: str, k: Optional[int],
                       stamp: str, offset: Optional[float], t: float, action: str):
        if status in EPISODE_STATUSES:
            st.normal_stamps.clear()
            ep = st.episode
            if ep is not None and (ep['status'] != status or ep['k'] != k):
                self._close_episode(st, 'changed')
                ep = None
            if ep is None:
                ep = self._open_episode(st, status, k, stamp, offset, t, action)
            ep['count'] += 1
            ep['last_recv'] = t
            ep['last_ts'] = stamp
            if offset is not None:
                ep['last_offset'] = offset
                ep['min_offset'] = offset if ep['min_offset'] is None else min(ep['min_offset'], offset)
                ep['max_offset'] = offset if ep['max_offset'] is None else max(ep['max_offset'], offset)
        elif status == TS_OK and st.episode is not None:
            st.normal_stamps.add(stamp)
            if len(st.normal_stamps) >= self.cfg.close_normal_stamps:
                self._close_episode(st, 'normal')

    def _open_episode(self, st: _RouterState, status: str, k: Optional[int],
                      stamp: str, offset: Optional[float], t: float, action: str) -> dict:
        self._episode_seq += 1
        ep = {
            'id': self._episode_seq,
            'router_sn': st.sn,
            'status': status,
            'k': k,
            'action': action,
            'start': t,
            'end': None,
            'last_recv': t,
            'count': 0,
            'first_ts': stamp,
            'last_ts': stamp,
            'last_offset': offset,
            'min_offset': None,
            'max_offset': None,
            'close_reason': None,
        }
        st.episode = ep
        st.episode_starts.append(t)
        logger.warning(
            f"Метка времени: роутер {st.sn} — начало эпизода {self._describe(status, k)}"
            f"{'' if offset is None else f', offset {offset:+.0f} с'}, метка {stamp!r}"
            f" ({self._describe_action(action)})")
        return ep

    def _close_episode(self, st: _RouterState, reason: str):
        ep = st.episode
        if ep is None:
            return
        ep['end'] = ep['last_recv']
        ep['close_reason'] = reason
        self._episodes.append(ep)
        st.episode = None
        st.normal_stamps.clear()
        duration = ep['end'] - ep['start']
        reason_text = {'normal': 'метки в норме', 'silence': 'роутер молчит',
                       'changed': 'сменился статус', 'reset': 'сброс'}.get(reason, reason)
        logger.warning(
            f"Метка времени: роутер {st.sn} — конец эпизода {self._describe(ep['status'], ep['k'])}: "
            f"записей {ep['count']}, длительность {duration:.0f} с ({reason_text})")

    @staticmethod
    def _describe(status: str, k: Optional[int]) -> str:
        return f"{status} k={k:+d}" if k is not None else status

    @staticmethod
    def _describe_action(action: str) -> str:
        return {EP_ACTION_CORRECTED: 'метки исправляются',
                EP_ACTION_FLAGGED: 'публикуется с флагом',
                EP_ACTION_QUARANTINED: 'записи уходят в карантин',
                EP_ACTION_REPLACED: 'метка заменяется временем приёма'}.get(action, action)

    # ----------------------------------------------------------------
    # Молчание публикатора после tz_shift k>0
    # ----------------------------------------------------------------

    def _note_pos_shift(self, st: _RouterState, k: int, ts_epoch: float, stamp: str, t: float):
        st.pos_shift_last_recv = t
        st.pos_shift_k = k
        if st.pos_shift_max_epoch is None or ts_epoch > st.pos_shift_max_epoch:
            st.pos_shift_max_epoch = ts_epoch
            st.pos_shift_max_ts = stamp

    def _on_activity(self, st: _RouterState, t: float):
        """Пришла запись от роутера: снять сигнал о молчании."""
        if st.silence is not None:
            silent = t - st.silence['since']
            logger.warning(f"Метка времени: роутер {st.sn} возобновил передачу "
                           f"после молчания {silent / 60:.0f} мин")
            st.silence = None
            st.pos_shift_last_recv = None
            st.pos_shift_k = None
            st.pos_shift_max_epoch = None
            st.pos_shift_max_ts = None

    def _silence_message(self, st: _RouterState, now: float) -> str:
        s = st.silence
        wait_until = s.get('wait_until')
        if wait_until is None:
            wait = ''
        else:
            tz = st.last_tz or _local_tz()
            until_text = format_router_ts(datetime.fromtimestamp(wait_until, tz=tz))
            left = (wait_until - now) / 60.0
            when = (f"≈ через {left:.0f} мин" if left >= 0
                    else f"срок прошёл {-left:.0f} мин назад")
            wait = (f" — публикатор, вероятно, ждёт, пока часы роутера дойдут до "
                    f"последней «будущей» метки {until_text} ({when})")
        return (f"Роутер молчит после tz_shift k=+{s['k']}{wait}; "
                f"перезапустите сервис опроса на роутере")

    # ----------------------------------------------------------------
    # Периодический тик (монитор состояния)
    # ----------------------------------------------------------------

    def tick(self, now: Optional[float] = None):
        """Закрыть эпизоды по молчанию, поднять сигнал о молчании публикатора."""
        if not self.cfg.enabled:
            return
        if now is None:
            now = time.time()
        try:
            with self._lock:
                for st in self._routers.values():
                    self._tick_router(st, now)
        except Exception as e:
            self._note_error(e)

    def _tick_router(self, st: _RouterState, now: float):
        cfg = self.cfg
        if st.last_recv is None:
            return
        silent = now - st.last_recv

        if silent > cfg.silence_close_sec:
            if st.episode is not None:
                self._close_episode(st, 'silence')
            st.neg.reset()
            st.jump.reset()
            st.normal_stamps.clear()

        if (st.silence is None
                and st.pos_shift_last_recv is not None
                and silent > cfg.silence_alert_sec
                and st.pos_shift_last_recv >= st.last_recv - cfg.silence_lookback_sec):
            st.silence = {
                'since': st.last_recv,
                'k': st.pos_shift_k,
                'wait_until': st.pos_shift_max_epoch,
                'wait_until_ts': st.pos_shift_max_ts,
            }
            logger.warning(f"Метка времени: роутер {st.sn}: {self._silence_message(st, now)}")

    # ----------------------------------------------------------------
    # Карантин
    # ----------------------------------------------------------------

    def quarantine(self, entry: dict) -> bool:
        """
        Записать запись в JSONL-карантин. Ошибки не пробрасываются.

        Счётчик quarantined — записи, не опубликованные в decoded и ушедшие
        в карантин. Растёт при каждом вызове, даже если файл выключен
        (quarantine.file пусто) или запись в него не удалась (тогда растёт
        и errors): иначе такие записи не видны нигде, кроме счётчика future.

        Возвращает True, если строка записана в файл.
        """
        with self._lock:
            self._counters['quarantined'] += 1
        try:
            return self._quarantine.write(entry)
        except Exception as e:
            self._note_error(e, f"Ошибка записи в файл карантина {self.cfg.quarantine_file}")
            return False

    def quarantine_topic(self, router_sn: str, device_type: str, bserver_id: Any) -> Optional[str]:
        """Топик карантина (только для наблюдения) или None, если выключен."""
        base = self.cfg.quarantine_topic_base
        if not base:
            return None
        return f"{base}/{router_sn}/{device_type}/{bserver_id}"

    # ----------------------------------------------------------------
    # Состояние для UI / API
    # ----------------------------------------------------------------

    def get_counters(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._counters)

    def router_status(self, router_sn: str, now: Optional[float] = None) -> Optional[dict]:
        """Статус часов одного роутера или None, если записей ещё не было."""
        if now is None:
            now = time.time()
        with self._lock:
            st = self._routers.get(str(router_sn))
            if st is None:
                return None
            return self._router_view(st, now)

    def snapshot(self, now: Optional[float] = None) -> dict:
        """Полное состояние: режим, счётчики, роутеры, эпизоды (новые первыми)."""
        if now is None:
            now = time.time()
        with self._lock:
            routers = [self._router_view(st, now) for st in
                       sorted(self._routers.values(), key=lambda s: s.sn)]
            episodes = [self._episode_view(ep, now) for ep in self._episodes]
            for st in self._routers.values():
                if st.episode is not None:
                    episodes.append(self._episode_view(st.episode, now))
            episodes.sort(key=lambda e: e['start'], reverse=True)
            return {
                'enabled': self.cfg.enabled,
                'mode': self.cfg.mode,
                'router_modes': dict(self.cfg.router_modes),
                'counters': dict(self._counters),
                'routers': routers,
                'episodes': episodes,
            }

    def _router_view(self, st: _RouterState, now: float) -> dict:
        while st.episode_starts and st.episode_starts[0] < now - 86400:
            st.episode_starts.popleft()
        state, label = self._clock_state(st)
        silence = None
        if st.silence is not None:
            silence = dict(st.silence)
            silence['since_local'] = _local_str(silence['since'])
            silence['message'] = self._silence_message(st, now)
        return {
            'router_sn': st.sn,
            'mode': self.mode_for(st.sn),
            'clock_state': state,
            'clock_label': label,
            'last_status': st.last_status,
            'last_offset_sec': None if st.last_offset is None else round(st.last_offset, 1),
            'last_ts': st.last_ts,
            'last_recv': st.last_recv,
            'last_recv_local': _local_str(st.last_recv),
            'episodes_24h': len(st.episode_starts),
            'episode': None if st.episode is None else self._episode_view(st.episode, now),
            'silence': silence,
        }

    @staticmethod
    def _clock_state(st: _RouterState) -> Tuple[str, str]:
        if st.silence is not None:
            return 'silent', f"молчит после сдвига на +{st.silence['k']} ч"
        ep = st.episode
        if ep is None:
            if st.last_status is None:
                return 'unknown', 'нет данных'
            return 'ok', 'в норме'
        status, k = ep['status'], ep['k']
        if status == TS_TZ_SHIFT and k is not None and k > 0:
            return 'ahead', f"спешат на {k} ч"
        if status == TS_TZ_SHIFT and k is not None:
            return 'behind', f"отстают на {-k} ч"
        if status == TS_INVALID:
            return 'invalid', 'метка неразборчива'
        if status == TS_FUTURE:
            minutes = (ep['last_offset'] or 0) / 60.0
            return 'future', f"спешат на {minutes:.0f} мин"
        if status == TS_OFFSET_JUMP:
            minutes = (ep['last_offset'] or 0) / 60.0
            return 'jump', f"скачок смещения: {minutes:+.0f} мин"
        return status, status

    @staticmethod
    def _episode_view(ep: dict, now: float) -> dict:
        view = dict(ep)
        view['open'] = ep['end'] is None
        end = ep['end'] if ep['end'] is not None else ep['last_recv']
        view['duration_sec'] = round(end - ep['start'], 1)
        view['start_local'] = _local_str(ep['start'])
        view['end_local'] = _local_str(ep['end'])
        for key in ('last_offset', 'min_offset', 'max_offset'):
            if view[key] is not None:
                view[key] = round(view[key], 1)
        return view

    # ----------------------------------------------------------------
    # Служебное
    # ----------------------------------------------------------------

    def reset(self) -> dict:
        """Сбросить состояние роутеров и журнал эпизодов (счётчики остаются)."""
        with self._lock:
            cleared = {'routers': len(self._routers),
                       'episodes': len(self._episodes)
                       + sum(1 for st in self._routers.values() if st.episode is not None)}
            # Открытые эпизоды закрываются с WARNING в лог: у каждого эпизода
            # в логе должны быть и начало, и конец
            for st in self._routers.values():
                if st.episode is not None:
                    self._close_episode(st, 'reset')
            self._routers.clear()
            self._episodes.clear()
        return cleared

    def close(self):
        self._quarantine.close()

    def _router(self, router_sn: str) -> _RouterState:
        st = self._routers.get(router_sn)
        if st is None:
            st = _RouterState(sn=router_sn,
                              baseline=deque(maxlen=self.cfg.baseline_max_samples))
            self._routers[router_sn] = st
        return st

    def _count(self, status: str, extra: Optional[str] = None):
        self._counters['total'] += 1
        self._counters[status] += 1
        if extra:
            self._counters[extra] += 1

    def _note_error(self, e: Exception,
                    what: str = "Внутренняя ошибка контроля метки времени"):
        """Счётчик errors + ERROR в лог (не чаще раза в минуту)."""
        try:
            with self._lock:
                self._counters['errors'] += 1
                now = time.time()
                if now - self._last_error_log < 60:
                    return
                self._last_error_log = now
            logger.error(f"{what}: {e}", exc_info=True)
        except Exception:
            pass


# Global instance
_clock_guard: Optional[ClockGuard] = None


def get_clock_guard() -> Optional[ClockGuard]:
    """Get the global ClockGuard instance (None — не инициализирован)."""
    return _clock_guard


def init_clock_guard(config: Optional[dict] = None) -> ClockGuard:
    """Initialize the global ClockGuard from the clock_guard config section."""
    global _clock_guard
    if _clock_guard is not None:
        _clock_guard.close()
    _clock_guard = ClockGuard(config)
    return _clock_guard
