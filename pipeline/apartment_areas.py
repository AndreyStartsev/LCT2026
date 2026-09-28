"""Площади квартир между стадиями по штампам квартир на планах АР. Задача #100.

На планах этажей АР у каждой квартиры стоит штамп: жилая площадь, общая, общая с летними
помещениями и тип квартиры. В текстовом слое штамп идёт четырьмя словами подряд:
«13,52 41,23 43,04 1.2.3», «21,34 31,31 34,06 Ст.1.1.1» (Полярная 16). Разбор экспликаций (#46)
такие штампы не видит: это не таблица.

Кандидат организатора POL16-V01: «в одинаковых квартирах изменены значения жилой/общей площади
и площади с летними помещениями», ПД АР1 против РД АР2 изм. 5. Одинаковые квартиры — одна
геометрия, поэтому квартиры стадий сопоставляются по типу и общей площади: у квартиры типа 1.2.1
общей площадью 37,47 м² в ПД площадь с летними 39,23 м², в РД — 40,99. Приставка «Ст.» (студия)
при сопоставлении снимается: на Полярной 16 студия Ст.1.1.1 общей площадью 31,31 м² в РД стала
квартирой 1.1.1 с жилой 15,64 м² вместо 21,34, и это тоже изменение. Квартира с другой общей
площадью — другая геометрия, и это не то расхождение: такие квартиры не сравниваются.

Берутся только листы АР. Штампы квартир стоят и на планах инженерных разделов как подложка, а
подложка отстаёт от действующей редакции АР: на Полярной 16 так у ИОС1.1, ИОС2.1, КР1 и сетей
связи. Заменённые редакции в сравнение не идут. Если цепочка редакций требует уточнения, берётся
её последняя редакция по номеру изменения: у Полярной 16 цепочку АР2 держат два файла изм. 5
(ВП и ОП), а изм. 2 и изм. 4 — прежние.

Площади в штампе записаны до сотых, поэтому «то же значение» — равенство до сотых.

Гипотезы помечены `for_submission: false`, как экспликации (#56): в сдачу они не идут, пока
инспектор не взял их в кандидаты. Этот вид специалист подтвердил нарушением 24.09, и
`pipeline/specialist.py` пускает его в сдачу (Р-86).

Записи разделены по стороне (`aspect`, пятый круг специалиста 26.09, Р-109): площадь с летними
помещениями и жилая площадь. Решения по ним разные. Площадь с летними у Полярной 16 выросла из-за
лоджий, учтённых целиком, — это подтверждённое нарушение (A1-loggia). Жилая площадь студий
уменьшилась при тех же помещениях: зону кухни 5,70 м² рабочая стадия перестала считать жилой.
Специалист: «это гипотеза скорее (может быть нарушением) — должен решить эксперт», а жилую площадь
сравнивать — «важный параметр».
"""
import collections
import re

STAMP = re.compile(r"(?<![\d,.])(\d{1,3},\d{2})\s+(\d{1,3},\d{2})\s+(\d{1,3},\d{2})\s+((?:Ст\.?\s?)?\d\.\d\.\d)(?![\d.])")
STUDIO = re.compile(r"^Ст\.?\s?")
REVISION = re.compile(r"(\d+)")
MAX_SINGLE = 5               # больше квартир с расхождением — одна запись на объект, а не на квартиру
MAX_EVIDENCE = 3
CODE, RESULT = "FREE-AR-FLAT-AREA", "VALUE_MISMATCH"
# сторона записи: (название для решения специалиста, ключ в finding_id, место в строке штампа,
# слово в значении, что изменено — для перечня)
ASPECTS = (("площадь с летними", "SUMMER", 2, "с летними", "площадь с летними помещениями"),
           ("жилая площадь", "LIVING", 1, "жилая", "жилая площадь"))
TITLE = "Площади одинаковых квартир в рабочей документации отличаются от проектных"
CRITICALITY = "Существенное (предписание) — требует утверждения"


