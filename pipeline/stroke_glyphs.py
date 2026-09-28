"""Чтение коротких обозначений по форме глифов-штрихов. Задача #48.

## В чём дело

На листах без текстового слоя чертёжный шрифт выведен линиями: каждая буква и цифра —
несколько отрезков. Tesseract такой шрифт читает нетвёрдо: в обозначениях систем
«ВД3», «ПД17.2» теряет цифру после «Д», «8» читает как «В», «У3» как «уз». Цифры конвейер
не исправляет, поэтому такие ячейки уходили в «обозначение не разобрано», а сравнение
по помещениям — в «сравнение невозможно».

## Как читается

Глифы одного шрифта в одном документе начертаны одинаково: их можно узнавать по форме,
а не по словарю Tesseract. Образцы форм берутся из того же листа:

1. Штрихи ячейки собираются в глифы по прямоугольникам векторных путей: перекрывающиеся
   по горизонтали отрезки — один глиф, мелкий элемент под глифом — его ножка («Д»), мелкий
   элемент у основания строки — точка или запятая.
2. Ячейки, которые Tesseract прочёл уверенно (два прочтения совпали или единственное
   прочтение по длине совпадает с числом глифов, а остальные — его начало), дают глифам
   метки. Метки кладутся на глифы по порядку, знак за знаком.
3. Для каждого знака берётся образцовый глиф — медоид его примеров; класс с одним примером
   или с примерами, не похожими друг на друга, не используется.
4. Каждый глиф каждой ячейки сравнивается с образцами: нормированная корреляция чернил
   с допуском сдвига на два пикселя при высоте строки 48 пикселей. Глиф принимается, если
   похож на образец не меньше `THRESHOLD`; ячейка читается, только если приняты все её глифы.

Это не исправление цифр: глиф либо совпал с образцом того же листа, либо ячейка остаётся
за Tesseract. Формы не зашиты в код — они выводятся из самого документа, поэтому способ
не привязан к одному шрифту и к одному объекту. Что он не читает: буквы, для которых на листе
нет ни одной уверенно прочитанной ячейки, и глифы, налезающие друг на друга.

Замер на четырёх листах таблиц систем Тюменской-5 — `docs/room-compare-report.md`, раздел 1.
"""
import collections
import re

H_PX = 48                  # высота строки в растре глифа
SHIFT_PX = 2               # допуск сдвига при сравнении
THRESHOLD = 0.85           # сходство, с которого глиф принимается
MIN_EXAMPLES = 2           # примеров у знака, чтобы стать образцом
MEDOID_SAMPLE = 12         # среди скольких примеров ищется образцовый глиф
MARGIN = 0.03              # ближайший образец должен опережать следующий не меньше чем на столько
CONDENSED = 0.7            # сжатый по ширине глиф: не уже стольких ширин образца
CONSISTENT = 0.8           # примеры знака должны быть похожи на медоид не меньше
SMALL = 0.5                # элемент ниже такой доли высоты строки — не глиф, а ножка или знак
TALL = 1.3                 # элемент выше стольких высот строки — скобка или облако, не глиф («Д» с ножками ниже)
NARROW = 0.3               # высокий элемент не шире стольких высот строки — скобка, разделитель
OVERSIZE = 1.6             # элемент шире стольких высот строки — не глиф вовсе
CAP_QUANTILE = 0.9         # высота строки — верхний квантиль высот элементов: прописные и цифры
DOT = 0.2                  # точка — ниже такой доли высоты строки
GAP = 0.9                  # зазор между обозначениями в строке, в высотах строки
WORD_GAP = 0.5             # зазор между словами текста: цифры в числе стоят теснее
JOIN = 0.05                # зазор между штрихами одного глифа, в высотах строки: у соседних глифов он больше
LETTER = re.compile(r"[А-ЯA-Z]")
DIGIT_TWINS = {"О": "0", "O": "0", "З": "3", "Ч": "4"}   # в цифровой части обозначения буква — двойник цифры


def available():
    """Есть ли numpy: без него сходство растров не посчитать, и обозначения остаются за Tesseract."""
    try:
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


# ---------- глифы ----------

