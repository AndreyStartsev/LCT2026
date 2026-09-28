"""Правила Матрицы: значение показателя в двух стадиях и их сравнение. Этап 4б плана.

Первая очередь — разделы ПЗ и СПЗУ, 39 параметров. Правила лежат в
`rules/matrix_queue1.json`: подписи, по которым показатель ищется, тип значения,
тип сравнения и порог. Каждое правило несёт цитату триггера каталога, из которой
выведено, чтобы перевод прозы в машинный вид можно было проверить.

## Почему от параметра к документу, а не наоборот

Сопоставить текст нарушения с параметром Матрицы трудно, и на трёх размеченных
примерах это не настраивается (задача #23). В обратную сторону трудности нет:
если извлекается конкретный параметр, его код известен заранее. Это и делает
первую очередь выполнимой сейчас.

## Как выбирается значение внутри стадии

Подпись показателя встречается на многих страницах стадии: в таблице
технико-экономических показателей, в текстовой части, в ведомостях, в общих
данных смежных разделов. Значения обычно совпадают, но не всегда.

Значение выбирается голосованием страниц, и у страниц разный вес. Страница,
на которой найдено много показателей первой очереди сразу, — это таблица
показателей, и её голос весит больше, чем случайное упоминание в тексте.
Остальные значения не выбрасываются, а сохраняются как расхождения внутри стадии:
инспектору надо их видеть.

## Что уходит в находку

Решение принимается, только если значение найдено в обеих стадиях. Если оно
найдено в одной, находка получает метку «сравнение невозможно» и причину. Если
ни в одной — находки нет: отсутствие подписи в текстовом слое не доказывает
отсутствия показателя, особенно на чертежах без слоя.
"""
import collections
import hashlib
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import (alarms, apartment_mix, demolition, detectors, durations, elements, encoding, facade_colors,
                      finish_classes, fire_doors, fire_water, insulation, joints, layers, windows,
                      lighting, metering, mgn_rooms,
                      office_text, outdoor_water, outlets, pipe_materials, pumps, reading, rebar, site_works, slopes,
                      steel, steel_protection, takeoffs,  # noqa: E402
                      risers, smoke_fans, switchboards, tep, test_protocols)
from pipeline.config import CACHE, OBJECTS, OUT  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_PATH = os.path.join(ROOT, "rules", "matrix_queue1.json")
# Очереди Матрицы: первая — объектные показатели ПЗ и СПЗУ, вторая — АР и КР по элементам (#26),
# третья — ППМ и ОДИ (#27), четвёртая — ПОС, ПОД и ЗУ (#28), пятая — ИОС по номерам групп ВРУ и стояков (#29)
QUEUES = {1: RULES_PATH, 2: os.path.join(ROOT, "rules", "matrix_queue2.json"),
          3: os.path.join(ROOT, "rules", "matrix_queue3.json"),
          4: os.path.join(ROOT, "rules", "matrix_queue4.json"),
          5: os.path.join(ROOT, "rules", "matrix_queue5.json")}
CATALOG_PATH = os.path.join(ROOT, "docs", "extracted", "parameter_catalog_132.jsonl")
# Профиль предварительных правил (#95): черновики, которые ещё не проверил специалист. Лежат
# отдельно от очередей, в прод не подмешиваются и запускаются только флагом (`rules --provisional`,
# `vlm --provisional`); находки пишутся в `provisional_q<N>.jsonl` отложенными — в сдачу, отчёт
# о качестве и протокол стенда они не попадают
PROVISIONAL_DIR = os.path.join(ROOT, "rules", "provisional")
PROVISIONAL_REASON = "правило на проверке: расхождение — гипотеза, в сдачу только решением инспектора"

# Стадия документа в реестре -> стадия сравнения. Смешанные тома сводятся
# к рабочей вслед за эталоном организатора, см. pipeline/submission.py.
STAGE = {"PD": "PD", "RD": "RD", "RD_ID_MIXED": "RD", "ID": "ID"}

# Виды значений, для которых запасной источник не вправе решать. Подписи
# «площадь», «объём» и «ширина» встречаются где угодно: у бытового контейнера,
# в перечне предельных значений, в журнале изменений. Если в разделе-источнике
# значения нет, такое значение идёт в находку только как «сравнение невозможно».
# Классы огнестойкости и отметка нуля однозначны, для них запасной источник годится.
STRICT_SOURCE_KINDS = {"area", "volume", "length", "schedule_sum", "count", "power"}


# ---------- данные ----------

def load_rules(path=RULES_PATH):
    with open(path, encoding="utf-8") as f:
        rules = json.load(f)
    # код параметра — ключ словаря; правилу он нужен и внутри (проход модели ищет свои
    # значения по коду), поэтому кладём его полем
    for code, rule in (rules.get("parameters") or {}).items():
        if isinstance(rule, dict):
            rule.setdefault("code", code)
    return rules


def load_provisional(queue):
    """Черновики правил очереди или None. Классы значений берутся у правил очереди: черновик
    с `class` пользуется тем же словарём, что и прод."""
    path = os.path.join(PROVISIONAL_DIR, f"q{queue}.json")
    if not os.path.exists(path):
        return None
    rules = load_rules(path)
    core = load_rules(QUEUES[queue]) if queue in QUEUES else {}
    rules.setdefault("classes", core.get("classes") or {})
    rules.setdefault("location_defaults", core.get("location_defaults") or {})
    for rule in (rules.get("parameters") or {}).values():
        if isinstance(rule, dict):
            rule["provisional"] = True
    return rules


def mark_provisional(findings):
    """Находка черновика — отложенная: не в сдачу, с пометкой для инспектора (#95, Р-44, Р-50)."""
    for f in findings:
        f.update(provisional=True, for_submission=False, needs_expert=True, finding_status="SUSPICION",
                 exclusion_reason=PROVISIONAL_REASON)
    return findings


def provisional_hypotheses(findings):
    """Какие находки черновиков идут в протокол гипотезами (#95): только с нарушением.

    Подход 25.09: в гипотезы — по максимуму, в нарушения — только одобренное. Гипотеза
    черновика в сдачу не идёт, пока инспектор не взял её в кандидаты и не подтвердил, как
    гипотеза свободного поиска. «Расхождения нет» и «сравнить нельзя» от черновика записью не
    становятся: без решения специалиста это не проверка, а только отметка в покрытии параметра.
    """
    return [f for f in findings if f.get("provisional") and f.get("violation_label") == "VIOLATION_PRESENT"]


def load_catalog():
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return {json.loads(l)["parameter_code"]: json.loads(l) for l in f if l.strip()}


# 4: слияние #116 и #85 — у обеих веток формат строк назывался 3, а кеш общий. Строка распознанной
# страницы несёт и отметку кеша чтения (#116), и источник его чтения `rs` (#85): отметка говорит, что
# страницу перечитали, ранг источника — что перечитали не хуже. 3: распознанный текст и у сканов
# со штампом в слое (#116); 2: к слою добавлен распознанный
# текст страниц без слоя (#52). Номер меняется вместе со смыслом строк кеша: кеш общий для веток,
# и код с прежним смыслом не должен молча читать чужие подстановки
# 6: починка кириллицы, раскодированной не той кодовой страницей (#98). Номер выше обеих
# ветвей: 4 — в origin, 5 — в локальной копии с тем же исправлением на прежнем чтении.
# 7: строка помнит отпечаток кода обработки (`pf`), а сырой слой PDF лежит отдельно
# (`.cache/layer`). Дальше номер меняется только с форматом строки: правку обработки видит
# отпечаток, и кеш пересобирается из сырого слоя, не открывая PDF
TEXT_CACHE_VERSION = 7
# Разбор документов Word и Excel (DOCX, DOC, XLS, XLSX): строка кеша такого документа помнит его
# номер (`f`), и строка с другим номером перечитывается. Файлы эти читаются за миллисекунды, а общий
# номер кеша сбросил бы и слой PDF, и подстановки распознанного у всех объектов.
# 2 — табуляция и разрыв строки внутри абзаца DOCX (#112)
OFFICE_TEXT_VERSION = 2
OFFICE_SOURCES = ("DOCX", "DOC", "XLS", "XLSX")
# Страница короче этого правилами не разбирается (`_extract_document`), и её слой распознанным
# текстом заменяется в любом случае
MIN_PAGE_TEXT = 30


# ---------- полный пересбор по требованию ----------

# Кеши сами стареют вместе с кодом, правилами и текстом. Пересобрать заново всё или часть можно
# и руками — после правки, которую отпечаток не видит (внешние данные, новая версия PyMuPDF),
# или чтобы проверить, что кеш не врёт. Управляется переменными окружения, чтобы одинаково
# работать в командах конвейера, в инструментах замера и в воркере сервиса:
#   PIPELINE_FRESH=all          текст и кандидаты всех правил заново;
#   PIPELINE_FRESH=text         сырой слой PDF и текст страниц заново (распознанное — из кеша чтения);
#   PIPELINE_FRESH=candidates   кандидаты всех правил заново, текст — из кеша;
#   PIPELINE_FRESH_RULES=AR-045,KR-055   кандидаты только этих правил заново.
# Каждый документ пересобирается один раз за прогон: иначе пять очередей правил читали бы
# один PDF пять раз. Воркер сервиса сбрасывает этот учёт перед каждым сравнением (`reset_fresh`).
_FRESH_DONE = set()


def _fresh_parts():
    return {p.strip().lower() for p in os.environ.get("PIPELINE_FRESH", "").split(",") if p.strip()}


def fresh_text():
    parts = _fresh_parts()
    return bool(parts & {"all", "text"})


def fresh_rules():
    """Коды правил, чьи кандидаты надо собрать заново; "*" — все правила."""
    if _fresh_parts() & {"all", "candidates"}:
        return {"*"}
    return {c.strip() for c in os.environ.get("PIPELINE_FRESH_RULES", "").split(",") if c.strip()}


def _fresh_once(kind, key):
    """Пересобрать ли `key` (документ или «документ + правило») в этом прогоне: да — один раз."""
    if (kind, key) in _FRESH_DONE:
        return False
    _FRESH_DONE.add((kind, key))
    return True


def reset_fresh():
    """Забыть, что уже пересобрано: следующий прогон с PIPELINE_FRESH пересоберёт заново."""
    _FRESH_DONE.clear()


def _text_cache_path(sha):
    # Свой каталог у каждого формата строки: кеш общий для веток, и ветка на прежнем формате
    # иначе перезаписывала бы файлы новой и обратно — каждый раз с чтением PDF заново
    d = os.path.join(CACHE, "text", f"v{TEXT_CACHE_VERSION}", sha[:2])
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, sha + ".jsonl")


# Форматы, из которых правила читают текст. DOCX — это «Разрешения на внесение
# изменений» рабочей стадии и полные версии актов освидетельствования: там написано,
# что и почему изменено, и до #42 это никто не читал
# DOC, XLS и XLSX — с #112: акты приёмки систем, акты испытаний, реестры передаваемой документации
READABLE_EXT = (".pdf", ".docx", ".doc", ".xls", ".xlsx")
_DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def docx_text(path):
    """Текст DOCX: абзацы и ячейки таблиц в порядке документа.

    Без внешней зависимости: DOCX — это zip, разметка лежит в word/document.xml.
    Абзац и строка таблицы разделяются переводом строки, ячейки — табуляцией,
    чтобы таблица значений не склеивалась в одну строку.
    """
    import xml.etree.ElementTree as ET
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("word/document.xml"))
    except Exception:
        return ""
    body = next((el for el in root if _tag(el) == "body"), root)
    out = []

    def para(el):
        # табуляция и разрыв строки внутри абзаца — разделители: в акте «№ 52<tab>20.04.2026 г.»
        # без них номер слипался с датой (#112). `w:tab` в свойствах абзаца — позиция табуляции,
        # не знак, поэтому берутся только дети прогонов `w:r`
        parts = []
        for r in el.iter():
            if _tag(r) != "r":
                continue
            for c in r:
                name = _tag(c)
                if name == "t":
                    parts.append(c.text or "")
                elif name == "tab":
                    parts.append("\t")
                elif name in ("br", "cr"):
                    parts.append("\n")
        return "".join(parts)

    def walk(el, depth=0):
        for child in el:
            name = _tag(child)
            if name == "p":
                text = para(child).strip()
                if text:
                    out.append(text)
            elif name == "tbl":
                for tr in child:
                    if _tag(tr) != "tr":
                        continue
                    cells = [" ".join(para(pp).strip() for pp in tc.iter()
                                      if _tag(pp) == "p").strip()
                             for tc in tr if _tag(tc) == "tc"]
                    # табуляция внутри ячейки — пробел: табуляцией разделены ячейки
                    row = "\t".join(re.sub(r"[\t\n]+", " ", c) for c in cells).strip()
                    if row:
                        out.append(row)
            elif depth < 4:
                walk(child, depth + 1)

    walk(body)
    return "\n".join(out)


def _tag(el):
    return re.sub(r"^\{[^}]*\}", "", el.tag)


# Насколько хорошо прочитана страница в кеше чтения (#85). Отметка кеша чтения (#116) говорит,
# что страницу перечитали, но не что лучше: страницу без слоя, прочитанную моделью, прогон
# сервиса в режиме `tesseract` перечитывает целиком и перезаписывает одним Tesseract. Тогда
# правилам остаётся прежний текст. Строка кеша без источника — ранг 0: принимается любое чтение
READ_RANK = {"NONE": 0, "LAYER": 1, "DOCX": 1, "DOC": 1, "XLS": 1, "XLSX": 1, "TEXT_LAYER": 1, "TESSERACT": 2,
             "RECOGNIZED": 2, "UNION": 3, "MODEL": 4}


def read_rank(source):
    return READ_RANK.get((source or "").upper(), 0)


def recognized_text(sha, page_no, layer=""):
    """Распознанный текст страницы из кеша чтения, если он заменяет слой, иначе None.

    Кеш чтения (`.cache/pages/**/NNNNN.read.json`) пополняют команда `pages`
    и шаг разбора сервиса, когда включено распознавание. Правила туда не ходили,
    и на объекте, где рабочая документация — сканы, им было нечего читать:
    у контрольного объекта 302 страницы рабочей стадии из 320 без текстового слоя,
    и все 22 записи получались «сравнение невозможно» (#52).

    Слой заменяется не только там, где его нет (#116). Скан со штампом несёт в слое несколько
    слов — номер листа, «Взам. инв. №», подписи, — и шаг чтения называет такую страницу
    сканом (`SCAN_SPARSE`) и распознаёт её; текст в кеше чтения — слой вместе с распознанным.
    Правила же читали один штамп: на Полярной 16 условия присоединения в томах ЭОМ до них
    не доходили, у Тюменской-5 таких распознанных страниц 1122. Заменяется и слой короче
    `MIN_PAGE_TEXT`: такую страницу правила всё равно пропускают. У чертежа со слоем
    распознанное — пересказ того же листа моделью, и слой остаётся: значения не удваиваются.
    """
    got = recognized_source(sha, page_no, layer)
    return got[0] if got else None


def recognized_source(sha, page_no, layer=""):
    """(распознанный текст, источник чтения), если распознанное заменяет слой, иначе None."""
    got = reading.cache_get(sha, page_no, "read")
    if not got:
        return None
    source = got.get("text_source")
    if not source or source in ("TEXT_LAYER", "NONE"):
        return None          # слой уже прочитан напрямую, второй раз он не нужен
    text = (got.get("text") or "").strip()
    if not text:
        return None
    if len((layer or "").strip()) < MIN_PAGE_TEXT or got.get("kind") in reading.OCR_KINDS:
        return text, source
    return None


def _may_be_scan(text):
    """Стоит ли спрашивать кеш чтения: у скана слов в слое меньше, чем у страницы с текстом.

    Порог — тот же, по которому шаг чтения отличает скан со штампом (`reading.classify`).
    Страницы со слоем длиннее кеш чтения не открывают: он хранит слова с координатами
    и на плотной странице весит сотни килобайт.
    """
    return len((text or "").split()) < reading.MIN_WORDS_FOR_TEXT_LAYER


def _read_stamp(sha, page_no):
    """Отметка файла кеша чтения страницы: время последней записи, наносекунды. None — файла нет."""
    try:
        return os.stat(reading._cache_path(sha, page_no, "read")).st_mtime_ns
    except OSError:
        return None


def _from_reading(sha, page_no, layer):
    """(распознанный текст, отметка кеша чтения, источник чтения), если распознанное заменяет слой."""
    got = recognized_source(sha, page_no, layer)
    return (got[0], _read_stamp(sha, page_no), got[1]) if got else None


def _view(rows, scans):
    """Строки кеша для потребителя. scans=False — слой там, где он есть: у скана со штампом это штамп."""
    for page_no, text, source, layer, _stamp, _rs in rows:
        if not scans and source == "RECOGNIZED" and layer and layer.strip():
            yield page_no, layer, "LAYER"
        else:
            yield page_no, text, source


def page_texts_src(doc, root, scans=True):
    """Текст всех страниц документа: (страница, текст, источник). Кешируется по SHA-256.

    Первый источник — текстовый слой PDF. Там, где слоя нет или он — штамп поверх скана
    (`recognized_text`), берётся распознанный текст из кеша чтения, если он там есть:
    распознавание само по себе здесь не запускается, это делают команда `pages` и шаг
    разбора сервиса.
    Источник страницы едет с текстом, чтобы значение, прочитанное машиной,
    было видно в находке и в протоколе.

    Страницы кеша, где слоя нет или в нём меньше слов, чем у страницы с текстом,
    проверяются заново на каждом чтении: документ могли распознать уже после того,
    как правила его прочитали, и тогда в кеше чтения появился текст, которого в кеше
    правил нет. Стоит это одного чтения маленького файла на такую страницу, а без
    этого распознавание объекта не доходит до правил, пока кто-нибудь не сотрёт кеш (#52).

    Страница, взятая из распознанного, помнит свой слой и отметку файла кеша чтения. Если
    файл с тех пор переписан — страницу перечитали, например моделью вместо Tesseract, —
    текст берётся заново. Раньше перечитывались только пустые страницы, и на Октябрьской
    20 исполнительных схем, прочитанных моделью, правила видели прежним чтением (#89, #116).

    `scans=False` отдаёт у скана со штампом его слой, как до #116. Так читает сравнение редакций:
    два скана одного листа, распознанные Tesseract, расходятся шумом, и у Полярной 16 в цепочке
    редакций «без изменений» становилось 9 страниц из 32 вместо 21. Страница совсем без слоя
    и там отдаётся распознанной, как с #52.

    Хуже прежнего текст не заменяется: строка помнит и источник чтения (`rs`), и если страницу
    перечитали источником ниже рангом — прогон сервиса в режиме `tesseract` перезаписывает
    одним Tesseract страницу, прочитанную моделью, — остаётся прежний текст, а обновляется
    только отметка, чтобы кеш чтения не открывался на каждом чтении (#85). Строка без
    источника считается рангом 0 и принимает любое чтение.

    У DOCX страниц нет, весь текст отдаётся одной страницей с номером 1 (#42).
    """
    sha = doc["sha256"]
    cache = _text_cache_path(sha)
    fresh = fresh_text() and _fresh_once("text", sha)
    if not fresh and os.path.exists(cache):
        rows, stale = [], False
        with open(cache, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r.get("v") != TEXT_CACHE_VERSION or r.get("pf") != text_fingerprint():
                    stale = True       # кеш старого образца или собран прежним кодом обработки
                    break
                if r.get("s") in OFFICE_SOURCES and r.get("f") != OFFICE_TEXT_VERSION:
                    stale = True       # документ Word или Excel, разобранный прежним разбором
                    break
                rows.append((r["p"], r["t"], r.get("s") or "LAYER", r.get("l"), r.get("m"), r.get("rs")))
        if not stale:
            fresh, changed = [], False
            for page_no, text, source, layer, stamp, rs in rows:
                if source == "LAYER" and _may_be_scan(text):
                    got = _from_reading(sha, page_no, text)
                    if got:
                        layer, source, changed = text, "RECOGNIZED", True
                        text, stamp, rs = got
                elif source == "RECOGNIZED" and _read_stamp(sha, page_no) != stamp:
                    got = _from_reading(sha, page_no, layer or "")
                    if not got:        # распознанного больше нет — остаётся слой
                        text, source, layer, stamp, rs = layer or "", "LAYER", None, None, None
                    elif read_rank(got[2]) < read_rank(rs):
                        stamp = got[1]         # перечитали хуже: текст прежний, запомнить отметку
                    else:
                        text, stamp, rs = got
                    changed = True
                fresh.append((page_no, text, source, layer, stamp, rs))
            if changed:
                _write_text_cache(cache, fresh)
            yield from _view(fresh, scans)
            return
    ext = (doc.get("extension") or "").lower()
    if ext in (".docx",) + office_text.OFFICE_EXT:
        path = os.path.join(root, doc["relative_path"])
        text = docx_text(path) if ext == ".docx" else office_text.text(path)
        if not text:
            return
        source = ext[1:].upper()                       # DOCX, DOC, XLS, XLSX — видно в находке
        _write_text_cache(cache, [(1, text, source, None, None, None)])
        yield 1, text, source
        return
    raw = raw_layer(doc, root, fresh)
    if raw is None:
        # Файл не открылся — чаще всего неверный путь в реестре. Пустой кеш здесь
        # записывать нельзя: он пережил бы исправление пути, и текст документа
        # больше не появился бы никогда.
        return
    rows = []
    for page_no, t in raw:
        # кириллица, раскодированная не той кодовой страницей: для правил такая страница
        # была пустотой, хотя это не картинка, а неверная кодировка (#98)
        t = encoding.repair(t)[0]
        source, layer, stamp, rs = "LAYER", None, None, None
        if _may_be_scan(t):
            got = _from_reading(sha, page_no, t)
            if got:
                layer, source = t, "RECOGNIZED"
                t, stamp, rs = got
        rows.append((page_no, t, source, layer, stamp, rs))
    _write_text_cache(cache, rows)
    yield from _view(rows, scans)


def _layer_cache_path(sha):
    d = os.path.join(CACHE, "layer", sha[:2])
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, sha + ".jsonl")


def _pymupdf_version():
    import pymupdf
    return getattr(pymupdf, "VersionBind", None) or getattr(pymupdf, "__version__", "")


def raw_layer(doc, root, fresh=False):
    """Сырой текстовый слой PDF по страницам: [(страница, текст)], None — файл не открылся.

    Слой зависит только от байтов файла и версии PyMuPDF, поэтому хранится отдельно от
    обработанного текста (`.cache/layer`) и не стареет с кодом. Открыть PDF и вынуть слой —
    самая дорогая часть чтения: 5–10 мс на страницу, 7–12 минут на корпус (замер 24.09).
    Раньше любая правка обработки (починка кодировки, подстановка распознанного) требовала
    нового номера кеша текста, и корпус перечитывался из PDF целиком. Теперь обработка
    пересобирается из этого слоя, а PDF открывается только при `fresh` или новой PyMuPDF.
    """
    sha = doc["sha256"]
    cache = _layer_cache_path(sha)
    version = _pymupdf_version()
    if not fresh and os.path.exists(cache):
        try:
            with open(cache, encoding="utf-8") as f:
                head = json.loads(f.readline())
                rows = [json.loads(line) for line in f if line.strip()]
            if head.get("pymupdf") == version and head.get("n") == len(rows):
                return [(r["p"], r["t"]) for r in rows]
        except Exception:
            pass                       # испорченный кеш слоя — прочитать PDF заново
    import pymupdf
    # MuPDF печатает в stderr на каждый повреждённый шрифт; текст при этом
    # извлекается, а поток сообщений прячет настоящий вывод
    try:
        pymupdf.TOOLS.mupdf_display_errors(False)
    except Exception:
        pass
    out = []
    try:
        pdf = pymupdf.open(os.path.join(root, doc["relative_path"]))
        for i in range(pdf.page_count):
            try:
                t = pdf[i].get_text("text")
            except Exception:
                t = ""
            out.append((i + 1, t))
        pdf.close()
    except Exception:
        return None
    _write_atomic(cache, [{"pymupdf": version, "n": len(out)}] + [{"p": p, "t": t} for p, t in out])
    return out


def _write_atomic(path, rows):
    """Строки JSON в файл целиком или никак: кеш общий, его читают параллельные прогоны."""
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass


_TEXT_FP = None


def text_fingerprint():
    """Отпечаток кода, который из сырого слоя и кеша чтения делает текст страницы."""
    global _TEXT_FP
    if _TEXT_FP is None:
        from pipeline import fingerprint
        _TEXT_FP = fingerprint.closure_digest("matrix_rules", [fingerprint.top_level("matrix_rules")["page_texts_src"]])
    return _TEXT_FP


def _write_text_cache(path, rows):
    """Строки кеша текста. У страницы из распознанного — ещё её слой, отметка и источник кеша чтения."""
    with open(path, "w", encoding="utf-8") as f:
        for p, t, s, layer, stamp, rs in rows:
            row = {"v": TEXT_CACHE_VERSION, "pf": text_fingerprint(), "p": p, "t": t, "s": s}
            if s in OFFICE_SOURCES:
                row["f"] = OFFICE_TEXT_VERSION
            if s == "RECOGNIZED":
                row.update(l=layer or "", m=stamp, rs=rs or "")
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def page_texts(doc, root, scans=True):
    """Текст всех страниц документа: (страница, текст). Источник и `scans` — в `page_texts_src`."""
    for page_no, text, _ in page_texts_src(doc, root, scans):
        yield page_no, text


# ---------- извлечение ----------

def _class_token(text, classes):
    """Первый класс из перечня после подписи. Омоглифы сводятся к одному алфавиту:
    в документах «С0» пишут и кириллицей, и латиницей, а «I» путают с «l» и «1»."""
    t = text.replace("C", "С").replace("c", "с")
    for token in sorted(classes, key=len, reverse=True):
        tok = token.replace("C", "С")
        if re.match(r"\s*[—–:\-]?\s*" + re.escape(tok) + r"(?![A-Za-zА-Яа-я+0-9])", t):
            return token
    # категория надёжности часто цифрой: «II категории» и «2 категории»
    m = re.match(r"\s*[—–:\-]?\s*([1-3])(?!\d)", t)
    if m and classes and classes[0] == "I":
        return ["I", "II", "III"][int(m.group(1)) - 1]
    return None


LIST_TAIL = 260          # перечень частей здания после подписи — до следующей подписи «Класс …»


def _class_list(text, classes):
    """Классы из перечня частей здания после подписи, или [].

    ПЗ, АР1 и КР1 Октябрьской: «Степень огнестойкости: - поземная автостоянка – I (первая); - Жилые
    секции (Корпуса 1 и 2) высотой более 50 м (не более 75 м) – I (первая); Класс конструктивной…».
    Первый класс здесь не сразу за подписью, и `_class_token` его не видел, а в пустоту вставала
    степень огнестойкости подстанции из сертификата в приложении. Перечень узнаётся по двоеточию и
    тире после подписи; класс — за тире у каждой части.
    """
    if not classes or not re.match(r"\s*:\s*[-–—−•]", text):
        return []
    body = re.split(r"\bкласс\w*\b", text, maxsplit=1, flags=re.I)[0]
    found = []
    for m in re.finditer(r"[-–—−]\s*(IV|V|I{1,3})(?=\s*(?:\(|;|,|\.|$))", body):
        if m.group(1) in classes and m.group(1) not in found:
            found.append(m.group(1))
    return found


def _document_allowed(rule, doc):
    """Документ из раздела, откуда правило берёт значение этой стадии (поле `documents`, #145).

    `documents` — шаблон имени файла по стадиям: {"PD": "ИОС\\s?3", "RD": "ВК|НК"}. Стадии без
    шаблона не ограничены. Это жёсткий отбор, а не предпочтение источника (`source_names`):
    на планах заземления ЭОМ Полярной 16 выпуски канализации подписаны наружным диаметром
    трубы, и запасным источником они не годятся.
    """
    pats = rule.get("documents")
    if not pats or not doc:
        return True
    pat = pats.get(STAGE.get(doc.get("stage")))
    return pat is None or bool(re.search(pat, os.path.basename(doc.get("relative_path") or ""), re.I))


def _foreign_context(rule, flat, start, end, doc):
    """Подпись стоит в чужом тексте, и значение за ней — не значение объекта (#109).

    Правило задаёт это полем `context_exclude`: слова, окно до и после подписи и стадии,
    где проверять. Подпись своей строки для этого мала: на ярлыке упаковки в ИД кровли
    ДОО «Количество мест 400 Дата изготовления…» чужое стоит за значением, а в копии
    условий подключения в рабочей стадии «…земельного участка заявителя… 3. Максимальная
    тепловая нагрузка: 24,376 Гкал/час» — в предыдущем пункте.
    """
    ctx = rule.get("context_exclude")
    if not ctx:
        return False
    if ctx.get("stages") and STAGE.get((doc or {}).get("stage")) not in ctx["stages"]:
        return False
    around = flat[max(0, start - ctx.get("before", 0)):end + ctx.get("after", 0)]
    return any(re.search(p, around, re.I) for p in ctx["patterns"])


