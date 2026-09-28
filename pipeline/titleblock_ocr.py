"""Основная надпись на чертежах без текстового слоя. Задача #16.

## В чём дело

Разбор основной надписи (`pipeline/titleblock.py`) работает по словам текстового
слоя. На чертежах рабочей документации надпись нарисована векторами, и в слой она
не попадает: у рабочей стадии Тюменской-5 шифр и лист определялись на 6 страницах
из 837. Без листа не работает связка «шифр плюс лист», а без неё номер страницы
рабочей документации приходится вписывать руками.

## Решение

Распознать только угол листа, где стоит надпись, получить слова с координатами
и читать значения по положению. Не сплошная транскрипция моделью, а Tesseract
на вырезе: бесплатно, локально, координаты точные.

**Вырез — в миллиметрах, а не в долях листа.** Основная надпись по ГОСТ Р 21.101
имеет фиксированный размер, 185 на 55 мм, и стоит в правом нижнем углу. Листы же
бывают разного формата: на Тюменской-5 соседние страницы тома — А0 и А1. Вырез
в долях страницы на листе А1 промахивался мимо графы «Лист».

**Значение читается под своей подписью, в миллиметрах.** Прежний разбор брал
«первое число в строке под подписями» в окне высотой в пять процентов листа.
На листе А0 это 59 мм — больше самой надписи, и в окно попадало «ООО «ТСП»»,
распознанное как «000».

**Подписи сравниваются с учётом двойников.** Шрифт надписи стилизован, и Tesseract
читает «Стадия» как «Cmagua», «Лист» как «Jlucm», «flucm» или «Пуст».

**Подпись «Лист» — самая правая, а не самая нижняя.** На последующих листах
(форма 2а) ниже всего стоит шапка таблицы изменений со своим «Лист».

**Второй проход по графе.** Одиночную цифру в пустой графе распознавание всего угла
теряет. Тогда графа вырезается по линиям рамки и читается отдельно, только цифры,
на двух языках. Совпавшие ответы принимаются, одиночный — только с подтверждением
соседа.

**Проверка соседями** (`pipeline/sheet_sequence.py`). Внутри комплекта разность
«страница минус лист» постоянна. Номер, противоречащий соседям с обеих сторон,
снимается; пропуск между листами с одной разностью заполняется.

## Замер на Тюменской-5

5863 страницы, основная надпись найдена на 2700.

| | До задачи | После |
|---|---|---|
| номер листа прочитан | 1406 | 2522 |
| доля страниц с надписью | 52% | 93% |
| с заполнением пропусков по соседям | — | 2560, 95% |
| том ИОС5.4.2, доля всех страниц | 54% | 80% |

Источники прочитанного: текстовый слой 1506 (разбор слоя тоже исправлен, было
1406), угол 822, графа 156, слабое прочтение графы с подтверждением 38.

Точность. Там, где номер есть и в слое, и в распознавании, они совпали на 1098
страницах из 1105. Соседями подтверждено 2387 номеров, 22 снято как противоречащие.
Глазами: все 23 снятых номера из первого прогона — настоящие ошибки, 20 из 20
номеров графы и 20 из 20 слабых прочтений верны. Из 40 случайных страниц без
найденной надписи надпись пропущена на одной.

Цена: 0,64 с процессорного времени на страницу, 5863 страницы за 472 с
в 8 процессов, второй проход по графе — ещё 0,1–0,2 с на пяти процентах страниц.
Денег не стоит: Tesseract локальный. Повторный прогон берёт слова из кеша.

"""
import csv
import io
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline.config import CACHE  # noqa: E402
from pipeline import titleblock  # noqa: E402
from pipeline.titleblock import CODE_RE, STAGE_TOKENS, _clean_code, _is_excluded, _strip_trailing_number  # noqa: E402

