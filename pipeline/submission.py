"""Проекция находки в формат сдачи организатора. Задача #8.

Находка — внутренняя единица результата: объект, параметр, сопоставленные редакции,
доказательные фрагменты, следы разбора и решение инспектора. Организатор принимает
из этого небольшую часть по `contracts/submission.schema.json`: код параметра,
локацию, значения по стадиям, метку нарушения, статус протокола, критичность
и доказательства из трёх полей — стадия, идентификатор файла, номер страницы PDF.

Проекция кажется механической, но именно на ней теряются баллы, и молча. Ниже —
всё, что выяснилось при сверке с эталонным пакетом организатора, с обоснованием.

## 1. Одна находка с несколькими помещениями это несколько записей сдачи

В эталоне организатора запись заводится на каждое помещение отдельно. Нарушение
«тёплый пол отсутствует» в помещениях 267, 270, 271, 272 записано четырьмя
контрольными точками TRAIN-0002…0005 с одинаковым кодом и разными локациями.
У нашей находки локации лежат списком, а в записи сдачи поле `location` одно.

Сопоставление записей идёт по ключу «объект, код параметра» с требованием
пересечения локаций, один к одному. Одна запись с четырьмя локациями заберёт
одну эталонную, а три оставшиеся станут пропусками. Поэтому находка
разворачивается по локациям: сколько локаций, столько записей.

Замерено на эталоне (`tests/test_submission.py`): без разворота четыре записи
вместо десяти, шесть пропусков, F1 падает с 1,000 до 0,571. Среди пропущенных
есть критические контрольные точки, поэтому срабатывает гейт и балл становится
ровно 59 вместо 100. Это самая дорогая ошибка проекции из возможных.

## 2. Стадия файла в реестре и стадия в доказательстве — разные вещи

В реестре организатора тома F0201 и F0202 помечены стадией RD_ID_MIXED: файл
содержит и рабочую часть, и исполнительную. В доказательствах тех же нарушений
организатор пишет стадию RD. То есть стадия реестра описывает файл, а стадия
доказательства — содержимое конкретной страницы.

В схеме сдачи стадия ограничена тремя значениями PD, RD и ID, RD_ID_MIXED там
недопустим. Доказательство со стадией из реестра не совпадёт с эталонным ни по
схеме, ни по сравнению, и локализация обнулится.

Замерено на эталоне: доказательство с проектной стадией не страдает, а оба
доказательства рабочей стадии перестают совпадать. Локализация падает с 1,000
до 0,500, балл со 100 до 92,50. Вдобавок такой документ не проходит схему
организатора: RD_ID_MIXED не входит в перечень допустимых стадий.

У организатора здесь нестыковка внутри собственного пакета. Его постраничный
индекс `page_index.jsonl` проставляет каждой странице стадию файла целиком: все
712 страниц смешанных томов помечены RD_ID_MIXED, то есть значением, которое его
же схема сдачи запрещает. В эталонных доказательствах стадия исправлена на RD
вручную. Вопрос вынесен в `docs/questions-to-organizers.md`.

Правильное решение — определять стадию страницы по её содержимому, а не по файлу.
Сегодня оно недостижимо: основная надпись на страницах смешанных томов читается
в 2 случаях из 712, остальное — чертежи без текстового слоя (задача #16). Поэтому
экспорт берёт стадию доказательства, если она задана, и лишь затем сводит стадию
файла к RD. Каждое такое сведение считается и попадает в отчёт, чтобы подмена
не была молчаливой.

## 3. В запись сдачи уходят поля сверх схемы организатора

Схема сдачи описывает меньше, чем несёт эталон самого организатора. В его
контрольных точках есть `comparison_result`, `matrix_scope`, `parameter_id`,
`location_type` и `document_status`, и ни одного из них в схеме нет.

`matrix_scope` и `comparison_result` кладутся обязательно: на них держится правило
отождествления для находок вне Матрицы, где кода параметра нет или он произвольный.
Остальные кладутся, когда находка их несёт. `document_status` выглядит ровно тем
полем, на котором может считаться составляющая о комплектности документов, и его
отсутствие в схеме похоже на недосмотр.

Риска в этом нет: `additionalProperties` в схеме не указан, а лишние ключи в JSON
Schema по умолчанию разрешены. Проверка по схеме организатора такой документ
пропускает, что мы и проверяем тестом.

## 4. Записи без нарушения тоже уходят в сдачу

Организатор опубликовал только название составляющей «комплектность документов
и сплит» и её вес, десять баллов. Правила он не публиковал. В нашем скорере
правило задано как гипотеза: половина за воспроизведение эталонных записей
с меткой не VIOLATION_PRESENT, половина за ссылки в пределах реестра объекта.
Это наше допущение, а не его формулировка, и оно вынесено вопросом в
`docs/questions-to-organizers.md`.

Независимо от правила фильтровать находки по метке нельзя: по карточке датасета
из 19 контрольных точек 11 положительных и 8 отрицательных. В публичной обучающей
части отрицательных нет ни одной, поэтому ошибка проявилась бы только на закрытой,
где её уже не исправить. Экспорт по метке не фильтрует.

## 5. Ссылки за пределы реестра объекта штрафуются

Вторая половина той же составляющей — доля доказательств, ссылающихся на файлы
реестра объекта. Плюс организатор исключил из корпуса два файла, F0149 и F0418.
Экспорт отбрасывает доказательства на файлы вне реестра и на исключённые,
и сообщает о каждом отброшенном.

## 6. Дробь в значении пишется с точкой

Во всех 19 контрольных точках организатора дробь записана с точкой: «3694.60 м²»,
«h=2.0 м; 174.45 м», «159.95». Документы и наши находки пишут её с запятой, как принято
в русском тексте. «Значение и статус» (15 баллов) организатор считает по «точному
совпадению нормализованных значений», а как он нормализует, не сказано. Если сверка
строгая — регистр и пробелы, — запятая стоит двух точек Речникова (TEST-0001 и TEST-0003):
по всем объектам с эталоном 96,59 вместо 98,02 (замер 24.09, Р-73). Наш скорер запятую
прощает, поэтому в нашей метрике этой потери не видно.

Поэтому в сдаче запятая между цифрами меняется на точку, а больше в значении ничего
не трогается. Номера через запятую без пробела («267,270,271») — перечень, а не дробь,
и остаются как есть. Экран инспектора и протокол показывают значение так, как оно
напечатано в документе: точка ставится только в файле сдачи.

## 7. Сводная запись берёт метку сильнейшей находки

Находки с одним ключом (код параметра или вид расхождения плюс локация) сводятся в одну
запись. Раньше метку давала первая из них. Файл стенда несёт и записи без решения, и у
Октябрьской по участку три листа схем с отклонением стояли после трёх неразобранных: сводная
запись выходила «сравнение невозможно», и эталонная точка терялась — 95,59 вместо 98,73 по
эталону (Р-82). Теперь нарушение сильнее «нарушения нет», то — сильнее «обязательный документ
отсутствует» и «сравнение невозможно»; значения берутся у той же записи, доказательства
объединяются.
"""
import json
import os
import re
import unicodedata

