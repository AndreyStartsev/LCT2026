"""Сравнение стадий по помещениям: какие системы обслуживают помещение в ПД и в РД. Задача #37.

## В чём дело

Все оцениваемые точки эталона — лист проекта против рабочего чертежа по номеру помещения:
«в помещениях 140, 142 отсутствует предусмотренная проектом вытяжная вентиляция, в 147, 198,
314 изменена конфигурация». Правила Матрицы по тексту таких находок не дают: на Тюменской-5
автоматика воспроизводила 0 эталонных точек из 10. Извлечение помещений и марок с чертежей
(`pipeline/plan_rooms.py`, #4) было, генератора находок не было.

## Почему не сравнение марок на планах

На проектной схеме марка системы стоит у подписи помещения, и привязка «ближайший номер»
работает. На рабочем плане марка стоит у воздуховода, а номер помещения — в кружке посреди
комнаты; без контуров помещений марку к комнате не привязать. К тому же подписи плана РД
выведены кривыми и в текстовый слой не попадают. Прямое сравнение давало 16–19 кандидатов
при двух настоящих (#21).

## Что сравнивается

Таблица «Характеристика отопительно-вентиляционных систем» есть в обеих стадиях и называет
помещение словами: «В2.7, В2.8, В2.9 | 3 | М.О. (поз.169) в пом. 140». Разбор —
`pipeline/hvac_systems.py`. Для каждого помещения, которому проект назначил системы:

| В рабочей стадии | Находка |
|---|---|
| помещение не названо ни в одной строке | нарушение, `MISSING_DESIGN_ELEMENT` |
| систем меньше, чем в проекте | нарушение, `CONFIGURATION_MISMATCH` |
| проектные системы помещение больше не обслуживают, вместо них другие | нарушение, `CONFIGURATION_MISMATCH` |
| проектные системы на месте, добавлены новые | нарушения нет, добавленное названо в пояснении |
| число и обозначения те же, расход меньше проектного | нарушение, `VALUE_DECREASE` |
| отличаются только позиции оборудования | нарушения нет, отличие названо в пояснении |
| всё совпало | нарушения нет |

Проверяется выполнение проектного решения, а не запрет на дополнения. Поэтому помещение,
которое системами наделила только рабочая стадия, находкой не становится, а система, добавленная
к проектным, — не нарушение. Замер на Тюменской-5 это подтверждает: у эталонных помещений 147
и 198 проектные системы заменены другими, у 131, 189 и 195 к проектным добавлены новые,
и эталон организатора первые называет нарушением, а вторые нет.

Обозначения сравниваются после свёртки двойников распознавания («82.4» и «B2.4» — это «В2.4»),
и только как множества: «В2.5» иногда читается как «В2.9», поэтому замена утверждается, лишь
когда пропавших проектных обозначений больше, чем неразобранных строк в рабочей таблице.

Номер помещения с распознанного листа принимается голосованием трёх прочтений
(`vector_tables.OCR_VOTES`): «(пом. 108, 201)» одно из прочтений выдаёт как «001», и без
голосования это было ложное «помещение 001 в рабочей документации не названо». Номер, названный
одним прочтением, в решении не участвует ни как проектный, ни как отсутствующий.

Если таблица одной из стадий не найдена или не прочитана, находок нет вовсе: отсутствие
строки в непрочитанной таблице ничего не доказывает.

## Установки

Строка таблицы без номера помещения («П17 | 1 | Пищеблок, 1 эт.») в сравнение по помещениям
не попадает, а обозначения приточных установок с распознанного листа ненадёжны. Состав установок
сверяется по другому источнику — строкам перечня оборудования в текстовом слое
(`pipeline/vent_units.py`): «П17 (L=9060 м3/ч, Pc=350 Па)». Установка, которая есть в проекте
и которой нет в рабочей документации, — находка по параметру «характеристики вентиляторов»;
адрес находки — помещение, у которого установка нарисована на проектных схемах. Если у этого
помещения уже есть находка по составу систем, вторая запись о том же изменении не выдаётся.
Уменьшение давления нарушением не считается: триггер каталога говорит о кратности воздухообмена,
то есть о расходе.

## Страницы-доказательства

У каждой находки — лист таблицы каждой стадии с рамкой строки и пара «проектная схема —
рабочий план» для этого помещения (`pipeline/sheet_pairs.py`, #21): на схеме помещение
подписано с марками систем, на плане показано в экспликации.
"""
import collections
import json
import os
import re

from pipeline import hvac_systems, plan_rooms, reading, room_names, sheet_pairs, vector_tables, vent_units
from pipeline.config import CACHE, OBJECTS, OUT

CACHE_TAG, SCAN_TAG, OCR_TAG = "hvac", "hvacscan", "hvacocr"
CACHE_VERSION = 13      # разбор строк таблицы; меняется вместе с правилами разбора (11: обозначения и номера по глифам, #48)
SCAN_VERSION = 7       # просмотр листов документа: от разбора строк не зависит
# страница может оказаться таблицей систем: по тексту слоя или прежнего распознавания
TABLE_HINT = re.compile(r"обслуживаем\w*\s+помещени|характеристика\s+(?:отопительно|систем)"
                        r"|отопительно\W{0,3}\s*вентиляционн\w+\s+систем", re.I)
MIN_SHEET_PT = 1000          # чертёжный лист: длинная сторона от А3
MAX_LAYER_WORDS = 120        # у таблицы без слоя слов на листе почти нет: основная надпись
MAX_SCAN_PAGES = 80          # сколько листов документа просматривается в поисках таблицы без слоя
MIN_GRID_ROWS, MIN_GRID_COLS = 12, 8
DISCIPLINE = "VENT"           # дисциплина находок этого модуля: рядом со схемой показывается план вентиляции
MIN_TABLE_ROWS = 5           # меньше строк — таблица стадии считается непрочитанной
MIN_ROWS_SHARE = 0.6         # таблица РД короче проектной в такой доле — прочитана не вся
MAX_CONTINUATION = 6         # сколько листов продолжения таблицы просматривается в каждую сторону
FLOW_TOLERANCE = 0.05        # расход в таблицах округлён до десятков
STAGES = {"PD": "PD", "RD": "RD", "RD_ID_MIXED": "RD"}


