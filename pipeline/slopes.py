"""Уклоны по плану организации рельефа: SPZU-033, черновик шестого круга.

Триггер Матрицы — «нарушение уклонов, ведущее к застою воды или превышению крутизны» — чисел не
даёт, а единый предел закладывать в правила специалист в третьем круге не советовал. Поэтому
уклоны рабочей стадии сравниваются с диапазоном, который заявила сама ПД: круче наибольшего
проектного — «превышение крутизны», положе наименьшего — «риск застоя воды».

На плане уклон подписан у стрелки вместе с длиной участка: «18‰ 17.27», «5.0‰ 64.36». Длина с двумя
знаками после точки и отличает подпись уклона от отметок. Из текста ПЗУ берётся заявленный
диапазон: «продольные уклоны по проездам составляют 5‰-15‰», «от 0,5% до 4,0 %», «максимальный
продольный уклон … составляет 28‰», «поперечный уклон принят 20‰». Проценты переводятся в
промилле. Требования («не должны быть более 4 %», «не более 20 ‰») — не проектное решение, но предел: по
решению специалиста шестого круга уклоны РД сравниваются и с нормами, на которые ссылается ПД. Требование
в тексте ПД — предел нормы (ключ с `NORM_MAX` или диапазон с `NORM_RANGE`); ссылка ПД на СП 59.13330.2020 даёт
пределы п. 5.1.7 для путей МГН: продольный не более 40‰ (климатический район II — Москва), поперечный 10–20‰.
Пределы нормы берутся только из ПД: требование в РД — не проектное решение рабочей стадии.
"""
import re

# «нарушения нет» в записи: чем рабочая стадия сошлась с проектом
SAME = "в пределах проекта"

LONG, CROSS = "продольные уклоны", "поперечные уклоны"
# уклоны путей МГН — отдельный ключ: «продольный уклон пути движения не превышает 4%» на разбивочном чертеже
# путей МГН — предел для пешехода, его нельзя сравнивать с уклоном проезда на плане организации рельефа
MGN = re.compile(r"пут\w*\s+движени|пешеход|МГН|инвалид|колясо?к|маломобил", re.I)
PLAN = re.compile(r"(?<![\d.,\-])(?P<v>\d{1,3}(?:[.,]\d)?)\s*‰\s+(?P<len>\d{1,3}[.,]\d{2})(?!\d)")
_NUM = r"\d+(?:[.,]\d+)?"
TEXT = re.compile(r"(?P<kind>продольн|поперечн)\w*\s+уклон\w*(?P<ctx>[^.;]{0,80}?)"
                  rf"(?:(?:от\s+)?(?P<a>{_NUM})\s*(?P<ua>‰|%)?\s*(?:[-–]|до)\s*(?P<b>{_NUM})\s*(?P<ub>‰|%)"
                  rf"|(?:составля\w+|не\s+превыша\w+|принят\w*|равн\w+)\s+(?P<c>{_NUM})\s*(?P<uc>‰|%)"
                  r"(?!\s*(?:[-–]|до)\s*\d))", re.I)
REQUIREMENT = re.compile(r"должн\w*|следует|не\s+более|допуска\w+|СП\s?\d|норм\w*", re.I)
# требование с числом: «продольный уклон … не должен превышать 5 %», «поперечный уклон должен составлять от 10 до 20‰»
REQ_TEXT = re.compile(r"(?P<kind>продольн|поперечн)\w*\s+уклон\w*(?P<ctx>[^.;]{0,80}?)"
                      r"(?:не\s+должн\w+\s+(?:быть\s+)?(?:более|превыша\w+)|должн\w+\s+(?:составлять|быть)(?:\s+не\s+более)?"
                      r"|не\s+более|следует\s+принимать(?:\s+не\s+более)?|допуска\w+(?:\s+не\s+более)?)\s+(?:от\s+)?"
                      rf"(?P<a>{_NUM})\s*(?P<ua>‰|%)?(?:\s*(?:[-–]|до)\s*(?P<b>{_NUM})\s*(?P<ub>‰|%))?", re.I)
NORM_MAX, NORM_RANGE = " · предел нормы", " · диапазон нормы"
SP59 = re.compile(r"[СC]П\s*59\.13330\.2020")
# уклон пути, а не рельефа участка: пандус, лестница, кровля, лоток, трубопровод
FOREIGN = re.compile(r"пандус|лестниц|кровл|лотк|трубопровод|канализац|отмостк|площадк\w*\s+(?:высадки|отдыха)|"
                     r"высадк|входн\w+\s+площадк", re.I)


def _permille(raw, unit):
    v = float(raw.replace(",", "."))
    return v * 10 if unit == "%" else v


