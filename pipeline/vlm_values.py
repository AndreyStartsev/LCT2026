"""Прицельный вопрос мультимодальной модели по чертежу. Задача #98.

Тридцать четыре параметра из нереализованных живут в рабочей стадии только в графике:
размерные линии, подписи у проёмов, узлы. Поле `vlm_prompt` в схеме предварительного правила
до сих пор никем не исполнялось — конвейер читал только текст страницы. Здесь этот проход есть:
правило объявляет вопрос, проход отбирает листы, спрашивает модель и складывает ответы в файл,
а правило берёт значения из файла — в прогоне правил модель не вызывается вовсе.

## Чему нельзя верить без проверки

Замер 24.09 на планах и спецификациях Алтуфьевского и Речникова показал две вещи.

**Модель читает то, что на листе есть.** На листе спецификаций заполнения проёмов
(Алтуфьевское, L0058 стр. 18) она вернула Д-6…Д-9 EI-30, Вр1–Вр3 EI-15, Вр4 EI-30 — всё
совпало с текстовым слоем до одного значения.

**И придумывает то, чего на листе нет.** У тех же восьми записей она заполнила поле «место»
(коридор, венткамера, лифтовой холл, кладовая), хотя в таблице спецификации графы места нет
вовсе. Ни одно из восьми мест проверку текстом не прошло.

Отсюда правило прохода: **ответ принимается только подтверждённым**. Если у страницы есть свой
текст (слой или распознавание), значение должно в нём найтись — иначе это выдумка, и она
отбрасывается со счётчиком. Если текста нет вовсе (скан), значение берётся, но помечается
прочитанным машиной: по Р-40 и #48 такое значение требует подтверждения инспектором и сверки
глазами по изображению листа.

**Разрешение решает.** На листе 1189 мм при 5000 px (107 dpi) модель трижды из четырёх
ответила «ничего не нашёл», а на листе 420 мм при 2481 px (150 dpi) прочитала таблицу целиком.
Предел растра здесь считается от размера листа, как в Р-60 и Р-70, с целевыми 150 dpi.
"""
import hashlib
import json
import os
import re
import threading
import time

from pipeline import encoding, reading, units
from pipeline.config import OUT

TARGET_DPI = int(os.environ.get("PIPELINE_VLM_DPI") or 150)
MAX_PX = int(os.environ.get("PIPELINE_VLM_MAX_PX") or 5000)
CALLS_PER_OBJECT = int(os.environ.get("PIPELINE_VLM_LIMIT") or 40)
# Сколько вопросов к модели держать одновременно. Своя модель на видеокарте отвечает на
# десятки запросов разом (vLLM, `LLM_MAX_NUM_SEQS`), а по одному проход ждёт каждый ответ
# отдельно. По умолчанию один — как было; ответы от числа потоков не зависят
WORKERS = max(1, int(os.environ.get("PIPELINE_VLM_WORKERS") or 1))
# MuPDF один на процесс (#113): открывать, рисовать и закрывать PDF из разных потоков можно
# только по очереди. Под замком только работа с PDF, вопрос модели идёт без него
PDF_LOCK = threading.Lock()
# Модель под прод — Р-55; здесь то же имя, что и у чтения страниц
MODEL = os.environ.get("PIPELINE_VLM_MODEL") or "qwen/qwen3.6-27b"
NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
# Виды правил, чьи вопросы задаёт проход: число с чертежа (#98) и двери с направлением открывания
# (AR-043, #191). У второго ответ — не числа, а перечень дверей (`vlm.answer: "doors"`)
VLM_KINDS = ("vlm_value", "door_opening")


def prompt_digest(prompt):
    return hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()[:10]


def cache_kind(code, prompt):
    """Вид записи кеша: свой у каждого правила и каждой редакции вопроса."""
    return f"vlm-{code}-{prompt_digest(prompt)}"


# Где на листе ищется его название: начало текста и хвост. Штамп с названием листа («План 3, 7,
# 11 этажа») часто стоит в конце текстового слоя — у Речникова на 6300-м знаке, и отбор по
# первым 4000 знакам не находил 25 планов РД из 42 (#135, черновики правил)
HEAD_CHARS, TAIL_CHARS = 4000, 3000


