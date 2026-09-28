"""Сравнение стадий по помещениям и установкам, пары листов ПД — РД. Задачи #21, #37.

  python tests/test_room_compare.py

Решение по помещению проверяется на строках таблиц, собранных руками. Сквозной путь — на
синтетическом объекте из двух PDF: таблица характеристик систем, проектная схема с марками
у помещений, рабочий план с экспликацией, перечень оборудования. Объект придуман для теста,
ни одна его строка не взята из корпуса.
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# сборка и кеш теста — во временном каталоге, до импорта конвейера
_TMP = tempfile.mkdtemp(prefix="rooms-")
os.environ["PIPELINE_OUT"] = os.path.join(_TMP, "build")
os.environ["PIPELINE_CACHE"] = os.path.join(_TMP, "cache")

import pymupdf  # noqa: E402

from pipeline import config, matrix_rules, registry, room_compare, sheet_pairs, vent_units  # noqa: E402

FONT = pymupdf.Font("cour")


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def row(stage, systems, count, rooms, positions=(), flow=None, source="LAYER", doubtful=()):
    return {"stage": stage, "systems": list(systems), "system_raw": ", ".join(systems), "count": count,
            "served": "пом. " + ", ".join(rooms), "rooms": list(rooms), "rooms_doubtful": list(doubtful),
            "positions": list(positions), "flow": flow, "source": source, "read": source,
            "file_id": "F0001" if stage == "PD" else "F0002", "pdf_page_number": 1, "document": f"{stage}.pdf",
            "section": "OV", "bbox": [0.1, 0.1, 0.2, 0.12]}


def test_decide():
    print("\n1. Решение по помещению")
    pd = [row("PD", ["В2.7", "В2.8", "В2.9"], 3, ["140"], ["169"])]
    label, result, _ = room_compare.decide(pd, [])
    ok = check("в рабочей стадии помещение не названо — отсутствует проектное решение",
               (label, result) == ("VIOLATION_PRESENT", "MISSING_DESIGN_ELEMENT"))
    label, _, detail = room_compare.decide(pd, [], rd_doubtful=True)
    ok &= check("номер в РД прочитан одним прочтением из трёх — сравнение невозможно", label == "COMPARISON_IMPOSSIBLE", detail)

    label, result, detail = room_compare.decide([row("PD", ["В2.10"], 1, ["147"], ["160"])],
                                                [row("RD", ["В2.2"], 1, ["147"], ["159"]),
                                                 row("RD", ["В2.3", "В2.4"], 2, ["147"], ["160"])])
    ok &= check("проектную систему заменили другими — изменена конфигурация",
                (label, result) == ("VIOLATION_PRESENT", "CONFIGURATION_MISMATCH") and "В2.10" in detail, detail)

    label, result, detail = room_compare.decide([row("PD", ["В10.5"], 1, ["131"])],
                                                [row("RD", ["В10.5"], 1, ["131"]), row("RD", ["ВД26"], 1, ["131"])])
    ok &= check("к проектным системам добавили новую — не нарушение",
                label == "NO_VIOLATION" and "ВД26" in detail, detail)

    label, result, _ = room_compare.decide([row("PD", ["У2"], 3, ["124"])], [row("RD", ["У2"], 2, ["124"])])
    ok &= check("систем меньше, чем в проекте — нарушение", (label, result) == ("VIOLATION_PRESENT", "CONFIGURATION_MISMATCH"))

    label, result, _ = room_compare.decide([row("PD", ["82.4"], 1, ["150"], source="OCR")],
                                           [row("RD", ["B2.4"], 1, ["150"], source="OCR")])
    ok &= check("двойники распознавания «82.4» и «B2.4» — одна система", (label, result) == ("NO_VIOLATION", "EQUAL_PD_RD"))

    label, _, detail = room_compare.decide([row("PD", ["ВД11", "ПД11"], 2, ["245"])],
                                           [row("RD", ["ВД11"], 1, ["245"]), row("RD", [], 1, ["245"])])
    ok &= check("обозначение в РД не разобрано — замена не утверждается", label == "COMPARISON_IMPOSSIBLE", detail)

    label, result, detail = room_compare.decide([row("PD", ["В1"], 1, ["201"], flow=1000)],
                                                [row("RD", ["В1"], 1, ["201"], flow=800)])
    ok &= check("расход меньше проектного — нарушение", (label, result) == ("VIOLATION_PRESENT", "VALUE_DECREASE"), detail)
    label, _, _ = room_compare.decide([row("PD", ["В1"], 1, ["201"], flow=1000)], [row("RD", ["В1"], 1, ["201"], flow=980)])
    ok &= check("расход в пределах округления — не нарушение", label == "NO_VIOLATION")

    label, result, detail = room_compare.decide([row("PD", ["В2.12"], 1, ["339"], ["159"])],
                                                [row("RD", ["В2.12"], 1, ["339"], ["162"])])
    ok &= check("другая позиция оборудования при том же составе — не нарушение, но названо",
                label == "NO_VIOLATION" and "162" in detail, detail)
    return ok


def test_compare_guards():
    print("\n2. Защита от непрочитанной таблицы")
    pd = [row("PD", [f"В{i}"], 1, [str(100 + i)]) for i in range(10)]
    rd_full = [row("RD", [f"В{i}"], 1, [str(100 + i)]) for i in range(9)]
    got, refusal = room_compare.compare(pd + rd_full)
    labels = {room: label for room, _, _, label, _, _ in got}
    ok = check("полная таблица РД: пропавшее помещение — нарушение",
               refusal is None and labels["109"] == "VIOLATION_PRESENT" and labels["100"] == "NO_VIOLATION")
    got, refusal = room_compare.compare(pd + rd_full[:5])
    labels = {room: label for room, _, _, label, _, _ in got}
    ok &= check("таблица РД вдвое короче проектной — «нет в РД» ничего не доказывает",
                labels["109"] == "COMPARISON_IMPOSSIBLE" and labels["100"] == "NO_VIOLATION", str(labels))
    got, refusal = room_compare.compare(pd + rd_full[:3])
    ok &= check("таблица стадии не прочитана — находок нет вовсе", got == [] and "рабочей" in (refusal or ""), str(refusal))

    copy = [dict(r, file_id="F0009", section="OTHER", document="ООС.pdf") for r in pd[:4]]
    kept = room_compare._authoritative(pd + copy + rd_full)
    ok &= check("копия таблицы из чужого раздела не удваивает системы",
                sum(1 for r in kept if r["stage"] == "PD") == len(pd) and all(r["section"] == "OV" for r in kept))
    kept = room_compare._authoritative(copy + rd_full)
    ok &= check("если своей таблицы раздела ОВ нет, берётся копия", sum(1 for r in kept if r["stage"] == "PD") == 4)

    doubtful_pd = [row("PD", ["ПД1"], 1, ["108", "201"], doubtful=["001"])] + pd
    got, _ = room_compare.compare(doubtful_pd + rd_full + [row("RD", ["ПД1"], 1, ["108", "201"])])
    ok &= check("сомнительный номер «001» в сравнение не попадает", "001" not in {room for room, *_ in got})
    return ok


def test_sheet_pairs():
    print("\n3. Пары листов ПД — РД")
    docs = {"P": {"stage": "PD", "section": "OV"}, "R": {"stage": "RD_ID_MIXED", "section": "OV"},
            "K": {"stage": "RD", "section": "KR"}}
    plan = []
    for n in range(101, 121):                       # схема проекта: этажи 1 и 2 на одном листе
        plan.append({"file_id": "P", "pdf_page_number": 10, "number": str(n)})
        plan.append({"file_id": "P", "pdf_page_number": 10, "number": str(n + 100)})
        for page in (5, 9):                         # два плана первого этажа: вентиляция и кондиционирование
            plan.append({"file_id": "R", "pdf_page_number": page, "number": str(n)})
        plan.append({"file_id": "R", "pdf_page_number": 6, "number": str(n + 100)})
        plan.append({"file_id": "K", "pdf_page_number": 3, "number": str(n)})
    titles = {("P", 10): "Принципиальная схема систем общеобменной вентиляции (продолжение №3)",
              ("R", 5): "План 1-го этажа (вентиляция)", ("R", 9): "План 1-го этажа (кондиционирование)",
              ("R", 6): "План 2-го этажа (вентиляция)"}
    got = sheet_pairs.pairs(plan, docs, titles)[("P", 10)]
    pages = [(r["file_id"], r["pdf_page_number"]) for r in got]
    ok = check("схеме на два этажа соответствуют оба поэтажных плана", ("R", 5) in pages and ("R", 6) in pages, str(pages))
    ok &= check("лист другого раздела парой не становится", ("K", 3) not in pages)
    ok &= check("план той же дисциплины выше плана кондиционирования", pages.index(("R", 5)) < pages.index(("R", 9)), str(pages))
    room = sheet_pairs.for_room(sheet_pairs.pairs(plan, docs, titles), ("P", 10), "215")
    ok &= check("для помещения второго этажа — план второго этажа", [(r["file_id"], r["pdf_page_number"]) for r in room] == [("R", 6)])
    no_titles = [(r["file_id"], r["pdf_page_number"]) for r in sheet_pairs.pairs(plan, docs)[("P", 10)]]
    ok &= check("без наименований листов пары всё равно есть, порядок — по составу помещений", set(no_titles) == set(pages))
    words = [("Стадия", 40.0, 28.0), ("План", 110.0, 12.0), ("1-го", 100.0, 12.0), ("этажа", 88.0, 12.0),
             ("(вентиляция)", 70.0, 8.0), ("Отопление,", 110.0, 30.0), ("кондиционирование", 80.0, 26.0)]
    name = sheet_pairs.sheet_name(words)
    ok &= check("наименование листа — только графа 4 основной надписи, без наименования комплекта",
                name == "План 1-го этажа (вентиляция)" and sheet_pairs.disciplines(name) == {"VENT"}, name)
    ok &= check("скобка без дисциплины не мешает: «схема … вентиляции (начало)»",
                sheet_pairs.disciplines("Принципиальная схема систем вентиляции (начало)") == {"VENT"})
    return ok


def test_sheet_names():
    print("\n3б. Наименование листа как признак пары")
    # Оформление второго вида: рабочая стадия повторяет чертёж проектной, а лист «Общие данные»
    # с экспликацией перечисляет все помещения этажа и по составу помещений обгоняет настоящий план.
    docs = {"P": {"stage": "PD", "section": "VK"}, "R": {"stage": "RD", "section": "VK"},
            "A": {"stage": "RD", "section": "AR"}}
    plan = []
    for n in range(1, 21):
        plan.append({"file_id": "P", "pdf_page_number": 4, "number": str(100 + n)})       # план 1 этажа, 20 помещений
        plan.append({"file_id": "R", "pdf_page_number": 2, "number": str(100 + n)})       # «Общие данные»: все помещения
        plan.append({"file_id": "R", "pdf_page_number": 2, "number": str(200 + n)})
        if n <= 12:
            plan.append({"file_id": "R", "pdf_page_number": 5, "number": str(100 + n)})   # настоящий план: часть подписей
            plan.append({"file_id": "R", "pdf_page_number": 6, "number": str(100 + n)})   # план другого этажа с теми же номерами
    titles = {("P", 4): "Пожаротушение. План 1 этажа М 1:100", ("R", 2): "Общие данные",
              ("R", 5): "Пожаротушение. План 1 этажа", ("R", 6): "Пожаротушение. План 2 этажа",
              ("P", 7): "Аксонометрическая схема систем пожаротушения 1 этажа",
              ("R", 8): "Аксонометрическая схема систем пожаротушения 1 этажа",
              ("A", 3): "Аксонометрическая схема систем пожаротушения 1 этажа"}
    paired = sheet_pairs.pairs(plan, docs, titles)
    first = paired[("P", 4)][0]
    ok = check("лист с тем же наименованием идёт первым, хотя «Общие данные» содержат все помещения",
               (first["file_id"], first["pdf_page_number"]) == ("R", 5) and first["by"] == "BOTH",
               str([(r["pdf_page_number"], r["score"]) for r in paired[("P", 4)]]))
    second_floor = next(r for r in paired[("P", 4)] if r["pdf_page_number"] == 6)
    ok &= check("масштаб в наименовании не мешает, а другой этаж по наименованию не пара",
                first["name_similarity"] == 1.0 and second_floor["name_similarity"] == 0.0)
    scheme = [(r["file_id"], r["pdf_page_number"], r["by"]) for r in paired.get(("P", 7), [])]
    ok &= check("лист без помещений находит пару по наименованию — только в своём разделе",
                scheme == [("R", 8, "NAME")], str(scheme))
    ok &= check("общее наименование само по себе парой не делает",
                sheet_pairs.pairs([], docs, {("P", 1): "Общие данные", ("R", 1): "Общие данные"}) == {})
    words = sheet_pairs.name_words("Изм. Кол.Лист № Подп. Дата Проверил Разработал")
    ok &= check("подписи граф основной надписи наименованием не считаются", words == (set(), set()), str(words))
    return ok


def test_titles_sources():
    print("\n3а. Наименование листа: слой и распознанный угол не смешиваются")
    from pipeline import reading
    mm = 72 / 25.4
    width, height = 420 * mm, 297 * mm

    def layer_word(text, dx, dy):
        x, y = 1 - dx / 420, 1 - dy / 297
        return {"t": text, "bbox": [x - 0.01, y - 0.004, x + 0.01, y + 0.004]}

    def put_corner(sha, words):
        folder = os.path.join(config.CACHE, "tbocr", sha[:2])
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, f"{sha}-00001.json"), "w", encoding="utf-8") as f:
            json.dump({"words": [{"t": t, "dx": dx, "dy": dy} for t, dx, dy in words]}, f, ensure_ascii=False)

    both, scan = "ab" * 32, "cd" * 32
    reading.cache_put(both, 1, "read", {"words": [layer_word("План", 110, 12), layer_word("подвала", 95, 12),
                                                  layer_word("(вентиляция)", 75, 12)],
                                        "width_pt": width, "height_pt": height})
    put_corner(both, [("Ллан", 110, 12), ("подбала", 95, 12), ("(вентиляция)", 75, 12)])
    put_corner(scan, [("План", 110, 12), ("кровли", 95, 12), ("(отопление)", 75, 12)])
    titles = room_compare._titles({"A": {"sha256": both}, "B": {"sha256": scan}}, {("A", 1), ("B", 1)})
    ok = check("у листа со слоем наименование берётся из слоя и не сдваивается",
               titles.get(("A", 1)) == "План подвала (вентиляция)", str(titles.get(("A", 1))))
    ok &= check("у листа без слоя — из распознанного угла", titles.get(("B", 1)) == "План кровли (отопление)",
                str(titles.get(("B", 1))))
    # листа нет в кеше чтения (чистый клон, объект без закоммиченного кеша): слова берутся прямо из PDF
    root = os.path.join(_TMP, "Без кеша")
    os.makedirs(root, exist_ok=True)
    pdf = pymupdf.open()
    page = pdf.new_page(width=width, height=height)
    writer = pymupdf.TextWriter(page.rect)
    for text, dx in (("Разрез", 112), ("по", 98), ("оси", 92), ("Б", 84)):
        writer.append((width - dx * mm, height - 12 * mm), text, font=FONT, fontsize=9)
    writer.write_text(page)
    pdf.save(os.path.join(root, "лист.pdf"))
    pdf.close()
    fresh = {"C": {"sha256": "ef" * 32, "relative_path": "лист.pdf"}}
    ok &= check("листа нет в кеше чтения — наименование читается из PDF",
                room_compare._titles(fresh, {("C", 1)}, root).get(("C", 1)) == "Разрез по оси Б",
                str(room_compare._titles(fresh, {("C", 1)}, root)))
    ok &= check("без корня объекта и без кеша наименования нет, сбоя тоже", room_compare._titles(fresh, {("C", 1)}) == {})
    return ok


def test_units():
    print("\n4. Установки: перечень оборудования и место на схеме")
    flat = "Итого по П17 (L=9060 м3/ч, Pc=350 Па) 100 В2.3,В2.4 (L=170 м3/ч, Pc=200 Па) ВД1 (L=13000 м3/ч, Pc=500 Па)"
    got = {d["unit"]: d["flow"] for d in vent_units.unit_duties(flat)}
    ok = check("установки с расходом; противодымные не берутся", got == {"П17": 9060, "В2.3": 170, "В2.4": 170}, str(got))
    mm = vent_units.MM
    words = [(100 * mm, 100 * mm, 110 * mm, 104 * mm, "П17"), (130 * mm, 100 * mm, 140 * mm, 104 * mm, "012"),
             (400 * mm, 100 * mm, 410 * mm, 104 * mm, "006"), (405 * mm, 60 * mm, 415 * mm, 64 * mm, "П1"),
             (700 * mm, 100 * mm, 710 * mm, 104 * mm, "П5")]
    near = vent_units.nearest_rooms(words, 800 * mm, 300 * mm, {"П17", "П1", "П5"})
    ok &= check("ближайший номер помещения, расстояние в миллиметрах листа",
                near["П17"][0] == "012" and near["П1"][0] == "006" and "П5" not in near, str(near))
    room, sheets = vent_units.vote_room([("a", "012", 30.0), ("b", "012.1", 60.0), ("c", "007", 80.0)])
    ok &= check("форкамера «012.1» голосует за «012»", room == "012" and len(sheets) == 2, f"{room} {len(sheets)}")
    return ok


# ---------- сквозной путь на синтетическом объекте ----------

HEAD = ["Обозначение системы", "Кол. систем", "Наименование обслуживаемого помещения", "Тип установки"]
XS = [60, 170, 230, 560, 700]


def table_page(doc, rows):
    page = doc.new_page(width=842, height=595)
    shape = page.new_shape()
    top, head_h, row_h = 60, 46, 22
    ys = [top, top + head_h] + [top + head_h + row_h * (i + 1) for i in range(len(rows))]
    for x in XS:
        shape.draw_line((x, top), (x, ys[-1]))
    for y in ys:
        shape.draw_line((XS[0], y), (XS[-1], y))
    shape.finish(width=0.7)
    shape.commit()
    writer = pymupdf.TextWriter(page.rect)
    writer.append((300, 40), "Характеристика отопительно-вентиляционных систем", font=FONT, fontsize=10)
    for c, head in enumerate(HEAD):
        for k, part in enumerate(head.split(" ", 1)):
            writer.append((XS[c] + 3, top + 14 + 12 * k), part, font=FONT, fontsize=8)
    for i, cells in enumerate(rows):
        for c, value in enumerate(cells):
            writer.append((XS[c] + 3, top + head_h + row_h * i + 15), value, font=FONT, fontsize=8)
    writer.write_text(page)


def drawing_page(doc, labels, title):
    """Чертёжный лист А1 с подписями (x, y, текст) и наименованием в графе 4 основной надписи."""
    mm = vent_units.MM
    page = doc.new_page(width=841 * mm, height=594 * mm)
    writer = pymupdf.TextWriter(page.rect)
    for x, y, text in labels:
        writer.append((x * mm, y * mm), text, font=FONT, fontsize=9)
    writer.append(((841 - 120) * mm, (594 - 10) * mm), title, font=FONT, fontsize=8)
    writer.write_text(page)


def equipment_page(doc, units):
    page = doc.new_page(width=595, height=842)
    writer = pymupdf.TextWriter(page.rect)
    for i, (unit, flow) in enumerate(units):
        writer.append((60, 80 + 22 * i), f"Итого по {unit} (L={flow} м3/ч, Pc=300 Па) 12 345,00", font=FONT, fontsize=9)
    writer.write_text(page)


def build_object(root):
    pd_rows = [["В2.7, В2.8", "2", "М.О. (поз.169) в пом. 140", "Канальный"],
               ["В2.10", "1", "М.О. (поз.160) в пом. 147", "Канальный"],
               ["В10.5", "1", "Серверная, пом.131, 1 эт.", "Канальный"],
               ["У2", "3", "Тамбур (пом. 124)", "Завеса"],
               ["В12.1", "1", "Медблок, пом.160, 161", "Канальный"],
               ["В4", "1", "Читальный зал, пом. 331", "Канальный"],
               ["П17", "1", "Пищеблок, 1 эт.", "Напольная"]]
    rd_rows = [["В2.2", "1", "М.О. (поз.159) в пом. 147", "Канальный"],
               ["В2.3", "1", "М.О. (поз.160) в пом. 147", "Канальный"],
               ["В10.5", "1", "Серверная, пом.131, 1 эт.", "Канальный"],
               ["ВД26", "1", "Пом. 131", "Крышный"],
               ["У2", "2", "Тамбур (пом. 124)", "Завеса"],
               ["В12.1", "1", "Медблок, пом.160, 161", "Канальный"],
               ["В4", "1", "Читальный зал, пом. 331", "Канальный"],
               ["П17.1", "1", "Пищеблок, 1 эт.", "Подвесная"]]
    rooms = ["124", "131", "140", "147", "160", "161", "331", "012"]
    pd = pymupdf.open()
    table_page(pd, pd_rows)
    drawing_page(pd, [(100 + 60 * i, 200, n) for i, n in enumerate(rooms)]
                 + [(100 + 60 * i + 10, 200, "Кабинет") for i in range(len(rooms))]
                 + [(100 + 60 * 2, 190, "В2.7"), (100 + 60 * 3, 190, "В2.10"), (100 + 60 * 7 + 20, 215, "П17")],
                 "Принципиальная схема систем вентиляции (начало)")
    equipment_page(pd, [("П17", 9000), ("В2.7", 950), ("В2.10", 170), ("В10.5", 100), ("В12.1", 300), ("В4", 600)])
    rd = pymupdf.open()
    table_page(rd, rd_rows)
    drawing_page(rd, [(100 + 60 * i, 400, n) for i, n in enumerate(rooms)]
                 + [(100 + 60 * i + 10, 400, "Кабинет") for i in range(len(rooms))], "План 1-го этажа (вентиляция)")
    equipment_page(rd, [("П17.1", 4000), ("П17.2", 5000), ("В2.2", 720), ("В10.5", 100), ("В12.1", 300), ("В4", 600)])
    for stage, name, doc in (("Проектная документация", "12-24-П-ИОС4.pdf", pd), ("Рабочая документация", "12-24-Р-ОВ1.pdf", rd)):
        os.makedirs(os.path.join(root, stage), exist_ok=True)
        doc.save(os.path.join(root, stage, name))
        doc.close()


def test_end_to_end():
    print("\n5. Сквозной путь: объект из двух PDF")
    obj = "OBJ-TEST-ROOMS"
    root = os.path.join(_TMP, "Объект")
    build_object(root)
    config.register_object(obj, root, "Синтетический объект", split="EXTERNAL")
    docs = registry.build(obj)
    os.makedirs(os.path.join(config.OUT, obj), exist_ok=True)
    with open(os.path.join(config.OUT, obj, "documents.jsonl"), "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    stages = {d["relative_path"].split("/")[0]: (d["stage"], d["section"]) for d in docs}
    ok = check("стадия и раздел томов определены по пути", sorted(stages.values()) == [("PD", "OV"), ("RD", "OV")], str(stages))

    rules = matrix_rules.load_rules(matrix_rules.QUEUES[5])
    findings, summary = matrix_rules.build_findings(obj, rules=rules)
    rooms = {f["locations"][0]: f for f in findings if f["parameter_code"] == "IOS4-078" and f["location_type"] == "ROOM"}
    ok &= check("находки по помещениям пришли из правила Матрицы IOS4-078", set(rooms) == {"124", "140", "147"}, str(sorted(rooms)))
    ok &= check("140 — системы отсутствуют, 147 — заменены, 124 — стало меньше",
                rooms["140"]["comparison_result"] == "MISSING_DESIGN_ELEMENT"
                and rooms["147"]["comparison_result"] == "CONFIGURATION_MISMATCH"
                and rooms["124"]["comparison_result"] == "CONFIGURATION_MISMATCH")
    # На рабочем плане марок нет ни у одного помещения, на проектной схеме подписаны только 140, 147 и 012:
    # отсутствие марки на листе находкой не становится, решает таблица систем обеих стадий.
    ok &= check("система, не показанная на этом листе, но названная в таблицах обеих стадий, — не находка",
                not {"131", "160", "161", "331"} & set(rooms), str(sorted(rooms)))
    equal = next((f for f in findings if f["finding_id"].endswith("rooms-equal")), {})
    ok &= check("совпавшие помещения — одной записью, добавленная в РД система названа в пояснении",
                equal.get("violation_label") == "NO_VIOLATION" and "ВД26" in equal.get("extraction", {}).get("detail", ""),
                equal.get("extraction", {}).get("detail", "")[:160])
    roles = [(e["stage"], e.get("role")) for e in rooms["140"]["evidence"]]
    ok &= check("доказательства: строка таблицы ПД, лист таблицы РД, проектная схема и парный рабочий план",
                ("PD", "SYSTEMS_TABLE") in roles and ("RD", "SYSTEMS_TABLE") in roles and ("PD", "SCHEME") in roles
                and ("RD", "PLAN") in roles, str(roles))
    boxes = [e for e in rooms["140"]["evidence"] if e.get("bbox_norm")]
    ok &= check("у строки таблицы и у подписи на схеме есть рамка", len(boxes) >= 2)

    units = [f for f in findings if f["parameter_code"] == "IOS4-079" and f["violation_label"] == "VIOLATION_PRESENT"]
    ok &= check("установка П17 заменена на П17.1 и П17.2 — находка IOS4-079 с адресом по схеме",
                len(units) == 1 and units[0]["locations"] == ["012"] and "П17.1" in units[0]["rd_value"],
                str([(f["finding_id"], f["locations"]) for f in units]))
    ok &= check("В2.10 тоже пропала из перечня, но её помещение 147 уже названо находкой — второй записи нет",
                not any("В2.10" in f["finding_id"] for f in units))
    from pipeline import submission
    body, _ = submission.build(obj, findings, allowed_files={d["file_id"] for d in docs},
                               stage_by_file={d["file_id"]: d["stage"] for d in docs})
    ok &= check("находки проходят схему сдачи организатора", submission.validate(body) == [], str(submission.validate(body)[:2]))
    return ok


def test_nothing_to_compare():
    print("\n6. Объект, где сравнивать нечего")
    import shutil
    obj = "OBJ-TEST-ROOMS-PD-ONLY"
    root = os.path.join(_TMP, "Объект без рабочей стадии")
    stage = "Проектная документация"
    os.makedirs(os.path.join(root, stage), exist_ok=True)
    shutil.copy(os.path.join(_TMP, "Объект", stage, "12-24-П-ИОС4.pdf"), os.path.join(root, stage, "12-24-П-ИОС4.pdf"))
    config.register_object(obj, root, "Синтетический объект без РД", split="EXTERNAL")
    docs = registry.build(obj)
    os.makedirs(os.path.join(config.OUT, obj), exist_ok=True)
    with open(os.path.join(config.OUT, obj, "documents.jsonl"), "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    findings, summary = matrix_rules.build_findings(obj, rules=matrix_rules.load_rules(matrix_rules.QUEUES[5]))
    made = [f for f in findings if f["parameter_code"] in ("IOS4-078", "IOS4-079")]
    ok = check("находок по помещениям и установкам нет", made == [], str([f["finding_id"] for f in made]))
    ok &= check("причина названа и указывает на рабочую стадию",
                "IOS4-078: в рабочей стадии нет документов отопления и вентиляции" in (summary.get("пояснения") or ""),
                str(summary.get("пояснения")))
    return ok


def main():
    ok = True
    for fn in (test_decide, test_compare_guards, test_sheet_pairs, test_sheet_names, test_titles_sources, test_units, test_end_to_end,
               test_nothing_to_compare):
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
