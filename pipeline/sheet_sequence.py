"""Проверка номеров листов по соседним страницам. Задача #16.

Внутри комплекта номер листа растёт на единицу вместе с номером страницы, поэтому
разность «страница минус лист» у соседних листов одна и та же. Это даёт проверку,
не зависящую от того, как номер прочитан.

- Подтверждён: у ближайшего прочитанного соседа до или после та же разность.
  Две независимые ошибки распознавания, давшие одну разность, маловероятны.
- Противоречие: ближайшие соседи с обеих сторон согласны между собой, а эта страница
  с ними нет. Номер почти наверняка прочитан неверно. Он не удаляется, а переносится
  в `sheet_rejected`, чтобы связка «шифр плюс лист» им не пользовалась.
- Не подтверждён: соседей нет или они сами расходятся. Так бывает на стыке комплектов.

Слабое прочтение (`sheet_candidate`: при распознавании графы ответил один язык из двух)
принимается, только если ближайший сосед с обычным прочтением даёт ту же разность.
Иначе оно отбрасывается: одиночные ответы верны в 12 случаях из 13, и без
подтверждения эта ошибка ушла бы в связку.

Шифр распознавание портит, причём одинаково на соседних листах: на томе ИОС5.5.5
«АНО/150321/1-П-ИОС5.5.5» читается как «АНО/150371/1-П-ИОСЪ.5.5» на большинстве
страниц. Внутри ряда листов с одной разностью шифр один, и он выравнивается
голосованием среди прочитанных в ряду написаний. Голос шифра, который встречается
в текстовом слое объекта, весит втрое, иначе систематическая ошибка распознавания
выигрывает у верного написания. Заменяется только шифр из распознавания и только
отличающийся от победителя не больше чем на два символа; прочитанное значение
остаётся в `document_code_read`. Шифр из текстового слоя не заменяется никогда.
Пустой шифр в ряду получает шифр ряда с источником SEQUENCE в `code_source`.

Привязывать шифр из распознавания к ближайшему шифру слоя нельзя: шифры одного
проекта сами отличаются на один-два символа. Такая привязка превращала «ИОС5.2.1.ГЧ»
в «ИОС5.2.1.ТЧ», графическую часть в текстовую, и «ИОС5.1.1» в «ИОС5.1».

Пропуск между двумя прочитанными листами с одной разностью заполняется: если
у страниц 60 и 64 листы 12 и 16, страницы между ними — листы 13, 14 и 15. Вставленная
страница без надписи сдвинула бы разность, поэтому одинаковая разность на концах
означает, что внутри только листы того же комплекта. Такие номера помечаются
источником SEQUENCE и в долю прочитанных не входят.
"""
import collections

from pipeline import code_registry

from pipeline.titleblock_ocr import _distance

WINDOW = 5      # на каком расстоянии в страницах сосед ещё считается соседом
MAX_GAP = 10    # пропуск длиннее не заполняется


def _neighbours(readings, i):
    page = readings[i][0]
    prev = readings[i - 1] if i > 0 and page - readings[i - 1][0] <= WINDOW else None
    nxt = readings[i + 1] if i + 1 < len(readings) and readings[i + 1][0] - page <= WINDOW else None
    return prev, nxt


def check(rows, registry_codes=None):
    """Проставляет sheet_check и заполняет пропуски. Меняет строки на месте.

    Строки — словари с file_id, pdf_page_number, document_sheet_number, document_code
    и sheet_source. `registry_codes` — шифр комплекта из реестра по file_id: им
    выправляются знаки, спутанные распознаванием (#52). Возвращает счётчик исходов.
    """
    stats = collections.Counter()
    vocab = {r["document_code"] for r in rows
             if r.get("code_source") == "TEXT_LAYER" and r.get("document_code")}
    by_file = collections.defaultdict(list)
    for r in rows:
        by_file[r["file_id"]].append(r)
    for file_rows in by_file.values():
        file_rows.sort(key=lambda r: r["pdf_page_number"])
        readings = [(r["pdf_page_number"], r["pdf_page_number"] - r["document_sheet_number"], r)
                    for r in file_rows if r["document_sheet_number"] is not None]
        for i, (page, offset, r) in enumerate(readings):
            prev, nxt = _neighbours(readings, i)
            if (prev and prev[1] == offset) or (nxt and nxt[1] == offset):
                r["sheet_check"] = "CONFIRMED"
            elif prev and nxt and prev[1] == nxt[1]:
                r["sheet_check"] = "CONFLICT"
            else:
                r["sheet_check"] = "UNCONFIRMED"
            stats[r["sheet_check"]] += 1
        for page, offset, r in readings:
            if r["sheet_check"] == "CONFLICT":
                r["sheet_rejected"] = {"sheet": r["document_sheet_number"], "source": r["sheet_source"]}
                r["document_sheet_number"] = None
                r["sheet_source"] = None
        _accept_weak(file_rows, stats)
        _align_to_registry(file_rows, (registry_codes or {}).get(file_rows[0]["file_id"]), stats)
        _harmonize_codes(file_rows, vocab, stats)
        _fill_gaps(file_rows, stats)
    return stats