def _union(a, b):
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def stroke_rects(page):
    """Прямоугольники штрихов страницы в видимых координатах: [(x0, y0, x1, y1)].

    Считается один раз на страницу: путей на чертёжном листе десятки тысяч, а обращение
    к повороту страницы в PyMuPDF стоит вызова в MuPDF.
    """
    rotation = page.rotation
    matrix = page.rotation_matrix if rotation else None
    out = []
    for d in page.get_drawings():
        if not d.get("width"):
            continue                      # заливка без обводки — не штрих
        r = d["rect"]
        if rotation:
            r = r * matrix
            r.normalize()
        if r.width <= 0.05 and r.height <= 0.05:
            continue
        out.append((r.x0, r.y0, r.x1, r.y1))
    return out


def cell_boxes(strokes, rect, line_h=None):
    """Прямоугольники штрихов внутри ячейки.

    Без `line_h` берутся штрихи, лежащие в ячейке целиком. С `line_h` — и те, что вылезают
    за границу, но центром внутри и размером с глиф: текст, не поместившийся в ячейку.
    """
    x0, y0, x1, y1 = rect
    out = []
    for rx0, ry0, rx1, ry1 in strokes:
        if rx1 < x0 - 4 or rx0 > x1 + 4 or ry1 < y0 - 4 or ry0 > y1 + 4:
            continue
        inside = rx0 >= x0 - 0.5 and rx1 <= x1 + 0.5 and ry0 >= y0 - 0.5 and ry1 <= y1 + 0.5
        if inside:
            out.append([rx0, ry0, rx1, ry1])
        elif line_h and ry1 - ry0 <= 1.6 * line_h and rx1 - rx0 <= 4 * line_h:
            cx, cy = (rx0 + rx1) / 2, (ry0 + ry1) / 2
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                out.append([rx0, ry0, rx1, ry1])
    return out


def glyph_rows(boxes):
    """Строки глифов ячейки: ([[{box, kind}]], высота строки). kind — glyph, «.», «,» или «|» (скобка)."""
    if not boxes:
        return [], 0.0
    # высота строки — высота прописных и цифр: в тексте со строчными буквами это верхние
    # значения, а не медиана; скобки выше строки отсеиваются ниже как разделители
    heights = sorted(b[3] - b[1] for b in boxes)
    line_h = heights[int(CAP_QUANTILE * (len(heights) - 1))]
    tall = [b for b in boxes if b[3] - b[1] > TALL * line_h]
    big = [b for b in boxes if SMALL * line_h <= b[3] - b[1] <= TALL * line_h]
    # облако изменений, выноска, обрывок линии сетки: заметно шире буквы — не глиф
    big = [b for b in big if b[2] - b[0] <= OVERSIZE * line_h]
    if not big:
        return [], 0.0
    small = [b for b in boxes if b[3] - b[1] < SMALL * line_h]
    big.sort(key=lambda b: ((b[1] + b[3]) / 2, b[0]))
    lines = []
    for b in big:
        mid = (b[1] + b[3]) / 2
        if lines and abs(mid - lines[-1][0]) <= 0.5 * line_h:
            lines[-1][1].append(b)
        else:
            lines.append([mid, [b]])
    rows = []
    for _, bs in lines:
        bs.sort(key=lambda b: b[0])
        merged = []
        for b in bs:
            if merged and b[0] <= merged[-1][2] + JOIN * line_h:
                merged[-1] = _union(merged[-1], b)
            else:
                merged.append(list(b))
        rows.append([{"box": m, "kind": "glyph"} for m in merged])
    for s in small:
        # мелкий штрих внутри глифа по горизонтали и по высоте — от его верха до ножек под строкой —
        # часть глифа: перекладина, ножка «Д», хвост. Точка и запятая стоят между глифами
        owner = None
        for row in rows:
            for g in row:
                b = g["box"]
                if (s[0] < b[2] + 0.1 * line_h and s[2] > b[0] - 0.1 * line_h
                        and b[1] - 0.1 * line_h <= s[1] <= b[3] + 0.3 * line_h):
                    owner = g
                    break
            if owner:
                break
        if owner:
            owner["box"] = _union(owner["box"], s)
            continue
        kind = "." if s[3] - s[1] < DOT * line_h else ","
        row = min(rows, key=lambda r: abs((s[1] + s[3]) / 2
                                          - sum((g["box"][1] + g["box"][3]) / 2 for g in r) / len(r)))
        row.append({"box": s, "kind": kind})
    for t in tall:
        # скобка, дробная черта: выше строки и узкая — разделитель; широкое — облако или выноска, не глиф
        if t[2] - t[0] <= NARROW * line_h:
            row = min(rows, key=lambda r: abs((t[1] + t[3]) / 2
                                              - sum((g["box"][1] + g["box"][3]) / 2 for g in r) / len(r)))
            row.append({"box": t, "kind": "|"})
    for row in rows:
        row.sort(key=lambda g: g["box"][0])
    return rows, line_h