def stamps(text):
    """Штампы квартир страницы: [(тип, жилая, общая, с летними)].

    Берутся только согласованные тройки — жилая меньше общей, общая не больше площади
    с летними: так числа размеров и отметок, случайно вставшие перед номером типа, отсеиваются.
    """
    out = []
    for m in STAMP.finditer(text or ""):
        living, total, summer = (round(float(x.replace(",", ".")), 2) for x in m.groups()[:3])
        if living < total <= summer:
            out.append((re.sub(r"\s+", "", m.group(4)), living, total, summer))
    return out


def base_type(kind):
    """Тип квартиры без приставки студии: «Ст.1.1.1» и «1.1.1» — одна квартира."""
    return STUDIO.sub("", kind)


def current_files(docs, chains=()):
    """Файлы действующих редакций: без заменённых и без копий по SHA-256.

    В цепочке «требует уточнения» остаётся последняя редакция по номеру изменения; если номера
    не читаются, остаются все файлы цепочки — выбирать между ними не на чем.
    """
    keep = {d["file_id"] for d in docs if not d.get("duplicate_of") and d.get("revision_status") != "SUPERSEDED"}
    for ch in chains:
        if ch.get("status") != "CLARIFICATION_REQUIRED":
            continue
        numbers = {}
        for f in ch.get("members") or []:
            m = REVISION.search(str(((ch.get("member_detail") or {}).get(f) or {}).get("revision") or ""))
            if m:
                numbers[f] = int(m.group(1))
        if numbers and len(numbers) == len(ch.get("members") or []):
            top = max(numbers.values())
            keep -= {f for f, n in numbers.items() if n < top}
    return keep


def compare(object_id, pages):
    """Гипотезы по штампам квартир. pages — [(стадия, файл, страница, текст)] листов АР
    действующих редакций. Возвращает (записи, сводка)."""
    by_stage = {"PD": collections.defaultdict(list), "RD": collections.defaultdict(list)}
    counts = collections.Counter()
    for stage, fid, page, text in pages:
        if stage not in by_stage:
            continue
        for kind, living, total, summer in stamps(text):
            by_stage[stage][(base_type(kind), total)].append((kind, living, summer, fid, page))
            counts[stage] += 1
    common = set(by_stage["PD"]) & set(by_stage["RD"])
    summary = {"штампов в проекте": counts["PD"], "штампов в рабочей стадии": counts["RD"],
               "квартир (тип и общая площадь) в проекте": len(by_stage["PD"]),
               "в рабочей стадии": len(by_stage["RD"]), "в обеих": len(common), "изменено": 0}
    found = []
    for key in sorted(common, key=lambda k: ([int(x) for x in k[0].split(".")], k[1])):
        pd_rows, rd_rows = by_stage["PD"][key], by_stage["RD"][key]
        pd_pairs = {(living, summer) for _, living, summer, _, _ in pd_rows}
        pd_kinds = {kind for kind, *_ in pd_rows}
        changed = [r for r in rd_rows if (r[1], r[2]) not in pd_pairs]
        if not changed:
            continue
        found.append({"type": key[0], "total": key[1],
                      "pd": sorted({(kind, living, summer) for kind, living, summer, _, _ in pd_rows}),
                      "rd": sorted({(kind, living, summer) for kind, living, summer, _, _ in changed}),
                      "renamed": sorted({kind for kind, *_ in changed} - pd_kinds),
                      "pd_pages": _pages(pd_rows), "rd_pages": _pages(changed)})
    summary["изменено"] = len(found)
    out = []
    # по стороне отдельно: у площади с летними и у жилой площади разные решения специалиста (Р-109)
    for aspect in ASPECTS:
        items = [x for x in (_aspect_item(it, aspect) for it in found) if x]
        summary[aspect[0]] = len(items)
        if len(items) > MAX_SINGLE:
            out.append(_grouped(object_id, aspect, items))
        else:
            out += [_single(object_id, aspect, it) for it in items]
    return out, summary


