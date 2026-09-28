"""Проверка стадии, марки, раздела и цепочек редакций. Задача #10.

  python tests/test_revisions.py

Имена файлов взяты из корпуса как есть, слова таблиц изменений — с настоящих страниц
Речникова и Октябрьской. У каждой проверки написано, какую ошибку она ловит: почти
каждая из них случилась при разработке на одном из шести объектов. PDF не нужны.
"""
import collections
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import revisions as rv  # noqa: E402
from pipeline import titleblock  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def w(t, x0, y0, x1, y1):
    return {"t": t, "bbox": [x0, y0, x1, y1]}


def code(name):
    return rv.parse_code(rv.parse_name(name)["rest"])


# ---------------------------------------------------------------- отметки в имени

def test_name_markers():
    ok = True
    p = rv.parse_name("АНО-150321-1-РД-ОВ1 изм. 4_в1 (1).pdf")
    ok &= check("«изм. 4_в1»: подчёркивание не мешает, прежнее \\b его не видело",
                p["change"] == 4 and p["version"] == 1 and p["copy_suffix"] == [1], str(p["change"]))
    p = rv.parse_name("01-0722-14-П-ИОС2.3-кор.3_Корр. 1.pdf")
    ok &= check("«кор.3_Корр. 1» — корректировка 3, подкорректировка 1",
                (p["correction"], p["correction_sub"]) == (3, 1))
    # Речников F0281, F0283, F0285: исходные тома 2022 года, на титуле шифр без «кор»
    p = rv.parse_name("01-0722-14-П-ИОС3.2_К1.pdf")
    ok &= check("«ИОС3.2_К1» — бытовая канализация К1, а не корректировка 1",
                p["correction"] is None and code(p["stem"])["mark"] == "ИОС3.2"
                and code(p["stem"])["part"] is None, str(p["correction"]))
    p = rv.parse_name("01-0722-14-П-ИОС2.3_В1.pdf")
    ok &= check("«ИОС2.3_В1» — водопровод В1, а не версия 1",
                p["version"] is None and code(p["stem"])["mark"] == "ИОС2.3", str(p["version"]))
    p = rv.parse_name("5.2. 245-0817-КМ-2_Н-3-ИОС2.1 17.04.2025 в2.pdf")
    ok &= check("строчная «в2» после даты — версия 2", p["version"] == 2, str(p["version"]))
    p = rv.parse_name("01-0723-14-РД-К1-КЖ1_Изм.3.pdf")
    ok &= check("«К1-» перед маркой — корпус, а не корректировка",
                p["correction"] is None and p["change"] == 3)
    p = rv.parse_name("23.009-ПОС1_корр.ГИП (1).pdf")
    ok &= check("«корр.ГИП» — корректировка главного инженера проекта", p["gip"] and p["correction"] is None)
    p = rv.parse_name("ИЗМ ПО ЗАМЕЧАНИЯ АНО1503211-П-АР.pdf")
    ok &= check("«ИЗМ ПО ЗАМЕЧАНИЯ» с опечаткой — переиздание, а не «изм» без номера",
                p["by_comments"] and p["change"] is None)
    p = rv.parse_name("23.009-Р-1-КЖ1.2_ред_2024-04-08_Вер5_Изм1.pdf")
    ok &= check("«ред_2024-04-08_Вер5_Изм1»: дата не становится версией",
                p["dates"] == ["2024-04-08"] and p["version"] == 5 and p["change"] == 1, str(p["dates"]))
    p = rv.parse_name("245-0817-КМ-2-Н-3-КЖ2(1)(1).1(Изм.1) ЭЦПЭЦП 08.04.2026.pdf")
    ok &= check("«КЖ2(1)(1).1(Изм.1)»: копии удаляются, марка КЖ2.1 цела",
                p["change"] == 1 and "E_SIGNATURE" in p["approval"] and code(p["stem"])["mark"] == "КЖ2.1",
                str(code(p["stem"])["mark"]))
    p = rv.parse_name("01_07_23_14_РД _КЖ7_Изм.1.pdf")
    ok &= check("«01_07_23_14» — шифр проекта, а не 1 июля 2023", p["dates"] == [], str(p["dates"]))
    p = rv.parse_name("5.4. Раздел ЖС-РЛ-0624-2024-П-ИОС4 13022025.pdf")
    ok &= check("дата без разделителей «13022025»", p["dates"] == ["2025-02-13"], str(p["dates"]))
    p = rv.parse_name("10-26_КЖ03.1.3_(Июнь 2026) 9_ Несущие конструкции.pdf")
    ok &= check("месяц словом «(Июнь 2026)»", p["month_date"] == "2026-06")
    p = rv.parse_name("1. Раздел 1 ЖС-РД-270121-П-ОПЗ 2024.pdf")
    ok &= check("хвост « 2024» у побайтовой копии не дата и не редакция",
                p["year_suffix"] == 2024 and p["dates"] == [])
    p = rv.parse_name("7. ТР снос Алтуфьевское ш 79Б корр.pdf")
    ok &= check("«корр» без номера — корректировка", p["generic_correction"])
    p = rv.parse_name("V2_01-03-00-01-20_Том 3.РЕД.pdf")
    ok &= check("«V2_» и «.РЕД» записываются, но редакцией не считаются",
                p["package_version"] == 2 and p["edited"] and rv.revision_label(p) is None)
    p = rv.parse_name("5.1. П-2025-04.266-ИОС1.1 от (27.4.2026).pdf")
    ok &= check("дата с однозначным месяцем в скобках", p["dates"] == ["2026-04-27"])
    return ok


# ---------------------------------------------------------------- шифр и марка

