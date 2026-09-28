"""Марка стали металлических элементов. KR-056, вторая очередь Матрицы.

Параметр требует сравнить марку стали стадий, а в одном абзаце проект называет несколько
марок для разных элементов:

    Распорки выполняется из стальных труб ∅530х8 мм … (сталь марки Ст2сп ГОСТ 380-2005).
    …распределительные пояса … из спаренных двутавров 70Б2 … (сталь класса C245 ГОСТ 27772-2015)

Поэтому марка без элемента в сравнение не идёт: множество, куда попали и распорки, и пояс,
и закладные пластины, делает правило слепым — наименьшим значением остаётся С235 листовой
стали, и подмена марки несущего элемента выглядит как «наименьшее не уменьшилось».

## Чем меряется прочность

Значение сравнения — нормативное сопротивление (предел текучести) марки, МПа: у ГОСТ 27772
это само число обозначения (С245 — 245 МПа), у ГОСТ 380 и ГОСТ 1050 оно взято из стандарта
для толщин до 20 мм. Толщина проката по тексту не определяется, поэтому сравнение идёт по
номинальному значению марки: это допущение, и оно записано в решении Р-62.

Понижение прочности — нарушение по триггеру параметра («подмена марки стали на менее
прочную»). Замена марки без понижения прочности нарушением не объявляется: Ст2сп → Ст20
на Новослободской поднимает предел текучести с 225 до 245 МПа. Но и молчать о ней нельзя —
организатор в своей разметке (`ANN-C-0001`) держит этот случай оранжевым кандидатом
«различие может быть допустимой расчётной корректировкой». Запись выходит с
`MATERIAL_SUBSTITUTION_NO_STRENGTH_DECREASE` и пометкой `needs_expert`: согласованность
изменения по документам не проверяется, в «СХЕМЕ GOLD» для этого есть поле
`approved_change_ref`, которого у нас нет.

## Как марка привязывается к элементу

CLAUSE — элемент назван в том же предложении. PAGE — предложением раньше в том же описании.
PATH — комплект назван папкой или именем файла: в томе распорной системы общие указания
называют только вид проката («Трубы должны соответствовать ГОСТ 10704-91, из стали марки
Ст20… Двутавры… сталь С245»), а что трубы здесь распорки, а двутавры — обвязочный пояс,
известно из назначения комплекта. Понижение объявляется только по привязке CLAUSE рабочей
стадии — это делает `decide_set`.

## Что в сравнение не идёт

Шпунт ограждения котлована, закладные детали, пластины, полосы, уголки и листовая сталь —
не несущие металлоконструкции: они названы, чтобы марка рядом с ними не досталась несущему
элементу, но своих записей не дают. Требование вида «стали класса не ниже С235» — не
решение, а нижняя граница: в указаниях АР Речникова так написано про перемычки, и сравнивать
это со спецификацией другой стадии нельзя.
"""
import collections
import os
import re

# Нормативное сопротивление (предел текучести) марки, МПа, для толщин до 20 мм.
# ГОСТ 27772-2015 — число в обозначении; ГОСТ 380-2005 и ГОСТ 1050-2013 — из стандарта;
# низколегированные — по ГОСТ 19281-2014. Ст0 гарантированного предела текучести не имеет
STRENGTH = {
    "С235": 235, "С245": 245, "С255": 255, "С285": 285, "С345": 345,
    "С355": 355, "С375": 375, "С390": 390, "С440": 440, "С590": 590,
    "Ст0": None, "Ст1": 195, "Ст2": 225, "Ст3": 245, "Ст4": 265, "Ст5": 285, "Ст6": 315,
    "Ст10": 205, "Ст20": 245, "Ст25": 275, "Ст35": 315, "Ст45": 355,
    "09Г2С": 345, "10Г2С1": 345, "15ХСНД": 345, "10ХСНД": 390,
}

# Порядок ветвей важен: «Ст20» — марка ГОСТ 1050, и разбирать её как «Ст2» с категорией 0
# нельзя. У ГОСТ 380 требуется степень раскисления (Ст2сп, ВСт3пс5) или граница слова:
# без этого «Ст20-1» с плана Октябрьской — подпись стены толщиной 200 мм, а не марка
GRADE_RE = re.compile(
    r"(?<![\w-])(?:"
    r"(?P<c>[СC]\s?-?\s?(?:235|245|255|285|345|355|375|390|440|590))"
    r"|(?P<l>09Г2С|10Г2С1|15ХСНД|10ХСНД)"
    r"|(?:[ВB]?[СCc]т\s?(?P<g1050>10|20|25|35|45))"
    r"|(?:[ВB]?[СCc]т\s?(?P<g380>[0-6])\s?(?P<kind>сп|пс|кп)?(?P<cat>[1-6])?)"
    r")(?![\w-])", re.I)