def _stage_of(doc):
    """Стадия документа для сравнения: PD, RD или ID.

    В смешанной папке организатора («Рабочая и исполнительная документация») исполнительный
    чертёж плана — тот же план, выпущенный отдельным файлом уже по факту строительства.
    Это исполнительная документация, а не рабочая: в пару к проектной схеме идёт лист тома РД,
    а не его исполнительная копия (`revisions.stage_group`, #10).
    """
    from pipeline import revisions
    return revisions.stage_group(doc.get("stage"), doc.get("relative_path") or "")
MM = 72 / 25.4


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _documents(object_id):
    docs = _read_jsonl(os.path.join(OUT, object_id, "documents.jsonl"))
    return [d for d in docs if _stage_of(d) in ("PD", "RD") and d.get("extension") == ".pdf"
            and not d.get("duplicate_of")]


def _page_hints(object_id, doc, root):
    """Страницы документа, текст которых похож на таблицу систем."""
    from pipeline import matrix_rules
    hits = {p for p, text in matrix_rules.page_texts(doc, root) if text and TABLE_HINT.search(text)}
    for row in _page_index(object_id).get(doc["file_id"], ()):
        if TABLE_HINT.search(row[1] or ""):
            hits.add(row[0])
    return sorted(hits)


_PAGE_INDEX = {}


def _page_index(object_id):
    """Текст страниц из постраничного индекса: там есть и прежнее распознавание."""
    if object_id not in _PAGE_INDEX:
        out = collections.defaultdict(list)
        for r in _read_jsonl(os.path.join(OUT, object_id, "pages.jsonl")):
            out[r["file_id"]].append((r["pdf_page_number"], r.get("text") or ""))
        _PAGE_INDEX[object_id] = out
    return _PAGE_INDEX[object_id]


def _is_hvac(doc, root=None):
    """Документ отопления и вентиляции: по разделу реестра, а где реестр раздел не назвал — по пути файла.

    По тексту первых страниц раздел не определяется: состав проекта перечисляет все тома
    в каждом томе, и «Отопление, вентиляция» стоит на третьей странице любого раздела.
    На Новослободской так в отопление и вентиляцию попадали 17 томов из 46.
    """
    from pipeline import registry
    if doc.get("section") == "OV":
        return True
    if doc.get("section") not in (None, "", "OTHER"):
        return False
    return registry.guess_section(doc.get("relative_path") or "") == "OV"


def _parse_cached(pdf, doc, page_no, use_ocr):
    got = reading.cache_get(doc["sha256"], page_no, CACHE_TAG)
    if got and got.get("version") == CACHE_VERSION and (got.get("ocr") or not use_ocr or not got.get("needs_ocr")):
        return got["rows"], got
    # прочтения ячеек хранятся отдельно от разбора: правка правил разбора не должна стоить минут Tesseract
    cells = (reading.cache_get(doc["sha256"], page_no, OCR_TAG) or {}).get("cells") or {}
    before = len(cells)
    rows, info = hvac_systems.parse_page(pdf[page_no - 1], use_ocr=use_ocr, ocr_cache=cells)
    if len(cells) > before:
        reading.cache_put(doc["sha256"], page_no, OCR_TAG, {"cells": cells})
    value = {"version": CACHE_VERSION, "rows": rows, "ocr": bool(use_ocr and not info["ocr_failed"]),
             "needs_ocr": bool(info["ocr_failed"] or (not use_ocr and info["grid"] and not rows)),
             "ocr_cells": info["ocr_cells"]}
    if not info["ocr_failed"]:
        reading.cache_put(doc["sha256"], page_no, CACHE_TAG, value)
    return rows, value


def _scan_pages(pdf, sha):
    """Листы без текстового слоя, на которых стоит большая сетка: кандидаты в таблицу систем.

    Просмотр идёт по всем листам документа и не зависит от распознавания, поэтому его итог
    кешируется целиком: страница 0 — сведения о документе.
    """
    got = reading.cache_get(sha, 0, SCAN_TAG)
    if got and got.get("version") == SCAN_VERSION:
        return got["pages"]
    out, looked = [], 0
    for i in range(pdf.page_count):
        if looked >= MAX_SCAN_PAGES:
            break
        page = pdf[i]
        if max(page.rect.width, page.rect.height) < MIN_SHEET_PT:
            continue
        if len(page.get_text("words")) > MAX_LAYER_WORDS:
            continue
        looked += 1
        grid = vector_tables.find_grid(page)
        if grid and len(grid.ys) >= MIN_GRID_ROWS and len(grid.xs) >= MIN_GRID_COLS:
            out.append(i + 1)
    reading.cache_put(sha, 0, SCAN_TAG, {"version": SCAN_VERSION, "pages": out})
    return out


def collect_systems(object_id, use_ocr=True, progress=None):
    """Строки таблиц систем по объекту: [{stage, file_id, pdf_page_number, document, source, …}].

    Вторым значением — сводка: сколько документов и листов просмотрено, сколько ячеек распознано.
    Сравнивать можно только обе стадии, поэтому сбор идёт по стадиям и обрывается, как только
    у одной из них таблицы нет: на объекте без рабочей документации ОВ проектные тома не читаются вовсе.
    """
    import pymupdf
    try:
        pymupdf.TOOLS.mupdf_display_errors(False)
    except Exception:
        pass
    root = OBJECTS[object_id]["root"]
    docs = [d for d in _documents(object_id) if _is_hvac(d)]
    by_stage = {stage: [d for d in docs if _stage_of(d) == stage] for stage in ("RD", "PD")}
    rows, summary = [], collections.Counter()
    names = {"PD": "проектной", "RD": "рабочей"}
    for stage in ("RD", "PD"):          # рабочих томов меньше, и чаще нет именно их
        if not by_stage[stage]:
            summary["отказ"] = f"в {names[stage]} стадии нет документов отопления и вентиляции"
            return [], summary
    done_docs = 0
    for stage in ("RD", "PD"):
        found_stage = 0
        for doc in by_stage[stage]:
            found_stage += _collect_document(object_id, doc, root, use_ocr, rows, summary)
            done_docs += 1
            if progress:
                progress(done_docs, len(docs), summary["листов разобрано"])
        if not found_stage:
            summary["отказ"] = f"таблица характеристик систем в {names[stage]} стадии не найдена"
            return [], summary
    return _authoritative(_latest_revisions(rows, object_id)), summary


