"""Протоколы испытаний бетона как источник значения исполнительной документации. Задача #62.

Класс бетона в исполнительной документации называют два вида документов. Акт
освидетельствования цитирует документ о качестве смеси: «бетонной смеси … БСТ В25 П4
F200 W8» — это читает `elements.concrete_classes(as_built=True)` (#42). Протокол испытаний
лаборатории — таблица: строка называет конструкцию и её место («Секция 2 на отм. -5.850,
фундаментная плита в/о Г-Д/1-5»), даты бетонирования и испытания, показания прибора,
среднюю прочность в МПа, класс бетона и долю набранной прочности: «ДА 26,1 B30 87%».
Слова «бетон» рядом с классом в строке нет, и общий разбор такой класс отбрасывает —
иначе «В1» из обозначения вытяжной системы становилось бы классом. Здесь класс берётся
без бетонного окружения, но только на странице протокола и только там, где он стоит
при прочности: перед ним среднее значение в МПа («23,9 B 30»), за ним прочность или
доля в процентах («B30 | 87%», «В25 | 33,4 | 104 %»), либо он подписан словами
«по проекту» / «фактический».

## Какой это класс

Проверено по изображениям листов (#62, `bench/gold/recognized_values.jsonl`): в протоколах
лаборатории «Паскаль» колонка с «В 30» называется **«Класс бетона по проекту»**, а фактический
класс прочности Вф стоит числом левее — «23,9», «26,1», «32,7» — и рядом доля от проектного
в процентах. То есть отсюда берётся класс, на который конструкцию проверяли, а не класс,
который бетон набрал. Сверка такого значения с рабочей стадией отвечает на вопрос «ту ли
марку проверяла лаборатория», а не «из чего построено»; фактическую прочность система
не сравнивает с требуемой — это отдельный счёт по ГОСТ 18105 с партиями и коэффициентом
вариации (журнал незакрытых пунктов). Вф и доля видны инспектору во фрагменте строки.

## Как читается строка

Страница — протокол, если на ней есть «Протокол … №» или «протокол испытаний» и признаки
строк таблицы: «в/о» (в осях) или отметка «отм. ±N». Строки разделяются парой дат
«забетонировано | испытано» (дд.мм.гггг | дд.мм.гггг): заголовок строки «Секция 1 на
отм. +9.650» распознавание ставит перед датами, конструкцию — после. Если дат нет
(другая лаборатория), строкой считается отрезок от одной конструкции до следующей.

Элемент — из перечня `elements.ELEMENT_TYPES` и сокращения протоколов: «В.К.» — вертикальные
конструкции. Часть здания — по знаку отметки: «+» надземная, «−» подземная; эталон
организатора так и делит вертикальные конструкции и плиты. Строка без отметки для стены
или плиты значения не даёт: протокол проверяет одну конструкцию на одной отметке, и
приписать класс обеим частям здания было бы домыслом. Строка с двумя разными классами
(«по проекту B30, фактический B25») значения тоже не даёт: какой из них построенный,
без заголовка таблицы не сказать. Такие строки возвращаются отдельно, с причиной,
чтобы замер видел, что именно не прочитано.

## Что в корпусе

Октябрьская, 103: девять протоколов лаборатории «Паскаль» (июнь–июль 2026). Четыре
июньских — сканы с распознанным текстом, класс в строках читается. Пять июльских — PDF
с текстовым слоем сканера, в котором колонок «средняя прочность / класс / %» нет:
строки есть, класса нет. Правила берут слой, когда он не пуст (журнал незакрытых пунктов).
Два протокола по градуировке «ЭРКОН» класса не содержат вовсе — только прочность в МПа.
"""
import re

from . import elements

