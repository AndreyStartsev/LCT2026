"""Площади квартир между стадиями по штампам квартир. Задача #100.

  python tests/test_apartment_areas.py

Синтетические страницы с штампами «жилая общая с_летними тип»: одинаковая квартира с другой
площадью с летними, студия, ставшая однокомнатной, квартира другой геометрии, размеры и отметки
перед номером типа, выбор действующей редакции.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import apartment_areas as aa  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def page(*stamps):
    """Текст страницы в том порядке, в каком его отдаёт слой: слова штампа — строками подряд."""
    return "\n".join(["А", "Б", "1750", "2900"] + [x for s in stamps for x in s.split()] + ["лист 21"])


def test_stamps():
    print("\n1. Разбор штампов")
    got = aa.stamps(page("17,32 37,47 39,23 1.2.1", "21,34 31,31 34,06 Ст.1.1.1"))
    ok = check("тип, жилая, общая, с летними", got == [("1.2.1", 17.32, 37.47, 39.23), ("Ст.1.1.1", 21.34, 31.31, 34.06)],
               str(got))
    ok &= check("несогласованная тройка — не штамп: жилая больше общей",
                aa.stamps(page("45,43 12,40 84,00 3.2.1")) == [])
    ok &= check("размеры перед номером листа — не штамп", aa.stamps("3600\n3000\n3900\n1.2") == [])
    ok &= check("приставка студии снимается", aa.base_type("Ст.1.1.1") == "1.1.1" and aa.base_type("1.2.3") == "1.2.3")
    return ok


def test_compare():
    print("\n2. Сравнение стадий")
    pages = [("PD", "P1", 62, page("17,32 37,47 39,23 1.2.1", "21,34 31,31 34,06 Ст.1.1.1", "45,05 89,09 91,84 3.2.2")),
             ("RD", "R1", 21, page("17,32 37,47 40,99 1.2.1", "15,64 31,31 36,80 1.1.1", "45,17 89,21 94,70 3.2.2")),
             ("RD", "R1", 22, page("17,32 37,47 40,99 1.2.1"))]
    got, s = aa.compare("OBJ-T", pages)
    ok = check("две квартиры одной геометрии изменены, третья — другой геометрии, не сравнивается",
               s["изменено"] == 2 and s["в обеих"] == 2, str(s))
    by = {(f["aspect"], f["locations"][0]) for f in got}
    ok &= check("записи по сторонам (Р-109): площадь с летними — у обеих квартир, жилая — только у студии",
                by == {("площадь с летними", "тип 1.2.1, общая 37,47 м²"), ("площадь с летними", "тип 1.1.1, общая 31,31 м²"),
                       ("жилая площадь", "тип 1.1.1, общая 31,31 м²")}, str(sorted(by)))
    ok &= check("у сторон разные finding_id", len({f["finding_id"] for f in got}) == 3
                and all("::SUMMER::" in f["finding_id"] or "::LIVING::" in f["finding_id"] for f in got))
    flat = next(f for f in got if f["locations"] == ["тип 1.2.1, общая 37,47 м²"])
    ok &= check("площадь с летними: 39,23 → 40,99",
                flat["pd_value"] == "с летними 39,23 м²" and flat["rd_value"] == "с летними 40,99 м²", flat["rd_value"])
    ok &= check("доказательства — страница проекта и страницы рабочей стадии, первой та, где штампов больше",
                [(e["stage"], e["file_id"], e["pdf_page_number"]) for e in flat["evidence"]]
                == [("PD", "P1", 62), ("RD", "R1", 21), ("RD", "R1", 22)])
    studio = next(f for f in got if f["aspect"] == "жилая площадь")
    ok &= check("жилая площадь студии: 21,34 → 15,64, в пояснении — тип в РД",
                studio["pd_value"] == "жилая 21,34 м²" and studio["rd_value"] == "жилая 15,64 м²"
                and "тип в РД записан как 1.1.1" in studio["extraction"]["detail"], studio["extraction"]["detail"])
    ok &= check("гипотеза, в сдачу не идёт", all(f["finding_status"] == "SUSPICION" and f["for_submission"] is False
                                                 and f["needs_expert"] for f in got))
    same, s2 = aa.compare("OBJ-T", [("PD", "P1", 1, page("17,32 37,47 39,23 1.2.1")),
                                    ("RD", "R1", 1, page("17,32 37,47 39,23 1.2.1"))])
    ok &= check("совпадающие квартиры — гипотез нет", same == [] and s2["в обеих"] == 1)
    many = [("PD", "P1", 1, page(*[f"10,{n:02d} 30,{n:02d} 32,00 1.2.{n}" for n in range(1, 8)])),
            ("RD", "R1", 1, page(*[f"10,{n:02d} 30,{n:02d} 33,00 1.2.{n}" for n in range(1, 8)]))]
    grouped, s3 = aa.compare("OBJ-T", many)
    ok &= check("много квартир — одна запись с перечнем; жилая площадь та же — записи по ней нет",
                len(grouped) == 1 and len(grouped[0]["locations"]) == 7 and grouped[0]["aspect"] == "площадь с летними"
                and grouped[0]["pd_value"] == "площадь с летними помещениями изменена у 7 квартир одной геометрии"
                and s3["изменено"] == 7, str(len(grouped)))
    return ok


def test_current_files():
    print("\n3. Действующая редакция")
    docs = [{"file_id": "A2", "revision_status": "CLARIFICATION_REQUIRED"},
            {"file_id": "A4", "revision_status": "CLARIFICATION_REQUIRED"},
            {"file_id": "A5v", "revision_status": "CLARIFICATION_REQUIRED"},
            {"file_id": "A5o", "revision_status": "CLARIFICATION_REQUIRED"},
            {"file_id": "OLD", "revision_status": "SUPERSEDED"},
            {"file_id": "NEW", "revision_status": "CURRENT"},
            {"file_id": "NEW", "revision_status": "CURRENT", "duplicate_of": "NEW"},
            {"file_id": "X1", "revision_status": "CLARIFICATION_REQUIRED"},
            {"file_id": "X2", "revision_status": "CLARIFICATION_REQUIRED"}]
    chains = [{"status": "CLARIFICATION_REQUIRED", "members": ["A2", "A4", "A5v", "A5o"],
               "member_detail": {"A2": {"revision": "изм. 2"}, "A4": {"revision": "изм. 4"},
                                 "A5v": {"revision": "изм. 5"}, "A5o": {"revision": "изм. 5"}}},
              {"status": "CLARIFICATION_REQUIRED", "members": ["X1", "X2"],
               "member_detail": {"X1": {"revision": None}, "X2": {"revision": "изм. 1"}}}]
    got = aa.current_files(docs, chains)
    ok = check("последняя редакция цепочки «требует уточнения» — оба файла изм. 5", {"A5v", "A5o"} <= got
               and not {"A2", "A4"} & got, str(sorted(got)))
    ok &= check("заменённая редакция не берётся", "OLD" not in got and "NEW" in got)
    ok &= check("номер редакции читается не у всех — цепочка берётся целиком", {"X1", "X2"} <= got)
    return ok


def main():
    ok = True
    for fn in (test_stamps, test_compare, test_current_files):
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
