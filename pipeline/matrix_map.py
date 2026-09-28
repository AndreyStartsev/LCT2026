"""Сопоставление находки с параметром Матрицы. Задача #23.

Зачем. Одна и та же находка, спроецированная в сдачу с кодом Матрицы и с кодом
свободного поиска, даёт совершенно разный балл: правило отождествления сравнивает
находки Матрицы по коду параметра, а находки свободного поиска — по типу
расхождения. Замерено на нашей находке о вытяжной вентиляции: с кодом IOS4-078
совпало 4 эталонные точки из 10, с кодом FREE-VENT-001 — ни одной. Разбор
и доказательства в обоих прогонах были одни и те же.

## Три источника, которые сужают выбор

**Разметка страницы.** Организатор проставил коды параметров прямо на страницах:
в `page_index.jsonl` они есть у 3810 страниц из 10146. На странице-доказательстве
проектной стадии эталонный код всегда оказывался среди размеченных. Это сужает
132 параметра до одного-восьми.

**Раздел проектной документации.** У каждого параметра в каталоге есть `pd_section`.
Раздел сужает сильнее, чем кажется: в ИОС4, куда попадают отопление и вентиляция,
параметров всего четыре. Самый населённый раздел — пояснительная записка, 23.

**Текст нарушения.** Сравнивается с наименованием параметра и его триггером
по основам слов. Морфология здесь обязательна: в перечне «вытяжная вентиляция»,
в каталоге «общеобменной вентиляции», точное вхождение даёт ноль.

## Что здесь работает, а что нет

**Сужение работает и проверено.** На обеих страницах-доказательствах проектной
стадии, где эталон называет параметр Матрицы, этот параметр оказался среди
размеченных организатором на той же странице. Сужение со 132 до четырёх.

**Окончательный выбор не работает и здесь не решён.** Совпадение основ слов
не различает параметры внутри раздела: нарушение «отсутствует вытяжная вентиляция»
цепляется одним словом «вентиляции» сразу за два параметра, 078 и 079, с разницей
в балле 0,017. Подбор порога «Матрица или свободный поиск» по двадцати восьми
размеченным вручную находкам упирается в вырожденный оптимум: лучший порог даёт
15 совпадений из 28, а тривиальное «всегда свободный поиск» даёт 14.

Модель различает 078 и 079 верно, чего лексика не может. Но граница со свободным
поиском ходит вслед за формулировкой правила: три разные формулировки дали 1, 2
и 2 попадания из трёх, и каждый раз ошибался другой случай.

**Причина одна: размеченных примеров три.** Эталон организатора называет параметр
всего у трёх доказательных групп. На трёх примерах порог не калибруется, и любая
правка чинит один случай за счёт другого. Это не дефект подхода, это нехватка
разметки, и она вынесена в задачу #23 отдельным пунктом.

Поэтому модуль отдаёт не одно значение, а суженный список с баллами и отрывом.
Для экрана инспектора это и есть нужная форма: по ТЗ кандидата подтверждает
человек, и ему важнее видеть, из чего выбирали, чем получить одну цифру.
"""
import collections
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dictionary.match import stem, stems  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_PATH = os.path.join(ROOT, "docs", "extracted", "parameter_catalog_132.jsonl")
# Постраничные индексы организатора. Обучающая часть и скрытый тест приехали
# отдельными пакетами, поэтому файлов два. Читаем оба: коды параметров на странице
# — это метаданные разметки, а не ответы, и на скрытом объекте они сужают выбор
# двенадцати формулировкам из пятнадцати.
PAGE_INDEX_PATHS = [
    os.path.join(ROOT, "docs", "extracted", "page_index.jsonl"),
    os.path.join(ROOT, "docs", "extracted", "page_index_test_hidden.jsonl"),
]

