# Copyright (c) 2026 ООО «НГ-ЭНЕРГОСЕРВИС». Все права защищены.
# Программный комплекс «Честная Генерация»
# Модуль декодирования Modbus-телеметрии
# Автор: Саввиди Александр Анатольевич | ИНН 4725009270
#
# Данное программное обеспечение является конфиденциальным.
# Несанкционированное копирование, распространение или использование
# без письменного разрешения правообладателя запрещено.

"""
Тесты разбора секции clock_guard при запуске (app.init_clock_guard_from_config).

Главное: выключатель оператора не должен молча превращаться во включение.
В DEFAULTS модуль включён, поэтому откат «к значениям по умолчанию» при
ошибке в секции соблюдает явное enabled: false, а clock_guard: false —
короткая форма выключения.

Запуск из корня репозитория:
    PYTHONIOENCODING=utf-8 env/Scripts/python.exe -m pytest tests/test_app_clock_config.py -q
"""

import logging
from datetime import datetime, timedelta, timezone

import pytest

import app
import clock_guard

MSK = timezone(timedelta(hours=3))
SN = '1126246373'


@pytest.fixture(autouse=True)
def fresh_global(monkeypatch):
    """Глобальный ClockGuard: свой на тест, исходный возвращает monkeypatch."""
    monkeypatch.setattr(clock_guard, '_clock_guard', None)
    yield
    guard = clock_guard.get_clock_guard()
    if guard is not None:
        guard.close()


def init(section):
    return app.init_clock_guard_from_config({'clock_guard': section})


def future_stamp() -> str:
    """Метка на 5 мин впереди — у включённого модуля это future (карантин)."""
    return (datetime.now(MSK) + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S%z')


def config_errors(caplog):
    return [r for r in caplog.records
            if r.levelno == logging.ERROR and 'clock_guard' in r.getMessage()]


def test_no_section_uses_defaults(caplog):
    caplog.set_level(logging.ERROR)
    for config in ({}, {'clock_guard': None}):
        guard, ok = app.init_clock_guard_from_config(config)
        assert ok is True
        assert guard.enabled is True and guard.cfg.mode == clock_guard.MODE_FLAG
        assert clock_guard.get_clock_guard() is guard
    assert config_errors(caplog) == []


def test_valid_section():
    guard, ok = init({'enabled': True, 'mode': 'correct', 'quarantine': {'file': ''}})
    assert ok is True
    assert guard.enabled is True and guard.cfg.mode == clock_guard.MODE_CORRECT
    assert guard.classify(SN, future_stamp()).action == clock_guard.ACTION_QUARANTINE


def test_enabled_false_disables():
    guard, ok = init({'enabled': False})
    assert ok is True
    assert guard.enabled is False
    assert guard.classify(SN, future_stamp()) is None


@pytest.mark.parametrize('value', [False, 'false', 'off', 'no', 'нет', 0])
def test_short_form_disables(value, caplog):
    """clock_guard: false — короткая форма выключения, не ошибка."""
    caplog.set_level(logging.ERROR)
    guard, ok = init(value)
    assert ok is True
    assert guard.enabled is False
    assert guard.classify(SN, future_stamp()) is None
    assert app.describe_clock_guard(guard) == 'контроль метки времени выключен'
    assert config_errors(caplog) == []


@pytest.mark.parametrize('section', [
    {'enabled': False, 'min_valid_date': '01.01.2024'},
    {'enabled': False, 'quarantine': {'max_bytes': '10MB'}},
    {'enabled': 'off', 'epsilon_sec': '2 мин'},
    {'enabled': 'false', 'max_shift_hours': [14]},
], ids=['date', 'max_bytes', 'epsilon', 'list'])
def test_error_in_section_keeps_explicit_off(section, caplog):
    """
    Ошибка в другом ключе не включает модуль, выключенный оператором:
    иначе на время инцидента записи future продолжали бы уходить в карантин.
    """
    caplog.set_level(logging.ERROR)
    guard, ok = init(section)
    assert ok is False
    assert guard.enabled is False
    assert guard.classify(SN, future_stamp()) is None
    errors = config_errors(caplog)
    assert len(errors) == 1
    assert 'контроль выключен' in errors[0].getMessage()


@pytest.mark.parametrize('section', [
    {'epsilon_sec': 'abc'},
    {'enabled': True, 'min_valid_date': 'garbage'},
    {'enabled': 'maybe', 'late_sec': 'x'},
    ['enabled'],
    'maybe',
], ids=['epsilon', 'date', 'unknown-enabled', 'list', 'string'])
def test_error_in_section_falls_back_to_defaults(section, caplog):
    caplog.set_level(logging.ERROR)
    guard, ok = init(section)
    assert ok is False
    assert guard.enabled is True
    assert guard.cfg.epsilon_sec == clock_guard.DEFAULTS['epsilon_sec']
    errors = config_errors(caplog)
    assert len(errors) == 1
    assert 'значения по умолчанию' in errors[0].getMessage()
