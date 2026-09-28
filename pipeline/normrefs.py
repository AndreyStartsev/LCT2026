"""Нормативные ссылки: разбор, нечёткое сравнение и перечень по корпусу. Задача #18.

Во всех восьми актах освидетельствования Октябрьской в перечне технических регламентов
стоит «СП 70.1330.2012», хотя свод правил называется СП 70.13330.2012: пропущена цифра,
и ошибка одинаковая во всех актах. По корпусу верная запись встречается 529 раз, с опечаткой —
18. Точное сравнение номера дало бы ложное расхождение на ровном месте, поэтому номер
сравнивается с допуском на одну пропущенную или лишнюю цифру.

Год редакции сравнивается точно: «СП 70.13330.2012» и «СП 70.13330.2017» — разные редакции
одного документа, и это настоящий кандидат в нарушения, а не опечатка.

Допуск только на вставку или пропуск цифры, не на замену: «СП 70.13330» и «СП 71.13330» —
разные своды правил («Несущие и ограждающие конструкции» и «Изоляционные и отделочные
покрытия»), и замена одной цифры в номере меняет документ, а не исправляет опечатку.

И только не в первом сегменте номера. Первый сегмент — номер самого документа, остальные —
серия: СП 1.13130 «Эвакуационные пути и выходы», СП 10.13130 «Внутренний противопожарный
водопровод» и СП 12.13130 «Определение категорий помещений» отличаются одной цифрой в первом
сегменте и все существуют, а 13130 у них общая. Поэтому лишняя цифра в серии (13330 против
1330) считается опечаткой, а в номере документа — другим документом.
"""
import re
import unicodedata

# Латинские двойники кириллических букв: в тексте чертежей «СП» попадается с латинской C,
# «ГОСТ» — с латинскими O и T. Значения не переписываются, приведение только для сравнения.
_HOMOGLYPH = str.maketrans("ABCEHKMOPTXYacehopxy", "АВСЕНКМОРТХУасенорху")

# Вид документа. Порядок важен: «ГОСТ Р» и «ТР ТС» разбираются раньше «ГОСТ» и «ТР»,
# «СТО НОСТРОЙ» — раньше «СТО». Виды, которых в корпусе нет, не добавляются.
KINDS = ("ГОСТ Р", "ГОСТ", "СНиП", "СанПиН", "СП", "СТО НОСТРОЙ", "СТО", "ОСТ", "ТР ТС",
         "МГСН", "ВСН", "ПУЭ", "НПБ", "ППБ", "РД", "ТУ")
_KIND_ALIAS = {"СНИП": "СНиП", "САНПИН": "СанПиН", "ГОСТР": "ГОСТ Р"}
# Разделитель перед годом редакции: у свода правил и стандарта организации точка
# (СП 70.13330.2012), у ГОСТ, СНиП и СанПиН — дефис (ГОСТ 34028-2016), у регламента
# Таможенного союза — дробь (ТР ТС 004/2011).
_YEAR_SEP = {"СП": ".", "СТО": ".", "СТО НОСТРОЙ": ".", "ТР ТС": "/"}

_KIND_RE = "|".join(k.replace(" ", r"\s*") for k in KINDS)
# Ссылка целиком: вид, номер, при наличии — год редакции.
#   ГОСТ 34028-2016, ГОСТ Р 21.101-2020, СП 70.13330.2012, СНиП 12-03-2001, СанПиН 2.1.3684-21
# Перед видом не должно быть буквы, цифры или дефиса: в шифре тома «ЖС-РД-270121-П-КР»
# «РД» — стадия документа, а не руководящий документ.
REF_RE = re.compile(
    rf"(?<![\w-])(?P<kind>{_KIND_RE})"
    r"(?![А-ЯЁа-яёA-Za-z])\s*[-–—]?\s*"
    r"(?P<number>\d+(?:[.\-/]\d+)*)",
    re.IGNORECASE,
)
# Год редакции: хвост номера. Четыре цифры с 19 или 20 — год целиком, две цифры после
# дефиса — сокращённый год («ГОСТ 3262-75» 1975, «СанПиН 2.1.3684-21» 2021).
_YEAR_TAIL = re.compile(r"^(?P<number>.*?)[.\-/](?P<year>(?:19|20)\d{2}|\d{2})$")


def _fold(text):
    return unicodedata.normalize("NFC", text or "").translate(_HOMOGLYPH)


def _kind(raw):
    key = re.sub(r"\s+", "", _fold(raw)).upper()
    return _KIND_ALIAS.get(key, next((k for k in KINDS if re.sub(r"\s+", "", k).upper() == key), key))


def _year(value):
    """Год редакции четырьмя цифрами: «75» — это 1975, «21» — 2021."""
    n = int(value)
    if n >= 100:
        return n
    return 2000 + n if n < 30 else 1900 + n


def split_year(number):
    """Номер и год редакции по хвосту номера: «70.13330.2012» -> («70.13330», 2012)."""
    m = _YEAR_TAIL.match(number)
    if not m:
        return number, None
    # «12-03» у СНиП 12-03-2001 — часть номера, а не год: год отделяется только если
    # после него ничего нет, и в номере остаётся хотя бы одна цифра
    return m.group("number"), _year(m.group("year"))


