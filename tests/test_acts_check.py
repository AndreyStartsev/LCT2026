"""Проверка сверки актов освидетельствования с рабочей документацией. Задача #42.

  python tests/test_acts_check.py

Акты берутся синтетические: в корпусе XML актов только у Октябрьской, и все они
об одном комплекте. Проверяется то, что акт говорит сам: шифр раздела и лист рабочей
документации, материалы и класс бетона.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import acts_check  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def act(number="12", code="23.009-Р-ГИ", sheet="2", materials=(), works=("Устройство гидроизоляции",)):
    return {"act_number": number, "act_date": "2026-04-20", "relative_path": f"ИД/AOSR_{number}.xml",
            "works": [{"name": w} for w in works],
            "materials": [{"name": m} for m in materials],
            "documentation_sections": [{"code": code, "name": "Гидроизоляция",
                                        "sheets": [sheet] if sheet else []}]}


SHEETS = [{"file_id": "L0011", "pdf_page_number": 5, "document_code": "23.009-Р-ГИ",
           "document_sheet_number": 2},
          {"file_id": "L0011", "pdf_page_number": 7, "document_code": "23.009-Р-ГИ",
           "document_sheet_number": 4}]


def run(acts, texts):
    return acts_check.check("OBJ-X", acts, SHEETS,
                            lambda fid, page: texts.get((fid, page), ""),
                            act_file_id=lambda a: "L0099")


def test_material_found():
    ok = True
    texts = {("L0011", 5): "План гидроизоляции. Отметки и размеры",
             ("L0011", 7): "Ведомость материалов: гидрошпонка ИКОПАЛ ХВС-150/1, штуцер инъекционный"}
    got, stats = run([act(materials=["Шпонка гидроизоляционная ИКОПАЛ ХВС-150/1"])], texts)
    ok &= check("материал найден в комплекте — нарушения нет",
                len(got) == 1 and got[0]["violation_label"] == "NO_VIOLATION", str(stats))
    ok &= check("доказательства: акт и лист рабочей документации",
                {e["stage"] for e in got[0]["evidence"]} == {"ID", "RD"},
                str([(e["stage"], e["file_id"], e["pdf_page_number"]) for e in got[0]["evidence"]]))
    ok &= check("значение исполнительной стадии заполнено",
                got[0]["id_value"].startswith("Шпонка"), str(got[0]["id_value"]))
    return ok


def test_material_missing():
    ok = True
    texts = {("L0011", 5): "План гидроизоляции", ("L0011", 7): "Ведомость материалов: трубка инъекционная"}
    got, _ = run([act(materials=["Инъекционная система WPI-Инжектосистема"])], texts)
    ok &= check("материала комплекта нет — не нарушение, а вопрос специалисту",
                len(got) == 1 and got[0]["violation_label"] == "COMPARISON_IMPOSSIBLE"
                and got[0]["needs_expert"], str(got[0]["violation_label"]))
    ok &= check("в пояснении сказано, где искали",
                "не назван в комплекте" in got[0]["extraction"]["detail"], got[0]["extraction"]["detail"][:80])
    return ok


def test_concrete_lower():
    ok = True
    texts = {("L0011", 5): "Бетон класса В30 W6 F150 по ГОСТ 26633", ("L0011", 7): "Общие указания"}
    got, _ = run([act(materials=["Бетонная смесь БСТ В25 П4 F150 W12"])], texts)
    ok &= check("класс бетона в акте ниже, чем на листе — кандидат",
                len(got) == 1 and got[0]["violation_label"] == "VIOLATION_PRESENT"
                and got[0]["comparison_result"] == "CLASS_DOWNGRADE", str(got[0]["violation_label"]))
    ok &= check("в пояснении обе стороны", "B25" in got[0]["extraction"]["detail"]
                and "B30" in got[0]["extraction"]["detail"], got[0]["extraction"]["detail"])
    texts_equal = {("L0011", 5): "Бетон класса В25 W6", ("L0011", 7): "Общие указания"}
    got, _ = run([act(materials=["Бетонная смесь БСТ В25 П4"])], texts_equal)
    ok &= check("класс совпал — нарушения нет", got[0]["violation_label"] == "NO_VIOLATION",
                str(got[0]["violation_label"]))
    return ok


def test_sheet_missing():
    ok = True
    texts = {("L0011", 5): "План гидроизоляции"}
    got, _ = run([act(sheet="99", materials=["Гидрошпонка ХВС-150/1"])], texts)
    ok &= check("листа, названного актом, в комплекте нет",
                got[0]["violation_label"] == "COMPARISON_IMPOSSIBLE"
                and "не найден" in got[0]["extraction"]["detail"], got[0]["extraction"]["detail"][:70])
    got, _ = run([act(materials=["Гидрошпонка ХВС-150/1"])], {})
    ok &= check("комплект без текста несовпадением не считается",
                got[0]["violation_label"] == "COMPARISON_IMPOSSIBLE"
                and "нет прочитанного текста" in got[0]["extraction"]["detail"],
                got[0]["extraction"]["detail"][:70])
    return ok


def test_no_materials():
    ok = True
    got, stats = run([act(materials=[])], {("L0011", 5): "План"})
    ok &= check("акт без материалов записей не даёт", got == [] and stats.get("без материалов") == 1,
                str(stats))
    return ok


# Акт в PDF: форма приказа Минстроя, текстовый слой. Так написаны все 80 актов
# Новослободской, и XML у объекта нет вовсе (#73)
PDF_ACT = ("АКТ освидетельствования скрытых работ № 1АФ от 11.02.2026 (наименование) "
           "1. К освидетельствованию предъявлены следующие работы: Армирование форшахты "
           "в осях 1-8 (наименование скрытых работ) 1 "
           "2. Работы выполнены по проектной документации 17_ПД/25-СВГ - Стена в грунте, "
           "ООО «ВЕЛЕС», лист 2 (номер, другие реквизиты чертежа, наименование проектной "
           "и (или) рабочей документации) "
           "3. При выполнении работ применены: Арматура А240С d12 Сертификат качества "
           "№1720110087 от 04.09.2028, Перечислено в реестре приложений "
           "(наименование строительных материалов (изделий), реквизиты сертификатов)")


def test_pdf_act():
    """Акт из PDF разбирается в ту же запись, что даёт XML."""
    from pipeline import aosr_text
    rec = aosr_text.parse(PDF_ACT, "АОСР №1АФ от 11.02.2026.pdf")
    ok = check("номер и дата акта", (rec["act_number"], rec["act_date"]) == ("1АФ", "11.02.2026"),
               str((rec["act_number"], rec["act_date"])))
    ok &= check("работы названы", rec["works"] and rec["works"][0]["name"].startswith("Армирование"),
                str(rec["works"]))
    sec = rec["documentation_sections"][0] if rec["documentation_sections"] else {}
    ok &= check("шифр раздела и лист", (sec.get("code"), sec.get("sheets")) == ("17_ПД/25-СВГ", ["2"]),
                str(sec))
    names = [m["name"] for m in rec["materials"]]
    ok &= check("материал без реквизитов документа о качестве", names == ["Арматура А240С d12"], str(names))
    ok &= check("«Перечислено в реестре приложений» материалом не считается",
                "Перечислено" not in " ".join(names))
    ok &= check("не акт — не запись", aosr_text.parse("Протокол испытаний бетона № 5", "п.pdf") is None)
    return ok


def test_act_without_sheet():
    """Акт назвал комплект без листа: материал ищется по комплекту, а не объявляется пропажа листа."""
    texts = {("L0011", 5): "План гидроизоляции",
             ("L0011", 7): "Ведомость материалов: гидрошпонка ИКОПАЛ ХВС-150/1"}
    got, stats = run([act(sheet=None, materials=["Шпонка гидроизоляционная ИКОПАЛ ХВС-150/1"])], texts)
    ok = check("лист не назван — не повод говорить «лист не найден»",
               stats.get("лист не назван") == 1 and not stats.get("лист не найден"), str(stats))
    ok &= check("материал найден по комплекту",
                len(got) == 1 and got[0]["violation_label"] == "NO_VIOLATION", str(stats))
    got, stats = run([act(sheet=None, code="23.009-Р-НЕТ", materials=["Шпонка ХВС-150/1"])], texts)
    ok &= check("комплекта нет в рабочей документации — сказано именно это",
                stats.get("комплект не найден") == 1
                and "комплект" in got[0]["extraction"]["detail"], str(stats))
    return ok


def test_material_without_mark():
    """Материал без марки и названия изделия проверить нечем — молчим, а не выдумываем пропажу."""
    texts = {("L0011", 5): "План гидроизоляции", ("L0011", 7): "Ведомость материалов"}
    got, stats = run([act(materials=["Сетка стальная сварная"])], texts)
    ok = check("записи нет", got == [], str(stats))
    ok &= check("и это видно счётчиком", stats.get("материалы без марки") == 1, str(stats))
    return ok


def test_act_confirms_itself():
    """Акт ИД с шифром комплекта РД в надписи материал сам себе не подтверждает (рецензия слияния 24.09)."""
    ok = True
    act_page = {"file_id": "L0125", "pdf_page_number": 2, "document_code": "23.009-Р-ГИ",
                "document_sheet_number": None}
    stage = {"L0011": "RD", "L0125": "ID", "L0200": "RD_ID_MIXED", "L0003": "PD"}.get
    kept = acts_check.rd_sheets(SHEETS + [act_page, dict(act_page, file_id="L0200"),
                                          dict(act_page, file_id="L0003")], stage)
    ok &= check("страницы ИД и проекта из связки убраны, РД и смешанная папка остаются",
                sorted({r["file_id"] for r in kept}) == ["L0011", "L0200"], str(kept))
    texts = {("L0011", 5): "План гидроизоляции", ("L0125", 2): "АОСР № 50: бетон M200Пк3F50"}
    got, _ = acts_check.check("OBJ-X", [act(number="50", materials=["Бетон M200Пк3F50"])],
                              acts_check.rd_sheets(SHEETS + [act_page], stage),
                              lambda fid, page: texts.get((fid, page), ""), act_file_id=lambda a: "L0125")
    ok &= check("материал только в самом акте — не «нарушения нет»",
                got and got[0]["violation_label"] != "NO_VIOLATION", str([g["violation_label"] for g in got]))
    return ok


def main():
    ok = True
    for title, fn in (("Материал найден", test_material_found),
                      ("Материала нет", test_material_missing),
                      ("Класс бетона", test_concrete_lower),
                      ("Лист и текст", test_sheet_missing),
                      ("Акт без материалов", test_no_materials),
                      ("Акт из PDF", test_pdf_act),
                      ("Акт без номера листа", test_act_without_sheet),
                      ("Материал без марки", test_material_without_mark),
                      ("Акт сам себя не подтверждает", test_act_confirms_itself)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
