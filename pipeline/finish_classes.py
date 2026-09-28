"""Класс пожарной опасности отделки на путях эвакуации (КМ0…КМ5). PPM-107, #145.

ПД задаёт требование по виду пути эвакуации и поверхности. Бывает двумя формами:
- таблица классов по виду пути (АР Речникова): «Вестибюли, лестничные клетки, лифтовые холлы |
  Общие коридоры, холлы, фойе | … Ф 1.3 … КМ0 КМ1 КМ1 КМ2» — стены и потолки вестибюлей и
  коридоров, затем полы вестибюлей и коридоров;
- перечень в записке: «класс КМ1 - для отделки стен, потолков … в вестибюлях, лестничных клетках».

РД называет класс либо общими указаниями по виду помещения («показатели пожарной опасности не
ниже: - лестничные клетки - КМ0 (НГ); - тех. помещения … - КМ1», АР0 Полярной 16), либо у марки
в ведомости отделки («Пт-2 … Класс пожарной опасности не более КМ2», АР0 Речникова).

Решения специалиста по черновику (третий круг 25.09, Р-91, п. 6): марка отделки, привязанная к
помещению только через план потолков, — needs_expert; марка, стоящая и в коридорах, и в
техпомещениях, — «требует уточнения»; общих указаний без ведомости для «нарушения нет» мало.
Поэтому класс хуже проектного — гипотеза для инспектора. Кроме общих коридоров и холлов: там
специалист в четвёртом круге (R4-H11, Р-116) признал нарушением потолки Речникова Пт-1…Пт-4.1
«не более КМ2» при КМ1 проекта — класс хуже требования к общим коридорам и холлам нарушение, и у
марки, которую к помещениям привязывает только план потолков: где она стоит, сверяет инспектор.

Формулировки «не ниже КМ0», «не более КМ1», «не выше КМ1» — одно требование «не хуже». Марка
комплекта «КМ1» (конструкции металлические), контакторы «КМ 1» в схемах ЭОМ и «кМ» — не класс.
"""
import re

GROUPS = (("вестибюли и лестничные клетки", r"вестибюл|лестничн\w*\s+клет|лифтов\w*\s+холл|тамбур"),
          ("общие коридоры и холлы", r"коридор|холл|фойе"))
# класс хуже требования к общим коридорам и холлам — нарушение (R4-H11, Р-116), к другим путям — гипотеза
CORRIDORS = GROUPS[1][0]
SURFACES = (("стены и потолки", r"стен|потол"), ("полы", r"пол(?:ов|ы|а)?\b|покрыти\w+\s+пол"))
KM = r"(?<![-/.\w])КМ\s?([0-5])(?![\d.\w-])"
# таблица ПД: заголовок вида пути, за ним ряд из четырёх классов
TABLE_HEAD = re.compile(r"Вестибюл\w*,?\s+лестничн\w+\s+клетк\w*", re.I)
FOUR = re.compile(r"КМ\s?([0-5])\s+КМ\s?([0-5])\s+КМ\s?([0-5])\s+КМ\s?([0-5])(?![\d])")
# перечень ПД: «класс КМ1 - для отделки стен, потолков … в вестибюлях, лестничных клетках…»
CLAUSE = re.compile(r"(?:класс\s+)?КМ\s?([0-5])\s*[–—-]\s*для\s+(?P<what>[^;]{5,200})", re.I)
# общие указания РД: «- лестничные клетки - КМ0 (НГ)»
GENERAL = re.compile(r"[–—-]\s*(?P<room>[а-яё][а-яё .,()\-]{3,80}?)\s*[–—-]\s*" + KM, re.I)
GENERAL_HEAD = re.compile(r"пожарн\w+\s+опасност", re.I)
# марка ведомости отделки: «Пт-2 … Класс пожарной опасности не более КМ2»
MARK = re.compile(r"(?<![\w-])((?:Пт|Ст|П|С)-\d+(?:\.\d+)?)(?![\w.])")
MARK_CLASS = re.compile(r"[Кк]ласс\w*\s+пожарной\s+опасности\s+(?:материал\w*\s+)?(?:не\s+(?:более|выше|ниже|менее)\s+)?"
                        + KM)


def _group(text):
    for name, pat in GROUPS:
        if re.search(pat, text, re.I):
            return name
    return None


