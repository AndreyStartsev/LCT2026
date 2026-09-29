"""Конвейер чтения страницы.

Выбран по результатам стенда, обоснование в `docs/ocr-pipeline-report.md`:

    текстовый слой и Tesseract вместе на всех страницах,
    мультимодальная модель дополнительно на сканах и чертежах

95,3 процента найденных значений, 3,5 секунды на страницу, около четырёх долларов
на весь корпус организатора.

Порядок обработки:

1. Тип страницы определяется по плотности текстового слоя и соотношению сторон.
   Без модели, мгновенно.
2. Текстовый слой и Tesseract читают страницу и склеиваются. На чертежах часть
   надписи нарисована векторами и в слой не попадает, зато читается с растра;
   мелкие подписи наоборот есть в слое и теряются распознаванием.
3. На сканах и чертежах тот же лист уходит в модель, ответ добавляется к тексту.
4. Результат кладётся в кеш по SHA-256 файла и номеру страницы: повторный прогон
   бесплатен.

Слова с координатами возвращаются отдельно: линейный текст на чертеже перемешан
по порядку чтения, и привязка элемента к помещению по нему невозможна.
"""
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import encoding
from pipeline.config import CACHE

TESSERACT_CMD = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract") or (
    r"C:\Users\user49\tesseract\tesseract.exe"
    if os.path.exists(r"C:\Users\user49\tesseract\tesseract.exe")
    else "tesseract"
)

# ниже этого числа слов страница считается сканом
MIN_WORDS_FOR_TEXT_LAYER = 40
# длинная сторона листа А3 и крупнее в пунктах (А4 — 842 pt, А3 — 1191 pt)
MIN_SHEET_PT = 1000
# Модель включается только там, где на стенде она реально добавляла значения:
# сканы без текстового слоя (32 из 49 без неё против 44 из 49 с ней) и чертежи
# (13 из 14 против 14 из 14). На разреженных сканах обе колонки дали 5 из 5,
# то есть модель не добавила ничего, а стоит там дорого: это крупные листы.
# Оговорка: на разреженных сканах эталон тонкий, всего пять значений.
MODEL_KINDS = {"SCAN_NO_TEXT", "DRAWING"}
# Из них модель читает только страницу, чей текст возьмут правила (27.09): скан без текста или чертёж
# с тонким слоем — меньше MIN_WORDS_FOR_TEXT_LAYER слов, как у `classify` и `matrix_rules._may_be_scan`.
# Это текст кривыми или растр со штампом. У чертежа со слоем правила читают сам слой, и полное
# переписывание моделью им не нужно: на Полярной 16 3922 векторных чертежа со слоем стоили $29 из $30
# и не изменили ни одного решения. Значения с чертежей правилам даёт прицельный проход (`vlm_values`).
# Порог не настраивается: прочитать моделью все страницы нельзя ни выбором при загрузке, ни настройкой
MODEL_LAYER_WORDS = MIN_WORDS_FOR_TEXT_LAYER
# распознавание включается только там, где текстового слоя нет или он беден.
# На стенде Tesseract по чертежам не дал ни одного значения сверх текстового слоя
# (13 из 14 у обоих), а на листе А1 при 300 dpi съедает до тридцати секунд.
OCR_KINDS = {"SCAN_NO_TEXT", "SCAN_SPARSE"}
# потолок длинной стороны растра для распознавания: без него лист А0 даёт
# картинку на десять тысяч пикселей и Tesseract встаёт
OCR_MAX_PX = 3500
# Плоский потолок 3500 px — это 299 dpi на A4, 150 dpi на A2 и всего 76 dpi на листе
# 1165 мм. Замер 24.09 на тринадцати сканах без слоя малого стенда (85 сверенных значений)
# показал то же, что и у модели (Р-60): поднимать предел всем нельзя.
#
#   предел      точных значений   Character Accuracy   секунд
#   3500 px         43 из 85            0,688            196
#   5000 px         39 из 85            0,686            220
#   7000 px         39 из 85            0,700            243
#
# На листах А4 от разрешения становится хуже: у скана Новослободской F0107 точных значений
# 4 из 5 против 3 из 5, у акта Октябрьской F0159 — 6 из 11 против 4 из 11. Выигрыш только
# там, где плоский предел даёт совсем мало dpi: на скане 1783 мм Character Accuracy
# 0,487 при 3500 px против 0,641 при 7000 px, плюс три секунды.
#
# Поэтому предел поднимается только до нижней границы разрешения и только тем листам,
# которым плоского потолка не хватает: таких страниц в корпусе 120 из 71 636.
OCR_MIN_DPI = int(os.environ.get("PIPELINE_OCR_MIN_DPI") or 100)
OCR_BIG_PX = int(os.environ.get("PIPELINE_OCR_MAX_PX") or 7000)


