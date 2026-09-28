"""Окна по ведомостям: черновик AR-046 (#193).

  python tests/test_window_schedule.py

Решения специалиста: без ведомости окон в ПД можно не сравнивать; любое уменьшение площади
остекления — нарушение. Строки — из ведомости Алтуфьевского (РД L0057, стр. 12).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import matrix_rules, windows  # noqa: E402

CATALOG = {"AR-046": {"parameter_id": 46, "criticality": "Критическое",
                      "parameter_name": "Общее количество и габариты оконных блоков"}}
SHEET = ("Ведомость окон, витражей В-1 В-3 Поз. Размер проема Кол. Прим. В-1 36210х9820(h) 1 Двойной стеклопакет, "
         "EI 15 В-2 4000х7910(h) 1 Двойной стеклопакет, EI 15 В-3 1400х8330(h) 2 Двойной стеклопакет Д-1 "
         "2000х2040(h) 1 Двойной стеклопакет")


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def parsing():
    ok = check("лист с названием ведомости и размерами проёмов — ведомость", windows.schedule(SHEET) is not None)
    ok &= check("строка перечня листов с тем же названием — не ведомость",
                windows.schedule("5 Ведомость наружных витражных конструкций 6 Ведомость внутренних витражных "
                                 "конструкций Изм.1(Зам)") is None)
    got = [(r["mark"], r["w"], r["h"], r["n"]) for r in windows.rows(SHEET)]
    ok &= check("строки «марка размер количество»; двери не считаются",
                got == [("В-1", 36210, 9820, 1), ("В-2", 4000, 7910, 1), ("В-3", 1400, 8330, 2)], str(got))
    count, area, _ = windows.totals([{"mark": "В-3", "w": 1400, "h": 8330, "n": 2},
                                     {"mark": "В-3", "w": 1400, "h": 8330, "n": 2}])
    ok &= check("одна ведомость в двух файлах не удваивает окна", count == 2 and area == 23.32, f"{count} {area}")
    return ok


def cand(stage, form, file_id, page, mark=None, w=None, h=None, n=None):
    c = {"stage": stage, "form": form, "file_id": file_id, "page": page, "document": f"{file_id}.pdf",
         "snippet": f"{file_id} с.{page}", "raw": "x"}
    if form == "row":
        c.update(key=mark, w=w, h=h, value=n, location=mark)
    else:
        c.update(key="ведомость", value="Ведомость окон", location="ведомость")
    return c


def build(cands):
    rule = matrix_rules.load_provisional(2)["parameters"]["AR-046"]
    found = {st: [c for c in cands if c["stage"] == st] for st in ("PD", "RD")}
    return matrix_rules.window_findings("OBJ", "AR-046", rule, found, CATALOG)


def findings():
    rows = lambda st, fid, n2: [cand(st, "schedule", fid, 12),  # noqa: E731
                                cand(st, "row", fid, 12, "В-1", 1500, 1500, 10), cand(st, "row", fid, 12, "В-2", 900, 1500, n2)]
    [f] = build(rows("PD", "P", 4) + rows("RD", "R", 3))
    ok = check("окон в РД меньше — нарушение (любое уменьшение)",
               f["violation_label"] == "VIOLATION_PRESENT" and f["comparison_result"] == "VALUE_DECREASE"
               and f["extraction"]["detail"].startswith("окон в РД 13 против 14 в ПД; площадь проёмов в РД 26,55 м²"),
               f["extraction"]["detail"])
    smaller = rows("PD", "P", 4) + [cand("RD", "schedule", "R", 12), cand("RD", "row", "R", 12, "В-1", 1500, 1400, 10),
                                    cand("RD", "row", "R", 12, "В-2", 900, 1500, 5)]
    [f] = build(smaller)
    ok &= check("проём марки меньше проектного — нарушение, даже если окон больше",
                f["violation_label"] == "VIOLATION_PRESENT"
                and "В-1: проём в РД 1500х1400 против 1500х1500 в ПД" in f["extraction"]["detail"],
                f["extraction"]["detail"])
    [f] = build(rows("PD", "P", 4) + rows("RD", "R", 4))
    ok &= check("те же окна — «нарушения нет»", f["violation_label"] == "NO_VIOLATION"
                and f["comparison_result"] == "EQUAL_PD_RD")
    [f] = build(rows("RD", "R", 4))
    ok &= check("ведомости в ПД нет — «сравнение невозможно», причина названа",
                f["violation_label"] == "COMPARISON_IMPOSSIBLE"
                and f["extraction"]["detail"] == "в ПД ведомости окон нет — число и площадь окон не сравниваются")
    [f] = build([cand("PD", "schedule", "P", 3)] + rows("RD", "R", 4))
    ok &= check("ведомость в ПД без разобранных строк — «сравнение невозможно»",
                f["violation_label"] == "COMPARISON_IMPOSSIBLE" and "строки в ПД не разобраны" in f["extraction"]["detail"])
    ok &= check("ведомостей нет — записи нет", build([]) == [])
    return ok


def pipeline_path():
    rule = matrix_rules.load_provisional(2)["parameters"]["AR-046"]
    ar = {"stage": "RD", "section": "AR", "relative_path": "АР2.pdf"}
    kr = {"stage": "PD", "section": "KR", "relative_path": "КР1.pdf"}
    got = sorted(c["form"] for c in matrix_rules.extract(rule, SHEET, doc=ar))
    ok = check("разбор страницы АР: ведомость и строки", got == ["row", "row", "row", "schedule"], str(got))
    ok &= check("ведомость проёмов КР — не ведомость окон", matrix_rules.extract(rule, SHEET, doc=kr) == [])
    return ok


def main():
    ok = parsing()
    ok &= findings()
    ok &= pipeline_path()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
