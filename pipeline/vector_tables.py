"""Таблицы на чертёжных листах: сетка из линий PDF, текст из слоя или распознаванием ячеек. Задачи #21, #37.

## В чём дело

Значения, по которым проектная стадия сверяется с рабочей, часто стоят не в пояснительной
записке, а в таблице на чертёжном листе: «Характеристика отопительно-вентиляционных систем»,
«Таблица воздухообменов», экспликация. Текст такой таблицы бывает двух видов:

- обычный текстовый слой (Октябрьская, Алтуфьевское, Новослободская, Речников);
- кривые: шрифт чертежа выведен линиями, слоя нет вовсе (оба тома ОВ Тюменской-5).

Сплошное распознавание листа таблицу второго вида не читает: линии сетки рвут строки,
колонки слипаются, обозначения систем пропадают. Замер на листе 2 тома РД ОВ1: из 70 строк
обозначение системы уцелело меньше чем в половине.

## Решение

Сетка таблицы в обоих случаях нарисована векторами, и PyMuPDF отдаёт её линиями. Поэтому:

1. Линии страницы переводятся в видимую систему координат (поворот листа учтён матрицей)
   и сливаются по общей координате: сетку чертят отрезками от ячейки к ячейке.
2. Линиями сетки считаются те, чья суммарная длина не меньше `COVER` от длины обычной длинной
   линии листа: отрезки основной надписи и выносок отпадают сами, а рамка листа меру не сбивает.
3. Границы ячеек берутся по колонке: горизонтальная линия делит колонку, только если
   проходит через неё. Так объединённые ячейки шапки остаются одной ячейкой.
4. Текст ячейки — слова текстового слоя, попавшие в неё центром. Если слоя в ячейке нет,
   а сама ячейка не пуста, она вырезается без линий сетки и распознаётся Tesseract.
   Вырезы отдаются одним вызовом списком файлов: 200 ячеек читаются за 2–3 секунды.

Замер на тех же двух листах: число систем и колонка «обслуживаемое помещение» читаются
без ошибок в номерах помещений; обозначения вытяжных систем — с двойниками «В» → «8», «B»,
которые сворачивает разбор; обозначения приточных («П1») Tesseract читает плохо, и сравнение
на них не опирается.

Зависимости те же, что у воркера: PyMuPDF и Tesseract из командной строки.
"""
import os
import shutil
import subprocess
import tempfile

MIN_H_LEN_PT = 40.0        # короче — не линия сетки, а штрих или буква
MIN_V_LEN_PT = 10.0
AXIS_TOL_PT = 0.7          # отклонение отрезка от горизонтали или вертикали
LINE_TOL_PT = 1.2          # отрезки одной линии сетки расходятся по координате не больше
GAP_TOL_PT = 1.5           # разрыв между отрезками одной линии
COVER = 0.6                # доля длины линии сетки, с которой линия в неё входит
LENGTH_SPREAD = 0.85       # линии одной таблицы отличаются по длине не больше чем на столько
COLUMN_COVER = 0.8         # доля ширины колонки, которую должна пройти граница ячейки
CELL_PAD_PT = 1.2          # отступ внутрь ячейки: линия сетки в вырез не попадает
OCR_DPI = 400
OCR_LANG = "rus+eng"
OCR_PSM = "6"              # ячейка — блок текста в одну-три строки
# Прочтения для голосования: (dpi, psm, язык, белый список). Одно прочтение цифрам не указ:
# «(пом. 108, 201)» режим блока читает как «001» на 400 dpi, «01» на 300, «50» на 500 и верно
# только на 600; режим разреженного текста читает «201» на любом разрешении, но путает порядок
# слов. Ошибаются они по-разному, поэтому значение принимается, когда его дали хотя бы два
# прочтения из трёх.
OCR_VOTES = ((400, "6", OCR_LANG, None), (400, "11", OCR_LANG, None), (600, "6", OCR_LANG, None))
# Обозначения систем: только заглавная кириллица, цифры и знаки. Без белого списка «ВД1» читается
# как «ВД!», «ПД19» — как «19», «В2.4» — как латинское «B2.4».
MARK_CHARS = "АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯ0123456789.,-/() "
MARK_VOTES = ((400, "6", "rus", MARK_CHARS), (600, "6", "rus", MARK_CHARS), (400, "6", OCR_LANG, None))
OCR_WORKERS = 3
MIN_ROWS, MIN_COLS = 3, 2