_PROTOCOL = re.compile(r"протокол\w*\s*(?:испытани\w*\s*)?(?:№|N[o°]\b)|протокол\w*\s+испытани", re.I)
_ROW_MARK = re.compile(r"\bв/о\b|\bв\s+осях\b|отм\.?\s*[+\-]\s?\d", re.I)
_DATES = re.compile(r"\d{2}\.\d{2}\.\d{4}\s*\|?\s*\d{2}\.\d{2}\.\d{4}")
# заголовок строки: «Секция 1 на отм. +9.650», «Паркинг на отм. -5.250»; распознавание
# теряет первую букву слова — «екция», «аркинг»
_HEADING = re.compile(r"(?:[СC]?екци[яи]|[Пп]?аркинг|[Кк]?орпус)\b[^|]{0,25}?отм|(?:с|на)\s+отм\.?\s*[+\-]\s?\d", re.I)
_ELEVATION = re.compile(r"отм\.?\s*([+\-])\s?\d|(?<!\w)([+\-])\s?\d{1,2}[,.]\d{3}")
_CLASS = re.compile(r"(?<![\w/])[BВ]\s?\.?\s?(\d{1,3}(?:[,.]5)?)(?![\d])")
_STRENGTH_BEFORE = re.compile(r"\d{2}[,.:]\d\s*\|?\s*$")            # «ДА 26,1 » — средняя прочность, МПа
_STRENGTH_AFTER = re.compile(r"^\s*\|\s*\d{2}[,.:]\d(?!\d)")            # «| 33,4» — прочность в следующей колонке
# «| 87%», «| 33,4 | 104 %» — доля проектной прочности, иногда через колонку прочности.
# Точка между классом и процентом не допускается: «…на сжатие B30. 17%» — это конец
# предложения и мусор распознавания рядом, а не колонка таблицы (#62)
_SHARE_AFTER = re.compile(r"^\s*\|?\s*(?:\d{2}[,.:]\d\s*\|?\s*)?(\d{2,3})\s?%")
# класс подписан словами: «по проекту B30 … фактический B25» — оба класса строки
_LABELLED_BEFORE = re.compile(
    r"(?:фактич\w*|по\s+проекту|проектн\w*)\s*(?:класс\w*\s*)?(?:бетона\s*)?"
    r"(?:по\s+прочности(?:\s+на\s+сжатие)?\s*)?[:\-–]?\s*$", re.I)
# «В.К.», «ВК.», «BK.» и «В К» перед «в/о» — вертикальные конструкции в протоколах «Паскаля»
_VK = re.compile(r"(?<![А-Яа-яA-Za-z])(?:[ВB]\s?\.\s?[КK]\.?|[ВB][КK]\.|[ВB]\s?[КK](?=\s*(?:в/о|во\s|в\s+осях)))")
VK_ELEMENT = "Вертикальные конструкции"
HEADING_BACK = 160      # заголовок строки ищется не дальше этого перед датами

# Бланки протоколов испытаний «СтройЭксперт» (#68)
_FORM_PLACE = re.compile(
    r"(?:(?:\d{1,2}\.?\s*)?[МM][еe][сc][тгr][оo]\s+проведения\s+испытани\w*[:\s])(.*?)"
    r"(?=(?:(?:\d{1,2}\.?\s*)?Наименование\s+материала|\d{1,2}\.?\s*Дата\b|\d{1,2}\.?\s*Методика|\d{1,2}\.?\s*Заключение|\Z))",
    re.I | re.S,
)
_FORM_MATERIAL = re.compile(
    r"(?:(?:\d{1,2}\.?\s*)?Наименование\s+материала[:\s])(.*?)"
    r"(?=(?:(?:\d{1,2}\.?\s*)?Дата\b|\d{1,2}\.?\s*Методика|\d{1,2}\.?\s*Заключение|\Z))",
    re.I | re.S,
)
_FORM_CONCLUSION = re.compile(
    r"(?:(?:\d{1,2}\.?\s*)?Заключение[:\s])(.*?)"
    r"(?=(?:Выполнил|Оформил|Протокол\s+не\s+может|\Z))",
    re.I | re.S,
)
_FORM_CONCRETE_CLASS = re.compile(r"(?:Бетон|класс\w*)\s+[BВ]\s?(\d{1,3}(?:[,.]5)?)", re.I)
_FORM_CONCLUSION_PROJECT_CLASS = re.compile(
    r"проектн\w*\s+класс\w*(?:\s+бетона)?(?:\s+по\s+прочности)?(?:\s+на\s+сжатие)?\s+[BВ]\s?(\d{1,3}(?:[,.]5)?)", re.I)
_FORM_AGE = re.compile(r"возрасте\s+(\d+)\s+суток", re.I)
_FORM_VF = re.compile(r"(?:В\s?[фoо]|B\s?[фoо])\s*[=\-–—]+\s*([\d,.\-]+)", re.I)
_FORM_SHARE = re.compile(r"(\d{2,3})(?:\s*-\s*(\d{2,3}))?\s*%")


def _clean(flat):
    """Мягкий перенос сканера и типографские минусы — обычный минус: «отм. \xad5.250»."""
    return flat.replace("\xad", "-").replace("−", "-").replace("–", "-")