def _collect_document(object_id, doc, root, use_ocr, rows, summary):
    """Таблицы систем одного документа — в rows. Возвращает число найденных строк."""
    import pymupdf
    try:
        pdf = pymupdf.open(os.path.join(root, doc["relative_path"]))
    except Exception:
        summary["документ не открылся"] += 1
        return 0
    summary["документов"] += 1
    done, found_here = set(), 0

    def take(page_no):
        """Разобрать лист; вернуть число строк таблицы на нём."""
        if page_no in done or not 1 <= page_no <= pdf.page_count:
            return 0
        done.add(page_no)
        summary["листов разобрано"] += 1
        page_rows, info = _parse_cached(pdf, doc, page_no, use_ocr)
        summary["ячеек распознано"] += info.get("ocr_cells") or 0
        if info.get("needs_ocr"):
            summary["листов без распознавания"] += 1
        for r in page_rows:
            rows.append(dict(r, stage=_stage_of(doc), file_id=doc["file_id"], pdf_page_number=page_no,
                             document=os.path.basename(doc["relative_path"]), section=doc.get("section"),
                             source=r.get("read") or "LAYER"))
        return len(page_rows)

    # Сначала листы, на которые указывает текст. Если таблица выведена кривыми, текст укажет
    # только на оглавление и пояснительную записку — тогда листы без слоя просматриваются
    # по сетке: на Тюменской-5 таблица тома ИОС5.4.2 нашлась только так.
    for by_grid in (False, True):
        pages = _scan_pages(pdf, doc["sha256"]) if by_grid else _page_hints(object_id, doc, root)
        for page_no in pages:
            got = take(page_no)
            found_here += got
            # Таблица занимает несколько листов подряд, а заголовок стоит только на первом:
            # лист продолжения текст не выдаёт. Пропущенное продолжение — это десятки ложных
            # «в рабочей документации помещение не названо», поэтому соседи разбираются всегда.
            for direction in (1, -1):
                step = 1
                while got and step <= MAX_CONTINUATION:
                    more = take(page_no + direction * step)
                    if not more:
                        break
                    found_here += more
                    step += 1
        if found_here:
            break
    pdf.close()
    if found_here:
        summary["документов с таблицей"] += 1
    return found_here


def _authoritative(rows):
    """Один источник на стадию: таблицы раздела ОВ, а копии из других разделов — только если своих нет.

    Таблицу систем повторяют чужие разделы: в томе 8.1 «Охрана окружающей среды» Тюменской-5
    лежит её копия с вытяжными системами. Сложенные вместе, две таблицы удваивают число систем
    у каждого помещения, а неполная копия даёт ложное «в проекте одна система, в рабочей две».
    Одинаковые строки разных документов одной стадии считаются один раз.
    """
    out = []
    for stage in ("PD", "RD"):
        side = [r for r in rows if r["stage"] == stage]
        own = [r for r in side if r.get("section") == "OV"]
        seen = set()
        for r in own or side:
            key = (re.sub(r"\W", "", r["system_raw"]).upper(), tuple(r["rooms"]), r.get("count"))
            if key not in seen:
                seen.add(key)
                out.append(r)
    return out


def _revision_rank(object_id):
    """Ранг редакции документа: по цепочкам реестра (#10), а без них — по имени файла, как в правилах Матрицы."""
    from pipeline import matrix_rules
    index = matrix_rules.chain_index(_read_jsonl(os.path.join(OUT, object_id, "documents.jsonl")),
                                     _read_jsonl(os.path.join(OUT, object_id, "revisions.jsonl")))

    def rank(file_id, name):
        chain = index.get(file_id)
        return (chain["chain"], chain["rank"]) if chain else matrix_rules.revision_key(name)
    return rank


def _latest_revisions(rows, object_id):
    """Таблицы только последней редакции каждого документа."""
    rank = _revision_rank(object_id)
    best = {}
    for r in rows:
        base, n = rank(r["file_id"], r["document"])
        key = (r["stage"], base)
        best[key] = max(best.get(key, -1), n)
    return [r for r in rows if rank(r["file_id"], r["document"])[1] == best[(r["stage"], rank(r["file_id"], r["document"])[0])]]


# ---------- сравнение ----------

def served_map(rows):
    """Помещение → строки таблицы, которые его называют."""
    out = collections.defaultdict(list)
    for r in rows:
        for room in r["rooms"]:
            out[room].append(r)
    return out


def _total(rows):
    return sum((r.get("count") or len(r["systems"]) or 1) for r in rows)


def _flow(rows):
    flows = [r.get("flow") for r in rows]
    return sum(f * (r.get("count") or 1) for f, r in zip(flows, rows)) if flows and all(flows) else None


def _names(rows):
    return sorted(_keys(rows))


def _describe(rows):
    """Строка значения для карточки: «3 системы: В2.7, В2.8, В2.9; поз. 169»."""
    if not rows:
        return None
    total = _total(rows)
    parts = [f"{total} {_plural(total)}"]
    names = ", ".join(_names(rows))
    if names:
        parts[0] += f": {names}" + ("" if all(r.get("source") == "LAYER" for r in rows) else " (распознано с листа)")
    positions = sorted({p for r in rows for p in r["positions"]}, key=int)
    if positions:
        parts.append("поз. " + ", ".join(positions))
    flow = _flow(rows)
    if flow:
        parts.append(f"L={flow} м³/ч")
    return "; ".join(parts)


def _plural(n):
    if n % 10 == 1 and n % 100 != 11:
        return "система"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "системы"
    return "систем"


_TWINS = str.maketrans({"A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О",
                         "P": "Р", "T": "Т", "X": "Х", "Y": "У"})


def system_key(text):
    """Обозначение для сравнения стадий: двойники распознавания свёрнуты, знаки отброшены."""
    key = re.sub(r"[^0-9A-ZА-Я.]", "", (text or "").upper().translate(_TWINS))
    return re.sub(r"^8(?=\d)", "В", key).rstrip(".")


def _keys(rows):
    return {system_key(s) for r in rows for s in r["systems"]} - {""}


def _unparsed(rows):
    """Сколько систем стоит в строках, обозначение которых разобрать не удалось."""
    return sum((r.get("count") or 1) for r in rows if not r["systems"])


