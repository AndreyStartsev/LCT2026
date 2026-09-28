"""Теплопроводность утеплителя наружных стен: черновик ZU-126 (#188).

  python tests/test_insulation_lambda.py

Решения специалиста: λ любой (по условиям А/Б или заявленный), но при разных условиях — «сравнение
невозможно»; рост до 2 % — норма, больше — нарушение; замена марки без λ — нужен эксперт. Фразы — из
АР, КР и ЭЭ открытых объектов: ДОО, Тюменская, Полярная 16, Речников.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import insulation as ins, matrix_rules  # noqa: E402

CATALOG = {"ZU-126": {"parameter_id": 126, "criticality": "Критическое",
                      "parameter_name": "Коэффициент теплопроводности (λ) утеплителя стен"}}


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def got(text):
    return [(s["key"], s["cond"], s["value"]) for s in ins.statements(text)]


def phrases():
    wall = "Наружные стены здания: "
    ok = check("цоколь ДОО: пеностекло в скобках при материале",
               got("Цоколь здания выполнен из монолитного железобетона с наружной теплоизоляцией плитами из пеностекла "
                   "(прочность на сжатие ≥0,7 Мпа, ρ≥130 кг/м.куб., λ=0,047 Вт/м.°С) толщиной 150 мм")
               == [("пеностекло", None, 0.047)])
    ok &= check("перечень слоёв ЭЭ: «λ - 0,040» и марка",
                [(s["key"], s["value"], s["product"]) for s in ins.statements(
                    wall + "- монолитная ж/б стена – 250 мм; - минераловатный утеплитель типа «Техновент Н Проф», "
                    "λ - 0,040 Вт/(м×ºС) – 100 мм; - воздушный зазор")] == [("минеральная вата", 0.04, "ТЕХНОВЕНТ Н ПРОФ")])
    ok &= check("ведомость материалов фасадов РД: марка после значения",
                [(s["value"], s["product"]) for s in ins.statements(
                    "Ведомость материалов фасадов 5 ГОСТ 32314-2012 Минераловатный утеплитель (наружный слой) "
                    "(ρ=80-100 кг/м³, предел прочности на сжатие не менее 12 кПа, λ=0,039 Вт/м°С) - 50 мм ТЕХНОВЕНТ "
                    "ОПТИМА 89,82 м³ НФС")] == [(0.039, "ТЕХНОВЕНТ ОПТИМА")])
    ok &= check("условия эксплуатации А и Б — у каждого значения своё",
                got(wall + "Плиты минераловатные Rockwool Венти БАТТС, γ=90 кг/м³, λА=0,038 Вт/(м°С), λБ=0,040 Вт/(м°С)")
                == [("минеральная вата", "А", 0.038), ("минеральная вата", "Б", 0.04)])
    ok &= check("кровля и полы — не стены (слово перед значением)",
                got("Покрытие (кровля): - монолитное ж/б перекрытие – 240 мм; - пароизоляция; - минераловатный "
                    "утеплитель типа «Техноруф Н Оптима», λ - 0,041 Вт/(м×ºС) – 100 мм") == []
                and got(wall + "Минераловатный утеплитель (ρ=99-121 кг/м³, предел прочности на сжатие не менее 25 кПа, "
                        "λ=0,044 Вт/м°С) Монолитное ж/б перекрытие - 5 мм") == [])
    ok &= check("покрытие плиты над подвалом за 400 знаков до значения — не стена",
                got("Ведомость материалов покрытия плиты над подвалом № п/п ГОСТ, ТУ Наименование Марка Ед. изм. "
                    "Кол-во Примечание 1 Бетонная брусчатка 200x100x60(h) - 0,00 см. раздел ГП 2 Сухая "
                    "цементно-песчаная смесь М 100 - 0,00 см. раздел ГП 3 ГОСТ 8267-93 Гравий фр. 5-20 мм м³ 0,79 4 "
                    "Двухслойная дренажная мембрана Planter Geo Planter Geo м² 21,96 5 ГОСТ 32310-2020 "
                    "Экструдированный пенополистирол (Прочность на сжатие при 10% линейной деформации ≥0,4 Мпа, "
                    "λ=0,034 Вт/м°С) - 100 мм Технониколь CARBON SOLID") == [])
    ok &= check("шахта на кровле («РОКФАСАД» — не слово «фасад») — не стена здания",
                got("Утеплитель ROCKWOOL РОКФАСАД или аналог Кирпичная стенка шахты +49,150 Металлический кровельный "
                    "колпак над шахтой Термовкладыш из утеплителя ТЕХНОНИКОЛЬ XPS CARBON PROF (или аналог) прочностью "
                    "на сжатие не менее 250 кПа с теплопроводностью не более 0.036 Вт/(м*К) - 40 мм") == [])
    ok &= check("λ кладки из ячеистого бетона и трения в трубах — не утеплитель",
                got(wall + "Коэффициент теплопроводности кладки из блоков из ячеистого бетона λ = 0,14") == []
                and got("коэффициент гидравлического трения λ = 0,025 трубопровод") == [])
    ok &= check("марки: серия без производителя узнаётся по серии; серии кровли — не стены",
                ins.product_of("минераловатный утеплитель Венти БАТТС Н плиты") == ("ROCKWOOL", "ВЕНТИ БАТТС Н")
                and ins.product_of("ТЕХНОВЕНТ СТАНДАРТ, плотностью 80 кг/м3") == ("ТЕХНОНИКОЛЬ", "ТЕХНОВЕНТ СТАНДАРТ")
                and ins.products("Кровля: утеплитель Техноруф Н Экстра") == [])
    return ok


def comparisons():
    by = lambda rows: ins.by_cond([{"key": k, "cond": c, "value": v} for k, c, v in rows])  # noqa: E731
    worse, ok_, other = ins.compare(by([("пеностекло", None, 0.047)]), by([("пеностекло", None, 0.048)]))
    ok = check("0,047 → 0,048: +2 %, в допуске (ДОО, цоколь)", not worse and ok_[0][4] == 2, str(ok_))
    worse, _ok, _other = ins.compare(by([("минеральная вата", "Б", 0.040)]), by([("минеральная вата", "Б", 0.042)]))
    ok &= check("0,040 → 0,042: +5 % — больше допуска", worse and worse[0][4] == 5, str(worse))
    worse, ok_, other = ins.compare(by([("минеральная вата", "А", 0.038), ("минеральная вата", "Б", 0.040)]),
                                    by([("минеральная вата", None, 0.039)]))
    ok &= check("λА/λБ против заявленного — разные условия, не нарушение", other and not worse and not ok_, str(other))
    return ok


def cand(stage, form, key, value, file_id, page, cond=None, maker=None, product=None, snippet=None):
    raw = product if form == "product" else f"λ={value}"
    return {"stage": stage, "form": form, "key": key, "value": product if form == "product" else value, "cond": cond,
            "maker": maker, "product": product, "raw": raw, "snippet": snippet or f"{file_id} с.{page}: {raw}",
            "file_id": file_id, "page": page, "document": f"{file_id}.pdf",
            "location": f"{'λ' if form == 'lambda' else 'марка'}: {key}"}


def build(cands):
    rule = matrix_rules.load_provisional(4)["parameters"]["ZU-126"]
    found = {st: [c for c in cands if c["stage"] == st] for st in ("PD", "RD")}
    return matrix_rules.lambda_findings("OBJ", "ZU-126", rule, found, CATALOG)


def findings():
    mw = "минеральная вата"
    [f] = build([cand("PD", "lambda", mw, 0.040, "PD1", 5, "Б"), cand("RD", "lambda", mw, 0.043, "RD1", 20, "Б")])
    ok = check("λ в РД хуже проектного больше чем на 2 % — нарушение",
               f["violation_label"] == "VIOLATION_PRESENT" and f["comparison_result"] == "VALUE_MISMATCH"
               and f["extraction"]["detail"] == "минеральная вата (условия Б): λ в РД 0,043 против 0,040 в ПД — "
                                                "больше на 8 %, допуск 2 %", f["extraction"]["detail"])
    [f] = build([cand("PD", "lambda", "пеностекло", 0.047, "PD1", 28), cand("RD", "lambda", "пеностекло", 0.048, "RD1", 20)])
    ok &= check("в допуске — «нарушения нет», разница названа",
                f["violation_label"] == "NO_VIOLATION" and f["comparison_result"] == "NON_TRIGGERING_DIFFERENCE_NO_DECREASE"
                and "пеностекло 0,048 против 0,047" in f["extraction"]["detail"], f["extraction"]["detail"])
    [f] = build([cand("PD", "lambda", mw, 0.038, "PD1", 18, "А"), cand("RD", "lambda", mw, 0.039, "RD1", 3)])
    ok &= check("разные условия — «сравнение невозможно» с условиями стадий",
                f["violation_label"] == "COMPARISON_IMPOSSIBLE"
                and "ПД: условия А, РД: заявленный" in f["extraction"]["detail"], f["extraction"]["detail"])
    [f] = build([cand("PD", "lambda", mw, 0.038, "PD1", 18, "А")])
    ok &= check("λ только в ПД — «сравнение невозможно»: в РД не назван",
                f["violation_label"] == "COMPARISON_IMPOSSIBLE"
                and f["extraction"]["detail"] == "λ утеплителя стен в рабочей стадии не назван")
    rows = [cand("PD", "product", mw, None, "PD1", 16, maker="ROCKWOOL", product="ВЕНТИ БАТТС",
                 snippet="«Rockwool» Венти БАТТС плиты плотностью 90 кг/м³ (или аналог)"),
            cand("RD", "product", mw, None, "RD1", 3, maker="ROCKWOOL", product="ВЕНТИ БАТТС"),
            cand("RD", "product", mw, None, "RD2", 6, maker="ТЕХНОНИКОЛЬ", product="ТЕХНОВЕНТ СТАНДАРТ")]
    [f] = build(rows)
    ok &= check("другой производитель минеральной ваты в РД без λ — гипотеза, решает эксперт",
                f["violation_label"] == "VIOLATION_PRESENT" and f["finding_status"] == "SUSPICION"
                and f["for_submission"] is False and f["needs_expert"] is True
                and f["extraction"]["detail"] == "минеральная вата: в РД ТЕХНОНИКОЛЬ: ТЕХНОВЕНТ СТАНДАРТ, в ПД — "
                                                 "ROCKWOOL: ВЕНТИ БАТТС; λ нового утеплителя в документах нет",
                f["extraction"]["detail"])
    ok &= check("доводы уверенности: λ нет — «низкая», «или аналог» в проекте — «средняя»",
                f["extraction"]["confidence"]["low"] and "или аналог" in f["extraction"]["confidence"]["medium"][0])
    ok &= check("доказательства замены — страница ПД со старой маркой и страница РД с новой",
                {(e["stage"], e["file_id"]) for e in f["evidence"]} == {("PD", "PD1"), ("RD", "RD2")},
                str([(e["stage"], e["file_id"]) for e in f["evidence"]]))
    rows[-1] = cand("RD", "product", "экструзионный пенополистирол", None, "RD2", 6, maker="ТЕХНОНИКОЛЬ",
                    product="CARBON SOLID")
    rows.append(cand("PD", "product", "экструзионный пенополистирол", None, "PD1", 23, maker="ПЕНОПЛЭКС",
                     product="ПЕНОПЛЭКС ФУНДАМЕНТ"))
    ok &= check("замена ищется только у минеральной ваты: пенополистирол фундамента и покрытия — разные слои",
                build(rows) == [])
    [f] = build([cand("PD", "product", mw, None, "PD1", 16, maker="ROCKWOOL", product="ВЕНТИ БАТТС"),
                 cand("RD", "product", mw, None, "RD2", 6, maker="ТЕХНОНИКОЛЬ", product="ТЕХНОВЕНТ ОПТИМА"),
                 cand("RD", "lambda", mw, 0.039, "RD2", 6, maker="ТЕХНОНИКОЛЬ", product="ТЕХНОВЕНТ ОПТИМА"),
                 cand("PD", "lambda", mw, 0.039, "PD1", 16)])
    ok &= check("у нового производителя λ в РД есть — решает сравнение λ, а не замена марки",
                f["violation_label"] == "NO_VIOLATION", f["extraction"]["detail"])
    ok &= check("ничего не названо — записи нет", build([]) == [])
    return ok


def pipeline_path():
    rule = matrix_rules.load_provisional(4)["parameters"]["ZU-126"]
    text = ("Наружные стены: теплоизоляционные плиты из пеностекла (прочность на сжатие ≥1,0 Мпа, ρ≥120 кг/м.куб., "
            "λ=0,048 Вт/м.°С) - 150 мм ИЗОСТЕК 13,65 м³ Отделка цоколя")
    ar = {"stage": "RD", "section": "AR", "mark": "АР2", "relative_path": "РД/АР2.pdf"}
    got_ = matrix_rules.extract(rule, text, doc=ar)
    ok = check("разбор страницы: λ и марка идут кандидатами со своим видом и «местом»",
               sorted((c["form"], c["location"]) for c in got_)
               == [("lambda", "λ: пеностекло"), ("product", "марка: пеностекло")], str(got_)[:200])
    ok &= check("в томах других разделов λ не ищется",
                matrix_rules.extract(rule, text, doc={"stage": "RD", "section": "OV", "relative_path": "ОВ.pdf"}) == []
                and matrix_rules.extract(rule, text, doc={"stage": "PD", "section": "OTHER", "mark": "ЭЭ",
                                                          "relative_path": "ЭЭ.pdf"}) != [])
    ok &= check("черновик в очереди ЗУ, прод-правило не реализовано",
                rule.get("provisional") is True
                and not matrix_rules.load_rules(matrix_rules.QUEUES[4])["parameters"]["ZU-126"].get("implemented"))
    return ok


def main():
    ok = phrases()
    ok &= comparisons()
    ok &= findings()
    ok &= pipeline_path()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