# Наш код раздела -> раздел проектной документации в каталоге параметров.
# Водоснабжение и канализация лежат у нас одним кодом, а в каталоге двумя
# разделами, поэтому значение — список.
SECTION_TO_PD = {
    "OV": ["Раздел 5. ИОС4"],
    "VK": ["Раздел 5. ИОС2", "Раздел 5. ИОС3"],
    "EOM": ["Раздел 5. ИОС1"],
    "SS": ["Раздел 5. ИОС5"],
    "KR": ["Раздел 4. КР"],
    "AR": ["Раздел 3. АР"],
    "GP": ["Раздел 2. СПЗУ"],
    "PB": ["Раздел 9. ППМ"],
    "POS": ["Раздел 6. ПОС"],
}

# Слова, которые есть почти в каждом нарушении и ничего не различают.
STOP = {stem(w) for w in (
    "проект", "проектной", "документации", "рабочей", "нарушение", "лист", "листа",
    "раздел", "согласно", "представленной", "требованиям", "соответствует",
    "предусмотренная", "выполнены", "работы", "помещения", "помещении", "здания",
    "шифр", "тома", "система",
    # Глаголы и существительные изменения. Они описывают, ЧТО случилось,
    # а сопоставлять надо по тому, С ЧЕМ это случилось. Веса по редкости их
    # не гасят, а наоборот раздувают: в каталоге 132 описаний слово «изменение»
    # встречается редко, в нарушениях — почти всегда. Из-за этого нарушение
    # о тёплых полах цеплялось за параметр о диаметрах магистралей отопления
    # по одному общему слову «изменена».
    "изменение", "изменена", "изменено", "отсутствует", "отсутствие",
    "увеличение", "уменьшение", "замена", "подмена", "снижение", "падение",
    "нарушение", "несоответствие",
)}

MIN_STEM_LEN = 4        # основы короче не различают: «дом», «вид», «под»
FREE_THRESHOLD = 0.12   # ниже этого находка остаётся свободным поиском (стеммы)
EMB_THRESHOLD = 0.40    # то же для эмбеддингов, подобран на настоящих весах BGE-M3 (#79):
                        # python tools/bench_embeddings.py --local. Порогом верных MATRIX
                        # не разделить с FREE: VS-0009 (FREE) даёт 0.572 — выше почти всех
                        # верных сопоставлений. Максимум (ГИП 8/10, организатор 3/4) держится
                        # на пороге 0.30–0.41 и у fp32, и у int8; 0.40 — верх этого плато.
                        # Ниже всех верных — ORG-3: 0.421 fp32, 0.412 int8. Прежние 0.58 роняли
                        # в FREE почти всё (ГИП 2/10).
CLOSE_MARGIN = 0.03     # отрыв меньше этого означает, что выбор надо показать человеку

# Переключатель: CLASSIFY_EMBEDDINGS=0 отключает эмбеддинги даже если ONNX доступен.
# По умолчанию включены, если модель есть.
CLASSIFY_EMBEDDINGS = os.environ.get("CLASSIFY_EMBEDDINGS", "1") != "0"

# ---------- правила по разделу (Д-58, ГИП 18.09.2026) ----------
# Когда эмбеддинги не различают семантически близкие параметры внутри раздела,
# ключевые слова из текста находки определяют выбор. Правила применяются всегда,
# когда у раздела они есть и хотя бы одно совпало: балл здесь не помощник, ради этого
# правила и заведены. Выбор правила виден в ответе полем `decided_by`.

SECTION_RULES = {
    "OV": {
        "IOS4-079": ["приточн", "установк", "агрегат", "вентилятор", "подмен",
                     r"расход.*вентиляц"],
        "IOS4-078": ["вытяжн", "воздуховод", "канал", "сечен",
                     r"отсутств.*вентиляц", r"изменен.*вентиляц",
                     r"состав.*систем"],
        "IOS4-077": ["тёпл", "отопительн", "радиатор", "конвектор", "полов"],
        "IOS4-076": ["диаметр", "стояк", "магистрал", "трубопровод"],
    },
    "GP": {
        "SPZU-032": ["покрыт", "одежд", "асфальт", "щебен", "сопряжени"],
        "SPZU-027": ["цветник", "озеленен", "газон", "деревь", "кустарник"],
        "SPZU-039": ["лоток", "дренаж", "водоотвод", "ливнев",
                     r"инженерн.*подготовк"],
    },
}

