"""Замер скорости чтения против п. 2 и 3 раздела 11 ТЗ: service/worker/measure_pages.py.

  python tests/test_measure_pages.py

Проверяется:

- вывод против нормы: до 100 страниц — 3 минуты с допуском 30 с, до 500 — 10 минут
  с допуском 60 с, файл больше 500 страниц пересчитывается на 500;
- замер читает тем же путём, что разбор (pages.build), в пустой временный кеш: кеш
  стенда не трогается, временный каталог после прогона удаляется;
- урезанный файл (--max-pages) вывода против нормы не получает.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from service.worker import measure_pages as mp  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return condition


def test_verdict():
    ok = True
    ok &= check("100 страниц за 180 с — укладывается", mp.verdict(100, 180)["verdict"] == "укладывается")
    ok &= check("100 страниц за 200 с — в допуске", mp.verdict(100, 200)["verdict"] == "в допуске")
    ok &= check("100 страниц за 211 с — не укладывается", mp.verdict(100, 211)["verdict"] == "НЕ укладывается")
    ok &= check("101 страница — сценарий 500 страниц", mp.verdict(101, 300)["norm_s"] == 600)
    ok &= check("500 страниц за 650 с — в допуске", mp.verdict(500, 650)["verdict"] == "в допуске")
    big = mp.verdict(1000, 1300)
    ok &= check("1000 страниц пересчитываются на 500", big["seconds_for_norm"] == 650 and big["verdict"] == "в допуске",
                str(big))
    return ok


def make_pdf(folder, pages):
    import pymupdf
    path = os.path.join(folder, "проба.pdf")
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), f"Акт освидетельствования скрытых работ страница {i + 1}", fontsize=12)
    doc.save(path)
    doc.close()
    return path


def test_measure_path():
    ok = True
    stand_cache = os.path.join(ROOT, ".cache", "pages")
    before = set(os.listdir(stand_cache)) if os.path.isdir(stand_cache) else set()
    with tempfile.TemporaryDirectory() as folder:
        path = make_pdf(folder, 3)
        got = mp.measure(path, "layer", False, False, None, workers=2, max_pages=None, stage="ID")
        ok &= check("прочитаны все страницы файла", got["pages"] == 3 and got["pages_in_file"] == 3, str(got["pages"]))
        ok &= check("источник — текстовый слой", got["by_source"] == {"TEXT_LAYER": 3}, str(got["by_source"]))
        ok &= check("вывод против нормы есть", got.get("tz", {}).get("verdict") == "укладывается", str(got.get("tz")))
        used = os.environ.get("PIPELINE_CACHE")
        ok &= check("временный кеш после прогона удалён", used and not os.path.exists(used), str(used))
        after = set(os.listdir(stand_cache)) if os.path.isdir(stand_cache) else set()
        ok &= check("кеш стенда не тронут", after == before, str(after - before))
        cut = mp.measure(path, "layer", False, False, None, workers=2, max_pages=2, stage="ID")
        ok &= check("урезанный файл: две страницы и без вывода против нормы",
                    cut["pages"] == 2 and "tz" not in cut, str(cut["pages"]))
    return ok


def main():
    ok = True
    for title, fn in (("Вывод против нормы ТЗ", test_verdict),
                      ("Путь чтения и кеш", test_measure_path)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
