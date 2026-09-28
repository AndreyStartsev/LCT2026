"""Черновики «раздела РД нет» с проверкой наличия — в правилах прода (#145, Р-101).

  python tests/test_round3_presence_rules.py

ODI-115 лифт или подъёмник для МГН, ODI-120 поручни санузлов МГН, ODI-123 системы вызова и
двусторонней связи, POD-092 защита действующих сетей при сносе, POD-097 площадки для мусора.
Выдержки — из текстового слоя Полярной 25, ДОО и Полярной 16.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import matrix_rules as mr  # noqa: E402

CODES = {"3": ["ODI-115", "ODI-120", "ODI-123"], "4": ["POD-092", "POD-097"]}


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def rules():
    out = {}
    for q, codes in CODES.items():
        params = json.load(open(os.path.join(ROOT, "rules", f"matrix_queue{q}.json"), encoding="utf-8"))["parameters"]
        out.update({c: params[c] for c in codes})
    return out


def names(rule, text, stage, doc_name):
    got = mr.extract(rule, text, None, {"stage": stage, "relative_path": f"x/{doc_name}"})
    return got[0]["columns"] if got else []


def main():
    ok = True
    r = rules()
    ok &= check("пять правил реализованы, наличие — сравнение presence",
                all(x["implemented"] and x["kind"] == "feature_presence" and x["compare"]["type"] == "presence"
                    for x in r.values()))
    lift = "для перевозки инвалидов и пожарных подразделений. Лифт для МГН Q=1000кг, V=1,0м/с"
    ok &= check("ODI-115: лифт для МГН в томе ВТ", names(r["ODI-115"], lift, "RD", "04-П.СКБ-ПИР-Р-ВТ_2025-10-28 (1).pdf")
                == ["лифт или подъёмник для МГН"])
    ok &= check("ODI-115: подъёмник для пищи не в счёт", names(r["ODI-115"], "Раздаточная с подъемником для пищи",
                                                               "RD", "Р-АР1.pdf") == [])
    ok &= check("ODI-115: чужой раздел рабочей стадии не источник", names(r["ODI-115"], lift, "RD", "Р-ЭОМ.pdf") == [])
    rail = "Конструкция напольного крепления с опорой для спины и откидными поручнями, 13 шт."
    ok &= check("ODI-120: откидные поручни в ОДИ рабочей стадии",
                "откидные поручни" in names(r["ODI-120"], rail, "RD", "04-П.СКБ-ПИР-Р-ОДИ_сборка_4.pdf"))
    pd = {"columns": ["откидные поручни", "стационарные поручни"], "raw": "PRESENT", "value": 2.0}
    rd = {"columns": ["стационарные поручни"], "raw": "PRESENT", "value": 1.0}
    label, _r, detail = mr.decide(r["ODI-120"], pd, rd)
    ok &= check("ODI-120: вид поручня не указан — не нарушение, в пояснении (Р-91, п. 5)",
                label == "NO_VIOLATION" and "откидные" in detail, detail)
    call = "Проводная влагозащищенная кнопка со шнуром GC-0423B1 GETCALL шт. 13. Кнопка вызова персонала"
    ok &= check("ODI-123: кнопка вызова в АОДИ", names(r["ODI-123"], call, "RD", "0073-Р-ДОО-Д9-АОДИ.pdf") == ["кнопка вызова"])
    plates = "Песок - 100мм Плита дорожная ПДП- 170мм по оси существующих коммуникаций. Экскаватор"
    ok &= check("POD-092: плиты по оси сетей на стройгенплане",
                names(r["POD-092"], plates, "RD", "130-1222-ОК-1_Н-СГП1 изм.1.pdf") == ["защита действующих сетей"])
    ok &= check("POD-092: молниезащитная сетка — не защита сетей", names(r["POD-092"], "молниезащитная сетка кровли",
                                                                        "PD", "130-1222-ОК-1-Н-ПОС.pdf") == [])
    ok &= check("POD-097: контейнер для мусора в ПОС",
                names(r["POD-097"], "Контур проектируемого котлована контейнер для мусора", "PD", "130-1222-ОК-1-Н-ПОС.pdf")
                == ["площадка или бункер для мусора"])
    ok &= check("POD-097: помещение хранения отходов в АР — не источник",
                names(r["POD-097"], "площадка для временного хранения отходов", "RD", "Р-АР2.pdf") == [])
    ok &= check("метка наличия без единицы каталога", mr._fmt({"raw": "PRESENT", "value": 2.0}, "шт.") == "PRESENT")
    ok &= check("POD-092 и POD-097 — по применимости к сносу; у POD-092 ещё и вынос сетей (R4-Q-POD-092)",
                r["POD-092"].get("applies_if") == "demolition_networks"
                and r["POD-097"].get("applies_if") == "demolition")
    # четвёртый круг (Р-108): поручни у раковин входят в ODI-120, «без поручней» и «поручни убраны» — нет
    sink = "умывальник и унитаз с опорными поручнями; Отступ от поручня до раковины 45 мм"
    ok &= check("ODI-120: поручни у раковин — третий вид",
                "поручни у раковин" in names(r["ODI-120"], sink, "RD", "04-П.СКБ-ПИР-Р-ОДИ_сборка.pdf"))
    for text in ("Высота установки умывальника 800 мм по верхнему краю, без поручней.",
                 "Возле большой раковины поручни убраны и зашивка укорочена."):
        ok &= check(f"ODI-120: «{text[:40]}…» — не наличие",
                    "поручни у раковин" not in names(r["ODI-120"], text, "RD", "04-П.СКБ-ПИР-Р-ОДИ_сборка.pdf"))
    gate = "На калитке установлена вызывная панель домофона для вызова персонала"
    ok &= check("ODI-123: вызывная панель на калитке — вызов на входе (R4-Q-ODI-123)",
                "вызывная панель" in names(r["ODI-123"], gate, "PD", "ПЗ.pdf"))
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
