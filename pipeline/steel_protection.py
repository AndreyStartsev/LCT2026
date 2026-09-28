"""Огнезащита и антикоррозионная защита стальных конструкций. KR-066, #145.

Решения специалиста по черновику (третий круг 25.09, Р-91):
- отсылка ПД к отдельному проекту огнезащиты («Огнезащиту выполняет специализированная
  организация по отдельно разработанному проекту», КР Алтуфьевского) — needs_expert с запросом
  этого проекта, а не «огнезащиты нет»;
- универсальный предел огнестойкости в правило не зашивается: предел сравнивается только тот,
  что сама ПД назвала для элемента, с тем, что назвала РД для того же элемента;
- ослабление антикоррозионной системы — нарушение: меньше слоёв или микрон, исключена эмаль.

Что считается утверждением об огнезащите стали: предложение со словом «огнезащит» и стальным
предметом (сталь, металлоконструкции, профлист, колонны, балки…). Огнезащитная пена, паста и
вкладыши кабельных проходок, изоляция воздуховодов, муфты, герметики, пропитка древесины и
строки перечня актов («Акт на устройство … огнезащитных покрытий») — другие параметры.

Антикоррозионная система — предложение о металлоконструкциях с грунтовкой, эмалью или толщиной
в микронах: «огрунтованы одним слоем грунтовки ГФ-021 … и покрыты эмалью», «грунтом ГФ-021 …
толщиной не менее 80мкм», «двумя слоями грунтовки ГФ-021 с последующим окрашиванием двумя
слоями эмали ПФ-115». Трубопроводы, воздуховоды и сварные швы сюда не относятся.
"""
import re

FIRE = re.compile(r"огнезащит\w*", re.I)
STEEL = re.compile(r"стальн|металл|профлист|профилированн\w+\s+лист|колонн|балк|ригел|ферм|прогон|связ[еиь]"
                   r"|несущ\w+\s+конструкц", re.I)
# огнезащита других предметов и строки перечней: у них свой параметр
FIRE_FOREIGN = re.compile(r"\bпен[аоыу]\b|пенн|кабел|проходк|воздуховод|муфт|герметик|вкладыш|паст[аыу]\b|трубопровод"
                          r"|клапан|древесин|деревянн|антисептир|\bакт\w*\s+на\b|двер|экран", re.I)
# перечень нормативных документов: «СТО АРСС … «Проектирование огнезащиты несущих стальных конструкций…»»
NORM_TITLE = re.compile(r"\bГОСТ\b|\bСТО\b|ВН[ПИ]Б|\bСП\s?\d|«\s*(?:Проектирование|Средства)", re.I)
PROJECT_REF = re.compile(r"отдельн\w*\s+(?:разработанн\w+\s+)?проект\w*|специализированн\w+\s+организаци\w*", re.I)
LIMIT = re.compile(r"(?<![A-Za-zА-Яа-я])(REI|R)\s?(\d{2,3})(?!\d)")
ELEMENTS = (("колонны", r"колонн"), ("балки", r"балк"), ("ригели", r"ригел"), ("связи", r"связ[еиь]"),
            ("фермы", r"ферм"), ("прогоны", r"прогон"), ("стойки", r"стоек|стойк"),
            ("профлист", r"профлист|профилированн\w+\s+лист"), ("лестницы", r"лестниц|марш"),
            ("несущие конструкции", r"несущ\w+"))

ANTICORR_SUBJECT = re.compile(r"металлоконструкц|стальн\w+\s+(?:конструкц|элемент)|металлическ\w+\s+конструкц", re.I)
ANTICORR_FOREIGN = re.compile(r"трубопровод|воздуховод|труб\b|арматур\w+\s+(?:запорн|трубопровод)", re.I)
COAT = re.compile(r"грунт\w*|эмал\w*|окраш\w*|окраск\w*|лакокрасочн\w*|мкм", re.I)
MATERIAL = re.compile(r"(?<![А-ЯЁа-яёA-Za-z])(ГФ|ПФ|ХВ|ЭП|АК|МЛ|УР|ФЛ|ХС|КО|ЭФ|ВЛ|ХП)\s?[-–]?\s?(\d{2,4})(?!\d)", re.I)
# «в 2 слоя», «двумя слоями», «одним слоем», «за 2 раза»
LAYERS = re.compile(r"(?<![\d,.])(\d|одн\w+|дв\w+|тр[её]\w+|четыр\w+)\s+(?:сло[йяеёю]\w*|раз[а]?\b)", re.I)
ROLE = re.compile(r"грунт\w*|эмал\w*", re.I)
MICRONS = re.compile(r"(?<![\d,.])(\d{2,3})\s*мкм", re.I)
WORDS = {"одн": 1, "дв": 2, "тр": 3, "четыр": 4}


