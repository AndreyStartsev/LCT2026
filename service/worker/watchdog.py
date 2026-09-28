"""Когда снимать шаг обработки по таймауту. Задача #113.

Срок шага (`TIMEOUT_PARSE_S` и соседи) ставился на зависание, а упирался в объём: разбор
Лосевской 3А с 3956 страницами сканов ИД шёл 1 ч 49 мин при сроке 2 ч, у Полярной 16
одной ИД 17 410 страниц. Снятый по сроку разбор не терялся — повтор продолжал с прочитанного
по кешу страниц, — но в журнале процесса оставался «повтор после сбоя», которого не было.

Поэтому срок теперь значит «с этого момента шаг должен показывать ход». Шаг, который
печатает строки или двигает ход в Redis не реже раза в `STALL_TIMEOUT_S`, идёт дальше срока,
но не дольше предельного срока `TIMEOUT_<ШАГ>_MAX_S` — по умолчанию втрое больше срока,
столько же, сколько давали три попытки. Зависший шаг снимается как раньше и повторяется.
Модуль без зависимостей: его проверяет `tests/test_parse_time.py`.
"""
import datetime
import json


def overdue(elapsed, quiet, timeout, limit, stall):
    """Причина снять шаг или None, если пусть идёт.

    elapsed — сколько шаг идёт, quiet — сколько секунд от последнего признака хода,
    timeout — срок шага, limit — предельный срок, stall — сколько можно молчать после срока.
    """
    if elapsed <= timeout:
        return None
    if elapsed > limit:
        return f"предельный срок {limit} с"
    if quiet > stall:
        return f"нет хода {quiet:.0f} с"
    return None


def progress_age(raw, now=None):
    """Сколько секунд назад шаг двигал ход в Redis; None, если хода нет или он не читается.

    raw — значение ключа process:<id>:progress, JSON с updated_at в ISO 8601 (`infra.progress`).
    """
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        at = datetime.datetime.fromisoformat(payload["updated_at"])
    except (ValueError, TypeError, KeyError):
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=datetime.timezone.utc)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return max((now - at).total_seconds(), 0.0)