def _is_stroyexpert_form(flat):
    return bool(_FORM_PLACE.search(flat) and (_FORM_MATERIAL.search(flat) or _FORM_CONCLUSION.search(flat)))


def is_protocol_page(flat):
    """Страница протокола испытаний: заголовок или колонтитул протокола и строки таблицы или бланк."""
    flat = _clean(flat)
    return bool(_PROTOCOL.search(flat) and (_ROW_MARK.search(flat) or _FORM_PLACE.search(flat)))


def rows(flat):
    """Строки таблицы протокола на странице: отрезки текста, по одной конструкции в каждом."""
    flat = _clean(flat)
    anchors = [m.start() for m in _DATES.finditer(flat)]
    if anchors:
        starts, prev = [], 0
        for a in anchors:
            head = _HEADING.search(flat, max(prev, a - HEADING_BACK), a)
            starts.append(head.start() if head else a)
            prev = a
        bounds = starts + [len(flat)]
        return [flat[bounds[i]:bounds[i + 1]] for i in range(len(starts))]
    # дат нет — от одной конструкции до следующей
    marks = sorted({s for s, _e, _n, _z in elements.element_mentions(flat)} | {m.start() for m in _VK.finditer(flat)})
    if not marks:
        return []
    starts = [max(0, marks[0] - 80)] + marks[1:]
    bounds = starts + [len(flat)]
    return [flat[bounds[i]:bounds[i + 1]] for i in range(len(starts))]


def row_elements(row):
    """Типы элементов, названные в строке: (тип, нужна ли зона), без повторов."""
    out = []
    for s, e, name, zoned in elements.element_mentions(row):
        if elements._NOT_STRUCTURAL.search(row[max(0, s - 30):e + 10]):
            continue
        if (name, zoned) not in out:
            out.append((name, zoned))
    if _VK.search(row) and (VK_ELEMENT, True) not in out:
        out.append((VK_ELEMENT, True))
    return out


def row_classes(row):
    """Классы бетона строки, стоящие при прочности: [(число, доля прочности или None)]."""
    out = []
    for m in _CLASS.finditer(row):
        number = float(m.group(1).replace(",", "."))
        if number not in elements.CONCRETE_CLASSES:
            continue
        # Окно назад — 30 знаков: подпись «по проекту» / «фактический» стоит вплотную к классу
        # в ячейке таблицы. Дальше не смотрим нарочно: в заключении протокола «СтройЭксперта»
        # («…соответствует 73 % от проектного класса бетона по прочности на сжатие B35») класс
        # стоит через 37 знаков после подписи, и окно пошире открывает 120 строк на Речникове —
        # объекте с эталоном организатора. Эти значения сперва надо сверить глазами (#68).
        before, after = row[max(0, m.start() - 30):m.start()], row[m.end():m.end() + 28]
        share = _SHARE_AFTER.match(after)
        if not (_STRENGTH_BEFORE.search(before[-14:]) or _STRENGTH_AFTER.match(after) or share
                or _LABELLED_BEFORE.search(before)):
            continue
        out.append((number, int(share.group(1)) if share else None))
    return out


def row_zone(row):
    """Часть здания по знакам отметок строки: все «+» — надземная, все «−» — подземная."""
    signs = {m.group(1) or m.group(2) for m in _ELEVATION.finditer(row)}
    if signs == {"+"}:
        return elements.ABOVEGROUND
    if signs == {"-"}:
        return elements.UNDERGROUND
    return None


def _snippet(row):
    return " ".join(row.split())[:220]


