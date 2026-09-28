"""Протокол проверки объекта: покрытие Матрицы, статусы комплектности и изменения версии. Задача #30.

Файл сдачи (`pipeline/submission.py`) — то, что уходит организатору на подсчёт балла.
Протокол — документ для инспектора по образцу Приложения 2 к ТЗ («Протокол
автоматизированной сверки» в существенной редакции ТЗ): статус загрузки, тип проверки,
сводка по 132 параметрам, пять таблиц и карточки доказательств. Здесь считается та его
часть, которая не зависит от решений инспектора: что проверено, что нет и почему,
и что изменилось с прошлой версии. Решения добавляет API в момент выгрузки.

## Статусы комплектности (ТЗ, 9.2)

- COMPLETE — сопоставимые значения найдены в обеих стадиях, сравнение выполнено.
- MISSING_EVIDENCE — нет обязательного документа или доказательного фрагмента: стадия
  не загружена или значение в ней не найдено. Нарушением не является. Если стадии в процессе
  нет вовсе, запись в файле сдачи получает метку MISSING_DOCUMENT и статус протокола
  PD_MISSING или RD_MISSING из перечня организатора (contracts/enums.json).
- NOT_COMPARABLE — значения есть, но сопоставить их корректно нельзя: взяты не из
  раздела-источника и расходятся, в рабочей стадии появилось значение другой части здания.
  Сюда же попадает конфликт редакций (#10, ТЗ 9.1): порядок редакций документа не определён,
  а значения в них расходятся. У такой записи `finding_status = CLARIFICATION_REQUIRED`,
  в сервисе она ждёт решения инспектора наравне с кандидатами: назвать актуальную редакцию
  на экране файлов и пересобрать протокол либо оставить «требует уточнения».
- NOT_CHECKED — правило для параметра не реализовано. Статуса в ТЗ нет; без него
  непроверенные параметры выглядели бы проверенными, поэтому он выводится явно.
- OUT_OF_SCOPE — параметр по документам не проверяется, и правило для него не пишется:
  событие стадии строительства во внешней системе (АИС «ОСИГ», ГЛОНАСС, КПТС, реестр ГРОО —
  OOS-098…101) или отказ по замеру (AR-050: ведомостей отделки в проектной стадии нет). Признак
  и причина — `out_of_scope` в файле правил; на дашборде это своя клетка с причиной.
- HYPOTHESIS — правила прода нет, параметр проверяет черновик правила (#95, Р-89): черновик
  ждёт решения специалиста, его нарушения идут в протокол гипотезами и в сдачу — только решением
  инспектора. Реализованным параметр не считается; в `hypothesis` — что нашёл черновик.
- NOT_APPLICABLE — параметр неприменим к объекту по его проектной документации: например,
  параметры ПОД, когда сноса нет или он выполняется по отдельному проекту (#28). Причина
  с цитатой берётся из `build/<объект>/applicability_q<очередь>.jsonl`.
"""
import collections
import re

STAGE_NAMES = {"PD": "проектная документация", "RD": "рабочая документация", "ID": "исполнительная документация"}
STAGE_SHORT = {"PD": "ПД", "RD": "РД", "ID": "ИД"}

# Очереди Матрицы по плану работ: код параметра -> номер очереди
QUEUE_BY_PREFIX = {"PZ": 1, "SPZU": 1, "AR": 2, "KR": 2, "PPM": 3, "ODI": 3,
                   "POS": 4, "POD": 4, "ZU": 4, "IOS": 5, "OOS": 5, "SM": 5}
QUEUE_SECTIONS = {1: "ПЗ и СПЗУ", 2: "АР и КР", 3: "ППМ и ОДИ", 4: "ПОС, ПОД и ЗУ", 5: "ИОС, ООС и СМ"}

DECIDED_LABELS = ("VIOLATION_PRESENT", "NO_VIOLATION")
# статусы проверки применимости (pipeline/matrix_rules.applicability), при которых параметр неприменим
NOT_APPLICABLE_STATUSES = ("NOT_APPLICABLE", "SEPARATE_PROJECT")


def queue_of(code):
    prefix = re.match(r"[A-Z]+", code or "")
    return QUEUE_BY_PREFIX.get(prefix.group(0)) if prefix else None


def section_of(catalog_row):
    """«Раздел 4. КР» -> «КР»."""
    m = re.search(r"\.\s*(\S+)\s*$", catalog_row.get("pd_section") or "")
    return m.group(1) if m else (catalog_row.get("pd_section") or "")


def stages_present(upload_status):
    """Стадии, у которых принят хотя бы один файл: PD_UPLOADED и PD_PARTIAL, но не PD_MISSING."""
    out = set()
    for status in upload_status or ():
        stage, _, state = str(status).partition("_")
        if state in ("UPLOADED", "PARTIAL"):
            out.add(stage)
    return out


