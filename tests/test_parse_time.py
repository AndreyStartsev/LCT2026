"""Время разбора объекта со сканами. Задача #113.

  python tests/test_parse_time.py

Разбор объекта со сканами шёл почти два часа при сроке шага 2 ч, и почти половину — угол
листа на одном PDF ИД в тысячи страниц, который открывался заново на каждой странице.
Замеры — в Р-90 (`docs/decisions.md`).
Проверки: шаг с ходом не снимается по сроку, молчащий и перешедший предел — снимается;
документ при чтении угла открывается раз на файл, а не раз на страницу; страницы мелких
документов читаются одним пулом процессов, а не пулом на документ.
"""
import datetime
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# кеш чтения теста — во временном каталоге, до импорта конвейера: иначе страницы
# синтетических PDF легли бы в общий кеш
os.environ["PIPELINE_CACHE"] = tempfile.mkdtemp(prefix="test-parse-time-")

from service.worker import watchdog  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def test_overdue():
    ok = True
    timeout, limit, stall = 7200, 21600, 1800
    ok &= check("в срок шаг не снимается, даже молча",
                watchdog.overdue(7000, 5000, timeout, limit, stall) is None)
    ok &= check("после срока шаг с ходом идёт дальше",
                watchdog.overdue(9000, 30, timeout, limit, stall) is None)
    got = watchdog.overdue(9000, 2000, timeout, limit, stall)
    ok &= check("после срока молчащий шаг снимается", got is not None and "нет хода" in got, str(got))
    got = watchdog.overdue(21700, 5, timeout, limit, stall)
    ok &= check("за предельным сроком снимается и шаг с ходом", got is not None and "предельный" in got, str(got))
    ok &= check("предел равен сроку — прежнее поведение",
                watchdog.overdue(7201, 1, timeout, timeout, stall) is not None)
    return ok


def test_progress_age():
    ok = True
    now = datetime.datetime(2026, 9, 24, 20, 0, 0, tzinfo=datetime.timezone.utc)
    raw = json.dumps({"step": "parse", "message": "Чтение страниц", "done": 25, "total": 100,
                      "updated_at": (now - datetime.timedelta(seconds=90)).isoformat()})
    age = watchdog.progress_age(raw, now)
    ok &= check("ход в Redis: возраст по updated_at", age is not None and abs(age - 90) < 1e-6, str(age))
    ok &= check("хода нет — возраста нет", watchdog.progress_age(None, now) is None)
    ok &= check("ход не читается — возраста нет", watchdog.progress_age(b"{oops", now) is None)
    naive = json.dumps({"updated_at": "2026-09-24T19:59:00"})
    ok &= check("время без пояса считается UTC", watchdog.progress_age(naive, now) == 60.0,
                str(watchdog.progress_age(naive, now)))
    return ok


