"""Пробный прогон одного правила на объекте: трасса и песочница страницы правил эксперта (#222, #223).

Трасса показывает, как правило решило на объекте: что нашлось в каждой стадии, какое значение
выбрано, что отбросили исключения. Песочница прогоняет вариант правила — другой порог, другие
подписи — и показывает, что изменится; у правил с разбором в коде песочницы нет, только трасса.
Ни то ни другое ничего не меняет:
- находки не пишутся в каталог сборки, протокол не собирается, решения инспектора не трогаются;
- правила прода в файлах остаются как есть: вариант живёт только в памяти прогона.

Решение повторяет рабочий прогон. Голос страницы весит тем больше, чем больше параметров очереди
на ней нашлось (`collect`, `reconcile`), поэтому кандидаты собираются по всей очереди — из кеша,
как у воркера, — а решается одно правило. У варианта плотность страниц та же, только вклад
испытуемого правила заменён вкладом варианта.

Кандидаты варианта считаются без кеша. В кеше документа держится `RULE_VARIANTS` последних
вариантов правила, и три пробных прогона вытеснили бы оттуда рабочий: следующая обработка
объекта разбирала бы правило заново.
"""
import collections
import copy
import math
import re
import time

# Как правило находит значение — тип на странице правил и граница песочницы.
# «Паттерн» — вид без своей ветки разбора в `matrix_rules.extract` (значение ищут подписи правила,
# общий разбор числа) и виды, чья ветка только читает шаблоны из файла правила: признаки, шапку и
# строку ведомости, словарь классов. «Код» — свой разбор в конвейере. «LLM» — значение с чертежей
# читает модель по вопросу из правила. Сверка со списком веток — tests/test_rule_test.py
PATTERN_KINDS = frozenset({None, "area", "volume", "count", "length", "height", "elevation", "percent", "flow",
                           "power", "heat", "class", "feature_presence", "schedule_sum", "schedule_positions",
                           "item_height"})
LLM_KINDS = frozenset({"vlm_value", "door_opening"})

# Числа сравнения, которые песочница меняет у паттерна и правила с моделью: порог, порог Матрицы, допуск
NUMERIC = ("threshold", "trigger", "tolerance", "tolerance_pct")
MAX_PATTERNS = 40
MAX_PATTERN_LEN = 400
CANDIDATES_PER_STAGE = 60
EXCLUDED_MAX = 40
EVIDENCE_MAX = 6
STAGES = ("PD", "RD", "ID")


def engine(rule):
    """Тип правила: pattern, code или llm; None — машинного правила нет."""
    if not isinstance(rule, dict):
        return None
    if rule.get("vlm") or rule.get("kind") in LLM_KINDS:
        return "llm"
    return "pattern" if rule.get("kind") in PATTERN_KINDS else "code"


def editable(rule):
    """Поля правила, которые песочница может поменять: у паттерна — ещё его шаблоны.

    Правило с разбором в коде в песочнице не прогоняется совсем, даже с порогом: логика у него в коде,
    а код в песочнице не меняют. Как оно решило на объекте, показывает трасса.
    """
    kind = engine(rule)
    if kind in (None, "code"):
        return set()
    fields = {"compare"} if isinstance(rule.get("compare"), dict) else set()
    if kind == "pattern":
        fields |= {k for k in ("labels", "exclude") if isinstance(rule.get(k), list)}
        if rule.get("kind") == "feature_presence" and isinstance(rule.get("features"), list):
            fields.add("features")
    return fields


class VariantError(ValueError):
    """Вариант правила нельзя прогнать: поле не меняется у такого правила или значение неверное."""


def _pattern(value, where):
    if not isinstance(value, str) or not value.strip():
        raise VariantError(f"{where}: нужна непустая строка")
    if len(value) > MAX_PATTERN_LEN:
        raise VariantError(f"{where}: не длиннее {MAX_PATTERN_LEN} знаков")
    try:
        re.compile(value, re.I)
    except re.error as error:
        raise VariantError(f"{where}: выражение не разбирается ({error})") from None
    return value


def _patterns(values, key):
    if not isinstance(values, list) or len(values) > MAX_PATTERNS:
        raise VariantError(f"{key}: нужен список до {MAX_PATTERNS} выражений")
    return [_pattern(v, f"{key}[{i}]") for i, v in enumerate(values)]


