"""Свободный поиск: предусмотрено проектом для помещений — нет в рабочей документации. Задача #31.

Четыре эталонные точки из девятнадцати лежат вне Матрицы: «тёплые полы в помещениях МГН
267, 270, 271, 272 предусмотрены в ПД и отсутствуют в РД». Параметра для них нет, но сам
проект говорит об этом прямо, обычной фразой текстовой части:

    «В помещениях раздевальных, санузлов и душевых для МГН (пом. 267, 270, 271, 272)
     предусмотрена система подогрева полов (теплые полы)…»

Отсюда логическое правило, которое не зависит от раздела и объекта: **элемент, который
проект предусмотрел для названных помещений, должен быть и в рабочей документации**.

Как оно работает.

1. В тексте проектной стадии ищутся фразы «(пом. N, N…) предусмотрен… <элемент>»
   и «в помещении № N … устанавливается <элемент>»: номера помещений, затем глагол
   проектного решения, затем то, что предусмотрено.
2. Элемент — физическая вещь: система, установка, завеса, кожух, подогрев. Процессы
   и требования («поддержание температуры», «возможность доступа») элементами не считаются:
   их отсутствие в чертежах ничего не значит.
3. Из названия элемента берутся опорные слова; если в скобках или кавычках дано
   обиходное название («теплые полы»), оно тоже опора.
4. В рабочей документации элемент ищется по всему тексту стадии. Гипотеза выдаётся,
   только если рабочая документация эти помещения называет (значит, она их охватывает),
   а элемента в ней нет нигде.

Чего правило не делает. Оно не видит элемент, показанный в рабочей документации только
условным знаком без подписи: поэтому результат — гипотеза для инспектора с пометкой
`needs_expert`, с цитатой проекта и страницей рабочей документации, где помещение есть,
а элемента нет. Задания на проектирование («предусмотреть…») не разбираются: это
требование к проекту, а не его решение.
"""
import collections
import os
import re
import sys

# номер помещения: «267», «012», «5.1», «2.1-24», «14а»
_ROOM = r"\d{1,4}[а-я]?(?:[.\-]\d{1,3}){0,2}"
_ROOMS = _ROOM + r"(?:\s*(?:,|и)\s*" + _ROOM + r")*"
# проектное решение: «предусмотрена», «предусматривается», «устанавливается», «оборудуются».
# Неопределённая форма («предусмотреть») — язык задания на проектирование, её не берём
_VERB = (r"предусмотрен[аоы]?|предусматрива[ею]тся|устанавлива[ею]тся|установлен[аоы]?"
         r"|оборуду[ею]тся|оборудован[аоы]?|оснаща[ею]тся|оснащен[аоы]?|монтиру[ею]тся")
# Номера вводятся сокращением «пом. 267, 270» или полным словом со знаком номера
# «в помещении №14». Полное слово без знака не годится: «через прочие помещения 0 Общие
# требования» — это номер раздела задания, а не помещение
CLAUSE_RE = re.compile(
    r"(?:пом\.\s*(?:№\s*)?|помещени\w*\s*№\s*)(?P<rooms>" + _ROOMS + r")\s*\)?"
    r"(?P<gap>[^.;]{0,80}?)\b(?P<verb>" + _VERB + r")\s+(?P<element>[^.;]{4,160})",
    re.I)
# Проектное решение без номера помещения: «предусмотрена ... » с адресом слева. Номер
# помещения — самая крепкая адресация, но в корпусе она редка: на пяти объектах разработки
# из 559–2434 проектных решений с элементом номер стоит у 2–13, а название помещения, этаж
# или конструкция — у 60–200 (#96). Поэтому адрес ищется и в этих формах
VERB_RE = re.compile(r"\b(?P<verb>" + _VERB + r")\s+(?P<element>[^.;]{4,160})", re.I)
ADDRESS_BACK = 140              # адрес ищется не дальше этого числа знаков слева от глагола

