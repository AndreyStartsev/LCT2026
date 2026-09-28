"""Черновики «значение на чертеже», решённые специалистом 25.09 днём, — в правилах прода (#145, Р-105).

  python tests/test_round3_drawing_rules.py

AR-040, AR-041, AR-042, AR-047, AR-048, PPM-104, ODI-116 — порог-триггер Матрицы (Р-104), KR-061,
KR-062 — сравнение набором, KR-054 — изменение набора. Нарушение по значению с чертежа — гипотеза;
неоднозначное сравнение набором — тоже гипотеза, с низкой уверенностью.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import matrix_rules as mr  # noqa: E402
from pipeline import vlm_values  # noqa: E402

MOVED = {"2": ["AR-040", "AR-041", "AR-042", "AR-047", "AR-048", "KR-054", "KR-061", "KR-062"], "3": ["PPM-104", "ODI-116"]}


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def side(values):
    return {"value": min(values), "raw": "; ".join(f"{v:g}" for v in values), "all_values": sorted(values)}


def page_requires(rule):
    """Ответ модели о подступенке не берётся с листа армирования без подписи проступи (R4-H03)."""
    got = {"vlm": {"value": 200.0, "raw": "200 мм", "columns": ["200"], "label": "подступенок", "snippet": "модель",
                   "text_source": "RECOGNIZED"}}
    saved = mr.vlm_candidates
    mr.vlm_candidates = lambda rule, doc, page_no, out=None: [dict(got["vlm"])]
    try:
        doc = {"stage": "RD", "object_id": "OBJ", "file_id": "R1", "relative_path": "x/КЖ0.6.pdf"}
        rebar = "Каркас КП-1 поперечные стержни 15х200=3000 5х200=1000"
        stair = "Разрез 1-1 лестницы ЛК-1: марш 9х150=1350, проступь 8х300=2400"
        ok = check("лист армирования: «15х200=3000» без подписи проступи — ответ модели не берётся",
                   [c for c in mr.extract(rule, rebar, None, doc, 4) if c.get("text_source") == "RECOGNIZED"] == [])
        ok &= check("разрез марша с подписью проступи — ответ модели берётся",
                    len([c for c in mr.extract(rule, stair, None, doc, 5) if c.get("text_source") == "RECOGNIZED"]) == 1)
        steel = "Марш МЛ-1 4х150=600 4х150=600 площадка ПЛ-1"
        ok &= check("лист стальной лестницы без подписи проступи, но и без армирования — ответ берётся (КМ1.1 Полярной 16)",
                    len([c for c in mr.extract(rule, steel, None, doc, 6) if c.get("text_source") == "RECOGNIZED"]) == 1)
        kzh = "Армирование марша ЛМ-2: 11х300=3300 9х150=1350"
        ok &= check("лист армирования с подписью проступи — это разрез марша, ответ берётся (КЖ6 Речникова)",
                    len([c for c in mr.extract(rule, kzh, None, doc, 7) if c.get("text_source") == "RECOGNIZED"]) == 1)
    finally:
        mr.vlm_candidates = saved
    return ok


def main():
    ok = True
    rules = {}
    for q, codes in MOVED.items():
        prod = json.load(open(os.path.join(ROOT, "rules", f"matrix_queue{q}.json"), encoding="utf-8"))["parameters"]
        prov = json.load(open(os.path.join(ROOT, "rules", "provisional", f"q{q}.json"), encoding="utf-8"))["parameters"]
        for code in codes:
            rules[code] = prod[code]
            ok &= check(f"{code}: в проде, из черновиков убран, гипотезы по чертежу",
                        prod[code].get("implemented") and code not in prov and prod[code].get("hypotheses") == "drawing")
    triggers = {c: rules[c]["compare"].get("trigger") for c in rules if rules[c]["compare"]["type"].endswith("_trigger")}
    ok &= check("пороги — триггеры Матрицы", triggers == {"AR-040": 1200, "AR-041": 900, "AR-042": 1900, "AR-047": 1500,
                                                          "AR-048": 150, "PPM-104": 1200, "ODI-116": 1500}, str(triggers))
    rule = {"unit": "мм", "compare": rules["AR-048"]["compare"]}
    label, _r, detail = mr.decide(rule, side([150]), side([150, 170]))
    ok &= check("подступенок выше триггера 150 мм — нарушение", label == "VIOLATION_PRESENT" and "больше триггера" in detail, detail)
    label, _r, detail = mr.decide(rule, side([140]), side([145]))
    ok &= check("не выше триггера, но выше проектного — слабее", label == "VIOLATION_PRESENT" and "больше проектного" in detail)
    label, _r, _d = mr.decide(rule, None, side([150]))
    ok &= check("150 мм — не больше порога", label == "NO_VIOLATION")
    rule = {"unit": "мм", "compare": rules["KR-054"]["compare"]}
    label, _r, detail = mr.decide(rule, side([3000, 6000, 9000]), side([3000, 9000]))
    ok &= check("шаг осей: в РД только проектные значения — нарушения нет", label == "NO_VIOLATION", detail)
    label, _r, detail = mr.decide(rule, side([3000, 6000, 9000]), side([3000, 5300]))
    ok &= check("шаг осей: в РД есть шаг, которого нет в проекте, — изменение", label == "VIOLATION_PRESENT"
                and "5300" in detail, detail)
    known = dict(side([3000, 6000, 9000]), known_values=[1090, 3620])
    label, _r, detail = mr.decide(rule, known, side([3000, 1090, 3620]))
    ok &= check("шаг осей: число, которое проект пишет на листе того же вида, — не изменение (R4-H06, R4-H10)",
                label == "NO_VIOLATION" and "стоят текстом на листах проекта" in detail, detail)
    label, _r, detail = mr.decide(rule, known, side([3000, 1090, 5300]))
    ok &= check("шаг осей: неизвестный проекту шаг остаётся изменением", label == "VIOLATION_PRESENT"
                and "есть 5300" in detail and "1090" in detail, detail)
    ok &= page_requires(rules["AR-048"])
    f = {"violation_label": "COMPARISON_IMPOSSIBLE", "comparison_result": "VALUE_MISMATCH", "finding_status": "CANDIDATE",
         "criticality": None, "extraction": {"detail": "проект 200; 300 → рабочая 180; 300: в рабочей стадии есть значение меньше "
                                                       "наименьшего проектного, но участков несколько и какому из них "
                                                       "принадлежит подпись, по чертежу не определить"}}
    mr.drawing_hypothesis(f, rules["KR-061"], "Критическое")
    ok &= check("неоднозначное сравнение набором — гипотеза с низкой уверенностью",
                f["violation_label"] == "VIOLATION_PRESENT" and f["finding_status"] == "SUSPICION" and f["for_submission"] is False
                and f["criticality"] == "Критическое" and f["extraction"]["confidence"]["low"], str(f["extraction"]["confidence"]))
    form = rules["AR-041"]["vlm"]["confirm_form"]
    ok &= check("ширина двери — первое число «ширина×высота(h)», обозначение ГОСТ «2600x1150» — нет",
                vlm_values.confirmed_values([1250.0], "4 1250x2450(h) 1", None, form)[0] == [1250.0]
                and vlm_values.confirmed_values([2600.0], "ДСН А Оп П 2600x1150 ГОСТ 31173", None, form)[0] == [])
    form = rules["KR-061"]["vlm"]["confirm_form"]
    ok &= check("толщина стены — «t=…» без отметки уровня; «+4,330 t=180» — плита",
                vlm_values.confirmed_values([180.0], "+4,330 t=180 +4,590", None, form)[0] == []
                and vlm_values.confirmed_values([200.0], "стен и пилонов толщиной 200 мм", None, form)[0] == [200.0])
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