def decide(pd_rows, rd_rows, rd_doubtful=False):
    """Решение по помещению: (метка, тип расхождения, пояснение)."""
    if not rd_rows:
        if rd_doubtful:
            return ("COMPARISON_IMPOSSIBLE", None,
                    "номер помещения в таблице рабочей стадии прочитан неуверенно: одно прочтение из трёх")
        return "VIOLATION_PRESENT", "MISSING_DESIGN_ELEMENT", "в таблице систем рабочей стадии помещение не названо"
    pd_total, rd_total = _total(pd_rows), _total(rd_rows)
    if rd_total < pd_total:
        return ("VIOLATION_PRESENT", "CONFIGURATION_MISMATCH",
                f"систем меньше, чем в проекте: {pd_total} в ПД, {rd_total} в РД")
    removed = sorted(_keys(pd_rows) - _keys(rd_rows))
    added = sorted(_keys(rd_rows) - _keys(pd_rows))
    if removed and not _unparsed(pd_rows):
        if len(removed) > _unparsed(rd_rows):
            return ("VIOLATION_PRESENT", "CONFIGURATION_MISMATCH",
                    f"проектные системы {', '.join(removed)} помещение в РД не обслуживают"
                    + (f", вместо них {', '.join(added)}" if added else ""))
        return ("COMPARISON_IMPOSSIBLE", None,
                f"обозначения систем рабочей стадии разобраны не все; проектные {', '.join(removed)} среди них не найдены")
    if rd_total > pd_total:
        return ("NO_VIOLATION", "NON_TRIGGERING_DIFFERENCE_NO_DECREASE",
                f"проектные системы на месте, в РД добавлено: {', '.join(added) or rd_total - pd_total}")
    pd_flow, rd_flow = _flow(pd_rows), _flow(rd_rows)
    if pd_flow and rd_flow and rd_flow < pd_flow * (1 - FLOW_TOLERANCE):
        return "VIOLATION_PRESENT", "VALUE_DECREASE", f"суммарный расход: {pd_flow} м³/ч в ПД, {rd_flow} м³/ч в РД"
    pd_pos = sorted({p for r in pd_rows for p in r["positions"]})
    rd_pos = sorted({p for r in rd_rows for p in r["positions"]})
    if pd_pos != rd_pos:
        return ("NO_VIOLATION", "NON_TRIGGERING_DIFFERENCE_NO_DECREASE",
                f"число систем совпадает, позиции оборудования: {', '.join(pd_pos) or '—'} в ПД, "
                f"{', '.join(rd_pos) or '—'} в РД")
    return "NO_VIOLATION", "EQUAL_PD_RD", "состав систем совпадает"


def compare(rows):
    """Сравнение по помещениям: [(помещение, строки ПД, строки РД, метка, тип, пояснение)] или причина отказа."""
    pd = [r for r in rows if r["stage"] == "PD"]
    rd = [r for r in rows if r["stage"] == "RD"]
    if len(pd) < MIN_TABLE_ROWS or len(rd) < MIN_TABLE_ROWS:
        missing = [name for name, side in (("проектной", pd), ("рабочей", rd)) if len(side) < MIN_TABLE_ROWS]
        return [], f"таблица систем {' и '.join(missing)} стадии не найдена или не прочитана"
    pd_map, rd_map = served_map(pd), served_map(rd)
    rd_doubtful = {room for r in rd for room in r.get("rooms_doubtful") or ()}
    partial = len(rd) < MIN_ROWS_SHARE * len(pd)
    out = []
    for room in sorted(pd_map, key=_room_key):
        label, result, detail = decide(pd_map[room], rd_map.get(room, []), room in rd_doubtful)
        if partial and result == "MISSING_DESIGN_ELEMENT":
            # «в таблице РД помещения нет» весит что-то, только если таблица РД прочитана целиком
            label, result = "COMPARISON_IMPOSSIBLE", None
            detail = (f"таблица систем рабочей стадии прочитана не полностью: строк {len(rd)} против {len(pd)} "
                      f"в проектной; отсутствие помещения в ней ничего не доказывает")
        out.append((room, pd_map[room], rd_map.get(room, []), label, result, detail))
    return out, None


def _room_key(room):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", room)]


# ---------- листы-доказательства ----------

def _plan_rows(object_id, documents, file_ids):
    """Помещения на чертёжных листах нужных документов: из сборки объекта, а если её нет — с листов."""
    ready = [r for r in _read_jsonl(os.path.join(OUT, object_id, "plan_rooms.jsonl")) if r["file_id"] in file_ids]
    if ready:
        return ready
    import pymupdf
    root, out = OBJECTS[object_id]["root"], []
    for fid in sorted(file_ids):
        doc = documents[fid]
        try:
            pdf = pymupdf.open(os.path.join(root, doc["relative_path"]))
        except Exception:
            continue
        for i in range(pdf.page_count):
            page = pdf[i]
            w, h = page.rect.width or 1.0, page.rect.height or 1.0
            if max(w, h) < MIN_SHEET_PT:
                continue
            words = [{"t": t, "bbox": [x0 / w, y0 / h, x1 / w, y1 / h]}
                     for x0, y0, x1, y1, t in vector_tables.layer_words(page)]
            for item in plan_rooms.extract(words):
                out.append({"file_id": fid, "stage": doc.get("stage"), "pdf_page_number": i + 1, **item})
        pdf.close()
    return out


def _titles(documents, keys, root=None):
    """Наименования листов из графы 4 основной надписи: по словам слоя, а если их там нет — по распознанному углу.

    Источники не смешиваются: у листа со слоем распознанный угол повторяет те же слова с ошибками,
    и наименование выходило сдвоенным — «Принципиальная Принципиальная схема схема сустем систем».
    Слова слоя берутся из кеша чтения; если листа в кеше нет, а корень объекта задан, — прямо из PDF:
    кеш чтения лежит в git не у всех объектов, и без этого пары молча подбирались бы без наименований.
    """
    out, opened = {}, {}
    for fid, page_no in sorted(keys):
        sha = documents[fid]["sha256"]
        layer, corner = [], []
        got = reading.cache_get(sha, page_no, "read")
        if got and got.get("words"):
            w_mm = (got.get("width_pt") or 0) / MM or 1.0
            h_mm = (got.get("height_pt") or 0) / MM or 1.0
            for w in got["words"]:
                b = w["bbox"]
                layer.append((w["t"], (1 - (b[0] + b[2]) / 2) * w_mm, (1 - (b[1] + b[3]) / 2) * h_mm))
        elif not got and root:
            layer = _corner_words(opened, os.path.join(root, documents[fid].get("relative_path") or ""), page_no)
        path = os.path.join(CACHE, "tbocr", sha[:2], f"{sha}-{page_no:05d}.json")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    corner = [(w.get("t") or "", w.get("dx") or 0.0, w.get("dy") or 0.0)
                              for w in (json.load(f).get("words") or [])]
            except (OSError, ValueError):
                pass
        name = sheet_pairs.sheet_name(layer) or sheet_pairs.sheet_name(corner)
        if name:
            out[(fid, page_no)] = name
    for pdf in opened.values():
        if pdf is not None:
            pdf.close()
    return out