def _sentences(flat):
    """Предложения страницы с позицией: точка, за которой пробел и заглавная или цифра пункта."""
    start = 0
    for m in re.finditer(r"(?<=[.;])\s+(?=[А-ЯЁA-Z0-9-])", flat):
        yield start, flat[start:m.start()]
        start = m.end()
    yield start, flat[start:]


def _element(sentence, pos, end):
    """Элемент, к которому относится предел: слово перед ним или «– для несущих» после него."""
    after = re.match(r"\s*[–—-]?\s*для\s+(\w+)", sentence[end:end + 40])
    if after:
        for name, pat in ELEMENTS:
            if re.match(pat, after.group(1), re.I):
                return name
    before = sentence[max(0, pos - 80):pos]
    best = None
    for name, pat in ELEMENTS:
        for m in re.finditer(pat, before, re.I):
            if best is None or m.start() > best[0]:
                best = (m.start(), name)
    return best[1] if best else None


def fire_statements(flat):
    """Утверждения об огнезащите стальных конструкций на странице.

    Возвращает список {kind: limit|project|mention, element, value, raw, snippet}: предел по элементу,
    отсылка к отдельному проекту огнезащиты или упоминание без предела.
    """
    out = []
    for _, s in _sentences(flat):
        if not FIRE.search(s) or FIRE_FOREIGN.search(s) or NORM_TITLE.search(s):
            continue
        snippet = " ".join(s.split())[:300]
        if PROJECT_REF.search(s):
            # отсылка к проекту огнезащиты стального слова может не иметь: «Огнезащиту выполняет
            # специализированная организация по отдельно разработанному проекту» (КР Алтуфьевского)
            out.append({"kind": "project", "element": None, "value": None, "raw": PROJECT_REF.search(s).group(0),
                        "snippet": snippet})
        if not STEEL.search(s):
            continue
        limits = []
        for m in LIMIT.finditer(s):
            element = _element(s, m.start(), m.end())
            if element:
                limits.append({"kind": "limit", "element": element, "value": int(m.group(2)),
                               "raw": f"{m.group(1)} {m.group(2)}", "snippet": snippet})
        out.extend(limits)
        if not limits:
            out.append({"kind": "mention", "element": None, "value": None, "raw": FIRE.search(s).group(0),
                        "snippet": snippet})
    return out


def _count(word):
    word = word.lower()
    if word.isdigit():
        return int(word)
    return next((n for stem, n in WORDS.items() if word.startswith(stem)), None)


