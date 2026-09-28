"""Стадия, дисциплина и редакция документа, цепочки редакций. Задача #10.

Сравнивать можно только сопоставимые документы: одна стадия, одна марка, актуальная
редакция. Этот модуль для каждого документа объекта определяет стадию, марку и раздел,
разбирает отметки редакции, собирает документы одной марки в цепочку и решает,
какая редакция актуальна. Если порядок не выводится однозначно, цепочка получает
статус «требует уточнения» с причиной, а не догадку.

Правила работают без реестра организатора: на новом объекте его не будет.
Реестр используется только для проверки.

Признаков редакции три, и ни один не главный:
  отметки в имени файла    «изм. 4_в1», «кор.3_Корр. 1», «корр.ГИП», «ИЗМ ПО ЗАМЕЧАНИЯМ»
  таблица изменений штампа номера в колонке «Изм.» над основной надписью
  близость по содержимому  одинаковый набор шифров на страницах и почти равное число страниц

Четвёртый признак — папка выпуска (#110): «Архив» внутри стадии держит прежние редакции,
«ПД 2022» и «ПД 2025» — два выпуска проекта со своими заключениями экспертизы, «Корр1» и «Корр2» —
корректировки одного выпуска. Разные выпуски сравниваются по папке, а не по отметкам в имени:
нумерация изменений в новом выпуске начинается заново.

Порядок редакций частичный. Корректировки («кор», «корр.ГИП», переиздание по замечаниям)
и изменения («изм») между собой не сравниваются: «ОПЗ Изм 2» и «ОПЗ-кор3» одного объекта
не упорядочить без внешнего основания. Версия («в1», «вер 2») сравнивается, только когда
корректировка и изменение равны. Дата используется, когда отметок нет, и проверяет порядок,
когда отметки есть.
"""
import collections
import math
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import registry  # noqa: E402


# ------------------------------------------------------------------ отметки в имени

_L = r"(?<![А-Яа-яЁёA-Za-z])"          # слева не буква: подчёркивание и цифра допустимы

BY_COMMENTS_RE = re.compile(r"изм\.?\s*по\s*замечани\w*", re.I)
GIP_RE = re.compile(_L + r"корр?\.?\s*ГИП", re.I)
CHANGE_RE = re.compile(_L + r"изм(?:енение)?\.?\s*№?\s*(\d{1,2})(?!\d)", re.I)
CORRECTION_RE = re.compile(_L + r"корр?\.?\s*(\d{1,2})(?!\d)", re.I)
GENERIC_CORR_RE = re.compile(_L + r"корр?\.?(?![А-Яа-яЁё])", re.I)
# Одна буква «в» только строчная: заглавные «В1», «К1», «Т3» после марки это обозначения
# систем водопровода, канализации и теплоснабжения, а не версия и не корректировка
VERSION_RE = re.compile(_L + r"(?:(?i:вер(?:сия)?)|в)\.?\s*(\d{1,2})(?![\d.])")
PACKAGE_RE = re.compile(r"^V(\d{1,2})_")
# Латинские отметки, обычные у зарубежных и BIM-проектировщиков: «rev.2», «Rev B», «_v2», «ver 3».
# Буквенная ревизия считается по порядку: A — 1, B — 2. Только после разделителя, чтобы «Rev»
# внутри слова и «v» в шифре не читались как отметка
REV_LAT_RE = re.compile(r"(?<![A-Za-zА-Яа-яЁё\d])rev(?:ision)?\.?\s*(?:(\d{1,2})|([A-Z]))(?![A-Za-z\d])", re.I)
VERSION_LAT_RE = re.compile(r"(?<![A-Za-zА-Яа-яЁё\d])(?:ver(?:sion)?|v)\.?\s*(\d{1,2})(?![\d.])", re.I)
EDITED_RE = re.compile(r"(?<![А-Яа-яЁё])РЕД(?![А-Яа-яЁё])")
APPROVAL_RES = [
    (re.compile(r"ЭЦП"), "E_SIGNATURE"),
    (re.compile(r"(?<![А-Яа-яЁё])МГЭ(?![А-Яа-яЁё])"), "STATE_EXPERTISE"),
    (re.compile(r"(?<![А-Яа-яЁё])РнС(?![а-яё])"), "BUILDING_PERMIT_PACKAGE"),
    (re.compile(r"в\s+производство", re.I), "ISSUED_FOR_CONSTRUCTION"),
]
COPY_RE = re.compile(r"\s*\((\d{1,2})\)")
COMP_RE = re.compile(r"\s*\(comp\)", re.I)
YEAR_SUFFIX_RE = re.compile(r"(?:\s\(?(20\d{2})\)?)$")

_MONTHS = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "май": 5, "мая": 5, "июн": 6,
           "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}
ISO_DATE_RE = re.compile(r"(?<!\d)(20\d{2})([-_.])(\d{1,2})\2(\d{1,2})(?!\d)")
DMY_DATE_RE = re.compile(r"(?<![\d.])(\d{1,2})(\.)(\d{1,2})\.((?:20)?\d{2})(?![\d.])")
# через подчёркивание только с полным годом: «01_07_23_14» это шифр проекта, а не 1 июля 2023
DMY_UNDERSCORE_RE = re.compile(r"(?<![\d_])(\d{1,2})(_)(\d{1,2})_(20\d{2})(?![\d_])")
COMPACT_DATE_RE = re.compile(r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)")
MONTH_DATE_RE = re.compile(r"(январ|феврал|март|апрел|май|мая|июн|июл|август|сентябр|октябр|ноябр|декабр)"
                           r"[а-яё]*\s+(20\d{2})", re.I)


def _nfc(s):
    return unicodedata.normalize("NFC", s or "")


def _stem(filename):
    name = _nfc(os.path.basename(filename))
    while True:
        base, ext = os.path.splitext(name)
        if ext.lower() in (".pdf", ".docx", ".xml", ".xlsx", ".doc") and base:
            name = base
        else:
            return name


def _valid(y, m, d):
    return 2015 <= y <= 2030 and 1 <= m <= 12 and 1 <= d <= 31


def _blank(text, span):
    a, b = span
    return text[:a] + " " * (b - a) + text[b:]


