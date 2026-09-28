"""Отклонения исполнительной схемы против допусков того же листа. Задача #89.

  python tests/test_tolerances.py

Фрагменты — с настоящих листов Октябрьской 103, прочитанных мультимодальной моделью; числа
сверены по изображениям листов 23.09.2026 и записаны в `bench/gold/recognized_values.jsonl`.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import tep, tolerances  # noqa: E402

# L0116 стр. 1: таблица отклонений и таблица допусков, как их прочитала модель
SHEET = """Исполнительная схема вертикальных конструкций на отм. -5,250 в осях: 5-8/Б-Д
№ проема низ верх
высота проект,м откл. от пр.отм.,мм высота проект,м откл. от пр.отм.,мм
1(КР-4.1) -3.950 +491 -2.900 +552
2(ВК-8) -2.900 +13 -2.250 +14
3(ВК-6.1) -2.900 +11 -2.350 +15
4(ВК-6.2) -2.900 -12 -2.250 -9
5(КР-4.2) -3.950 +980 -2.900 +537
6(ВК/ОВ-5) -2.170 -14 -1.670 -12
7(КР-4.3) -3.950 +201 -2.000 +349
Допустимые отклонения СП 70.13330.2012, табл. 5.12
Отклонение линий плоскостей пересечения от вертикали или проектного наклона на всю высоту
конструкций для стен и колонн, поддерживающих монолитные покрытия и перекрытия 15 мм
Отклонение от соосности вертикальных конструкций 15 мм
Отклонение размеров оконных, дверных и других проемов ±12 мм
Размер поперечного сечения элемента h при h < 200 мм (-3,+6)
h = 400 мм -9,+11
h > 2000 мм -20,+25
Отклонение длин или пролетов элементов, размеров в свету ±20 мм
Отклонение горизонтальных плоскостей на весь выбираемый участок 20 мм
"""


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def flat(text):
    return tep.flatten(text)


def test_limits():
    """Числа условий таблицы 5.12 допусками не считаются, иначе порог вырастет до 2000 мм."""
    ok = True
    limits = {n for n, _ in tolerances.declared_limits(flat(SHEET))}
    ok &= check("допуски листа: 12, 15 и 20 мм", limits == {12, 15, 20}, str(sorted(limits)))
    ok &= check("«h < 200 мм» — размер конструкции, не допуск", 200 not in limits)
    ok &= check("«h > 2000 мм» не даёт ни 2000, ни 000", not ({2000, 0} & limits))
    return ok


def test_deviations():
    """Проектные отметки не путаются с отклонениями: «-3.950» — отметка, «+491» — отклонение."""
    rows = {r["mark"]: r["values"] for r in tolerances.deviations(flat(SHEET))}
    ok = check("строк таблицы семь", len(rows) == 7, str(sorted(rows)))
    ok &= check("проём 5: +980 и +537", rows.get("5(КР-4.2)") == [980, 537], str(rows.get("5(КР-4.2)")))
    ok &= check("отрицательные отклонения читаются", rows.get("4(ВК-6.2)") == [-12, -9])
    ok &= check("отметка -3.950 отклонением не стала",
                all(abs(v) != 3950 for vals in rows.values() for v in vals))
    return ok


def test_verdict():
    """Сравнение идёт с наибольшим допуском листа: +15 мм при допуске 20 — не нарушение."""
    ok = True
    f = tolerances.sheet_findings("LOC-OKTYABRSKAYA-103", "L0116", 1, flat(SHEET), "Исп.схема")
    ok &= check("запись одна", len(f) == 1)
    r = f[0]
    over = {(o["mark"], o["value"]) for o in r["extraction"]["over"]}
    ok &= check("порог — наибольший допуск, 20 мм", r["extraction"]["bar_mm"] == 20)
    ok &= check("нарушение объявлено", r["violation_label"] == "VIOLATION_PRESENT")
    ok &= check("шесть превышений", len(over) == 6, str(sorted(over, key=lambda x: -abs(x[1]))))
    ok &= check("наибольшее отклонение в значении записи", r["id_value"] == "+980 мм", str(r["id_value"]))
    ok &= check("+15 мм при допуске 20 нарушением не объявлено",
                not any(abs(v) <= 20 for _m, v in over))
    ok &= check("локация — объект, как в эталонном перечне", r["locations"] == ["SITE"])
    ok &= check("значение помечено прочитанным машиной",
                r["extraction"]["id"]["text_source"] == "RECOGNIZED" and r["needs_expert"])
    return ok


def test_incomplete_table():
    """Обрывок таблицы допусков порога не задаёт: вердикта по нему не будет.

    На листе С2_ВК от 01.07 из шума распознавания разбирался «допуск» 45 мм, которого
    в таблице 5.12 нет, и он поднимал порог выше настоящих 20 мм.
    """
    piece = ("Исполнительная схема. № проема низ верх откл. от пр.отм.,мм "
             "1(ЗДЗ.1) -3.190 -521 -2.730 -516 "
             "Допустимые отклонения СП 70.13330.2012, табл. 5.12 45 мм 15 мм "
             "откл. превышают допустимые зн.")
    f = tolerances.sheet_findings("LOC-OKTYABRSKAYA-103", "L0084", 1, flat(piece), "Исп.схема")
    ok = check("запись есть: лист сам говорит о превышении", len(f) == 1)
    if f:
        ok &= check("но вердикта нет", f[0]["violation_label"] == "COMPARISON_IMPOSSIBLE",
                    f[0]["extraction"]["detail"][:90])
        ok &= check("пометка геодезиста названа", f[0]["extraction"]["sheet_note"] is True)
    return ok


def test_silence():
    """Лист без таблицы допусков и без пометки записи не даёт."""
    return check("на обычном листе записи нет",
                 tolerances.sheet_findings("X", "F1", 1, flat("Исполнительная схема. Ситуационный план"), None) == [])


if __name__ == "__main__":
    print("Отклонения исполнительной схемы против допусков (#89)")
    results = [test_limits(), test_deviations(), test_verdict(), test_incomplete_table(), test_silence()]
    print("\nИТОГ: " + ("все проверки пройдены" if all(results) else "есть сбои"))
    sys.exit(0 if all(results) else 1)
