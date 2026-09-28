"""Разборы очередей 2–5 на строках вне корпуса. Задача #41, пункт «у каждого парсера не меньше
пяти проверок на строках вне корпуса с ожидаемым значением или ожидаемым «не определено»».

  python tests/test_parsers_outside.py

Строки нарочно не из шести объектов: другие проектировщики, другие обороты, латиница вместо
кириллицы, другие единицы. Проверяется и то, что берётся, и то, что не должно браться:
парсер на чужом оформлении обязан либо ответить верно, либо промолчать, но не выдать чужое.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import demolition, elements, fire_water, lighting, metering, mgn_rooms, risers  # noqa: E402
from pipeline import smoke_fans, switchboards  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def test_switchboards():
    print("\n1. Групповые схемы ВРУ (switchboards)")
    rows = switchboards.group_rows("Щит ЩР-2. 3РП2-7 Iр=12 А QF7 ВА47-29 C 16 А кабель ВВГнг(А)-LS 3x2,5 освещение")
    ok = check("группа, автомат и кабель другого щита", rows and rows[0]["group"] == "3РП2-7"
               and rows[0]["breaker"]["raw"] == "ВА47-29 C 16 А" and rows[0]["cables"][0]["section"] == 2.5, str(rows))
    rows = switchboards.group_rows("2РП1.СПЗ-3 QF3 ВА47-100 C 25 А ВВГнг(А)-FRLS 5x4 щит противопожарных устройств")
    ok &= check("группа СПЗ с огнестойким кабелем", rows and rows[0]["group"] == "2РП1.СПЗ-3" and rows[0]["cables"][0]["fire"], str(rows))
    rows = switchboards.group_rows("Группа ЩР1-3, автомат S201 C16, кабель NYM 3x2,5")
    ok &= check("чужое обозначение группы «ЩР1-3» — не определено, чужой кабель не выдуман", rows == [], str(rows))
    rows = switchboards.group_rows("1РП3-12 QF12 ВА47-29 C 10 А")
    ok &= check("группа без кабеля в окне — кабелей нет, автомат есть",
                rows and rows[0]["cables"] == [] and rows[0]["breaker"]["current"] == 10, str(rows))
    rows = switchboards.group_rows("Расчётный ток 1РП3-12 QF12 ВА47-29 C 10 А. Резерв 1РП3-13 QF13 ВА47-29 C 16 А")
    ok &= check("две группы подряд: у каждой свой автомат", [r["breaker"]["current"] for r in rows] == [10, 16], str(rows))
    spec = switchboards.cable_spec("ПвПГнг(А)-HF", "5x16")
    ok &= check("кабель с пятью жилами и сечением 16", spec["cores"] == 5 and spec["section"] == 16.0 and not spec["fire"], str(spec))
    return ok


def test_risers():
    print("\n2. Стояки водопровода (risers)")
    got = risers.riser_labels("Ст.В1-12 Ø40х3,5 сталь")
    ok = check("стояк с точкой после «Ст» и другим знаком диаметра", got and got[0]["riser"] == "Ст В1-12" and got[0]["diameter"] == 40, str(got))
    got = risers.riser_labels("Ст Т3-4 Ф25х2,8 полипропилен PN20")
    ok &= check("диаметр через «Ф»", got and got[0]["diameter"] == 25 and got[0]["raw"] == "⌀25х2,8", str(got))
    got = risers.riser_labels("В1-⌀50х3.5 магистраль по подвалу")
    ok &= check("участок магистрали без номера стояка не берётся", got == [], str(got))
    got = risers.riser_labels("Ст К1-3 ⌀110")
    ok &= check("стояк канализации К1 — не система водопровода, не определено", got == [], str(got))
    got = risers.riser_labels("Стояк В2-7 ⌀32х3")
    ok &= check("слово «Стояк» целиком вместо «Ст» — не разбирается, а не выдаёт чужой номер", got == [], str(got))
    ok &= check("уменьшение диаметра по номеру", risers.reductions({"Ст В1-1": {32}}, {"Ст В1-1": {25}}) == [("Ст В1-1", [32], [25])]
                and risers.reductions({"Ст В1-1": {32}}, {"Ст В1-1": {32, 40}}) == [])
    return ok


def test_smoke_fans():
    print("\n3. Вентиляторы дымоудаления (smoke_fans)")
    got = smoke_fans.fan_duties("ДУ2 (L=18500 м³/ч, Pc=650 Па) крышный")
    ok = check("система ДУ с кубическим метром надстрочным", got and got[0]["system"] == "ДУ2" and got[0]["flow"] == 18500 and got[0]["pressure"] == 650, str(got))
    got = smoke_fans.fan_duties("Проект: ПД3 KSP 56 Данные Заданные Расчетные Производительность 12000 м3/ч 11800 м3/ч Статическое давление 400 Па 380 Па")
    ok &= check("лист подбора: заданные и расчётные величины", got and got[0]["flow"] == 12000 and got[0]["calc"] == (11800, 380), str(got))
    got = smoke_fans.fan_duties("П5 (L=9000 м3/ч, Pc=350 Па) приточная")
    ok &= check("приточная система П5 — не противодымная, не берётся", got == [], str(got))
    got = smoke_fans.fan_duties("ВД4 L=13000 м3/ч без давления и скобок")
    ok &= check("запись без скобок и давления — не определено, а не половина", got == [], str(got))
    got = smoke_fans.fan_duties("ДВ2,ПД2 Lв=27000м3/ч Lпр=21000м3/ч")
    ok &= check("пара систем со схемы: расход у каждой, давления нет",
                [(d["system"], d["flow"], d["pressure"]) for d in got] == [("ДВ2", 27000, None), ("ПД2", 21000, None)], str(got))
    return ok


def test_fire_water():
    print("\n4. Внутренний противопожарный водопровод (fire_water)")
    got = fire_water.jet_cases("Расход на внутреннее пожаротушение 2 струи по 2,6 л/с.")
    ok = check("«2 струи по 2,6 л/с»", got and got[0]["value"] == (2, 2.6), str(got))
    got = fire_water.jet_cases("принято 3 пожарные струи с расходом воды не менее 5,2 л/сек каждая")
    ok &= check("«3 пожарные струи с расходом воды не менее 5,2 л/сек»", got and got[0]["value"] == (3, 5.2), str(got))
    got = fire_water.jet_cases("По СП 10.13130 следует принимать 4 струи по 2,5 л/с")
    ok &= check("цитата нормы «следует принимать» не берётся", got == [], str(got))
    got = fire_water.jet_cases("1 струя, 2,9л/с")
    ok &= check("«1 струя, 2,9л/с» без пробела", got and got[0]["value"] == (1, 2.9) and got[0]["raw"] == "1 струя по 2,9 л/с", str(got))
    got = fire_water.jet_cases("гидранты 2 шт по 15 л/с наружное пожаротушение")
    ok &= check("наружное пожаротушение гидрантами — не струи ВПВ", got == [], str(got))
    label, result, _ = fire_water.decide({(2, 2.6)}, {(1, 2.6)})
    ok &= check("меньше струй в РД — нарушение", label == "VIOLATION_PRESENT", str((label, result)))
    return ok


def test_mgn_rooms():
    print("\n5. Санузлы МГН (mgn_rooms)")
    got = mgn_rooms.toilet_areas("2.3-7 Доступная кабина уборной 4,8")
    ok = check("чужая нумерация «2.3-7» и «Доступная кабина уборной»", got and got[0]["room"] == "2.3-7" and got[0]["area"] == 4.8, str(got))
    got = mgn_rooms.toilet_areas("2-3.7 Доступная кабина уборной 4,8")
    ok &= check("незнакомая форма номера «2-3.7» — не определено, а не обрывок номера", got == [], str(got))
    got = mgn_rooms.toilet_areas("015 Санузел для инвалидов 5,25")
    ok &= check("«Санузел для инвалидов» с ведущим нулём", got and got[0]["room"] == "015" and got[0]["area"] == 5.25, str(got))
    got = mgn_rooms.toilet_areas("104 Санузел 3,2")
    ok &= check("обычный санузел — не кабина МГН", got == [], str(got))
    got = mgn_rooms.toilet_areas("Универсальная кабина МГН 5,1")
    ok &= check("кабина без номера помещения — не определено", got == [], str(got))
    got = mgn_rooms.toilet_areas("12а Универсальная кабина 5,10 м2")
    ok &= check("буква в номере помещения", got and got[0]["room"] == "12а" and got[0]["area"] == 5.1, str(got))
    ok &= check("уменьшение площади с допуском округления",
                mgn_rooms.reductions({"12а": {5.1}}, {"12а": {5.05}}) == []
                and mgn_rooms.reductions({"12а": {5.1}}, {"12а": {4.4}}) == [("12а", ["5,1 м²"], ["4,4 м²"])])
    return ok


def test_demolition():
    print("\n6. Снос (demolition)")
    kinds = lambda text: [k for k, _ in demolition.statements(text)]
    ok = check("«существующие строения подлежат демонтажу»",
               kinds("Существующие строения на участке подлежат демонтажу до начала работ.") == ["APPLICABLE"])
    ok &= check("«снос не предусмотрен»", kinds("Снос существующих зданий проектом не предусмотрен.") == ["NOT_APPLICABLE"])
    ok &= check("«снос будет производиться в рамках отдельного проекта»",
                kinds("Снос будет производиться в рамках отдельного проекта заказчика.") == ["SEPARATE_PROJECT"])
    ok &= check("название раздела сметы со словом «снос» — ничего", kinds("Глава 1. Подготовка территории строительства, снос объекта, перенос сетей") == [])
    ok &= check("«безопасности» со «снос» внутри — ничего", kinds("Раздел мероприятий по обеспечению пожарной безопасности объекта") == [])
    got = demolition.decide([("NOT_APPLICABLE", "F1", 3, "снос не предусмотрен"), ("APPLICABLE", "F2", 5, "подлежат демонтажу")])
    ok &= check("при противоречии сильнее «снос есть»", got["status"] == "APPLICABLE", got["status"])
    return ok


def test_lighting():
    print("\n7. Источники света (lighting)")
    kinds = lambda text: sorted({v["value"] for v in lighting.light_sources(text)})
    ok = check("«светильники со светодиодными модулями»", kinds("Приняты светильники со светодиодными модулями 36 Вт.") == ["светодиодные"])
    ok &= check("«лампы накаливания» у переносных светильников не берутся", kinds("Переносной светильник, лампа накаливания 36 В") == [])
    ok &= check("рекомендация «заменить люминесцентные лампы» — не решение",
                kinds("Рекомендуется замена люминесцентных ламп на светодиодные светильники") == [])
    ok &= check("«прожекторы с галогенными лампами» вне освещения здания — ДНаТ на фасаде считается",
                kinds("Наружное освещение фасада: прожекторы с лампами ДНаТ 150 Вт") == ["ДНаТ"])
    ok &= check("слово без светильника рядом — ничего", kinds("Светодиодный индикатор на панели управления лифтом") == [])
    label, result, _ = lighting.decide({"светодиодные"}, {"люминесцентные"})
    ok &= check("проект светодиодные, в РД люминесцентные — нарушение", label == "VIOLATION_PRESENT", str((label, result)))
    return ok


def test_metering():
    print("\n8. Приборы учёта (metering)")
    keys = lambda text: sorted({m["key"] for m in metering.meters(text)})
    ok = check("«электросчётчик Меркурий 234»", keys("Учёт: электросчётчик Меркурий 234 ARTM-02") == ["электроэнергия"])
    ok &= check("«водосчётчик ВСХд-32»", keys("В водомерном узле установлен водосчётчик ВСХд-32") == ["вода"])
    ok &= check("«теплосчётчик ТВ7» и «узел учёта тепловой энергии»", keys("Узел учёта тепловой энергии на базе теплосчётчика ТВ7") == ["тепловая энергия"])
    ok &= check("«приборы учёта холодной воды» из договора — не прибор", keys("Абонент устанавливает приборы учета (узлы учета) холодной воды") == [])
    ok &= check("«счётчик посетителей» — не ресурс", keys("Установить счётчик посетителей на входе") == [])
    label, result, _ = metering.decide("вода", True, False, True)
    ok &= check("в проекте назван, в РД раздела не найден — сравнение невозможно", label == "COMPARISON_IMPOSSIBLE", str((label, result)))
    return ok


def test_elements():
    print("\n9. Классы бетона по элементам (elements)")
    got = elements.concrete_classes("Ростверки монолитные железобетонные из бетона класса В25, W6, F150.")
    ok = check("ростверки и класс с латинской подписью марок", got and got[0]["location"] == "Ростверки" and got[0]["value"] == 25, str(got))
    got = elements.concrete_classes("Стены в грунте выполняются из бетона B30 W8.")
    ok &= check("стена в грунте с латинской «B»", got and got[0]["location"] == "Стена в грунте" and got[0]["value"] == 30, str(got))
    got = elements.concrete_classes("Бетонная подготовка из бетона класса В7,5 толщиной 100 мм")
    ok &= check("бетонная подготовка — не несущий элемент, класс не берётся", got == [], str(got))
    got = elements.concrete_classes("Витамин B12 и группа B6 в рационе")
    ok &= check("«B12» без бетонного окружения — ничего", got == [], str(got))
    got = elements.concrete_classes("Фундаментная плита толщиной 1200 мм из бетона класса В35 марки F150")
    ok &= check("фундаментная плита В35", got and got[0]["location"] == "Фундаментная плита" and got[0]["value"] == 35, str(got))
    got = elements.concrete_classes("Колонны подземной части из бетона класса В40, колонны надземной части — из бетона класса В30.")
    ok &= check("вертикальные конструкции с зоной", {(g["location"], g["value"]) for g in got}
                >= {("Вертикальные конструкции подземной части", 40.0), ("Вертикальные конструкции надземной части", 30.0)}, str(got))
    return ok


def main():
    ok = True
    for fn in (test_switchboards, test_risers, test_smoke_fans, test_fire_water, test_mgn_rooms,
               test_demolition, test_lighting, test_metering, test_elements):
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