def _corner_words(opened, path, page_no):
    """Слова текстового слоя листа с расстоянием до правого нижнего угла в миллиметрах."""
    import pymupdf
    if path not in opened:
        try:
            opened[path] = pymupdf.open(path)
        except Exception:
            opened[path] = None
    pdf = opened[path]
    if pdf is None or not 1 <= page_no <= pdf.page_count:
        return []
    page = pdf[page_no - 1]
    width, height = page.rect.width, page.rect.height
    return [(t, (width - (x0 + x1) / 2) / MM, (height - (y0 + y1) / 2) / MM)
            for x0, y0, x1, y1, t in vector_tables.layer_words(page)]


def _scheme_pages(plan_rows, documents, room, family):
    """Проектные листы, где помещение подписано с марками систем того же рода («В», «П»)."""
    out = []
    for r in plan_rows:
        if r["number"] != room or _stage_of(documents.get(r["file_id"]) or {}) != "PD":
            continue
        marks = [m for m in r.get("marks") or [] if not family or m[:1] in family]
        if marks:
            out.append((len(marks), r))
    out.sort(key=lambda x: (-x[0], x[1]["file_id"], x[1]["pdf_page_number"]))
    return [r for _, r in out]


def _evidence(room, pd_rows, rd_rows, rd_pages, plan_rows, paired, documents):
    evidence = []
    for stage, rows in (("PD", pd_rows), ("RD", rd_rows)):
        for r in rows:
            evidence.append({"stage": stage, "file_id": r["file_id"], "pdf_page_number": r["pdf_page_number"],
                             "quote": f"{r['system_raw']} | {r.get('count') or ''} | {r['served']}".strip(" |"),
                             "localization": "BBOX", "bbox_norm": r["bbox"], "role": "SYSTEMS_TABLE"})
    if not rd_rows:
        # помещения в таблице РД нет: показываем сами листы таблицы, рамки на них быть не может
        for fid, page_no in rd_pages[:2]:
            evidence.append({"stage": "RD", "file_id": fid, "pdf_page_number": page_no, "localization": "PAGE_LEVEL",
                             "quote": f"в таблице систем помещение {room} не названо", "role": "SYSTEMS_TABLE"})
    family = {s[:1] for r in pd_rows for s in r["systems"]}
    for scheme in _scheme_pages(plan_rows, documents, room, family)[:1]:
        key = (scheme["file_id"], scheme["pdf_page_number"])
        evidence.append({"stage": "PD", "file_id": key[0], "pdf_page_number": key[1], "localization": "BBOX",
                         "bbox_norm": scheme["bbox"], "role": "SCHEME",
                         "quote": f"{room} {scheme.get('name') or ''}: {', '.join(scheme.get('marks') or [])}".strip()})
        for plan in sheet_pairs.for_room(paired, key, room, want=DISCIPLINE)[:1]:
            spot = next((r["bbox"] for r in plan_rows if r["file_id"] == plan["file_id"]
                         and r["pdf_page_number"] == plan["pdf_page_number"] and r["number"] == room), None)
            evidence.append({"stage": "RD", "file_id": plan["file_id"], "pdf_page_number": plan["pdf_page_number"],
                             "localization": "BBOX" if spot else "PAGE_LEVEL", "bbox_norm": spot, "role": "PLAN",
                             "quote": f"лист рабочей документации с помещением {room}; общих помещений со схемой "
                                      f"{plan['shared']}"})
    return evidence


# ---------- находки ----------

def build_findings(object_id, code="IOS4-078", rule=None, catalog=None, use_ocr=True, progress=None):
    """Находки сравнения по помещениям. Возвращает (находки, сводка, строки таблиц)."""
    rule, cat = rule or {}, (catalog or {}).get(code, {})
    rows, summary = collect_systems(object_id, use_ocr=use_ocr, progress=progress)
    compared, refusal = compare(rows)
    summary["строк ПД"] = sum(1 for r in rows if r["stage"] == "PD")
    summary["строк РД"] = sum(1 for r in rows if r["stage"] == "RD")
    if refusal:
        summary["отказ"] = summary.get("отказ") or refusal      # причина со сбора точнее: она называет стадию
        return [], summary, rows
    documents = {d["file_id"]: d for d in _documents(object_id)}
    file_ids = {r["file_id"] for r in rows}
    hvac_ids = {fid for fid, d in documents.items() if d.get("section") == "OV"} | file_ids
    plan_rows = _plan_rows(object_id, documents, hvac_ids)
    keys = {(r["file_id"], r["pdf_page_number"]) for r in plan_rows}
    paired = sheet_pairs.pairs(plan_rows, documents, _titles(documents, keys, OBJECTS[object_id]["root"]))
    rd_pages = sorted({(r["file_id"], r["pdf_page_number"]) for r in rows if r["stage"] == "RD"})
    rd_map = served_map([r for r in rows if r["stage"] == "RD"])
    pd_rooms = set(served_map([r for r in rows if r["stage"] == "PD"]))

    # Сверка наименований (#46): номер должен носить одно и то же помещение. Если рабочая стадия
    # перенумеровала помещения, сравнение по номеру даёт пачку ложных «помещение не названо»
    names = room_names.load(object_id, OUT)
    renumbered, named, differ = room_names.refusal(names, [room for room, *_ in compared])
    summary["наименования в двух стадиях"] = f"сверено {named}, разных {differ}"
    if renumbered:
        summary["отказ"] = renumbered

    findings, equal, impossible = [], [], []
    for room, pd_rows, rd_rows, label, result, detail in compared:
        label, result, detail = refuse_renumbered(label, result, detail, renumbered)
        summary[label] += 1
        if label == "NO_VIOLATION":
            equal.append((room, result, detail, pd_rows, rd_rows))
            continue
        if label == "COMPARISON_IMPOSSIBLE":
            impossible.append((room, result, detail, pd_rows, rd_rows))
            continue
        moved = _moved_to(pd_rows, rd_map, pd_rooms) if result == "MISSING_DESIGN_ELEMENT" else ""
        # тот ли это номер: том раздела может называть номером другое помещение, чем экспликация
        checked = names.check(room, pd_rows[0]["file_id"])
        named_as = room_names.note(room, checked)
        if checked["status"] == "DIFFERENT" and checked.get("carried_by"):
            other = checked["carried_by"]
            _l, _r, other_detail = decide(pd_rows, rd_map.get(other, []))
            named_as += f"; по номеру {other} в таблице рабочей стадии: {other_detail}"
        made = _finding(object_id, code, cat, rule, room, label, result, detail + moved + named_as,
                        _describe(pd_rows), _describe(rd_rows) or "систем для помещения нет",
                        _evidence(room, pd_rows, rd_rows, rd_pages, plan_rows, paired, documents))
        made["extraction"]["room_names"] = checked
        findings.append(made)
    if equal:
        findings.append(_group_finding(object_id, code, cat, rule, equal, "NO_VIOLATION"))
    if impossible:
        findings.append(_group_finding(object_id, code, cat, rule, impossible, "COMPARISON_IMPOSSIBLE"))
    summary["помещений сравнено"] = len(compared)
    return findings, summary, rows