def tesseract_available():
    return shutil.which(os.environ.get("TESSERACT_CMD") or "tesseract") is not None


def _tesseract():
    return os.environ.get("TESSERACT_CMD") or "tesseract"


# ---------- линии ----------

def _visible(page, point):
    """Точка содержимого страницы в координатах видимой страницы."""
    p = point * page.rotation_matrix if page.rotation else point
    return p.x, p.y


def page_lines(page):
    """Горизонтальные и вертикальные отрезки страницы: [(координата, начало, конец)]."""
    horizontal, vertical = [], []

    def add(a, b):
        ax, ay = _visible(page, a)
        bx, by = _visible(page, b)
        if abs(ay - by) <= AXIS_TOL_PT and abs(ax - bx) >= MIN_H_LEN_PT:
            horizontal.append(((ay + by) / 2, min(ax, bx), max(ax, bx)))
        elif abs(ax - bx) <= AXIS_TOL_PT and abs(ay - by) >= MIN_V_LEN_PT:
            vertical.append(((ax + bx) / 2, min(ay, by), max(ay, by)))

    for drawing in page.get_drawings():
        for item in drawing["items"]:
            kind = item[0]
            if kind == "l":
                add(item[1], item[2])
            elif kind == "re":
                r = item[1]
                add(r.tl, r.tr), add(r.bl, r.br), add(r.tl, r.bl), add(r.tr, r.br)
            elif kind == "qu":
                q = item[1]
                add(q.ul, q.ur), add(q.ll, q.lr), add(q.ul, q.ll), add(q.ur, q.lr)
    return horizontal, vertical


def merge_lines(lines):
    """Отрезки одной координаты — в линии: {координата: [(начало, конец), ...]}."""
    groups = []
    for coord, a, b in sorted(lines):
        if groups and coord - groups[-1][0][-1] <= LINE_TOL_PT:
            groups[-1][0].append(coord)
            groups[-1][1].append((a, b))
        else:
            groups.append(([coord], [(a, b)]))
    out = {}
    for coords, segments in groups:
        merged = []
        for a, b in sorted(segments):
            if merged and a <= merged[-1][1] + GAP_TOL_PT:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        out[sum(coords) / len(coords)] = [(a, b) for a, b in merged]
    return out


def _length(segments):
    return sum(b - a for a, b in segments)


def _covers(segments, a, b, share):
    """Проходит ли линия через отрезок [a, b] не меньше чем на долю share."""
    if b <= a:
        return False
    inside = sum(max(0.0, min(b, s1) - max(a, s0)) for s0, s1 in segments)
    return inside >= share * (b - a)


def _reference(lines):
    """Длина линии сетки: самая многочисленная группа линий близкой длины.

    Мерить от наибольшей линии нельзя: наибольшая — рамка листа. У таблицы, которая уже листа
    (характеристика систем Речникова — 1010 пунктов при рамке 1684), порог от рамки срезал
    все колонки разом. Линии одной таблицы, наоборот, почти равны между собой, и их много:
    берётся группа длин в пределах `LENGTH_SPREAD`, в которой линий больше всего, при равенстве —
    более длинная.
    """
    lengths = sorted((_length(s) for s in lines.values()), reverse=True)
    groups = []
    for length in lengths:
        if groups and length >= LENGTH_SPREAD * groups[-1][0]:
            groups[-1].append(length)
        else:
            groups.append([length])
    groups = [g for g in groups if len(g) >= MIN_COLS] or groups
    if not groups:
        return 0.0
    return max(groups, key=lambda g: (len(g), g[0]))[0]