def apply_variant(rule, variant):
    """Вариант правила: поля `variant` поверх рабочего правила, только те, что песочница меняет."""
    if variant and engine(rule) == "code":
        raise VariantError("правило с разбором в коде в песочнице не прогоняется: код в песочнице не меняют")
    allowed = editable(rule)
    out = copy.deepcopy(rule)
    for key, value in (variant or {}).items():
        if key not in allowed:
            raise VariantError(f"поле «{key}» у правила типа «{engine(rule)}» в песочнице не меняется")
        if key in ("labels", "exclude"):
            out[key] = _patterns(value, key)
        elif key == "features":
            if not isinstance(value, list) or not value or len(value) > MAX_PATTERNS:
                raise VariantError(f"features: нужен список до {MAX_PATTERNS} признаков")
            out[key] = []
            for i, f in enumerate(value):
                if not isinstance(f, dict) or not isinstance(f.get("name"), str) or not f["name"].strip():
                    raise VariantError(f"features[{i}]: нужны название и выражение")
                out[key].append({"name": f["name"].strip(), "pattern": _pattern(f.get("pattern"), f"features[{i}]")})
        elif key == "compare":
            if not isinstance(value, dict):
                raise VariantError("compare: нужен объект с порогом или допуском")
            base = dict(out.get("compare") or {})
            for k, v in value.items():
                if k not in NUMERIC or k not in base:
                    raise VariantError(f"compare.{k}: меняются только порог и допуск, которые у правила уже есть")
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
                    raise VariantError(f"compare.{k}: нужно неотрицательное число")
                base[k] = v
            out["compare"] = base
    return out


def locate(code):
    """Очередь и правила, по которым параметр считается в проде: (очередь, правила очереди, черновик ли).

    Работающее правило — из очереди прода, иначе черновик из `rules/provisional` (#95): у черновиков
    своя плотность страниц, их очередь считается отдельно, как у воркера.
    """
    from pipeline import matrix_rules
    for queue, path in sorted(matrix_rules.QUEUES.items()):
        rules = matrix_rules.load_rules(path)
        rule = rules["parameters"].get(code)
        if rule and rule.get("implemented") and not rule.get("out_of_scope"):
            return queue, rules, False
    for queue in sorted(matrix_rules.QUEUES):
        rules = matrix_rules.load_provisional(queue)
        if rules and code in rules["parameters"]:
            return queue, rules, True
    raise KeyError(f"у параметра {code} нет машинного правила: прогонять нечего")


def _only(found, code):
    """Кандидаты одного правила в той же форме, что у `collect`: код -> стадия -> список."""
    out = collections.defaultdict(lambda: collections.defaultdict(list))
    for stage, cands in (found.get(code) or {}).items():
        out[code][stage] = [dict(c) for c in cands]
    return out


def _pages(found, code):
    return {(c.get("file_id"), c.get("page")) for cands in (found.get(code) or {}).values() for c in cands}


def swap_density(density, before, after):
    """Плотность страниц очереди, где вклад правила `before` (страницы с его кандидатами) заменён на `after`."""
    out = collections.Counter(density)
    for page in before - after:
        out[page] -= 1
    for page in after - before:
        out[page] += 1
    return out


def _decide(object_id, rules, code, rule, found, density, pages_read):
    from pipeline import matrix_rules
    single = dict(rules, parameters={code: rule})
    return matrix_rules.build_findings(object_id, rules=single, collected=(_only(found, code), density, pages_read))


def _text(value):
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


def compact(finding):
    """Запись без тяжёлых полей: для итога прогона и сравнения до и после."""
    extraction = finding.get("extraction") or {}
    return {
        "finding_id": finding.get("finding_id"),
        "locations": [str(x) for x in (finding.get("locations") or [])],
        "violation_label": finding.get("violation_label"),
        "finding_status": finding.get("finding_status"),
        "pd_value": _text(finding.get("pd_value")),
        "rd_value": _text(finding.get("rd_value")),
        "id_value": _text(finding.get("id_value")),
        "detail": extraction.get("detail") if isinstance(extraction.get("detail"), str) else None,
        "evidence": [{"stage": e.get("stage"), "file_id": e.get("file_id"), "page": e.get("pdf_page_number")}
                     for e in (finding.get("evidence") or [])[:EVIDENCE_MAX] if isinstance(e, dict)],
    }


NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def _numbers(text):
    return [float(m.group(0).replace(",", ".")) for m in NUMBER_RE.finditer(str(text or ""))]


def _same_value(a, b):
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= 1e-6 * max(1.0, abs(float(a)))
    except (TypeError, ValueError):
        return str(a).strip().lower() == str(b).strip().lower()


def _chosen(findings):
    """Выбранные значения стадий: {стадия: [значения]} из решений записей.

    У записи по одному значению стадии выбор лежит в `extraction`; у записей по элементам и ключам
    (KR-067: «бетон для обвязочного пояса: 47.88 м³») — только в значении записи: тогда выбранным
    считается число, которое в нём стоит.
    """
    out = collections.defaultdict(list)
    for f in findings:
        extraction = f.get("extraction") or {}
        for stage in STAGES:
            side = extraction.get(stage.lower())
            if isinstance(side, dict) and side.get("value") is not None:
                out[stage].append(side["value"])
            else:
                out[stage].extend(_numbers(f.get(f"{stage.lower()}_value")))
    return out


def _shown(findings):
    """Что показать выбранным в заголовке стадии: значение стадии, как оно стоит в записи."""
    out = collections.defaultdict(list)
    for f in findings:
        for stage in STAGES:
            value = _text(f.get(f"{stage.lower()}_value"))
            if value and value not in out[stage]:
                out[stage].append(value)
    return out


