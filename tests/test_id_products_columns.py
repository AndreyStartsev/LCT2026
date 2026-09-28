"""Показатели здания из паспортов изделий в ИД и колонки таблиц без шапки (#145, Р-107).

  python tests/test_id_products_columns.py

Выдержки — из школы на Полярной 25: паспорта учебного и медицинского оборудования в ИД/ТХ,
баланс благоустройства РД ГП (доля последней колонкой без строки «100 %»), картограмма земляных
масс ПЗУ и отметки высот АР (ряды чисел без шапки).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import matrix_rules as mr  # noqa: E402
from pipeline import tep  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


BALANCE = ("Артикул: м2 331,80 1,52 Р13.2. брусчатка м2 252,60 1,16 RRх.1 крошки м2 515,90 2,36 RRх.2 площадках "
           "м2 2333,33 10,68 S1.1 отсева м2 5,95 0,03 S4.1 песка м2 21,00 0,10 4 Площадь озеленения : м2 7173,7 32,83 "
           "G1 Посевной газон. м2 4194,02 19,20 G2 газон м2 1315,41 6,02")


def main():
    ok = True
    ok &= check("паспорта учебного и медицинского оборудования — документы изделий",
                mr.product_document("ИД/ТХ/ИД Полярная корп 7/Эл.Копия ИД - Полярная 25, к. 7 СОШ 1100 - Учебное "
                                    "оборудование/16. Астролябия.pdf")
                and mr.product_document("ИД/ТХ/Эл.копия_ПОЛЯРНАЯ 25 кор.7 СОШ1100_Медицинское оборудование/10. Дозаторы "
                                        "для мыла, держатель для бумажных полотенец.pdf")
                and mr.product_document("ИД/ВИС/Паспорт насоса Grundfos.pdf"))
    ok &= check("акт, исполнительная схема и технический паспорт здания — не документы изделий",
                not mr.product_document("ИД/ВИС/АОСР №3 К3 монтаж ниже 0.pdf")
                and not mr.product_document("ИД/КЖ/Исполнительная схема плиты.pdf")
                and not mr.product_document("ИД/Технический паспорт здания БТИ.pdf"))
    got = [(c["value"], c["column_choice"]) for c in tep.find_values(BALANCE, ["площадь озеленения"], [], "last", unit="м2")]
    ok &= check("доля от общего итога, которого на листе нет: 32,83 % — не площадь", got == [(7173.7, "share")], str(got))
    lonely = "Площадь озеленения : м2 7173,7 32,83 G1 Посевной газон."
    got = [c["value"] for c in tep.find_values(lonely, ["площадь озеленения"], [], "last", unit="м2")]
    ok &= check("одной строки для доли мало — прежнее правило колонки", got == [32.83], str(got))
    got = tep.find_values("всего, м³ +1685.96 Выемка -3.47 -0.82 -1.25 0.00 -86.73 -518.93 -609.56", ["выемк"], [], "first",
                          unit="м3")
    ok &= check("ряд картограммы без шапки — не строка показателей", got == [], str(got))
    got = tep.find_values("всего, м³ +93 Выемка -96 -436 -299 -147 -305 -445", ["выемк"], [], "first")
    ok &= check("ряд картограммы со знаками — не одно число «96»", got == [], str(got))
    ok &= check("обычная строка объёма — по-прежнему значение",
                [c["value"] for c in tep.find_values("Объем выемки м3 1250 насыпи", ["объем выемки"], [], "first")] == [1250.0])
    ok &= check("папка ТХ в ИД — оборудование: паспорт ИБП актового зала",
                mr.product_document("ИД/ТХ/Эл.Копия ИД - Полярная 25, к. 7 СОШ 1100 - Актовый зал/33. Источник "
                                    "бесперебойного питания.pdf"))
    import json as _json
    pz013 = _json.load(open(os.path.join(ROOT, "rules", "matrix_queue1.json"), encoding="utf-8"))["parameters"]["PZ-013"]
    ok &= check("«совместимость» — не вместимость",
                mr.extract(pz013, "2.1 Электромагнитная совместимость 9 Хранение", None, {"stage": "ID"}) == [])
    got = tep.find_values("16840 (высота здания) 1 5 10 14 21 24 30 27400 28400", [r"высота\s+здани\w*"], [], "first")
    ok &= check("номера и отметки подряд за подписью — не значение", got == [], str(got))
    got = [c["value"] for c in tep.find_values("Площадь застройки м2 1250,4 1310,2", ["площадь застройки"], [], "last",
                                               unit="м2")]
    ok &= check("две колонки без шапки — по-прежнему по правилу", got == [1310.2], str(got))

    rule = {"labels": ["высота здания"], "kind": "height", "compare": {"type": "any_change"}, "scope": "building",
            "implemented": True, "rule": "first"}
    rules = {"parameters": {"PZ-008": rule}, "classes": {}, "location_defaults": {}}

    def cand(stage, value, file_id, document, **extra):
        return {"file_id": file_id, "page": 1, "document": document, "stage": stage, "value": value, "raw": f"{value:g}",
                "columns": [value], "label": "высота здания", "snippet": f"высота здания {value:g}", **extra}

    found = {"PZ-008": {"PD": [cand("PD", 16.8, "P1", "П-АР.pdf")], "RD": [cand("RD", 16.8, "R1", "Р-АР.pdf")],
                        "ID": [cand("ID", 4.0, "I1", "16. Астролябия.pdf", product_doc=True)]}}
    saved = mr.collect
    mr.collect = lambda object_id, rules, progress=None: (found, {}, 3)
    try:
        f = mr.build_findings("OBJ", rules)[0][0]
    finally:
        mr.collect = saved
    ok &= check("показатель здания из паспорта изделия в ИД не сравнивается", f["violation_label"] == "NO_VIOLATION"
                and f.get("id_value") is None, f"{f['violation_label']} {f.get('id_value')}")
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
