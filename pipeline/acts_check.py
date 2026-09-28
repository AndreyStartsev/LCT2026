"""Сверка актов освидетельствования с рабочей документацией. Задача #42.

Акт освидетельствования сам говорит, какой лист какой рабочей документации он
подтверждает, и чем работы выполнены:

    раздел 23.009-Р-ГИ, лист 2
    работы    «Устройство гидрошпонки ХВС 150/1»
    материалы «Шпонка гидроизоляционная ИКОПАЛ ХВС-150/1», «Бетон-В15, F150, W6»

Отсюда две проверки, для которых не нужно ни распознавание, ни разбор основной
надписи:

1. **Лист есть в рабочей документации.** Акт ссылается на шифр и лист; если такого
   листа в комплекте нет, освидетельствовано то, чего в рабочей документации не видно.
2. **Материал акта назван на этом листе.** У материала берётся марка — часть
   с цифрами: «ХВС-150/1», «В15», «F150». Если марка на листе не названа, это кандидат
   для инспектора: применено не то, что запроектировано, либо лист читается не полностью.

Чего проверка не делает. Она не объявляет нарушение: в рабочей документации изделие
часто названо обобщённо («инъекционная трубка», «инъекционный штуцер»), а в акте — маркой
поставщика («WPI-Инжектосистема»), и хуже ли применённое проектного, решает специалист.
Поэтому расхождение выдаётся как «сравнение невозможно» с пометкой `needs_expert`
и доказательствами обеих сторон. Комплект без текстового слоя несовпадением не считается:
там нечего искать.
"""
import collections
import re
import unicodedata

# Марка материала — часть с цифрами: «ХВС-150/1», «В15», «F150», «W6».
MARK_RE = re.compile(r"[A-Za-zА-Яа-яЁё]*\d[A-Za-zА-Яа-яЁё0-9]*(?:[./-]\d+)*")
MIN_MARK = 2
# Название изделия: слово из заглавных или латиницей — «ИКОПАЛ», «Icopal», «WPI».
# Обычные слова («гидроизоляционная») в счёт не идут: они найдутся на любом листе
BRAND_RE = re.compile(r"(?:[A-Z][A-Za-z]{2,}|[А-ЯЁ]{3,})")
GENERIC = {"БЕТОН", "ШПОНКА", "СИСТЕМА", "СМЕСЬ", "МАРКА", "КЛАСС", "ГОСТ", "ТУ",
           "ГИДРОШПОНКА", "ПВХ", "ХВС", "БСТ"}
MAX_PAGES = 300          # сколько страниц комплекта просматривать в поисках марки
# класс бетона в акте и на листе: «Бетон-В15», «БСТ В30 П4», «бетон класса В25»
CONCRETE_RE = re.compile(r"(?<![A-Za-zА-Яа-яЁё0-9])[ВB]\s?(\d{1,3})(?![\d,.])")


def concrete_classes(text):
    """Классы бетона, названные в тексте: {15, 30}."""
    return {int(m.group(1)) for m in CONCRETE_RE.finditer(str(text or ""))
            if 3 <= int(m.group(1)) <= 100}
FREE_CODE = "FREE-ID-001"
TITLE = "Материал акта освидетельствования не назван на листе рабочей документации"


def norm(text):
    """Сведение к одному виду: латинские близнецы к кириллице, разделители убраны."""
    t = unicodedata.normalize("NFC", str(text or "")).upper()
    t = t.translate(str.maketrans({"A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К",
                                   "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У"}))
    return re.sub(r"[\s.,/\\-]+", "", t)


def sheet_index(rows):
    """Связка «шифр + лист» → (file_id, страница). Первая страница листа выигрывает."""
    out = {}
    for r in rows:
        code, sheet = r.get("document_code"), r.get("document_sheet_number")
        if not code or sheet is None:
            continue
        out.setdefault((norm(code), str(sheet)), (r["file_id"], r["pdf_page_number"]))
    return out


def marks(name):
    """Отличительные части названия материала: марки с цифрами и название изделия."""
    text = str(name or "")
    out = [m.group(0) for m in MARK_RE.finditer(text) if len(m.group(0)) >= MIN_MARK]
    out += [m.group(0) for m in BRAND_RE.finditer(text)
            if norm(m.group(0)) not in GENERIC and len(m.group(0)) >= 3]
    return out