def slopes(flat):
    """Уклоны на странице: [{key, value, raw, source, snippet}], value — в промилле."""
    out = []
    for m in PLAN.finditer(flat):
        v = float(m.group("v").replace(",", "."))
        if 0 < v <= 200:
            out.append({"key": LONG, "value": v, "raw": f"{m.group('v')}‰", "source": "plan",
                        "snippet": " ".join(flat[max(0, m.start() - 60):m.end() + 60].split())})
    for m in REQ_TEXT.finditer(flat):
        if FOREIGN.search(flat[max(0, m.start() - 60):m.end()]):
            continue
        key = LONG if m.group("kind").lower().startswith("продольн") else CROSS
        if MGN.search(m.group(0)):
            key += " путей МГН"
        if m.group("b"):
            unit = m.group("ub")
            pairs, key = [(m.group("a"), m.group("ua") or unit), (m.group("b"), unit)], key + NORM_RANGE
        elif m.group("ua"):
            pairs, key = [(m.group("a"), m.group("ua"))], key + NORM_MAX
        else:
            continue
        for raw, unit in pairs:
            v = _permille(raw, unit)
            if 0 < v <= 200:
                out.append({"key": key, "value": v, "raw": f"{raw}{unit}", "source": "norm", "norm": True,
                            "snippet": " ".join(flat[max(0, m.start() - 40):m.end() + 40].split())})
    if SP59.search(flat):
        snippet = " ".join(flat[max(0, SP59.search(flat).start() - 40):SP59.search(flat).end() + 80].split())
        for key, v, raw in ((LONG + " путей МГН" + NORM_MAX, 40.0, "СП 59.13330.2020 п. 5.1.7: не более 40‰"),
                            (CROSS + " путей МГН" + NORM_RANGE, 10.0, "СП 59.13330.2020 п. 5.1.7: 10–20‰"),
                            (CROSS + " путей МГН" + NORM_RANGE, 20.0, "СП 59.13330.2020 п. 5.1.7: 10–20‰")):
            out.append({"key": key, "value": v, "raw": raw, "source": "norm", "norm": True, "snippet": snippet})
    for m in TEXT.finditer(flat):
        around = flat[max(0, m.start() - 60):m.end()]
        if REQUIREMENT.search(m.group(0)) or FOREIGN.search(around):
            continue
        key = LONG if m.group("kind").lower().startswith("продольн") else CROSS
        if MGN.search(m.group(0)):
            key += " путей МГН"
        if m.group("c"):
            pairs = [(m.group("c"), m.group("uc"))]
        else:
            ub = m.group("ub")
            pairs = [(m.group("a"), m.group("ua") or ub), (m.group("b"), ub)]
        for raw, unit in pairs:
            v = _permille(raw, unit)
            if 0 < v <= 200:
                out.append({"key": key, "value": v, "raw": f"{raw}{unit}", "source": "text",
                            "snippet": " ".join(flat[max(0, m.start() - 40):m.end() + 40].split())})
    return out


def _base(key):
    for suffix in (NORM_MAX, NORM_RANGE):
        if key.endswith(suffix):
            return key[:-len(suffix)], suffix
    return key, None


def compare_pairs(pd, rd):
    """Пары ключей: одинаковый вид уклона и предел нормы из ПД против того же вида в РД."""
    out = []
    for k in sorted(pd):
        base, suffix = _base(k)
        if base in rd and (suffix or k == base):
            out.append((k, base))
    return out


def changes(pd, rd):
    """Уклоны рабочей стадии вне проектного диапазона или предела нормы: [(ключ, проект, рабочая, почему)]."""
    out = []
    for kp, kr in compare_pairs(pd, rd):
        p, r = pd[kp], rd[kr]
        suffix = _base(kp)[1]
        where = "проектного" if suffix is None else "по норме, на которую ссылается проект,"
        why = []
        top = min(p) if suffix == NORM_MAX else max(p)
        if max(r) > top + 1e-9:
            why.append(f"круче наибольшего {where}: {max(r):g}‰ > {top:g}‰")
        if suffix != NORM_MAX and min(r) < min(p) - 1e-9:
            why.append(f"положе наименьшего {where}: {min(r):g}‰ < {min(p):g}‰ (риск застоя воды)")
        if why:
            out.append((kr if kp == kr else f"{kr} ({suffix.strip(' ·')})", p, r, "; ".join(why)))
    return out


def show(key, values):
    values = sorted(values)
    return f"{values[0]:g}–{values[-1]:g}‰ ({len(values)} знач.)" if len(values) > 1 else f"{values[0]:g}‰"