def refuse_renumbered(label, result, detail, reason):
    """Нарушение по номеру помещения не объявляется, если стадии нумеруют помещения по-разному (#46)."""
    if not reason or label != "VIOLATION_PRESENT":
        return label, result, detail
    return "COMPARISON_IMPOSSIBLE", None, f"{reason}; по номеру вышло бы: {detail}"


def _moved_to(pd_rows, rd_map, pd_rooms):
    """Куда в рабочей стадии ушло оборудование тех же позиций: помещения, которых в таблице ПД не было."""
    positions = {p for r in pd_rows for p in r["positions"]}
    rooms = sorted({room for room, rows in rd_map.items() if room not in pd_rooms
                    and positions & {p for r in rows for p in r["positions"]}}, key=_room_key)
    return f"; оборудование тех же позиций в РД отнесено к пом. {', '.join(rooms)}" if rooms and positions else ""


def _finding(object_id, code, cat, rule, room, label, result, detail, pd_value, rd_value, evidence):
    titles = {"MISSING_DESIGN_ELEMENT": f"Системы, назначенные проектом помещению {room}, в рабочей документации отсутствуют",
              "CONFIGURATION_MISMATCH": f"Состав систем помещения {room} в рабочей документации изменён",
              "VALUE_DECREASE": f"Расход систем помещения {room} в рабочей документации уменьшен"}
    return {
        "finding_id": f"{object_id}::{code}::room-{room}",
        "object_id": object_id,
        "matrix_scope": "MATRIX",
        "parameter_code": code,
        "parameter_id": cat.get("parameter_id"),
        "title": titles.get(result, cat.get("parameter_name") or code),
        "comparison_result": result,
        "location_type": "ROOM",
        "locations": [room],
        "pd_value": pd_value,
        "rd_value": rd_value,
        "id_value": None,
        "violation_label": label,
        "criticality": cat.get("criticality") if label == "VIOLATION_PRESENT" else None,
        "finding_status": "CANDIDATE",
        "needs_expert": True,
        "evidence": evidence,
        "extraction": {"rule_basis": rule.get("basis"), "detail": detail, "source": "SYSTEMS_TABLE",
                       "pd": {"raw": pd_value}, "rd": {"raw": rd_value}},
    }


def _group_finding(object_id, code, cat, rule, group, label):
    """Одна запись на все помещения без нарушения (или без сравнения): запись на помещение здесь — шум."""
    rooms = [room for room, *_ in group]
    evidence, seen = [], set()
    for _, _, _, pd_rows, rd_rows in group:
        for stage, rows in (("PD", pd_rows), ("RD", rd_rows)):
            for r in rows:
                key = (stage, r["file_id"], r["pdf_page_number"])
                if key not in seen:
                    seen.add(key)
                    evidence.append({"stage": stage, "file_id": r["file_id"], "pdf_page_number": r["pdf_page_number"],
                                     "quote": "таблица характеристик систем", "localization": "PAGE_LEVEL",
                                     "role": "SYSTEMS_TABLE"})
    if label == "NO_VIOLATION":
        notes = [f"пом. {room}: {detail}" for room, result, detail, *_ in group if result != "EQUAL_PD_RD"]
        value = f"состав систем совпадает, помещений: {len(rooms)}"
        detail = "сверены помещения " + ", ".join(rooms) + ("; " + "; ".join(notes) if notes else "")
        title = "Состав систем, обслуживающих помещения, совпадает в проектной и рабочей стадии"
        slug, result = "rooms-equal", "EQUAL_PD_RD"
    else:
        value = f"помещений с системами по проекту: {len(rooms)}"
        detail = group[0][2] + "; помещения " + ", ".join(rooms)
        title = "Состав систем по помещениям сравнить не удалось"
        slug, result = "rooms-impossible", "VALUE_MISMATCH"
    return {
        "finding_id": f"{object_id}::{code}::{slug}",
        "object_id": object_id,
        "matrix_scope": "MATRIX",
        "parameter_code": code,
        "parameter_id": cat.get("parameter_id"),
        "title": title,
        "comparison_result": result,
        "location_type": "OBJECT",
        "locations": ["Здание"],
        "pd_value": value,
        "rd_value": value if label == "NO_VIOLATION" else None,
        "id_value": None,
        "violation_label": label,
        "criticality": None,
        "finding_status": "CANDIDATE",
        "evidence": evidence[:6],
        "extraction": {"rule_basis": rule.get("basis"), "detail": detail, "source": "SYSTEMS_TABLE",
                       "pd": {"raw": value}, "rd": {"raw": value if label == "NO_VIOLATION" else None}},
    }


# ---------- установки ----------