def code_pages(rows):
    """Страницы комплекта по шифру: {шифр → [(file_id, страница)]}."""
    out = collections.defaultdict(list)
    for r in rows:
        if r.get("document_code"):
            out[norm(r["document_code"])].append((r["file_id"], r["pdf_page_number"]))
    return out


RD_STAGES = ("RD", "RD_ID_MIXED")


def rd_sheets(rows, stage_of):
    """Связка листов без исполнительной документации: материал акта ищется в РД, а не в ИД.

    У актов и схем ИД в основной надписи бывает шифр комплекта РД, к которому они выпущены,
    и тогда акт «подтверждал» сам себя: у Новослободской все 12 актов из PDF, у Октябрьской
    № 50 и 60 (рецензия слияния 24.09). Берутся только документы рабочей стадии; смешанные
    папки «РД и ИД» (`RD_ID_MIXED`) тоже — у Тюменской-5 в них лежат все тома РД ОВ. Том проекта
    с тем же шифром подтверждением не считается. stage_of(file_id) → стадия документа по реестру.
    """
    return [r for r in rows if stage_of(r.get("file_id")) in RD_STAGES]


def act_sheets(act):
    """Пары «шифр раздела, лист», названные актом."""
    out = []
    for sec in act.get("documentation_sections") or []:
        code = sec.get("code")
        if not code:
            continue
        for sheet in sec.get("sheets") or []:
            out.append((code, str(sheet)))
        if not sec.get("sheets"):
            out.append((code, None))
    return out


