"""Акт освидетельствования скрытых работ из PDF. Задача #73.

Разбор актов написан под XML (`pipeline/aosr_xml.py`), и в корпусе XML есть только
у Октябрьской: 18 актов. У Новослободской те же акты лежат PDF — 80 файлов, — и в сверку
с рабочей документацией они не попадали вовсе. Форма акта утверждена приказом Минстроя,
и в тексте у неё устойчивые пункты:

    АКТ освидетельствования скрытых работ № 1БТ от 17.04.2026
    1. К освидетельствованию предъявлены следующие работы: Бетонирование технологической
       дороги 1-2.8/А-1.Л (наименование скрытых работ)
    2. Работы выполнены по проектной документации 17_ПД/25-СВГ - Стена в грунте, ООО «ВЕЛЕС»
    3. При выполнении работ применены: БСТ В15П4F(I)150W6 Документ о качестве бетонной
       смеси … партии №18-000001597 от 07.02.2026

Отсюда те же поля, что даёт XML: номер и дата акта, работы, шифр раздела с листами
и применённые материалы. Запись той же формы, поэтому сверка `pipeline/acts_check.py`
принимает её без изменений.

## Чего разбор не делает

Он не читает сканы: акт без текстового слоя пропускается — в записи это видно счётчиком.
Документы о качестве из строки материалов вырезаются: это подтверждение поставки, а не
применённое изделие, и на листе рабочей документации их номеров нет никогда. Прочерк
(«-------») материалом не считается.
"""
import os
import re

TITLE_RE = re.compile(r"акт\w*\s+освидетельствования\s+скрытых\s+работ", re.I)
NUMBER_RE = re.compile(r"освидетельствования\s+скрытых\s+работ\s*№?\s*([0-9][^\s]{0,12}?)\s*(?:от\s+(\d{2}\.\d{2}\.\d{4}))?[\s(]", re.I)
NAME_NUMBER_RE = re.compile(r"№\s*([0-9][A-Za-zА-Яа-яЁё0-9./-]{0,12})")
NAME_DATE_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})")
# Дата сразу за номером, без «от»: «№ 52 20.04.2026 г.», «№ 4.2-ОВ2/К9 « 29 » октября 2025 г.»,
# «№ 1-ВК/К2/К9 21 февраля 2025 г.» — так у актов в DOCX (#112). Незаполненная «« » 20 г.» — не дата
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
          "октября", "ноября", "декабря")
AFTER_DATE_RE = re.compile(r"^\s*(?:от\s+)?(?:(\d{2}\.\d{2}\.\d{4})|[«\"]?\s*(\d{1,2})\s*[»\"]?\s+("
                           + "|".join(MONTHS) + r")\s+(\d{4}))", re.I)
WORKS_RE = re.compile(r"1\.\s*К\s+освидетельствованию\s+предъявлены\s+следующие\s+работы[:\s]*(.{0,400}?)"
                      r"\s*\(наименование\s+скрытых\s+работ", re.I | re.S)
DOCS_RE = re.compile(r"2\.\s*Работы\s+выполнены\s+по\s+проектной\s+документации[:\s]*(.{0,300}?)"
                     r"\s*\((?:номер|наименование)", re.I | re.S)
MATERIALS_RE = re.compile(r"3\.\s*При\s+выполнении\s+работ\s+применены[:\s]*(.{0,600}?)"
                          r"\s*\(наименование\s+строительных\s+материалов", re.I | re.S)
# «Документ о качестве бетонной смеси … партии №18-000001597 от 07.02.2026» — подтверждение
# поставки, а не применённое изделие
QUALITY_DOC_RE = re.compile(r"(?:документ\w*|паспорт\w*|сертификат\w*|протокол\w*)\s+(?:о\s+качестве|качества|соответствия|испытани\w*)"
                            r"[^;]*?(?=\s\d+\.\s|$)", re.I)
# Тот же документ о качестве в конце названия материала: «Арматура А500С d10 Сертификат
# качества» — название кончается там, где начинается документ
TRAILING_DOC_RE = re.compile(r"\s*(?:документ\w*|паспорт\w*|сертификат\w*|протокол\w*)\s+"
                             r"(?:о\s+качестве|качества|соответствия|испытани\w*).*$", re.I)
