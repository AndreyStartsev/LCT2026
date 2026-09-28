"""Состав и ёмкость АПС: черновик IOS5-080 (#190).

  python tests/test_alarm_capacity.py

Решения специалиста: ёмкость АПС — число адресных устройств; объединение ЗКПС в РД при том же числе
извещателей — не нарушение; ЗКПС, описанные только текстом, не сравниваются. Строки — из
спецификаций и структурных схем ДОО, Тюменской и Алтуфьевского.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import detectors as det, matrix_rules  # noqa: E402

CATALOG = {"IOS5-080": {"parameter_id": 80, "criticality": "Критическое",
                        "parameter_name": "Состав и емкость систем пожарной сигнализации (АПС)"}}
DOO = ("1.3 Прибор приемно-контрольный и управления охранно-пожарный R3-Рубеж-2ОП Рубеж шт. 2 3 ПС 2, ППА 1 1.4 "
       "Контроллер адресных устройств R3-РУБЕЖ-КАУ2 Рубеж шт. 2 ПС 1, ППА 1 1.5 Блок индикации и управления "
       "R3-Рубеж-БИУ Рубеж шт. 2 1.7 Адресная метка АМ-1-R3 Рубеж шт. 5 1.8 Адресный релейный модуль РМ-4-R3 Рубеж "
       "шт. 10 1.11 Модуль управления клапаном дымоудаления МДУ-1С прот.R3 Рубеж шт. 126 129 1.12 Извещатель "
       "пожарный дымовой оптико-электронный адресно-аналоговый ИП 212-64-R3 W1.02 Рубеж шт. 287 289 для монтажа")


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def parsing():
    got = [(r["value"], r["raw"]) for r in det.device_rows(DOO)]
    ok = check("адресные устройства: метки, модули, МДУ, извещатели; приборы, контроллер и блок индикации — нет",
               got == [(5, "шт. 5"), (10, "шт. 10"), (129, "шт. 126 129"), (289, "шт. 287 289")], str(got))
    ok &= check("охранные адресные устройства не считаются",
                det.device_rows("Извещатель охранный магнитоконтактный адресный С2000-СМК шт 8 "
                                "Извещатель оптико-электронный объемный адресный шт. 77") == [])
    ok &= check("подпись «(12шт.)» на структурной схеме — не строка спецификации",
                det.device_rows("а ППА ) ИЗ1 1ИЗ1.250 (12шт.) ИЗ1 1ИЗ1.250 МДУ R3.2ОП(ППА)-1 (3шт.)") == [])
    ok &= check("метки ЗКПС: «ЗКПС_ду1» и «ЗКПС ду1» — одна метка, три и больше на странице",
                det.zones("ЗКПС ду1 ЗКПС_ду1 ЗКПС0.1 ЗКПС 1.6") == ["0.1", "1.6", "ду1"])
    ok &= check("ЗКПС, названные только текстом, не берутся",
                det.zones("объект условно делится на отдельные ЗКПС 1 и ЗКПС 2") == [])
    return ok


def cand(stage, form, value, file_id, page, key=det.DEVICE_KEY):
    return {"stage": stage, "form": form, "key": key if form != "zone" else "ЗКПС", "value": value,
            "raw": f"{value}", "snippet": f"{file_id} с.{page}", "file_id": file_id, "page": page,
            "document": f"{file_id}.pdf", "location": key}


def build(cands):
    rule = matrix_rules.load_provisional(5)["parameters"]["IOS5-080"]
    found = {st: [c for c in cands if c["stage"] == st] for st in ("PD", "RD")}
    return matrix_rules.alarm_findings("OBJ", "IOS5-080", rule, found, CATALOG)


def fire(stage, file_id):
    return cand(stage, "detector", 1, file_id, 1, key="дымовой")


def findings():
    [f] = build([cand("PD", "device", 460, "P", 46), fire("PD", "P"), cand("RD", "device", 400, "R", 69), fire("RD", "R")])
    ok = check("адресных устройств в РД меньше на 13 % — нарушение",
               f["violation_label"] == "VIOLATION_PRESENT" and f["comparison_result"] == "COUNT_MISMATCH"
               and f["extraction"]["detail"] == "адресных устройств в РД 400 против 460 в ПД — меньше на 13 %, допуск 5 %",
               f["extraction"]["detail"])
    zones_pd = [cand("PD", "zone", z, "P", 25) for z in ("1.1", "1.2", "1.3")]
    zones_rd = [cand("RD", "zone", z, "R", 7) for z in ("1.1", "1.2")]
    [f] = build([cand("PD", "device", 460, "P", 46), fire("PD", "P"), cand("RD", "device", 470, "R", 69), fire("RD", "R")]
                + zones_pd + zones_rd)
    ok &= check("ЗКПС объединены при том же числе устройств — «нарушения нет», зона без пары названа",
                f["violation_label"] == "NO_VIOLATION" and "ЗКПС проекта без пары в РД: 1.3" in f["extraction"]["detail"]
                and "не нарушение" in f["extraction"]["detail"], f["extraction"]["detail"])
    [f] = build(zones_pd + [cand("RD", "zone", z, "R", 7) for z in ("1.1", "1.2", "1.3")]
                + [cand("RD", "device", 1039, "R", 69), fire("RD", "R")])
    ok &= check("ДОО: в ПД только схема с ЗКПС — «сравнение невозможно», зоны те же",
                f["violation_label"] == "COMPARISON_IMPOSSIBLE"
                and f["extraction"]["detail"] == "число адресных устройств в проектной стадии не названо; ЗКПС в ПД и РД "
                                                 "одни и те же — 3", f["extraction"]["detail"])
    ok &= check("значения стадий: адресные устройства и число ЗКПС",
                f["pd_value"] == "ЗКПС 3" and f["rd_value"] == "адресных устройств 1039; ЗКПС 3")
    [f] = build([cand("PD", "device", 900, "P", 38), cand("PD", "device", 400, "P2", 40), fire("PD", "P2")])
    ok &= check("том без пожарных извещателей (охрана) в ёмкость не идёт",
                f["pd_value"] == "адресных устройств 400", f["pd_value"])
    ok &= check("ничего не названо — записи нет", build([]) == [])
    return ok


def pipeline_path():
    rule = matrix_rules.load_provisional(5)["parameters"]["IOS5-080"]
    ps = {"stage": "RD", "section": "SS", "mark": "ПС", "relative_path": "ПС сборка.pdf"}
    got = matrix_rules.extract(rule, DOO, doc=ps)
    forms = sorted({c["form"] for c in got})
    ok = check("разбор страницы: адресные устройства и пожарные извещатели — кандидаты своего вида",
               forms == ["detector", "device"], str(forms))
    ios5 = {"stage": "PD", "section": "OTHER", "mark": "ИОС5.4", "relative_path": "ИОС5.4.pdf"}
    ok &= check("ИОС5 узнаётся по обозначению и без раздела СС",
                bool(matrix_rules.extract(rule, "ЗКПС ду1 ЗКПС ду2 ЗКПС 0.1", doc=ios5)))
    ok &= check("черновик в очереди ИОС, прод-правило не реализовано",
                rule.get("provisional") is True
                and not matrix_rules.load_rules(matrix_rules.QUEUES[5])["parameters"]["IOS5-080"].get("implemented"))
    return ok


def main():
    ok = parsing()
    ok &= findings()
    ok &= pipeline_path()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
