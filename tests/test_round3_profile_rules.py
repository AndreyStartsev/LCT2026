"""Черновики профиля третьего круга — в правилах прода (#145, Р-100; порог двери — Р-104).

  python tests/test_round3_profile_rules.py

PPM-102, ODI-121, ODI-117, PPM-105, ZU-124, ZU-127, ZU-131 перенесены из rules/provisional в
очереди прода. Здесь — то, что для переноса пришлось дописать: порог — триггер Матрицы, второй — требование ПД (`min_trigger`, Р-104),
форма записи ширины в свету, без которой ответ модели не подтверждён (`vlm.confirm_form`), ширина двери с
чертежа уже требования — гипотеза, и класс энергосбережения по тексту.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import matrix_rules as mr  # noqa: E402
from pipeline import vlm_values  # noqa: E402

MOVED = {"q3": ["PPM-102", "ODI-121", "ODI-117", "PPM-105"], "q4": ["ZU-124", "ZU-127", "ZU-131"]}


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def side(values, unit="мм"):
    shown = "; ".join(f"{v:g}" for v in values) + f" {unit}"
    return {"value": min(values), "raw": shown, "all_values": sorted(values)}


def test_min_trigger():
    """Порог — триггер Матрицы, второй — требование ПД (Р-104)."""
    ok = True
    rule = {"unit": "мм", "compare": {"type": "min_trigger", "trigger": 900, "result_violation": "DIMENSION_REDUCED"}}
    label, result, detail = mr.decide(rule, side([1200]), side([800, 1350]))
    ok &= check("дверь уже триггера — нарушение по триггеру", label == "VIOLATION_PRESENT"
                and result == "DIMENSION_REDUCED" and "меньше триггера" in detail, detail)
    label, _r, detail = mr.decide(rule, side([1200]), side([1050, 1350]))
    ok &= check("не уже триггера, но уже требования ПД — тоже нарушение, слабее", label == "VIOLATION_PRESENT"
                and "меньше требования ПД" in detail, detail)
    label, _r, detail = mr.decide(rule, None, side([850]))
    ok &= check("без ПД сравнение с триггером всё равно есть", label == "VIOLATION_PRESENT", detail)
    label, _r, _d = mr.decide(rule, side([900, 1200]), side([1350]))
    ok &= check("не уже порогов — нарушения нет", label == "NO_VIOLATION")
    label, _r, _d = mr.decide(rule, side([1200]), None)
    ok &= check("ширины РД нет — «сравнение невозможно»", label == "COMPARISON_IMPOSSIBLE")
    return ok


def test_value_form():
    """Ширина в свету подтверждается только числом сразу за подписью: на листах ДОО (АР5 изм.2, стр. 8)
    и Полярной 16 (АР1 изм.3, стр. 23) рядом стоят норма «min 900», высота ручки 1000 и ширина проёма."""
    ok = True
    q3 = json.load(open(os.path.join(ROOT, "rules", "matrix_queue3.json"), encoding="utf-8"))["parameters"]
    form = q3["PPM-105"]["vlm"]["confirm_form"]
    doo = ("Решетка Решетка 1000 1000 1000 1000 (в свету) min 900 проём 1150 (в свету) min 900 проём 1150 "
           "проём 1250 (в свету) 1050 проём 1550 (в свету) 1350 (в свету) min 900 ДН-1 - маркировка")
    got, _how = vlm_values.confirmed_values([1000.0, 1050.0, 1350.0, 900.0], doo, None, form)
    ok &= check("ДОО: 1050 и 1350 в свету подтверждены, высота ручки 1000 и норма min 900 — нет",
                got == [1050.0, 1350.0], str(got))
    pol16 = "1210 20 1250 в свету 1050 20 1310 20 1350 1650 20 1610 20 в свету ≥ 900 450 1350"
    got, _how = vlm_values.confirmed_values([1050.0, 1350.0, 1310.0, 900.0], pol16, None, form)
    ok &= check("Полярная 16: в свету 1050; ширина проёма 1350 и «≥ 900» — нет", got == [1050.0], str(got))
    return ok


def test_rules_moved():
    ok = True
    for q, codes in MOVED.items():
        prod = json.load(open(os.path.join(ROOT, "rules", f"matrix_queue{q[1]}.json"), encoding="utf-8"))["parameters"]
        prov = json.load(open(os.path.join(ROOT, "rules", "provisional", f"{q}.json"), encoding="utf-8"))["parameters"]
        for code in codes:
            rule = prod.get(code) or {}
            ok &= check(f"{code}: в очереди прода, из черновиков убран",
                        rule.get("implemented") is True and code not in prov and "compare_draft" not in rule)
    q3 = json.load(open(os.path.join(ROOT, "rules", "matrix_queue3.json"), encoding="utf-8"))["parameters"]
    ok &= check("ODI-117 и PPM-105: порог из ПД и форма записи ширины",
                all(q3[c]["compare"]["type"] == "min_trigger" and q3[c]["vlm"].get("confirm_form") for c in ("ODI-117", "PPM-105")))
    q4 = json.load(open(os.path.join(ROOT, "rules", "matrix_queue4.json"), encoding="utf-8"))
    ok &= check("ZU-124 — класс по тексту, перечень классов у очереди",
                q4["parameters"]["ZU-124"]["kind"] == "class" and "B+" in q4["classes"]["energy"])
    return ok


def test_hypothesis_for_door_widths():
    """Нарушение `min_trigger` — гипотеза с доводом «триггер»: какая это дверь, ответ модели не говорит."""
    ok = True
    rules = mr.load_rules(os.path.join(ROOT, "rules", "matrix_queue3.json"))
    rules["parameters"] = {"ODI-117": rules["parameters"]["ODI-117"]}

    def cands(stage, values):
        # документы разделов-источников каталога (ОДИ в ПД, АР в РД): иначе запасной источник
        # с расхождением решения не даёт
        name = "П-ОДИ.pdf" if stage == "PD" else "Р-АР1.pdf"
        return [{"file_id": f"{stage}-1", "page": 1, "document": name, "stage": stage, "value": v,
                 "raw": f"{v:g}", "columns": [f"{v:g}"], "label": "ширина", "snippet": f"ширина {v:g}"} for v in values]

    found = {"ODI-117": {"PD": cands("PD", [1200.0]), "RD": cands("RD", [600.0, 1200.0])}}
    saved = mr.collect
    mr.collect = lambda object_id, rules, progress=None: (found, {}, 2)
    try:
        findings, _summary = mr.build_findings("OBJ", rules)
    finally:
        mr.collect = saved
    f = findings[0]
    ok &= check("ширина с чертежа уже триггера — гипотеза: подозрение, не в сдачу",
                f["violation_label"] == "VIOLATION_PRESENT" and f["finding_status"] == "SUSPICION"
                and f["for_submission"] is False and f.get("needs_expert") is True, f["extraction"]["detail"])
    note = f["extraction"].get("confidence") or {}
    ok &= check("доводы уверенности: «за» — триггер, «проверить» — какая это дверь",
                note.get("up") == ["порог — триггер Матрицы"] and note.get("medium"), str(note))
    found = {"ODI-117": {"PD": cands("PD", [1200.0]), "RD": cands("RD", [1050.0, 1500.0])}}
    rules["parameters"]["ODI-117"] = dict(rules["parameters"]["ODI-117"], compare={
        "type": "min_trigger", "trigger": 900, "result_violation": "DIMENSION_REDUCED"})
    mr.collect = lambda object_id, rules, progress=None: (found, {}, 2)
    try:
        f = mr.build_findings("OBJ", rules)[0][0]
    finally:
        mr.collect = saved
    note = f["extraction"].get("confidence") or {}
    ok &= check("не ниже триггера, ниже требования ПД — довод «против», а не «триггер»",
                not note.get("up") and "за порогом только проектной документации, не триггера Матрицы" in note.get("medium", []),
                str(note))
    return ok


def test_energy_class_text():
    ok = True
    q4 = json.load(open(os.path.join(ROOT, "rules", "matrix_queue4.json"), encoding="utf-8"))
    rule = q4["parameters"]["ZU-124"]
    got = mr.extract(rule, "Класс энергосбережения здания - B+ (высокий)", q4["classes"]["energy"], {"stage": "PD"})
    ok &= check("класс энергосбережения из текста, «B+» — свой класс", [c["value"] for c in got] == ["B+"], str(got))
    label, _r, detail = mr.decide(rule, {"value": "B+", "raw": "B+"}, {"value": "B", "raw": "B"}, q4["classes"]["energy"])
    ok &= check("B+ → B — понижение класса", label == "VIOLATION_PRESENT", detail)
    return ok


def main():
    ok = True
    for name, test in (("порог — триггер Матрицы", test_min_trigger), ("форма записи ширины", test_value_form),
                       ("перенос правил", test_rules_moved), ("ширины дверей — гипотеза", test_hypothesis_for_door_widths),
                       ("класс энергосбережения", test_energy_class_text)):
        print(name)
        ok &= test()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