def extract(rule, text, classes=None, doc=None, page_no=None):
    """Кандидаты значения показателя на одной странице."""
    if rule.get("kind") in ROOM_KINDS:
        return []          # сравнение по помещениям читает таблицы листов само, не по тексту страницы (#37)
    if rule.get("kind") == "element_class":
        flat = tep.flatten(text)
        as_built = (doc or {}).get("stage") == "ID"
        found = elements.concrete_classes(flat, (doc or {}).get("relative_path", ""), as_built=as_built)
        if as_built:
            # протокол испытаний бетона читается ещё и построчно: конструкция, отметка и класс
            # в одной строке таблицы, слова «бетон» при классе нет (#62). Общий разбор при этом
            # остаётся: акт с реестром приложений тоже поминает «протокол испытаний №», а класс
            # в нём стоит при марке смеси
            found += test_protocols.protocol_classes(flat)[0]
        return [{"value": c["value"], "raw": c["raw"], "columns": [c["raw"]], "label": c["location"],
                 "location": c["location"], "binding": c["binding"], "snippet": c["snippet"],
                 **({"source": c["source"]} if c.get("source") else {}),
                 **({"share": c["share"]} if c.get("share") is not None else {}),
                 **({"vf": c["vf"]} if c.get("vf") else {}),
                 **({"age_days": c["age_days"]} if c.get("age_days") is not None else {})}
                for c in found]
    if rule.get("kind") in ("switchboard_breakers", "switchboard_cables", "switchboard_fire_cables"):
        out = []
        for row in switchboards.group_rows(tep.flatten(text)):
            if rule["kind"] == "switchboard_breakers" and row["breaker"]:
                label = row["breaker"]["raw"]
                out.append({"key": row["group"], "value": label, "raw": label, "columns": [label],
                            "label": row["group"], "snippet": row["snippet"]})
            elif rule["kind"] != "switchboard_breakers" and row["cables"]:
                specs = sorted({c["raw"] for c in row["cables"]})
                out.append({"key": row["group"], "value": tuple(specs), "raw": ", ".join(specs), "columns": specs,
                            "label": row["group"], "cables": row["cables"], "snippet": row["snippet"]})
        return out
    if rule.get("kind") == "smoke_fans":
        return [{"key": f["system"], "value": (f["flow"], f["pressure"]), "raw": f["raw"], "columns": [f["raw"]],
                 "label": f["system"], "calc": f["calc"], "snippet": f["snippet"]}
                for f in smoke_fans.fan_duties(tep.flatten(text))]
    if rule.get("kind") == "mgn_toilet_area":
        return [{"key": r["room"], "value": r["area"], "raw": r["raw"], "columns": [r["raw"]],
                 "label": r["name"], "snippet": r["snippet"]}
                for r in mgn_rooms.toilet_areas(tep.flatten(text))]
    if rule.get("kind") == "light_sources":
        return [{**x, "columns": [x["raw"]], "label": "освещение"} for x in lighting.light_sources(tep.flatten(text))]
    if rule.get("kind") == "resource_meters":
        return [{**x, "columns": [x["raw"]], "label": x["key"]} for x in metering.meters(tep.flatten(text))]
    if rule.get("kind") == "fire_jets":
        return [{**j, "columns": [j["raw"]], "label": "ВПВ"} for j in fire_water.jet_cases(tep.flatten(text))]
    if rule.get("kind") == "vlm_value":
        # значение живёт в графике: его читает отдельный проход модели (pipeline/vlm_values.py,
        # команда `vlm`), а здесь оно берётся из его файла. В прогоне правил модель не
        # вызывается вовсе (#98). Проход модели — добавка к тексту, а не замена ему: на
        # Алтуфьевском уклон кровли назван и текстом пояснительной записки (1,7 %), и
        # подписями на плане, и текст — доказательство лучше, поэтому берётся и то и то
        got = []
        # `labels_stages` — стадии, где подписи текста читаются: у ширины дверей (ODI-117, PPM-105)
        # подпись «ширина в свету не менее …» — требование ПД, а в спецификации РД та же фраза —
        # норма, одна у дверей разного размера (Р-91, п. 2); ширины РД даёт только чертёж (#145)
        text_stages = rule.get("labels_stages")
        if rule.get("labels") and (not text_stages or STAGE.get((doc or {}).get("stage")) in text_stages):
            got = tep.find_values(text, rule["labels"], rule.get("exclude", []),
                                  rule.get("rule", "first"), unit=rule.get("unit"))
            # Пределы параметра (`vlm.value_range`) — для значения из текста так же, как для ответа
            # модели: у Полярной 17 подпись «шахт… толщин…» в томе ТХ.ВТ поймала «в лифтовой шахте
            # использовать стальную полосу толщиной 4мм», и толщина стен ядра вышла 4 мм (#229)
            got = [c for c in got if in_value_range(c.get("value"), rule)]
        want_stage = (rule.get("vlm") or {}).get("stage") or "RD"
        want_stage = {want_stage} if isinstance(want_stage, str) else set(want_stage)
        # ответ модели берётся только с листа, который несёт признак предмета (`vlm.page_requires`): у
        # подступенка — не лист армирования без подписи проступи. На КЖ0.6 лестниц Октябрьской «15х200=3000» —
        # шаг стержней (специалист, R4-H03), а на листе стальной лестницы КМ1.1 Полярной 16 «4х150=600» —
        # подступенок, хотя проступь там не подписана
        need = (rule.get("vlm") or {}).get("page_requires")
        if (doc or {}).get("stage") in want_stage and (not need or re.search(need, text, re.I)):
            got = got + vlm_candidates(rule, doc, page_no)
        if rule.get("elements") == "roof_insulation":
            # утеплитель кровли по элементу (ZU-128, #137): лифтовые шахты, рампа, стилобат. Эти
            # кандидаты помечены: в сравнение набором они не идут, их сравнивает roof_elements()
            for e in layers.roof_insulation(text):
                shown = f"{e['material']} {e['mm']:g} мм".replace(".", ",")
                got.append({"key": e["key"], "element": True, "value": shown, "raw": shown, "columns": [shown],
                            "label": e["key"], "mm": e["mm"], "material": e["material"], "mark": e["mark"],
                            "snippet": e["snippet"]})
        return got
    if rule.get("kind") == "fire_barrier_limits":
        # предел огнестойкости преград по местам (PPM-103, #93): ключ — место и вид преграды,
        # значение — минуты с набором критериев. Разбор — pipeline/fire_doors.py
        flat = tep.flatten(text)
        out = []
        for row in fire_doors.limits(flat, elements.clause_bounds):
            if not row["place"] and not row["mark"]:
                continue          # ни места, ни марки: ни сравнить, ни пояснить
            # утверждение без места в сравнение не идёт, но его марка нужна в пояснении:
            # «одна марка, три предела» — это и есть довод против ключа по марке (#93)
            key = (fire_doors.key_of(row["place"], row["kind"]) if row["place"]
                   else fire_doors.NO_PLACE_KEY)
            out.append({"key": key, "value": fire_doors.value_of(row), "raw": row["raw"],
                        "columns": [row["raw"]], "label": key, "mark": row["mark"],
                        "atleast": row["atleast"], "snippet": row["snippet"]})
        return out
    if rule.get("kind") == "booster_pumps":
        # повысительные установки хоз-питьевого водоснабжения (IOS2-073, #135): pipeline/pumps.py
        return [{"key": c["key"], "value": (c["model"], c["flow"], c["head"], c["point"]), "raw": c["raw"],
                 "columns": [c["raw"]], "label": c["key"], "zone": c["zone"], "model": c["model"],
                 "snippet": c["snippet"]}
                for c in pumps.installations(tep.flatten(text))]
    if rule.get("kind") == "layer_stack":
        # составы по слоям (#137): дорожная одежда SPZU-032, кровля AR-044 — pipeline/layers.py.
        # Разбор читает строки страницы, поэтому текст не сплющивается. Расчётное обоснование
        # на той же странице делает изменение делом инспектора, а не правила
        justified = bool(layers.JUSTIFIED.search(text))
        out = []
        profile = rule.get("profile") or "pavement"
        for st in layers.stacks(text, profile):
            # у утеплителя стен значение — набор толщин утеплителя («50 + 130 мм»), ZU-125
            shown = layers.combo(st["layers"]) if profile == "wall" else layers.show(st["layers"])
            out.append({"key": st["key"] or "", "value": shown, "raw": shown, "columns": [shown],
                        "label": st["key"] or "состав", "purpose": st["purpose"], "layers": st["layers"],
                        "form": st.get("form"), "justified": justified, "snippet": st["snippet"]})
        return out
    if rule.get("kind") == "apartment_mix":
        # квартирография PZ-011 (#138): ТЭП записки, строки таблицы «Квартирография жилого дома»
        # и ссылка РД на стадию ПД с положительным заключением — pipeline/apartment_mix.py
        out = []
        tep_counts = apartment_mix.tep_counts(text)
        if tep_counts:
            shown = apartment_mix.show(tep_counts)
            out.append({"key": "tep", "value": shown, "raw": shown, "columns": [shown], "label": "ТЭП",
                        "counts": tep_counts, "snippet": shown})
        rows = apartment_mix.table_rows(text)
        if rows:
            counts = collections.Counter()
            for r in rows:
                counts[r["type"]] += r["count"]
            shown = apartment_mix.show(dict(counts))
            out.append({"key": "table", "value": shown, "raw": shown, "columns": [shown], "label": "квартирография",
                        "counts": dict(counts), "renamed": sum(r["count"] for r in rows if r["renamed"]),
                        "snippet": "; ".join(f"{r['label'][-40:]} {r['mark']}: {r['count']}" for r in rows[:4])})
        ref = apartment_mix.PD_REFERENCE.search(text) if re.search(r"квартирограф", text, re.I) else None
        if ref:
            quote = re.sub(r"\s+", " ", ref.group(0)).strip()
            out.append({"key": "reference", "value": quote, "raw": quote, "columns": [quote], "label": "ссылка на ПД",
                        "snippet": quote})
        return out
    if rule.get("kind") == "sewer_outlets":
        # выпуски канализации по обозначению (IOS3-074, #145): только разделы водоотведения —
        # на планах ЭОМ и ЭН те же выпуски подписаны наружным диаметром трубы
        if not _document_allowed(rule, doc):
            return []
        return [{"key": r["outlet"], "value": r["diameter"], "raw": r["raw"], "columns": [r["raw"]],
                 "label": r["outlet"], "snippet": r["snippet"]}
                for r in outlets.outlet_labels(tep.flatten(text))]
    if rule.get("kind") == "outdoor_fire_water":
        # расход на наружное пожаротушение здания и число гидрантов (PPM-114, #145)
        if not _document_allowed(rule, doc):
            return []
        flat = tep.flatten(text)
        out = [{"key": outdoor_water.FLOW_KEY, "value": f["value"], "raw": f["raw"], "columns": [f["raw"]],
                "label": outdoor_water.FLOW_KEY, "building": f["building"], "snippet": f["snippet"]}
               for f in outdoor_water.flows(flat)]
        out += [{"key": outdoor_water.HYDRANT_KEY, "value": h["value"], "raw": h["raw"], "columns": [h["raw"]],
                 "label": outdoor_water.HYDRANT_KEY, "existing": h["existing"], "snippet": h["snippet"]}
                for h in outdoor_water.hydrants(flat)]
        return out
    if rule.get("kind") == "steel_protection":
        # огнезащита и антикоррозия стальных конструкций (KR-066, #145): pipeline/steel_protection.py
        if not _document_allowed(rule, doc):
            return []
        flat = tep.flatten(text)
        out = [{"key": "fire", "value": f"{f['kind']}:{f['element'] or ''}:{f['value'] or ''}", "raw": f["raw"],
                "columns": [f["raw"]], "label": f["element"] or "огнезащита", "location": f["element"],
                "statement": f["kind"], "element": f["element"], "limit": f["value"], "snippet": f["snippet"]}
               for f in steel_protection.fire_statements(flat)]
        out += [{"key": "coat", "value": c["raw"], "raw": c["raw"], "columns": [c["raw"]],
                 "label": "антикоррозионная защита", "location": "антикоррозионная защита",
                 "system": {k: c[k] for k in ("primer", "enamel", "layers", "microns")}, "snippet": c["snippet"]}
                for c in steel_protection.coating_systems(flat)]
        return out
    if rule.get("kind") == "finish_fire_class":
        # класс КМ отделки на путях эвакуации (PPM-107, #145): требования ПД и классы РД —
        # pipeline/finish_classes.py; какая сторона что берёт, решает построитель записи
        if not _document_allowed(rule, doc):
            return []
        flat = tep.flatten(text)
        out = [{"key": f"{r['group']}: {r['surface']}", "value": r["value"], "raw": r["raw"], "columns": [r["raw"]],
                "label": f"{r['group']}: {r['surface']}", "form": r["form"], "group": r["group"],
                "surface": r["surface"], "snippet": r["snippet"]}
               for r in finish_classes.requirements(flat)]
        out += [{"key": c["mark"] or c["room"], "value": c["value"], "raw": c["raw"], "columns": [c["raw"]],
                 "label": c["mark"] or c["room"], "form": c["form"], "group": c["group"], "mark": c["mark"],
                 "room": c["room"], "snippet": c["snippet"]}
                for c in finish_classes.rd_classes(flat)]
        return out
    if rule.get("kind") == "window_schedule":
        # окна по ведомостям (AR-046, #193): pipeline/windows.py; тома АР. Лист-ведомость — свой кандидат:
        # без ведомости в ПД сравнения нет (решение специалиста)
        if (doc or {}).get("section") != "AR":
            return []
        flat = tep.flatten(text)
        title = windows.schedule(flat)
        if not title:
            return []
        out = [{"form": "schedule", "key": "ведомость", "value": title, "raw": title, "columns": [title],
                "label": "ведомость окон", "location": "ведомость", "snippet": title}]
        out += [{"form": "row", "key": r["mark"], "value": r["n"], "raw": f"{r['mark']} {r['w']}х{r['h']} — {r['n']} шт.",
                 "columns": [r["mark"]], "label": r["mark"], "location": r["mark"], "w": r["w"], "h": r["h"],
                 "snippet": f"{r['mark']} {r['w']}х{r['h']}(h) {r['n']}"} for r in windows.rows(flat)]
        return out
    if rule.get("kind") == "deformation_joints":
        # деформационные швы (KR-063, #192): pipeline/joints.py; только тома КР. Схема плиты или вертикальных
        # конструкций — свой кандидат: на ней отсутствие шва уже вывод (решение специалиста)
        if (doc or {}).get("section") != "KR":
            return []
        flat = tep.flatten(text)
        out = [dict(c, form="joint", columns=[c["raw"]], label="деформационный шов", location="шов")
               for c in joints.statements(flat)]
        title = joints.schemes(flat)
        if title:
            out.append({"form": "scheme", "key": "схема", "value": title, "raw": title, "columns": [title],
                        "label": "схема", "location": "схема", "snippet": title})
        return out
    if rule.get("kind") == "door_opening":
        # направление открывания дверей (AR-043, #191): двери — ответами прохода модели по планам,
        # требование проекта — текстом записки («двери на путях эвакуации открываются по направлению выхода»)
        out = []
        if STAGE.get((doc or {}).get("stage")) == "PD":
            flat = tep.flatten(text)
            out += [{"form": "requirement", "key": DOOR_REQUIREMENT_KEY, "value": "по ходу", "raw": m.group(0)[:160],
                     "columns": ["по ходу"], "label": "требование", "location": "требование",
                     "snippet": " ".join(flat[max(0, m.start() - 30):m.end() + 30].split())}
                    for m in DOOR_REQUIREMENT.finditer(flat)]
        return out + vlm_door_candidates(rule, doc, page_no)
    if rule.get("kind") == "alarm_capacity":
        # состав и ёмкость АПС (IOS5-080, #190): адресные устройства спецификации и метки ЗКПС со схем,
        # pipeline/detectors.py. Вид кандидата — «место» значения
        if not detectors.doc_allowed(doc):
            return []
        flat = tep.flatten(text)
        out = [dict(r, form="device", columns=[r["raw"]], label=r["key"], location=r["key"])
               for r in detectors.device_rows(flat)]
        # пожарные извещатели страницы — признак тома АПС: адресные устройства берутся только из таких томов
        out += [dict(r, form="detector", columns=[r["raw"]], label=r["key"], location=f"извещатели: {r['key']}")
                for r in detectors.rows(flat)]
        out += [{"form": "zone", "key": "ЗКПС", "value": z, "raw": f"ЗКПС {z}", "columns": [f"ЗКПС {z}"], "label": "ЗКПС",
                 "location": "ЗКПС", "snippet": " ".join(flat[:160].split())} for z in detectors.zones(flat)]
        return out
    if rule.get("kind") == "detector_count":
        # число пожарных извещателей по видам из спецификаций (PPM-108, #189): pipeline/detectors.py. Вид
        # извещателя — «место» значения: конфликт редакций считается по виду
        if not detectors.doc_allowed(doc):
            return []
        return [dict(r, columns=[r["raw"]], label=r["key"], location=r["key"]) for r in detectors.rows(tep.flatten(text))]
    if rule.get("kind") == "insulation_lambda":
        # λ утеплителя наружных стен и марки утеплителя (ZU-126, #188): pipeline/insulation.py. Вид кандидата —
        # «место» значения: конфликт редакций считается отдельно по λ и по маркам каждого вида утеплителя
        if not insulation.doc_allowed(doc):
            return []
        flat = tep.flatten(text)
        out = [dict(c, form="lambda", columns=[c["raw"]], label=c["key"], location=f"λ: {c['key']}")
               for c in insulation.statements(flat)]
        out += [dict(p, form="product", value=p["product"], raw=p["product"], columns=[p["product"]], label=p["key"],
                     location=f"марка: {p['key']}")
                for p in insulation.products(flat)]
        return out
    if rule.get("kind") == "construction_duration":
        # срок строительства в ПОС, ООС и ППР (POS-082, #187): pipeline/durations.py. Раздел документа
        # идёт в кандидата: сравниваются ПОС и ООС одной, проектной стадии. Ключ (срок или подготовительный
        # период) — «место» значения: конфликт редакций считается по ключу, а не по смеси двух сроков
        part = durations.part_of(doc)
        if not part:
            return []
        return [dict(c, part=part, columns=[c["raw"]], label=c["key"], location=c["key"])
                for c in durations.statements(tep.flatten(text))]
    # перечень видов — литералом, а не SITE_PARSERS: отпечаток кода (`fingerprint.kind_digests`) узнаёт ветку
    # вида только по литералу или множеству-константе, и ветка по словарю стала бы общей для всех видов
    if rule.get("kind") in ("crane_zones", "pit_edge_limits", "collapse_zone", "demolition_methods", "build_technology"):
        # стройплощадка и снос (POS-081, POS-085, POD-090, POD-091, POS-087, #145): pipeline/site_works.py
        if not _document_allowed(rule, doc):
            return []
        got = getattr(site_works, SITE_PARSERS[rule["kind"]][0])(tep.flatten(text))
        return [dict(c, columns=[c["raw"]], label=c["key"]) for c in got]
    if rule.get("kind") in ("pipe_materials", "facade_colors", "slope_range", "material_takeoff"):
        # черновики шестого круга: материал труб по участку (IOS2-072, IOS3-075), цвет элементов фасада
        # (AR-052), уклоны по плану (SPZU-033), объём бетона по элементу (KR-067); запись строит set_findings
        if not _document_allowed(rule, doc):
            return []
        flat = tep.flatten(text)
        if rule["kind"] == "pipe_materials":
            got = pipe_materials.materials(flat, rule.get("system") or pipe_materials.WATER)
        else:
            got = getattr(DRAFT_PARSERS[rule["kind"]][0], DRAFT_PARSERS[rule["kind"]][1])(flat)
        if rule["kind"] == "slope_range" and doc is not None and STAGE.get(doc.get("stage")) != "PD":
            # предел нормы — только из ПД: требование в РД не проектное решение рабочей стадии
            got = [c for c in got if not c.get("norm")]
        return [dict(c, columns=[c["raw"]], label=c.get("label") or c["key"]) for c in got]
    if rule.get("kind") == "soue_type":
        # тип СОУЭ (PPM-110, #145): pipeline/alarms.py; сравнение — обычное, `decide`
        if not _document_allowed(rule, doc):
            return []
        return [dict(c, columns=[c["value"]], label="тип СОУЭ") for c in alarms.soue_types(tep.flatten(text))]
    if rule.get("kind") == "riser_diameters":
        return [{"key": r["riser"], "value": r["diameter"], "raw": r["raw"], "columns": [r["raw"]],
                 "label": r["riser"], "snippet": r["snippet"]}
                for r in risers.riser_labels(tep.flatten(text))]
    if rule.get("kind") == "element_rebar_class":
        # класс рабочей арматуры по элементам (KR-057): назначение решает, что сравнивать,
        # разбор — pipeline/rebar.py. В исполнительной стадии назначения нет, класс берётся
        # как применённый по акту
        flat = tep.flatten(text)
        as_built = (doc or {}).get("stage") == "ID"
        found = rebar.working(rebar.rebar_classes(flat, doc, as_built=as_built))
        return [{"value": c["value"], "raw": c["raw"], "columns": [c["raw"]], "label": c["location"],
                 "location": c["location"], "binding": c["binding"], "purpose": c["purpose"],
                 "snippet": c["snippet"]}
                for c in found]
    if rule.get("kind") == "element_steel_grade":
        # марка стали по металлическим элементам (KR-056): разбор — pipeline/steel.py.
        # Значение сравнения — (прочность марки в МПа, обозначение): две марки бывают равной
        # прочности («С245» и «Ст20»), и сравнивать надо и прочность, и сам набор марок
        flat = tep.flatten(text)
        return [{"value": (c["value"], c["raw"]), "raw": c["raw"], "columns": [c["raw"]],
                 "label": c["location"], "location": c["location"], "binding": c["binding"],
                 "snippet": c["snippet"]}
                for c in steel.grades(flat, doc, elements.clause_bounds)]
    if rule.get("kind") == "element_thickness":
        flat = tep.flatten(text)
        element = rule["element"]
        if element in elements.ZONED:
            # Толщина диска перекрытия по частям здания (KR-059, #92). Часть здания входит
            # в локацию; сказанное о перекрытиях без части здания идёт в обе, как у класса
            # бетона (#52), но с привязкой SHEET, а не CLAUSE: толщина у перекрытия своя
            # на каждом уровне, и значение без уровня — запасной источник. Иначе «t=180»
            # из условных обозначений листа армирования у Октябрьской объявляло понижение
            # проектных 200 мм плиты покрытия на отм. +60,52
            out = []
            for values, snippet, zone, form in elements.slab_thickness(flat):
                locations = elements.location_names(element, zone)
                # вердикт выдаётся только по прозе с названным уровнем: подпись участка
                # схемы армирования («t=180») и толщина без уровня — запасной источник.
                # Иначе наименьший участок рабочей стадии объявляет понижение: на Речникове
                # так выходило «250 мм → 200/250/300/350 мм», хотя это разные участки
                strong = form == "prose" and zone and zone != elements.MIXED
                binding = "CLAUSE" if strong else "SHEET"
                # «плиты перекрытия −1 этажа толщиной 350, 250, 200 мм» — перечень толщин без границ
                # плит: какая плита какой толщины, по фразе не сказать (#136)
                enumerated = form == "prose" and len(values) > 1
                for location in locations:
                    out += [{"value": v, "raw": str(v), "columns": [str(v)], "label": location,
                             "location": location, "binding": binding, "snippet": snippet,
                             **({"enumerated": True} if enumerated else {})}
                            for v in values]
            return out
        return [{"value": v, "raw": str(v), "columns": [str(v)], "label": element,
                 "location": element, "binding": "CLAUSE", "snippet": snippet}
                for values, snippet in elements.plate_thickness(flat) for v in values]
    if rule.get("kind") == "schedule_sum":
        rows = tep.schedule_rows(text, rule["header"])
        if not rows:
            return []
        got = tep.schedule_sum(text, rule["header"], rule["row"], rule.get("exclude", []))
        if got is None:
            # Строк такого покрытия в ведомости нет — это «не найдено», а не ноль.
            # Сначала здесь стоял ноль, из рассуждения «ведомость перечисляет все
            # покрытия». Рассуждение оказалось неверным: в третьей корректировке
            # ПЗУ Речникова строки асфальтобетона нет, хотя в исходном томе и в
            # первой корректировке она есть, 129 м², и легенды чертежей той же
            # третьей корректировки асфальтовые проезды показывают. Рабочая стадия
            # совпадает с исходным проектом, а ложное нарушение «0 → 129» получилось
            # из пропуска строки в новой редакции ведомости.
            return []
        return [{"value": got["value"], "raw": got["raw"], "columns": got["columns"],
                 "label": "ведомость", "rows": got.get("rows", []),
                 "snippet": "; ".join(f"{n[-48:]} — {v}" for n, v in got.get("rows", [])[:4])
                            or "строк такого покрытия в ведомости нет"}]
    if rule.get("kind") == "schedule_positions":
        got = tep.schedule_positions(text, rule["header"])
        if got is None:
            return []
        count, snippet = got
        # подпись к числу добавляет запись находки: у правила своя, по числу — «позиция МАФ»,
        # «позиций МАФ» (`display_unit`, Р-73), вместо каталожной «шт. / компл.»; здесь только число
        return [{"value": float(count), "raw": str(count), "columns": [str(count)],
                 "label": rule.get("element", "ведомость"), "location": rule.get("element"),
                 "binding": "CLAUSE", "snippet": snippet}]
    if rule.get("kind") == "item_height":
        got = tep.item_with_height(text, rule["row"])
        if got is None:
            return []
        row, height, length = got
        raw = f"h={str(height).replace('.', ',')} м" + (f"; {length}" if length is not None else "")
        return [{"value": height, "raw": raw, "columns": [row],
                 "label": rule.get("element", "строка перечня"), "location": rule.get("element"),
                 "binding": "CLAUSE", "snippet": row}]
    if rule.get("kind") == "feature_presence":
        # раздел-источник, если правило его задаёт (#145): «защита сетей» из ПОС, а не из ЭОМ
        if not _document_allowed(rule, doc):
            return []
        names = tep.features_named(text, [(f["name"], f["pattern"]) for f in rule["features"]])
        if not names:
            return []
        return [{"value": float(len(names)), "raw": "PRESENT", "columns": sorted(names),
                 "label": rule.get("element", "наличие"), "location": rule.get("element"),
                 "binding": "CLAUSE", "snippet": "названы: " + ", ".join(sorted(names))}]
    if rule.get("kind") == "class":
        flat = tep.flatten(text)
        out = []
        for pat in rule["labels"]:
            for m in re.finditer(pat, flat, re.I):
                ctx = flat[max(0, m.start() - 40):m.end() + 60]
                if any(re.search(x, ctx, re.I) for x in rule.get("exclude", [])):
                    continue
                if _foreign_context(rule, flat, m.start(), m.end(), doc):
                    continue
                direct = _class_token(flat[m.end():m.end() + 40], classes or [])
                tokens = [direct] if direct else _class_list(flat[m.end():m.end() + LIST_TAIL], classes or [])
                tail = 60 if direct else LIST_TAIL
                for token in tokens:
                    out.append({"value": token, "columns": [token], "raw": token,
                                "label": m.group(0),
                                "snippet": flat[max(0, m.start() - 30):m.end() + tail]})
        return out
    found = tep.find_values(text, rule["labels"], rule.get("exclude", []),
                            rule.get("rule", "first"), rule.get("exclude_unless_header", []),
                            unit=rule.get("unit"), max_columns=rule.get("max_columns"))
    if rule.get("context_exclude") and found:
        flat = tep.flatten(text)
        found = [c for c in found if not _foreign_context(rule, flat, c["pos"], c["pos"] + len(c["label"]), doc)]
    return found


_VLM_BY_OBJECT = {}
_VLM_DIGEST = {}


