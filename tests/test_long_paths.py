"""Длинные имена папок пакета организатора на диске воркера.

  python tests/test_long_paths.py

Предел имени в файловой системе контейнера — 255 байт, кириллица в UTF-8 весит два байта
на знак. Папка «10.1 Мероприятия по обеспечению соблюдения требований энергетической
эффективности и требований оснащенности зданий, строений и сооружений приборами учета»
занимает 290 байт: выкладка файлов процесса падала на ней с «File name too long», объект
не разбирался вовсе. На macOS такая папка создаётся, поэтому в командной строке разбор
шёл, а через сервис — нет.

Проверяется и то, что укорочение не ломает разбор: стадию и раздел конвейер определяет
по началу пути, и оно должно остаться на месте.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import registry  # noqa: E402
from service.worker import paths  # noqa: E402

LONG_DIR = ("10.1 Мероприятия по обеспечению соблюдения требований энергетической эффективности "
            "и требований оснащенности зданий, строений и сооружений приборами учета")


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def longest(path):
    return max(len(p.encode("utf-8")) for p in path.split("/"))


def test_short_paths_untouched():
    ok = True
    for path in ("ПД/1 Пояснительная записка/Том 1.1.pdf",
                 "Рабочая и исполнительная документация/АОСР №1_ОВ. от 07.04.2025.pdf",
                 "one.pdf"):
        ok &= check(f"обычный путь не меняется: {path[:40]}…", paths.disk_path(path) == path)
    ok &= check("пустой путь не ломает разбор", paths.disk_path("") == "")
    ok &= check("обратные косые приводятся к прямым",
                paths.disk_path("ПД\\Том 1.1.pdf") == "ПД/Том 1.1.pdf")
    return ok


def test_long_name_fits():
    rel = f"ПД/{LONG_DIR}/V2_01-10-01-02-05_Том 10.1.pdf"
    out = paths.disk_path(rel)
    ok = check("длинное имя действительно длинное", longest(rel) > 255, f"{longest(rel)} байт")
    ok &= check("после укорочения имя помещается в предел", longest(out) <= 255, f"{longest(out)} байт")
    ok &= check("начало имени сохранено", out.split("/")[1].startswith("10.1 Мероприятия по обеспечению"))
    ok &= check("имя файла и расширение не тронуты", out.endswith("/V2_01-10-01-02-05_Том 10.1.pdf"), out)
    ok &= check("число частей пути не изменилось", len(out.split("/")) == len(rel.split("/")))
    return ok


def test_long_names_do_not_merge():
    """Две длинные папки с общим началом не должны слиться в одну: файлы перемешались бы."""
    a = paths.disk_path(LONG_DIR + " (изменение 1)")
    b = paths.disk_path(LONG_DIR + " (изменение 2)")
    ok = check("разные длинные имена остаются разными", a != b, f"{a[-12:]} и {b[-12:]}")
    ok &= check("оба помещаются в предел", longest(a) <= 255 and longest(b) <= 255,
                f"{longest(a)} и {longest(b)} байт")
    # точка в номере тома — не расширение: принять её за расширение значило бы оставить
    # длинный хвост и снова упереться в предел
    dotted = paths.disk_path("ПД/" + LONG_DIR + ".1 книга 2")
    ok &= check("точка в середине длинного имени не считается расширением",
                longest(dotted) <= 255, f"{longest(dotted)} байт")
    ok &= check("одно и то же имя переводится одинаково",
                paths.disk_path(LONG_DIR) == paths.disk_path(LONG_DIR))
    long_file = "В" * 200 + ".pdf"
    ok &= check("длинное имя файла сохраняет расширение", paths.disk_path(long_file).endswith(".pdf"),
                paths.disk_path(long_file))
    ok &= check("длинное имя файла помещается в предел", longest(paths.disk_path(long_file)) <= 255)
    return ok


def test_parsing_survives():
    """Стадию и раздел конвейер определяет по началу пути — оно должно пережить укорочение."""
    rel = f"ПД/{LONG_DIR}/V2_01-10-01-02-05_Том 10.1.pdf"
    short = paths.disk_path(rel)
    ok = check("стадия та же", registry.guess_stage(short) == registry.guess_stage(rel),
               f'{registry.guess_stage(short)} и {registry.guess_stage(rel)}')
    ok &= check("раздел тот же", registry.guess_section(short) == registry.guess_section(rel),
                f'{registry.guess_section(short)} и {registry.guess_section(rel)}')
    ok &= check("стадия определена, а не «неизвестно»", registry.guess_stage(short) == "PD",
                registry.guess_stage(short))
    return ok


def test_written_to_disk():
    """Укороченный путь действительно создаётся: проверка на файловой системе машины."""
    import tempfile
    rel = paths.disk_path(f"ПД/{LONG_DIR}/Том 10.1.pdf")
    with tempfile.TemporaryDirectory() as tmp:
        dest = os.path.join(tmp, rel)
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                f.write("x")
            made = os.path.exists(dest)
        except OSError as e:
            made = False
            print(f"       {type(e).__name__}: {e}")
    return check("файл по укороченному пути создаётся", made)


def main():
    ok = True
    for title, fn in (("Обычные пути", test_short_paths_untouched),
                      ("Длинная папка", test_long_name_fits),
                      ("Длинные имена не слипаются", test_long_names_do_not_merge),
                      ("Разбор переживает укорочение", test_parsing_survives),
                      ("Запись на диск", test_written_to_disk)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