def tokens(rows, line_h, gap=GAP):
    """Глифы строки — по группам: делят запятая, скобка и зазор шире `gap` высот строки.
    Для обозначений зазор — GAP (между «В2.4, В2.5» есть и запятая), для слов текста — WORD_GAP."""
    out = []
    for row in rows:
        cur, prev = [], None
        for g in row:
            if g["kind"] in (",", "|"):
                if cur:
                    out.append(cur)
                cur, prev = [], None
                continue
            if prev is not None and g["box"][0] - prev["box"][2] > gap * line_h:
                if cur:
                    out.append(cur)
                cur = []
            cur.append(g)
            prev = g
        if cur:
            out.append(cur)
    return out


# ---------- растр и сходство ----------

def raster(display_list, box, line_h):
    """Чернила глифа: массив 0..1 высотой H_PX на высоту строки. display_list — page.get_displaylist(),
    один на страницу: растрирование по нему не перестраивает список отображения на каждый глиф."""
    import numpy as np
    import pymupdf
    z = H_PX / line_h
    # clip задаётся в видимых координатах: поворот листа PyMuPDF учитывает сам
    clip = pymupdf.Rect(box[0] - 0.15, box[1] - 0.15, box[2] + 0.15, box[3] + 0.15)
    pix = display_list.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=clip, colorspace=pymupdf.csGRAY, alpha=False)
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).astype(np.float32)
    return (255 - a) / 255.0


def similarity(a, b):
    """Нормированная корреляция чернил двух растров с допуском сдвига на SHIFT_PX."""
    import numpy as np
    h = max(a.shape[0], b.shape[0]) + 2 * SHIFT_PX
    w = max(a.shape[1], b.shape[1]) + 2 * SHIFT_PX
    A = np.zeros((h, w), np.float32)
    A[SHIFT_PX:SHIFT_PX + a.shape[0], SHIFT_PX:SHIFT_PX + a.shape[1]] = a
    na = float(np.sqrt((A * A).sum())) or 1.0
    nb = float(np.sqrt((b * b).sum())) or 1.0
    best = 0.0
    for dy in range(2 * SHIFT_PX + 1):
        for dx in range(2 * SHIFT_PX + 1):
            B = np.zeros((h, w), np.float32)
            B[dy:dy + b.shape[0], dx:dx + b.shape[1]] = b
            best = max(best, float((A * B).sum()) / (na * nb))
    return best


# ---------- самообучение и чтение ----------

def _digit_part(text):
    """Нормализация грамматики обозначения: после первой цифры буквы-двойники — цифры."""
    out, digits = [], False
    for ch in text:
        if ch.isdigit():
            digits = True
        elif digits and ch in DIGIT_TWINS:
            ch = DIGIT_TWINS[ch]
        out.append(ch)
    return "".join(out)


def _confident(readings, glyph_tokens, normalize):
    """Метки ячейки по прочтениям Tesseract: список обозначений или None.

    Принимается прочтение, которое дали хотя бы два прочтения из трёх, либо единственное,
    у которого число знаков совпало с числом глифов, а остальные прочтения — его начало.
    Число знаков и положение точек должны совпасть с глифами, иначе меток нет.
    """
    lists = [normalize(t) for t in readings or ()]
    lists = [l for l in lists if l]
    if not lists:
        return None
    counts = collections.Counter(tuple(l) for l in lists)
    best, votes = counts.most_common(1)[0]
    if votes < 2:
        fits = [l for l in lists if _shape_fits(l, glyph_tokens)]
        distinct = {tuple(l) for l in fits}
        if len(distinct) != 1:
            return None
        best = fits[0]
        joined = "".join(best)
        if not all("".join(l) == joined or joined.startswith("".join(l)) for l in lists):
            return None
    return list(best) if _shape_fits(best, glyph_tokens) else None


def _shape_fits(marks, glyph_tokens):
    if len(marks) != len(glyph_tokens):
        return False
    for text, tok in zip(marks, glyph_tokens):
        if len(text) != len(tok):
            return False
        if any((ch == ".") != (g["kind"] == ".") for ch, g in zip(text, tok)):
            return False
    return True