def check(object_id, acts, sheets, page_text, act_file_id=None):
    """Находки по актам. page_text(file_id, page) → текст страницы или пустая строка.

    act_file_id(act) → идентификатор файла акта в реестре объекта, чтобы доказательство
    ссылалось на сам акт, а не только на лист рабочей документации.
    """
    index = sheet_index(sheets)
    pages_by_code = code_pages(sheets)
    out = []
    stats = collections.Counter()
    for act in acts:
        named = [m.get("name") for m in act.get("materials") or [] if m.get("name")]
        # Материал без марки и без названия изделия проверить нечем: «Сетка стальная сварная»
        # не найдётся ни на одном листе не потому, что её там нет, а потому, что искать нечего.
        # Такой акт молчит, и это видно счётчиком (#73)
        materials = [name for name in named if marks(name)]
        pairs = act_sheets(act)
        if named and not materials:
            stats["материалы без марки"] += 1
            continue
        if not materials:
            stats["без материалов"] += 1
            continue
        for code, sheet in pairs:
            stats["ссылок на листы"] += 1
            key = (norm(code), sheet) if sheet else None
            place = index.get(key) if key else None
            number = act.get("act_number")
            loc = f"Акт № {number}" if number else "Акт освидетельствования"
            evidence = []
            fid = act_file_id(act) if act_file_id else None
            if fid:
                evidence.append({"stage": "ID", "file_id": fid, "pdf_page_number": 1,
                                 "quote": "; ".join(materials)[:300], "localization": "DOCUMENT_LEVEL"})
            rd_fid = rd_page = None
            if sheet is None:
                # Акт назвал комплект, но не лист: так написаны все акты Новослободской
                # («Работы выполнены по проектной документации 17_ПД/25-СВГ»). Это не повод
                # говорить «лист не найден» — материал ищется по всему комплекту (#73)
                if not pages_by_code.get(norm(code)):
                    stats["комплект не найден"] += 1
                    out.append(_finding(object_id, act, loc, code, sheet, materials, evidence,
                                        "COMPARISON_IMPOSSIBLE", None,
                                        f"комплект {code} в рабочей документации не найден"))
                    continue
                stats["лист не назван"] += 1
            elif place is None:
                stats["лист не найден"] += 1
                out.append(_finding(object_id, act, loc, code, sheet, materials, evidence,
                                    "COMPARISON_IMPOSSIBLE", None,
                                    f"лист {sheet} комплекта {code} в рабочей документации не найден"))
                continue
            else:
                rd_fid, rd_page = place
                evidence.append({"stage": "RD", "file_id": rd_fid, "pdf_page_number": rd_page,
                                 "quote": f"{code}, лист {sheet}", "localization": "PAGE_LEVEL"})
            # Класс бетона сравнивается с листом, который назвал сам акт: если на листе
            # класс назван и он выше применённого, это понижение класса в работах (#42)
            act_concrete = concrete_classes(" ".join(materials))
            sheet_concrete = concrete_classes(page_text(rd_fid, rd_page)) if rd_fid else set()
            if act_concrete and sheet_concrete and min(act_concrete) < min(sheet_concrete):
                stats["класс бетона ниже"] += 1
                out.append(_finding(object_id, act, loc, code, sheet, materials, evidence,
                                    "VIOLATION_PRESENT", "CLASS_DOWNGRADE",
                                    f"в акте бетон B{min(act_concrete)}, на листе {sheet} "
                                    f"комплекта {code} — B{min(sheet_concrete)}",
                                    needs_expert=True))
                continue
            # Материал ищется по всему комплекту, а не только на названном листе: лист —
            # это чертёж с размерами, а материал назван в общих указаниях или спецификации
            found_on, read = {}, 0
            for fid, page in pages_by_code.get(norm(code), [])[:MAX_PAGES]:
                text = norm(page_text(fid, page))
                if not text:
                    continue
                read += 1
                for name in materials:
                    if name in found_on:
                        continue
                    if any(norm(mark) in text for mark in marks(name)):
                        found_on[name] = (fid, page)
            if not read:
                stats["комплект без текста"] += 1
                out.append(_finding(object_id, act, loc, code, sheet, materials, evidence,
                                    "COMPARISON_IMPOSSIBLE", None,
                                    f"в комплекте {code} нет прочитанного текста"))
                continue
            missing = [name for name in materials if name not in found_on]
            if missing:
                stats["материал не найден"] += 1
                # Нарушением это не объявляется: в проекте изделие часто названо обобщённо
                # («инъекционная трубка»), а в акте — маркой поставщика («WPI-Инжектосистема»).
                # Решает специалист, система показывает расхождение с доказательствами (#42)
                out.append(_finding(object_id, act, loc, code, sheet, missing, evidence,
                                    "COMPARISON_IMPOSSIBLE", None,
                                    f"материал акта не назван в комплекте {code} "
                                    f"({read} страниц с текстом): " + "; ".join(missing[:3])
                                    + "; в рабочей документации изделие может быть названо обобщённо",
                                    needs_expert=True))
            else:
                where = sorted(set(found_on.values()))[:2]
                for fid, page in where:
                    evidence.append({"stage": "RD", "file_id": fid, "pdf_page_number": page,
                                     "quote": "; ".join(materials)[:200], "localization": "PAGE_LEVEL"})
                stats["материал подтверждён"] += 1
                out.append(_finding(object_id, act, loc, code, sheet, materials, evidence,
                                    "NO_VIOLATION", "EQUAL_PD_RD",
                                    f"материалы акта названы в комплекте {code}"))
    return out, dict(stats)


def _finding(object_id, act, loc, code, sheet, materials, evidence, label, result, detail,
             needs_expert=False):
    number = act.get("act_number") or act.get("act_uuid", "")[:8]
    return {
        "finding_id": f"{object_id}::ACT::{re.sub(r'[^A-Za-zА-Яа-я0-9]+', '-', str(number))}"
                      f"::{norm(code)}-{sheet or 'x'}",
        "object_id": object_id,
        "matrix_scope": "FREE_SEARCH",
        "parameter_code": FREE_CODE,
        "parameter_id": None,
        "title": TITLE,
        "comparison_result": result or "VALUE_MISMATCH",
        "location_type": "CONSTRUCTION_ELEMENT",
        "locations": [loc],
        "pd_value": None,
        "rd_value": f"{code}, лист {sheet}" if sheet else code,
        "id_value": "; ".join(materials)[:300],
        "violation_label": label,
        "criticality": None,
        "finding_status": "CANDIDATE",
        "needs_expert": bool(needs_expert),
        "evidence": evidence,
        "extraction": {"rule_basis": "акт освидетельствования против листа рабочей документации",
                       "detail": detail,
                       "act_number": act.get("act_number"),
                       "act_date": act.get("act_date"),
                       "works": [w.get("name") for w in act.get("works") or []]},
    }