# Адресация помещения по названию: в корпусе так пишут чаще, чем номером. Локация записи —
# каноническое название, а не найденная форма слова
NAMED_ROOMS = (
    (r"санузл\w+|уборн\w+|сануз\.", "санузлы"), (r"душев\w+", "душевые"),
    (r"раздевал\w+", "раздевальные"), (r"кладов\w+", "кладовые"),
    (r"венткамер\w+|вентиляционн\w+\s+камер\w+", "венткамеры"),
    (r"электрощитов\w+|щитов\w+\s+помещени\w+", "электрощитовые"),
    (r"насосн\w+", "насосные"), (r"тепл\w+\s+пункт\w*|\bИТП\b", "тепловой пункт"),
    (r"лестничн\w+\s+клетк\w+", "лестничные клетки"), (r"тамбур\w*", "тамбуры"),
    (r"коридор\w*", "коридоры"), (r"вестибюл\w*", "вестибюль"),
    (r"лифтов\w+\s+холл\w*", "лифтовые холлы"), (r"мусорокамер\w*|мусоросборн\w+", "мусорокамера"),
    (r"колясочн\w*", "колясочные"), (r"(?:подземн\w+\s+)?(?:автостоянк\w+|паркинг\w*)", "автостоянка"),
)
# Адресация этажом или уровнем: локация записи — «3 этаж», «подвал», «кровля»
FLOORS = (
    (r"(?<![\d.,])(\d{1,2})\s*(?:-?[гм]о)?\s*этаж\w*", None),
    (r"перв\w+\s+этаж\w*", "1 этаж"), (r"втор\w+\s+этаж\w*", "2 этаж"),
    (r"трет\w+\s+этаж\w*", "3 этаж"), (r"типов\w+\s+этаж\w*", "типовой этаж"),
    (r"подземн\w+\s+этаж\w*|подвал\w*|техподполь\w*|техническ\w+\s+подполь\w*", "подземная часть"),
    (r"кровл\w*", "кровля"), (r"чердак\w*|чердачн\w+", "чердак"),
)
# Адресация конструкцией: там, где помещений нет вовсе — генплан, КР, фасады
ADDRESS_ELEMENTS = (
    (r"фундаментн\w+\s+плит\w+", "Фундаментная плита"), (r"стен\w+\s+в\s+грунте", "Стена в грунте"),
    (r"ростверк\w*", "Ростверки"), (r"плит\w+\s+перекрыти\w*|перекрыти\w*", "Плиты перекрытия"),
    (r"фасад\w*", "Фасады"), (r"ограждени\w+\s+котлован\w*", "Ограждение котлована"),
    (r"парапет\w*", "Парапет"), (r"шахт\w+\s+лифт\w*|лифтов\w+\s+шахт\w*", "Лифтовые шахты"),
    (r"приямк\w*", "Приямки"), (r"пандус\w*", "Пандусы"),
)


def _address_table(rows, location_type):
    return [(re.compile(rx, re.I), canonical, location_type) for rx, canonical in rows]


ADDRESS_KINDS = (
    ("название", _address_table(NAMED_ROOMS, "ROOM")),
    ("этаж", _address_table(FLOORS, "SECTION")),
    ("конструкция", _address_table(ADDRESS_ELEMENTS, "CONSTRUCTION_ELEMENT")),
)
# «должны быть предусмотрены» — требование задания, а не решение проекта
REQUIREMENT = re.compile(r"должн\w+\s+быть|следует|необходимо|требуется", re.I)

# Голова названия элемента — физическая вещь. Список общий для инженерных разделов,
# а не подобранный под эталон: по нему отсеиваются процессы и требования
ELEMENT_HEAD = re.compile(
    r"(?<![а-яё])(?:систем|установк|устройств|прибор|оборудовани|завес|шкаф|щит|кожух|огражден"
    r"|клапан|трап|лоток|лотк|люк|насос|вентилятор|калорифер|радиатор|конвектор|кабел|светильник"
    r"|датчик|извещател|оросител|кран|сч[её]тчик|фильтр|подогрев|обогрев|изоляци|гидроизоляци"
    r"|покрыти|пандус|поручн|подъ[её]мник|лифт|воздуховод|зонт|отсос|сигнализаци|розетк|кнопк)",
    re.I)