def templates_from(cells, normalize):
    """Образцы знаков из уверенно прочитанных ячеек: {знак: растр}. cells — [(строки глифов, прочтения)]."""
    examples = collections.defaultdict(list)
    for rows, line_h, readings in cells:
        toks = tokens(rows, line_h)
        marks = _confident(readings, toks, normalize)
        if not marks:
            continue
        for text, tok in zip(marks, toks):
            for ch, g in zip(_digit_part(text), tok):
                if g["kind"] == "glyph" and g.get("raster") is not None:
                    examples[ch].append(g["raster"])
    out = {}
    for ch, rasters in examples.items():
        if len(rasters) < MIN_EXAMPLES:
            continue
        # медоид ищется среди выборки примеров: попарное сравнение сотни глифов стоило бы секунд
        step = max(1, len(rasters) // MEDOID_SAMPLE)
        sample = rasters[::step][:MEDOID_SAMPLE]
        mean = [sum(similarity(a, b) for b in sample) / len(sample) for a in sample]
        medoid = sample[max(range(len(sample)), key=lambda i: mean[i])]
        alike = sum(1 for r in rasters if similarity(r, medoid) >= CONSISTENT)
        if alike >= MIN_EXAMPLES:
            out[ch] = medoid
    return out


def _stretched(a, width):
    """Растр, растянутый по ширине до width пикселей: сжатый по ширине текст против образца."""
    import numpy as np
    if a.shape[1] == width or a.shape[1] == 0:
        return a
    xs = np.linspace(0, a.shape[1] - 1, width)
    left = np.floor(xs).astype(int)
    right = np.minimum(left + 1, a.shape[1] - 1)
    frac = (xs - left).astype(np.float32)
    return a[:, left] * (1 - frac) + a[:, right] * frac


def _scores(raster_, templates):
    """Сходство глифа с каждым образцом, по убыванию. Текст, не поместившийся в ячейку, чертёж
    выводит сжатым по ширине, поэтому глиф уже образца сравнивается и растянутым до его ширины;
    глиф вдвое уже («1» против «2») не растягивается — это другой знак, а не сжатие."""
    out = []
    for ch, t in templates.items():
        score = similarity(raster_, t)
        if CONDENSED <= raster_.shape[1] / t.shape[1] < 1.0:
            score = max(score, similarity(_stretched(raster_, t.shape[1]), t))
        out.append((score, ch))
    return sorted(out, reverse=True)


def classify(raster_, templates):
    """(знак, сходство) — ближайший образец; знак None, если сходство ниже порога или второй
    образец почти так же похож: «8» и «В» одного шрифта близки, и без образца одного из них
    глиф другого не должен приниматься за него."""
    scored = _scores(raster_, templates)
    if not scored:
        return None, 0.0
    best, ch = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best < THRESHOLD or best - second < MARGIN:
        return None, best
    return ch, best


def read_cell(rows, line_h, templates):
    """Текст ячейки по образцам: обозначения через запятую, или None, если хоть один глиф не узнан."""
    out = []
    for tok in tokens(rows, line_h):
        text = ""
        for g in tok:
            if g["kind"] == ".":
                text += "."
            elif g["kind"] == "glyph":
                ch, _ = classify(g["raster"], templates)
                if ch is None:
                    return None
                text += ch
        if text:
            out.append(_digit_part(text))
    return ", ".join(out) if out else None


class Sheet:
    """Штрихи и список отображения одной страницы плюс образцы знаков, выведенные из неё."""

    def __init__(self, page):
        self.page = page
        self.strokes = stroke_rects(page)
        self.display_list = page.get_displaylist()
        self.templates = {}
        self.line_h = None      # высота строки, при которой собраны образцы: масштаб растров листа

    def glyphs(self, rect):
        """Строки глифов ячейки с растрами: (строки, высота строки).

        Растр каждого глифа строится в масштабе высоты строки своей ячейки: колонка помещений
        набрана мельче колонки обозначений, но тем же шрифтом, и после масштабирования цифры
        совпадают с образцами.
        """
        rows, line_h = glyph_rows(cell_boxes(self.strokes, rect))
        if rows:
            rows, line_h = glyph_rows(cell_boxes(self.strokes, rect, line_h))
        for row in rows:
            for g in row:
                g["raster"] = raster(self.display_list, g["box"], line_h) if g["kind"] == "glyph" else None
        return rows, line_h

    def read_marks(self, rects, readings, normalize):
        """Прочтение ячеек с обозначениями по форме глифов: ([текст или None] по числу rects, сведения).

        rects — прямоугольники ячеек в видимых координатах; readings — прочтения Tesseract тех же
        ячеек (список списков) для самообучения; normalize — разбор текста ячейки в обозначения.
        Образцы, собранные здесь, остаются в `templates` и годятся для чисел в других колонках листа.
        """
        cells = [self.glyphs(rect) for rect in rects]
        heights = sorted(line_h for rows, line_h in cells if rows)
        self.line_h = heights[len(heights) // 2] if heights else None
        self.templates = templates_from(
            [(rows, line_h, reads) for (rows, line_h), reads in zip(cells, readings) if rows], normalize)
        info = {"cells": sum(1 for rows, _ in cells if rows), "templates": "".join(sorted(self.templates)), "read": 0}
        out = []
        for rows, line_h in cells:
            text = read_cell(rows, line_h, self.templates) if rows and self.templates else None
            if text:
                info["read"] += 1
            out.append(text)
        return out, info

    def numbers(self, rect):
        """Числа ячейки по форме глифов: [«247», «138», …] в порядке чтения.

        Число — группа глифов, каждый из которых узнан как цифра (точка внутри допускается);
        группа с буквой или с неузнанным глифом числом не считается. Что это за число —
        помещение, этаж, число мест — решает текст Tesseract, здесь только его цифры.
        """
        if not self.templates:
            return []
        rows, line_h = self.glyphs(rect)
        out = []
        for tok in tokens(rows, line_h, gap=WORD_GAP):
            chars = []
            for g in tok:
                if g["kind"] == ".":
                    chars.append(".")
                elif g["kind"] == "glyph":
                    ch, _ = classify(g["raster"], self.templates)
                    chars.append(ch if ch and ch.isdigit() else None)
                else:
                    chars.append(None)
            number = _number_of(chars)
            if number:
                out.append(number)
        return out


def _number_of(chars):
    """Число из знаков группы: цифры и точки — само число («331.1»); слово с приклеенным числом
    («пом.160») — цифры после последней точки; иначе None."""
    if not chars or all(c is None for c in chars):
        return None
    if all(c is not None for c in chars) and any(c.isdigit() for c in chars):
        return "".join(chars).strip(".") or None
    if "." in chars:
        tail = chars[len(chars) - chars[::-1].index("."):]
        if tail and all(c is not None and c.isdigit() for c in tail):
            return "".join(tail)
    return None


def read_marks(page, rects, readings, normalize):
    """Прочтение ячеек с обозначениями по форме глифов без сохранения образцов: см. Sheet.read_marks."""
    return Sheet(page).read_marks(rects, readings, normalize)


def reconcile_numbers(accepted, doubtful, numbers):
    """Номера из текста Tesseract против чисел, прочитанных по глифам той же ячейки.

    Сомнительный номер (дало одно прочтение из трёх), который есть среди чисел ячейки, принимается:
    форма глифов — второе независимое прочтение. Номер, которого среди чисел ячейки нет, заменяется
    единственным числом, с которым он расходится в одной цифре или которого он начало либо конец:
    это не исправление цифры, а чтение той же группы глифов другим способом. Если таких чисел
    несколько или ни одного, номер остаётся как был. Числа ячейки, не названные текстом, номерами
    не становятся: без слова «пом.» неизвестно, помещение это, этаж или число мест.
    """
    if not numbers:
        return list(accepted), list(doubtful)
    known = set(numbers)

    def match(value):
        if len(value) < 2:
            return None               # «1» из «1 эт.» тоже число ячейки: одной цифре подтверждения нет
        if value in known:
            return value
        found = {n for n in known if _same_group(value, n)}
        return found.pop() if len(found) == 1 else None

    out, still = [], []
    for value in list(accepted) + list(doubtful):
        got = match(value)
        target = out if got or value in accepted else still
        got = got or value
        if got not in target:
            target.append(got)
    return out, [v for v in still if v not in out]


def _same_group(value, number):
    """Похоже ли прочтение на число: та же длина с одной иной цифрой, либо начало или конец числа."""
    if not value or not number or value == number:
        return False
    if len(value) == len(number):
        return sum(1 for a, b in zip(value, number) if a != b) == 1
    if len(value) >= 2 and len(number) == len(value) + 1:
        return number.startswith(value) or number.endswith(value)
    return False