# Марка стоит в тексте про сталь: «сталь марки», «из стали», «прокат марки», «ГОСТ 380-2005».
# Без этого в подписи стены «Ст25-1» и в номере позиции видится марка
STEEL_CTX = re.compile(r"стал[ьияе]|стальн\w*|прокат\w*|марк\w*|двутавр\w*|труб\w*|ГОСТ\s?(?:380|1050|10704|27772|103|19903|8509|8240|57837|32931|8732|10705)", re.I)
CTX_BACK, CTX_FWD = 90, 70
# Требование, а не решение: «стали класса не ниже С235», «не менее С245»
REQUIREMENT = re.compile(r"не\s+(?:ниже|менее|хуже)\s+(?:класса\s+|марки\s+)?$", re.I)
REQ_BACK = 40

# Элементы, к которым относится марка. Порядок важен: «пояса ферм» — ферма, а не обвязочный
# пояс, поэтому пояс требует уточнения «обвязочный» или «распределительный».
# `excluded` — элемент называется, чтобы марка рядом с ним не досталась несущему, но своей
# записи не даёт
ELEMENT_TYPES = (
    ("Распорки котлована", r"распорк\w*|распорн\w+\s+систем\w*", False),
    ("Обвязочный пояс", r"(?:обвязочн\w*|распредел\w*)\.?\s+(?:пояс\w*|балк\w*)", False),
    ("Шпунт ограждения", r"шпунт\w*", True),
    ("Закладные детали", r"закладн\w*|пластин\w*|полос[аыу]\b|уголк\w*|уголок|стал[ьи]\s+листов\w*"
                         r"|листов\w+\s+стал\w*|скоб\w*|креп[её]ж\w*|анкер\w*|болт\w*", True),
    ("Стальные фермы", r"ферм[аыуе]?\b|ферм\w*|раскос\w*", False),
    ("Связи", r"(?:вертикальн\w+|горизонтальн\w+)\s+связ\w*|связ[иией]\w*\s+между", False),
    ("Металлические колонны", r"колонн\w*|стойк\w*", False),
    ("Металлические балки", r"балк\w*|ригел\w*|прогон\w*|перекладин\w*", False),
    ("Стальные лестницы", r"лестниц\w*|стремянк\w*|марш\w*", False),
    ("Перемычки", r"перемычк\w*", False),
    ("Профилированный настил", r"профилированн\w+\s+настил\w*|профнастил\w*", False),
    ("Навес", r"навес\w*|козыр[ьё]\w*", False),
)
_ELEMENT_RES = [(name, re.compile(rx, re.I), excluded) for name, rx, excluded in ELEMENT_TYPES]
EXCLUDED = {name for name, _rx, excluded in ELEMENT_TYPES if excluded}

# Комплект ограждения котлована и распорной системы: в нём вид проката говорит об элементе —
# трубы это распорки, двутавры и швеллеры — обвязочный пояс
PIT_SET = re.compile(r"распорк\w*|распорн\w+\s+систем\w*|ограждени\w+\s+котлован\w*"
                     r"|(?<![А-Яа-яЁёA-Za-z])СВГ(?![А-Яа-яЁёA-Za-z])", re.I)
# Том котлована по имени файла: «23.009-Р-КР. Котлован. Шпунтовое ограждение (включая водопонижение)»
# у Октябрьской. В его спецификации пояс назван позицией «ОП | ГОСТ Р 57837-2017 | два двутавра №30Ш1»,
# слова «пояс» в строке нет, и без этого двутавр доставался распоркам из заголовка таблицы
PIT_PATH = re.compile(r"(?<![А-Яа-яЁё])котлован\w*", re.I)
PROFILE = ((r"труб\w*|Тр\.\s?\d{3}", "Распорки котлована"),
           (r"двутавр\w*|Дв\.\s?\d{2}Б|швеллер\w*|\d{2}[БУ]\d", "Обвязочный пояс"))
_PROFILE_RES = [(re.compile(rx, re.I), name) for rx, name in PROFILE]

CLAUSE_BACK = 400        # элемент в том же предложении — не дальше
BACK = 600               # элемент предложением раньше — не дальше


