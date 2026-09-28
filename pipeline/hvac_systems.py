"""Характеристика отопительно-вентиляционных систем: какая система какие помещения обслуживает. Задача #37.

## Зачем

Все оцениваемые нарушения эталона — «в проекте для помещения предусмотрено, в рабочей
документации нет или иначе». На планах это видно глазами, но не разбором: на плане РД марка
системы стоит у воздуховода, а не у номера помещения, и без контуров помещений её не привязать.

Зато и проектная, и рабочая стадия обязаны содержать лист «Характеристика отопительно-
вентиляционных систем» (форма ГОСТ 21.602): обозначение системы, число систем, наименование
обслуживаемого помещения, тип установки, расход, давление. В этой таблице привязка записана
словами: «В2.7, В2.8, В2.9 | 3 | М.О. (поз.169) в пом. 140». Номер помещения — ключ сравнения
стадий, как номер группы у схем ВРУ и номер стояка в пятой очереди.

На Тюменской-5 таблица ПД (том ИОС5.4.2, листы 5–6) отдаёт помещению 140 три местных отсоса,
помещению 142 — ещё три; в таблице РД (ОВ1, листы 2–3) у этих помещений систем нет, а у 147
и 198 состав другой. Это и есть третье эталонное нарушение.

## Как читается

Сетка и текст ячеек — `pipeline/vector_tables.py`: текстовый слой, а где его нет — распознавание
ячеек. Колонки узнаются по шапке, а не по порядку: якорь — колонка со словом «помещени»,
обозначение и число систем стоят левее неё. Страница без такой шапки таблицей систем не считается.

Распознавание чертёжного шрифта даёт двойников: «В2.7» читается как «82.7» и «B2.7», «пом.» —
как «nom.» и «now.», «поз.» — как «no3.». Двойники сворачиваются только в служебных словах
и в первой букве обозначения; цифры не правятся никогда.

Обозначения на листах без слоя Tesseract читает нетвёрдо: «ВД3» — как «ВД», «ПД17.2» — как
«ПД7.2». Поэтому колонка обозначений дочитывается по форме глифов-штрихов (`pipeline/stroke_glyphs.py`,
#48): образцы знаков берутся из ячеек того же листа, которые Tesseract прочёл уверенно, и ячейка,
у которой узнаны все глифы, читается ими. Замер на 183 строках четырёх листов Тюменской-5 —
`docs/room-compare-report.md`.
"""
import re

from pipeline import stroke_glyphs, vector_tables

# служебные слова шапки и ячеек после свёртки двойников
_FOLD = str.maketrans({
    "a": "а", "b": "в", "c": "с", "e": "е", "h": "н", "k": "к", "m": "м", "n": "п", "o": "о",
    "p": "р", "t": "т", "w": "м", "x": "х", "y": "у", "0": "о", "3": "з", "6": "в", "8": "в",
})
_UPPER_TWINS = str.maketrans({
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р",
    "T": "Т", "X": "Х", "Y": "У",
})

# «Наименование обслуживаемого помещения» — формулировка формы ГОСТ 21.602. Одного слова «помещения»
# мало: оно есть в шапке таблицы воздухообменов и таблицы теплоизбытков, которые стоят на соседних
# листах. Распознавание теряет буквы («обслжибаемого»), поэтому от слова берётся начало.
SERVED_HEAD = re.compile(r"обсл\w*\s+помещени")
SYSTEM_HEAD = re.compile(r"обозн|чени[ея]\s*(?:\S+\s*)?сист|систем")
COUNT_HEAD = re.compile(r"\bкол")
FLOW_HEAD = re.compile(r"(?:^|[\s,;])l\b[^а-я]{0,6}м\s?[3³']?\s?/\s?ч|\bl\s*,\s*м", re.I)

# «пом. 140», «пом.160, 161, 162», «помещение 131»; после свёртки двойников
ROOMS = re.compile(r"пом(?:ещени[еяй]|\b)\.?\s*[№n]?\s*(\d{1,4}(?:\.\d{1,2})?[а-я]?"
                   r"(?:\s*[,;и]\s*\d{1,4}(?:\.\d{1,2})?[а-я]?)*)")