def _missing_sides(finding):
    return [st for st, value in (("PD", finding.get("pd_value")), ("RD", finding.get("rd_value")))
            if value in (None, "")]


def absent_stage(finding, present):
    """Стадия, которой нет в процессе, если из-за неё у записи нет значения: «PD», «RD» или None."""
    if finding.get("violation_label") in DECIDED_LABELS:
        return None
    return next((st for st in _missing_sides(finding) if st not in present), None)


def mark_absent_stage(finding, present):
    """Запись без значения из-за незагруженной стадии — «обязательный документ отсутствует».

    Правила Матрицы не знают, что загружено в процесс, и ставят COMPARISON_IMPOSSIBLE:
    значение не найдено. Если стадии нет вовсе, по перечню организатора это
    MISSING_DOCUMENT со статусом протокола PD_MISSING или RD_MISSING. Возвращает стадию или None.
    """
    stage = absent_stage(finding, present)
    if stage:
        finding["violation_label"] = "MISSING_DOCUMENT"
        finding["protocol_status"] = f"{stage}_MISSING"
    return stage


def completeness(finding, present):
    """Статус комплектности записи и причина. present — стадии, загруженные в процесс."""
    label = finding.get("violation_label")
    detail = (finding.get("extraction") or {}).get("detail")
    if label in DECIDED_LABELS:
        return "COMPLETE", None
    stage = absent_stage(finding, present)
    if stage:
        return "MISSING_EVIDENCE", f"нет {STAGE_SHORT[stage]}: {STAGE_NAMES[stage]} не загружена"
    if label == "MISSING_DOCUMENT" or _missing_sides(finding):
        return "MISSING_EVIDENCE", detail
    return "NOT_COMPARABLE", detail


def coverage(catalog, rules_by_queue, findings, present, applicability=None, provisional=None):
    """Все параметры Матрицы: реализовано ли правило, чем закончилась проверка и почему.

    catalog — строки parameter_catalog_132.jsonl, rules_by_queue — {номер очереди: правила},
    findings — находки всех очередей по объекту, applicability — строки проверки применимости,
    provisional — {код: находки черновика правила} по всем черновикам профиля, и с пустым
    списком, если черновик ничего не нашёл (#95).
    """
    not_applicable = {r["parameter_code"]: r for r in applicability or ()
                      if r.get("status") in NOT_APPLICABLE_STATUSES}
    rules = {}
    for queue, doc in rules_by_queue.items():
        for code, rule in (doc.get("parameters") or {}).items():
            rules[code] = (queue, rule)
    by_code = collections.defaultdict(list)
    for f in findings:
        by_code[f.get("parameter_code")].append(f)
    out = []
    for row in sorted(catalog, key=lambda r: r.get("parameter_id") or 0):
        code = row["parameter_code"]
        queue, rule = rules.get(code, (queue_of(code), None))
        item = {
            "parameter_id": row.get("parameter_id"),
            "parameter_code": code,
            "parameter_name": row.get("parameter_name"),
            "section": section_of(row),
            "criticality": row.get("criticality"),
            "queue": queue,
            "implemented": bool(rule and rule.get("implemented")),
            "findings": [f["finding_id"] for f in by_code.get(code, [])],
        }
        if code in not_applicable:
            item["status"] = "NOT_APPLICABLE"
            item["reason"] = not_applicable[code].get("reason")
        elif rule is not None and rule.get("out_of_scope"):
            # проверяется не по документам (внешние системы стадии строительства) или отказ по
            # замеру: правило не пишется, и на дашборде это своя клетка с причиной, а не
            # «не проверено» наравне с правилами в работе
            item["status"] = "OUT_OF_SCOPE"
            item["out_of_scope"] = rule["out_of_scope"].get("kind")
            item["reason"] = rule["out_of_scope"].get("reason")
        elif not (rule and rule.get("implemented")) and provisional is not None and code in provisional:
            # правила прода нет, но параметр проверяет черновик (#95): это гипотеза, а не проверка
            got = collections.Counter(f.get("violation_label") for f in provisional[code])
            item["status"] = "HYPOTHESIS"
            item["hypothesis"] = {"violation": got.get("VIOLATION_PRESENT", 0),
                                  "no_violation": got.get("NO_VIOLATION", 0),
                                  "not_comparable": got.get("COMPARISON_IMPOSSIBLE", 0)}
            item["findings"] = [f["finding_id"] for f in provisional[code]
                                if f.get("violation_label") == "VIOLATION_PRESENT"]
            item["reason"] = hypothesis_reason(item["hypothesis"])
        elif rule is None:
            item["status"] = "NOT_CHECKED"
            item["reason"] = f"правила очереди {queue} ({QUEUE_SECTIONS.get(queue, '—')}) не разработаны"
        elif not rule.get("implemented"):
            item["status"] = "NOT_CHECKED"
            item["reason"] = rule.get("reason") or "правило не реализовано"
            # `reason` — заметка разработки про корпус, её дашборд не показывает (#83); инспектору — пометка без
            # привязки к корпусу: что нужно правилу и чего нет в пакете, где черновик у специалиста
            if rule.get("inspector_note"):
                item["note"] = rule["inspector_note"]
        elif not by_code.get(code):
            item["status"] = "MISSING_EVIDENCE"
            item["reason"] = "значение не найдено ни в проектной, ни в рабочей стадии"
        else:
            statuses = collections.Counter(completeness(f, present)[0] for f in by_code[code])
            # у параметра по элементам записей несколько: сопоставлен, если сравнена хотя бы одна
            for status in ("COMPLETE", "NOT_COMPARABLE", "MISSING_EVIDENCE"):
                if statuses.get(status):
                    item["status"] = status
                    break
            item["reason"] = None
        # третий массив (#42): нашлось ли значение в исполнительной документации. Сравнение ПД — РД
        # её не требует (PD_RD_AVAILABLE_ID_NOT_REQUIRED_FOR_PAIRWISE_CHECK), но инспектору нужен
        # перечень параметров, по которым исполнительная документация промолчала — и почему (Д-57)
        if "ID" in (present or ()) and by_code.get(code):
            if any(f.get("id_value") for f in by_code[code]):
                item["id_status"] = "FOUND"
            else:
                item["id_status"] = "NOT_FOUND"
                item["id_reason"] = id_reason(row.get("source_id"))
        out.append(item)
    return out