NOT_ELEMENT = re.compile(
    r"^(?:возможност|поддержани|обеспечени|соблюдени|доступ|температур|параметр|режим|место|мест[ао]"
    r"|помещени|зал|зона|кладов)", re.I)
# служебные слова в названии элемента опорой не служат
STOP = {"система", "системы", "систему", "системой", "установка", "установки", "устройство",
        "устройства", "для", "при", "под", "над", "или", "либо", "также", "типа", "вида",
        "с", "в", "на", "и", "из", "от", "по", "не", "совмещенная", "совмещённая"}
ALIAS_RE = re.compile(r"[(«\"“]\s*([А-Яа-яЁё][А-Яа-яЁё\s-]{3,40}?)\s*[)»\"”]")


def _stem(word):
    """Основа слова без окончания: «полы» → «пол», «теплые» → «тепл», «подогрева» → «подогре»."""
    w = word.lower().replace("ё", "е")
    if len(w) > 5:
        return w[:-2]
    # короткое слово: снимается только окончание, основа не короче трёх букв
    cut = re.sub(r"(?:ов|ев|ам|ом|ах|ы|а|у|е|и|я|й|ь)$", "", w)
    return cut if len(cut) >= 3 else w


# Окончания прилагательных и существительных, от длинных к коротким. `_stem` просто срезает две буквы и
# у «наплавляемого» оставляет «наплавляемо», которое «наплавляемым» уже не находит; шаблон по головному
# слову ищет слово в любом падеже и числе, поэтому ему нужна основа без окончания (#229)
_ENDINGS = re.compile(r"(?:ого|его|ому|ему|ыми|ими|ами|ями|ых|их|ый|ий|ой|ая|яя|ое|ее|ые|ие|ую|юю|ом|ем|ам|ям"
                      r"|ах|ях|ов|ев|ей|ия|ию|ю|а|я|о|е|ы|и|у|ь)$")


def _root(word):
    """Основа слова без окончания, не короче четырёх букв: «наплавляемого» → «наплавляем»."""
    w = word.lower().replace("ё", "е")
    cut = _ENDINGS.sub("", w)
    return cut if len(cut) >= 4 else w[:4] if len(w) >= 4 else w


# Между опорными словами допускается короткий служебный: опорные слова берутся значимыми
# («трапы», «стяжке»), а в тексте между ними стоит предлог — «трапы в стяжке пола»
_LINK = r"[\s\"«»“”'(),-]{1,4}(?:(?:в|во|на|для|из|с|со|под|по|от|при|у)\s{1,2})?"


def _phrase_pattern(words):
    """Слова подряд с любыми окончаниями: «теплые полы» находит и «тёплого пола», и «“теплый пол”».

    Слова должны стоять рядом и начинаться с основы: иначе «теплоноситель» рядом
    с «полотенцесушителем» сошёл бы за «тёплый пол», а он есть в любом томе отопления.
    """
    parts = [r"(?<![а-яё])" + re.escape(_stem(w)) + r"[а-яё]{0,4}(?![а-яё])" for w in words]
    return re.compile(_LINK.join(parts), re.I)


def split_rooms(text):
    return [r for r in re.findall(_ROOM, text) if r.strip("0")]


# Происхождение и марка — не то, чем элемент назван в РД: «конвекторы отечественного производства» в РД
# Полярной 17 — «Конвектор Tepla Neo Expo», «насосы фирмы Grundfos» — насосы любой фирмы (#229)
QUALIFIER = re.compile(r"\s+(?:отечественн\w*|импортн\w*|российск\w*|производств\w*|фирм\w*|марк[иа]"
                       r"|тип[аов]?|серии)(?![а-яё])", re.I)
# Обозначение системы — две-четыре буквы и номер: «ДУ1», «ПД10», «КДУ1». Оно называет систему однозначно
# и в РД стоит тем же знаком, например в схеме щита «щит управления вентилятором ДУ1» (#229). Одна буква с
# номером («П1», «В2») — марка чего угодно, от пола до окна, опорой она не служит
DESIGNATION = re.compile(r"(?<![А-ЯЁA-Zа-яёa-z0-9])([А-ЯЁ]{2,4})[\s-]?(\d{1,3}(?:\.\d{1,2})?)(?![\dА-ЯЁа-яё]|[.,]\d)")


