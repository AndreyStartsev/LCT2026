"""Отклонения исполнительной схемы против допусков, объявленных на том же листе. Задача #89.

Исполнительная схема геодезиста сама несёт обе половины сравнения: таблицу фактических
отклонений от проектных отметок и таблицу допусков со ссылкой на норматив.

    № проема   низ                          верх
               высота проект,м  откл.,мм    высота проект,м  откл.,мм
    1(КР-4.1)  -3.950           +491        -2.900           +552
    5(КР-4.2)  -3.950           +980        -2.900           +537

    Допустимые отклонения СП 70.13330.2012, табл. 5.12
    Отклонение размеров оконных, дверных и других проемов        ±12 мм
    Отклонение длин или пролетов элементов, размеров в свету     ±20 мм
    Отклонение горизонтальных плоскостей на весь участок          20 мм

Сравнение идёт с **наибольшим** допуском листа, а не с тем, который подходит по смыслу:
какая строка таблицы 5.12 относится к отметке проёма, по тексту не решить, а отклонение
больше самого большого объявленного допуска выходит за границы при любом прочтении. Поэтому
+980 мм при наибольшем допуске 20 мм — нарушение, а +15 мм при допуске ±12 мм — нет, хотя
геодезист и выделил его на листе красным. Пропуск такого случая дешевле ложного нарушения.

Числа условий из таблицы допусками не считаются: в «Размер поперечного сечения элемента h
при h < 200 мм» двести — это размер конструкции, и если взять его за допуск, не найдётся
ничего. Отбрасываются числа, перед которыми стоит знак сравнения.

## Чего проверка не делает

Она не решает, какая конструкция отклонилась: адресация листа — оси и отметки, а запись
идёт на объект, как в эталонном перечне (VS-0021). Числа берутся из распознанного текста,
поэтому запись помечается `needs_expert`, а значение — прочитанным машиной (Р-40): на
растровой схеме цифры читает мультимодальная модель, и без режима чтения `model` таблица
не разбирается вовсе (#85).
"""
import re

from pipeline import tep

FREE_CODE = "FREE-KR-002"
TITLE = "Превышение допусков геометрических параметров по исполнительной схеме"

# Лист исполнительной схемы: в штампе слово написано целиком («Исполнительная схема
# вертикальных конструкций на отм. -5,250»), в имени файла — сокращением («Исп.схема № 52»)
SCHEME_RE = re.compile(r"(?:исполнительн\w*|исп\.?)\s*схем\w*", re.I)
# Начало таблицы допусков: «Допустимые отклонения СП 70.13330.2012, табл. 5.12»
LIMITS_HEAD = re.compile(r"допустим\w*\s+отклонени\w*", re.I)
LIMITS_SPAN = 1400
MIN_LIMITS = 3           # меньше — обрывок чтения таблицы, а не объявленные допуски
# Допуск: «15 мм», «±12 мм», «-20,+25 мм». Знак сравнения перед числом означает условие
# («h < 200 мм»), а не допуск
# Цифра внутри числа допуском не бывает: в «2000 мм» не должно найтись «000»
LIMIT_RE = re.compile(r"(?<![\d<>=≤≥])(?:±|\+|-)?\s?(\d{1,3})(?:\s*,\s*\+\s?(\d{1,3}))?\s*мм")
COMPARE_BEFORE = re.compile(r"[<>=≤≥]")
COMPARE_SPAN = 10
# Шапка таблицы отклонений: «откл. от пр.отм., мм»
DEV_HEAD = re.compile(r"откл\w*\.?\s*от\s*пр", re.I)
# Строка таблицы: «1(КР-4.1) -3.950 +491 -2.900 +552»
DEV_ROW = re.compile(r"(?<!\d)(\d{1,2})\s*\(([^)\n]{2,24})\)\s*((?:[-+−–]?\s?\d[\d.,]*\s+){1,8})")
# Отметка, а не отклонение: «-3.950», «-2,900» — три знака после разделителя
ELEVATION = re.compile(r"^[-+−–]?\d{1,2}[.,]\d{3}$")
DEVIATION = re.compile(r"^([-+−–])\s?(\d{1,4})$")
# Замечание геодезиста на самом листе
NOTE_RE = re.compile(r"откл\w*\.?\s*превыша\w*\s+допустим\w*", re.I)


def _limits_of(block):
    out = []
    for hit in LIMIT_RE.finditer(block):
        if COMPARE_BEFORE.search(block[max(0, hit.start() - COMPARE_SPAN):hit.start()]):
            continue           # «h < 200 мм» — размер конструкции, а не допуск
        for group in (1, 2):
            if hit.group(group):
                out.append((int(hit.group(group)), " ".join(block[max(0, hit.start() - 70):hit.end()].split())))
    return out


def declared_limits(flat):
    """Допуски, объявленные на листе, в миллиметрах: [(число, фрагмент)].

    Текст страницы бывает склейкой распознавания и модели (`text_source: UNION`), и тогда
    таблица допусков встречается дважды: у Tesseract обрывками среди чисел чертежа, у модели
    целиком. Берётся то вхождение, где разобралось больше строк: обрывок даёт один-два допуска
    и ложный порог.
    """
    best = []
    for m in LIMITS_HEAD.finditer(flat):
        got = _limits_of(flat[m.start():m.start() + LIMITS_SPAN])
        if len(got) > len(best):
            best = got
    return best


