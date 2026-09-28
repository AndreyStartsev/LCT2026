"""Теплопроводность утеплителя наружных стен: ПД против РД (ZU-126, #188).

Решения специалиста (R3-ZU-126):
- λ берётся любой — расчётный по условиям эксплуатации А или Б (СП 50) или заявленный
  производителем. Если стадии называют λ при разных условиях, это «сравнение невозможно»;
- допуск 2 %: рост λ до 2 % — нормально, больше — нарушение. У ДОО цоколь из пеностекла: ПД
  «λ=0,047», РД «λ=0,048» — это +2 %, в допуске. Доля округляется до целого процента: λ пишут
  тремя знаками, и шаг последнего знака у 0,047 — те же 2 %;
- замена марки без λ — «нужен эксперт». У Полярной 16 ПД называет «Rockwool Венти Баттс», а РД —
  «ТЕХНОВЕНТ СТАНДАРТ … (или аналог)», и λ нет ни там, ни там.

Где λ стоит в документах: в скобках при материале («плиты из пеностекла (прочность на сжатие
≥0,7 Мпа, ρ≥130 кг/м.куб., λ=0,047 Вт/м.°С) – 150 мм»), в перечне слоёв раздела ЭЭ
(«минераловатный утеплитель типа «Техновент Н Проф», λ - 0,040 Вт/(м×ºС) – 100 мм»), в ведомости
материалов фасадов РД («… λ=0,039 Вт/м°С) - 50 мм ТЕХНОВЕНТ ОПТИМА 89,82 м³ НФС»).

Что сравнивается. Ключ — материал утеплителя: минеральная вата, пеностекло, экструзионный
пенополистирол, пенополистирол, PIR. У каждого условия (А, Б, без буквы — заявленный)
сравнивается наибольший λ стадий: РД не должна называть λ хуже наибольшего проектного больше
чем на 2 %. Марка — производитель и серия («ТЕХНОНИКОЛЬ ТЕХНОВЕНТ СТАНДАРТ»): производитель в РД,
которого нет в ПД, без λ у его утеплителя — замена без подтверждения λ.

Стены отличаются от кровли и полов по ближайшему слову перед значением: «стена», «фасад»,
«НФС», «СФТК», «цоколь», «облицовка», «воздушный зазор» — стена; «кровля», «покрытие»,
«перекрытие», «пол», «стяжка», «подвал», «чердак», «тамбур», «потолок», трубопроводы — нет.
Серии кровли и полов («Техноруф», «Руф Баттс», «Флор Баттс») — не стены при любом слове. У РД
ДОО «Ведомость материалов покрытия плиты над подвалом» стоит за 400 знаков до
«CARBON SOLID … λ=0,034»: окно слов перед значением — 600 знаков.
"""
import re
from decimal import ROUND_HALF_UP, Decimal

LAMBDA = re.compile(r"(?:λ|лямбда)\s*(?P<c>(?<![а-яёa-z])[АБабAaBb](?![а-яёa-z])|10|25)?\s*[=:–—-]?\s*"
                    r"(?P<v>0[,.]\d{2,3})(?!\d)"
                    r"|теплопроводност\w*\s+(?:не\s+более\s+|до\s+)?(?P<v2>0[,.]\d{2,3})(?!\d)", re.I)
LOW, HIGH = 0.018, 0.075        # λ утеплителей; у бетона, кирпича и ячеистого бетона больше
TOLERANCE_PCT = 2

# вид утеплителя по строке; порядок важен: «экструдированный пенополистирол» — не просто пенополистирол
MATERIALS = (("пеностекло", r"пеностекл|изостек|foam\s?glas"),
             ("экструзионный пенополистирол", r"экструд\w*|экструз\w*|\bxps\b|carbon\s+(?:prof|solid|eco)|пеноплэкс"),
             ("PIR", r"\bpir\b|полиизоцианурат|logicpir"),
             ("пенополистирол", r"пенополистирол|\bппс\b|\beps\b"),
             ("минеральная вата", r"минерал\w*|минват|мин\.\s*ват|каменн\w*\s+ват|базальт\w*|rockwool|roc?kwool|роквул|"
                                  r"техновент|технофас|технолайт|изовент|изофас|изовол|paroc|isover|баттс"))
MATERIAL_RE = [(name, re.compile(p, re.I)) for name, p in MATERIALS]

