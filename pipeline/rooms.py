"""Разбор экспликаций помещений. Задача #3.

Зачем: все три эталонных нарушения адресованы номером помещения (венткамера 012,
помещения МГН 267, 270, 271, 272, помещения 140 и 142), и все десять обучающих
проверок имеют тип локации ROOM. Без достоверного реестра помещений сравнивать нечего.

Почему из экспликации, а не с чертежа: на чертеже порядок чтения текстового слоя
перемешан, и в строке «Воздухозаборная шахта 012.1 Форкамера 012 Венткамера»
не видно, какой номер к какому названию относится. Экспликация же обычная таблица:

    012 Венткамера 99.7 В2

Строки собираются по координатам слов, а не по линейному тексту: так строка таблицы
не склеивается с соседней.
"""
import collections
import re

HEADER_WORDS = ("экспликация", "наименование", "площадь", "помещени")
# Номер помещения в корпусе — две-три цифры с необязательным подномером. За корпусом
# нумерация другая: «1.01», «2.3.1», «А101», «1.1-4», «7», «1001». Поэтому форма номера
# не задаётся заранее, а выводится из столбца номеров самой экспликации (#41): кандидатом
# считается короткий токен из цифр с необязательной буквой и разделителями, а какие формы
# у этого объекта — решает то, что в столбце повторяется. NUM_RE остаётся запасным
# разбором для одиночной строки без столбца.
NUM_RE = re.compile(r"^(\d{2,3}(?:\.\d{1,2})?)$")
# Одиночная заглавная буква — тоже номер: лестничные клетки «А», «Б» в спецификациях Revit
# (Алтуфьевское, #114). Как и любая чужая форма, принимается, только если столбец подписан номером
# помещения и буквы в нём повторяются
NUM_CANDIDATE = re.compile(r"^(?:[А-ЯA-Z]?\d{1,4}(?:[.\-/]\d{1,3}){0,2}[а-яa-z]?|[А-ЯЁ])$")
AREA_RE = re.compile(r"^\d{1,5}[.,]\d{1,2}$")
CAT_RE = re.compile(r"^(?:[А-Я]\d|[А-Я]\d[А-Я]?|Д|В\d)$")
# сколько раз форма должна встретиться в столбце, чтобы считаться нумерацией объекта
SHAPE_MIN = 2
# Подпись столбца номеров: «Номер помещения», «№ пом.», «Номер комнаты». По ней столбец
# номеров отличается от нумерации строк таблицы («№ п/п» в балансе площадей) и от позиций
# спецификации («Поз. обозн.»). Слово берётся по началу: в текстовом слое подпись приходит
# разорванной переносом — «Номер | поме | - | щения»
ROOM_HEADER = re.compile(r"(?:^|[^а-яёa-z])(?:пом|комнат)", re.I)
# Заголовок над шапкой таблицы: «Экспликация помещений». У части проектировщиков столбец номеров
# подписан одним словом «Номер» (Полярная 25, ДОО: «Номер | Наименование | Площадь, м2 | Кат.
# помещения»), и без заголовка такая экспликация не отличалась бы от спецификации (#100)
# «Спецификация помещений» — то же самое под именем, которое даёт спецификации помещений Revit
# (Алтуфьевское: «Спецификация помещений 1-го этажа | Номер | Имя | Площадь», #114)
EXPLICATION_TITLE = re.compile(r"(?:экспликаци|спецификаци)\w*\s+помещени", re.I)
TITLE_DY = 0.04          # заголовок стоит над шапкой не дальше стольких долей высоты листа
# «Номер» или «№» среди слов шапки столбца: заголовок таблицы стоит над шапкой близко
# и попадает в ту же полосу («Экспликация Номер»)
HEADER_NUMBER = re.compile(r"(?:^|\s)(?:номер|№)", re.I)


def shape(token):
    """Форма номера: цифра → «9», буква → «A». «012» → «999», «1.01» → «9.99», «А101» → «A999»."""
    return re.sub(r"[А-ЯA-Zа-яa-z]", "A", re.sub(r"\d", "9", token))


