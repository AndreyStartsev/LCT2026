"""Правила шестого круга: трубы, цвет фасада, уклоны, объём бетона (#172, Р-111, перенос в прод — Р-112).

  python tests/test_round6_drafts.py

Выдержки — из текстов открытых объектов: ИОС2/ВК Полярной 16, школы и Тюменской, ИОС3 Полярной 16,
фасады АР Алтуфьевского, ПЗУ и ГП ДОО и Речникова, КР и ограждение котлована Новослободской.
"""
import collections
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import facade_colors as fc  # noqa: E402
from pipeline import matrix_rules as mr  # noqa: E402
from pipeline import pipe_materials as pm  # noqa: E402
from pipeline import slopes as sl  # noqa: E402
from pipeline import takeoffs as to  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def keyed(cands):
    out = collections.defaultdict(set)
    for c in cands:
        out[c["key"]].add(c["value"])
    return dict(out)


P16_PD = ("Дата Формат А4 - магистрали и стояки из стальных водогазопроводных оцинкованных труб по ГОСТ 3262-75* на "
          "муфтовых соединениях типа «грувлок» диаметрами 25 мм и больше")
SOSH_RD = ("10. Магистрали и стояки систем водоснабжения предусмотрены из стальных водогазопроводных оцинкованных труб по "
           "ГОСТ 3262-75* (D≤50мм.) и стальных электросварных прямошовных оцинкованных труб по ГОСТ 10704-91 (D>50мм.). "
           "Соединение труб предусматривается на резьбе. 11. Разводка по сан.узлам предусмотрена из труб из "
           "полипропиленовых труб PP-R с гибкой подводкой к санитарно-техническим приборам.")
TYUM_PD = ("Трубопроводы запроектированы из стальных оцинкованных водогазопроводных труб по ГОСТ 3262-75 (магистрали, "
           "стояки) и полипропиленовых сварных труб PN20 (подводки к приборам).")
SUPPLY = ("Подводки (от водоразборных стояков) к санитарным приборам хозяйственно- питьевого водопровода запроектированы "
          "из полимерных труб")
NORM = "СП 40-101-96 «Проектирование и монтаж трубопроводов из полипропилена «Рандом сополимер»» Холодное водоснабжение"
P16_SEWER = ("- стояки выше перекрытия первого этажа, фановая часть стояков с выходом на кровлю – раструбными "
             "полипропиленовыми трубопроводами с пониженным уровнем шума диаметрами 110 мм; - магистральные трубопроводы "
             "в подвале, стояки ниже перекрытия первого этажа – чугунными безраструбными трубопроводами SML; - выпуски "
             "прокладываются раструбными чугунными трубами ВЧШГ.")
SPEC_ROW = "Канализационный затвор ТП-85.100-КЗЭ Труба из высокопрочного чугуна с шаровидным графитом (ВЧШГ) на фиксированном"

ALT_PD = ("В отделке фасадов применяются материалы: • Цоколь - керамогранитные плиты Тан Браун RAL 7024 монтируемые на "
          "бетонную поверхность; • Оконные заполнения - ПВХ/металл RAL 9006, стекло закаленное - прозрачное; Стены: • "
          "Сэндвич панели RAL 9006 \"ТЕХНОСТИЛЬ\"; • Двери - металл/дерево с окраской RAL 9006;")
ALT_RD = ("Фасад в осях 1*-14*/А* М 1:100 п/п Элемент фасада Вид отделки и материал 1 Наружные стены - трехслойная "
          "сэндвич-панель полной заводской готовности с покрытием RAL 9006 4 Цоколь - керамогранитная плитка RAL 7024 7 "
          "Оконные переплеты - алюминиевый профиль по типу \"Татпроф\" RAL 7024 9 Козырьки - Стеклянные на металлическом "
          "каркасе RAL 9006")