class Grid:
    """Сетка таблицы: линии в пунктах видимой страницы."""

    def __init__(self, horizontal, vertical):
        self.h, self.v = horizontal, vertical          # {координата: [(начало, конец)]}
        self.ys = sorted(y for y, s in horizontal.items() if _length(s) >= COVER * _reference(horizontal))
        self.xs = sorted(x for x, s in vertical.items() if _length(s) >= COVER * _reference(vertical))

    def __bool__(self):
        return len(self.ys) > MIN_ROWS and len(self.xs) > MIN_COLS

    @property
    def columns(self):
        return list(zip(self.xs, self.xs[1:]))

    def bands(self, column):
        """Ячейки колонки сверху вниз: [(y0, y1)]. Делит колонку только линия, которая через неё проходит."""
        x0, x1 = self.columns[column]
        top, bottom = self.ys[0], self.ys[-1]
        cuts = sorted(y for y, segments in self.h.items()
                      if top - LINE_TOL_PT <= y <= bottom + LINE_TOL_PT and _covers(segments, x0, x1, COLUMN_COVER))
        return [(a, b) for a, b in zip(cuts, cuts[1:]) if b - a > 2 * CELL_PAD_PT]

    def cell(self, column, band):
        x0, x1 = self.columns[column]
        return (x0, band[0], x1, band[1])

    def band_at(self, column, y):
        """Ячейка колонки, в которую попадает высота y."""
        return next(((a, b) for a, b in self.bands(column) if a <= y <= b), None)


def find_grid(page):
    horizontal, vertical = page_lines(page)
    grid = Grid(merge_lines(horizontal), merge_lines(vertical))
    return grid if grid else None


# ---------- текст ячеек ----------

def layer_words(page):
    """Слова текстового слоя в пунктах видимой страницы: [(x0, y0, x1, y1, текст)]."""
    import pymupdf
    out = []
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        r = pymupdf.Rect(x0, y0, x1, y1)
        if page.rotation:
            r = r * page.rotation_matrix
            r.normalize()
        out.append((r.x0, r.y0, r.x1, r.y1, text))
    return out


