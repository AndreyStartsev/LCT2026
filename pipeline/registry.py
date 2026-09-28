"""Реестр документов объекта.

Одна строка на файл по схеме `contracts/document.schema.json`.

Главное правило: идентификатор файла берётся из реестра организатора по SHA-256
содержимого, а не по имени и не по пути. Имена корпуса приехали в кодировке cp866,
часть восстановлена, часть нет, а манифест организатора ссылается на исходные пути.
Сопоставление по содержимому переживает и переименование, и перепаковку.

Файлы, которых нет в реестре организатора (наши дополнительные объекты), получают
локальный идентификатор с префиксом L. Перепутать его с настоящим нельзя: настоящие
начинаются с F.

Локальный идентификатор не должен зависеть от машины, на которой собран реестр.
Реестры Изумрудной и Алтуфьевского, пересобранные в Windows, получили другие номера
при тех же файлах (18 и 59 перенумерованных) и пути через обратную косую черту,
по которым файлы не находятся на других системах. Причин три, и все устранены:
порядок обхода каталогов зависел от файловой системы, путь писался системным
разделителем, а номера раздавались заново при каждой сборке. Теперь каталоги
обходятся по порядку, путь всегда через «/», а номера из прежнего реестра объекта
сохраняются по SHA-256 содержимого.
"""
import hashlib
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline.config import (IOS_SECTIONS, OBJECTS, SECTION_MARKS, SECTION_PHRASES, STAGE_ABBR,
                             STAGE_CODE_MARKERS, STAGE_FOLDER_SKIP, STAGE_FOLDER_WORDS, STAGE_LETTERS,
                             STAGE_NAME_EXACT, STAGE_NAME_WORDS, STAGE_WORDS, manifest_paths)

# Форматы, которые читает хотя бы один разбор. Остальные попадают в реестр строкой
# со статусом: файл нового объекта не должен исчезать молча (#39).
# Форматы, которые принимает система. ТЗ, модуль 1: «Загрузка ПД, РД, ИД (PDF, DOCX, XML)»
# и отдельной строкой в обработке ошибок: «Загружен файл в неподдерживаемом формате →
# отклонение с указанием поддерживаемых форматов (PDF, DOCX, XML)». XLSX там нет, и сервис
# его тоже не принимает (`service/api/src/filecheck.ts`) — реестр не должен расходиться
# с дверью: иначе файл, отклонённый при загрузке, числится поддержанным в реестре.
#
# DOC, XLS и XLSX конвейер читает с #112 (`pipeline/office_text.py`), а дверь сервиса их по-прежнему
# не принимает — так требует ТЗ. Расхождения нет: файл, отклонённый при загрузке, в хранилище
# процесса не попадает, и реестр его не видит. Эти форматы читаются у объектов, разложенных папкой,
# как корпус организатора: у Полярной 25, ДОО их 194, и до #112 они стояли «формат не читается».
SUPPORTED_EXT = (".pdf", ".docx", ".xml", ".doc", ".xls", ".xlsx")


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _manifest_row(r):
    """Строка реестра организатора в наших полях или None, если файл не опознать.

    Форматов два: наш `document_manifest.jsonl` и файловый индекс пакета
    `files_index.jsonl`, где те же поля названы source_sha256, source_relative_path
    и source_page_count. Реестр нового объекта подключается в любом из двух.
    """
    digest = r.get("sha256") or r.get("source_sha256")
    if not digest or not r.get("file_id"):
        return None
    return {"file_id": r["file_id"], "sha256": digest,
            "stage": r.get("stage"), "section": r.get("section"),
            "pdf_pages": r.get("pdf_pages") or r.get("source_page_count"),
            "relative_path": r.get("relative_path") or r.get("source_relative_path")}


def load_official(paths=None):
    """Реестры организатора, разложенные по SHA-256.

    Читаются все пути из `config.manifest_paths()`: сначала заданные окружением
    реестры нового объекта, затем реестр пакета. Один и тот же файл в двух реестрах
    оставляет идентификатор первого, отсутствующий путь пропускается молча.
    """
    out = {}
    for path in manifest_paths() if paths is None else paths:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    r = _manifest_row(json.loads(line))
                except ValueError as e:
                    raise ValueError(f"реестр {path}, строка {n}: {e}") from None
                if r:
                    out.setdefault(r["sha256"], r)
    return out


_WORD = re.compile(r"[0-9a-zа-яё]+")


