"""Тип СОУЭ PPM-110 и огнезадерживающие клапаны PPM-111 — черновики, принятые специалистом как есть (#145, Р-106).

  python tests/test_round3_alarm_rules.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import alarms  # noqa: E402
from pipeline import matrix_rules as mr  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def main():
    ok = True
    types = lambda t: [c["value"] for c in alarms.soue_types(t)]  # noqa: E731
    ok &= check("«предусмотрена СОУЭ 3-го типа», «СОУЭ - 3 типа», «СОУЭ не ниже 4-го типа»",
                types("предусмотрена СОУЭ 3-го типа. здание оснащается СОУЭ - 3 типа. оборудуется СОУЭ не ниже 4-го типа")
                == [3.0, 3.0, 4.0])
    ok &= check("условие инструкции и экстренная связь — не тип объекта",
                types("Организация ОСО (при отсутствии на объекте СОУЭ 3-го типа и выше). Для системы экстренной связи "
                      "использовать панели экстренной связи СОУЭ не ниже 3-го типа") == [])
    q3 = json.load(open(os.path.join(ROOT, "rules", "matrix_queue3.json"), encoding="utf-8"))["parameters"]
    label, _r, detail = mr.decide(q3["PPM-110"], {"value": 4.0, "raw": "4-го типа"}, {"value": 3.0, "raw": "3-го типа"})
    ok &= check("тип в РД ниже проектного — нарушение", label == "VIOLATION_PRESENT", detail)
    got = mr.extract(q3["PPM-111"], "Клапан противопожарный канальный нормально открытый КПУ-1Н 200х100 шт. 4", None,
                     {"stage": "RD", "relative_path": "x/130-1222-ОК-1_Н-ОВ1 изм2.pdf"})
    ok &= check("ОЗК в спецификации ОВ", bool(got) and got[0]["columns"] == ["огнезадерживающие клапаны"])
    got = mr.extract(q3["PPM-111"], "Соленоидный клапан нормально открытый 24В, DN32 AMZ-112 Ридан шт. 13", None,
                     {"stage": "PD", "relative_path": "x/130-1222-ОК-1_Н-ИОС4.1.pdf"})
    ok &= check("соленоидный клапан водоснабжения — не ОЗК", got == [])
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
