"""Страница-доказательство для экрана инспектора: картинка и место на ней. Задача #33.

Карточка находки показывает страницы ПД и РД рядом, и место расхождения на них
обведено облаком изменений. Здесь две вещи:

- `render_page` — картинка видимой страницы (с учётом поворота) для экрана;
- `locate` — прямоугольники места на этой странице во внутренней системе координат
  конвейера (`pipeline/coords.py`): доли видимой страницы, ось Y сверху. В этой же
  системе лежит картинка, поэтому облако рисуется поверх неё без пересчёта.

Место ищется по тексту страницы: сначала значение из находки в том написании,
в каком его прочитал разбор («3694,60»), затем номер помещения как отдельное слово.
Если ничего не найдено, прямоугольников нет. Место не угадывается и не ставится
по умолчанию: рамка на случайном участке листа выглядит доказательством, а им не является.
"""
import re

RENDER_LONG_SIDE_PX = 2200
JPEG_QUALITY = 82
MAX_RECTS = 6


def render_page(page, long_side_px=RENDER_LONG_SIDE_PX, quality=JPEG_QUALITY):
    """JPEG видимой страницы: байты, ширина и высота в пикселях."""
    import pymupdf
    rect = page.rect
    zoom = long_side_px / max(rect.width, rect.height, 1.0)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    return pix.tobytes("jpeg", jpg_quality=quality), pix.width, pix.height


def _visible(page, rect):
    """Прямоугольник текстового слоя (неповёрнутая страница) в доли видимой страницы."""
    r = rect * page.rotation_matrix if page.rotation else rect
    w, h = page.rect.width or 1.0, page.rect.height or 1.0
    box = [r.x0 / w, r.y0 / h, r.x1 / w, r.y1 / h]
    return [round(max(0.0, min(1.0, v)), 5) for v in box]


def value_variants(raw):
    """Написания числа на странице: «3694,60», «3 694,60», «3694.60», «3694,6»."""
    raw = (raw or "").strip()
    if not raw or not re.search(r"\d", raw):
        return []
    compact = re.sub(r"(?<=\d)[\s ](?=\d)", "", raw)
    out = [raw, compact]
    m = re.fullmatch(r"(\d+)([.,])(\d+)", compact)
    if m:
        whole, sep, frac = m.groups()
        other = "." if sep == "," else ","
        spaced = re.sub(r"(?<=\d)(?=(\d{3})+$)", " ", whole)
        for w in (whole, spaced):
            out += [f"{w}{sep}{frac}", f"{w}{other}{frac}"]
            trimmed = frac.rstrip("0")
            if trimmed and trimmed != frac:
                out += [f"{w}{sep}{trimmed}", f"{w}{other}{trimmed}"]
    seen, uniq = set(), []
    for v in out:
        if v not in seen and len(re.sub(r"\D", "", v)) >= 2:
            seen.add(v)
            uniq.append(v)
    return uniq


def _digit_bounded(page, rect, variant):
    """Совпадение не является частью более длинного числа: «694,60» внутри «3694,60» не годится."""
    import pymupdf
    wide = pymupdf.Rect(rect.x0 - rect.width, rect.y0, rect.x1 + rect.width, rect.y1)
    text = page.get_textbox(wide) or ""
    compact = re.sub(r"\s+", " ", text)
    idx = compact.find(variant)
    if idx < 0:
        return True  # текст вокруг не восстановился: не отбрасываем найденное
    before = compact[idx - 1] if idx > 0 else " "
    after = compact[idx + len(variant)] if idx + len(variant) < len(compact) else " "
    return not (before.isdigit() or after.isdigit())


def find_value(page, raw):
    """Прямоугольники значения на странице."""
    for variant in value_variants(raw):
        rects = [r for r in page.search_for(variant) if _digit_bounded(page, r, variant)]
        if rects:
            return [_visible(page, r) for r in rects[:MAX_RECTS]]
    return []


def find_element_values(page, kind, columns):
    """Значения элемента на странице: классы бетона «B40» и толщины «1200 мм» по отдельности.

    Класс ищется в обоих алфавитах: в документах «В40» кириллицей, в разборе — латиницей.
    Толщина сначала ищется с обозначением «t=1200», «h=1200» или единицей, и только потом
    голым числом: на чертеже «1200» — это ещё и размер.
    """
    rects = []
    for column in columns or ():
        m = re.search(r"\d+(?:[,.]\d+)?", str(column))
        if not m:
            continue
        number = m.group(0)
        if kind == "element_class":
            variants = [f"В{number}", f"B{number}", f"В {number}", f"B {number}"]
        else:
            variants = [f"t={number}", f"h={number}", f"t = {number}", f"h = {number}",
                        f"{number} мм", f"{number}мм", number]
        for variant in variants:
            hits = [r for r in page.search_for(variant) if _digit_bounded(page, r, variant)]
            if hits:
                rects += [_visible(page, r) for r in hits[:2 if variant == number else MAX_RECTS]]
                break
        if len(rects) >= MAX_RECTS:
            break
    return rects[:MAX_RECTS]


def find_word(page, token):
    """Прямоугольники слова, совпадающего с токеном целиком: «012», но не «2012»."""
    token = (token or "").strip()
    if not token:
        return []
    hits = []
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        if re.sub(r"^[^\w]+|[^\w]+$", "", text) == token:
            import pymupdf
            hits.append(_visible(page, pymupdf.Rect(x0, y0, x1, y1)))
            if len(hits) >= MAX_RECTS:
                break
    return hits


def number_raws(value):
    """Написания числа из разбора для поиска на странице: 1835.5 → «1835,5», «1835,50»."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return []
    out = []
    for digits in (1, 2):
        text = f"{v:.{digits}f}"
        out += [text.replace(".", ","), text]
    return out


def locate(page, raw_value=None, locations=(), row_values=()):
    """Место на странице: (прямоугольники, чем найдено) или ([], None).

    row_values — слагаемые, если показатель собран суммой строк ведомости: самой
    суммы на странице нет, и место — это строки, из которых она сложена.
    """
    if raw_value:
        rects = find_value(page, raw_value)
        if rects:
            return rects, "VALUE"
    rows = []
    for value in row_values or ():
        for raw in number_raws(value):
            hits = find_value(page, raw)
            if hits:
                rows += hits[:2]
                break
    if rows:
        return rows[:MAX_RECTS * 2], "ROWS"
    for token in locations or ():
        token = str(token).strip()
        # номер помещения или короткое обозначение; «Здание» и «Участок» на листе не ищутся
        if re.fullmatch(r"[\w.-]{1,12}", token) and re.search(r"\d", token):
            rects = find_word(page, token)
            if rects:
                return rects, "LOCATION"
    return [], None