def ocr_max_px(width_pt=None, height_pt=None):
    """Сколько пикселей по длинной стороне дать распознаванию листу такого размера.

    Размер берётся из уже прочитанного слоя, а не из документа: страницу читают и там,
    где документа под рукой нет. Без размера остаётся плоский потолок.
    """
    long_pt = max(width_pt or 0, height_pt or 0)
    if not long_pt:
        return OCR_MAX_PX
    want = round(long_pt / 72 * OCR_MIN_DPI)
    return min(OCR_BIG_PX, max(OCR_MAX_PX, want))
# Предел картинки для модели. Плоские 2000 пикселей по длинной стороне — это 170 dpi
# по бумаге на A4 и всего 43 dpi на A0, и мелкий текст спецификации при таком уменьшении
# нечитаем: на листе A0 без текстового слоя qwen3.6-27b возвращала 196 символов — только
# заголовки разделов, два прогона подряд, — а при 4000 px прочитала таблицу материалов
# целиком (#105, #86).
#
# Поднимать предел всем крупным листам нельзя: замер 23.09 на трёх крупных **векторных**
# чертежах объектов разработки показал обратное. Доля числовых значений текстового слоя,
# которые модель находит сама:
#
#   Новослободская F0137 стр. 13, 1260 мм    65 % при 2000 px, 60 % при 4000, 50 % при 6000
#   Новослободская F0105 стр. 24,  841 мм    61 % при 2000 px, 32 % при 4000, 29 % при 6000
#   Речников F0253 стр. 47,       1189 мм    зацикливание при 2000 и 6000, 3 % при 4000
#
# На большой картинке модель уходит в графику и переписывает меньше. Но у такой страницы
# есть текстовый слой, и значения берутся из него — модель там только дополняет. Поэтому
# предел от размера листа поднимается **только там, где модель единственный источник**:
# на сканах без текстового слоя.
MODEL_TARGET_DPI = int(os.environ.get("PIPELINE_MODEL_DPI") or 170)
MODEL_MAX_PX = int(os.environ.get("PIPELINE_MODEL_MAX_PX") or 4000)
MODEL_FLAT_PX = int(os.environ.get("PIPELINE_MODEL_FLAT_PX") or 2000)
MODEL_MIN_PX = 1600


def page_max_px(page, kind=None, target_dpi=None, cap=None):
    """Сколько пикселей по длинной стороне дать модели на этой странице.

    У страницы с текстовым слоем предел прежний: значения берутся из слоя, а модель на
    большой картинке переписывает меньше. У скана без слоя предел считается от размера
    листа: там модель — единственный источник.
    """
    if kind not in (None, "SCAN_NO_TEXT"):
        return MODEL_FLAT_PX
    long_mm = max(page.rect.width, page.rect.height) / 72 * 25.4
    want = round(long_mm / 25.4 * (target_dpi or MODEL_TARGET_DPI))
    return max(MODEL_MIN_PX, min(cap or MODEL_MAX_PX, want))
# Распознавание сканов можно выключить окружением: PIPELINE_OCR=0. Сервис так
# проводит объект до протокола за минуты, когда в кеше нет прочитанных страниц.
OCR_ENABLED = os.environ.get("PIPELINE_OCR", "1") != "0"
# Куда рисуются картинки страниц перед распознаванием. Не в кеш: на стенде кеш —
# это каталог репозитория, смонтированный в контейнер, и запись туда идёт 26 МБ/с
# против 574 МБ/с у файловой системы контейнера (замер 18.09, #52). Лист А0 при
# 300 dpi — десятки мегабайт, и Tesseract читает их оттуда же: на разборе объекта
# это давало 2,8 страницы в минуту вместо 47 на хосте. Картинки временные: каждая стирается
# сразу после того, как её прочитали Tesseract и модель (`drop_render`, #67), кешируется
# только текст. Если чтение упало посередине, картинка остаётся — каталог одноразовый.
RENDER_DIR = os.environ.get("PIPELINE_RENDER_DIR") or os.path.join(tempfile.gettempdir(), "inspector-render")
# Модель по умолчанию — выбранная под прод (Р-55): она первая в списке моделей сервиса
# (PIPELINE_MODEL_CHOICES), её раздаёт своя модель поставки (service/llm/serve.py) и спрашивает
# прицельный проход (vlm_values.MODEL). Берётся, когда у вызова нет имени модели и не заданы
# PIPELINE_MODEL_NAME и BENCH_MODEL: командная строка, замеры, сервис с пустым списком моделей
# (Р-169). Прежнее умолчание google/gemini-2.5-flash-lite — на нём сняты 0,967 режима model в
# замере #54; повторить тот замер — bench/measure_reading_modes.py --model-name с его именем
DEFAULT_MODEL = "qwen/qwen3.6-27b"

PROMPT = (
    "Это страница российской строительной документации. "
    "Перепиши весь видимый текст страницы дословно, сохраняя порядок чтения и переносы строк. "
    "Таблицы передавай построчно, разделяя ячейки вертикальной чертой. "
    "Ничего не переводи, не сокращай и не комментируй. Верни только текст страницы."
)


