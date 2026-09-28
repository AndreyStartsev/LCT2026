"""Срок строительства в разделах проекта: ПОС против ООС и ППР (POS-082, #187).

Параметр — «Продолжительность этапов строительства (Календарный график)»: срок критического
этапа в графике ППР больше, чем в ПОС, более чем на 10 %. ППР и общего журнала работ в пакетах
объектов нет. Поэтому сравнивается тот же срок внутри проектной документации (R6-POS-082):
раздел ООС считает выбросы, стоки и отходы на срок строительства и повторяет его из ПОС
(«Согласно ПОС продолжительность строительства составляет 22,0 месяцев»). Если ООС ни разу не
называет срок ПОС, одно из двух неверно — это гипотеза.

Стороны:
- ПОС — общий срок строительства и подготовительный период. Только основная книга: вторая и
  третья — наружные сети и водопонижение — называют свой «общий срок» (у Октябрьской в ПОС2
  «Общая продолжительность строительства: 4,0 мес.» — это сети, у объекта 27 мес.);
- ООС — все книги;
- ППР рабочей стадии — общий срок, если ППР в пакете есть.

Значение — в месяцах, годы переводятся в месяцы. Дни не сравниваются: ООС ДОО пишет «671 дня»
календарных, а ООС Полярной 16 — «546 дней» рабочих (24,8 × 22).

Какие фразы берутся:
- сильные: «общий срок строительства», «общая продолжительность строительства (работ)»,
  «директивный срок строительства», «продолжительность строительства принята директивно»,
  «календарный срок строительства», «строительство … в срок, равный», «Тобщ = … = 27 мес.»;
- простые: «продолжительность строительства», «срок строительства», «срок производства работ
  по строительству», «продолжительность (строительных) работ» — только со сказуемым или тире
  перед числом: так не берутся шапки календарного плана («Продолжительность строительства, мес
  Работы подготовительного периода 1 1 2 3…»).

В документе, где есть сильная фраза, простые не берутся: в ПОС Полярной 16 «Продолжительность
строительства составит: Тздание = … = 21,3 месяца» — срок одного здания, а общий срок —
«общий срок строительства составит 24,8 месяца». Не берутся нормы и аналоги («по СНиП»,
«табл. №2 … равна 9,6 мес.»), расчёты частей («с учетом интерполяции», «на единицу прироста»),
сети, снос, демонтаж, водопонижение, подземная часть, этапы и очереди.

Сравнение по каждому ключу (общий срок, подготовительный период): расхождение — если у ПОС и
ООС нет ни одного общего значения. ООС повторяет срок в разных расчётах, и не всегда тот же:
у Новослободской «60 месяцев» четыре раза и «30,95 месяцев» один раз в расчёте отходов. Лишнее
значение одной стороны расхождением не считается, расхождение — когда ООС срок ПОС не называет
ни разу.
"""
import re

# Распознавание курсива путает кириллицу с латиницей: «Продолжительность cmpoumenbcmba составит
# 10,5 месяцев, 6 mom числе подготовительный nepuod 2 месяцо» (ООС Алтуфьевского, скан). Ключевые
# слова допускают такие буквы
_STROIT = r"[сc][тm][рp][оo][иu][тm][еe][лn][ьb]\w*"
_PERIOD = r"[пn][еe][рp][иu][оo][дd]\w*"
_VTOM = r"(?:[вb6]\s+[тm][оo][мm]\s+числе|в\s*т\.\s*ч\.?|включая|из\s+них)"
_PREP = r"подг(?:отови-?\s*тельн\w*|\.)"
_NUM = r"(?<![\d,.])(?P<v>\d{1,3}(?:[,.]\d{1,2})?)(?!\d)"
_UNIT = r"(?P<u>меся\w*|мес(?![а-яё])\.?|год[а-яё]*|лет)(?![а-яё])"

STRONG = re.compile(
    r"(?:общ\w+\s+(?:нормативн\w+\s+)?(?:продолжительн\w+|срок\w*)\s+(?:" + _STROIT + r"|работ(?![а-яё]))"
    r"|директивн\w+\s+срок\w*\s+" + _STROIT +
    r"|продолжительн\w+\s+" + _STROIT + r"\s+(?:\w+\s+){0,2}?принят\w*\s+директивн\w+"
    r"|продолжительн\w+\s+" + _STROIT + r"\s+в\s+соответствии\s+с\s+заданием"
    r"|календарн\w+\s+срок\w*\s+" + _STROIT +
    r"|" + _STROIT + r"\s+(?:\w+\s+){0,4}?в\s+срок(?![а-яё]))", re.I)
PLAIN = re.compile(
    r"(?:продолжительн\w+|срок\w*)\s+" + _STROIT +
    r"|срок\w*\s+производства\s+работ\s+по\s+" + _STROIT +
    r"|продолжительн\w+\s+(?:строительн\w+\s+)?работ(?![а-яё])", re.I)