def test_names_outside_corpus():
    """Имена не из корпуса: латинские отметки, чужие форматы дат, имена без отметок (#10, #41)."""
    ok = True
    p = rv.parse_name("01-24-П-АР_v2.pdf")
    ok &= check("«_v2» — версия 2", p["version"] == 2 and p["rest"] == "01-24-П-АР", str(p["rest"]))
    ok &= check("«ver 3», «version 3» — версия", rv.parse_name("АР ver 3.pdf")["version"] == 3
                and rv.parse_name("АР version 3.pdf")["version"] == 3)
    ok &= check("«Rev.2» — изменение 2, «rev.B» — второе по буквам",
                rv.parse_name("АР Rev.2.pdf")["change"] == 2 and rv.parse_name("АР rev.B.pdf")["change"] == 2
                and rv.parse_name("АР Rev A.pdf")["change"] == 1)
    ok &= check("«Revised», «review», марка «В2» в шифре — не отметки",
                rv.parse_name("Revised plan.pdf")["change"] is None and rv.parse_name("review.pdf")["change"] is None
                and rv.parse_name("01-24-П-ВК_В2.pdf")["version"] is None)
    ok &= check("пакет организатора «V2_…» — версия пакета, а не редакция",
                rv.parse_name("V2_01-05-04-02-07_Том 5.4.2 ОВ (1).pdf")["package_version"] == 2
                and rv.parse_name("V2_01-05-04-02-07_Том 5.4.2 ОВ (1).pdf")["version"] is None)
    def marked(name):                     # как в analyse: отметка изменения из имени действует
        p = rv.parse_name(name)
        p["change_effective"] = p["change"]
        return p
    ok &= check("порядок латинских отметок: rev.2 позже rev.1, v3 позже v2 при равных изменениях",
                rv.compare(marked("АР rev.1.pdf"), marked("АР rev.2.pdf")) < 0
                and rv.compare(marked("АР rev.2 v2.pdf"), marked("АР rev.2 v3.pdf")) < 0)
    ok &= check("имя без отметок и дат — редакция не определена, а не нулевая",
                rv.revision_label(rv.parse_name("Пояснительная записка.pdf")) is None)
    ok &= check("дата в чужом формате «08.04.25» и ISO «2025-04-08» — одна дата",
                rv.parse_name("АР 08.04.25.pdf")["dates"] == ["2025-04-08"]
                and rv.parse_name("АР 2025-04-08.pdf")["dates"] == ["2025-04-08"])
    return ok


def test_marks():
    ok = True
    c = code("АНО1503211-П-ПЗУ.pdf")
    ok &= check("шифр Тюменской: марка, стадия, основа шифра",
                (c["mark"], c["stage_token"], c["code_base"]) == ("ПЗУ", "PD", "153211"), str(c))
    c = code("01-0723-14-РД-К2 -КЖ5.1.pdf")
    ok &= check("«К2 -КЖ5.1»: корпус отдельно, марка без пробела", (c["part"], c["mark"]) == ("К2", "КЖ5.1"))
    c = code("23.009-Р-1-КЖ0.3_С1_Плита техэт на отм. -2,170 (1).pdf")
    ok &= check("марка до описания листа, «С1» — секция, а не марка",
                (c["mark"], c["section_part"]) == ("КЖ0.3", "С1"), str(c["mark"]))
    ok &= check("«КР4.РР» — отдельная марка, а не КР4", code("01-0722-14-П-КР4.РР-кор2.pdf")["mark"] == "КР4.РР")
    ok &= check("«ИОС 4.4 ТС» — ИОС4.4", code("01-07.22-14-П-ИОС 4.4 ТС.pdf")["mark"] == "ИОС4.4")
    ok &= check("неизвестная марка в конце шифра, а не «ОК» из шифра проекта",
                code("12. 245-0817-КМ-2Н-3-ЗСГО (26.03.2025).pdf")["mark"] == "ЗСГО")
    c = code("V2_01-05-04-02-07_Том 5.4.2 ОВ (1).pdf")
    ok &= check("номер тома важнее «ОВ» после него", c["mark"] == "ТОМ5.4.2" and c["descriptors"] == ["ОВ"])
    ok &= check("книга тома входит в ключ: Книга 1 и Книга 3 — разные документы",
                code("01-01-00-02-19_Том 1.2_Книга 1.pdf")["part"] == "КН1")
    ok &= check("«фундаменты под» строчными — не марка ПОД",
                code("! папка 30 - 7.7 - aocp - k1.2 - кукушки, парапет, брс, фундаменты под.pdf")["mark"] is None)
    ok &= check("пометка в скобках «(ВП)» не марка", code("17_ПД-25-КР (ВП).pdf")["mark"] == "КР")
    ok &= check("«СОШ» без шифра перед ним не марка",
                code("V2_Расценка Перечень СОШ на 600 мест.pdf")["mark"] is None)
    ok &= check("синоним: МОДИ и ОДИ — одна марка", code("23.009-МОДИ.pdf")["mark"] == "ОДИ")
    ok &= check("шифр из штампа с частями через слеш",
                rv.mark_from_code("АНО/150321/1-П-ИОС5.4.2-СТ") == "ИОС5.4.2")
    return ok


# ---------------------------------------------------------------- стадия и раздел