def parse_name(filename):
    """Отметки редакции, даты и признаки копии из имени файла.

    Возвращает словарь с разобранными отметками и `rest` — имя без них, из которого
    потом берутся шифр и марка. Отметки вырезаются по месту, чтобы «кор3» в «ПБ1.кор3»
    не превратилось в часть марки.
    """
    stem = _stem(filename)
    s = stem
    out = {"stem": stem, "change": None, "correction": None, "correction_sub": None,
           "version": None, "by_comments": False, "gip": False, "generic_correction": False,
           "edited": False, "package_version": None, "dates": [], "month_date": None,
           "copy_suffix": [], "compressed": False, "year_suffix": None, "approval": []}

    m = PACKAGE_RE.match(s)
    if m:
        out["package_version"] = int(m.group(1))
        s = _blank(s, m.span())

    for rx, tag in APPROVAL_RES:
        for m in list(rx.finditer(s)):
            if tag not in out["approval"]:
                out["approval"].append(tag)
            s = _blank(s, m.span())

    m = BY_COMMENTS_RE.search(s)
    if m:
        out["by_comments"] = True
        s = _blank(s, m.span())
    m = GIP_RE.search(s)
    if m:
        out["gip"] = True
        s = _blank(s, m.span())

    # даты раньше номеров: в «ред_2024-04-08_Вер5_Изм1» дата не должна стать версией
    dates = []
    for rx in (ISO_DATE_RE, DMY_DATE_RE, DMY_UNDERSCORE_RE, COMPACT_DATE_RE):
        for m in list(rx.finditer(s)):
            g = m.groups()
            if rx is ISO_DATE_RE:
                y, mo, d = int(g[0]), int(g[2]), int(g[3])
            elif rx in (DMY_DATE_RE, DMY_UNDERSCORE_RE):
                d, mo, y = int(g[0]), int(g[2]), int(g[3])
                y = y + 2000 if y < 100 else y
            else:
                d, mo, y = int(g[0]), int(g[1]), int(g[2])
            if _valid(y, mo, d):
                dates.append(f"{y:04d}-{mo:02d}-{d:02d}")
                s = _blank(s, m.span())
    m = MONTH_DATE_RE.search(s)
    if m:
        key = next(k for k in _MONTHS if m.group(1).lower().startswith(k))
        out["month_date"] = f"{int(m.group(2)):04d}-{_MONTHS[key]:02d}"
        s = _blank(s, m.span())
    out["dates"] = sorted(set(dates))

    changes = [(m.span(), int(m.group(1))) for m in CHANGE_RE.finditer(s)]
    for m in REV_LAT_RE.finditer(s):
        number, letter = m.group(1), m.group(2)
        changes.append((m.span(), int(number) if number else ord(letter.upper()) - ord("A") + 1))
    for span, n in changes:
        s = _blank(s, span)
    if changes:
        out["change"] = max(n for _, n in changes)

    corrections = [(m.span(), int(m.group(1))) for m in CORRECTION_RE.finditer(s)]
    for span, _ in corrections:
        s = _blank(s, span)
    if corrections:
        out["correction"] = corrections[0][1]
        if len(corrections) > 1:
            out["correction_sub"] = corrections[1][1]

    for rx in (VERSION_RE, VERSION_LAT_RE):
        for m in list(rx.finditer(s)):
            out["version"] = max(out["version"] or 0, int(m.group(1)))
            s = _blank(s, m.span())

    if COMP_RE.search(s):
        out["compressed"] = True
        s = COMP_RE.sub("", s)
    out["copy_suffix"] = [int(x) for x in COPY_RE.findall(s)]
    s = COPY_RE.sub("", s)
    s = re.sub(r"\(\s*\)", " ", s)

    s = s.rstrip(" ._-")
    m = YEAR_SUFFIX_RE.search(s.rstrip())
    if m:
        out["year_suffix"] = int(m.group(1))
        s = _blank(s, m.span())

    if out["correction"] is None and not out["gip"]:
        m = GENERIC_CORR_RE.search(s)
        if m:
            out["generic_correction"] = True
            s = _blank(s, m.span())
    if EDITED_RE.search(s):
        out["edited"] = True
        s = EDITED_RE.sub(" ", s)

    out["rest"] = re.sub(r"\s+", " ", s).strip(" ._-")
    return out


def revision_label(p):
    """Человекочитаемая редакция: «кор. 3.1», «изм. 4, в1», «корр. ГИП»."""
    parts = []
    if p.get("correction") is not None:
        parts.append(f"кор. {p['correction']}" + (f".{p['correction_sub']}" if p.get("correction_sub") else ""))
    if p.get("by_comments"):
        parts.append("переиздание по замечаниям")
    if p.get("gip"):
        parts.append("корр. ГИП")
    if p.get("generic_correction"):
        parts.append("корр.")
    change = p.get("change_effective", p.get("change"))
    if change is not None:
        parts.append(f"изм. {change}")
    if p.get("version") is not None:
        parts.append(f"в{p['version']}")
    return ", ".join(parts) or None


# ------------------------------------------------------------------ шифр и марка

# буквы марки после нормализации латинских омоглифов
_HOMO = str.maketrans("ABCEHKMOPTXaceopxy", "АВСЕНКМОРТХасеорху")

# Марки, известные по ПП 87, ГОСТ 21.101 и корпусу. Значение — раздел.
MARKS = {
    "ПЗ": "PZ", "ОПЗ": "PZ", "СП": "PZ", "ИРД": "PZ", "ПЗЗ": "PZ",
    "ПЗУ": "GP", "СПОЗУ": "GP", "СПЗУ": "GP", "ГП": "GP", "ПП": "GP",
    "АР": "AR", "АС": "AR", "АПР": "AR", "АГР": "AR", "КЕО": "AR",
    "КР": "KR", "КЖ": "KR", "КМ": "KR", "КМД": "KR", "КЖД": "KR", "КЖЛ": "KR", "КК": "KR",
    "ОК": "KR", "ГИ": "KR", "СВГ": "KR", "РС": "KR", "ПГМ": "KR",
    "ЭОМ": "EOM", "ЭМ": "EOM", "ЭО": "EOM", "ЭН": "EOM", "ЭГ": "EOM", "ЭС": "EOM", "ОЗДС": "EOM",
    "ВК": "VK", "НВК": "VK", "ВВ": "VK", "НВ": "VK", "НК": "VK", "НС": "VK", "АУПТ": "VK", "ВПВ": "VK",
    "ОВ": "OV", "ТС": "OV", "НТС": "OV", "ИТП": "OV", "ДУ": "OV", "ХС": "OV", "ОВК": "OV",
    "СС": "SS", "АПС": "SS", "СОУЭ": "SS", "СКС": "SS",
    "ТХ": "TX", "МПТА": "TX", "ВТ": "TX",
    "ПОС": "POS", "ППР": "POS", "СГП": "POS",
    "ПОД": "POD",
    "ООС": "OOS", "ПМООС": "OOS", "ТРПО": "OOS",
    "ПБ": "PB", "МОПБ": "PB", "ППМ": "PB",
    "ОДИ": "ODI", "МОДИ": "ODI",
    "ЭЭ": "EE", "ЭЭФ": "EE",
    "ТБЭ": "BE", "ТБЭО": "BE", "БЭО": "BE", "БЭОКС": "BE", "ТОБЭ": "BE",
    "СМ": "SM",
    "ИОС": None,          # раздел решает номер подраздела, его читает registry.section_with_hint
}
# одна и та же часть проекта под разными буквами
MARK_SYNONYMS = {"СПОЗУ": "ПЗУ", "СПЗУ": "ПЗУ", "ОПЗ": "ПЗ", "МОДИ": "ОДИ",
                 "ТБЭО": "ТБЭ", "БЭО": "ТБЭ", "БЭОКС": "ТБЭ", "ТОБЭ": "ТБЭ"}