VALUE = re.compile(r"(?P<gap>[^.;]{0,110}?)" + _NUM + r"\s*" + _UNIT, re.I)
# «Тобщ.=14 мес. +10мес. +3 мес. (демон.) =27 мес.» — последнее число после знака равенства
TOTAL_FORMULA = re.compile(r"(?<![А-ЯЁа-яё])Т\s?общ\.?\s*=(?:[^=;]{0,60}=)*\s*" + _NUM + r"\s*" + _UNIT)
# директивный срок из задания с адресом объекта между словами и числом (ПОС Новослободской:
# «директивный срок строительства объекта: «Жилой дом …», расположенный по адресу: г. Москва, …,
# составит 60 месяцев»)
DIRECTIVE_LONG = re.compile(r"директивн\w+\s+срок\w*\s+" + _STROIT + r"(?P<gap>[^;]{0,420}?)состав\w+[\s:–—-]*"
                            r"(?:\d{1,3}\s+){0,3}" + _NUM + r"\s*" + _UNIT, re.I)
VERB = re.compile(r"состав\w+|принят\w*|принимаем|равн\w+|(?:^|\s)[–—=:-](?=\s|$)", re.I)
# чужое число: норма или аналог, часть объекта, расчёт части
FOREIGN_BEFORE = re.compile(r"СНиП|норм\w*|табл\.|аналог|увеличени\w+|уменьшени\w+", re.I)
FOREIGN_GAP = re.compile(r"сет(?:ей|и|ь)(?![а-яё])|прокладк|водопонижен|демонтаж|снос|подземн|надземн|паркинг|"
                         r"автостоянк|кран|подъемник|механизм|интерполяц|экстраполяц|единицу|норм|этап|очеред|"
                         r"одного\s+здания|секци", re.I)
PREP_AFTER = (
    re.compile(_VTOM + r"[\s,]*(?:работ\w*\s+)?" + _PREP + r"\s+(?:" + _PERIOD + r"|работ\w*)[\s:–—-]*"
               r"(?:состав\w+\s+)?" + _NUM + r"\s*" + _UNIT, re.I),
    re.compile(_VTOM + r"[\s,]*" + _NUM + r"\s*" + _UNIT + r"[\s,.–—-]*(?:работ\w*\s+)?" + _PREP, re.I),
    re.compile(_VTOM + r"[\s,]*(?P<one>месяц)\s+подготови-?\s*тельн", re.I),
)
PREP_ALONE = re.compile(r"продолжительн\w+\s+подготовительн\w+\s+" + _PERIOD + r"[^.;]{0,20}?(?:состав\w+|[–—:-])"
                        r"[^.;]{0,30}?" + _NUM + r"\s*" + _UNIT, re.I)

TOTAL_KEY = "срок строительства"
PREP_KEY = "подготовительный период"
KEYS = (TOTAL_KEY, PREP_KEY)
PPR_THRESHOLD = 0.10

# раздел документа: ПОС и ООС проектной стадии, ППР рабочей
POS_PATH = re.compile(r"(?<![А-ЯЁа-яё])ПОС(?![а-яё])|организаци\w+\s+строительств", re.I)
OOS_PATH = re.compile(r"(?<![А-ЯЁа-яё])ООС(?![а-яё])|охран\w+\s+окружающ", re.I)
PPR_PATH = re.compile(r"(?<![А-ЯЁа-яё])ППР\w?(?![а-яё])|проект\w*\s+производства\s+работ", re.I)
BOOK = re.compile(r"ПОС[\s._-]?(\d+(?:\.\d+)*)", re.I)


def months(raw, unit):
    value = float(raw.replace(",", "."))
    return round(value * 12 if unit.lower().startswith(("год", "лет")) else value, 2)


def part_of(doc):
    """Раздел документа для сравнения: «ПОС», «ООС», «ППР» или None.

    ПОС — только основная книга: у второй и третьей свой «общий срок» (сети, водопонижение).
    Номер книги — из обозначения по реестру («ПОС6.1», «ПОС2») или из имени файла.
    """
    stage = (doc or {}).get("stage")
    path = (doc or {}).get("relative_path") or ""
    mark = (doc or {}).get("mark") or ""
    name = path.rsplit("/", 1)[-1]
    if stage in ("RD", "RD_ID_MIXED"):
        return "ППР" if PPR_PATH.search(path) or mark.upper().startswith("ППР") else None
    if stage != "PD":
        return None
    if mark.upper().startswith("ООС") or (not mark.upper().startswith("ПОС") and OOS_PATH.search(path)):
        return "ООС"
    if mark.upper().startswith("ПОС") or doc.get("section") == "POS" or POS_PATH.search(path):
        m = BOOK.search(mark) or BOOK.search(name)
        book = int(m.group(1).split(".")[-1]) if m else None
        return "ПОС" if book in (None, 1) else None
    return None


def _snippet(flat, start, end, before=60, after=40):
    return " ".join(flat[max(0, start - before):end + after].split())


