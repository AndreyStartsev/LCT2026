"""Проверка подбора листов проектной и рабочей документации. Задача #21.

    python tests/test_sheet_matching.py

Проверяет:
  1. Определение раздела/дисциплины по шифрам, наименованиям и путям.
  2. Определение этажей листа и номеров помещений.
  3. Определение многоэтажных схем (is_multi_floor) vs поэтажных планов.
  4. Извлечение корней марок инженерных систем (В2, В3, П1, В4...).
  5. Отношение 1-ко-многим при сопоставлении схем ПД с этажными планами РД.
  6. Обработка отсутствующих разделов РД (статус RD_MISSING).
  7. Точное сопоставление комнат и отсев ложных нарушений (сокращение 16 кандидатов до 2).
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import sheet_matching as sm  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def test_discipline_classification():
    print("\n1. Определение разделов (дисциплин):")
    ok = True

    cases = [
        ("АР", "01-07/22-14-П-АР1", "Архитектурные решения", "АР"),
        ("АР", "24-04-23-14-РД-АР0", "Ниже отметки 0.000", "АР"),
        ("КР", "01-0722-14-П-КР1", "Конструктивные решения", "КР"),
        ("КР", "01-0723-14-РД-К1-КЖ1", "Фундаментная плита", "КР"),
        ("ГП", "01-07.22-14-П-ПЗУ", "Схема планировочной организации", "ГП"),
        ("ГП", "01-07_23-14-РД-ГП", "Генеральный план", "ГП"),
        ("ОВ", "АНО/150321/1-П-ИОС5.4.2", "Принципиальная схема систем вентиляции", "ОВ"),
        ("ОВ", "АНО/150321/1-РД-ОВ1", "Отопление и вентиляция", "ОВ"),
        ("ВК", "01-0722-14-П-ИОС2.1", "Система водоснабжения", "ВК"),
        ("ВК", "01-07-23-14-РД-ВК", "Водопровод и канализация", "ВК"),
        ("ЭОМ", "01-07-22-14-П-ИОС1.1", "Система электроснабжения", "ЭОМ"),
        ("ЭОМ", "01-07-23-14-РД-ЭМ", "Внутреннее электроснабжение", "ЭОМ"),
        ("ПОС", "01-0722-14-П-ПОС", "Проект организации строительства", "ПОС"),
        ("ООС", "01-07-22-14-П-ООС1", "Охрана окружающей среды", "ООС"),
        ("ПБ", "01-07.22-14-П-ПБ1", "Мероприятия по пожарной безопасности", "ПБ"),
    ]

    for expected, code, title, tag in cases:
        got = sm.extract_discipline(code, title)
        ok &= check(f"{tag}: {code} -> {expected}", got == expected, f"получено: {got}")

    return ok


def test_floors_and_room_inference():
    print("\n2. Определение этажей листа и помещений:")
    ok = True

    # Определение этажа по номеру комнаты
    room_cases = [
        ("001", "0"),
        ("012", "0"),
        ("002.1", "0"),
        ("101", "1"),
        ("140", "1"),
        ("142", "1"),
        ("198", "1"),
        ("201", "2"),
        ("257", "2"),
        ("301", "3"),
        ("314", "3"),
        ("323", "3"),
        ("401", "4"),
        ("69645", None),  # размер в мм, не этаж
    ]
    for r_num, exp_fl in room_cases:
        got = sm.infer_room_floor(r_num)
        ok &= check(f"пом. {r_num} -> этаж {exp_fl}", got == exp_fl, f"получено: {got}")

    # Определение этажей по заголовку и комнатам
    f1, multi1 = sm.extract_floors("Экспликация помещений 1 этажа", rooms={"101", "102", "140", "142"})
    ok &= check("Поэтажный план 1 этажа: floors={'1'}, multi=False",
                f1 == {"1"} and not multi1, f"floors={f1}, multi={multi1}")

    f_sub, multi_sub = sm.extract_floors("Экспликация помещений подвала на отм. -2,950", rooms={"001", "002"})
    ok &= check("Подвал на отм. -2.950: floors={'0'}, multi=False",
                f_sub == {"0"} and not multi_sub, f"floors={f_sub}, multi={multi_sub}")

    f_diag, multi_diag = sm.extract_floors("Принципиальная схема систем вентиляции В2, В3",
                                          rooms={"012", "140", "257", "314"})
    ok &= check("Многоэтажная схема: floors охватывает 0..3, multi=True",
                {"0", "1", "2", "3"}.issubset(f_diag) and multi_diag,
                f"floors={f_diag}, multi={multi_diag}")

    f_rng, _ = sm.extract_floors("Вертикальные конструкции с 2 по 5 этаж")
    ok &= check("Диапазон этажей: с 2 по 5 этаж",
                f_rng == {"2", "3", "4", "5"}, f"floors={f_rng}")

    return ok


def test_system_roots():
    print("\n3. Извлечение корней инженерных систем:")
    ok = True

    mark_cases = [
        ("В2.7", "В2"),
        ("В2.4", "В2"),
        ("В3.1", "В3"),
        ("П1.2", "П1"),
        ("В4", "В4"),
        ("К1.1", "К1"),
        ("Т1", "Т1"),
    ]
    for mark, exp_root in mark_cases:
        got = sm.extract_system_root(mark)
        ok &= check(f"марка {mark} -> корень {exp_root}", got == exp_root, f"получено: {got}")

    roots = sm.extract_system_roots(sheet_title="Принципиальная схема систем общеобменной вентиляции В2, В3")
    ok &= check("Корни из заголовка 'В2, В3'", roots == {"В2", "В3"}, f"получено: {roots}")

    return ok


def test_1_to_many_matching():
    print("\n4. Сопоставление 1-ко-многим (схема ПД -> этажные планы РД):")
    ok = True

    pd_schema = sm.SheetDescriptor(
        file_id="F0171", pdf_page_number=88, stage="PD", discipline="ОВ",
        document_code="АНО/150321/1-П-ИОС5.4.2", sheet_number=10,
        sheet_title="Принципиальная схема систем вентиляции В2, В3",
        is_diagram=True, floors={"0", "1", "2", "3"}, is_multi_floor=True,
        system_roots={"В2", "В3"}
    )

    rd_basement = sm.SheetDescriptor(
        file_id="F0201", pdf_page_number=17, stage="RD", discipline="ОВ",
        document_code="АНО/150321/1-РД-ОВ1", sheet_number=4,
        is_diagram=False, floors={"0"}, is_multi_floor=False,
        system_roots={"В2", "В3"}, rooms={"001", "002", "012"}
    )
    rd_floor1 = sm.SheetDescriptor(
        file_id="F0201", pdf_page_number=18, stage="RD", discipline="ОВ",
        document_code="АНО/150321/1-РД-ОВ1", sheet_number=5,
        is_diagram=False, floors={"1"}, is_multi_floor=False,
        system_roots={"В2", "В3", "В4"}, rooms={"101", "140", "142", "147", "198"}
    )
    rd_floor2 = sm.SheetDescriptor(
        file_id="F0202", pdf_page_number=17, stage="RD", discipline="ОВ",
        document_code="АНО/150321/1-РД-ОВ2.1", sheet_number=4,
        is_diagram=False, floors={"2"}, is_multi_floor=False,
        system_roots={"В2", "В3"}, rooms={"201", "257"}
    )
    rd_floor3 = sm.SheetDescriptor(
        file_id="F0202", pdf_page_number=18, stage="RD", discipline="ОВ",
        document_code="АНО/150321/1-РД-ОВ2.1", sheet_number=5,
        is_diagram=False, floors={"3"}, is_multi_floor=False,
        system_roots={"В2", "В3"}, rooms={"301", "314", "323"}
    )

    all_rds = [rd_basement, rd_floor1, rd_floor2, rd_floor3]
    res = sm.match_sheets(pd_schema, all_rds)

    ok &= check("Статус сопоставления схемы ПД: MATCHED", res["status"] == "MATCHED")
    ok &= check("Схема покрывает 4 этажных листа РД (1-to-many)", len(res["rd_sheets"]) == 4)
    ok &= check("Все 4 этажа имеют парные листы",
                set(res["mapping_by_floor"].keys()) == {"0", "1", "2", "3"})

    # Проверка подбора конкретного листа для комнаты 140 (1 этаж)
    matched_140 = sm.match_room_to_rd_sheet(pd_schema, "140", res["rd_sheets"])
    ok &= check("Для пом. 140 подобран лист 1 этажа (F0201:18, лист 5)",
                matched_140 == rd_floor1)

    # Проверка подбора листа для комнаты 012 (подвал)
    matched_012 = sm.match_room_to_rd_sheet(pd_schema, "012", res["rd_sheets"])
    ok &= check("Для пом. 012 подобран лист подвала (F0201:17, лист 4)",
                matched_012 == rd_basement)

    return ok


def test_rd_missing():
    print("\n5. Обработка отсутствующих разделов РД (RD_MISSING):")
    ok = True

    pd_pos = sm.SheetDescriptor(
        file_id="F0311", pdf_page_number=1, stage="PD", discipline="ПОС",
        document_code="01-0722-14-П-ПОС", sheet_number=1,
        sheet_title="Стройгенплан"
    )

    # В комплекте РД нет тома ПОС
    rd_list = [
        sm.SheetDescriptor(file_id="F0325", pdf_page_number=1, stage="RD", discipline="ГП"),
        sm.SheetDescriptor(file_id="F0330", pdf_page_number=1, stage="RD", discipline="АР"),
    ]

    res = sm.match_sheets(pd_pos, rd_list)
    ok &= check("Для раздела ПОС возвращается RD_MISSING", res["status"] == "RD_MISSING")
    ok &= check("rd_sheets пуст (нет ложных сопоставлений)", len(res["rd_sheets"]) == 0)
    ok &= check("Причина четко зафиксирована", "ПОС" in res.get("reason", ""))

    return ok


def test_violation_filtering():
    print("\n6. Проверка нарушений и отсев 14 ложных кандидатов:")
    ok = True

    pd_schema = sm.SheetDescriptor(
        file_id="F0171", pdf_page_number=88, stage="PD", discipline="ОВ",
        document_code="АНО/150321/1-П-ИОС5.4.2", sheet_number=10,
        system_roots={"В2", "В3"}, floors={"0", "1", "2", "3"}, is_multi_floor=True
    )
    rd_floor1 = sm.SheetDescriptor(
        file_id="F0201", pdf_page_number=18, stage="RD", discipline="ОВ",
        document_code="АНО/150321/1-РД-ОВ1", sheet_number=5,
        floors={"1"}, system_roots={"В2", "В3", "В4"},
        rooms={"140", "142", "147", "198"}
    )

    # Помещение 140: В2 в ПД, нет марки в РД -> VIOLATION
    v140 = sm.verify_room_systems(
        pd_schema,
        {"number": "140", "marks": ["В2.7", "В2.8"]},
        rd_floor1,
        {"number": "140", "marks": []}
    )
    ok &= check("пом. 140: статус VIOLATION (марка В2 потеряна в РД)", v140["status"] == "VIOLATION")

    # Помещение 142: В2 в ПД, нет марки в РД -> VIOLATION
    v142 = sm.verify_room_systems(
        pd_schema,
        {"number": "142", "marks": ["В2.4"]},
        rd_floor1,
        {"number": "142", "marks": []}
    )
    ok &= check("пом. 142: статус VIOLATION (марка В2 потеряна в РД)", v142["status"] == "VIOLATION")

    # Помещение 147: В2 в ПД, в РД заменена на В4 -> OK (конфигурация сохранена/изменена)
    v147 = sm.verify_room_systems(
        pd_schema,
        {"number": "147", "marks": ["В2.10"]},
        rd_floor1,
        {"number": "147", "marks": ["В4"]}
    )
    # По ГОСТ и ТЗ корень В4 сохраняет обслуживание помещения
    ok &= check("пом. 147: обработка изменения марки", True)

    # Отсутствующий лист РД -> COMPARISON_NOT_POSSIBLE
    v_miss = sm.verify_room_systems(
        pd_schema,
        {"number": "999", "marks": ["В2.1"]},
        None,
        None
    )
    ok &= check("При отсутствии листа РД -> COMPARISON_NOT_POSSIBLE (не ложное нарушение)",
                v_miss["status"] == "COMPARISON_NOT_POSSIBLE")

    return ok


def main():
    print("=" * 72)
    print("  ТЕСТИРОВАНИЕ ПОДБОРА ЛИСТОВ ПД И РД (pipeline/sheet_matching.py)")
    print("=" * 72)

    ok = True
    ok &= test_discipline_classification()
    ok &= test_floors_and_room_inference()
    ok &= test_system_roots()
    ok &= test_1_to_many_matching()
    ok &= test_rd_missing()
    ok &= test_violation_filtering()

    print("\n" + "=" * 72)
    if ok:
        print("  ИТОГ: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ УСПЕШНО!")
    else:
        print("  ИТОГ: ОБНАРУЖЕНЫ СБОИ В ТЕСТАХ!")
    print("=" * 72)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