# Обозначение засчитывается только рядом со словом о системе: «ДВ-2» в ведомости окон Алтуфьевского — дверь,
# а не система дымоудаления ДВ2, а «щит управления вентилятором ДУ1» у Полярной 17 — та самая система (#229)
_SYSTEM_WORD = r"(?:систем|вентилятор|установк|щит|шкаф|клапан|дымоудал|подпор|приточн|вытяжн|отоплени|насос)"


def _designation_pattern(letters, number):
    return re.compile(r"(?<![а-яё])" + _SYSTEM_WORD + r"[а-яё]*(?:\s+\S+){0,3}?\s+" + re.escape(letters.lower())
                      + r"[\s-]?" + re.escape(number) + r"(?![\dа-яё]|[.,]\d)", re.I)


# Родовое головное слово: у «спринклерной установки пожаротушения» имя элемента — определение, и без него
# «установка … пожаротушения» нашлась бы в РД любого пожаротушения (#229)
GENERIC_HEAD = re.compile(r"(?:систем|установк|устройств|оборудовани|прибор)", re.I)
# Запятая и предлог начинают другое обстоятельство, а не продолжают имя элемента: «конвекторы, в лифтовом
# холле устанавливаются …» — элемент «конвекторы», «в лифтовом холле» к имени не относится (#229)
CLAUSE_BREAK = re.compile(r"[,;]\s+(?:в|во|на|для|из|с|со|при|по|у|от|до|над|под)\s", re.I)


def element_terms(phrase):
    """Как искать элемент в тексте: шаблоны по названию, по обиходному названию в скобках,
    по обозначению системы и по головному слову с тем, что за ним (#229)."""
    head = re.split(r"\s+(?:которая|который|которые|обеспечивающ\w+|совмещ[её]нн\w+)\b", phrase)[0]
    head = CLAUSE_BREAK.split(head)[0]
    head = ALIAS_RE.sub(" ", head)
    cut = QUALIFIER.search(head)
    if cut:
        head = head[:cut.start()]
    words = [w for w in re.findall(r"[А-Яа-яЁё-]{3,}", head)
             if w.lower() not in STOP and not NOT_ELEMENT.match(w)]
    patterns = []
    if len(words) >= 2:
        patterns.append(_phrase_pattern(words[:2]))
        # Перед головным словом стоит определение, которое РД может не повторить: «оклеечная
        # гидроизоляция из наплавляемого материала» в РД Полярной 17 — «гидроизоляция стен рулонным
        # наплавляемым материалом». Тогда ищется головное слово и следующее за ним значимое слово
        # на расстоянии до трёх слов. Если головное слово первое, это уже первый шаблон
        at = next((i for i, w in enumerate(words) if ELEMENT_HEAD.match(w)), None)
        if at and at + 1 < len(words) and not GENERIC_HEAD.match(words[at]):
            near = (r"(?<![а-яё])" + re.escape(_root(words[at])) + r"[а-яё]{0,4}(?![а-яё])(?:\s+\S+){0,3}?\s+"
                    + re.escape(_root(words[at + 1])) + r"[а-яё]{0,4}(?![а-яё])")
            patterns.append(re.compile(near, re.I))
    for alias in ALIAS_RE.findall(phrase):
        alias_words = [w for w in re.findall(r"[А-Яа-яЁё-]{3,}", alias) if w.lower() not in STOP]
        if alias_words:
            patterns.append(_phrase_pattern(alias_words[:3]))
    # обозначение помогает найти элемент, но само элемента не делает: без шаблона по словам фраза
    # по-прежнему не разбирается, иначе появились бы гипотезы, которых раньше не было
    if patterns:
        patterns += [_designation_pattern(letters, number) for letters, number in DESIGNATION.findall(phrase)]
    return patterns


