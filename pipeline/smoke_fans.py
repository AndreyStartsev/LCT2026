"""Вентиляторы противодымной вентиляции по системам: расход и давление. Третья очередь Матрицы, #27.

В ОВ Тюменской-5 обе стадии называют системы одинаково: «ВД1» — дымоудаление, «ПД1» — подпор
воздуха и компенсация. В перечне оборудования и в ведомости стоимости у системы стоят заданные
расход и давление: «ВД1 (L=13000 м3/ч, Pc=500 Па)». Номер системы — ключ сравнения, как номер
группы у схем ВРУ.

В рабочей стадии к каждой системе есть ещё лист подбора вентилятора: «Проект: ПД1 KSP 45-2,2х30
Данные Заданные Расчетные Производительность 8600 м3/ч 7830м3/ч Статическое давление 500 Па
414 Па». С проектом сравниваются заданные величины: это то, что стадия требует от системы.
Расчётная точка — то, что даёт выбранный вентилятор на сети. С проектом она не сравнивается,
но если она ниже заданной, это выносится в пояснение записи.

На схеме ПД Алтуфьевского у пары систем записан только расход: «ДВ1,ПД1 Lв=30100м3/ч
Lпр=24000м3/ч». Давления у такой записи нет, и оно не сравнивается.
"""
import re

SYSTEM = r"(?:ВД|ДВ|ДУ|ПД|ДП|КДВ)\d{1,2}(?:\.\d{1,2})?(?:\(\d\))?"
LISTED = re.compile(rf"(?<![\w.-])({SYSTEM}(?:,\s?{SYSTEM})*)\s*\(\s*L\s?=\s?(\d{{3,6}})\s*м[3³]/ч\s*,?\s*Pc\s?=\s?(\d{{2,4}})\s*Па\s*\)")
SELECTION = re.compile(rf"Проект:\s*({SYSTEM}(?:,\s?{SYSTEM})*)\s.{{0,80}}?Производительность\s+(\d{{3,6}})\s*м[3³]/ч\s+"
                       rf"(\d{{3,6}})\s*м[3³]/ч\s+Статическое давление\s+(\d{{2,4}})\s*Па\s+(\d{{2,4}})\s*Па")
SCHEME = re.compile(r"(?<![\w.-])((?:ДВ|ВД)\d{1,2}),\s?((?:ПД|ДП)\d{1,2})\s+Lв\s?=\s?(\d{3,6})\s?м[3³]/ч\s+"
                    r"Lпр\s?=\s?(\d{3,6})\s?м[3³]/ч")


def label(flow, pressure):
    return f"L={flow} м³/ч" + (f", Pc={pressure} Па" if pressure else "")


def _systems(text):
    return [s.strip() for s in text.split(",")]


def fan_duties(flat):
    """Заданные расход и давление систем на странице; у листа подбора — ещё и расчётная точка."""
    out = []
    for m in LISTED.finditer(flat):
        for system in _systems(m.group(1)):
            out.append({"system": system, "flow": int(m.group(2)), "pressure": int(m.group(3)), "calc": None,
                        "snippet": " ".join(flat[max(0, m.start() - 40):m.end() + 40].split())})
    for m in SELECTION.finditer(flat):
        for system in _systems(m.group(1)):
            out.append({"system": system, "flow": int(m.group(2)), "pressure": int(m.group(4)),
                        "calc": (int(m.group(3)), int(m.group(5))),
                        "snippet": " ".join(flat[m.start():m.end() + 20].split())})
    for m in SCHEME.finditer(flat):
        snippet = " ".join(flat[max(0, m.start() - 20):m.end() + 20].split())
        for system, flow in ((m.group(1), m.group(3)), (m.group(2), m.group(4))):
            out.append({"system": system, "flow": int(flow), "pressure": None, "calc": None, "snippet": snippet})
    for d in out:
        d["raw"] = label(d["flow"], d["pressure"])
    return out


def reductions(pd, rd):
    """Системы, у которых в РД заданы расход или давление меньше проектного наибольшего.

    pd, rd: система → набор (расход, давление). Возвращает [(система, значения ПД, значения РД, причины)].
    """
    out = []
    for system in sorted(set(pd) & set(rd), key=_key):
        flows = [f for f, _ in pd[system]]
        pressures = [p for _, p in pd[system] if p]
        why = []
        for flow, pressure in sorted(rd[system] - pd[system], key=lambda v: (v[0], v[1] or 0)):
            if flow < max(flows):
                why.append(f"расход {max(flows)} → {flow} м³/ч")
            if pressure and pressures and pressure < max(pressures):
                why.append(f"давление {max(pressures)} → {pressure} Па")
        if why:
            out.append((system, [label(*v) for v in sorted(pd[system], key=lambda v: (v[0], v[1] or 0))],
                        [label(*v) for v in sorted(rd[system], key=lambda v: (v[0], v[1] or 0))], why))
    return out


def below_duty(cands):
    """Листы подбора, где расчётная точка вентилятора ниже заданной: [(система, заданное, расчётное)].

    Сначала системы с наибольшей недостачей расхода.
    """
    seen = {}
    for c in cands:
        if c.get("calc"):
            flow, pressure = c["value"]
            calc_flow, calc_pressure = c["calc"]
            if calc_flow < flow or calc_pressure < (pressure or 0):
                seen[c["key"]] = ((flow, pressure), (calc_flow, calc_pressure))
    return [(k, *seen[k]) for k in sorted(seen, key=lambda k: ((seen[k][1][0] - seen[k][0][0]) / seen[k][0][0], _key(k)))]


def _key(system):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", system)]