MM = 72 / 25.4                 # пунктов в миллиметре
CROP_W_MM, CROP_H_MM = 230, 75  # вырез с запасом вокруг надписи 185 на 55 мм
# Один поток на процесс: углы листов распознаются параллельно по страницам, и Tesseract
# с OpenMP отнимал бы ядра у соседних страниц — в контейнере это стоило 137 секунд
# на лист вместо 3,8 (#52).
TESSERACT_ENV = {**os.environ, "OMP_THREAD_LIMIT": os.environ.get("OMP_THREAD_LIMIT", "1")}

DPI = 300
PSM = "11"                     # разреженный текст: на надписи psm 6 путал «ОВ1» с «ОВА»

# Латинские и цифровые двойники кириллических букв в стилизованном шрифте надписи.
# Используются только для сравнения подписей, значения не переписываются.
_TWINS = str.maketrans({
    "C": "С", "c": "с", "m": "т", "a": "а", "g": "д", "u": "и", "J": "Л", "l": "л",
    "o": "о", "O": "О", "p": "р", "P": "Р", "e": "е", "E": "Е", "x": "х", "y": "у",
    "H": "Н", "K": "К", "M": "М", "T": "Т", "B": "В", "A": "А", "b": "ь", "n": "п",
    "r": "г", "6": "б", "f": "Л",
})


def fold_label(text):
    """Подпись к сравнимому виду: двойники в кириллицу, нижний регистр, без знаков.

    Кроме латинских двойников, стилизованная «Л» читается как кириллическая «П»,
    а «и» как «у»: на листах 3917×2863 тома ВВ подписи вышли «Пуст», «Пустов»,
    «Стадбуя». В словах «Стадия», «Лист», «Листов» нет ни «п», ни «у», поэтому
    замена ничего не путает в сравнении с ними.
    """
    t = (text or "").translate(_TWINS).lower()
    t = t.replace("jl", "л").replace("лл", "л").replace("п", "л").replace("у", "и")
    return re.sub(r"[^а-яё]", "", t)


LABELS = {"стадия": "stage", "лист": "sheet", "листов": "total"}
SHEET_LABEL_MAX_DX_MM = 120


