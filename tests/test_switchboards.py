"""Проверка сравнения по номерам: группы ВРУ и стояки. Пятая очередь Матрицы, #29.

  python tests/test_switchboards.py

Строки взяты из текстового слоя однолинейных схем ВРУ Речникова (ИОС1.1 и ЭМ)
и планов ИОС2 и ВК Алтуфьевского.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import risers, switchboards  # noqa: E402
from pipeline.switchboards import cable_spec  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def test_rows():
    ok = True
    rows = switchboards.group_rows(
        "Рабочее освещение шахты лифта №1 1РП1-10 0,07 - 1 - 0,07 - 0,9 - 0,35 - 90 - 0,1 QF10 ВА47-100 C 10 А "
        "ВВГнг(А)-LS 3x2,5 фаза B Рабочее освещение шахты лифта №2 1РП1-11 0,07 - 1 - 0,07 - 0,9 - 0,35 - 90 - 0,1 "
        "QF11 ВА47-100 C 16 А ВВГнг(А)-FRLS 3x1,5 фаза C")
    got = {r["group"]: r["breaker"]["raw"] for r in rows}
    ok &= check("автомат — первый после расчётных величин своей группы",
                got == {"1РП1-10": "ВА47-100 C 10 А", "1РП1-11": "ВА47-100 C 16 А"}, str(got))
    rows = switchboards.group_rows(
        "2РП2-1 117,8 - 1 - 117,8 - 0,93 - 192,5 - 60 - 1,4 QF1 ВА-99 C 200 А . . . . . . Резерв QF2 ВА-99 C 16 А")
    ok &= check("резервный автомат следующей строки не номинал группы",
                rows[0]["breaker"]["current"] == 200, str(rows[0]["breaker"]))
    rows = switchboards.group_rows(
        "Электрический конвертор электрощитовой 5РП1-6 0,5 - 1 - 0,5 - 0,95 - 2,39 - 12 - 0,2 QF6 АВДТ 63 C 16 А")
    ok &= check("дифавтомат «АВДТ 63 C 16 А»: номинал 16, а не 63",
                rows[0]["breaker"]["current"] == 16 and rows[0]["breaker"]["model"] == "АВДТ 63", str(rows[0]["breaker"]))
    # по образцу ИОС1.1 и ЭМ Речникова: строка обычной группы, за ней группа панели противопожарных устройств
    rows = switchboards.group_rows(
        "Блок управления БУЗО-1 1РП4-4 0,02 - 1 - 0,02 - 0,95 - 0,1 - 80 - 0,1 QF4 ВА47-100 C 16 А "
        "ВВГнг(А)-LS 3x1,5 1ДВ1.1 1РП5.СПЗ-16 5,5 - 1 - 5,5 - 0,85 - 9,8 - 8 - 0,2 QF16 ВА47-100М D 20 А ШУ "
        "ШУ-1ДВ1.1 ШУВ-5,5-03-R3 ВВГнг(А)-FRLS 5x4 1ДВ1.2")
    got = {r["group"]: (r["breaker"]["raw"], [c["raw"] for c in r["cables"]]) for r in rows}
    ok &= check("группа СПЗ «1РП5.СПЗ-16» — своя строка, её кабель не в окне соседней группы",
                got == {"1РП4-4": ("ВА47-100 C 16 А", ["ВВГнг(А)-LS 3x1,5"]),
                        "1РП5.СПЗ-16": ("ВА47-100М D 20 А", ["ВВГнг(А)-FRLS 5x4"])}, str(got))
    spec = cable_spec("ВВГнг(А)-LS", "4(1x70)+1х35")
    ok &= check("«4(1x70)+1х35»: четыре жилы по 70", (spec["cores"], spec["section"]) == (4, 70.0), str(spec))
    ok &= check("FRLS — огнестойкий кабель", cable_spec("ВВГнг(А)-FRLS", "3x2,5")["fire"])
    return ok


def test_changes():
    ok = True
    ok &= check("номинал группы в РД другой — расхождение",
                switchboards.breaker_changes({"1РП1-10": {"ВА47-100 C 10 А"}}, {"1РП1-10": {"ВА47-100 C 16 А"}})
                == [("1РП1-10", ["ВА47-100 C 10 А"], ["ВА47-100 C 16 А"])])

    def cables(*raws):
        out = {}
        for raw in raws:
            mark, size = raw.rsplit(" ", 1)
            out[raw] = cable_spec(mark, size)
        return out

    got = switchboards.cable_changes({"7РП1-3": cables("ВВГнг(А)-FRLS 3x2,5")}, {"7РП1-3": cables("ВВГнг(А)-LS 3x2,5")})
    ok &= check("огнестойкий кабель заменён обычным", len(got) == 1 and "огнестойкий" in got[0][3][0], str(got))
    got = switchboards.cable_changes({"1РП1-22": cables("ВВГнг(А)-LS 5x4")}, {"1РП1-22": cables("ВВГнг(А)-LS 5x2,5")})
    ok &= check("сечение той же марки уменьшено", len(got) == 1 and "сечение" in got[0][3][0], str(got))
    # Речников, 1РП1-22: рядом с номером группы на листе РД ещё и контрольный кабель
    got = switchboards.cable_changes({"1РП1-22": cables("ВВГнг(А)-LS 5x2,5")},
                                     {"1РП1-22": cables("ВВГнг(А)-LS 5x2,5", "ВВГЭнг(А)-LS 3x2,5")})
    ok &= check("кабель, который в РД только добавился, не замена", got == [], str(got))
    return ok


def test_risers():
    ok = True
    got = risers.riser_labels("20 21 22 Ст В1-1 ⌀32х3 Ст Т3-1 ⌀32х3 155 Ст К1-4 ⌀110х2.7")
    ok &= check("стояки В1 и Т3 с диаметрами, канализация не берётся",
                [(r["riser"], r["diameter"]) for r in got] == [("Ст В1-1", 32), ("Ст Т3-1", 32)], str(got))
    ok &= check("у стояка в РД диаметр меньше — уменьшение",
                risers.reductions({"Ст В1-3": {32}}, {"Ст В1-3": {25, 32}}) == [("Ст В1-3", [32], [25, 32])])
    ok &= check("у стояка в РД диаметр больше — не уменьшение",
                risers.reductions({"Ст В1-3": {32}}, {"Ст В1-3": {32, 40}}) == [])
    return ok


def main():
    ok = True
    for title, fn in (("Строки групповой схемы", test_rows), ("Расхождения по группам", test_changes),
                      ("Стояки", test_risers)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