STAGE_TOKENS = {"П": "PD", "ПД": "PD", "Р": "RD", "РД": "RD"}
# хвосты марки, которые называют тип документа, а не раздел: «ПБ9.1.ПЗ», «АР-ТЧ», «ОВ1.С»
DOC_TYPE_TAILS = {"ПЗ", "ТЧ", "ГЧ", "СО", "СТ", "С", "ВР", "ОД", "Р", "РР"}

_MARK_TOKEN_RE = re.compile(r"^([А-ЯЁ]{1,6})(\d+(?:\.\d+)*)?((?:\.[А-ЯЁ0-9]+)*)$")
_UNKNOWN_MARK_RE = re.compile(r"^([А-ЯЁ]{2,6})(\d+(?:\.\d+)*)?((?:\.[А-ЯЁ0-9]+)*)$")
_PART_RE = re.compile(r"^К\d$")
_SECTION_PART_RE = re.compile(r"^С\d$")
_TOME_RE = re.compile(r"Том\s*(\d+(?:\.\d+)*)", re.I)
_NUMBERING_RE = re.compile(r"^(?:\d+(?:\.\d+)*\.(?:\s+|(?=[А-ЯЁA-Z])))?(?:Раздел\s+\d+(?:\.\d+)*\s+)?")
_NUMBERING_VALUE_RE = re.compile(r"^(\d+(?:\.\d+)*)\.(?:\s+|(?=[А-ЯЁA-Z]))")
# «Книга 2» и «ПЗ фрагмент 2» — части одного тома, а не его редакции: у ДОО пояснительная
# записка выпуска 2025 разложена на три фрагмента (#110)
_BOOK_RE = re.compile(r"(Книга|фрагмент)\s*(\d+)", re.I)


def _clean(tok):
    return tok.translate(_HOMO).strip("().,;:")


def _mark_token(tok, known_only=True):
    t = _clean(tok)
    m = (_MARK_TOKEN_RE if known_only else _UNKNOWN_MARK_RE).match(t)
    if not m:
        return None
    letters, num, tail = m.group(1), m.group(2) or "", m.group(3) or ""
    if known_only and letters not in MARKS:
        return None
    if not known_only and (letters in MARKS or t in STAGE_TOKENS):
        return None
    return letters, num, tail


def parse_code(rest):
    """Шифр, марка, корпус и стадия из имени без отметок редакции.

    Марка — последний токен с известными буквами до первого описательного слова:
    в «23.009-Р-1-КЖ0.3_С1_Плита техэт» это КЖ0.3, а не С1. Номер тома
    («Том 5.4.2») важнее короткой марки после него: «ОВ» там описание тома.
    """
    text = _NUMBERING_RE.sub("", rest.strip())
    text = re.sub(r"\([^)]*\)", " ", text)                        # «КР (ВП)»: пометка в скобках не марка
    text = re.sub(r"(ИОС)\s+(\d)", r"\1\2", text)                  # «ИОС 4.4» -> «ИОС4.4»
    text = re.sub(r"\s+-", "-", text)                             # «К2 -КЖ5.1»
    tokens = [t for t in re.split(r"[\s_\-/]+", text) if t]

    tome = _TOME_RE.search(rest)
    book = _BOOK_RE.search(rest)
    found, part, section_part, stage_token, descriptors = None, None, None, None, []
    code_end = None
    seen_digits = False
    for i, tok in enumerate(tokens):
        up = _clean(tok)
        if up in STAGE_TOKENS and i > 0:
            stage_token = STAGE_TOKENS[up]
            continue
        mt = _mark_token(tok)
        if not mt and seen_digits and not (found and found[1]):
            # Марка не из списка: «245-0817-КМ-2Н-3-ЗСГО». Без этого маркой становилось
            # «ОК» из шифра проекта, и тома ЗСГО, ТР1, ДПВ1 сливались в одну цепочку.
            mt = _mark_token(tok, known_only=False)
        if mt:
            if found and found[1] and not mt[1] and len(mt[0]) <= 4:
                descriptors.append(mt[0])        # «КЖ0.3 … ОВ» — описание, марка уже есть
                continue
            if i > 0 and _PART_RE.match(_clean(tokens[i - 1])):
                part = _clean(tokens[i - 1])
            found = mt
            code_end = i
            continue
        if re.search(r"\d", tok):
            seen_digits = True
        if found and _SECTION_PART_RE.match(up):
            section_part = up
            continue
        if found and re.search(r"[а-яё]{3,}", tok):
            break                                 # началось описание листа

    mark = None
    if tome and (not found or not found[1]):
        mark = "ТОМ" + tome.group(1)
        if found:
            descriptors.append(found[0])
    elif found:
        letters, num, tail = found
        mark = MARK_SYNONYMS.get(letters, letters) + num + tail

    if book:
        part = (part or "") + ("КН" if book.group(1).lower().startswith("кн") else "ФР") + book.group(2)

    code_tokens = tokens[:code_end + 1] if code_end is not None else []
    code = "-".join(_clean(t) for t in code_tokens) or None
    base_digits = ""
    for t in code_tokens[:-1]:
        up = _clean(t)
        if up in STAGE_TOKENS or _PART_RE.match(up) or _mark_token(t):
            continue                              # «ЖС-РД-270121»: РД здесь часть имени фирмы
        base_digits += re.sub(r"\D", "", t)
    code_base = base_digits.replace("0", "") or None
    if code_base and len(code_base) < 3:
        code_base = None
    numbering = _NUMBERING_VALUE_RE.match(rest.strip())
    return {"code": code, "mark": mark, "part": part, "section_part": section_part,
            "stage_token": stage_token, "descriptors": descriptors, "code_base": code_base,
            "numbering": numbering.group(1) if numbering else None}


def mark_from_code(code):
    """Марка из шифра основной надписи, например АНО/150321/1-П-ИОС5.4.2 -> ИОС5.4.2."""
    if not code:
        return None
    return parse_code(code)["mark"]


# ------------------------------------------------------------------ стадия

ID_WORDS_RE = re.compile(r"(?<![а-яё])(аоср|аоок|акт\w*|исп\.?\s*сх\w*|исполнительн\w*|журнал\w*|"
                         r"сертификат\w*|паспорт\w*|документ\s+о\s+качестве|протокол\w*)", re.I)


