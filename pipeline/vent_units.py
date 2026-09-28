"""Установки общеобменной вентиляции: какие есть в стадии, с каким расходом и где стоят. Задача #37.

## Что читается

**Заданные величины установки.** В перечне оборудования и в листах подбора у системы стоят
расход и давление: «П17 (L=9060 м3/ч, Pc=350 Па)», «В2.3,В2.4 (L=170 м3/ч, Pc=200 Па)». Строка
лежит в текстовом слое обеих стадий, обозначение в ней чистое. Системы противодымной вентиляции
(«ВД», «ПД», «ДУ») сюда не входят: их сверяет третья очередь, `pipeline/smoke_fans.py`.

**Помещение установки.** Таблица систем называет обслуживаемое помещение, а не то, где стоит
агрегат. Место видно на проектных схемах: марка «П17» нарисована внутри венткамеры, рядом
с подписью «012 Венткамера». Берётся ближайший к марке номер помещения на листе, расстояние —
в миллиметрах листа, а не в долях страницы: листы тома разного формата. Если марка есть
на нескольких листах, помещение выбирается большинством листов.

Привязка по ближайшему номеру годится для схемы, где установка стоит в помещении. Поэтому она
используется только как адрес находки и всегда помечается как требующая проверки человеком.
"""
import collections
import math
import re

MM = 72 / 25.4
SMOKE = re.compile(r"^(?:ВД|ДВ|ДУ|ПД|ДП|КДВ)\d")
SYSTEM = r"[А-Я]{1,3}\d{1,2}(?:\.\d{1,2})?(?:\(\d\))?"
LISTED = re.compile(rf"(?<![\w.-])({SYSTEM}(?:,\s?{SYSTEM})*)\s*\(\s*L\s?=\s?(\d{{2,6}})\s*м[3³]/ч\s*,?\s*"
                    rf"Pc\s?=\s?(\d{{1,4}})\s*Па\s*\)")
ROOM = re.compile(r"^\d{2,4}(?:\.\d{1,2})?$")
MAX_ROOM_MM = 90.0        # дальше этого номер помещения к марке установки не относится
MIN_SHEET_PT = 1000


def unit_duties(flat):
    """Установки страницы с заданными расходом и давлением: [{unit, flow, pressure, snippet}]."""
    out = []
    for m in LISTED.finditer(flat or ""):
        for unit in m.group(1).replace(" ", "").split(","):
            if SMOKE.match(unit):
                continue
            out.append({"unit": unit, "flow": int(m.group(2)), "pressure": int(m.group(3)),
                        "snippet": " ".join(flat[max(0, m.start() - 30):m.end() + 30].split())})
    return out


def family(unit):
    """«П17.1» и «П17.2» — той же установки «П17»: основа обозначения без подномера."""
    return unit.split(".")[0]


def nearest_rooms(words, width_pt, height_pt, units):
    """Ближайший номер помещения к каждой марке установки на листе.

    words — слова листа в пунктах видимой страницы [(x0, y0, x1, y1, текст)].
    Возвращает {установка: (номер помещения, расстояние в мм, прямоугольник марки в долях листа)}.
    """
    rooms = [(w, ((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)) for w in words if ROOM.match(w[4].strip(" ,;"))]
    out = {}
    for w in words:
        mark = w[4].strip(" ,;")
        if mark not in units or not rooms:
            continue
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        room, distance = min(((r[4].strip(" ,;"), math.hypot(rx - cx, ry - cy)) for r, (rx, ry) in rooms),
                             key=lambda x: x[1])
        distance_mm = distance / MM
        if distance_mm <= MAX_ROOM_MM and (mark not in out or distance_mm < out[mark][1]):
            box = [round(v, 5) for v in (w[0] / width_pt, w[1] / height_pt, w[2] / width_pt, w[3] / height_pt)]
            out[mark] = (room, round(distance_mm, 1), box)
    return out


def vote_room(sightings):
    """Помещение установки по листам: [(лист, помещение, расстояние)] → (помещение, листы) или (None, [])."""
    if not sightings:
        return None, []
    # «012.1 Форкамера» и «012 Венткамера» — одно место: голос отдаётся основному номеру
    base = collections.Counter(room.split(".")[0] for _, room, _ in sightings)
    room = max(base, key=lambda r: (base[r], -min(d for _, x, d in sightings if x.split(".")[0] == r)))
    return room, [s for s in sightings if s[1].split(".")[0] == room]