ROOM_NUMBER = re.compile(r"\d{1,4}(?:\.\d{1,2})?[а-я]?")
POSITION = re.compile(r"по[з3]\.?\s*(\d{1,4})")
# обозначение системы: буквы марки, затем номер с подномерами и буквами корпуса или секции.
# Тюменская-5 «В2.7», «ВЕ14»; Октябрьская «П1.1м*», «У1.1м - У1.2м»; Новослободская «П1.А1»;
# Речников «В-1.12»; Алтуфьевское «П1/В1»
SYSTEM = re.compile(r"[А-Я]{1,3}-?\d[\dА-Яа-я.]{0,10}")
MIN_DATA_ROWS = 3


def fold(text):
    """Строка для поиска служебных слов: нижний регистр, латинские и цифровые двойники свёрнуты."""
    return (text or "").lower().replace("ё", "е").translate(_FOLD)


def systems_of(text):
    """Обозначения систем из ячейки: «82.8, B2.9» → [«В2.8», «В2.9»].

    Правится только первая буква: «8» и латинская «B» на месте марки — это «В». Цифры номера
    не трогаются, поэтому «87.6» вместо «В2.6» останется «В7.6»: сравнение стадий на обозначения
    с распознанного листа опирается в последнюю очередь. Одно исключение — «УЗ»: без номера
    обозначения не бывает, поэтому буква «З» в конце слова из одних букв — это тройка, «У3».
    """
    out = []
    for token in re.split(r",\s+|[;\n]|\s-\s|\s{2,}", text or ""):
        token = token.strip(" .:|[]()*,")
        # буквы марки прописные; прочтение без белого списка отдаёт их строчными и латиницей: «y2», «уз»
        token = re.sub(r"^[A-Za-zА-Яа-я]{1,3}(?=-?\d|$)", lambda m: m.group(0).upper(), token).translate(_UPPER_TWINS)
        token = re.sub(r"^8(?=\d)", "В", token)
        token = re.sub(r"^([А-Я]{1,3})З$", r"\g<1>3", token)
        token = re.sub(r"(?<=\d),(?=\d)", ".", token)          # «В-1,7» — опечатка в самой таблице
        for part in token.split("/"):
            part = part.strip(" *").rstrip(".")
            if SYSTEM.fullmatch(part):
                out.append(part)
    return out


# «1 эт.», «1-3 эт.»: этаж, а не помещение; распознавание пишет «эт» как «эм», «3m», «9m», «am»
FLOOR = re.compile(r"\b\d{1,2}(?:\s*-\s*\d{1,2})?\s*(?:эт|эм|этаж\w*|[39]m|[39]м|am)(?![а-яa-z])\.?", re.I)


def rooms_of(text):
    """Номера помещений, названные в ячейке словом «пом.»."""
    out = []
    text = FLOOR.sub(" ", (text or "").replace("ё", "е"))
    for m in ROOMS.finditer(_keywords_folded(text)):
        for number in ROOM_NUMBER.findall(m.group(1)):
            if number not in out:
                out.append(number)
    return out


def _keywords_folded(text):
    """Свёртка двойников в словах, цифры остаются цифрами."""
    out = []
    for token in re.split(r"(\d[\d.,]*)", (text or "").lower().replace("ё", "е")):
        out.append(token if token[:1].isdigit() else token.translate(_FOLD))
    return "".join(out)


def positions_of(text):
    return sorted({m.group(1) for m in POSITION.finditer(_keywords_folded(text))}, key=int)


def _int(text):
    m = re.search(r"\d{1,6}", (text or "").replace(" ", ""))
    return int(m.group()) if m else None


HEAD_BANDS = 6             # сколько верхних ячеек колонки просматривается в поисках шапки
LEFT_COLUMNS = 8           # якорная колонка «помещение» стоит среди первых
FLOW_COLUMNS = 12          # расход стоит не дальше стольких колонок правее неё