def detect_stage(rel_path, name_info=None, code_info=None):
    """Стадия по пути. Правило одно на весь конвейер — `registry.guess_stage` (#39, #41):
    папка стадии сильнее имени файла, чужие названия папок понимаются, «рд» внутри шифра
    стадией не считается. Возвращает (стадия, источник); прежняя собственная реализация
    этого модуля снята, чтобы стадия не определялась двумя способами.
    """
    stage = registry.guess_stage(rel_path)
    return stage, ("PATH" if stage != "UNKNOWN" else None)


def stage_group(stage, rel_path):
    """Группа для цепочек: смешанный файл относится к ИД или РД по типу документа."""
    if stage == "RD_ID_MIXED":
        return "ID" if ID_WORDS_RE.search(_stem(rel_path)) else "RD"
    return stage


# ------------------------------------------------------------------ раздел

def detect_section(rel_path, code_info=None, stage=None):
    """Раздел по пути (`registry.section_with_hint`, #41), а если путь раздел не называет —
    по марке из шифра основной надписи: у акта освидетельствования штамп приложенной схемы
    называет комплект, к которому относится работа. Возвращает (раздел, источник).
    """
    section, _hint = registry.section_with_hint(rel_path)
    if section != "OTHER":
        return section, "PATH"
    mark = (code_info or {}).get("mark")
    if mark and not mark.startswith("ТОМ"):
        by_mark, _hint = registry.section_with_hint(mark)
        if by_mark != "OTHER":
            return by_mark, "MARK"
    return "OTHER", None


# ------------------------------------------------------------------ сравнение редакций

def _sign(x):
    return (x > 0) - (x < 0)


# ------------------------------------------------------------------ выпуски по папкам (#110)

ARCHIVE_RE = re.compile(r"(?<![А-Яа-яЁё])архив", re.I)
# папка выпуска: «ПД 2022», «ПД 2025», «РД 2024», просто «2025»
ISSUE_YEAR_RE = re.compile(r"^(?:ПД|РД|П|Р)?[\s._-]*(20\d{2})$", re.I)
ISSUE_CORR_RE = re.compile(r"^корр?\.?\s*(\d{1,2})$", re.I)
# заключение экспертизы — не том проекта и не его редакция, сколько бы шифров в нём ни стояло
EXPERTISE_RE = re.compile(r"(?<![А-Яа-яЁё])заключени\w*\s+(?:[А-Яа-яЁё]+\s+){0,2}экспертиз", re.I)


def issue_folder(rel_path):
    """Выпуск по папкам пути: {archive, year, corr}.

    «РД/00. Архив/…» — архив; «пд/ПД 2022/…» — выпуск 2022 года; «пд/ПД 2025/Корр2/…» —
    выпуск 2025 года, корректировка 2. Папку «Архив» и год ищем только в папках, не в имени файла.
    """
    parts = [p.strip() for p in re.split(r"[\\/]+", _nfc(rel_path))[:-1]]
    out = {"archive": any(ARCHIVE_RE.search(p) for p in parts), "year": None, "corr": None}
    for p in parts:
        m = ISSUE_YEAR_RE.match(p)
        if m:
            out["year"] = int(m.group(1))
        m = ISSUE_CORR_RE.match(p)
        if m:
            out["corr"] = int(m.group(1))
    return out


def latest_issue(paths):
    """Выпуск документа, лежащего в нескольких местах: самый поздний из его копий.

    Одинаковый по SHA-256 файл у ДОО лежит и в «РД/00. Архив», и в «РД/к 15.09.2025»: из архива
    его никто не убирал, он и в действующем выпуске. Том, не менявшийся между выпусками,
    так же лежит в обоих — он принадлежит последнему.
    """
    issues = [issue_folder(p) for p in paths] or [issue_folder("")]
    return max(issues, key=lambda i: (not i["archive"], i["year"] or 0, i["corr"] or 0))


def issue_order(a, b):
    """Порядок двух редакций по папкам выпуска: 1, -1 или None, если папки о порядке молчат.

    Архив раньше всего остального. Разные годы выпуска решают сразу; номер корректировки —
    внутри одного года. Сравниваются только признаки, которые есть у обоих: том из корня
    «ПД 2025» и том из «ПД 2025/Корр1» папками не упорядочить, решают отметки в имени.
    """
    ia, ib = a.get("issue") or {}, b.get("issue") or {}
    if bool(ia.get("archive")) != bool(ib.get("archive")):
        return -1 if ia.get("archive") else 1
    ya, yb = ia.get("year"), ib.get("year")
    if ya is not None and yb is not None and ya != yb:
        return 1 if ya > yb else -1
    if ya == yb:
        ca, cb = ia.get("corr"), ib.get("corr")
        if ca is not None and cb is not None and ca != cb:
            return 1 if ca > cb else -1
    return None


def compare(a, b):
    """Порядок двух редакций одного документа: 1, -1, 0 или None, если не сравнить.

    a и b — разобранные отметки (parse_name) с полем change_effective и выпуском `issue`.
    Разные выпуски сравниваются по папке (`issue_order`): «изм. 1» корректировки 2025 года
    позже тома 2022 года без отметок, и «изм. 2» 2022 года не позже «изм. 1» 2025-го.
    """
    by_issue = issue_order(a, b)
    if by_issue is not None:
        return by_issue
    def corr(p):
        level = p.get("correction")
        if level is None:
            level = 1 if (p.get("by_comments") or p.get("gip") or p.get("generic_correction")) else 0
        return (level, p.get("correction_sub") or 0, 1 if p.get("gip") else 0)

    c = _sign((corr(a) > corr(b)) - (corr(a) < corr(b)))
    ch = _sign((a.get("change_effective") or 0) - (b.get("change_effective") or 0))
    if c and ch and c != ch:
        return None                                  # «изм. 2» против «кор. 3»
    result = c or ch
    if not result:
        result = _sign((a.get("version") or 0) - (b.get("version") or 0))
    da, db = _latest_date(a), _latest_date(b)
    if da and db and da != db:
        by_date = 1 if da > db else -1
        if not result:
            result = by_date
        elif result != by_date:
            return None                              # отметки и даты противоречат
    return result


def _latest_date(p):
    d = list(p.get("dates") or [])
    if p.get("month_date"):
        d.append(p["month_date"] + "-01")
    return max(d) if d else None


# ------------------------------------------------------------------ близость по содержимому

def code_profiles(sheets_rows):
    """Набор шифров основной надписи по файлу: сколько страниц с каким шифром.

    Латинские буквы-двойники приводятся к кириллице: «AHO/150321/1-РД-ОВ2.1» и
    «АНО/150321/1-РД-ОВ2.1» на листах одного тома Тюменской-5 — один шифр.
    """
    prof = collections.defaultdict(collections.Counter)
    for r in sheets_rows or []:
        if r.get("document_code"):
            prof[r["file_id"]][r["document_code"].translate(_HOMO)] += 1
    return prof


_CODE_MARKS = {}