def _words(text):
    # macOS отдаёт имена в NFD: «й» приходит как «и» и отдельный знак бреве
    return _WORD.findall(unicodedata.normalize("NFC", text).lower())


def _stem_stage(word, stems):
    return next((stage for stem, stage in stems if word.startswith(stem)), None)


def _folder_stage(folder):
    """Стадия, которую называет папка, или None.

    Название должно начинаться со стадии: «ПД», «01_РД», «Стадия П», «Проектная
    документация». «Рабочая и исполнительная документация» у организатора помечена
    RD_ID_MIXED; другие сочетания стадий папка не решает.
    """
    words = _words(folder)
    while words and (words[0].isdigit() or words[0] in STAGE_FOLDER_SKIP):
        words.pop(0)                             # номер и слово состава впереди: «1. ПД», «Том 1 ПД»
    if not words:
        return None
    if len(words) > 1 and words[0] == "стадия":
        return STAGE_LETTERS.get(words[1]) or STAGE_ABBR.get(words[1])
    if words[0] in STAGE_FOLDER_WORDS and (words[0] != "проект" or len(words) == 1):
        # «Проект» решает только целой папкой: «Проект производства работ» — рабочая стадия
        return STAGE_FOLDER_WORDS[words[0]]
    stages = []
    for word in words:
        stage = STAGE_ABBR.get(word) or _stem_stage(word, STAGE_WORDS)
        if stage:
            stages.append(stage)
        elif word != "и" or not stages:
            break
    if set(stages) == {"RD", "ID"}:
        return "RD_ID_MIXED"
    return stages[0] if len(set(stages)) == 1 else None


def _code_stage(filename):
    """Буква стадии в шифре: «23.009-Р-1-КЖ0.1», «ЖС-РД-270121-П-ИОС5.5.1».

    Буква стоит между дефисами или подчёркиваниями сразу после базового номера,
    поэтому слово перед ней должно содержать цифру. Так не считаются ни организация
    «ЖС-РД» перед номером, ни буква в начале имени: «П-2025-04-266-КЖ01» лежит
    в рабочей документации.
    """
    stem = unicodedata.normalize("NFC", os.path.splitext(filename)[0]).lower()
    parts = re.split(r"[-_]", stem)
    for i in range(1, len(parts) - 1):
        before = parts[i - 1].split()
        if parts[i] in STAGE_CODE_MARKERS and before and any(ch.isdigit() for ch in before[-1]):
            return STAGE_CODE_MARKERS[parts[i]]
    return None


def guess_stage(rel_path):
    """Стадия файла по пути, если его нет в реестре организатора.

    Папка стадии сильнее имени файла, ближняя к файлу папка сильнее внешней.
    Имя файла решает, только когда ни одна папка стадию не называет: сначала
    слово исполнительной стадии, затем буква стадии в шифре.
    """
    *folders, filename = re.split(r"[\\/]+", rel_path.strip("\\/"))
    for folder in reversed(folders):
        stage = _folder_stage(folder)
        if stage:
            return stage
    for word in _words(os.path.splitext(filename)[0]):
        stage = _stem_stage(word, STAGE_NAME_WORDS) or STAGE_NAME_EXACT.get(word)
        if stage:
            return stage
    return _code_stage(filename) or "UNKNOWN"


_NOT_LETTER_BEFORE = r"(?<![a-zа-яё])"
_NOT_LETTER_AFTER = r"(?![a-zа-яё])"
# «Раздел 5.1», «Подраздел 5.4», «Том 5.2.1»
_SUBSECTION = re.compile(_NOT_LETTER_BEFORE + r"(?:под)?(?:раздел|том)\s*5\.(\d)(?!\d)")
# «ИОС1.2», «ИОС 4.4 ТС», «ИОС.5.7», «ИОС5.5.1»
_IOS = re.compile(_NOT_LETTER_BEFORE + r"иос\s*\.?\s*(\d)(?!\d)(?:\.(\d{1,2})(?!\d))?(?:\.(\d{1,2})(?!\d))?")
# «вк и пп с 8 по 12 этаж» у Речникова — акты вертикальных конструкций и плит перекрытия.
# Сокращение читается так только рядом со словами акта: в обычном пути «РД/ВК/ВК и ПП
# насосная» те же две буквы — водопровод и канализация (#41)
_VK_PP = re.compile(_NOT_LETTER_BEFORE + r"вк\W+(?:и\W+)?пп" + _NOT_LETTER_AFTER)
# «aook» у Речникова набрано латиницей, поэтому проверяются оба алфавита
_ACT_CONTEXT = re.compile(r"(?<![a-zа-яё])(?:аоок|aook|аоср|aocp|акт|акты|освидетельствован\w*"
                          r"|исполнительн\w*|скрыт\w+\s+работ\w*)(?![a-zа-яё])")
