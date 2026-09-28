"""Откуда правила Матрицы берут текст страницы. Задача #52.

  python tests/test_page_texts.py

Первый источник — текстовый слой PDF. Там, где слоя нет, берётся распознанный текст
из кеша чтения, если он там есть: на объекте, где рабочая документация — сканы,
правилам иначе нечего читать. Само распознавание отсюда не запускается.

Источник едет вместе с текстом (`LAYER`, `RECOGNIZED`, `DOCX`) и доходит до находки:
распознавание путает цифры, и инспектор должен видеть, что значение прочитано машиной.

Скан со штампом (#116): в слое несколько слов штампа, шаг чтения называет страницу
`SCAN_SPARSE` и распознаёт её. Правила берут распознанное и там, а у чертежа со слоем
оставляют слой.

Документы организатора не нужны: PDF собирается здесь же.
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def make_pdf(path, texts=("Класс бетона B25 по проекту, толщина плиты 200 мм", "")):
    """Страница на каждый текст; пустой текст — страница без слоя, как отсканированный лист.

    По умолчанию две страницы: первая с текстовым слоем, вторая без него.
    """
    import pymupdf
    doc = pymupdf.open()
    for text in texts:
        page = doc.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(72, 72, 540, 770), text)
    doc.save(path)
    doc.close()
    return path


def setup(tmp, texts=None):
    """Каталог кеша, документ реестра и PDF. Возвращает (doc, root)."""
    os.environ["PIPELINE_CACHE"] = os.path.join(tmp, "cache")
    for name in [m for m in list(sys.modules) if m.startswith("pipeline")]:
        del sys.modules[name]          # config читает переменные при импорте
    root = os.path.join(tmp, "docs")
    os.makedirs(root, exist_ok=True)
    if texts is None:
        make_pdf(os.path.join(root, "kj.pdf"))
    else:
        make_pdf(os.path.join(root, "kj.pdf"), texts)
    doc = {"file_id": "F0001", "relative_path": "kj.pdf", "extension": ".pdf",
           "sha256": "a" * 64, "stage": "RD"}
    return doc, root


def rows_layer(doc, root):
    """Слой страниц тестового PDF, как его прочтёт PyMuPDF: у встроенного шрифта нет кириллицы,
    и буквы приходят знаками «?», поэтому проверки опираются на длину и латиницу."""
    import pymupdf
    pdf = pymupdf.open(os.path.join(root, doc["relative_path"]))
    out = {i + 1: pdf[i].get_text("text") for i in range(pdf.page_count)}
    pdf.close()
    return out


def put_recognized(sha, page_no, text, source="TESSERACT", kind="SCAN_NO_TEXT", layer=""):
    """Запись кеша чтения. Тип скана хранится как есть, а тип страницы со слоем кеш пересчитывает
    по словам и размеру листа (`reading.cache_get`): у чертежа — слова слоя и лист А3."""
    from pipeline import reading
    drawing = kind == "DRAWING"
    reading.cache_put(sha, page_no, "read", {"version": 2, "kind": kind, "text": text, "text_source": source,
                                             "words": [{"t": w} for w in layer.split()],
                                             "images": 0 if drawing else 1,
                                             "width_pt": 1191 if drawing else 841, "height_pt": 842 if drawing else 595})


def test_layer_first():
    with tempfile.TemporaryDirectory() as tmp:
        doc, root = setup(tmp)
        from pipeline import matrix_rules as mr
        # у чертежа со слоем модель пересказывает тот же лист: текст в кеше чтения — слой и пересказ
        put_recognized(doc["sha256"], 1, "совсем другой текст", source="UNION", kind="DRAWING",
                       layer=rows_layer(doc, root)[1])
        rows = list(mr.page_texts_src(doc, root))
        ok = check("страниц столько, сколько в документе", len(rows) == 2, str(len(rows)))
        page, text, source = rows[0]
        ok &= check("страница со слоем читается слоем, распознанное её не подменяет",
                    (source, "B25" in text) == ("LAYER", True), f"{source} «{text.strip()[:40]}»")
        return ok


def test_recognized_where_no_layer():
    with tempfile.TemporaryDirectory() as tmp:
        doc, root = setup(tmp)
        from pipeline import matrix_rules as mr
        put_recognized(doc["sha256"], 2, "Бетон B30 F150 W6")
        rows = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        text, source = rows[2]
        ok = check("на странице без слоя берётся распознанный текст",
                   (source, "B30" in text) == ("RECOGNIZED", True), f"{source} «{text[:40]}»")
        ok &= check("обёртка page_texts отдаёт пары «страница, текст» как раньше",
                    dict(mr.page_texts(doc, root))[2] == text)
        return ok


def test_nothing_to_read():
    with tempfile.TemporaryDirectory() as tmp:
        doc, root = setup(tmp)
        from pipeline import matrix_rules as mr
        rows = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        text, source = rows[2]
        ok = check("нет ни слоя, ни распознанного — пустая страница, а не ошибка",
                   (text.strip(), source) == ("", "LAYER"), f"{source} «{text[:20]}»")
        from pipeline import reading
        reading.cache_put(doc["sha256"], 2, "read", {"version": 2, "kind": "TEXT", "text": "слой",
                                                     "text_source": "TEXT_LAYER"})
        ok &= check("запись кеша чтения со слоем распознанной не считается",
                    mr.recognized_text(doc["sha256"], 2) is None)
        return ok


def test_recognized_after_cache():
    """Документ прочитали правилами, а распознали позже: текст должен дойти без стирания кеша."""
    with tempfile.TemporaryDirectory() as tmp:
        doc, root = setup(tmp)
        from pipeline import matrix_rules as mr
        first = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        ok = check("сначала страницы без слоя пусты", first[2] == ("", "LAYER"), str(first[2]))
        put_recognized(doc["sha256"], 2, "Бетон B30 F150 W6")     # распознали после
        second = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        ok &= check("распознанное дошло до правил на следующем чтении",
                    second[2] == ("Бетон B30 F150 W6", "RECOGNIZED"), str(second[2]))
        ok &= check("страница со слоем не тронута", second[1] == first[1])
        third = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        ok &= check("обновлённый кеш отдаёт то же самое", third == second)
        return ok


def test_stale_cache_rebuilt():
    """Кеш прежнего образца собран до того, как правила читали распознанное, — он пересобирается."""
    with tempfile.TemporaryDirectory() as tmp:
        doc, root = setup(tmp)
        from pipeline import matrix_rules as mr
        path = mr._text_cache_path(doc["sha256"])
        with open(path, "w", encoding="utf-8") as f:
            for p in (1, 2):
                f.write(json.dumps({"p": p, "t": ""}, ensure_ascii=False) + "\n")
        put_recognized(doc["sha256"], 2, "Бетон B30")
        rows = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        ok = check("старый кеш не отдаёт устаревший текст", rows[2][1] == "RECOGNIZED", rows[2][1])
        ok &= check("пересобранный кеш помечен версией",
                    all(json.loads(l).get("v") == mr.TEXT_CACHE_VERSION
                        for l in open(path, encoding="utf-8") if l.strip()))
        second = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        ok &= check("второй проход берётся из кеша и даёт то же самое", second == rows)
        return ok


STAMP = "Взам. инв. № Подпись и дата Инв. № подл. Изм."        # штамп скана: 10 слов, 45 знаков
DENSE = " ".join(["Бетон B25 для плиты перекрытия"] * 12)         # страница с текстом: 60 слов
SCAN_TEXTS = (STAMP, "Лист 5", "А-А", "Разрез 1-1, отметка верха плиты +3,300, бетон B25", DENSE)


def test_scan_with_stamp():
    """Скан со штампом в слое, тонкий слой, чертёж со слоем и плотная страница (#116)."""
    with tempfile.TemporaryDirectory() as tmp:
        doc, root = setup(tmp, SCAN_TEXTS)
        from pipeline import matrix_rules as mr, reading
        sha = doc["sha256"]
        put_recognized(sha, 1, STAMP + "\n4. Категория надежности: II", source="UNION", kind="SCAN_SPARSE")
        put_recognized(sha, 2, "Лист 5\nМаксимальная тепловая нагрузка 0,856 Гкал/ч", source="UNION",
                       kind="SCAN_SPARSE")
        layers = rows_layer(doc, root)
        put_recognized(sha, 3, "А-А\nПлита П1, бетон B30", source="UNION", kind="DRAWING", layer=layers[3])
        put_recognized(sha, 4, "Разрез 1-1\nбетон B30", source="UNION", kind="DRAWING", layer=layers[4])
        put_recognized(sha, 5, DENSE, source="TEXT_LAYER", kind="DENSE_TEXT")
        asked, get = [], reading.cache_get
        reading.cache_get = lambda digest, page, tag: (asked.append(page), get(digest, page, tag))[1]
        try:
            rows = {p: (t, src) for p, t, src in mr.page_texts_src(doc, root)}
        finally:
            reading.cache_get = get
        ok = check("скан со штампом: распознанное вместо штампа, штамп в нём остаётся",
                   rows[1][1] == "RECOGNIZED" and "Категория надежности" in rows[1][0] and "Взам. инв." in rows[1][0],
                   f"{rows[1][1]} «{rows[1][0][:60]}»")
        ok &= check("слой короче 30 знаков на скане — распознанное", rows[2][1] == "RECOGNIZED"
                    and "0,856" in rows[2][0], rows[2][1])
        ok &= check("чертёж с тонким слоем — пересказ модели: правилам больше нечего читать",
                    rows[3][1] == "RECOGNIZED" and "B30" in rows[3][0], rows[3][1])
        ok &= check("чертёж со слоем — слой, пересказ не удваивает значения",
                    rows[4][1] == "LAYER" and "B25" in rows[4][0] and "B30" not in rows[4][0], rows[4][1])
        ok &= check("страница с текстом — слой, кеш чтения не открывается",
                    rows[5][1] == "LAYER" and 5 not in asked, f"спрашивали страницы {sorted(set(asked))}")
        return ok


def test_revisions_read_layer():
    """Сравнение редакций читает у скана со штампом слой: распознанные сканы одного листа расходятся шумом."""
    with tempfile.TemporaryDirectory() as tmp:
        doc, root = setup(tmp, SCAN_TEXTS + ("",))
        from pipeline import matrix_rules as mr
        sha = doc["sha256"]
        put_recognized(sha, 1, STAMP + "\n4. Категория надежности: II", source="UNION", kind="SCAN_SPARSE")
        put_recognized(sha, 6, "Бетон B30 F150 W6")
        rules = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        revisions = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root, scans=False)}
        ok = check("правилам — распознанное", rules[1][1] == "RECOGNIZED", rules[1][1])
        ok &= check("сравнению редакций — штамп из слоя", revisions[1][1] == "LAYER"
                    and "Категория" not in revisions[1][0] and revisions[1][0].strip(), revisions[1][1])
        ok &= check("страница совсем без слоя — распознанная и там, как с #52",
                    revisions[6] == ("Бетон B30 F150 W6", "RECOGNIZED"), str(revisions[6]))
        ok &= check("обёртка page_texts передаёт режим", dict(mr.page_texts(doc, root, scans=False))[1] == revisions[1][0])
        return ok