def test_stage():
    """Стадию и раздел даёт правило реестра (`pipeline/registry.py`), модуль редакций его вызывает."""
    ok = True
    ok &= check("«рд» в шифре «ЖС-РД-270121-П» не рабочая стадия: 37 файлов Алтуфьевского",
                rv.detect_stage("Проектная документация/1. Раздел 1 ЖС-РД-270121-П-ОПЗ.pdf")[0] == "PD")
    ok &= check("«ид» внутри слова не исполнительная стадия",
                rv.detect_stage("Проектная документация/5.3. Гидроизоляция/видовые.pdf")[0] == "PD")
    ok &= check("смешанная папка организатора",
                rv.detect_stage("Рабочая и исполнительная документация/Полные разделы/АНО-150321-1-РД-ОВ1.pdf")[0]
                == "RD_ID_MIXED")
    ok &= check("«Стадия РД» Новослободской",
                rv.detect_stage("Новослободская/Стадия РД/НСЛ-17-02.2026-1_2-КЖ1.1.4.pdf")[0] == "RD")
    ok &= check("короткая папка «ИД»", rv.detect_stage("ИД/! 4 этаж.pdf")[0] == "ID")
    ok &= check("без папки: акт — исполнительная", rv.detect_stage("АОСР № 52 от 20.04.2026.pdf")[0] == "ID")
    ok &= check("без папки: стадия по шифру", rv.detect_stage("01-0722-14-П-КР1.pdf")[0] == "PD")
    ok &= check("чужие названия папок: «Том 1 ПД», «Раздел 3. РД», «Проект», латиница",
                rv.detect_stage("Том 1 ПД/х.pdf")[0] == "PD" and rv.detect_stage("Раздел 3. РД/х.pdf")[0] == "RD"
                and rv.detect_stage("Проект/х.pdf")[0] == "PD" and rv.detect_stage("RD/х.pdf")[0] == "RD")
    ok &= check("ничего не названо — «не определено», а не догадка",
                rv.detect_stage("Материалы/книга.pdf") == ("UNKNOWN", None))
    ok &= check("смешанный файл: акт уходит в ИД, комплект в РД",
                rv.stage_group("RD_ID_MIXED", "АОСР №1-ОВ2.1 от 20.12.2024.pdf") == "ID"
                and rv.stage_group("RD_ID_MIXED", "АНО1503211-РД-ВК изм. 2_в1.pdf") == "RD")
    return ok


def test_section():
    ok = True
    sec = lambda path, stage=None: rv.detect_section(path, code(path), stage)[0]
    ok &= check("ИОС5.4.2 — отопление", sec("Х-П-ИОС5.4.2.pdf") == "OV")
    ok &= check("ИОС4.1 — отопление по номеру подраздела", sec("НВС-2025.03-ИОС4.1.pdf") == "OV")
    ok &= check("«ИОС5.1» без номера подраздела рядом — раздел не определён (#41), а не связь по догадке",
                sec("НВС-2025_03-ИОС5.1.pdf") == "OTHER")
    ok &= check("Алтуфьевское: «5.2. …ИОС5.2» — водоснабжение по номеру подраздела в папке",
                sec("Проектная документация/5.2. Раздел 5.2 ЖС-РД-270121-П-ИОС5.2 2024.pdf") == "VK")
    ok &= check("хвост «ПЗ» в «ПБ9.1.ПЗ» — тип документа, раздел пожарный",
                rv.detect_section("Х.pdf", {"mark": "ПБ9.1.ПЗ"})[0] == "PB")
    ok &= check("«НС.ЭОМ» — электрика насосной станции", rv.detect_section("Х.pdf", {"mark": "НС.ЭОМ"})[0] == "EOM")
    ok &= check("марка из штампа — запасной источник, путь сильнее",
                rv.detect_section("РД/ОВ/лист.pdf", {"mark": "ЭОМ"}) == ("OV", "PATH")
                and rv.detect_section("акт.pdf", {"mark": "КЖ2"}) == ("KR", "MARK"))
    ok &= check("«ИД Ривер Парк … электроснабжение» — не «исходные данные»",
                sec("ИД/ИД Ривер Парк 7.7 Внутреннее электроснабжение №1ЭМ Февраль-Апрель.pdf") == "EOM")
    ok &= check("номер папки «1.» в рабочей стадии не раздел 1 по ПП 87, марка папки «ГП»",
                sec("РД/1. ГП/Ответы на замечания Заказчика_14.docx", stage="RD") == "GP")
    return ok


# ---------------------------------------------------------------- сравнение редакций

def n(name, tb=None):
    p = rv.parse_name(name)
    marked = any(p[k] for k in ("change", "correction", "version", "by_comments", "gip",
                                "generic_correction", "dates"))
    p["change_titleblock"] = tb
    p["change_effective"] = p["change"] if marked else tb
    return p


def test_compare():
    ok = True
    ok &= check("исходный том раньше «кор3»", rv.compare(n("Х-ОДИ.pdf"), n("Х-ОДИ-кор3.pdf")) == -1)
    ok &= check("«Изм 2» и «кор3» не сравниваются", rv.compare(n("Х-ОПЗ Изм 2.pdf"), n("Х-ОПЗ-кор3.pdf")) is None)
    ok &= check("исходный том с обозначением системы раньше «кор.3_Корр. 1»",
                rv.compare(n("Х-ИОС2.3-кор.3_Корр. 1.pdf"), n("Х-ИОС2.3_В1.pdf")) == 1)
    ok &= check("версия ниже корректировки: «кор3» позже «в2»",
                rv.compare(n("Х-ИОС2.1-кор3.pdf"), n("Х-ИОС2.1 в2.pdf")) == 1)
    ok &= check("датированный исходник раньше «кор3»",
                rv.compare(n("1-07_22-14-П-ИОС1.3_20.12.2022.pdf"), n("01-07_22-14-П-ИОС1.3-кор3.pdf")) == -1)
    ok &= check("без отметок порядок по дате",
                rv.compare(n("Х-КР1_13.05.25.pdf"), n("Х-КР1_08.04.25.pdf")) == 1)
    ok &= check("отметки и даты противоречат — не сравнить",
                rv.compare(n("Х-АР изм 3 от 01.01.2024.pdf"), n("Х-АР изм 2 от 01.01.2025.pdf")) is None)
    ok &= check("номер из штампа работает, когда в имени отметок нет",
                rv.compare(n("Х-КЖ1.pdf", tb=2), n("Х-КЖ1.pdf", tb=1)) == 1)
    ok &= check("номер из штампа не спорит с «кор» из имени: у томов «кор3» своя нумерация изменений",
                rv.compare(n("Х-АР1-кор3.pdf", tb=19), n("Х-АР1кор2.pdf", tb=1)) == 1
                and n("Х-АР1-кор3.pdf", tb=19)["change_effective"] is None)
    return ok