def _code_mark(code):
    if code not in _CODE_MARKS:
        _CODE_MARKS[code] = parse_code(code)["mark"]
    return _CODE_MARKS[code]


def document_code_profiles(profiles, name_keys):
    """Оставить в наборе шифров файла только те, что отличают один документ от другого.

    Разбор листов записывает в шифр всё, что похоже на шифр. Без марки это шифр комплекта
    («01-07/23-14-РД», «НСЛ-17-02/2026-1»), штамп системы качества («СМК-ДК42-10») или
    слова адреса («ВН.ТЕР.Г» из «вн.тер.г.»). Шифр на листах документов с разными марками
    в имени — тоже шифр комплекта: «245-0817-КМ-2/Н-3» стоит и на АР1, и на РИО одного объекта.
    По таким шифрам разные тома выглядят одним документом: на Речникове КЖ1 «сменялся»
    КЖ2.2, а пять томов КЖ1.1.x Новослободской уходили на уточнение.

    Общим шифр считается, только если он частый в каждом из файлов. Случайный лист
    не в счёт: в томе ОВ1 Тюменской-5 на одной странице из 602 стоит шифр ОВ2.1,
    и без этого условия том ОВ2.1 терял собственный шифр.

    name_keys — корпус и марка из имени файла; номер тома маркой не считается.
    """
    keys_by_code = collections.defaultdict(set)
    for fid, prof in profiles.items():
        key = name_keys.get(fid)
        if not key or not key[1] or key[1].startswith("ТОМ"):
            continue
        total = sum(prof.values())
        for code, k in prof.items():
            if k >= max(2, 0.1 * total):
                keys_by_code[code].add(key)
    out = {}
    for fid, prof in profiles.items():
        kept = collections.Counter({code: k for code, k in prof.items()
                                    if len(keys_by_code[code]) < 2 and _code_mark(code)})
        if kept:
            out[fid] = kept
    return out


def code_has_mark(code, mark):
    """Марка стоит в шифре целиком: «ОВ1» есть в «АНО/150321/1-РД-ОВ1.С», но не в «…-ОВ1.1»,
    а «КР» нет в «…-КРЫША». Синонимы тоже ищутся: «ПЗУ» есть в «…-СПОЗУ.ТЧ»."""
    code = code.translate(_HOMO).upper()
    letters = re.match(r"[А-ЯЁ]*", mark).group(0)
    variants = {mark} | {syn + mark[len(letters):] for syn, canon in MARK_SYNONYMS.items() if canon == letters}
    return any(re.search(r"(?<![А-ЯЁA-Z0-9])" + re.escape(v) + r"(?![0-9А-ЯЁA-Z]|\.[0-9])", code)
               for v in variants)


def _mark_letters(mark):
    return re.sub(r"[^А-ЯЁA-Z]", "", mark)


def marks_compatible(a, b):
    """Могут ли две марки означать один документ. Номер тома совместим с любой маркой.

    «ПЗ» и «ПЗ1.2» совместимы: марка без номера бывает у переиздания того же тома.
    «КЖ1» и «КЖ2.2», «КЖ7» и «КЖ.ГИ», «АР1» и «РИО» — разные документы.
    """
    if not a or not b or a == b or a.startswith("ТОМ") or b.startswith("ТОМ"):
        return True
    if _mark_letters(a) != _mark_letters(b):
        return False
    return not (re.search(r"\d", a) and re.search(r"\d", b))


def specific_code(profile, min_share=0.1):
    """Шифр файла по основной надписи: самый конкретный из частых.

    Разбор штампа нередко обрезает шифр: на томе 5.1.1 Тюменской-5 «АНО/150321/1-П-ИОС»
    стоит на 23 страницах, а полный «…-ИОС5.1.1-ПЗ» на 18. Самый частый шифр дал бы марку
    «ИОС» без номера, и тома разных подразделов слились бы в одну цепочку. Поэтому среди
    шифров, стоящих хотя бы на десятой части страниц, берётся тот, у которого марка длиннее.
    """
    total = sum(profile.values())
    frequent = [(c, n) for c, n in profile.most_common() if n >= max(2, min_share * total)]
    if not frequent:
        return profile.most_common(1)[0][0]
    return max(frequent, key=lambda cn: (len(parse_code(cn[0])["mark"] or ""), cn[1]))[0]


def _cosine(p, q):
    keys = set(p) | set(q)
    dot = sum(p[k] * q[k] for k in keys)
    na = math.sqrt(sum(v * v for v in p.values()))
    nb = math.sqrt(sum(v * v for v in q.values()))
    return dot / (na * nb) if na and nb else 0.0


def same_content(pa, pb, pages_a, pages_b, min_pages=5, min_cos=0.95):
    """Переиздание того же документа: те же шифры на страницах и почти то же число страниц."""
    if sum(pa.values()) < min_pages or sum(pb.values()) < min_pages:
        return False
    if not pages_a or not pages_b or abs(pages_a - pages_b) > max(3, 0.03 * max(pages_a, pages_b)):
        return False
    return _cosine(pa, pb) >= min_cos


# ------------------------------------------------------------------ штамп: редакция из таблицы изменений

def _titleblock_revision_of_file(path):
    """Наибольший номер изменения по таблицам изменений всех страниц файла."""
    import pymupdf
    from pipeline import reading, titleblock
    best = None
    try:
        doc = pymupdf.open(path)
    except Exception:
        return None
    try:
        for page_no in range(1, doc.page_count + 1):
            try:
                n = titleblock.revision(reading.read_text_layer(doc, page_no)["words"])
            except Exception:
                continue
            if n is not None:
                best = max(best or 0, n)
    finally:
        doc.close()
    return best


def titleblock_revisions(docs, root, workers=4):
    """Номер изменения из штампа по файлу проектной и рабочей стадии.

    Слова читаются из текстового слоя PDF заново, а не из кеша чтения: в кеше у повёрнутых
    листов старые координаты без поворота (#20), и штамп там оказывается не внизу листа.
    На Тюменской-5 все страницы ВВ со штампом повёрнуты на 90°. Текстовый слой читается
    быстро, распознавание и модель не нужны.
    """
    import multiprocessing
    tasks = []
    for d in docs:
        if d.get("duplicate_of") or (d.get("extension") or "").lower() != ".pdf":
            continue
        if stage_group(d.get("stage"), d["relative_path"]) not in ("PD", "RD"):
            continue
        tasks.append((d["file_id"], os.path.join(root, d["relative_path"])))
    if not tasks:
        return {}
    with multiprocessing.Pool(max(1, workers)) as pool:
        found = pool.map(_titleblock_revision_of_file, [p for _, p in tasks], chunksize=1)
    return {fid: n for (fid, _), n in zip(tasks, found) if n is not None}


# ------------------------------------------------------------------ сборка цепочек