def _sheet_words(text):
    """Начало и хвост текста листа, с починенной кодировкой: у Полярной 16 795 листов АР и КР РД
    записаны в cp1251, прочитанной как latin-1, и выражение отбора их не видело."""
    text = " ".join((text or "").split())
    if encoding.looks_broken(text[:HEAD_CHARS]):
        text = encoding.repair(text)[0]
    return text[:HEAD_CHARS] + " " + text[-TAIL_CHARS:] if len(text) > HEAD_CHARS + TAIL_CHARS else text


def sheets_for(rule, pages, limit=None, skip=()):
    """Листы, на которых искать значение: [(file_id, страница, почему)].

    Отбор идёт по постраничному индексу, а не подряд: у объекта 38 тысяч страниц, а вопрос
    имеет смысл на чертежах нужного раздела. Условия правила — раздел, вид страницы, слово
    в тексте листа и наименьший размер листа.
    """
    want = rule.get("vlm") or {}
    sections = {s.upper() for s in want.get("sections") or []}
    kinds = set(want.get("kinds") or ("DRAWING", "SCAN_NO_TEXT"))
    stages = want.get("stage") or "RD"
    stages = {stages} if isinstance(stages, str) else set(stages)
    if "RD" in stages:
        stages.add("RD_ID_MIXED")        # смешанная папка «РД и ИД»: у Тюменской-5 так лежат все тома РД ОВ
    min_mm = float(want.get("min_mm") or 0)
    needle = re.compile(want["sheet_text"], re.I) if want.get("sheet_text") else None
    avoid = re.compile(want.get("avoid_text") or r"ведомость\s+(?:рабочих\s+чертежей|ссылочных)", re.I)
    out, taken = [], {}
    for page in pages:
        if page.get("stage") not in stages or page.get("kind") not in kinds:
            continue
        if page.get("file_id") in skip:
            continue                      # заменённая редакция: спрашивать надо действующую
        if sections and (page.get("section") or "").upper() not in sections:
            continue
        long_mm = max(page.get("width_pt") or 0, page.get("height_pt") or 0) / 72 * 25.4
        if long_mm < min_mm:
            continue
        words = _sheet_words(page.get("text"))
        if avoid.search(words[:2000]):
            continue                      # лист-ведомость комплекта: там только названия листов
        if needle and not needle.search(words):
            continue
        # потолок листов — на каждую стадию: иначе бюджет уходит на проектные листы,
        # а рабочую сторону сравнения спросить уже не на что
        stage_now = page.get("stage")
        if limit and taken.get(stage_now, 0) >= limit:
            continue
        taken[stage_now] = taken.get(stage_now, 0) + 1
        out.append((page["file_id"], page["pdf_page_number"],
                    f"{stage_now}, {long_mm:.0f} мм, {page.get('kind')}"))
    return out


# «2 100», «1 730» — разряды через пробел: на листах вертикального транспорта Полярной 16 размеры
# шахт записаны так, и значение ответа «2100» на листе не находилось
_GROUPED = re.compile(r"(?<![\d.,])(\d{1,3}) (\d{3})(?![\d])")


def confirmed_values(values, page_text, near=None, form=None):
    """Какие значения ответа подтверждены текстом страницы: (подтверждённые, чем).

    Ответ-набор сверяется по каждому значению: раньше одно подтверждённое число пропускало весь
    ответ, и у ДОО (DOO25-000887, стр. 7) в принятом наборе «1800, 520, 999» оказалось 999,
    которого на листе нет. У страницы без своего текста проверять нечем — значения берутся все
    с пометкой «none», как и прежде (Р-40).
    """
    text = " ".join((page_text or "").split())
    if not text:
        return list(values), "none"
    grouped = _GROUPED.sub(r"\1\2", text)
    got, how = [], None
    for value in values:
        ok, why = confirmed([value], text, near, form)
        if not ok and grouped != text:
            ok, why = confirmed([value], grouped, near, form)
        if ok:
            got.append(value)
            how = how or why
    return got, how or "no"


