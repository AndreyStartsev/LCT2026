"""Таблицы на чертёжных листах и таблица характеристик систем. Задачи #21, #37.

  python tests/test_vector_tables.py

Таблицы здесь синтетические: сетка нарисована линиями, текст лежит в слое или вставлен картинкой
(тогда слоя нет, и ячейки распознаются). Оформление нарочно не из корпуса: другие обозначения,
таблица уже листа, повёрнутый лист, колонка без горизонтальных линий.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pymupdf  # noqa: E402

from pipeline import hvac_systems, vector_tables  # noqa: E402

FONT = pymupdf.Font("cour")          # у встроенного Helvetica нет кириллицы
HEAD = ["Обозначение системы", "Кол. систем", "Наименование обслуживаемого помещения", "Тип установки", "L, м3/ч"]
XS = [60, 150, 210, 520, 640, 720]   # границы колонок
ROW_H, TOP, HEAD_H = 26, 80, 50


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def draw_table(page, rows, count_lines=True, frame=True, as_image=False, segmented=True):
    """Нарисовать таблицу систем: сетка линиями, текст — слоем или картинкой."""
    shape = page.new_shape()
    bottom = TOP + HEAD_H + ROW_H * len(rows)
    ys = [TOP, TOP + HEAD_H] + [TOP + HEAD_H + ROW_H * (i + 1) for i in range(len(rows))]
    for x in XS:
        shape.draw_line((x, TOP), (x, bottom))
    for k, y in enumerate(ys):
        for a, b in zip(XS, XS[1:]):
            if not count_lines and a == XS[1] and 1 < k < len(ys) - 1:
                continue                     # колонка «Кол.» без горизонтальных линий между строками
            if segmented:
                shape.draw_line((a, y), (b, y))      # сетку чертят отрезками от ячейки к ячейке
        if not segmented:
            shape.draw_line((XS[0], y), (XS[-1], y))
    if frame:                                # рамка листа длиннее любой линии таблицы
        r = page.rect
        shape.draw_rect(pymupdf.Rect(20, 5, r.width - 5, r.height - 5))
    shape.finish(width=0.7)
    shape.commit()
    texts = [(XS[c] + 4, TOP + 14 + 11 * line, part)
             for c, head in enumerate(HEAD) for line, part in enumerate(_wrap(head, 18))]
    for i, row in enumerate(rows):
        for c, value in enumerate(row):
            texts.append((XS[c] + 4, TOP + HEAD_H + ROW_H * i + 17, value))
    if not as_image:
        writer = pymupdf.TextWriter(page.rect)
        for x, y, text in texts:
            writer.append((x, y), text, font=FONT, fontsize=9)
        writer.write_text(page)
        return
    # текст картинкой: слоя нет, как у чертежа, выведенного кривыми
    donor = pymupdf.open()
    sheet = donor.new_page(width=page.rect.width, height=page.rect.height)
    writer = pymupdf.TextWriter(sheet.rect)
    for x, y, text in texts:
        writer.append((x, y), text, font=FONT, fontsize=9)
    writer.write_text(sheet)
    pix = sheet.get_pixmap(matrix=pymupdf.Matrix(5, 5), alpha=False)
    page.insert_image(page.rect, pixmap=pix, overlay=False)


def _wrap(text, width):
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = (cur + " " + word).strip()
    return lines + [cur]


ROWS = [
    ["В2.7, В2.8", "2", "М.О. (поз.169) в пом. 140", "Канальный", "950"],
    ["П1.А1", "1", "Досуговая, пом.160, 161, 162, 1 эт.", "Подвесная", "360"],
    ["В-1.12", "1", "Помещение кладовых", "Канальный", "630"],
    ["У1.1м - У1.2м", "2", "Тамбур (пом. 124)", "Завеса", "1200"],
]


def test_grid():
    print("\n1. Сетка из линий")
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    draw_table(page, ROWS)
    grid = vector_tables.find_grid(page)
    ok = check("сетка найдена", bool(grid))
    inner = [x for x in grid.xs if 50 < x < 730]
    ok &= check("колонки — по линиям таблицы, рамка листа меру не сбивает",
                [round(x) for x in inner] == XS, str([round(x) for x in grid.xs]))
    column = grid.xs.index(next(x for x in grid.xs if abs(x - XS[0]) < 1))
    bottom = TOP + HEAD_H + ROW_H * len(ROWS)
    bands = [b for b in grid.bands(column) if TOP - 1 <= b[0] and b[1] <= bottom + 1]   # без полей до рамки листа
    ok &= check("шапка — одна ячейка, строк данных четыре", len(bands) == 5 and round(bands[0][1] - bands[0][0]) == HEAD_H,
                str([(round(a), round(b)) for a, b in bands]))
    doc.close()
    return ok


def test_layer_rows():
    print("\n2. Строки таблицы из текстового слоя")
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    draw_table(page, ROWS)
    rows, info = hvac_systems.parse_page(page, use_ocr=False)
    ok = check("колонки узнаны по шапке", bool(info["roles"]) and "flow" in info["roles"], str(info["roles"]))
    ok &= check("четыре строки, распознавание не понадобилось", len(rows) == 4 and info["ocr_cells"] == 0, str(len(rows)))
    by = {tuple(r["systems"]): r for r in rows}
    first = by.get(("В2.7", "В2.8")) or {}
    ok &= check("обозначения через запятую, число систем, помещение, позиция, расход",
                first.get("count") == 2 and first.get("rooms") == ["140"] and first.get("positions") == ["169"]
                and first.get("flow") == 950, str(first))
    second = by.get(("П1.А1",)) or {}
    ok &= check("список помещений без этажа: «пом.160, 161, 162, 1 эт.»", second.get("rooms") == ["160", "161", "162"],
                str(second.get("rooms")))
    ok &= check("обозначение с дефисом «В-1.12», помещение не названо — строка без номеров",
                ("В-1.12",) in by and by[("В-1.12",)]["rooms"] == [])
    ok &= check("диапазон «У1.1м - У1.2м» — две системы", ("У1.1м", "У1.2м") in by, str(list(by)))
    ok &= check("рамка строки — в долях видимой страницы", all(0 <= v <= 1 for v in first.get("bbox", [2])), str(first.get("bbox")))
    doc.close()
    return ok


def test_rotated_and_unruled():
    print("\n3. Повёрнутый лист и колонка без линий между строками")
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    draw_table(page, ROWS, count_lines=False)
    rows, _ = hvac_systems.parse_page(page, use_ocr=False)
    ok = check("число систем берётся из полосы строки, а не из всей колонки",
               [r["count"] for r in rows] == [2, 1, 1, 2], str([r["count"] for r in rows]))
    page.set_rotation(90)
    rows90, info = hvac_systems.parse_page(page, use_ocr=False)
    ok &= check("после поворота листа на 90° разбор не находит таблицу «боком» и не выдаёт мусор",
                rows90 == [] or [r["rooms"] for r in rows90] == [r["rooms"] for r in rows], str(info["roles"]))
    doc.close()
    # лист, который повёрнут в PDF, а выглядит прямо: содержимое записано боком, поворот его выправляет
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.set_rotation(270)
    visible = pymupdf.open()
    sheet = visible.new_page(width=842, height=595)
    draw_table(sheet, ROWS)
    page.show_pdf_page(page.rect, visible, 0, rotate=270)
    rows270, info = hvac_systems.parse_page(page, use_ocr=False)
    ok &= check("таблица на листе с поворотом 270° читается в видимых координатах",
                [r["rooms"] for r in rows270] == [r["rooms"] for r in rows], f"{len(rows270)} строк, {info['roles']}")
    doc.close()
    return ok


def test_not_a_systems_table():
    print("\n4. Чужие таблицы")
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    global HEAD
    saved, HEAD = HEAD, ["Номер помещения", "Кол.", "Наименование помещения", "Площадь", "Кат."]
    try:
        draw_table(page, [["140", "1", "Кабинет физики, пом. 140", "52,3", "В4"]] * 4)
    finally:
        HEAD = saved
    rows, info = hvac_systems.parse_page(page, use_ocr=False)
    ok = check("экспликация со словом «помещения» в шапке — не таблица систем", rows == [] and not info["roles"], str(info))
    empty = doc.new_page(width=842, height=595)
    rows, info = hvac_systems.parse_page(empty, use_ocr=False)
    ok &= check("лист без сетки", rows == [] and not info["grid"])
    doc.close()
    return ok


def test_ocr_cells():
    print("\n5. Таблица без текстового слоя: распознавание ячеек")
    if not vector_tables.tesseract_available():
        print("  [пропуск] Tesseract не установлен")
        return True
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    draw_table(page, ROWS, as_image=True)
    ok = check("текстового слоя на листе нет", not page.get_text("words"))
    rows, info = hvac_systems.parse_page(page)
    ok &= check("ячейки распознаны", info["ocr_cells"] > 0 and not info["ocr_failed"], str(info))
    rooms = sorted(room for r in rows for room in r["rooms"])
    ok &= check("номера помещений прочитаны голосованием трёх прочтений",
                rooms == ["124", "140", "160", "161", "162"], str(rooms))
    ok &= check("строка помечена как распознанная", all(r["read"] == "OCR" for r in rows), str({r["read"] for r in rows}))
    rows_off, info_off = hvac_systems.parse_page(page, use_ocr=False)
    ok &= check("без распознавания таблица не выдумывается", rows_off == [])
    kept = {}
    rows_kept, _ = hvac_systems.parse_page(page, ocr_cache=kept)
    rows_again, _ = hvac_systems.parse_page(page, use_ocr=False, ocr_cache=kept)
    ok &= check("прочтения ячеек сохраняются, и по ним лист разбирается заново без Tesseract",
                len(kept) > 0 and rows_kept == rows and rows_again == rows, f"ячеек в словаре {len(kept)}")
    doc.close()
    return ok


def test_helpers():
    print("\n6. Двойники распознавания и голосование")
    ok = check("«82.8, B2.9» — это В2.8 и В2.9", hvac_systems.systems_of("82.8, B2.9") == ["В2.8", "В2.9"])
    ok &= check("опечатка таблицы «В-1,7» — одно обозначение", hvac_systems.systems_of("В-1,7") == ["В-1.7"])
    ok &= check("мусор распознавания обозначением не становится", hvac_systems.systems_of("[2.1") == []
                and hvac_systems.systems_of("ИТОГО") == [])
    ok &= check("«УЗ» — это «У3»: без номера обозначения не бывает; «ТЗ1» с номером не трогается",
                hvac_systems.systems_of("УЗ") == ["У3"] and hvac_systems.systems_of("ТЗ1") == ["ТЗ1"])
    ok &= check("«nom.» и «now.» — это «пом.»", hvac_systems.rooms_of("М.0. (no3.159) 6 now. 198") == ["198"]
                and hvac_systems.positions_of("М.0. (no3.159) 6 now. 198") == ["159"])
    ok &= check("этаж не помещение: «3 эт., пом. 302»", hvac_systems.rooms_of("Тех. центр, 3 эт., пом. 302") == ["302"])
    accepted, doubtful = hvac_systems._vote([["108", "001"], ["108", "201"], ["108", "201"]])
    ok &= check("номер принят двумя прочтениями из трёх, одиночный — сомнительный",
                accepted == ["108", "201"] and doubtful == ["001"], f"{accepted} {doubtful}")
    ok &= check("текстовый слой — одно прочтение, принимается целиком", hvac_systems._vote([["140"]]) == (["140"], []))
    ok &= check("три разных прочтения — ничего не принято", hvac_systems._vote([["12"], ["13"], ["14"]])[0] == [])
    return ok


def main():
    ok = True
    for fn in (test_grid, test_layer_rows, test_rotated_and_unruled, test_not_a_systems_table, test_ocr_cells,
               test_helpers):
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