def _sig_nearby(root, rel_path):
    """Рядом с файлом лежит открепленная подпись: «имя.sig» или «имя_ФИО.sig»."""
    if not root:
        return False
    folder = os.path.join(root, os.path.dirname(rel_path))
    stem = _stem(rel_path)
    try:
        return any(f.lower().endswith(".sig") and _nfc(f).startswith(stem) for f in os.listdir(folder))
    except OSError:
        return False


def _title_key(code_info, name_info):
    """Ключ документа без марки: название без отметок, цифр нумерации и знаков."""
    t = _NUMBERING_RE.sub("", name_info["rest"]).lower().translate(_HOMO)
    return re.sub(r"[^а-яёa-z0-9]+", "", t) or name_info["stem"].lower()


def _stage_group_of(d, name_info, code_info):
    """Группа стадии так, как её увидит сборка цепочек: стадия организатора не меняется."""
    detected = detect_stage(d["relative_path"], name_info, code_info)[0]
    official = d.get("id_source") == "OFFICIAL"
    stage = detected if not official and detected != "UNKNOWN" else d.get("stage")
    return stage_group(stage, d["relative_path"])


SHEET_REISSUE_RE = re.compile(r"(?<![а-яё])(лист|л\.)\s*\d", re.I)


def analyse(object_id, docs, sheets_rows=None, tb_revisions=None, root=None, require_approval=False, manual=None):
    """Разобрать документы объекта и собрать цепочки редакций.

    docs — строки реестра (documents.jsonl). Возвращает (документы с новыми полями, цепочки).
    Идентификаторы и официальные стадия и раздел из реестра организатора не меняются:
    найденное своими правилами кладётся рядом в *_detected.
    manual — {file_id: True} документов, которые инспектор назвал актуальной редакцией
    своей цепочки: такой выбор сильнее разбора (ТЗ 9.1, правка идёт в журнал аудита).
    """
    tb_revisions = tb_revisions or {}
    # выпуск по папкам — по всем копиям файла: копия вне архива делает документ действующим
    paths = collections.defaultdict(list)
    for d in docs:
        paths[d.get("duplicate_of") or d["file_id"]].append(d["relative_path"])
    parsed, groups = [], []
    for d in docs:
        n = parse_name(d["relative_path"])
        n["issue"] = latest_issue(paths[d.get("duplicate_of") or d["file_id"]])
        c = parse_code(n["rest"])
        parsed.append((n, c))
        groups.append(_stage_group_of(d, n, c))
    # Дубль по SHA-256 носит file_id исходника, но путь у него свой: «5.5. …ИОС5.5.1 (2)»
    # рядом с «5.1. …ИОС5.1 (2)» на Алтуфьевском. Имя и папка разбираются по своей строке,
    # цепочки и шифры штампа — по строке исходника.
    primary = {d["file_id"]: i for i, d in enumerate(docs) if not d.get("duplicate_of")}
    for i, d in enumerate(docs):
        primary.setdefault(d["file_id"], i)
    group_of = {fid: groups[i] for fid, i in primary.items()}
    # Штамп исполнительного документа — копия штампа листа РД, на который он ссылается:
    # акты Новослободской несут «НВС-2025/03-КР1» приложенной схемы. Марку и шифр акта
    # он не называет, и в наборы шифров исполнительная документация не входит. Раздел
    # по нему определить можно: исполнительный план отопления — это отопление.
    raw_profiles = code_profiles(sheets_rows)
    profiles = document_code_profiles(
        {fid: prof for fid, prof in raw_profiles.items() if group_of.get(fid) != "ID"},
        {fid: (parsed[i][1]["part"] or "", parsed[i][1]["mark"]) for fid, i in primary.items()})
    dominant = {fid: specific_code(prof) for fid, prof in profiles.items()}
    section_hint = {}
    for fid, prof in raw_profiles.items():
        marked = collections.Counter({code: k for code, k in prof.items() if _code_mark(code)})
        if group_of.get(fid) == "ID" and marked:
            section_hint[fid] = parse_code(specific_code(marked))

    info = []
    for i, d in enumerate(docs):
        n, c = parsed[i]
        tb = parse_code(dominant[d["file_id"]]) if dominant.get(d["file_id"]) else {}
        tb_mark = tb.get("mark")
        # марка штампа без номера («ИОС») не заменяет номер тома из имени
        if tb_mark and re.search(r"\d", tb_mark) and not tb_mark.startswith("ТОМ") \
                and (not c["mark"] or c["mark"].startswith("ТОМ")):
            c = {**c, "mark": tb_mark, "mark_source": "TITLEBLOCK",
                 "code_base": c["code_base"] or tb.get("code_base")}
        else:
            c = {**c, "mark_source": "NAME" if c["mark"] else None}
        tb_rev = tb_revisions.get(d["file_id"])
        n["change_titleblock"] = tb_rev
        # Номер из штампа подставляется, только если в имени нет никаких отметок редакции.
        # У томов «кор3» Речникова в штампах своя сквозная нумерация изменений до 19:
        # смешав её с «изм» из имени, получим ложные конфликты корректировки и изменения.
        marked = any(n[k] for k in ("change", "correction", "version", "by_comments", "gip",
                                    "generic_correction", "dates"))
        n["change_effective"] = n["change"] if marked else tb_rev
        info.append((n, c))

    out_docs = []
    for i, d in enumerate(docs):
        n, c = info[i]
        stage_det, stage_src = detect_stage(d["relative_path"], n, c)
        section_det, section_src = detect_section(d["relative_path"], c,
                                                  stage=stage_group(stage_det, d["relative_path"]))
        if section_det == "OTHER" and d["file_id"] in section_hint:
            hinted, _ = detect_section(d["relative_path"], section_hint[d["file_id"]], stage="ID")
            if hinted != "OTHER":
                section_det, section_src = hinted, "TITLEBLOCK_MARK"
        row = dict(d)
        official = d.get("id_source") == "OFFICIAL"
        row["stage_detected"], row["stage_source"] = stage_det, stage_src
        # Стадия и раздел в реестре уже стоят тем же правилом; здесь только заполняются
        # пробелы. Значение, которое уже есть, не трогается: его могла задать рука
        # инспектора (#39), а у файлов организатора — его реестр
        if d.get("stage") in (None, "", "UNKNOWN") and stage_det != "UNKNOWN":
            row["stage"] = stage_det
        row["section_detected"], row["section_source"] = section_det, section_src
        # раздел, каким его назвал реестр (организатора или свой): нужен замеру согласия,
        # ведь ниже пустой раздел заполняется найденным, и повторный прогон его не отличит
        row["section_registry"] = d.get("section_registry", d.get("section"))
        if d.get("section") in (None, "", "OTHER") and section_det != "OTHER":
            row["section"] = section_det
        row["mark"] = c["mark"]
        row["part"] = c["part"]
        # Шифр штампа — самый частый конкретный на страницах, но в томе бывают чужие листы:
        # у МОПБ Новослободской это «…-ИОС4.2». Если марка из имени есть, она должна
        # стоять в шифре штампа.
        tb_code = dominant.get(d["file_id"])
        name_mark = c["mark"] if c.get("mark_source") == "NAME" and not c["mark"].startswith("ТОМ") else None
        if tb_code and name_mark and not code_has_mark(tb_code, name_mark):
            tb_code = None
        row["document_code"] = tb_code or c["code"]
        row["document_code_source"] = "TITLEBLOCK" if tb_code else ("NAME" if c["code"] else None)
        row["revision"] = revision_label(n)
        row["revision_detail"] = {k: n[k] for k in (
            "change", "change_titleblock", "change_effective", "correction", "correction_sub",
            "version", "by_comments", "gip", "generic_correction", "edited", "package_version",
            "dates", "month_date", "copy_suffix", "year_suffix")}
        evidence = list(n["approval"])
        if _sig_nearby(root, d["relative_path"]):
            evidence.append("E_SIGNATURE_FILE")
        row["approval_evidence"] = evidence
        row["approval_status"] = "APPROVED" if evidence else d.get("approval_status") or "UNKNOWN"
        row["predecessor_file_id"] = None
        row["successor_file_id"] = None
        out_docs.append(row)

    by_id = {r["file_id"]: r for r in out_docs if not r.get("duplicate_of")}

    # семьи: стадия, корпус, марка; без марки — название
    families = collections.defaultdict(list)
    for r in by_id.values():
        n, c = info[primary[r["file_id"]]]
        group = stage_group(r["stage"], r["relative_path"])
        if (r.get("extension") or os.path.splitext(r["relative_path"])[1]).lower() != ".pdf":
            key = ("NOT_PDF", r["file_id"])            # извещения и ведомости в DOCX — не редакции
        elif group == "ID":
            key = ("ID", r["file_id"])                # у ИД нет редакций: каждый акт отдельный документ
        elif EXPERTISE_RE.search(os.path.basename(r["relative_path"])):
            key = (group, r["file_id"])              # заключение экспертизы: не том и не редакция тома
        elif c["mark"]:
            key = (group, c["part"] or "", c["section_part"] or "", c["mark"])
        else:
            key = (group, "", "", "~" + _title_key(c, n))
        families[key].append(r["file_id"])

    # Переиздания без общей марки в имени, но с тем же набором шифров на страницах.
    # Разные марки, корпуса и книги не сливаются, сколько бы ни совпадало содержимое.
    parent = {k: k for k in families}
    marks = {k: ({k[3]} if len(k) == 4 and not k[3].startswith("~") else set()) for k in families}
    parts = {k: ({p for p in k[1:3] if p} if len(k) == 4 else set()) for k in families}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def issue_split(fa_list, fb_list):
        """Все тома одного семейства из более раннего выпуска по папкам, чем все тома другого (#110):
        «ПБ» выпуска 2022 и «ПБ1» выпуска 2025, «ПЗ» 2022 и «ПЗ фрагмент 1» 2025 — один том."""
        orders = {issue_order(info[primary[fa]][0], info[primary[fb]][0]) for fa in fa_list for fb in fb_list}
        return orders in ({1}, {-1})

    keys = [k for k in families if k[0] not in ("ID", "NOT_PDF")]
    for i, ka in enumerate(keys):
        for kb in keys[i + 1:]:
            ra, rb = find(ka), find(kb)
            if ka[0] != kb[0] or ra == rb:
                continue
            if not all(marks_compatible(x, y) for x in marks[ra] for y in marks[rb]):
                continue
            if parts[ra] and parts[rb] and parts[ra] != parts[rb]:
                continue
            if (len(ka) == 4 and len(kb) == 4 and not ka[3].startswith("~") and not kb[3].startswith("~")
                    and issue_split(families[ka], families[kb])) or \
                    any(same_content(profiles.get(fa, {}), profiles.get(fb, {}),
                                     by_id[fa].get("pdf_pages"), by_id[fb].get("pdf_pages"))
                        for fa in families[ka] for fb in families[kb]):
                parent[rb] = ra
                marks[ra] |= marks[rb]
                parts[ra] |= parts[rb]
    merged = collections.defaultdict(list)
    for k, members in families.items():
        merged[find(k)].extend(members)

    chains = []
    for idx, (key, members) in enumerate(sorted(merged.items(), key=lambda kv: (kv[0][0], str(kv[0][1:])))):
        chain_id = f"{object_id}:{key[0]}:{key[-1]}" if len(members) == 1 else f"{object_id}:{key[0]}:{key[-1]}:{idx}"
        rows = [by_id[f] for f in sorted(members)]
        ch = resolve(rows, {f: info[primary[f]][0] for f in members}, {f: info[primary[f]][1] for f in members},
                     require_approval=require_approval)
        ch = choose_manually(ch, manual or {})
        ch.update({"chain_id": chain_id, "object_id": object_id, "stage_group": key[0],
                   "mark": info[primary[members[0]]][1]["mark"], "part": key[1] if len(key) > 3 else ""})
        chains.append(ch)
        order = ch.get("order") or []
        for i, f in enumerate(order):
            by_id[f]["predecessor_file_id"] = order[i - 1] if i > 0 else None
            by_id[f]["successor_file_id"] = order[i + 1] if i + 1 < len(order) else None
        for f in members:
            by_id[f]["chain_id"] = chain_id
            by_id[f]["revision_status"] = ch["member_status"][f]

    for r in out_docs:
        if r.get("duplicate_of"):
            src = by_id.get(r["duplicate_of"], {})
            r["chain_id"] = src.get("chain_id")
            r["revision_status"] = "DUPLICATE"
    dup_by_src = collections.defaultdict(list)
    for r in out_docs:
        if r.get("duplicate_of"):
            dup_by_src[r["duplicate_of"]].append(r["relative_path"])
    for ch in chains:
        ch["duplicates"] = {f: dup_by_src[f] for f in ch["members"] if dup_by_src.get(f)}
    return out_docs, chains