# ---------------------------------------------------------------- цепочки

def doc(fid, path, pages=10, stage=None, sha=None, **extra):
    row = {"file_id": fid, "object_id": "OBJ-X", "stage": stage or rv.detect_stage(path)[0],
           "section": "OTHER", "relative_path": path, "sha256": sha or (fid * 16)[:64],
           "pdf_pages": pages, "extension": os.path.splitext(path)[1].lower(), "id_source": "LOCAL",
           "approval_status": "UNKNOWN"}
    row.update(extra)
    return row


def chains_by_mark(chains):
    return {(c["stage_group"], c["mark"]): c for c in chains}


def test_chains():
    ok = True
    docs = [
        doc("L0001", "ПД/2 Схема/01-07.22-14-П-ПЗУ.pdf", 20),
        doc("L0002", "ПД/2 Схема/01-07.22-14-П-ПЗУ_кор1.pdf", 21),
        doc("L0003", "ПД/2 Схема/01-07.22-14-П-ПЗУ-кор.3(1).pdf", 25),
        doc("L0004", "ПД/1 ПЗ/01-07-22-14-П-ОПЗ.pdf", 26),
        doc("L0005", "ПД/1 ПЗ/01-07-22-14-П-ОПЗ Изм 2.pdf", 29),
        doc("L0006", "ПД/1 ПЗ/01-07-22-14-П-ОПЗ-кор3.pdf", 71),
        doc("L0007", "ПД/6 ПОС/01-07-22-П-14-ПОС-кор3.pdf", 67),
        doc("L0008", "ПД/6 ПОС/01-0722-14-П-ПОС-кор3.pdf", 67),
        doc("L0009", "РД/К1-КЖ4.2/01-0723-14-РД-К1-КЖ4.2.pdf", 20),
        doc("L0010", "РД/К1-КЖ4.2/К1-КЖ4.2 Лист 6/01-0723-14-РД-К1-КЖ4.2_6.pdf", 1),
        doc("L0011", "Проектная документация/6. П-2025-04-266-ПОС2 (Изм. 1).pdf", 50),
        doc("L0012", "Проектная документация/6. Раздел 6 ЖС-РД_270121_П_ПОС2.pdf", 43),
        doc("L0013", "ИД/АОСР №1 от 01.02.2026.pdf", 2),
        doc("L0014", "ИД/АОСР №1 от 01.02.2026 (1).pdf", 2),
        doc("L0015", "РД/П_КЖ1_Изм.1.docx", 1),
        doc("L0016", "РД/01-0723-14-РД-КЖ1.pdf", 14),
        doc("L0017", "ПД/1 ПЗ/01-07-22-14-П-ОПЗ copy.pdf", 26, sha=("L0004" * 16)[:64],
            duplicate_of="L0004"),
    ]
    out, chains = rv.analyse("OBJ-X", docs)
    by = chains_by_mark(chains)
    rows = {r["file_id"]: r for r in out if not r.get("duplicate_of")}

    c = by[("PD", "ПЗУ")]
    ok &= check("исходник, кор1, кор3: актуальна кор3, порядок и связи",
                c["status"] == "RESOLVED" and c["current_file_id"] == "L0003"
                and c["order"] == ["L0001", "L0002", "L0003"]
                and rows["L0003"]["predecessor_file_id"] == "L0002"
                and rows["L0001"]["successor_file_id"] == "L0002", str(c.get("order")))
    ok &= check("устаревшие редакции помечены", rows["L0001"]["revision_status"] == "SUPERSEDED")

    c = by[("PD", "ПЗ")]
    ok &= check("«Изм 2» и «кор3» одного тома — требует уточнения",
                c["status"] == "CLARIFICATION_REQUIRED" and "не упорядочить" in c["reason"], c.get("reason") or "")
    c = by[("PD", "ПОС")]
    ok &= check("два разных «ПОС-кор3» — требует уточнения",
                c["status"] == "CLARIFICATION_REQUIRED" and "одинаковая редакция" in c["reason"], c.get("reason") or "")
    c = by[("RD", "КЖ4.2")]
    ok &= check("переизданный отдельный лист — требует уточнения, без дублирующей причины",
                c["status"] == "CLARIFICATION_REQUIRED" and c["reason"].startswith("переизданы отдельные листы")
                and "одинаковая" not in c["reason"], c.get("reason") or "")
    c = by[("PD", "ПОС2")]
    ok &= check("разные поколения шифров проекта — требует уточнения",
                c["status"] == "CLARIFICATION_REQUIRED" and "разные шифры проекта" in c["reason"], c.get("reason") or "")
    ok &= check("у исполнительной документации нет цепочек: два акта с одним именем не редакции",
                rows["L0013"]["chain_id"] != rows["L0014"]["chain_id"]
                and rows["L0013"]["revision_status"] == "CURRENT")
    ok &= check("извещение об изменении в DOCX не становится редакцией комплекта",
                rows["L0016"]["revision_status"] == "CURRENT" and rows["L0015"]["chain_id"] != rows["L0016"]["chain_id"])
    dup = next(r for r in out if r["file_id"] == "L0017")
    ok &= check("побайтовая копия помечена дублем и в цепочку не входит",
                dup["revision_status"] == "DUPLICATE" and "L0017" not in by[("PD", "ПЗ")]["members"])
    return ok