# ---------- тип страницы ----------

def classify(words, images, width_pt, height_pt):
    """Тип страницы. Листы крупного формата (А3+) считаются чертежами независимо от числа слов."""
    if words == 0:
        return "SCAN_NO_TEXT"
    if words < MIN_WORDS_FOR_TEXT_LAYER and images:
        return "SCAN_SPARSE"
    if max(width_pt, height_pt) >= MIN_SHEET_PT:
        return "DRAWING"
    wide = width_pt > height_pt
    if wide and words < 400:
        return "DRAWING"
    if words >= 400:
        return "DENSE_TEXT"
    return "TEXT"


# ---------- кеш ----------

READ_VERSION = 3


def _cache_path(digest, page, tag):
    d = os.path.join(CACHE, "pages", digest[:2], digest)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{page:05d}.{tag}.json")


def cache_get(digest, page, tag):
    p = _cache_path(digest, page, tag)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
                if tag == "read" and isinstance(data, dict):
                    # Пересчёт типа страницы при чтении из кэша (задача #20):
                    # листы крупного формата (А3+, max_pt >= 1000) относятся к DRAWING независимо от числа слов.
                    if data.get("kind") not in OCR_KINDS:
                        data["kind"] = classify(len(data.get("words") or []),
                                                data.get("images", 0),
                                                data.get("width_pt", 0),
                                                data.get("height_pt", 0))
                return data
        except Exception:
            return None
    return None


