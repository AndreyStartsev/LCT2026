"""Число пожарных извещателей по видам: черновик PPM-108 (#189).

  python tests/test_detector_count.py

Решения специалиста: автономные извещатели считаются в составе АПС; уменьшение в пределах допуска —
не нарушение; две цифры в колонке количества без пометки о запасе — без запаса. Строки — из
спецификаций открытых объектов: Тюменская, Алтуфьевское (ПД), ДОО, Полярная 16 (РД).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import detectors as det, matrix_rules  # noqa: E402

CATALOG = {"PPM-108": {"parameter_id": 108, "criticality": "Критическое",
                       "parameter_name": "Количество и расстановка извещателей АПС"}}


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def got(text):
    return [(r["key"], r["value"]) for r in det.rows(text)]


def rows():
    ok = check("Полярная 16: номер следующей строки за количеством не берётся, тепловой по «ИП 101»",
               got("3 Извещатель пожарный тепловой максимально-дифференциальный адресно-аналоговый ИП 101-29-PR-R3 "
                   "(для монтажа извещателя на подвесной потолок) ИП 101-29-PR-R3 W2.02 се- рия 5 RUBEZH шт. 1518 "
                   "4 Извещатель пожарный дымовой оптико-электронный автономный ИП 212-142 ИП 212-142 RUBEZH шт. 1104 "
                   "5 Изолятор шлейфа ИЗ-1 прот.R3 ИЗ-1-R3 серия 5 RUBEZH шт. 6")
               == [("тепловой", 1518), ("дымовой", 1104)])
    ok &= check("автономный дымовой — в счёте и помечен",
                [r["autonomous"] for r in det.rows("Извещатель пожарный дымовой оптико-электронный автономный "
                                                    "ИП 212-142 RUBEZH шт. 1104")] == [True])
    ok &= check("Тюменская: количество перед «шт.», линейный дымовой — дымовой",
                got("АБ 1240С 4 шт. Болид Извещатель пожарный дымовой адресный ДИП-34А-03 337 шт. Болид "
                    "Извещатель пожарный ручной адресный ИПР-513-3АМ исп.01 69 шт. Болид Извещатель пожарный дымовой "
                    "линейный адресный С2000-ИПДЛ исп.60 9 шт.") == [("дымовой", 337), ("ручной", 69), ("дымовой", 9)])
    ok &= check("ДОО: две цифры в колонке — вторая, количество после изменения",
                got("1.12 Извещатель пожарный дымовой оптико-электронный адресно-аналоговый ИП 212-64-R3 W1.02 Рубеж "
                    "шт. 287 289 для монтажа на несущих конструкциях 1.13 Извещатель") == [("дымовой", 289)])
    ok &= check("Алтуфьевское: «шт 172 20 Извещатель» — 172, а 20 — номер строки",
                got("19 Извещатель пожарный дымовой оптико-электронный адресно-аналоговый ДИП-34А-03 НВП Болид шт 172 "
                    "20 Извещатель пожарный ручной адресный ИПР 513-3АМ исп.01 НВП Болид шт 16 21 Блок")
                == [("дымовой", 172), ("ручной", 16)])
    ok &= check("охранные извещатели и принадлежности не считаются",
                got("Извещатель охранный поверхностный звуковой адресный С2000-СТ исп.03 НВП Болид шт 11 "
                    "Извещатель магнитоконтактный шт. 383 Извещатель оптико-электронный объемный адресный шт. 77 "
                    "ЗСК 101 Защитный сетчатый кожух для ручных пожарных извещателей Кабельные системы шт. 3") == [])
    ok &= check("подпись на структурной схеме «(3шт.)» и число из обозначения «…/220 шт 119» — не количество строки",
                got("Извещатель пожарный дымовой ИП 212-64-R3 (3шт.) 1ИЗ1.250") == []
                and got("Извещатель пожарный дымовой адресный на 220 В ДИП-34/220 шт 119") == [("дымовой", 119)])
    ok &= check("вид по обозначению ГОСТ Р 53325",
                [det.type_of(x) for x in ("ИП 101-29", "ИП 212-64", "ИП 329-5", "ИП 435-1", "ИПР 513", "ИП 212/101")]
                == ["тепловой", "дымовой", "пламени", "газовый", "ручной", "комбинированный"])
    return ok


def cand(stage, key, value, file_id, page, chain=None, autonomous=False):
    c = {"stage": stage, "key": key, "value": value, "raw": f"шт. {value}", "autonomous": autonomous,
         "snippet": f"{file_id} с.{page}: {key} {value}", "file_id": file_id, "page": page, "document": f"{file_id}.pdf",
         "location": key}
    if chain:
        c["chain"] = {"chain": chain, "rank": 0, "status": "RESOLVED"}
    return c


def totals():
    group = {"A1": "СПА", "A2": "СПА", "B": "СОУЭ"}.get
    t = det.totals([cand("RD", "дымовой", 100, "A1", 30), cand("RD", "дымовой", 20, "A1", 31),
                    cand("RD", "дымовой", 120, "A2", 30), cand("RD", "дымовой", 5, "B", 3)], group)
    return check("строки тома складываются, копии одной цепочки — нет, разные тома — складываются",
                 t == {"дымовой": 125}, str(t))


def build(cands):
    rule = matrix_rules.load_provisional(3)["parameters"]["PPM-108"]
    found = {st: [c for c in cands if c["stage"] == st] for st in ("PD", "RD")}
    return matrix_rules.detector_findings("OBJ", "PPM-108", rule, found, CATALOG)


def findings():
    [f] = build([cand("PD", "дымовой", 337, "P", 40), cand("PD", "ручной", 69, "P", 40),
                 cand("RD", "дымовой", 300, "R", 69), cand("RD", "ручной", 68, "R", 69)])
    ok = check("дымовых меньше на 11 % — нарушение, ручных на 1 % — в допуске",
               f["violation_label"] == "VIOLATION_PRESENT" and f["comparison_result"] == "COUNT_MISMATCH"
               and f["extraction"]["detail"] == "дымовой: в РД 300 против 337 в ПД — меньше на 11 %, допуск 5 %",
               f["extraction"]["detail"])
    ok &= check("значения стадий — по видам", f["pd_value"] == "дымовой — 337, ручной — 69 шт.", f["pd_value"])
    [f] = build([cand("PD", "дымовой", 172, "P", 46), cand("PD", "ручной", 16, "P", 46),
                 cand("RD", "дымовой", 180, "R", 69)])
    ok &= check("вид проекта, которого нет в РД, — нарушение",
                f["violation_label"] == "VIOLATION_PRESENT"
                and f["extraction"]["detail"] == "ручной: в ПД 16 шт., в РД извещателей этого вида нет",
                f["extraction"]["detail"])
    [f] = build([cand("PD", "дымовой", 287, "P", 69), cand("RD", "дымовой", 280, "R", 69),
                 cand("RD", "дымовой", 1104, "R", 30, autonomous=True), cand("RD", "тепловой", 7, "R", 70)])
    ok &= check("в допуске и больше — «нарушения нет»; вид только в РД не мешает",
                f["violation_label"] == "NO_VIOLATION", f["extraction"]["detail"])
    [f] = build([cand("RD", "дымовой", 634, "R", 69)])
    ok &= check("спецификация только в РД — «сравнение невозможно», причина названа",
                f["violation_label"] == "COMPARISON_IMPOSSIBLE"
                and f["extraction"]["detail"] == "спецификации пожарных извещателей с количеством в проектной стадии нет")
    [f] = build([cand("PD", "дымовой", 400, "P", 40), cand("RD", "дымовой", 300, "R", 30, autonomous=True)])
    ok &= check("автономные только в одной стадии — довод «средней» уверенности",
                any("автономные" in x for x in f["extraction"]["confidence"]["medium"]))
    ok &= check("спецификаций нет — записи нет", build([]) == [])
    return ok


def pipeline_path():
    rule = matrix_rules.load_provisional(3)["parameters"]["PPM-108"]
    text = "19 Извещатель пожарный дымовой оптико-электронный адресно-аналоговый ДИП-34А-03 НВП Болид шт 172 20"
    docs = {"ИОС5": {"stage": "PD", "section": "SS", "mark": "ИОС5.5.4", "relative_path": "ИОС5.5.4.pdf"},
            "СПА": {"stage": "RD", "section": "OTHER", "mark": "СПА", "relative_path": "СПА изм.9.pdf"},
            "ОПЗ": {"stage": "PD", "section": "OTHER", "mark": "ПЗ", "relative_path": "ОПЗ.pdf"}}
    seen = {name: [(c["key"], c["value"], c["location"]) for c in matrix_rules.extract(rule, text, doc=doc)]
            for name, doc in docs.items()}
    ok = check("разбор страницы: ИОС5 и том СПА — да, общая записка — нет",
               seen["ИОС5"] == [("дымовой", 172, "дымовой")] and seen["СПА"] and not seen["ОПЗ"], str(seen))
    ok &= check("черновик в очереди ППМ, прод-правило не реализовано",
                rule.get("provisional") is True
                and not matrix_rules.load_rules(matrix_rules.QUEUES[3])["parameters"]["PPM-108"].get("implemented"))
    return ok


def main():
    ok = rows()
    ok &= totals()
    ok &= findings()
    ok &= pipeline_path()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
