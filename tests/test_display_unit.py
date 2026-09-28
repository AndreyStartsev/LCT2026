"""Подпись значения в записи находки: своя у правила вместо единицы каталога. Р-73.

  python tests/test_display_unit.py

Каталог Матрицы называет единицу параметра, а правило может считать другое. SPZU-029
считает позиции ведомости МАФ: штуки у неё в своей колонке, и каталожное «шт. / компл.»
выдало бы шесть позиций за шесть изделий. Эталон организатора пишет так же, как правило:
«16 позиций МАФ» (TEST-0002). Объект синтетический: ведомость МАФ на листе проектной
и рабочей стадий, в рабочей две позиции добавлены.
"""
import json
import os
import sys
import tempfile
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="dispunit-")
os.environ["PIPELINE_OUT"] = os.path.join(_TMP, "build")
os.environ["PIPELINE_CACHE"] = os.path.join(_TMP, "cache")

import pymupdf  # noqa: E402

from pipeline import config, matrix_rules, registry  # noqa: E402

FONT = pymupdf.Font("cour")

# Та же ведомость, что в tests/test_tep.py: в проекте шесть позиций, в рабочей стадии восемь.
# Числа количеств стоят между номерами позиций, у позиции 5 есть подпозиция 5.1
MAF_PD = ("ВЕДОМОСТЬ МАЛЫХ АРХИТЕКТУРНЫХ ФОРМ И ЭЛЕМЕНТОВ БЛАГОУСТРОЙСТВА "
          "Поз. Обозначение Наименование Кол-во шт. Примечание "
          "1 Урна, арт. У.У2 15 Завод (или аналог) 2 Скамейка, арт. PG60 14 Завод (или аналог) "
          "3 Кресло, арт. PG61 8 Завод (или аналог) 4 Скамья №1 1 индивид. изготовление "
          "5 Ограждение территории, м. пог. секция забора 2, h=2,0м 174.45 Завод заборов (или аналог) "
          "5.1 Ограждение въезда в паркинг, секция забора 2, h=0,75м. 31.35 Завод заборов "
          "6 Глыба Базальт 6 Карьер (или аналог) "
          "Номер на плане Наименование породы Количество, шт Проектируемые деревья: "
          "1 Сосна обыкновенная 2 2 Ель колючая 4 3 Черемуха Маака 5")
MAF_RD = MAF_PD.replace("6 Глыба Базальт 6 Карьер (или аналог)",
                        "6 Глыба Базальт 6 Карьер (или аналог) 7 Качели, арт. 6.14 1 Завод "
                        "8 Гамак, арт. 6.44 1 Завод")


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def _pdf(path, text):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    writer = pymupdf.TextWriter(page.rect)
    writer.append((60, 80), "Схема планировочной организации земельного участка.", font=FONT, fontsize=8)
    for i, line in enumerate(textwrap.wrap(text, 80)):
        writer.append((60, 110 + 12 * i), line, font=FONT, fontsize=8)
    writer.write_text(page)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc.save(path)
    doc.close()


def _findings(obj, files):
    root = os.path.join(_TMP, obj)
    for rel, text in files:
        _pdf(os.path.join(root, rel), text)
    config.register_object(obj, root, obj, split="EXTERNAL")
    docs = registry.build(obj)
    os.makedirs(os.path.join(config.OUT, obj), exist_ok=True)
    with open(os.path.join(config.OUT, obj, "documents.jsonl"), "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    findings, _ = matrix_rules.build_findings(obj, rules=matrix_rules.load_rules(matrix_rules.QUEUES[1]))
    return findings


def test_maf_positions():
    print("\n1. Позиции МАФ подписаны позициями, а не штуками каталога")
    found = _findings("OBJ-TEST-MAF", [
        ("Проектная документация/01-24-П-ПЗУ.pdf", MAF_PD),
        ("Рабочая документация/01-24-Р-ГП.pdf", MAF_RD),
    ])
    f = next((x for x in found if x["parameter_code"] == "SPZU-029"), None)
    ok = check("запись SPZU-029 есть и решена: позиций стало больше, сокращения нет",
               f is not None and f["violation_label"] == "NO_VIOLATION"
               and f["comparison_result"] == "NO_POSITION_REDUCTION",
               str(f and (f["violation_label"], f["comparison_result"])))
    ok &= check("значения стадий — «6 позиций МАФ» и «8 позиций МАФ», как пишет эталон",
                f is not None and (f["pd_value"], f["rd_value"]) == ("6 позиций МАФ", "8 позиций МАФ"),
                str(f and (f["pd_value"], f["rd_value"])))
    ok &= check("единицы каталога в записи нет", f is not None and "шт" not in f"{f['pd_value']} {f['rd_value']}")
    ok &= check("остальное из каталога на месте: название параметра",
                f is not None and f["title"] == "Спецификация МАФ", str(f and f["title"]))
    ok &= check("сам каталог не тронут: у параметра по-прежнему «шт. / компл.»",
                matrix_rules.load_catalog()["SPZU-029"]["unit"] == "шт. / компл.")
    return ok


def test_plural():
    print("\n2. Подпись согласуется с числом, как пишет человек")
    forms = matrix_rules.load_rules(matrix_rules.QUEUES[1])["parameters"]["SPZU-029"]["display_unit"]
    ok = True
    for n, want in ((1, "позиция"), (21, "позиция"), (101, "позиция"), (3, "позиции"), (22, "позиции"),
                    (104, "позиции"), (11, "позиций"), (12, "позиций"), (14, "позиций"), (16, "позиций"),
                    (27, "позиций"), (111, "позиций"), (0, "позиций")):
        got = matrix_rules._fmt({"value": float(n), "raw": str(n)}, forms)
        ok &= check(f"{n} → «{n} {want} МАФ»", got == f"{n} {want} МАФ", got)
    ok &= check("подпись строкой приписывается как есть",
                matrix_rules._fmt({"value": 5.0, "raw": "5"}, "шт. / компл.") == "5 шт. / компл.")
    return ok


def main():
    ok = test_maf_positions()
    ok &= test_plural()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
