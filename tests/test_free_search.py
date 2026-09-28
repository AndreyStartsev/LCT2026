"""Проверка свободного поиска: предусмотрено проектом для помещений — нет в рабочей документации. Задача #31.

  python tests/test_free_search.py

Тексты синтетические, кроме одной фразы Тюменской-5 (том ИОС5.4.2, F0171, стр. 11),
с которой правило и началось. Проверяется не только находка, но и молчание: гипотеза
без основания хуже пропуска, потому что отнимает время инспектора.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import free_search as fs  # noqa: E402

# Тюменская-5, F0171, стр. 11
TYUMEN = ("Все применяемые приборы должны быть выполнены в травмобезопасном исполнении. "
          "В помещениях раздевальных, санузлов и душевых для МГН (пом. 267, 270, 271, 272) "
          "предусмотрена система подогрева полов (теплые полы) совмещенная с системой "
          "радиаторного отопления. Регулирование температуры пола осуществляется регуляторами.")


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def run(pd_text, rd_texts, pd_section="OV", rd_section="OV", extra_pd=()):
    pd = [("P1", 11, pd_text, pd_section)] + [("P1", n, t, pd_section) for n, t in extra_pd]
    rd = [("R1", i + 1, t, rd_section) for i, t in enumerate(rd_texts)]
    return fs.search("OBJ-X", pd, rd)


RD_ROOMS = ("Экспликация помещений 2 этажа 267 Раздевальная для МГН 12.4 270 Санузел для МГН 5.0 "
            "271 Раздевальная для МГН 12.4 272 Душевая для МГН 4.1 Радиаторы стальные панельные")


def test_clauses():
    ok = True
    got = fs.clauses(TYUMEN)
    ok &= check("фраза проекта разобрана: помещения и элемент",
                len(got) == 1 and got[0]["rooms"] == ["267", "270", "271", "272"]
                and got[0]["element"].startswith("система подогрева полов"), str(got)[:120])
    cases = [
        ("задание на проектирование — требование, а не решение",
         "Все вентустановки (пом. 12, 14) должны быть предусмотрены с устройствами защиты от замерзания."),
        ("предусмотрено само помещение, а не элемент в нём",
         "Для подметальных машин предусмотрено помещение уборочной техники (пом. 23) на минус первом этаже."),
        ("процесс элементом не считается",
         "В помещении горячего цеха (пом. 189) предусматривается поддержание температуры воздуха +12."),
        ("номер раздела задания — не помещение",
         "транзиты через прочие помещения 0 Общие требования Все установки предусмотрены с системой защиты."),
        ("неопределённая форма — язык задания",
         "В серверной (пом. 14) предусмотреть систему кондиционирования с резервированием."),
    ]
    for name, text in cases:
        got = fs.clauses(text)
        ok &= check(name, got == [], str(got)[:100])
    got = fs.clauses("В помещении №14 (серверная) на первом этаже устанавливается шкаф телекоммуникационный 19 дюймов.")
    ok &= check("полное слово со знаком номера разбирается",
                len(got) == 1 and got[0]["rooms"] == ["14"] and "шкаф" in got[0]["element"], str(got)[:100])
    return ok


def test_element_matching():
    ok = True
    pats = fs.element_terms("система подогрева полов (теплые полы) совмещенная с системой отопления")
    for text, expected in (("Регулятор для системы “теплый пол” Multibox C/RTL", True),
                           ("устройство тёплого пола в санузлах", True),
                           ("подогрев пола электрический", True),
                           ("теплоноситель подаётся в полотенцесушитель", False),
                           ("выполнить заполнение системы теплоносителем", False)):
        got = fs.mentions(text.lower(), pats)
        ok &= check(f"«{text[:45]}» → {'назван' if expected else 'не назван'}", got == expected)
    return ok


def test_hypothesis():
    ok = True
    found, stats = run(TYUMEN, [RD_ROOMS])
    ok &= check("элемента нет в рабочей документации — одна гипотеза на четыре помещения",
                len(found) == 1 and found[0]["locations"] == ["267", "270", "271", "272"], str(stats))
    f = found[0]
    ok &= check("гипотеза вне Матрицы, для специалиста",
                f["matrix_scope"] == "FREE_SEARCH" and f["finding_status"] == "SUSPICION"
                and f["needs_expert"] and f["comparison_result"] == "MISSING_DESIGN_ELEMENT")
    stages = {(e["stage"], e["file_id"], e["pdf_page_number"]) for e in f["evidence"]}
    ok &= check("доказательства обеих стадий: фраза проекта и лист, где помещение названо",
                ("PD", "P1", 11) in stages and ("RD", "R1", 1) in stages, str(sorted(stages)))

    drawn = "Схема системы отопления 267, 270 Раздевальная Регулятор для системы “теплый пол” 271, 272"
    found, _ = run(TYUMEN, [RD_ROOMS], extra_pd=[(99, drawn)])
    stages = {(e["stage"], e["pdf_page_number"]) for e in found[0]["evidence"]}
    ok &= check("лист проекта, где элемент показан рядом с помещениями, тоже в доказательствах",
                ("PD", 99) in stages, str(sorted(stages)))
    return ok


def test_silence():
    ok = True
    found, stats = run(TYUMEN, [RD_ROOMS + " В санузлах МГН выполнить тёплый пол с регулятором RTL."])
    ok &= check("элемент назван в рабочей документации — гипотезы нет",
                found == [] and stats.get("элемент назван в рабочей документации") == 1, str(stats))
    found, stats = run(TYUMEN, [RD_ROOMS], rd_section="VK")
    ok &= check("раздела нет в рабочей документации — «элемента нет» ничего не значит",
                found == [] and stats.get("раздела нет в рабочей документации") == 1, str(stats))
    found, stats = run(TYUMEN, ["Экспликация помещений 1 этажа 101 Тамбур 8.6 102 Вестибюль 134.0"])
    ok &= check("рабочая документация этих помещений не называет — сравнивать не с чем",
                found == [] and stats.get("адрес не назван в рабочей документации раздела") == 1, str(stats))
    found, stats = run(TYUMEN, [])
    ok &= check("рабочей документации с текстом нет — гипотезы нет", found == [], str(stats))
    found, stats = run(TYUMEN, [RD_ROOMS], pd_section="OTHER")
    ok &= check("раздел проектного тома не определён — проверить нечем", found == [], str(stats))
    return ok


def test_matrix_flag():
    """Перенос в MATRIX по эмбеддингам — только по флагу (#79, Р-127): модель есть, флага нет."""
    from pipeline import matrix_map as mm
    ok = True
    saved = mm._onnx_available, mm.classify, fs.MATRIX_BY_EMBEDDINGS
    mm._onnx_available = lambda: True          # веса есть и загрузились
    mm.classify = lambda *a, **k: {"matrix_scope": "MATRIX", "parameter_code": "IOS4-077",
                                   "parameter_id": 77, "criticality": "Критическое (приостановка работ)",
                                   "needs_expert": True}
    try:
        fs.MATRIX_BY_EMBEDDINGS = False
        f = run(TYUMEN, [RD_ROOMS])[0][0]
        ok &= check("модель есть, флага нет — гипотеза остаётся вне Матрицы",
                    f["matrix_scope"] == "FREE_SEARCH" and f["parameter_code"] == "FREE-OV-DESIGN-ELEMENT",
                    f"{f['matrix_scope']} {f['parameter_code']}")
        fs.MATRIX_BY_EMBEDDINGS = True
        f = run(TYUMEN, [RD_ROOMS])[0][0]
        ok &= check("FREE_SEARCH_MATRIX=1 — перенос по ответу classify()",
                    f["matrix_scope"] == "MATRIX" and f["parameter_code"] == "IOS4-077",
                    f"{f['matrix_scope']} {f['parameter_code']}")
    finally:
        mm._onnx_available, mm.classify, fs.MATRIX_BY_EMBEDDINGS = saved
    return ok


# Адресация не номером помещения: в корпусе она встречается в 10–100 раз чаще (#96)
NAMED = "В венткамерах приточных систем предусмотрены трапы в стяжке пола для отвода стоков."
FLOOR = "На 3 этаже в осях 1-4 установлены шкафы пожарных краников с ручными пожарными извещателями."
ROOF = "По кровле предусмотрена система молниезащиты с токоотводами по парапету."
ELEMENT = "В фундаментной плите предусмотрены приямки с насосами для откачки аварийных стоков."
FAR = ("Мусороудаление выполнено по фасадам здания. В соответствии с заданием на проектирование "
       "предусмотрена система мусороудаления с клапанами на этажах.")


def test_address_forms():
    """Адресация шире номера помещения: название помещения, этаж, конструкция."""
    ok = True
    for text, kind, location, location_type in (
            (NAMED, "название", "венткамеры", "ROOM"),
            (FLOOR, "этаж", "3 этаж", "SECTION"),
            (ROOF, "этаж", "кровля", "SECTION"),
            (ELEMENT, "конструкция", "Фундаментная плита", "CONSTRUCTION_ELEMENT")):
        got = fs.clauses(text)
        address = got[0]["address"] if got else {}
        ok &= check(f"«{text[:40]}…» → {kind}: {location}",
                    len(got) == 1 and address.get("kind") == kind
                    and address.get("locations") == [location]
                    and address.get("location_type") == location_type, str(got)[:140])
    got = fs.clauses("В венткамере на кровле предусмотрена система обогрева воздуховодов.")
    ok &= check("побеждает ближайший к глаголу адрес",
                got and got[0]["address"]["locations"] == ["кровля"], str(got)[:120])
    got = fs.clauses(FAR)
    ok &= check("адрес из соседнего предложения не берётся: «фасады» здесь не про мусороудаление",
                got == [], str(got)[:140])
    got = fs.clauses("Насосной станцией предусмотрен из приямка выход в коридор с лотком.")
    ok &= check("предусмотренное с предлога — это разбор зацепил не то", got == [], str(got)[:120])
    got = fs.clauses("В помещении №14 (серверная) устанавливается шкаф телекоммуникационный 19 дюймов.")
    ok &= check("номер помещения не удваивается адресацией по названию",
                len(got) == 1 and got[0]["address"]["kind"] == "номер", str(got)[:140])
    return ok


def test_hypothesis_by_name():
    """Гипотеза по названию помещения: рабочая документация про венткамеры говорит, трапов нет."""
    rd = "План 2 этажа. Венткамера приточной системы П1. Воздуховоды, клапаны КПУ-1М."
    found, stats = run(NAMED, [rd])
    ok = check("одна гипотеза, локация — название помещения",
               len(found) == 1 and found[0]["locations"] == ["венткамеры"]
               and found[0]["location_type"] == "ROOM", str(stats))
    if found:
        ok &= check("в пояснении сказано, какой адресацией найдено",
                    (found[0]["extraction"] or {}).get("address") == "название",
                    str((found[0]["extraction"] or {}).get("detail"))[:120])
    found, stats = run(NAMED, ["План 2 этажа. Трапы в стяжке пола венткамеры, отвод стоков самотёком."])
    ok &= check("элемент назван в рабочей документации — гипотезы нет", found == [], str(stats))
    found, stats = run(NAMED, ["План 2 этажа. Насосная станция, приямок, лотки."])
    ok &= check("рабочая документация венткамеры не называет — сравнивать не с чем",
                found == [] and stats.get("адрес не назван в рабочей документации раздела") == 1, str(stats))
    return ok


def test_named_otherwise():
    """Элемент есть в РД, но назван иначе, чем в проекте (Полярная 17, #229): гипотезы нет."""
    ok = True
    # обозначение системы: в РД оно стоит в схеме щита, а не в словах проекта
    pd = "Дымоудаление из автостоянки предусматриваются самостоятельной системами ДУ1, ДУ2. Расход продуктов горения"
    rd_park = "План автостоянки на отм. -3.300. Автостоянка, рампа, тамбур-шлюз"
    found, stats = run(pd, [rd_park, "Щит управления вентилятором ДУ1 щит управления вентилятором КДУ1"])
    ok &= check("ДУ1 назван в РД — система есть", found == [], str(stats))
    found, stats = run(pd, [rd_park, "Щит управления вентилятором КДУ1"])
    ok &= check("КДУ1 — не ДУ1: гипотеза остаётся", len(found) == 1, str(stats))
    found, stats = run(pd, [rd_park, "Ведомость дверей Д-1 Д-2 2000 2040 ДУ-1 2600 2040"])
    ok &= check("марка двери «ДУ-1» в ведомости — не система: гипотеза остаётся", len(found) == 1, str(stats))
    # происхождение и марка — не имя элемента
    pd = ("В качестве отопительных приборов лестничных клеток, вестибюлей и других МОПов установлены конвекторы "
          "отечественного производства. Отопительные приборы")
    found, stats = run(pd, ["Вестибюль 1 этажа. Конвектор Tepla Neo Expo нижнее подключение"])
    ok &= check("«отечественного производства» не ищется — одно слово «конвекторы» гипотезы не даёт",
                found == [], str(stats))
    # определение перед головным словом РД может не повторить
    pd = ("В качестве материала вторичной защиты плит ростверков, наружных стен и плиты покрытия предусмотрена "
          "оклеечная гидроизоляция из наплавляемого материала, в два слоя по огрунтованной поверхности.")
    rd_kr = "Ростверк. Ростверки жилого дома — монолитные железобетонные плиты толщиной 1000 мм"
    found, stats = run(pd, [rd_kr, "Гидроизоляция стен рулонным наплавляемым материалом по праймеру"],
                       pd_section="KR", rd_section="KR")
    ok &= check("«гидроизоляция … наплавляемым» в РД — элемент назван", found == [], str(stats))
    found, stats = run(pd, [rd_kr, "Обмазочная гидроизоляция санузлов"], pd_section="KR", rd_section="KR")
    ok &= check("другая гидроизоляция — гипотеза остаётся", len(found) == 1, str(stats))
    return ok


def test_instruction_and_section():
    """Указание — не элемент; элемент чужого раздела ищется в РД своего раздела (#229)."""
    ok = True
    ok &= check("«выполнить до щита механизации» — не элемент",
                not fs._element_ok("выполнить до щита механизации, устанавливаемого в каждом блоке", ""))
    ok &= check("«щиты механизации» — элемент", fs._element_ok("щиты механизации в каждом блоке", ""))
    ok &= check("ВРУ из тома КР — раздел электрики",
                fs.element_section("вводно- распределительные устройства типа ВРУ, щиты", "KR") == "EOM")
    ok &= check("тёплые полы — раздел тома", fs.element_section(
        "система подогрева полов (теплые полы) совмещенная с системой", "OV") == "OV")
    # Октябрьская: ВРУ названы в томе КР, а РД — одни КЖ: сравнивать не с чем, гипотезы нет
    pd = ("Электрощитовые располагаются на -1-ом этаже. В электрощитовой устанавливаются вводно- распределительные "
          "устройства типа ВРУ, щиты распределительные и щиты освещения.")
    found, stats = run(pd, ["План -1 этажа. Электрощитовая, венткамера. Армирование стен"],
                       pd_section="KR", rd_section="KR")
    ok &= check("в РД нет электрики — гипотезы нет", found == [] and stats.get("раздела нет в рабочей документации") == 1,
                str(stats))
    return ok


def main():
    ok = True
    for title, fn in (("Фразы проекта", test_clauses), ("Название элемента в тексте", test_element_matching),
                      ("Формы адресации", test_address_forms), ("Гипотеза", test_hypothesis),
                      ("Гипотеза по названию помещения", test_hypothesis_by_name),
                      ("Когда правило молчит", test_silence),
                      ("Элемент назван в РД иначе", test_named_otherwise),
                      ("Указание и раздел элемента", test_instruction_and_section),
                      ("Сопоставление с Матрицей по флагу", test_matrix_flag)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