def test_stamp_recognized_later():
    """Скан со штампом распознали после того, как правила его прочитали (#116)."""
    with tempfile.TemporaryDirectory() as tmp:
        doc, root = setup(tmp, SCAN_TEXTS)
        from pipeline import matrix_rules as mr
        first = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        ok = check("до распознавания — штамп из слоя", first[1][1] == "LAYER" and first[1][0].strip()
                   and "Категория" not in first[1][0], first[1][1])
        put_recognized(doc["sha256"], 1, STAMP + "\n4. Категория надежности: II", source="UNION", kind="SCAN_SPARSE")
        second = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        ok &= check("распознанное дошло на следующем чтении, без стирания кеша",
                    second[1][1] == "RECOGNIZED" and "Категория" in second[1][0], second[1][1])
        ok &= check("остальные страницы не тронуты", {p: v for p, v in second.items() if p != 1}
                    == {p: v for p, v in first.items() if p != 1})
        return ok


def test_version_2_cache_rebuilt():
    """Кеш версии 2 держит штамп вместо распознанного — он собирается заново (#116)."""
    with tempfile.TemporaryDirectory() as tmp:
        doc, root = setup(tmp, SCAN_TEXTS)
        from pipeline import matrix_rules as mr
        path = mr._text_cache_path(doc["sha256"])
        with open(path, "w", encoding="utf-8") as f:
            for p, t in enumerate(SCAN_TEXTS, 1):
                f.write(json.dumps({"v": 2, "p": p, "t": t, "s": "LAYER"}, ensure_ascii=False) + "\n")
        put_recognized(doc["sha256"], 1, STAMP + "\n4. Категория надежности: II", source="UNION", kind="SCAN_SPARSE")
        rows = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        ok = check("версия 2 не отдаёт штамп вместо распознанного", rows[1][1] == "RECOGNIZED", rows[1][1])
        ok &= check("пересобранный кеш — текущей версии", all(json.loads(l).get("v") == mr.TEXT_CACHE_VERSION
                                                          for l in open(path, encoding="utf-8") if l.strip()))
        return ok