def in_range(values, want):
    """Значения в правдоподобных пределах параметра: `vlm.value_range` [от, до] в единице правила.

    Модель на плане отвечает всеми размерами, какие видит: длинами коридоров (6–27 м) вместо
    ширины, номерами осей из пояснения («оси 1–17») вместо шага. Текст листа такие числа
    подтверждает — они на листе есть, — поэтому отсекаются они пределами самого параметра
    (Новослободская, черновики правил, #95). Без пределов значения не отсекаются.
    """
    lo, hi = ((want or {}).get("value_range") or [None, None])[:2]
    return [v for v in values if (lo is None or v >= lo) and (hi is None or v <= hi)]


LOOPED = "ответ зациклился"         # так read_model называет зациклившийся ответ


def failed(answer):
    """Вызов не состоялся: ошибка без текста. Зациклившийся ответ — не сбой, а ответ листа:
    повторный вопрос даст тот же повтор, поэтому он кешируется, как и прежде."""
    return bool(answer.get("error")) and not answer.get("text") \
        and not answer.get("looped") and answer.get("error") != LOOPED


def cached_answer(sha, page_no, code, prompt):
    """Ответ из кеша или None. Несостоявшийся вызов ответом не считается: так его писал кеш
    до 25.09, и лист молчал бы до `--fresh`."""
    got = reading.cache_get(sha, page_no, cache_kind(code, prompt))
    return got if got and not failed(got) else None


def ask(doc, page_no, sha, code, prompt, model=None, work_dir=None, use_cache=True):
    """Спросить модель про страницу. Ответ кешируется по «sha + страница + вопрос»."""
    kind = cache_kind(code, prompt)
    if use_cache:
        got = cached_answer(sha, page_no, code, prompt)
        if got:
            return {**got, "cached": True}
    work_dir = work_dir or reading.RENDER_DIR
    # картинка своя у вопроса: два правила могут спрашивать один лист одновременно
    png = os.path.join(work_dir, f"vlm-{sha[:12]}-{page_no:05d}-{kind[4:]}.png")
    with PDF_LOCK:
        rect = doc[page_no - 1].rect      # страница отпускается здесь же, под замком
        long_pt = max(rect.width, rect.height) or 1
        max_px = min(MAX_PX, max(1600, round(long_pt / 72 * TARGET_DPI)))
        reading.render(doc, page_no, png, dpi=300, max_px=max_px)
    t0 = time.time()
    answer = reading.read_model(png, model=model or MODEL, prompt=prompt)
    reading.drop_render(png)
    out = {"text": answer.get("text") or "", "error": answer.get("error"),
           "model": answer.get("model"), "cost_usd": answer.get("cost_usd") or 0.0,
           "ms": answer.get("ms") or int((time.time() - t0) * 1000), "max_px": max_px,
           "version": reading.READ_VERSION}
    if answer.get("looped"):
        out["looped"] = True
    # Несостоявшийся вызов в кеш не идёт: модель не ответила (сеть, 5xx, сервер ещё поднимается) —
    # это не ответ листа, и с кешем лист молчал бы до `--fresh`. Следующий проход спросит снова
    if not failed(out):
        reading.cache_put(sha, page_no, kind, out)
    return {**out, "cached": False}


def parse_numbers(text, unit=None):
    """Числа из ответа модели, приведённые к единице правила. Пустой список — ответ без чисел."""
    if not text:
        return []
    body = text
    try:
        data = json.loads(text[text.index("{"):text.rindex("}") + 1])
        if isinstance(data, dict):
            found = data.get("values")
            if isinstance(found, list):
                body = " ".join(str(x) for x in found)
                unit_said = data.get("unit")
                return _to_unit(body, unit_said, unit)
    except (ValueError, KeyError):
        pass
    return _to_unit(body, None, unit)


def _to_unit(body, unit_said, want):
    out = []
    for m in NUMBER_RE.finditer(body):
        value = float(m.group(0).replace(",", "."))
        if want:
            value = units.convert(value, unit_said or want, want)
            if value is None:
                continue
        out.append(value)
    return out


CONFIRM_WINDOW = 120