def _parse_stroyexpert_form(flat):
    """Разбор бланка протокола испытаний ООО «СтройЭксперт» (#68).

    В отличие от таблицы «Паскаля», бланк содержит один протокол на лист:
    - п. 5 («Место проведения испытаний») — конструкция и отметка со знаком (+ надземная, - подземная);
    - п. 6 («Наименование материала») — проектный класс бетона («Бетон B30»);
    - п. 13 («Заключение») — возраст бетона, фактический класс Вф и процент набора прочности.
    """
    p_m = _FORM_PLACE.search(flat)
    if not p_m:
        return None
    m_m = _FORM_MATERIAL.search(flat)
    c_m = _FORM_CONCLUSION.search(flat)
    if not m_m and not c_m:
        return None
    place_text = p_m.group(1).strip()
    mat_text = m_m.group(1).strip() if m_m else ""
    conc_text = c_m.group(1).strip() if c_m else ""

    names = row_elements(place_text)
    if not names:
        return [], [("конструкция в строке не прочитана", _snippet(place_text or flat))]
    if len(names) > 1:
        return [], [("в строке несколько конструкций", _snippet(place_text))]
    name, zoned = names[0]
    zone = row_zone(place_text) if zoned else None
    loc = elements.location_name(name, zone)
    if loc is None:
        return [], [("часть здания не названа: отметки в строке нет", _snippet(place_text))]

    # Проектный класс бетона: из п. 6 или из фразы заключения
    cls_m = _FORM_CONCRETE_CLASS.search(mat_text)
    if not cls_m and conc_text:
        cls_m = _FORM_CONCLUSION_PROJECT_CLASS.search(conc_text)
    if not cls_m:
        cls_m = _CLASS.search(mat_text)
    if not cls_m:
        return [], [("класс в строке не прочитан", _snippet(mat_text or conc_text or flat))]

    number = float(cls_m.group(1).replace(",", "."))
    if number not in elements.CONCRETE_CLASSES:
        return [], [("класс в строке не прочитан", _snippet(mat_text or conc_text))]
    if number < elements.MIN_STRUCTURAL_CLASS:
        return [], [("класс ниже конструкционного — подготовка или стяжка", _snippet(mat_text or conc_text))]

    age_days = None
    m_age = _FORM_AGE.search(conc_text)
    if m_age:
        age_days = int(m_age.group(1))

    vf = None
    m_vf = _FORM_VF.search(conc_text)
    if m_vf:
        vf = m_vf.group(1).rstrip(",.; ")

    share = None
    m_sh = _FORM_SHARE.search(conc_text)
    if m_sh:
        s1 = int(m_sh.group(1))
        s2 = int(m_sh.group(2)) if m_sh.group(2) else None
        share = s1 if (s2 is None or s1 == s2) else f"{s1}-{s2}"

    snippet = _snippet(f"{place_text} | {mat_text} | {conc_text}" if mat_text or conc_text else place_text)
    cand = {
        "location": loc,
        "binding": "CLAUSE",
        "value": number,
        "raw": elements.class_label(number),
        "snippet": snippet,
        "source": "PROTOCOL",
    }
    if share is not None:
        cand["share"] = share
    if vf is not None:
        cand["vf"] = vf
    if age_days is not None:
        cand["age_days"] = age_days
    return [cand], []


def protocol_classes(flat):
    """Пары «элемент — класс» из строк протокола: (кандидаты, непрочитанные строки).

    Кандидат — как у `elements.concrete_classes`: локация, привязка CLAUSE (конструкция
    названа в той же строке), значение, метка, фрагмент; поле `source` — PROTOCOL.
    Значение — класс из колонки протокола (у «Паскаля» это «класс бетона по проекту»).
    Непрочитанная строка — (причина, фрагмент): строка без конструкции, без класса,
    без отметки у стены или плиты, с двумя классами, с двумя конструкциями.
    """
    if not is_protocol_page(flat):
        return [], []
    flat = _clean(flat)
    if _is_stroyexpert_form(flat):
        parsed = _parse_stroyexpert_form(flat)
        if parsed is not None:
            return parsed
    found, skipped = [], []
    for row in rows(flat):
        names = row_elements(row)
        classes = row_classes(row)
        if not names and not classes:
            continue                       # заголовок таблицы, подпись, шапка — не строка
        if not names:
            skipped.append(("конструкция в строке не прочитана", _snippet(row)))
            continue
        if not classes:
            skipped.append(("класс в строке не прочитан", _snippet(row)))
            continue
        if len(names) > 1:
            skipped.append(("в строке несколько конструкций", _snippet(row)))
            continue
        values = sorted({c[0] for c in classes})
        if len(values) > 1:
            skipped.append(("в строке два разных класса — по проекту и фактический не различить", _snippet(row)))
            continue
        number = values[0]
        if number < elements.MIN_STRUCTURAL_CLASS:
            skipped.append(("класс ниже конструкционного — подготовка или стяжка", _snippet(row)))
            continue
        name, zoned = names[0]
        zone = row_zone(row) if zoned else None
        loc = elements.location_name(name, zone)
        if loc is None:
            skipped.append(("часть здания не названа: отметки в строке нет", _snippet(row)))
            continue
        share = next((s for _n, s in classes if s is not None), None)
        found.append({"location": loc, "binding": "CLAUSE", "value": number, "raw": elements.class_label(number),
                      "snippet": _snippet(row), "source": "PROTOCOL", **({"share": share} if share is not None else {})})
    return found, skipped
