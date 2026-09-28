"""Загрузчик папки объекта: лимиты браузера и маршрут без лимитов (Р-110).

  python tests/test_upload_object.py

Лимиты ТЗ — файл до 50 МБ, пакет до 200 МБ — относятся к загрузке инспектором в браузере.
Загрузчик с ролью admin грузит в маршрут без лимитов: в корпусе 115 PDF больше 50 МБ,
среди них действующие ПЗ и ПЗУ Тюменской и тома ИД под гигабайт. Здесь проверяется, что
он их передаёт, что по лимитам браузера пропускает, как раньше, и что пакеты не разрастаются.
Файлы в проверке разреженные: места на диске они не занимают.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import upload_object as uo  # noqa: E402

MB = 1024 * 1024
HEALTH = {"max_file_mb": 50, "max_package_mb": 200, "formats": ["PDF", "DOCX", "XML"],
          "loader_path": "/api/v1/documents/bulk"}


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def sparse(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)


def collect(limits):
    """Папка объекта с файлами до и после лимита браузера — через collect загрузчика."""
    with tempfile.TemporaryDirectory(prefix="upload-object-") as root:
        sparse(os.path.join(root, "ПД", "ИЗМ ПО ЗАМЕЧАНИЯМ ПЗУ.pdf"), 52 * MB)
        sparse(os.path.join(root, "ПД", "Том 1.1.pdf"), 1 * MB)
        sparse(os.path.join(root, "ИД", "! ИД АР.pdf"), 912 * MB)
        sparse(os.path.join(root, "ИД", "Документы.zip"), 60 * MB)
        return uo.collect(root, limits)


def paths(items):
    return sorted(item["relative_path"] if isinstance(item, dict) else item[1] for item in items)


def test_browser_limits():
    ok = True
    eligible, skipped = collect(HEALTH)
    ok &= check("по лимитам браузера передаётся только файл до 50 МБ", paths(eligible) == ["ПД/Том 1.1.pdf"],
                str(paths(eligible)))
    ok &= check("крупные файлы и архив — в skipped: отказ записывает сервис",
                paths(skipped) == ["ИД/! ИД АР.pdf", "ИД/Документы.zip", "ПД/ИЗМ ПО ЗАМЕЧАНИЯМ ПЗУ.pdf"],
                str(paths(skipped)))
    return ok


def test_loader_no_limits():
    ok = True
    route, limits = uo.choose_route(HEALTH, "admin")
    ok &= check("admin грузит в маршрут загрузчика", route == "/api/v1/documents/bulk", route)
    eligible, skipped = collect(limits)
    ok &= check("без лимитов передаются и 52 МБ, и 912 МБ",
                paths(eligible) == ["ИД/! ИД АР.pdf", "ПД/ИЗМ ПО ЗАМЕЧАНИЯМ ПЗУ.pdf", "ПД/Том 1.1.pdf"],
                str(paths(eligible)))
    ok &= check("формат по-прежнему проверяется: архив в skipped", paths(skipped) == ["ИД/Документы.zip"],
                str(paths(skipped)))
    return ok


def test_route_choice():
    ok = True
    ok &= check("inspector идёт по лимитам браузера",
                uo.choose_route(HEALTH, "inspector") == (uo.UPLOAD_PATH, HEALTH))
    ok &= check("--browser-limits у admin — тоже лимиты браузера",
                uo.choose_route(HEALTH, "admin", browser_limits=True) == (uo.UPLOAD_PATH, HEALTH))
    old = {k: v for k, v in HEALTH.items() if k != "loader_path"}
    ok &= check("сервис без маршрута загрузчика — лимиты браузера, файлы не теряются молча",
                uo.choose_route(old, "admin") == (uo.UPLOAD_PATH, old))
    return ok


def test_batches():
    ok = True
    items = [("a", "a", 300 * MB), ("b", "b", 912 * MB), ("c", "c", 10 * MB), ("f", "f", 1500 * MB),
             ("d", "d", 700 * MB), ("e", "e", 400 * MB)]
    plan = uo.batches(items, 1024 * MB)
    sizes = [sum(i[2] for i in p) // MB for p in plan]
    ok &= check("пакеты не больше --batch-mb, файл крупнее идёт один", sizes == [300, 922, 1500, 700, 400], str(sizes))
    ok &= check("ни один файл не потерян", sorted(i[0] for p in plan for i in p) == ["a", "b", "c", "d", "e", "f"])
    return ok


def main():
    ok = True
    for title, fn in (("Лимиты браузера", test_browser_limits),
                      ("Загрузчик без лимитов", test_loader_no_limits),
                      ("Выбор маршрута", test_route_choice),
                      ("Пакеты", test_batches)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
