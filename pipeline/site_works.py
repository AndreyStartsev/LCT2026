"""Стройплощадка: опасные зоны кранов и ограничения у бровки котлована. POS-081 и POS-085, #145.

Рабочая стадия по каталогу — ППР, а его в корпусе нет ни у одного объекта. Специалист (третий
круг 25.09, Р-91, п. 4): стройгенплан в составе РД — рабочая сторона «для гипотезы» (POS-081);
ограничение нагрузки из РД КР вместо ППР — «нарушение, раздел в раздел, но хорошо оставить как
гипотезу» (POS-085). Поэтому расхождение здесь — всегда гипотеза для инспектора.

POS-081. Башенный кран ПОС («башенным краном Potain MDT 189 с длиной стрелы 50,0 м») против
стройгенплана РД («Башенный кран Potain MDT 189, 8 т») и радиусы опасной зоны («Опасная зона при
работе крана составит: … = 5,6 м»). Автокраны (КС-55713, Liebherr LTM) не сравниваются: их
на стройгенплане не ставят. Марки приводятся к одному написанию: у Речникова «Potain MСT 178»
набрано с кириллической «С».

POS-085. Нагрузка на бровку котлована («Ограничить нагрузку на бровку котлована до 2 тс/м²»,
«Нагрузка на бровке принята равной 20кПа») и зона без складирования у бровки («складирование
материалов не допускается в зоне 2 метров от бровки котлована»). Нагрузка приводится к кПа так,
как её пишут в самих документах: «20 кПа (2,0 т/м2)» — одна тонна-сила на метр — 10 кПа.
"""
import re

# марка: «Potain MDT 189», «Potain MD 235A», «Liebherr 132-EC-H8», «XCMG XE500EHR», «КБ-405.1»
CRANE = re.compile(r"(?<![A-Za-zА-Яа-я])(?P<m>(?P<base>(?:Potain|Liebherr|Terex|Comansa|Jaso|Zoomlion|XCMG|SANY|Yongmao)\s?"
                   r"[A-Za-zА-Яа-я]{0,4}[-‑\s]?\d{2,4})[A-Za-z]{0,4}(?:[-‑][A-Za-z0-9]{1,4})*"
                   r"|(?P<kb>КБ[-‑]?\s?\d{3}(?:\.\d)?))", re.I)
# автокраны, манипуляторы и экскаваторы: на стройгенплане их не ставят, опасную зону башенного крана
# они не задают. Liebherr серии R — гусеничный экскаватор (R954C у Полярной 16 — снос)
MOBILE = re.compile(r"LTM|КС[-‑\s]?\d|автокран|автомобильн\w+\s+кран|манипулятор|UNIC|экскаватор|Liebherr\s?R\s?\d", re.I)
ZONE = re.compile(r"(?<![а-яё])опасн\w+\s+зон\w*[^.;]{0,60}?(?:составит|составляет|принимаем|принята|равна)[^.;]{0,80}?"
                  r"(?:=\s*|:\s*)(?P<v>\d+(?:[.,]\d+)?)\s*м(?![а-яё²2])"
                  r"|принимаем\s+величину\s+опасной\s+зоны\s*:?\s*(?P<v2>\d+(?:[.,]\d+)?)\s*м(?![а-яё²2])", re.I)
EDGE_LOAD = re.compile(r"нагрузк\w*[^.;]{0,100}?бровк\w*[^.;]{0,60}?(?<![\d,.])(?P<v>\d+(?:[.,]\d+)?)\s*"
                       r"(?P<u>кПа|т[сc]?\s*/\s*м\s?[2²])", re.I)
EDGE_ZONE = re.compile(r"(?:складировани\w*|проезд\w*)[^.;]{0,80}?не\s+допуска\w+\s+в\s+зоне\s+(?P<v>\d+(?:[.,]\d+)?)\s*"
                       r"(?:м|метр\w*)(?![а-яё²])[^.;]{0,20}?от\s+бровк", re.I)

CRANE_KEY = "башенный кран"
ZONE_KEY = "радиус опасной зоны крана"
LOAD_KEY = "нагрузка на бровку котлована"
EDGE_KEY = "зона без складирования у бровки"
_LOOKALIKE = str.maketrans("АВСЕНКМОРТХасеорх", "ABCEHKMOPTXaceopx")


def _num(raw):
    return float(raw.replace(",", "."))


def crane_model(raw):
    """Одно написание марки: латиница, без пробелов и дефисов, заглавные — «POTAINMCT178»."""
    return re.sub(r"[\s\-‑]", "", raw.translate(_LOOKALIKE)).upper()


