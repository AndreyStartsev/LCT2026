"""Стройплощадка и снос: POS-081, POS-085 (#145, Р-102), POD-090, POD-091, POS-087 (Р-103).

  python tests/test_round3_site_rules.py

Выдержки — из текстового слоя ПОС и СГП Полярной 16, ПОС Речникова, КР Октябрьской.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import matrix_rules as mr  # noqa: E402
from pipeline import site_works as sw  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def cand(stage, key, value, raw=None, file_id=None):
    return {"file_id": file_id or f"{stage}-1", "page": 1, "document": "П-ПОС.pdf" if stage == "PD" else "Р-СГП3.pdf",
            "stage": stage, "key": key, "value": value, "raw": raw or str(value), "snippet": f"{key} {value}"}


def main():
    ok = True
    got = [(c["value"], c["raw"]) for c in sw.cranes("кранами Potain MСT 178, Liebherr 132-EC-H8 с длиной стрелы")
           if c["key"] == sw.CRANE_KEY]
    ok &= check("марка с кириллической «С» и с хвостом «-EC-H8» — основа марки",
                got == [("POTAINMCT178", "Potain MСT 178"), ("LIEBHERR132", "Liebherr 132-EC-H8")], str(got))
    ok &= check("экскаватор Liebherr R954C и автокран LTM — не башенный кран",
                sw.cranes("Экскаватор Liebherr R954C с навесным. Автокраном Liebherr LTM 1060") == [])
    zones = [c["value"] for c in sw.cranes("Опасная зона при работе крана составит: Rоп = 0,3·18 + 5,0 = 5,6 м.")
             if c["key"] == sw.ZONE_KEY]
    ok &= check("радиус опасной зоны из ПОС", zones == [5.6], str(zones))
    loads = sw.edge_limits("Ограничить нагрузку на бровку котлована до 2 тс/м² от машин. Нагрузка на бровке принята "
                           "равной 20кПа на расстоянии 1,0м. Складирование материалов не допускается в зоне 2 метров от "
                           "бровки котлована")
    ok &= check("2 тс/м² = 20 кПа, как пишут документы; зона 2 м от бровки",
                [(c["key"], c["value"]) for c in loads] == [(sw.LOAD_KEY, 20.0), (sw.LOAD_KEY, 20.0), (sw.EDGE_KEY, 2.0)],
                str(loads))
    catalog = {"POS-081": {"parameter_name": "Опасные зоны кранов", "criticality": "Критическое"},
               "POS-085": {"parameter_name": "Площадки складирования", "criticality": "Критическое"}}
    crane_rule = {"kind": "crane_zones", "compare": {"type": "site_works", "result": "VALUE_MISMATCH"}}
    same = {"PD": [cand("PD", sw.CRANE_KEY, "POTAINMDT189", "Potain MDT 189")],
            "RD": [cand("RD", sw.CRANE_KEY, "POTAINMDT189", "Potain MDT 189")]}
    f = mr.site_findings("OBJ", "POS-081", crane_rule, same, catalog)[0]
    ok &= check("тот же кран на стройгенплане — «сравнение невозможно»: по стройгенплану только гипотеза",
                f["violation_label"] == "COMPARISON_IMPOSSIBLE" and "только гипотеза" in f["extraction"]["detail"],
                f["extraction"]["detail"])
    other = {"PD": same["PD"], "RD": [cand("RD", sw.CRANE_KEY, "LIEBHERR132", "Liebherr 132-EC-H8")]}
    f = mr.site_findings("OBJ", "POS-081", crane_rule, other, catalog)[0]
    ok &= check("другой кран — гипотеза, не в сдачу", f["violation_label"] == "VIOLATION_PRESENT"
                and f["finding_status"] == "SUSPICION" and f["for_submission"] is False, f["extraction"]["detail"])
    edge_rule = {"kind": "pit_edge_limits", "compare": {"type": "site_works", "result": "VALUE_MISMATCH"}}
    f = mr.site_findings("OBJ", "POS-085", edge_rule, {"PD": [cand("PD", sw.LOAD_KEY, 20.0)],
                                                        "RD": [cand("RD", sw.LOAD_KEY, 20.0)]}, catalog)[0]
    ok &= check("те же ограничения у бровки — «нарушения нет»", f["violation_label"] == "NO_VIOLATION")
    f = mr.site_findings("OBJ", "POS-085", edge_rule, {"PD": [cand("PD", sw.LOAD_KEY, 20.0)],
                                                        "RD": [cand("RD", sw.LOAD_KEY, 30.0)]}, catalog)[0]
    ok &= check("нагрузка на бровку больше проектной — гипотеза", f["violation_label"] == "VIOLATION_PRESENT"
                and f["finding_status"] == "SUSPICION", f["extraction"]["detail"])
    ok &= check("зона развала из ПОС; «высота зоны развала» и «4-этажного» — не размер",
                [c["value"] for c in sw.collapse_zones("принимаем опасную зону (зону развала) при сносе здания 5,3 м. "
                                                      "Зона развала для демонтажа 4-этажного здания составляет от 6,3 м. "
                                                      "Высота зоны развала сносимых зданий высотой 7м")] == [5.3, 6.3])
    methods = lambda t: [c["value"] for c in sw.demolition_methods(t)]  # noqa: E731
    ok &= check("методы сноса: техника сводится к методу",
                methods("принимаем механизированный и ручной методы сноса объектов") == ["механизированный", "ручной"]
                and methods("Экскаватор с навесным разрушающим оборудованием, гидромолот") == ["механизированный"])
    ok &= check("смена навесного оборудования при том же методе — не нарушение (специалист)",
                sw.method_changes({sw.METHODS_KEY: {"механизированный"}}, {sw.METHODS_KEY: {"механизированный"}}) == [])
    ok &= check("обрушение вместо разборки — метод не из проекта",
                bool(sw.method_changes({sw.METHODS_KEY: {"поэлементный"}}, {sw.METHODS_KEY: {"обрушение"}})))
    tech = {(c["key"], c["value"]) for c in sw.technologies("Шпунтовое ограждение котлована с распорной системой. "
                                                            "Бетонирование сверху вниз. Каркас из монолитного железобетона")}
    ok &= check("технологии по группам; «сверху вниз» без top-down не берётся", tech == {
        ("крепление котлована", "шпунт"), ("крепление котлована", "распорная система"), ("каркас", "монолитный железобетон")},
        str(sorted(tech)))
    ok &= check("замена в группе — проектной нет, названа другая",
                sw.technology_changes({"каркас": {"монолитный железобетон"}}, {"каркас": {"сборный железобетон"}})
                and not sw.technology_changes({"крепление котлована": {"шпунт", "стена в грунте"}},
                                              {"крепление котлована": {"стена в грунте"}}))
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