def deviations(flat):
    """Отклонения из таблицы схемы: [{mark, values, snippet}]. Пусто, если шапки нет."""
    if not DEV_HEAD.search(flat):
        return []
    out = []
    for m in DEV_ROW.finditer(flat):
        numbers = m.group(3).split()
        values = []
        for token in numbers:
            token = token.replace("−", "-").replace("–", "-").strip(",;")
            if ELEVATION.match(token):
                continue       # проектная отметка, не отклонение
            dev = DEVIATION.match(token)
            if dev:
                values.append(int(dev.group(1).replace("−", "-").replace("–", "-") + dev.group(2)))
        if values:
            out.append({"mark": f"{m.group(1)}({m.group(2).strip()})", "values": values,
                        "snippet": " ".join(m.group(0).split())})
    return out


def excesses(limits, rows):
    """Отклонения больше наибольшего допуска: (порог, [(марка, значение, фрагмент)])."""
    if not limits or not rows:
        return None, []
    bar = max(n for n, _ in limits)
    out, seen = [], set()
    for r in rows:
        for v in r["values"]:
            # текст страницы бывает склейкой распознавания и модели, и та же строка таблицы
            # разбирается дважды: «3(ЗД4.1) -459» и «3(304.1) -459» — одно и то же отклонение
            key = (re.sub(r"[^\d]", "", r["mark"]), v)
            if abs(v) > bar and key not in seen:
                seen.add(key)
                out.append((r["mark"], v, r["snippet"]))
    return bar, sorted(out, key=lambda x: -abs(x[1]))


def sheet_findings(object_id, file_id, page, flat, document=None):
    """Запись по одному листу исполнительной схемы или пустой список."""
    if not SCHEME_RE.search(flat):
        return []
    limits = declared_limits(flat)
    rows = deviations(flat)
    # Таблица 5.12 объявляет допуски строками; разобранные один-два — обрывок чтения, и
    # порог по нему выдумывать нельзя: на листе С2_ВК от 01.07 из шума Tesseract разбирался
    # допуск 45 мм, которого в таблице нет, и он поднимал порог выше настоящих 15 мм
    trusted = len({n for n, _ in limits}) >= MIN_LIMITS
    bar, over = excesses(limits, rows) if trusted else (None, [])
    note = bool(NOTE_RE.search(flat))
    if not over and not note:
        return []
    shown = "; ".join(f"{mark} {value:+d} мм" for mark, value, _ in over[:6])
    more = f" и ещё {len(over) - 6}" if len(over) > 6 else ""
    if over:
        label, result = "VIOLATION_PRESENT", "VALUE_MISMATCH"
        detail = (f"наибольший допуск листа {bar} мм, из {sum(len(r['values']) for r in rows)} отклонений "
                  f"{len(over)} больше него: {shown}{more}")
    elif not trusted:
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = (f"таблица допусков прочитана не целиком: разобрано допусков "
                  f"{len({n for n, _ in limits})}, порог по такому обрывку не назначается. "
                  f"Числа на растровой схеме читает мультимодальная модель")
    else:
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = (f"наибольший допуск листа {bar} мм, но таблица отклонений не разобрана: "
                  f"числа на растровой схеме без чтения моделью не читаются")
    if note:
        detail += "; геодезист на листе пометил превышение допусков"
    limits_text = ", ".join(f"{n} мм" for n in sorted({n for n, _ in limits}))
    return [{
        "finding_id": f"{object_id}::TOLERANCE::{file_id}-{page}",
        "object_id": object_id,
        "matrix_scope": "FREE_SEARCH",
        "parameter_code": FREE_CODE,
        "parameter_id": None,
        "title": TITLE,
        "comparison_result": result or "VALUE_MISMATCH",
        "location_type": "OBJECT",
        "locations": ["SITE"],
        "pd_value": f"допуски листа: {limits_text}" if limits else None,
        "rd_value": None,
        "id_value": f"{over[0][1]:+d} мм" if over else None,
        "violation_label": label,
        # Кода параметра в каталоге нет, критичность оттуда не приходит, а без неё статус
        # протокола остаётся пустым и теряет балл за «значение и статус». Берём ту же, что
        # в эталонном перечне (VS-0021): геометрическое отклонение требует утверждения
        "criticality": ("Существенное (предписание) — требует утверждения"
                        if label == "VIOLATION_PRESENT" else None),
        "finding_status": "CANDIDATE",
        "needs_expert": True,
        "evidence": [{"stage": "ID", "file_id": file_id, "pdf_page_number": page,
                      "quote": (over[0][2] if over else shown or detail)[:300],
                      "localization": "PAGE_LEVEL"}],
        "extraction": {
            "rule_basis": "отклонения исполнительной схемы против допусков, объявленных на том же листе",
            "detail": detail,
            "document": document,
            "limits": [n for n, _ in limits],
            "bar_mm": bar,
            "over": [{"mark": mark, "value": value} for mark, value, _ in over],
            "sheet_note": note,
            # значение прочитано машиной: на растровой схеме цифры читает модель (Р-40)
            "id": {"raw": f"{over[0][1]:+d}" if over else None, "text_source": "RECOGNIZED"},
        },
    }]


def findings(object_id, documents, page_text):
    """Записи по всем исполнительным схемам объекта. page_text(file_id, page) → текст страницы."""
    out = []
    for doc in documents:
        if doc.get("stage") != "ID" or doc.get("duplicate_of"):
            continue
        if (doc.get("extension") or "").lower() != ".pdf":
            continue
        if not SCHEME_RE.search(doc.get("relative_path") or ""):
            continue                      # схему видно по имени файла, читать весь комплект незачем
        name = (doc.get("relative_path") or "").replace("\\", "/").split("/")[-1]
        for page in range(1, int(doc.get("pdf_pages") or 0) + 1):
            text = page_text(doc["file_id"], page)
            if not text:
                continue
            out += sheet_findings(object_id, doc["file_id"], page, tep.flatten(text), name)
    return out