def touch_later(sha, page_no, seconds=5):
    """Сдвинуть время записи файла кеша чтения вперёд: запись в ту же секунду иначе неотличима."""
    from pipeline import reading
    path = reading._cache_path(sha, page_no, "read")
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + seconds * 10 ** 9))


def test_reread_by_model():
    """Страницу перечитали моделью после того, как правила взяли чтение Tesseract (#89, #116)."""
    with tempfile.TemporaryDirectory() as tmp:
        doc, root = setup(tmp)
        from pipeline import matrix_rules as mr
        sha = doc["sha256"]
        put_recognized(sha, 2, "Бетон B3O F150", source="TESSERACT")
        first = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        ok = check("сначала — чтение Tesseract", first[2] == ("Бетон B3O F150", "RECOGNIZED"), str(first[2]))
        put_recognized(sha, 2, "Бетон B30 F150 W6", source="UNION")
        touch_later(sha, 2)
        second = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        ok &= check("кеш чтения переписан — правила видят новое чтение, кеш текста не стирали",
                    second[2] == ("Бетон B30 F150 W6", "RECOGNIZED"), str(second[2]))
        ok &= check("страница со слоем не тронута", second[1] == first[1])
        third = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        ok &= check("следующее чтение — то же самое", third == second)
        from pipeline import reading
        reading.cache_put(sha, 2, "read", {"version": 2, "kind": "TEXT", "text": "", "text_source": "TEXT_LAYER",
                                           "words": [], "images": 0, "width_pt": 595, "height_pt": 842})
        touch_later(sha, 2, 10)
        fourth = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        ok &= check("распознанного больше нет — остаётся слой страницы", fourth[2] == ("", "LAYER"), str(fourth[2]))
        return ok


