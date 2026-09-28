"""Символ NUL из слоя PDF не роняет запись разбора в базу.

  python tests/test_worker_nul.py

27.09 разбор Полярной 16 на стенде прочитал все 26 247 страниц и упал на записи изменений между
редакциями: в тексте листа со сломанной кодировкой шрифта стоял символ NUL, а Postgres не хранит
его ни в jsonb («\\u0000 cannot be converted to text»), ни в text. Три попытки — три одинаковых
падения. Проверяется, что всё, что воркер пишет в базу из текста документов, приходит без NUL:
jsonb через общий сериализатор psycopg, значения сторон и место записи, шифр и изменение файла.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from psycopg.adapt import PyFormat, Transformer  # noqa: E402
from psycopg.types.json import Json, Jsonb  # noqa: E402

from service.worker import infra, steps  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def dumped(wrapper):
    """Что psycopg отправит в базу за этот объект — тем же путём, что execute."""
    return bytes(Transformer().get_dumper(wrapper, PyFormat.TEXT).dump(wrapper)).decode("utf-8")


def main():
    # строка изменения из revision_diff.jsonl Полярной 16: NUL в конце слова «…дни»
    page = {"new_page": 7, "changes": [{"was": "ан\x00дни\x00", "now": None}],
            "place": {"sheet": "3\x00"}, "keys\x00": ("a\x00", 1, None, 2.5, True)}
    got = infra.clean(page)
    ok = check("clean убирает NUL в строках, ключах, списках и кортежах; прочее не трогает",
               got == {"new_page": 7, "changes": [{"was": "андни", "now": None}], "place": {"sheet": "3"},
                       "keys": ["a", 1, None, 2.5, True]}, str(got))
    ok &= check("clean не меняет исходную запись", page["changes"][0]["was"] == "ан\x00дни\x00")

    body = dumped(Jsonb({"items": [page]}))
    ok &= check("jsonb уходит в базу без \\u0000", "\\u0000" not in body and "\x00" not in body, body[:120])
    ok &= check("и разбирается обратно в ту же запись без NUL",
                json.loads(body) == {"items": [got]})
    ok &= check("json (не jsonb) — тем же сериализатором", "\\u0000" not in dumped(Json(["x\x00"])))
    literal = "в тексте написано \\u0000 буквами"
    ok &= check("написанное буквами «\\u0000» — не NUL, остаётся как было",
                json.loads(dumped(Jsonb({"t": literal})))["t"] == literal)

    ok &= check("значение стороны строкой — без NUL", steps._text("12\x00,5 м") == "12,5 м")
    ok &= check("значение стороны списком — JSON без \\u0000",
                steps._text(["12\x00", 5]) == '["12", 5]', steps._text(["12\x00", 5]))
    ok &= check("пустое значение стороны остаётся пустым", steps._text(None) is None)

    source = open(os.path.join(ROOT, "service", "worker", "steps.py"), encoding="utf-8").read()
    ok &= check("место записи и поля файла, прочитанные с листа, проходят через clean",
                'location = infra.clean(", ".join(' in source
                and "infra.clean((d[\"file_id\"], d[\"stage\"]" in source)

    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
