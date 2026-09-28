"""Составы по слоям: дорожная одежда (SPZU-032) и кровля (AR-044). Задача #137.

Специалист во втором и третьем круге (Р-88, Р-91): изменение состава без расчётного обоснования —
нарушение, «считать должен проектировщик, а не правило». Не нарушение — тот же набор слоёв,
а толщина больше (правка AR-044). Примечание «конструкции даны с учётом нагрузки от пожарной
техники» расчётным обоснованием не считается (SPZU-032).

Состав — последовательность слоёв. У слоя вид (асфальтобетон, щебень, утеплитель, пароизоляция…),
толщина в мм, если она подписана, и текст строки. Формы записи в корпусе:
- дорожная одежда блоком «ТИП 2 (Конструкция тротуара с проездом пожарной техники)» и строками
  «материал … - 5 см» (Полярная 16, ПЗУ и ГП);
- дорожная одежда строкой заключения «Конструкция тротуаров, тип 3: бетонная плитка – 6 см; …»;
- кровля нумерованным списком «Кровля - тип I (…) … 1. Два слоя … толщ. 4,2 мм; 2. Праймер …»
  в записке ПД;
- кровля выносками разреза: слои столбиком, толщины отдельной колонкой «-10 мм | -50 мм».
  Колонка к слоям не привязывается (у Полярной 16 слоёв семь, чисел пять), поэтому у выносок
  сравнивается только набор слоёв.
"""
import re

# Вид слоя по тексту строки. Порядок важен: «керамзитобетон» — уклонообразующий слой, а не бетон,
# «пароизоляция … техноэласт» — пароизоляция, а не гидроизоляционный ковёр
KINDS = [
    ("vapor", "пароизоляция", r"пароизоляц"),
    ("separation", "разделительный слой", r"разделительн\w*\s+сло|\bп[эе]\s*-?\s*пл[её]нк|полиэтиленов\w*\s+пл[её]нк"),
    ("slope", "уклонообразующий слой", r"керамзитобетон|уклонообразующ|керамзитов\w*\s+гравий"),
    ("waterproofing", "гидроизоляционный ковёр", r"кровельн\w*\s+(?:гидроизоляционн\w*\s+)?ковр|гидроизоляционн\w*\s+ков[её]?р|"
                                                 r"гидроизоляционн\w*\s+мембран|пвх[- ]мембран|техноэласт\s+(?:пламя|эпп|экп|эмп)|"
                                                 r"^\s*-?\s*(?:верхний|нижний)\s+слой\b.*(?:пламя|эпп|экп)"),
    ("drainage", "дренажный слой", r"дренажн"),
    ("primer", "праймер", r"праймер"),
    ("screed", "стяжка", r"стяжк|цементно-песчан\w*\s+(?:р-р|раствор|смес)"),
    # «Минираловатная плита» — так в РД Речникова (АР4, покрытие лифтовых шахт)
    ("insulation", "утеплитель", r"пенополистирол|\bxps\b|мин[еи]раловатн|утеплител|базальтов\w*\s+плит|пеностекл"),
    ("paving", "плитка", r"плитк|брусчатк"),
    ("rubber", "резиновое покрытие", r"резинов\w*\s+крошк|мастерфайбер"),
    ("asphalt", "асфальтобетон", r"асфальтобетон"),
    ("concrete", "бетон основания", r"цементобетон|укатываем\w*\s+бетон|бетонн\w*\s+плит\w*\s+из|монолитн\w*\s+бетонн\w*\s+плит"),
    ("stone", "щебень", r"щеб[её]н|гравийно|щебеночн"),
    ("sand", "песок", r"\bпес(?:ок|ка|чан\w*\s+(?:основани|подготовк|подсыпк))"),
    ("geotextile", "геотекстиль", r"геотекстил|геосетк"),
    ("soil", "почвенный слой", r"почвенн\w*\s+субстрат|растительн\w*\s+грунт"),
    ("base", "несущее основание", r"плит\w*\s+покрыти|ж/б\s+плит|железобетонн\w*\s*плит"),
    # слои наружной стены (ZU-125): зазор и основание стены толщину утеплителя не несут
    ("gap", "воздушный зазор", r"воздушн\w*\s+зазор"),
    ("masonry", "кладка", r"блок\w*\s+(?:из\s+ячеист|газобетон|стенов)|газобетонн\w*\s+блок|кладк\w*|кирпич"),
    ("wall", "несущая стена", r"стена\s+монолитн|монолитн\w*\s+(?:ж/б|железобетонн\w*)\s+стен"),
]
KIND_RE = [(kind, name, re.compile(pattern, re.I)) for kind, name, pattern in KINDS]
KIND_NAME = {kind: name for kind, name, _ in KINDS}