_MARK = re.compile(_NOT_LETTER_BEFORE + "(" + "|".join(sorted(SECTION_MARKS, key=len, reverse=True)) + ")"
                   + _NOT_LETTER_AFTER)
_PHRASES = [(re.compile(_NOT_LETTER_BEFORE + phrase), section) for phrase, section in SECTION_PHRASES]
_AMBIGUOUS = 9


def _section_signals(part, acts=False):
    """Что называет раздел в одном звене пути: [(сила, место, раздел)], сила 0 — самая высокая.

    acts — путь говорит об актах освидетельствования: только там «ВК и ПП» читается
    как вертикальные конструкции и плиты перекрытия.
    """
    text = unicodedata.normalize("NFC", part).lower().replace("ё", "е")
    found = [(0, m.start(), IOS_SECTIONS.get(m.group(1), "OTHER")) for m in _SUBSECTION.finditer(text)]
    for m in _IOS.finditer(text):
        first, second, third = m.groups()
        if first == "5" and second and not third:
            # «ИОС5.1»: у Новослободской и Изумрудной это часть 1 сетей связи,
            # у проектировщика ЖС на Алтуфьевском — подраздел 5.1, электроснабжение
            found.append((_AMBIGUOUS, m.start(), IOS_SECTIONS["5"]))
        else:
            number = second if first == "5" and third else first
            found.append((1, m.start(), IOS_SECTIONS.get(number, "OTHER")))
    if acts:
        found += [(2, m.start(), "KR") for m in _VK_PP.finditer(text)]
    found += [(3, m.start(), SECTION_MARKS[m.group(1)]) for m in _MARK.finditer(text)]
    for rx, section in _PHRASES:
        found += [(4, m.start(), section) for m in rx.finditer(text)]
    return found


def _strongest(found):
    # при равной силе решает написанное позже: марка комплекта завершает шифр, уточнение
    # стоит перед ней. «Исп.схема № С2_ВК_КЖ0.2» — вертикальные конструкции по комплекту КЖ0.2
    return min(found, key=lambda s: (s[0], -s[1]))[2]


def section_with_hint(rel_path):
    """Раздел файла по пути и догадка, если уверенного ответа нет: (раздел, догадка).

    Имя файла сильнее папок, ближняя к файлу папка сильнее внешней: шифр тома называет
    раздел точнее папки, куда том положили. Внутри одного звена номер подраздела сильнее
    шифра ИОС, шифр ИОС сильнее марки, марка сильнее названия словами.

    «ИОС5.1» без номера подраздела рядом раздел не называет: у одного проектировщика это
    часть 1 сетей связи (Новослободская), у другого — подраздел 5.1, электроснабжение
    (Алтуфьевское). Раньше в таком случае молча выбирались сети связи; теперь раздел
    «не определён», а догадка возвращается отдельно и пишется в реестр (#41).
    """
    *folders, filename = re.split(r"[\\/]+", rel_path.strip("\\/"))
    # акты освидетельствования: по словам пути или по исполнительной стадии
    flat = unicodedata.normalize("NFC", rel_path).lower().replace("ё", "е")
    acts = bool(_ACT_CONTEXT.search(flat)) or guess_stage(rel_path) == "ID"
    ambiguous = None
    for part in [filename, *reversed(folders)]:
        found = _section_signals(part, acts=acts)
        sure = [s for s in found if s[0] != _AMBIGUOUS]
        if sure:
            return _strongest(sure), None
        if found and ambiguous is None:
            ambiguous = _strongest(found)
    return "OTHER", ambiguous


def guess_section(rel_path):
    """Раздел файла по пути, если его нет в реестре организатора; «OTHER» — не определён."""
    return section_with_hint(rel_path)[0]


def pdf_page_count(path):
    try:
        import pymupdf
        d = pymupdf.open(path)
        try:
            return d.page_count
        finally:
            d.close()
    except Exception:
        return None