def grade_of(m):
    """(обозначение, прочность) для совпадения или (обозначение, None), если прочность не знаем."""
    if m.group("c"):
        token = "С" + re.sub(r"\D", "", m.group("c"))          # латинская C в обозначении — как русская
    elif m.group("l"):
        token = m.group("l").upper()
    elif m.group("g1050"):
        token = "Ст" + m.group("g1050")
    else:
        token = "Ст" + m.group("g380")
    raw = token + (m.group("kind").lower() if m.groupdict().get("kind") else "")
    return raw, STRENGTH.get(token)


def _mentions(text):
    """Упоминания элементов: (начало, тип). Пересечения отдаются раньше найденному типу."""
    taken, out = [], []
    for name, rx, _excluded in _ELEMENT_RES:
        for m in rx.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            out.append((m.start(), name))
    out.sort()
    return out


def _pit_element(text):
    """Элемент по виду проката в комплекте ограждения котлована: последний вид перед маркой."""
    hits = [(m.start(), name) for rx, name in _PROFILE_RES for m in rx.finditer(text)]
    return sorted(hits)[-1][1] if hits else None


def element_of(flat, pos, doc=None, clause_start=0):
    """(элемент, привязка) для марки в позиции pos.

    Порядок: элемент в предложении; вид проката в предложении, если это комплект ограждения
    котлована; элемент предложением раньше; вид проката раньше. Вид проката в предложении
    сильнее элемента из соседнего предложения: в общих указаниях СВГ Новослободской строка
    «Трубы стальные по ГОСТ 10704-91 из стали Ст20» стоит сразу за строкой про уголки и
    листовую сталь, и марка труб иначе досталась бы закладным деталям.
    """
    clause = flat[max(clause_start, pos - CLAUSE_BACK):pos]
    hits = _mentions(clause)
    if hits:
        return hits[-1][1], "CLAUSE"
    path = (doc or {}).get("relative_path") or ""
    pit = PIT_SET.search(path) or PIT_PATH.search(os.path.basename(path)) or PIT_SET.search(flat[:400])
    if pit:
        by_profile = _pit_element(clause)
        if by_profile:
            return by_profile, "CLAUSE"
    back = _mentions(flat[max(0, pos - BACK):pos])
    if back:
        return back[-1][1], "PAGE"
    if pit:
        by_profile = _pit_element(flat[max(0, pos - BACK):pos])
        if by_profile:
            return by_profile, "PATH"
    return None, None


def grades(flat, doc=None, clause_bounds=None):
    """Марки стали страницы: [{location, binding, value, raw, snippet}].

    `clause_bounds(flat, pos)` — начало предложения; по умолчанию окно фиксированной длины.
    """
    out = []
    for m in GRADE_RE.finditer(flat):
        before = flat[max(0, m.start() - CTX_BACK):m.start()]
        around = before + flat[m.start():m.end() + CTX_FWD]
        if not STEEL_CTX.search(around):
            continue
        if REQUIREMENT.search(before[-REQ_BACK:]):
            continue
        raw, value = grade_of(m)
        if value is None:
            continue
        start = clause_bounds(flat, m.start()) if clause_bounds else 0
        location, binding = element_of(flat, m.start(), doc, start)
        if not location or location in EXCLUDED:
            continue
        out.append({"location": location, "binding": binding, "value": value, "raw": raw,
                    "snippet": " ".join(flat[max(0, m.start() - 80):m.end() + 50].split())})
    return out


# Замена марки, при которой прочность не понижена. Значение словаря `comparison_result`
# наше: организатор в своей разметке называет такой случай
# SUBSTANTIAL_DESIGN_CHANGE_REQUIRES_APPROVAL_CHECK и держит его оранжевым кандидатом
SUBSTITUTION = "MATERIAL_SUBSTITUTION_NO_STRENGTH_DECREASE"


def substitution(pd, rd):
    """Решение о замене марки без понижения прочности: (метка, тип, пояснение).

    Нарушением это не объявляется: триггер параметра — «подмена марки стали на менее
    прочную», а предел текучести здесь не снизился. Но и в «разницу, которая не
    срабатывает», случай не убирается: марка несущего элемента заменена, и согласовано ли
    изменение, по документации не видно — в «СХЕМЕ GOLD» организатора для этого есть поле
    `approved_change_ref`, которого у нас нет. Решение за инспектором.
    """
    was, now = min(v for v, _g in pd["value"]), min(v for v, _g in rd["value"])
    gone = [g for v, g in pd["value"] if (v, g) not in set(rd["value"])]
    added = [g for v, g in rd["value"] if (v, g) not in set(pd["value"])]
    what = (f"{'/'.join(gone)} → {'/'.join(added)}" if gone and added
            else f"{pd['raw']} → {rd['raw']}")
    detail = (f"марка стали заменена: {what}; предел текучести не понижен ({was} → {now} МПа). "
              f"Согласовано ли изменение, по документации не видно — решение за инспектором")
    return "NO_VIOLATION", SUBSTITUTION, detail