def _candidate(c, chosen):
    snippet = c.get("snippet") or c.get("label") or ""
    return {
        "document": c.get("document"),
        "file_id": c.get("file_id"),
        "page": c.get("page"),
        "value": _text(c.get("value")),
        "raw": _text(c.get("raw")),
        "label": c.get("label") if isinstance(c.get("label"), str) else None,
        "snippet": str(snippet)[:240],
        "chosen": any(_same_value(c.get("value"), v) for v in chosen),
        "recognized": c.get("text_source") == "RECOGNIZED",
    }


def trace(found, findings, code, excluded=()):
    """Что правило нашло по стадиям: кандидаты (сначала выбранные), сколько всего, что отбросили исключения."""
    chosen, shown = _chosen(findings), _shown(findings)
    excluded = list(excluded)
    stages = {}
    for stage in STAGES:
        cands = (found.get(code) or {}).get(stage) or []
        rows = sorted((_candidate(c, chosen[stage]) for c in cands),
                      key=lambda r: (not r["chosen"], r["document"] or "", r["page"] or 0))
        stages[stage] = {"total": len(cands), "documents": len({c.get("file_id") for c in cands}),
                         "chosen": shown[stage] if cands else [],
                         "candidates": rows[:CANDIDATES_PER_STAGE]}
    return {"stages": stages, "excluded": excluded[:EXCLUDED_MAX], "excluded_total": len(excluded)}


def _excluded(object_id, rules, code, rule, found):
    """Строки, которые нашла бы подпись правила, но отбросили его исключения (только у паттерна)."""
    from pipeline import matrix_rules
    drop = ("exclude", "context_exclude", "exclude_unless_header")
    if engine(rule) != "pattern" or not any(rule.get(k) for k in drop):
        return []
    relaxed = {k: v for k, v in rule.items() if k not in drop}
    loose, _, _ = matrix_rules.collect(object_id, dict(rules, parameters={code: relaxed}), use_cache=False)
    kept = {(c.get("file_id"), c.get("page"), str(c.get("raw"))) for cands in (found.get(code) or {}).values()
            for c in cands}
    out = []
    for stage in STAGES:
        for c in (loose.get(code) or {}).get(stage) or []:
            if (c.get("file_id"), c.get("page"), str(c.get("raw"))) not in kept:
                out.append(dict(_candidate(c, ()), stage=stage))
    return out


def diff(before, after):
    """Что изменилось между записями до и после: добавилась, пропала, поменялись значение или вывод."""
    keys = ("violation_label", "finding_status", "pd_value", "rd_value", "id_value")
    old = {f["finding_id"]: f for f in before}
    new = {f["finding_id"]: f for f in after}
    changes, same = [], 0
    for fid in sorted(set(old) | set(new)):
        a, b = old.get(fid), new.get(fid)
        if a is None:
            changes.append({"finding_id": fid, "change": "added", "before": None, "after": b})
        elif b is None:
            changes.append({"finding_id": fid, "change": "removed", "before": a, "after": None})
        elif any(a.get(k) != b.get(k) for k in keys):
            changes.append({"finding_id": fid, "change": "changed", "before": a, "after": b})
        else:
            same += 1
    return changes, same


def run(object_id, code, variant=None, with_trace=True):
    """Пробный прогон правила `code` на объекте `object_id`, который уже разобран (есть `documents.jsonl`).

    Без `variant` — трасса рабочего правила. С `variant` — ещё вариант и разница с рабочим правилом
    на тех же данных: так видно действие только варианта, а не того, что протокол объекта собирали
    прежним кодом. Ошибка варианта — `VariantError` до всякого разбора.
    """
    from pipeline import matrix_rules
    started = time.monotonic()
    queue, rules, draft = locate(code)
    rule = rules["parameters"][code]
    changed = apply_variant(rule, variant) if variant else None

    found, density, pages_read = matrix_rules.collect(object_id, rules)
    base, base_summary = _decide(object_id, rules, code, rule, found, density, pages_read)
    out = {"object_id": object_id, "code": code, "queue": queue, "draft": draft, "engine": engine(rule),
           "pages_read": pages_read, "base": {"findings": [compact(f) for f in base],
                                              "summary": dict(base_summary)}}
    if with_trace:
        out["trace"] = trace(found, base, code, _excluded(object_id, rules, code, rule, found))
    if changed is not None:
        tried, _, _ = matrix_rules.collect(object_id, dict(rules, parameters={code: changed}), use_cache=False)
        density2 = swap_density(density, _pages(found, code), _pages(tried, code))
        after, after_summary = _decide(object_id, rules, code, changed, tried, density2, pages_read)
        changes, same = diff(out["base"]["findings"], [compact(f) for f in after])
        out["variant"] = {"findings": [compact(f) for f in after], "summary": dict(after_summary),
                          "changes": changes, "same": same}
        if with_trace:
            out["variant"]["trace"] = trace(tried, after, code)
    out["elapsed_s"] = round(time.monotonic() - started, 1)
    return out