def _head_cells(table, columns, bottom=None):
    """Свёрнутый текст верхних ячеек колонок: {колонка: [(ячейка, текст)]}. bottom — низ шапки, если известен."""
    grid = table.grid
    cells = []
    for c in columns:
        for band in grid.bands(c)[:HEAD_BANDS]:
            if bottom is None or band[1] <= bottom + vector_tables.LINE_TOL_PT:
                cells.append((c, band))
    out = {c: [] for c in columns}
    for (c, band), text in zip(cells, table.texts(cells)):
        out[c].append((band, fold(text)))
    return out


def _header_roles(table):
    """Колонки таблицы по шапке: {«system», «count», «served», «flow», «bottom»} или None.

    Якорь — ячейка со словом «помещени»: её низ и есть низ шапки, ниже идут строки данных.
    """
    total = len(table.grid.columns)
    left = _head_cells(table, range(min(LEFT_COLUMNS, total)))
    served, bottom = None, None
    for c, cells in left.items():
        hit = next((band for band, text in cells if SERVED_HEAD.search(text)), None)
        if hit and c > 0:
            served, bottom = c, hit[1]
            break
    if served is None:
        return None
    heads = {c: " ".join(t for band, t in cells if band[1] <= bottom + vector_tables.LINE_TOL_PT and t)
             for c, cells in left.items()}
    roles = {"served": served, "bottom": bottom}
    before = [c for c in heads if c < served]
    system = next((c for c in before if SYSTEM_HEAD.search(heads[c])), None)
    if system is None:
        return None                   # без колонки обозначений это не таблица систем
    roles["system"] = system
    count = next((c for c in before if c != roles["system"] and COUNT_HEAD.search(heads[c])), None)
    if count is None and served - 1 != roles["system"]:
        count = served - 1
    roles["count"] = count
    right = _head_cells(table, range(served + 1, min(served + 1 + FLOW_COLUMNS, total)), bottom)
    flow = next((c for c, cells in right.items() if FLOW_HEAD.search(" ".join(t for _, t in cells))), None)
    if flow is not None:
        roles["flow"] = flow
    return roles


def _first(texts):
    """Прочтение для показа: первое непустое."""
    return next((t for t in texts or () if t), "")


def _vote(lists):
    """Голосование прочтений: (принятые значения, сомнительные).

    Одно прочтение (текстовый слой) принимается целиком. Из нескольких значение принимается,
    если его дали хотя бы два; названное одним прочтением — сомнительное: утверждать по нему
    нельзя, но и считать, что его нет, тоже.
    """
    lists = [l for l in lists if l is not None]
    if len(lists) <= 1:
        return (list(lists[0]) if lists else []), []
    seen = {}
    for values in lists:
        for v in dict.fromkeys(values):
            seen[v] = seen.get(v, 0) + 1
    order = list(dict.fromkeys(v for values in lists for v in values))
    return [v for v in order if seen[v] >= 2], [v for v in order if seen[v] < 2]