def column_shapes(tokens, header="", titled=False):
    """Формы номеров этой экспликации по её столбцу номеров.

    Привычная форма корпуса берётся всегда. Чужие формы — «1.01», «2.3.1», «А101»,
    «1.1-4», «7», «1001» — принимаются, если столбец подписан номером помещения и форма
    в нём повторяется. Подпись обязательна: без неё столбцом номеров притворяются
    нумерация строк баланса площадей («№ п/п») и позиции спецификации, где «80-6.3» —
    диаметр и давление, а не помещение (#41).

    Повтор обязателен по той же причине: одиночное число в столбце — чаще случайность.
    Проверено на корпусе: так находятся «К1.1 Досуговая» Новослободской, «0010…0012»
    Тюменской-5 и однозначные номера комнат в квартирах.

    `titled` — над таблицей заголовок «Экспликация помещений», а столбец подписан «Номер»:
    это та же подпись номера помещения, разнесённая на две строки (#114).
    """
    cands = [t for t in tokens if NUM_CANDIDATE.match(t)]
    classic = {shape(t) for t in cands if NUM_RE.match(t)}
    if not (ROOM_HEADER.search(header) or titled):
        return classic
    counts = collections.Counter(shape(t) for t in cands)
    return classic | {sh for sh, n in counts.items() if n >= SHAPE_MIN}


def is_explication(text):
    """Похожа ли страница на экспликацию помещений."""
    low = (text or "").lower()
    hits = sum(1 for w in HEADER_WORDS if w in low)
    return hits >= 2


# Допуск «та же строка» в высотах слова. Прежние 0,006 доли листа — это высота слова
# экспликации на А3, умноженная на 1,1; в долях допуск зависел бы от формата листа,
# в высотах слова — ни от формата, ни от масштаба (#41). Замер на Тюменской-5:
# при 1,1 разбирается 211 помещений и 40 % строк остаются неразобранными,
# при 0,75 — 192 и 45 %, при 0,6 — 175 и 47 %
ROW_TOL_H = 1.1
ROW_TOL_DEFAULT = 0.006