def address_before(before):
    """Адрес проектного решения слева от глагола: (вид, локации, шаблон поиска в РД) или None.

    Побеждает ближайший к глаголу адрес: во фразе «в венткамере на кровле предусмотрена…»
    решение относится к кровле. Номер помещения ищется отдельно (CLAUSE_RE) и сильнее любого
    названия: он адресует ровно одно помещение.
    """
    best = None
    for kind, table in ADDRESS_KINDS:
        for rx, canonical, location_type in table:
            for m in rx.finditer(before):
                if best and m.start() <= best[0]:
                    continue
                label = canonical
                if label is None:                    # «3 этаж»: номер берётся из совпадения
                    label = f"{m.group(1)} этаж"
                best = (m.start(), kind, label, location_type, rx)
    if not best:
        return None
    _pos, kind, label, location_type, rx = best
    return {"kind": kind, "locations": [label], "location_type": location_type, "pattern": rx}


# Номер помещения слева от глагола: такую фразу разбирает CLAUSE_RE, и второй раз её брать
# по названию помещения не нужно
ROOM_ADDR = re.compile(r"(?:пом\.\s*(?:№\s*)?|помещени\w*\s*№\s*)" + _ROOM, re.I)


# Предусмотренное начинается с предлога — разбор зацепил не то: «предусмотрен из насосной
# станции выход в коридор» это про выход, а «насосной» просто попалась в опорные слова
ELEMENT_START = re.compile(r"^(?:из|на|в|во|с|со|для|от|до|по|при|через|над|под|между|у)\s", re.I)
# Предусмотрено «выполнить …», «обеспечить …» — это указание, а не элемент: у Полярной 17 из фразы
# «электроснабжение … предусматривается выполнить до щита механизации» элементом стало «выполнить до щита
# механизации», и такого в РД, конечно, не нашлось, хотя щиты ЩМ-1…6 там есть (#229)
INSTRUCTION_START = re.compile(
    r"^(?:выполнить|предусмотреть|установить|обеспечить|осуществить|произвести|смонтировать|проложить"
    r"|подключить|запроектировать|выполнять|производить|осуществлять)(?![а-яё])", re.I)
ELEMENT_HEAD_WORDS = 3          # голова элемента — в первых словах, а не где угодно во фразе


# Раздел элемента по головному слову, когда оно однозначно: светильник, щит, ВРУ — электрика; вентилятор,
# воздуховод, конвектор — отопление и вентиляция. Проектная фраза бывает в томе другого раздела: у Октябрьской
# ВРУ названы в томе КР, а РД — одни КЖ; «элемента нет в РД» там ничего не значит — электрики в РД нет (#229)
ELEMENT_SECTIONS = (
    (re.compile(r"(?<![а-яё])(?:светильник|прожектор|розетк|выключател|щит|вру(?![а-яё])|вводно-?\s*распределит)",
                re.I), "EOM"),
    (re.compile(r"(?<![а-яё])(?:вентилятор|воздуховод|калорифер|конвектор|радиатор|завес)", re.I), "OV"),
)


# Тому инженерного раздела верим: «установка электрического конвектора» в томе ЭОМ — электрика, а не ОВ
ENGINEERING_SECTIONS = {"EOM", "OV", "VK", "SS"}


def element_section(element, section):
    """Раздел, в РД которого искать элемент: раздел тома проекта, а у тома неинженерного раздела (КР, АР,
    пояснительная записка) — раздел по головному слову элемента, если оно однозначно."""
    if section in ENGINEERING_SECTIONS:
        return section
    head = " ".join(element.split()[:ELEMENT_HEAD_WORDS])
    return next((sec for rx, sec in ELEMENT_SECTIONS if rx.search(head)), section)


def _element_ok(element, gap):
    """Годится ли то, что предусмотрено, в элемент, и решение ли это вообще."""
    if ELEMENT_START.match(element) or INSTRUCTION_START.match(element):
        return False
    head = " ".join(element.split()[:ELEMENT_HEAD_WORDS])
    if not ELEMENT_HEAD.search(head) or NOT_ELEMENT.match(element):
        return False
    # «предусмотрено помещение (пом. 23)» — предусмотрено само помещение, а не элемент в нём
    if re.search(r"помещени\w*\s*$", gap or "", re.I):
        return False
    return not REQUIREMENT.search(gap or "")