def resolve(rows, names, codes, require_approval=False):
    """Актуальная редакция цепочки или статус «требует уточнения» с причиной."""
    ids = [r["file_id"] for r in rows]
    detail = {r["file_id"]: {"relative_path": r["relative_path"], "revision": revision_label(names[r["file_id"]]),
                              "code_base": codes[r["file_id"]]["code_base"], "pdf_pages": r.get("pdf_pages"),
                              "approval_status": r.get("approval_status"),
                              "issue": names[r["file_id"]].get("issue")} for r in rows}
    base = {"members": ids, "member_detail": detail}
    if len(rows) == 1:
        status = "CURRENT"
        chain = {**base, "status": "SINGLE", "current_file_id": ids[0], "order": ids, "reason": None,
                 "member_status": {ids[0]: status}}
        return _approval_gate(chain, rows, require_approval)

    reasons = []
    # Разные шифры внутри одного выпуска — разные документы. Между выпусками шифр из имени
    # меняется вместе с нумерацией томов: «01-05-01-01-04 Пол25 ИОС1.1» в ПД 2022 и
    # «05 Раздел ПД 5 подраздел 1 ИОС1.1» в ПД 2025 — один том (#110)
    based = [(f, codes[f]["code_base"]) for f in ids if codes[f]["code_base"]]
    clash = sorted({x for (fa, a), (fb, b) in ((p, q) for i, p in enumerate(based) for q in based[i + 1:])
                    if a not in b and b not in a and issue_order(names[fa], names[fb]) is None for x in (a, b)})
    if clash:
        reasons.append("разные шифры проекта: " + ", ".join(clash))

    small = [r for r in rows if (r.get("pdf_pages") or 0) <= 3
             and (r.get("pdf_pages") or 0) <= 0.2 * max(x.get("pdf_pages") or 0 for x in rows)]
    sheet_files = set()
    if small and SHEET_REISSUE_RE.search(" ".join(r["relative_path"] for r in small)):
        sheet_files = {r["file_id"] for r in small}
        reasons.append("переизданы отдельные листы: " + ", ".join(sorted(sheet_files))
                       + "; листы по отдельности в один выпуск не сливаются")

    later = {f: set() for f in ids}          # later[a] — кто позже a
    incomparable = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            c = compare(names[a], names[b])
            if c is None:
                incomparable.append((a, b))
            elif c > 0:
                later[b].add(a)
            elif c < 0:
                later[a].add(b)
            else:
                incomparable.append((a, b))
    maximal = [f for f in ids if not later[f]]

    if not reasons and len(maximal) == 1:
        top = maximal[0]
        blocked = [p for p in incomparable if top in p]
        if not blocked:
            order = sorted(ids, key=lambda f: len(_all_later(f, later)), reverse=True)
            member_status = {f: ("CURRENT" if f == top else "SUPERSEDED") for f in ids}
            chain = {**base, "status": "RESOLVED", "current_file_id": top, "order": order, "reason": None,
                     "member_status": member_status}
            return _approval_gate(chain, rows, require_approval)

    for a, b in incomparable:
        if a in sheet_files or b in sheet_files:
            continue
        if a in maximal and b in maximal:
            la, lb = revision_label(names[a]) or "без отметки", revision_label(names[b]) or "без отметки"
            if compare(names[a], names[b]) == 0:
                reasons.append(f"одинаковая редакция у разных файлов: {a} и {b} ({la})")
            else:
                reasons.append(f"редакции не упорядочить: {a} ({la}) и {b} ({lb})")
    if not reasons:
        reasons.append("несколько кандидатов в актуальные: " + ", ".join(maximal))
    # Том, который папка выпуска ставит раньше другого тома цепочки, — прежняя редакция при любом
    # исходе: архив и прошлый выпуск не становятся кандидатами в актуальные (#110)
    older = {f for f in ids if any(issue_order(names[g], names[f]) == 1 for g in ids if g != f)}
    return {**base, "status": "CLARIFICATION_REQUIRED", "current_file_id": None, "order": None,
            "candidates": [f for f in maximal if f not in older], "reason": "; ".join(dict.fromkeys(reasons)),
            "member_status": {f: ("SUPERSEDED" if f in older else "CLARIFICATION_REQUIRED") for f in ids}}