# строки, которые слоем не являются: основание под одеждой, отметка грунтовых вод, деталь бортового камня
NOT_LAYER = re.compile(r"уровень\s+грунтов|уплотн[её]нн?\w*\s+грунт|плодородн\w*\s+грунт|естественн\w*\s+грунт|"
                       r"газон\s+сеян|цветущ\w*\s+многолетник|^\s*грунт\s*$", re.I)
CURB = re.compile(r"обмазать\s+битумом|камень\s+бортов|бортов\w*\s+камн", re.I)

THICK = re.compile(r"(?:^|\s)[-–]\s*(\d+(?:[,.]\d+)?)\s*(см|мм)\b|толщ(?:\.|иной)?\s*\(?(\d+(?:[,.]\d+)?)\)?\s*(мм|см)|"
                   r"(?<![\d.,/])(\d+(?:[,.]\d+)?)\s*(мм|см)\s*[;.]?\s*$", re.I)

# Расчётное обоснование в рабочей стадии: тогда изменение решает инспектор, а не правило.
# «С учётом нагрузки от пожарной техники» — не обоснование (специалист, SPZU-032)
JUSTIFIED = re.compile(r"расч[её]т\w*\s+(?:дорожн\w*\s+одежд|конструкци\w*\s+(?:дорожн|покрыти|кровл))|"
                       r"расч[её]тн\w*\s+обосновани|теплотехническ\w*\s+расч[её]т", re.I)


def kind_of(line):
    """Вид слоя строки или None: по первому упоминанию в строке, без пояснений в скобках.

    «(поднять на вертикальные грани на высоту утеплителя - 200мм)» — пояснение к пароизоляции,
    а не слой утеплителя; «Пароизоляция - слой техноэласта» — пароизоляция, а не ковёр.
    """
    core = re.sub(r"\([^)]*\)?", " ", line)
    if NOT_LAYER.search(core):
        return None
    found = [(m.start(), i, kind) for i, (kind, _name, pattern) in enumerate(KIND_RE) for m in [pattern.search(core)] if m]
    return min(found)[2] if found else None


def thickness(line):
    """Толщина слоя в мм из строки или None. «- 5 см» → 50, «толщ. 4,2 мм» → 4.2."""
    m = THICK.search(line)
    if not m:
        return None
    value, unit = next((m.group(i), m.group(i + 1)) for i in (1, 3, 5) if m.group(i))
    mm = float(value.replace(",", ".")) * (10 if unit.lower() == "см" else 1)
    return round(mm, 1)


def _layers(lines):
    """Слои блока: новая строка вида начинает слой, строка без вида продолжает прежний,
    толщина достаётся последнему начатому слою."""
    out = []
    split = []
    for line in lines:
        # «Тротуарная плитка 60 мм/ цементно-песчаная стяжка 30 мм» — два слоя одной строкой
        parts = [x for x in re.split(r"(?<=[мс]м)\s*/\s*", line) if x.strip()]
        split += parts if len(parts) > 1 and all(kind_of(x) for x in parts) else [line]
    for line in split:
        line = line.strip()
        if not line:
            continue
        kind = kind_of(line)
        if kind and not (out and out[-1]["kind"] == kind and out[-1]["mm"] is None and not THICK.search(line)
                         and kind == "waterproofing"):
            out.append({"kind": kind, "mm": None, "text": line})
        elif not out:
            continue
        else:
            out[-1]["text"] += " " + line
        mm = thickness(line)
        if mm is not None and out and out[-1]["mm"] is None:
            out[-1]["mm"] = mm
    return out


# ---------- дорожная одежда ----------

PAVEMENT_TYPE = re.compile(r"ТИП\s*(\d+(?:\.\d+)?)\s*\(((?:Конструкци|Покрыт)[^)]*)\)", re.I)
PAVEMENT_INLINE = re.compile(r"Конструкци\w*\s+([^,:;]{3,80}?),\s*тип\s*(\d+(?:\.\d+)?)\s*:\s*(.+?)(?=Конструкци\w*\s+[^,:;]{3,80}?,\s*тип\s*\d|\n\s*\d+\.\d+|\Z)",
                             re.I | re.S)