def row_tolerance(words):
    """Допуск «та же строка» по высоте слов страницы."""
    heights = sorted(w["bbox"][3] - w["bbox"][1] for w in words if w["bbox"][3] > w["bbox"][1])
    if not heights:
        return ROW_TOL_DEFAULT
    return heights[len(heights) // 2] * ROW_TOL_H or ROW_TOL_DEFAULT


def rows_from_words(words, y_tol=None):
    """Сгруппировать слова в строки таблицы по вертикали."""
    y_tol = y_tol or row_tolerance(words)
    ws = sorted(words, key=lambda w: (round(w["bbox"][1] / y_tol), w["bbox"][0]))
    out, cur, last = [], [], None
    for w in ws:
        y = w["bbox"][1]
        if last is not None and abs(y - last) > y_tol:
            if cur:
                out.append(cur)
            cur = []
        cur.append(w)
        last = y
    if cur:
        out.append(cur)
    return out


def is_classic_shape(sh):
    """Форма, которую и так разбирает NUM_RE: «999», «99.9». Для неё ничего менять не нужно."""
    return bool(NUM_RE.match(sh.replace("9", "1").replace("A", "А")))


def parse_row(row, learned=None):
    """Разобрать строку таблицы. Возвращает список записей: их может быть несколько.

    Позиционный разбор («первый токен — номер») не работает: в одной физической
    строке слипаются заголовок группы и несколько записей подряд, например
    «Группа начальных классов 223 Рекреация коридорного типа 190.9 224».
    Поэтому идём последовательностью: встретили номер — копим наименование —
    встретили площадь — выдали запись.

    learned(слово) — номер той формы, которую подсказал столбец номеров этой экспликации
    (`parse_page`). Проверяется раньше площади: «1.01» и «12.5» на вид неразличимы,
    и что из них номер, решает столбец, а не вид токена (#41). Привычные номера корпуса
    разбираются как раньше — после площади и в любом месте строки.
    """
    words = [w for w in row if w["t"].strip()]
    if learned is None:
        def learned(_w):
            return False
    out = []
    number, name_parts, category = None, [], None

    def flush(area):
        nonlocal number, name_parts, category
        if number is None or area is None:
            number, name_parts, category = None, [], None
            return
        name = " ".join(name_parts).strip(" .,:;")
        letters = sum(1 for c in name if c.isalpha())
        digits = sum(1 for c in name if c.isdigit())
        if (name and 4 <= len(name) <= 70 and letters >= 4 and digits <= 2
                and letters / max(len(name), 1) >= 0.5):
            out.append({"number": number, "name": name,
                        "area_m2": area, "category": category})
        number, name_parts, category = None, [], None

    for w in words:
        t = w["t"].strip()
        if learned(w):
            # новый номер: предыдущая незакрытая запись отбрасывается
            number, name_parts, category = t, [], None
            continue
        norm = t.replace(",", ".")
        if AREA_RE.match(norm):
            flush(float(norm))
            continue
        m = NUM_RE.match(t)
        if m:
            number, name_parts, category = m.group(1), [], None
            continue
        if CAT_RE.match(t):
            category = t
            continue
        if number is not None:
            name_parts.append(t)
    return out


# Слова шапки, по которым узнаются столбцы таблицы (#15). Сравнение — по началу слова
# в нижнем регистре: в текстовом слое подпись приходит разорванной переносом,
# «Номер | поме | - | щения», и «Площадь, м2» — тремя словами.
HEAD_NUMBER = ("номер", "№", "n")
HEAD_NAME = ("наименование", "назначение")
HEAD_AREA = ("площадь", "s,")
HEAD_CAT = ("кат", "категория")
HEAD_ROW_DY = 0.02       # шапка занимает одну строку листа
# Конец таблицы — вертикальный разрыв в столбце номеров больше `GAP_ROWS` шагов строки и не меньше
# `GAP_MIN` высоты листа. Под спецификацией Revit сразу идёт чертёж: подписи плана «1 : 50»
# и метки помещений в полосу таблицы попадать не должны (#114)
GAP_ROWS = 4
GAP_MIN = 0.03


def head_words(words, y_head, lo, hi):
    """Слова шапки таблицы между lo и hi по горизонтали."""
    return sorted((w for w in words
                   if lo <= w["bbox"][0] <= hi and abs(w["bbox"][1] - y_head) <= HEAD_ROW_DY
                   and w["t"].strip()),
                  key=lambda w: w["bbox"][0])


def _is_head(word, variants):
    t = word["t"].strip(" .,:;").lower()
    return any(t.startswith(v) for v in variants)


def _name_head(word, words):
    """Подпись столбца наименований: «Наименование» или, у Revit, «Имя» между «Номер» и «Площадь».

    «Имя» само по себе встречается и в других таблицах, поэтому принимается только в шапке, где
    слева в той же строке подпись номера, а справа — площади (#114).
    """
    t = word["t"].strip(" .,")
    if t == "Наименование":
        return True
    if t != "Имя":
        return False
    x0, x1, y = word["bbox"][0], word["bbox"][2], word["bbox"][1]
    row = [w for w in words if w is not word and abs(w["bbox"][1] - y) <= HEAD_ROW_DY]
    return (any(x0 - 0.12 < w["bbox"][0] < x0 and _is_head(w, ("номер", "№")) for w in row)
            and any(x1 < w["bbox"][0] < x1 + 0.12 and _is_head(w, HEAD_AREA) for w in row))


def columns(words, y_head, left, right, name_x, learned=None, bottom=float("inf")):
    """Границы столбцов таблицы: {number, name, area, cat} → (от, до).

    Подпись шапки стоит по центру столбца, поэтому её края столбцов не задают:
    «Наименование» начинается на 0,614, а наименования строк — на 0,590. Границы
    берутся по самим строкам: где стоят номера, где площади, где категории.
    Столбец наименования — всё между ними. Так в наименование перестают затекать
    слова соседней колонки и соседней таблицы (#15).

    Пустой словарь — столбцы не опознаны, разбор идёт прежним способом. `bottom` — нижний
    край таблицы: подписи чертежа под ней границ столбцов не сдвигают (#114).
    """
    band = [w for w in words
            if left <= (w["bbox"][0] + w["bbox"][2]) / 2 < right
            and y_head + 0.002 < w["bbox"][1] < bottom - 0.002 and w["t"].strip()]
    nums = [w for w in band
            if (w["bbox"][0] + w["bbox"][2]) / 2 < name_x
            and (NUM_RE.match(w["t"].strip()) or (learned and learned(w)))]
    if not nums:
        return {}
    num_right = max(w["bbox"][2] for w in nums)
    areas = [w for w in band if w["bbox"][0] > num_right
             and AREA_RE.match(w["t"].strip().replace(",", "."))]
    cats = [w for w in band if w["bbox"][0] > num_right and CAT_RE.match(w["t"].strip())]
    area_left = min((w["bbox"][0] for w in areas), default=right)
    cat_left = min((w["bbox"][0] for w in cats if w["bbox"][0] >= area_left), default=right)
    out = {"number": (left, num_right + 0.001),
           "name": (num_right + 0.001, min(area_left, cat_left) - 0.001)}
    if areas:
        out["area"] = (area_left - 0.001, cat_left)
    if cats:
        out["cat"] = (cat_left - 0.001, right)
    if out["name"][1] <= out["name"][0]:
        return {}
    return out


MIN_NAME_LETTERS = 3      # «ПУИ» — наименование, «м2» — нет
MAX_NAME = 120


def parse_row_columns(row, cols, learned=None):
    """Строка таблицы по столбцам шапки: одна строка — одна запись (#15).

    Площадь необязательна: раньше строка без площади отбрасывалась как проза,
    и помещения вроде «147 Лаборантская» в реестр не попадали. Наименование
    собирается только из своего столбца, поэтому слова соседней таблицы в него
    не затекают.
    """
    def in_col(word, kind):
        if kind not in cols:
            return False
        x0, x1 = cols[kind]
        center = (word["bbox"][0] + word["bbox"][2]) / 2
        return x0 - 0.002 <= center < x1

    numbers = [w for w in row if in_col(w, "number")
               and ((learned and learned(w)) or NUM_RE.match(w["t"].strip()))]
    if not numbers:
        return []
    # В одну полосу по вертикали иногда попадают несколько строк таблицы: тогда
    # каждое слово достаётся ближайшему по высоте номеру, иначе наименования
    # склеиваются — «Прихожая Гардеробная Жилая комната Жилая комната» (#15)
    numbers.sort(key=lambda w: (w["bbox"][1] + w["bbox"][3]) / 2)
    buckets = {id(w): {"name": [], "area": [], "cat": []} for w in numbers}

    def nearest(word):
        wy = (word["bbox"][1] + word["bbox"][3]) / 2
        return min(numbers, key=lambda n: abs((n["bbox"][1] + n["bbox"][3]) / 2 - wy))

    for w in row:
        if w in numbers or not w["t"].strip():
            continue
        for kind in ("name", "area", "cat"):
            if in_col(w, kind):
                buckets[id(nearest(w))][kind].append(w)
                break

    out = []
    for num in numbers:
        got = buckets[id(num)]
        name = re.sub(r"\s+", " ", " ".join(w["t"].strip() for w in got["name"])).strip(" .,:;")
        if sum(1 for c in name if c.isalpha()) < MIN_NAME_LETTERS or len(name) > MAX_NAME:
            continue
        area = next((float(w["t"].strip().replace(",", "."))
                     for w in got["area"] if AREA_RE.match(w["t"].strip().replace(",", "."))), None)
        category = next((w["t"].strip() for w in got["cat"] if CAT_RE.match(w["t"].strip())), None)
        out.append({"number": num["t"].strip(), "name": name,
                    "area_m2": area, "category": category})
    return out


def tables(words):
    """Границы таблиц на листе.

    На одном листе экспликаций бывает несколько бок о бок: на листе 2 этажа
    объекта Тюменская-5 их четыре. Если этого не учесть, строки разных таблиц
    склеиваются по вертикали и разбор превращается в мусор.

    Каждую таблицу отмечает слово «Наименование» в шапке. Слева таблица кончается
    столбцом номеров соседней, а не серединой между наименованиями: подпись «Номер
    помещения» соседней таблицы — и есть её левый край (#15). Если её нет, остаётся
    прежний отступ: «Кат» справа, иначе начало следующего наименования.

    Соседями считаются только таблицы бок о бок — те, чьи строки идут на той же высоте, что
    строки этой. Таблица целиком под этой (у Revit спецификации этажей идут столбиком,
    Алтуфьевское, #114) её правого края не задаёт. Высота шапок для этого не годится: на листе
    Полярной ДОО экспликация начинается с середины листа рядом с таблицей от самого верха.

    Возвращает (левый край, правый край, высота шапки, начало подписи наименований, конец строк).
    """
    heads = sorted([w for w in words if _name_head(w, words)], key=lambda w: w["bbox"][0])
    # строки таблицы по высоте: от шапки до первого разрыва в полосе номеров слева от подписи
    span = {id(h): (h["bbox"][1], table_end(words, h["bbox"][0] - 0.12, h["bbox"][0], h["bbox"][1], float("inf")))
            for h in heads}

    def beside(a, b):
        (a0, a1), (b0, b1) = span[id(a)], span[id(b)]
        return a0 < b1 and b0 < a1
    if not heads:
        # Разбирать лист целиком без шапки нельзя. Пробовали: приходит проза
        # вида «15 человек, не менее» и «80 приставных мест», потому что номер,
        # слова и число подряд встречаются в обычном тексте сплошь и рядом.
        # Прибавка была 7 помещений против 15 мусорных записей.
        return []
    cats = sorted([w for w in words if w["t"].strip(" .,") in ("Кат", "Кат.")],
                  key=lambda w: w["bbox"][0])
    out = []
    right_of = {}                        # правый край таблицы по её шапке
    for h in heads:
        hx, hy = h["bbox"][0], h["bbox"][1]
        row = [o for o in heads if o is h or beside(o, h)]   # по x, как и heads
        k = row.index(h)
        prev_right = right_of[id(row[k - 1])] if k > 0 else 0.0
        # Колонка с номером помещения стоит левее шапки «Наименование», и отступ
        # бывает заметным: на листе РД ОВ1 номер 012 лежит на 0,077 левее.
        # Ограничиваем слева правой границей предыдущей таблицы, чтобы не залезть в неё.
        own_number = [w for w in words
                      if hx - 0.12 < w["bbox"][0] < hx and abs(w["bbox"][1] - hy) <= HEAD_ROW_DY
                      and _is_head(w, HEAD_NUMBER)]
        left = max(prev_right, min((w["bbox"][0] for w in own_number), default=hx - 0.09) - 0.002)
        nxt_head = row[k + 1] if k + 1 < len(row) else None
        if nxt_head is not None:
            nx, ny = nxt_head["bbox"][0], nxt_head["bbox"][1]
            nxt_number = [w for w in words
                          if nx - 0.12 < w["bbox"][0] < nx and abs(w["bbox"][1] - ny) <= HEAD_ROW_DY
                          and _is_head(w, HEAD_NUMBER)]
            nxt = min((w["bbox"][0] for w in nxt_number), default=nx) - 0.004
        else:
            nxt = 1.0
        right = nxt
        for c in cats:
            if c["bbox"][0] > hx:
                right = min(nxt, c["bbox"][2] + 0.03)
                break
        out.append((left, max(right, hx + 0.01), hy, hx, span[id(h)][1]))
        right_of[id(h)] = right
    return out


def table_end(words, left, name_x, y_head, bottom):
    """Нижний край таблицы: первый разрыв по высоте в столбце номеров, заметно больший шага строк.

    Разрыв ищется только среди строк с номерами: шапка бывает высокой, в две-три строки
    («Номер | помещения», «Площадь, | м2»), и от неё до первой строки таблицы далеко.
    """
    lines = collections.defaultdict(list)
    for w in words:
        if left <= w["bbox"][0] < name_x and y_head + 0.002 < w["bbox"][1] < bottom and w["t"].strip():
            lines[round(w["bbox"][1], 4)].append(w["t"].strip())
    ys = sorted(lines)
    first = next((i for i, y in enumerate(ys) if any(NUM_CANDIDATE.match(t) for t in lines[y])), None)
    if first is None or len(ys) - first < 3:
        return bottom
    ys = ys[first:]
    steps = sorted(b - a for a, b in zip(ys, ys[1:]))
    pitch = steps[len(steps) // 2]
    for prev, y in zip(ys, ys[1:]):
        if y - prev > max(GAP_MIN, GAP_ROWS * pitch):
            return prev + (y - prev) / 2
    return bottom


def parse_page(words, text=""):
    """Помещения со страницы. Пустой список, если это не экспликация."""
    return parse_page_full(words, text)[0]


def parse_page_full(words, text=""):
    """Помещения со страницы и счёт строк: (записи, {rows, parsed, unparsed, shapes}).

    Строкой считается та, что начинается номером из столбца номеров. Если из неё
    не вышло записи — не нашлась площадь или наименование не похоже на наименование —
    она попадает в «неразобранные»: их доля говорит, годится ли разбор для этой
    экспликации, а не выглядит ли пустой результат нормой (#41).
    """
    stats = {"rows": 0, "parsed": 0, "unparsed": 0, "shapes": []}
    if not is_explication(text):
        return [], stats
    seen, out, shapes = {}, [], set()
    tabs = tables(words)
    for left, right, y_head, name_x, _end in tabs:
        # Таблица кончается там, где под ней в той же полосе начинается другая: иначе строки
        # спецификации антресоли достаются спецификации этажа над ней (#114). Уровень — самая
        # верхняя шапка из стоящих бок о бок: номер повторяется на листе, только если таблицы
        # стоят одна под другой («1 Зона мойки» этажа и «1 Тех.помещение» антресоли)
        below = [t for t in tabs if t[2] >= _end and left <= t[3] <= right]
        bottom = table_end(words, left, name_x, y_head, min((t[2] for t in below), default=float("inf")))
        level = min(t[2] for t in tabs if t[2] < _end and y_head < t[4])
        band = [w for w in words
                if left <= w["bbox"][0] <= right and y_head + 0.002 < w["bbox"][1] < bottom - 0.002]
        column = [w["t"].strip() for w in band if w["bbox"][0] < name_x and w["t"].strip()]
        header = " ".join(w["t"] for w in words
                          if left <= w["bbox"][0] < name_x and abs(w["bbox"][1] - y_head) < 0.02)
        title = " ".join(w["t"] for w in sorted(words, key=lambda w: w["bbox"][0])
                         if left - 0.02 <= w["bbox"][0] < right and 0 < y_head - w["bbox"][1] <= TITLE_DY)
        # по заголовку — только при чистой подписи столбца «Номер» или «№»: у распознанных сканов
        # заголовок читается, а строки нет, и в словарь наименований шёл мусор (Тюменская-5, F0203)
        titled = bool(EXPLICATION_TITLE.search(title) and HEADER_NUMBER.search(header))
        labeled = bool(ROOM_HEADER.search(header)) or titled
        table_shapes = column_shapes(column, header, titled)
        shapes |= table_shapes

        foreign = {sh for sh in table_shapes if not is_classic_shape(sh)}
        # литера — номер, только если стоит в столбце цифровых номеров: обломок подписи «М» у начала
        # наименования иначе сдвигал границу столбца, и строки этажа терялись (Алтуфьевское, #114)
        digits = [w for w in band if w["bbox"][0] < name_x and re.search(r"\d", w["t"])
                  and NUM_CANDIDATE.match(w["t"].strip())]
        col = (min(w["bbox"][0] for w in digits) - 0.003, max(w["bbox"][2] for w in digits) + 0.003) if digits else None

        def learned(w, _shapes=foreign, _name_x=name_x, _col=col):
            """Выученная форма номера — только в столбце номеров этой таблицы."""
            t = w["t"].strip()
            if not (w["bbox"][0] < _name_x and shape(t) in _shapes and NUM_CANDIDATE.match(t)):
                return False
            if t.isalpha():
                center = (w["bbox"][0] + w["bbox"][2]) / 2
                return _col is not None and _col[0] <= center <= _col[1]
            return True

        cols = columns(words, y_head, left, right, name_x, learned, bottom)
        for row in rows_from_words(band):
            got = parse_row_columns(row, cols, learned) if cols else parse_row(row, learned)
            # строкой экспликации считается та, у которой номер стоит в столбце номеров:
            # иначе в счёт попадают строки спецификаций, где число значит другое
            numbered = any((learned(w) or NUM_RE.match(w["t"].strip())) and w["bbox"][0] < name_x
                           for w in row if w["t"].strip())
            if numbered:
                stats["rows"] += 1
                stats["parsed" if got else "unparsed"] += 1
            for r in got:
                if (r["number"], level) in seen:
                    continue
                seen[(r["number"], level)] = True
                # заголовок таблицы — по нему сверка экспликаций различает этажи, когда номера
                # на каждом этаже начинаются заново (#114)
                r["table"] = re.sub(r"\s+", " ", title).strip() if EXPLICATION_TITLE.search(title) else None
                # столбец номеров подписан «Номер помещения» или над таблицей заголовок «Экспликация
                # помещений»: это экспликация помещений, а не экспликация зданий на генплане и не
                # спецификация. Сверка наименований (#46) берёт в словарь только такие записи
                r["labeled"] = labeled
                out.append(r)
    stats["shapes"] = sorted(shapes)
    return out, stats


def merge(per_page):
    """Свести помещения со всех страниц объекта в один реестр.

    Одно помещение встречается в экспликациях нескольких стадий. Берём первое
    непустое название и площадь, а страницы накапливаем: они пригодятся как
    доказательство.
    """
    reg = {}
    for file_id, page_no, items in per_page:
        for it in items:
            key = it["number"]
            cur = reg.setdefault(key, {"number": key, "name": None, "area_m2": None,
                                       "category": None, "seen_on": []})
            for f in ("name", "area_m2", "category"):
                if cur[f] is None and it.get(f) is not None:
                    cur[f] = it[f]
            cur["seen_on"].append({"file_id": file_id, "pdf_page_number": page_no})
    return sorted(reg.values(), key=lambda r: (len(r["number"]), r["number"]))