# Хвост реквизитов документа о качестве: «№МА000020387 от 23.04.2026», «( , №18-000001597»
DOC_TAIL_RE = re.compile(r"[(\s,]*№\s?[A-Za-zА-Яа-яЁё0-9-]+\s*(?:от\s*\d{2}\.\d{2}\.\d{4})?\s*\)?", re.I)
# Нумерация перечня: «1. Инъекционная система…»
ITEM_RE = re.compile(r"(?:^|\s)(\d{1,2})\.\s+")
SHEET_RE = re.compile(r"(?:лист\w*|\bл\.)\s*№?\s*([0-9]{1,3}(?:\s*[,;]\s*[0-9]{1,3})*)", re.I)
# Шифр раздела: «17_ПД/25-СВГ», «23.009-Р-ГИ», «01-07_23-14-РД-ОК»
CODE_RE = re.compile(r"(?<![\w/-])([0-9][0-9A-Za-zА-Яа-яЁё._/-]{4,40}?)(?=\s*[-–—]\s|\s*,|\s*$)")
DASHES_RE = re.compile(r"^[\s\-–—_.]*$")
LEAD_O_RE = re.compile(r"(?<![\wА-Яа-яЁё])[ОO](?=\d)")
# Не материал, а отсылка формы: «в случае если необходимо указывать более 5 документов,
# указывается ссылка на реестр». В актах Новослободской так написано 43 раза
NOT_MATERIAL_RE = re.compile(r"^(?:перечислен\w*|указан\w*|см\.|согласно|приложени\w*|реестр\w*"
                             r"|документ\w*|паспорт\w*|сертификат\w*|протокол\w*)\b", re.I)
MAX_PAGES = 3            # форма акта умещается в первые страницы; дальше идут приложения
# Форматы актов: PDF (#73), DOCX и DOC (#112). У Полярной 25, ДОО 57 актов скрытых работ лежат в DOCX,
# и в сверку с рабочей документацией они не попадали: разбор брал только PDF
TEXT_EXT = (".pdf", ".docx", ".doc")
# имя файла называет акт — тогда номер в имени это номер акта, а не реестра («Реестр №1 ЭМ-К9»)
ACT_NAME_RE = re.compile(r"аоср|(?<![а-яё])акт", re.I)
LEAD_RE = re.compile(r"\d+")
FREE_NUMBER_CODE = "FREE-ID-002"
FREE_NUMBER_TITLE = "Номер акта в имени файла не совпадает с номером в документе"


def looks_like_act(flat):
    return bool(TITLE_RE.search(flat or ""))


def _clean(text):
    return " ".join((text or "").replace(" ", " ").split())


def materials(flat):
    """Применённые материалы: строка пункта 3 без документов о качестве."""
    m = MATERIALS_RE.search(flat or "")
    if not m:
        return []
    body = QUALITY_DOC_RE.sub(" ", _clean(m.group(1)))
    body = DOC_TAIL_RE.sub(" ", body)
    # Перечень разбивается по нумерации и точке с запятой, но не по запятой: «Бетон-В15,
    # F150, W6» — это одна марка бетона, а не три материала
    parts = re.split(r"\s*;\s*|(?:^|\s)\d{1,2}\.\s+", body)
    out = []
    for part in parts:
        part = _clean(part).strip(" ,;.")
        if not part or DASHES_RE.match(part) or len(part) < 3:
            continue
        part = _clean(TRAILING_DOC_RE.sub("", part)).strip(" ,;.")
        if not part or len(part) < 3 or NOT_MATERIAL_RE.match(part):
            continue
        out.append({"name": part[:200], "quality_documents": []})
    return out[:12]


def sections(flat):
    """Разделы рабочей документации, названные актом: [{code, name, sheets}]."""
    m = DOCS_RE.search(flat or "")
    if not m:
        return []
    # «шифр проекта О4-П.СКБ-ПИР-Р-ВК»: буква О вместо нуля в начале шифра — у 14 актов ДОО в DOCX,
    # и без замены раздел акта не разбирался вовсе (#112, дефект организатора DOO25-F-0007)
    body = LEAD_O_RE.sub("0", _clean(m.group(1)))
    code = CODE_RE.search(body)
    if not code:
        return []
    sheets = []
    for hit in SHEET_RE.finditer(body):
        sheets += [s.strip() for s in re.split(r"[,;]", hit.group(1)) if s.strip()]
    name = _clean(body[code.end():].lstrip(" -–—,"))
    return [{"code": code.group(1).strip(" .,"), "name": name[:160], "sheets": sheets}]


def works(flat):
    m = WORKS_RE.search(flat or "")
    if not m:
        return []
    body = _clean(m.group(1))
    return [{"name": body[:200], "place": None}] if body and not DASHES_RE.match(body) else []


def parse(flat, file_name=""):
    """Запись акта той же формы, что даёт XML, или None, если это не акт."""
    flat = _clean(flat)
    if not looks_like_act(flat):
        return None
    number = date = None
    m = NUMBER_RE.search(flat)
    if m:
        number, date = m.group(1).strip(" .,"), m.group(2) or after_date(flat[m.end(1):])
    if not number:
        m = NAME_NUMBER_RE.search(file_name or "")
        number = m.group(1) if m else None
    if not date:
        m = NAME_DATE_RE.search(file_name or "")
        date = m.group(1) if m else None
    rec = {"act_number": number, "act_date": date, "works": works(flat),
           "documentation_sections": sections(flat), "materials": materials(flat),
           "regulations": [], "schemas": [], "source": "PDF"}
    in_name = name_number(file_name)
    if in_name and number and _lead(in_name) != _lead(number) and m_in_text(flat):
        rec["number_in_filename"] = in_name
    return rec