def clauses(flat):
    """Проектные фразы «для этого адреса предусмотрен элемент».

    Возвращает [{rooms, address, element, terms, quote}]. `address` — как записана локация:
    номер помещения, название помещения, этаж или конструкция. Номер помещения — самая
    крепкая форма и разбирается первой; остальные формы нужны для обобщаемости (#96):
    в разделах генплана и КР помещений нет вовсе, а в инженерных разделах решение чаще
    адресовано названием («в венткамерах предусмотрены…»).
    """
    out, taken = [], []
    for m in CLAUSE_RE.finditer(flat):
        element = " ".join(m.group("element").split())
        if not _element_ok(element, m.group("gap")):
            continue
        terms = element_terms(element)
        rooms = split_rooms(m.group("rooms"))
        if not terms or not rooms:
            continue
        taken.append(m.end("gap"))
        out.append({"rooms": rooms, "element": element[:140], "terms": terms,
                    "address": {"kind": "номер", "locations": rooms, "location_type": "ROOM",
                                "pattern": None},
                    "quote": " ".join(flat[max(0, m.start() - 90):m.end() + 20].split())})
    for m in VERB_RE.finditer(flat):
        if any(abs(pos - m.start()) < 4 for pos in taken):
            continue                      # эту фразу уже разобрали по номеру помещения
        before = flat[max(0, m.start() - ADDRESS_BACK):m.start()]
        if ROOM_ADDR.search(before):
            continue                      # номер помещения есть, но фраза не прошла разбор CLAUSE_RE
        element = " ".join(m.group("element").split())
        gap = before[before.rfind(".") + 1:]
        if not _element_ok(element, gap):
            continue
        # адрес ищется в том же предложении: у Речникова «в соответствии с Заданием на
        # проектирование предусмотрена система мусороудаления» иначе адресовалась фасадам,
        # названным предложением раньше
        address = address_before(gap)
        if not address:
            continue
        terms = element_terms(element)
        if not terms:
            continue
        out.append({"rooms": [], "element": element[:140], "terms": terms, "address": address,
                    "quote": " ".join(flat[max(0, m.start() - 110):m.end() + 20].split())})
    return out


def mentions(flat_lower, patterns):
    """Назван ли элемент в тексте: найден хотя бы один из его шаблонов."""
    text = flat_lower.replace("ё", "е")
    return any(p.search(text) for p in patterns)


def room_pattern(room):
    return re.compile(r"(?<![\d.,])" + re.escape(room) + r"(?![\d])")


MAX_EVIDENCE = 3
CRITICALITY = "Существенное (предписание) — требует утверждения"
_MATCH_WARNED = False             # сбой сопоставления пишется в журнал один раз за процесс
# Перенос гипотезы в MATRIX по эмбеддингам — только по флагу FREE_SEARCH_MATRIX=1 (#79, Р-127).
# На настоящих весах BGE-M3 (fp32 и int8 одинаково) он переносил 29 гипотез из 38 на девяти
# объектах, 23 — с критичностью «приостановка работ», и по смыслу подходили 7–8: при отрыве
# 0,001–0,05 «противодымная вентиляция» уходила в канализационные трубы, «спринклерная
# установка» — в наружное пожаротушение. Полнота по эталону падала с 25 до 21 из 25, балл —
# с 99,28 до 93,96. Порогом не отделить: неверные 0,49–0,60, верные на разметке 0,42–0,61.
MATRIX_BY_EMBEDDINGS = os.environ.get("FREE_SEARCH_MATRIX", "0") == "1"


