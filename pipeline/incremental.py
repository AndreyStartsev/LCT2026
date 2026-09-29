"""Что пересчитывать при дозагрузке. Задача #60.

Разъяснение организатора (`docs/meeting-qa-2026-09.md`, 29:10): «При дозагрузке файлов
система не запускает весь объект заново, а пересчитывает только те параметры, которых
коснулись новые документы».

Разбор объекта устроен по документам: страница читается, основная надпись разбирается,
экспликация разбирается, штамп редакции читается — всё это для одного документа и от
остальных не зависит. Поэтому при дозагрузке достаточно пересчитать новые документы,
а строки прежнего разбора взять как есть. Правила Матрицы устроены иначе: значение
параметра собирается со всего объекта, и там своя мерка — какие параметры новые
документы вообще затронули.

Что считается изменившимся документом: тот, которого в прошлом разборе не было, или тот,
у которого другое содержимое (SHA-256). Пропавший документ тоже меняет объект: у
параметра могли исчезнуть кандидаты, поэтому при пропаже считается всё заново. Так же —
при смене стадии или раздела документа с прошлого разбора (`restaged`): содержимое то же,
а кандидаты у параметров могли и появиться, и исчезнуть.

Полный пересчёт нужен и тогда, когда изменились сами правила или версия конвейера:
перенос прежних записей обещал бы, что они посчитаны по новым правилам, а это неправда.
"""
import collections


def changed_files(documents, previous):
    """Идентификаторы документов, которых в прошлом разборе не было или содержимое иное."""
    was = {d.get("file_id"): d.get("sha256") for d in previous or []}
    return {d["file_id"] for d in documents
            if d.get("file_id") not in was or was.get(d["file_id"]) != d.get("sha256")}


def lost_files(documents, previous):
    """Документы прошлого разбора, которых больше нет: заменены или отклонены."""
    now = {d.get("file_id") for d in documents}
    return {d["file_id"] for d in (previous or []) if d.get("file_id") not in now}


def restaged(documents, previous):
    """Документы прежнего содержимого, у которых стадия или раздел не те, что при прошлом разборе.

    Стадию и раздел правит инспектор (#39): задаёт, меняет, снимает правку, выбирает значение,
    равное угаданному по пути. Сравнивается с итогом прошлого разбора, а не с угаданным:
    ручная стадия, которая стоит с прошлого разбора, ничего не меняет, а снятая — меняет.

    В итоге прошлого разбора пустую стадию и раздел OTHER заполнил найденным разбор редакций
    (`revisions.analyse` трогает только пробелы). Текущие значения заполняются тем же найденным,
    иначе такой документ считался бы поправленным на каждом разборе: у Новослободской это
    51 документ из 126. Копии (`duplicate_of`) и файлы без разбора (без SHA-256) не сравниваются:
    их не читают ни разбор, ни правила.
    """
    was = {d["file_id"]: d for d in previous or [] if d.get("sha256") and not d.get("duplicate_of")}
    out = set()
    for d in documents:
        p = was.get(d.get("file_id"))
        if p is None or d.get("duplicate_of") or p.get("sha256") != d.get("sha256"):
            continue            # новый или заменённый документ считается и так
        stage, section = d.get("stage"), d.get("section")
        if stage in (None, "", "UNKNOWN") and p.get("stage_detected") not in (None, "UNKNOWN"):
            stage = p["stage_detected"]
        if section in (None, "", "OTHER") and p.get("section_detected") not in (None, "OTHER"):
            section = p["section_detected"]
        if (stage, section) != (p.get("stage"), p.get("section")):
            out.add(d["file_id"])
    return out


def plan(documents, previous):
    """Что пересчитывать: (пересчитывать всё, идентификаторы документов, причина).

    Причина пишется в журнал и в протокол: инспектор должен понимать, почему объект
    пересчитан целиком, а не по одному документу.
    """
    if not previous:
        return True, {d["file_id"] for d in documents}, "прошлого разбора нет"
    lost = lost_files(documents, previous)
    if lost:
        return True, {d["file_id"] for d in documents}, f"документов не стало: {len(lost)}"
    moved = restaged(documents, previous)
    if moved:
        return True, {d["file_id"] for d in documents}, f"стадия или раздел изменены, документов: {len(moved)}"
    changed = changed_files(documents, previous)
    if not changed:
        return False, set(), "новых документов нет"
    return False, changed, f"новых или изменившихся документов: {len(changed)}"


# Правила, которые читают документы сами, минуя сбор кандидатов: по ним «затронут ли
# параметр» решается не по кандидатам, а по стадии и разделу новых документов.
DIRECT_KINDS = {
    "room_systems": ("PD", "RD"),     # таблицы систем и планы проектной и рабочей стадии
    "vent_units": ("PD", "RD"),
    "resource_meters": ("RD",),       # решает по тому, какие разделы есть в рабочей стадии
}


def chain_broken(documents, changed):
    """Встал ли новый документ в цепочку редакций к прежнему.

    Такой документ делает прежние значения неактуальными у параметров, которых сам
    не упоминает: `latest_only` отбирает кандидатов по цепочке. Пересчитывать в этом
    случае нужно всё.
    """
    by_chain = collections.defaultdict(set)
    for d in documents:
        if d.get("chain_id"):
            by_chain[d["chain_id"]].add(d["file_id"])
    return any(members & changed and members - changed for members in by_chain.values())


def affected_codes(rules, touched, documents, changed):
    """Параметры очереди, которых коснулись новые документы.

    `touched` — коды, по которым новые документы дали хоть одного кандидата: это точная
    мерка, а не догадка по разделу. К ним добавляются правила, читающие документы сами.
    """
    stages = {d.get("stage") for d in documents if d["file_id"] in changed}
    stages = {"RD" if s == "RD_ID_MIXED" else s for s in stages}
    out = {code for code in rules["parameters"] if code in touched}
    for code, rule in rules["parameters"].items():
        want = DIRECT_KINDS.get(rule.get("kind"))
        if want and stages & set(want):
            out.add(code)
    return out


def keep(rows, changed):
    """Строки прошлого разбора по документам, которых дозагрузка не касалась."""
    return [r for r in (rows or []) if r.get("file_id") not in changed]


def merge(kept, fresh, key=("file_id", "pdf_page_number")):
    """Прежние и пересчитанные строки в одном порядке с полным разбором.

    Порядок важен не только для чтения глазами: реестр помещений берёт первое непустое
    наименование, и от порядка страниц зависит результат.
    """
    by_key = collections.OrderedDict()
    for row in list(kept) + list(fresh):
        by_key[tuple(row.get(k) for k in key)] = row
    return [by_key[k] for k in sorted(by_key, key=lambda t: tuple((x is None, x) for x in t))]