def after_date(rest):
    """Дата составления акта, записанная сразу за номером: «дд.мм.гггг» или None."""
    m = AFTER_DATE_RE.match(rest[:60])
    if not m:
        return None
    if m.group(1):
        return m.group(1)
    return f"{int(m.group(2)):02d}.{MONTHS.index(m.group(3).lower()) + 1:02d}.{m.group(4)}"


def _lead(number):
    m = LEAD_RE.search(number or "")
    return m.group(0).lstrip("0") or "0" if m else None


def m_in_text(flat):
    """Номер акта взят из текста, а не из имени файла."""
    return NUMBER_RE.search(flat) is not None


def name_number(file_name):
    """Номер акта из имени файла, если имя называет акт: «4. АОСР №1 Монтаж креплений» → «1»."""
    if not ACT_NAME_RE.search(file_name or ""):
        return None
    m = NAME_NUMBER_RE.search(file_name or "")
    return m.group(1).strip(" .,") if m else None


def number_findings(object_id, rows):
    """Акты, у которых номер в имени файла не тот, что в самом документе (#112).

    Организатор отмечает это дефектом комплекта (DOO25-F-0008, `DATASET_DEFECT_CONFIRMED`):
    «4. АОСР №1 Монтаж креплений» внутри — акт № 6-ОВ2/К7. Сравнивается ведущий номер: «№4» в имени
    и «4-ВК/К2/К9» в тексте — один акт. Нарушением правил это не объявляется и в сдачу не идёт:
    это запись для инспектора о качестве комплекта ИД.
    """
    out = []
    for r in rows:
        in_name = r.get("number_in_filename")
        if not in_name:
            continue
        name = os.path.basename(r.get("relative_path") or "")
        out.append({
            "finding_id": f"{object_id}::ACT-NUMBER::{r.get('file_id')}",
            "object_id": object_id,
            "matrix_scope": "FREE_SEARCH",
            "parameter_code": FREE_NUMBER_CODE,
            "parameter_id": None,
            "title": FREE_NUMBER_TITLE,
            "comparison_result": "VALUE_MISMATCH",
            "location_type": "DOCUMENT",
            "locations": [name],
            "pd_value": None, "rd_value": None,
            "id_value": f"в имени № {in_name}, в документе № {r.get('act_number')}",
            "violation_label": "VIOLATION_PRESENT",
            "criticality": None,
            "finding_status": "SUSPICION",
            "needs_expert": True,
            "for_submission": False,
            "evidence": [{"stage": "ID", "file_id": r.get("file_id"), "pdf_page_number": 1,
                          "quote": f"акт освидетельствования скрытых работ № {r.get('act_number')}",
                          "localization": "PAGE_LEVEL"}],
            "extraction": {"rule_basis": "номер акта в имени файла против номера в тексте акта",
                           "detail": f"имя файла «{name}» называет акт № {in_name}, "
                                     f"а в документе — акт № {r.get('act_number')}",
                           "source": r.get("source")},
        })
    return out


def scan(documents, page_texts):
    """Акты из PDF, DOCX и DOC исполнительной документации: (записи, сводка).

    `page_texts(doc)` — итератор (страница, текст) документа; читаются первые страницы.
    """
    out, stats = [], {"файлов ИД": 0, "актов": 0, "без текста": 0, "с материалами": 0,
                      "с разделом": 0}
    for doc in documents:
        if doc.get("stage") != "ID" or doc.get("duplicate_of"):
            continue
        ext = (doc.get("extension") or "").lower()
        if ext not in TEXT_EXT:
            continue
        stats["файлов ИД"] += 1
        parts = []
        for page_no, text in page_texts(doc):
            if page_no > MAX_PAGES:
                break
            parts.append(text or "")
        flat = _clean(" ".join(parts))
        if not flat:
            stats["без текста"] += 1
            continue
        rec = parse(flat, os.path.basename(doc.get("relative_path") or ""))
        if not rec:
            continue
        rec["relative_path"] = doc.get("relative_path")
        rec["file_id"] = doc.get("file_id")
        rec["source"] = ext[1:].upper()
        stats["актов"] += 1
        stats["с материалами"] += bool(rec["materials"])
        stats["с разделом"] += bool(rec["documentation_sections"])
        out.append(rec)
    return out, stats
