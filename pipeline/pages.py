"""Постраничный индекс объекта.

Одна строка на страницу по схеме `contracts/page.schema.json`.
Текст берётся конвейером чтения из `pipeline/reading.py`.

Поле `document_sheet_number` здесь остаётся пустым: номер листа основной надписи
заполняет отдельный разбор, и он не равен номеру страницы PDF. В эталоне лист 26
тома ИОС5.4.2 это страница 104.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import reading
from pipeline.config import OBJECTS

# Номер помещения в экспликации: три-четыре цифры, иногда с точкой и подномером.
ROOM_RE = re.compile(r"(?<!\d)(\d{2,4}(?:\.\d{1,2})?)(?!\d)")

# Исполнительная схема: «Исполнительная схема вертикальных конструкций на отм. -5,250»,
# «Исп.схема № 52». Признак тот же, что у проверки допусков (#89, pipeline/tolerances.py)
ID_SCHEME_RE = re.compile(r"(?:исполнительн\w*|исп\.?)\s*схем\w*", re.I)
# Исполнительные схемы читаются моделью в любом режиме чтения. Это исключение из Р-54
# («режим чтения выбирается на объект»), и вот его цена: во всём корпусе таких страниц
# 265 на двух объектах из девяти, а числа на них — единственный источник исполнительной
# геометрии: отметки, промеры и таблицы допусков нарисованы, и Tesseract не читает
# с них ни одного значения (#85). Выключается PIPELINE_ID_SCHEME_MODEL=0
ID_SCHEME_MODEL = os.environ.get("PIPELINE_ID_SCHEME_MODEL", "1").strip().lower() \
    not in ("0", "false", "no", "")


def id_scheme(doc_row):
    """Исполнительная схема: стадия ИД и слово «схема» в пути файла."""
    return (doc_row.get("stage") == "ID"
            and bool(ID_SCHEME_RE.search(doc_row.get("relative_path") or "")))


def guess_rooms(text, limit=60):
    """Черновые номера помещений со страницы.

    Это подсказка для поиска страниц-кандидатов, а не утверждение. Достоверный
    реестр помещений строится из экспликации, см. отдельную задачу.
    """
    out, seen = [], set()
    for m in ROOM_RE.finditer(text or ""):
        v = m.group(1)
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
        if len(out) >= limit:
            break
    return out


# Документ, открытый в этом процессе чтения, — один: страницы приходят подряд по документу.
# Два разных документа в одном процессе открытыми не держатся: MuPDF делит между ними склад
# ресурсов, и отрисовка страницы начинает зависеть от соседа. У ДОО паспорт В9.pdf, прочитанный
# при открытых В5.pdf и В8.pdf того же генератора (те же номера объектов), выходил с другим
# цветом штампа и лишним «+» в распознанном тексте (#113).
_opened = {"path": None, "doc": None}


def _doc(path):
    import pymupdf
    if _opened["path"] != path:
        doc, _opened["doc"], _opened["path"] = _opened["doc"], None, None
        if doc is not None:
            doc.close()
        _opened["doc"] = pymupdf.open(path)
        _opened["path"] = path
    return _opened["doc"]


def _read(task):
    """Страница в процессе пула: (номер, строка реестра, прочитанное)."""
    doc_row, path, use_model, model, use_ocr, page_no = task
    got = reading.read_page(_doc(path), page_no, doc_row["sha256"],
                            use_model=use_model, model=model, use_ocr=use_ocr)
    return page_no, doc_row, got


def build(object_id, documents, use_model=True, model=None, progress=None, workers=6, use_ocr=None):
    """Собрать постраничный индекс по реестру документов.

    Страницы читаются параллельно, процессами: распознавание упирается в процессор, запрос
    к модели в сеть, и вместе они хорошо перекрываются. Процессы, а не потоки, — чтобы
    разные документы не делили склад MuPDF: у каждого процесса открыт один документ.

    Пул один на объект, а не на документ. Исполнительная документация — это сотни
    файлов по одной-четыре страницы (у ДОО на Полярной 25 таких 375 из 434 PDF ИД), и пул
    на документ держал занятыми один-четыре потока из шести: 150 файлов ИД ДОО читались
    387 с, одним пулом процессов — 97; шесть томов РД с текстовым слоем — 12,9 с и 3,7
    (#113, Р-90). Страницы раздаются по порядку, подряд по документу.

    `use_ocr` — распознавать ли сканы; None означает настройку окружения. Сервис задаёт
    его явно: способ чтения выбирается на объект, а не на весь воркер (#54).
    """
    import multiprocessing
    import pymupdf
    root = OBJECTS[object_id]["root"]
    rows = []
    tasks = []
    for doc_row in documents:
        if doc_row.get("duplicate_of") or doc_row["extension"] != ".pdf":
            continue
        path = os.path.join(root, doc_row["relative_path"])
        try:
            probe = pymupdf.open(path)
            n_pages = probe.page_count
            probe.close()
        except Exception as e:
            rows.append({"file_id": doc_row["file_id"], "pdf_page_number": 1,
                         "kind": "SCAN_NO_TEXT", "text_source": "NONE",
                         "quality": "ABSTAIN", "error": f"{type(e).__name__}: {e}"[:160]})
            continue
        # исполнительную схему читаем моделью независимо от режима: иначе её числа
        # не появляются вовсе (#85)
        doc_model = use_model or (ID_SCHEME_MODEL and id_scheme(doc_row))
        tasks.extend((doc_row, path, doc_model, model, use_ocr, page_no) for page_no in range(1, n_pages + 1))

    if not tasks:
        return sorted(rows, key=lambda r: (r["file_id"], r["pdf_page_number"]))
    with multiprocessing.Pool(max(1, min(workers, len(tasks)))) as pool:
        for page_no, doc_row, got in pool.imap(_read, tasks, chunksize=2):
            rows.append({
                "file_id": doc_row["file_id"],
                "object_id": object_id,
                "stage": doc_row["stage"],
                "section": doc_row["section"],
                "pdf_page_number": page_no,
                "document_sheet_number": None,
                "kind": got["kind"],
                "text_source": got["text_source"],
                "text": got["text"],
                "rooms": guess_rooms(got["text"]),
                "rotation": got["rotation"],
                "width_pt": got["width_pt"],
                "height_pt": got["height_pt"],
                "quality": got["quality"],
                "word_count": len(got["words"]),
                # время чтения страницы и ответ модели: по ним видно, во что обошёлся
                # способ чтения и не отказывалась ли модель отвечать (#54)
                "ms": got.get("ms"),
                "cost_usd": got["cost_usd"],
                **({"model_call": got["model_call"]} if got.get("model_call") else {}),
            })
            if progress and len(rows) % 25 == 0:
                progress(len(rows))
    rows.sort(key=lambda r: (r["file_id"], r["pdf_page_number"]))
    return rows


def summary(rows):
    import collections
    kinds = collections.Counter(r.get("kind") for r in rows)
    src = collections.Counter(r.get("text_source") for r in rows)
    return {
        "pages": len(rows),
        "with_text": sum(1 for r in rows if (r.get("text") or "").strip()),
        "by_kind": dict(kinds),
        "by_source": dict(src),
        "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rows), 4),
        "errors": sum(1 for r in rows if r.get("error")),
    }