from pipeline import coords

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCHEMA_PATH = os.path.join(ROOT, "contracts", "submission.schema.json")
ENUMS_PATH = os.path.join(ROOT, "contracts", "enums.json")
SPLIT_POLICY_PATH = os.path.join(ROOT, "docs", "extracted", "split_policy.json")
CATALOG_PATH = os.path.join(ROOT, "docs", "extracted", "parameter_catalog_132.jsonl")

# Стадия файла в реестре -> стадия в доказательстве сдачи. RD_ID_MIXED сводится
# к RD не по нашему решению, а вслед за организатором: в его реестре тома F0201
# и F0202 помечены RD_ID_MIXED, а в его же эталонных доказательствах по этим
# файлам стоит RD.
STAGE_TO_SUBMISSION = {
    "PD": "PD", "RD": "RD", "ID": "ID",
    "RD_ID_MIXED": "RD",
    "ПД": "PD", "РД": "RD", "ИД": "ID",
}

# Стадии, которые описывают саму страницу. Всё остальное описывает файл целиком
# и годится только как запасной вариант.
PAGE_LEVEL_STAGES = {"PD", "RD", "ID"}

# Поля записи сдачи в порядке схемы организатора. Порядок фиксирован, чтобы
# разница между двумя выгрузками читалась глазами.
CHECK_FIELDS = ("parameter_code", "location", "matrix_scope", "comparison_result",
                "parameter_id", "location_type", "pd_value", "rd_value", "id_value",
                "violation_label", "protocol_status", "criticality",
                "document_status", "finding_status", "evidence")