def search(object_id, pd_pages, rd_pages):
    """Гипотезы по объекту.

    pd_pages, rd_pages — [(file_id, страница, текст, раздел)] проектной и рабочей стадии.
    Возвращает (находки, сводка).

    Одна и та же фраза встречается в нескольких томах проекта (в томе отопления
    и в томе энергоэффективности). Проверяется то вхождение, чей раздел есть в рабочей
    документации: без него «элемента нет» значит только то, что раздел не выпущен.
    """
    stats = collections.Counter()
    rd_flat = [(fid, page, " ".join((text or "").split()), sec) for fid, page, text, sec in rd_pages]
    rd_flat = [r for r in rd_flat if len(r[2]) > 30]
    rd_sections = {sec for _f, _p, _t, sec in rd_flat if sec and sec != "OTHER"}
    pd_flat = [(fid, page, " ".join((text or "").split()), sec) for fid, page, text, sec in pd_pages]

    grouped = collections.OrderedDict()
    for fid, page, flat, section in pd_flat:
        if len(flat) < 60:
            continue
        for clause in clauses(flat):
            key = (tuple(clause["address"]["locations"]), tuple(p.pattern for p in clause["terms"]))
            grouped.setdefault(key, []).append((fid, page, section, clause))

    found = []
    for key, occurrences in grouped.items():
        stats["проектных фраз"] += 1
        stats[f"адресация: {occurrences[0][3]['address']['kind']}"] += 1
        # раздел элемента только отсекает: если в РД нет тома его раздела, «элемента нет» ничего не значит;
        # охват адреса и сам поиск — как прежде, по разделу тома проекта, чтобы новых гипотез не появилось
        usable = [o for o in occurrences
                  if o[2] in rd_sections and element_section(o[3]["element"], o[2]) in rd_sections]
        if not usable:
            stats["раздела нет в рабочей документации"] += 1
            continue
        fid, page, section, clause = usable[0]
        same = [r for r in rd_flat if r[3] == section]
        covered = coverage(clause, same)
        if not covered:
            stats["адрес не назван в рабочей документации раздела"] += 1
            continue
        if any(mentions(t.lower(), clause["terms"]) for _f, _p, t, _s in rd_flat):
            stats["элемент назван в рабочей документации"] += 1
            continue
        # где элемент показан в самом проекте: страницы того же тома, где он назван рядом
        # с этим адресом (схема или план), — доказательство сильнее одной фразы
        drawn = [(f, p) for f, p, t, _s in pd_flat
                 if f == fid and p != page and mentions(t.lower(), clause["terms"])
                 and address_in(t, clause)][:MAX_EVIDENCE]
        stats["гипотез"] += 1
        found.append(_finding(object_id, clause, fid, page, section, covered, drawn))
    return found, dict(stats)


def address_in(text, clause):
    """Назван ли адрес решения в этом тексте."""
    address = clause["address"]
    if address["kind"] == "номер":
        return any(room_pattern(r).search(text) for r in clause["rooms"])
    return bool(address["pattern"].search(text))


def coverage(clause, rd_section_pages):
    """Страницы рабочей стадии, где назван адрес решения: {локация: [(файл, страница)]}.

    Это доказательство охвата: рабочая документация про это место говорит, значит «элемента
    в ней нет» — утверждение о решении, а не о том, что раздел не выпущен.
    """
    address = clause["address"]
    out = {}
    if address["kind"] == "номер":
        targets = [(room, room_pattern(room)) for room in clause["rooms"]]
    else:
        targets = [(address["locations"][0], address["pattern"])]
    for label, rx in targets:
        hits = []
        for f, p, t, _s in rd_section_pages:
            if rx.search(t) and f not in {h[0] for h in hits}:
                hits.append((f, p))
        if hits:
            out[label] = hits[:MAX_EVIDENCE]
    return out


# Элемент ищется в тексте РД словами проектной фразы, и «не найден» — слабый вывод: специалист в
# четвёртом круге (Р-108) нашёл половину таких элементов в РД под другими словами («ВРУ» вместо
# «вводно-распределительного устройства», «лоток» вместо «лотков», «мембранный бак»)
WORDS_ONLY = "элемент искали по словам проекта, в РД он может быть назван иначе"


