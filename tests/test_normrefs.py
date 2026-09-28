"""Проверка разбора и нечёткого сравнения нормативных ссылок. Задача #18.

  python tests/test_normrefs.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import normrefs  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def one(text):
    refs = normrefs.parse(text)
    return refs[0] if refs else None


def test_parse():
    ok = True
    cases = [
        ("СП 70.13330.2012", "СП", "70.13330", 2012),
        ("СП 70.13330-2012", "СП", "70.13330", 2012),
        ("ГОСТ 34028-2016", "ГОСТ", "34028", 2016),
        ("ГОСТ Р 21.101-2020", "ГОСТ Р", "21.101", 2020),
        ("ГОСТ 3262-75", "ГОСТ", "3262", 1975),
        ("СанПиН 2.1.3684-21", "СанПиН", "2.1.3684", 2021),
        ("СНиП 12-03-2001", "СНиП", "12-03", 2001),
        ("ТР ТС 004/2011", "ТР ТС", "004", 2011),
        ("СП 70.13330", "СП", "70.13330", None),
    ]
    for text, kind, number, year in cases:
        got = one(text)
        ok &= check(f"разбор «{text}»", got and (got["kind"], got["number"], got["year"]) == (kind, number, year),
                    got and f"{got['kind']} | {got['number']} | {got['year']}")
    # латинские двойники: в тексте чертежей «СП» попадается с латинской C
    ok &= check("латинская C в «CП 22.13330.2016»", one("CП 22.13330.2016")["kind"] == "СП")
    ok &= check("ссылка внутри строки", [r["label"] for r in normrefs.parse(
        "выполнено по СП 70.13330.2012 и ГОСТ 26633-2015, см. лист 3")] ==
        ["СП 70.13330.2012", "ГОСТ 26633-2015"])
    ok &= check("стадия в шифре тома не ссылка", normrefs.parse("ЖС-РД-270121-П-КР") == [],
                str(normrefs.parse("ЖС-РД-270121-П-КР")))
    ok &= check("«СПб» и «СПМ-жилстрой» не ссылки", normrefs.parse("СПб, ООО «СПМ-жилстрой»") == [])
    return ok


def test_compare():
    ok = True
    # опечатка корпуса: во всех восьми актах Октябрьской пропущена цифра серии
    typo, right = one("СП 70.1330.2012"), one("СП 70.13330.2012")
    got = normrefs.compare(typo, right)
    ok &= check("«СП 70.1330.2012» и «СП 70.13330.2012» — один документ, одна редакция",
                got["same_document"] and got["same_edition"] and got["verdict"] == "TYPO", str(got))
    edition = one("СП 70.13330.2017")
    got = normrefs.compare(right, edition)
    ok &= check("«СП 70.13330.2012» и «СП 70.13330.2017» — один документ, разные редакции",
                got["same_document"] and got["same_edition"] is False and got["verdict"] == "OTHER_EDITION", str(got))
    got = normrefs.compare(right, one("СП 70.13330.2012"))
    ok &= check("одна и та же запись", got["verdict"] == "EXACT" and not got["typo"], str(got))
    got = normrefs.compare(right, one("СП 71.13330.2017"))
    ok &= check("СП 70 и СП 71 — разные своды правил", not got["same_document"], str(got))
    # номер документа и серия: первая цифра меняет документ, лишняя в серии — опечатка
    got = normrefs.compare(one("СП 1.13130.2020"), one("СП 10.13130.2020"))
    ok &= check("СП 1.13130 и СП 10.13130 существуют оба, это разные документы",
                not got["same_document"], str(got))
    got = normrefs.compare(one("СП 12.13130.2020"), one("СП 1.13130.2020"))
    ok &= check("СП 12.13130 и СП 1.13130 — разные документы", not got["same_document"], str(got))
    got = normrefs.compare(one("СП 50.133330.2012"), one("СП 50.13330.2012"))
    ok &= check("лишняя цифра в серии — тот же документ", got["verdict"] == "TYPO", str(got))
    got = normrefs.compare(one("ГОСТ 26633-2015"), one("СП 26633.2015"))
    ok &= check("вид документа обязан совпасть", not got["same_document"], str(got))
    got = normrefs.compare(one("СП 70.13330"), one("СП 70.13330.2012"))
    ok &= check("без года редакции сравнить редакции нельзя",
                got["same_document"] and got["verdict"] == "NO_EDITION" and got["same_edition"] is None, str(got))
    return ok


def test_inventory():
    ok = True
    entries = (
        [dict(one("СП 70.13330.2012"), object_id="A", source="страницы")] * 9
        + [dict(one("СП 70.1330.2012"), object_id="B", source="акты")] * 2
        + [dict(one("СП 70.13330.2017"), object_id="B", source="страницы")]
        + [dict(one("ГОСТ 21.110-2013"), object_id="A", source="страницы")] * 3
        + [dict(one("ГОСТ 21.1101-2013"), object_id="A", source="страницы")]
        + [dict(one("ГОСТ 21.1101-2020"), object_id="A", source="страницы")]
    )
    refs = {r["label"]: r for r in normrefs.inventory(entries)}
    ok &= check("ссылка в перечне записана как принято: ГОСТ через дефис, СП через точку",
                "ГОСТ 21.110-2013" in refs and "СП 70.13330.2012" in refs, ", ".join(sorted(refs))[:120])
    ok &= check("перечень собран по упоминаниям", refs["СП 70.13330.2012"]["mentions"] == 9
                and refs["СП 70.13330.2012"]["objects"] == ["A"], str(refs["СП 70.13330.2012"]))
    ok &= check("редкая запись помечена опечаткой частой",
                refs["СП 70.1330.2012"]["typo_of"] == "СП 70.13330.2012"
                and refs["СП 70.1330.2012"]["typo_hint"] == "пропущена цифра",
                str(refs["СП 70.1330.2012"]))
    ok &= check("источники записи видны", refs["СП 70.1330.2012"]["sources"] == ["акты"])
    ok &= check("редакции одного документа собираются вместе",
                {refs[l]["document"] for l in ("СП 70.13330.2012", "СП 70.1330.2012", "СП 70.13330.2017")}
                == {"СП 70.13330"})
    ok &= check("другая редакция опечаткой не считается", refs["СП 70.13330.2017"]["typo_of"] is None)
    ok &= check("номер со своими редакциями опечаткой не считается: ГОСТ 21.1101 в двух годах",
                refs["ГОСТ 21.1101-2013"]["typo_of"] is None and refs["ГОСТ 21.1101-2020"]["typo_of"] is None,
                str(refs["ГОСТ 21.1101-2013"]["typo_of"]))
    return ok


def main():
    ok = True
    for title, fn in (("Разбор ссылки", test_parse), ("Сравнение ссылок", test_compare),
                      ("Перечень по корпусу", test_inventory)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