def _aspect_item(it, aspect):
    """Квартира с изменённой площадью этой стороны: строки РД, где значение не такое, как в проекте."""
    index = aspect[2]
    pd_values = {row[index] for row in it["pd"]}
    rd = [row for row in it["rd"] if row[index] not in pd_values]
    return dict(it, rd=rd) if rd else None


def _pages(rows):
    """Страницы с наибольшим числом штампов этой квартиры: [(файл, страница)]."""
    count = collections.Counter((fid, page) for *_, fid, page in rows)
    return [p for p, _ in sorted(count.items(), key=lambda x: (-x[1], x[0]))]


def _area(x):
    return f"{x:.2f}".replace(".", ",")


def _describe(it, aspect):
    index, word = aspect[2], aspect[3]
    pd = "; ".join(f"{row[0]}: {word} {_area(row[index])}" for row in it["pd"])
    rd = "; ".join(f"{row[0]}: {word} {_area(row[index])}" for row in it["rd"])
    note = f"; тип в РД записан как {', '.join(it['renamed'])}" if it["renamed"] else ""
    return (f"квартира типа {it['type']} общей площадью {_area(it['total'])} м²: в проекте {pd}; "
            f"в рабочей документации {rd}{note}")


def _evidence(stage, pages, quote):
    return [{"stage": stage, "file_id": fid, "pdf_page_number": page, "quote": quote, "localization": "PAGE_LEVEL"}
            for fid, page in pages]


def _record(object_id, aspect, locations, pd_value, rd_value, detail, evidence):
    return {
        "finding_id": f"{object_id}::FREE::FLAT_AREA::{aspect[1]}::{'-'.join(locations)[:80]}",
        "object_id": object_id,
        "matrix_scope": "FREE_SEARCH",
        "parameter_code": CODE,
        "aspect": aspect[0],
        "parameter_id": None,
        "title": TITLE,
        "comparison_result": RESULT,
        "location_type": "ROOM",
        "locations": locations,
        "pd_value": pd_value,
        "rd_value": rd_value,
        "id_value": None,
        "violation_label": "VIOLATION_PRESENT",
        "criticality": CRITICALITY,
        "finding_status": "SUSPICION",
        "needs_expert": True,
        "for_submission": False,
        "evidence": evidence,
        "extraction": {
            "rule_basis": "штампы квартир на планах АР сверяются по типу и общей площади",
            "detail": detail,
            "source": "apartment_stamps",
        },
    }


def _location(it):
    return f"тип {it['type']}, общая {_area(it['total'])} м²"


def _single(object_id, aspect, it):
    index, word = aspect[2], aspect[3]
    rd, pd = it["rd"][0], it["pd"][0]
    evidence = (_evidence("PD", it["pd_pages"][:MAX_EVIDENCE], f"штамп квартиры {pd[0]} в проекте")
                + _evidence("RD", it["rd_pages"][:MAX_EVIDENCE], f"штамп квартиры {rd[0]} в рабочей документации"))
    return _record(object_id, aspect, [_location(it)], f"{word} {_area(pd[index])} м²",
                   f"{word} {_area(rd[index])} м²", _describe(it, aspect), evidence)


def _grouped(object_id, aspect, items):
    """Одна запись на объект: перечень квартир и страницы, где их больше всего."""
    pd_pages, rd_pages = collections.Counter(), collections.Counter()
    for it in items:
        for rank, p in enumerate(it["pd_pages"]):
            pd_pages[p] += 1 + (rank == 0)
        for rank, p in enumerate(it["rd_pages"]):
            rd_pages[p] += 1 + (rank == 0)
    top = lambda c: [p for p, _ in sorted(c.items(), key=lambda x: (-x[1], x[0]))][:MAX_EVIDENCE]
    evidence = (_evidence("PD", top(pd_pages), "штампы квартир в проекте")
                + _evidence("RD", top(rd_pages), "штампы квартир в рабочей документации"))
    head = f"{aspect[4]} изменена у {len(items)} квартир одной геометрии"
    detail = head + ": " + " | ".join(_describe(it, aspect) for it in items)
    return _record(object_id, aspect, [_location(it) for it in items], head, "см. пояснение", detail[:2000], evidence)