MIN_UNITS = 5               # меньше установок в стадии — перечень оборудования не найден


def collect_units(object_id):
    """Установки по стадиям из текстового слоя: {стадия: {установка: [{flow, pressure, file_id, page, snippet}]}}."""
    from pipeline import matrix_rules, tep
    root = OBJECTS[object_id]["root"]
    found = {"PD": collections.defaultdict(list), "RD": collections.defaultdict(list)}
    ranks = {}
    rank = _revision_rank(object_id)
    for doc in _documents(object_id):
        if not _is_hvac(doc):
            continue
        stage = _stage_of(doc)
        name = os.path.basename(doc["relative_path"])
        for page_no, text in matrix_rules.page_texts(doc, root):
            for d in vent_units.unit_duties(tep.flatten(text or "")):
                found[stage][d["unit"]].append(dict(d, file_id=doc["file_id"], page=page_no, document=name))
                ranks[(stage, doc["file_id"])] = rank(doc["file_id"], name)
    # только последняя редакция каждого документа, как в правилах Матрицы
    best = {}
    for (stage, fid), (base, rank) in ranks.items():
        best[(stage, base)] = max(best.get((stage, base), -1), rank)
    for stage, units in found.items():
        for unit in list(units):
            units[unit] = [d for d in units[unit]
                           if ranks[(stage, d["file_id"])][1] == best[(stage, ranks[(stage, d["file_id"])][0])]]
            if not units[unit]:
                del units[unit]
    return found


def _unit_rooms(object_id, documents, units):
    """Где на проектных схемах стоят установки: {установка: (помещение, [(file_id, стр., прямоугольник)])}."""
    import pymupdf
    root = OBJECTS[object_id]["root"]
    sightings = collections.defaultdict(list)
    for fid, doc in sorted(documents.items()):
        if _stage_of(doc) != "PD" or not _is_hvac(doc):
            continue
        try:
            pdf = pymupdf.open(os.path.join(root, doc["relative_path"]))
        except Exception:
            continue
        for i in range(pdf.page_count):
            page = pdf[i]
            if max(page.rect.width, page.rect.height) < MIN_SHEET_PT:
                continue
            words = vector_tables.layer_words(page)
            near = vent_units.nearest_rooms(words, page.rect.width or 1.0, page.rect.height or 1.0, units)
            for unit, (room, distance, box) in near.items():
                sightings[unit].append(((fid, i + 1, box), room, distance))
        pdf.close()
    out = {}
    for unit, seen in sightings.items():
        room, sheets = vent_units.vote_room(seen)
        if room:
            out[unit] = (room, [sheet for sheet, _, _ in sorted(sheets, key=lambda x: x[2])])
    return out