def test_issue_folders():
    """Выпуски проекта по папкам и архив рабочей стадии (#110): ДОО на Полярной 25."""
    ok = True
    ok &= check("папки выпуска: год, корректировка, архив",
                rv.issue_folder("пд/ПД 2025/Корр2/03 Раздел ПД 3 АР_изм.2_01.pdf") == {"archive": False, "year": 2025, "corr": 2}
                and rv.issue_folder("РД/00. Архив/x.pdf")["archive"]
                and rv.issue_folder("пд/ПД 2022/заключ. 77-2-1-3-094627-2022 от 29.12.2022/40778-1-4.pdf")["year"] == 2022)
    ok &= check("копия файла вне архива делает его действующим выпуском",
                rv.latest_issue(["РД/00. Архив/ВК.pdf", "РД/к 15.09.2025/ВК.pdf"])["archive"] is False)
    i = lambda path: {"issue": rv.issue_folder(path)}                                         # noqa: E731
    ok &= check("порядок по папкам: 2022 раньше 2025, Корр1 раньше Корр2, архив раньше всего",
                rv.issue_order(i("пд/ПД 2025/Корр1/a.pdf"), i("пд/ПД 2022/a.pdf")) == 1
                and rv.issue_order(i("пд/ПД 2025/Корр1/a.pdf"), i("пд/ПД 2025/Корр2/a.pdf")) == -1
                and rv.issue_order(i("РД/00. Архив/a.pdf"), i("РД/06. СС/a.pdf")) == -1
                and rv.issue_order(i("пд/ПД 2025/a.pdf"), i("пд/ПД 2025/Корр1/a.pdf")) is None)
    docs = [
        doc("P1", "пд/ПД 2022/01-05-01-01-04 Пол25 ИОС1.1.pdf", 34, stage="PD"),
        doc("P2", "пд/ПД 2025/Корр1/05 Раздел ПД 5 подраздел 1 ИОС1.1_изм.1_04.pdf", 36, stage="PD"),
        doc("P3", "пд/ПД 2022/01-09-00-01-05 Пол25 ПБ.pdf", 90, stage="PD"),
        doc("P4", "пд/ПД 2025/Корр1/09 Раздел ПД 9 ПБ1_изм.1_06.pdf", 95, stage="PD"),
        doc("P5", "пд/ПД 2022/01-01-00-02-10 Пол25 ПЗ.pdf", 415, stage="PD"),
        doc("P6", "пд/ПД 2025/Корр1/01 Раздел ПД 1.2 ПЗ фрагмент 1_изм.1_11.pdf", 528, stage="PD"),
        doc("P7", "пд/ПД 2025/Корр1/01 Раздел ПД 1.2 ПЗ фрагмент 2_изм.1_01.pdf", 403, stage="PD"),
        doc("P8", "пд/ПД 2025/Корр2/01 Раздел ПД 1.2 ПЗ фрагмент 1_изм.2_01.pdf", 532, stage="PD"),
        doc("E1", "пд/ПД 2025/Корр2/Заключение экспертизы 77-2-1-2-063019-2025 от 22.10.2025.pdf", 10, stage="PD"),
        doc("R1", "РД/00. Архив/0073-Р-ДОО-Д9-АОДИ.pdf", 16, stage="RD"),
        doc("R2", "РД/06. СС/0073-Р-ДОО-Д9-АОДИ (3).pdf", 16, stage="RD"),
        doc("R3", "РД/00. Архив/04-П.СКБ-ПИР-Р-ОДИ_сборка.pdf", 31, stage="RD"),
        doc("R4", "РД/10. ОДИ/04-П.СКБ-ПИР-Р-ОДИ_сборка_4.pdf", 31, stage="RD"),
        doc("R5", "РД/к 15.09.2025/04-П.СКБ-ПИР-Р-ОДИ_сборка_3 (1).pdf", 31, stage="RD"),
        doc("R6", "РД/00. Архив/04-П.СКБ-ПИР-Р-ВК (1).pdf", 40, stage="RD"),
        doc("R6", "РД/к 15.09.2025/04-П.СКБ-ПИР-Р-ВК (1).pdf", 40, stage="RD", duplicate_of="R6"),
        doc("R7", "РД/05. ВК/04-П.СКБ-ПИР-Р-ВК Сборка.pdf", 41, stage="RD"),
    ]
    out, chains = rv.analyse("OBJ-X", docs)
    st = {r["file_id"]: r["revision_status"] for r in out if not r.get("duplicate_of")}
    ok &= check("ИОС1.1 2022 и корректировка 2025 с разными шифрами из имени — выпуск 2025 действующий",
                (st["P1"], st["P2"]) == ("SUPERSEDED", "CURRENT"), str((st["P1"], st["P2"])))
    ok &= check("«ПБ» 2022 и «ПБ1» 2025 — один том: 2025 действующий", (st["P3"], st["P4"]) == ("SUPERSEDED", "CURRENT"))
    ok &= check("ПЗ 2022 заменён фрагментом 1; фрагмент 1 Корр1 — фрагментом 1 Корр2; фрагмент 2 — свой",
                (st["P5"], st["P6"], st["P7"], st["P8"]) == ("SUPERSEDED", "SUPERSEDED", "CURRENT", "CURRENT"),
                str((st["P5"], st["P6"], st["P7"], st["P8"])))
    ok &= check("заключение экспертизы — не том и не редакция тома",
                next(c for c in chains if "E1" in c["members"])["members"] == ["E1"] and st["E1"] == "CURRENT")
    ok &= check("архивный том рабочей стадии заменён томом вне архива", (st["R1"], st["R2"]) == ("SUPERSEDED", "CURRENT"))
    ok &= check("цепочка требует уточнения, но архивный том в ней — прежняя редакция",
                st["R3"] == "SUPERSEDED" and st["R4"] == st["R5"] == "CLARIFICATION_REQUIRED", str((st["R3"], st["R4"], st["R5"])))
    ok &= check("том в архиве, но с копией вне архива — не заменён", st["R6"] != "SUPERSEDED", st["R6"])

    # проверка содержимым не отменяет цепочку томов разных выпусков
    from pipeline import revision_diff
    texts = {"P1": [(p, f"выпуск 2022 лист {p} " * 5) for p in range(1, 11)],
             "P2": [(p, f"выпуск 2025 другой текст {p} " * 5) for p in range(1, 11)]}
    c = next(c for c in chains if "P2" in c["members"])
    got, _ = revision_diff.verify_chains([dict(c)], [r for r in out if r["file_id"] in ("P1", "P2")],
                                         lambda d: texts[d["file_id"]])
    ok &= check("тома разных выпусков непохожи по содержимому — цепочка остаётся, сравнение записано",
                got[0]["status"] == "RESOLVED" and got[0]["content_check"][0].get("by_issue_folder"), got[0]["status"])
    return ok


