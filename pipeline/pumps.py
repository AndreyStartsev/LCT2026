"""Повысительные насосные установки хоз-питьевого водоснабжения: расход и напор. IOS2-073, #135.

Правило дал специалист по проектированию (второй круг, 24.09): «Везде сравнивать паспортную
производительность насосных установок. Занижение — нарушение, как по расходу, так и по напору.
Завышение в пределах 20 % — не нарушение».

Установка записана строкой с расходом и напором, в ПЗ ИОС2, в указаниях ВК и в перечне оборудования:
«повысительная насосная установка COR-4 MVL 1206/SKw-LC-EB-R … (Q = 33,3 м3/ч; Н = 63,1 м»,
«Марка насосной установки Aikon PBS 3 CDM10-5 FCC. Рабочая точка: Q=15.98 м3/час Н= 44,36м».
Расход бывает в л/с («Q=8,569 л/с») — приводится к м³/ч.

Что сравнивается:
- **ключ** — установка и зона водоснабжения («зона 1»); у одной зоны в стадии несколько установок —
  они разводятся по модели;
- **точка** — рабочая или паспортная, если она записана («Рабочая точка», «Рабочие параметры»),
  иначе расчётная из ПЗ. Паспортная сильнее: её и велел сравнивать специалист;
- **итог** — расход или напор в РД ниже ПД больше чем на округление — нарушение; выше не больше
  чем на 20 % — нарушения нет; выше больше чем на 20 % — нарушения нет, но это сказано в пояснении.

Станции пожаротушения и канализационные установки в параметр не входят: IOS2-073 — «насосные
станции хоз-питьевого водоснабжения». На Речникове у станции пожаротушения в указаниях ВК1 записаны
те же Q и Н, что у повысительной установки, но это другой параметр.
"""
import re

EXCESS = 0.20          # завышение до стольких долей — не нарушение (специалист)
ROUNDING = 0.005       # 8,569 л/с = 30,85 м³/ч: пересчёт единиц и округление не занижение

_QH = re.compile(r"Q\s*[=≈]\s*(\d+(?:[.,]\d+)?)\s*(л/с|м3/ч(?:ас)?|м³/ч(?:ас)?|m3/h|m³/h)"
                 r"(?:\s*\(\s*\d+(?:[.,]\d+)?\s*м[3³]/ч(?:ас)?\s*\))?"
                 r"[\s,;]{0,4}[HН]\s*[=≈]\s*(\d+(?:[.,]\d+)?)\s*м(?![\w³3])", re.I)
_INSTALL = re.compile(r"(?:насосн\w*|повысительн\w*|повышени\w*\s+давлени\w*)"
                      r"[^.;]{0,40}?(?:установк|станци)\w*|(?:установк|станци)\w*\s+повышени\w*\s+давлени\w*", re.I)
# не хоз-питьевые: пожаротушение, канализация, дренаж, отопление и теплоснабжение, подпитка
_OTHER = re.compile(r"пожар|спринкл|дренчер|канализац|\bКНС\b|дренаж|стоков|циркуляц|подпит|отоплени|теплоснабж|"
                    r"\bИТП\b|теплов\w+\s+пункт|жокей", re.I)
# признак хоз-питьевого водоснабжения рядом с установкой: без него строка «Насосная установка:
# ВНУпж 2 IR 65-125B … Рабочие параметры: Q = 59,4 м3/ч» спринклерной установки Тюменской-5
# проходила бы как повысительная — слово «пожарной» у неё абзацем выше
_DOMESTIC = re.compile(r"хоз\w*|питьев|\bХВС\b|холодн\w+\s+(?:и\s+горяч\w+\s+)?вод|водоснабжени|"
                       r"повысительн|повышени\w*\s+давлени", re.I)
_WORKING = re.compile(r"рабоч\w+\s+(?:точк|параметр)|паспорт", re.I)
_GIVEN = re.compile(r"заданн\w+\s+параметр", re.I)
_ZONE = re.compile(r"зон\w*\s*(\d{1,2})\b|(\d{1,2})\s*(?:-?\s*я\s+)?зон", re.I)
_MODEL = re.compile(r"(COR-\d\s*[A-Z]{2,4}\s*\d{3,4}|PBS\s*\d\s*CDM\s*\d+-\d+|L\s*\d\s*CV\s*\d+-\d+|"
                    r"Hydro\s*\w+\s*\w*\s*\d+-\d+|CR\s*\d+-\d+)", re.I)
BACK = 320             # окно слева от расхода, где названа установка
AHEAD = 90             # модель бывает записана после напора: «…Н=44,36 м, N=2х2,2 кВт Aikon PBS 3 CDM10-5»

POINT_RANK = {"working": 0, "given": 1, "calc": 2}
POINT_WORD = {"working": "рабочая точка", "given": "заданные параметры", "calc": "точка не названа"}


def _num(s):
    return float(s.replace(",", "."))


