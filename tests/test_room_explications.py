"""Экспликации между стадиями: пропавшее помещение, площадь, категория. Задача #56.

  python tests/test_room_explications.py

Синтетические строки экспликаций (`rooms_pages.jsonl`): помещение пропало, площадь уменьшена,
категория изменена, шум ниже порога, перенумерация, ведущие нули номера, том-отщепенец,
незакрытая строка разбора, много расхождений одного вида, номер в таблицах разных мест здания.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import room_explications as rx, room_names  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def row(stage, file_id, page, number, name, area=None, category=None, table=None):
    return {"stage": stage, "file_id": file_id, "pdf_page_number": page, "number": number,
            "name": name, "area_m2": area, "category": category, "labeled": True, "table": table}


def names_of(rows):
    clean = [(r["stage"], r["file_id"], r["number"], r["name"]) for r in rows if r.get("labeled")]
    return room_names.Names(clean, [])


def kinds(findings):
    return sorted(f["finding_id"].split("::")[2] for f in findings)


def test_missing():
    print("\n1. Помещение пропало")
    pd = [row("PD", "P1", 3, n, name, a) for n, name, a in
          (("101", "Кабинет директора", 20.0), ("102", "Приёмная", 12.0), ("103", "Серверная", 9.5), ("104", "Коридор", 40.0))]
    rd = [row("RD", "R1", 5, n, name, a) for n, name, a in
          (("101", "Кабинет директора", 20.0), ("102", "Приёмная", 12.0), ("104", "Коридор", 40.0))]
    got, s = rx.compare("OBJ-T", pd + rd, names_of(pd + rd))
    ok = check("103 есть в проекте, в рабочей экспликации стоят соседи 102 и 104 — гипотеза",
               kinds(got) == ["MISSING"] and got[0]["locations"] == ["103"], str(kinds(got)))
    f = got[0] if got else {}
    ok &= check("запись — гипотеза свободного поиска, не для сдачи, нужен эксперт",
                f.get("matrix_scope") == "FREE_SEARCH" and f.get("finding_status") == "SUSPICION"
                and f.get("needs_expert") is True and f.get("for_submission") is False)
    ok &= check("доказательства: страницы проекта и страница рабочей экспликации с соседями",
                [(e["stage"], e["file_id"], e["pdf_page_number"]) for e in f.get("evidence", [])] == [("PD", "P1", 3), ("RD", "R1", 5)])
    rd2 = [row("RD", "R1", 5, "101", "Кабинет директора", 20.0), row("RD", "R1", 5, "102", "Приёмная", 12.0)]
    got, _ = rx.compare("OBJ-T", pd + rd2, names_of(pd + rd2))
    ok &= check("соседей с обеих сторон нет — лист рабочей экспликации просто не закрыт, гипотезы нет", not [g for g in got if "MISSING" in g["finding_id"]])
    text = {("R1", 5): "101 Кабинет директора 20.0 102 Приёмная 12.0 103 Серверная 9.5 104 Коридор 40.0"}
    got, s = rx.compare("OBJ-T", pd + rd, names_of(pd + rd), text_of=lambda f, p: text.get((f, p), ""))
    ok &= check("номер с наименованием есть в тексте страницы — незакрытая строка разбора, не пропажа",
                not got and s["пропало: номер есть в тексте страницы"] == 1, str(s))
    # другой том проекта уже без 103: соседи стоят, номера нет — проект переиздан, а не РД разошлась
    pd_other = [row("PD", "P2", 7, n, name, a) for n, name, a in
                (("101", "Кабинет директора", 20.0), ("102", "Приёмная", 21.5), ("104", "Коридор", 40.0))]
    got, s = rx.compare("OBJ-T", pd + pd_other + rd, names_of(pd + pd_other + rd))
    ok &= check("том проекта без номера при тех же соседях — проект сам с собой не согласен, гипотезы нет",
                not [g for g in got if "MISSING" in g["finding_id"]] and s["пропало: проект сам с собой не согласен"] == 1, str(s))
    pd_noarea = [row("PD", "P1", 3, "103", "- кирпичная")] + [r for r in pd if r["number"] != "103"]
    got, _ = rx.compare("OBJ-T", pd_noarea + rd, names_of(pd_noarea + rd))
    ok &= check("строка проекта без площади — пункт перечня, а не помещение: гипотезы нет", not got)
    return ok


def test_area():
    print("\n2. Площадь")
    def pair(pd_area, rd_area, extra_pd=()):
        pd = [row("PD", "P1", 3, "201", "Лаборантская", pd_area), row("PD", "P2", 7, "201", "Лаборантская", pd_area)]
        pd += [row("PD", f, 1, "201", "Лаборантская", a) for f, a in extra_pd]
        rd = [row("RD", "R1", 5, "201", "Лаборантская", rd_area)]
        return pd + rd
    rows = pair(21.9, 18.0)
    got, s = rx.compare("OBJ-T", rows, names_of(rows))
    ok = check("21,9 → 18,0 м² (−18 %) — гипотеза «площадь уменьшена»",
               kinds(got) == ["AREA"] and got[0]["pd_value"] == "21.9 м²" and got[0]["rd_value"] == "18 м²", str(got and got[0]["pd_value"]))
    rows = pair(21.9, 21.2)
    got, _ = rx.compare("OBJ-T", rows, names_of(rows))
    ok &= check("−3 % — ниже порога, гипотезы нет", not got)
    rows = pair(18.0, 21.9)
    got, _ = rx.compare("OBJ-T", rows, names_of(rows))
    ok &= check("площадь выросла — не уменьшение, гипотезы нет", not got)
    rows = pair(21.9, 18.0, extra_pd=(("P3", 18.0), ("P4", 18.0)))
    got, s = rx.compare("OBJ-T", rows, names_of(rows))
    ok &= check("тома проекта разошлись 2:2 — стадия не согласна сама с собой, сравнения нет",
                not got and s["площадь: стадия не согласна сама с собой"] == 1, str(s))
    rows = pair(21.9, 18.0, extra_pd=(("P3", 21.9), ("P4", 18.0)))
    got, _ = rx.compare("OBJ-T", rows, names_of(rows))
    ok &= check("три тома из четырёх говорят 21,9 — большинство решает, гипотеза есть с оговоркой",
                kinds(got) == ["AREA"] and "в части томов проекта 18 м²" in got[0]["extraction"]["detail"], str(got and got[0]["extraction"]["detail"]))
    rows = [row("PD", "P1", 3, "201", "Лаборантская", 21.9), row("RD", "R1", 5, "201", "Кабинет физики", 18.0)]
    got, s = rx.compare("OBJ-T", rows, names_of(rows))
    ok &= check("наименования разные — другое помещение под тем же номером, сравнения нет", not got and s["сверено"] == 0)
    return ok


def test_superseded():
    print("\n2а. Заменённая редакция ПД не голосует за площадь (#100)")
    # первоначальная ПД в двух томах и корректировка в одном; рабочая стадия осталась по первоначальной
    rows = [row("PD", "OLD1", 27, "145", "Помещение с холодильным оборудованием", 11.8),
            row("PD", "OLD2", 40, "145", "Помещение с холодильным оборудованием", 11.8),
            row("PD", "NEW", 27, "145", "Помещение с холодильным оборудованием", 13.7),
            row("RD", "R1", 12, "145", "Помещение с холодильным оборудованием", 11.8)]
    ok = True
    got, s = rx.compare("OBJ-T", rows, names_of(rows))
    ok &= check("без редакций большинство томов за старый выпуск — расхождения нет", got == [], str(s))
    got, s = rx.compare("OBJ-T", rows, names_of(rows), superseded={"OLD1", "OLD2"})
    # рабочая стадия повторяет заменённый выпуск: не «площадь уменьшена», а «не обновлена» (#111)
    ok &= check("старый выпуск заменён, РД по нему — рабочая стадия не обновлена после корректировки",
                kinds(got) == ["STALE"] and "13.7 м²" in got[0]["extraction"]["detail"]
                and "11.8 м²" in got[0]["extraction"]["detail"], str([f["finding_id"] for f in got]))
    ok &= check("доказательства: действующий выпуск, заменённый выпуск и том РД",
                [(e["stage"], e["file_id"]) for e in got[0]["evidence"]] == [("PD", "NEW"), ("PD", "OLD1"), ("RD", "R1")],
                str([(e["stage"], e["file_id"]) for e in got[0]["evidence"]]))
    ok &= check("сводка называет отброшенные строки", s["строк заменённых редакций"] == 2, str(s))
    return ok


def test_not_updated():
    """Рабочая стадия частично не обновлена после корректировки проекта (#111)."""
    print("\n2б. Рабочая стадия частично не обновлена после корректировки проекта (#111)")
    name = "Помещение с холодильным оборудованием"
    base = [row("PD", "OLD1", 27, "145", name, 11.8), row("PD", "OLD2", 40, "145", name, 11.8),
            row("PD", "NEW", 27, "145", name, 13.7)]
    volumes = {"R_AR": "АР1 изм. 3", "R_AI": "АИ2", "R_EOM": "ЭОМ"}
    rows = base + [row("RD", "R_EOM", 5, "145", name, 11.8), row("RD", "R_AR", 12, "145", name, 11.8),
                   row("RD", "R_AI", 8, "145", name, 13.7)]
    got, s = rx.compare("OBJ-T", rows, names_of(rows), superseded={"OLD1", "OLD2"}, volumes=volumes)
    ok = check("тома РД разошлись: АР1 и ЭОМ по заменённой редакции, АИ2 по действующей — одна гипотеза",
               kinds(got) == ["STALE"] and s["не обновлено после корректировки проекта"] == 1, str(kinds(got)))
    detail = got[0]["extraction"]["detail"]
    ok &= check("пояснение называет тома обеих групп, АР первым",
                "по заменённой редакции проекта — АР1 изм. 3, ЭОМ" in detail and "по действующей — АИ2" in detail, detail[:200])
    ok &= check("том РД в доказательствах — АР", [e["file_id"] for e in got[0]["evidence"] if e["stage"] == "RD"][0] == "R_AR")
    ok &= check("гипотеза, в сдачу не идёт", got[0]["for_submission"] is False and got[0]["needs_expert"])
    rows = base + [row("RD", "R_AR", 12, "145", name, 13.7), row("RD", "R_AI", 8, "145", name, 13.7)]
    got, _ = rx.compare("OBJ-T", rows, names_of(rows), superseded={"OLD1", "OLD2"}, volumes=volumes)
    ok &= check("все тома РД по действующей редакции — гипотез нет", got == [], str(kinds(got)))
    chains = {"OLD1": "AR", "OLD2": "AR", "NEW": "AR"}
    rows = base + [row("RD", "R_AR", 12, "145", name, 11.8)]
    got, _ = rx.compare("OBJ-T", rows, names_of(rows), superseded={"OLD1", "OLD2"}, volumes=volumes, chain_of=chains)
    ok &= check("корректировка видна в цепочке АР: 11,8 в заменённом томе, 13,7 в его преемнике", kinds(got) == ["STALE"])
    # Тюменская-5, венткамера 006: действующий АР и заменённый «Том 3.РЕД» — 71,4; тома сетей связи — 51,2
    vent = [row("PD", "AR_OLD", 26, "006", "Венткамера", 71.4), row("PD", "AR", 27, "006", "Венткамера", 71.4),
            row("PD", "SS1", 32, "006", "Венткамера", 51.2), row("PD", "SS2", 20, "006", "Венткамера", 51.2),
            row("PD", "SS3", 20, "006", "Венткамера", 51.2), row("RD", "OV1", 17, "006", "Венткамера", 71.4)]
    got, _ = rx.compare("OBJ-T", vent, names_of(vent), superseded={"AR_OLD"}, volumes=volumes,
                        chain_of={"AR_OLD": "AR", "AR": "AR", "SS1": "S1", "SS2": "S2", "SS3": "S3"})
    ok &= check("большинство томов проекта за другое значение, но в цепочке АР площадь не менялась — «не обновлено» нет",
                "STALE" not in kinds(got), str(kinds(got)))
    rows = [row("PD", "OLD1", 27, "145", name, 13.6), row("PD", "NEW", 27, "145", name, 13.7),
            row("RD", "R_AR", 12, "145", name, 11.0)]
    got, _ = rx.compare("OBJ-T", rows, names_of(rows), superseded={"OLD1"}, volumes=volumes)
    ok &= check("корректировка площадь не меняла — обычная гипотеза «площадь уменьшена»", kinds(got) == ["AREA"], str(kinds(got)))
    cat = [row("PD", "OLD1", 3, "123", "Электрощитовая", 10.0, "В4"), row("PD", "NEW", 3, "123", "Электрощитовая", 10.0, "В3"),
           row("RD", "R_AR", 5, "123", "Электрощитовая", 10.0, "В3"), row("RD", "R_EOM", 6, "123", "Электрощитовая", 10.0, "В4")]
    got, _ = rx.compare("OBJ-T", cat, names_of(cat), superseded={"OLD1"}, volumes=volumes)
    ok &= check("категория: ЭОМ по заменённой (В4), АР1 по действующей (В3) — не «категория изменена», а «не обновлено»",
                kinds(got) == ["STALE"] and "категория" in got[0]["extraction"]["detail"], str(kinds(got)))
    # площади и категории — разными записями: у специалиста по ним разные решения (Р-86)
    both = base + [row("RD", "R_AR", 12, "145", name, 11.8)] + cat
    got, _ = rx.compare("OBJ-T", both, names_of(both), superseded={"OLD1", "OLD2"}, volumes=volumes)
    ok &= check("площадь и категория не обновлены — две записи, у каждой своя сторона",
                sorted((f.get("aspect"), tuple(f["locations"])) for f in got) == [("категория", ("123",)), ("площадь", ("145",))],
                str([(f.get("aspect"), f["locations"]) for f in got]))
    ok &= check("запись о категориях так и названа", any(f["title"].endswith("категории помещений") for f in got))
    return ok


def test_category_and_numbers():
    print("\n3. Категория, ведущие нули, много расхождений")
    rows = [row("PD", "P1", 3, "301", "Кладовая", 10.0, "В2"), row("RD", "R1", 5, "301", "Кладовая", 10.0, "В4")]
    got, _ = rx.compare("OBJ-T", rows, names_of(rows))
    ok = check("категория В2 → В4 — гипотеза", kinds(got) == ["CATEGORY"] and got[0]["pd_value"] == "В2" and got[0]["rd_value"] == "В4")
    rows = [row("PD", "P1", 3, "301", "Кладовая", 10.0, "В2"), row("RD", "R1", 5, "301", "Кладовая", 10.0, "В2")]
    got, _ = rx.compare("OBJ-T", rows, names_of(rows))
    ok &= check("категория та же — гипотезы нет", not got)
    ok &= check("«0010», «010» и «10» — один номер; «1.01» не трогается",
                rx.norm_number("0010") == rx.norm_number("010") == "10" and rx.norm_number("1.01") == "1.01")
    rows = [row("PD", "P1", 3, "0010", "Тамбур-шлюз", 24.0), row("PD", "P1", 3, "0011", "Лестница", 25.8), row("PD", "P1", 3, "0012", "Венткамера", 83.2),
            row("RD", "R1", 5, "010", "Тамбур", 24.5), row("RD", "R1", 5, "011", "Лестница", 26.5), row("RD", "R1", 5, "012", "Венткамера", 99.7)]
    got, s = rx.compare("OBJ-T", rows, names_of(rows))
    ok &= check("проект пишет «0010», рабочая стадия «010» — помещения не пропали", not got and s["в обеих"] == 3, str(s))
    pd = [row("PD", "P1", 3, str(n), f"Кабинет {n}", 30.0) for n in range(401, 421)]
    rd = [row("RD", "R1", 5, str(n), f"Кабинет {n}", 30.0 if n % 2 else 20.0) for n in range(401, 421)]
    got, s = rx.compare("OBJ-T", pd + rd, names_of(pd + rd))
    ok &= check("десять уменьшений площади — одна запись на вид с перечнем помещений",
                len(got) == 1 and len(got[0]["locations"]) == 10 and s["площадь"] == 10, str((len(got), s["площадь"])))
    return ok


def test_category_same_name():
    print("\n4а. Категория сравнивается у одного помещения, а не у номера (#100)")
    # номер 2.3 носят разные помещения на разных уровнях: тех. этаж (В4) и машинное помещение (В3)
    rows = [row("PD", "P1", 1, "2.3", "Тамбур-шлюз с пожаробезопасной зоной", 18.17),
            row("PD", "P1", 2, "2.3", "Тех. помещение для прокладки коммуникаций", 640.77, "В4"),
            row("RD", "R1", 1, "2.3", "Тамбур-шлюз с пожаробезопасной зоной", 18.27),
            row("RD", "R1", 3, "2.3", "Машинное помещение", 34.34, "В3")]
    got, _ = rx.compare("OBJ-T", rows, names_of(rows))
    ok = check("категории чужих помещений под одним номером не сравниваются", "CATEGORY" not in kinds(got), str(kinds(got)))
    rows2 = [row("PD", "P1", 5, "123", "Электрощитовая", 11.3, "В4"), row("PD", "P1", 6, "123", "Электрощитовая", 11.3, "В4"),
             row("RD", "R1", 7, "123", "Электрощитовая", 11.3, "В4"), row("RD", "R2", 8, "123", "Электрощитовая", 11.3, "В3"),
             row("RD", "R3", 9, "123", "Электрощитовая", 11.3, "В3")]
    got, _ = rx.compare("OBJ-T", rows2, names_of(rows2))
    ok &= check("у одного помещения категория изменена — гипотеза", kinds(got) == ["CATEGORY"], str(kinds(got)))
    ok &= check("доказательства рабочей стадии — страницы с категорией В3, а не первые страницы номера",
                {(e["file_id"], e["pdf_page_number"]) for e in got[0]["evidence"] if e["stage"] == "RD"} == {("R2", 8), ("R3", 9)})
    return ok


def test_refusal():
    print("\n4. Отказ при перенумерации и без экспликаций")
    pd = [row("PD", "P1", 3, str(n), name, 10.0) for n, name in
          ((1, "Тепловой пункт"), (2, "Насосная"), (3, "Электрощитовая"), (4, "Венткамера"), (5, "Серверная"), (6, "Кладовая уборочного инвентаря"))]
    rd = [row("RD", "R1", 5, str(n), name, 9.0) for n, name in
          ((1, "Насосная"), (2, "Электрощитовая"), (3, "Венткамера"), (4, "Серверная"), (5, "Кладовая уборочного инвентаря"), (6, "Тепловой пункт"))]
    got, s = rx.compare("OBJ-T", pd + rd, names_of(pd + rd))
    ok = check("рабочая стадия сдвинула номера — отказ с причиной, гипотез нет", not got and s["отказ"] and "разные наименования" in s["отказ"], str(s["отказ"]))
    got, s = rx.compare("OBJ-T", pd, names_of(pd))
    ok &= check("экспликаций рабочей стадии нет — отказ", not got and s["отказ"] == "экспликаций нет в одной из стадий")
    return ok


def floor_rows(stage, file_id, page, table, rooms):
    return [dict(row(stage, file_id, page, n, name, a), table=table) for n, name, a in rooms]


FLOOR_1 = [("1", "Зона мойки", 165.05), ("2", "Зона выдачи", 69.10), ("3", "Тамбур", 17.32),
           ("21", "Инструментальная", 40.50), ("23", "Помещение", 19.41)]


def test_floors():
    """Поэтажная сверка: номера на каждом этаже с единицы, назначение сменилось при той же площади (#114)."""
    print("\n7. Поэтажная сверка экспликаций")
    ok = True
    for title, want in (("Спецификация помещений 1-го этажа", "1 этаж"), ("Экспликация помещений 2-го этажа", "2 этаж"),
                        ("Экспликация помещений антесольного этажа", "антресоль"),
                        ("Экспликация помещений ТЕХ.ЭТАЖА", "технический этаж"), ("Экспликация помещений", None)):
        ok &= check(f"этаж по заголовку «{title}»", rx.floor_of(title) == want, str(rx.floor_of(title)))
    pd = floor_rows("PD", "P1", 19, "Спецификация помещений 1-го этажа", FLOOR_1)
    # другой проект: те же номера, другие помещения — с ним рабочая стадия не сверяется
    other = floor_rows("PD", "P2", 18, "Экспликация помещений 1-го этажа",
                       [("1", "Склад", 300.0), ("2", "Офис", 20.0), ("3", "Тамбур", 9.0), ("23", "Кладовая", 5.0)])
    renamed = [("1", "Зона мойки", 165.88), ("2", "Зона выдачи", 70.27), ("3", "Тамбур", 17.02),
               ("21", "Инструментальная", 42.11), ("22", "Комната отдыха", 19.62)]
    rd = floor_rows("RD", "R2", 4, "Экспликация помещений 1-го этажа", renamed)
    # тот же этаж на другом листе тома — повтор, запись одна
    rd += floor_rows("RD", "R2", 8, "Экспликация помещений 1-го этажа", renamed)
    same = floor_rows("RD", "R1", 7, "Спецификация помещений 1-го этажа", FLOOR_1)
    code = {"P1": "2254266", "P2": "27121", "R1": "2254266", "R2": "2254266"}
    got, s = rx.compare_floors("OBJ-T", pd + other + rd + same, code)
    ok &= check("одна запись на этаж", len(got) == 1 and got[0]["locations"] == ["1 этаж"], str([g["locations"] for g in got]))
    if got:
        f = got[0]
        ok &= check("назначение изменено: «23 Помещение» → «22 Комната отдыха»",
                    "23 «Помещение»" in f["pd_value"] and "22 «Комната отдыха»" in f["rd_value"], f["rd_value"])
        ok &= check("доказательства — том проекта того же шифра и первый лист тома РД",
                    [(e["file_id"], e["pdf_page_number"]) for e in f["evidence"]] == [("P1", 19), ("R2", 4)],
                    str([(e["file_id"], e["pdf_page_number"]) for e in f["evidence"]]))
        ok &= check("том РД, повторяющий проект, назван", "R1 назначения прежние" in f["extraction"]["detail"])
        ok &= check("гипотеза, в сдачу не идёт", f["finding_status"] == "SUSPICION" and f["for_submission"] is False)
    ok &= check("том другого шифра не сверяется", s["пар томов"] == 2, str(s))
    # площадь другая — это не смена назначения, а другое помещение
    moved = floor_rows("RD", "R2", 4, "Экспликация помещений 1-го этажа", renamed[:4] + [("22", "Комната отдыха", 30.0)])
    got, _ = rx.compare_floors("OBJ-T", pd + moved, code)
    ok &= check("при другой площади смены назначения нет", not got, str(got))
    got, _ = rx.compare_floors("OBJ-T", pd + rd, {})
    ok &= check("без шифров томов поэтажной сверки нет", not got)
    # назначение задаёт раздел АР: том ОВ проекта того же шифра уже пишет «Комната отдыха»
    ov_pd = floor_rows("PD", "P3", 33, "Экспликация помещений 1-го этажа", renamed)
    ov_rd = floor_rows("RD", "R3", 3, "Экспликация помещений 1-го этажа", renamed)
    code3 = dict(code, P3="2254266", R3="2254266")
    sections = {"P1": "AR", "P2": "AR", "R1": "AR", "R2": "AR", "P3": "OV", "R3": "OV"}
    got, s = rx.compare_floors("OBJ-T", pd + ov_pd + rd + same + ov_rd, code3, sections=sections)
    detail = got[0]["extraction"]["detail"] if got else ""
    ok &= check("сверяются тома АР, запись одна", len(got) == 1 and s["сверено по АР"] == 1
                and [(e["file_id"], e["pdf_page_number"]) for e in got[0]["evidence"]] == [("P1", 19), ("R2", 4)], str(s))
    ok &= check("том ОВ проекта с назначением как в РД назван: проект сам с собой не согласен",
                "проекта того же шифра P3" in detail, detail)
    ok &= check("том РД не назван одновременно изменённым и прежним",
                "то же в томах" not in detail and "R1 назначения прежние" in detail and "R2 назначения прежние" not in detail, detail)
    return ok


def test_split_room():
    """Помещение разделено в рабочей стадии: площадь проекта сравнивается с суммой частей (#114)."""
    print("\n8. Помещение разделено на части")
    pd = [row("PD", "P1", 3, n, name, a) for n, name, a in
          (("001", "ИТП", 84.9), ("002", "Коридор", 62.9), ("003", "Тамбур", 9.7))]
    rd = [row("RD", "R1", 5, n, name, a) for n, name, a in
          (("001", "ИТП", 84.9), ("002", "Коридор", 39.3), ("002.1", "Коридор", 20.3), ("003", "Тамбур", 9.7))]
    got, s = rx.compare("OBJ-T", pd + rd, names_of(pd + rd))
    area = [g for g in got if "::AREA::" in g["finding_id"]]
    ok = check("уменьшение считается по сумме частей: 62,9 → 59,6",
               len(area) == 1 and area[0]["rd_value"] == "59.6 м²", str([g["rd_value"] for g in area]))
    ok &= check("в пояснении названы части", area and "002.1 — 20.3" in area[0]["extraction"]["detail"],
                area and area[0]["extraction"]["detail"])
    rd_same = [dict(r, area_m2=23.6) if r["number"] == "002.1" else r for r in rd]
    got, s = rx.compare("OBJ-T", pd + rd_same, names_of(pd + rd_same))
    ok &= check("части вместе дают проектную площадь — гипотезы нет",
                not [g for g in got if "::AREA::" in g["finding_id"]]
                and s["площадь: помещение разделено, сумма та же"] == 1, str(s))
    return ok


def test_places():
    print("\n9. Площадь — только в пределах одного места (Р-156)")
    home = "Корпус 1. Секция 1. Экспликация помещений 1-го этажа"
    parking = "Экспликация помещений автостоянки Кат."
    ok = check("место по заголовку: корпус, секция, этаж; автостоянка — часть здания",
               rx.place_of(home) == {"building": 1, "section": 1, "floor": "1 этаж"}
               and rx.place_of(parking) == {"part": "автостоянка"}
               and rx.place_of("Экспликация помещений") is None, str(rx.place_of(home)))

    def rows_for(pd_table, rd_tables):
        pd = [row("PD", "P1", 29, "6", "Тамбур-шлюз", 11.56, table=pd_table)]
        rd = [row("RD", f"R{i}", 8, "6", "Тамбур-шлюз", 4.53, table=t) for i, t in enumerate(rd_tables, 1)]
        return pd + rd
    # Полярная 17: номер 6 в проекте — в таблице корпуса и секции, в рабочей стадии — в таблицах автостоянки
    rows = rows_for(home, [parking, parking, parking])
    got, s = rx.compare("OBJ-T", rows, names_of(rows))
    ok &= check("проект — секция 1 на 1-м этаже, рабочая стадия — автостоянка: разные помещения, сверки нет",
                not got and s["площадь: в заголовках экспликаций разные места"] == 1, str(s))
    rows = rows_for(home, ["Экспликация помещений 2-го этажа. Секция 1"] * 2)
    got, _ = rx.compare("OBJ-T", rows, names_of(rows))
    ok &= check("этажи разные — сверки нет", not got)
    rows = rows_for(home, ["Экспликация помещений 1 этажа"] * 2)
    got, _ = rx.compare("OBJ-T", rows, names_of(rows))
    ok &= check("этаж тот же, секция названа только в проекте — сверка прежняя, гипотеза есть", kinds(got) == ["AREA"])
    rows = rows_for(home, ["Экспликация помещений", "Экспликация помещений"])
    got, _ = rx.compare("OBJ-T", rows, names_of(rows))
    ok &= check("место названо только в проекте — сверка прежняя, гипотеза есть", kinds(got) == ["AREA"])
    rows = rows_for(home, [parking, None, None])
    got, s = rx.compare("OBJ-T", rows, names_of(rows))
    ok &= check("у части строк рабочей стадии места нет — сверку не снимаем",
                kinds(got) == ["AREA"] and s["площадь: в заголовках экспликаций разные места"] == 0, str(s))
    return ok


def main():
    ok = True
    for fn in (test_missing, test_area, test_superseded, test_not_updated, test_category_and_numbers, test_category_same_name,
               test_refusal, test_floors, test_split_room, test_places):
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