def coating_systems(flat):
    """Антикоррозионные системы металлоконструкций на странице.

    Возвращает список {primer, enamel, layers: {primer, enamel}, microns, raw, snippet}. Грунтовка и
    эмаль — марки после слов «грунт…» и «эмал…»; слои — число перед «слоя» у ближайшей марки.
    """
    out = []
    for _, s in _sentences(flat):
        if not ANTICORR_SUBJECT.search(s) or ANTICORR_FOREIGN.search(s) or not COAT.search(s):
            continue
        if re.search(r"сварн\w+\s+(?:соединени|шв)", s, re.I) and not re.search(r"грунт|эмал", s, re.I):
            continue
        primer, enamel, layers = set(), set(), {}
        roles = list(ROLE.finditer(s))
        for i, m in enumerate(roles):
            role = "primer" if m.group(0).lower().startswith("грунт") else "enamel"
            # своё у слова — до следующего «грунт…»/«эмал…»: «грунтом ГФ-021 и окрашены эмалью ПФ 115
            # в два слоя» — два слоя у эмали, а не у грунта
            end = min(roles[i + 1].start() if i + 1 < len(roles) else len(s), m.end() + 60)
            own = s[m.end():end]
            mat = MATERIAL.search(own[:40])
            if mat:
                (primer if role == "primer" else enamel).add(f"{mat.group(1).upper()}-{mat.group(2)}")
            elif role == "enamel":
                enamel.add("эмаль")
            # число слоёв — перед словом («двумя слоями грунтовки») или после марки («в 2 слоя»)
            before = s[max(0, m.start() - 25):m.start()]
            got = [c for c in (_count(x.group(1)) for x in list(LAYERS.finditer(before))[-1:] + list(LAYERS.finditer(own)))
                   if c]
            if got:
                layers[role] = max(layers.get(role, 0), got[0])
        # «ПФ-115» после «окрашиванием» без слова «эмаль» — тоже эмаль
        for mat in MATERIAL.finditer(s):
            name = f"{mat.group(1).upper()}-{mat.group(2)}"
            if name.startswith("ПФ") and name not in primer:
                enamel.add(name)
        microns = max((int(m.group(1)) for m in MICRONS.finditer(s)), default=None)
        if not (primer or enamel or microns):
            continue
        if len(enamel) > 1:
            enamel.discard("эмаль")
        out.append({"primer": sorted(primer), "enamel": sorted(enamel), "layers": layers, "microns": microns,
                    "raw": show_system(primer, enamel, layers, microns), "snippet": " ".join(s.split())[:300]})
    return out


def show_system(primer, enamel, layers, microns):
    """«грунтовка ГФ-021 в 2 сл.; эмаль ПФ-115 в 2 сл.; 80 мкм»."""
    parts = []
    if primer:
        parts.append(f"грунтовка {', '.join(sorted(primer))}" + (f" в {layers['primer']} сл." if layers.get("primer") else ""))
    if enamel:
        marks = ", ".join(sorted(e for e in enamel if e != "эмаль"))
        parts.append(("эмаль " + marks).strip() + (f" в {layers['enamel']} сл." if layers.get("enamel") else ""))
    if microns:
        parts.append(f"{microns} мкм")
    return "; ".join(parts)


def limit_decreases(pd, rd):
    """Элементы, у которых предел в РД ниже проектного: [(элемент, пределы ПД, пределы РД)]."""
    out = []
    for element in sorted(set(pd) & set(rd)):
        if min(rd[element]) < max(pd[element]):
            out.append((element, sorted(pd[element]), sorted(rd[element])))
    return out


def weakenings(pd_systems, rd_systems):
    """Ослабление антикоррозионной системы РД против ПД: список причин.

    Сравнивается сильнейшее, что назвала каждая стадия: наибольшая толщина, наибольшее число
    слоёв грунтовки и эмали, есть ли эмаль вообще. Ослабление — только по тому, что названо
    в обеих стадиях: неуказанное — не нарушение (Р-91, п. 5); исключение эмали — нарушение,
    если рабочая стадия систему описала, а эмали в ней нет.
    """
    if not pd_systems or not rd_systems:
        return []
    why = []
    pd_mic = [s["microns"] for s in pd_systems if s["microns"]]
    rd_mic = [s["microns"] for s in rd_systems if s["microns"]]
    if pd_mic and rd_mic and max(rd_mic) < max(pd_mic):
        why.append(f"толщина покрытия {max(rd_mic)} мкм против {max(pd_mic)} мкм")
    for role, name in (("primer", "грунтовки"), ("enamel", "эмали")):
        pd_l = [s["layers"].get(role) for s in pd_systems if s["layers"].get(role)]
        rd_l = [s["layers"].get(role) for s in rd_systems if s["layers"].get(role)]
        if pd_l and rd_l and max(rd_l) < max(pd_l):
            why.append(f"слоёв {name} {max(rd_l)} против {max(pd_l)}")
    if any(s["enamel"] for s in pd_systems) and not any(s["enamel"] for s in rd_systems) \
            and any(s["primer"] for s in rd_systems):
        why.append("эмаль исключена: в рабочей стадии только грунтовка")
    return why