# Поля, которые несёт эталон организатора, но которых нет в его схеме сдачи.
# Кладём их, только если находка их несёт: лишние ключи схема разрешает,
# а `document_status` похож на основание составляющей о комплектности.
OPTIONAL_FIELDS = ("parameter_id", "location_type", "document_status", "finding_status")

_SPACE = re.compile(r"\s+")


def _norm(s):
    if s is None:
        return ""
    return _SPACE.sub(" ", unicodedata.normalize("NFC", str(s))).strip()


# Дробь с запятой: число, запятая, число, и ни одного соседнего числа через запятую —
# «267,270,271» это три номера, а не дробь
_DECIMAL_COMMA = re.compile(r"(?<![\d,])(\d+),(\d+)(?![,\d])")


def submission_value(value):
    """Значение для файла сдачи: дробь с точкой, как в эталоне организатора (раздел 6)."""
    if not isinstance(value, str):
        return value
    return _DECIMAL_COMMA.sub(r"\1.\2", value)


def _load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def criticality_map():
    """Критичность -> статус протокола. Таблица живёт в contracts/enums.json,
    чтобы не расходиться с описанием контрактов."""
    enums = _load_json(ENUMS_PATH) or {}
    return {_norm(k).lower(): v
            for k, v in (enums.get("criticality") or {}).items()
            if not k.startswith("$")}


_CATALOG = None