def test_better_read_reaches_rules():
    """Перечитали лучше — текст меняется; перечитали хуже — остаётся прежний (#85 поверх #116).

    Отметка кеша чтения говорит, что страницу перечитали, ранг источника — что не хуже: прогон
    сервиса в режиме `tesseract` перезаписывает одним Tesseract страницу, которую прочитала модель.
    """
    with tempfile.TemporaryDirectory() as tmp:
        doc, root = setup(tmp)
        from pipeline import matrix_rules as mr
        sha = doc["sha256"]
        put_recognized(sha, 2, "Бтн ВЗО", source="TESSERACT")
        first = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        ok = check("сначала в кеше распознанное Tesseract", first[2][0] == "Бтн ВЗО", str(first[2]))
        put_recognized(sha, 2, "Бетон В30 F150 W6", source="MODEL")
        touch_later(sha, 2)
        second = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        ok &= check("чтение моделью дошло до правил без стирания кеша",
                    second[2][0] == "Бетон В30 F150 W6", str(second[2]))
        put_recognized(sha, 2, "снова Tesseract", source="TESSERACT")
        touch_later(sha, 2, seconds=10)
        third = {p: (t, s) for p, t, s in mr.page_texts_src(doc, root)}
        ok &= check("чтение хуже прежнего текст не заменяет",
                    third[2][0] == "Бетон В30 F150 W6", str(third[2]))
        rows = [json.loads(l) for l in open(mr._text_cache_path(sha), encoding="utf-8") if l.strip()]
        row = next(r for r in rows if r["p"] == 2)
        ok &= check("у распознанной страницы записан источник чтения модели", row.get("rs") == "MODEL", str(row.get("rs")))
        ok &= check("отметка запомнена — кеш чтения не открывается на каждом чтении",
                    row.get("m") == mr._read_stamp(sha, 2), str(row.get("m")))
        return ok


def main():
    ok = True
    for title, fn in (("Слой первым", test_layer_first),
                      ("Распознанное там, где слоя нет", test_recognized_where_no_layer),
                      ("Читать нечего", test_nothing_to_read),
                      ("Распознали позже", test_recognized_after_cache),
                      ("Кеш прежнего образца", test_stale_cache_rebuilt),
                      ("Скан со штампом", test_scan_with_stamp),
                      ("Сравнению редакций — слой", test_revisions_read_layer),
                      ("Штамп распознали позже", test_stamp_recognized_later),
                      ("Кеш версии 2", test_version_2_cache_rebuilt),
                      ("Страницу перечитали моделью", test_reread_by_model),
                      ("Перечитали хуже прежнего", test_better_read_reaches_rules)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