def _finding(object_id, clause, pd_file, pd_page, section, covered, drawn=()):
    by_number = clause["address"]["kind"] == "номер"
    rooms = sorted(covered, key=lambda r: [int(x) if x.isdigit() else 0 for x in re.split(r"\D+", r)]) \
        if by_number else sorted(covered)
    where = "помещениями" if by_number else "адресом"
    evidence = [{"stage": "PD", "file_id": pd_file, "pdf_page_number": pd_page,
                 "quote": clause["quote"][:400], "localization": "PAGE_LEVEL"}]
    for fid, page in drawn:
        evidence.append({"stage": "PD", "file_id": fid, "pdf_page_number": page,
                         "quote": f"элемент назван на листе вместе с {where} {', '.join(rooms)}",
                         "localization": "PAGE_LEVEL"})
    for room in rooms:
        for fid, page in covered[room]:
            if not any(e["stage"] == "RD" and (e["file_id"], e["pdf_page_number"]) == (fid, page)
                       for e in evidence):
                named = f"помещение {room}" if by_number else room
                evidence.append({"stage": "RD", "file_id": fid, "pdf_page_number": page,
                                 "quote": f"{named} названо, элемента нет",
                                 "localization": "PAGE_LEVEL"})
    slug = re.sub(r"[^A-Za-zА-Яа-я0-9]+", "-", clause["element"][:40]).strip("-")
    finding = {
        "finding_id": f"{object_id}::FREE::{'-'.join(rooms)}::{slug}",
        "object_id": object_id,
        "matrix_scope": "FREE_SEARCH",
        "parameter_code": f"FREE-{section or 'OTHER'}-DESIGN-ELEMENT",
        "parameter_id": None,
        "title": f"Предусмотрено проектом и не найдено в рабочей документации: {clause['element'][:80]}",
        "comparison_result": "MISSING_DESIGN_ELEMENT",
        "location_type": clause["address"]["location_type"],
        "locations": rooms,
        "pd_value": clause["element"][:200],
        "rd_value": "в рабочей документации не названо",
        "id_value": None,
        "violation_label": "VIOLATION_PRESENT",
        # у находки вне Матрицы каталожной критичности нет; в перечне организатора для таких
        # есть своя формулировка, и она же означает статус протокола WARNING (contracts/enums.json)
        "criticality": CRITICALITY,
        "finding_status": "SUSPICION",
        "needs_expert": True,
        "evidence": evidence,
        "extraction": {
            "rule_basis": "элемент, предусмотренный проектом для названных помещений, "
                          "должен быть в рабочей документации",
            "detail": f"в проекте: «{clause['quote'][:200]}»; в рабочей документации "
                      f"{'помещения' if by_number else 'адрес'} {', '.join(rooms)} "
                      f"назван{'ы' if by_number else ''}, элемент не назван ни на одной странице "
                      f"с текстом. Адресация решения — {clause['address']['kind']}",
            "address": clause["address"]["kind"],
            "terms": [p.pattern for p in clause["terms"]],
            # уверенность в выводе (#80): значений у записи нет, довод — сам способ поиска (Р-108)
            "confidence": {"up": [], "medium": [], "low": [WORDS_ONLY]},
        },
    }

    if not MATRIX_BY_EMBEDDINGS:
        return finding
    # Попытка сопоставить с параметром Матрицы (#72). Только по флагу (см. MATRIX_BY_EMBEDDINGS)
    # и когда доступны эмбеддинги (ONNX) — на стеммах classify() слишком шумный для автоматики.
    try:
        from pipeline import matrix_map
        if matrix_map._onnx_available():
            cls = matrix_map.classify(
                finding["title"], section=section, evidence=evidence, top=3)
            if cls["matrix_scope"] == "MATRIX" and cls["parameter_code"]:
                finding["matrix_scope"] = "MATRIX"
                finding["parameter_code"] = cls["parameter_code"]
                finding["parameter_id"] = cls["parameter_id"]
                finding["criticality"] = cls["criticality"] or finding["criticality"]
                finding["needs_expert"] = cls["needs_expert"]
    except Exception as e:
        # classify() не должен ронять free_search, но и молчать нельзя: в контейнере
        # без dictionary/ импорт падал, и сопоставление не шло ни разу, а видно этого не было (#79)
        global _MATCH_WARNED
        if not _MATCH_WARNED:
            _MATCH_WARNED = True
            sys.stderr.write(f"free_search: сопоставление с Матрицей не выполнено: "
                             f"{type(e).__name__}: {e}\n")

    return finding