# Марка: (производитель, серия). Производитель без серии узнаётся по самой серии: «Баттс» — только у
# Rockwool, «Техновент» — у ТЕХНОНИКОЛЬ
PRODUCTS = (
    ("ROCKWOOL", r"(?:венти|фасад|лайт|руф|флор|кавити)\s+баттс(?:\s+(?:н|д|и|оптима|экстра|стандарт)(?![а-яё]))?"),
    ("ТЕХНОНИКОЛЬ", r"техновент(?:\s+(?:н\s+проф|н|стандарт|оптима|экстра|проф)(?![а-яё]))?|"
                    r"технофас(?:\s+(?:оптима|эффект|проф|экстра|декор)(?![а-яё]))?|технолайт(?:\s+\w+)?|"
                    r"техноруф(?:\s+(?:н|в)?\s*(?:оптима|экстра|проф|стандарт)?)?|технофлор\w*|"
                    r"carbon\s+(?:prof|solid|eco)\w*"),
    ("ИЗОРОК", r"изофас[-\s]?\d*|изовент[-\s]?\w*"),
    ("ИЗОСТЕК", r"изостек"),
    ("ISOVER", r"isover\s+\w+"),
    ("PAROC", r"paroc\s+\w+"),
    ("ПЕНОПЛЭКС", r"пеноплэкс\w*(?:\s+\w+)?"),
    ("ИЗОВОЛ", r"изовол\s*\w*"),
)
PRODUCT_RE = re.compile("|".join(f"(?P<p{i}>{p})" for i, (_m, p) in enumerate(PRODUCTS)), re.I)
# серии кровли и полов: не стены при любых словах рядом
NOT_WALL_PRODUCT = re.compile(r"руф\s+баттс|флор\s+баттс|техноруф|технофлор", re.I)

WALL_WORD = r"(?<![а-яё])стен(?:а|ы|е|у|ой|ам|ами|ах)?(?![а-яё])|(?<![а-яё])фасад\w*|\bНФС\b|\bСФТК\b|цокол\w*|" \
            r"облицов\w*|воздушн\w*\s+зазор\w*|вентилируем\w*|откос\w*|простен\w*"
# шахты на кровле («Кирпичная стенка шахты … Термовкладыш XPS», РД Речникова) — не наружные стены здания
NOT_WALL_WORD = r"кровл\w*|кровел\w*|покрыти\w*|перекрыти\w*|(?<![а-яё])пол(?:ы|ов|а|ах|ам|у)?(?![а-яё])|стяжк\w*|" \
                r"подвал\w*|чердак\w*|тамбур\w*|потол\w*|шахт\w*|трубопровод\w*|воздуховод\w*|кабел\w*"
ZONE_WORD = re.compile(f"(?P<wall>{WALL_WORD})|(?P<other>{NOT_WALL_WORD})", re.I)
# слои разреза на чертеже идут вперемешку: «λ=0,044 Вт/м°С) Монолитное ж/б перекрытие» — перекрытие сразу за значением
NOT_WALL_AFTER = re.compile(r"^[^.;]{0,40}?(?:перекрыти|кровл|покрыти)", re.I)
ITEM_START = re.compile(r";|•|\s[-–—]\s+(?=[А-ЯЁа-яёA-Za-z«\"])|\b\d{1,2}\s+ГОСТ\b")
WINDOW = 600


def doc_allowed(doc):
    """Тома, где названы составы наружных стен: ПД — АР, КР и энергоэффективность (ЭЭ), РД — АР и КР."""
    stage = (doc or {}).get("stage")
    section, mark = (doc or {}).get("section"), ((doc or {}).get("mark") or "").upper()
    if stage == "PD":
        return section in ("AR", "KR") or mark.startswith("ЭЭ")
    return stage in ("RD", "RD_ID_MIXED") and section in ("AR", "KR")


def _cond(raw):
    if not raw:
        return None
    raw = raw.upper().replace("A", "А").replace("B", "Б")
    return raw


def product_of(text):
    """Марка в строке: (производитель, «Серия как в документе» в верхнем регистре) или None."""
    m = PRODUCT_RE.search(text)
    if not m:
        return None
    i = next(int(k[1:]) for k, v in m.groupdict().items() if v)
    return PRODUCTS[i][0], " ".join(m.group(0).upper().split())


def material_of(text):
    return next((name for name, rx in MATERIAL_RE if rx.search(text)), None)


def zone(flat, start, end):
    """Стена или нет по ближайшему слову перед значением: «wall», «other» или None — не понять."""
    if NOT_WALL_AFTER.search(flat[end:end + 60]):
        return "other"
    last = None
    for m in ZONE_WORD.finditer(flat, max(0, start - WINDOW), start):
        last = m
    if last is None:
        return None
    return "wall" if last.group("wall") else "other"


def _item(flat, start):
    """Строка перечня перед значением: от начала пункта («- », «;», «•», «5 ГОСТ») до значения."""
    before = flat[max(0, start - 240):start]
    cut = 0
    for m in ITEM_START.finditer(before):
        cut = m.end()
    return before[cut:]


def _snippet(flat, start, end, before=160, after=60):
    return " ".join(flat[max(0, start - before):end + after].split())