def _slug(location):
    return re.sub(r"\s+", "-", location.strip().lower())


# ---------- профиль проката распорной системы (#106) ----------

FREE_PROFILE_CODE = "FREE-KR-003"
FREE_PROFILE_TITLE = "Понижение прокатного профиля распорной системы между стадиями"
# Прокатный профиль: 70Б2, 55Б1, 30Ш1, 25К1, 30У, 16П. Первое число — высота в сантиметрах
PROFILE_RE = re.compile(r"(?<![\w.,])(?P<h>[1-9]\d{0,2})\s?(?P<s>[БШКУПМ])\s?(?P<v>\d)?(?![\w])")
# Слева от обозначения — вид проката. Без этого требования адрес объекта «Алтуфьевское шоссе,
# 79Б» читается как двутавр 790 мм, и сравнение профилей даёт ложное понижение
PROFILE_WORD = re.compile(r"(?:двутавр\w*|дв\.|балк\w*|швеллер\w*|шв\.|спаренн\w*|сдвоенн\w*)"
                          r"[\s\d.,№xх×-]{0,14}$", re.I)
PROFILE_MIN_CM, PROFILE_MAX_CM = 10, 100
# Сравниваются только элементы распорной системы: там название элемента обозначает одну
# конструкцию яруса, и множество профилей элемента — это множество всей системы. У балок и
# колонн здания то же название покрывает десятки марок (на Алтуфьевском в проектной стадии
# 14 разных профилей балок, в рабочей — больше двадцати), и сравнивать их множества нельзя:
# единицей сравнения там должна быть марка отдельного элемента, а её текст не даёт (#106)
PROFILE_ELEMENTS = ("Обвязочный пояс", "Распорки котлована")
ROW_TAIL = 90            # хвост строки спецификации за профилем — до разделителя колонки


def _row_element(flat, end):
    """Элемент, названный в той же строке спецификации после профиля, или None.

    В спецификации распорной системы КР3 Октябрьской строка «7. | Двутавр № 30Ш1 (вес 1 п.м. -
    53,60 кг) - обвязочный пояс | 57837-2017 |» идёт за строкой «Мет. трубы Ø426х9 мм … - подкосы и
    распорки |», и поиск назад отдавал двутавр распоркам. Строка таблицы кончается разделителем
    колонки «|»: без него хвост — уже не та же строка, и элемент берётся по-старому.
    """
    tail = flat[end:end + ROW_TAIL]
    cut = tail.find("|")
    if cut < 0:
        return None
    hits = _mentions(tail[:cut])
    return hits[0][1] if hits else None


def profiles(flat, doc=None, clause_bounds=None):
    """Прокатные профили страницы: [{location, binding, height, raw, snippet}]. Высота в мм."""
    out = []
    for m in PROFILE_RE.finditer(flat):
        height = int(m.group("h"))
        if not PROFILE_MIN_CM <= height <= PROFILE_MAX_CM:
            continue
        if not PROFILE_WORD.search(flat[max(0, m.start() - 60):m.start()]):
            continue
        start = clause_bounds(flat, m.start()) if clause_bounds else 0
        row = _row_element(flat, m.end())
        location, binding = (row, "CLAUSE") if row else element_of(flat, m.start(), doc, start)
        if location not in PROFILE_ELEMENTS:
            continue
        out.append({"location": location, "binding": binding, "height": height * 10,
                    "raw": f'{height}{m.group("s").upper()}{m.group("v") or ""}',
                    "snippet": " ".join(flat[max(0, m.start() - 80):m.end() + 40].split())})
    return out


def _profile_side(rows):
    """Сторона стадии: наибольший профиль и страницы, где он назван."""
    if not rows:
        return None
    top = max(r["height"] for r in rows)
    marks = sorted({r["raw"] for r in rows if r["height"] == top})
    pages, first = [], None
    for r in rows:
        if r["height"] != top:
            continue
        key = (r["file_id"], r["page"])
        if key not in pages:
            pages.append(key)
        first = first or r
    return {"height": top, "raw": "/".join(marks), "pages": pages[:3], "snippet": first["snippet"],
            # при равной высоте — по обозначению: иначе порядок 70Б2 и 70Б3 менялся от прогона к прогону
            "all": "/".join(sorted({r["raw"] for r in rows}, key=lambda x: (-int(re.match(r"\d+", x).group()), x)))}


