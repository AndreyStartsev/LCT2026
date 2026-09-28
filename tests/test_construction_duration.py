"""Срок строительства: ПОС против ООС и ППР — черновик POS-082 (#187).

  python tests/test_construction_duration.py

ППР в пакетах объектов нет, поэтому сравнивается срок внутри проектной документации: ООС считает
выбросы, стоки и отходы на срок строительства и повторяет его из ПОС. ООС, который ни разу не
называет срок ПОС, — гипотеза. Фразы — из ПОС и ООС открытых объектов: Тюменская, Новослободская,
Речников, Октябрьская, Алтуфьевское, ДОО, Полярная 16.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import durations, matrix_rules, protocol  # noqa: E402

CATALOG = {"POS-082": {"parameter_id": 82, "criticality": "Существенное",
                       "parameter_name": "Продолжительность этапов строительства (Календарный график)"}}


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def values(text, key=durations.TOTAL_KEY):
    return [s["value"] for s in durations.statements(text) if s["key"] == key]


def phrases():
    ok = check("ПОС Тюменской: принятый срок, а не норма аналога из таблицы",
               values("табл. №2, п.2.4, об- щая продолжительность строительства общеобразовательной школы 3-4 этажа, "
                      "стены - моно- литные, площадью 8800м2, равна 9,6 мес. Принимаем общую продолжительность "
                      "строительства объекта равной 10,8 месяца, в том числе 1,0 мес. подготовительного периода.")
               == [10.8])
    ok &= check("подготовительный период — в хвосте фразы о сроке",
                values("Принимаем общую продолжительность строительства объекта равной 10,8 месяца, в том числе "
                       "1,0 мес. подготовительного периода.", durations.PREP_KEY) == [1.0])
    ok &= check("директивный срок с адресом объекта между словами и числом (ПОС Новослободской)",
                values("Согласно заданию на проектирование, директивный срок строительства объекта: «Жилой дом», "
                       "расположенный по адресу: г. Москва, ул. Новослободская, земельный участок с кадастровым "
                       "номером № 77:01:0004009:3829, составит 60 60 60 60 месяцев.") == [60])
    ok &= check("«в том числе месяц подготовительной работы» — один месяц",
                values("директивный срок строительства объекта составит 60 месяцев, в том числе месяц "
                       "подготовительной работы", durations.PREP_KEY) == [1.0])
    ok &= check("шапка календарного плана — не срок",
                values("Продолжительность строительства, мес Работы подготовительного периода 1 1 2 3 4 5 6 7 8 9 10 "
                       "11 12 1 2 3 4 5 6 7 8 9 10 11 12 1 год 2 год 1 2 3") == [])
    ok &= check("расчёт части по нормам — не срок (сети ПОС2 Речникова)",
                values("Продолжительность строительства с учетом интерполяции составит: Т=2+2,5*0,095= 2,475=2,24 "
                       "месяца. Продолжительность строительства на единицу прироста длины прокладки составит: "
                       "(2,5-2)/(0,3-0,1)=2,5 мес.") == [])
    ok &= check("годы — в месяцах, подготовительный период из оборота «из них»",
                values("исходя из календарного срока строительства 3 года, из них 0,5 года – подготовительный период")
                == [36] and values("календарного срока строительства 3 года, из них 0,5 года – подготовительный "
                                   "период", durations.PREP_KEY) == [6])
    ok &= check("«Тобщ = … = 27 мес.» — последнее число формулы",
                values("С учетом совмещения части работ К=0,5 Тобщ.=14 мес. +10мес. +3 мес. (демон.) =27 мес.") == [27])
    ok &= check("«в срок, равный 27 месяцам»",
                values("Проектом предусматривается строительство объекта согласно календарному плану в срок, равный "
                       "27 месяцам.") == [27])
    ok &= check("срок одного вида работ — не срок строительства",
                values("Общая продолжительность демонтажных работ составляет – 3,0 мес. Продолжительность "
                       "асфальтобетонных работ составит не более 1 месяца. Продолжительность работы башенного крана: "
                       "19,0 мес.") == [])
    ok &= check("скан ООС: курсив распознан латиницей («cmpoumenbcmba», «6 mom числе», «nepuod»)",
                values("Продолжительность cmpoumenbcmba составит 10,5 месяцев, 6 mom числе подготовительный nepuod 2 "
                       "месяцо.") == [10.5]
                and values("Продолжительность cmpoumenbcmba составит 10,5 месяцев, 6 mom числе подготовительный "
                           "nepuod 2 месяцо.", durations.PREP_KEY) == [2.0])
    ok &= check("дни не сравниваются: «671 дня» не срок в месяцах",
                values("общая продолжительность строительства составит 671 дня. В целях") == [])
    ok &= check("нормы и климат — не срок",
                values("В соответствии со СНиП 1.04.03-85* продолжительность строительства жилого здания определяется "
                       "с прибавлением 0,5 мес. Продолжительность неблагоприятного периода – с 20 октября по 5 мая "
                       "(6.5 месяцев).") == [])
    return ok


def parts():
    doc = lambda stage, path, mark=None, section=None: {"stage": stage, "relative_path": path, "mark": mark,  # noqa: E731
                                                          "section": section}
    cases = [(doc("PD", "ПД/6 Проект организации строительства/V2_01-05-06-01-17_Том 6.1.pdf", "ПОС6.1", "POS"), "ПОС"),
             (doc("PD", "ПД/6 Проект организации строительства/V2_01-05-06-02-03_ПОС6.2_Водопонижение.pdf", "ПОС6.2",
                  "POS"), None),
             (doc("PD", "23.009-ПОС2 (4).pdf", "ПОС2", "POS"), None),
             (doc("PD", "НВС-2025.03-7.1-ПОС1.pdf", "ПОС1", "POS"), "ПОС"),
             (doc("PD", "06 Раздел ПД 6 ПОС изм.1_05.pdf", "ПОС", "POS"), "ПОС"),
             (doc("PD", "ПД/8 Перечень мероприятий по охране окружающей среды/V2_01-08-00-02-03_том 8.2.pdf"), "ООС"),
             (doc("PD", "01-07-22-14-П-ООС3.pdf", "ООС3", "OTHER"), "ООС"),
             (doc("PD", "АР/Том 3.pdf", "АР", "AR"), None),
             (doc("RD", "РД/ППР на возведение каркаса.pdf"), "ППР"),
             (doc("RD", "РД/КЖ1.pdf", "КЖ", "KR"), None),
             (doc("ID", "ИД/ППР.pdf"), None)]
    bad = [f"{d['relative_path']}: {durations.part_of(d)} вместо {want}" for d, want in cases
           if durations.part_of(d) != want]
    return check("раздел документа: основная книга ПОС, все книги ООС, ППР рабочей стадии", not bad, "; ".join(bad))


def cand(part, key, value, raw, file_id, page, strong=True, recognized=False):
    stage = "RD" if part == "ППР" else "PD"
    c = {"key": key, "value": value, "raw": raw, "strong": strong, "snippet": f"{file_id} с.{page}: {raw}",
         "part": part, "location": key, "columns": [raw], "label": key, "stage": stage, "file_id": file_id,
         "page": page, "document": f"{file_id}.pdf"}
    if recognized:
        c["text_source"] = "RECOGNIZED"
    return c


def build(cands):
    rule = matrix_rules.load_provisional(4)["parameters"]["POS-082"]
    found = {"PD": [c for c in cands if c["stage"] == "PD"], "RD": [c for c in cands if c["stage"] == "RD"]}
    return matrix_rules.duration_findings("OBJ", "POS-082", rule, found, CATALOG)


def findings():
    T, P = durations.TOTAL_KEY, durations.PREP_KEY
    [f] = build([cand("ПОС", T, 12.0, "12 мес.", "POS", 36), cand("ПОС", P, 2.0, "2 мес.", "POS", 36),
                 cand("ООС", T, 10.5, "10,5 месяцев", "OOS", 15, strong=False, recognized=True),
                 cand("ООС", P, 2.0, "2 месяцо", "OOS", 15, strong=False, recognized=True)])
    ok = check("ООС не называет срок ПОС — гипотеза, в сдачу только решением инспектора",
               f["violation_label"] == "VIOLATION_PRESENT" and f["finding_status"] == "SUSPICION"
               and f["for_submission"] is False and f["needs_expert"] is True, f["extraction"]["detail"])
    ok &= check("в пояснении оба срока, подготовительный период совпал и не упомянут",
                f["extraction"]["detail"].startswith("срок строительства: ПОС — 12 мес., ООС — 10,5 мес.")
                and "подготовительный" not in f["extraction"]["detail"], f["extraction"]["detail"])
    ok &= check("значение ПД — обе стороны, РД (ППР) нет",
                f["pd_value"] == "ПОС: срок 12 мес., подготовительный период 2 мес.; ООС: срок 10,5 мес., "
                                 "подготовительный период 2 мес." and f["rd_value"] is None, f["pd_value"])
    ok &= check("доказательства — страница ПОС и страница ООС",
                [(e["file_id"], e["pdf_page_number"]) for e in f["evidence"]] == [("POS", 36), ("OOS", 15)])
    ok &= check("срок ООС прочитан распознаванием — это видно в записи",
                f["extraction"]["pd"].get("text_source") == "RECOGNIZED")

    [f] = build([cand("ПОС", T, 36.0, "36 мес", "POS", 59), cand("ПОС", P, 1.0, "1 мес.", "POS", 59),
                 cand("ООС", T, 36.0, "36 месяцев", "OOS1", 199), cand("ООС", T, 36.0, "3 года", "OOS3", 20),
                 cand("ООС", P, 6.0, "0,5 года", "OOS3", 20)])
    ok &= check("расходится только подготовительный период — гипотеза с доводом «средней» уверенности",
                f["violation_label"] == "VIOLATION_PRESENT"
                and f["extraction"]["detail"].startswith("подготовительный период: ПОС — 1 мес., ООС — 6 мес. (0,5 года)")
                and "расходится только подготовительный период" in f["extraction"]["confidence"]["medium"][0],
                f["extraction"]["detail"])
    ok &= check("доказательства — страницы, на которых стоит решение: ООС с подготовительным периодом",
                ("OOS3", 20) in [(e["file_id"], e["pdf_page_number"]) for e in f["evidence"]]
                and ("OOS1", 199) not in [(e["file_id"], e["pdf_page_number"]) for e in f["evidence"]])

    [f] = build([cand("ПОС", T, 24.8, "24,8 месяца", "POS", 68),
                 cand("ПОС", T, 21.3, "21,3 месяца", "POS", 67, strong=False),
                 cand("ООС", T, 24.8, "24,8 мес", "OOS", 13, strong=False),
                 cand("ООС", T, 28.4, "28,4 месяца", "OOS", 14, strong=False),
                 cand("ООС", T, 2.5, "2,5 месяца", "OOS", 15, strong=False)])
    ok &= check("ООС называет срок ПОС хотя бы раз — расхождения нет; ППР нет — «сравнение невозможно»",
                f["violation_label"] == "COMPARISON_IMPOSSIBLE"
                and f["extraction"]["detail"] == "проекта производства работ в пакете нет; ПОС и ООС называют один "
                                                 "срок строительства — 24,8 мес.", f["extraction"]["detail"])
    ok &= check("срок части объекта в ПОС при сильной фразе в том же документе не берётся",
                "21,3" not in f["pd_value"], f["pd_value"])
    ok &= check("доказательства — только страницы с общим сроком",
                [(e["file_id"], e["pdf_page_number"]) for e in f["evidence"]] == [("POS", 68), ("OOS", 13)])

    [f] = build([cand("ПОС", T, 24.0, "24 мес.", "POS", 10), cand("ППР", T, 27.0, "27 мес.", "PPR", 3)])
    ok &= check("ППР в пакете есть и его срок больше ПОС более чем на 10 % — нарушение",
                f["violation_label"] == "VIOLATION_PRESENT"
                and f["extraction"]["detail"] == "срок строительства в ППР — 27 мес., в ПОС — 24 мес.: больше на 12 %"
                and f["rd_value"] == "ППР: срок 27 мес.", f["extraction"]["detail"])
    [f] = build([cand("ПОС", T, 24.0, "24 мес.", "POS", 10), cand("ППР", T, 26.0, "26 мес.", "PPR", 3)])
    ok &= check("срок ППР в пределах 10 % — «нарушения нет»", f["violation_label"] == "NO_VIOLATION",
                f["extraction"]["detail"])
    [f] = build([cand("ПОС", T, 22.0, "22 месяца", "POS", 54), cand("ООС", T, 22.0, "22,0 месяцев", "OOS", 83)])
    ok &= check("«22 месяца» и «22,0 месяцев» — один срок", f["violation_label"] == "COMPARISON_IMPOSSIBLE")
    [f] = build([cand("ПОС", T, 60.0, "60 месяцев", "POS", 71)])
    ok &= check("срок только в ПОС — «сравнение невозможно», причина названа",
                f["violation_label"] == "COMPARISON_IMPOSSIBLE" and "в ООС срок не найден" in f["extraction"]["detail"])
    ok &= check("срока нет ни в одном разделе — записи нет", build([]) == [])
    return ok


def pipeline_path():
    rule = matrix_rules.load_provisional(4)["parameters"]["POS-082"]
    text = ("19.1 Заказчиком принят директивный срок строительства, который составляет 36 мес, включая "
            "подготовительный период 1 мес.")
    pos = {"stage": "PD", "relative_path": "ПД/01-07_22-14-П-ПОС1.pdf", "mark": "ПОС1", "section": "POS"}
    ar = {"stage": "PD", "relative_path": "ПД/01-07-22-14-П-АР.pdf", "mark": "АР", "section": "AR"}
    got = matrix_rules.extract(rule, text, doc=pos)
    ok = check("разбор страницы: раздел и ключ идут в кандидата",
               [(c["part"], c["location"], c["value"]) for c in got]
               == [("ПОС", durations.TOTAL_KEY, 36.0), ("ПОС", durations.PREP_KEY, 1.0)], str(got)[:200])
    ok &= check("в томах других разделов срок не ищется", matrix_rules.extract(rule, text, doc=ar) == [])
    ok &= check("черновик в очереди ПОС, у прод-правила пометка для инспектора осталась",
                rule.get("provisional") is True and rule["kind"] == "construction_duration"
                and not matrix_rules.load_rules(matrix_rules.QUEUES[4])["parameters"]["POS-082"].get("implemented"))
    # на дашборде клетка — «гипотеза», а не «не проверено»
    marked = matrix_rules.mark_provisional([{"finding_id": "OBJ::POS-082", "parameter_code": "POS-082",
                                             "violation_label": "VIOLATION_PRESENT"}])
    rules4 = matrix_rules.load_rules(matrix_rules.QUEUES[4])
    catalog = [{"parameter_code": "POS-082", "parameter_id": 82, "parameter_name": "Продолжительность"}]
    [item] = protocol.coverage(catalog, {4: rules4}, [], {"PD"}, provisional={"POS-082": marked})
    ok &= check("покрытие: параметр проверяет черновик — клетка «гипотеза»",
                item["status"] == "HYPOTHESIS" and item["reason"] == "правило на проверке: похоже на нарушение — 1",
                json.dumps(item, ensure_ascii=False)[:200])
    return ok


def texts():
    """Тексты записи — для инспектора: без внутренней кухни."""
    T = durations.TOTAL_KEY
    said = []
    for cands in ([cand("ПОС", T, 12.0, "12 мес.", "P", 1), cand("ООС", T, 10.5, "10,5 мес.", "O", 1)],
                  [cand("ПОС", T, 12.0, "12 мес.", "P", 1)], [cand("ООС", T, 12.0, "12 мес.", "O", 1)]):
        f = build(cands)[0]
        said += [f["extraction"]["detail"], f.get("exclusion_reason") or ""]
        said += [x for items in (f["extraction"].get("confidence") or {}).values() for x in items]
    bad = [s for s in said if any(w in s.lower() for w in ("специалист", "р-", "#", "организатор", "корпус",
                                                            "черновик", "ещё не"))]
    return check("пояснение, причина и доводы уверенности — без внутренней кухни", not bad, "; ".join(bad))


def main():
    ok = phrases()
    ok &= parts()
    ok &= findings()
    ok &= pipeline_path()
    ok &= texts()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