def cache_put(digest, page, tag, value):
    with open(_cache_path(digest, page, tag), "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False)


# ---------- источники текста ----------

def read_text_layer(doc, page_no):
    """Текстовый слой и слова с координатами."""
    import pymupdf
    page = doc[page_no - 1]
    rect = page.rect
    words = page.get_text("words")     # x0, y0, x1, y1, слово, блок, строка, номер
    w, h = rect.width or 1, rect.height or 1
    rot_m = page.rotation_matrix if page.rotation else None
    out_words = []
    for x in words:
        if rot_m:
            r = pymupdf.Rect(x[0], x[1], x[2], x[3]) * rot_m
            x0, y0, x1, y1 = r.x0, r.y0, r.x1, r.y1
        else:
            x0, y0, x1, y1 = x[0], x[1], x[2], x[3]
        out_words.append({
            "t": x[4],
            "bbox": [max(0.0, min(1.0, round(x0 / w, 5))),
                     max(0.0, min(1.0, round(y0 / h, 5))),
                     max(0.0, min(1.0, round(x1 / w, 5))),
                     max(0.0, min(1.0, round(y1 / h, 5)))]
        })
    # Кириллица, раскодированная не той кодовой страницей, чинится здесь: для правил такая
    # страница была пустотой, а это не картинка, а неверная кодировка (#98, pipeline/encoding.py)
    raw = page.get_text("text").strip()
    text, fixed = encoding.repair(raw)
    if fixed:
        # слова чинятся по одному, а решения — по странице: иначе одиночные буквы (Р-140)
        # в тексте страницы починены, а в словах с координатами остались бы латиницей
        for w, t in zip(out_words, encoding.repair_words([w["t"] for w in out_words], raw)):
            w["t"] = t
    return {
        "text": text,
        "words": out_words,
        "encoding_fixed": fixed,
        "images": len(page.get_images(full=True)),
        "rotation": page.rotation,
        "coords_rotated": True,
        "width_pt": round(rect.width, 1),
        "height_pt": round(rect.height, 1),
    }


def drop_render(out_png):
    """Стереть картинку страницы: она нужна только на время чтения (#67).

    Tesseract и модель получают файл на диске, и дальше он не нужен. Лист А0 при 300 dpi —
    десятки мегабайт; на объекте в тысячи сканов невынесенные картинки съедали временный
    каталог гигабайтами, а на стенде это `/tmp` контейнера воркера, который между объектами
    никто не чистит. Каталог целиком не подметаем: страницы читаются в шесть потоков, и
    чужая картинка в этот момент может быть в работе.
    """
    try:
        os.remove(out_png)
    except OSError:
        pass                        # файла нет или его уже убрали — не повод ронять чтение


def render(doc, page_no, out_png, dpi=300, max_px=None):
    page = doc[page_no - 1]
    if max_px:
        long_pt = max(page.rect.width, page.rect.height) or 1
        dpi = max(72, min(dpi, int(max_px * 72 / long_pt)))
    out_dir = os.path.dirname(out_png)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    page.get_pixmap(dpi=dpi).save(out_png)
    return out_png


# Tesseract собран с OpenMP и по умолчанию берёт все ядра на одну страницу. Страницы мы
# читаем параллельно сами, и потоки начинают мешать друг другу: в контейнере стенда один
# лист распознавался 137 секунд, с одним потоком на процесс — 3,8 секунды (замер 18.09, #52).
# Параллелим процессами, а каждому процессу оставляем один поток.
TESSERACT_ENV = {**os.environ, "OMP_THREAD_LIMIT": os.environ.get("OMP_THREAD_LIMIT", "1")}


def read_tesseract(png, psm="6"):
    """Распознавание страницы через Tesseract с возвратом текста и слов с координатами (задача #22)."""
    with tempfile.TemporaryDirectory() as td:
        base = os.path.join(td, "o")
        try:
            subprocess.run([TESSERACT_CMD, png, base, "-l", "rus+eng", "--psm", psm, "tsv", "txt"],
                           check=True, capture_output=True, timeout=180, env=TESSERACT_ENV)
        except Exception as e:
            return {"text": "", "words": [], "error": f"{type(e).__name__}"}

        text = ""
        txt_path = base + ".txt"
        if os.path.exists(txt_path):
            try:
                with open(txt_path, encoding="utf-8", errors="replace") as f:
                    text = f.read().strip()
            except Exception:
                pass

        tsv_path = base + ".tsv"
        words = []
        if os.path.exists(tsv_path):
            try:
                with open(tsv_path, encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
                    pw, ph = None, None
                    rows = []
                    for row in reader:
                        if row.get("level") == "1":
                            try:
                                pw = float(row.get("width") or 0)
                                ph = float(row.get("height") or 0)
                            except (TypeError, ValueError):
                                pass
                        t = (row.get("text") or "").strip()
                        if t:
                            rows.append(row)

                    if not pw or not ph:
                        import pymupdf
                        pix = pymupdf.Pixmap(png)
                        pw, ph = float(pix.width or 1), float(pix.height or 1)

                    for row in rows:
                        t = (row.get("text") or "").strip()
                        try:
                            left = int(row["left"])
                            top = int(row["top"])
                            w = int(row["width"])
                            h = int(row["height"])
                            conf = float(row.get("conf") or -1)
                        except (TypeError, ValueError, KeyError):
                            continue
                        if conf < 20:
                            continue
                        x0 = max(0.0, min(1.0, round(left / pw, 5)))
                        y0 = max(0.0, min(1.0, round(top / ph, 5)))
                        x1 = max(0.0, min(1.0, round((left + w) / pw, 5)))
                        y1 = max(0.0, min(1.0, round((top + h) / ph, 5)))
                        words.append({
                            "t": t,
                            "bbox": [x0, y0, x1, y1],
                            "conf": round(conf, 1),
                            "source": "TESSERACT",
                        })
            except Exception:
                pass

        return {"text": text, "words": words}


# Куда ходить за моделью. Совместимо с OpenAI-подобным /chat/completions, поэтому один
# и тот же режим работает и с моделью на своём железе (vLLM, Ollama, llama.cpp), и через
# OpenRouter. Ключ нужен не всякому адресу: своя модель обычно раздаётся без него (#54).
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_URL = os.environ.get("PIPELINE_MODEL_URL") or OPENROUTER_URL
MODEL_KEY_ENV = os.environ.get("PIPELINE_MODEL_KEY_ENV") or "OPENROUTER_API_KEY"
# Запасной адрес на случай, когда своя модель не отвечает: карта занята, веса ещё грузятся,
# контейнер модели не поднялся. Тогда страница читается запасным адресом, обычно OpenRouter,
# и только если для него есть ключ. По умолчанию запасного нет: стенд с OpenRouter
# основным адресом работает как работал. Своё и запасное имя модели совпадают — сервер своей
# модели раздаёт её под именем OpenRouter (deploy/docker-compose.release.yml).
MODEL_FALLBACK_URL = os.environ.get("PIPELINE_MODEL_FALLBACK_URL") or ""
MODEL_FALLBACK_KEY_ENV = os.environ.get("PIPELINE_MODEL_FALLBACK_KEY_ENV") or "OPENROUTER_API_KEY"
# Сколько секунд не стучаться в основной адрес, который не ответил по сети: иначе каждая
# страница ждёт отказа, прежде чем уйти на запасной. Счёт свой у каждого процесса чтения.
MODEL_PRIMARY_PAUSE_S = float(os.environ.get("PIPELINE_MODEL_PRIMARY_PAUSE_S") or 60)
_primary_paused_until = 0.0
# Потолок ответа: страница документации — это тысячи знаков, а не десятки тысяч. Без потолка
# зациклившаяся модель добирает лимит до конца и тратит время и деньги впустую (#54).
MODEL_MAX_TOKENS = int(os.environ.get("PIPELINE_MODEL_MAX_TOKENS") or 4000)
# Переспрос обрезанного ответа (27.09). Ответ, который упёрся в потолок и повтором не оказался, —
# это плотный лист, спецификация или таблица, и у него пропал конец страницы, а на чертеже там
# штамп. Такая страница спрашивается ещё раз с потолком побольше; зациклившийся ответ — нет.
# На Полярной 16 так обрезано 10 честных ответов из 468, 2 %
MODEL_RETRY_TOKENS = int(os.environ.get("PIPELINE_MODEL_RETRY_TOKENS") or 16000)
# 16 тысяч токенов у провайдера — это минуты: зациклившийся ответ в 4000 токенов шёл 92–240 с
MODEL_RETRY_TIMEOUT = int(os.environ.get("PIPELINE_MODEL_RETRY_TIMEOUT") or 1200)
# что из ответа модели записывается у страницы: имя, время, стоимость, отказ, переспрос (#54),
# запасной адрес (Р-98)
MODEL_NOTE_KEYS = ("model", "ms", "cost_usd", "looped", "error", "finish_reason", "tokens_in", "tokens_out",
                   "retried", "first_tokens_out", "retry_error", "loop_from", "fallback")
# Просить ли модель размышлять перед ответом. По умолчанию нет: работа — переписать текст
# страницы, и размышление добавляет цену и время, а не качество (#71).
MODEL_REASONING = os.environ.get("PIPELINE_MODEL_REASONING", "0") not in ("0", "false", "no", "")
# Какой сервер стоит за адресом, если это не OpenRouter: от этого зависит, каким полем
# выключается размышление. vllm — vLLM, SGLang, llama.cpp (шаблоном чата); ollama — Ollama
# (reasoning_effort); openai — любой другой совместимый сервер, поле не передаётся.
MODEL_SERVER = (os.environ.get("PIPELINE_MODEL_SERVER") or "vllm").strip().lower()
# Лишние поля запроса своему серверу, JSON-объектом: то, что понимает только он
# (например {"top_k": 1} у vLLM). OpenRouter их не получает.
MODEL_EXTRA_BODY = os.environ.get("PIPELINE_MODEL_EXTRA_BODY") or ""
# Сколько ждать ответа на одну страницу. Медленному серверу с очередью (Ollama на одной
# карте, чужой сервис) трёх минут может не хватить.
MODEL_TIMEOUT_S = float(os.environ.get("PIPELINE_MODEL_TIMEOUT_S") or 180)


def model_name():
    """Имя модели: настройка сервиса, стенда или значение по умолчанию."""
    return os.environ.get("PIPELINE_MODEL_NAME") or os.environ.get("BENCH_MODEL") or DEFAULT_MODEL


def is_openrouter(url):
    return "openrouter.ai" in (url or "")


def model_endpoints(url=None):
    """Адреса модели по порядку попытки: [(адрес, переменная ключа, запасной ли)].

    Явно переданный адрес идёт один: замер или проверка просят именно его. Адрес OpenRouter
    без ключа в списке остаётся только основным — чтобы отказ «нет ключа» был виден.
    """
    if url:
        return [(url, MODEL_KEY_ENV, False)]
    out = [(MODEL_URL, MODEL_KEY_ENV, False)]
    if MODEL_FALLBACK_URL and MODEL_FALLBACK_URL != MODEL_URL:
        if not is_openrouter(MODEL_FALLBACK_URL) or os.environ.get(MODEL_FALLBACK_KEY_ENV):
            out.append((MODEL_FALLBACK_URL, MODEL_FALLBACK_KEY_ENV, True))
    return out


def model_body(model, prompt, b64, url, max_tokens=None):
    """Тело запроса к модели. Отключение размышления у каждого адреса своё.

    `max_tokens` — потолок ответа: `MODEL_MAX_TOKENS`, у переспроса обрезанного ответа — больше.
    """
    body = {
        "model": model, "temperature": 0, "max_tokens": max_tokens or MODEL_MAX_TOKENS,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt or PROMPT},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
        ]}],
    }
    # Размышление модели здесь не нужно: её просят переписать видимый текст, а не решать задачу.
    # У «думающих» вариантов оно стоит вдесятеро дороже и втрое дольше при прибавке в пару
    # тысячных (#71). OpenRouter понимает своё поле reasoning. vLLM и SGLang его пропускают
    # молча, и Qwen3.6 думает: 0,922 против 0,988 на трудной выборке. У них размышление
    # выключается шаблоном чата, как велит карточка модели; у Ollama — полем reasoning_effort.
    server = "openrouter" if is_openrouter(url) else MODEL_SERVER
    if not MODEL_REASONING:
        if server == "openrouter":
            body["reasoning"] = {"enabled": False, "exclude": True}
        elif server == "ollama":
            body["reasoning_effort"] = "none"
        elif server != "openai":
            body["chat_template_kwargs"] = {"enable_thinking": False}
    if server != "openrouter" and MODEL_EXTRA_BODY:
        body.update(json.loads(MODEL_EXTRA_BODY))
    return body


