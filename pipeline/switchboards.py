"""Групповые схемы ВРУ: номиналы автоматов и кабели по группам. Пятая очередь Матрицы, #29.

Однолинейные схемы вводно-распределительных устройств Речникова есть и в проекте
(ИОС1.1), и в рабочей документации (ЭМ), и в текстовом слое это одна и та же таблица:
номер группы «1РП1-10», расчётные величины, автомат «QF10 ВА47-100 C 10 А», кабель
«ВВГнг(А)-LS 3x2,5». Номер группы по ключу схемы — номер ВРУ, панель и отходящая
линия, он одинаков в обеих стадиях. По нему строки и сравниваются.

## Подвох порядка текста

Автомат в текстовом слое идёт сразу после расчётных величин своей группы, а кабель
может оказаться и до номера группы, и после автомата — в начале следующей строки.
Поэтому номинал автомата берётся первым после номера группы, а кабели — набором
в окне от номера группы до следующего номера. Окна у одинаковых схем одинаковы, и
замена кабеля в РД видна в окне той группы, где она напечатана; пояснение записи
называет окно, а не утверждает, что это кабель именно этой группы.

Группы панели противопожарных устройств пишутся с названием секции: «1РП5.СПЗ-16». Пока их
номер не узнавался, строки СПЗ попадали в окно соседней обычной группы, а сами группы СПЗ
не сравнивались. Другие обозначения групп («ЩР1-3», «ГРЩ-1 QF3») не разбираются.
"""
import re

GROUP = re.compile(r"(?<![\w.])(\d{1,2}РП\d{1,2}(?:\.(?:\d{1,2}|СПЗ))?-\d{1,3})(?![\w])")
BREAKER = re.compile(
    r"\bQFD?\d{1,3}\s+([А-ЯA-Z]{2,5}[\w-]*(?:\s\d{2,3}(?=\s))?)\s+(?:\d[РрPp]\s+)?([BCD])?\s?(\d{1,4})\s?А\b")
CABLE = re.compile(
    r"\b(А?(?:ВВГ|ППГ|ВБШв|ПвБШв|КППГ|ПуГВ|ПвПу|КВВГ)[\wа-яА-Я()]*(?:-[A-ZА-Я]{2,4})*)\s+"
    r"(\d{1,2}\s?\(\s?\d\s?[хx×]\s?\d{1,3}(?:[,.]\d)?\s?\)(?:\s?\+\s?\d\s?[хx×]\s?\d{1,3}(?:[,.]\d)?)?"
    r"|\d{1,2}\s?[хx×]\s?\d{1,3}(?:[,.]\d)?)")
FIRE_RESISTANT = re.compile(r"FR(?:LS|HF)", re.I)
WINDOW = 260          # окно после последней группы страницы


def breaker_label(model, char, current):
    return f"{model} {char + ' ' if char else ''}{current} А"


def cable_spec(mark, size):
    """«ВВГнг(А)-LS» и «4(1x70)+1х35» → марка, число жил, сечение фазной жилы."""
    size = re.sub(r"\s", "", size).replace("х", "x").replace("×", "x")
    m = re.match(r"(\d{1,2})\((\d)x(\d{1,3}(?:[,.]\d)?)\)", size) or re.match(r"(\d{1,2})x(\d{1,3}(?:[,.]\d)?)", size)
    if m and len(m.groups()) == 3:
        cores, section = int(m.group(1)) * int(m.group(2)), float(m.group(3).replace(",", "."))
    elif m:
        cores, section = int(m.group(1)), float(m.group(2).replace(",", "."))
    else:
        cores, section = None, None
    return {"mark": mark, "size": size, "cores": cores, "section": section,
            "fire": bool(FIRE_RESISTANT.search(mark)), "raw": f"{mark} {size}"}


def group_rows(flat):
    """Строки групповой схемы на странице: номер группы, первый автомат после него, кабели окна."""
    marks = list(GROUP.finditer(flat))
    rows = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else min(len(flat), m.end() + WINDOW)
        window = flat[m.end():end]
        b = BREAKER.search(window[:180])
        breaker = None
        if b:
            model, char, current = b.group(1), b.group(2), int(b.group(3))
            breaker = {"model": model, "char": char, "current": current, "raw": breaker_label(model, char, current)}
        cables = [cable_spec(c.group(1), c.group(2)) for c in CABLE.finditer(window)]
        rows.append({"group": m.group(1), "breaker": breaker, "cables": cables,
                     "snippet": " ".join((m.group(1) + window[:170]).split())})
    return rows


# ---------- сравнение ----------

def breaker_changes(pd, rd):
    """Группы, у которых номинал автомата в РД другой. pd, rd: группа → набор подписей автоматов."""
    out = []
    for group in sorted(set(pd) & set(rd), key=_group_key):
        if pd[group] and rd[group] and pd[group] != rd[group]:
            out.append((group, sorted(pd[group]), sorted(rd[group])))
    return out


def cable_changes(pd, rd):
    """Замены кабелей по окнам групп: огнестойкий на обычный и уменьшение сечения.

    pd, rd: группа → {подпись: спецификация}. Кабель, который в РД просто добавился,
    не нарушение: на листах РД рядом с номером группы встречаются и контрольные кабели.
    """
    out = []
    for group in sorted(set(pd) & set(rd), key=_group_key):
        p, r = pd[group], rd[group]
        if not p or not r or set(p) <= set(r):
            continue
        lost = [p[k] for k in sorted(set(p) - set(r))]
        reasons = []
        if any(c["fire"] for c in lost) and not any(c["fire"] for c in r.values()):
            reasons.append("огнестойкий кабель в РД не указан")
        for c in lost:
            same = [x for x in r.values() if x["cores"] == c["cores"] and x["section"] is not None
                    and c["section"] is not None and _family(x["mark"]) == _family(c["mark"])]
            if same and max(x["section"] for x in same) < c["section"]:
                reasons.append(f"сечение {c['raw']} уменьшено до {max(same, key=lambda x: x['section'])['raw']}")
        if reasons:
            out.append((group, sorted(p), sorted(r), reasons))
    return out


def fire_lines(keyed):
    """Группы, в окне которых есть огнестойкий кабель. keyed: группа → {подпись: спецификация}."""
    return {group for group, cables in keyed.items() if any(c["fire"] for c in cables.values())}


def fire_cable_losses(pd, rd):
    """Линии с огнестойким кабелем в ПД, у которых в окне группы РД огнестойкого кабеля нет. PPM-109.

    Пустое окно РД не замена: в нём нет текста, а не кабеля. Сечение здесь не сравнивается,
    это делает `cable_changes` для IOS1-069.
    """
    out = []
    for group in sorted(fire_lines(pd) & set(rd), key=_group_key):
        if rd[group] and group not in fire_lines(rd):
            out.append((group, sorted(k for k, c in pd[group].items() if c["fire"]), sorted(rd[group])))
    return out


def _family(mark):
    """Марка без исполнения по горючести: «ВВГнг(А)-FRLS» и «ВВГнг(А)-LS» — одна жила сравнения."""
    return re.sub(r"-?(?:FR)?(?:LS|HF|LTx)$", "", mark, flags=re.I)


def _group_key(group):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", group)]