def _all_later(f, later, seen=None):
    seen = seen if seen is not None else set()
    for g in later[f]:
        if g not in seen:
            seen.add(g)
            _all_later(g, later, seen)
    return seen


def _approval_gate(chain, rows, require_approval):
    """Признак утверждения и актуальная редакция.

    Строгий режим ТЗ (`require_approval`): без признака утверждения актуальная редакция
    не определена. Обычный режим — по данным: признаки утверждения (ЭЦП, МГЭ, РнС в имени,
    файл `.sig` рядом) в корпусе редки, и требовать их всюду значило бы отправить на уточнение
    каждую цепочку. Поэтому отказ только тогда, когда утверждена прежняя редакция, а последняя —
    нет: последняя может быть рабочей заготовкой, и какая из двух действует, решает человек.
    """
    top = next(r for r in rows if r["file_id"] == chain["current_file_id"])
    if top.get("approval_status") == "APPROVED":
        return chain
    approved = [r["file_id"] for r in rows if r["file_id"] != top["file_id"] and r.get("approval_status") == "APPROVED"]
    if not require_approval and not approved:
        return chain
    reason = ("нет признака утверждения у " + top["file_id"] if not approved else
              f"признак утверждения есть у прежней редакции {', '.join(approved)}, у последней {top['file_id']} нет")
    return {**chain, "status": "CLARIFICATION_REQUIRED", "reason": reason,
            "candidates": [top["file_id"], *approved], "current_file_id": None, "order": None,
            "member_status": {f: "CLARIFICATION_REQUIRED" for f in chain["members"]}}


def choose_manually(chain, manual):
    """Выбор инспектора: документ из цепочки назван актуальной редакцией.

    manual — {file_id: True}. Выбор сильнее разбора и снимает «требует уточнения»; в цепочке
    остаётся отметка `resolved_by: INSPECTOR`, чтобы протокол показывал, чьё это решение.
    Порядок остальных редакций, если разбор его вывел, сохраняется; иначе они просто
    считаются устаревшими.
    """
    chosen = [f for f in chain["members"] if manual.get(f)]
    if not chosen:
        return chain
    top = chosen[-1]
    order = [f for f in (chain.get("order") or []) if f != top] or [f for f in chain["members"] if f != top]
    return {**chain, "status": "RESOLVED", "current_file_id": top, "order": [*order, top],
            "reason": None, "resolved_by": "INSPECTOR",
            "member_status": {f: ("CURRENT" if f == top else "SUPERSEDED") for f in chain["members"]}}


def summary(docs, chains):
    status = collections.Counter(c["status"] for c in chains)
    multi = [c for c in chains if len(c["members"]) > 1]
    return {
        "documents": len(docs),
        "unique": sum(1 for d in docs if not d.get("duplicate_of")),
        "duplicates": sum(1 for d in docs if d.get("duplicate_of")),
        "chains": len(chains),
        "chains_with_revisions": len(multi),
        "resolved": sum(1 for c in multi if c["status"] == "RESOLVED"),
        "clarification": status.get("CLARIFICATION_REQUIRED", 0),
        "with_revision_mark": sum(1 for d in docs if d.get("revision")),
        "with_mark": sum(1 for d in docs if d.get("mark")),
        "section_other": sum(1 for d in docs if d.get("section") == "OTHER"),
        "approved": sum(1 for d in docs if d.get("approval_status") == "APPROVED"),
    }