def profile_findings(object_id, pages, clause_bounds=None):
    """Гипотезы о понижении профиля распорной системы. `pages` — [(документ, страница, текст)].

    Сравнивается **наибольший** профиль элемента: ярусы в тексте не различаются, а множество
    профилей элемента покрывает их все, и наибольший — это самый нагруженный ярус. Наименьший
    для этого не годится: у Новослободской в проектной стадии рядом с поясами 70Б2 и 70Б3 том
    ПОС поминает пояса 50Б2, и по наименьшему выходило бы, что профиль вырос.

    Вердикта о нарушении гипотеза не выдаёт: равнопрочность решается расчётом, которого у нас
    нет. Три двутавра 55Б1 вместо двух 70Б2 могут быть допустимой корректировкой — организатор
    в разметке `ANN-C-0001` держит этот случай оранжевым кандидатом.
    """
    from pipeline import elements, tep
    clause_bounds = clause_bounds or elements.clause_bounds
    by_stage = collections.defaultdict(lambda: collections.defaultdict(list))
    for doc, page, text in pages:
        stage = doc.get("stage")
        if stage not in ("PD", "RD") or not text:
            continue
        for row in profiles(tep.flatten(text), doc, clause_bounds):
            by_stage[row["location"]][stage].append({**row, "file_id": doc["file_id"], "page": page})
    out = []
    for location in PROFILE_ELEMENTS:
        pd = _profile_side(by_stage[location].get("PD") or [])
        rd = _profile_side(by_stage[location].get("RD") or [])
        if not pd or not rd:
            continue                     # одна стадия молчит — сравнивать нечего
        if rd["height"] < pd["height"]:
            label, result = "VIOLATION_PRESENT", "DIMENSION_REDUCED"
            detail = (f"наибольший профиль понижен: {pd['raw']} ({pd['height']} мм) → "
                      f"{rd['raw']} ({rd['height']} мм). Профили проектной стадии: {pd['all']}, "
                      f"рабочей: {rd['all']}. Равнопрочность замены проверяется расчётом, "
                      f"которого у нас нет — решение за инспектором")
        else:
            label, result = "NO_VIOLATION", ("EQUAL_PD_RD" if pd["raw"] == rd["raw"]
                                             else "NON_TRIGGERING_DIFFERENCE_NO_DECREASE")
            detail = (f"наибольший профиль не понижен: {pd['raw']} ({pd['height']} мм) → "
                      f"{rd['raw']} ({rd['height']} мм). Профили проектной стадии: {pd['all']}, "
                      f"рабочей: {rd['all']}")
        evidence = [{"stage": stage, "file_id": fid, "pdf_page_number": page,
                     "quote": side["snippet"][:300], "localization": "PAGE_LEVEL"}
                    for side, stage in ((pd, "PD"), (rd, "RD")) for fid, page in side["pages"]]
        out.append({
            "finding_id": f"{object_id}::PROFILE::{_slug(location)}",
            "object_id": object_id,
            "matrix_scope": "FREE_SEARCH",
            "parameter_code": FREE_PROFILE_CODE,
            "parameter_id": None,
            "title": FREE_PROFILE_TITLE,
            "comparison_result": result,
            "location_type": "CONSTRUCTION_ELEMENT",
            "locations": [location],
            "pd_value": pd["raw"],
            "rd_value": rd["raw"],
            "id_value": None,
            "violation_label": label,
            # кода параметра в каталоге нет, критичность оттуда не приходит; замена профиля
            # без расчёта — то же, что геометрическое отклонение у FREE-KR-002
            "criticality": ("Существенное (предписание) — требует утверждения"
                            if label == "VIOLATION_PRESENT" else None),
            "finding_status": "SUSPICION" if label == "VIOLATION_PRESENT" else "NEGATIVE_VERIFIED",
            "needs_expert": label == "VIOLATION_PRESENT",
            "evidence": evidence,
            "extraction": {
                "rule_basis": "профиль проката несущего элемента распорной системы не должен "
                              "понижаться между стадиями без расчётного обоснования",
                "detail": detail,
                "pd": {"raw": pd["raw"], "height_mm": pd["height"], "profiles": pd["all"]},
                "rd": {"raw": rd["raw"], "height_mm": rd["height"], "profiles": rd["all"]},
            },
        })
    return out