def test_content_and_approval():
    ok = True
    docs = [doc("F0146", "ПД/1 Пояснительная записка/01-01-00-02-19_Том 1.2_Книга 1.pdf", 613),
            doc("F0150", "ПД/1 Пояснительная записка/ИЗМ ПО ЗАМЕЧАНИЯМ АНО1503211-П-ОПЗ.pdf", 614),
            doc("F0148", "ПД/1 Пояснительная записка/V2_01-01-00-04-22_Том 1.2_Книга 3.pdf", 466)]
    # набор шифров с настоящих страниц Тюменской-5: приложение изысканий, номенклатура
    # листов топосъёмки и собственный шифр книги на 13 и 14 страницах
    sheets = ([{"file_id": "F0146", "document_code": "036-21-ИГИ-Т"}] * 70
              + [{"file_id": "F0146", "document_code": "ГКИНП-02-033-082"}] * 27
              + [{"file_id": "F0146", "document_code": "ГКИНП-02-033-82"}] * 25
              + [{"file_id": "F0146", "document_code": "АНО/150321/1-П-ПЗ1.2"}] * 13
              + [{"file_id": "F0150", "document_code": "036-21-ИГИ-Т"}] * 70
              + [{"file_id": "F0150", "document_code": "ГКИНП-02-033-082"}] * 27
              + [{"file_id": "F0150", "document_code": "ГКИНП-02-033-82"}] * 25
              + [{"file_id": "F0150", "document_code": "АНО/150321/1-П-ПЗ1.2"}] * 14
              + [{"file_id": "F0148", "document_code": "АЛ-30/IVECO"}] * 30)
    out, chains = rv.analyse("OBJ-X", docs, sheets_rows=sheets)
    c = next(c for c in chains if "F0150" in c["members"])
    ok &= check("переиздание без общей марки связано по шифрам на страницах и числу страниц",
                c["status"] == "RESOLVED" and c["members"] == ["F0146", "F0150"]
                and c["current_file_id"] == "F0150", str(c["members"]))
    row = next(r for r in out if r["file_id"] == "F0146")
    ok &= check("шифр книги — её собственный, а не шифр приложения изысканий на 70 страницах",
                row["document_code"] == "АНО/150321/1-П-ПЗ1.2" and row["mark"] == "ПЗ1.2",
                str(row["document_code"]))

    # Речников: в штампах томов КЖ1 и КЖ2.2 почти везде только шифр комплекта
    docs = [doc("F0342", "РД/КЖ1/01-0723-14-РД-КЖ1.pdf", 14),
            doc("F0348", "РД/КЖ2.2/01-0723-14-РД-КЖ2.2_Изм.1.pdf", 16),
            doc("F0350", "РД/ГИ/01-07_23-14-РД-КЖ.ГИ_Изм2.pdf", 9)]
    sheets = ([{"file_id": "F0342", "document_code": "01-07/23-14-РД"}] * 12
              + [{"file_id": "F0348", "document_code": "01-07/23-14-РД"}] * 13
              + [{"file_id": "F0348", "document_code": "01-07/23-14-РД-КЖ2.2"}]
              + [{"file_id": "F0350", "document_code": "01-07/23-14-РД"}] * 6)
    out, chains = rv.analyse("OBJ-X", docs, sheets_rows=sheets)
    ok &= check("шифр комплекта без марки не склеивает разные тома",
                all(c["status"] == "SINGLE" for c in chains) and len(chains) == 3,
                str([c["members"] for c in chains]))
    codes = {r["file_id"]: r["document_code"] for r in out}
    ok &= check("шифр документа из штампа, только если в нём есть марка",
                codes["F0342"] == "01-0723-14-РД-КЖ1" and codes["F0348"] == "01-07/23-14-РД-КЖ2.2",
                str(codes))

    prof = {"L0023": collections.Counter({"245-0817-КМ-2/Н-3": 25, "СМК-ДК42-10": 1}),
            "L0061": collections.Counter({"245-0817-КМ-2/Н-3": 17, "СМК-ДК42-10": 1}),
            "F0001": collections.Counter({"ВН.ТЕР.Г": 3}),
            "L0019": collections.Counter({"245-0817-КМ-2/Н-1-ПЗУ1": 4})}
    kept = rv.document_code_profiles(prof, {"L0023": ("", "АР1"), "L0061": ("", "РИО"),
                                            "F0001": ("", None), "L0019": ("", "ПЗУ1")})
    ok &= check("шифр на томах с разными марками, штамп и слова адреса не отличают документ",
                set(kept) == {"L0019"}, str(kept))
    # Тюменская-5: шифр ОВ2.1 на 11 листах тома ОВ2.1, в латинском написании ещё на одном,
    # и на одной странице из 602 в томе ОВ1
    docs = [doc("F0201", "РД/АНО-150321-1-РД-ОВ1 изм. 4_в1 (1).pdf", 676),
            doc("F0202", "РД/АНО-150321-1-РД-ОВ2.1_изм. 3_в1.pdf", 36)]
    sheets = ([{"file_id": "F0201", "document_code": "АНО/150321/1-РД-ОВ1.С"}] * 119
              + [{"file_id": "F0201", "document_code": "АНО/150321/1-РД-ОВ2.1"}]
              + [{"file_id": "F0202", "document_code": "АНО/150321/1-РД-ОВ2.1"}] * 11
              + [{"file_id": "F0202", "document_code": "AHO/150321/1-РД-ОВ2.1"}])
    out, _ = rv.analyse("OBJ-X", docs, sheets_rows=sheets)
    codes = {r["file_id"]: r["document_code"] for r in out}
    ok &= check("латинские двойники в шифре — тот же шифр, случайный лист в чужом томе не делает шифр общим",
                codes == {"F0201": "АНО/150321/1-РД-ОВ1.С", "F0202": "АНО/150321/1-РД-ОВ2.1"}, str(codes))
    prof = rv.code_profiles([{"file_id": "F0202", "document_code": "AHO/150321/1-РД-ОВ2.1"},
                             {"file_id": "F0202", "document_code": "АНО/150321/1-РД-ОВ2.1"}])
    ok &= check("набор шифров приводит латинские двойники к кириллице",
                prof["F0202"] == collections.Counter({"АНО/150321/1-РД-ОВ2.1": 2}), str(dict(prof["F0202"])))
    # Новослободская: акт несёт штамп приложенной схемы, том МОПБ — чужие листы ИОС4.2
    docs = [doc("F0013", "ИД/АОСР №10АЗ от 12.05.2026.pdf", 6),
            doc("F0117", "ПД/НВС-2025.03-9-МОПБ.pdf", 40)]
    sheets = ([{"file_id": "F0013", "document_code": "НВС-2025/03-КР1"}] * 5
              + [{"file_id": "F0117", "document_code": "НВС-2025/03-ИОС4.2"}] * 20)
    out, _ = rv.analyse("OBJ-X", docs, sheets_rows=sheets)
    rows = {r["file_id"]: r for r in out}
    ok &= check("у акта марка и шифр не со штампа приложенной схемы, а раздел по нему",
                rows["F0013"]["mark"] is None and rows["F0013"]["document_code_source"] != "TITLEBLOCK"
                and (rows["F0013"]["section"], rows["F0013"]["section_source"]) == ("KR", "TITLEBLOCK_MARK"),
                f'{rows["F0013"]["mark"]} {rows["F0013"]["document_code"]} {rows["F0013"]["section"]}')
    ok &= check("шифр штампа без марки из имени не становится шифром тома",
                rows["F0117"]["document_code"] == "НВС-2025.03-9-МОПБ"
                and rows["F0117"]["document_code_source"] == "NAME", str(rows["F0117"]["document_code"]))
    ok &= check("марка в шифре ищется целиком и с синонимами",
                rv.code_has_mark("АНО/150321/1-РД-ОВ1.С", "ОВ1") and not rv.code_has_mark("Х-РД-ОВ1.1", "ОВ1")
                and not rv.code_has_mark("Х-КРЫША", "КР") and rv.code_has_mark("П-2025-04.266-СПОЗУ.ТЧ", "ПЗУ")
                and rv.code_has_mark("AHO/150321/1-П-ИОС5.1.4.СО", "ИОС5.1.4"))
    # Алтуфьевское: дубль по SHA-256 носит file_id исходника, но лежит под другим именем
    docs = [doc("L0030", "ПД/5.1. Раздел 5.1 ЖС-РД-270121-П-ИОС5.1.pdf", 40, sha="a" * 64),
            doc("L0030", "ПД/5.1. Раздел 5.1 ЖС-РД-270121-П-ИОС5.1 2024.pdf", 40, sha="a" * 64,
                duplicate_of="L0030")]
    out, _ = rv.analyse("OBJ-X", docs)
    ok &= check("исходник и дубль разбираются каждый по своему имени",
                [r["revision_detail"]["year_suffix"] for r in out] == [None, 2024]
                and [r["revision_status"] for r in out] == ["CURRENT", "DUPLICATE"],
                str([r["revision_detail"]["year_suffix"] for r in out]))
    ok &= check("совместимость марок: номер тома и марка без номера совместимы, разные тома нет",
                rv.marks_compatible("ТОМ1.2", "ПЗ") and rv.marks_compatible("ПЗ", "ПЗ1.2")
                and not rv.marks_compatible("КЖ1", "КЖ2.2") and not rv.marks_compatible("КЖ7", "КЖ.ГИ")
                and not rv.marks_compatible("АР1", "РИО"))

    prof = collections.Counter({"АНО/150321/1-П-ИОС": 23, "АНО/150321/1-П-ИОС5": 19,
                                "АНО/150321/1-П-ИОС5.1.1-ПЗ": 18, "ГУ-ИСХ-45274": 1})
    ok &= check("шифр штампа — самый конкретный из частых, а не обрезанный самый частый",
                rv.specific_code(prof) == "АНО/150321/1-П-ИОС5.1.1-ПЗ")

    signed = [doc("L0001", "Рабочая документация/245-0817-КМ-2-Н-3-КЖ02.1 Изм.4 ЭЦП 03.12.2025.pdf")]
    plain = [doc("L0001", "Рабочая документация/245-0817-КМ-2-Н-3-КЖ02.2.pdf")]
    _, strict_signed = rv.analyse("OBJ-X", signed, require_approval=True)
    out_plain, strict_plain = rv.analyse("OBJ-X", plain, require_approval=True)
    _, soft_plain = rv.analyse("OBJ-X", plain)
    ok &= check("строгий режим: подписанный ЭЦП документ актуален",
                strict_signed[0]["status"] == "SINGLE")
    ok &= check("строгий режим: без признака утверждения — требует уточнения",
                strict_plain[0]["status"] == "CLARIFICATION_REQUIRED" and "утверждения" in strict_plain[0]["reason"])
    ok &= check("обычный режим: признак утверждения не блокирует выбор редакции",
                soft_plain[0]["status"] == "SINGLE" and out_plain[0]["approval_status"] == "UNKNOWN")
    return ok