def hypothesis_reason(got):
    """Что нашёл черновик правила — словами для протокола и клетки дашборда."""
    parts = [f"{what} — {got[key]}" for key, what in (("violation", "похоже на нарушение"),
                                                        ("no_violation", "расхождения нет"),
                                                        ("not_comparable", "сравнить нельзя")) if got.get(key)]
    return ("правило на проверке: " + (", ".join(parts) if parts else "значение не найдено"))


# Источники в ИД, которые появляются при вводе объекта в эксплуатацию, а не в ходе стройки:
# у строящегося объекта их нет, и молчание ИД по такому параметру — не пробел комплекта (Д-57)
COMMISSIONING_SOURCES = ("бти", "зос", "разрешение на ввод", "ввода в эксплуатацию", "ввод в эксплуатацию")


def id_reason(source_id):
    """Почему в исполнительной документации нет значения: документ ввода или пробел комплекта.

    Источник из Матрицы («Технический план БТИ; Акт выноса осей») делится по «;» и «,»;
    если все названные документы — документы ввода, значения на стройке быть не может.
    """
    parts = [p.strip().lower() for p in re.split(r"[;,]", source_id or "") if p.strip()]
    if not parts:
        return "источник в ИД для параметра в Матрице не назван"
    commissioning = [p for p in parts if any(k in p for k in COMMISSIONING_SOURCES)]
    if len(commissioning) == len(parts):
        return f"источник в ИД — документ ввода в эксплуатацию ({source_id}): у строящегося объекта его нет"
    if commissioning:
        return (f"в загруженной исполнительной документации значение не найдено; часть источников — документы "
                f"ввода в эксплуатацию ({'; '.join(commissioning)}), их у строящегося объекта нет")
    return "в загруженной исполнительной документации значение не найдено"


def _values(f):
    return (f.get("pd_value"), f.get("rd_value"), f.get("violation_label"))


def changes(previous, findings, decided_statuses=("CONFIRMED_VIOLATION", "NEGATIVE_VERIFIED", "CLARIFICATION_REQUIRED")):
    """Что изменилось по сравнению с прошлой версией протокола.

    previous — {finding_id: {pd_value, rd_value, violation_label, verification_status, origin}}
    из базы до пересборки. Решение инспектора переносится по идентификатору записи, но если
    значения записи после дозагрузки стали другими, решение относилось к прежним значениям:
    такие записи возвращаются отдельно, чтобы инспектор их пересмотрел.
    """
    current = {f["finding_id"]: f for f in findings}
    added = sorted(set(current) - set(previous))
    removed = sorted(k for k, v in previous.items()
                     if k not in current and v.get("origin") != "INSPECTOR_SPLIT")
    changed, stale = [], []
    for fid in sorted(set(current) & set(previous)):
        before = previous[fid]
        after = current[fid]
        if _values(after) != (before.get("pd_value"), before.get("rd_value"), before.get("violation_label")):
            entry = {"finding_id": fid,
                     "before": {"pd_value": before.get("pd_value"), "rd_value": before.get("rd_value"),
                                "violation_label": before.get("violation_label")},
                     "after": {"pd_value": after.get("pd_value"), "rd_value": after.get("rd_value"),
                               "violation_label": after.get("violation_label")}}
            changed.append(entry)
            if before.get("verification_status") in decided_statuses:
                stale.append(dict(entry, verification_status=before.get("verification_status")))
    return {"added": added, "removed": removed, "changed": changed, "decided_changed": stale}