def _purpose(text):
    """Назначение типа без «конструкция» и лишних пробелов: по нему связываются типы стадий."""
    text = re.sub(r"\s+", " ", text or "").strip().lower()
    return re.sub(r"^(?:конструкци\w*|покрыти\w*)\s+", "", text)


def pavement(text):
    """Составы дорожной одежды на странице: [{key, purpose, layers, snippet}]."""
    out = []
    heads = list(PAVEMENT_TYPE.finditer(text))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[m.end():end]
        curb = CURB.search(body)
        # деталь бортового камня стоит внутри блока газона и площадки: её бетон — не слой одежды
        tail = re.search(r"Цементобетон[^\n]*\n[^\n]*\n\s*Обмазать", body, re.I)
        stop = min(x.start() for x in (curb, tail) if x) if (curb or tail) else len(body)
        legend = re.search(r"Условные\s+обозначения|Экспликаци", body, re.I)
        if legend:
            stop = min(stop, legend.start())
        layers = _layers(body[:stop].splitlines())
        if layers:
            out.append({"key": m.group(1), "purpose": _purpose(m.group(2)), "layers": layers,
                        "snippet": re.sub(r"\s+", " ", text[m.start():m.end() + 160]).strip()})
    for m in PAVEMENT_INLINE.finditer(text):
        parts = re.split(r";\s*", m.group(3))
        layers = _layers(parts)
        if layers:
            out.append({"key": m.group(2), "purpose": _purpose(m.group(1)), "layers": layers,
                        "snippet": re.sub(r"\s+", " ", m.group(0)[:220]).strip()})
    return out


# ---------- кровля ----------

ROOF_LIST = re.compile(r"Кровля\s*[-–]\s*тип\s*([IVX]+|\d+)\s*(?:\(([^)]*)\))?", re.I)
ROOF_TYPE = re.compile(r"ТИП\s+КРОВЛИ\s+([IVX]+|\d+)", re.I)
ROOF_END = re.compile(r"Сопротивление\s+теплопередач|Кровля\s*[-–]\s*тип|Формат\s+А\d", re.I)
ROOF_KINDS = {"vapor", "separation", "slope", "waterproofing", "drainage", "primer", "screed", "insulation",
              "paving", "base", "geotextile", "concrete"}


def _roof_list(text):
    out = []
    heads = list(ROOF_LIST.finditer(text))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[m.end():end]
        stop = ROOF_END.search(body)
        body = body[:stop.start()] if stop else body
        items = re.split(r"(?m)^\s*\d+\.\s+", body)[1:]
        layers = [l for item in items for l in _layers(re.split(r"\n\s*-\s+|\n", item))]
        layers = [l for l in layers if l["kind"] in ROOF_KINDS]
        if len({l["kind"] for l in layers}) >= 3:
            out.append({"key": m.group(1).upper(), "purpose": _purpose(m.group(2) or ""), "layers": layers,
                        "form": "list", "snippet": re.sub(r"\s+", " ", text[m.start():m.end() + 200]).strip()})
    return out


def _roof_callouts(text):
    """Выноски разреза: подряд идущие строки слоёв кровли, от ковра или плитки до основания."""
    out, run, gap = [], [], 0
    lines = text.splitlines()

    def flush(at):
        kinds = {l["kind"] for l in run}
        if len(kinds) >= 4 and kinds & {"waterproofing", "paving"} and kinds & {"base", "insulation", "vapor"}:
            before = "\n".join(lines[max(0, at - len(run) - 40): at - len(run)])
            types = ROOF_TYPE.findall(before)
            out.append({"key": types[-1].upper() if types else None, "purpose": "", "layers": list(run),
                        "form": "callout", "snippet": "; ".join(l["text"][:60] for l in run[:4])})

    for i, line in enumerate(lines):
        kind = kind_of(line)
        if kind in ROOF_KINDS:
            if run and kind == "waterproofing" and run[-1]["kind"] == "waterproofing":
                run[-1]["text"] += " " + line.strip()
            else:
                run.append({"kind": kind, "mm": thickness(line), "text": line.strip()})
            gap = 0
            if kind == "base":
                flush(i + 1)
                run, gap = [], 0
        elif run and gap < 2 and not re.fullmatch(r"\s*[-–]?\s*\d+(?:[,.]\d+)?\s*(?:мм|см)?.*", line):
            gap += 1
            run[-1]["text"] += " " + line.strip()
        else:
            if run:
                flush(i)
            run, gap = [], 0
    if run:
        flush(len(lines))
    return out


