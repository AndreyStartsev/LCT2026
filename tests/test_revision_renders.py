"""Картинки страниц для сравнения редакций у листов-доказательств. Задача #81.

  python tests/test_revision_renders.py

У томов проекта страницы пар редакций рисуются в пределах `REVISION_RENDER_LIMIT` за разбор.
Лист доказательства мог остаться без картинки прежней редакции, и ссылка «сравнить с кор. 2»
под его страницей открывала сравнение с пустой левой стороной (КР1 Речникова, стр. 21 → 29).
`render_revision_evidence` дорисовывает обе стороны таких строк сравнения и отмечает это
в `revision_changes`. Хранилище и база здесь поддельные, PDF — два листа, собранные на лету.
"""
import contextlib
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pymupdf  # noqa: E402

from service.worker import infra, steps  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


class Storage:
    """Хранилище картинок: stat_object падает, если ключа нет, как у MinIO."""

    def __init__(self, keys=()):
        self.objects = {k: b"" for k in keys}

    def stat_object(self, bucket, key):
        if key not in self.objects:
            raise KeyError(key)

    def put_object(self, bucket, key, data, length, content_type=None):
        self.objects[key] = data.read()


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class Conn:
    """База: строки revision_changes и записанные обновления."""

    def __init__(self, rows):
        self.rows, self.updates = rows, []

    def execute(self, sql, params=()):
        if sql.lstrip().startswith("select"):
            return Result(self.rows)
        self.updates.append((sql, params))
        return Result([])

    @contextlib.contextmanager
    def transaction(self):
        yield


def pdf(path, pages):
    doc = pymupdf.open()
    for n in range(pages):
        doc.new_page().insert_text((72, 72), f"страница {n + 1}")
    doc.save(path)


def main():
    print("\nСтраницы редакций у листов-доказательств (#81)")
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        pdf(os.path.join(tmp, "kr1.pdf"), 3)
        pdf(os.path.join(tmp, "kr1-kor3.pdf"), 3)
        documents = [
            {"file_id": "F1", "relative_path": "kr1.pdf", "extension": ".pdf", "sha256": "a" * 64},
            {"file_id": "F2", "relative_path": "kr1-kor3.pdf", "extension": ".pdf", "sha256": "b" * 64},
        ]
        with open(os.path.join(tmp, "documents.jsonl"), "w", encoding="utf-8") as f:
            f.write("\n".join(json.dumps(d) for d in documents) + "\n")
        storage = Storage({f"renders/{'b' * 64}/2.jpg"})   # лист доказательства уже отрисован
        pages = [
            # лист доказательства: содержание изменилось, прежней редакции нет в хранилище
            {"old_page": 1, "new_page": 2, "content_changed": True, "rendered_old": False, "rendered_new": True},
            # тот же файл, содержание не изменилось — ссылки нет, рисовать нечего
            {"old_page": 2, "new_page": 3, "content_changed": False, "rendered_old": False, "rendered_new": False},
        ]
        conn = Conn([{"pair_id": "P", "old_file_id": "F1", "new_file_id": "F2", "pages": pages}])
        findings = [{"finding_id": "X", "evidence": [{"file_id": "F2", "pdf_page_number": 2},
                                                     {"file_id": "F2", "pdf_page_number": 3}]}]
        patched = {"files_dir": steps.files_dir, "out_path": steps.out_path}
        storage_fn, progress_fn = infra.storage, infra.progress
        steps.files_dir = lambda pid: tmp
        steps.out_path = lambda obj, name: os.path.join(tmp, name)
        infra.storage = lambda: storage
        infra.progress = lambda *a, **k: None
        try:
            steps.render_revision_evidence(conn, {"id": "p1", "object_id": "OBJ"}, findings)
        finally:
            steps.files_dir, steps.out_path = patched["files_dir"], patched["out_path"]
            infra.storage, infra.progress = storage_fn, progress_fn
        ok &= check("прежняя редакция листа доказательства отрисована", f"renders/{'a' * 64}/1.jpg" in storage.objects,
                    str(sorted(storage.objects)))
        ok &= check("страница, где содержание не изменилось, не рисуется",
                    f"renders/{'a' * 64}/2.jpg" not in storage.objects and f"renders/{'b' * 64}/3.jpg" not in storage.objects)
        written = conn.updates[0][1][0].obj if conn.updates else []
        ok &= check("в revision_changes у строки обе картинки отмечены, у другой — как было",
                    len(conn.updates) == 1 and written[0]["rendered_old"] and written[0]["rendered_new"]
                    and not written[1]["rendered_old"], str(written))
        conn = Conn([{"pair_id": "P", "old_file_id": "F1", "new_file_id": "F2", "pages": written}])
        steps.render_revision_evidence(conn, {"id": "p1", "object_id": "OBJ"}, findings)
        ok &= check("повторный разбор ничего не рисует и базу не трогает", not conn.updates)

        # разбор: у тома проекта не больше REVISION_RENDER_LIMIT новых картинок, у РД — все
        storage, limit = Storage(), steps.REVISION_RENDER_LIMIT
        steps.files_dir = lambda pid: tmp
        steps.out_path = lambda obj, name: os.path.join(tmp, name)
        infra.storage = lambda: storage
        infra.progress = lambda *a, **k: None
        steps.REVISION_RENDER_LIMIT = 1
        try:
            pair = {"pair_id": "P", "old_file_id": "F1", "new_file_id": "F2", "stage_group": "PD"}
            rows = {"P": [{"old_page": 1, "new_page": 1, "content_changed": True},
                          {"old_page": 2, "new_page": 2, "content_changed": True}]}
            have_pd = steps.render_revision_pages({"id": "p1", "object_id": "OBJ"}, [pair], rows)
            storage.objects.clear()
            have_rd = steps.render_revision_pages({"id": "p1", "object_id": "OBJ"}, [dict(pair, stage_group="RD")], rows)
        finally:
            steps.files_dir, steps.out_path = patched["files_dir"], patched["out_path"]
            infra.storage, infra.progress = storage_fn, progress_fn
            steps.REVISION_RENDER_LIMIT = limit
        ok &= check("том проекта: предел на разбор соблюдается, у РД рисуются все страницы",
                    len(have_pd) == 1 and len(have_rd) == 4, f"ПД {sorted(have_pd)}, РД {sorted(have_rd)}")
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