# ---------------------------------------------------------------- таблица изменений штампа

def test_titleblock_revision():
    ok = True
    # Речников F0352 стр. 4, «К1-КЖ1_Изм.3»: три строки «Зам.» над основной надписью
    rech_p4 = [w('Изм.', 0.7772, 0.9339, 0.7830, 0.9401), w('Кол.уч.', 0.7864, 0.9333, 0.7972, 0.9401),
               w('Лист', 0.8004, 0.9337, 0.8072, 0.9398), w('№док.', 0.8104, 0.9333, 0.8212, 0.9401),
               w('Подпись', 0.8249, 0.9337, 0.8361, 0.9398), w('Дата', 0.8415, 0.9337, 0.8492, 0.9398),
               w('Зам.', 0.8004, 0.9253, 0.8071, 0.9321), w('Зам.', 0.8004, 0.9169, 0.8071, 0.9236),
               w('Зам.', 0.8004, 0.9084, 0.8071, 0.9152), w('-', 0.7910, 0.9253, 0.7927, 0.9321),
               w('-', 0.7910, 0.9169, 0.7927, 0.9236), w('-', 0.7910, 0.9084, 0.7927, 0.9152),
               w('2220', 0.8037, 0.8984, 0.8046, 0.8991),
               w('1', 0.7795, 0.9256, 0.7805, 0.9318), w('29.02.24', 0.8411, 0.9256, 0.8501, 0.9318),
               w('2', 0.7793, 0.9171, 0.7806, 0.9233), w('07.03.24', 0.8411, 0.9171, 0.8501, 0.9233),
               w('3', 0.7793, 0.9087, 0.7806, 0.9148), w('21.06.24', 0.8413, 0.9087, 0.8499, 0.9148),
               w('112-24', 0.8132, 0.9258, 0.8184, 0.9319), w('125-24', 0.8130, 0.9173, 0.8185, 0.9235),
               w('420-24', 0.8128, 0.9087, 0.8187, 0.9149)]
    ok &= check("номер изменения — наибольший в колонке «Изм.»", titleblock.revision(rech_p4) == 3,
                str(titleblock.revision(rech_p4)))

    # Октябрьская L0013 стр. 2, «КЖ_ГИ-изм3»: подпись «Изм» без точки, даты «02.26»
    okt_p2 = [w('Изм', 0.6837, 0.9054, 0.6932, 0.9146), w('Кол.', 0.6977, 0.9058, 0.7059, 0.9145),
              w('Лист', 0.7158, 0.9053, 0.7284, 0.9145), w('№док.', 0.7314, 0.9053, 0.7465, 0.9145),
              w('1', 0.6871, 0.8950, 0.6892, 0.9042), w('-', 0.7040, 0.8950, 0.7069, 0.9042),
              w('Зам', 0.7160, 0.8950, 0.7258, 0.9042), w('91-25', 0.7322, 0.8952, 0.7455, 0.9041),
              w('2', 0.6871, 0.8831, 0.6901, 0.8923), w('Зам', 0.7160, 0.8831, 0.7258, 0.8923),
              w('933-25', 0.7306, 0.8833, 0.7475, 0.8922), w('3', 0.6871, 0.8711, 0.6901, 0.8804),
              w('Зам', 0.7160, 0.8711, 0.7258, 0.8804), w('158-26', 0.7306, 0.8714, 0.7467, 0.8803),
              w('02.26', 0.7749, 0.8711, 0.7879, 0.8804)]
    ok &= check("подпись «Изм» без точки и даты вида «02.26»", titleblock.revision(okt_p2) == 3)

    # Речников F0352 стр. 5: в колонку попадает список общих указаний «4.» … «10.»
    notes = [w('Изм.', 0.6844, 0.9534, 0.6926, 0.9577), w('Зам.', 0.7173, 0.9472, 0.7268, 0.9520),
             w('4.', 0.6797, 0.8650, 0.6836, 0.8698), w('Приямки', 0.6857, 0.8650, 0.7041, 0.8698),
             w('11', 0.7760, 0.8650, 0.7796, 0.8698), w('6.', 0.6797, 0.8763, 0.6833, 0.8811),
             w('Материалы', 0.6854, 0.8763, 0.7106, 0.8811), w('10.', 0.6797, 0.9103, 0.6851, 0.9151),
             w('1409', 0.7592, 0.9160, 0.7689, 0.9207), w('м².', 0.7711, 0.9160, 0.7772, 0.9207)]
    ok &= check("нумерованный список общих указаний не номер изменения", titleblock.revision(notes) is None)
    row2 = notes + [w('2', 0.6874, 0.9475, 0.6892, 0.9519), w('07.03.24', 0.7748, 0.9475, 0.7876, 0.9519),
                    w('125-24', 0.7351, 0.9476, 0.7429, 0.9520)]
    ok &= check("строка таблицы под списком засчитывается", titleblock.revision(row2) == 2)

    # прежнее правило находило «изм 60» в тексте страницы тома ПОС
    body = [w('Изм.', 0.80, 0.95, 0.81, 0.96), w('60', 0.803, 0.90, 0.806, 0.91),
            w('Изм', 0.20, 0.30, 0.22, 0.31), w('60', 0.23, 0.30, 0.24, 0.31)]
    ok &= check("число над подписью без вида изменения, номера документа и даты не засчитывается",
                titleblock.revision(body) is None)
    return ok


def main():
    ok = True
    for title, fn in (("Отметки в имени", test_name_markers), ("Имена вне корпуса", test_names_outside_corpus),
                      ("Шифр и марка", test_marks),
                      ("Стадия", test_stage), ("Раздел", test_section), ("Сравнение редакций", test_compare),
                      ("Цепочки", test_chains), ("Выпуски по папкам", test_issue_folders),
                      ("Содержимое и утверждение", test_content_and_approval),
                      ("Таблица изменений штампа", test_titleblock_revision)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