def _prep_after(flat, end):
    """Подготовительный период в хвосте фразы о сроке: «…12 мес., в т.ч. подготовительный период 2 мес.».

    (значение, как написано, конец) или None; оборот «в том числе» — сразу за сроком.
    """
    window = flat[end:end + 110]
    for rx in PREP_AFTER:
        m = rx.search(window)
        if m and m.start() <= 12:
            if m.groupdict().get("one"):
                return 1.0, m.group("one"), end + m.end()
            return (*_value(m), end + m.end())
    return None


def _value(m):
    return months(m.group("v"), m.group("u")), f"{m.group('v')} {m.group('u')}"


def statements(flat):
    """Сроки на странице: [{key, value (мес.), raw, strong, snippet}]."""
    out, ends = [], {TOTAL_KEY: set(), PREP_KEY: set()}

    def add(key, value, raw, strong, start, end):
        # одно число — одна запись: «общая продолжительность строительства» — и сильная, и простая фраза
        if 0 < value <= 240 and end not in ends[key]:
            ends[key].add(end)
            out.append({"key": key, "value": value, "raw": " ".join(raw.split()), "strong": strong,
                        "snippet": _snippet(flat, start, end)})

    for rx, strong in ((STRONG, True), (PLAIN, False)):
        for k in rx.finditer(flat):
            if FOREIGN_BEFORE.search(flat[max(0, k.start() - 40):k.start()]):
                continue
            m = VALUE.match(flat, k.end())
            if not m:
                continue
            gap = m.group("gap")
            verb = VERB.search(gap)
            if (strong and not verb and len(gap) > 25) or (not strong and (not verb or verb.start() > 40)) \
                    or FOREIGN_GAP.search(gap):
                continue
            add(TOTAL_KEY, *_value(m), strong, k.start(), m.end())
            prep = _prep_after(flat, m.end())
            if prep:
                add(PREP_KEY, prep[0], prep[1], strong, m.end(), prep[2])
    for rx in (TOTAL_FORMULA, DIRECTIVE_LONG):
        for m in rx.finditer(flat):
            add(TOTAL_KEY, *_value(m), True, m.start(), m.end())
    for m in PREP_ALONE.finditer(flat):
        add(PREP_KEY, *_value(m), False, m.start(), m.end())
    return out


def pick(cands):
    """Значения стороны по ключам: {ключ: {значение: [кандидаты]}}.

    В документе, где срок назван сильной фразой («общий срок строительства»), простые фразы
    того же ключа не берутся: они называют срок части объекта или расчёт.
    """
    strong = {(c["file_id"], c["key"]) for c in cands if c.get("strong")}
    out = {}
    for c in cands:
        if not c.get("strong") and (c["file_id"], c["key"]) in strong:
            continue
        out.setdefault(c["key"], {}).setdefault(c["value"], []).append(c)
    return out


def same(a, b):
    """Один срок: «22 месяца» и «22,0 месяцев», «3 года» и «36 мес.»."""
    return abs(a - b) < 0.06


def changes(pos, oos):
    """Расхождения ПОС и ООС: [(ключ, значения ПОС, значения ООС)] — ключи, у которых нет общего значения."""
    return [(key, sorted(pos[key]), sorted(oos[key])) for key in KEYS
            if pos.get(key) and oos.get(key) and not any(same(a, b) for a in pos[key] for b in oos[key])]


def ppr_excess(pos, ppr, threshold=PPR_THRESHOLD):
    """Срок в ППР больше срока ПОС более чем на порог: (ПОС, ППР, доля) или None."""
    if not pos.get(TOTAL_KEY) or not ppr.get(TOTAL_KEY):
        return None
    base, got = max(pos[TOTAL_KEY]), max(ppr[TOTAL_KEY])
    share = (got - base) / base
    return (base, got, share) if share > threshold + 1e-9 else None


def show(values, raws=None):
    """«12 мес.», «12 мес., 13 мес.»: месяцы с запятой. Срок, записанный годами, — и как записан:
    «6 мес. (0,5 года)». raws — {значение: [как написано]}."""
    out = []
    for v in sorted(values):
        years = sorted({r for r in (raws or {}).get(v, ()) if re.search(r"год|лет", r, re.I)})
        out.append(f"{v:g}".replace(".", ",") + " мес." + (f" ({years[0]})" if years else ""))
    return ", ".join(out)


def side_text(got):
    """Значение стороны для записи: «срок 24,8 мес., подготовительный период 1,9 мес.».

    got — {ключ: {значение: [кандидаты]}}, как отдаёт `pick`."""
    parts = []
    for key, word in ((TOTAL_KEY, "срок"), (PREP_KEY, "подготовительный период")):
        if got.get(key):
            raws = {v: [c["raw"] for c in cs] for v, cs in got[key].items()}
            parts.append(f"{word} {show(got[key], raws)}")
    return ", ".join(parts) or None
