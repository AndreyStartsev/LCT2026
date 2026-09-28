"""Привязка элементов к помещениям на планах и схемах. Задача #4.

Зачем: организатор помечает доказательства нарушений прямо на планах, а не
в экспликациях. Помещения 140, 142, 147, 314 из перечня нарушений в экспликациях
отсутствуют в принципе, их можно достать только с чертежа.

Как устроена подпись помещения на плане. Вокруг номера обнаруживается устойчивая
картина, проверенная на страницах, которые организатор пометил как доказательства:

    поз.169            маркировка позиции, строкой выше
    140 Физического    номер и наименование на одной строке
    эксперимента       продолжение наименования строкой ниже
    В2.9               марка системы рядом

Именно марка рядом с номером и есть предмет сравнения: третье эталонное нарушение
говорит, что в помещениях 140 и 142 отсутствует предусмотренная проектом вытяжная
вентиляция, а «В» — это марка вытяжной системы.

Почему нельзя фильтровать по реестру помещений из экспликаций: на странице-доказательстве
из пяти целевых номеров в реестре нашёлся один. Реестр отсеивает не шум, а цель.

Внимание к системе координат: организатор публикует прямоугольники в системе PDF
с началом в левом нижнем углу, а слова из текстового слоя приходят с началом
в левом верхнем. По оси X координаты совпадают точно, по Y они зеркальны.
"""
import math
import re

from pipeline import coords

# Номер помещения. Хвостовая запятая допускается: на плане одна подпись часто
# закрывает несколько помещений сразу — «267, 270 Раздевальная и душевая».
# Точка в хвосте, наоборот, отсекается: «10.» и «11.» — это нумерация списков.
NUM_RE = re.compile(r"^(\d{2,3}(?:\.\d{1,2})?)[,;]?$")
POS_RE = re.compile(r"^(?:поз|оз)\.?\s?\d{1,4}$", re.I)
POS_PREFIX_RE = re.compile(r"^(?:поз|оз|п)\.?$", re.I)
# Марка инженерной системы: приточная, вытяжная, приточно-вытяжная, дымоудаление.
MARK_RE = re.compile(r"^(?:П|В|ПВ|ВЕ|ДУ|К|Т)\s?\d{1,2}(?:\.\d{1,2})?$")
WORD_RE = re.compile(r"^[А-ЯЁа-яё][А-ЯЁа-яё\-]{3,}$")

# Латинские близнецы для нормализации марок инженерных систем из OCR (задача #22)
_TWINS = str.maketrans({
    "B": "В", "P": "Р", "T": "Т", "K": "К", "E": "Е", "A": "А",
    "C": "С", "H": "Н", "M": "М", "O": "О", "X": "Х",
})

# Расстояния привязки. Доли листа подобраны на листах А3 Тюменской-5 и остаются
# запасным вариантом, когда размер листа неизвестен. Когда он известен, те же
# расстояния считаются в миллиметрах листа: доля листа зависит от формата, и на А1
# «рядом» растягивалось бы вдвое, а марка уходила бы чужому помещению (#41).
SAME_LINE_DY = 0.005      # слова одной строки отличаются по Y не больше этого (допуск под OCR)
NAME_MAX_DX = 0.045       # наименование стоит вплотную справа или слева от номера
# Наименование бывает и не на одной строке с номером, а прямо под ним: на схеме
# теплоснабжения «012» стоит над словом «Венткамера» со сдвигом 0,014 по высоте.
BELOW_DY = 0.022          # насколько ниже номера ещё считается его подписью
BELOW_DX = 0.020          # и насколько вбок при этом
# Радиус поиска марок и позиций вокруг номера. Подобран по замеру, а не на глаз:
# на проектном листе марки стоят строго вертикальной стопкой над номером, по три
# на помещение, на расстояниях 0,031, 0,039 и 0,049. Радиус 0,04 срезал третью
# марку у каждого помещения. Расширение до 0,06 и дальше ничего нового к целевым
# помещениям не добавляет, только увеличивает число привязанных марок.
NEIGHBOUR_R = 0.05

# Те же расстояния в высотах строки. Высота строки — единственная мера, которая
# не зависит ни от формата листа, ни от масштаба чертежа: на А0 подпись и чертёж
# крупнее, и «рядом» там больше в тех же миллиметрах. Сняты с листа А3 Тюменской-5,
# где высота слова 2,5 мм: 1,5 мм, 19 мм, 6,5 мм, 8,4 мм и 15 мм (#41).
SAME_LINE_H = 0.6
NAME_MAX_H = 7.6
BELOW_H = 2.6
BELOW_DX_H = 3.4
NEIGHBOUR_H = 6.0
DEFAULT_WORD_MM = 2.5     # высота слова, если рамка слова вырождена