def _flow_m3h(value, unit):
    return round(value * 3.6, 2) if unit.lower().startswith("л") else value


def installations(flat):
    """Повысительные установки на странице: [{key, zone, model, flow, head, point, raw, snippet}]."""
    out, prev_end = [], 0
    for m in _QH.finditer(flat):
        start = max(prev_end, m.start() - BACK)
        window = flat[start:m.start()]
        prev_end = m.end()
        inst = list(_INSTALL.finditer(window))
        if not inst:
            continue
        own = window[inst[-1].start():]              # от названия установки до расхода
        # предложение с названием установки: «для нужд пожаротушения предусмотрена установка CO 2 BL…»
        head = window[max(0, inst[-1].start() - 80):inst[-1].start()]
        clause = re.split(r"[.;]\s", head)[-1] + own
        if _OTHER.search(clause) or not _DOMESTIC.search(flat[max(0, m.start() - BACK):m.start()]):
            continue
        flow = _flow_m3h(_num(m.group(1)), m.group(2))
        head_m = _num(m.group(3))
        if not (0.1 <= flow <= 1000 and 2 <= head_m <= 300):
            continue
        zone_m = _ZONE.search(clause) or _ZONE.search(flat[m.end():m.end() + 40])
        zone = next((g for g in (zone_m.groups() if zone_m else ()) if g), None)
        model_m = _MODEL.search(own) or _MODEL.search(flat[m.end():m.end() + AHEAD])
        model = re.sub(r"\s+", " ", model_m.group(1)).upper() if model_m else None
        near = flat[max(start, m.start() - 80):m.start()]
        point = "working" if _WORKING.search(near) else "given" if _GIVEN.search(near) else "calc"
        key = "Повысительная установка" + (f", зона {zone}" if zone else "")
        raw = f"Q={flow:g} м³/ч, Н={head_m:g} м".replace(".", ",")
        out.append({"key": key, "zone": zone, "model": model, "flow": flow, "head": head_m, "point": point,
                    "raw": raw, "snippet": (window[inst[-1].start():] + flat[m.start():m.end()])[-300:]})
    return out


def adopt_zones(pd, rd):
    """Зона установки из другой стадии по той же модели: у Полярной 16 проект называет две
    установки без зон, рабочая стадия — «зоны 1» и «зоны 2» с теми же моделями. Кандидаты
    меняются на месте; ключ пересобирается."""
    zones = {}
    for c in pd + rd:
        if c.get("zone") and c.get("model"):
            zones.setdefault(c["model"], set()).add(c["zone"])
    for c in pd + rd:
        if not c.get("zone") and c.get("model") and len(zones.get(c["model"], ())) == 1:
            c["zone"] = next(iter(zones[c["model"]]))
            c["key"] = c["label"] = f"Повысительная установка, зона {c['zone']}"


def show(value):
    model, flow, head, point = value
    text = f"Q={flow:g} м³/ч, Н={head:g} м".replace(".", ",")
    return f"{model + ': ' if model else ''}{text} ({POINT_WORD[point]})"


def _best(values):
    """Самая сильная точка каждой модели: рабочая или паспортная, затем заданная, затем расчётная."""
    by_model = {}
    # второй ключ — само значение: точки одного ранга приходят множеством, и без него выбор
    # и порядок установок менялись от прогона к прогону (IOS2-073 Полярной 16, #145)
    for v in sorted(values, key=lambda v: (POINT_RANK[v[3]], str(v))):
        by_model.setdefault(v[0], v)
    return by_model


def _pairs(pd_values, rd_values):
    """Пары «проект — рабочая стадия» одного ключа: по модели, а у единственной установки — любые."""
    pd, rd = _best(pd_values), _best(rd_values)
    common = sorted(set(pd) & set(rd) - {None}, key=str)
    if common:
        return [(pd[m], rd[m]) for m in common]
    if len(pd) == 1 and len(rd) == 1:
        return [(next(iter(pd.values())), next(iter(rd.values())))]
    return []


def compare(pdk, rdk):
    """(занижения, завышения больше 20 %) по общим ключам: [(ключ, [ПД], [РД], почему)]."""
    lower, higher = [], []
    for key in sorted(set(pdk) & set(rdk)):
        for p, r in _pairs(pdk[key], rdk[key]):
            dq, dh = r[1] / p[1] - 1, r[2] / p[2] - 1
            why = []
            if dq < -ROUNDING:
                why.append(f"расход ниже на {-dq:.0%}")
            if dh < -ROUNDING:
                why.append(f"напор ниже на {-dh:.0%}")
            if why:
                lower.append((key, [show(p)], [show(r)], ", ".join(why)))
            elif dq > EXCESS or dh > EXCESS:
                over = [f"расход +{dq:.0%}" for _ in [0] if dq > EXCESS] + [f"напор +{dh:.0%}" for _ in [0] if dh > EXCESS]
                higher.append((key, [show(p)], [show(r)], ", ".join(over)))
    return lower, higher
