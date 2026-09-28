"""Постраничное сравнение пар редакций. Задача #19.

  python tests/test_revision_diff.py

Синтетические тома: страницы совпали, изменилось число, вставлена страница (сдвиг остальных),
удалена страница, сменился только номер листа, слой не читается, а также проверка цепочек
по содержимому: тома без общих страниц — не редакции, переиздание и том-близнец — редакции.

Задача #81 — синтетические листы из слов с координатами: сравнение по месту (лист на месте,
чертёж сдвинут внутри рамки, сменилась только дата штампа «В производство работ», лист
перевыпущен в другом формате, перекомпонован, подпись перенесена), текст, перетёкший между
страницами записки, строки таблицы изменений
штампа, отметки «Изм. N (Зам.)» в ведомости, статусы отметки и гипотезы «без отметки».
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import revision_diff as rd  # noqa: E402
from pipeline import titleblock  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def page(n, body, sheet=None):
    text = f"Раздел проекта, страница {n}.\n" + "\n".join(body)
    if sheet is not None:
        text += f"\nИзм. Кол.уч. Лист {sheet} № док. Подп. Дата"
    return text


BODY = {
    1: ["Общие данные. Объект: школа на 550 мест.", "Заказчик: АО Пример.", "Генеральный проектировщик: ООО Проект."],
    2: ["Технико-экономические показатели.", "Площадь участка 12 345,60 м2.", "Площадь застройки 3 987,30 м2.", "Этажность 3."],
    3: ["Конструктивные решения.", "Фундаментная плита толщиной 600 мм из бетона класса B30.", "Стены подвала B30 W6."],
    4: ["Инженерные системы.", "Вентиляция приточно-вытяжная с механическим побуждением.", "Отопление водяное."],
}


def volume(pages, sheet_from=1, overrides=None):
    overrides = overrides or {}
    out = []
    for i, n in enumerate(pages):
        body = overrides.get(n, BODY[n])
        out.append((i + 1, page(n, body, sheet=sheet_from + i)))
    return out


def status_of(rows, old_page=None, new_page=None):
    for r in rows:
        if (old_page is None or r["old_page"] == old_page) and (new_page is None or r["new_page"] == new_page):
            return r
    return None


def test_pages():
    print("\n1. Страницы пары")
    old = volume([1, 2, 3, 4])
    rows, s = rd.compare(old, volume([1, 2, 3, 4]))
    ok = check("тот же том — все страницы без изменений", s["same"] == 4 and s["changed"] == 0 and s["added"] == 0 and s["removed"] == 0, str(s))
    ok &= check("пара похожа на переиздание", s["looks_like_revision"] is True)
    new = volume([1, 2, 3, 4], overrides={2: ["Технико-экономические показатели.", "Площадь участка 12 345,60 м2.", "Площадь застройки 3 694,60 м2.", "Этажность 3."]})
    rows, s = rd.compare(old, new)
    r = status_of(rows, old_page=2)
    ok &= check("изменилось число на странице 2 — CHANGED с указанием числа",
                s["changed"] == 1 and r["status"] == "CHANGED" and r["numbers"] == ["3 987,30 → 3 694,60"], str(r and r.get("numbers")))
    ok &= check("описание страницы называет число", "3 987,30 → 3 694,60" in rd.describe(r))
    inserted = [(1, page(1, BODY[1], 1)), (2, page(9, ["Состав проектной документации.", "Том 1. Пояснительная записка.", "Том 2. Схема планировочной организации."], 2))]
    inserted += [(i + 3, page(n, BODY[n], i + 3)) for i, n in enumerate([2, 3, 4])]
    rows, s = rd.compare(old, inserted)
    ok &= check("вставлена страница — остальные сдвинулись, но совпали по содержимому: SAME 4, ADDED 1",
                s["same"] == 4 and s["added"] == 1 and s["removed"] == 0 and s["changed"] == 0, str(s))
    r = status_of(rows, new_page=2)
    ok &= check("добавленная страница названа", r["status"] == "ADDED" and rd.describe(r) == "страница добавлена")
    r = status_of(rows, old_page=3)
    ok &= check("страница 3 сопоставлена со страницей 4 новой редакции, номер листа сменился — не изменение",
                r["new_page"] == 4 and r["status"] == "SAME", str(r))
    rows, s = rd.compare(old, volume([1, 2, 4]))
    r = status_of(rows, old_page=3)
    ok &= check("удалена страница 3 — REMOVED", s["removed"] == 1 and r["status"] == "REMOVED" and s["same"] == 3, str(s))
    broken = list(old)
    broken[1] = (2, "\n".join(["ǟ57=8:>-M:>=><8G5A:85 ?>:070B5;8.", "ȼ74<. <=6. 7 >7?4;. <=6. 7", "ǟ2=4 12345,60 <2", "3987,30 <2 >?", "ȼ74<. ǁ>;.CG. ǎ8AB 2"]))
    rows, s = rd.compare(broken, new)
    r = status_of(rows, old_page=2)
    ok &= check("битый слой прежней редакции — UNREADABLE, не изменение",
                r["status"] == "UNREADABLE" and s["unreadable"] == 1 and s["changed"] == 0 and "не читается" in rd.describe(r), str(r))
    return ok


def test_chains():
    print("\n2. Проверка цепочек по содержимому")
    docs = {
        "A": volume([1, 2, 3, 4]),
        "B": volume([1, 2, 3, 4], overrides={2: ["Технико-экономические показатели.", "Площадь участка 12 345,60 м2.", "Площадь застройки 3 694,60 м2.", "Этажность 3."]}),
        "C": [(1, page(1, ["Совсем другой документ.", "Ведомость рабочих чертежей.", "Лист 1 Общие данные."])),
              (2, page(2, ["Спецификация оборудования.", "Позиция 1 насос.", "Позиция 2 задвижка."])),
              (3, page(3, ["Кабельный журнал.", "Кабель 1 от щита до насоса.", "Кабель 2 от щита до задвижки."])),
              (4, page(4, ["Узел учёта.", "Счётчик воды.", "Фильтр."]))],
    }
    texts = lambda d: docs[d["file_id"]]  # noqa: E731
    reg = [{"file_id": f, "revision_status": "SUPERSEDED", "predecessor_file_id": None} for f in ("A", "B", "C")]
    chain = {"chain_id": "X:PD:ПЗ:1", "status": "RESOLVED", "members": ["A", "B"], "order": ["A", "B"], "current_file_id": "B",
             "member_status": {"A": "SUPERSEDED", "B": "CURRENT"}}
    chains, out = rd.verify_chains([dict(chain)], [dict(r) for r in reg], texts)
    ok = check("переиздание с одной изменённой страницей — цепочка остаётся RESOLVED",
               chains[0]["status"] == "RESOLVED" and chains[0]["content_check"][0]["looks_like_revision"] is True, str(chains[0].get("status")))
    chain2 = {"chain_id": "X:PD:ПЗ:2", "status": "RESOLVED", "members": ["A", "C"], "order": ["A", "C"], "current_file_id": "C",
              "member_status": {"A": "SUPERSEDED", "C": "CURRENT"}}
    chains, out = rd.verify_chains([dict(chain2)], [dict(r) for r in reg], texts)
    by = {d["file_id"]: d for d in out}
    ok &= check("тома без общих страниц — UNRELATED, порядка нет, оба действующие",
                chains[0]["status"] == "UNRELATED" and chains[0]["order"] is None and by["A"]["revision_status"] == "CURRENT"
                and by["C"]["revision_status"] == "CURRENT" and "общих по содержимому страниц 0" in chains[0]["reason"], str(chains[0].get("reason")))
    pairs, unordered = rd.pairs_of([chains[0], chain, {"chain_id": "Y", "status": "CLARIFICATION_REQUIRED", "members": ["D", "E"], "order": None}])
    ok &= check("пары строятся только из цепочек с порядком", [(p["old_file_id"], p["new_file_id"]) for p in pairs] == [("A", "B")] and unordered == 2, str(pairs))
    return ok


# ---------------------------------------------------------------- #81: листы из слов с координатами

A2 = (1684.0, 1191.0)       # лист А2 в пунктах, альбомный
A1 = (2384.0, 1684.0)


def sheet_layer(words, size=A2):
    """Слой страницы в виде `reading.read_text_layer`: слова в долях листа, размер в пунктах."""
    w, h = size
    return {"words": [{"t": t, "bbox": [x / w, y / h, (x + max(6.0, 5.0 * len(t))) / w, (y + 8.0) / h]} for t, x, y in words],
            "width_pt": w, "height_pt": h}


def drawing(changes=None, shift=(0.0, 0.0), stamp_date="20.02.26", extra=()):
    """Чертёж: сетка размеров, штамп в правом нижнем углу и штамп «В производство работ»."""
    changes = changes or {}
    words = []
    for k in range(8):
        for m in range(5):
            value = str(1000 + 100 * k + 7 * m)
            words.append((changes.get(value, value), 100 + 150 * k + shift[0], 100 + 120 * m + shift[1]))
    words += [(t, 150 + 60 * i + shift[0], 720 + shift[1]) for i, t in enumerate(("Схема", "расположения", "подготовки", "плиты"))]
    words += [("В", 1330, 880), ("производство", 1345, 880), ("работ", 1420, 880), ("Алдушанков", 1340, 900), (stamp_date, 1340, 915)]
    words += [("Изм.", 1060, 1100), ("Кол.уч.", 1080, 1100), ("Лист", 1120, 1100), ("№док.", 1150, 1100),
              ("23.009-Р-ГИ", 1400, 1000), ("Стадия", 1500, 1060), ("Лист", 1550, 1060), ("Р", 1500, 1075), ("6", 1550, 1075)]
    return words + list(extra)


def test_place():
    print("\n3. Где на листе изменилось (#81)")
    base = sheet_layer(drawing())
    r = rd.place(base, sheet_layer(drawing()))
    ok = check("тот же лист — на месте, изменений нет",
               r["layout"] == "SAME_PLACE" and r["content_removed"] == r["content_added"] == 0 and r["service_removed"] == 0, str(r))
    r = rd.place(base, sheet_layer(drawing(changes={"1307": "1300"})))
    ok &= check("размер 1307 стал 1300 — одна пара «было → стало» и рамки на обеих страницах",
                r["numbers"] == ["1307 → 1300"] and r["content_removed"] == 1 and r["content_added"] == 1
                and len(r["zones_old"]) == 1 and len(r["zones_new"]) == 1, str(r["numbers"]))
    zone = r["zones_new"][0]
    # «1307» стоит на 550 × 220 pt листа 1684 × 1191 pt
    ok &= check("рамка — в долях листа, там, где стоит размер", 0.32 < zone[0] < 0.34 and 0.18 < zone[1] < 0.19, str(zone))
    r = rd.place(base, sheet_layer(drawing(shift=(0.0, -55.0))))
    ok &= check("чертёж сдвинут внутри рамки на 55 pt, штамп на месте — изменений содержания нет",
                r["layout"] == "SHIFTED" and r["content_removed"] == r["content_added"] == 0 and r["service_removed"] == 0,
                str({k: r[k] for k in ("layout", "offsets", "content_removed", "service_removed")}))
    r = rd.place(base, sheet_layer(drawing(stamp_date="14.05.26")))
    ok &= check("сменилась только дата штампа «В производство работ» — служебное поле",
                r["content_removed"] == r["content_added"] == 0 and r["service"] == ["20.02.26 → 14.05.26"], str(r["service"]))
    ok &= check("такая страница — только служебные поля", rd.content_changed({"status": "CHANGED", "place": r}) is False
                and rd.describe({"status": "CHANGED", "place": r}).startswith("изменились только служебные поля"))
    big = [(t, x * A1[0] / A2[0], y * A1[1] / A2[1]) for t, x, y in drawing()]
    r = rd.place(base, sheet_layer(big, size=A1))
    ok &= check("лист перевыпущен в формате А1 с тем же чертежом — RESIZED, изменений нет",
                r["layout"] == "RESIZED" and r["content_removed"] == r["content_added"] == 0, str(r["layout"]))
    other = [(str(3000 + i), 90 + 37 * (i % 30), 80 + 23 * (i // 30)) for i in range(40)]
    r = rd.place(base, sheet_layer(other))
    ok &= check("другой лист — RELAID: мест изменений не показываем", r["layout"] == "RELAID" and not r["zones_new"], r["layout"])
    moved = [(t, x + (12.0 if t == "плиты" else 0.0), y) for t, x, y in drawing()]
    r = rd.place(base, sheet_layer(moved))
    ok &= check("подпись перенесена на 12 pt — сдвиг, а не изменение содержания",
                r["moved"] == 1 and r["content_removed"] == r["content_added"] == 0, str({k: r[k] for k in ("moved", "content_removed")}))
    ok &= check("чертёж из одних размеров читается, битая кодировка — нет",
                rd.readable(["32300 6900 1800 4250 3850 5830 3730"]) and not rd.readable(["Ɉ5M5EF6> E >7D4=<G5==>= «ȻD4FɄ><-7DG??»"]))
    return ok



A4 = (595.0, 842.0)         # лист А4 записки, книжный

PARA = {
    "P": "Раздел освещения предусматривает рабочее аварийное и ремонтное освещение всех помещений здания "
         "с питанием от вводно-распределительного устройства",
    "A": "Для дистанционного тестирования светильников эвакуационного освещения используется устройство "
         "Telecontrol с автоматическим контролем каждого светильника",
    "B": "Светильники над каждым входом в здание номерные знаки и указатели пожарных гидрантов присоединены "
         "к сети аварийного освещения Освещенность от резервного освещения составляет не менее 30 % "
         "нормируемой освещенности от общего рабочего освещения помещений",
    "C": "Замкнутые пространства зданий где человек из МГН может оказаться один оборудованы светильниками "
         "аварийного освещения перепад освещенности между соседними помещениями не более 1:4",
    "D": "Кабельные линии прокладываются в лотках и трубах из негорючих материалов с пределом огнестойкости",
}


def text_page(paras, number, edits=None):
    """Страница записки: абзацы строками по восемь слов сверху вниз, номер страницы в правом
    верхнем углу рамки (служебное поле). edits — замены слов {было: стало}."""
    edits = edits or {}
    words, y = [(str(number), 560.0, 20.0)], 60.0
    for key in paras:
        tokens = [edits.get(t, t) for t in PARA[key].split()]
        for k in range(0, len(tokens), 8):
            words += [(t, 70.0 + 58.0 * m, y) for m, t in enumerate(tokens[k:k + 8])]
            y += 16.0
        y += 8.0
    return sheet_layer(words, size=A4)


def test_flow():
    print("\n4. Текст перетёк между страницами")
    size = lambda key: len(PARA[key].split())  # noqa: E731
    # прежняя редакция: [P] [A B] [C D]; новая: абзац A ушёл в конец предыдущей страницы, C пришёл со следующей
    old = {1: text_page("P", 1), 2: text_page("AB", 2), 3: text_page("CD", 3)}
    new = {1: text_page("PA", 3), 2: text_page("BC", 4), 3: text_page("D", 5)}
    near = lambda pages, n: (rd.page_stream(pages.get(n - 1)), rd.page_stream(pages.get(n + 1)))  # noqa: E731
    r = rd.place(old[2], new[2])
    # («освещения» есть в обоих абзацах — такую пару сравнение по месту считает перенесённой подписью)
    ok = check("без соседних страниц абзацы, ушедший и пришедший, выглядят убранным и добавленным",
               r["content_removed"] >= size("A") - 2 and r["content_added"] >= size("C") - 2 and r["zones_old"] and r["zones_new"],
               str({k: r[k] for k in ("content_removed", "content_added")}))
    r = rd.place(old[2], new[2], old_near=near(old, 2), new_near=near(new, 2))
    row = {"status": "CHANGED", "place": r}
    ok &= check("с соседними — изменений содержания нет, рамок нет, слова посчитаны ушедшими и пришедшими",
                r["content_removed"] == r["content_added"] == 0 and not r["zones_old"] and not r["zones_new"]
                and r["flowed_out"] == size("A") and r["flowed_in"] == size("C"),
                str({k: r[k] for k in ("content_removed", "content_added", "flowed_out", "flowed_in", "zones_old")}))
    ok &= check("такая страница — содержание не изменилось, описание говорит о сдвиге текста",
                rd.content_changed(row) is False
                and rd.describe(row).startswith("содержание не изменилось: текст сдвинулся между страницами"), rd.describe(row))
    edited = {**new, 2: text_page("BC", 4, edits={"30": "50"})}
    r = rd.place(old[2], edited[2], old_near=near(old, 2), new_near=near(edited, 2))
    ok &= check("правка внутри сдвинувшегося текста видна: 30 → 50, остальное — перетекание",
                r["numbers"] == ["30 → 50"] and r["content_removed"] == r["content_added"] == 1
                and r["flowed_out"] == size("A") and rd.content_changed({"status": "CHANGED", "place": r}) is True,
                str({k: r[k] for k in ("numbers", "content_removed", "content_added", "flowed_out")}))
    # чертёж: цепочка размеров снята с листа, а на соседнем листе новой редакции стоит такая же
    chain = [(t, 150 + 90 * i, 650) for i, t in enumerate(("6900", "1800", "6900", "1800", "6900", "1800"))]
    old_sheet, new_sheet = sheet_layer(drawing(extra=chain)), sheet_layer(drawing())
    next_sheet = sheet_layer([(t, x, y + 100) for t, x, y in chain] + [("План", 150, 100), ("кровли", 200, 100)])
    r = rd.place(old_sheet, new_sheet, old_near=(None, None), new_near=(None, rd.page_stream(next_sheet)))
    ok &= check("снятая цепочка размеров не «перетекла» на соседний лист, где стоит такая же",
                r["content_removed"] == len(chain) and r["flowed_out"] == 0,
                str({k: r[k] for k in ("content_removed", "flowed_out")}))
    # «Проверка» в тексте записки над штампом — не подпись штампа первого листа
    body = [("Проверка", 70.0, 720.0), ("срабатывания", 140.0, 720.0), ("автоматики", 230.0, 720.0)]
    words = rd._pt_words(sheet_layer(body + [("Лист", 540.0, 800.0), ("12", 560.0, 815.0)], size=A4))
    inside = rd.service_zone(words, *A4)
    first = rd._pt_words(sheet_layer(body + [("Разраб.", 250.0, 790.0), ("Стадия", 450.0, 770.0)], size=A4))
    ok &= check("«Проверка» в тексте над штампом — не штамп первого листа, строка остаётся содержанием",
                not any(inside(w) for w in words[:3]) and all(rd.service_zone(first, *A4)(w) for w in first[:3]))
    return ok

def ved_words(marks):
    """Ведомость рабочих чертежей на листе 1: шапка, восемь листов, отметки в примечании.
    Строка таблицы вырастает под столбик отметок, номер листа и столбик — по её середине."""
    words = [("Лист", 110, 100), ("Наименование", 250, 100), ("Примечание", 520, 100)]
    top = 112
    for n in range(1, 9):
        numbers = marks.get(n, [])
        height = 10 * max(1, len(numbers)) + 14
        mid = top + height / 2
        words += [(str(n), 112, mid), ("Схема", 250, mid)]
        for k, number in enumerate(numbers):
            y = mid - 5 * (len(numbers) - 1) + 10 * k
            words += [("Изм.", 512, y), (str(number), 535, y), ("(Зам.)", 548, y)]
        top += height
    return words


def stamp_rows(rows):
    """Таблица изменений штампа: номера над подписью «Изм.»."""
    words = [("Изм.", 1060, 1100)]
    for k, (number, doc, date) in enumerate(rows):
        y = 1086 - 14 * k
        words += [(str(number), 1062, y), ("Зам.", 1080, y), (doc, 1120, y), (date, 1180, y)]
    return words


def test_marks():
    print("\n4. Отметки изменений: штамп и ведомость (#81)")
    base = sheet_layer(drawing())
    size = A2
    rows = titleblock.change_rows(sheet_layer(stamp_rows([(1, "91-25", "08.25"), (2, "933-25", "11.25")]))["words"], size)
    ok = check("строки таблицы изменений штампа — номер, вид, документ, дата",
               [(r["number"], r["kind"], r["doc"], r["date"]) for r in rows] == [(1, "Зам.", "91-25", "08.25"), (2, "Зам.", "933-25", "11.25")], str(rows))
    ok &= check("номер последнего изменения — как прежде", titleblock.revision(sheet_layer(stamp_rows([(1, "91-25", "08.25"), (3, "158-26", "02.26")]))["words"], page_size=size) == 3)
    got = rd.listed_changes(sheet_layer(ved_words({1: [1, 2, 3, 4], 2: [1], 4: [1, 3], 8: [1, 2, 3, 4]}))["words"], size)
    ok &= check("ведомость: столбики отметок у листов 1, 2, 4, 8", {k: [m["number"] for m in v] for k, v in got.items()}
                == {1: [1, 2, 3, 4], 2: [1], 4: [1, 3], 8: [1, 2, 3, 4]}, str(got))
    ok &= check("вид изменения из скобок", got[2][0]["kind"] == "Зам.", str(got[2]))
    ok &= check("без шапки «Лист … Наименование» ведомости нет",
                rd.listed_changes(sheet_layer([("Изм.", 512, 124), ("1", 535, 124), ("(Зам.)", 548, 124)])["words"], size) == {})
    old_marks = rd.file_marks([(1, sheet_layer(ved_words({1: [1], 2: [1]})))])
    new_marks = rd.file_marks([(1, sheet_layer(ved_words({1: [1, 2], 2: [1], 4: [2]}))),
                               (5, sheet_layer(drawing(extra=stamp_rows([(2, "933-25", "11.25")]))))])
    ok &= check("отметки файла: номера из ведомости и штампов", new_marks["numbers"] == [1, 2]
                and new_marks["listed"] == {1: [1, 2], 2: [1], 4: [2]} and new_marks["stamp"] == {5: [2]}, str(new_marks))
    ok &= check("таблица изменений читается у листа со штампом, у ведомости — нет", new_marks["readable"] == [5],
                str(new_marks["readable"]))
    # в настоящем томе штамп есть у каждого листа: сверяемые страницы — с читаемой таблицей изменений
    new_marks = dict(new_marks, readable=[1, 4, 5, 6, 7, 9])
    changed = {"layout": "SAME_PLACE", "content_removed": 1, "content_added": 1, "numbers": ["2700 → 1300"],
               "zones_old": [[0.1, 0.1, 0.2, 0.2]], "zones_new": [[0.1, 0.1, 0.2, 0.2]]}
    service = {"layout": "SAME_PLACE", "content_removed": 0, "content_added": 0, "zones_old": [], "zones_new": []}
    rows = [{"status": "CHANGED", "old_page": 1, "new_page": 1, "place": changed},     # лист 1: отмечен в ведомости
            {"status": "CHANGED", "old_page": 4, "new_page": 4, "place": changed},     # лист 4: отмечен в ведомости
            {"status": "CHANGED", "old_page": 5, "new_page": 5, "place": changed},     # лист 5: отмечен в штампе
            {"status": "CHANGED", "old_page": 6, "new_page": 6, "place": changed},     # лист 6: без отметки
            {"status": "CHANGED", "old_page": 7, "new_page": 7, "place": service},     # лист 7: только дата
            {"status": "CHANGED", "old_page": 9, "new_page": 9, "place": changed}]     # номер листа неизвестен
    sheet_of = {1: 1, 4: 4, 5: 5, 6: 6, 7: 7}.get
    summary = rd.registration(rows, old_marks, new_marks, sheet_of)
    status = [r["registration"]["status"] for r in rows]
    ok &= check("новое изменение — 2; листы 1, 4, 5 отмечены, 6 — без отметки, 7 — только служебные поля, 9 — неизвестно",
                summary["introduced"] == [2] and status == ["REGISTERED", "REGISTERED", "REGISTERED", "UNREGISTERED", "NOT_NEEDED", "UNKNOWN"],
                str((summary, status)))
    none = [dict(r) for r in rows]
    rd.registration(none, new_marks, new_marks, sheet_of)
    ok &= check("новых номеров нет — ответа нет, лист без отметки не выдумываем",
                {r["registration"]["status"] for r in none} <= {"UNKNOWN", "NOT_NEEDED"}, str([r["registration"]["status"] for r in none]))
    stamp_only = {"stamp": {5: [2]}, "listed": {}, "numbers": [2]}
    guarded = [dict(r) for r in rows]
    rd.registration(guarded, old_marks, stamp_only, sheet_of)
    ok &= check("ведомости с отметками нет — «без отметки» не утверждается, лист 6 не определён",
                guarded[3]["registration"]["status"] == "UNKNOWN" and "ведомость" in guarded[3]["registration"]["why"],
                str(guarded[3]["registration"]))
    added = [{"status": "ADDED", "old_page": None, "new_page": 6}]
    rd.registration(added, old_marks, new_marks, sheet_of)
    ok &= check("добавленный лист без отметки «Нов.» — не определено, не гипотеза",
                added[0]["registration"]["status"] == "UNKNOWN", str(added[0]["registration"]))
    unread = [dict(r) for r in rows]
    rd.registration(unread, old_marks, dict(new_marks, readable=[5]), sheet_of)
    ok &= check("штамп листа 6 не читается (чертёжный шрифт) — «без отметки» не утверждается",
                unread[3]["registration"]["status"] == "UNKNOWN" and "штампе" in unread[3]["registration"]["why"],
                str(unread[3]["registration"]))
    small = [{"status": "CHANGED", "old_page": 6, "new_page": 6,
              "place": {"layout": "SAME_PLACE", "content_removed": 3, "content_added": 2, "numbers": []}}]
    rd.registration(small, old_marks, new_marks, sheet_of)
    ok &= check("пять изменённых слов без пары чисел — «без отметки» не утверждается",
                small[0]["registration"]["status"] == "UNKNOWN", str(small[0]["registration"]))
    edge = rd.place(base, sheet_layer(drawing(extra=[("Время", 900, 1188), ("печати:", 940, 1188), ("14.05.2026", 990, 1188)])))
    ok &= check("строка печати за рамкой чертежа — служебное поле",
                edge["content_added"] == 0 and edge["service_added"] == 3, str({k: edge[k] for k in ("content_added", "service_added")}))
    tiny = {"status": "CHANGED", "place": {"layout": "SAME_PLACE", "content_removed": 0, "content_added": 2, "numbers": []}}
    ok &= check("два добавленных слова без пары чисел — изменение слишком мало, чтобы судить",
                rd.content_changed(tiny) is None)
    pair = {"old_file_id": "L0012", "new_file_id": "L0013", "old_revision": "изм. 1", "new_revision": "изм. 3",
            "pair_id": "X::REV::L0012-L0013", "introduced": [2]}
    found = rd.unmarked("LOC-TEST", pair, rows, "RD", code="23.009-Р-ГИ")
    ok &= check("гипотеза на лист 6: не для сдачи, свободный поиск, доказательства — обе редакции с рамками",
                len(found) == 1 and found[0]["locations"] == ["23.009-Р-ГИ, лист 6, изм. 3"] and found[0]["for_submission"] is False
                and found[0]["matrix_scope"] == "FREE_SEARCH" and [e["file_id"] for e in found[0]["evidence"]] == ["L0013", "L0012"]
                and found[0]["evidence"][0]["boxes_norm"] == [[0.1, 0.1, 0.2, 0.2]] and "2700 → 1300" in found[0]["rd_value"],
                json.dumps(found[:1], ensure_ascii=False)[:300])
    many = [dict(rows[3], new_page=10 + k, old_page=10 + k, registration=dict(rows[3]["registration"], sheet=10 + k)) for k in range(5)]
    grouped = rd.unmarked("LOC-TEST", pair, many, "RD", code="23.009-Р-ГИ")
    ok &= check("пять листов без отметки — одна запись с перечнем",
                len(grouped) == 1 and grouped[0]["locations"] == ["23.009-Р-ГИ, листы 10, 11, 12, 13, 14, изм. 3"]
                and len(grouped[0]["evidence"]) == rd.MAX_EVIDENCE, str(grouped[0]["locations"]))
    try:
        import jsonschema
        schema = json.load(open(os.path.join(ROOT, "contracts", "finding.schema.json"), encoding="utf-8"))
        for f in found + grouped:
            jsonschema.validate(f, schema)
        ok &= check("гипотезы проходят схему находки contracts/finding.schema.json", True)
    except ImportError:
        print("  [--  ] jsonschema не установлен: схема находки не проверялась")
    return ok


def main():
    ok = True
    for fn in (test_pages, test_chains, test_place, test_flow, test_marks):
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
