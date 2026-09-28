"""Квартирография по типам квартир — PZ-011 (#138).

  python tests/test_apartment_mix.py

Выдержки — из текстового слоя Полярной 16: ТЭП записки ПД (стр. 13) и таблица «Квартирография
жилого дома. 2 секция» АР2 изм.5 (стр. 5).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import apartment_mix as am  # noqa: E402
from pipeline import matrix_rules as mr  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


TEP = """Общее количество квартир 
422 шт. 
в том числе:   -  квартиры-студии  
54 шт. 
                        - однокомнатных  
184 шт. 
                        - двухкомнатных  
123 шт. 
                        - трехкомнатных  
61 шт. 
11 
Площадь встроенных нежилых помещений"""

TABLE = "\n".join("""Кол-во
Квартирография жилого дома. 2 секция
1-
однокомнатная квартира
ТИП 1
1.2.1
17,32
37,47
40,99
23
2-
двухкомнатная квартира
ТИП 1
2.1
29,53
53,18
56,17
31
1-
однокомнатная квартира
с кухней-нишей
Ст.1.1.1
15,64
31,31
36,80
31
Квартира-студия с
кухней-нишей
Ст.1.1.2
15,86
32,45
37,94
23
Итого
5159,82
10214,95
10971,65
108""".splitlines())


def main():
    ok = True
    tep = am.tep_counts(TEP)
    ok &= check("ТЭП: всего и по типам", tep == {"total": 422, "studio": 54, "1": 184, "2": 123, "3": 61}, str(tep))
    rows = am.table_rows(TABLE)
    ok &= check("строки таблицы: количество — первое целое после площадей",
                [(r["type"], r["count"]) for r in rows] == [("1", 23), ("2", 31), ("1", 31), ("studio", 23)],
                str([(r["type"], r["mark"], r["count"]) for r in rows]))
    ok &= check("марка «Ст.» при названии «однокомнатная» — отмечено как переименование",
                [r["renamed"] for r in rows] == [False, False, True, False])
    ok &= check("строка «Итого» строкой квартир не считается", sum(r["count"] for r in rows) == 108)
    ok &= check("тип без названия берётся по марке", am.type_of("", "3.2.1") == ("3", "3")
                and am.type_of("", "Ст.1.1.1") == ("studio", "studio"))
    diff = am.changes({"studio": 54, "1": 184}, {"studio": 0, "1": 238})
    ok &= check("смена распределения — изменённые типы", diff == [("studio", 54, 0), ("1", 184, 238)], str(diff))
    ok &= check("ссылка РД на стадию ПД с положительным заключением находится",
                bool(am.PD_REFERENCE.search("Квартирография жилого дома (1 секция) приведена в соответствии со стадией ПД, "
                                            "получившей положительное заключение №")))
    ok &= check("по числу комнат: студии вместе с однокомнатными (R4-Q-PZ-011)",
                am.by_rooms({"studio": 54, "1": 184, "2": 123, "total": 361}) == {"1": 238, "2": 123, "total": 361})
    ok &= mix_record()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


def tep(stage, counts):
    """Кандидат ТЭП стадии, как его отдаёт сбор по объекту."""
    return {"key": "tep", "counts": dict(counts, total=sum(counts.values())), "file_id": f"{stage}-1", "page": 13,
            "document": f"{stage.lower()}-ПЗ.pdf", "stage": stage, "value": "ТЭП", "snippet": "Общее количество квартир"}


def mix_record():
    """Запись PZ-011: студии, ставшие однокомнатными, — уточнение; другая сумма — нарушение (четвёртый круг)."""
    rule = {"kind": "apartment_mix", "compare": {"type": "count_by_type", "result": "COUNT_MISMATCH"}}
    catalog = {"PZ-011": {"parameter_name": "Квартирография", "criticality": "Существенное"}}
    pd = {"studio": 54, "1": 184, "2": 123, "3": 61}
    f = mr.mix_findings("OBJ", "PZ-011", rule, {"PD": [tep("PD", pd)],
                                                "RD": [tep("RD", {"1": 238, "2": 123, "3": 61})]}, catalog)[0]
    ok = check("студии 54 → 0, однокомнатные 184 → 238 — «нарушения нет», в пояснении — уточнение",
               f["violation_label"] == "NO_VIOLATION" and f["comparison_result"] == "NON_TRIGGERING_DIFFERENCE_NO_DECREASE"
               and "студии 54 → 0" in f["extraction"]["detail"] and "уточнение" in f["extraction"]["detail"],
               f["extraction"]["detail"])
    f = mr.mix_findings("OBJ", "PZ-011", rule, {"PD": [tep("PD", pd)],
                                                "RD": [tep("RD", {"1": 230, "2": 131, "3": 61})]}, catalog)[0]
    ok &= check("однокомнатных со студиями меньше, двухкомнатных больше — нарушение",
                f["violation_label"] == "VIOLATION_PRESENT" and "студии и однокомнатные вместе: 238 → 230"
                in f["extraction"]["detail"], f["extraction"]["detail"])
    f = mr.mix_findings("OBJ", "PZ-011", rule, {"PD": [tep("PD", pd)], "RD": [tep("RD", pd)]}, catalog)[0]
    ok &= check("то же распределение — совпадает", f["violation_label"] == "NO_VIOLATION"
                and f["comparison_result"] == "EQUAL_PD_RD")
    return ok


if __name__ == "__main__":
    sys.exit(main())