def _snippet(flat, m, before=60, after=60):
    return " ".join(flat[max(0, m.start() - before):m.end() + after].split())


def cranes(flat):
    """Башенные краны и радиусы опасной зоны на странице: [{key, value, raw, snippet}]."""
    out = []
    for m in CRANE.finditer(flat):
        near = flat[max(0, m.start() - 40):m.end() + 5]
        if MOBILE.search(near) or MOBILE.search(m.group("m")):
            continue
        raw = " ".join(m.group("m").split())
        # сравнивается основа марки — производитель, серия и число; хвост «-EC-H8» пишут не везде
        base = m.group("base") or m.group("kb")
        out.append({"key": CRANE_KEY, "value": crane_model(base), "raw": raw, "snippet": _snippet(flat, m)})
    for m in ZONE.finditer(flat):
        raw = m.group("v") or m.group("v2")
        value = _num(raw)
        if 1 <= value <= 150:
            out.append({"key": ZONE_KEY, "value": value, "raw": f"{raw} м", "snippet": _snippet(flat, m, 80, 20)})
    return out


def edge_limits(flat):
    """Ограничения у бровки котлована: нагрузка (кПа) и зона без складирования (м)."""
    out = []
    for m in EDGE_LOAD.finditer(flat):
        value = _num(m.group("v"))
        kpa = value * 10 if m.group("u").lower().startswith("т") else value
        if 1 <= kpa <= 200:
            out.append({"key": LOAD_KEY, "value": round(kpa, 1), "raw": f"{m.group('v')} {m.group('u')}",
                        "snippet": _snippet(flat, m, 30, 40)})
    for m in EDGE_ZONE.finditer(flat):
        value = _num(m.group("v"))
        if 0.3 <= value <= 30:
            out.append({"key": EDGE_KEY, "value": value, "raw": f"{m.group('v')} м", "snippet": _snippet(flat, m, 20, 30)})
    return out


def crane_changes(pd, rd):
    """Расхождения кранов: другой кран в РД, радиус опасной зоны больше проектного. [(ключ, ПД, РД, почему)]."""
    out = []
    if pd.get(CRANE_KEY) and rd.get(CRANE_KEY) and rd[CRANE_KEY] - pd[CRANE_KEY]:
        out.append((CRANE_KEY, sorted(pd[CRANE_KEY]), sorted(rd[CRANE_KEY]), "в рабочей стадии другой кран"))
    if pd.get(ZONE_KEY) and rd.get(ZONE_KEY) and max(rd[ZONE_KEY]) > max(pd[ZONE_KEY]) + 1e-9:
        out.append((ZONE_KEY, sorted(pd[ZONE_KEY]), sorted(rd[ZONE_KEY]), "опасная зона больше проектной"))
    return out


def edge_changes(pd, rd):
    """Ослабление у бровки: нагрузка больше проектной, зона без складирования меньше. [(ключ, ПД, РД, почему)]."""
    out = []
    if pd.get(LOAD_KEY) and rd.get(LOAD_KEY) and max(rd[LOAD_KEY]) > max(pd[LOAD_KEY]) + 1e-9:
        out.append((LOAD_KEY, sorted(pd[LOAD_KEY]), sorted(rd[LOAD_KEY]), "допустимая нагрузка больше проектной"))
    if pd.get(EDGE_KEY) and rd.get(EDGE_KEY) and min(rd[EDGE_KEY]) < min(pd[EDGE_KEY]) - 1e-9:
        out.append((EDGE_KEY, sorted(pd[EDGE_KEY]), sorted(rd[EDGE_KEY]), "зона без складирования меньше проектной"))
    return out


def show(key, values):
    if all(isinstance(v, str) for v in values):
        return ", ".join(sorted(values))
    unit = " кПа" if key == LOAD_KEY else " м"
    return ", ".join(f"{v:g}".replace(".", ",") for v in sorted(values)) + unit


# ---------- снос и технология возведения: POD-090, POD-091, POS-087 ----------

COLLAPSE = re.compile(r"зон\w*\s+(?:возможного\s+)?развал\w*[^.;]{0,120}?(?<![\d,.])(?P<v>\d+(?:[.,]\d+)?)\s*м(?![а-яё²2])"
                      r"|опасн\w+\s+зон\w*\s*\(\s*зон\w*\s+развал\w*\s*\)[^.;]{0,40}?(?<![\d,.])(?P<v2>\d+(?:[.,]\d+)?)\s*м(?![а-яё²2])",
                      re.I)
# «Высота зоны развала сносимых зданий высотой 7м» (Алтуфьевское): число — высота здания
COLLAPSE_FOREIGN = re.compile(r"высот\w+\s+зон\w*\s+развал", re.I)
COLLAPSE_KEY = "зона развала"