def roof(text):
    """Составы кровли на странице: нумерованные списки записки и выноски разрезов."""
    return _roof_list(text) + _roof_callouts(text)


# ---------- наружные стены: утеплитель (ZU-125) ----------

# «Тип 1.1» записки ПД — состав наружной стены. «Тип 1.1/1.2/5.1/5.2» — строка ведомости изменений
# («было / стало» подряд), её состав не разбирается: иначе прежний утеплитель попадал бы в действующие
WALL_TYPE = re.compile(r"Тип\s+(\d+\.\d+)(?![\d.]|\s*/)")
WALL_END = re.compile(r"Тип\s+(?:покрыти|кровл)|Кровля|Покрытие\s+-|Формат\s+А\d", re.I)
# выноска узла фасада в РД: «Конструкция вентилируемого фасада … Минераловатные плиты … - 100+80 мм»
WALL_CONTEXT = re.compile(r"фасад|наружн\w*\s+стен|\bНФС\b", re.I)
NOT_WALL = re.compile(r"кровл|покрыти|перекрыти|потол|тамбур|трубопровод|\bПт-\d", re.I)
PLUS = re.compile(r"[-–]\s*(\d{2,3})\s*\+\s*(\d{2,3})\s*мм", re.I)
ANY_TYPE = re.compile(r"Тип\s+\d+\.\d+")
# подземная часть: утеплитель под гидроизоляцией — не фасад (РД Речникова, «Тип 2.2» подземной стены)
BELOW_GRADE = re.compile(r"гидроизоляц|битумн\w*\s+(?:грунтовк|мастик)|засыпк|подземн", re.I)
# ведомость изменений ПД: «Тип 1.1/1.2/5.1/5.2» дважды подряд — сначала «было», потом «стало»
CHANGE_TYPE = re.compile(r"Тип\s+(\d+\.\d+(?:/\d+\.\d+)+)")


def _wall_layers(body):
    """Слои утеплителя блока стены; толщины колонкой относятся к слоям по порядку."""
    # в РД толщины стоят колонкой после слоёв («-80 мм | -100 мм | -200 мм»): по порядку они
    # относятся к слоям без толщины, кроме облицовки и зазора, — если числа сходятся. Строки
    # колонки из блока убираются, иначе первая из них прилипла бы к последнему слою
    column_re = re.compile(r"(?m)^\s*[-–]\s*(\d{1,3})\s*мм\s*$")
    column = [float(x) for x in column_re.findall(body)]
    items = re.split(r"\n\s*[−–-]\s*(?!\d)", "\n" + column_re.sub("", body))
    found = _layers(items)
    targets = [l for l in found if l["mm"] is None and l["kind"] not in ("gap", "paving", "rubber")]
    if column and len(column) == len(targets):
        for l, mm in zip(targets, column):
            l["mm"] = mm
    # «Тип 2.2 (10)» бывает и типом пола или покрытия: состав стены узнаётся по зазору, кладке,
    # несущей стене или словам «фасад», «НФС», «наружная стена»
    wall = any(l["kind"] in ("gap", "masonry", "wall") for l in found) or WALL_CONTEXT.search(body)
    if not wall or NOT_WALL.search(body[:120]) or BELOW_GRADE.search(body):
        return []
    return [l for l in found if l["kind"] == "insulation" and l["mm"]]