def _accept_weak(file_rows, stats):
    strong = [(r["pdf_page_number"], r["pdf_page_number"] - r["document_sheet_number"])
              for r in file_rows if r["document_sheet_number"] is not None]
    for r in file_rows:
        cand = r.get("sheet_candidate")
        if cand is None or r["document_sheet_number"] is not None:
            continue
        page, offset = r["pdf_page_number"], r["pdf_page_number"] - cand
        before = [o for p, o in strong if 0 < page - p <= WINDOW]
        after = [o for p, o in strong if 0 < p - page <= WINDOW]
        nearest = ([before[-1]] if before else []) + ([after[0]] if after else [])
        if offset in nearest:
            r["document_sheet_number"] = cand
            r["sheet_source"] = "OCR_CELL_WEAK"
            r["sheet_check"] = "CONFIRMED"
            stats["WEAK_CONFIRMED"] += 1
        else:
            stats["WEAK_REJECTED"] += 1


def similar_codes(a, b):
    """Шифры одного комплекта с поправкой на ошибки распознавания."""
    if not a or not b:
        return True
    return a == b or _distance(a, b) <= 2


def _runs(file_rows):
    """Ряды подряд идущих прочитанных листов с одной разностью «страница минус лист»."""
    runs, cur = [], []
    for r in file_rows:
        if r["document_sheet_number"] is None:
            continue
        offset = r["pdf_page_number"] - r["document_sheet_number"]
        if cur and (offset != cur[-1]["pdf_page_number"] - cur[-1]["document_sheet_number"]
                    or r["pdf_page_number"] - cur[-1]["pdf_page_number"] > WINDOW):
            runs.append(cur)
            cur = []
        cur.append(r)
    if cur:
        runs.append(cur)
    return [run for run in runs if len(run) > 1]


def _align_to_registry(file_rows, registry_code, stats):
    """Выправить знаки, спутанные распознаванием, по шифру комплекта из реестра (#52).

    Ошибка распознавания одинакова на всех листах комплекта, и голосование по ряду её
    не ловит: «КЖ1.1» читается как «КЖ.1» на 35 листах из 43. Шифр комплекта известен
    из имени файла — это независимый источник. Подменять им прочтение нельзя (на листе
    шифр длиннее и с другими разделителями), поэтому правятся только спутанные знаки,
    и только пока их не больше двух: см. pipeline/code_registry.py.
    """
    if not registry_code:
        return
    for r in file_rows:
        code = r.get("document_code")
        if not code or r.get("code_source") == "TEXT_LAYER":
            continue          # слою верим больше, чем имени файла
        fixed, changed = code_registry.align(code, registry_code)
        if changed:
            r.setdefault("document_code_read", code)
            r["document_code"] = fixed
            r["code_fixed_by_registry"] = [list(pair) for pair in changed]
            stats["CODE_FIXED_BY_REGISTRY"] += 1


def _harmonize_codes(file_rows, vocab, stats):
    for run in _runs(file_rows):
        votes = collections.Counter()
        for r in run:
            code = r.get("document_code")
            if code:
                votes[code] += 3 if code in vocab else 1
        if not votes:
            continue
        best = votes.most_common(1)[0][0]
        for r in run:
            code = r.get("document_code")
            # шифр из текстового слоя не трогаем: соседние листы тома законно
            # подписаны по-разному («ИОС5.7.3.1ПЗ» и «ИОС5.7.3.1»), и замена его портит
            if code == best or r.get("code_source") == "TEXT_LAYER":
                continue
            if code is None:
                r["document_code"] = best
                r["code_source"] = "SEQUENCE"
                stats["CODE_FROM_RUN"] += 1
            elif _distance(code, best) <= 2:
                r.setdefault("document_code_read", code)
                r["document_code"] = best
                stats["CODE_HARMONIZED"] += 1


def _fill_gaps(file_rows, stats):
    """Пропуски между двумя подтверждёнными листами с одной разностью."""
    anchors = [r for r in file_rows
               if r["document_sheet_number"] is not None and r.get("sheet_check") == "CONFIRMED"]
    by_page = {r["pdf_page_number"]: r for r in file_rows}
    for a, b in zip(anchors, anchors[1:]):
        pa, pb = a["pdf_page_number"], b["pdf_page_number"]
        offset = pa - a["document_sheet_number"]
        if pb - pa < 2 or pb - pa > MAX_GAP or pb - b["document_sheet_number"] != offset:
            continue
        if not similar_codes(a.get("document_code"), b.get("document_code")):
            continue
        for page in range(pa + 1, pb):
            r = by_page.get(page)
            if r is None or r["document_sheet_number"] is not None:
                continue
            r["document_sheet_number"] = page - offset
            r["sheet_source"] = "SEQUENCE"
            r["sheet_check"] = "INFERRED"
            if not r.get("document_code") and (a.get("document_code") or b.get("document_code")):
                r["document_code"] = a.get("document_code") or b.get("document_code")
                r["code_source"] = "SEQUENCE"
            stats["INFERRED"] += 1