def _post_model(url, key_env, body, timeout):
    """Один запрос: (ответ, None, сетевой ли отказ) или (None, ошибка, сетевой ли отказ).

    Сетевой отказ — адрес не ответил вовсе: нет имени, соединение отвергнуто, истекло время.
    Так ведёт себя сервер своей модели, который не поднялся или ещё грузит веса.
    """
    import urllib.error, urllib.request
    key = os.environ.get(key_env)
    if not key and is_openrouter(url):
        return None, f"нет {key_env}", False
    headers = {"Content-Type": "application/json", "X-Title": "inspector-ai"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()), None, False
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}", False
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        reason = getattr(e, "reason", None)
        return None, type(reason if isinstance(reason, BaseException) else e).__name__, True
    except Exception as e:
        return None, type(e).__name__, False


# Ответы основного адреса, после которых страницу стоит повторить запасным: сервер есть,
# но модели на нём нет (404), он перегружен или упал внутри (408, 429, 5xx). Отказ 400 —
# плохой запрос, запасной ответит тем же.
_FALLBACK_HTTP = {"HTTP 404", "HTTP 408", "HTTP 429"} | {f"HTTP {c}" for c in range(500, 600)}
THINK_BLOCK = re.compile(r"^\s*<think>.*?</think>", re.S)