def walls(text):
    """Утеплитель наружных стен на странице: [{key, layers, form, snippet}] — только слои утеплителя."""
    out = []
    bounds = [m.start() for m in ANY_TYPE.finditer(text)] + [len(text)]

    def block(start):
        end = min([b for b in bounds if b > start] + [start + 1500])
        body = text[start:end]
        stop = WALL_END.search(body, 12)
        return body[:stop.start()] if stop else body

    for m in WALL_TYPE.finditer(text):
        ins = _wall_layers(block(m.start())[len(m.group(0)):])
        if ins:
            out.append({"key": m.group(1), "purpose": "", "layers": ins, "form": "type",
                        "snippet": re.sub(r"\s+", " ", text[m.start():m.end() + 220]).strip()})
    heads = list(CHANGE_TYPE.finditer(text))
    for a, b in zip(heads, heads[1:]):
        if a.group(1) != b.group(1):
            continue
        ins = _wall_layers(text[a.end():b.start()])
        for key in a.group(1).split("/") if ins else ():
            out.append({"key": key, "purpose": "", "layers": ins, "form": "before",
                        "snippet": re.sub(r"\s+", " ", text[a.start():a.end() + 220]).strip()})
    for m in PLUS.finditer(text):
        line_start = text.rfind("\n", 0, max(0, text.rfind("\n", 0, m.start()))) + 1
        line = text[line_start:m.end()]
        before = text[max(0, m.start() - 250):m.start()]
        if kind_of(line) != "insulation" or not WALL_CONTEXT.search(before) or NOT_WALL.search(line):
            continue
        ins = [{"kind": "insulation", "mm": float(m.group(g)), "text": re.sub(r"\s+", " ", line).strip()} for g in (1, 2)]
        out.append({"key": "", "purpose": "", "layers": ins, "form": "callout",
                    "snippet": re.sub(r"\s+", " ", text[max(0, m.start() - 160):m.end()]).strip()})
    return out


def combo(layers):
    """Набор толщин утеплителя: «50 + 130 мм». Порядок слоёв не важен: сравнивается набор."""
    return " + ".join(f"{x:g}" for x in sorted(l["mm"] for l in layers)) + " мм"


# ---------- утеплитель кровли по элементу (ZU-128) ----------

ROOF_ELEMENTS = [("кровля лифтовых шахт", r"лифтов\w*\s+шахт"), ("рампа", r"рамп"), ("стилобат", r"стилобат"),
                 ("выходы на кровлю", r"выход\w*\s+на\s+кровл"), ("машинные помещения", r"машинн\w*\s+помещ")]
ROOF_HEAD = re.compile(r"(?:Кровл[яи]|Покрыти[ея])\s+(?:\S+\s+){0,3}?(" + "|".join(p for _, p in ROOF_ELEMENTS) + r")\w*"
                       r"(?:\s+(П\s?\d+(?:\.\d+)?))?", re.I)
ROOF_BLOCK_END = re.compile(r"(?:Кровл[яи]|Покрыти[ея]|Перекрыти[ея]|Тип\s+(?:покрыти|кровл))\s", re.I)
CHANGE_LOG = re.compile(r"до\s+корректировки|до\s+внесения\s+изменени|Изменение\s+состава", re.I)


def material(text):
    """Материал утеплителя: пенополистирол, минеральная вата или иной."""
    if re.search(r"пенополистирол|\bXPS\b|CARBON|экструз", text, re.I):
        return "пенополистирол"
    if re.search(r"минерал|минирал|базальт|каменн\w*\s+ват", text, re.I):
        return "минеральная вата"
    return "утеплитель"


def roof_insulation(text):
    """Утеплитель кровли по элементам: [{key, mark, material, mm, snippet}].

    Элемент — лифтовые шахты, рампа, стилобат, выходы на кровлю: марки покрытий у стадий разные
    (П5 в ПД, П3 в РД Речникова), а название элемента одно. В ведомости изменений у элемента
    два состава подряд — «было» и «стало»; берётся последний.
    """
    found = {}
    for m in ROOF_HEAD.finditer(text):
        name = next(n for n, p in ROOF_ELEMENTS if re.match(p, m.group(1), re.I))
        rest = text[m.end():m.end() + 900]
        stop = ROOF_BLOCK_END.search(rest, 5)
        body = rest[:stop.start()] if stop else rest
        mark = (m.group(2) or "").replace(" ", "")
        # ведомость изменений: «Тип П5 … Тип П5 …» — сначала «было», потом «стало»; берётся «стало»
        marks = list(re.finditer(r"Тип\s+(П\d+(?:\.\d+)?)", body))
        if len(marks) > 1 and marks[-1].group(1) == marks[0].group(1):
            body, mark = body[marks[-1].end():], marks[-1].group(1)
        items = re.split(r"\n\s*(?:\d+\.\s+|[−–-]\s+(?!\d))|;\s*\n", "\n" + body)
        ins = [l for l in _layers(items) if l["kind"] == "insulation" and l["mm"]]
        if not ins:
            continue
        found[name] = {"key": name, "mark": mark, "material": material(ins[0]["text"]),
                       "mm": sum(l["mm"] for l in ins), "form": "element",
                       "snippet": re.sub(r"\s+", " ", text[m.start():m.end() + 260]).strip()}
    return list(found.values())