def _majority(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    best = max(set(values), key=lambda v: (values.count(v), -values.index(v)))
    return best


def _own_band(grid, roles, role, band):
    """Ячейка колонки role для строки band.

    Наименование помещения бывает одно на несколько систем — объединённая ячейка, её текст
    относится к каждой строке. Число систем и расход у каждой строки свои: если в их колонке
    нет горизонтальных линий (Речников, Октябрьская), берётся полоса строки, иначе в одну
    ячейку попадают единицы всех строк разом — «111111».
    """
    if role == "system":
        return band
    own = grid.band_at(roles[role], (band[0] + band[1]) / 2) or band
    if role != "served" and own[1] - own[0] > 1.5 * (band[1] - band[0]):
        return band
    return own


def parse_page(page, use_ocr=True, ocr_cache=None):
    """Строки таблицы систем со страницы: [{systems, count, served, rooms, positions, flow, bbox}] или [].

    Вторым значением — сведения о чтении: сколько ячеек распознано, был ли доступен Tesseract.
    `ocr_cache` — прочтения ячеек прежнего запуска (`vector_tables.Table`); словарь пополняется на месте.
    """
    table = vector_tables.read_table(page, use_ocr=use_ocr, ocr_cache=ocr_cache)
    info = {"grid": bool(table), "ocr_cells": 0, "ocr_failed": False, "roles": None}
    if not table:
        return [], info
    roles = _header_roles(table)
    info.update(ocr_cells=table.ocr_used, ocr_failed=table.ocr_failed, roles=roles)
    if not roles:
        return [], info
    grid = table.grid
    bands = [b for b in grid.bands(roles["system"]) if b[0] >= roles["bottom"] - vector_tables.LINE_TOL_PT]
    wanted = [r for r in ("system", "count", "served", "flow") if roles.get(r) is not None]
    cells = []
    for band in bands:
        for role in wanted:
            cells.append((roles[role], _own_band(grid, roles, role, band)))
    marks = [k for k, (column, _) in enumerate(cells) if column == roles["system"]]
    reads = table.variants(cells)
    # колонка обозначений читается своим набором прочтений: с белым списком символов марок
    for k, texts in zip(marks, table.variants([cells[k] for k in marks], votes=vector_tables.MARK_VOTES)):
        reads[k] = texts
    info.update(ocr_cells=table.ocr_used, ocr_failed=table.ocr_failed, glyph_cells=0, glyph_templates="")
    by_glyphs, sheet = set(), None
    if table.ocr_used and stroke_glyphs.available():
        # обозначения на листе без слоя дочитываются по форме глифов-штрихов (#48): ячейка,
        # у которой узнаны все глифы, читается ими, остальные остаются за голосованием Tesseract
        sheet = stroke_glyphs.Sheet(page)
        glyph_texts, glyph_info = sheet.read_marks(
            [grid.cell(*cells[k]) for k in marks], [reads[k] for k in marks], systems_of)
        for k, text in zip(marks, glyph_texts):
            if text and len(reads[k]) > 1:
                reads[k] = [text]
                by_glyphs.add(k)
        info.update(glyph_cells=glyph_info["read"], glyph_templates=glyph_info["templates"])
    rows = []
    for i, band in enumerate(bands):
        got = dict(zip(wanted, reads[i * len(wanted):(i + 1) * len(wanted)]))
        system_raw = _first(got.get("system"))
        served = _first(got.get("served"))
        systems = _vote([systems_of(t) for t in got.get("system") or [""]])[0]
        rooms, doubtful = _vote([rooms_of(t) for t in got.get("served") or [""]])
        if sheet is not None and sheet.templates and len(got.get("served") or []) > 1 and (rooms or doubtful):
            # номера помещений с распознанного листа сверяются с числами, прочитанными по глифам (#48)
            rooms, doubtful = stroke_glyphs.reconcile_numbers(
                rooms, doubtful, sheet.numbers(grid.cell(roles["served"], _own_band(grid, roles, "served", band))))
        if not systems and not rooms and not doubtful:
            continue                      # шапка, пустая строка, примечание
        if "помещени" in fold(served) and "обслужива" in fold(served):
            continue                      # шапка, повторённая на листе продолжения
        rows.append({
            "systems": systems,
            "system_raw": system_raw,
            "count": _majority([_int(t) for t in got.get("count") or []]),
            "served": served,
            "rooms": rooms,
            "rooms_doubtful": doubtful,
            "positions": _vote([positions_of(t) for t in got.get("served") or [""]])[0],
            "flow": _majority([_int(t) for t in got.get("flow") or []]) if "flow" in got else None,
            "read": "OCR" if len(got.get("served") or []) > 1 else "LAYER",
            "marks_read": "GLYPHS" if i * len(wanted) in by_glyphs else ("OCR" if len(got.get("system") or []) > 1 else "LAYER"),
            "bbox": table.rect_norm(roles["served"], _own_band(grid, roles, "served", band)),
        })
    if len(rows) < MIN_DATA_ROWS:
        return [], info
    return rows, info