def build(object_id, progress=None, previous=None):
    """Собрать реестр документов одного объекта.

    previous — строки прежнего реестра этого объекта. Локальные идентификаторы
    из него переходят к тем же файлам по SHA-256, новые файлы получают номера
    после наибольшего занятого.
    """
    spec = OBJECTS[object_id]
    root = spec["root"]
    if not os.path.isdir(root):
        raise FileNotFoundError(f"каталог объекта не найден: {root}")

    official = load_official()
    keep = {}
    for r in previous or []:
        if r.get("id_source") == "LOCAL" and r.get("sha256") and re.fullmatch(r"L\d{4}", r.get("file_id") or ""):
            keep.setdefault(r["sha256"], r["file_id"])
    local_n = max((int(fid[1:]) for fid in keep.values()), default=0)
    rows, seen = [], {}
    skipped_n = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()          # порядок обхода не должен зависеть от файловой системы
        for fn in sorted(filenames):
            if fn.startswith(".") or fn == ".DS_Store":
                continue
            ext = os.path.splitext(fn)[1].lower()
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if ext not in SUPPORTED_EXT:
                # формат не читает ни один разбор: раньше файл пропадал молча, теперь
                # виден в реестре со статусом и попадает в отчёт о готовности (#39)
                skipped_n += 1
                rows.append({
                    "file_id": f"U{skipped_n:04d}", "object_id": object_id,
                    "stage": guess_stage(rel), "section": guess_section(rel),
                    "document_code": None, "revision": None, "approval_status": "UNKNOWN",
                    "relative_path": rel, "sha256": None, "pdf_pages": 0,
                    "size_bytes": os.path.getsize(path), "extension": ext,
                    "id_source": "NONE", "status": "UNSUPPORTED_FORMAT",
                })
                continue
            digest = sha256(path)

            if digest in seen:
                # тот же файл лежит в корпусе дважды: встречается регулярно,
                # например архивы исполнительной документации дублируют распакованное
                rows.append({**seen[digest], "relative_path": rel,
                             "duplicate_of": seen[digest]["file_id"]})
                continue

            off = official.get(digest)
            section_guess, hint = section_with_hint(rel)
            if off:
                file_id = off["file_id"]
                stage = off.get("stage") or guess_stage(rel)
                section = off.get("section") or section_guess
                pages = off.get("pdf_pages")
            else:
                if digest in keep:
                    file_id = keep[digest]
                else:
                    local_n += 1
                    file_id = f"L{local_n:04d}"
                stage = guess_stage(rel)
                section = section_guess
                pages = pdf_page_count(path) if ext == ".pdf" else None

            row = {
                "file_id": file_id,
                "object_id": object_id,
                "stage": stage,
                "section": section,
                "document_code": None,      # заполнит команда revisions (#10)
                "revision": None,           # заполнит команда revisions (#10)
                "approval_status": "UNKNOWN",
                "relative_path": rel,
                "sha256": digest,
                "pdf_pages": pages if pages is not None else 0,
                "size_bytes": os.path.getsize(path),
                "extension": ext,
                "id_source": "OFFICIAL" if off else "LOCAL",
            }
            if section == "OTHER" and hint:
                # «ИОС5.N» без подсказки подраздела: раздел не определён, догадка сохранена (#41)
                row["section_hint"] = hint
            seen[digest] = row
            rows.append(row)
            if progress and len(rows) % 25 == 0:
                progress(len(rows))

    lost = sorted(set(keep.values()) - {r["file_id"] for r in rows})
    if lost:
        print(f"  из прежнего реестра нет на диске: {len(lost)} ({', '.join(lost[:5])}…)")
    rows.sort(key=lambda r: (r["file_id"], r["relative_path"]))
    return rows


def summary(rows):
    """Сводка по реестру. Файлы неподдержанных форматов считаются отдельно."""
    import collections
    readable = [r for r in rows if not r.get("status")]
    by_stage = collections.Counter(r["stage"] for r in readable)
    dupes = sum(1 for r in readable if r.get("duplicate_of"))
    official = sum(1 for r in readable if r["id_source"] == "OFFICIAL")
    pages = sum(r.get("pdf_pages") or 0 for r in readable if not r.get("duplicate_of"))
    return {
        "files": len(readable),
        "unique": len(readable) - dupes,
        "duplicates": dupes,
        "with_official_id": official,
        "pages": pages,
        "by_stage": dict(by_stage),
        "unsupported": len(rows) - len(readable),
        "unsupported_by_extension": dict(collections.Counter(
            r["extension"] for r in rows if r.get("status") == "UNSUPPORTED_FORMAT")),
    }