def stacks(text, profile):
    if profile == "wall":
        return walls(text)
    return pavement(text) if profile == "pavement" else roof(text)


# ---------- сравнение ----------

def show(layers):
    """«асфальтобетон 50 мм; щебень 200 мм; песок 450 мм»."""
    return "; ".join(KIND_NAME[l["kind"]] + (f" {l['mm']:g} мм".replace(".", ",") if l["mm"] is not None else "")
                     for l in layers)


def _by_kind(layers):
    out = {}
    for l in layers:
        out.setdefault(l["kind"], []).append(l["mm"])
    return out


def differences(pd_layers, rd_layers, thickness=True, complete=True, ignore=(), added=True):
    """Что изменилось в составе: [описание]. Пусто — тот же набор слоёв, толщины не меньше.

    complete=False — состав рабочей стадии мог прочитаться не целиком (выноска разреза оборвалась):
    тогда «исключён слой» не утверждается. ignore — виды, которые не сравниваются (несущая плита
    под кровлей — не слой кровли). added=False — добавленный слой изменением не считается: у кровли
    это «признак изменения состава», а не нарушение (специалист, R4-Q-AR-044); такие слои называет
    `added_layers`.
    """
    pd = {k: v for k, v in _by_kind(pd_layers).items() if k not in ignore}
    rd = {k: v for k, v in _by_kind(rd_layers).items() if k not in ignore}
    out = [f"исключён слой: {KIND_NAME[k]}" for k in pd if k not in rd] if complete else []
    out += [f"добавлен слой: {KIND_NAME[k]}" for k in rd if k not in pd] if added else []
    if not thickness:
        return out
    for k in pd:
        if k not in rd:
            continue
        a, b = [x for x in pd[k] if x is not None], [x for x in rd[k] if x is not None]
        if not a or not b:
            continue
        if len(a) == len(b):
            less = [(x, y) for x, y in zip(a, b) if y < x]
        else:
            # слой разбит на два или слит в один (резиновое покрытие 15 → 10 + 20 мм): по сумме
            less = [(sum(a), sum(b))] if sum(b) < sum(a) else []
        for x, y in less:
            out.append(f"{KIND_NAME[k]}: толщина {x:g} → {y:g} мм".replace(".", ","))
    return out


def added_layers(pd_layers, rd_layers, ignore=()):
    """Виды слоёв, которых в проектном составе нет: [название]."""
    pd = set(_by_kind(pd_layers)) - set(ignore)
    return [KIND_NAME[k] for k in _by_kind(rd_layers) if k not in pd and k not in ignore]


def similarity(a, b):
    ka, kb = {l["kind"] for l in a}, {l["kind"] for l in b}
    return len(ka & kb) / len(ka | kb) if ka | kb else 0.0


def pair(pd_stacks, rd_stacks, profile):
    """Пары составов стадий: [(ключ, состав ПД, состав РД, как связаны)].

    Дорожная одежда связывается по номеру типа; тип, которого в ПД нет (ТИП 2.1 у Полярной 16),
    — по назначению. Кровля — по номеру типа, если он есть у обеих, иначе по сходству набора слоёв:
    выноски РД номера типа рядом не несут.
    """
    out = []
    by_key = {}
    for s in pd_stacks:
        by_key.setdefault(s["key"], s)
    for s in rd_stacks:
        mate, how = (by_key.get(s["key"]), "по номеру типа") if s.get("key") else (None, "")
        if profile == "pavement" and mate is None:
            same = [p for p in pd_stacks if p["purpose"] and p["purpose"] == s["purpose"]]
            if same:
                mate, how = same[0], "по назначению: в ПД такого номера типа нет"
        if profile == "roof" and (mate is None or similarity(mate["layers"], s["layers"]) < 0.5):
            scored = sorted(((similarity(p["layers"], s["layers"]), i) for i, p in enumerate(pd_stacks)), reverse=True)
            if scored and scored[0][0] >= 0.6:
                mate, how = pd_stacks[scored[0][1]], "по сходству набора слоёв"
            else:
                mate = None
        if mate:
            out.append((s.get("key") or mate.get("key") or "—", mate, s, how))
    return out