# метод сноса: техника сводится к методу — смена навесного оборудования при том же механизированном
# методе не нарушение (специалист, POD-091)
METHODS = (("механизированный", r"механизированн\w*[^.;]{0,30}?(?:метод|способ|снос|демонтаж|разборк)"
                                r"|(?:метод|способ)\w*[^.;]{0,20}?механизированн"
                                r"|навесн\w+\s+(?:разрушающ\w+\s+)?оборудовани|гидромолот|гидроножниц"),
           ("ручной", r"ручн\w+\s+(?:\w+\s+)?(?:метод|способ|разборк|демонтаж)|(?:и|,)\s+ручн\w+\s+метод"),
           ("поэлементный", r"поэлементн\w+\s+(?:разборк|демонтаж|снос)"),
           ("обрушение", r"(?:методом|способом)\s+обрушени"),
           ("взрывной", r"взрывн\w+\s+(?:метод|способ)|методом\s+взрыв"))
METHODS_KEY = "методы сноса"

# технологии несущих конструкций по группам: замена внутри группы — критическая (специалист, POS-087)
TECHNOLOGIES = (("крепление котлована", "шпунт", r"шпунт\w*"),
                ("крепление котлована", "стена в грунте", r"стен\w*\s+в\s+грунте"),
                ("крепление котлована", "буросекущие сваи", r"буросекущ\w+\s+сва"),
                ("крепление котлована", "распорная система", r"распорн\w+\s+систем"),
                # «сверху вниз» без «top-down» не берётся: так пишут и порядок демонтажа, и бетонирование
                ("порядок возведения", "сверху вниз (top-down)", r"top[-\s]?down|полузакрыт\w+\s+способ"),
                ("каркас", "монолитный железобетон", r"монолитн\w+\s+(?:железобетон|ж/?б)"),
                ("каркас", "сборный железобетон", r"сборн\w+\s+(?:железобетон|ж/?б)"))


def collapse_zones(flat):
    """Размер зоны развала при сносе, м: [{key, value, raw, snippet}]."""
    out = []
    for m in COLLAPSE.finditer(flat):
        if COLLAPSE_FOREIGN.search(flat[max(0, m.start() - 20):m.end()]):
            continue
        raw = m.group("v") or m.group("v2")
        value = _num(raw)
        if 1 <= value <= 100:
            out.append({"key": COLLAPSE_KEY, "value": value, "raw": f"{raw} м", "snippet": _snippet(flat, m, 20, 20)})
    return out


def demolition_methods(flat):
    """Методы сноса, названные на странице: [{key, value: метод, raw, snippet}]."""
    out = []
    for name, pat in METHODS:
        m = re.search(pat, flat, re.I)
        if m:
            out.append({"key": METHODS_KEY, "value": name, "raw": name, "snippet": _snippet(flat, m, 60, 60)})
    return out


def technologies(flat):
    """Технологии несущих конструкций на странице: [{key: группа, value: технология, raw, snippet}]."""
    out = []
    for group, name, pat in TECHNOLOGIES:
        m = re.search(pat, flat, re.I)
        if m:
            out.append({"key": group, "value": name, "raw": name, "snippet": _snippet(flat, m, 60, 60)})
    return out


def collapse_changes(pd, rd):
    if pd.get(COLLAPSE_KEY) and rd.get(COLLAPSE_KEY) and max(rd[COLLAPSE_KEY]) > max(pd[COLLAPSE_KEY]) + 1e-9:
        return [(COLLAPSE_KEY, sorted(pd[COLLAPSE_KEY]), sorted(rd[COLLAPSE_KEY]), "зона развала больше проектной")]
    return []


def method_changes(pd, rd):
    """Метод рабочей стадии, которого нет в проекте: обрушение вместо разборки, взрыв."""
    extra = (rd.get(METHODS_KEY) or set()) - (pd.get(METHODS_KEY) or set())
    if pd.get(METHODS_KEY) and extra:
        return [(METHODS_KEY, sorted(pd[METHODS_KEY]), sorted(rd[METHODS_KEY]),
                 "метод, которого нет в проекте: " + ", ".join(sorted(extra)))]
    return []


def technology_changes(pd, rd):
    """Замена технологии в группе: проектной в РД нет, а вместо неё названа другая."""
    out = []
    for group in sorted(set(pd) & set(rd)):
        gone, came = pd[group] - rd[group], rd[group] - pd[group]
        if gone and came:
            out.append((group, sorted(pd[group]), sorted(rd[group]),
                        f"{', '.join(sorted(gone))} → {', '.join(sorted(came))}"))
    return out