def confirmed(values, page_text, near=None, form=None):
    """Есть ли значения ответа в собственном тексте страницы.

    Возвращает (подтверждено, чем): «layer» — текст страницы есть и значения в нём нашлись,
    «near» — значение нашлось рядом с предметом вопроса, «none» — своего текста у страницы
    нет и сверять нечем, «no» — текст есть, значений в нём нет, «нет предмета» — на листе
    нет и слова о предмете, так что ответ сверять нечем.

    `near` — выражение предмета вопроса (`vlm.confirm_near`). Без него проверка отвечает
    только на вопрос «есть ли такое число на листе», и для размера в миллиметрах это почти
    ничего не значит: на плане Алтуфьевского (L0010 стр. 20) модель ответила «900 мм»,
    хотя подписано «Защитное ограждение 1200», и 900 на листе нашлось — это другой размер.
    Поэтому у параметров-размеров проверка требует, чтобы число стояло рядом со словом
    о предмете, а лист, где предмет не назван, ответом не подтверждается вовсе (#98).

    `form` — как значение написано на листе (`vlm.confirm_form`, `{v}` вместо числа).
    Соседство для доли слабо: на листе общих данных ВК номер пункта «2.1. Монтаж системы
    канализации» стоял рядом со знаком процента, и ответ «2,1 %» проверку соседства проходил
    (замер 24.09 по изображениям листов). Если правило назвало форму, значение должно найтись
    именно в ней — «2,1%» или «i=0,021», а не просто «2.1» где-то на листе.
    """
    text = " ".join((page_text or "").split())
    if not text:
        return True, "none"
    flat = encoding.repair(text)[0].replace(",", ".")
    if form:
        ranged = _RANGE.sub(r"\1\3 \2\3", flat)
        for value in values:
            for pat in _forms(form, value):
                if re.search(pat, flat, re.I) or (ranged != flat and re.search(pat, ranged, re.I)):
                    return True, "форма"
        return False, "не в своей форме"
    spots = None
    if near:
        spots = [m.start() for m in re.finditer(near, flat, re.I)]
        if not spots:
            return False, "нет предмета"
    for value in values:
        for shown in (f"{value:g}", f"{value:g}".replace(".", ",")):
            start = 0
            while True:
                at = flat.find(shown, start)
                if at < 0:
                    break
                if spots is None:
                    return True, "layer"
                if any(abs(at - s) <= CONFIRM_WINDOW for s in spots):
                    return True, "near"
                start = at + 1
    return False, "no"


def number_pattern(value):
    """Выражение для числа так, как его пишут на листе.

    Разделитель дроби любой, лишние нули в конце не мешают: уклон на кровле бывает подписан
    «1.50%», а модель отвечает «1,5». Целое число пишут и «2», и «2,0».
    """
    shown = f"{value:g}"
    if "." in shown:
        whole, frac = shown.split(".")
        return re.escape(whole) + "[.,]" + re.escape(frac) + "0*"
    return re.escape(shown) + "(?:[.,]0+)?"


# Диапазон со знаком только у верхней границы: «1.4-1.8%», «0,9–1,2 %». Нижняя граница — тоже
# подписанное значение, но знак у неё не повторён, и форма «{v}%» её не находила: на плане кровли
# Новослободской (F0106 стр. 131) из «1.4-1.8% 0.9-1.2% 4.5-4.9%» терялись 0,9, 1,4 и 4,5 (Р-141).
# Для сверки такой диапазон читается как «1.4% 1.8%»; запятые к этому месту уже стали точками
_RANGE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)\s*(%|‰)")


def _forms(form, value):
    """Написания значения, которые ищет `vlm.confirm_form`.

    `{v}` — само значение, `{f}` — оно же долей: уклон на листе подписан и «2,1%», и
    «i=0,021», а модель по вопросу приводит ответ к процентам.
    """
    return [form.replace("{v}", number_pattern(value)).replace("{f}", number_pattern(value / 100))]


def path_for(object_id, out=OUT, provisional=False):
    """Файл ответов прохода. У черновиков правил (#95) свой файл: их ответы не смешиваются
    с прод-файлом, который лежит в build/ и входит в отпечаток кеша прод-правил."""
    return os.path.join(out, object_id, "vlm_provisional.jsonl" if provisional else "vlm_values.jsonl")


def load(object_id, code=None, out=OUT, provisional=False):
    """Значения, прочитанные проходом. Пустой список, если прохода не было."""
    path = path_for(object_id, out, provisional)
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            if code and row.get("parameter_code") != code:
                continue
            rows.append(row)
    return rows