def thresholds(page_size=None):
    """Как мерить расстояния на этом листе: миллиметры листа или доли (запасной путь)."""
    size = coords.page_mm(page_size)
    if not size:
        return {"mm": None, "same_line_dy": SAME_LINE_DY, "name_max_dx": NAME_MAX_DX,
                "below_dy": BELOW_DY, "below_dx": BELOW_DX, "radius": NEIGHBOUR_R}
    return {"mm": size}


def limits(word, th):
    """Пределы привязки для одного номера: в долях листа, считая от высоты его строки."""
    if not th["mm"]:
        return th
    w_mm, h_mm = th["mm"]
    line_mm = (word["bbox"][3] - word["bbox"][1]) * h_mm or DEFAULT_WORD_MM
    return {"mm": th["mm"],
            "same_line_dy": SAME_LINE_H * line_mm / h_mm,
            "name_max_dx": NAME_MAX_H * line_mm / w_mm,
            "below_dy": BELOW_H * line_mm / h_mm,
            "below_dx": BELOW_DX_H * line_mm / w_mm,
            "radius": NEIGHBOUR_H * line_mm}


def _clean_tok(t):
    """Очистка пунктуации и скобок вокруг токена (актуально для OCR)."""
    return (t or "").strip(" \t\r\n[]()«»\"'|;:,.?!/\\“”„`~")


def _center(w):
    b = w["bbox"]
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def _dist(a, b):
    ax, ay = _center(a)
    bx, by = _center(b)
    return math.hypot(ax - bx, ay - by)


def flip_y(bbox):
    """Устарело: используйте coords.internal_to_tz."""
    return coords.internal_to_tz(bbox)


def _preprocess_words(words):
    """Нормализация слов: фильтрация шума OCR и склейка поз. + число."""
    valid = [w for w in words if w.get("conf", 100) >= 20 and (w.get("t") or "").strip()]

    # Ищем пары (префикс позиции + число)
    pos_prefixes = []
    for w in valid:
        t = _clean_tok(w["t"])
        if POS_PREFIX_RE.match(t):
            pos_prefixes.append(w)

    merged_pos = set()
    positions = []
    for p in pos_prefixes:
        px, py = _center(p)
        for w in valid:
            if w is p or id(w) in merged_pos:
                continue
            t = _clean_tok(w["t"])
            if re.match(r"^\d{1,4}$", t):
                wx, wy = _center(w)
                dx = w["bbox"][0] - p["bbox"][2]
                dy = abs(wy - py)
                if -0.005 <= dx <= 0.025 and dy <= 0.01:
                    merged_pos.add(id(p))
                    merged_pos.add(id(w))
                    positions.append({
                        "t": f"поз.{t}",
                        "bbox": [min(p["bbox"][0], w["bbox"][0]),
                                 min(p["bbox"][1], w["bbox"][1]),
                                 max(p["bbox"][2], w["bbox"][2]),
                                 max(p["bbox"][3], w["bbox"][3])],
                        "source": p.get("source"),
                    })
                    break

    out = []
    for w in valid:
        if id(w) in merged_pos:
            continue
        t = _clean_tok(w["t"])
        if re.match(r"^8\d\.\d{1,2}$", t):
            w = dict(w, t="В" + t[1:])
        out.append(w)
    out.extend(positions)
    return out


