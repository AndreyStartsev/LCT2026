"""Цитата доказательства записи по элементу — со своей страницы (Р-158, #253).

  python tests/test_evidence_quotes_158.py

У записей по элементам (KR-055…KR-059, KR-067) на все страницы стороны ставилась одна цитата — цитата
первой страницы. Если значения набора взяты с разных страниц, у второй и третьей цитата была чужой:
у KR-058 Полярной 16 на ПД КР1 стр. 34 и РД КЖ04 изм. 2 стр. 3, где плита 1200 мм, стояло
«толщиной 900 мм (низ на отм. -4,400…». Тексты ниже — сокращённые фрагменты этих страниц.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import matrix_rules as mr  # noqa: E402

KR058 = {"kind": "element_thickness", "element": "Фундаментная плита", "scope": "element",
         "compare": {"type": "thickness_decrease", "result": "THICKNESS_DECREASE"}}
PLATE_900 = "Ростверк – монолитная железобетонная плита толщиной 900 мм (низ на отм. -4,400, абс. 148,450)"
PLATE_1200 = "Фундаменты под отдельно стоящий башенный кран – плита толщиной 1200 мм (низ на отм. -4,650)"


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def cand(fid, page, value, snippet, binding="CLAUSE", document="КР1.pdf", location="Фундаментная плита"):
    return {"location": location, "value": value, "raw": str(value), "columns": [str(value)], "label": location,
            "binding": binding, "file_id": fid, "page": page, "document": document, "snippet": snippet}


def quotes_of(finding, stage):
    return [(e["file_id"], e["pdf_page_number"], e["quote"]) for e in finding["evidence"] if e["stage"] == stage]


def test_set_from_pages():
    """Значения набора с разных страниц: у каждой страницы — цитата о её значении."""
    print("\n1. Набор значений с разных страниц (KR-058 Полярной 16)")
    found = {"PD": [cand("P1", 27, 900, PLATE_900), cand("P1", 34, 1200, PLATE_1200)],
             "RD": [cand("R3", 3, 900, "КЖ03: " + PLATE_900, document="КЖ03.pdf"),
                    cand("R4", 3, 1200, "КЖ04: " + PLATE_1200, document="КЖ04.pdf")]}
    got = mr.element_findings("OBJ-X", "KR-058", KR058, found, {})
    ok = check("одна запись, 900/1200 в обеих стадиях",
               [(f["pd_value"], f["rd_value"]) for f in got] == [("900/1200 мм", "900/1200 мм")],
               str([(f["pd_value"], f["rd_value"]) for f in got]))
    ok &= check("ПД: у стр. 34 цитата про 1200 мм, а не про 900",
                sorted(quotes_of(got[0], "PD")) == [("P1", 27, PLATE_900), ("P1", 34, PLATE_1200)],
                str(quotes_of(got[0], "PD")))
    ok &= check("РД: у КЖ04 — своя цитата",
                sorted(quotes_of(got[0], "RD")) == [("R3", 3, "КЖ03: " + PLATE_900), ("R4", 3, "КЖ04: " + PLATE_1200)],
                str(quotes_of(got[0], "RD")))
    return ok


def test_quote_choice():
    """На странице несколько кандидатов: значение из набора, затем привязка крепче, затем порядок текста."""
    print("\n2. Какой кандидат страницы даёт цитату")
    cands = [cand("P1", 1, 900, "указания: плита толщиной 900 мм"),
             # на второй странице первой по тексту идёт подпись листа, затем два указания
             cand("P1", 2, 900, "t=900 на листе", binding="SHEET"),
             cand("P1", 2, 900, "указания второй страницы: толщиной 900 мм"),
             cand("P1", 2, 900, "ещё раз толщиной 900 мм"),
             # третья страница попала в доказательства только подписью листа; первой на ней идёт чужое значение
             cand("P1", 3, 700, "t=700 на третьем листе", binding="SHEET"),
             cand("P1", 3, 900, "t=900 на третьем листе", binding="SHEET"),
             # на четвёртой первой по тексту идёт ведомость, затем те же указания, что на второй
             cand("P1", 4, 900, "ведомость: плита 900 мм"),
             cand("P1", 4, 900, "указания второй страницы: толщиной 900 мм")]
    side = mr.reconcile_set(KR058, cands)
    ok = check("набор — 900 мм; страницы: с двумя указаниями, с одним, с подписью листа",
               side["value"] == [900] and side["pages"] == [("P1", 2), ("P1", 4), ("P1", 1), ("P1", 3)],
               str(side["pages"]))
    ok &= check("у страницы с подписью и указаниями — цитата указания, первого по тексту",
                side["quotes"][("P1", 2)] == "указания второй страницы: толщиной 900 мм", side["quotes"][("P1", 2)])
    ok &= check("при равной привязке — та же цитата, что у первой страницы, если она есть и здесь",
                side["quotes"][("P1", 4)] == "указания второй страницы: толщиной 900 мм", side["quotes"][("P1", 4)])
    ok &= check("страница только с подписью листа — цитата подписи со значением из набора, а не первой по тексту",
                side["quotes"][("P1", 3)] == "t=900 на третьем листе", side["quotes"][("P1", 3)])
    ok &= check("у каждой страницы своя цитата",
                side["quotes"][("P1", 1)] == "указания: плита толщиной 900 мм", side["quotes"][("P1", 1)])
    ok &= check("у первой страницы цитата та же, что и цитата стороны",
                side["quotes"][side["pages"][0]] == side["snippet"], side["snippet"])
    return ok


def test_id_pages():
    """Страницы исполнительной документации: у набора — своя цитата, у одного значения — прежняя."""
    print("\n3. Доказательства из исполнительной документации")
    built = mr.reconcile_set({"kind": "element_class"}, [
        dict(cand("I1", 5, 3, "акт 1: бетон B25"), stage="ID"),
        dict(cand("I1", 9, 3, "акт 2: бетон B25 W6"), stage="ID")], by_registry=True)
    evidence = []
    mr.id_evidence(built, evidence)
    ok = check("у каждого акта своя цитата",
               [(e["pdf_page_number"], e["quote"]) for e in evidence] == [(5, "акт 1: бетон B25"),
                                                                           (9, "акт 2: бетон B25 W6")],
               str(evidence))
    single = {"value": 4, "raw": "4", "pages": [("I", 5), ("I", 6)], "snippet": "4 этажа"}
    evidence = []
    mr.id_evidence(single, evidence)
    ok &= check("у значения одного показателя цитата прежняя на всех страницах",
                [e["quote"] for e in evidence] == ["4 этажа", "4 этажа"], str(evidence))
    return ok


def test_lower_pages():
    """Страница меньшей толщины, которую решение не сочло понижением (#136): цитата — фрагмент страницы."""
    print("\n4. Страница меньшей толщины плиты (Речников, KR-059)")
    loc = "Плиты перекрытия подземной части"
    rule = {"kind": "element_thickness", "element": loc, "scope": "element",
            "compare": {"type": "thickness_decrease", "result": "THICKNESS_DECREASE"}}
    roof = "Плита покрытия Сплошная монолитная, железобетонная толщиной 200 мм"
    found = {"PD": [cand("P", 9, 250, "Толщина плиты перекрытия (монолитная, железобетонная): 250 мм", location=loc),
                    cand("P", 11, 200, roof, binding="SHEET", location=loc)],
             "RD": [dict(cand("R", 4, v, "в виде монолитных железобетонных плит толщиной 350, 250, 200 мм",
                              document="КЖ.pdf", location=loc), enumerated=True) for v in (350, 250, 200)]}
    got = mr.element_findings("OBJ-X", "KR-059", rule, found, {})
    ok = check("нарушения нет: 200 мм есть и в проекте", [f["violation_label"] for f in got] == ["NO_VIOLATION"],
               str([f["extraction"]["detail"] for f in got]))
    ok &= check("у страницы проекта с 200 мм — её фрагмент, а не подпись «толщина 200 мм»",
                ("P", 11, roof) in quotes_of(got[0], "PD"), str(quotes_of(got[0], "PD")))
    return ok


if __name__ == "__main__":
    print("Цитата доказательства — со своей страницы (Р-158)")
    results = [test_set_from_pages(), test_quote_choice(), test_id_pages(), test_lower_pages()]
    print("\nИТОГ: " + ("все проверки пройдены" if all(results) else "есть сбои"))
    sys.exit(0 if all(results) else 1)