def _distance(a, b):
    """Расстояние Левенштейна для коротких слов."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def label_key(text):
    """Какая это подпись надписи, с допуском в одну букву.

    Стилизованная «я» читается как латинская «a»: «Стадия» распознаётся как
    «Cmagua» и сворачивается в «стадиа». Допуск в одну букву это покрывает,
    а «лист» и «листов» отличаются на две и не путаются.
    """
    folded = fold_label(text)
    if folded in LABELS:
        return LABELS[folded]
    for word, key in LABELS.items():
        if len(folded) >= 4 and _distance(folded, word) <= 1:
            return key
    return None


def _cache_path(sha, page):
    d = os.path.join(CACHE, "tbocr", sha[:2])
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{sha}-{page:05d}.json")


def ocr_corner(page):
    """Слова правого нижнего угла листа: текст и центр в миллиметрах от угла.

    Координаты считаются от правого нижнего угла, x влево и y вверх: в этой системе
    положение граф основной надписи не зависит от формата листа.
    """
    import pymupdf
    r = page.rect
    clip = pymupdf.Rect(max(0, r.width - CROP_W_MM * MM), max(0, r.height - CROP_H_MM * MM),
                        r.width, r.height)
    pix = page.get_pixmap(dpi=DPI, clip=clip)
    with tempfile.TemporaryDirectory() as td:
        png = os.path.join(td, "corner.png")
        pix.save(png)
        try:
            out = subprocess.run(["tesseract", png, "stdout", "-l", "rus+eng",
                                  "--psm", PSM, "tsv"],
                                 capture_output=True, text=True, timeout=120, env=TESSERACT_ENV).stdout
        except Exception:
            return []
    sx, sy = clip.width / pix.width, clip.height / pix.height
    words = []
    for t, left, top, w, h, conf in tsv_words(out):
        cx = clip.x0 + (left + w / 2) * sx
        cy = clip.y0 + (top + h / 2) * sy
        words.append({"t": t, "dx": round((r.width - cx) / MM, 1),
                      "dy": round((r.height - cy) / MM, 1), "conf": round(conf, 1)})
    return words


def tsv_words(out):
    """Слова из TSV Tesseract: (текст, left, top, width, height, conf) в пикселях.

    QUOTE_NONE обязателен. Слово, начинающееся с прямой кавычки («"АРКТОС”»),
    открывает поле в кавычках, и без этого разбор проглатывал весь остальной вывод
    вместе с подписью «Лист» и номером: так на Тюменской-5 терялись 440 страниц.
    """
    words = []
    for row in csv.DictReader(io.StringIO(out), delimiter="\t", quoting=csv.QUOTE_NONE):
        t = (row.get("text") or "").strip()
        if not t:
            continue
        try:
            left, top, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
            conf = float(row.get("conf") or -1)
        except (TypeError, ValueError):
            continue
        words.append((t, left, top, w, h, conf))
    return words


def _below(words, label, max_dx=7.0, min_gap=2.0, max_gap=15.0):
    """Слова, стоящие под подписью в её графе."""
    return [w for w in words
            if abs(w["dx"] - label["dx"]) <= max_dx
            and min_gap <= label["dy"] - w["dy"] <= max_gap]


def find_labels(words):
    """Подписи «Стадия», «Лист», «Листов» в нижней части угла."""
    labels = {}
    for w in words:
        key = label_key(w["t"])
        # Берём самую правую подпись, а не самую нижнюю. «Лист» есть и в заголовке
        # таблицы изменений («Изм. Кол.уч. Лист №док.»), и в графе номера листа.
        # На надписи по форме 2а таблица изменений стоит в самом низу, примерно
        # в 165 мм от правого края, а графа номера листа — в 13 мм. Самая нижняя
        # подпись оказывалась заголовком таблицы, и под ней стояло «№док.», а не номер.
        # Графа номера листа во всех формах правее таблицы изменений.
        if not key or w["dy"] >= 45:
            continue
        # «Лист» дальше 120 мм от края — шапка таблицы изменений: графа номера листа
        # на форме 3 стоит в 25–35 мм от края, на форме 2а — в 10–15 мм
        if key == "sheet" and w["dx"] > SHEET_LABEL_MAX_DX_MM:
            continue
        if key not in labels or w["dx"] < labels[key]["dx"]:
            labels[key] = w
    return labels


_UNDER_RE = re.compile(r"\D{0,2}(\d{1,3}(?:[.,]\d{1,2})?)\D{0,2}")


def _number_under(words, label):
    """Номер листа из графы под подписью, по убыванию уверенности распознавания.

    Дробный номер («6.1» между листами 6 и 7) раньше не подходил под образец, и графа
    уходила на второй проход — распознавание выреза графы, где точка теряется в линиях
    рамки: на Новослободской F0134 листы 6.1 и 6.2 выходили как 61 и 62.
    """
    found = []
    for w in sorted(_below(words, label), key=lambda w: -w["conf"]):
        m = _UNDER_RE.fullmatch(w["t"])
        value = titleblock.sheet_number(m.group(1)) if m else None
        if value is not None:
            found.append(value)
    return titleblock.whole_first(found)


def read(words):
    """Стадия, лист, листов и шифр по словам угла. Возвращает словарь и способ."""
    labels = find_labels(words)
    sheet = total = stage = None
    how = "подписи"
    if "sheet" in labels:
        sheet = _number_under(words, labels["sheet"])
    if "total" in labels:
        total = _number_under(words, labels["total"])
    if "stage" in labels:
        for w in _below(words, labels["stage"]):
            token = w["t"].translate(_TWINS).upper().strip(".|[]()")
            if token in STAGE_TOKENS:
                stage = STAGE_TOKENS[token]
                break
    if not labels:
        how = "нет подписей"

    # шифр: самое длинное совпадение образца среди слов верхней строки надписи
    text = " ".join(w["t"] for w in sorted(words, key=lambda w: (-w["dy"], -w["dx"])))
    code, code_rank = None, -1
    for m in CODE_RE.finditer(text):
        raw = m.group(0).strip(" .,;|")
        # то же приведение, что у разбора по текстовому слою: тире и пробелы вокруг
        # разделителей и номер листа, приклеенный через разделитель с пробелами
        cand = _clean_code(_strip_trailing_number(raw))
        # те же отсевы, что у разбора по текстовому слою: сертификаты, ГОСТ, СП, письма
        if _is_excluded(text, m) or len(cand) < 8 or not re.search(r"[А-ЯA-Z]{2}|-[ПР]-", cand):
            continue
        # сравнение по длине до отрезания номера, как в разборе текстового слоя
        rank = len(_clean_code(raw))
        if code is None or rank > code_rank:
            code, code_rank = cand, rank
    if not labels:
        # Без подписей надписи на странице нет, и образец шифра цепляет постороннее:
        # в смешанном томе ОВ1 «шифр» KR22-031295/1 находился на 418 страницах
        # паспортов оборудования.
        code = None
    # Надпись есть, даже если опознана только шапка таблицы изменений: без этого
    # страницы с нечитаемыми подписями выпадали бы из знаменателя доли покрытия.
    stamped = bool(labels) or any(label_key(w["t"]) for w in words if w["dy"] < 45)
    return {"document_sheet_number": sheet, "sheets_total": total,
            "stage_from_titleblock": stage, "document_code": code,
            "has_titleblock": stamped, "source": "OCR_CORNER"}, how


CELL_DPI = 300
CELL_PAD_PX = 30
# Графа значения под подписью: от линии, отделяющей подпись, до нижней рамки.
# На формах 3 и 2а корпуса значение стоит на 7,5–8 мм ниже центра подписи.
CELL_TOP_MM, CELL_BOTTOM_MM, CELL_HALF_W_MM = 4.5, 12.0, 4.0
# Языки распознавания графы, решение принимает vote(). Подбор на 45 графах тома ОВ1
# с известными номерами, проверка на 300 графах других томов, где номер известен
# из текстового слоя:
#   eng — верно 291 из 300, rus — 281 из 300;
#   согласие обоих — 278 верных и ни одного неверного, на ОВ1 — 33 из 45 без ошибок.
# Растяжение по горизонтали под узкий шрифт проверялось и отвергнуто: при вырезе
# по линиям рамки оно только портит, растяжение 2,2 даёт 194 из 300.
CELL_LANGS = ("rus", "eng")
# Версия второго прохода в кеше: при смене выреза или голосования старые ответы пересчитываются.
CELL_VERSION = 2


def _clean_cell(pix):
    """Серый вырез графы без линий рамки и с белыми полями.

    Строка или столбец, тёмные больше чем на 60 и 80 процентов, — это линия рамки,
    а не цифра: штрих цифры занимает меньше половины ширины выреза и меньше трёх
    четвертей высоты. Прилегающая линия сбивает распознавание: «3» у нижней рамки
    читалась как «5».
    """
    import pymupdf
    w, h = pix.width, pix.height
    buf = bytearray(pix.samples)
    for y in range(h):
        if sum(1 for v in buf[y * w:(y + 1) * w] if v < 128) > 0.6 * w:
            buf[y * w:(y + 1) * w] = b"\xff" * w
    for x in range(w):
        if sum(1 for v in buf[x::w] if v < 128) > 0.8 * h:
            for y in range(h):
                buf[y * w + x] = 255
    pw, ph = w + 2 * CELL_PAD_PX, h + 2 * CELL_PAD_PX
    out = bytearray(b"\xff" * (pw * ph))
    for y in range(h):
        start = (y + CELL_PAD_PX) * pw + CELL_PAD_PX
        out[start:start + w] = buf[y * w:(y + 1) * w]
    return pymupdf.Pixmap(pymupdf.csGRAY, pw, ph, bytes(out), False)


def vote(answers):
    """Номер листа по ответам языков: (номер, сильное ли прочтение) или (None, False).

    Сильное — все ответы непустые и совпали: на отложенной выборке 278 из 300 верных
    и ни одного неверного. Слабое — ответил один язык, другой промолчал: так бывает
    с одиночной цифрой, и из 13 таких ответов верны 12. Слабое прочтение само по себе
    не принимается, его должен подтвердить сосед (`pipeline.sheet_sequence`).
    Разные ответы — отказ: при большинстве «два из трёх» графа «57» на странице 105
    тома ОВ1 принималась как «7».
    """
    got = [a for a in answers if a]
    if not got or len(set(got)) != 1 or len(got[0]) > 3 or int(got[0]) == 0:
        return None, False
    return int(got[0]), len(got) == len(answers)


def _dark_runs(flags):
    """Отрезки подряд идущих True: [(начало, конец), ...]."""
    runs, start = [], None
    for i, f in enumerate(list(flags) + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            runs.append((start, i))
            start = None
    return runs


def value_row(page, label):
    """Границы строки значения под подписью, в миллиметрах от нижнего края листа.

    Высота строки у надписей корпуса разная: 8 мм на формах 3 и 2а тома ОВ1 и 5 мм
    на титульной надписи тома СПОЗУ. Фиксированный вырез на 4,5–12 мм ниже подписи
    захватывал на пятимиллиметровой строке только низ единицы, и все варианты
    распознавания дружно читали её как «7». Поэтому строка ищется по линиям рамки:
    первая горизонтальная линия ниже подписи — верх строки, следующая — низ.
    Если линий не видно, остаётся прежний вырез.
    """
    import pymupdf
    r = page.rect
    top_mm, bottom_mm = label["dy"] - 1.5, max(label["dy"] - 20.0, 0.0)
    clip = pymupdf.Rect(r.width - (label["dx"] + CELL_HALF_W_MM) * MM, r.height - top_mm * MM,
                        r.width - (label["dx"] - CELL_HALF_W_MM) * MM, r.height - bottom_mm * MM)
    pix = page.get_pixmap(dpi=CELL_DPI, clip=clip, colorspace=pymupdf.csGRAY)
    w, h = pix.width, pix.height
    buf = pix.samples
    flags = [sum(1 for v in buf[y * w:(y + 1) * w] if v < 128) > 0.6 * w for y in range(h)]
    px_mm = (top_mm - bottom_mm) / max(h, 1)
    lines = [(a * px_mm, b * px_mm) for a, b in _dark_runs(flags)]
    if len(lines) >= 2 and lines[1][0] - lines[0][1] >= 2.5:
        return top_mm - lines[0][1], top_mm - lines[1][0]
    if len(lines) == 1:
        return top_mm - lines[0][1], max(top_mm - lines[0][1] - 10.0, 0.0)
    return label["dy"] - CELL_TOP_MM, label["dy"] - CELL_BOTTOM_MM


def cell_answers(page, label, langs=CELL_LANGS):
    """Ответы распознавания графы значения на каждом языке, только цифры."""
    import pymupdf
    r = page.rect
    row_top, row_bottom = value_row(page, label)
    clip = pymupdf.Rect(r.width - (label["dx"] + CELL_HALF_W_MM) * MM, r.height - row_top * MM,
                        r.width - (label["dx"] - CELL_HALF_W_MM) * MM, r.height - row_bottom * MM)
    answers = []
    with tempfile.TemporaryDirectory() as td:
        png = os.path.join(td, "cell.png")
        _clean_cell(page.get_pixmap(dpi=CELL_DPI, clip=clip, colorspace=pymupdf.csGRAY)).save(png)
        for lang in langs:
            try:
                out = subprocess.run(["tesseract", png, "stdout", "--psm", "7", "-l", lang,
                                      "-c", "tessedit_char_whitelist=0123456789"],
                                     capture_output=True, text=True, timeout=60, env=TESSERACT_ENV).stdout
            except Exception:
                out = ""
            answers.append(re.sub(r"\D", "", out))
    return answers


# Документ, открытый в этом процессе. Том ИД бывает одним PDF на тысячи страниц сканов
# и сотни мегабайт: открытие такого файла стоит секунды — дольше распознавания угла, и
# открывался он заново на каждую страницу. Страницы раздаются процессам пула по порядку,
# подряд по документу (`cli.cmd_sheets`), поэтому одного открытого документа на процесс
# хватает, чтобы открывать файл раз на процесс, а не раз на страницу (#113, Р-90). Угол
# читается только в процессах пула, без потоков: документ PyMuPDF не потокобезопасен.
#
# Склад ресурсов MuPDF перед каждой отрисовкой очищается. Открытый документ держит в нём
# отрисованное с прежних страниц, и угол следующей выходил чуть другим: у трёх страниц
# из семи тысяч разошлись уверенности и пара букв в словах вне граф. С очисткой каждая
# страница рисуется как из только что открытого файла — ответы те же, что до #113.
_opened = {"key": None, "pdf": None}


def _release():
    pdf, _opened["pdf"], _opened["key"] = _opened["pdf"], None, None
    if pdf is not None:
        try:
            pdf.close()
        except Exception:
            pass


def _open_page(doc_path, page_no):
    """Страница документа; документ остаётся открытым до страницы другого файла."""
    import pymupdf
    try:
        pymupdf.TOOLS.mupdf_display_errors(False)
    except Exception:
        pass
    st = os.stat(doc_path)
    key = (doc_path, st.st_size, st.st_mtime_ns)
    if _opened["key"] != key:
        _release()
        _opened["pdf"] = pymupdf.open(doc_path)
        _opened["key"] = key
    pymupdf.TOOLS.store_shrink(100)
    return _opened["pdf"][page_no - 1]


def page_words(doc_path, sha, page_no, use_cache=True):
    """Распознанный угол листа с кешем по SHA-256 и странице.

    В кеше лежат слова, а не готовый разбор: правило чтения граф меняется,
    а распознавание — самая дорогая часть, около секунды на страницу.
    Возвращает словарь с ключом words или None, если страницу открыть не удалось.
    """
    cache = _cache_path(sha, page_no)
    if use_cache and os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "words" in data:
            return data
    try:
        data = {"words": ocr_corner(_open_page(doc_path, page_no))}
    except Exception:
        return None
    _save(cache, data)
    return data


def _save(cache, data):
    tmp = cache + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, cache)


def parse_page(doc_path, sha, page_no, use_cache=True):
    """Основная надпись страницы по распознаванию угла."""
    data = page_words(doc_path, sha, page_no, use_cache)
    if data is None:
        return {"document_sheet_number": None, "error": "не удалось распознать",
                "source": "OCR_CORNER"}
    result, how = read(data["words"])
    labels = find_labels(data["words"])
    if result["document_sheet_number"] is None and "sheet" in labels:
        label = labels["sheet"]
        key = f'{label["dx"]}:{label["dy"]}'
        cell = data.get("cell") if use_cache else None
        if not cell or cell.get("label") != key or cell.get("version") != CELL_VERSION:
            try:
                answers = cell_answers(_open_page(doc_path, page_no), label)
            except Exception:
                answers = []
            # в кеше ответы, а не решение: правило голосования можно менять без распознавания
            cell = {"label": key, "answers": answers, "version": CELL_VERSION}
            data["cell"] = cell
            _save(_cache_path(sha, page_no), data)
        value, strong = vote(cell.get("answers") or [])
        if value and strong:
            result["document_sheet_number"] = value
            how = "подписи, графа отдельно"
        elif value:
            result["sheet_candidate"] = value
    result["how"] = how
    return result
