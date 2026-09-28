"""Проверка приведения значения к единице правила. Задача #94.

  python tests/test_units.py

Строки взяты из корпуса: ширина проезда у Речникова напечатана в миллиметрах
(«6100 мм 6000 мм»), у Тюменской — в метрах, толщина стен у Тюменской в миллиметрах,
у Речникова в метрах («st=0.55 м»). Пока движок брал число как напечатано, правило
с абсолютным порогом на таком корпусе либо врало, либо было слепо.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import matrix_rules, tep, units  # noqa: E402

# Речников, F0237 стр. 47: ширина проезда автостоянки в миллиметрах. Значение стоит за
# подписью, как в строке таблицы: значение через слова движок не берёт и без единиц
RECHNIKOV = "Ширина проезда 6100 мм 6000 мм в свету"
# Тюменская, таблица ПЗУ: та же ширина в метрах
TYUMEN = "Ширина проезда, м 4,25 4,25 Покрытие асфальтобетон"
# Ниже порога 4,2 м: в миллиметрах и в метрах
NARROW_MM = "Ширина проезда 3500 мм по расчёту"
NARROW_M = "Ширина проезда, м 3,5"


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def test_table():
    """Словарь единиц: написания корпуса и размерности."""
    ok = True
    for token, want in (("мм", "мм"), ("кв.м.", "м²"), ("м2", "м²"), ("куб.м", "м³"),
                        ("метров", "м"), ("п.м", "м"), ("шт.", "шт"), ("кВт", "кВт")):
        ok &= check(f"«{token}» → {want}", units.canon(token) == want, str(units.canon(token)))
    ok &= check("6100 мм → 6,1 м", units.convert(6100, "мм", "м") == 6.1)
    ok &= check("0,9 м → 900 мм", units.convert(0.9, "м", "мм") == 900)
    ok &= check("площадь в длину не переводится", units.convert(4.2, "кв.м", "м") is None)
    ok &= check("незнакомая единица не переводится", units.convert(5, "дюйм", "м") is None)
    ok &= check("порог 1200 при «м» неправдоподобен", units.implausible(1200, "м") is not None)
    ok &= check("порог 4,2 при «м» правдоподобен", units.implausible(4.2, "м") is None)
    return ok


def values(text, unit=None):
    return tep.find_values(text, [r"ширина (?:проезда|проездов|проезжей части)"], (), "first", unit=unit)


def test_mixed_corpus():
    """Одно правило, значения в миллиметрах и в метрах: оба приводятся верно."""
    ok = True
    mm = values(RECHNIKOV, "м")
    ok &= check("«6100 мм» при единице правила «м» → 6,1",
                len(mm) == 1 and mm[0]["value"] == 6.1 and mm[0]["unit"] == "мм", str(mm)[:160])
    ok &= check("в записи осталось напечатанное число", mm and mm[0]["raw"] == "6100")
    ok &= check("колонки приведены тоже", mm and mm[0]["columns"] == [6.1, 6.0], str(mm[0]["columns"]) if mm else "")
    m = values(TYUMEN, "м")
    ok &= check("«, м 4,25» → 4,25", len(m) == 1 and m[0]["value"] == 4.25 and m[0]["unit"] == "м", str(m)[:140])
    ok &= check("без единицы правила значение остаётся как напечатано",
                values(RECHNIKOV)[0]["value"] == 6100.0)
    return ok


def test_no_unit_no_value():
    """Единицу определить нельзя — значение не берётся."""
    ok = True
    ok &= check("строка без единицы не даёт значения", values("Ширина проезда 6100 по расчёту", "м") == [])
    ok &= check("единица другой размерности не даёт значения", values("Ширина проезда 4,2 кв.м", "м") == [])
    ok &= check("а без единицы правила та же строка читается как раньше",
                values("Ширина проезда 6100 по расчёту")[0]["value"] == 6100.0)
    return ok


def decide(rd_text):
    rule = {"labels": [r"ширина (?:проезда|проездов|проезжей части)"], "rule": "first",
            "kind": "length", "unit": "м", "compare": {"type": "min_absolute", "threshold": 4.2}}
    got = matrix_rules.extract(rule, rd_text)
    side = {"value": got[0]["value"], "raw": got[0]["raw"]} if got else None
    return matrix_rules.decide(rule, None, side)


def test_decision():
    """Решение по абсолютному порогу: обе записи корпуса решаются одинаково."""
    ok = True
    label, _result, detail = decide(NARROW_MM)
    ok &= check("3500 мм — нарушение порога 4,2 м", label == "VIOLATION_PRESENT", detail)
    ok &= check("в пояснении названа единица", "м" in detail and "3.5" in detail, detail)
    label, _result, detail = decide(NARROW_M)
    ok &= check("3,5 м — то же нарушение", label == "VIOLATION_PRESENT", detail)
    label, _result, detail = decide(RECHNIKOV)
    ok &= check("6100 мм — нарушения нет", label == "NO_VIOLATION", detail)
    label, _result, detail = decide("Ширина проезда 6100 без единицы")
    ok &= check("значение без единицы в решение не попадает вовсе",
                label is None and "не найдено" in detail, f"{label}: {detail}")
    return ok


if __name__ == "__main__":
    print("Приведение к единице правила (#94)")
    results = [test_table(), test_mixed_corpus(), test_no_unit_no_value(), test_decision()]
    print("\nИТОГ: " + ("все проверки пройдены" if all(results) else "есть сбои"))
    sys.exit(0 if all(results) else 1)