def statements(flat):
    """λ утеплителя стен на странице: [{key: вид, value: λ, cond, product, maker, raw, snippet}]."""
    out = []
    for m in LAMBDA.finditer(flat):
        raw_v = m.group("v") or m.group("v2")
        value = float(raw_v.replace(",", "."))
        if not LOW <= value <= HIGH:
            continue
        item = _item(flat, m.start())
        tail = flat[m.end():m.end() + 80]
        material = material_of(item) or material_of(tail[:40])
        if not material or re.search(r"кладк|ячеист\w*\s+бетон|газобетон", item, re.I):
            continue
        product = product_of(item) or product_of(tail)
        if (product and NOT_WALL_PRODUCT.search(product[1])) or zone(flat, m.start(), m.end()) != "wall":
            continue
        out.append({"key": material, "value": value, "cond": _cond(m.group("c")),
                    "maker": product[0] if product else None, "product": product[1] if product else None,
                    "raw": " ".join(m.group(0).split()), "snippet": _snippet(flat, m.start(), m.end())})
    return out


def products(flat):
    """Марки утеплителя стен на странице без привязки к λ: [{maker, product, key, snippet}]."""
    out, seen = [], set()
    for m in PRODUCT_RE.finditer(flat):
        maker, name = product_of(m.group(0))
        if NOT_WALL_PRODUCT.search(name) or name in seen or zone(flat, m.start(), m.end()) != "wall":
            continue
        seen.add(name)
        out.append({"maker": maker, "product": name, "key": material_of(name) or "минеральная вата",
                    "snippet": _snippet(flat, m.start(), m.end(), 120, 80)})
    return out


def by_cond(cands):
    """{вид: {условие: {λ}}} по кандидатам с λ."""
    out = {}
    for c in cands:
        if c.get("value") is not None:
            out.setdefault(c["key"], {}).setdefault(c.get("cond"), set()).add(c["value"])
    return out


def increase_pct(pd, rd):
    """Рост λ в процентах, до целого: λ пишут тысячными, и доля считается по ним, без ошибок дробей
    (0,040 → 0,043 — ровно 7,5 %, то есть 8 %)."""
    a, b = round(pd * 1000), round(rd * 1000)
    return int((Decimal(b - a) * 100 / Decimal(a)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compare(pd, rd, tolerance=TOLERANCE_PCT):
    """Сравнение λ по видам: (хуже, в допуске, разные условия) — списки кортежей.

    хуже — [(вид, условие, λ ПД, λ РД, %)]; в допуске — те же кортежи; разные условия — [(вид,
    условия ПД, условия РД)]. Сравнивается наибольший λ стадии при одном условии.
    """
    worse, ok, other = [], [], []
    for key in sorted(set(pd) & set(rd)):
        common = set(pd[key]) & set(rd[key])
        if not common:
            other.append((key, sorted(pd[key], key=str), sorted(rd[key], key=str)))
            continue
        for cond in sorted(common, key=str):
            p, r = max(pd[key][cond]), max(rd[key][cond])
            pct = increase_pct(p, r)
            (worse if pct > tolerance else ok).append((key, cond, p, r, pct))
    return worse, ok, other


# Замена марки ищется только у минеральной ваты — утеплителя фасадов. Пенополистирол в томах АР и КР
# лежит и под фундаментом, и в покрытии над подвалом, и у цоколя: у ДОО «ПЕНОПЛЭКС ФУНДАМЕНТ» проекта
# и «CARBON SOLID» покрытия плиты над подвалом в РД — разные слои, а не замена
REPLACEMENT_KEYS = ("минеральная вата",)


def new_makers(pd_products, rd_products, rd_lambda):
    """Замена утеплителя без подтверждения λ: производитель в РД, которого у того же вида утеплителя нет в ПД.

    [(вид, производитель, серии РД, {производитель ПД: серии})]. У Полярной 16 минеральная вата в ПД —
    Rockwool, а в РД рядом с ней ТЕХНОВЕНТ ТЕХНОНИКОЛЬ. Производитель с λ в РД сравнивается числом
    (`compare`).
    """
    pd_makers = {}
    for p in pd_products:
        if p["key"] in REPLACEMENT_KEYS:
            pd_makers.setdefault(p["key"], {}).setdefault(p["maker"], set()).add(p["product"])
    with_lambda = {(c["key"], c.get("maker")) for c in rd_lambda if c.get("maker")}
    out = {}
    for p in rd_products:
        own = pd_makers.get(p["key"])
        if own and p["maker"] not in own and (p["key"], p["maker"]) not in with_lambda:
            out.setdefault((p["key"], p["maker"]), set()).add(p["product"])
    return sorted((key, maker, sorted(names), {m: sorted(n) for m, n in sorted(pd_makers[key].items())})
                  for (key, maker), names in out.items())


def show(value):
    """λ тремя знаками, как в документах: «0,040»."""
    return f"{value:.3f}".replace(".", ",")


def cond_text(cond):
    return {None: "", "А": " (условия А)", "Б": " (условия Б)", "10": " (λ10)", "25": " (λ25)"}.get(cond, f" ({cond})")


def conds_text(conds):
    return ", ".join({None: "заявленный", "А": "условия А", "Б": "условия Б", "10": "λ10", "25": "λ25"}.get(c, str(c))
                     for c in conds)