def _surface(text):
    for name, pat in SURFACES:
        if re.search(pat, text, re.I):
            return name
    return None


def requirements(flat):
    """Требования ПД на странице: [{group, surface, value, raw, snippet}] (value — число класса)."""
    out = []
    for head in TABLE_HEAD.finditer(flat):
        row = FOUR.search(flat, head.end(), head.end() + 400)
        if not row:
            continue
        snippet = " ".join(flat[head.start():row.end()].split())[-300:]
        values = [int(row.group(i)) for i in range(1, 5)]
        cells = ((GROUPS[0][0], SURFACES[0][0]), (GROUPS[1][0], SURFACES[0][0]),
                 (GROUPS[0][0], SURFACES[1][0]), (GROUPS[1][0], SURFACES[1][0]))
        for (group, surface), value in zip(cells, values):
            out.append({"group": group, "surface": surface, "value": value, "raw": f"КМ{value}",
                        "form": "table", "snippet": snippet})
    for m in CLAUSE.finditer(flat):
        what = m.group("what")
        group, surface = _group(what), _surface(what)
        if not group or not surface or not re.search(r"эвакуац|вестибюл|коридор|лестничн|холл", flat[max(0, m.start() - 400):m.end()], re.I):
            continue
        out.append({"group": group, "surface": surface, "value": int(m.group(1)), "raw": f"КМ{m.group(1)}",
                    "form": "clause", "snippet": " ".join(flat[max(0, m.start() - 40):m.end()].split())[:300]})
    return out


def rd_classes(flat):
    """Классы РД на странице: общие указания по виду помещения и классы у марок ведомости.

    [{form: general|mark, group, mark, value, raw, snippet}]. У общего указания `group` — вид пути
    (или None для техпомещений); у марки — сама марка, помещения к ней текст не привязывает.
    """
    out = []
    for m in GENERAL.finditer(flat):
        if not GENERAL_HEAD.search(flat[max(0, m.start() - 300):m.start()]):
            continue
        room = " ".join(m.group("room").split())
        out.append({"form": "general", "group": _group(room), "room": room, "mark": None,
                    "value": int(m.group(2)), "raw": f"{room} — КМ{m.group(2)}",
                    "snippet": " ".join(flat[max(0, m.start() - 60):m.end() + 20].split())[:300]})
    for m in MARK_CLASS.finditer(flat):
        marks = list(MARK.finditer(flat, max(0, m.start() - 400), m.start()))
        if not marks:
            continue
        mark = marks[-1].group(1)
        out.append({"form": "mark", "group": None, "room": None, "mark": mark, "value": int(m.group(1)),
                    "raw": f"{mark} — КМ{m.group(1)}",
                    "snippet": " ".join(flat[marks[-1].start():m.end()].split())[-300:]})
    return out


def strictest(reqs):
    """Строжайшее требование ПД по (вид пути, поверхность): {(group, surface): класс}."""
    out = {}
    for r in reqs:
        key = (r["group"], r["surface"])
        out[key] = min(out.get(key, 9), r["value"])
    return out


def worse(rd, need):
    """Утверждения РД, чей класс хуже проектного требования. [(утверждение РД, требование ПД, ключ)].

    Общее указание сравнивается с требованием к стенам и потолкам того же вида пути: указание АР0
    дано «для декоративно-отделочных материалов стен и потолков». Марка без помещения — с самым
    мягким требованием к стенам и потолкам: где она стоит, текст не говорит, и хуже проектного
    она наверняка только тогда, когда хуже любого пути. Марка между требованиями (КМ1 при КМ0
    у вестибюлей и КМ1 у коридоров) — `between`: это «требует уточнения», а не гипотеза.
    """
    out, between = [], []
    walls = {g: v for (g, s), v in need.items() if s == SURFACES[0][0]}
    for c in rd:
        if c["form"] == "general" and c["group"] in walls and c["value"] > walls[c["group"]]:
            out.append((c, walls[c["group"]], c["group"]))
        elif c["form"] == "mark" and walls:
            group = max(walls, key=walls.get)
            if c["value"] > walls[group]:
                out.append((c, walls[group], group))
            elif c["value"] > min(walls.values()):
                between.append(c)
    return out, between