def build_unit_findings(object_id, code="IOS4-079", rule=None, catalog=None, reported_rooms=()):
    """Находки по составу установок. reported_rooms — помещения, по которым находка уже выдана."""
    rule, cat = rule or {}, (catalog or {}).get(code, {})
    summary = collections.Counter()
    units = collect_units(object_id)
    pd, rd = units["PD"], units["RD"]
    summary["установок ПД"], summary["установок РД"] = len(pd), len(rd)
    if len(pd) < MIN_UNITS or len(rd) < MIN_UNITS:
        summary["отказ"] = "перечень установок с расходом найден не в обеих стадиях"
        return [], summary
    documents = {d["file_id"]: d for d in _documents(object_id)}
    gone = sorted(set(pd) - set(rd))
    rooms = _unit_rooms(object_id, documents, set(gone))
    plan_rows = paired = None
    findings, compared = [], 0
    for unit in gone:
        heirs = sorted(u for u in set(rd) - set(pd) if vent_units.family(u) == unit)
        room, sheets = rooms.get(unit, (None, []))
        if room and room in reported_rooms:
            summary["уже названо находкой по помещению"] += 1
            continue
        pd_flow = max(d["flow"] for d in pd[unit])
        rd_flow = sum(max(d["flow"] for d in rd[h]) for h in heirs) if heirs else None
        if heirs and rd_flow < pd_flow * (1 - FLOW_TOLERANCE):
            result = "VALUE_DECREASE"
            detail = f"установка {unit} заменена на {', '.join(heirs)} с меньшим суммарным расходом"
        elif heirs:
            result = "CONFIGURATION_MISMATCH"
            detail = f"установка {unit} заменена на {', '.join(heirs)}, суммарный расход не меньше проектного"
        else:
            result = "MISSING_DESIGN_ELEMENT"
            detail = f"установки {unit} в перечне оборудования рабочей стадии нет"
        if plan_rows is None:
            hvac_ids = {fid for fid, d in documents.items() if d.get("section") == "OV"}
            plan_rows = _plan_rows(object_id, documents, hvac_ids)
            keys = {(r["file_id"], r["pdf_page_number"]) for r in plan_rows}
            paired = sheet_pairs.pairs(plan_rows, documents, _titles(documents, keys, OBJECTS[object_id]["root"]))
        evidence = [{"stage": "PD", "file_id": d["file_id"], "pdf_page_number": d["page"], "quote": d["snippet"],
                     "localization": "PAGE_LEVEL", "role": "EQUIPMENT_LIST"} for d in pd[unit][:1]]
        for fid, page_no, box in sheets[:3]:
            evidence.append({"stage": "PD", "file_id": fid, "pdf_page_number": page_no, "localization": "BBOX",
                             "bbox_norm": box, "role": "SCHEME", "quote": f"{unit} у помещения {room}"})
        for h in heirs:
            for d in rd[h][:1]:
                evidence.append({"stage": "RD", "file_id": d["file_id"], "pdf_page_number": d["page"],
                                 "quote": d["snippet"], "localization": "PAGE_LEVEL", "role": "EQUIPMENT_LIST"})
        plans = []
        for fid, page_no, _ in sheets:
            plans += [p for p in sheet_pairs.for_room(paired, (fid, page_no), room) if p not in plans]
        for plan in sorted(plans, key=lambda r: (0 if DISCIPLINE in r.get("tags", ()) else 1, -r["score"],
                                                 r["file_id"], r["pdf_page_number"]))[:1]:
            spot = next((r["bbox"] for r in plan_rows if r["file_id"] == plan["file_id"]
                         and r["pdf_page_number"] == plan["pdf_page_number"] and r["number"] == room), None)
            evidence.append({"stage": "RD", "file_id": plan["file_id"], "pdf_page_number": plan["pdf_page_number"],
                             "localization": "BBOX" if spot else "PAGE_LEVEL", "bbox_norm": spot, "role": "PLAN",
                             "quote": f"лист рабочей документации с помещением {room}"})
        pd_value = f"{unit}: L={pd_flow} м³/ч, Pc={max(d['pressure'] for d in pd[unit])} Па"
        rd_value = ("; ".join(f"{h}: L={max(d['flow'] for d in rd[h])} м³/ч, Pc={max(d['pressure'] for d in rd[h])} Па"
                              for h in heirs) if heirs else "установки нет")
        if not any(e["stage"] == "RD" for e in evidence):
            # установки в РД нет, и показать нечего, кроме самого перечня оборудования рабочей стадии
            first = min((d for ds in rd.values() for d in ds), key=lambda d: (d["file_id"], d["page"]))
            evidence.append({"stage": "RD", "file_id": first["file_id"], "pdf_page_number": first["page"],
                             "quote": f"в перечне оборудования установки {unit} нет", "localization": "PAGE_LEVEL",
                             "role": "EQUIPMENT_LIST"})
        findings.append({
            "finding_id": f"{object_id}::{code}::unit-{unit}",
            "object_id": object_id,
            "matrix_scope": "MATRIX",
            "parameter_code": code,
            "parameter_id": cat.get("parameter_id"),
            "title": f"Установка {unit} по проекту" + (f" в помещении {room}" if room else "")
                     + (" заменена в рабочей документации" if heirs else " в рабочей документации отсутствует"),
            "comparison_result": result,
            "location_type": "ROOM" if room else "OBJECT",
            "locations": [room] if room else ["Здание"],
            "pd_value": pd_value,
            "rd_value": rd_value,
            "id_value": None,
            "violation_label": "VIOLATION_PRESENT",
            "criticality": cat.get("criticality"),
            "finding_status": "CANDIDATE",
            "needs_expert": True,
            "evidence": evidence,
            "extraction": {"rule_basis": rule.get("basis"), "detail": detail, "source": "EQUIPMENT_LIST",
                           "pd": {"raw": pd_value}, "rd": {"raw": rd_value}},
        })
        summary["VIOLATION_PRESENT"] += 1
    lower = []
    for unit in sorted(set(pd) & set(rd)):
        compared += 1
        a, b = max(d["flow"] for d in pd[unit]), max(d["flow"] for d in rd[unit])
        if b < a * (1 - FLOW_TOLERANCE):
            lower.append((unit, a, b))
    for unit, a, b in lower:
        summary["VIOLATION_PRESENT"] += 1
        findings.append({
            "finding_id": f"{object_id}::{code}::unit-{unit}",
            "object_id": object_id, "matrix_scope": "MATRIX", "parameter_code": code,
            "parameter_id": cat.get("parameter_id"),
            "title": f"Расход установки {unit} в рабочей документации меньше проектного",
            "comparison_result": "VALUE_DECREASE", "location_type": "OBJECT", "locations": ["Здание"],
            "pd_value": f"{unit}: L={a} м³/ч", "rd_value": f"{unit}: L={b} м³/ч", "id_value": None,
            "violation_label": "VIOLATION_PRESENT", "criticality": cat.get("criticality"),
            "finding_status": "CANDIDATE", "needs_expert": True,
            "evidence": [{"stage": st, "file_id": d["file_id"], "pdf_page_number": d["page"], "quote": d["snippet"],
                          "localization": "PAGE_LEVEL", "role": "EQUIPMENT_LIST"}
                         for st, side in (("PD", pd), ("RD", rd)) for d in side[unit][:1]],
            "extraction": {"rule_basis": rule.get("basis"), "detail": "расход установки уменьшен",
                           "source": "EQUIPMENT_LIST", "pd": {"raw": f"L={a} м³/ч"}, "rd": {"raw": f"L={b} м³/ч"}},
        })
    summary["установок сверено"] = compared
    if compared and not lower:
        value = f"расход не меньше проектного, установок: {compared}"
        first = [next(iter(side[u])) for side in (pd, rd) for u in sorted(set(pd) & set(rd))[:1]]
        findings.append({
            "finding_id": f"{object_id}::{code}::units-equal",
            "object_id": object_id, "matrix_scope": "MATRIX", "parameter_code": code,
            "parameter_id": cat.get("parameter_id"),
            "title": "Расход установок общеобменной вентиляции не меньше проектного",
            "comparison_result": "EQUAL_PD_RD", "location_type": "OBJECT", "locations": ["Здание"],
            "pd_value": value, "rd_value": value, "id_value": None, "violation_label": "NO_VIOLATION",
            "criticality": None, "finding_status": "CANDIDATE",
            "evidence": [{"stage": st, "file_id": d["file_id"], "pdf_page_number": d["page"], "quote": d["snippet"],
                          "localization": "PAGE_LEVEL", "role": "EQUIPMENT_LIST"}
                         for st, d in zip(("PD", "RD"), first)],
            "extraction": {"rule_basis": rule.get("basis"), "source": "EQUIPMENT_LIST",
                           "detail": f"сверено установок по обозначению: {compared}; только в ПД: {', '.join(gone) or '—'}; "
                                     f"только в РД: {', '.join(sorted(set(rd) - set(pd))) or '—'}",
                           "pd": {"raw": value}, "rd": {"raw": value}},
        })
        summary["NO_VIOLATION"] += 1
    return findings, summary


# ---------- правило Матрицы ----------

def rule_findings(object_id, code, rule, catalog, findings_so_far=(), progress=None):
    """Находки правила Матрицы вида `room_systems` или `vent_units`. Возвращает (находки, сводка)."""
    if rule.get("kind") == "room_systems":
        made, summary, _ = build_findings(object_id, code, rule, catalog,
                                          use_ocr=os.environ.get("PIPELINE_TABLE_OCR", "1") != "0")
        return made, summary
    reported = {room for f in findings_so_far if f.get("location_type") == "ROOM"
                and f.get("violation_label") == "VIOLATION_PRESENT" and f.get("extraction", {}).get("source") == "SYSTEMS_TABLE"
                for room in f.get("locations") or ()}
    return build_unit_findings(object_id, code, rule, catalog, reported_rooms=reported)