def read_model(png, model=None, timeout=None, url=None, prompt=None):
    """Мультимодальная модель по адресу MODEL_URL: своё железо или OpenRouter.

    Зациклившийся ответ не принимается: модель повторяет заголовки таблицы, пока не упрётся
    в лимит токенов, и такой текст выглядит правдоподобно, но страницы в нём нет. Он стоит
    времени на своём железе и денег у провайдера, поэтому отбрасывается сразу (#54).

    Ответ, который упёрся в потолок `MODEL_MAX_TOKENS` и повтором не оказался, спрашивается ещё
    раз с потолком `MODEL_RETRY_TOKENS`: страница длиннее потолка, и без переспроса у неё пропал
    бы конец. Время, токены и деньги обоих вызовов складываются.

    `prompt` — прицельный вопрос вместо общего «перепиши весь текст»: так у правила можно
    спросить одно значение с чертежа, где текста нет вовсе (#98). Он не переспрашивается: ответ
    на него — одно значение, и длинный ответ там сам по себе сбой.

    Если основной адрес не ответил, а запасной задан (MODEL_FALLBACK_URL), страница читается
    запасным, и в ответе стоит `fallback: True`.
    """
    import base64
    model = model or model_name()
    timeout = timeout or MODEL_TIMEOUT_S
    with open(png, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    first = _ask(url, model, b64, prompt, MODEL_MAX_TOKENS, timeout)
    if (prompt is not None or first.get("finish_reason") != "length" or not first.get("text")
            or MODEL_RETRY_TOKENS <= MODEL_MAX_TOKENS):
        return first
    again = _ask(url, model, b64, prompt, MODEL_RETRY_TOKENS, max(timeout, MODEL_RETRY_TIMEOUT))
    spent = {k: (first.get(k) or 0) + (again.get(k) or 0) for k in ("cost_usd", "tokens_in", "tokens_out", "ms")}
    note = {"retried": True, "first_tokens_out": first.get("tokens_out")}
    if first.get("fallback") or again.get("fallback"):
        note["fallback"] = True
    if again.get("text"):
        return {**again, **spent, **note}
    # Переспрос текста не дал: сбой вызова или повтор дальше первого потолка. Остаётся первый
    # ответ — обрезанный, но без повтора; больше страница не переспрашивается
    return {**first, **spent, **note, "retry_error": again.get("error") or "пустой ответ",
            **({"loop_from": again["loop_from"]} if again.get("loop_from") is not None else {})}


def _ask(url, model, b64, prompt, max_tokens, timeout):
    """Один вызов модели: ответ, его токены, время и цена.

    Адреса — по `model_endpoints`: основной, а если он не ответил и запасной задан — запасной.
    """
    global _primary_paused_until
    endpoints = model_endpoints(url)
    # основной адрес недавно не ответил по сети — сразу к запасному, если он есть
    if len(endpoints) > 1 and time.time() < _primary_paused_until:
        endpoints = endpoints[1:]
    t0 = time.time()
    errors = []
    data = None
    fallback = False
    for address, key_env, fallback in endpoints:
        data, error, network = _post_model(address, key_env, model_body(model, prompt, b64, address, max_tokens),
                                           timeout)
        if data is not None:
            break
        errors.append(error if not fallback else f"запасной: {error}")
        if not fallback and network:
            _primary_paused_until = time.time() + MODEL_PRIMARY_PAUSE_S
        if not (network or error in _FALLBACK_HTTP):
            break
    if data is None:
        return {"text": "", "error": "; ".join(errors)}
    usage = data.get("usage") or {}
    choice = (data.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content") or "").strip()
    # Размышление, если сервер его всё-таки включил, приходит в начале ответа блоком <think>:
    # в тексте страницы ему не место
    text = THINK_BLOCK.sub("", text).strip()
    out = {
        "model": data.get("model", model),
        "cost_usd": float(usage.get("cost") or 0.0),
        # Токены — то немногое в ответе провайдера, что переносится на своё железо: страница
        # стоит столько-то токенов на входе и выходе, а скорость карты считается в токенах
        # в секунду. Секунды провайдера — это его очередь, а не модель (#71).
        "tokens_in": int(usage.get("prompt_tokens") or 0),
        "tokens_out": int(usage.get("completion_tokens") or 0),
        "ms": int((time.time() - t0) * 1000),
        "finish_reason": choice.get("finish_reason"),
    }
    if fallback:
        out["fallback"] = True
    if text and looks_looped(text):
        # ответ зациклился: берём текст страницы без модели, чтобы повтор не попал в правила
        return {**out, "text": "", "looped": True, "error": "ответ зациклился",
                "loop_from": loop_start(text, out["tokens_out"])}
    return {**out, "text": text}


def loop_start(text, tokens, min_len=24):
    """С какого токена ответ пошёл по кругу: оценка по месту, где хвост ответа встретился впервые.

    По ней выбирается потолок первого вызова. Раннее зацикливание потолок пониже обрывает
    дешевле, а позднее в обрезке уже не узнаётся и уходит в переспрос с потолком побольше.
    """
    t = " ".join((text or "").split())
    if len(t) < min_len or not tokens:
        return None
    return int(tokens * t.find(t[-min_len:]) / len(t))


def layer_words(read):
    """Слов текстового слоя у прочитанной страницы — без слов распознавания."""
    return sum(1 for w in read.get("words") or [] if not (isinstance(w, dict) and w.get("source") == "TESSERACT"))


def wants_model(kind, words):
    """Отдавать ли страницу модели: скан без текста или чертёж, у которого в слое меньше MODEL_LAYER_WORDS слов."""
    return kind == "SCAN_NO_TEXT" or (kind == "DRAWING" and words < MODEL_LAYER_WORDS)


def _cut_short(cached):
    """Ответ модели в кеше упёрся в потолок, не зациклился и не переспрашивался — код до 27.09."""
    call = cached.get("model_call") or {}
    return (call.get("finish_reason") == "length" and not call.get("looped") and not call.get("retried")
            and "MODEL" in (cached.get("sources") or []))


def looks_looped(text, min_len=24, times=8):
    """Признак зацикливания модели на повторяющейся таблице.

    Встретилось на спецификации оборудования: модель бесконечно повторяла
    заголовки колонок «Р, Па N, об/мин Тип корпуса Степень защиты IP». Текст
    выглядит правдоподобно, но содержит только повтор, и основная надпись в него
    не попадает. Такую страницу честнее пометить как низкокачественную.
    """
    t = " ".join((text or "").split())
    if len(t) < min_len * times:
        return False
    probe = t[-min_len:]
    return t.count(probe) >= times


# ---------- сборка ----------

def read_page(doc, page_no, digest, use_model=True, model=None, dpi=300,
              max_px=None, work_dir=None, use_ocr=None):
    """Прочитать страницу целиком. Возвращает текст, слова с координатами и источник.

    `use_ocr` — распознавать ли сканы; None означает настройку окружения. Явное значение
    нужно сервису: способ чтения там выбирается на объект, а не на весь воркер (#54).
    `max_px` — предел картинки для модели; None считает его от размера листа (`page_max_px`).
    """
    ocr_on = OCR_ENABLED if use_ocr is None else bool(use_ocr)
    cached = cache_get(digest, page_no, "read")
    if cached is not None and use_model and _cut_short(cached) and wants_model(cached.get("kind"), layer_words(cached)):
        # Ответ модели в кеше обрезан потолком, а переспроса тогда не было: страница читается
        # заново целиком — текст модели в кеше не отделить от слоя и распознавания
        cached = None
    if cached is not None:
        # 1. Поворот координат (задача #20): если страница повёрнута и была сохранена
        #    старой версией без rotation_matrix, перечитываем текстовый слой из doc.
        if cached.get("rotation") and not cached.get("coords_rotated") and doc is not None:
            layer = read_text_layer(doc, page_no)
            cached["words"] = layer["words"]
            cached["coords_rotated"] = True
            cached["version"] = READ_VERSION
            cache_put(digest, page_no, "read", cached)

        # 2. Тип страницы пересчитывается:
        if cached.get("kind") not in OCR_KINDS:
            cached["kind"] = classify(len(cached.get("words") or []),
                                      cached.get("images", 0),
                                      cached.get("width_pt", 0),
                                      cached.get("height_pt", 0))

        need_ocr = (ocr_on and cached.get("kind") in OCR_KINDS
                    and "TESSERACT" not in (cached.get("sources") or [])
                    and cached.get("ocr_skipped"))
        need_model = (use_model and wants_model(cached.get("kind"), layer_words(cached))
                      and "MODEL" not in (cached.get("sources") or []))
        has_tesseract_words = (cached.get("ocr_words_checked")
                               or any(w.get("source") == "TESSERACT" for w in (cached.get("words") or [])))
        need_ocr_words = (ocr_on and cached.get("kind") in OCR_KINDS
                          and not has_tesseract_words and doc is not None)

        if not need_ocr and not need_model and not need_ocr_words:
            return cached

        # Довызов OCR для пополнения слов с координатами (задача #22):
        if need_ocr_words and not need_ocr and not need_model and doc is not None:
            work_dir = work_dir or RENDER_DIR
            png = render(doc, page_no,
                         os.path.join(work_dir, f"{digest[:12]}-{page_no:05d}.png"),
                         dpi=dpi, max_px=ocr_max_px(cached.get("width_pt"), cached.get("height_pt")))
            ocr = read_tesseract(png)
            drop_render(png)
            cached["ocr_words_checked"] = True
            if ocr.get("words"):
                existing = [w for w in (cached.get("words") or []) if w.get("source") != "TESSERACT"]
                cached["words"] = existing + ocr["words"]
            cached["version"] = READ_VERSION
            cache_put(digest, page_no, "read", cached)
            return cached

        # Довызов модели на существующем кеше без повторного распознавания:
        if need_model and not need_ocr and doc is not None:
            work_dir = work_dir or RENDER_DIR
            small = render(doc, page_no,
                           os.path.join(work_dir, f"{digest[:12]}-{page_no:05d}-m.png"),
                           dpi=dpi, max_px=max_px or page_max_px(doc[page_no - 1], cached.get("kind")))
            got = read_model(small, model=model)
            drop_render(small)
            # Что ответила модель, записывается и здесь, а не только при первом чтении страницы:
            # на повторном разборе и при дозагрузке модель зовётся именно по готовому кешу, и без
            # этой записи отчёт готовности не видел ни вызовов, ни отказов, ни потраченных денег.
            # Деньги считаются и за ответ без текста: провайдер берёт за вызов, а не за пользу.
            cached["model_call"] = {k: got[k] for k in MODEL_NOTE_KEYS
                                    if got.get(k) is not None}
            cached["cost_usd"] = round((cached.get("cost_usd") or 0.0) + (got.get("cost_usd") or 0.0), 6)
            if got.get("text"):
                parts = [cached.get("text", "")] if cached.get("text") else []
                parts.append(got["text"])
                cached["text"] = "\n".join(parts).strip()
                sources = cached.get("sources") or []
                sources.append("MODEL")
                cached["sources"] = sources
                cached["text_source"] = "UNION" if len(sources) > 1 else "MODEL"
            cached["version"] = READ_VERSION
            cache_put(digest, page_no, "read", cached)
            return cached

    t0 = time.time()
    layer = read_text_layer(doc, page_no)
    kind = classify(len(layer["words"]), layer["images"],
                    layer["width_pt"], layer["height_pt"])

    parts, sources, cost = [], [], 0.0
    words = list(layer["words"])
    if layer["text"]:
        parts.append(layer["text"])
        sources.append("TEXT_LAYER")

    work_dir = work_dir or RENDER_DIR

    if kind in OCR_KINDS and ocr_on:
        png = render(doc, page_no,
                     os.path.join(work_dir, f"{digest[:12]}-{page_no:05d}.png"),
                     dpi=dpi, max_px=ocr_max_px(layer["width_pt"], layer["height_pt"]))
        ocr = read_tesseract(png)
        drop_render(png)
        if ocr.get("text"):
            parts.append(ocr["text"])
            sources.append("TESSERACT")
        if ocr.get("words"):
            if not words:
                words = ocr["words"]
            else:
                words = words + ocr["words"]

    model_note = None
    if use_model and wants_model(kind, len(layer["words"])):
        small = render(doc, page_no,
                       os.path.join(work_dir, f"{digest[:12]}-{page_no:05d}-m.png"),
                       dpi=dpi, max_px=max_px or page_max_px(doc[page_no - 1], kind))
        got = read_model(small, model=model)
        drop_render(small)
        cost += got.get("cost_usd") or 0.0
        # что ответила модель, видно в записи страницы: имя, время, стоимость, отказ (#54)
        model_note = {k: got[k] for k in MODEL_NOTE_KEYS
                      if got.get(k) is not None}
        if got.get("text"):
            parts.append(got["text"])
            sources.append("MODEL")

    out = {
        "version": READ_VERSION,
        "kind": kind,
        "text": "\n".join(parts).strip(),
        "text_source": "UNION" if len(sources) > 1 else (sources[0] if sources else "NONE"),
        "sources": sources,
        "words": words,
        "rotation": layer["rotation"],
        "coords_rotated": True,
        "width_pt": layer["width_pt"],
        "height_pt": layer["height_pt"],
        "images": layer.get("images", 0),
        "quality": ("ABSTAIN" if not parts
                    else "LOW_QUALITY" if looks_looped("\n".join(parts)) else "OK"),
        "ocr_skipped": kind in OCR_KINDS and not ocr_on,
        "ms": int((time.time() - t0) * 1000),
        "cost_usd": round(cost, 6),
    }
    if model_note:
        out["model_call"] = model_note
    cache_put(digest, page_no, "read", out)
    return out