# ---------- двери и направление открывания: AR-043 (#191) ----------
#
# Ответ — перечень дверей: {"doors": [{"mark", "room", "opens", "exit"}]}. Направление текстом не
# проверить никак, поэтому дверь принимается, только если её марка или помещение есть в тексте
# листа: так отсекаются двери, которые модель дописала (замер #98: «место» у восьми записей из восьми
# на листе не нашлось). Лист без своего текста (скан) — двери берутся с пометкой «none», как и числа.

OPENS = (("против хода", r"против"), ("по ходу", r"по\s*ход|наружу|по\s+направлени"), ("не видно", r""))


def _opens(raw):
    raw = str(raw or "").lower()
    return next(name for name, rx in OPENS if not rx or re.search(rx, raw))


# Подпись огнестойкости у двери — не её марка: на плане ПД Полярной 16 модель вернула «EI30» маркой
# четырёх дверей, и текст листа это «подтвердил» — подпись там есть. Марка отбрасывается, только если
# она целиком — предел огнестойкости («EI30», «EI 60», «EIS30», «E30», «REI120»); «ДПМ EI30» и «Д-1» не
# трогаются. Кириллические «Е», «І», «Ѕ» — те же буквы
FIRE_RATING = re.compile(r"^R?E(?:I[SW]?|W)?\s*[-–]?\s*\d{2,3}$", re.I)
_RATING_LETTERS = str.maketrans("ЕеІіЅѕ", "EeIiSs")


def _mark(raw):
    mark = " ".join(str(raw or "").split())
    return "" if FIRE_RATING.match(mark.translate(_RATING_LETTERS)) else mark


def parse_doors(text):
    """Двери из ответа модели: [{mark, room, opens, exit}]. Ответ без JSON — пустой список.

    Дверь без марки и без помещения отбрасывается: сравнивать её не с чем. Подпись огнестойкости
    вместо марки (`FIRE_RATING`) маркой не считается."""
    try:
        data = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except (ValueError, TypeError, AttributeError):
        return []
    out = []
    for d in (data.get("doors") if isinstance(data, dict) else None) or []:
        if not isinstance(d, dict):
            continue
        mark, room = _mark(d.get("mark")), str(d.get("room") or "").strip()
        if mark or room:
            out.append({"mark": mark, "room": room, "opens": _opens(d.get("opens")), "exit": bool(d.get("exit"))})
    return out


def _token_rx(value):
    """Марка или номер так, как их пишут на листе: «Д-1» — и «Д1», и «Д 1», но не «Д10» и не «ДД1»."""
    parts = re.findall(r"[А-ЯЁA-Zа-яёa-z]+|\d+(?:[.,]\d+)?", value)
    if not parts:
        return None
    body = r"[\s\-‑–.]?".join(re.escape(p.replace(",", ".")).replace(r"\.", "[.,]") for p in parts)
    return re.compile(r"(?<![А-ЯЁA-Zа-яёa-z0-9])" + body + r"(?![0-9])", re.I)


def door_on_sheet(door, text):
    """Есть ли дверь на листе: её марка или номер помещения (иначе название помещения) — в тексте."""
    if door.get("mark"):
        rx = _token_rx(door["mark"])
        if rx and rx.search(text):
            return True
    room = door.get("room") or ""
    # номер помещения с буквами при нём: «Л1», «1.05», «105»; одна цифра есть на любом листе
    number = re.search(r"[А-ЯЁA-Za-zа-яё]*\d+(?:[.,]\d+)?", room)
    if number and len(re.sub(r"\W", "", number.group(0))) >= 2:
        rx = _token_rx(number.group(0))
        return bool(rx and rx.search(text))
    words = [w for w in re.findall(r"[А-ЯЁа-яё]{4,}", room)]
    return bool(words) and all(re.search(re.escape(w[:6]), text, re.I) for w in words[:2])


def confirmed_doors(doors, page_text):
    """Какие двери ответа подтверждены текстом листа: (подтверждённые, чем)."""
    text = " ".join((page_text or "").split())
    if not text:
        return list(doors), "none"
    text = encoding.repair(text)[0]
    got = [d for d in doors if door_on_sheet(d, text)]
    return got, "layer" if got else "no"