def test_run_step():
    """Воркер целиком: шаг — настоящий процесс, срок и предел — секунды.

    Без брокера: соединение подменено, pika — пустым модулем, если её нет. Redis подменён:
    свежий ход (так пишет чтение страниц, молча в вывод) или отказ, как при сбое Redis на стенде.
    """
    import subprocess
    import types
    if "pika" not in sys.modules:
        try:
            import pika  # noqa: F401
        except ImportError:
            sys.modules["pika"] = types.ModuleType("pika")
    from service.worker import main, settings

    class Connection:
        def process_data_events(self, time_limit=1):
            import time
            time.sleep(min(time_limit, 0.1))

    class Redis:
        """Ход в Redis свежий: так пишет чтение страниц, молча в вывод."""
        def get(self, key):
            return json.dumps({"step": "parse", "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})

    def no_redis():
        raise ConnectionError("Redis недоступен")

    silent = "import time\nprint('старт', flush=True); time.sleep(2.2)"
    scripts = {
        "ход, затем конец": ("import time\nfor i in range(8):\n    print(i, flush=True); time.sleep(0.3)", no_redis),
        "молчит": ("import time\nprint('старт', flush=True); time.sleep(30)", no_redis),
        "молчит в вывод, ход в Redis": (silent, Redis),
        "молчит в вывод, Redis нет": (silent, no_redis),
        "ход без конца": ("import time\nwhile True:\n    print('.', flush=True); time.sleep(0.3)", no_redis),
        "падает": ("import sys\nprint('старт', flush=True); sys.exit(3)", no_redis),
    }
    real_popen, real_log, real_redis = subprocess.Popen, main.log, main.infra.redis
    saved = (dict(settings.STEP_TIMEOUT_S), dict(settings.STEP_TIMEOUT_MAX_S), settings.STALL_TIMEOUT_S)
    lines = []
    got = {}
    try:
        settings.STEP_TIMEOUT_S["parse"], settings.STEP_TIMEOUT_MAX_S["parse"] = 1, 4
        settings.STALL_TIMEOUT_S = 1.5
        main.log = lambda message, level="INFO", **fields: lines.append(message)
        for name, (code, redis) in scripts.items():
            def fake(args, _code=code, **kwargs):
                return real_popen([sys.executable, "-c", _code], **{**kwargs, "cwd": None})
            main.subprocess.Popen, main.infra.redis = fake, redis
            got[name] = main.run_step(Connection(), "parse", "test-113", {})
    finally:
        main.subprocess.Popen, main.log, main.infra.redis = real_popen, real_log, real_redis
        settings.STEP_TIMEOUT_S.update(saved[0])
        settings.STEP_TIMEOUT_MAX_S.update(saved[1])
        settings.STALL_TIMEOUT_S = saved[2]
    ok = True
    ok &= check("шаг с ходом пережил срок и закончился", got["ход, затем конец"] == (True, None, False),
                str(got["ход, затем конец"]))
    ok &= check("о продлении — строка в журнале", any("дольше срока" in x for x in lines))
    ok &= check("молчащий шаг снят по таймауту", got["молчит"][2] and "нет хода" in got["молчит"][1],
                str(got["молчит"]))
    ok &= check("ход в Redis держит шаг, молчащий в вывод", got["молчит в вывод, ход в Redis"] == (True, None, False),
                str(got["молчит в вывод, ход в Redis"]))
    ok &= check("без Redis тот же шаг снят", got["молчит в вывод, Redis нет"][2],
                str(got["молчит в вывод, Redis нет"]))
    ok &= check("шаг с ходом снят за пределом", got["ход без конца"][2] and "предельный" in got["ход без конца"][1],
                str(got["ход без конца"]))
    ok &= check("сбой — не таймаут", got["падает"] == (False, "шаг parse завершился с кодом 3", False),
                str(got["падает"]))
    return ok


def test_open_once():
    """Угол листа: страницы одного файла читаются из одного открытого документа."""
    import pymupdf
    from pipeline import titleblock_ocr
    ok = True
    with tempfile.TemporaryDirectory() as td:
        paths = []
        for name, n in (("a.pdf", 3), ("b.pdf", 2)):
            doc = pymupdf.open()
            for _ in range(n):
                doc.new_page()
            path = os.path.join(td, name)
            doc.save(path)
            doc.close()
            paths.append(path)
        opened = []
        real = pymupdf.open

        def counting(*args, **kwargs):
            opened.append(args[0] if args else None)
            return real(*args, **kwargs)

        pymupdf.open = counting
        try:
            titleblock_ocr._release()
            numbers = [titleblock_ocr._open_page(paths[0], p).number for p in (1, 2, 3)]
            numbers += [titleblock_ocr._open_page(paths[1], p).number for p in (1, 2)]
            numbers.append(titleblock_ocr._open_page(paths[1], 1).number)
        finally:
            pymupdf.open = real
            titleblock_ocr._release()
        ok &= check("страницы те, что просили", numbers == [0, 1, 2, 0, 1, 0], str(numbers))
        ok &= check("каждый файл открыт один раз", opened == paths, str([os.path.basename(p) for p in opened]))
    return ok


def test_page_pool():
    """Индекс страниц: один пул процессов на объект, строки — в прежнем порядке и из своих файлов."""
    import multiprocessing
    import pymupdf
    from pipeline import pages
    ok = True
    with tempfile.TemporaryDirectory() as td:
        documents = []
        for fid, n in (("F3", 1), ("F1", 3), ("F2", 2)):
            doc = pymupdf.open()
            for i in range(n):
                # латиницей: у встроенного шрифта helv кириллицы нет
                doc.new_page().insert_text((72, 72), f"Doc {fid} page {i + 1}", fontname="helv")
            doc.save(os.path.join(td, f"{fid}.pdf"))
            doc.close()
            documents.append({"file_id": fid, "stage": "ID", "section": "OTHER", "relative_path": f"{fid}.pdf",
                              "sha256": fid.lower() * 16, "extension": ".pdf"})
        documents.append({"file_id": "F4", "stage": "ID", "section": "OTHER", "relative_path": "нет.pdf",
                          "sha256": "f4" * 16, "extension": ".pdf"})
        pools = []
        real_pool, real_objects = multiprocessing.Pool, pages.OBJECTS

        def counting(*args, **kwargs):
            pools.append(args)
            return real_pool(*args, **kwargs)

        multiprocessing.Pool, pages.OBJECTS = counting, {"T": {"root": td}}
        try:
            rows = pages.build("T", documents, use_model=False, workers=3, use_ocr=False)
        finally:
            multiprocessing.Pool, pages.OBJECTS = real_pool, real_objects
    got = [(r["file_id"], r["pdf_page_number"]) for r in rows]
    want = [("F1", 1), ("F1", 2), ("F1", 3), ("F2", 1), ("F2", 2), ("F3", 1), ("F4", 1)]
    ok &= check("строки по документу и странице, неоткрывшийся файл — строкой с ошибкой", got == want, str(got))
    ok &= check("у неоткрывшегося файла ошибка", "error" in rows[-1] and rows[-1]["kind"] == "SCAN_NO_TEXT")
    texts = [" ".join(r.get("text", "").split()) for r in rows[:-1]]
    ok &= check("страница прочитана из своего документа",
                all(t.startswith(f"Doc {fid} page {p}") for t, (fid, p) in zip(texts, want)), str(texts))
    ok &= check("пул один на объект, а не на документ", len(pools) == 1, f"пулов {len(pools)}")
    return ok


def test_one_document_per_process():
    """В процессе чтения открыт один документ: соседний файл не делит с ним склад MuPDF."""
    import pymupdf
    from pipeline import pages
    ok = True
    with tempfile.TemporaryDirectory() as td:
        paths = []
        for name in ("a.pdf", "b.pdf"):
            doc = pymupdf.open()
            doc.new_page()
            doc.save(os.path.join(td, name))
            doc.close()
            paths.append(os.path.join(td, name))
        first = pages._doc(paths[0])
        ok &= check("тот же файл — тот же открытый документ", pages._doc(paths[0]) is first)
        second = pages._doc(paths[1])
        ok &= check("другой файл — прежний закрыт", first.is_closed and not second.is_closed)
        second.close()
        pages._opened.update(path=None, doc=None)
    return ok


def main():
    ok = True
    for title, fn in (("Когда снимать шаг", test_overdue), ("Ход в Redis", test_progress_age),
                      ("Воркер: срок, ход и предел", test_run_step),
                      ("Открытие документа при чтении угла", test_open_once),
                      ("Один пул на индекс страниц", test_page_pool),
                      ("Один документ на процесс чтения", test_one_document_per_process)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
