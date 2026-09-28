"""Класс рабочей арматуры по конструктивным элементам. KR-057, вторая очередь Матрицы.

Параметр требует сравнить **рабочую** арматуру стадий. В одном предложении проект называет
обе: «основная рабочая арматура А400, конструктивная А240 по ГОСТ 34028-2016». Поэтому
класс без назначения в сравнение не идёт: множество, куда попали и рабочая, и конструктивная,
делает правило слепым — наименьшим значением всегда остаётся конструктивная А240, и подмена
рабочей А400 на А240 выглядит как «наименьшее не уменьшилось».

## Как определяется назначение

По ближайшей метке слева, и побеждает последняя: в «основная рабочая арматура А400,
конструктивная А240» у А400 ближе «рабочая», у А240 — «конструктивная». Рабочей считается и
«продольные стержни»: в рабочей документации назначение записано так («Продольные стержни
арматуры ∅12 А240, использованные для армирования форшахты»). Хомуты, шпильки, сетки,
распределительная и монтажная арматура — конструктивные.

## Как класс привязывается к элементу

CLAUSE — элемент назван в том же предложении. PATH — элемент назван папкой работ: у акта
освидетельствования предмет работ стоит в пути файла («Ограждение котлована. Форшахта»),
а в тексте акта раньше поминается ограждение котлована, то есть стена в грунте. PAGE — элемент
назван предложением раньше в том же описании работ: пояснительная записка описывает работы
подряд («бетонируется монолитная железобетонная форшахта – балка… Армирование производится…
основная рабочая арматура А400»), и привязка к нему слабее предложения, но не слабее таблицы
листа. Решение по привязке принимает `decide_set`: понижение объявляется только по CLAUSE
рабочей стадии.

## Форшахта

Для класса бетона и толщины плиты форшахта не несущая конструкция и отброшена
`elements._NOT_STRUCTURAL`. Для класса арматуры организатор считает её местом нарушения:
контрольная точка `ANN-0001` (Новослободская) — подмена рабочей А400 на А240 при армировании
форшахты, подтверждённая актом освидетельствования. Поэтому исключение здесь параметрное:
список элементов свой, `_NOT_STRUCTURAL` в этом разборе не применяется.

## Чего разбор не делает

Старые обозначения (A-I, A-II, A-III) не читаются: в корпусе их нет. Класс без назначения
берётся только в исполнительной стадии — акт перечисляет то, что фактически применено,
и назначения в нём нет. Ошибочно помеченный рабочим низкий класс проектной стадии занижает
наименьшее значение и может скрыть нарушение; обратной ошибки — ложного нарушения — он не даёт.
"""
import re

from pipeline import elements

# А240, А400, А500, А500С. Латинские A и C — как в документах («А500C») и после распознавания
CLASS_RE = re.compile(r"(?<![\w-])[АA]\s?-?\s?(240|400|500)\s?(?P<s>[СCс])?(?![\d\w])")
WORKING = re.compile(r"рабоч\w*|основн\w*|продольн\w*|вертикальн\w+\s+стержн\w*", re.I)
CONSTRUCTIVE = re.compile(r"конструктивн\w*|хомут\w*|шпильк\w*|сет(?:ка|ки|ок|чат\w*)"
                          r"|распределительн\w*|монтажн\w*|поперечн\w*", re.I)
# Элементы, которых нет в общем списке: у класса арматуры свой перечень
EXTRA_ELEMENTS = (("Форшахта", re.compile(r"форшахт\w*", re.I)),)
NEAR = 90            # метка назначения ищется не дальше
BACK = 600           # элемент предложением раньше — не дальше


def purpose(before):
    """Назначение по ближайшей метке слева: «working», «constructive» или None."""
    work = [m.end() for m in WORKING.finditer(before)]
    constr = [m.end() for m in CONSTRUCTIVE.finditer(before)]
    if not work and not constr:
        return None
    if work and (not constr or work[-1] > constr[-1]):
        return "working"
    return "constructive"


def _back_element(flat, pos, window=BACK):
    """Ближайший элемент позади значения в том же описании работ."""
    back = flat[max(0, pos - window):pos]
    hits = [(s, e, name) for s, e, name, _zoned in elements.element_mentions(back)]
    for name, rx in EXTRA_ELEMENTS:
        hits += [(m.start(), m.end(), name) for m in rx.finditer(back)]
    return sorted(hits)[-1][2] if hits else None


def _path_element(doc):
    """Элемент из пути файла: у акта освидетельствования он назван папкой работ."""
    path = (doc or {}).get("relative_path") or ""
    for name, rx in EXTRA_ELEMENTS:
        if rx.search(path):
            return name
    return None


def element_of(flat, pos, doc=None):
    """(локация, привязка) для класса в позиции pos."""
    start = elements.clause_bounds(flat, pos)
    clause = flat[max(start, pos - 400):pos + 120]
    for name, rx in EXTRA_ELEMENTS:
        if rx.search(clause):
            return name, "CLAUSE"
    for _s, _e, name, zoned in elements.element_mentions(clause):
        if not zoned:                       # зона элемента здесь не разбирается: класс арматуры
            return name, "CLAUSE"           # в корпусе не делится на подземную и надземную часть
    from_path = _path_element(doc)
    if from_path:
        return from_path, "PATH"
    back = _back_element(flat, pos)
    if back:
        return back, "PAGE"
    return None, None


def rebar_classes(flat, doc=None, as_built=False):
    """Классы арматуры страницы: [{location, binding, purpose, value, raw, snippet}].

    `as_built` — исполнительная стадия: класс без назначения берётся, в проектной и рабочей
    такой класс пропускается.
    """
    out = []
    for m in CLASS_RE.finditer(flat):
        why = purpose(flat[max(0, m.start() - NEAR):m.start()])
        if why is None and not as_built:
            continue
        location, binding = element_of(flat, m.start(), doc)
        if not location:
            continue
        number = int(m.group(1))
        out.append({"location": location, "binding": binding, "purpose": why or "unknown",
                    "value": number, "raw": f"А{number}" + ("С" if m.group("s") else ""),
                    "snippet": " ".join(flat[max(0, m.start() - 70):m.end() + 40].split())})
    return out


def working(rows):
    """Только рабочая арматура: она и сравнивается между стадиями."""
    return [r for r in rows if r["purpose"] in ("working", "unknown")]