def parse(text):
    """Нормативные ссылки из текста в порядке появления.

    Возвращает записи {kind, number, year, label, raw, start}. У неполной ссылки
    («СП 70.13330» без года) year равен None: сравнение такой ссылки по редакции невозможно.
    """
    out = []
    for m in REF_RE.finditer(_fold(text or "")):
        number, year = split_year(m.group("number"))
        kind = _kind(m.group("kind"))
        out.append({
            "kind": kind,
            "number": number,
            "year": year,
            "label": label(kind, number, year),
            "raw": m.group(0).strip(),
            "start": m.start(),
        })
    return out


def label(kind, number, year):
    """Ссылка так, как её пишут: «СП 70.13330.2012», «ГОСТ 34028-2016», «ТР ТС 004/2011»."""
    return f"{kind} {number}" + (f"{_YEAR_SEP.get(kind, '-')}{year}" if year else "")


def digits(number):
    """Цифры номера без разделителей: точки, дефисы и дроби записывают по-разному."""
    return re.sub(r"\D", "", number or "")


def segments(number):
    """Сегменты номера: «70.13330» -> [«70», «13330»], «12-03» -> [«12», «03»]."""
    return [s for s in re.split(r"[.\-/]", number or "") if s]


def _digit_inserted(short, long_):
    return len(long_) - len(short) == 1 and any(
        long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def one_digit_apart(a, b):
    """Номера отличаются одной лишней цифрой в серии, а не в номере документа.

    Сегменты должны совпасть все, кроме одного, и этот один не первый: разница в первом
    сегменте — другой документ (СП 1.13130 и СП 10.13130 существуют оба).
    """
    left, right = segments(a), segments(b)
    if len(left) != len(right) or not left:
        return False
    diff = [i for i, (x, y) in enumerate(zip(left, right)) if x != y]
    if len(diff) != 1 or diff[0] == 0:
        return False
    i = diff[0]
    short, long_ = sorted((left[i], right[i]), key=len)
    return _digit_inserted(short, long_)


def same_document(a, b):
    """Один и тот же документ: вид совпал, номер совпал точно или с одной цифрой разницы."""
    if a["kind"] != b["kind"]:
        return False
    return digits(a["number"]) == digits(b["number"]) or one_digit_apart(a["number"], b["number"])


def compare(a, b):
    """Как соотносятся две ссылки.

    verdict: EXACT — одна и та же запись; TYPO — тот же документ и та же редакция, номер
    записан с разницей в одну цифру; OTHER_EDITION — тот же документ, редакции разные;
    NO_EDITION — тот же документ, но у одной из ссылок года нет и сравнить редакции нельзя;
    OTHER_DOCUMENT — разные документы.
    """
    if not same_document(a, b):
        return {"same_document": False, "same_edition": False, "verdict": "OTHER_DOCUMENT"}
    typo = digits(a["number"]) != digits(b["number"])
    if a["year"] is None or b["year"] is None:
        verdict = "NO_EDITION"
        same_edition = None
    elif a["year"] == b["year"]:
        verdict = "TYPO" if typo else "EXACT"
        same_edition = True
    else:
        verdict = "OTHER_EDITION"
        same_edition = False
    return {"same_document": True, "same_edition": same_edition, "verdict": verdict, "typo": typo}


def inventory(entries):
    """Перечень ссылок по корпусу с догадкой об опечатках.

    entries — записи {label, kind, number, year, object_id, source}. Считаются упоминания,
    объекты и источники. Записи одного вида, номера которых отличаются одной цифрой,
    сводятся в пару: реже встречающаяся помечается `typo_of` в пользу частой, а `typo_hint`
    говорит, цифра пропущена или лишняя. Догадка не переписывает данные — она попадает
    в перечень, чтобы её проверил человек: ГОСТ 21.110 и ГОСТ 21.1101 отличаются одной
    цифрой и существуют оба.

    Номер, который встречается в корпусе больше чем в одной редакции, опечаткой не считается:
    у опечатки год один — её переписывают вместе с ним.
    """
    refs = {}
    for e in entries:
        key = (e["kind"], e["number"], e["year"])
        ref = refs.setdefault(key, {"kind": e["kind"], "number": e["number"], "year": e["year"],
                                    "label": label(e["kind"], e["number"], e["year"]),
                                    "document": label(e["kind"], e["number"], None),
                                    "mentions": 0, "objects": set(), "sources": set(),
                                    "typo_of": None, "typo_hint": None})
        ref["mentions"] += 1
        if e.get("object_id"):
            ref["objects"].add(e["object_id"])
        if e.get("source"):
            ref["sources"].add(e["source"])
    years = {}
    for r in refs.values():
        years.setdefault((r["kind"], digits(r["number"])), set()).add(r["year"])
    order = sorted(refs.values(), key=lambda r: (-r["mentions"], r["label"]))
    for i, rare in enumerate(order):
        if len(years[(rare["kind"], digits(rare["number"]))]) > 1:
            continue
        for common in order[:i]:
            if (rare["kind"] == common["kind"] and rare["year"] == common["year"]
                    and one_digit_apart(rare["number"], common["number"])
                    and common["mentions"] > rare["mentions"]):
                rare["typo_of"] = common["label"]
                rare["typo_hint"] = ("пропущена цифра" if len(digits(rare["number"])) < len(digits(common["number"]))
                                     else "лишняя цифра")
                # у записи с опечаткой документ тот же, что у частой записи: по полю
                # `document` редакции одного документа собираются вместе
                rare["document"] = common["document"]
                break
    return [dict(r, objects=sorted(r["objects"]), sources=sorted(r["sources"])) for r in order]