def words_in(words, rect):
    """Текст слов, попавших в прямоугольник центром, в порядке чтения."""
    x0, y0, x1, y1 = rect
    inside = [w for w in words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1]
    if not inside:
        return ""
    height = sorted(w[3] - w[1] for w in inside)[len(inside) // 2] or 1.0
    lines = []
    for w in sorted(inside, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        middle = (w[1] + w[3]) / 2
        if lines and abs(middle - lines[-1][0]) <= 0.6 * height:
            lines[-1][1].append(w)
        else:
            lines.append([middle, [w]])
    return " ".join(w[4] for _, line in lines for w in sorted(line, key=lambda w: w[0])).strip()


def _clip(page, rect):
    import pymupdf
    x0, y0, x1, y1 = rect
    return pymupdf.Rect(x0 + CELL_PAD_PT, y0 + CELL_PAD_PT, x1 - CELL_PAD_PT, y1 - CELL_PAD_PT)


def _render(page, rects, dpi, folder):
    """Вырезы ячеек в PNG: [(номер ячейки, путь)]. Пустая ячейка не рендерится и не распознаётся."""
    import pymupdf
    zoom = pymupdf.Matrix(dpi / 72, dpi / 72)
    out = []
    for i, rect in enumerate(rects):
        clip = _clip(page, rect)
        if clip.width < 3 or clip.height < 3:
            continue
        pix = page.get_pixmap(matrix=zoom, clip=clip, colorspace=pymupdf.csGRAY, alpha=False)
        if pix.is_unicolor:
            continue
        path = os.path.join(folder, f"{dpi}-{i:05}.png")
        pix.save(path)
        out.append((i, path))
    return out


def _recognize(images, folder, tag, lang, psm, whitelist):
    """Один вызов Tesseract на список вырезов: {номер ячейки: текст} или None при сбое."""
    if not images:
        return {}
    listing = os.path.join(folder, f"cells-{tag}.txt")
    with open(listing, "w", encoding="utf-8") as f:
        f.write("\n".join(path for _, path in images))
    cmd = [_tesseract(), listing, "stdout", "-l", lang, "--psm", psm]
    if whitelist:
        cmd += ["-c", f"tessedit_char_whitelist={whitelist}"]
    try:
        # один поток на процесс: Tesseract с OpenMP иначе отнимает ядра у соседних ячеек (#52)
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=900,
                             env={**os.environ, "OMP_THREAD_LIMIT": os.environ.get("OMP_THREAD_LIMIT", "1")})
    except (OSError, subprocess.SubprocessError):
        return None
    if run.returncode != 0:
        return None
    parts = run.stdout.split("\f")
    return {i: " ".join(text.split()) for (i, _), text in zip(images, parts)}


def ocr_cells(page, rects, votes=((OCR_DPI, OCR_PSM, OCR_LANG, None),)):
    """Распознать вырезы страницы: по списку строк на каждое прочтение из votes, или None.

    Вырезы рендерятся один раз на разрешение, прочтения идут параллельно: Tesseract — отдельный
    процесс, и три прочтения 200 ячеек занимают столько же, сколько одно.
    """
    from concurrent.futures import ThreadPoolExecutor
    if not tesseract_available():
        return None
    folder = tempfile.mkdtemp(prefix="cells-")
    try:
        rendered = {dpi: _render(page, rects, dpi, folder) for dpi in dict.fromkeys(v[0] for v in votes)}
        with ThreadPoolExecutor(max_workers=OCR_WORKERS) as pool:
            jobs = [pool.submit(_recognize, rendered[dpi], folder, k, lang, psm, whitelist)
                    for k, (dpi, psm, lang, whitelist) in enumerate(votes)]
            reads = [job.result() for job in jobs]
        if any(read is None for read in reads):
            return None
        return [[read.get(i, "") for i in range(len(rects))] for read in reads]
    finally:
        shutil.rmtree(folder, ignore_errors=True)


class Table:
    """Сетка страницы и ленивое чтение ячеек: сначала слой, затем распознавание.

    `ocr_cache` — словарь прочтений ячеек от прежнего запуска. Распознавание листа занимает минуты,
    а правила разбора текста меняются чаще, чем лист: вызывающий хранит словарь рядом с листом
    и после правки правил разбирает те же прочтения заново, без Tesseract.
    """

    def __init__(self, page, grid, use_ocr=True, ocr_cache=None):
        self.page, self.grid, self.use_ocr = page, grid, use_ocr
        self.words = layer_words(page)
        self.ocr_cache = ocr_cache   # {ключ ячейки и набора прочтений: [прочтения]}
        self.ocr_used = 0            # сколько ячеек пришлось распознать
        self.ocr_failed = False      # Tesseract недоступен или упал

    def texts(self, cells):
        """Тексты ячеек [(колонка, (y0, y1))] → список строк; у распознанной ячейки — первое прочтение."""
        return [texts[0] if texts else "" for texts in self.variants(cells, votes=OCR_VOTES[:1])]

    @staticmethod
    def _cache_key(rect, votes):
        how = ";".join(f"{dpi}/{psm}/{lang}/{'w' if chars else '-'}" for dpi, psm, lang, chars in votes)
        return how + "|" + ",".join(f"{v:.1f}" for v in rect)

    def variants(self, cells, votes=OCR_VOTES):
        """Прочтения ячеек для голосования: у слоя одно, у распознанной ячейки — по числу votes."""
        rects = [self.grid.cell(column, band) for column, band in cells]
        out = [[words_in(self.words, r)] for r in rects]
        empty = [i for i, texts in enumerate(out) if not texts[0]]
        known = {}
        if self.ocr_cache is not None:
            known = {i: self.ocr_cache[self._cache_key(rects[i], votes)] for i in empty
                     if self._cache_key(rects[i], votes) in self.ocr_cache}
        todo = [i for i in empty if i not in known]
        if todo and self.use_ocr:
            reads = ocr_cells(self.page, [rects[i] for i in todo], votes=votes)
            if reads is None:
                self.ocr_failed = True
                todo = []
            for k, i in enumerate(todo):
                known[i] = [read[k] for read in reads]
                if self.ocr_cache is not None:
                    self.ocr_cache[self._cache_key(rects[i], votes)] = known[i]
        for i, texts in known.items():
            if any(texts):
                out[i] = texts
                self.ocr_used += 1
        return out

    def rect_norm(self, column, band):
        """Прямоугольник ячейки во внутренней системе конвейера: доли видимой страницы, Y сверху."""
        x0, y0, x1, y1 = self.grid.cell(column, band)
        w, h = self.page.rect.width or 1.0, self.page.rect.height or 1.0
        return [round(max(0.0, min(1.0, v)), 5) for v in (x0 / w, y0 / h, x1 / w, y1 / h)]


def read_table(page, use_ocr=True, ocr_cache=None):
    """Таблица страницы или None, если сетки на странице нет."""
    grid = find_grid(page)
    return Table(page, grid, use_ocr=use_ocr, ocr_cache=ocr_cache) if grid else None
