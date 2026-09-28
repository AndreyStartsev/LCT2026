"""Шифр с листа, выправленный по шифру комплекта из реестра. Задача #52.

Распознавание портит шифр одинаково на всех листах комплекта: единица в шрифте основной
надписи сливается с рамкой и теряется, ноль читается буквой «О», кириллица — латиницей.
Голосование внутри ряда листов такую ошибку не ловит: она одинакова у всех голосующих.
На одном из объектов корпуса так испорчены 35 листов комплекта из 43.

Шифр комплекта известен и без распознавания: он стоит в имени файла и лежит в реестре
документов (`document_code`). Это независимый источник, поэтому им можно выправить
прочтение — но не подменить его целиком: на листе шифр часто длиннее, чем в имени файла
(«КЖ2.1.И1» против «КЖ2.1»), а разделители расходятся (косая черта на листе против дефиса
в имени). Подменять значило бы менять одну ошибку на другую.

Поэтому правится только то, что распознавание портит: буквы, спутанные с цифрами,
латиница вместо кириллицы и потерянный знак. Разделители, регистр и хвост прочтения
остаются как прочитаны. Если прочтение расходится с реестром сильнее, чем на два знака,
оно не трогается вовсе: два разных комплекта объекта сами отличаются на один-два знака,
и «выправление» превратило бы один в другой.
"""
import difflib
import re

# Знаки, которые распознавание путает между собой. Пары двусторонние: «О» вместо нуля
# встречается так же часто, как ноль вместо «О».
CONFUSABLE = [
    "0OО○o", "1IlІ|", "3ЗЗз", "4Ч", "5S", "6б", "8В", "9g",
    "AА", "BВ", "CС", "EЕ", "HН", "KК", "MМ", "OО", "PР", "TТ", "XХ", "YУ", "aа", "cс",
    "eе", "oо", "pр", "xх", "yу", "ГF", "ДA", "ИN", "ЛJ", "ПN", "ЦU", "ЧY",
]
_SAME = {}
for group in CONFUSABLE:
    for ch in group:
        _SAME.setdefault(ch.lower(), set()).update(group.lower())

MAX_FIXES = 2          # больше — это другой комплект, а не ошибка чтения
_TOKEN = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+")


def confusable(a, b):
    """Один ли это знак с точки зрения распознавания: «О» и «0», «И» и «N»."""
    if a == b:
        return True
    return b.lower() in _SAME.get(a.lower(), ())


def skeleton(code):
    """Буквы и цифры шифра без разделителей и регистра: по ним шифры и сравниваются."""
    return "".join(_TOKEN.findall((code or "").lower()))


def tokens(code):
    """Куски шифра из букв и цифр: «НВС-2025/03-КЖ2.1» → НВС, 2025, 03, КЖ2, 1."""
    return _TOKEN.findall(code or "")


def _fix_token(read_token, registry_token):
    """Выправленный кусок прочтения или None, если это другой кусок, а не ошибка чтения.

    Вторым значением — сколько знаков исправлено.
    """
    a, b = read_token.lower(), registry_token.lower()
    if a == b:
        return read_token, 0
    if len(a) == len(b):
        if all(confusable(x, y) for x, y in zip(a, b)):
            fixed = "".join(y.upper() if x.isupper() or x.isdigit() else y
                            for x, y in zip(read_token, registry_token))
            return fixed, sum(1 for x, y in zip(a, b) if x != y)
        return None, 0
    if len(b) - len(a) == 1:
        # в прочтении пропал знак: «КЖ.1» вместо «КЖ2.1» — цифра сливается с рамкой
        for cut in range(len(b)):
            if b[:cut] + b[cut + 1:] == a:
                return registry_token if read_token.isupper() or read_token.isdigit() else registry_token, 1
        if all(confusable(x, y) for x, y in zip(a, b)) or all(confusable(x, y) for x, y in zip(a, b[1:])):
            return registry_token, 1
    return None, 0


def align(read, registry):
    """Прочтение, выправленное по шифру комплекта, или прочтение как есть.

    Возвращает (шифр, что исправлено): вторым значением — список пар «кусок прочтения,
    кусок реестра», пустой, если ничего не менялось.
    """
    if not read or not registry:
        return read, []
    a, b = tokens(read), tokens(registry)
    if not a or not b or [t.lower() for t in a] == [t.lower() for t in b]:
        return read, []
    ops = difflib.SequenceMatcher(None, [t.lower() for t in a], [t.lower() for t in b],
                                  autojunk=False).get_opcodes()
    fixes, changed, spent = {}, [], 0
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            continue
        if tag == "delete":
            # хвост прочтения, которого нет в имени файла: «КЖ2.1.И1» против «КЖ2.1» — оставляем
            if i2 == len(a):
                continue
            return read, []
        if tag == "insert":
            return read, []          # в прочтении нет целого куска: это другой шифр, а не описка
        if i2 - i1 != j2 - j1:
            return read, []
        for k in range(i2 - i1):
            fixed, cost = _fix_token(a[i1 + k], b[j1 + k])
            if fixed is None:
                return read, []
            if cost:
                fixes[i1 + k] = fixed
                changed.append((a[i1 + k], fixed))
                spent += cost
    if not fixes or spent > MAX_FIXES:
        return read, []
    return _rebuild(read, fixes), changed


def _rebuild(read, fixes):
    """Собрать шифр обратно: куски заменены, разделители прочтения сохранены."""
    out, index, pos = [], 0, 0
    for m in _TOKEN.finditer(read):
        out.append(read[pos:m.start()])
        out.append(fixes.get(index, m.group(0)))
        index, pos = index + 1, m.end()
    out.append(read[pos:])
    return "".join(out)