def extract(words, min_name=1, page_size=None):
    """Помещения, найденные на листе, с наименованием и марками рядом.

    min_name: сколько слов наименования требовать. Ноль означает «брать номер
    и без наименования», это резко повышает шум и годится только для отладки.

    page_size: (ширина, высота) листа в пунктах. Если известен, расстояния привязки
    считаются в миллиметрах листа, а не в долях (#41).
    """
    th = thresholds(page_size)
    words = _preprocess_words(words)
    num_map = {}
    for w in words:
        clean = _clean_tok(w["t"])
        m = NUM_RE.match(clean)
        if m:
            num_map[id(w)] = m.group(1)

    nums = [w for w in words if id(w) in num_map]
    if not nums:
        return []

    # Марка и позиция принадлежат ровно одному помещению — ближайшему по номеру.
    # Раздавать их всем номерам в радиусе нельзя: на рабочем чертеже помещения
    # перечислены в таблице строка за строкой, соседняя строка отстоит на 0,029,
    # и марка соседа попадает в радиус. Именно так помещению 142 доставалась
    # чужая вытяжка В4 из строки помещения 147, а нарушение говорит ровно
    # обратное — вытяжки в 142 нет.
    centers = {id(w): _center(w) for w in words}

    # Марка и позиция принадлежат ровно одному помещению — ближайшему по номеру.
    attached = {}
    for o in words:
        raw_t = (o["t"] or "").strip()
        parts = [p for p in re.split(r"[/,]", raw_t) if p.strip()] or [raw_t]
        items_to_attach = []
        for part in parts:
            clean_t = _clean_tok(part)
            norm_t = clean_t.translate(_TWINS)
            # Замена 8 -> В в марках из OCR (82.10 -> В2.10, 8.1 -> В1.1)
            if re.match(r"^8\d(?:\.\d{1,2})?$", norm_t):
                norm_t = "В" + norm_t[1:]

            if MARK_RE.match(norm_t):
                items_to_attach.append(("marks", norm_t.replace(" ", "")))
            elif POS_RE.match(clean_t):
                items_to_attach.append(("positions", clean_t.replace(" ", "")))

        if not items_to_attach:
            continue

        ox, oy = centers[id(o)]
        best, best_d = None, None
        for n in nums:
            nx, ny = centers[id(n)]
            lim = limits(n, th)
            if th["mm"]:
                # расстояние в миллиметрах листа: по долям оно вытягивалось вдоль
                # длинной стороны, и «ближайшее» помещение зависело от формата
                d = math.hypot((nx - ox) * th["mm"][0], (ny - oy) * th["mm"][1])
            else:
                d = math.hypot(nx - ox, ny - oy)
            if d < lim["radius"] and (best_d is None or d < best_d):
                best, best_d = n, d
        if best is not None:
            entry = attached.setdefault(id(best), {"marks": [], "positions": []})
            for kind, token_val in items_to_attach:
                entry[kind].append(token_val)

    out = []
    for w in nums:
        wx, wy = centers[id(w)]
        lim = limits(w, th)
        name_parts = []
        for o in words:
            if o is w:
                continue
            ox, oy = centers[id(o)]
            t = _clean_tok(o["t"])
            same_line = abs(oy - wy) <= lim["same_line_dy"] and abs(ox - wx) <= lim["name_max_dx"]
            below = 0 < (oy - wy) <= lim["below_dy"] and abs(ox - wx) <= lim["below_dx"]
            if (same_line or below) and WORD_RE.match(t):
                name_parts.append((oy, ox, t))
        if len(name_parts) < min_name:
            continue
        name_parts.sort()
        got = attached.get(id(w), {"marks": [], "positions": []})
        num_str = num_map[id(w)]

        # Нормализация марок с пропущенной точкой (В27 при наличии В2.* -> В2.7)
        raw_marks = got["marks"]
        dotted_prefs = {m[:m.find(".") + 1] for m in raw_marks if "." in m}
        norm_marks = []
        for m in raw_marks:
            nodot = re.match(r"^([А-ЯA-Z]+)(\d)(\d)$", m)
            if nodot:
                cand_pref = f"{nodot.group(1)}{nodot.group(2)}."
                if cand_pref in dotted_prefs:
                    norm_marks.append(f"{cand_pref}{nodot.group(3)}")
                    continue
            norm_marks.append(m)

        out.append({
            "number": num_str,
            "name": " ".join(t for _, _, t in name_parts)[:70] or None,
            "marks": sorted(set(norm_marks)),
            "positions": sorted(set(got["positions"])),
            "bbox": w["bbox"],
            "bbox_tz": coords.internal_to_tz(w["bbox"]),
            "bbox_pdf": coords.internal_to_tz(w["bbox"]),
        })

    # Один номер часто встречается на листе дважды: в экспликации, свёрстанной
    # на том же листе, и на самом плане. Наименование есть только у первой записи,
    # марки систем — только у второй, и выбор одной из них теряет половину смысла.
    # Поэтому записи с одинаковым номером сливаем: наименование берём длиннейшее,
    # марки и позиции объединяем, прямоугольник оставляем от записи с марками —
    # именно она указывает на место нарушения на чертеже.
    best = {}
    for r in out:
        cur = best.get(r["number"])
        if cur is None:
            best[r["number"]] = dict(r)
            continue
        if len(r["name"] or "") > len(cur["name"] or ""):
            cur["name"] = r["name"]
        if r["marks"] and not cur["marks"]:
            cur["bbox"] = r["bbox"]
            cur["bbox_tz"] = r.get("bbox_tz") or coords.internal_to_tz(r["bbox"])
            cur["bbox_pdf"] = cur["bbox_tz"]
        cur["marks"] = sorted(set(cur["marks"]) | set(r["marks"]))
        cur["positions"] = sorted(set(cur["positions"]) | set(r["positions"]))
    return sorted(best.values(), key=lambda r: (len(r["number"]), r["number"]))


def elements_by_room(rows):
    """Свод «помещение — марки систем» для сравнения между стадиями."""
    out = {}
    for r in rows:
        if r["marks"]:
            out.setdefault(r["number"], set()).update(r["marks"])
    return {k: sorted(v) for k, v in out.items()}