def vlm_digest(doc, out=None, provisional=False):
    """Отпечаток ответов модели по этому документу. None, если их нет (#98).

    Кеш кандидатов адресован документом и правилами, а значения с чертежей живут в стороне —
    в `build/<объект>/vlm_values.jsonl`. Без отпечатка прогон правил после прохода модели
    отвечал старым кешем: проход уже прочитал уклоны, а находки их не видели. Документы,
    по которым проход ничего не дал, отпечатка не получают — иначе правка прохода на одном
    листе обнуляла бы кеш всего корпуса. У черновиков правил (#95) свой файл ответов — и свой
    отпечаток: иначе прогон черновиков после прохода отвечал бы кешем, собранным до него.
    """
    object_id = (doc or {}).get("object_id")
    file_id = (doc or {}).get("file_id")
    if not object_id or not file_id:
        return None
    key = (object_id, out, bool(provisional))
    if key not in _VLM_DIGEST:
        from pipeline import vlm_values
        by_file = collections.defaultdict(list)
        for row in vlm_values.load(object_id, out=out or OUT, provisional=bool(provisional)):
            key = (row.get("parameter_code"), row.get("pdf_page_number"), tuple(row.get("values") or ()))
            if row.get("doors"):
                # двери с направлением открывания (AR-043): без них отпечаток у строк прежний
                key += (json.dumps(row["doors"], ensure_ascii=False, sort_keys=True),)
            by_file[row.get("file_id")].append(key)
        _VLM_DIGEST[key] = {fid: hashlib.sha256(
            json.dumps(sorted(rows), ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
            for fid, rows in by_file.items()}
    return _VLM_DIGEST[key].get(file_id)


def in_value_range(value, rule):
    """Число в правдоподобных пределах параметра (`vlm.value_range`); не число и правило без пределов — да."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return True
    lo, hi = ((rule.get("vlm") or {}).get("value_range") or [None, None])[:2]
    return (lo is None or value >= lo) and (hi is None or value <= hi)


def vlm_candidates(rule, doc, page_no, out=None):
    """Кандидаты из файла прохода модели для этой страницы (#98).

    Значение, прочитанное моделью, помечается `text_source: RECOGNIZED`: по Р-40 и #48 такое
    значение не решает молча — нарушение по нему требует подтверждения инспектором. Ответ,
    который не подтвердился собственным текстом страницы, проход в файл не пишет вовсе.
    """
    object_id = (doc or {}).get("object_id")
    code = rule.get("code") or rule.get("parameter_code")
    if not object_id or page_no is None:
        return []
    provisional = bool(rule.get("provisional"))
    key = (object_id, out, provisional)
    if key not in _VLM_BY_OBJECT:
        from pipeline import vlm_values
        # черновик правила (#95) читает свой файл ответов, прод-правило — прод-файл
        rows = vlm_values.load(object_id, out=out or OUT, provisional=provisional)
        by_page = collections.defaultdict(list)
        for row in rows:
            by_page[(row.get("parameter_code"), row.get("file_id"), row.get("pdf_page_number"))].append(row)
        _VLM_BY_OBJECT[key] = by_page
    by_page = _VLM_BY_OBJECT[key]
    got = by_page.get((code, (doc or {}).get("file_id"), page_no)) or []
    unit = rule.get("unit")
    out_rows = []
    for row in got:
        for value in row.get("values") or []:
            shown = f"{value:g}".replace(".", ",")
            confirm = {"layer": "подтверждено текстовым слоем листа",
                        "tesseract": "подтверждено распознаванием листа"}.get(row.get("confirmed_by"), "")
            what = row.get("what") or "значение"
            snippet = f"{what} по подписи на чертеже: {shown}{' ' + unit if unit else ''}" \
                      f" — прочитано моделью{', ' + confirm if confirm else ''}"
            out_rows.append({"value": value, "raw": f"{shown} {unit}".strip() if unit else shown,
                             "columns": [shown], "label": row.get("what") or "чертёж",
                             "snippet": snippet,
                             "text_source": "RECOGNIZED",
                             # значение дала модель, а не текст листа: так гипотеза по чертежу
                             # называет причину верно (`drawing_hypothesis`, #229)
                             "from_model": True,
                             **({"unit": unit, "unit_to": unit} if unit else {})})
    return out_rows


# требование проекта к дверям на путях эвакуации — текстом: «двери эвакуационных выходов и другие двери
# на путях эвакуации открываются по направлению выхода из здания» (ДОО, Новослободская), «Двери
# открываются по ходу эвакуации» (Алтуфьевское). «Двери должны открываться наружу» без слова о выходе —
# не требование к эвакуации: так пишут и о кабине МГН, и о машинном помещении
DOOR_REQUIREMENT = re.compile(r"двер\w*[^.;]{0,160}?открыва\w*[^.;]{0,40}?"
                              r"(?:по\s+направлени\w*\s+(?:выхода|эвакуац\w*)|по\s+ходу\s+эвакуац\w*)", re.I)
DOOR_REQUIREMENT_KEY = "двери на путях эвакуации"


def door_key(door):
    """Ключ двери для сравнения стадий: марка без пробелов и дефисов («Д-1» → «Д1»), иначе помещение."""
    if door.get("mark"):
        return re.sub(r"[\s\-‑–]", "", door["mark"]).upper()
    return " ".join((door.get("room") or "").split()).lower()


def vlm_door_candidates(rule, doc, page_no, out=None):
    """Двери с направлением открывания из файла прохода модели для этой страницы (AR-043, #191).

    Направление прочитано моделью по условному знаку — `text_source: RECOGNIZED`: решает инспектор.
    """
    object_id = (doc or {}).get("object_id")
    code = rule.get("code") or rule.get("parameter_code")
    if not object_id or page_no is None:
        return []
    provisional = bool(rule.get("provisional"))
    key = (object_id, out, provisional)
    if key not in _VLM_BY_OBJECT:
        vlm_candidates(rule, doc, page_no, out)          # заполняет _VLM_BY_OBJECT
    rows = _VLM_BY_OBJECT.get(key, {}).get((code, (doc or {}).get("file_id"), page_no)) or []
    found = []
    for row in rows:
        for d in row.get("doors") or []:
            name = d.get("mark") or d.get("room")
            where = f"{d['mark']}, {d['room']}" if d.get("mark") and d.get("room") else name
            found.append({"form": "door", "key": door_key(d), "value": d.get("opens") or "не видно",
                          "raw": f"{name}: {d.get('opens')}", "columns": [d.get("opens")], "label": name,
                          "location": door_key(d), "mark": d.get("mark"), "room": d.get("room"),
                          "exit": bool(d.get("exit")), "text_source": "RECOGNIZED",
                          "snippet": f"дверь {where}: {d.get('opens')} — по условному знаку на плане, прочитано моделью"})
    return found


# ---------- кандидаты одного документа ----------

# Ручная эпоха кеша кандидатов. Код разбора и поля правила кеш теперь видит сам — отпечатком
# (`rule_fingerprint`, `pipeline/fingerprint.py`), и поднимать номер при правке `extract` больше
# не нужно. Поднимать — только если разбор стал зависеть от данных вне кода, которых отпечаток
# не видит. Кеш с отпечатками лежит в новом каталоге (`.cache/rule_candidates`), поэтому номера
# ниже, выданные до него, с ним не сталкиваются. История номеров — для чтения старых веток:
# 10 — перенос работы 23.09 в master: марка стали (#91), допуски схем, предел картинки. Выше обеих
# веток — master разбирал с версией 7, feat/73 с 8 и 9, и одинаковый номер отдал бы здесь
# кандидатов чужого разбора из общего кеша (так на контрольном объекте появлялось ложное
# KR-058 из кандидатов ветки #73, задача #99)
# 21 — слияние master 24.09: единицы и перекрытия (#94, #92), акты из PDF (#73), огнестойкость по
# местам (#93) с #109 и #116 из origin. Обе ветки держали свой номер (13 и 20) на одном общем кеше
# кандидатов — берётся номер выше обоих, иначе кеш отдаёт кандидатов чужого разбора (#99).
# 20 — предел огнестойкости по местам (#93); 13 — сканы со штампом (#116); 11 — доля по итогу
# таблицы, чужой контекст подписи, предел в подписи (#109) и единицы правила (#94)
# 22 — источники света: вариант «ДНаТ, МГЛ, или … LED» — не решение о лампе (#110)
# 23 — DOC, XLS и XLSX в правилах; «кл. В 100x100» воздуховода — не класс бетона (#112)
# 25 — значения с чертежей проходом модели (#98). Номер выше всех записей в общем кеше: 23 заняли
# #112 в origin и #98 в локальной копии, 24 — #98 на основе до #112. Одинаковый номер при разном
# разборе отравляет общий кеш кандидатов (#99)
CANDIDATES_VERSION = 25     # 9 — марка стали по элементам (#91); 7 — тот же разбор, что 6, без кода #73


def _rules_digest(rules):
    payload = json.dumps({"parameters": rules["parameters"], "classes": rules.get("classes"),
                          "version": CANDIDATES_VERSION}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _text_digest(pages):
    """Отпечаток прочитанного текста документа: кеш кандидатов стареет вместе с чтением.

    Страницу без текстового слоя могли распознать позже (#52), и тогда кандидаты на ней
    другие. Читать текст дёшево — весь объект в 5863 страницы читается за десятую долю
    секунды, — а разбор правилами дорог, поэтому кешируется он, а текст проверяется.
    """
    h = hashlib.sha256()
    for page_no, text, source in pages:
        h.update(f"{page_no}\x1f{source}\x1f".encode("utf-8"))
        h.update((text or "").encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()[:16]


def _encode(value):
    """JSON не знает кортежей, а значение правила бывает кортежем: «(расход, напор)»."""
    if isinstance(value, tuple):
        return {"__tuple__": [_encode(v) for v in value]}
    if isinstance(value, list):
        return [_encode(v) for v in value]
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    return value


def _decode(value):
    if isinstance(value, dict):
        if set(value) == {"__tuple__"}:
            return tuple(_decode(v) for v in value["__tuple__"])
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def _candidates_path(sha, digest):
    d = os.path.join(CACHE, "candidates", sha[:2], sha)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{digest}.json")


def _extract_document(doc, pages, active, rules):
    """Кандидаты всех правил по страницам одного документа, без привязки к объекту.

    Возвращает список «страница, источник текста, {код: кандидаты}». Стадия, файл и
    цепочка редакций приписываются позже: они зависят от объекта и меняются без
    изменения документа.
    """
    out = []
    for page_no, text, text_source in pages:
        if not text or len(text) < MIN_PAGE_TEXT:
            continue
        by_code = {}
        for code, rule in active.items():
            cls = rules["classes"].get(rule.get("class")) if rule.get("class") else None
            got = []
            for c in extract(rule, text, cls, doc, page_no):
                # количество дробным не бывает: «6,71» — это литры, а не места
                if rule.get("kind") == "count" and isinstance(c["value"], float) \
                        and not c["value"].is_integer():
                    continue
                got.append(c)
            if got:
                by_code[code] = got
        if by_code:
            out.append((page_no, text_source, by_code))
    return out


# Поля правила, которые разбор страницы не читает: их правка кеш кандидатов не старит.
# Всё остальное — в отпечатке правила, и новое поле по умолчанию считается полем разбора:
# лишний пересчёт дешевле, чем кандидаты по прежнему правилу
NOT_EXTRACTION = {"note", "basis", "reason", "compare", "implemented", "display_unit", "evidence_pages",
                  "applies_if", "source_names"}
# Сколько последних вариантов правила помнит кеш документа: «попробовал правку — откатил»
# не должно стоить второго разбора корпуса, как и переключение между ветками с разными правилами
RULE_VARIANTS = 3
_KIND_DIGESTS = None


def kind_digests():
    """Отпечаток кода разбора по видам правил (`pipeline/fingerprint.py`)."""
    global _KIND_DIGESTS
    if _KIND_DIGESTS is None:
        from pipeline import fingerprint
        _KIND_DIGESTS = fingerprint.kind_digests("matrix_rules", "extract", ("_extract_document",),
                                                 {"ROOM_KINDS": ROOM_KINDS})
    return _KIND_DIGESTS


def rule_fingerprint(rule, classes=None, vlm=None):
    """Отпечаток всего, от чего зависят кандидаты правила на документе.

    Поля правила, которые читает разбор, перечень классов, код разбора его вида и ручная
    эпоха `CANDIDATES_VERSION`. У правила с проходом модели — ещё ответы модели по этому
    документу (`vlm_digest`): они лежат вне документа.
    """
    digests = kind_digests()
    payload = {"rule": {k: v for k, v in rule.items() if k not in NOT_EXTRACTION},
               "classes": classes, "code": digests.get(rule.get("kind"), digests["*"]),
               "epoch": CANDIDATES_VERSION,
               "vlm": vlm if rule.get("kind") in ("vlm_value", "door_opening") else None}
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _rule_cache_path(sha):
    d = os.path.join(CACHE, "rule_candidates", "v2", sha[:2])
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, sha + ".json")


def _load_rule_cache(path, key):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                got = json.load(f)
            if got.get("key") == key:
                return got
        except Exception:
            pass                      # испорченный кеш — не причина не разобрать документ
    return {"key": key, "pages": {}, "rules": {}}


def document_candidates(doc, root, active, rules, digest=None, use_cache=True, fresh=None):
    """Кандидаты документа: из кеша, если документ и правило те же. Возвращает (страницы, прочитано).

    Кеш — по «документ × правило» (`.cache/rule_candidates/<sha>.json`). Ключ документа —
    путь, стадия и отпечаток прочитанного текста; у каждого правила внутри — кандидаты по его
    отпечатку (`rule_fingerprint`), до `RULE_VARIANTS` последних вариантов. Разбирается заново
    только то правило, чьего отпечатка в кеше нет:
    правка одного правила стоит секунд на корпус, правка примечания или сравнения — ничего.
    Раньше ключом был хеш всех правил очереди и общий номер версии, и любая из этих правок
    перечитывала правилами весь корпус (#98, замер 24.09: 7 минут на кандидаты).

    `fresh` — коды правил, чьих кандидатов собрать заново; "*" — все. По умолчанию — из
    `PIPELINE_FRESH` и `PIPELINE_FRESH_RULES` (`fresh_rules`), один раз на документ за прогон.
    `use_cache=False` — ни читать, ни писать кеш: так мерится разбор сам по себе.
    `digest` не используется — оставлен для прежних вызовов.
    """
    pages = list(page_texts_src(doc, root))
    sha = doc.get("sha256")
    if not use_cache or not sha:
        return _extract_document(doc, pages, active, rules), len(pages)
    fresh = fresh_rules() if fresh is None else set(fresh)
    path = _rule_cache_path(sha)
    key = {"relative_path": doc.get("relative_path"), "stage": doc.get("stage"), "text": _text_digest(pages)}
    store = _load_rule_cache(path, key)
    vlm = {p: vlm_digest(doc, provisional=p) for p in {bool(r.get("provisional")) for r in active.values()}}
    classes_of = lambda rule: rules["classes"].get(rule.get("class")) if rule.get("class") else None  # noqa: E731
    prints = {code: rule_fingerprint(rule, classes_of(rule), vlm[bool(rule.get("provisional"))])
              for code, rule in active.items()}
    missing = {}
    for code, rule in active.items():
        again = ("*" in fresh or code in fresh) and _fresh_once("candidates", (sha, code))
        if again or prints[code] not in (store["rules"].get(code) or {}):
            missing[code] = rule
    native = {}
    if missing:
        for page_no, source, by_code in _extract_document(doc, pages, missing, rules):
            store["pages"][str(page_no)] = source
            for code, cands in by_code.items():
                native.setdefault(code, {})[page_no] = cands
        for code in missing:
            variants = {k: v for k, v in (store["rules"].get(code) or {}).items() if k != prints[code]}
            variants[prints[code]] = {str(p): _encode(c) for p, c in native.get(code, {}).items()}
            # последний вариант — в конце: при переполнении уходит самый давний
            store["rules"][code] = dict(list(variants.items())[-RULE_VARIANTS:])
        try:
            text = json.dumps(store, ensure_ascii=False)
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, path)
        except Exception:
            # кеш не обязателен: без него просто медленнее. Значение, которое не ложится
            # в JSON, тоже не повод ронять разбор объекта
            try:
                os.remove(path)
            except OSError:
                pass
    # Сборка по страницам в прежнем порядке: страницы по возрастанию, правила — как в очереди
    by_page = collections.defaultdict(dict)
    for code in active:
        got = native.get(code) if code in missing else \
            {int(p): _decode(c) for p, c in store["rules"][code][prints[code]].items()}
        for page_no, cands in (got or {}).items():
            by_page[page_no][code] = cands
    out = [(page_no, store["pages"][str(page_no)], by_page[page_no]) for page_no in sorted(by_page)]
    return out, len(pages)


def collect(object_id, rules=None, progress=None, only_files=None, use_cache=True):
    """Все кандидаты значений по объекту: код -> стадия -> список кандидатов.

    `only_files` ограничивает разбор этими документами: так проверяется, каких параметров
    коснулась дозагрузка (#60). Плотность страниц при этом считается только по ним, поэтому
    для построения находок сужать объект нельзя — сужается кеш, а не перечень документов.
    """
    rules = rules or load_rules()
    spec = OBJECTS[object_id]
    docs_path = os.path.join(OUT, object_id, "documents.jsonl")
    with open(docs_path, encoding="utf-8") as f:
        docs = [json.loads(l) for l in f if l.strip()]
    active = {c: r for c, r in rules["parameters"].items() if r.get("implemented")}
    digest = _rules_digest(rules)
    found = collections.defaultdict(lambda: collections.defaultdict(list))
    density = collections.Counter()
    pages_read = 0
    chains = chain_index(docs, _read_jsonl(os.path.join(OUT, object_id, "revisions.jsonl")))
    for n, doc in enumerate(docs, 1):
        stage = STAGE.get(doc.get("stage"))
        if not stage or (doc.get("extension") or "").lower() not in READABLE_EXT \
                or doc.get("duplicate_of") or (only_files is not None and doc["file_id"] not in only_files):
            continue
        chain = chains.get(doc["file_id"])
        per_page, read = document_candidates(doc, spec["root"], active, rules, digest, use_cache)
        pages_read += read
        for page_no, text_source, by_code in per_page:
            for code, cands in by_code.items():
                for c in cands:
                    c = dict(c, stage=stage, file_id=doc["file_id"], page=page_no,
                             document=os.path.basename(doc["relative_path"]))
                    if stage == "ID" and product_document(doc["relative_path"]):
                        c["product_doc"] = True     # паспорт изделия, оборудование: не про здание
                    if chain:
                        c["chain"] = chain          # место документа в цепочке редакций (#10)
                    if text_source == "RECOGNIZED":
                        # значение прочитано машиной, а не взято из текстового слоя:
                        # распознавание путает цифры, и в находке это должно быть видно (#52)
                        c["text_source"] = "RECOGNIZED"
                    found[code][stage].append(c)
            density[(doc["file_id"], page_no)] = len(by_code)
        if progress:
            progress(n, len(docs), pages_read)
    return found, density, pages_read


# ---------- редакции ----------

REV_RE = re.compile(r"(?:кор|изм|ред)\.?\s*(\d{1,2})", re.I)


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def chain_index(docs, chains=()):
    """Место документа в цепочке редакций по реестру (`pipeline/revisions.py`, #10).

    {file_id: {chain, rank, status, reason}}: ранг — номер в порядке цепочки (у исходной
    редакции 0), status — CURRENT, SUPERSEDED или CLARIFICATION_REQUIRED, reason — почему
    порядок не определён. Документы без цепочки в индекс не входят: для них редакция
    по-прежнему берётся из имени файла (`revision_key`).
    """
    # строка-копия реестра (тот же файл в другой папке, `duplicate_of`) носит file_id оригинала,
    # но без предшественника и со статусом DUPLICATE. Идя в реестре после оригинала, она его
    # подменяла и в обходе, и в индексе: у Полярной 16 изм.6 и изм.9 СПА получали ранг 0, и
    # `latest_only` оставлял обе. Правила копии не читают (`collect`) — место в цепочке у оригинала
    docs = [d for d in docs if not d.get("duplicate_of")]
    by_id = {d["file_id"]: d for d in docs}
    reasons = {ch.get("chain_id"): ch.get("reason") for ch in chains}
    # кандидаты в актуальные у цепочки с неопределённым порядком: остальные её члены заведомо
    # старше (у Полярной 16 две копии изм.5 «(ВП)» и «(ОП)», а изм.2 и изм.4 — прежние выпуски)
    tied = {ch.get("chain_id"): ch.get("candidates") for ch in chains if ch.get("candidates")}
    out = {}
    for d in docs:
        if not d.get("chain_id"):
            continue
        rank, cur, seen = 0, d, set()
        while cur.get("predecessor_file_id") in by_id and cur["file_id"] not in seen:
            seen.add(cur["file_id"])
            cur = by_id[cur["predecessor_file_id"]]
            rank += 1
        out[d["file_id"]] = {"chain": d["chain_id"], "rank": rank, "status": d.get("revision_status"),
                             "reason": reasons.get(d["chain_id"]), "candidates": tied.get(d["chain_id"])}
    return out


# ИД изделий и оборудования: паспорта, сертификаты, инструкции, комплекты поставки. У школы на Полярной 25
# в ИД/ТХ 1216 таких документов, и показатели здания брались из них: «высота здания» из паспорта учебной
# астролябии, «вместимость — 2 пачки» из паспорта дозатора мыла (#145). Технический паспорт здания (БТИ) —
# документ о здании, он остаётся
PRODUCT_DOC_RE = re.compile(r"паспорт|сертификат|декларац\w*|инструкц|руководств\w*|каталог|оборудовани|мебел|инвентар"
                            r"|отказн\w+\s+письм|комплект\w*\s+поставк|спецификаци\w+\s+изделия"
                            # папка ТХ в ИД — технологическое оборудование: «ИД/ТХ/…Актовый зал/33. Источник
                            # бесперебойного питания.pdf»
                            r"|(?:^|/)ТХ(?:/|$)", re.I)
BUILDING_DOC_RE = re.compile(r"технич\w+\s+паспорт\w*\s+(?:на\s+)?(?:здани|объект|жил)|\bБТИ\b|технич\w+\s+план", re.I)


def product_document(path):
    """Документ ИД об изделии или оборудовании, а не о здании: по пути файла."""
    return bool(PRODUCT_DOC_RE.search(path or "")) and not BUILDING_DOC_RE.search(path or "")


def revision_rank(cand):
    """(документ, ранг редакции) кандидата: по цепочке реестра, а без неё — по имени файла."""
    chain = cand.get("chain")
    if chain:
        return chain["chain"], chain["rank"]
    return revision_key(cand["document"])


def revision_conflicts(cands):
    """Цепочки, чей порядок не определён, а значения в их документах расходятся.

    Возвращает [(множество file_id, элемент или None, причина)]. У параметров по элементам
    значения сравниваются в пределах элемента («ростверки» с «ростверками»): разные элементы
    в одном томе расходятся законно. Если документы цепочки называют одно и то же значение
    (или один и тот же набор значений), конфликта нет: какая редакция действует, для сравнения неважно.
    """
    by_chain = collections.defaultdict(lambda: collections.defaultdict(set))
    reasons, names = {}, {}
    for c in cands:
        chain = c.get("chain")
        if not chain or chain.get("status") != "CLARIFICATION_REQUIRED":
            continue
        if chain.get("candidates") and c["file_id"] not in chain["candidates"]:
            # прежний выпуск: порядок с кандидатами определён, его значение законно другое
            # (изм.2 против изм.5), спор только между кандидатами в актуальные
            continue
        group = (chain["chain"], c.get("location"))
        by_chain[group][c["file_id"]].add(_key(c["value"]))
        reasons[chain["chain"]] = chain.get("reason")
        names[c["file_id"]] = c["document"]
    out = []
    for (chain_id, location), files in by_chain.items():
        # спор — когда документы называют разные наборы значений. Многозначный параметр в двух
        # копиях одной редакции даёт одно и то же «190; 300 мм» (Полярная 16, АР1 изм.3 «(ВП)»
        # и «(ОП)»): в объединении два значения, но расхождения нет
        if len({frozenset(values) for values in files.values()}) < 2:
            continue
        listing = ", ".join(f"{fid} ({names[fid]})" for fid in sorted(files))
        out.append((set(files), location,
                    f"актуальная редакция не определена: {reasons[chain_id] or 'порядок редакций неизвестен'}; "
                    f"значения в редакциях расходятся: {listing}"))
    return out


# Почему сравнить не удалось: не хватило документа или фрагмента (MISSING_EVIDENCE) либо
# источники несопоставимы (NOT_COMPARABLE). Словарь статусов — легенда организатора к Матрице,
# раздел «Правила присвоения эталонной метки»; наши значения перечислены в contracts/enums.json.
# «в указаниях рабочей стадии значение не названо» — это слабая привязка, а не нехватка
# документа: значение есть, сопоставить его нельзя. Поэтому «не назван» в список не входит
_MISSING_EVIDENCE = re.compile(r"не найдено|не найден[аоы]?\b|записей нет|документ\w*\s+нет", re.I)


def finding_status(findings):
    """Статус записи по легенде организатора: чего не хватило или почему несопоставимо.

    Ставится только там, где статус ещё «кандидат»: конфликт редакций уже сказал
    «требует уточнения» (`clarify_revisions`), гипотезы свободного поиска — «подозрение».
    Нарушение и «нарушения нет» остаются кандидатами: отрицательной и положительной
    эталонной меткой их делает решение инспектора, а не машина.
    """
    for f in findings:
        if f.get("finding_status") not in (None, "CANDIDATE"):
            continue
        label = f.get("violation_label")
        if label == "MISSING_DOCUMENT":
            f["finding_status"] = "MISSING_EVIDENCE"
        elif label == "COMPARISON_IMPOSSIBLE":
            detail = (f.get("extraction") or {}).get("detail") or ""
            f["finding_status"] = ("MISSING_EVIDENCE" if _MISSING_EVIDENCE.search(detail)
                                   else "NOT_COMPARABLE")
        else:
            f["finding_status"] = "CANDIDATE"
    return findings


def clarify_revisions(findings, conflicts):
    """Записи, чьи доказательства взяты из цепочки с конфликтом редакций, — «требует уточнения» (ТЗ 9.1).

    Конфликт редакций не нарушение и не «нарушения нет»: актуальную редакцию называет
    инспектор (экран файлов процесса), после чего сравнение повторяется.
    """
    for f in findings:
        if f.get("violation_label") not in ("VIOLATION_PRESENT", "NO_VIOLATION"):
            continue
        used = {e["file_id"] for e in f.get("evidence") or []}
        hits = [text for files, location, text in conflicts
                if used & files and (location is None or location in (f.get("locations") or []))]
        if not hits:
            continue
        f["violation_label"] = "COMPARISON_IMPOSSIBLE"
        f["criticality"] = None
        f["finding_status"] = "CLARIFICATION_REQUIRED"
        f["extraction"]["detail"] = "конфликт редакций: " + "; ".join(hits) + "; " + (f["extraction"].get("detail") or "")
        f["extraction"]["revision_conflict"] = True
    return findings


_STAGE_GEN = {"PD": "проектной", "RD": "рабочей", "ID": "исполнительной"}


def recognized_review(findings):
    """Значение, прочитанное распознаванием, не решает молча (#41).

    Пометка `text_source: RECOGNIZED` у стороны видна в карточке; здесь — что из неё следует
    для решения. Подтверждения инспектора (`needs_expert`, причина в пояснении) требуют:
    нарушение, опирающееся на распознанное значение; распознанное значение, расходящееся
    со значением из текстового слоя — другой стадии или других страниц той же стадии
    (`layer_conflict`); значения, отложенные как похожие на ошибку чтения (`doubtful`).
    Совпадение распознанного значения со слоем подтверждения не требует — только пометки.
    """
    for f in findings:
        ext = f.get("extraction") or {}
        sides = {st: ext.get(st.lower()) or {} for st in ("PD", "RD", "ID")}
        machine = [st for st, s in sides.items() if s.get("text_source") == "RECOGNIZED"]
        doubts = [(st, d) for st, s in sides.items() for d in s.get("doubtful") or []]
        if not machine and not doubts:
            continue
        notes, ask = [], []
        if machine:
            notes.append(f"значение {' и '.join(_STAGE_GEN[s] for s in machine)} стадии прочитано распознаванием сканов")
        if machine and f.get("violation_label") == "VIOLATION_PRESENT":
            ask.append("нарушение опирается на распознанное значение")
        layer = {st: s.get("value") for st, s in sides.items() if s and st not in machine}
        for st in machine:
            if sides[st].get("layer_conflict"):
                ask.append(f"в {_STAGE_GEN[st]} стадии текстовый слой других страниц даёт {sides[st]['layer_conflict']}")
            # у параметра-набора (уклоны участков, высоты ограждений) значения стадий
            # различаются по делу: это предмет сравнения, а не расхождение чтения (#98)
            if not ext.get("values_are_set") and \
                    any(v is not None and v != sides[st].get("value") for v in layer.values()):
                ask.append(f"распознанное значение {_STAGE_GEN[st]} стадии расходится со значением из текстового слоя")
        for st, d in doubts:
            ask.append(f"в {_STAGE_GEN[st]} стадии «{d['value']}» ({d['mentions']}) рядом с «{d['against']}» "
                       f"({d['against_mentions']}) отложено как похожее на ошибку распознавания")
        if ask:
            f["needs_expert"] = True
            notes.append("требует подтверждения инспектора: " + "; ".join(ask))
        ext["recognized"] = {"stages": machine, "confirmation": bool(ask)}
        ext["detail"] = "; ".join(filter(None, [ext.get("detail"), *notes]))
    return findings


def binding_note(pd, rd, built=None):
    """Пояснение о привязке значений элемента, взятых не из указаний (#41).

    Поле `binding` стороны видно в карточке тегом; в протокол уходит пояснение, чтобы
    и там было сказано, что значение стоит на листе и может относиться к соседнему элементу.
    """
    words = {"SHEET": "с листа чертежа", "PAGE": "со страницы, не из указаний", "PATH": "по пути файла"}
    parts = []
    for side, stage in ((pd, "PD"), (rd, "RD"), (built, "ID")):
        if side and side.get("binding") in words:
            parts.append(f"значение {_STAGE_GEN[stage]} стадии взято {words[side['binding']]}")
    if not parts:
        return None
    if any(s and s.get("binding") == "SHEET" for s in (pd, rd, built)):
        parts.append("на чертеже значение может относиться к соседнему элементу")
    return "; ".join(parts)


def protocol_note(built):
    """Класс построенного взят из протоколов испытаний бетона (#62): строка протокола называет
    конструкцию, отметку и класс при прочности, слова «бетон» при классе нет."""
    n = (built or {}).get("protocol_rows")
    if not n:
        return None
    rows = "строка" if n % 10 == 1 and n % 100 != 11 else ("строки" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "строк")
    return f"значение исполнительной стадии — из протоколов испытаний бетона ({n} {rows})"


def revision_key(name):
    """Основа имени документа и номер редакции.

    Одна и та же таблица показателей живёт в нескольких редакциях тома, и значения
    в них расходятся. На Речникове площадь озеленения в исходном томе ПЗУ
    и в первой корректировке равна 3987,3, а в третьей — 3694,6. Эталон
    организатора берёт третью. Голосование по всем редакциям сразу выбирало
    старое значение: двух старых томов больше, чем одного нового.

    Пометки редакции в именах корпуса: «кор3», «кор.3», «Изм 2», «(Изм.2)»,
    «ИЗМ1», «изм. 4_в1», а также «ИЗМ ПО ЗАМЕЧАНИЯМ» без номера. Номер берётся
    наибольший из найденных. Пометка без номера считается первой редакцией после
    исходной. Основа имени — всё остальное без пунктуации, копий «(1)» и дат.
    """
    stem = os.path.splitext(os.path.basename(name))[0].lower()
    numbers = [int(x) for x in REV_RE.findall(stem)]
    if numbers:
        rank = max(numbers)
    elif re.search(r"изм\w*\s+по\s+замечани", stem):
        rank = 1
    else:
        rank = 0
    base = re.sub(r"изм\w*\s+по\s+замечани\w*", "", stem)
    base = re.sub(r"(?:кор|изм|ред)\.?\s*\d{0,2}", "", base)
    base = re.sub(r"\(\d+\)", "", base)
    base = re.sub(r"_в\d+", "", base)
    base = re.sub(r"\d{2}\.\d{2}\.\d{2,4}", "", base)
    base = re.sub(r"[\s._\-()]+", "", base)
    return base, rank


def latest_only(cands):
    """Кандидаты только из последней редакции каждого документа, которая значение называет.

    Последняя редакция ищется среди документов, где значение нашлось, а не среди
    всех редакций цепочки. Это сознательно: корректировка, которая значение
    не затрагивает, его не отменяет. В третьей корректировке ПЗУ Речникова строки
    асфальтобетона нет, а в первой она есть — действующим считается значение
    первой, и оно совпадает с рабочей стадией.
    """
    # цепочка с неопределённым порядком: прежние выпуски известны — это всё, что не среди
    # кандидатов в актуальные. Если значение называют кандидаты, прежние выпуски не берутся
    named = {c["chain"]["chain"] for c in cands
             if (c.get("chain") or {}).get("candidates") and c["file_id"] in c["chain"]["candidates"]}
    cands = [c for c in cands if not ((c.get("chain") or {}).get("candidates") and c["chain"]["chain"] in named
                                      and c["file_id"] not in c["chain"]["candidates"])]
    best = {}
    for c in cands:
        base, rank = revision_rank(c)
        best[base] = max(best.get(base, -1), rank)
    return [c for c in cands if revision_rank(c)[1] == best[revision_rank(c)[0]]]


def revision_label(name):
    """Пометка редакции из имени файла, как она написана: «кор.3», «Изм 2»; без пометки — «исходная»."""
    stem = os.path.splitext(os.path.basename(name))[0]
    marks = [(int(m.group(1)), m.group(0)) for m in REV_RE.finditer(stem)]
    if marks:
        return max(marks)[1]
    if re.search(r"изм\w*\s+по\s+замечани", stem, re.I):
        return "изм. по замечаниям"
    return "исходная"


def revision_history(cands, side):
    """Прежние редакции документов, из которых взято значение стадии, если в них значение другое.

    Сравнение идёт по последней редакции тома, а устаревшая редакция эталоном быть
    не может (ТЗ, 9.1). Но инспектор должен видеть, что редакций несколько и значения
    в них расходятся: на Речникове площадь озеленения в исходном томе ПЗУ и в первой
    корректировке 3987,30, а в третьей — 3694,60. Возвращает пустой список, если
    устаревших редакций с другим значением нет.
    """
    if not side:
        return []
    used_files = {fid for fid, _ in side["pages"]}
    groups = collections.defaultdict(lambda: collections.defaultdict(dict))
    for c in cands:
        base, rank = revision_rank(c)
        entry = groups[base][rank].setdefault(c["file_id"], {"document": c["document"], "values": {}})
        entry["values"].setdefault(_key(c["value"]), str(c["raw"]))
    out = []
    for base in sorted(groups):
        ranks = groups[base]
        latest = max(ranks)
        if len(ranks) < 2 or not used_files & set(ranks[latest]):
            continue
        used = {}
        for entry in ranks[latest].values():
            used.update(entry["values"])
        superseded = []
        for rank in sorted(r for r in ranks if r != latest):
            for fid, entry in sorted(ranks[rank].items()):
                if set(entry["values"]) != set(used):
                    superseded.append({"file_id": fid, "document": entry["document"],
                                       "revision": revision_label(entry["document"]),
                                       "values": [entry["values"][k] for k in sorted(entry["values"], key=str)]})
        if superseded:
            fid, entry = sorted(ranks[latest].items())[0]
            out.append({"used": {"file_id": fid, "document": entry["document"],
                                 "revision": revision_label(entry["document"]),
                                 "values": [used[k] for k in sorted(used, key=str)]},
                        "superseded": superseded})
    return out


# ---------- предпочтительный источник ----------

# Сокращения разделов в полях source_pd и source_rd каталога -> как раздел
# называется в именах файлов корпуса.
SECTION_ALIASES = {
    "ПЗ": {"ПЗ", "ОПЗ"}, "ПЗУ": {"ПЗУ"}, "СПЗУ": {"ПЗУ"},
    "ПП": {"ГП", "ПП"}, "ГП": {"ГП", "ПП"},
    "АР": {"АР"}, "КР": {"КР", "КЖ", "КМ"}, "КК": {"КЖ", "КМ", "КР"},
    # «Опалубочные чертежи плиты; Разрезы (КЖ)» — источник РД всех параметров KR-054…KR-067.
    # Без этого ключа подсказка пустая, и значение РД бралось из любого тома, где плита упомянута:
    # экспликация слоёв в томе дренажа Новослободской вытесняла из доказательств чертёж плиты КЖ.
    # «КМ» ключом не ставим: в каталоге это ещё и класс пожарной опасности отделки (КМ1…КМ5)
    "КЖ": {"КЖ", "КР", "КМ"},
    "ЭОМ": {"ЭОМ", "ЭМ", "ЭО"}, "ВК": {"ВК", "НВК"}, "ОВ": {"ОВ"},
    "ТХ": {"ТХ"}, "ГСВ": {"ГСВ", "ГСН"}, "ОДИ": {"ОДИ"}, "НВК": {"НВК"},
}


def source_hints(text):
    """Какие разделы каталог называет источником: «Раздел ПЗ: Таблица ТЭП» -> {ПЗ, ОПЗ}."""
    out = set()
    for tok in re.findall(r"[А-ЯЁ]{2,4}", text or ""):
        out |= SECTION_ALIASES.get(tok, set())
    return out


def rule_hints(rule, cat, field):
    """Разделы-источники по именам файлов: из правила, если оно их задаёт, иначе из каталога.

    Правило задаёт токены имени файла напрямую («ЭЭ», «ИОС», «ЭО»), «*» — источник не ограничен.
    """
    names = (rule.get("source_names") or {}).get(field)
    if not names:
        return source_hints(cat.get(field))
    return set() if names == ["*"] else set(names)


def from_source(document, hints):
    """Относится ли документ к разделу-источнику. Сравнение по буквенным токенам
    имени: «01-07-22-14-П-ОПЗ-кор3» даёт токены П, ОПЗ, КОР."""
    tokens = set(re.findall(r"[А-ЯЁ]+", os.path.basename(document).upper()))
    return bool(tokens & hints)


def prefer_source(cands, hints):
    """Кандидаты из документов раздела-источника, если такие есть.

    Шум первой очереди почти весь из чужих документов. «Полезная площадь 15,5 м²»
    на Речникове — бытовой контейнер из проекта организации строительства.
    «Строительный объём – 150000 куб.м.» — предельное значение из специальных
    технических условий, а не объём здания. Каталог прямо говорит, где искать:
    «Раздел ПЗ: Таблица ТЭП». Если в разделе-источнике значения нет, берутся
    остальные документы, и это помечается.
    """
    if not hints:
        return cands, False
    own = [c for c in cands if from_source(c["document"], hints)]
    return (own, False) if own else (cands, bool(cands))


# ---------- согласование и решение ----------

def _decimals(raw):
    m = re.search(r"[.,](\d+)", str(raw))
    return len(m.group(1)) if m else 0


def _key(value):
    if value is None or isinstance(value, str):
        # пустое место в наборе — не число: у повысительной установки без названной модели значение
        # (None, расход, напор, точка), и `round(None)` ронял разбор школы на Полярной 25 (#145)
        return value
    if isinstance(value, (tuple, list)):
        # значения по ключу бывают наборами: марки кабелей группы, расход и напор струи
        return tuple(_key(v) for v in value)
    if isinstance(value, (int, float)):
        return round(value, 2)
    return str(value)


def _one_digit_apart(a, b):
    """Две записи одной длины, различающиеся ровно одной цифрой: «B30» и «B50», «1200» и «1000»."""
    a, b = str(a), str(b)
    if len(a) != len(b) or a == b:
        return False
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    return len(diff) == 1 and diff[0][0].isdigit() and diff[0][1].isdigit()


def recognized_doubts(cands, key=lambda c: c["value"]):
    """Значения из распознавания, похожие на ошибку чтения (#41).

    Распознавание путает цифры: в рабочей документации контрольного объекта класс бетона
    встречается как «B30» 62 раза и «B50» 3 раза. Значение, прочитанное только машиной,
    втрое и более редкое рядом с другим и отличающееся от него одной цифрой, — не решение,
    а вопрос: оно откладывается, в находке остаётся полем `doubtful` стороны, и запись
    уходит инспектору с `needs_expert` (см. `recognized_review`).

    Перечень допустимых значений здесь не нужен: класс бетона и число уже прошли разбор
    (иначе кандидата бы не было), а «B50» — законный класс. Ошибку выдаёт не сама запись,
    а её редкость рядом с похожей частой.
    """
    counts = collections.Counter(key(c) for c in cands)
    if len(counts) < 2:
        return []
    raws = {}
    for c in cands:
        raws.setdefault(key(c), str(c["raw"]))
    out = []
    for v, n in counts.items():
        if not all(c.get("text_source") == "RECOGNIZED" for c in cands if key(c) == v):
            continue
        rivals = [(m, u) for u, m in counts.items() if u != v and m >= 3 * n and _one_digit_apart(raws[v], raws[u])]
        if rivals:
            m, u = max(rivals)
            out.append({"key": v, "value": raws[v], "mentions": n, "against": raws[u], "against_mentions": m})
    return out


def _doubt_view(doubtful):
    return [{k: v for k, v in d.items() if k != "key"} for d in doubtful]


def choose_values(rule, cands):
    """Кандидаты стадии, которые голосуют, по правилу `choose` (#229).

    «max» — наибольшее значение стадии. Баланс земляных масс считается по участкам: у Полярной 17
    в ПД итоги 30 460,7 (участок вне кровли автостоянки), 4 133 (кровля) и 153,1 м³, в РД — 28 108,
    2 254 и 84,6 м³. Голосование страниц их не различает — все на одном листе, и побеждал первый по
    тексту слоя; сравнивать надо итог основного участка с итогом основного участка.
    """
    if rule.get("choose") != "max" or not cands:
        return cands
    nums = [c["value"] for c in cands if isinstance(c.get("value"), (int, float)) and not isinstance(c.get("value"), bool)]
    if not nums:
        return cands
    top = max(nums)
    return [c for c in cands if c.get("value") == top]


def reconcile(cands, density):
    """Значение стадии голосованием страниц. Возвращает словарь или None.

    Голос страницы весит 1 плюс число показателей первой очереди, найденных на ней:
    таблица показателей перевешивает случайное упоминание в тексте.

    Значения, прочитанные распознаванием и похожие на ошибку чтения, в голосовании не
    участвуют (`recognized_doubts`, #41). Если победило значение, прочитанное только
    машиной, а текстовый слой других страниц даёт иное, — это расхождение записывается
    полем `layer_conflict`: инспектор подтверждает, какое верно.
    """
    if not cands:
        return None
    doubtful = recognized_doubts(cands, key=lambda c: _key(c["value"]))
    doubted = {d["key"] for d in doubtful}
    voting = [c for c in cands if _key(c["value"]) not in doubted] or cands
    groups = collections.defaultdict(list)
    for c in voting:
        groups[_key(c["value"])].append(c)
    scored = []
    for key, items in groups.items():
        pages = {(c["file_id"], c["page"]) for c in items}
        weight = sum(1 + density.get(p, 0) for p in pages)
        scored.append((weight, len(pages), key, items))
    scored.sort(key=lambda s: (-s[0], -s[1]))
    weight, n_pages, key, items = scored[0]
    best = max(items, key=lambda c: density.get((c["file_id"], c["page"]), 0))
    machine_only = all(c.get("text_source") == "RECOGNIZED" for c in items)
    layer_other = [s[3][0]["raw"] for s in scored[1:] if any(c.get("text_source") != "RECOGNIZED" for c in s[3])]
    return {
        "value": items[0]["value"],
        "raw": best["raw"],
        "columns": best["columns"],
        # чем выбрана колонка в строке-источнике: доля, шапка или правило (#41)
        "column_choice": best.get("column_choice"),
        "snippet": best["snippet"],
        "pages": sorted({(c["file_id"], c["page"]) for c in items}),
        "support": n_pages,
        "weight": weight,
        # порядок равных по весу и страницам — по значению: иначе он зависел от того, взяты кандидаты
        # из кеша или разобраны заново, и запись менялась без изменения данных (AR-045 Речникова, #145)
        "alternatives": [{"value": s[2], "pages": s[1]}
                         for s in sorted(scored[1:], key=lambda s: (-s[0], -s[1], str(s[2])))[:5]],
        # прочитано машиной хотя бы на одной странице, подтвердившей значение:
        # распознавание путает цифры, инспектор должен видеть это в находке (#52)
        "text_source": "RECOGNIZED" if any(c.get("text_source") == "RECOGNIZED" for c in items) else None,
        **({"doubtful": _doubt_view(doubtful)} if doubtful else {}),
        **({"layer_conflict": layer_other[0]} if machine_only and layer_other else {}),
    }


def union_presence(side, cands):
    """Наличие систем — по всем страницам стадии, а не голосованием одной страницы.

    Система, названная в пояснительной части, и система, названная на листе покрытий,
    обе в стадии есть. Голосование выбрало бы одну страницу, а названия с остальных
    посчитало бы пропавшими: на Речникове лотки названы в тексте, дренаж — в составе
    кровельного пирога, и по одной странице выходило ложное «в рабочей стадии не названо».
    """
    if side is None:
        return None
    names = sorted({n for c in cands for n in (c.get("columns") or [])})
    if not names:
        return side
    # страницы — все, где системы названы: доказательство наличия живёт не на одном листе
    pages = sorted({(c["file_id"], c["page"]) for c in cands})
    return dict(side, columns=names, value=float(len(names)), pages=pages, support=len(pages),
                raw="PRESENT", snippet="названы: " + ", ".join(names))


def with_all_values(side, cands):
    """Все числа стадии рядом с выбранным: у части параметров значение не одно (#98).

    Уклон кровли подписан на плане у каждого участка: на одном листе Речникова тринадцать
    подписей. Голосование страниц выбирает представителя стадии, и сравнение представителей
    даёт «2,1 % → 2,0 %» — это два участка одной кровли, а не занижение. Поэтому у таких
    параметров сторона несёт весь набор, а решение принимает `set_decrease`.
    """
    if side is None:
        return None
    vals = sorted({c["value"] for c in cands if isinstance(c.get("value"), (int, float))})
    if not vals:
        return side
    # «значение прочитано машиной, а слой других страниц даёт другое» — у набора не
    # расхождение, а второй участок: значения стадии здесь и должны различаться (#98).
    # По той же причине снимается и «похоже на ошибку чтения»: у кровли рядом стоят
    # участки 1,5 % и 1,6 %, и одна цифра разницы здесь — не описка распознавания
    drop = ("layer_conflict", "doubtful")
    return {k: v for k, v in dict(side, all_values=vals).items() if k not in drop}


def _row_key(side):
    """Строка перечня без номера позиции и без разметки: по ней видно замену типа.

    Одна и та же строка в проектной и рабочей ведомости стоит под разными номерами
    («11 Ограждение территории…» и «21 Ограждение территории…»), поэтому номер
    отбрасывается, а остальное сводится к буквам и цифрам.
    """
    text = (side.get("columns") or [side.get("raw", "")])[0]
    text = re.sub(r"^\s*\d{1,3}(?:\.\d{1,2})?\s+", "", str(text))
    return re.sub(r"[^0-9a-zа-яё]+", "", text.lower())


def _join_values(values):
    return "; ".join(f"{v:g}".replace(".", ",") for v in values)


def decide(rule, pd, rd, classes=None):
    """Решение по паре значений. Возвращает (метка, тип результата, пояснение)."""
    cmp = rule["compare"]
    kind = cmp["type"]

    if kind == "min_absolute":
        if pd is None and rd is None:
            return None, None, "значение не найдено ни в одной стадии"
        if rd is None:
            return "COMPARISON_IMPOSSIBLE", None, "значение в рабочей стадии не найдено"
        thr = cmp["threshold"]
        # единица правила названа в пояснении: значение приведено к ней при извлечении (#94),
        # и без единицы «3.5 меньше 4.2» ничего не говорит о том, что сравнивалось
        unit = f" {rule['unit']}" if rule.get("unit") else ""
        if rd["value"] < thr:
            return ("VIOLATION_PRESENT", "DIMENSION_REDUCED",
                    f"в рабочей стадии {rd['value']:g}{unit} меньше нормативного {thr:g}{unit}")
        return "NO_VIOLATION", "NON_TRIGGERING_DIFFERENCE_NO_DECREASE", \
            f"в рабочей стадии {rd['value']:g}{unit} не меньше {thr:g}{unit}"

    if kind == "min_trigger":
        # Порог — триггер Матрицы (решение пользователя 25.09, Р-104: триггер важнее требования ПД;
        # в третьем круге «порог каталога» специалист прочёл как норматив записки). Требование ПД —
        # второй порог: значение ниже него, но не ниже триггера — тоже гипотеза, только слабее.
        # Без ПД сравнение с триггером всё равно возможно. Значение стороны — набор (ширины всех
        # дверей листа): решает наименьшее
        if rd is None:
            return (None, None, "значение не найдено ни в одной стадии") if pd is None else \
                ("COMPARISON_IMPOSSIBLE", None, "значение в рабочей стадии не найдено")
        trig = cmp["trigger"]
        unit = f" {rule['unit']}" if rule.get("unit") else ""
        rd_all = rd.get("all_values") or [rd["value"]]
        pd_all = (pd.get("all_values") or [pd["value"]]) if pd else []
        low = min(rd_all)
        shown = (f"в рабочей стадии {_join_values(rd_all)}{unit}; триггер Матрицы {trig:g}{unit}"
                 + (f", требование ПД {_join_values(pd_all)}{unit}" if pd_all else ""))
        bad = cmp.get("result_violation") or "DIMENSION_REDUCED"
        if low < trig - 1e-9:
            return "VIOLATION_PRESENT", bad, f"{shown}: {low:g}{unit} меньше триггера"
        if pd_all and low < min(pd_all) - 1e-9:
            return "VIOLATION_PRESENT", bad, f"{shown}: {low:g}{unit} не меньше триггера, но меньше требования ПД"
        return ("NO_VIOLATION", cmp.get("result_ok") or "NON_TRIGGERING_DIFFERENCE_NO_DECREASE",
                f"{shown}: не меньше порогов")

    if kind == "max_trigger":
        # то же, что min_trigger, но порог сверху: высота подступенка не больше 150 мм (AR-048, Р-105)
        if rd is None:
            return (None, None, "значение не найдено ни в одной стадии") if pd is None else \
                ("COMPARISON_IMPOSSIBLE", None, "значение в рабочей стадии не найдено")
        trig = cmp["trigger"]
        unit = f" {rule['unit']}" if rule.get("unit") else ""
        rd_all = rd.get("all_values") or [rd["value"]]
        pd_all = (pd.get("all_values") or [pd["value"]]) if pd else []
        high = max(rd_all)
        shown = (f"в рабочей стадии {_join_values(rd_all)}{unit}; триггер Матрицы {trig:g}{unit}"
                 + (f", в проекте {_join_values(pd_all)}{unit}" if pd_all else ""))
        bad = cmp.get("result_violation") or "VALUE_MISMATCH"
        if high > trig + 1e-9:
            return "VIOLATION_PRESENT", bad, f"{shown}: {high:g}{unit} больше триггера"
        if pd_all and high > max(pd_all) + 1e-9:
            return "VIOLATION_PRESENT", bad, f"{shown}: {high:g}{unit} не больше триггера, но больше проектного"
        return ("NO_VIOLATION", cmp.get("result_ok") or "NON_TRIGGERING_DIFFERENCE_NO_DECREASE",
                f"{shown}: не больше порогов")

    if pd is None and rd is None:
        return None, None, "значение не найдено ни в одной стадии"
    if pd is None:
        return "COMPARISON_IMPOSSIBLE", None, "значение в проектной стадии не найдено"
    if rd is None:
        return "COMPARISON_IMPOSSIBLE", None, "значение в рабочей стадии не найдено"

    a, b = pd["value"], rd["value"]
    # Часть параметров описывает не число, а перечень: их решения называются своими
    # словами каталога организатора, поэтому правило может задать коды исхода (#84).
    ok_result, bad_result = cmp.get("result_ok"), cmp.get("result_violation")

    if kind == "presence":
        # Нарушение — исключение решения целиком: в рабочей стадии не названо ничего
        # из группы. Пропажа одного слова из двух нарушением не считается: на
        # контрольном объекте проектная стадия говорит «дренаж», а рабочая «лотки» —
        # это одно и то же решение, названное разными словами, и требование совпадения
        # состава слов давало там ложное нарушение. Что разошлось, инспектор видит
        # в пояснении.
        had = list(pd.get("columns") or [])
        have = list(rd.get("columns") or [])
        missing = [n for n in had if n not in have]
        if had and not have:
            return ("VIOLATION_PRESENT", bad_result or "MISSING_DESIGN_ELEMENT",
                    "в рабочей стадии не названо ничего из: " + ", ".join(had))
        note = "; в проектной названо и " + ", ".join(missing) if missing else ""
        return ("NO_VIOLATION", ok_result or "EQUAL_PD_RD",
                "названо в рабочей стадии: " + ", ".join(have) + note)

    if kind == "decrease_or_text_change":
        # Ограждение меняют двумя способами: занижают высоту и подменяют тип.
        # Высота — число, тип — текст строки, поэтому смотрятся оба.
        if b < a:
            return ("VIOLATION_PRESENT", bad_result or "DIMENSION_REDUCED",
                    f"высота уменьшена: {pd['raw']} → {rd['raw']}")
        if _row_key(pd) != _row_key(rd):
            return ("VIOLATION_PRESENT", bad_result or "VALUE_MISMATCH",
                    f"запись изменилась: {pd['columns'][0][:70]} → {rd['columns'][0][:70]}")
        return ("NO_VIOLATION", ok_result or "EQUAL_PD_RD", f"совпадает: {pd['raw']}")

    if kind == "set_decrease":
        # Параметр, подписанный на чертеже не одним числом: у кровли свой уклон у каждого
        # участка. Сторона несёт весь набор (`with_all_values`), и уменьшением объявляется
        # только сдвиг всего набора — наибольшее значение рабочей стадии ниже наименьшего
        # проектного. Набор, который пересекается с проектным, — не решение: подпись,
        # меньшая наименьшей проектной, может принадлежать другому участку кровли или
        # вовсе лотку, и какому — по чертежу не определить (та же осторожность, что
        # в `_decide_set` по элементам).
        #
        # `tolerance` — доля, ниже которой разница не считается уменьшением: подписи разных
        # участков одной кровли отличаются на десятые (на одном листе Речникова стоят 1,9 %,
        # 2,0 % и 2,1 %), и такую разницу не отличить от разброса по участкам.
        pd_all = pd.get("all_values") or [a]
        rd_all = rd.get("all_values") or [b]
        tol_rel = cmp.get("tolerance", 0.0)
        unit = f" {rule['unit']}" if rule.get("unit") else ""
        shown = f"проект {_join_values(pd_all)}{unit} → рабочая {_join_values(rd_all)}{unit}"

        def _below(value, ref):
            margin = ref * tol_rel if ref > 0 else 0.0
            return value < ref - margin - 1e-9

        if len(pd_all) == len(rd_all) and all(abs(x - y) <= 1e-9 for x, y in zip(pd_all, rd_all)):
            return "NO_VIOLATION", ok_result or "EQUAL_PD_RD", f"значения совпадают: {shown}"
        if _below(max(rd_all), min(pd_all)):
            return ("VIOLATION_PRESENT", bad_result or "VALUE_DECREASE",
                    f"уменьшение на всех участках: {shown}")
        if _below(min(rd_all), min(pd_all)):
            return ("COMPARISON_IMPOSSIBLE", None,
                    f"{shown}: в рабочей стадии есть значение меньше наименьшего проектного, "
                    f"но участков несколько и какому из них принадлежит подпись, по чертежу не определить")
        if min(rd_all) < min(pd_all):
            return ("NO_VIOLATION", ok_result or "NON_TRIGGERING_DIFFERENCE_NO_DECREASE",
                    f"{shown}, разница в пределах разброса подписей по участкам ({tol_rel:.0%})")
        return ("NO_VIOLATION", ok_result or "NON_TRIGGERING_DIFFERENCE_NO_DECREASE",
                f"{shown}, наименьшее значение не уменьшилось")

    if kind == "set_change":
        # Набор значений должен совпасть: шаг координационных осей (KR-054, Р-105). Значение рабочей
        # стадии, которого нет в проекте, — изменение; проектное, которого нет в рабочей, нарушением
        # не считается: лист РД показывает не все оси
        pd_all = sorted({round(x) for x in (pd.get("all_values") or [a])})
        rd_all = sorted({round(x) for x in (rd.get("all_values") or [b])})
        unit = f" {rule['unit']}" if rule.get("unit") else ""
        # число, которое проект пишет текстом на листе того же вида, модель в проекте просто не
        # выписала: специалист (R4-H06, R4-H10) — это проёмы и простенки, а не новый шаг осей
        known = set(pd.get("known_values") or ())
        extra = [x for x in rd_all if x not in pd_all and x not in known]
        named = [x for x in rd_all if x not in pd_all and x in known]
        shown = f"проект {_join_values(pd_all)}{unit} → рабочая {_join_values(rd_all)}{unit}"
        also = (f"; {_join_values(named)}{unit} модель в проекте не выписала, но они стоят текстом на листах проекта "
                f"того же вида" if named else "")
        if not extra:
            return ("NO_VIOLATION", "EQUAL_PD_RD" if rd_all == pd_all else "NON_TRIGGERING_DIFFERENCE_NO_DECREASE",
                    f"{shown}: значений, которых нет в проекте, в рабочей стадии нет{also}")
        return ("VIOLATION_PRESENT", bad_result or "VALUE_MISMATCH",
                f"{shown}: в рабочей стадии есть {_join_values(extra)}{unit} — в проекте таких нет{also}")

    if kind == "class_downgrade":
        order = classes or []
        if a not in order or b not in order:
            return "COMPARISON_IMPOSSIBLE", None, f"класс вне перечня: {a} и {b}"
        ra, rb = order.index(a), order.index(b)
        if rb > ra:
            return "VIOLATION_PRESENT", "CLASS_DOWNGRADE", f"класс понижен: {a} → {b}"
        return "NO_VIOLATION", "EQUAL_PD_RD" if ra == rb else \
            "NON_TRIGGERING_DIFFERENCE_NO_DECREASE", f"{a} → {b}"

    # точность сравнения — по менее точной записи: «159,95» и «159.95» равны,
    # «2854,2» и «2854,20» тоже
    digits = min(_decimals(pd["raw"]), _decimals(rd["raw"]))
    tol = 0.5 * 10 ** (-digits) if digits else 0.5
    equal = abs(a - b) <= tol
    same_raw = re.sub(r"[\s,.]", "", str(pd["raw"])) == re.sub(r"[\s,.]", "", str(rd["raw"]))

    if equal:
        result = "EQUAL_PD_RD" if same_raw and str(pd["raw"]) == str(rd["raw"]) \
            else "EQUAL_AFTER_DECIMAL_NORMALIZATION"
        return "NO_VIOLATION", result, f"значения совпадают: {pd['raw']} и {rd['raw']}"

    if kind == "any_change":
        return "VIOLATION_PRESENT", "VALUE_MISMATCH", f"{a} → {b}"
    if kind == "relative":
        rel = abs(b - a) / abs(a) if a else math.inf
        thr = cmp["threshold"]
        if rel > thr:
            return "VIOLATION_PRESENT", "VALUE_MISMATCH", \
                f"{a} → {b}, отклонение {rel:.1%} больше {thr:.0%}"
        return "NO_VIOLATION", "NON_TRIGGERING_DIFFERENCE_NO_DECREASE", \
            f"{a} → {b}, отклонение {rel:.1%} в пределах {thr:.0%}"
    if kind == "decrease":
        if b < a:
            return "VIOLATION_PRESENT", bad_result or "VALUE_DECREASE", f"уменьшение: {a} → {b}"
        return "NO_VIOLATION", ok_result or "NON_TRIGGERING_DIFFERENCE_NO_DECREASE", f"увеличение: {a} → {b}"
    if kind == "increase":
        if b > a:
            return "VIOLATION_PRESENT", "VALUE_MISMATCH", f"увеличение: {a} → {b}"
        return "NO_VIOLATION", "NON_TRIGGERING_DIFFERENCE_NO_DECREASE", f"уменьшение: {a} → {b}"
    return "COMPARISON_IMPOSSIBLE", None, f"неизвестный тип сравнения {kind}"


# ---------- исполнительная документация (#42) ----------

EQUAL_RESULTS = {"EQUAL_PD_RD", "EQUAL_AFTER_DECIMAL_NORMALIZATION", "EQUAL_ALL_AVAILABLE_STAGES"}


def id_review(rule, pd, rd, built, label, result, detail, judge, **kwargs):
    """Третий массив — исполнительная документация (ТЗ 1.2). Возвращает (метка, тип, пояснение, заметка).

    Сравнение попарное, как велит сценарий загрузки: построенное сверяется с рабочей стадией,
    а если рабочей нет — с проектной (PD_ID_ONLY). Что построено хуже документации —
    нарушение, даже когда проект и рабочая стадия между собой сошлись; сошлось всё —
    `EQUAL_ALL_AVAILABLE_STAGES`. Если пары ПД — РД нет (одной стадии не нашлось),
    а пара с ИД есть, решение даёт она. `judge` — функция сравнения пары: `decide`
    для одного значения, `decide_set` для набора значений элемента.
    """
    if built is None:
        return label, result, detail, None
    ref, ref_name = (rd, "рабочей") if rd is not None else (pd, "проектной")
    if ref is None:
        return label, result, detail, "значение найдено только в исполнительной документации"
    id_label, id_result, id_detail = judge(rule, ref, built, **kwargs)
    note = f"ИД против {ref_name} стадии: {id_detail}"
    joined = f"{detail}; {note}" if detail else note
    if id_label == "VIOLATION_PRESENT":
        return "VIOLATION_PRESENT", id_result, joined, note
    if id_label == "NO_VIOLATION":
        if label == "NO_VIOLATION":
            all_equal = result in EQUAL_RESULTS and id_result in EQUAL_RESULTS
            return label, ("EQUAL_ALL_AVAILABLE_STAGES" if all_equal else result), joined, note
        if label == "COMPARISON_IMPOSSIBLE" and (pd is None) != (rd is None):
            # пары ПД — РД нет, решает пара с ИД (сценарии PD_ID_ONLY и RD_ID_ONLY): совпадение —
            # «все доступные стадии равны», а не EQUAL_PD_RD, которого не было
            return "NO_VIOLATION", ("EQUAL_ALL_AVAILABLE_STAGES" if id_result in EQUAL_RESULTS else id_result), joined, note
        return label, result, joined, note
    return label, result, joined, note


def lower_evidence(rule, pd, rd, loc, label, evidence):
    """Страницы меньшей толщины плиты, которую решение не сочло понижением (#136): где она названа
    в рабочей стадии и где та же толщина стоит в проекте, хотя бы на листе чертежа. Иначе довод
    «в проекте такая толщина тоже есть» не на что проверить."""
    if label != "NO_VIOLATION" or not (pd and rd) or rule.get("kind") != "element_thickness":
        return
    if not str(loc).startswith("Плиты перекрытия"):
        return
    have = {(e["stage"], e["file_id"], e["pdf_page_number"]) for e in evidence}
    for v in (v for v in rd["value"] if v < min(pd["value"])):
        for side, stage in ((pd, "PD"), (rd, "RD")):
            for fid, page in (side.get("every_pages") or {}).get(v, []):
                if (stage, fid, page) not in have:
                    have.add((stage, fid, page))
                    evidence.append({"stage": stage, "file_id": fid, "pdf_page_number": page,
                                     "quote": f"толщина {_set_raw(rule, [v])}", "localization": "PAGE_LEVEL"})


def id_evidence(built, evidence):
    """Страницы исполнительной документации — в доказательства записи."""
    for fid, page in (built or {}).get("pages", [])[:3]:
        evidence.append({"stage": "ID", "file_id": fid, "pdf_page_number": page,
                         "quote": built["snippet"], "localization": "PAGE_LEVEL"})


# ---------- значения по элементам (вторая очередь) ----------

BINDING_RANK = {"CLAUSE": 0, "PAGE": 1, "PATH": 2, "SHEET": 3}


def _set_raw(rule, values):
    if rule.get("kind") == "element_class":
        return "/".join(elements.class_label(v) for v in values)
    if rule.get("kind") == "element_rebar_class":
        return "/".join(f"А{v:g}" for v in values)
    if rule.get("kind") == "element_steel_grade":
        return "/".join(grade for _strength, grade in values)
    return "/".join(f"{v:g}" for v in values) + " мм"


def reconcile_set(rule, cands, by_registry=False):
    """Значения элемента в стадии — множество, как в эталоне: «1000/1200 мм».

    Страницы доказательств — по крепости привязки, затем по числу упоминаний на странице;
    `by_registry` — вместо числа упоминаний порядок реестра: акты освидетельствования идут
    серией с одним значением, и доказательство — первый акт, а не тот, где значение
    повторено чаще (#42).

    Сказанное в указаниях (привязка CLAUSE) сильнее таблицы листа и пути файла: в томе
    фундаментной плиты Речникова таблица расхода бетона несёт и чужие строки. Страницы
    доказательств — сначала указания, затем таблицы с теми же значениями.

    Привязка «лист» — запасной источник: значение стоит на чертеже и может относиться
    к соседнему элементу. Раньше она отбрасывалась совсем, и на объекте, где рабочая
    документация — сканы чертежей, стадия оставалась пустой: у контрольного объекта
    правило находило 14 кандидатов класса бетона и не брало ни одного (#52). Теперь
    она берётся, когда привязки крепче в стадии нет вовсе, и остаётся видна в находке
    полем `binding`: решение по ней принимается так же, но источник назван.
    """
    usable = [c for c in cands if c["binding"] != "SHEET"]
    if not usable:
        usable = list(cands)
    if not usable:
        return None
    # значение, прочитанное только распознаванием и похожее на ошибку чтения, — вопрос
    # инспектору, а не часть множества (#41): «B50» три раза рядом с «B30» 62 раза
    doubtful = recognized_doubts(cands)
    doubted = {d["key"] for d in doubtful}
    usable = [c for c in usable if c["value"] not in doubted] or usable
    best = min(BINDING_RANK[c["binding"]] for c in usable)
    chosen = [c for c in usable if BINDING_RANK[c["binding"]] == best]
    values = sorted({c["value"] for c in chosen})
    support = collections.Counter()
    for c in cands:
        if c["value"] in values:
            support[(BINDING_RANK[c["binding"]], c["file_id"], c["page"])] += 1
    ranked = sorted(support.items(), key=lambda kv: (kv[0][0], 0 if by_registry else -kv[1], kv[0][1], kv[0][2]))
    pages = []
    for (_, fid, page), _n in ranked:
        if (fid, page) not in pages:
            pages.append((fid, page))
    first = next(c for c in chosen if (c["file_id"], c["page"]) == pages[0])
    # множество собрано только из распознанных упоминаний, а текстовый слой той же стадии
    # (другие страницы, слабее привязанные) называет иное значение — инспектор решает, какое верно
    machine_only = all(c.get("text_source") == "RECOGNIZED" for c in chosen)
    layer_other = sorted({c["value"] for c in cands if c.get("text_source") != "RECOGNIZED"} - set(values))
    # строки протоколов испытаний среди выбранных: в находке сказано, откуда класс построенного (#62)
    protocol_rows = sum(1 for c in chosen if c.get("source") == "PROTOCOL")
    # значения, названные только перечнем толщин без границ плит (#136)
    enumerated = [v for v in values if all(c.get("enumerated") for c in chosen if c["value"] == v)]
    # все значения стадии при любой привязке, лист чертежа тоже: у Речникова плита на −2,100
    # толщиной 200 мм в ПД есть только подписью «t=200» на листе КР2-кор3 (#136)
    every = sorted({c["value"] for c in cands})
    every_pages = collections.defaultdict(list)
    for c in sorted(cands, key=lambda c: (BINDING_RANK[c["binding"]], c["file_id"], c["page"])):
        if (c["file_id"], c["page"]) not in every_pages[c["value"]] and len(every_pages[c["value"]]) < 2:
            every_pages[c["value"]].append((c["file_id"], c["page"]))
    return {
        "value": values,
        "raw": _set_raw(rule, values),
        "columns": [_set_raw(rule, [v]) for v in values],
        "snippet": first["snippet"],
        "pages": pages,
        "support": len(pages),
        "binding": next(k for k, v in BINDING_RANK.items() if v == best),
        "alternatives": [{"value": _set_raw(rule, [v])} for v in sorted({c["value"] for c in usable} - set(values))],
        "text_source": "RECOGNIZED" if any(c.get("text_source") == "RECOGNIZED" for c in chosen) else None,
        **({"doubtful": _doubt_view(doubtful)} if doubtful else {}),
        **({"layer_conflict": _set_raw(rule, layer_other)} if machine_only and layer_other else {}),
        **({"protocol_rows": protocol_rows} if protocol_rows else {}),
        **({"enumerated": enumerated} if enumerated else {}),
        "every": every,
        "every_pages": dict(every_pages),
    }


# Конструкции, которые стадии называют по-разному. Фундамент здания на сваях проект
# описывает ростверком, а рабочая документация — плитой; перекрытие в одном томе
# «плита перекрытия», в другом «горизонтальная конструкция». Это подсказка инспектору,
# а не правило сравнения: ленточный ростверк и плита — разные вещи, эталон организатора
# держит их порознь, и слить их значило бы объявлять нарушения наугад (#52).
KIN_ELEMENTS = [
    {"Ростверки", "Распределительный ростверк", "Фундаментная плита"},
    {"Плиты перекрытия подземной части", "Плиты перекрытия надземной части"},
    {"Вертикальные конструкции подземной части", "Вертикальные конструкции надземной части"},
]


def kin_of(element, others):
    """Родственные названия элемента среди названных в другой стадии."""
    out = []
    for group in KIN_ELEMENTS:
        if element in group:
            out += sorted(x for x in others if x in group and x != element)
    return out


def _elsewhere(named, stage, element=None):
    """Для каких других элементов значение в этой стадии всё-таки названо.

    Инспектору надо видеть, чего ждать: «класс назван, но для других элементов» — это повод
    посмотреть самому, а «не назван вовсе» — повод искать документ. Если среди названных есть
    конструкция, которую стадии зовут по-разному, об этом сказано прямо: чаще всего сравнение
    не складывается именно так, а не потому, что в документации чего-то нет (#52).
    """
    others = sorted(named.get(stage) or ())
    where = "проектной" if stage == "PD" else "рабочей"
    if not others:
        return f"значение в {where} стадии не найдено ни для одного элемента"
    detail = f"значение в {where} стадии не найдено; для других элементов оно там названо: {', '.join(others)}"
    kin = kin_of(element, others) if element else []
    if kin:
        detail += (f". Возможно, это та же конструкция под другим названием: {', '.join(kin)} — "
                   f"сверьте сами, система их не отождествляет")
    return detail


def decide_set(rule, pd, rd, named=None, element=None):
    """Решение по элементу с поправками, которые делает сам параметр.

    Марка стали: замена марки без понижения прочности — не нарушение по триггеру параметра,
    но и не «разница, которая не срабатывает»: организатор держит такой случай кандидатом
    на проверку согласованного изменения (`pipeline/steel.py`, Р-62).
    """
    label, result, detail = _decide_set(rule, pd, rd, named, element)
    if (rule.get("kind") == "element_steel_grade" and label == "NO_VIOLATION"
            and result == "NON_TRIGGERING_DIFFERENCE_NO_DECREASE"):
        return steel.substitution(pd, rd)
    return label, result, detail


def _decide_set(rule, pd, rd, named=None, element=None):
    """Решение по элементу: наименьшее значение в РД против наименьшего в ПД.

    named — какие элементы названы в каждой стадии у этого параметра: нужно, чтобы
    объяснить, почему сравнивать нечего.
    """
    named = named or {}
    if pd is None and rd is None:
        return None, None, "значение не найдено ни в одной стадии"
    if pd is None:
        return "COMPARISON_IMPOSSIBLE", None, _elsewhere(named, "PD", element)
    if rd is None:
        return "COMPARISON_IMPOSSIBLE", None, _elsewhere(named, "RD", element)
    if pd["value"] == rd["value"]:
        return "NO_VIOLATION", "EQUAL_PD_RD", f"значения совпадают: {pd['raw']} и {rd['raw']}"
    if min(rd["value"]) < min(pd["value"]):
        lower = [v for v in rd["value"] if v < min(pd["value"])]
        listed = set(rd.get("enumerated") or [])
        slab = rule.get("kind") == "element_thickness" and str(element or "").startswith("Плиты перекрытия")
        in_pd = set(pd.get("every") or []) if slab else set()
        if lower and all(v in listed or v in in_pd for v in lower):
            # Меньшая толщина плиты не привязана к плите с границей: названа перечнем («350, 250,
            # 200 мм») или в проекте та же толщина тоже есть, хотя бы на листе чертежа. Специалист
            # (#136): «если явно не указана граница плиты перекрытия — то не нарушение». На Речникове
            # 200 мм — ветви рампы на засыпке и плита на −2,100, которая с t=200 есть и в ПД
            why = "; ".join(f"{_set_raw(rule, [v])} — " + ("в проекте такая толщина тоже есть" if v in in_pd
                                                           else "названы только перечнем без границ плит")
                            for v in lower)
            if set(pd["value"]) & set(rd["value"]) or all(v in in_pd for v in lower):
                return ("NO_VIOLATION", "NON_TRIGGERING_DIFFERENCE_NO_DECREASE",
                        f"{pd['raw']} → {rd['raw']}: {why}; граница плиты с меньшей толщиной явно не указана, "
                        f"поэтому это не нарушение")
            return ("COMPARISON_IMPOSSIBLE", None,
                    f"{pd['raw']} → {rd['raw']}: {why}; какой плите какая толщина, по тексту не определить")
        if rd["binding"] != "CLAUSE":
            # понижение только из таблицы листа или пути файла инспектору объявлять рано
            return ("COMPARISON_IMPOSSIBLE", None,
                    f"уменьшение {pd['raw']} → {rd['raw']} видно только в таблице листа или по пути файла, "
                    f"в указаниях рабочей стадии значение не названо")
        return "VIOLATION_PRESENT", rule["compare"]["result"], f"уменьшение: {pd['raw']} → {rd['raw']}"
    # Новое значение в РД меньше проектного наибольшего: на Речникове в ПД плита 900 мм под корпусами
    # и 600 под паркингом, а в РД корпуса 1 есть участки t=800. Без привязки к части здания
    # не сказать, уменьшение это или другой участок, и «нарушения нет» было бы утверждением наугад.
    new_lower = sorted(set(rd["value"]) - set(pd["value"]))
    new_lower = [v for v in new_lower if v < max(pd["value"])]
    if new_lower:
        shown = _set_raw(rule, new_lower)
        return ("COMPARISON_IMPOSSIBLE", None,
                f"{pd['raw']} → {rd['raw']}: в рабочей стадии есть {shown}, меньше проектного наибольшего; "
                f"какой части здания это значение, по тексту не определить")
    return ("NO_VIOLATION", "NON_TRIGGERING_DIFFERENCE_NO_DECREASE",
            f"{pd['raw']} → {rd['raw']}, наименьшее значение не уменьшилось")


def _slug(location):
    return re.sub(r"\s+", "-", location.strip().lower())


def element_findings(object_id, code, rule, found, catalog):
    """Находки параметра по элементам: одна запись на элемент, как в эталоне организатора."""
    cat = catalog.get(code, {})
    by_loc = collections.defaultdict(lambda: collections.defaultdict(list))
    named = {"PD": set(), "RD": set(), "ID": set()}
    for stage in ("PD", "RD", "ID"):
        for c in found.get(stage, []):
            by_loc[c["location"]][stage].append(c)
            named[stage].add(c["location"])
    out = []
    for loc in sorted(by_loc):
        sides, fallback = {}, {}
        history = {}
        outside = {}
        for stage, field in (("PD", "source_pd"), ("RD", "source_rd"), ("ID", "source_rd")):
            cands, fb = prefer_source(latest_only(by_loc[loc].get(stage, [])), source_hints(cat.get(field)))
            if fb and stage in (rule.get("strict_source") or []):
                # только раздел-источник (`strict_source`): у KR-058 толщина РД — из томов КЖ, а не из сноски
                # «по чертежам КЖ» в томе дренажа (#229). Нет значения в КЖ — сравнивать не с чем
                outside[stage] = sorted({os.path.basename(c["document"]) for c in cands})
                cands, fb = [], False
            sides[stage], fallback[stage] = reconcile_set(rule, cands, by_registry=(stage == "ID")), fb
            history[stage] = revision_history(by_loc[loc].get(stage, []), sides[stage])
        pd, rd, built = sides["PD"], sides["RD"], sides["ID"]
        label, result, detail = decide_set(rule, pd, rd, named, loc)
        if outside.get("RD") and rd is None and label == "COMPARISON_IMPOSSIBLE":
            detail = (f"в томах рабочей стадии, которые каталог называет источником, значения нет; вне их оно "
                      f"названо ({', '.join(outside['RD'][:3])}), но такое значение не берётся")
        # исполнительная документация: построенное против рабочей стадии (#42)
        label, result, detail, id_note = id_review(rule, pd, rd, built, label, result, detail, decide_set)
        if label is None and built is not None:
            label, result, detail = "COMPARISON_IMPOSSIBLE", None, id_note
        if label is None:
            continue
        # привязка не из указаний — сказано в пояснении, не только полем `binding` (#41)
        detail = "; ".join(filter(None, [detail, binding_note(pd, rd, built), protocol_note(built)]))
        evidence = []
        for side, stage in ((pd, "PD"), (rd, "RD")):
            if side:
                for fid, page in side["pages"][:3]:
                    evidence.append({"stage": stage, "file_id": fid, "pdf_page_number": page,
                                     "quote": side["snippet"], "localization": "PAGE_LEVEL"})
        lower_evidence(rule, pd, rd, loc, label, evidence)
        id_evidence(built, evidence)
        out.append({
            "finding_id": f"{object_id}::{code}::{_slug(loc)}",
            "object_id": object_id,
            "matrix_scope": "MATRIX",
            "parameter_code": code,
            "parameter_id": cat.get("parameter_id"),
            "title": cat.get("parameter_name"),
            "comparison_result": result or "VALUE_MISMATCH",
            "location_type": "CONSTRUCTION_ELEMENT",
            "locations": [loc],
            "pd_value": pd and pd["raw"],
            "rd_value": rd and rd["raw"],
            "id_value": built and built["raw"],
            "violation_label": label,
            "criticality": cat.get("criticality") if label == "VIOLATION_PRESENT" else None,
            "finding_status": "CANDIDATE",
            # замена марки без понижения прочности: решение о согласованности изменения — за инспектором
            **({"needs_expert": True} if result == steel.SUBSTITUTION else {}),
            "evidence": evidence,
            "extraction": {
                "rule_basis": rule.get("basis"),
                "detail": detail,
                "source_fallback": fallback,
                "pd": pd and _side_view(pd, ELEMENT_SIDE_VIEW, history["PD"]),
                "rd": rd and _side_view(rd, ELEMENT_SIDE_VIEW, history["RD"]),
                "id": built and _side_view(built, ELEMENT_SIDE_VIEW, history["ID"]),
                "id_check": id_note,
            },
        })
    return out


SIDE_VIEW = ("value", "all_values", "raw", "support", "alternatives", "columns", "column_choice",
             "text_source", "doubtful", "layer_conflict")
ELEMENT_SIDE_VIEW = SIDE_VIEW + ("binding", "protocol_rows")


def _side_view(side, keys, revisions):
    # ключи необязательные: выбор колонки (column_choice) ставится только там, где колонку
    # выбирало правило, привязка (binding) — только у параметров по элементам,
    # источник текста (text_source) — только там, где значение прочитано машиной
    view = {k: side[k] for k in keys if k in side and not (k == "text_source" and side[k] is None)}
    if revisions:
        view["revisions"] = revisions
    return view


def _plural(value, forms):
    """Форма подписи по числу: «1 позиция», «3 позиции», «16 позиций», «21 позиция»."""
    if not isinstance(value, (int, float)):
        return forms[-1]
    n = abs(int(value))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


# ---------- сравнение по номерам: группы ВРУ, стояки (пятая очередь) ----------

# правила, которые сверяют стадии по помещениям и установкам: pipeline/room_compare.py, задача #37
ROOM_KINDS = {"room_systems", "vent_units"}
KEYED_KINDS = {"switchboard_breakers", "switchboard_cables", "riser_diameters", "booster_pumps", "layer_stack",
               "switchboard_fire_cables", "smoke_fans", "mgn_toilet_area", "fire_barrier_limits", "sewer_outlets",
               "outdoor_fire_water"}
_KEYED_WHAT = {"switchboard_breakers": "групп ВРУ", "switchboard_cables": "групп ВРУ", "riser_diameters": "стояков",
               "booster_pumps": "повысительных установок", "layer_stack": "составов",
               "fire_barrier_limits": "мест с противопожарными преградами",
               "switchboard_fire_cables": "линий с огнестойким кабелем", "smoke_fans": "систем противодымной вентиляции",
               "mgn_toilet_area": "помещений МГН", "sewer_outlets": "выпусков канализации",
               "outdoor_fire_water": "показателей наружного пожаротушения"}
_KEYED_FORMS = {"switchboard_breakers": ("группа", "группы", "групп"), "switchboard_cables": ("группа", "группы", "групп"),
                "riser_diameters": ("стояк", "стояка", "стояков"),
                "booster_pumps": ("установка", "установки", "установок"),
                "layer_stack": ("состав", "состава", "составов"),
                "fire_barrier_limits": ("место", "места", "мест"),
                "switchboard_fire_cables": ("линия", "линии", "линий"), "smoke_fans": ("система", "системы", "систем"),
                "mgn_toilet_area": ("помещение", "помещения", "помещений"),
                "sewer_outlets": ("выпуск", "выпуска", "выпусков"),
                "outdoor_fire_water": ("показатель", "показателя", "показателей")}
# адресация записи с нарушением: номер помещения — как в эталоне организатора
_KEYED_LOCATION = {"mgn_toilet_area": "ROOM", "fire_barrier_limits": "ROOM", "outdoor_fire_water": "OBJECT"}


def _count(kind, n, suffix=""):
    """«154 группы», «15 стояков»."""
    one, few, many = _KEYED_FORMS[kind]
    if n % 10 == 1 and n % 100 != 11:
        word = one
    elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        word = few
    else:
        word = many
    return f"{n} {word}{suffix}"


def _pages(cands, keys=None, limit=3):
    """Страницы, где больше всего нужных номеров."""
    count = collections.Counter()
    for c in cands:
        if keys is None or c["key"] in keys:
            count[(c["file_id"], c["page"])] += 1
    return [p for p, _ in sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))][:limit]


def _keyed_summary(kind, keyed, keys):
    """Значение стадии для записи без нарушения: сколько сверено и в каком диапазоне."""
    keys = sorted(keys)
    if kind == "switchboard_breakers":
        currents = sorted({int(m.group(1)) for k in keys for v in keyed[k] for m in [re.search(r"(\d+) А$", v)] if m})
        head = _count(kind, len(keys))
        return f"{head}: {currents[0]}–{currents[-1]} А" if currents else head
    if kind == "switchboard_cables":
        fire = sum(1 for k in keys if any(c["fire"] for c in keyed[k].values()))
        return f"{_count(kind, len(keys))}, с огнестойким кабелем {fire}"
    if kind == "switchboard_fire_cables":
        return f"{_count(kind, len(keys))}, огнестойкий кабель во всех"
    if kind == "smoke_fans":
        flows = sorted({f for k in keys for f, _ in keyed[k]})
        return f"{_count(kind, len(keys))}: L={flows[0]}–{flows[-1]} м³/ч"
    if kind == "booster_pumps":
        shown = [f"{k}: {pumps.show(v)}" for k in keys for v in pumps._best(keyed[k]).values()]
        return "; ".join(shown[:4]) + (f" и ещё {len(shown) - 4}" if len(shown) > 4 else "")
    if kind == "layer_stack":
        shown = [f"{k}: {v}" for k in keys for v in sorted(keyed[k])]
        return "; ".join(shown[:3]) + (f" и ещё {len(shown) - 3}" if len(shown) > 3 else "")
    if kind == "mgn_toilet_area":
        areas = sorted({a for k in keys for a in keyed[k]})
        span = f"{areas[0]:g}" if areas[0] == areas[-1] else f"{areas[0]:g}–{areas[-1]:g}"
        return f"{_count(kind, len(keys))}: {span} м²".replace(".", ",")
    if kind == "outdoor_fire_water":
        return "; ".join(f"{k}: {outdoor_water.show(k, keyed[k])}" for k in keys)
    if kind == "fire_barrier_limits":
        shown = sorted({fire_doors.show(v) for k in keys for v in keyed[k]},
                       key=lambda x: (int(re.search(r"\d+", x).group()), x))
        return f"{_count(kind, len(keys))}: {', '.join(shown)}" if shown else _count(kind, len(keys))
    sizes = sorted({d for k in keys for d in keyed[k]})
    head = _count(kind, len(keys))
    return f"{head}: ⌀{sizes[0]}–⌀{sizes[-1]}" if sizes else head


def _wall_changes(pd_c, rd_c):
    """Утеплитель наружных стен ZU-125 (#137): набор толщин РД против ПД.

    Тип РД сравнивается с тем же типом ПД, выноска без типа — со всеми составами ПД. Специалист:
    неидентичная теплоизоляция без расчётного обоснования — нарушение (V-insulation-walls). Набор РД,
    совпадающий с графой «было» ведомости изменений ПД, — рабочая стадия не обновлена после
    корректировки ПД: это пишется в пояснение.
    """
    now = [c for c in pd_c if c.get("form") != "before"]
    by_type, every = collections.defaultdict(set), collections.defaultdict(set)
    for c in now:
        by_type[c["key"]].add(c["value"])
        every[c["value"]].add(c["key"])
    before = collections.defaultdict(set)
    for c in pd_c:
        if c.get("form") == "before":
            before[c["value"]].add(c["key"])
    changes, pdk, rdk, justified, flagged = [], {}, {}, [], set()
    if not every:
        return changes, pdk, rdk, justified
    # сначала записи РД с типом: выноска без типа с тем же набором их не повторяет
    for r in sorted(rd_c, key=lambda c: not c["key"]):
        name = f"тип {r['key']}" if r["key"] else "наружные стены"
        allowed = by_type.get(r["key"]) if r["key"] and by_type.get(r["key"]) else set(every)
        pdk.setdefault(name, set()).update(allowed)
        rdk.setdefault(name, set()).add(r["value"])
        r["key"] = name
        if r["value"] in allowed or (name == "наружные стены" and r["value"] in flagged) \
                or (name, r["value"]) in flagged:
            continue
        flagged.update({r["value"], (name, r["value"])})
        why = f"утеплитель {' или '.join(sorted(allowed))} → {r['value']}"
        if r["value"] in before:
            why += (f"; совпадает с составом ПД до корректировки (ведомость изменений, типы "
                    f"{', '.join(sorted(before[r['value']]))}) — рабочая стадия не обновлена после корректировки ПД")
        changes.append((name, sorted(allowed), [r["value"]], why))
        if r.get("justified"):
            justified.append(name)
    for c in now:
        c["key"] = next((n for n in pdk if n == f"тип {c['key']}"), c["key"])
    return changes, pdk, rdk, justified


def outdoor_water_sides(cands):
    """Кандидаты стадии для PPM-114: расход «здания», если такой назван, иначе все (#145)."""
    flows = [c for c in cands if c["key"] == outdoor_water.FLOW_KEY]
    if any(c.get("building") for c in flows):
        cands = [c for c in cands if c["key"] != outdoor_water.FLOW_KEY or c.get("building")]
    return cands


def keyed_findings(object_id, code, rule, found, catalog):
    """Одна запись на параметр: строки обеих стадий сопоставлены по номеру группы или стояка."""
    cat = catalog.get(code, {})
    kind = rule["kind"]
    sides, fallback = {}, {}
    for stage, field in (("PD", "source_pd"), ("RD", "source_rd")):
        sides[stage], fallback[stage] = prefer_source(latest_only(found.get(stage, [])), rule_hints(rule, cat, field))
    pd_c, rd_c = sides["PD"], sides["RD"]
    if not pd_c and not rd_c:
        return []
    note, signs, ask = "", [], False
    if kind in ("switchboard_cables", "switchboard_fire_cables"):
        pdk, rdk = {}, {}
        for cands, keyed in ((pd_c, pdk), (rd_c, rdk)):
            for c in cands:
                keyed.setdefault(c["key"], {}).update({x["raw"]: x for x in c["cables"]})
        if kind == "switchboard_cables":
            changes = [(k, p, r, "; ".join(why)) for k, p, r, why in switchboards.cable_changes(pdk, rdk)]
        else:
            # сравниваются линии, которым проект назначил огнестойкий кабель; огнестойкий кабель,
            # появившийся только в РД, считается строкой «только в РД»
            designed = switchboards.fire_lines(pdk)
            pdk = {k: v for k, v in pdk.items() if k in designed}
            rdk = {k: v for k, v in rdk.items() if k in designed or k in switchboards.fire_lines(rdk)}
            changes = [(k, p, r, "огнестойкий кабель в РД не указан")
                       for k, p, r in switchboards.fire_cable_losses(pdk, rdk)]
    elif kind == "layer_stack":
        # составы стадий связываются по номеру типа, новый тип РД — по назначению, выноска разреза
        # кровли — по сходству набора слоёв (#137). У выноски толщины стоят отдельной колонкой:
        # у кровли сравнивается набор слоёв, несущая плита слоем кровли не считается
        profile = rule.get("profile") or "pavement"
        roof = profile == "roof"
        pdk, rdk, changes, justified, linked = {}, {}, [], [], []
        if profile == "wall":
            changes, pdk, rdk, justified = _wall_changes(pd_c, rd_c)
        for key, p, r, how in (layers.pair(pd_c, rd_c, profile) if profile != "wall" else ()):
            name = f"тип {key}"
            # добавленный слой кровли — «признак изменения состава», не нарушение (R4-Q-AR-044)
            diffs = layers.differences(p["layers"], r["layers"], thickness=not roof,
                                       complete=not roof or any(x["kind"] == "base" for x in r["layers"]),
                                       ignore={"base"} if roof else (), added=not roof)
            if name in pdk:
                continue
            pdk[name], rdk[name] = {p["value"]}, {r["value"]}
            p["key"] = r["key"] = name
            if roof:
                more = layers.added_layers(p["layers"], r["layers"], ignore={"base"})
                if more:
                    signs.append((name, more))
            if diffs:
                changes.append((name, [p["value"]], [r["value"]], "; ".join(diffs)))
                if how not in ("по номеру типа", ""):
                    linked.append(f"{name} связан с проектным {how}")
                if r.get("justified"):
                    justified.append(name)
        if linked:
            note = "; " + "; ".join(linked[:3])
        if signs:
            added = "; ".join(f"{n}: {', '.join(m)}" for n, m in signs[:3])
            note += (f"; в рабочей стадии добавлены слои ({added}) — это признак изменения "
                     f"состава для проектировщика, а не нарушение")
        if justified:
            note += (f"; в рабочей стадии рядом с составом есть расчётное обоснование ({', '.join(justified[:3])}) — "
                     f"изменение решает инспектор, а не правило")
    else:
        if kind == "booster_pumps":
            pumps.adopt_zones(pd_c, rd_c)
        if kind == "outdoor_fire_water":
            # расход, про который сказано «здания», сильнее безымянного: безымянный бывает
            # расходом сети из другого раздела (у ДОО 110 л/с ИОС2.2 при 20 л/с ТБЭ и ЭЭ)
            pd_c, rd_c = outdoor_water_sides(pd_c), outdoor_water_sides(rd_c)
        pdk, rdk = collections.defaultdict(set), collections.defaultdict(set)
        for cands, keyed in ((pd_c, pdk), (rd_c, rdk)):
            for c in cands:
                keyed[c["key"]].add(c["value"])
        if kind == "switchboard_breakers":
            changes = [(k, p, r, "номинал автомата изменён") for k, p, r in switchboards.breaker_changes(pdk, rdk)]
        elif kind == "smoke_fans":
            changes = [(k, p, r, ", ".join(why)) for k, p, r, why in smoke_fans.reductions(pdk, rdk)]
            below = smoke_fans.below_duty(rd_c)
            if below:
                shown = "; ".join(f"{k} L={calc[0]} из {duty[0]} м³/ч ({(calc[0] - duty[0]) / duty[0]:+.0%}), "
                                  f"Pc={calc[1]} из {duty[1]} Па" for k, duty, calc in below[:6])
                more = f" и ещё {len(below) - 6}" if len(below) > 6 else ""
                note = (f"; в листах подбора РД расчётная точка вентилятора ниже заданной у "
                        f"{_count(kind, len(below))}: {shown}{more}")
        elif kind == "booster_pumps":
            # специалист (#135): занижение расхода или напора — нарушение, завышение до 20 % — нет
            changes, higher = pumps.compare(pdk, rdk)
            if higher:
                shown = "; ".join(f"{k}: {', '.join(p)} → {', '.join(r)} ({why})" for k, p, r, why in higher[:4])
                note = (f"; в рабочей стадии параметры выше проектных больше чем на {pumps.EXCESS:.0%}: {shown} — "
                        f"это не нарушение, но стоит проверить подбор")
        elif kind == "mgn_toilet_area":
            changes = [(k, p, r, "площадь уменьшена") for k, p, r in mgn_rooms.reductions(pdk, rdk)]
        elif kind == "outdoor_fire_water":
            changes = [(k, [outdoor_water.show(k, p)], [outdoor_water.show(k, r)], "меньше проектного")
                       for k, p, r in outdoor_water.reductions(pdk, rdk)]
            existing = [c for c in pd_c if c.get("existing")]
            if existing and not rdk.get(outdoor_water.HYDRANT_KEY):
                note = ("; в проектной стадии здание обеспечивают существующие гидранты городской сети — "
                        "в рабочей стадии их могут не показывать: это не нарушение, а вопрос инспектору")
        elif kind == "fire_barrier_limits":
            # утверждения без места в сравнение не идут: место — единственный ключ, общий
            # у стадий. Их марки остаются в пояснении ниже
            pdk.pop(fire_doors.NO_PLACE_KEY, None)
            rdk.pop(fire_doors.NO_PLACE_KEY, None)
            changes = fire_doors.reductions(pdk, rdk)
            # марка, под которой в рабочей стадии стоит несколько разных пределов, вердикта
            # не даёт: на Алтуфьевском Д-6 подписана EI30, EI45 и EI60, и какая дверь какая,
            # видно только на плане (#93)
            ambiguous = fire_doors.ambiguous_marks(rd_c)
            if ambiguous:
                shown = "; ".join(f"{mark}: {', '.join(sorted(v))}" for mark, v in sorted(ambiguous.items())[:4])
                note = (f"; в рабочей стадии под одной маркой стоят разные пределы ({shown}) — "
                        f"какая дверь какая, видно только на плане: сверьте сами")
        else:
            changes = [(k, [f"⌀{d}" for d in p], [f"⌀{d}" for d in r], "диаметр уменьшен")
                       for k, p, r in risers.reductions(pdk, rdk)]
            if kind == "sewer_outlets":
                # выпуски без номера в одной стадии и с номерами в другой: наименьший диаметр системы
                # не сравнивается, сопоставляет инспектор (специалист, R4-Q-IOS3-074: needs_expert)
                loose = outlets.numbering_mismatch(pdk, rdk)
                if loose:
                    ask = True
                    shown = "; ".join(f"{system}: в проекте {', '.join(p)}, в рабочей {', '.join(r)}"
                                      for system, p, r in loose[:3])
                    note += (f"; выпуски одной системы обозначены в стадиях по-разному ({shown}) — какой выпуск "
                             f"чему соответствует, решает инспектор")
    what = _KEYED_WHAT[kind]
    common = set(pdk) & set(rdk)
    changed = [k for k, *_ in changes]
    if not pd_c or not rd_c:
        stage = "проектной" if not pd_c else "рабочей"
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = f"{what[0].upper()}{what[1:]} в {stage} стадии не найдено"
    elif not common:
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = f"номера {what} в ПД и РД не совпадают: сопоставить нечего"
    elif changes:
        label, result = "VIOLATION_PRESENT", rule["compare"]["result"]
        shown = "; ".join(f"{k}: {', '.join(p)} → {', '.join(r)} ({why})" for k, p, r, why in changes[:5])
        more = f" и ещё {len(changes) - 5}" if len(changes) > 5 else ""
        detail = f"расходится {len(changes)} из {len(common)} {what}: {shown}{more}"
    else:
        # разница есть, но нарушением не срабатывает: у кровли добавлен слой (R4-Q-AR-044)
        label, result = "NO_VIOLATION", "NON_TRIGGERING_DIFFERENCE_NO_DECREASE" if signs else "EQUAL_PD_RD"
        suffix = " ВРУ" if kind in ("switchboard_breakers", "switchboard_cables") else ""
        detail = (f"сверено {_count(kind, len(common), suffix)}, расхождений нет; "
                  f"только в ПД {len(set(pdk) - set(rdk))}, только в РД {len(set(rdk) - set(pdk))}")
    detail += note
    if changes:
        pd_value = "; ".join(f"{k}: {', '.join(p)}" for k, p, _r, _w in changes[:5])
        rd_value = "; ".join(f"{k}: {', '.join(r)}" for k, _p, r, _w in changes[:5])
    elif kind == "outdoor_fire_water":
        # показателей два, и значения стадии понятнее счёта: «расход …: 30 л/с; число …: 2 гидранта»
        pd_value = _keyed_summary(kind, pdk, set(pdk)) or None
        rd_value = _keyed_summary(kind, rdk, set(rdk)) or None
    else:
        pd_value = _keyed_summary(kind, pdk, common) if common else (_count(kind, len(pdk)) if pdk else None)
        rd_value = _keyed_summary(kind, rdk, common) if common else (_count(kind, len(rdk)) if rdk else None)
    evidence = []
    wanted = set(changed) if changed else common
    for cands, stage in ((pd_c, "PD"), (rd_c, "RD")):
        for fid, page in _pages(cands, wanted or None):
            snippet = next((c["snippet"] for c in cands if (c["file_id"], c["page"]) == (fid, page)
                            and (not wanted or c["key"] in wanted)), "")
            evidence.append({"stage": stage, "file_id": fid, "pdf_page_number": page,
                             "quote": snippet, "localization": "PAGE_LEVEL"})
    violation = label == "VIOLATION_PRESENT"
    expert = (kind == "layer_stack" and violation and "расчётное обоснование" in note) \
        or (kind == "outdoor_fire_water" and "существующие гидранты" in note) or ask
    return [{
        "finding_id": f"{object_id}::{code}",
        "object_id": object_id,
        "matrix_scope": "MATRIX",
        "parameter_code": code,
        "parameter_id": cat.get("parameter_id"),
        "title": cat.get("parameter_name"),
        **({"needs_expert": True} if expert else {}),
        "comparison_result": result or "VALUE_MISMATCH",
        # разница без нарушения (добавленный слой кровли) — у своих составов: «нарушения нет» по типу II и III
        "location_type": _KEYED_LOCATION.get(kind, "CONSTRUCTION_ELEMENT") if violation or signs else "OBJECT",
        "locations": changed[:20] if violation else [n for n, _m in signs][:20] or ["Здание"],
        "pd_value": pd_value,
        "rd_value": rd_value,
        "id_value": None,
        "violation_label": label,
        "criticality": cat.get("criticality") if violation else None,
        "finding_status": "CANDIDATE",
        "evidence": evidence,
        "extraction": {
            "rule_basis": rule.get("basis"),
            "detail": detail,
            "source_fallback": fallback,
            "pd": {"raw": pd_value, "compared": len(common), "keys": len(pdk)},
            "rd": {"raw": rd_value, "compared": len(common), "keys": len(rdk)},
        },
    }]


def jets_findings(object_id, code, rule, found, catalog):
    """Расход ВПВ: наборы расчётных случаев обеих стадий, одна запись на здание (третья очередь)."""
    cat = catalog.get(code, {})
    sides, fallback = {}, {}
    for stage, field in (("PD", "source_pd"), ("RD", "source_rd")):
        sides[stage], fallback[stage] = prefer_source(latest_only(found.get(stage, [])), rule_hints(rule, cat, field))
    pd = {c["value"] for c in sides["PD"]}
    rd = {c["value"] for c in sides["RD"]}
    label, result, detail = fire_water.decide(pd, rd)
    if label is None:
        return []
    evidence = _page_evidence(sides)
    violation = label == "VIOLATION_PRESENT"
    return [{
        "finding_id": f"{object_id}::{code}",
        "object_id": object_id,
        "matrix_scope": "MATRIX",
        "parameter_code": code,
        "parameter_id": cat.get("parameter_id"),
        "title": cat.get("parameter_name"),
        "comparison_result": result or "VALUE_MISMATCH",
        "location_type": "OBJECT",
        "locations": ["Здание"],
        "pd_value": fire_water.show(pd),
        "rd_value": fire_water.show(rd),
        "id_value": None,
        "violation_label": label,
        "criticality": cat.get("criticality") if violation else None,
        "finding_status": "CANDIDATE",
        "evidence": evidence,
        "extraction": {
            "rule_basis": rule.get("basis"),
            "detail": detail,
            "source_fallback": fallback,
            "pd": {"raw": fire_water.show(pd), "columns": [fire_water.label(*c) for c in sorted(pd)]},
            "rd": {"raw": fire_water.show(rd), "columns": [fire_water.label(*c) for c in sorted(rd)]},
        },
    }]


def _stage_mix(cands):
    """Квартирография стадии: ТЭП, в котором сумма по типам сходится со «всего», иначе сумма строк
    таблиц по документу (секции на разных страницах). Возвращает (числа, кандидаты-доказательства)."""
    teps = [c for c in cands if c["key"] == "tep"]
    full = [c for c in teps if sum(v for k, v in c["counts"].items() if k != "total") == c["counts"]["total"]]
    if full:
        best = max(full, key=lambda c: c["counts"]["total"])
        return best["counts"], [best]
    by_file = collections.defaultdict(dict)
    for c in cands:
        if c["key"] == "table":
            by_file[c["file_id"]][c["page"]] = c
    if not by_file:
        return (teps[0]["counts"], teps[:1]) if teps else ({}, [])
    pages = max(by_file.values(), key=lambda v: sum(sum(c["counts"].values()) for c in v.values()))
    counts = collections.Counter()
    for c in pages.values():
        counts.update(c["counts"])
    return dict(counts), list(pages.values())


def mix_findings(object_id, code, rule, found, catalog):
    """Квартирография PZ-011 (#138): число квартир по типам в ПД и РД, одна запись на здание.

    Специалист (U-flat-mix): смена распределения по типам — нарушение, с оговоркой, что изменение
    могло быть оформлено документом, которого в пакете нет. Поэтому ссылка РД на стадию ПД с
    положительным заключением и переименование студий (марка «Ст.» при названии «однокомнатная»)
    идут в пояснение, а запись требует подтверждения инспектором.

    Четвёртый круг (R4-Q-PZ-011, Р-108): студия — не отдельный тип, стадии сравниваются по числу
    комнат. Студии, ставшие однокомнатными при той же сумме, — «нарушения нет» с пояснением.
    """
    cat = catalog.get(code, {})
    sides, fallback = {}, {}
    for stage, field in (("PD", "source_pd"), ("RD", "source_rd")):
        sides[stage], fallback[stage] = prefer_source(latest_only(found.get(stage, [])), rule_hints(rule, cat, field))
    pd, pd_used = _stage_mix(sides["PD"])
    rd, rd_used = _stage_mix(sides["RD"])
    if not pd and not rd:
        return []
    renamed = sum(c.get("renamed") or 0 for c in rd_used)
    refs = sorted({c["value"] for c in sides["RD"] if c["key"] == "reference"})
    notes = []
    if renamed:
        notes.append(f"{renamed} квартир с маркой «Ст.» в рабочей стадии названы однокомнатными — похоже на "
                     f"переименование студий")
    if refs:
        notes.append(f"рабочая стадия ссылается на проектную: «{refs[0][:160]}» — если этого документа в пакете нет, "
                     f"изменение могло быть оформлено там")
    if not pd or not rd:
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = f"квартирография в {'проектной' if not pd else 'рабочей'} стадии не найдена"
    else:
        diff = apartment_mix.changes(pd, rd)
        shown = "; ".join(f"{apartment_mix.NAME[t]} {a} → {b}" for t, a, b in diff)
        # студии вместе с однокомнатными: «квартира-студия» — не юридическое понятие (R4-Q-PZ-011)
        rooms = apartment_mix.changes(apartment_mix.by_rooms(pd), apartment_mix.by_rooms(rd))
        if rooms:
            label, result = "VIOLATION_PRESENT", "COUNT_MISMATCH"
            detail = "распределение квартир по числу комнат изменено: " + shown
            if any(t == "studio" for t, _a, _b in diff):
                one = next(((a, b) for t, a, b in rooms if t == "1"), None)
                detail += (f"; студии и однокомнатные вместе: {one[0]} → {one[1]}" if one else
                           "; студии и однокомнатные вместе не изменились")
        elif diff:
            label, result = "NO_VIOLATION", "NON_TRIGGERING_DIFFERENCE_NO_DECREASE"
            ones = apartment_mix.by_rooms(pd).get("1", 0)
            detail = (f"число квартир по числу комнат совпадает, студии и однокомнатные вместе — {ones}; изменено "
                      f"только деление между ними ({shown}): отдельного юридического понятия «квартира-студия» нет, "
                      f"это уточнение, а не изменение квартирографии")
        else:
            label, result, detail = "NO_VIOLATION", "EQUAL_PD_RD", "число квартир по типам совпадает"
    if notes:
        detail += "; " + "; ".join(notes)
    violation = label == "VIOLATION_PRESENT"
    evidence = _page_evidence({"PD": pd_used, "RD": rd_used})
    pd_raw = apartment_mix.show(pd) if pd else None
    rd_raw = apartment_mix.show(rd) if rd else None
    return [{
        "finding_id": f"{object_id}::{code}",
        "object_id": object_id,
        "matrix_scope": "MATRIX",
        "parameter_code": code,
        "parameter_id": cat.get("parameter_id"),
        "title": cat.get("parameter_name"),
        **({"needs_expert": True} if violation and (renamed or refs) else {}),
        "comparison_result": result or "VALUE_MISMATCH",
        "location_type": "OBJECT",
        "locations": ["Здание"],
        "pd_value": pd_raw,
        "rd_value": rd_raw,
        "id_value": None,
        "violation_label": label,
        "criticality": cat.get("criticality") if violation else None,
        "finding_status": "CANDIDATE",
        "evidence": evidence,
        "extraction": {"rule_basis": rule.get("basis"), "detail": detail, "source_fallback": fallback,
                       "pd": {"raw": pd_raw}, "rd": {"raw": rd_raw}},
    }]


def _page_evidence(sides, limit=3):
    """Страницы-доказательства обеих стадий: сначала страницы с большим числом упоминаний."""
    evidence = []
    for stage in ("PD", "RD"):
        pages = collections.Counter((c["file_id"], c["page"]) for c in sides.get(stage, []))
        for (fid, page), _n in sorted(pages.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]:
            snippet = next(c["snippet"] for c in sides[stage] if (c["file_id"], c["page"]) == (fid, page))
            evidence.append({"stage": stage, "file_id": fid, "pdf_page_number": page,
                             "quote": snippet, "localization": "PAGE_LEVEL"})
    return evidence


def _object_finding(object_id, code, cat, rule, label, result, detail, fallback, pd_raw, rd_raw, evidence,
                    location_type="OBJECT", locations=None, suffix=None, sides=None):
    violation = label == "VIOLATION_PRESENT"
    # прочитано машиной хотя бы на одной странице стороны: распознавание путает цифры (#52)
    machine = {stage: any(c.get("text_source") == "RECOGNIZED" for c in (sides or {}).get(stage) or ())
               for stage in ("PD", "RD")}
    return {
        "finding_id": f"{object_id}::{code}" + (f"::{_slug(suffix)}" if suffix else ""),
        "object_id": object_id,
        "matrix_scope": "MATRIX",
        "parameter_code": code,
        "parameter_id": cat.get("parameter_id"),
        "title": cat.get("parameter_name"),
        "comparison_result": result or "VALUE_MISMATCH",
        "location_type": location_type,
        "locations": locations if locations is not None else ["Здание"],
        "pd_value": pd_raw,
        "rd_value": rd_raw,
        "id_value": None,
        "violation_label": label,
        "criticality": cat.get("criticality") if violation else None,
        "finding_status": "CANDIDATE",
        "evidence": evidence,
        "extraction": {
            "rule_basis": rule.get("basis"),
            "detail": detail,
            "source_fallback": fallback,
            "pd": {"raw": pd_raw, **({"text_source": "RECOGNIZED"} if machine["PD"] else {})},
            "rd": {"raw": rd_raw, **({"text_source": "RECOGNIZED"} if machine["RD"] else {})},
        },
    }


def _sides(rule, cat, found):
    sides, fallback = {}, {}
    for stage, field in (("PD", "source_pd"), ("RD", "source_rd")):
        sides[stage], fallback[stage] = prefer_source(latest_only(found.get(stage, [])), rule_hints(rule, cat, field))
    return sides, fallback


def lighting_findings(object_id, code, rule, found, catalog):
    """Виды источников света обеих стадий, одна запись на здание (четвёртая очередь, ZU-130)."""
    cat = catalog.get(code, {})
    sides, fallback = _sides(rule, cat, found)
    pd = {c["value"] for c in sides["PD"]}
    rd = {c["value"] for c in sides["RD"]}
    label, result, detail = lighting.decide(pd, rd)
    if label is None:
        return []
    weak = [name for stage, name in (("PD", "проектной"), ("RD", "рабочей")) if fallback[stage]]
    if label in ("VIOLATION_PRESENT", "NO_VIOLATION") and weak:
        # светильник из чужого тома — лампа приямка дренажных насосов, переносной светильник ИТП:
        # о светильниках здания он ничего не говорит
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = f"источники света в {' и '.join(weak)} стадии найдены не в томах освещения: {detail}"
    return [_object_finding(object_id, code, cat, rule, label, result, detail, fallback,
                            lighting.show(pd), lighting.show(rd), _page_evidence(sides), sides=sides)]


def meter_findings(object_id, code, rule, found, catalog):
    """Учёт энергоресурсов: одна запись на вид ресурса (четвёртая очередь, ZU-129)."""
    cat = catalog.get(code, {})
    sides, fallback = _sides(rule, cat, found)
    with open(os.path.join(OUT, object_id, "documents.jsonl"), encoding="utf-8") as f:
        rd_sections = {d.get("section") for d in (json.loads(line) for line in f if line.strip())
                       if STAGE.get(d.get("stage")) == "RD"}
    out = []
    for name, section, _rx in metering.RESOURCES:
        own = {stage: [c for c in sides[stage] if c["key"] == name] for stage in ("PD", "RD")}
        label, result, detail = metering.decide(name, bool(own["PD"]), bool(own["RD"]), section in rd_sections)
        if label is None:
            continue
        # как названо в тексте, до трёх разных написаний: «Энергомера; счетчик активной энергии»
        raws = {stage: "; ".join(list(dict.fromkeys(c["raw"] for c in own[stage]))[:3]) or None
                for stage in ("PD", "RD")}
        out.append(_object_finding(object_id, code, cat, rule, label, result, detail, fallback,
                                   raws["PD"], raws["RD"], _page_evidence(own), sides=own,
                                   location_type="CONSTRUCTION_ELEMENT", locations=[f"учёт: {name}"], suffix=name))
    return out


# Проверки применимости: параметр неприменим к объекту, если проект так говорит (#28)
APPLICABILITY = {"demolition": demolition.applicability,
                 # снос есть, но сети выносятся до работ по отдельному проекту — POD-092 неприменим (Р-108)
                 "demolition_networks": demolition.networks_applicability}
NOT_APPLICABLE_STATUSES = ("NOT_APPLICABLE", "SEPARATE_PROJECT")


# ---------- огнезащита стали и класс отделки: решения специалиста третьего круга (#145) ----------

def as_hypothesis(finding, reason):
    """Запись — гипотеза: в сдачу только решением инспектора, как гипотеза свободного поиска (Р-91)."""
    finding.update(finding_status="SUSPICION", for_submission=False, needs_expert=True, exclusion_reason=reason)
    return finding


def _steel_side(fire, coat):
    """Значение стадии для KR-066: пределы огнезащиты по элементам и антикоррозионные системы."""
    parts = []
    limits = sorted({f"{c['element']} {c['raw']}" for c in fire if c["statement"] == "limit"})
    if limits:
        parts.append("огнезащита: " + ", ".join(limits))
    elif any(c["statement"] == "project" for c in fire):
        parts.append("огнезащита — по отдельному проекту")
    elif fire:
        parts.append("огнезащита названа без предела")
    systems = sorted({steel_protection.show_system(s["primer"], s["enamel"], s["layers"], s["microns"]) for s in coat})
    if systems:
        more = f" и ещё {len(systems) - 3}" if len(systems) > 3 else ""
        parts.append("антикоррозия: " + " | ".join(systems[:3]) + more)
    return "; ".join(parts) or None


def steel_findings(object_id, code, rule, found, catalog):
    """Огнезащита и антикоррозионная защита стальных конструкций, одна запись на здание (KR-066, #145).

    Нарушение — предел огнестойкости элемента в РД ниже того, что ПД назвала для того же элемента,
    или ослабленная антикоррозионная система (`steel_protection.weakenings`). Отсылка ПД к отдельному
    проекту огнезащиты — «сравнение невозможно» с needs_expert: инспектору запросить проект.
    Огнезащита, не упомянутая в РД, — не нарушение (Р-91, п. 5), а пояснение к записи.
    """
    cat = catalog.get(code, {})
    sides, fallback = _sides(rule, cat, found)
    if not sides["PD"] and not sides["RD"]:
        return []
    fire = {st: [c for c in sides[st] if c["key"] == "fire"] for st in ("PD", "RD")}
    coat = {st: [c["system"] for c in sides[st] if c["key"] == "coat"] for st in ("PD", "RD")}
    limits = {st: collections.defaultdict(set) for st in ("PD", "RD")}
    for st in ("PD", "RD"):
        for c in fire[st]:
            if c["statement"] == "limit":
                limits[st][c["element"]].add(c["limit"])
    decreases = steel_protection.limit_decreases(limits["PD"], limits["RD"])
    reasons = [f"{el}: R {', '.join(map(str, p))} → R {', '.join(map(str, r))}" for el, p, r in decreases]
    reasons += steel_protection.weakenings(coat["PD"], coat["RD"])
    common = set(limits["PD"]) & set(limits["RD"])
    compared = ([f"пределы огнестойкости ({len(common)} элем.)"] if common else []) + \
        (["антикоррозионная система"] if coat["PD"] and coat["RD"] else [])
    marks = {st: {m for sy in coat[st] for m in sy["primer"] + sy["enamel"] if m != "эмаль"} for st in ("PD", "RD")}
    project = any(c["statement"] == "project" for c in fire["PD"])
    expert = substituted = False
    if reasons:
        label, result = "VIOLATION_PRESENT", rule["compare"]["result"]
        detail = "ослабление защиты стальных конструкций: " + "; ".join(reasons)
    elif compared and marks["PD"] and marks["RD"] and not marks["PD"] & marks["RD"]:
        # низкая уверенность — в гипотезы (Р-104): замена системы может быть и ослаблением
        label, result, expert, substituted = "VIOLATION_PRESENT", "VALUE_MISMATCH", True, True
        detail = (f"система покрытия заменена: ПД {', '.join(sorted(marks['PD']))} → РД {', '.join(sorted(marks['RD']))}; "
                  f"слоёв и толщины меньше не стало, стойкость замены правило не оценивает — решает инспектор")
    elif compared:
        label = "NO_VIOLATION"
        same = _steel_side([], coat["PD"]) == _steel_side([], coat["RD"]) and not decreases
        result = "EQUAL_PD_RD" if same else "NON_TRIGGERING_DIFFERENCE_NO_DECREASE"
        detail = f"сверено: {', '.join(compared)}; ослабления нет"
    else:
        label, result = "COMPARISON_IMPOSSIBLE", None
        parts = []
        if not sides["PD"]:
            parts.append("защита стальных конструкций в проектной стадии не найдена")
        if project:
            expert = True
            parts.append("проектная документация отсылает огнезащиту к отдельному проекту специализированной "
                         "организации — запросите проект огнезащиты")
        if fire["PD"] and not fire["RD"]:
            parts.append("в рабочей стадии огнезащита стальных конструкций не упомянута — неуказанное не "
                         "нарушение")
        elif fire["RD"] and not limits["RD"]:
            parts.append("в рабочей стадии огнезащита названа без предела огнестойкости и марки состава")
        if coat["PD"] or coat["RD"]:
            parts.append(f"антикоррозионная система названа только в {'рабочей' if coat['RD'] else 'проектной'} стадии")
        detail = "; ".join(parts) or "сопоставить нечего"
    # доказательства — страницы с пределом, отсылкой к проекту и системой покрытия; упоминание
    # огнезащиты без предела — только если другого нет: в спецификации кровли оно шум
    strong = {st: [c for c in sides[st] if c["key"] == "coat" or c.get("statement") in ("limit", "project")]
              for st in ("PD", "RD")}
    f = _object_finding(object_id, code, cat, rule, label, result, detail, fallback,
                        _steel_side(fire["PD"], coat["PD"]), _steel_side(fire["RD"], coat["RD"]),
                        _page_evidence({st: strong[st] or sides[st] for st in ("PD", "RD")}), sides=sides)
    if expert:
        f["needs_expert"] = True
    if substituted:
        as_hypothesis(f, STEEL_SUBSTITUTION_HYPOTHESIS)
        confidence_note(f, low=["марки покрытия разные, а стойкость систем правило не сравнивает"])
    return [f]


STEEL_SUBSTITUTION_HYPOTHESIS = ("антикоррозионная система заменена целиком без ослабления по слоям и толщине: равноценна ли "
                                 "замена, решает инспектор — в сдачу только его решением")
MIN_TRIGGER_HYPOTHESIS = ("значение прочитано с чертежа, а к какому элементу оно относится — входная ли это дверь, коридор ли "
                          "на пути эвакуации — по ответу модели не видно: в сдачу только решением инспектора")
DRAWING_HYPOTHESIS = ("значение прочитано моделью с чертежа, а к какому элементу оно относится, по ответу не видно: в сдачу "
                      "только решением инспектора")
# То же правило, но значения взяты из текста листа, а не из ответа модели: причина та же — к какому элементу
# относится число, подпись не всегда говорит, — но «прочитано моделью» было бы неправдой (#229)
DRAWING_TEXT_HYPOTHESIS = ("значение взято из подписи на листе, а к какому элементу оно относится, по подписи не всегда "
                           "видно: в сдачу только решением инспектора")


def confidence_note(finding, up=(), medium=(), low=()):
    """Доводы уверенности, которые знает только правило (#80, Р-104): их читает `confidence.ts` API.

    `up` — на что вывод опирается, `medium` — что стоит проверить глазами, `low` — почему выводу
    мало оснований. Уровень записи считает API; гипотеза с доводами «против» идёт в список гипотез
    с низкой или средней уверенностью, а не пропадает в «сравнение невозможно».
    """
    note = finding["extraction"].setdefault("confidence", {"up": [], "medium": [], "low": []})
    for key, items in (("up", up), ("medium", medium), ("low", low)):
        note[key].extend(x for x in items if x not in note[key])
    return finding


def threshold_confidence(finding):
    """Значение против триггера и проектного порога (min_trigger, max_trigger): гипотеза с уровнем уверенности.

    Модель отвечает всеми элементами листа: у ДОО в ответе про двери была дверь техпомещения.
    Поэтому нарушение — гипотеза; порог-триггер — довод «за», один проектный порог — довод
    «против». «Нарушения нет» остаётся записью: все значения листа в пределах порогов.
    """
    detail = finding["extraction"].get("detail") or ""
    if finding["violation_label"] == "VIOLATION_PRESENT":
        as_hypothesis(finding, MIN_TRIGGER_HYPOTHESIS)
        # «не меньше (больше) триггера, но …» — порог только из ПД (`decide`, min_trigger / max_trigger)
        if "но меньше требования ПД" in detail or "но больше проектного" in detail:
            confidence_note(finding, medium=["за порогом только проектной документации, не триггера Матрицы"])
        else:
            confidence_note(finding, up=["порог — триггер Матрицы"])
    confidence_note(finding, medium=["значение прочитано с чертежа: к какому элементу оно относится, по ответу модели не видно"])
    return finding


def rule_hypothesis(finding, rule, cands):
    """Нарушение, которое специалист признал только гипотезой (Р-112): у правила `hypotheses: always` — всегда,
    у правила с `hypothesis_when` — когда рядом со значением есть его довод «против». ODI-118: порог выше 14 мм —
    нарушение, если в документации нет явного обоснования (путь не для МГН, переносной пандус)."""
    if finding["violation_label"] != "VIOLATION_PRESENT" or finding.get("finding_status") == "SUSPICION":
        return finding
    if rule.get("hypotheses") == "always":
        return as_hypothesis(finding, rule.get("hypothesis_reason") or RULE_HYPOTHESIS)
    when = rule.get("hypothesis_when")
    if when:
        text = " ".join(c.get("snippet") or "" for c in cands)
        hit = next((m for m in (re.search(p, text, re.I) for p in when["patterns"]) if m), None)
        if hit:
            as_hypothesis(finding, when["reason"])
            confidence_note(finding, low=[f"рядом со значением: «{hit.group(0)}»"])
    return finding


def drawing_hypothesis(finding, rule, criticality=None, cands=None):
    """Правило со значениями с чертежа (`hypotheses: drawing`, Р-104, Р-105): нарушение — гипотеза.

    Неоднозначное сравнение набором («в рабочей стадии есть значение меньше наименьшего проектного,
    но участков несколько») при невысокой уверенности тоже идёт в гипотезы, а не в «сравнение
    невозможно»: пусть инспектор посмотрит, уровень скажет, насколько это вероятно.

    `cands` — кандидаты сравнения: если ни одно значение не дала модель, причина называется
    подписью на листе, а не ответом модели (#229). Без кандидатов — прежняя причина.
    """
    by_model = cands is None or any(c.get("from_model") for c in cands)
    label = finding["violation_label"]
    detail = finding["extraction"].get("detail") or ""
    if label == "COMPARISON_IMPOSSIBLE" and "по чертежу не определить" in detail:
        finding["violation_label"] = "VIOLATION_PRESENT"
        finding["comparison_result"] = (rule.get("compare") or {}).get("result_violation") or "VALUE_DECREASE"
        finding["criticality"] = criticality
        confidence_note(finding, low=["значение меньше наименьшего проектного, но к какому элементу оно относится, "
                                      "по чертежу не определить"])
        label = "VIOLATION_PRESENT"
    if label == "VIOLATION_PRESENT":
        as_hypothesis(finding, DRAWING_HYPOTHESIS if by_model else DRAWING_TEXT_HYPOTHESIS)
        confidence_note(finding, medium=["значение прочитано моделью с чертежа" if by_model
                                         else "значение взято из подписи на листе"])
    return finding
FINISH_HYPOTHESIS = ("класс отделки назван общими указаниями или у марки ведомости без привязки к помещению — "
                     "для нарушения этого мало: в сдачу только решением инспектора")


def finish_findings(object_id, code, rule, found, catalog):
    """Класс пожарной опасности отделки на путях эвакуации, одна запись на здание (PPM-107, #145).

    ПД даёт требование по виду пути и поверхности, РД — класс общими указаниями или у марки
    ведомости. Специалист (Р-91, п. 6): привязка марки к помещению только через план потолков —
    needs_expert, марка в коридорах и техпомещениях — «требует уточнения», общих указаний для
    «нарушения нет» мало. Поэтому класс хуже проектного — гипотеза, а не нарушение. Кроме общих
    коридоров и холлов (R4-H11, Р-116): класс хуже их требования — нарушение, у марки без помещения —
    с needs_expert, где она стоит, сверяет инспектор по плану потолков.
    """
    cat = catalog.get(code, {})
    sides, fallback = _sides(rule, cat, found)
    reqs = [c for c in sides["PD"] if c.get("form") in ("table", "clause")]
    rd = [c for c in sides["RD"] if c.get("form") in ("general", "mark")]
    if not reqs and not rd:
        return []
    need = finish_classes.strictest(reqs)
    worse, between = finish_classes.worse(rd, need)
    pd_raw = "; ".join(f"{g}, {s}: КМ{v}" for (g, s), v in sorted(need.items())) or None
    by_class = collections.defaultdict(set)
    for c in rd:
        by_class[c["value"]].add(c["mark"] or c["room"])
    rd_raw = "; ".join(f"{', '.join(sorted(names, key=_mark_key))}: КМ{v}" for v, names in sorted(by_class.items())) or None
    evidence_sides = {"PD": reqs, "RD": rd}
    status, hypothesis = None, False
    if not reqs:
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = "требование к классу отделки путей эвакуации в проектной стадии не найдено"
    elif not rd:
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = "класс пожарной опасности отделки в рабочей стадии не найден"
    elif worse:
        # хуже требования к общим коридорам и холлам — нарушение (R4-H11), к другим путям — гипотеза
        corridors = [x for x in worse if x[2] == finish_classes.CORRIDORS]
        label, result, hypothesis = "VIOLATION_PRESENT", rule["compare"]["result"], not corridors
        if corridors and any(c["form"] == "mark" for c, _r, _g in corridors):
            status = "CANDIDATE"          # марку к помещениям привязывает план потолков: сверяет инспектор
        groups = collections.defaultdict(set)
        for c, required, group in worse:
            groups[(c["value"], required, group)].add(c["mark"] or c["room"])
        shown = "; ".join(f"{', '.join(sorted(n, key=_mark_key))} — КМ{v} при требовании ПД КМ{req} ({g}, стены и потолки)"
                          for (v, req, g), n in sorted(groups.items()))
        detail = f"класс отделки в рабочей стадии хуже проектного: {shown}"
        if any(c["form"] == "mark" for c, _r, _g in worse):
            detail += "; к помещениям марки привязывает только план потолков — где они стоят, сверьте по нему"
        evidence_sides["RD"] = [c for c, _r, _g in worse]
    elif between:
        # было «требует уточнения» (Р-91, п. 6); при низкой уверенности — гипотеза (Р-104)
        label, result, hypothesis = "VIOLATION_PRESENT", rule["compare"]["result"], True
        names = ", ".join(sorted({c["mark"] for c in between}, key=_mark_key))
        detail = (f"требует уточнения: марки {names} годятся для одних путей эвакуации и хуже требования для других "
                  f"({pd_raw}); где стоит марка, видно только на плане потолков")
        evidence_sides["RD"] = between
    else:
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = ("классы рабочей стадии не хуже проектных, но названы общими указаниями или у марок без привязки "
                  "к помещениям — для «нарушения нет» этого мало")
    f = _object_finding(object_id, code, cat, rule, label, result, detail, fallback, pd_raw, rd_raw,
                        _page_evidence(evidence_sides), sides=sides)
    if hypothesis:
        as_hypothesis(f, FINISH_HYPOTHESIS)
        flagged = [c for c, _r, _g in worse] or between
        if any(c["value"] >= 3 for c, _r, _g in worse):
            confidence_note(f, up=["триггер Матрицы: класс КМ3 и хуже на путях эвакуации"])
        if any(c["form"] == "mark" for c in flagged):
            confidence_note(f, low=["марка отделки привязана к помещению только планом потолков"])
        if any(c["form"] == "general" for c in flagged):
            confidence_note(f, medium=["класс назван общими указаниями, без ведомости по помещениям"])
        if between and not worse:
            confidence_note(f, low=["марка годится для одних путей эвакуации и хуже требования для других"])
    elif status:
        f["finding_status"] = status
        f["needs_expert"] = True
        confidence_note(f, low=["марка отделки привязана к помещению только планом потолков"])
    return [f]


# вид правила → (разбор страницы, сравнение стадий, совпадение без ППР — «нарушения нет»?)
SITE_PARSERS = {"crane_zones": ("cranes", "crane_changes", False),
                "pit_edge_limits": ("edge_limits", "edge_changes", True),
                "collapse_zone": ("collapse_zones", "collapse_changes", False),
                "demolition_methods": ("demolition_methods", "method_changes", False),
                "build_technology": ("technologies", "technology_changes", True)}
SITE_HYPOTHESIS = ("рабочая сторона — стройгенплан или раздел КР в составе РД, а не ППР: такое сравнение даёт "
                   "только гипотезу — в сдачу только решением инспектора")


def site_findings(object_id, code, rule, found, catalog):
    """Стройплощадка: краны и опасные зоны (POS-081), ограничения у бровки котлована (POS-085), #145.

    ППР в корпусе нет, рабочая сторона — стройгенплан или КР в составе РД. Расхождение —
    гипотеза. Совпадение у кранов — «сравнение невозможно» с пояснением: стройгенплан специалист
    допустил только «для гипотезы». Совпадение у бровки — «нарушения нет»: одно и то же
    ограничение в двух разделах, раздел в раздел (POS-085).
    """
    cat = catalog.get(code, {})
    sides, fallback = _sides(rule, cat, found)
    if not sides["PD"] and not sides["RD"]:
        return []
    keyed, raws = {}, collections.defaultdict(dict)
    for st in ("PD", "RD"):
        keyed[st] = collections.defaultdict(set)
        for c in sides[st]:
            keyed[st][c["key"]].add(c["value"])
            raws[c["key"]].setdefault(c["value"], c["raw"])
    shown = lambda key, values: ", ".join(sorted(raws[key][v] for v in values)) \
        if key == site_works.CRANE_KEY else site_works.show(key, values)  # noqa: E731
    side_value = lambda k: "; ".join(f"{key}: {shown(key, vals)}" for key, vals in sorted(k.items())) or None  # noqa: E731
    _parse, compare, same_is_ok = SITE_PARSERS[rule["kind"]]
    changes = getattr(site_works, compare)(keyed["PD"], keyed["RD"])
    common = set(keyed["PD"]) & set(keyed["RD"])
    hypothesis = False
    if changes:
        label, result, hypothesis = "VIOLATION_PRESENT", rule["compare"]["result"], True
        detail = "; ".join(f"{k}: {shown(k, p)} → {shown(k, r)} ({why})" for k, p, r, why in changes)
    elif not sides["PD"] or not sides["RD"]:
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = f"в {'проектной' if not sides['PD'] else 'рабочей'} стадии значений не найдено"
        if not sides["RD"]:
            detail += " (ППР в пакете нет)"
    elif not common:
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = "стадии называют разное: " + ", ".join(sorted(set(keyed["PD"]) | set(keyed["RD"])))
    elif not same_is_ok:
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = (f"совпадает: {', '.join(sorted(common))}; рабочая сторона — стройгенплан, а не ППР, по нему "
                  f"возможна только гипотеза")
    else:
        same = all(keyed["PD"][k] == keyed["RD"][k] for k in common)
        label, result = "NO_VIOLATION", "EQUAL_PD_RD" if same else "NON_TRIGGERING_DIFFERENCE_NO_DECREASE"
        what = "ограничения те же" if rule["kind"] == "pit_edge_limits" else "технологии рабочей стадии есть и в проекте"
        detail = f"{what}: {', '.join(sorted(common))}"
    f = _object_finding(object_id, code, cat, rule, label, result, detail, fallback,
                        side_value(keyed["PD"]), side_value(keyed["RD"]), _page_evidence(sides),
                        location_type="SITE", locations=["Строительная площадка"], sides=sides)
    if hypothesis:
        as_hypothesis(f, SITE_HYPOTHESIS)
    return [f]


DURATION_HYPOTHESIS = "ПОС и ООС называют разный срок строительства — гипотеза: в сдачу только решением инспектора"
DURATION_PARTS = (("ПОС", "PD"), ("ООС", "PD"), ("ППР", "RD"))


def _duration_evidence(used, limit=2):
    """Страницы-доказательства по разделам: страницы со сроком, на котором стоит решение, — сначала
    названные сильной фразой. Одинаковые цитаты (копии тома под разными именами) — один раз."""
    evidence = []
    for part, stage in DURATION_PARTS:
        cands = used.get(part) or []
        pages = collections.Counter((c["file_id"], c["page"]) for c in cands)
        strong = {(c["file_id"], c["page"]) for c in cands if c.get("strong")}
        quotes = set()
        for (fid, page), _n in sorted(pages.items(), key=lambda kv: (kv[0] not in strong, -kv[1], kv[0])):
            quote = next(c["snippet"] for c in cands if (c["file_id"], c["page"]) == (fid, page))
            if quote in quotes:
                continue
            quotes.add(quote)
            evidence.append({"stage": stage, "file_id": fid, "pdf_page_number": page, "quote": quote,
                             "localization": "PAGE_LEVEL"})
            if len(quotes) == limit:
                break
    return evidence


def duration_findings(object_id, code, rule, found, catalog):
    """Срок строительства: ПОС против ООС и ППР, одна запись на объект (POS-082, #187).

    ППР в пакете нет — сравнивается срок внутри проектной документации: ООС, который ни разу не
    называет срок ПОС (общий или подготовительного периода), — гипотеза. ППР есть — его срок против
    ПОС с порогом правила. ПОС и ООС сходятся, а ППР нет — «сравнение невозможно» с названным сроком:
    сам параметр, график ППР, не проверен.

    Доказательства и пометка «прочитано распознаванием» — по значениям, на которых стоит решение:
    у Октябрьской ООС называет и 27 мес. объекта, и 3,6 мес. сетей, а решение — по 27.

    Конфликт редакций здесь решения не меняет: у Алтуфьевского три выпуска ПОС в одной цепочке с
    неизвестным порядком (12 и 13 мес.), и ООС (10,5 мес.) не называет ни одного из их сроков.
    Поэтому ключ кандидата — его «место» (`extract`), и `clarify_revisions` записи не трогает.
    """
    cat = catalog.get(code, {})
    cands = latest_only(found.get("PD", [])) + latest_only(found.get("RD", []))
    parts = {part: [c for c in cands if c.get("part") == part] for part, _stage in DURATION_PARTS}
    if not any(parts.values()):
        return []
    got = {part: durations.pick(cs) for part, cs in parts.items()}
    pos, oos, ppr = got["ПОС"], got["ООС"], got["ППР"]
    total, prep = durations.TOTAL_KEY, durations.PREP_KEY
    changed = durations.changes(pos, oos)
    over = durations.ppr_excess(pos, ppr, (rule.get("compare") or {}).get("threshold", durations.PPR_THRESHOLD))
    raws = collections.defaultdict(lambda: collections.defaultdict(list))
    for c in cands:
        raws[c.get("key")][c["value"]].append(c["raw"])

    def show(values, key=total):
        return durations.show(values, raws[key])

    decisive = collections.defaultdict(lambda: collections.defaultdict(set))
    if changed or over:
        label, result = "VIOLATION_PRESENT", (rule.get("compare") or {}).get("result") or "VALUE_MISMATCH"
        said = [f"{key}: ПОС — {show(p, key)}, ООС — {show(o, key)}" for key, p, o in changed]
        for key, p, o in changed:
            decisive["ПОС"][key] |= set(p)
            decisive["ООС"][key] |= set(o)
        if changed:
            said[-1] += "; в ООС значения ПОС нет"
        if over:
            base, value, share = over
            said.append(f"срок строительства в ППР — {show([value])}, в ПОС — {show([base])}: больше на "
                        f"{share * 100:.0f} %")
            decisive["ПОС"][total].add(base)
            decisive["ППР"][total].add(value)
        detail = "; ".join(said)
    elif ppr.get(total) and pos.get(total):
        label = "NO_VIOLATION"
        result = "EQUAL_PD_RD" if any(durations.same(a, b) for a in pos[total] for b in ppr[total]) \
            else "NON_TRIGGERING_DIFFERENCE_NO_DECREASE"
        detail = f"срок строительства в ППР — {show(ppr[total])}, в ПОС — {show(pos[total])}: в пределах порога"
        decisive["ПОС"][total] |= set(pos[total])
        decisive["ППР"][total] |= set(ppr[total])
    else:
        label, result = "COMPARISON_IMPOSSIBLE", None
        if pos.get(total) and oos.get(total):
            shared = {a for a in pos[total] for b in oos[total] if durations.same(a, b)}
            said = f"ПОС и ООС называют один срок строительства — {show(shared)}"
            decisive["ПОС"][total] |= shared
            decisive["ООС"][total] |= {b for b in oos[total] if any(durations.same(a, b) for a in shared)}
        elif pos.get(total):
            said = f"срок строительства по ПОС — {show(pos[total])}, в ООС срок не найден"
        elif oos.get(total):
            said = f"срок строительства назван только в ООС — {show(oos[total])}"
        else:
            said = "назван только подготовительный период"
        detail = f"проекта производства работ в пакете нет; {said}"
    # на чём стоит решение; если решает сам факт, что срок назван, — все названные значения
    everything = not decisive
    used = {part: [c for key, values in got[part].items() for value, cs in values.items() for c in cs
                   if everything or value in decisive[part][key]]
            for part, _stage in DURATION_PARTS}
    side = {part: durations.side_text(got[part]) for part, _stage in DURATION_PARTS}
    pd_raw = "; ".join(f"{part}: {side[part]}" for part in ("ПОС", "ООС") if side[part]) or None
    rd_raw = f"ППР: {side['ППР']}" if side["ППР"] else None
    f = _object_finding(object_id, code, cat, rule, label, result, detail, {"PD": False, "RD": False}, pd_raw, rd_raw,
                        _duration_evidence(used), location_type="SITE", locations=["Строительная площадка"],
                        sides={"PD": used["ПОС"] + used["ООС"], "RD": used["ППР"]})
    if changed:
        as_hypothesis(f, DURATION_HYPOTHESIS)
        confidence_note(f, up=["срок назван и в ПОС, и в ООС, общего значения у разделов нет"])
        if all(key == prep for key, _p, _o in changed):
            confidence_note(f, medium=["общий срок в ПОС и ООС один, расходится только подготовительный период"])
        if len(pos.get(total) or ()) > 1:
            confidence_note(f, medium=[f"ПОС в пакете называет несколько сроков: {show(pos[total])}"])
    return [f]


def joint_findings(object_id, code, rule, found, catalog):
    """Деформационные швы здания: наличие, ширина и материал заполнения, одна запись на объект (KR-063, #192).

    Шов в обеих стадиях: уже в РД или другой материал заполнения — нарушение (в черновике гипотеза),
    иначе «нарушения нет». Шов только в ПД: если в РД есть схемы плиты или вертикальных конструкций,
    а шва на них нет, — нарушение (решение специалиста: этих схем достаточно); схем нет — «сравнение
    невозможно».
    """
    cat = catalog.get(code, {})
    sides = {st: latest_only(found.get(st, [])) for st in ("PD", "RD")}
    seam = {st: [c for c in cs if c.get("form") == "joint"] for st, cs in sides.items()}
    plans = {st: [c for c in cs if c.get("form") == "scheme"] for st, cs in sides.items()}
    widths = {st: {c["value"] for c in cs if c.get("value") is not None} for st, cs in seam.items()}
    mats = {st: {m for c in cs for m in c.get("materials") or ()} for st, cs in seam.items()}
    if not seam["PD"] and not seam["RD"]:
        return []
    show = joints.show_widths
    used = {st: list(cs) for st, cs in seam.items()}
    if seam["PD"] and seam["RD"]:
        said = []
        if widths["PD"] and widths["RD"] and min(widths["RD"]) < min(widths["PD"]):
            said.append(f"ширина шва в РД {show(widths['RD'])} меньше проектной {show(widths['PD'])}")
        if mats["PD"] and mats["RD"] and not mats["PD"] & mats["RD"]:
            said.append(f"материал заполнения в РД — {', '.join(sorted(mats['RD']))}, "
                        f"в ПД — {', '.join(sorted(mats['PD']))}")
        if said:
            label, result, detail = "VIOLATION_PRESENT", "CONFIGURATION_MISMATCH", "; ".join(said)
        else:
            label = "NO_VIOLATION"
            result = "EQUAL_PD_RD" if widths["PD"] == widths["RD"] else "NON_TRIGGERING_DIFFERENCE_NO_DECREASE"
            detail = "деформационный шов есть в обеих стадиях"
            if widths["PD"] and widths["RD"]:
                detail += f": ширина в ПД {show(widths['PD'])}, в РД {show(widths['RD'])}"
            elif widths["PD"]:
                detail += f"; ширина в ПД {show(widths['PD'])}, в РД не подписана"
    elif seam["PD"]:
        if plans["RD"]:
            label, result = "VIOLATION_PRESENT", "MISSING_DESIGN_ELEMENT"
            detail = (f"шов назван в ПД{' (' + show(widths['PD']) + ')' if widths['PD'] else ''}, а на схемах плиты и "
                      f"вертикальных конструкций РД ({len({(c['file_id'], c['page']) for c in plans['RD']})} стр.) "
                      f"его нет")
            used["RD"] = plans["RD"]
        else:
            label, result = "COMPARISON_IMPOSSIBLE", None
            detail = "шов назван в ПД, а схем плиты и вертикальных конструкций РД в пакете нет"
    else:
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = "шов назван только в РД, в ПД его нет"

    def side(st):
        if not seam[st]:
            return None
        parts = [f"ширина {show(widths[st])}" if widths[st] else "шов назван"]
        if mats[st]:
            parts.append("заполнение: " + ", ".join(sorted(mats[st])))
        return "; ".join(parts)

    f = _object_finding(object_id, code, cat, rule, label, result, detail, {"PD": False, "RD": False}, side("PD"),
                        side("RD"), _page_evidence(used, limit=2), location_type="CONSTRUCTION_ELEMENT",
                        locations=["Деформационные швы"], sides=used)
    if result == "MISSING_DESIGN_ELEMENT":
        confidence_note(f, medium=["шов искали по тексту схем РД: подпись шва на листе могла быть нарисована, а не "
                                   "написана"])
    elif label == "VIOLATION_PRESENT":
        confidence_note(f, up=["шов назван в обеих стадиях"])
    return [f]


def window_findings(object_id, code, rule, found, catalog):
    """Окна: число и площадь проёмов по ведомостям стадий, одна запись на здание (AR-046, #193).

    Ведомости в обеих стадиях и строки разобраны: меньше окон или меньше площадь проёмов в РД — нарушение
    (решение специалиста: любое уменьшение), у марки проём меньше — тоже; иначе «нарушения нет».
    Ведомости в ПД нет — «сравнение невозможно» (решение специалиста: можно не сравнивать).
    """
    cat = catalog.get(code, {})
    sides = {st: latest_only(found.get(st, [])) for st in ("PD", "RD")}
    lists = {st: [c for c in cs if c.get("form") == "schedule"] for st, cs in sides.items()}
    items = {st: [{"mark": c["key"], "w": c["w"], "h": c["h"], "n": c["value"]} for c in cs if c.get("form") == "row"]
             for st, cs in sides.items()}
    if not lists["PD"] and not lists["RD"]:
        return []
    got = {st: windows.totals(items[st]) for st in ("PD", "RD")}
    used = {st: [c for c in sides[st] if c.get("form") == "row"] or lists[st] for st in ("PD", "RD")}

    def side(st):
        if not lists[st]:
            return None
        count, area, _best = got[st]
        return f"окон {count}, площадь проёмов {area:g} м²".replace(".", ",") if count else "ведомость окон есть"

    if not lists["PD"]:
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = "в ПД ведомости окон нет — число и площадь окон не сравниваются"
    elif not lists["RD"]:
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = "в РД ведомости окон нет"
    elif not items["PD"] or not items["RD"]:
        label, result = "COMPARISON_IMPOSSIBLE", None
        where = " и ".join(n for st, n in (("PD", "ПД"), ("RD", "РД")) if not items[st])
        detail = f"ведомость окон есть в обеих стадиях, но строки в {where} не разобраны"
    else:
        (pn, pa, pb), (rn, ra, rb) = got["PD"], got["RD"]
        said = []
        if rn < pn:
            said.append(f"окон в РД {rn} против {pn} в ПД")
        if ra < pa:
            said.append(f"площадь проёмов в РД {ra:g} м² против {pa:g} м² в ПД".replace(".", ","))
        said += [f"{m}: проём в РД {r} против {p} в ПД" for m, p, r in windows.smaller_marks(pb, rb)]
        if said:
            label, result, detail = "VIOLATION_PRESENT", "VALUE_DECREASE", "; ".join(said)
        else:
            label = "NO_VIOLATION"
            result = "EQUAL_PD_RD" if (pn, pa) == (rn, ra) else "NON_TRIGGERING_DIFFERENCE_NO_DECREASE"
            detail = f"окон в РД {rn}, в ПД {pn}; площадь проёмов не меньше проектной"
    f = _object_finding(object_id, code, cat, rule, label, result, detail, {"PD": False, "RD": False}, side("PD"),
                        side("RD"), _page_evidence(used, limit=2), sides=used)
    return [f]


DOOR_HYPOTHESIS = "направление открывания прочитано моделью по плану — гипотеза: в сдачу только решением инспектора"


def door_findings(object_id, code, rule, found, catalog):
    """Направление открывания дверей на путях эвакуации, одна запись на объект (AR-043, #191).

    Решения специалиста (R3-AR-043): для гипотезы — все двери, для нарушения — только явно обозначенные
    как эвакуационные на плане или в записке; без дуг открывания хватает текста. Дверь РД «против хода
    эвакуации» — гипотеза: у той же двери в ПД «по ходу», или проект требует открывания по направлению
    выхода текстом, или направления в ПД нет. Та же дверь «против хода» и в ПД — не изменение стадий.
    """
    cat = catalog.get(code, {})
    sides = {st: latest_only(found.get(st, [])) for st in ("PD", "RD")}
    doors = {st: [c for c in cs if c.get("form") == "door"] for st, cs in sides.items()}
    need = [c for c in sides["PD"] if c.get("form") == "requirement"]
    pd_by = collections.defaultdict(set)
    for c in doors["PD"]:
        pd_by[c["key"]].add(c["value"])
    against = collections.OrderedDict()
    for c in doors["RD"]:
        if c["value"] == "против хода" and "против хода" not in pd_by.get(c["key"], ()):
            against.setdefault(c["key"], c)
    seen_rd = [c for c in doors["RD"] if c["value"] != "не видно"]
    if not against and not seen_rd and not doors["PD"] and not need:
        return []
    said, used = [], {"PD": list(need[:1]), "RD": []}
    if against:
        label, result = "VIOLATION_PRESENT", "CONFIGURATION_MISMATCH"
        for key, c in against.items():
            name = c.get("mark") or c.get("room") or key
            if "по ходу" in pd_by.get(key, ()):
                why = "в ПД по ходу"
                used["PD"] += [p for p in doors["PD"] if p["key"] == key][:1]
            elif need:
                why = "проект требует открывания по направлению выхода"
            else:
                why = "в ПД направление не найдено"
            said.append(f"дверь {name}: в РД против хода эвакуации, {why}")
            used["RD"].append(c)
        detail = "; ".join(said[:8]) + (f"; и ещё {len(said) - 8}" if len(said) > 8 else "")
        locations = [c.get("mark") or c.get("room") or k for k, c in list(against.items())[:5]]
    elif seen_rd and (need or doors["PD"]):
        label = "NO_VIOLATION"
        result = "EQUAL_PD_RD"
        names = lambda cs: ", ".join(sorted({c.get("mark") or c.get("room") or c["key"] for c in cs})[:10])  # noqa: E731
        forward = [c for c in seen_rd if c["value"] == "по ходу"]
        kept = [c for c in seen_rd if c["value"] == "против хода"]
        detail = "; ".join(x for x in ((f"двери РД на путях эвакуации открываются по ходу эвакуации: {names(forward)}"
                                        if forward else ""),
                                       (f"против хода, как и в ПД: {names(kept)}" if kept else "")) if x)
        used["RD"] = seen_rd[:2]
        locations = ["Двери эвакуационных выходов"]
    else:
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = ("направление открывания в РД не прочитано" if not seen_rd
                  else "направление открывания в ПД не найдено ни на планах, ни текстом")
        used = {"PD": need[:1] + doors["PD"][:1], "RD": seen_rd[:2]}
        locations = ["Двери эвакуационных выходов"]

    def side(st):
        parts = []
        if st == "PD" and need:
            parts.append("требование: открывание по направлению выхода")
        shown = sorted({f"{c.get('mark') or c.get('room') or c['key']} — {c['value']}" for c in doors[st]
                        if c["value"] != "не видно"})
        if shown:
            parts.append(", ".join(shown[:6]) + (f" и ещё {len(shown) - 6}" if len(shown) > 6 else ""))
        return "; ".join(parts) or None

    f = _object_finding(object_id, code, cat, rule, label, result, detail, {"PD": False, "RD": False}, side("PD"),
                        side("RD"), _page_evidence(used, limit=2), location_type="CONSTRUCTION_ELEMENT",
                        locations=locations, sides=used)
    if label == "VIOLATION_PRESENT":
        as_hypothesis(f, DOOR_HYPOTHESIS)
        confidence_note(f, low=["направление открывания прочитано моделью по условному знаку на плане"])
        if any(c.get("exit") for c in against.values()):
            confidence_note(f, up=["дверь обозначена на плане как эвакуационный выход"])
        else:
            confidence_note(f, medium=["дверь не обозначена как эвакуационный выход: нарушением её назвать нельзя, "
                                       "только гипотезой"])
    return [f]


def alarm_findings(object_id, code, rule, found, catalog):
    """Состав и ёмкость АПС, одна запись на здание (IOS5-080, #190).

    Ёмкость — число адресных устройств по спецификациям томов АПС ПД и РД (решение специалиста): меньше
    проектного сверх допуска — нарушение (черновик: гипотеза), иначе «нарушения нет». Метки ЗКПС со
    структурной схемы и планов в решение не входят — объединение зон при том же числе извещателей не
    нарушение; они идут в пояснение: те же зоны или какие зоны проекта в РД без пары.
    """
    cat = catalog.get(code, {})
    tolerance = (rule.get("compare") or {}).get("tolerance_pct", detectors.TOLERANCE_PCT)
    sides = {st: latest_only(found.get(st, [])) for st in ("PD", "RD")}
    fire = {c["file_id"] for cs in sides.values() for c in cs if c.get("form") == "detector"}
    dev = {st: [c for c in cs if c.get("form") == "device" and c["file_id"] in fire] for st, cs in sides.items()}
    zon = {st: sorted({c["value"] for c in cs if c.get("form") == "zone"}) for st, cs in sides.items()}
    chain = {c["file_id"]: (c.get("chain") or {}).get("chain") or c["file_id"] for cs in dev.values() for c in cs}
    cap = {st: detectors.totals(cs, chain.get).get(detectors.DEVICE_KEY) for st, cs in dev.items()}
    if not cap["PD"] and not cap["RD"] and not zon["PD"] and not zon["RD"]:
        return []
    if cap["PD"] and cap["RD"]:
        pct = round((cap["PD"] - cap["RD"]) / cap["PD"] * 100)
        if pct > tolerance:
            label, result = "VIOLATION_PRESENT", "COUNT_MISMATCH"
            detail = (f"адресных устройств в РД {cap['RD']} против {cap['PD']} в ПД — меньше на {pct} %, "
                      f"допуск {tolerance} %")
        else:
            label = "NO_VIOLATION"
            result = "EQUAL_PD_RD" if cap["PD"] == cap["RD"] else "NON_TRIGGERING_DIFFERENCE_NO_DECREASE"
            detail = f"адресных устройств в РД {cap['RD']}, в ПД {cap['PD']}: не меньше проектного сверх допуска {tolerance} %"
    else:
        label, result = "COMPARISON_IMPOSSIBLE", None
        if cap["PD"] or cap["RD"]:
            detail = f"число адресных устройств в {'рабочей' if cap['PD'] else 'проектной'} стадии не названо"
        else:
            detail = "спецификаций с адресными устройствами нет ни в одной стадии"
    if zon["PD"] and zon["RD"]:
        gone, came = sorted(set(zon["PD"]) - set(zon["RD"])), sorted(set(zon["RD"]) - set(zon["PD"]))
        if not gone and not came:
            detail += f"; ЗКПС в ПД и РД одни и те же — {len(zon['PD'])}"
        if gone:
            detail += (f"; ЗКПС проекта без пары в РД: {', '.join(gone[:12])}" + (" и др." if len(gone) > 12 else "")
                       + " — объединение зон при том же числе устройств не нарушение")
        if came:
            detail += f"; в РД добавлены ЗКПС: {', '.join(came[:12])}" + (" и др." if len(came) > 12 else "")
    side = lambda st: "; ".join(x for x in ((f"адресных устройств {cap[st]}" if cap[st] else None),  # noqa: E731
                                            (f"ЗКПС {len(zon[st])}" if zon[st] else None)) if x) or None
    evidence = _page_evidence({st: dev[st] or [c for c in sides[st] if c.get("form") == "zone"] for st in sides}, limit=2)
    f = _object_finding(object_id, code, cat, rule, label, result, detail, {"PD": False, "RD": False}, side("PD"),
                        side("RD"), evidence, sides=dev)
    if label == "VIOLATION_PRESENT":
        confidence_note(f, medium=["адресные устройства посчитаны по строкам спецификации: проверьте, все ли тома "
                                   "АПС в пакете"])
    return [f]


def detector_findings(object_id, code, rule, found, catalog):
    """Число пожарных извещателей по видам: спецификация ПД против РД, одна запись на здание (PPM-108, #189).

    Уменьшение вида больше допуска правила или вид проекта, которого нет в РД, — нарушение (черновик:
    гипотеза). В допуске или больше — «нарушения нет». Спецификация с количеством только в одной
    стадии — «сравнение невозможно». Копии тома одной цепочки редакций не складываются
    (`detectors.totals`).
    """
    cat = catalog.get(code, {})
    tolerance = (rule.get("compare") or {}).get("tolerance_pct", detectors.TOLERANCE_PCT)
    sides = {st: latest_only(found.get(st, [])) for st in ("PD", "RD")}
    chain = {c["file_id"]: (c.get("chain") or {}).get("chain") or c["file_id"] for cs in sides.values() for c in cs}
    tot = {st: detectors.totals(cs, chain.get) for st, cs in sides.items()}
    if not tot["PD"] and not tot["RD"]:
        return []
    if tot["PD"] and tot["RD"]:
        fewer, missing, ok = detectors.compare(tot["PD"], tot["RD"], tolerance)
        if fewer or missing:
            label, result = "VIOLATION_PRESENT", "COUNT_MISMATCH"
            said = [f"{kind}: в РД {r} против {p} в ПД — меньше на {pct} %, допуск {tolerance} %"
                    for kind, p, r, pct in fewer]
            said += [f"{kind}: в ПД {tot['PD'][kind]} шт., в РД извещателей этого вида нет" for kind in missing]
            detail = "; ".join(said)
        else:
            label = "NO_VIOLATION"
            result = "EQUAL_PD_RD" if all(p == r for _k, p, r, _pct in ok) else "NON_TRIGGERING_DIFFERENCE_NO_DECREASE"
            detail = (f"число извещателей по видам в РД не меньше проектного сверх допуска {tolerance} %: "
                      + "; ".join(f"{kind} {r} против {p}" for kind, p, r, _pct in ok))
    else:
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = (f"спецификации пожарных извещателей с количеством в "
                  f"{'рабочей' if tot['PD'] else 'проектной'} стадии нет")
    f = _object_finding(object_id, code, cat, rule, label, result, detail, {"PD": False, "RD": False},
                        detectors.show(tot["PD"]), detectors.show(tot["RD"]), _page_evidence(sides, limit=2),
                        sides=sides)
    auto = {st: any(c.get("autonomous") for c in cs) for st, cs in sides.items()}
    if label == "VIOLATION_PRESENT" and auto["PD"] != auto["RD"]:
        where = "проекта" if auto["PD"] else "рабочей стадии"
        confidence_note(f, medium=[f"автономные извещатели названы только в спецификации {where}: их может "
                                   f"учитывать другой том"])
    if label == "VIOLATION_PRESENT":
        confidence_note(f, medium=["расстановка по планам текстом не проверена: число могло измениться с "
                                   "уточнением планировок"])
    return [f]


INSULATION_HYPOTHESIS = ("утеплитель стен в РД другого производителя, λ нового утеплителя в документах нет — гипотеза: "
                         "в сдачу только решением инспектора")


def _insulation_side(lam, prods):
    """Значение стадии для ZU-126: λ по видам утеплителя, а где λ нет — марки."""
    parts = []
    for key in sorted({c["key"] for c in lam} | {p["key"] for p in prods}):
        values = insulation.by_cond([c for c in lam if c["key"] == key]).get(key) or {}
        if values:
            shown = "; ".join(", ".join(insulation.show(v) for v in sorted(vals)) + insulation.cond_text(cond)
                              for cond, vals in sorted(values.items(), key=lambda kv: str(kv[0])))
            parts.append(f"{key}: λ {shown}")
        else:
            names = sorted({p["product"] for p in prods if p["key"] == key})
            parts.append(f"{key}: {', '.join(names[:4])}" + (f" и ещё {len(names) - 4}" if len(names) > 4 else ""))
    return "; ".join(parts) or None


def lambda_findings(object_id, code, rule, found, catalog):
    """Теплопроводность утеплителя наружных стен, одна запись на объект (ZU-126, #188).

    λ стадий сравнивается по виду утеплителя и условиям (`insulation.compare`): рост больше допуска
    правила — нарушение, в допуске — «нарушения нет», разные условия — «сравнение невозможно».
    Производитель утеплителя в РД, которого у того же вида нет в ПД, без λ — гипотеза «замена без
    подтверждения λ»: решает эксперт.

    Конфликт редакций решения не меняет: сравнивается наибольший λ стадии, а замена ищется среди
    всех названных марок. Поэтому «место» кандидата — вид утеплителя, и `clarify_revisions` записи
    не трогает.
    """
    cat = catalog.get(code, {})
    tolerance = (rule.get("compare") or {}).get("tolerance_pct", insulation.TOLERANCE_PCT)
    sides = {st: latest_only(found.get(st, [])) for st in ("PD", "RD")}
    lam = {st: [c for c in cs if c.get("form") == "lambda"] for st, cs in sides.items()}
    prods = {st: [c for c in cs if c.get("form") == "product"] for st, cs in sides.items()}
    worse, ok, other = insulation.compare(insulation.by_cond(lam["PD"]), insulation.by_cond(lam["RD"]), tolerance)
    replaced = insulation.new_makers(prods["PD"], prods["RD"], lam["RD"])
    if not lam["PD"] and not lam["RD"] and not replaced:
        return []
    show, cond_text = insulation.show, insulation.cond_text
    decisive = {"PD": [], "RD": []}

    def pick(st, key, cond, value):
        decisive[st] += [c for c in lam[st] if c["key"] == key and c.get("cond") == cond and c["value"] == value]

    if worse or replaced:
        label = "VIOLATION_PRESENT"
        result = "VALUE_MISMATCH" if worse else "CONFIGURATION_MISMATCH"
        said = []
        for key, cond, p, r, pct in worse:
            said.append(f"{key}{cond_text(cond)}: λ в РД {show(r)} против {show(p)} в ПД — больше на {pct} %, "
                        f"допуск {tolerance} %")
            pick("PD", key, cond, p)
            pick("RD", key, cond, r)
        for key, maker, rd_names, pd_names in replaced:
            was = "; ".join(f"{m}: {', '.join(n)}" for m, n in pd_names.items())
            said.append(f"{key}: в РД {maker}: {', '.join(rd_names)}, в ПД — {was}; λ нового утеплителя в документах нет")
            decisive["RD"] += [c for c in prods["RD"] if c["key"] == key and c["maker"] == maker]
            decisive["PD"] += [c for c in prods["PD"] if c["key"] == key and c["maker"] in pd_names]
        detail = "; ".join(said)
    elif ok:
        label = "NO_VIOLATION"
        result = "EQUAL_PD_RD" if all(p == r for _k, _c, p, r, _pct in ok) else "NON_TRIGGERING_DIFFERENCE_NO_DECREASE"
        detail = (f"λ утеплителя стен в РД не больше проектного сверх допуска {tolerance} %: "
                  + "; ".join(f"{key}{cond_text(cond)} {show(r)} против {show(p)}" for key, cond, p, r, _pct in ok))
        for key, cond, p, r, _pct in ok:
            pick("PD", key, cond, p)
            pick("RD", key, cond, r)
    else:
        label, result = "COMPARISON_IMPOSSIBLE", None
        if other:
            detail = "λ названы при разных условиях эксплуатации: " + "; ".join(
                f"{key} — ПД: {insulation.conds_text(p)}, РД: {insulation.conds_text(r)}" for key, p, r in other)
        elif lam["PD"]:
            detail = "λ утеплителя стен в рабочей стадии не назван"
        else:
            detail = "λ утеплителя стен в проектной стадии не назван"
        decisive = {st: lam[st] for st in ("PD", "RD")}
    f = _object_finding(object_id, code, cat, rule, label, result, detail, {"PD": False, "RD": False},
                        _insulation_side(lam["PD"], prods["PD"]), _insulation_side(lam["RD"], prods["RD"]),
                        _page_evidence(decisive, limit=2), location_type="CONSTRUCTION_ELEMENT",
                        locations=["Наружные стены"], sides=decisive)
    if replaced:
        as_hypothesis(f, INSULATION_HYPOTHESIS)
        confidence_note(f, low=["λ нового утеплителя в документах не назван: сравнить нельзя, решает эксперт"])
        if any("аналог" in c["snippet"] for c in decisive["PD"]):
            confidence_note(f, medium=["в проекте марка названа с оговоркой «или аналог»: замена допустима при λ "
                                       "не хуже проектного"])
    if worse:
        confidence_note(f, up=["λ одного вида утеплителя назван в обеих стадиях при одних условиях"])
    return [f]


# черновики шестого круга (26.09): вид → (модуль, функция разбора, место записи)
DRAFT_PARSERS = {"pipe_materials": (pipe_materials, "materials", "OBJECT"),
                 "facade_colors": (facade_colors, "colors", "OBJECT"),
                 "slope_range": (slopes, "slopes", "SITE"),
                 "material_takeoff": (takeoffs, "takeoffs", "OBJECT")}
DRAFT_WHY = {
    "pipe_materials": "решение о материале названо фразой проекта («магистрали и стояки … из …»), спецификация не "
                      "сравнивается",
    "facade_colors": "код цвета стоит у элемента фасада в перечне отделки",
    "slope_range": "уклоны рабочей стадии сравниваются с диапазоном, заявленным в проекте, и с пределами норм, на "
                   "которые проект ссылается: единого предела нет",
    "material_takeoff": "объём бетона одного и того же элемента из ведомости или примечания к листу",
}
# почему расхождение — гипотеза, а не нарушение: ответы специалиста шестого круга (Р-111, Р-112)
DRAFT_HYPOTHESIS = {
    "pipe_materials": "замена на части участка, на участке, о котором проект молчит, или при сравнении системы "
                      "целиком — гипотеза: в сдачу только решением инспектора",
    "facade_colors": "изменение цвета фасада без ссылки на согласование — гипотеза: согласование по документам "
                     "пакета не видно",
    "slope_range": "расхождение уклонов — гипотеза: подпись уклона на плане не говорит, проезд это, тротуар или "
                   "газон",
    "material_takeoff": "расхождение объёма бетона — гипотеза",
}
RULE_HYPOTHESIS = "такое расхождение — гипотеза: в сдачу только решением инспектора"


def _draft_confidence(finding, kind, sides):
    """Доводы уверенности записи черновика шестого круга (`confidence_note`, Р-104)."""
    rd = sides.get("RD") or []
    if kind == "pipe_materials":
        if finding["violation_label"] == "VIOLATION_PRESENT" and pipe_materials.WHOLE in finding["extraction"]["detail"]:
            confidence_note(finding, low=["участок системы не назван хотя бы в одной стадии: сравнивается система "
                                          "целиком"])
        detail = finding["extraction"]["detail"]
        if finding["violation_label"] == "VIOLATION_PRESENT" and pipe_materials.UNNAMED in detail:
            confidence_note(finding, low=["участок рабочей стадии в проекте не назван: такая замена — гипотеза"])
        if finding["violation_label"] == "VIOLATION_PRESENT" and "переход на трубу" in detail:
            confidence_note(finding, medium=["материал виден по переходу на схеме или в спецификации: на каком "
                                             "участке труба, по тексту не определить"])
        if finding["violation_label"] == "VIOLATION_PRESENT" and any(c.get("expansion") for c in rd):
            # компенсаторы замену не снимают: перерасчёта расширения в пакете всё равно нет (IOS2-072, вопрос 1)
            confidence_note(finding, medium=["в рабочей стадии названы компенсаторы или неподвижные опоры, но "
                                             "перерасчёта расширения в пакете нет — замену это не снимает"])
        confidence_note(finding, medium=["участок системы назван по фразе, а не по схеме: проверьте, тот ли это "
                                         "участок"])
    elif kind == "facade_colors":
        detail = finding["extraction"]["detail"]
        if finding["violation_label"] == "VIOLATION_PRESENT" and "другой код" not in detail:
            confidence_note(finding, low=["в рабочей стадии к проектным кодам добавлен ещё один — возможно, это "
                                          "другой участок фасада"])
        if any(c.get("approval") for c in rd):
            confidence_note(finding, low=["на листе РД есть ссылка на архитектурно-градостроительное решение — "
                                          "изменение, возможно, согласовано"])
        confidence_note(finding, medium=["согласование изменения по документам пакета не видно"])
    elif kind == "slope_range":
        confidence_note(finding, medium=["вид пути (проезд, тротуар, газон) по подписи уклона на плане не виден"])
    elif kind == "material_takeoff":
        confidence_note(finding, up=["объём одного и того же элемента назван в обеих стадиях"])
    return finding


def set_findings(object_id, code, rule, found, catalog):
    """Набор значений по ключу обеих стадий: черновики шестого круга, одна запись на параметр.

    Ключ — участок системы (трубы), элемент фасада (цвет), вид уклона, элемент (бетон); какое
    расхождение считать изменением, решает функция `changes` модуля разбора, какое из них
    нарушение — `strict` модуля (ответы специалиста шестого круга, Р-112). Остальные расхождения
    и модули без `strict` (цвет фасада, уклоны) — гипотезы. Совпадение — «нарушения нет».
    """
    cat = catalog.get(code, {})
    kind = rule["kind"]
    module = DRAFT_PARSERS[kind][0]
    sides, fallback = _sides(rule, cat, found)
    if not sides["PD"] and not sides["RD"]:
        return []
    keyed, raws, labels = {}, collections.defaultdict(set), collections.defaultdict(set)
    for st in ("PD", "RD"):
        keyed[st] = collections.defaultdict(set)
        for c in sides[st]:
            keyed[st][c["key"]].add(c["value"])
            raws[(st, c["key"])].add(c["raw"])
            if c.get("label"):
                labels[c["key"]].add(c["label"])
    numeric = kind in ("slope_range", "material_takeoff")

    def name(key):
        # ключ элемента бетона — основы слов («обвя пояс»); инспектору — как элемент назван в стадиях
        return module.title(key, labels[key]) if hasattr(module, "title") else key

    def side_value(st):
        parts = []
        for key in sorted(keyed[st]):
            shown = module.show(key, keyed[st][key]) if numeric else ", ".join(sorted(raws[(st, key)]))
            parts.append(f"{name(key)}: {shown}")
        return "; ".join(parts) or None

    if kind == "material_takeoff":
        changes = takeoffs.changes(keyed["PD"], keyed["RD"], (rule.get("compare") or {}).get("threshold", 0.02))
    else:
        changes = module.changes(keyed["PD"], keyed["RD"])
    pairs = module.compare_pairs(keyed["PD"], keyed["RD"]) if hasattr(module, "compare_pairs") else \
        [(k, k) for k in sorted(set(keyed["PD"]) & set(keyed["RD"]))]
    if changes:
        label, result = "VIOLATION_PRESENT", (rule.get("compare") or {}).get("result_violation") or "VALUE_MISMATCH"
        detail = "; ".join(f"{name(k)}: {module.show(k, p) if numeric else ', '.join(sorted(p))} → "
                           f"{module.show(k, r) if numeric else ', '.join(sorted(r))} ({why})" for k, p, r, why in changes)
    elif not sides["PD"] or not sides["RD"]:
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = f"в {'проектной' if not sides['PD'] else 'рабочей'} стадии значений не найдено"
    elif not pairs:
        label, result = "COMPARISON_IMPOSSIBLE", None
        detail = "стадии называют разное: проект — " + ", ".join(sorted(keyed["PD"])) + \
            "; рабочая — " + ", ".join(sorted(keyed["RD"]))
    else:
        label, result = "NO_VIOLATION", "EQUAL_PD_RD"
        same = [name(kp) if kp == kr else f"{kp} → {kr}" for kp, kr in pairs]
        detail = f"{getattr(module, 'SAME', 'совпадает')}: {', '.join(same)}"
    detail += f". {DRAFT_WHY[kind]}"
    where = DRAFT_PARSERS[kind][2]
    f = _object_finding(object_id, code, cat, rule, label, result, detail, fallback, side_value("PD"), side_value("RD"),
                        _page_evidence(sides), location_type=where,
                        locations=["Строительная площадка"] if where == "SITE" else None, sides=sides)
    if label == "VIOLATION_PRESENT" and not any(getattr(module, "strict", lambda c: False)(c) for c in changes):
        as_hypothesis(f, DRAFT_HYPOTHESIS[kind])
    return [_draft_confidence(f, kind, sides)]


def _mark_key(name):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", name or "")]


def applicability(object_id, rules):
    """Применимость параметров, правила которых её задают (`applies_if`): одна строка на параметр."""
    checks, out = {}, []
    for code, rule in rules["parameters"].items():
        check = rule.get("applies_if")
        if not check:
            continue
        if check not in checks:
            checks[check] = APPLICABILITY[check](object_id, page_texts)
        out.append({"parameter_code": code, "check": check, **checks[check]})
    return out


def _fmt(side, unit, rule=None):
    """Значение стороны для записи: как напечатано плюс единица каталога.

    Если правило объявило единицу (#94), печатается приведённое значение, а не исходная
    строка: «радиус поворота 5500 мм» при единице правила «м» это «5,5 м», и писать
    «5500 м» — значит выдать за метры миллиметры. Исходная строка остаётся в `extraction`.
    """
    if side is None:
        return None
    if isinstance(unit, list):
        # подпись правила в трёх формах (`display_unit`, Р-73) согласуется с числом стороны
        unit = _plural(side.get("value"), unit)
    unit = "" if unit in (None, "—", "ед.", "Буква", "Степень", "Кат.") or \
        str(unit).startswith("Класс") else unit
    shown = side["raw"]
    if shown == "PRESENT":
        # наличие — метка, а не число: «PRESENT шт.» у поручней МГН ничего не значит (#145)
        return shown
    want = (rule or {}).get("unit")
    if want and isinstance(side.get("value"), (int, float)):
        shown = f"{side['value']:g}".replace(".", ",")
        unit = want
    # у параметра, значение которого подписано на чертеже не одним числом, в записи стоит
    # весь набор: писать один уклон кровли, у которой участки с разными уклонами, — неправда (#98)
    if len(side.get("all_values") or []) > 1:
        shown = _join_values(side["all_values"])
        unit = want or unit
    return f"{shown} {unit}".strip()


NUMBER = re.compile(r"(?<![\d.,])(\d{3,5})(?![\d.,])")


def known_values(object_id, rule, cands):
    """Числа, которые проект пишет текстом на листах того же вида, что читала модель (R4-H06, R4-H10).

    Модель выписывает с листа осей не все размеры и не всегда те: в двух гипотезах KR-054 все
    «новые» размеры рабочей стадии стояли текстом на листах осей проекта — это проёмы и простенки.
    Листы — страницы томов проекта, откуда модель брала значения, с тем же признаком листа
    (`vlm.sheet_text`); числа — в диапазоне правила (`vlm.value_range`). Сравнение набором их
    изменением не считает. Читается при сравнении, а не при разборе страницы: такие кандидаты
    сдвигали бы плотность страниц, по которой сводятся значения других правил.
    """
    vlm = rule.get("vlm") or {}
    if not vlm.get("sheet_text"):
        return []
    sheet = re.compile(vlm["sheet_text"], re.I)
    lo, hi = vlm.get("value_range") or (0, math.inf)
    files = {c["file_id"] for c in cands if c.get("file_id")}
    if not files:
        return []
    docs = {d["file_id"]: d for d in _read_jsonl(os.path.join(OUT, object_id, "documents.jsonl"))}
    root = OBJECTS[object_id]["root"]
    out = set()
    for fid in sorted(files):
        if fid not in docs:
            continue
        for _page, text in page_texts(docs[fid], root):
            if text and sheet.search(text):
                out |= {int(x) for x in NUMBER.findall(text) if lo <= int(x) <= hi}
    return sorted(out)


def build_findings(object_id, rules=None, progress=None, collected=None):
    """Находки первой очереди по объекту. Возвращает (находки, сводка).

    `collected` — уже собранные кандидаты `(кандидаты, плотность, прочитано страниц)`, как их отдаёт
    `collect`. Так пробный прогон правила (`pipeline/rule_test.py`) решает одно правило с весами
    страниц всей очереди, а не только своими: иначе голосование шло бы иначе, чем в рабочем прогоне.
    """
    rules = rules or load_rules()
    catalog = load_catalog()
    found, density, pages_read = collected if collected is not None else collect(object_id, rules, progress)
    loc = rules.get("location_defaults", {})
    findings, summary = [], collections.Counter()

    element_sides = {}
    for code, rule in rules["parameters"].items():
        if not rule.get("implemented"):
            summary["не реализовано"] += 1
            continue
        if rule.get("elements"):
            # кандидаты по элементам (ZU-128) идут своим сравнением, а не набором значений правила
            element_sides[code] = {st: [c for c in cs if c.get("element")] for st, cs in found[code].items()}
            found[code] = collections.defaultdict(list, {st: [c for c in cs if not c.get("element")]
                                                         for st, cs in found[code].items()})
        # цепочки редакций с неупорядоченными и расходящимися значениями (#10): такие записи
        # уходят на уточнение, а не в нарушение и не в «нарушения нет»
        conflicts = revision_conflicts(found[code].get("PD", []) + found[code].get("RD", []))
        if rule.get("kind") in ROOM_KINDS:
            # состав систем по помещениям и состав установок (#37): свой разбор таблиц и листов
            from pipeline import room_compare
            made, note = room_compare.rule_findings(object_id, code, rule, catalog, findings, progress)
            if note.get("отказ"):
                # почему сравнивать нечего: «в рабочей стадии нет документов отопления и вентиляции»
                summary["пояснения"] = "; ".join(filter(None, [summary.get("пояснения"), f"{code}: {note['отказ']}"]))
            if not made:
                summary["не найдено"] += 1
            for f in made:
                summary[f["violation_label"]] += 1
            findings.extend(made)
            continue
        builders = {"fire_jets": jets_findings, "light_sources": lighting_findings, "resource_meters": meter_findings,
                    "apartment_mix": mix_findings, "steel_protection": steel_findings,
                    "finish_fire_class": finish_findings, "construction_duration": duration_findings,
                    "insulation_lambda": lambda_findings, "detector_count": detector_findings,
                    "alarm_capacity": alarm_findings, "door_opening": door_findings,
                    "deformation_joints": joint_findings, "window_schedule": window_findings,
                    **{kind: site_findings for kind in SITE_PARSERS},
                    **{kind: set_findings for kind in DRAFT_PARSERS}}
        if rule.get("kind") in KEYED_KINDS or rule.get("kind") in builders:
            build = builders.get(rule["kind"], keyed_findings)
            made = build(object_id, code, rule, found[code], catalog)
            clarify_revisions(made, conflicts)
            recognized_review(made)
            if not made:
                summary["не найдено"] += 1
            for f in made:
                summary[f["violation_label"]] += 1
            findings.extend(made)
            continue
        if rule.get("scope") == "element":
            made = element_findings(object_id, code, rule, found[code], catalog)
            clarify_revisions(made, conflicts)
            recognized_review(made)
            if not made:
                summary["не найдено"] += 1
            for f in made:
                summary[f["violation_label"]] += 1
            findings.extend(made)
            continue
        classes = rules["classes"].get(rule.get("class")) if rule.get("class") else None
        cat_rec = catalog.get(code, {})
        pd_c, pd_fb = prefer_source(latest_only(found[code].get("PD", [])),
                                    source_hints(cat_rec.get("source_pd")))
        rd_c, rd_fb = prefer_source(latest_only(found[code].get("RD", [])),
                                    source_hints(cat_rec.get("source_rd")))
        pd_c, rd_c = choose_values(rule, pd_c), choose_values(rule, rd_c)
        pd = reconcile(pd_c, density)
        rd = reconcile(rd_c, density)
        id_all = latest_only(found[code].get("ID", []))
        if rule.get("scope") not in ("element", "keyed"):
            # показатель здания или участка из паспорта изделия — не показатель здания (#145)
            id_all = [c for c in id_all if not c.get("product_doc")]
        id_c, id_fb = prefer_source(id_all, source_hints(cat_rec.get("source_rd")))
        id_c = choose_values(rule, id_c)
        built = reconcile(id_c, density)
        if rule.get("kind") == "feature_presence":
            pd, rd, built = (union_presence(pd, pd_c), union_presence(rd, rd_c),
                             union_presence(built, id_c))
        as_set = (rule.get("compare") or {}).get("type") in ("set_decrease", "min_trigger", "max_trigger", "set_change")
        if as_set:
            pd, rd, built = (with_all_values(pd, pd_c), with_all_values(rd, rd_c),
                             with_all_values(built, id_c))
        if pd and (rule.get("compare") or {}).get("type") == "set_change":
            pd["known_values"] = known_values(object_id, rule, pd_c)
        history = {"PD": revision_history(found[code].get("PD", []), pd),
                   "RD": revision_history(found[code].get("RD", []), rd)}
        label, result, detail = decide(rule, pd, rd, classes)
        if (label in ("VIOLATION_PRESENT", "NO_VIOLATION") and pd_fb and rd_fb
                and pd and rd and pd["value"] != rd["value"]):
            # Оба значения взяты не из раздела-источника и расходятся. Совпадение
            # двух независимых документов подтверждает значение, а расхождение
            # скорее говорит, что документы описывают разное: на Алтуфьевском
            # степень огнестойкости III взята из раздела доступности инвалидов,
            # а II — из энергоэффективности, и это могут быть разные корпуса.
            label, result = "COMPARISON_IMPOSSIBLE", None
            detail = f"оба значения не из раздела-источника и расходятся: {detail}"
        if (label in ("VIOLATION_PRESENT", "NO_VIOLATION")
                and rule.get("kind") in STRICT_SOURCE_KINDS and (pd_fb or rd_fb)):
            weak = [st for st, fb in (("проектной", pd_fb), ("рабочей", rd_fb)) if fb]
            label, result = "COMPARISON_IMPOSSIBLE", None
            detail = (f"значение в {' и '.join(weak)} стадии найдено не в разделе, "
                      f"который каталог называет источником: {detail}")
        # колонка выбрана положением, а не шапкой: на чужом оформлении это догадка (#41)
        by_rule = [name for name, side in (("проектной", pd), ("рабочей", rd))
                   if side and side.get("column_choice") == "rule" and len(side.get("columns") or []) > 1]
        if by_rule and label is not None:
            detail += (f"; в {' и '.join(by_rule)} стадии шапка таблицы не распознана, "
                       f"колонка выбрана по правилу «{rule.get('rule', 'last')}»")
        # исполнительная документация: построенное против рабочей стадии (#42)
        label, result, detail, id_note = id_review(rule, pd, rd, built, label, result, detail, decide, classes=classes)
        if label is None and built is not None:
            label, result, detail = "COMPARISON_IMPOSSIBLE", None, id_note
        if label is None:
            summary["не найдено"] += 1
            continue
        summary[label] += 1
        l = loc.get(code) or loc.get("__site__" if rule.get("scope") == "site" else "__building__", {})
        cat = catalog.get(code, {})
        if rule.get("display_unit"):
            # Каталог называет единицу параметра, а правило может считать другое: SPZU-029
            # считает позиции ведомости МАФ, штуки у неё в своей колонке, и каталожное
            # «шт. / компл.» выдало бы 16 позиций за 16 изделий (Р-73)
            cat = dict(cat, unit=rule["display_unit"])
        # Сколько страниц показывать: значению из таблицы хватает трёх, а наличие
        # системы подтверждается тем, что она названа на нескольких листах (#84).
        page_limit = rule.get("evidence_pages", 3)
        evidence = []
        for side, stage in ((pd, "PD"), (rd, "RD")):
            if side:
                for fid, page in side["pages"][:page_limit]:
                    evidence.append({"stage": stage, "file_id": fid, "pdf_page_number": page,
                                     "quote": side["snippet"], "localization": "PAGE_LEVEL"})
        id_evidence(built, evidence)
        findings.append({
            "finding_id": f"{object_id}::{code}",
            "object_id": object_id,
            "matrix_scope": "MATRIX",
            "parameter_code": code,
            "parameter_id": cat.get("parameter_id"),
            "title": cat.get("parameter_name"),
            "comparison_result": result or "VALUE_MISMATCH",
            "location_type": l.get("location_type", "OBJECT"),
            "locations": [l.get("location", "")] if l.get("location") else [],
            "pd_value": _fmt(pd, cat.get("unit"), rule),
            "rd_value": _fmt(rd, cat.get("unit"), rule),
            "id_value": _fmt(built, cat.get("unit"), rule),
            "violation_label": label,
            "criticality": cat.get("criticality") if label == "VIOLATION_PRESENT" else None,
            "finding_status": "CANDIDATE",
            # замена марки без понижения прочности: решение о согласованности изменения — за инспектором
            **({"needs_expert": True} if result == steel.SUBSTITUTION else {}),
            "evidence": evidence,
            "extraction": {
                "rule_basis": rule.get("basis"),
                "detail": detail,
                # значение параметра — набор подписей, а не одно число: расхождение значений
                # стадий здесь и есть предмет сравнения, а не признак ошибки чтения (#98)
                **({"values_are_set": True} if as_set else {}),
                "source_fallback": {"PD": pd_fb, "RD": rd_fb, "ID": id_fb},
                "pd": pd and _side_view(pd, SIDE_VIEW, history["PD"]),
                "rd": rd and _side_view(rd, SIDE_VIEW, history["RD"]),
                "id": built and _side_view(built, SIDE_VIEW, []),
                "id_check": id_note,
            },
        })
        if conflicts:
            summary[label] -= 1
            clarify_revisions(findings[-1:], conflicts)
            summary[findings[-1]["violation_label"]] += 1
        recognized_review(findings[-1:])
        # порог-триггер у значений модели — гипотеза (модель отвечает всеми элементами листа); у значения из
        # текста (ODI-118, порог двери) нарушение по триггеру остаётся нарушением (Р-112)
        if as_set and rule.get("vlm") and (rule.get("compare") or {}).get("type") in ("min_trigger", "max_trigger") \
                and findings[-1]["violation_label"] in ("VIOLATION_PRESENT", "NO_VIOLATION"):
            threshold_confidence(findings[-1])
        elif rule.get("hypotheses") == "drawing":
            drawing_hypothesis(findings[-1], rule, cat.get("criticality"), pd_c + rd_c)
        rule_hypothesis(findings[-1], rule, pd_c + rd_c)
    for code, sides in element_sides.items():
        roof_elements(object_id, code, rules["parameters"][code], sides, catalog, findings, summary)
    finding_status(findings)
    # решения специалиста по виду записи (Р-108); решений по отдельной записи нет (Р-116): они
    # подменяли правило готовым ответом на открытом корпусе и на новом объекте не срабатывали
    from pipeline import specialist
    findings, _ = specialist.apply(findings)
    summary["страниц прочитано"] = pages_read
    return findings, summary


def roof_elements(object_id, code, rule, sides, catalog, findings, summary):
    """Утеплитель кровли по элементам (ZU-128, #137) поверх сравнения значений правила.

    Марки покрытий у стадий разные (П5 в ПД, П3 в РД Речникова), а элемент — лифтовые шахты —
    один. Материал и толщина утеплителя сравниваются по элементу, названному в обеих стадиях:
    другой материал или меньшая толщина — нарушение (специалист, V-insulation-roof: «нарушение, если
    не представлено расчётного обоснования»; решение пользователя 25.09 ставить так и эту находку).
    Если расхождения по элементам нет, остаётся прежний вывод, а совпадение пишется в пояснение.
    """
    pd = {}
    rd = {}
    for stage, into in (("PD", pd), ("RD", rd)):
        for c in latest_only(sides.get(stage, [])):
            into.setdefault(c["key"], []).append(c)
    common = sorted(set(pd) & set(rd))
    if not common:
        return
    changes, same = [], []
    for element in common:
        for r in rd[element]:
            ok = [p for p in pd[element] if p["material"] == r["material"] and r["mm"] >= p["mm"]]
            if ok:
                same.append(element)
                continue
            p = max(pd[element], key=lambda c: c["mm"])
            why = []
            if p["material"] != r["material"]:
                why.append("материал утеплителя заменён")
            if r["mm"] < p["mm"]:
                why.append(f"толщина {p['mm']:g} → {r['mm']:g} мм")
            changes.append((element, p, r, "; ".join(why)))
            break
    old = next((f for f in findings if f["finding_id"] == f"{object_id}::{code}"), None)
    if not changes:
        if old is not None:
            old["extraction"]["detail"] = (old["extraction"].get("detail") or "") + \
                f"; по элементам кровли совпадает: {', '.join(sorted(set(same)))}"
        return
    cat = catalog.get(code, {})
    shown = "; ".join(f"{e}: {p['value']} → {r['value']} ({why})" for e, p, r, why in changes)
    before = (old or {}).get("extraction", {}).get("detail")
    material_changed = any("материал" in why for *_x, why in changes)
    evidence = _page_evidence({"PD": [p for _e, p, _r, _w in changes], "RD": [r for _e, _p, r, _w in changes]})
    made = {
        "finding_id": f"{object_id}::{code}",
        "object_id": object_id,
        "matrix_scope": "MATRIX",
        "parameter_code": code,
        "parameter_id": cat.get("parameter_id"),
        "title": cat.get("parameter_name"),
        "comparison_result": "CONFIGURATION_MISMATCH" if material_changed else "VALUE_DECREASE",
        "location_type": "CONSTRUCTION_ELEMENT",
        "locations": [e for e, *_x in changes],
        "pd_value": "; ".join(f"{e}: {p['value']}" for e, p, _r, _w in changes),
        "rd_value": "; ".join(f"{e}: {r['value']}" for e, _p, r, _w in changes),
        "id_value": None,
        "violation_label": "VIOLATION_PRESENT",
        "criticality": cat.get("criticality"),
        "finding_status": "CANDIDATE",
        "evidence": evidence,
        "extraction": {
            "rule_basis": rule.get("basis"),
            "detail": f"утеплитель кровли по элементам: {shown}" + (f"; по чертежам: {before}" if before else ""),
            "elements": [{"element": e, "pd": p["value"], "pd_mark": p.get("mark"), "rd": r["value"],
                          "rd_mark": r.get("mark"), "why": why} for e, p, r, why in changes],
            "pd": {"raw": "; ".join(p["value"] for _e, p, _r, _w in changes)},
            "rd": {"raw": "; ".join(r["value"] for _e, _p, r, _w in changes)},
        },
    }
    if old is not None:
        summary[old["violation_label"]] -= 1
        findings[findings.index(old)] = made
    else:
        findings.append(made)
    summary["VIOLATION_PRESENT"] += 1
