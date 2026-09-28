"""Решения специалиста по видам гипотез (#114, #129, Р-86, Р-108, Р-116).

Специалист по проектированию разбирает гипотезы на странице проверки и решает о виде гипотезы —
коде свободного поиска и, если нужно, стороне (`aspect`): у «рабочая документация не обновлена
после корректировки проекта» подтверждены площади (пищеблок ДОО), а по категориям помещений данных
не хватило. Решения лежат данными в `rules/specialist_guidance.json`: следующий круг проверки меняет
файл, а не код.

Решения:
- «нарушение» (`violation`, `submit`): вид идёт в файл сдачи и отмечается так же, как гипотеза,
  которую инспектор взял в кандидаты (#63), — `promoted_at` и `promoted_by`;
- «нужны данные» (`need_info`) и «гипотеза» (`hypothesis`): записи вида — гипотезы с пометкой;
- «низкий приоритет» (`drop`): специалист предложил такие записи не показывать, а пользователь
  26.09 решил показывать их в конце таблицы гипотез с низкой уверенностью.

В файл сдачи решение по виду вмешивается только данными: `submit: true` пускает вид туда,
`hold: true` снимает — запись остаётся гипотезой, и в сдачу её отправит только решение инспектора
(#63). `submit: false` у вида значит «не подтверждён», сдачу он не трогает.

Снят «элемент проекта не найден в РД» разделов КР, АР и ЭОМ (Р-155, решение пользователя 28.09):
в 7 из 8 проверенных записей элемент в РД был под другим названием или в пакете не было тома
нужного раздела. Остальные решения сдачу не трогают, записи вида идут туда, как их собрал разбор.
У Тюменской-5 организатор считает нарушением тёплые полы, найденные тем же поиском в разделе ОВ
(TRAIN-0002…0005), и перевод вида ОВ в «не в сдачу» стоил четырёх эталонных точек (Р-108).

Решений по отдельной записи нет (Р-116). Они узнавали запись открытого корпуса по объекту и
значению, поэтому на новом объекте не срабатывали ни разу, а на открытом подменяли работу правила
готовым ответом. Причины, названные в них специалистом, переносятся в правила.

Пометка — слово решения и одна-две фразы по существу. Её видно значком на экране проверки и в
конце пояснения записи. `confidence_low` вида — довод против вывода из того, что специалист нашёл в
записях вида («в 3 из 8 проверенных записей элемент в РД назван иначе»); он идёт в
`extraction.confidence.low`, уровень записи считает API (`service/api/src/confidence.ts`). Решение
и уверенность не смешиваются: довод — о том, как найдено расхождение, решение — отдельной пометкой.

«Гипотеза» и «низкий приоритет» касаются записей о расхождении: запись «нарушения нет» того же вида
(профиль распорной системы не изменился) остаётся как есть.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "rules", "specialist_guidance.json")
# слово решения — то же, что на значке экрана проверки (service/web/src/labels.ts)
VERDICT = {"violation": "нарушение", "need_info": "нужны данные", "no_violation": "не нарушение",
           "hypothesis": "гипотеза", "drop": "низкий приоритет"}
SECTION = {"AR": "АР", "OV": "ОВ", "VK": "ВК", "EOM": "ЭОМ", "SS": "СС", "KR": "КР", "GP": "ГП",
           "POS": "ПОС", "PB": "ПБ", "OTHER": "других разделов"}
# решения, которые касаются только записей о расхождении
DISCREPANCY_ONLY = ("hypothesis", "drop")

PROMOTED_BY = "specialist-guidance"   # не пользователь стенда: вид гипотезы взят в кандидаты решением специалиста
# причина для отчёта о сдаче у вида, снятого со сдачи (`hold: true`, Р-155)
HELD = ("элемент проекта, не найденный в РД этого раздела, чаще назван в РД иначе или относится к тому, "
        "которого в пакете нет: в сдачу только решением инспектора")

_cache = {}


def guidance(path=PATH):
    """Решения: ({(код, сторона или None): вид}, дата разбора, отметка времени)."""
    if path not in _cache:
        data = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"kinds": []}
        kinds = {(k["code"], k.get("aspect")): k for k in data.get("kinds") or []}
        _cache[path] = (kinds, data.get("reviewed"), data.get("reviewed_at"))
    return _cache[path]


def _kind(finding, kinds):
    code = finding.get("parameter_code")
    return kinds.get((code, finding.get("aspect"))) or kinds.get((code, None))


def _notes(k, f, section_of):
    """Фразы пометки: общая по виду и, если нужно, про эту запись — откуда взята сторона РД."""
    notes = [k["note"]] if k.get("note") else []
    if k.get("not_ar") and section_of:
        rd = sorted({section_of(e.get("file_id")) or "?" for e in f.get("evidence") or []
                     if e.get("stage") == "RD"})
        if rd and "AR" not in rd:
            named = [SECTION.get(x, x) for x in rd if x != "OTHER"]
            label = ", ".join(named) + (" и других разделов" if "OTHER" in rd and named else
                                        "других разделов" if "OTHER" in rd else "")
            notes.append(k["not_ar"].format(sections=label))
    if k.get("unnamed"):
        pd = str(f.get("pd_value") or "")
        name = next((n for n in k.get("unnamed_names") or [] if n.lower() in pd.lower()), None)
        if name:
            notes.append(k["unnamed"].format(name=name))
    return notes


def apply(findings, section_of=None, path=PATH):
    """Отметить записи решениями специалиста по виду. Возвращает (записи, сводка); записи не убираются.

    section_of(file_id) → раздел документа по реестру (`AR`, `OV`…): площадь помещения, взятая
    рабочей стадией не из тома АР, по словам специалиста справочная — это сказано в пометке.
    """
    kinds, reviewed, reviewed_at = guidance(path)
    summary = {"в сдачу": 0, "гипотезой": 0}
    for f in findings:
        k = _kind(f, kinds)
        if not k or (k["verdict"] in DISCREPANCY_ONLY and f.get("violation_label") == "NO_VIOLATION"):
            continue
        when, stamp = k.get("reviewed") or reviewed, k.get("reviewed_at") or reviewed_at
        note = " ".join(_notes(k, f, section_of))
        word = VERDICT.get(k["verdict"], k["verdict"])
        f["specialist"] = {"verdict": k["verdict"], "scope": "kind", "reviewed": when, "cases": k.get("cases") or [],
                           "note": note}
        ext = f.setdefault("extraction", {})
        base = (ext.get("detail") or "").rstrip(". ")
        ext["detail"] = ((base + ". " if base else "") + f"Специалист о таких записях: {word}."
                         + (f" {note}" if note else ""))[:2400]
        if k.get("confidence_low"):
            low = ext.setdefault("confidence", {"up": [], "medium": [], "low": []}).setdefault("low", [])
            if k["confidence_low"] not in low:
                low.append(k["confidence_low"])
        if k.get("submit"):
            f["for_submission"] = True
            f["finding_status"] = "CANDIDATE"
            f.setdefault("promoted_at", stamp)
            f.setdefault("promoted_by", PROMOTED_BY)
        elif k.get("hold") and f.get("for_submission") is not False:
            f["for_submission"] = False
            f.setdefault("exclusion_reason", HELD)
            summary["снято со сдачи"] = summary.get("снято со сдачи", 0) + 1
        summary["в сдачу" if k.get("submit") else "гипотезой"] += 1
        if k["verdict"] == "drop":
            summary["вид «низкий приоритет»"] = summary.get("вид «низкий приоритет»", 0) + 1
    return findings, summary
