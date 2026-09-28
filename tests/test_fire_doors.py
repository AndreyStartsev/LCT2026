"""Проверка предела огнестойкости преград по местам. PPM-103, задача #93.

  python tests/test_fire_doors.py

Фрагменты с настоящих страниц: ППМ Речникова и Новослободской (проза с местом),
спецификация дверей Речникова (марка без места), планы Алтуфьевского (одна марка
с тремя пределами). У каждой проверки написано, какую ошибку она ловит.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import elements, fire_doors as fd, matrix_rules  # noqa: E402

# Речников, F0240 стр. 304: в одном предложении два предмета и два предела
TWO_SUBJECTS = ("Помещения, не обслуживающие автостоянку, отделить от помещения хранения "
                "автомобилей противопожарными перегородками с пределом огнестойкости не менее "
                "EI 90 c заполнением проемов противопожарными дверями EI 60.")
# Новослободская, F0102 стр. 90
LIFT_HALL = ("Двери указанных лифтовых холлов должны быть с пределом огнестойкости не менее EIS60.")
# Речников, F0330 стр. 14: спецификация — марка есть, места нет
SPEC = ("Дверь наружная противопожарная с коробкой замкнутого типа, металлическая, однопольная. "
        "2100х1050 Д11 ДПС 01 Пр 2430(h)-1210 EI 30 ГОСТ Р 57327-2016. Предел огнестойкости EI30.")
# Плоский текст плана: подписи EI без слова «огнестойкость»
PLAN = "403 EI-30 12 15 13 14 EI30 EI30 Д5л Д5л Д3л EIS60 EIS60 945 700"


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def rows(text):
    return fd.limits(text, elements.clause_bounds)


def test_parse():
    ok = True
    got = [(r["kind"], r["raw"], r["place"], r["atleast"]) for r in rows(TWO_SUBJECTS)]
    ok &= check("предмет берётся слева от числа: перегородки EI90, двери EI60",
                got == [("barrier", "EI90", "Автостоянка", True),
                        ("door", "EI60", "Автостоянка", False)], str(got))
    got = [(r["kind"], r["raw"], r["place"]) for r in rows(LIFT_HALL)]
    ok &= check("двери лифтовых холлов — место и вид названы",
                got == [("door", "EIS60", "Лифтовые холлы")], str(got))
    ok &= check("подписи плана без слова «огнестойкость» утверждением не считаются",
                rows(PLAN) == [], str(rows(PLAN)))
    spec = rows(SPEC)
    ok &= check("в спецификации предел есть, места нет",
                spec and all(r["place"] is None for r in spec), str([(r["raw"], r["place"]) for r in spec]))
    ok &= check("марка спецификации записана", any(r["mark"] == "Д11" for r in spec),
                str([r["mark"] for r in spec]))
    ok &= check("критерии разобраны буквами",
                [r["letters"] for r in rows(LIFT_HALL)] == ["EIS"], str([r["letters"] for r in rows(LIFT_HALL)]))
    return ok


def test_reductions():
    """Сравнение по местам: минуты, критерии и запрет мешать шкалы."""
    ok = True
    key = fd.key_of("Лифтовые холлы", "door")
    got = fd.reductions({key: {(60, "EIS")}}, {key: {(60, "EI")}})
    ok &= check("EIS60 → EI60 — потерян критерий S", got and "потерян критерий S" in got[0][3], str(got))
    got = fd.reductions({key: {(60, "EI")}}, {key: {(30, "EI")}})
    ok &= check("EI60 → EI30 — предел снижен", got and "снижен с 60 до 30" in got[0][3], str(got))
    got = fd.reductions({key: {(60, "EI")}}, {key: {(90, "EI")}})
    ok &= check("EI60 → EI90 — не нарушение", got == [], str(got))
    wall, door = fd.key_of("Шахты лифтов", "barrier"), fd.key_of("Шахты лифтов", "door")
    got = fd.reductions({wall: {(60, "REI")}}, {door: {(90, "EI")}})
    ok &= check("стена и дверь — разные ключи, сравнения нет", got == [], str(got))
    got = fd.reductions({wall: {(120, "R")}}, {wall: {(120, "EI")}})
    ok &= check("R120 и EI120 — разные величины, критерий не «потерян»", got == [], str(got))
    got = fd.reductions({key: {(60, "EI")}}, {fd.key_of("Коридоры", "door"): {(30, "EI")}})
    ok &= check("место без пары не сравнивается", got == [], str(got))
    return ok


def test_ambiguous_marks():
    """Марка с несколькими пределами — пояснение, а не вердикт (Алтуфьевское Д-6)."""
    cands = [{"mark": "Д-6", "raw": "EI30"}, {"mark": "Д-6", "raw": "EI45"},
             {"mark": "Д-6", "raw": "EI60"}, {"mark": "Д11", "raw": "EI30"}]
    got = fd.ambiguous_marks(cands)
    ok = check("Д-6 с тремя пределами найдена", set(got) == {"Д-6"}, str(got))
    ok &= check("однозначная марка в пояснение не идёт", "Д11" not in got)
    return ok


def test_candidates():
    """Кандидаты движка: ключ «место — вид», значение хешируемое."""
    rule = {"kind": "fire_barrier_limits"}
    got = matrix_rules.extract(rule, TWO_SUBJECTS)
    keys = [(c["key"], c["value"], c["raw"]) for c in got]
    ok = check("два кандидата с разными ключами",
               keys == [("Автостоянка — ограждающие конструкции", (90, "EI"), "EI90"),
                        ("Автостоянка — заполнение проёмов", (60, "EI"), "EI60")], str(keys))
    # без места кандидат извлекается под ключом «Место не названо»: в сравнение он не идёт
    # (build_findings его отбрасывает), а его марка нужна в пояснении — случай «одна марка, три предела»
    spec = matrix_rules.extract(rule, SPEC)
    ok &= check("кандидат без места — под ключом «Место не названо», с маркой для пояснения",
                [(c["key"], c.get("mark")) for c in spec] == [(fd.NO_PLACE_KEY, "Д11")], str(spec))
    ok &= check("подпись плана без слова «огнестойкость» кандидатом не становится",
                matrix_rules.extract(rule, PLAN) == [], str(matrix_rules.extract(rule, PLAN)))
    return ok


if __name__ == "__main__":
    print("Предел огнестойкости преград по местам (PPM-103)")
    results = [test_parse(), test_reductions(), test_ambiguous_marks(), test_candidates()]
    print("\nИТОГ: " + ("все проверки пройдены" if all(results) else "есть сбои"))
    sys.exit(0 if all(results) else 1)
