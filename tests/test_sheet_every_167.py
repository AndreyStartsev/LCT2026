"""Лист схемы плиты перекрытия — только в набор «в проекте такая толщина есть» (Р-167, KR-059).

  python tests/test_sheet_every_167.py

Тексты — со страниц корпуса, сокращены: ПД Речникова, лист 4 КР2-кор3 (F0260, стр. 18), и ПД Октябрьской, КР1
(L0020, стр. 63). До правки подпись «t=200 -2,100» на листе Речникова кандидатов не давала: название листа стоит
в штампе, в конце текста, и довод #136 «в проекте такая толщина тоже есть» держался на плите покрытия надземного
корпуса (F0262 стр. 11, F0267 стр. 27).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import elements, tep, matrix_rules as mr  # noqa: E402

# ПД Речникова, F0260 стр. 18: фундаментная плита на −5,700, участки плиты на −2,100, название — в конце
RECHNIKOV_SHEET = ("1200 1200 t=900 -5,700 t=600 -5,700 300 15450 t=800 -2,100 Деформационный шов t=900 -2.000 3100 "
                   "1650 4300 1050 900 16050 2.4 t=200 -2,100 300 Схема расположения вертикальных несущих "
                   "конструкций на отм. -5,700 Схема расположения плиты перекрытия в осях 1/1-1/7 на отм. -2,100")
# ПД Октябрьской, L0020 стр. 63: участки плит и подпись стены с отметкой
OKTYABRSKAYA_SHEET = ("t=180 +5,590 t=200 +6,290 t=180 Балка 250х900 Стена монолитная ж.б. t=250 +6,110 "
                      "Схема расположения плит перекрытия секций 1, 2 на отм. +5,590")
# лист без названия схемы плиты — подписи не берутся
NO_TITLE = "Схема расположения вертикальных несущих конструкций на отм. -2,100 t=200 -2,100"
# нулевая отметка части здания не называет
ZERO_LEVEL = "Схема расположения плиты перекрытия на отм. 0,000 t=200 ±0,000 t=220 +0,000"

ELEMENT = "Плиты перекрытия"
UNDER = f"{ELEMENT} {elements.UNDERGROUND}"


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def marks(text):
    return [(v, z) for v, _snippet, z in elements.slab_sheet_marks(tep.flatten(text))]


def test_sheet_marks():
    got = marks(RECHNIKOV_SHEET)
    ok = check("Речников: 200 мм подземной части; 900, 600, 800 — вне диапазона перекрытий",
               got == [(200, elements.UNDERGROUND)], str(got))
    got = marks(OKTYABRSKAYA_SHEET)
    ok &= check("Октябрьская: 180 и 200 надземной части, подпись стены 250 не берётся",
                got == [(180, elements.ABOVEGROUND), (200, elements.ABOVEGROUND)], str(got))
    ok &= check("без названия схемы плиты — пусто", marks(NO_TITLE) == [], str(marks(NO_TITLE)))
    ok &= check("нулевая отметка — пусто", marks(ZERO_LEVEL) == [], str(marks(ZERO_LEVEL)))
    snippets = [s for _v, s, _z in elements.slab_sheet_marks(tep.flatten(RECHNIKOV_SHEET))]
    ok &= check("цитата — фрагмент самой страницы", all(s in tep.flatten(RECHNIKOV_SHEET) for s in snippets))
    return ok


def extract_sheet(text):
    rule = {"kind": "element_thickness", "element": ELEMENT}
    return [c for c in mr.extract(rule, text) if c.get("every_only")]


def test_extract():
    got = extract_sheet(RECHNIKOV_SHEET)
    return check("правило даёт подпись листа кандидатом every_only, локация — подземная часть, привязка «лист»",
                 [(c["value"], c["location"], c["binding"]) for c in got] == [(200, UNDER, "SHEET")],
                 str([(c["value"], c["location"], c["binding"]) for c in got]))


def cand(value, fid, page, binding="CLAUSE", every_only=False, location=UNDER):
    return {"value": value, "raw": str(value), "columns": [str(value)], "label": location, "location": location,
            "binding": binding, "snippet": f"толщиной {value} мм", "file_id": fid, "page": page,
            "document": f"ПД/{fid}-КР.pdf", **({"every_only": True} if every_only else {})}


def test_reconcile_set():
    rule = {"kind": "element_thickness", "element": ELEMENT}
    plain = [cand(250, "F0262", 9)]
    sheet = [cand(200, "F0260", 18, binding="SHEET", every_only=True)]
    side = mr.reconcile_set(rule, plain, every_extra=sheet)
    ok = check("значение стадии — только проза: 250", side["value"] == [250], str(side["value"]))
    ok &= check("страницы доказательств — без листа", side["pages"] == [("F0262", 9)], str(side["pages"]))
    ok &= check("в «есть в проекте» — и 200 с листа", side["every"] == [200, 250], str(side["every"]))
    ok &= check("страница листа — в страницах набора", side["every_pages"].get(200) == [("F0260", 18)],
                str(side["every_pages"].get(200)))
    ok &= check("без обычных кандидатов сторона пуста", mr.reconcile_set(rule, [], every_extra=sheet) is None)
    return ok


def test_decision():
    """Речников: ПД 250, РД 200/250/350 — «нарушения нет», и довод держится на листе, а не на плите покрытия."""
    rule = {"kind": "element_thickness", "element": ELEMENT, "compare": {"result": "DIMENSION_REDUCED"}}
    found = {
        "PD": [cand(250, "F0262", 9), cand(200, "F0260", 18, binding="SHEET", every_only=True)],
        "RD": [cand(200, "F0345", 3), cand(250, "F0348", 4), cand(350, "F0348", 4)],
    }
    for stage in found:
        for c in found[stage]:
            c.setdefault("chain", None)
    out = mr.element_findings("OBJ", "KR-059", rule, found, {})
    rec = out[0] if out else {}
    ok = check("одна запись", len(out) == 1, str(len(out)))
    ok &= check("нарушения нет", rec.get("violation_label") == "NO_VIOLATION", rec.get("violation_label"))
    pages = [(e["stage"], e["file_id"], e["pdf_page_number"]) for e in rec.get("evidence", [])]
    ok &= check("в доказательствах — лист F0260 стр. 18", ("PD", "F0260", 18) in pages, str(pages))
    # без листа — понижение: 200 в РД меньше 250 в ПД и в проекте его нет
    found["PD"] = found["PD"][:1]
    rec = mr.element_findings("OBJ", "KR-059", rule, found, {})[0]
    ok &= check("без листа — нарушение", rec["violation_label"] == "VIOLATION_PRESENT", rec["violation_label"])
    # только подпись листа, без прозы — записи нет
    only = {"PD": [cand(200, "F0260", 18, binding="SHEET", every_only=True)], "RD": []}
    ok &= check("одна подпись листа запись не заводит", mr.element_findings("OBJ", "KR-059", rule, only, {}) == [])
    return ok


if __name__ == "__main__":
    ok = True
    for fn in (test_sheet_marks, test_extract, test_reconcile_set, test_decision):
        print(fn.__name__)
        ok &= fn()
    print("OK" if ok else "ЕСТЬ СБОИ")
    sys.exit(0 if ok else 1)
