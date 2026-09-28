"""Проверка разбора третьей очереди Матрицы: ППМ и ОДИ, #27.

  python tests/test_fire_safety.py

Строки взяты из текстового слоя корпуса: перечни оборудования и листы подбора вентиляторов
ОВ Тюменской-5, схема ИОС4 Алтуфьевского, расходы ВПВ Речникова, Тюменской-5, Алтуфьевского
и Изумрудной, экспликации Речникова и Тюменской-5, однолинейные схемы ВРУ Речникова.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import fire_water, mgn_rooms, smoke_fans, switchboards  # noqa: E402
from pipeline.switchboards import cable_spec  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def test_fans():
    ok = True
    got = smoke_fans.fan_duties(
        "Итого по ВД9 (L=12300 м3/ч, Pc=600 Па) 481 083,90 ВД10(1), ВД10(2) (L=25400 м3/ч, Pc=300 Па) Оборудование")
    ok &= check("перечень оборудования: две системы одной строкой получают одно значение",
                [(f["system"], f["flow"], f["pressure"]) for f in got]
                == [("ВД9", 12300, 600), ("ВД10(1)", 25400, 300), ("ВД10(2)", 25400, 300)], str(got))
    got = smoke_fans.fan_duties(
        "Проект: ПД1 KSP 45-2,2х30 Данные Заданные Расчетные Производительность 8600 м3/ч 7830м3/ч "
        "Статическое давление 500 Па 414 Па Характеристики вентилятора")
    ok &= check("лист подбора: заданные величины и расчётная точка",
                [(f["system"], f["flow"], f["pressure"], f["calc"]) for f in got] == [("ПД1", 8600, 500, (7830, 414))],
                str(got))
    got = smoke_fans.fan_duties("Данные Заданные Расчетные Производительность 630 м3/ч 630 м3/ч Свободный напор 180 Па")
    ok &= check("подбор общеобменной системы без номера противодымной не берётся", got == [], str(got))
    got = smoke_fans.fan_duties("102 ДВ1,ПД1 Lв=30100м3/ч Lпр=24000м3/ч 1 этаж 2 этаж Кровля")
    ok &= check("схема ПД Алтуфьевского: расход вытяжки и притока без давления",
                [(f["system"], f["flow"], f["pressure"]) for f in got] == [("ДВ1", 30100, None), ("ПД1", 24000, None)],
                str(got))
    got = smoke_fans.fan_duties("QF3 3P/D25A ВА47-60MA ВД25 ВВГнг(А)-FRLSLTx (5x16) ВД4-175м-Л175 Ду80 L=2,0 м")
    ok &= check("номер системы в схеме щита и «Ду80 L=2,0 м» не значения", got == [], str(got))
    ok &= check("расход системы в РД меньше проектного — уменьшение",
                smoke_fans.reductions({"ПД1": {(8600, 500)}}, {"ПД1": {(8000, 500)}})
                == [("ПД1", ["L=8600 м³/ч, Pc=500 Па"], ["L=8000 м³/ч, Pc=500 Па"], ["расход 8600 → 8000 м³/ч"])])
    ok &= check("давление меньше при том же расходе — уменьшение",
                smoke_fans.reductions({"ВД1": {(13000, 500)}}, {"ВД1": {(13000, 450)}})[0][3] == ["давление 500 → 450 Па"])
    ok &= check("у проектной записи без давления давление не сравнивается",
                smoke_fans.reductions({"ПД1": {(24000, None)}}, {"ПД1": {(24000, 300)}}) == [])
    cands = [{"key": "ПД1", "value": (8600, 500), "calc": (7830, 414)},
             {"key": "ПД14", "value": (6400, 300), "calc": (6364, 296)},
             {"key": "ВД1", "value": (13000, 500), "calc": (13446, 534)}]
    got = smoke_fans.below_duty(cands)
    ok &= check("расчётная точка ниже заданной: сначала наибольшая недостача, запас не в списке",
                [k for k, *_ in got] == ["ПД1", "ПД14"], str(got))
    return ok


def test_jets():
    ok = True
    cases = [
        ("− 5,80 л/с – пожарные краны ПК-с (2 струи по 2,90 л/с);", (2, 2.9)),
        ("5,8 0,52 0,59 0,36 2 струи, 2,9л/с Ширинов", (2, 2.9)),
        ("внутреннее пожаротушение — 3,7 л/сек (1 струя по 3,7 л/сек) Итого", (1, 3.7)),
        ("− 2 струи с расходом не менее 5,2 л/с каждая в пожарном отсеке автостоянки", (2, 5.2)),
        ("предусматривается не менее 2 струй с расходом по 5 л/с каждая", (2, 5.0)),
        ("пожарные краны Ду50 с расчетом 2 струи на 2,6л/с. Система В2", (2, 2.6)),
    ]
    for text, expected in cases:
        got = [c["value"] for c in fire_water.jet_cases(text)]
        ok &= check(f"«{text[:48]}…»", got == [expected], str(got))
    got = fire_water.jet_cases("зданиях высотой свыше 50 м и объемом до 150 000 м3 следует принимать 2 струи по 0,6 / 1,0 л/с")
    ok &= check("цитата нормы «следует принимать» не случай проекта", got == [], str(got))
    got = fire_water.jet_cases("продувают сжатым воздухом и промывают струей воды, арматурные пленки")
    ok &= check("«струей воды» без расхода не случай", got == [], str(got))
    ok &= check("метка случая", fire_water.label(2, 5.2) == "2 струи по 5,2 л/с" and fire_water.label(1, 3.7) == "1 струя по 3,7 л/с")

    one, two = {(2, 2.9)}, {(2, 2.9), (2, 5.2)}
    ok &= check("совпадение наборов", fire_water.decide(one, {(2, 2.9)})[:2] == ("NO_VIOLATION", "EQUAL_PD_RD"))
    ok &= check("один случай в проекте, меньший в РД — нарушение",
                fire_water.decide({(2, 5.2)}, {(2, 2.9)})[:2] == ("VIOLATION_PRESENT", "VALUE_DECREASE"))
    ok &= check("меньше струй при том же суммарном расходе — нарушение",
                fire_water.decide({(2, 2.9)}, {(1, 5.8)})[:2] == ("VIOLATION_PRESENT", "VALUE_DECREASE"))
    ok &= check("больше струй, но расход струи меньше — нарушение",
                fire_water.decide({(2, 2.9)}, {(3, 2.5)})[:2] == ("VIOLATION_PRESENT", "VALUE_DECREASE"))
    ok &= check("больше струй и не меньший расход — нарушения нет",
                fire_water.decide({(2, 2.9)}, {(3, 2.9)})[:2] == ("NO_VIOLATION", "NON_TRIGGERING_DIFFERENCE_NO_DECREASE"))
    ok &= check("несколько случаев в проекте, меньший в РД — сравнение невозможно",
                fire_water.decide(two, {(1, 2.9)})[0] == "COMPARISON_IMPOSSIBLE")
    # Алтуфьевское: в ПД два комплекта, 2 струи по 2,6 и по 2,9 л/с, в РД 2 струи по 2,9 л/с
    got = fire_water.decide({(2, 2.6), (2, 2.9)}, {(2, 2.9)})
    ok &= check("РД называет часть случаев проекта — нарушения нет, пропуск назван",
                got[:2] == ("NO_VIOLATION", "NON_TRIGGERING_DIFFERENCE_NO_DECREASE") and "2,6" in got[2], str(got))
    ok &= check("в РД случаев нет — сравнение невозможно", fire_water.decide(two, set())[0] == "COMPARISON_IMPOSSIBLE")
    return ok


def test_rooms():
    ok = True
    got = mgn_rooms.toilet_areas("1.1-3 Комната ожидания посетителей 7,9 1.1-4 Универсальная кабина МГН 5,1 1.1-5 ПУИ 2,9 В4")
    ok &= check("экспликация Речникова", [(r["room"], r["area"]) for r in got] == [("1.1-4", 5.1)], str(got))
    got = mgn_rooms.toilet_areas("116 Санузел для девочек 18.1 117 Санузел для МГН 5.0 118 Санузел для мальчиков 15.9")
    ok &= check("экспликация Тюменской-5: номер без корпуса, площадь через точку",
                [(r["room"], r["area"]) for r in got] == [("117", 5.0)], str(got))
    got = mgn_rooms.toilet_areas("290,0 Класс пожарной опасности материала не менее КМ0 1.1-14 Универсальная кабина МГН "
                                 "Монолитные железобетонные конструкции/ кладка")
    ok &= check("строка ведомости отделки без площади не берётся", got == [], str(got))
    ok &= check("площадь в РД меньше проектной — уменьшение",
                mgn_rooms.reductions({"1.1-4": {5.1}}, {"1.1-4": {4.6}}) == [("1.1-4", ["5,1 м²"], ["4,6 м²"])])
    ok &= check("совпадение после округления экспликации не уменьшение",
                mgn_rooms.reductions({"1.1-4": {5.1}}, {"1.1-4": {5.06}}) == [])
    return ok


def test_fire_cables():
    ok = True

    def cables(*raws):
        out = {}
        for raw in raws:
            mark, size = raw.rsplit(" ", 1)
            out[raw] = cable_spec(mark, size)
        return out

    pd = {"1РП5.СПЗ-16": cables("ВВГнг(А)-FRLS 5x4"), "1РП1-10": cables("ВВГнг(А)-LS 3x2,5")}
    ok &= check("линии с огнестойким кабелем по проекту", switchboards.fire_lines(pd) == {"1РП5.СПЗ-16"})
    got = switchboards.fire_cable_losses(pd, {"1РП5.СПЗ-16": cables("ВВГнг(А)-LS 5x4"), "1РП1-10": cables("ВВГнг(А)-LS 3x2,5")})
    ok &= check("огнестойкий кабель заменён обычным — потеря", got == [("1РП5.СПЗ-16", ["ВВГнг(А)-FRLS 5x4"], ["ВВГнг(А)-LS 5x4"])],
                str(got))
    got = switchboards.fire_cable_losses(pd, {"1РП5.СПЗ-16": {}})
    ok &= check("пустое окно РД — не замена", got == [], str(got))
    got = switchboards.fire_cable_losses(pd, {"1РП5.СПЗ-16": cables("ВВГнг(А)-FRLS 5x4", "ВВГнг(А)-LS 3x1,5")})
    ok &= check("огнестойкий кабель в окне РД остался — не потеря", got == [], str(got))
    return ok


def main():
    ok = True
    for title, fn in (("Вентиляторы противодымной вентиляции", test_fans), ("Расход ВПВ", test_jets),
                      ("Кабины и санузлы для МГН", test_rooms), ("Огнестойкие кабели линий", test_fire_cables)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
