"""Ложные значения правил на Полярной 17 (#229): толщина стен ядра, объём грунта, толщина фундаментной плиты.

  python tests/test_false_values_229.py

Тексты взяты со страниц Полярной 17 на демо-стенде: том ТХ.ВТ (стр. 4), ПЗУ1 (стр. 18), ГП1 (стр. 7);
строка баланса со слитыми числами — синтетическая. На стенде правила дали «стены ядра 250; 500 → 4 мм»
(критическое) и «объём грунта 41 → 6 м³»; текущий код — «41 → 2074 м³», где 2074 — площадь насыпи в м².
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import matrix_rules as mr  # noqa: E402

# Полярная 17, 133-0820-ОК-1-ТХ.ВТ, стр. 4 — указания по лифтам
LIFT_NOTES = ("в приямке лифта - 500мм от пола приямка шахты лифта. В качестве основной заземляющей магистрали "
              "в лифтовой шахте использовать стальную полосу толщиной 4мм и шириной 25мм. 2.11. В машинном "
              "помещении выполнить контур защитного заземления на высоте 500мм от уровня пола.")
# ПЗУ1, стр. 18: три участка, у каждого свой итог
PD_EARTH = ("ВЕДОМОСТЬ ОБЪЁМОВ ЗЕМЛЯНЫХ РАБОТ Насыпь (+) Выемка (-) 41.0 - - - - - 0.20 1661.7 332.3 "
            "ИТОГО ПЕРЕРАБАТЫВАЕМОГО ГРУНТА 30460.7 30460.7 - - - 26397.0 - - 332.3 "
            "ИТОГО ПЕРЕРАБАТЫВАЕМОГО ГРУНТА 4133.0 4133.0 2867.3 - - - При подсчете объемов "
            "ИТОГО ПЕРЕРАБАТЫВАЕМОГО ГРУНТА 153.1 153.1")
# ГП1, стр. 7: картограмма, площади и итоги
RD_EARTH = ("Насыпь +109 +32 +67 Всего, м³ +208 Выемка -6 -76 -193 -275 Площадь картограммы: 3823м² "
            "В том числе: насыпь: 2074м² выемка: 1625м² 8. Итого перерабатываемого грунта 28108 28108 -*** "
            "6. ИТОГО ПЕРЕРАБАТЫВАЕМОГО ГРУНТА 2254 2254 1355** - - При подсчете объемов")
# за двумя колонками баланса текст слоя продолжается отметками соседнего чертежа
RD_LONG_ROW = "Итого перерабатываемого грунта 1850 1850 20,00 20,00 20,00 20,00 14,70"


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def rule(code):
    for path in mr.QUEUES.values():
        got = mr.load_rules(path)["parameters"].get(code)
        if got:
            return got
    raise KeyError(code)


def test_wall_thickness():
    """Толщина стен ядра: число вне пределов параметра не берётся и из текста, не только из ответа модели."""
    kr061 = rule("KR-061")
    got = [c["value"] for c in mr.extract(kr061, LIFT_NOTES)]
    ok = check("полоса заземления 4 мм в лифтовой шахте — не толщина стены", got == [], str(got))
    got = [c["value"] for c in mr.extract(kr061, "Стены лифтовой шахты толщиной 200 мм, бетон B30")]
    ok &= check("стена шахты 200 мм берётся", got == [200.0], str(got))
    ok &= check("пределы без правила не отсекают", mr.in_value_range(4.0, {}) and mr.in_value_range("B30", kr061))
    return ok


def test_earth_volume():
    """Объём грунта — итог основного участка ведомости земляных масс в обеих стадиях."""
    spzu = rule("SPZU-024")
    pd = mr.extract(spzu, PD_EARTH)
    rd = mr.extract(spzu, RD_EARTH)
    ok = check("в ПД взяты итоги трёх участков, ячейка шапки 41,0 — нет",
               sorted(c["value"] for c in pd) == [153.1, 4133.0, 30460.7], str([c["value"] for c in pd]))
    ok &= check("в РД — итоги, а не ячейки картограммы и не площади в м²",
                sorted(c["value"] for c in rd) == [2254.0, 28108.0], str([c["value"] for c in rd]))
    ok &= check("у стадии — итог основного участка",
                [c["value"] for c in mr.choose_values(spzu, pd)] == [30460.7]
                and [c["value"] for c in mr.choose_values(spzu, rd)] == [28108.0])
    got = [c["value"] for c in mr.extract(spzu, RD_LONG_ROW)]
    ok &= check("строка баланса со слитыми числами соседнего листа — не ряд картограммы", got == [1850.0], str(got))
    ok &= check("без choose кандидаты не трогаются", mr.choose_values({}, pd) == pd)
    # две равные колонки из трёх цифр — не число с разрядами: «188 188» — это 188 и 188 м³, а не 188 188
    got = [(c["value"], c["columns"]) for c in mr.extract(spzu, "Итого перерабатываемого грунта 188 188 * в балансе")]
    ok &= check("«188 188» — две колонки по 188", got == [(188.0, [188.0, 188.0])], str(got))
    got = [c["value"] for c in mr.extract(spzu, "Итого перерабатываемого грунта 12 500 м3")]
    ok &= check("одна колонка с разрядами остаётся числом", got == [12500.0], str(got))
    return ok


def test_plate_from_kzh():
    """KR-058: плитный ростверк — фундаментная плита, толщина РД — только из томов КЖ (Полярная 17)."""
    kr058 = rule("KR-058")
    kzh = ("13. Ростверк. Ростверк пристроенной автостоянки представляет собой монолитную железобетонную плиту "
           "толщиной 500мм на свайном основании.")
    got = [(c["location"], c["value"]) for c in mr.extract(kr058, kzh)]
    ok = check("«ростверк … плиту толщиной 500мм» — толщина фундаментной плиты", got == [("Фундаментная плита", 500)],
               str(got))
    got = mr.extract(kr058, "Распределительный ростверк - монолитная плита толщиной 400мм.")
    ok &= check("распределительный ростверк — отдельный элемент, не плита", got == [], str(got))
    catalog = mr.load_catalog()

    def cand(doc, fid, value):
        return {"location": "Фундаментная плита", "value": value, "raw": str(value), "columns": [str(value)],
                "binding": "CLAUSE", "file_id": fid, "page": 1, "document": doc, "snippet": f"толщиной {value}",
                "label": "Фундаментная плита"}

    found = {"PD": [cand("пд/133-0820-ОК-1-КР1.pdf", "P1", 600)], "RD": [cand("рд/133-0820-ОК-1-ДР.pdf", "R1", 500)]}
    got = mr.element_findings("OBJ-X", "KR-058", kr058, found, catalog)
    ok &= check("толщина РД только из тома дренажа — сравнивать не с чем",
                [f["violation_label"] for f in got] == ["COMPARISON_IMPOSSIBLE"]
                and "ДР.pdf" in got[0]["extraction"]["detail"], str([f["extraction"]["detail"] for f in got]))
    found["RD"].append(cand("рд/133-0820-ОК-1-КЖ0.1.3.pdf", "R2", 500))
    got = mr.element_findings("OBJ-X", "KR-058", kr058, found, catalog)
    ok &= check("есть том КЖ — значение из него, доказательство — КЖ",
                [(f["violation_label"], [e["file_id"] for e in f["evidence"]]) for f in got]
                == [("VIOLATION_PRESENT", ["P1", "R2"])], str(got and got[0]["evidence"]))
    return ok


def test_drawing_reason():
    """Причина гипотезы по чертежу: «прочитано моделью» — только если значение дала модель."""
    def finding():
        return {"violation_label": "VIOLATION_PRESENT", "extraction": {"detail": "уменьшение"}}

    text_only = mr.drawing_hypothesis(finding(), {}, None, [{"value": 250.0}, {"value": 200.0}])
    by_model = mr.drawing_hypothesis(finding(), {}, None, [{"value": 250.0}, {"value": 200.0, "from_model": True}])
    unknown = mr.drawing_hypothesis(finding(), {}, None)
    ok = check("значения из текста — причина называет подпись на листе",
               text_only["exclusion_reason"] == mr.DRAWING_TEXT_HYPOTHESIS
               and "значение взято из подписи на листе" in text_only["extraction"]["confidence"]["medium"])
    ok &= check("значение модели — прежняя причина", by_model["exclusion_reason"] == mr.DRAWING_HYPOTHESIS
                and "значение прочитано моделью с чертежа" in by_model["extraction"]["confidence"]["medium"])
    ok &= check("без кандидатов — прежняя причина", unknown["exclusion_reason"] == mr.DRAWING_HYPOTHESIS)
    ok &= check("гипотеза по чертежу не идёт в сдачу", text_only["for_submission"] is False)
    return ok


if __name__ == "__main__":
    print("Ложные значения правил (#229)")
    results = [test_wall_thickness(), test_earth_volume(), test_plate_from_kzh(), test_drawing_reason()]
    print("\nИТОГ: " + ("все проверки пройдены" if all(results) else "есть сбои"))
    sys.exit(0 if all(results) else 1)