def main():
    ok = True
    # ---- водопровод, IOS2-072
    got = keyed(pm.materials(P16_PD, pm.WATER))
    ok &= check("«магистрали и стояки из стальных оцинкованных труб» — металл на обоих участках",
                got == {"магистрали": {pm.METAL}, "стояки": {pm.METAL}}, str(got))
    got = keyed(pm.materials(SOSH_RD, pm.WATER))
    ok &= check("«электросварных» — не чужая фраза об электроснабжении; разводка PP-R — полимер",
                got.get("магистрали") == {pm.METAL} and got.get("разводка") == {pm.POLYMER}, str(got))
    got = keyed(pm.materials(TYUM_PD, pm.WATER))
    ok &= check("участки в скобках за материалом — его: (магистрали, стояки) у стали, (подводки) у полипропилена",
                got == {"магистрали": {pm.METAL}, "стояки": {pm.METAL}, "разводка": {pm.POLYMER}}, str(got))
    got = keyed(pm.materials(SUPPLY, pm.WATER))
    ok &= check("«подводки (от водоразборных стояков)» — разводка, а не стояки", got == {"разводка": {pm.POLYMER}}, str(got))
    ok &= check("ссылка на норму в кавычках — не решение", pm.materials(NORM, pm.WATER) == [])
    ok &= check("замена: металл в ПД → полимер в РД на том же участке",
                [c[0] for c in pm.changes({"магистрали": {pm.METAL}}, {"магистрали": {pm.POLYMER}})] == ["магистрали"])
    ok &= check("полимер разрешён проектом — не замена",
                pm.changes({"стояки": {pm.METAL, pm.POLYMER}}, {"стояки": {pm.POLYMER}}) == [])
    ok &= check("«система целиком» против участка другой стадии",
                pm.changes({pm.WHOLE: {pm.POLYMER}}, {"магистрали": {pm.POLYMER}}) == []
                and pm.compare_pairs({pm.WHOLE: {1}}, {"магистрали": {1}}) == [(pm.WHOLE, "магистрали")])
    ok &= check("запасной ключ — внутри подсистемы: водостоки по участкам против водостоков системой целиком",
                [c[0] for c in pm.changes({"магистрали": {pm.METAL}, "водостоки: стояки": {pm.METAL}},
                                          {"магистрали": {pm.METAL}, "водостоки: " + pm.WHOLE: {pm.POLYMER}})]
                == ["водостоки: стояки → водостоки: " + pm.WHOLE])
    # ---- канализация, IOS3-075
    got = keyed(pm.materials(P16_SEWER, pm.SEWER))
    ok &= check("канализация Полярной 16: стояки выше 1 этажа ПП, магистрали и выпуски — чугун (творительный падеж)",
                got.get("магистрали") == {pm.METAL} and got.get("выпуски") == {pm.METAL}
                and got.get("стояки") == {pm.POLYMER, pm.METAL}, str(got))
    ok &= check("строка спецификации «Труба из … чугуна» — не решение", pm.materials(SPEC_ROW, pm.SEWER) == [])
    page = ("Внутренние системы водоснабжения приняты из следующих материалов: - магистрали и стояки из стальных "
            "водогазопроводных оцинкованных труб по ГОСТ 3262-75*. Внутренние системы канализации выполняются: " + P16_SEWER)
    got = keyed(pm.materials(page, pm.WATER))
    ok &= check("канализационные стояки на том же листе ВК — не водопровод (система — последняя названная)",
                got == {"магистрали": {pm.METAL}, "стояки": {pm.METAL}}, str(got))
    storm = ("выпуски в наружную сеть дождевой канализации 6 Проектом предусматривается монтаж системы внутренних "
             "водостоков из напорных полипропиленовых труб по ТУ 2248-060-42943419-2012 (2-13 этажи)")
    got = keyed(pm.materials(storm, pm.SEWER))
    ok &= check("водостоки — свой ключ, участок из предыдущего пункта не переходит",
                got == {"водостоки: " + pm.WHOLE: {pm.POLYMER}}, str(got))
    norms = ("Перечень нормативных документов: СП 30.13330.2020 Внутренний водопровод и канализация зданий; "
             "СП 40-102-2000 Проектирование и монтаж трубопроводов систем водоснабжения и канализации из полимерных "
             "материалов. Системы внутренней канализации здания запроектированы из чугунных труб SML")
    got = keyed(pm.materials(norms, pm.SEWER))
    ok &= check("название нормы в перечне без кавычек — не решение (ДОО Полярной, РД ВК)",
                got == {pm.WHOLE: {pm.METAL}}, str(got))
    # решения специалиста шестого круга: ПВХ отдельно от ПП, переход на схеме, участок без решения в проекте
    p16_storm_pd = ("Внутренний водосток проектируются из труб следующих материалов: - горизонтальные разводки от кровельных "
                    "воронок – полипропиленовыми напорными трубопроводами диаметрами 110 мм; - стояки выше перекрытия "
                    "первого этажа – полипропиленовыми напорными трубопроводами диаметрами 160 мм; - магистральные "
                    "трубопроводы на подвале, стояки ниже перекрытия первого этажа – чугунными безраструбными "
                    "трубопроводами SML с усиливающими хомутами; - выпуски прокладываются раструбными чугунными трубами ВЧШГ.")
    p16_storm_rd = ("К2 К2 К2 К2 СтК 2-3 ∅110 СтК 2-3 ∅110 ∅110 переход ПП -НПВХ 0,025 ∅110 R R R 0,000 1 этаж +4,500 2 этаж")
    pd, rd = keyed(pm.materials(p16_storm_pd, pm.SEWER)), keyed(pm.materials(p16_storm_rd, pm.SEWER))
    ok &= check("переход ПП–НПВХ на стояке К2 — материалы водостока", rd == {"водостоки: переход": {pm.POLYMER, pm.PVC}},
                str(rd))
    ch = pm.changes(pd, rd)
    ok &= check("Полярная 16: переход на НПВХ при чугуне и ПП в проекте — замена (IOS3-075, вопрос 3)",
                [c[0] for c in ch] == ["водостоки: переход"] and "ПВХ" in ch[0][3], str(ch))
    ok &= check("переход ПП–чугун при чугуне и ПП в проекте — не замена",
                pm.changes(pd, keyed(pm.materials("К2 СтК 2-1 ∅110 Переход ПП -Чуг ∅110", pm.SEWER))) == [])
    ok &= check("переход у условно-чистых стоков К4 — не канализация К1/К2",
                pm.materials("2.4. Канализация условно-чистых стоков К4 2.4.1 Дренажный насос 2.4.17 Переход НПВХ-ВЧШГ "
                             "DN 110 Smart SML", pm.SEWER) == [])
    ok &= check("переход без названной перед ним системы (лист спецификации с середины раздела) — не берётся",
                pm.materials("2.4.16 Муфта трубопроводная соединительная жесткая DN 50 RC шт. 192 2.4.17 Переход "
                             "НПВХ-ВЧШГ DN 110 Smart SML шт. 2", pm.SEWER) == [])
    ok &= check("типовой узел с вариантами переходов — не труба системы (ДОО Полярной)",
                pm.materials("Канализация К1. Узел выпуска систем канализации с переходом Чугун-Чугун Узел выпуска систем "
                             "канализации с переходом ПП-Чугун Узел выпуска систем канализации с переходом ПВХ-Чугун",
                             pm.SEWER) == [])
    ok &= check("ПВХ вместо ПП на том же участке при чугуне в проекте — замена",
                [c[0] for c in pm.changes({"стояки": {pm.METAL, pm.POLYMER}}, {"стояки": {pm.PVC}})] == ["стояки"])
    ch = pm.changes({"магистрали": {pm.METAL}, "стояки": {pm.METAL}}, {"магистрали": {pm.METAL}, "разводка": {pm.POLYMER}})
    ok &= check("разводка, о которой проект молчит, из полимера при стальных стояках — гипотеза (IOS2-072, вопрос 2)",
                [c[0] for c in ch] == ["разводка"] and pm.UNNAMED in ch[0][3], str(ch))
    ok &= check("разводка без решения в проекте, если проект где-то назначил полимер, — не замена",
                pm.changes({"стояки": {pm.METAL}, "магистрали": {pm.POLYMER}},
                           {"стояки": {pm.METAL}, "разводка": {pm.POLYMER}}) == [])
    # ---- цвет фасада, AR-052
    pd, rd = keyed(fc.colors(ALT_PD)), keyed(fc.colors(ALT_RD))
    ok &= check("Алтуфьевское: коды по элементам фасада",
                pd.get("оконные переплёты") == {"RAL 9006"} and rd.get("оконные переплёты") == {"RAL 7024"}
                and rd.get("козырьки") == {"RAL 9006"}, f"{pd} | {rd}")
    ch = fc.changes(pd, rd)
    ok &= check("переплёты RAL 9006 → RAL 7024 — изменение, стены и цоколь совпадают",
                [(k, why) for k, _p, _r, why in ch] == [("оконные переплёты", "другой код")], str(ch))
    ok &= check("RAL и NCS не сравниваются", fc.changes({"наружные стены": {"RAL 9006"}},
                                                        {"наружные стены": {"NCS S 1502-R"}}) == [])
    ok &= check("код у клапана ОВ — не фасад", fc.colors("фасад Клапан противопожарный RAL 9003 ВЕЗА шт 1") == [])
    # ---- уклоны, SPZU-033
    got = sl.slopes("6‰ 28.11 18‰ 17.27 10‰ 12.77 150.45 Вх.")
    ok &= check("подписи уклона на плане: число с ‰ и длина участка", sorted(c["value"] for c in got) == [6, 10, 18],
                str(got))
    got = sl.slopes("Поперечные уклоны дорог приняты 10-20 ‰, продольные уклоны по проездам составляют 5‰-15‰.")
    ok &= check("диапазоны ПЗУ Алтуфьевского", keyed(got) == {sl.CROSS: {10, 20}, sl.LONG: {5, 15}}, str(keyed(got)))
    got = sl.slopes("Продольные уклоны по проездам и тротуарам составляют от 0,5% до 4,0 %.")
    ok &= check("проценты — в промилле", keyed(got) == {sl.LONG: {5, 40}}, str(keyed(got)))
    got = keyed([c for c in sl.slopes("разработаны согласно CП 59.13330.2020: - продольный уклон пути движения не "
                                      "превышает 4%; - ") if not c.get("norm")])
    ok &= check("уклон пути движения МГН — свой ключ", set(got) == {sl.LONG + " путей МГН"}, str(got))
    got = sl.slopes("продольные уклоны путей движения (пешеходных дорожек) не должны быть более 4%")
    ok &= check("требование «не должны быть более 4 %» — не значение, а предел нормы",
                keyed(got) == {sl.LONG + " путей МГН" + sl.NORM_MAX: {40}} and all(c["norm"] for c in got), str(keyed(got)))
    ok &= check("РД в диапазоне ПД — без изменений; круче — изменение",
                sl.changes({sl.LONG: {5, 25}}, {sl.LONG: {6, 18}}) == []
                and len(sl.changes({sl.LONG: {5, 25}}, {sl.LONG: {6, 49}})) == 1)
    # нормы, на которые ссылается ПД (решение специалиста шестого круга, SPZU-033, вопрос 1)
    got = keyed(sl.slopes("Проект разработан в соответствии с СП 59.13330.2020 «Доступность зданий и сооружений для МГН»"))
    ok &= check("ссылка на СП 59.13330.2020 — пределы п. 5.1.7 для путей МГН",
                got == {sl.LONG + " путей МГН" + sl.NORM_MAX: {40}, sl.CROSS + " путей МГН" + sl.NORM_RANGE: {10, 20}},
                str(got))
    mgn = sl.LONG + " путей МГН"
    ch = sl.changes({mgn + sl.NORM_MAX: {40}}, {mgn: {45}})
    ok &= check("путь МГН круче предела нормы — изменение", len(ch) == 1 and "по норме" in ch[0][3], str(ch))
    ok &= check("предел нормы «не более» — только сверху: положе не проверяется",
                sl.changes({mgn + sl.NORM_MAX: {40}}, {mgn: {5}}) == [])
    cross = sl.CROSS + " путей МГН"
    ch = sl.changes({cross + sl.NORM_RANGE: {10, 20}}, {cross: {5}})
    ok &= check("поперечный уклон положе диапазона нормы — риск застоя воды", len(ch) == 1 and "застоя" in ch[0][3], str(ch))
    ok &= check("пары: предел нормы из ПД против того же вида уклона в РД",
                sl.compare_pairs({mgn + sl.NORM_MAX: {40}, sl.LONG: {5}}, {mgn: {30}, sl.LONG: {6}})
                == [(sl.LONG, sl.LONG), (mgn + sl.NORM_MAX, mgn)])
    # ---- объём бетона, KR-067
    pd = to.takeoffs("158,90 верх Об-3 Ведомость расхода бетона для устройства обвязочной балки № Наименование Ед. изм. "
                     "Кол-во Прим. 1 Бетон тяжёлый В25 W8 F200 П4 ГОСТ 26633-2012 м³ 47,8800 Спецификация")
    rd = to.takeoffs("ГОСТ 26633-2015. 3. Объем бетона на устройство обвязочного пояса - 49,5 м3. - отметки верха")
    ok &= check("обвязочная балка ПД и обвязочный пояс РД — один элемент",
                [(c["key"], c["value"]) for c in pd] == [("обвя пояс", 47.88)] and [(c["key"], c["value"]) for c in rd]
                == [("обвя пояс", 49.5)], f"{pd} | {rd}")
    ch = to.changes(keyed(pd), keyed(rd))
    ok &= check("47,88 → 49,5 м³ — больше 2 %", len(ch) == 1 and "+3.4%" in ch[0][3], str(ch))

    # ---- запись черновика
    catalog = {"AR-052": {"parameter_id": 52, "parameter_name": "Цвет фасада", "criticality": "Существенное"}}
    rule = {"kind": "facade_colors", "compare": {"type": "keyed", "result_violation": "VALUE_MISMATCH"}, "basis": "x"}

    def cand(stage, c):
        return dict(c, file_id=stage + "1", page=1, document=f"{stage}-АР.pdf", stage=stage, columns=[c["raw"]])

    found = {"PD": [cand("PD", c) for c in fc.colors(ALT_PD)], "RD": [cand("RD", c) for c in fc.colors(ALT_RD)]}
    f = mr.set_findings("OBJ", "AR-052", rule, found, catalog)[0]
    ok &= check("запись: изменение цвета — гипотеза с доводами уверенности",
                f["violation_label"] == "VIOLATION_PRESENT" and f["for_submission"] is False
                and f["finding_status"] == "SUSPICION" and f["extraction"]["confidence"]["medium"], f["extraction"]["detail"])
    same = {"PD": found["PD"], "RD": [cand("RD", c) for c in fc.colors(ALT_PD)]}
    f = mr.set_findings("OBJ", "AR-052", rule, same, catalog)[0]
    ok &= check("те же коды — «нарушения нет»", f["violation_label"] == "NO_VIOLATION", f["extraction"]["detail"])
    f = mr.set_findings("OBJ", "AR-052", rule, {"PD": found["PD"], "RD": []}, catalog)[0]
    ok &= check("рабочей стадии нет — «сравнение невозможно»", f["violation_label"] == "COMPARISON_IMPOSSIBLE")

    # ---- перенос в очереди прода (Р-112): какое расхождение — нарушение, какое — гипотеза
    def submitted(f):
        return f["violation_label"] == "VIOLATION_PRESENT" and f.get("for_submission", True) is not False \
            and f["finding_status"] != "SUSPICION"

    catalog["IOS3-075"] = {"parameter_id": 75, "parameter_name": "Материал канализационных труб", "criticality": "Существенное"}
    sewer = {"kind": "pipe_materials", "system": "sewer", "compare": {"type": "keyed", "result_violation": "VALUE_MISMATCH"},
             "basis": "x"}
    found = {"PD": [cand("PD", c) for c in pm.materials(p16_storm_pd, pm.SEWER)],
             "RD": [cand("RD", c) for c in pm.materials(p16_storm_rd, pm.SEWER)]}
    f = mr.set_findings("OBJ", "IOS3-075", sewer, found, catalog)[0]
    ok &= check("переход ПП–НПВХ на К2 при чугуне в ПД — нарушение, идёт в сдачу (IOS3-075, вопрос 3)", submitted(f),
                f"{f['violation_label']} {f['finding_status']} {f['extraction']['detail'][:120]}")

    def one(stage, key, value, raw):
        return cand(stage, {"key": key, "value": value, "raw": raw, "snippet": raw})

    whole = {"PD": [one("PD", "водостоки: стояки", pm.METAL, "чугун")],
             "RD": [one("RD", "водостоки: " + pm.WHOLE, pm.POLYMER, "полимер")]}
    f = mr.set_findings("OBJ", "IOS3-075", sewer, whole, catalog)[0]
    ok &= check("участок против системы целиком — гипотеза, в сдачу не идёт",
                f["violation_label"] == "VIOLATION_PRESENT" and not submitted(f)
                and "в сдачу только решением инспектора" in (f.get("exclusion_reason") or ""), f.get("exclusion_reason"))
    part = {"PD": [one("PD", "стояки", pm.METAL, "чугун")], "RD": [one("RD", "стояки", pm.POLYMER, "полимер")]}
    f = mr.set_findings("OBJ", "IOS3-075", sewer, part, catalog)[0]
    ok &= check("участок целиком из другого материала — нарушение (IOS3-075, вопрос 1)", submitted(f))
    unnamed = {"PD": [one("PD", "стояки", pm.METAL, "сталь")],
               "RD": [one("RD", "стояки", pm.METAL, "сталь"), one("RD", "разводка", pm.POLYMER, "полимер")]}
    f = mr.set_findings("OBJ", "IOS3-075", dict(sewer, system="water"), unnamed, catalog)[0]
    ok &= check("участок, о котором проект молчит, — гипотеза (IOS2-072, вопрос 2)",
                f["violation_label"] == "VIOLATION_PRESENT" and not submitted(f))
    catalog["KR-067"] = {"parameter_id": 67, "parameter_name": "Объём бетона", "criticality": "Существенное"}
    concrete = {"kind": "material_takeoff", "compare": {"type": "keyed", "threshold": 0.02}, "basis": "x"}
    f = mr.set_findings("OBJ", "KR-067", concrete, {"PD": [cand("PD", c) for c in pd], "RD": [cand("RD", c) for c in rd]},
                        catalog)[0]
    ok &= check("объём бетона элемента больше 2 % — нарушение (KR-067, вопросы 1 и 2)", submitted(f), f["extraction"]["detail"])

    def violation():
        return {"violation_label": "VIOLATION_PRESENT", "finding_status": "CANDIDATE", "extraction": {}}

    f = mr.rule_hypothesis(violation(), {"hypotheses": "always", "hypothesis_reason": "довод"}, [])
    ok &= check("правило «hypotheses: always» — нарушение становится гипотезой",
                f["finding_status"] == "SUSPICION" and f["for_submission"] is False and f["exclusion_reason"] == "довод")
    when = {"hypothesis_when": {"patterns": [r"переносн\w*\s+пандус\w*"], "reason": "обоснование"}}
    f = mr.rule_hypothesis(violation(), when, [{"snippet": "порог 20 мм; предусмотрен переносной пандус"}])
    ok &= check("порог с обоснованием рядом — гипотеза (ODI-118, вопрос 1)",
                f["finding_status"] == "SUSPICION" and f["extraction"]["confidence"]["low"], str(f["extraction"]))
    f = mr.rule_hypothesis(violation(), when, [{"snippet": "порог 20 мм"}])
    ok &= check("порог без обоснования — нарушение", f["finding_status"] == "CANDIDATE" and "for_submission" not in f)

    moved = {1: ["SPZU-033"], 2: ["AR-051", "AR-052", "AR-053", "KR-067"], 3: ["ODI-118", "ODI-122"],
             5: ["IOS2-072", "IOS3-075"]}
    placed = all(c in mr.load_rules(mr.QUEUES[q])["parameters"] and c not in mr.load_provisional(q)["parameters"]
                 for q, codes in moved.items() for c in codes)
    ok &= check("девять правил шестого круга — в очередях прода, не в черновиках", placed)

    d = mr.kind_digests()
    ok &= check("у новых видов своя ветка отпечатка", all(k in d for k in mr.DRAFT_PARSERS), str(sorted(d))[:120])
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