def parameter_catalog():
    """Каталог 132 параметров организатора, разложенный по коду."""
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = {}
        if os.path.exists(CATALOG_PATH):
            with open(CATALOG_PATH, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        r = json.loads(line)
                        if r.get("parameter_code"):
                            _CATALOG[_norm(r["parameter_code"]).upper()] = r
    return _CATALOG


def criticality_for(finding):
    """Критичность находки. Возвращает (значение, было ли взято из каталога вопреки находке).

    Для параметра Матрицы критичность задаёт каталог организатора, а не находка:
    это свойство параметра, а не конкретного расхождения. У параметра IOS4-078
    в каталоге стоит «Критическое (приостановка работ)», и эталонные контрольные
    точки по нему тоже критические. Находка, объявившая то же нарушение
    существенным, теряет баллы за статус, хотя разбор у неё верный.

    У находок свободного поиска каталога нет, и остаётся значение находки.

    Записей без нарушения это не касается вовсе. В эталоне организатора у всех
    восьми записей с меткой не VIOLATION_PRESENT критичность пустая, а статус
    протокола OK — независимо от того, что каталог говорит о самом параметре.
    Критичность описывает тяжесть нарушения, а нарушения там нет.
    """
    own = finding.get("criticality")
    if _norm(finding.get("violation_label")).upper() != "VIOLATION_PRESENT":
        return own, False
    code = _norm(finding.get("parameter_code")).upper()
    if not code or code.startswith("FREE-"):
        return own, False
    if _norm(finding.get("matrix_scope")).upper() == "FREE_SEARCH":
        return own, False
    rec = parameter_catalog().get(code)
    if not rec or not rec.get("criticality"):
        return own, False
    fromcat = rec["criticality"]
    return fromcat, bool(own) and _norm(own).lower() != _norm(fromcat).lower()


def excluded_file_ids():
    """Файлы, исключённые организатором из корпуса."""
    policy = _load_json(SPLIT_POLICY_PATH) or {}
    return {_norm(x) for x in policy.get("excluded_file_ids") or []}


# ---------- отдельные поля ----------

def submission_stage(stage):
    """Стадия доказательства в терминах схемы сдачи. None, если стадия неизвестна."""
    return STAGE_TO_SUBMISSION.get(_norm(stage).upper())


def protocol_status(finding, criticality=None):
    """Статус протокола. Если находка его не несёт, выводим из критичности.

    Статус сравнивается с эталонным напрямую и стоит пятнадцати баллов вместе
    с меткой нарушения, поэтому пустым его оставлять нельзя, когда критичность
    известна.

    Если критичность пришла из каталога и разошлась с той, что несёт находка,
    статус находки тоже считается устаревшим и выводится заново.
    """
    crit_use = criticality if criticality is not None else finding.get("criticality")
    got = _norm(finding.get("protocol_status"))
    # Статус записи без нарушения из критичности не выводится: критичности у неё
    # нет. В эталоне организатора у всех восьми отрицательных записей стоит OK,
    # у «сравнение невозможно» — одноимённый статус. Без этого правила такая
    # запись уходила с пустым статусом и теряла балл за «значение и статус».
    label = _norm(finding.get("violation_label")).upper()
    if not got and label == "NO_VIOLATION":
        return "OK"
    if not got and label == "COMPARISON_IMPOSSIBLE":
        return "COMPARISON_IMPOSSIBLE"
    if got and _norm(crit_use).lower() == _norm(finding.get("criticality")).lower():
        return got.upper()
    crit = _norm(crit_use).lower()
    if not crit:
        return None
    table = criticality_map()
    if crit in table:
        return table[crit]
    # формулировки критичности у организатора разрастаются оговорками вроде
    # «— требует утверждения»; опираемся на первое слово
    for key, value in table.items():
        if crit.startswith(key.split(" (")[0]):
            return value
    return None


def locations_of(finding):
    """Локации находки списком. Принимает и `locations`, и одиночное `location`."""
    loc = finding.get("locations")
    if loc is None:
        one = finding.get("location")
        loc = [one] if one not in (None, "") else []
    seen, out = set(), []
    for x in loc:
        t = _norm(x)
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def bbox_for_submission(evidence):
    """Прямоугольник в системе координат ТЗ (раздел 9.1): видимая страница, ось Y снизу.

    ТЗ, раздел 9.1 (пункт 4 алгоритма), требует нормализованный прямоугольник
    в диапазоне [0;1] относительно видимой области страницы после учёта CropBox,
    MediaBox и Rotate. В схеме сдачи поле не является обязательным (по умолчанию
    сдача идёт на уровне страницы PAGE_LEVEL_VISUALLY_VERIFIED). Прямоугольник
    включается ключом --with-bbox.
    """
    b = evidence.get("bbox_tz") or evidence.get("bbox_pdf")
    if b is None:
        raw = evidence.get("bbox") or evidence.get("bbox_norm")
        if raw and len(raw) == 4:
            b = coords.internal_to_tz(raw)
    if not b or len(b) != 4:
        return None
    return coords.clamp_bbox([round(float(v), 5) for v in b])


def evidence_of(finding, allowed_files=None, excluded=None, stage_by_file=None,
                with_bbox=False):
    """Доказательства в формате сдачи. Возвращает (список, отброшенное, сведённые стадии).

    Остаются ровно три поля. Номер листа, цитаты, картинки и прямоугольники
    организатор не принимает: в схеме доказательства их нет. Прямоугольник
    добавляется по `with_bbox` — это необязательный вариант под требование ТЗ,
    см. `bbox_for_submission`.

    Стадия берётся сначала с доказательства, и только если она не описывает
    страницу (например RD_ID_MIXED) — из реестра файла. Каждое такое сведение
    возвращается отдельным списком: подменять стадию молча нельзя.
    """
    excluded = excluded if excluded is not None else excluded_file_ids()
    out, dropped, adapted, seen = [], [], [], set()
    for e in finding.get("evidence") or []:
        fid = _norm(e.get("file_id"))
        page = e.get("pdf_page_number")
        raw = _norm(e.get("stage")).upper() or _norm(
            (stage_by_file or {}).get(fid)).upper()
        stage = submission_stage(raw)
        if not fid:
            dropped.append((e, "нет идентификатора файла"))
            continue
        if page is None or not isinstance(page, int) or page < 1:
            dropped.append((e, f"номер страницы не годится: {page!r}"))
            continue
        if stage is None:
            dropped.append((e, f"стадия не приводится к PD, RD или ID: "
                               f"{e.get('stage')!r}"))
            continue
        if fid in excluded:
            dropped.append((e, "файл исключён из пакета объекта"))
            continue
        if allowed_files is not None and fid not in allowed_files:
            dropped.append((e, "файла нет в реестре объекта"))
            continue
        key = (stage, fid, page)
        if key in seen:
            continue
        seen.add(key)
        if raw not in PAGE_LEVEL_STAGES:
            adapted.append({"file_id": fid, "page": page,
                            "from": raw or None, "to": stage})
        row = {"stage": stage, "file_id": fid, "pdf_page_number": page}
        if with_bbox:
            bbox = bbox_for_submission(e)
            row["localization"] = "BBOX" if bbox else "PAGE_LEVEL"
            if bbox:
                row["bbox"] = bbox
        out.append(row)
    out.sort(key=lambda e: (e["stage"], e["file_id"], e["pdf_page_number"]))
    return out, dropped, adapted


# ---------- запись и документ ----------

def checks_from_finding(finding, allowed_files=None, excluded=None,
                        stage_by_file=None, with_bbox=False):
    """Записи сдачи из одной находки: по одной на локацию."""
    evidence, dropped, adapted = evidence_of(
        finding, allowed_files, excluded, stage_by_file, with_bbox)
    crit, overridden = criticality_for(finding)
    base = {
        "parameter_code": finding.get("parameter_code"),
        "matrix_scope": finding.get("matrix_scope"),
        "comparison_result": finding.get("comparison_result"),
        "pd_value": submission_value(finding.get("pd_value")),
        "rd_value": submission_value(finding.get("rd_value")),
        "id_value": submission_value(finding.get("id_value")),
        "violation_label": finding.get("violation_label"),
        "protocol_status": protocol_status(finding, crit),
        "criticality": crit,
        "evidence": evidence,
    }
    for key in OPTIONAL_FIELDS:
        if finding.get(key) not in (None, ""):
            base[key] = finding[key]
    locs = locations_of(finding) or [None]
    checks = []
    for loc in locs:
        # схема требует строку: находка без локации отдаёт пустую, а не null
        row = dict(base, location=loc if loc is not None else "")
        checks.append({k: row[k] for k in CHECK_FIELDS if k in row})
    return checks, dropped, adapted, overridden


# Номер локации целиком: «пом. 012» → «12», «1.01» → «1.1», «Секция 2, пом. 15» → «2.15».
# Раньше ключом было первое число строки, и «1.01» с «1.02» становились одной записью,
# а «Секция 2, пом. 15» — секцией 2 (#41).
_LOC_TOKEN = re.compile(r"[а-яёa-z]?\d+(?:[.\-/]\d+)*[а-яёa-z]?", re.I)


def _no_leading_zeros(part):
    return re.sub(r"(?<!\d)0+(\d)", r"\1", part)


def norm_location(value):
    """Номер помещения к одному виду: нули впереди убираются, номер берётся целиком."""
    text = _norm(value).lower()
    parts = _LOC_TOKEN.findall(text)
    return ".".join(_no_leading_zeros(p) for p in parts) if parts else text


# Какая метка побеждает, когда в одну запись сдачи сводятся несколько находок с одним ключом.
# Решение сильнее его отсутствия, нарушение — сильнее «нарушения нет»: у Октябрьской по участку
# шесть листов исполнительных схем, на трёх отклонения больше допуска, три не разобраны, и
# сводная запись брала метку первого листа — «сравнение невозможно»; эталонная точка терялась
# на файле стенда, где записи без решения остаются (98,73 → 95,59 по эталону)
LABEL_RANK = {"VIOLATION_PRESENT": 3, "NO_VIOLATION": 2, "MISSING_DOCUMENT": 1, "COMPARISON_IMPOSSIBLE": 0}


def _label_rank(check):
    return LABEL_RANK.get(_norm(check.get("violation_label")).upper(), -1)


def _dedup_key(check):
    """Чем две записи считаются одной и той же.

    Совпадает с ключом отождествления в скорере: для находок Матрицы это код
    параметра, для свободного поиска — тип расхождения. Плюс нормализованная
    локация: «пом. 012», «012» и «12» это одно помещение, а «1.01» и «1.02» — разные.
    """
    code = _norm(check.get("parameter_code")).upper()
    free = (_norm(check.get("matrix_scope")).upper() == "FREE_SEARCH"
            or code.startswith("FREE-"))
    head = ("FREE", _norm(check.get("comparison_result")).upper()) if free else ("MATRIX", code)
    return head + (norm_location(check.get("location")),)


def _sort_key(check):
    m = re.search(r"\d+", _norm(check.get("location")))
    return (_norm(check.get("parameter_code")).upper(),
            0 if m else 1, int(m.group()) if m else 0,
            _norm(check.get("location")).lower())


def build(object_id, findings, allowed_files=None, excluded=None,
          stage_by_file=None, keep_evidenceless=True, with_bbox=False):
    """Документ сдачи по объекту. Возвращает (документ, отчёт о потерях).

    keep_evidenceless: оставлять ли запись, у которой не уцелело ни одного
    доказательства. По умолчанию да: такая запись всё ещё приносит балл
    за выявление нарушения, теряя только балл за локализацию. Отчёт о ней
    сообщает в любом случае.

    with_bbox: необязательный вариант под требование ТЗ о координатах. По
    умолчанию выключен: в схеме сдачи поля для прямоугольника нет, а эталон
    организатора локализован постранично. См. `docs/questions-to-organizers.md`.
    """
    excluded = excluded if excluded is not None else excluded_file_ids()
    checks, report = [], {
        "findings_in": 0, "checks_out": 0, "duplicates_dropped": 0,
        "evidence_dropped": [], "checks_without_evidence": [],
        "findings_from_other_objects": [], "stage_adapted": [],
        "criticality_from_catalog": [], "excluded_by_origin": [], "locations_merged": [],
    }
    seen = {}
    for f in findings:
        fobj = _norm(f.get("object_id"))
        if fobj and object_id and fobj != _norm(object_id):
            report["findings_from_other_objects"].append(
                f.get("finding_id") or fobj)
            continue
        if f.get("for_submission") is False:
            # Запись, помеченная «не для сдачи»: эталонный перечень, расходящийся с эталоном
            # организатора (#40), и гипотезы свободного поиска (#56). Проекция всё равно
            # считается и откладывается: инспектор может взять гипотезу в кандидаты и
            # подтвердить, и тогда запись идёт в сдачу (#63). Считать её потом нечем —
            # реестр файлов и стадии есть только здесь.
            held, _, _, _ = checks_from_finding(f, allowed_files, excluded, stage_by_file, with_bbox)
            report["excluded_by_origin"].append({"finding_id": f.get("finding_id"),
                                                 "reason": f.get("exclusion_reason"),
                                                 "checks": held})
            continue
        report["findings_in"] += 1
        rows, dropped, adapted, overridden = checks_from_finding(
            f, allowed_files, excluded, stage_by_file, with_bbox)
        if overridden:
            report["criticality_from_catalog"].append({
                "finding_id": f.get("finding_id"),
                "parameter_code": f.get("parameter_code"),
                "was": f.get("criticality"), "now": rows[0]["criticality"]})
        for a in adapted:
            report["stage_adapted"].append({"finding_id": f.get("finding_id"), **a})
        for e, why in dropped:
            report["evidence_dropped"].append({
                "finding_id": f.get("finding_id"),
                "file_id": e.get("file_id"), "page": e.get("pdf_page_number"),
                "stage": e.get("stage"), "reason": why})
        for row in rows:
            key = _dedup_key(row)
            if key in seen:
                report["duplicates_dropped"] += 1
                first = seen[key].get("location")
                if _norm(first) != _norm(row.get("location")):
                    # слиты записи с разными исходными строками локации: в отчёте видно,
                    # что именно сведено в одну запись, а не снято молча (#41)
                    report["locations_merged"].append({
                        "finding_id": f.get("finding_id"),
                        "parameter_code": row.get("parameter_code"),
                        "kept": first, "merged": row.get("location"), "key": key[-1]})
                # метка и значения — у записи с более сильной меткой (LABEL_RANK); запись
                # остаётся на своём месте в перечне, меняется её содержимое
                if _label_rank(row) > _label_rank(seen[key]):
                    report.setdefault("labels_raised", []).append({
                        "finding_id": f.get("finding_id"), "parameter_code": row.get("parameter_code"),
                        "location": row.get("location"), "from": seen[key].get("violation_label"),
                        "to": row.get("violation_label")})
                    keep = seen[key]["evidence"]
                    seen[key].clear()
                    seen[key].update(row, evidence=keep)
                # доказательства двух одинаковых записей объединяем: они могут
                # прийти из разных находок и покрывать разные страницы
                have = {(e["stage"], e["file_id"], e["pdf_page_number"])
                        for e in seen[key]["evidence"]}
                for e in row["evidence"]:
                    if (e["stage"], e["file_id"], e["pdf_page_number"]) not in have:
                        seen[key]["evidence"].append(e)
                        have.add((e["stage"], e["file_id"], e["pdf_page_number"]))
                seen[key]["evidence"].sort(
                    key=lambda e: (e["stage"], e["file_id"], e["pdf_page_number"]))
                continue
            if not row["evidence"]:
                report["checks_without_evidence"].append({
                    "finding_id": f.get("finding_id"),
                    "parameter_code": row.get("parameter_code"),
                    "location": row.get("location")})
                if not keep_evidenceless:
                    continue
            seen[key] = row
            checks.append(row)

    checks.sort(key=_sort_key)
    report["checks_out"] = len(checks)
    return {"object_id": object_id, "checks": checks}, report


# ---------- проверка по схеме организатора ----------

def _validate(node, schema, path="$"):
    """Проверка по подмножеству JSON Schema, которым пользуется схема сдачи:
    type, required, properties, items, enum, minimum. Зависимостей не тянем,
    а поведение печатаем, чтобы результат нельзя было прочитать неправильно."""
    errs = []
    if "enum" in schema:
        if node not in schema["enum"]:
            errs.append(f"{path}: {node!r} не входит в {schema['enum']}")
        return errs
    types = schema.get("type")
    if types is not None:
        types = [types] if isinstance(types, str) else list(types)
        ok = {
            "object": lambda v: isinstance(v, dict),
            "array": lambda v: isinstance(v, list),
            "string": lambda v: isinstance(v, str),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool),
            "null": lambda v: v is None,
        }
        if not any(ok.get(t, lambda _: True)(node) for t in types):
            errs.append(f"{path}: тип {type(node).__name__}, ожидался {'/'.join(types)}")
            return errs
    if isinstance(node, dict):
        for req in schema.get("required") or []:
            if req not in node:
                errs.append(f"{path}: нет обязательного поля {req!r}")
        for key, sub in (schema.get("properties") or {}).items():
            if key in node:
                errs.extend(_validate(node[key], sub, f"{path}.{key}"))
    if isinstance(node, list) and schema.get("items"):
        for i, item in enumerate(node):
            errs.extend(_validate(item, schema["items"], f"{path}[{i}]"))
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        if "minimum" in schema and node < schema["minimum"]:
            errs.append(f"{path}: {node} меньше минимума {schema['minimum']}")
    return errs


def validate(document, schema=None):
    """Ошибки документа сдачи по схеме организатора. Пустой список — всё в порядке."""
    schema = schema or _load_json(SCHEMA_PATH)
    if not schema:
        return [f"схема не найдена: {SCHEMA_PATH}"]
    return _validate(document, schema)


def write(path, document):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(document, f, ensure_ascii=False, indent=1)
    return path
