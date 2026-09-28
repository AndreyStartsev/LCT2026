"""Черновики третьего круга с данными текстом — в правилах прода (#145, Р-99).

  python tests/test_round3_text_rules.py

IOS3-074 выпуски канализации, PPM-114 наружное пожаротушение, KR-066 огнезащита и антикоррозия
стали, PPM-107 класс КМ отделки. Выдержки — из текстового слоя корпуса: ИОС3.1 и ВК1 Полярной 16,
ОПЗ Тюменской-5, ИОС2.1 Полярной 16, КР Алтуфьевского, АР0 Речникова, АР0 Полярной 16.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import finish_classes as fc  # noqa: E402
from pipeline import matrix_rules as mr  # noqa: E402
from pipeline import outdoor_water as ow  # noqa: E402
from pipeline import outlets, risers  # noqa: E402
from pipeline import steel_protection as sp  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def cand(stage, key, value, page=1, file_id=None, **extra):
    """Кандидат, как его отдаёт сбор по объекту: файл, страница, документ, подпись."""
    return {"file_id": file_id or f"{stage}-1", "page": page, "document": f"{stage.lower()}.pdf", "stage": stage,
            "key": key, "value": value, "raw": str(value), "snippet": f"{key} {value}", **extra}


def test_outlets():
    ok = True
    flat = ("Выпуск К1.1-1 ∅150 Q=4,62 л/с Выпуск К1.2-2 Ø100;L=6,50 Выпуск К2-3 | ⌀150 "
            "Выпуск К13 ∅100 Выпуск К11 Ø100 Выпуск К2 Ø250 К1.2-⌀110 Выпуск К4-1 ⌀100")
    got = {(o["outlet"], o["diameter"]) for o in outlets.outlet_labels(flat)}
    ok &= check("выпуски К1 и К2 по обозначению, без номера — свой ключ",
                got == {("К1.1-1", 150), ("К1.2-2", 100), ("К2-3", 150), ("К2", 250)}, str(sorted(got)))
    ok &= check("К13, К11 и К4 в параметр не входят, подпись участка без «Выпуск» не берётся",
                not any(o in {"К13", "К11", "К4-1", "К1.2"} for o, _ in got))
    rule = {"documents": {"PD": r"ИОС\s?3|ИОС\s?5\.3", "RD": r"(?<![А-ЯЁ])(?:Н?ВК|НК|ВиК)(?![А-ЯЁа-яё])"}}
    allowed = lambda stage, name: mr._document_allowed(rule, {"stage": stage, "relative_path": f"x/{name}"})  # noqa: E731
    ok &= check("источники — только разделы водоотведения: ЭОМ, ЭН и ИТП отсекаются",
                allowed("RD", "130-1222-ОК-1_Н-ВК1 изм 6.pdf") and allowed("RD", "04-П.СКБ-ПИР-Р-ВК.ТР3.pdf")
                and allowed("RD", "130-1222-ОК-1_Н-НК2 изм.1.pdf") and allowed("PD", "130-1222-ОК-1_Н-ИОС3.1.pdf")
                and not allowed("RD", "130-1222-ОК-1_Н-ЭОМ.ЖД изм.4.pdf") and not allowed("RD", "04-П.СКБ-ПИР-Р-9-ЭН.pdf")
                and not allowed("RD", "04-П.СКБ-ПИР-Р-9-ИТП.ТМ.pdf") and not allowed("RD", "ОВК-1.pdf")
                and allowed("ID", "схема.pdf"))
    # наружный диаметр к условному не приводится (Р-91, п. 3): ⌀110 против ⌀100 — это разные числа
    red = risers.reductions({"К1.2-1": {110}}, {"К1.2-1": {100}})
    ok &= check("сравниваются только одинаково обозначенные значения: 110 → 100 — уменьшение", red == [("К1.2-1", [110], [100])])
    ok &= check("совпадение и увеличение — не нарушение",
                risers.reductions({"К2-1": {150}, "К1-1": {100}}, {"К2-1": {150, 200}, "К1-1": {100}}) == [])
    loose = outlets.numbering_mismatch({"К2": {250}, "К1-1": {150}}, {"К2-1": {150}, "К2-3": {150}, "К1-1": {150}})
    ok &= check("в проекте выпуск без номера, в рабочей с номерами — сопоставляет инспектор (R4-Q-IOS3-074)",
                loose == [("К2", ["К2"], ["К2-1", "К2-3"])], str(loose))
    ok &= check("одинаково обозначенные выпуски инспектору не отдаются",
                outlets.numbering_mismatch({"К2-1": {150}}, {"К2-1": {150}, "К2-2": {100}}) == [])
    rule = {"kind": "sewer_outlets", "compare": {"type": "keyed", "result": "DIMENSION_REDUCED"}}
    catalog = {"IOS3-074": {"parameter_name": "Диаметры выпусков канализации", "criticality": "Существенное"}}
    f = mr.keyed_findings("OBJ", "IOS3-074", rule, {"PD": [cand("PD", "К2", 250)],
                                                    "RD": [cand("RD", "К2-1", 150), cand("RD", "К2-3", 150)]}, catalog)[0]
    ok &= check("запись «сравнение невозможно» с needs_expert и пояснением",
                f["violation_label"] == "COMPARISON_IMPOSSIBLE" and f.get("needs_expert") is True
                and "решает инспектор" in f["extraction"]["detail"], f["extraction"]["detail"])
    return ok


def test_outdoor_water():
    ok = True
    balance = ("Расход воды — 30,3 м³/час, 11,8 л/с Расход бытовых стоков — 13,4 л/с Наружное пожаротушение — 110 л/с "
               "Среднечасовой расход горячей воды — 1,5 м³/час, БАЛАНС ВОДОПОТРЕБЛЕНИЯ")
    ok &= check("строка баланса водопотребления — не расход здания", ow.flows(balance) == [])
    pol16 = ("Расход воды для обеспечения наружного пожаротушения проектируемого здания предусмотрен в количестве "
             "не менее 30 л/с, с возможностью подачи от двух существующих пожарных гидрантов, установленных на "
             "кольцевой водопроводной сети")
    flows = ow.flows(pol16)
    ok &= check("расход «здания» берётся и рядом с «кольцевой сетью»",
                [(f["value"], f["building"]) for f in flows] == [(30.0, True)], str(flows))
    hyd = ow.hydrants(pol16)
    ok &= check("число гидрантов и «существующие»", [(h["value"], h["existing"]) for h in hyd] == [(2, True)], str(hyd))
    ok &= check("«не менее чем от трех пожарных гидрантов»",
                [h["value"] for h in ow.hydrants("Наружное пожаротушение обеспечивается не менее чем от трех "
                                                 "пожарных гидрантов")] == [3])
    for text in ("- наружное пожаротушение - 110 л/с.", "Система пожаротушения: Система наружного пожаротушения 110л/с",
                 "Расход воды на наружное пожаротушение составляет 110 л/с."):
        ok &= check(f"110 л/с без «здания» — расход сети и квартала, не сравнивается (R4-Q-PPM-114): «{text[:36]}…»",
                    ow.flows(text) == [], str(ow.flows(text)))
    ok &= check("расход «здания» берётся и от 100 л/с",
                [f["value"] for f in ow.flows("Расход воды на наружное пожаротушение здания 110 л/с")] == [110.0])
    ok &= check("расход для магистральных кольцевых линий отбрасывается",
                ow.flows("для расчета магистральных кольцевых линий водопроводной сети принят расход на наружное "
                         "пожаротушение 110 л/с") == [])
    sides = mr.outdoor_water_sides([cand("PD", ow.FLOW_KEY, 110.0, building=False),
                                    cand("PD", ow.FLOW_KEY, 30.0, building=True),
                                    cand("PD", ow.HYDRANT_KEY, 2)])
    ok &= check("расход «здания» сильнее безымянного, гидранты остаются",
                sorted(c["value"] for c in sides) == [2, 30.0])
    red = ow.reductions({ow.FLOW_KEY: {30.0}, ow.HYDRANT_KEY: {3}}, {ow.FLOW_KEY: {30.0}, ow.HYDRANT_KEY: {2}})
    ok &= check("меньше гидрантов, чем в ПД, — нарушение", red == [(ow.HYDRANT_KEY, [3], [2])], str(red))
    ok &= check("вывод значений", ow.show(ow.FLOW_KEY, {30.0}) == "30 л/с" and ow.show(ow.HYDRANT_KEY, {2}) == "2 гидранта")
    return ok


def test_outdoor_record():
    ok = True
    rule = {"kind": "outdoor_fire_water", "compare": {"type": "keyed", "result": "VALUE_DECREASE"}}
    catalog = {"PPM-114": {"parameter_name": "Расход воды на наружное пожаротушение (НПВ)", "criticality": "Критическое"}}
    found = {"PD": [cand("PD", ow.FLOW_KEY, 30.0, building=True), cand("PD", ow.HYDRANT_KEY, 2, existing=True)]}
    f = mr.keyed_findings("OBJ", "PPM-114", rule, found, catalog)[0]
    ok &= check("РД без расхода — «сравнение невозможно», значение ПД в записи",
                f["violation_label"] == "COMPARISON_IMPOSSIBLE" and "30 л/с" in f["pd_value"], f["pd_value"])
    ok &= check("существующие гидранты и пустая РД — вопрос инспектору",
                f.get("needs_expert") is True and "существующие гидранты" in f["extraction"]["detail"])
    found["RD"] = [cand("RD", ow.FLOW_KEY, 20.0, building=True)]
    f = mr.keyed_findings("OBJ", "PPM-114", rule, found, catalog)[0]
    ok &= check("расход в РД меньше проектного — нарушение",
                f["violation_label"] == "VIOLATION_PRESENT" and f["comparison_result"] == "VALUE_DECREASE",
                f["extraction"]["detail"])
    return ok


def test_steel_protection():
    ok = True
    alt = ("Для защиты конструкций от воздействия пожара предусмотрено нанесение огнезащитного состава для "
           "достижения требуемого предела огнестойкости конструкций (REI 45 – для несущих стальных конструкций). "
           "Огнезащиту выполняет специализированная организация по отдельно разработанному проекту. "
           "Все стальные конструкции покрыть грунтом ГФ-021 по ГОСТ 25129-2020 толщиной не менее 80мкм.")
    fire = sp.fire_statements(alt)
    ok &= check("предел по элементу: «REI 45 – для несущих»",
                [(f["element"], f["value"]) for f in fire if f["kind"] == "limit"] == [("несущие конструкции", 45)],
                str(fire))
    ok &= check("отсылка к отдельному проекту огнезащиты — и без стального слова",
                any(f["kind"] == "project" for f in fire))
    coat = sp.coating_systems(alt)
    ok &= check("грунт ГФ-021, 80 мкм", [(c["primer"], c["microns"]) for c in coat] == [(["ГФ-021"], 80)], str(coat))
    noise = ("Пена двухкомпонентная огнезащитная DN1201 для металлических коробок. Противопожарный огнезащитный экран "
             "Е 30 на металлическом каркасе. СТО АРСС 11251254.001-018-03 «Проектирование огнезащиты несущих стальных "
             "конструкций». Акт на устройство обмазочных, окрасочных огнезащитных покрытий стальных конструкций.")
    ok &= check("пена, экран, перечень норм и строка перечня актов — не огнезащита стали",
                sp.fire_statements(noise) == [], str(sp.fire_statements(noise)))
    rech = ("Все наружные поверхности металлоконструкций должны быть огрунтованы грунтом ГФ-021 и окрашены эмалью "
            "ПФ 115 в два слоя на монтаже; Защиту металлических конструкций производить двумя слоями грунтовки ГФ-021 "
            "с последующим окрашиванием двумя слоями эмали ПФ-115.")
    systems = sp.coating_systems(rech)
    ok &= check("слои эмали не приписываются грунту: «грунтом ГФ-021 и окрашены эмалью ПФ 115 в два слоя»",
                systems[0]["layers"] == {"enamel": 2} and systems[0]["enamel"] == ["ПФ-115"], str(systems[0]))
    ok &= check("«двумя слоями грунтовки … двумя слоями эмали»", systems[1]["layers"] == {"primer": 2, "enamel": 2},
                str(systems[1]))
    ok &= check("«грунт Гф-021 за 2 раза» — строчная марка и «раз»",
                sp.coating_systems("Все металлические конструкции грунтовать и покрыть эмалью : - грунт Гф-021 за 2 раза")
                [0]["layers"].get("primer") == 2)
    pd = [{"primer": ["ГФ-021"], "enamel": ["ПФ-115"], "layers": {"primer": 2, "enamel": 2}, "microns": 90}]
    ok &= check("меньше микрон и слоёв — ослабление",
                len(sp.weakenings(pd, [{"primer": ["ГФ-021"], "enamel": ["ПФ-115"], "layers": {"primer": 1, "enamel": 2},
                                        "microns": 60}])) == 2)
    ok &= check("эмаль исключена — ослабление",
                sp.weakenings(pd, [{"primer": ["ГФ-021"], "enamel": [], "layers": {}, "microns": None}])
                == ["эмаль исключена: в рабочей стадии только грунтовка"])
    ok &= check("неуказанное — не нарушение: в РД слоёв и толщины нет", sp.weakenings(
        pd, [{"primer": ["ГФ-021"], "enamel": ["ПФ-115"], "layers": {}, "microns": None}]) == [])
    ok &= check("предел элемента ниже проектного", sp.limit_decreases({"колонны": {90}}, {"колонны": {60}, "балки": {45}})
                == [("колонны", [90], [60])])
    return ok


def test_steel_record():
    ok = True
    rule = {"kind": "steel_protection", "compare": {"type": "steel_protection", "result": "VALUE_DECREASE"}}
    catalog = {"KR-066": {"parameter_name": "Антикоррозионная и огнезащитная обработка", "criticality": "Критическое"}}
    project = cand("PD", "fire", "project::", statement="project", element=None, limit=None)
    limit = cand("PD", "fire", "limit:несущие конструкции:45", page=2, statement="limit",
                 element="несущие конструкции", limit=45)
    mention = cand("RD", "fire", "mention::", statement="mention", element=None, limit=None)
    f = mr.steel_findings("OBJ", "KR-066", rule, {"PD": [project, limit], "RD": [mention]}, catalog)[0]
    ok &= check("отсылка к проекту огнезащиты — «сравнение невозможно», needs_expert, запросить проект",
                f["violation_label"] == "COMPARISON_IMPOSSIBLE" and f.get("needs_expert") is True
                and "запросите проект огнезащиты" in f["extraction"]["detail"], f["extraction"]["detail"])
    weak = {"primer": ["ГФ-021"], "enamel": [], "layers": {"primer": 1}, "microns": 60}
    strong = {"primer": ["ГФ-021"], "enamel": ["ПФ-115"], "layers": {"primer": 1, "enamel": 2}, "microns": 90}
    f = mr.steel_findings("OBJ", "KR-066", rule, {"PD": [cand("PD", "coat", "x", system=strong)],
                                                   "RD": [cand("RD", "coat", "y", system=weak)]}, catalog)[0]
    ok &= check("ослабленная антикоррозия — нарушение", f["violation_label"] == "VIOLATION_PRESENT"
                and "60 мкм против 90 мкм" in f["extraction"]["detail"], f["extraction"]["detail"])
    other = {"primer": ["ЭП-0010"], "enamel": ["ЭП-773"], "layers": {}, "microns": None}
    f = mr.steel_findings("OBJ", "KR-066", rule, {"PD": [cand("PD", "coat", "x", system=other)],
                                                   "RD": [cand("RD", "coat", "y", system=strong)]}, catalog)[0]
    ok &= check("система заменена целиком без ослабления — гипотеза с низкой уверенностью (Р-104)",
                f["violation_label"] == "VIOLATION_PRESENT" and f["finding_status"] == "SUSPICION"
                and f.get("needs_expert") is True and (f["extraction"].get("confidence") or {}).get("low"))
    return ok


def test_finish_classes():
    ok = True
    table = ("Вестибюли, лестничные клетки, лифтовые холлы Общие коридоры, холлы, фойе Вестибюли, лестничные клетки, "
             "лифтовые холлы Общие коридоры, холлы, фойе Ф 1.3; Ф 4.3; Ф 5.1; Ф 5.2 КМ0 КМ1 КМ1 КМ2 Классы пожарной")
    need = fc.strictest(fc.requirements(table))
    ok &= check("таблица ПД: стены и потолки КМ0/КМ1, полы КМ1/КМ2", need == {
        ("вестибюли и лестничные клетки", "стены и потолки"): 0, ("общие коридоры и холлы", "стены и потолки"): 1,
        ("вестибюли и лестничные клетки", "полы"): 1, ("общие коридоры и холлы", "полы"): 2}, str(need))
    rd = fc.rd_classes("Пт-2 1. Шпаклевка - 5 мм; 3. Окраска поверхности водно-дисперсионной краской в 2 слоя. 413,1 "
                       "Класс пожарной опасности не более КМ2 Пт-7 1. Потолок 2 слоя ГКЛВ 125,1 Класс пожарной "
                       "опасности не более КМ1 Пт-8 1. Обеспыливание 22,4 Класс пожарной опасности не более КМ0")
    ok &= check("марки ведомости и их классы", [(c["mark"], c["value"]) for c in rd] == [("Пт-2", 2), ("Пт-7", 1), ("Пт-8", 0)],
                str([(c["mark"], c["value"]) for c in rd]))
    worse, between = fc.worse(rd, need)
    ok &= check("марка хуже любого пути — хуже проектного, между путями — «требует уточнения»",
                [c["mark"] for c, _r, _g in worse] == ["Пт-2"] and [c["mark"] for c in between] == ["Пт-7"])
    general = fc.rd_classes("13. Для декоративно-отделочных материалов стен и потолков принять показатели пожарной "
                            "опасности не ниже: - лестничные клетки - КМ0 (НГ); - тех. помещения для прокладки")
    ok &= check("общие указания РД: вид пути и класс",
                [(c["group"], c["value"]) for c in general] == [("вестибюли и лестничные клетки", 0)], str(general))
    ok &= check("марка комплекта и контактор — не класс",
                fc.rd_classes("23.009-Р-1-КМ1 Конструкции металлические. 3 КМ 1 160 3 КМ 2 160") == [])
    return ok


def test_finish_record():
    ok = True
    rule = {"kind": "finish_fire_class", "compare": {"type": "finish_fire_class", "result": "CLASS_DOWNGRADE"}}
    catalog = {"PPM-107": {"parameter_name": "Класс пожарной опасности отделочных материалов", "criticality": "Критическое"}}
    pd = [cand("PD", "вестибюли и лестничные клетки: стены и потолки", 0, form="table",
               group="вестибюли и лестничные клетки", surface="стены и потолки"),
          cand("PD", "общие коридоры и холлы: стены и потолки", 1, form="table",
               group="общие коридоры и холлы", surface="стены и потолки")]
    rd = [cand("RD", "Пт-2", 2, form="mark", group=None, mark="Пт-2", room=None)]
    f = mr.finish_findings("OBJ", "PPM-107", rule, {"PD": pd, "RD": rd}, catalog)[0]
    ok &= check("марка хуже требования к общим коридорам — нарушение (R4-H11), где стоит — сверяет инспектор",
                f["violation_label"] == "VIOLATION_PRESENT" and f["finding_status"] == "CANDIDATE"
                and f.get("for_submission") is not False and f["needs_expert"] is True
                and "план потолков" in f["extraction"]["detail"]
                and "марка отделки привязана к помещению только планом потолков" in f["extraction"]["confidence"]["low"],
                f["extraction"]["detail"])
    rd = [cand("RD", "коридоры", 2, form="general", group="общие коридоры и холлы", mark=None, room="коридоры")]
    f = mr.finish_findings("OBJ", "PPM-107", rule, {"PD": pd, "RD": rd}, catalog)[0]
    ok &= check("общее указание РД для коридоров хуже проектного — нарушение без оговорки о плане потолков",
                f["violation_label"] == "VIOLATION_PRESENT" and f["finding_status"] != "SUSPICION"
                and f.get("for_submission") is not False and not f.get("needs_expert"), f["extraction"]["detail"])
    rd = [cand("RD", "лестничные клетки", 1, form="general", group="вестибюли и лестничные клетки", mark=None,
               room="лестничные клетки")]
    f = mr.finish_findings("OBJ", "PPM-107", rule, {"PD": pd, "RD": rd}, catalog)[0]
    ok &= check("хуже требования только к вестибюлям и лестничным клеткам — гипотеза, как решил третий круг",
                f["violation_label"] == "VIOLATION_PRESENT" and f["finding_status"] == "SUSPICION"
                and f["for_submission"] is False and f["needs_expert"] is True, f["extraction"]["detail"])
    rd = [cand("RD", "Пт-7", 1, form="mark", group=None, mark="Пт-7", room=None)]
    f = mr.finish_findings("OBJ", "PPM-107", rule, {"PD": pd, "RD": rd}, catalog)[0]
    ok &= check("марка между требованиями путей — гипотеза с низкой уверенностью (Р-104)",
                f["violation_label"] == "VIOLATION_PRESENT" and f["finding_status"] == "SUSPICION"
                and (f["extraction"].get("confidence") or {}).get("low"))
    rd = [cand("RD", "лестничные клетки", 0, form="general", group="вестибюли и лестничные клетки", mark=None,
               room="лестничные клетки")]
    f = mr.finish_findings("OBJ", "PPM-107", rule, {"PD": pd, "RD": rd}, catalog)[0]
    ok &= check("общие указания не хуже проектных — для «нарушения нет» мало",
                f["violation_label"] == "COMPARISON_IMPOSSIBLE" and "для «нарушения нет» этого мало" in f["extraction"]["detail"])
    return ok


def main():
    ok = True
    for name, test in (("IOS3-074: выпуски канализации", test_outlets),
                       ("PPM-114: наружное пожаротушение", test_outdoor_water),
                       ("PPM-114: запись", test_outdoor_record),
                       ("KR-066: огнезащита и антикоррозия", test_steel_protection),
                       ("KR-066: запись", test_steel_record),
                       ("PPM-107: класс отделки", test_finish_classes),
                       ("PPM-107: запись", test_finish_record)):
        print(name)
        ok &= test()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