# ---------- эмбеддинги (ONNX оффлайн / API для разработки) ----------

MODEL_DIR = os.path.join(ROOT, "models", "embeddings")
# Какие файлы модели брать, по убыванию предпочтения: fp32 и квантованная int8
# (`models/embeddings/download.py`). Сравнить их на разметке — tools/bench_embeddings.py.
ONNX_NAMES = ("model.onnx", "model_quantized.onnx")
_ONNX_SESSION = None       # onnxruntime.InferenceSession, лениво
_ONNX_ERROR = None         # почему модель не загрузилась; повторно не пробуем
_TOKENIZER = None          # dict из tokenizer.json, лениво
_PARAM_EMBEDDINGS = None   # {parameter_code: numpy.ndarray}
_TEXT_EMBEDDINGS = {}      # {текст: numpy.ndarray}: один текст сверяется со всем разделом
TEXT_CACHE_MAX = 1024      # больше не держим: воркер живёт долго, а тексты не повторяются

_CATALOG = None
_IDF = None
_PAGE_CODES = None


# ---------- данные ----------

def catalog():
    """Каталог 132 параметров, разложенный по коду."""
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = {}
        if os.path.exists(CATALOG_PATH):
            with open(CATALOG_PATH, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        r = json.loads(line)
                        _CATALOG[r["parameter_code"]] = r
    return _CATALOG


def page_codes():
    """Коды параметров, размеченные организатором на странице: (файл, страница) -> коды."""
    global _PAGE_CODES
    if _PAGE_CODES is None:
        _PAGE_CODES = {}
        for path in PAGE_INDEX_PATHS:
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    p = json.loads(line)
                    codes = p.get("matrix_codes") or []
                    if codes:
                        _PAGE_CODES[(p["file_id"], p["output_page_number"])] = codes
    return _PAGE_CODES


def param_stems(rec):
    """Значимые основы описания параметра.

    Наименование весит больше триггера: триггер описывает, при каких условиях
    параметр срабатывает, и набирает общие слова вроде «уменьшение» и «падение»,
    которые есть в любом нарушении.
    """
    out = collections.Counter()
    for key, weight in (("parameter_name", 2.0), ("trigger", 1.0), ("unit", 1.0)):
        for s in stems(str(rec.get(key) or "")):
            if len(s) >= MIN_STEM_LEN and s not in STOP:
                out[s] = max(out[s], weight)
    return out


def idf():
    """Насколько основа редка среди 132 описаний параметров.

    Без этого «вентиляции» весит столько же, сколько «воздуховодов», и параметры
    одного раздела становятся неразличимы: в ИОС4 слово «вентиляции» стоит
    в наименовании у половины.
    """
    global _IDF
    if _IDF is None:
        df = collections.Counter()
        recs = list(catalog().values())
        for r in recs:
            for s in param_stems(r):
                df[s] += 1
        n = len(recs) or 1
        _IDF = {s: math.log(n / (1 + c)) + 1.0 for s, c in df.items()}
    return _IDF


# ---------- эмбеддинги ----------

def _onnx_path():
    """Файл модели, который есть на диске, или None."""
    for name in ONNX_NAMES:
        path = os.path.join(MODEL_DIR, name)
        if os.path.exists(path):
            return path
    return None


def _onnx_available():
    """Доступна ли ONNX-модель для инференса.

    Доступна — значит загрузилась. Одного файла графа мало: у BGE-M3 веса лежат
    отдельно (`model.onnx_data`), и граф без них на машинах уже лежал — его скачивал
    прежний download.sh. Такая модель не загрузится, и сопоставление должно идти на
    стеммах, а не падать на каждой находке.

    Токенизатор обязателен: без него текст не превратить в те же номера,
    на которых модель обучалась, а вектор наугад хуже стемм — он выглядит
    настоящим и молча ведёт сопоставление не туда.
    """
    if _ONNX_SESSION is not None:
        return True
    if _ONNX_ERROR is not None or _onnx_path() is None:
        return False
    if not os.path.exists(os.path.join(MODEL_DIR, "tokenizer.json")):
        return False
    try:
        _load_onnx()
    except Exception as e:  # любая причина значит «модели нет»
        _fail(f"{type(e).__name__}: {e}")
        return False
    return True


def _fail(reason):
    """Запомнить, почему эмбеддингов нет, и сказать об этом один раз."""
    global _ONNX_ERROR
    _ONNX_ERROR = reason
    sys.stderr.write(f"matrix_map: эмбеддинги выключены, сопоставление на стеммах: {reason}\n")


def _load_tokenizer():
    """Загрузить токенизатор BGE-M3 (XLM-RoBERTa). Один раз."""
    global _TOKENIZER
    if _TOKENIZER is not None:
        return _TOKENIZER
    from tokenizers import Tokenizer
    tok_path = os.path.join(MODEL_DIR, "tokenizer.json")
    if os.path.exists(tok_path):
        _TOKENIZER = Tokenizer.from_file(tok_path)
    return _TOKENIZER


def _load_onnx():
    """Загрузить ONNX-сессию и токенизатор. Один раз.

    Вектор BGE-M3 — выход графа `sentence_embedding`: пулинг и нормировка сделаны
    внутри. Граф без этого выхода — другой экспорт, и свой пулинг поверх него дал бы
    не те векторы, на которых подбирался порог.
    """
    global _ONNX_SESSION
    _load_tokenizer()
    if _ONNX_SESSION is not None:
        return
    import onnxruntime as ort
    session = ort.InferenceSession(_onnx_path(), providers=["CPUExecutionProvider"])
    outputs = [o.name for o in session.get_outputs()]
    if "sentence_embedding" not in outputs:
        raise ValueError(f"у графа нет выхода sentence_embedding: {outputs}")
    _ONNX_SESSION = session


def _tokenize(text, max_len=512):
    """Номера токенов и маска для XLMRoberta одной строкой текста.

    Динамическая длина без добивки до max_len:
    настоящие находки имеют длину 15–30 токенов (в среднем ~22), описания
    параметров — 20–47 токенов. Обрезка добивки до фактической длины
    сокращает объём вычислений XLM-RoBERTa Large на CPU примерно в 23 раза
    (FFN O(L), Attention O(L^2)), снижая задержку с ~1 с до десятков миллисекунд.
    """
    import numpy as np
    if _TOKENIZER is None:
        _load_tokenizer()
    ids = _TOKENIZER.encode(text).ids[:max_len]
    if not ids:
        ids = [0]
    length = len(ids)
    input_ids = np.array([ids], dtype=np.int64)
    attention_mask = np.ones((1, length), dtype=np.int64)
    return {"input_ids": input_ids, "attention_mask": attention_mask}


def _embed_onnx(text):
    """Эмбеддинг текста через ONNX-модель. Возвращает numpy вектор.

    Один и тот же текст сверяется со всеми кандидатами раздела, поэтому вектор
    запоминается: без этого каждое сопоставление считало его заново — 4 раза
    в разделе ОВ, 16 в ГП и 132, когда раздел неизвестен.
    """
    import numpy as np
    cached = _TEXT_EMBEDDINGS.get(text)
    if cached is not None:
        return cached
    if _ONNX_SESSION is None:
        _load_onnx()
    inputs = _tokenize(text)
    # Первый выход графа — векторы токенов; усреднять их нельзя, BGE-M3 так не обучался
    vec = _ONNX_SESSION.run(["sentence_embedding"], inputs)[0][0]
    # граф уже нормирует; повтор дешёвый и держит косинус равным скалярному произведению
    norm = np.linalg.norm(vec)
    vec = vec / norm if norm > 0 else vec
    if len(_TEXT_EMBEDDINGS) >= TEXT_CACHE_MAX:
        _TEXT_EMBEDDINGS.clear()
    _TEXT_EMBEDDINGS[text] = vec
    return vec


def _param_embedding(rec):
    """Эмбеддинг описания параметра (кешируется)."""
    global _PARAM_EMBEDDINGS
    if _PARAM_EMBEDDINGS is None:
        _PARAM_EMBEDDINGS = {}
    code = rec["parameter_code"]
    if code not in _PARAM_EMBEDDINGS:
        text = rec.get("parameter_name", "")
        if rec.get("trigger"):
            text += ". " + rec["trigger"]
        _PARAM_EMBEDDINGS[code] = _embed_onnx(text)
    return _PARAM_EMBEDDINGS[code]


def embedding_score(text, rec):
    """Близость по эмбеддингам. Косинус нормализованных векторов."""
    import numpy as np
    emb_text = _embed_onnx(text)
    emb_param = _param_embedding(rec)
    return float(np.dot(emb_text, emb_param))


# ---------- правила по разделу ----------

def _apply_section_rules(text, section, candidates_ranked):
    """Переранжировать кандидатов по SECTION_RULES.

    Возвращает пару: порядок кандидатов и признак того, что выбор сделан правилом,
    а не баллом. Признак нужен дальше: у поднятого кандидата балл остаётся своим,
    меньшим, и по нему нельзя ни считать отрыв, ни решать, Матрица это или
    свободный поиск.

    Порядок не меняется и признак остаётся ложным, если:
    - для раздела нет правил
    - ни одно правило не сработало
    - правила подтверждают текущий top-1
    """
    rules = SECTION_RULES.get(str(section or "").upper())
    if not rules:
        return candidates_ranked, False

    text_lower = text.lower()
    rule_scores = {}  # код параметра -> сколько признаков правила совпало
    for code, patterns in rules.items():
        hits = sum(1 for p in patterns if re.search(p, text_lower))
        if hits > 0:
            rule_scores[code] = hits

    if not rule_scores:
        return candidates_ranked, False

    # Лучший код по правилам
    best_rule_code = max(rule_scores, key=rule_scores.get)

    # Найти этот код среди кандидатов и поднять наверх
    new_ranked = list(candidates_ranked)
    for i, (sc, rec) in enumerate(new_ranked):
        if rec["parameter_code"] == best_rule_code and i > 0:
            # Поднимаем, но сохраняем балл: он честно показывает, насколько
            # текст похож на описание параметра, а выбрало кандидата правило.
            item = new_ranked.pop(i)
            new_ranked.insert(0, item)
            return new_ranked, True
        if rec["parameter_code"] == best_rule_code:
            break  # правило подтвердило top-1, порядок прежний

    return new_ranked, False


# ---------- сопоставление ----------

def text_stems(text):
    return {s for s in stems(text) if len(s) >= MIN_STEM_LEN and s not in STOP}


def score(text, rec):
    """Близость текста находки к описанию параметра. Косинус на весах редкости.

    Доля покрытия не годится: описание параметра богаче любого нарушения, и
    у параметра с длинным триггером доля всегда ниже, хотя совпадение то же.
    Косинус нормирует обе стороны и не наказывает за подробность описания.
    """
    need = param_stems(rec)
    have = text_stems(text)
    if not need or not have:
        return 0.0
    w = idf()
    num = sum(need[s] * w.get(s, 1.0) ** 2 for s in need if s in have)
    na = math.sqrt(sum((need[s] * w.get(s, 1.0)) ** 2 for s in need))
    nb = math.sqrt(sum(w.get(s, 1.0) ** 2 for s in have))
    return num / (na * nb) if na and nb else 0.0


def candidates(section=None, evidence=None, full=False):
    """Параметры-кандидаты по убыванию уместности и то, чем отобран первый ярус.

    Раньше это был жёсткий фильтр, и он терял верный ответ. Разметка человеком
    показала, сколько именно: из двадцати одной формулировки выбранный код
    не попадал в список шесть раз. Четыре из них — вина разметки страницы,
    которая сужала до трёх-шести кандидатов и выбрасывала нужный. Паспорт
    разметки предупреждает об этом прямо: отсутствие рамки не доказывает
    отсутствие поля.

    Ещё два случая — переход между разделами: нарушение найдено в конструктивном
    разделе, а параметр живёт в пояснительной записке, потому что там таблица
    технико-экономических показателей. Раздел документа тут тоже не фильтр.

    Поэтому теперь это порядок, а не отбор. Сначала коды, размеченные на самой
    странице, потом остальные параметры её раздела, потом вся Матрица. Кто
    показывает список, сам решает, где его обрезать.
    """
    cat = catalog()
    tier1, seen = [], set()
    if evidence:
        pc = page_codes()
        for e in evidence:
            for c in pc.get((e.get("file_id"), e.get("pdf_page_number")), []):
                if c in cat and c not in seen:
                    seen.add(c)
                    tier1.append(cat[c])
    tier2 = []
    wanted = SECTION_TO_PD.get(str(section or "").upper())
    if wanted:
        for r in cat.values():
            if r.get("pd_section") in wanted and r["parameter_code"] not in seen:
                seen.add(r["parameter_code"])
                tier2.append(r)
    rest = [r for r in cat.values() if r["parameter_code"] not in seen]
    how = ("разметка страницы" if tier1 else
           "раздел документа" if tier2 else "вся Матрица")
    pool = tier1 + tier2 + (rest if full else [])
    return (pool or list(cat.values())), how


def classify(text, section=None, evidence=None, threshold=FREE_THRESHOLD, top=3):
    """Код параметра для находки. Возвращает разбор, а не одно значение.

    Стратегия:
    1. Если доступны ONNX-эмбеддинги (BGE-M3) → embedding_score()
    2. Иначе → score() на стеммах (fallback)
    3. SECTION_RULES переранжируют при маленьком отрыве или в разделах
       с неразличимыми параметрами (OV, GP).

    Ответ намеренно показывает, из чего выбирали и с каким отрывом: сопоставление
    предварительное, и человеку надо видеть вторую версию, а не только первую.
    """
    pool, how = candidates(section, evidence)
    use_emb = CLASSIFY_EMBEDDINGS and _onnx_available()
    scorer = embedding_score if use_emb else score
    effective_threshold = EMB_THRESHOLD if use_emb else threshold
    ranked = sorted(((scorer(text, r), r) for r in pool), key=lambda p: -p[0])

    # SECTION_RULES: переранжировать если раздел в правилах
    by_rule = False
    if section and str(section).upper() in SECTION_RULES:
        ranked, by_rule = _apply_section_rules(text, section, ranked)

    best_score, best = (ranked[0] if ranked else (0.0, None))
    runner = ranked[1][0] if len(ranked) > 1 else 0.0
    if by_rule:
        # Кандидата выбрало правило, и его балл меньше, чем у сдвинутого вниз.
        # Отрыва в таком выборе нет, а порог смотрит на лучший балл раздела:
        # иначе сработавшее правило само роняло бы находку в свободный поиск.
        margin = 0.0
        matrix = bool(best) and max(sc for sc, _ in ranked) >= effective_threshold
    else:
        margin = best_score - runner
        matrix = bool(best) and best_score >= effective_threshold
    return {
        # Эмбеддинги улучшают ранг, но человек всегда проверяет: 14 точек мало
        # для доверия автоматике. needs_expert=False только когда accuracy ≥95% на ≥50 точках.
        "needs_expert": True,
        "matrix_scope": "MATRIX" if matrix else "FREE_SEARCH",
        "parameter_code": best["parameter_code"] if matrix else None,
        "parameter_id": best["parameter_id"] if matrix else None,
        "criticality": best.get("criticality") if matrix else None,
        "score": round(best_score, 3),
        "margin": round(margin, 3),
        "scoring_method": "embedding" if use_emb else "stem",
        "decided_by": "section_rule" if by_rule else "score",
        "selected_from": how,
        "pool_size": len(pool),
        "candidates": [{"parameter_code": r["parameter_code"],
                        "parameter_name": r["parameter_name"],
                        "score": round(s, 3)} for s, r in ranked[:top]],
    }


def finding_text(finding):
    """Текст находки для сопоставления: всё, что описывает суть расхождения."""
    parts = [finding.get(k) for k in
             ("title", "raw_text", "pd_value", "rd_value", "id_value")]
    return " ".join(str(p) for p in parts if p)
