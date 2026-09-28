"""Квартирография — число квартир по типам (PZ-011). Задача #138.

Специалист во втором круге (U-flat-mix, Полярная 16) признал нарушением смену распределения
квартир по типам, с оговоркой: «возможно, даже не нарушение, а изменение, не оформленное должным
образом». В третьем круге черновик принят как есть (Р-91). Типы — по терминологии норм:
квартира-студия отдельно, дальше по числу комнат.

Источники:
- ТЭП записки ПД: «Общее количество квартир 422 шт. в том числе: - квартиры-студии 54 шт.
  - однокомнатных 184 шт. …»;
- таблица «Квартирография жилого дома. N секция» в АР: строки «1- | однокомнатная квартира | ТИП 1 |
  1.2.1 | 17,29 | 37,41 | 40,78 | 23», количество — первое целое после площадей, по секции «Итого».

Тип строки — по названию («студия», «однокомнатная», «1-»), а без названия — по марке («Ст.1.1.1» —
студия, «2.1» — двухкомнатная). Если название и марка расходятся — в РД Полярной 16 изм.5 квартиры
с маркой «Ст.» названы однокомнатными, — это отмечается: так выглядит переименование студий.

Четвёртый круг (26.09, R4-Q-PZ-011, Р-108): «отдельного юридического понятия квартира-студия не
существует; это не изменение квартирографии, а уточнение, не являющееся нарушением». Поэтому стадии
сравниваются по числу комнат, студии вместе с однокомнатными (`by_rooms`); деление между ними идёт
в пояснение. Перенумерация марок без смены числа комнат — тоже не нарушение: марки не сравниваются.
"""
import re

ORDER = ["studio", "1", "2", "3", "4", "5"]
NAME = {"studio": "студии", "1": "однокомнатные", "2": "двухкомнатные", "3": "трёхкомнатные",
        "4": "четырёхкомнатные", "5": "пятикомнатные"}
WORDS = [("studio", r"студи"), ("1", r"однокомнатн"), ("2", r"двухкомнатн"), ("3", r"тр[её]хкомнатн"),
         ("4", r"четыр[её]хкомнатн"), ("5", r"пятикомнатн")]
WORD_RE = [(t, re.compile(p, re.I)) for t, p in WORDS]

MARK = re.compile(r"^(Ст\.?\s?)?(\d)(?:\.\d){0,2}$")
AREA = re.compile(r"^\d+,\d+$")
COUNT = re.compile(r"^\d{1,4}$")
TABLE = re.compile(r"Квартирограф\w*\s+жил\w*\s+дом\w*\.?\s*(?:\d+\s*секци\w*)?", re.I)
TOTAL = re.compile(r"Итого\s*\n(?:\s*[\d\s]+,\d+\s*\n)+\s*(\d{1,4})\s*$", re.I | re.M)

TEP_HEAD = re.compile(r"Общее\s+количество\s+квартир\s*[:\n ]*(\d[\d ]*)\s*шт", re.I)
TEP_ITEM = re.compile(r"-\s*(?:квартир\w*-)?(студи\w*|одно\w*|двух\w*|тр[её]х\w*|четыр[её]х\w*|пяти\w*)[^\n]*?\n?\s*(\d{1,4})\s*шт",
                      re.I)
# «однокомнатных/ в том числе с кухней-нишей 184 шт. 69 шт.» — второе число «в том числе», не отдельный тип
TEP_WORD = {"студи": "studio", "одно": "1", "двух": "2", "тре": "3", "трё": "3", "чет": "4", "пят": "5"}

# РД ссылается на стадию ПД или заключение, которого в пакете может не быть: изменение, возможно,
# оформлено там — решение за инспектором (специалист, U-flat-mix)
PD_REFERENCE = re.compile(r"приведен\w*\s+в\s+соответстви\w*\s+со?\s+стади\w*\s+ПД[^\n]{0,120}|"
                          r"получивш\w*\s+положительн\w*\s+заключени\w*[^\n]{0,80}", re.I)


def type_of(label, mark):
    """Тип квартиры строки: по названию, иначе по марке. Возвращает (тип, тип по марке)."""
    by_mark = None
    m = MARK.match(mark or "")
    if m:
        by_mark = "studio" if m.group(1) else m.group(2)
    for t, pattern in WORD_RE:
        if pattern.search(label or ""):
            return t, by_mark
    m = re.search(r"(?<!\d)([1-5])\s*-\s*$|^\s*([1-5])\s*-", label or "")
    if m:
        return m.group(1) or m.group(2), by_mark
    return by_mark, by_mark


def table_rows(text):
    """Строки таблицы квартирографии: [{type, mark, count, label, renamed}]."""
    if not TABLE.search(text):
        return []
    tokens = [t.strip() for t in text.splitlines() if t.strip()]
    rows, start = [], 0
    for i, tok in enumerate(tokens):
        if tok.lower().startswith(("кол-во", "квартирограф")):
            start = i + 1
            continue
        if not MARK.match(tok) or i + 4 >= len(tokens):
            continue
        j = i + 1
        while j < len(tokens) and AREA.match(tokens[j]):
            j += 1
        if j - i - 1 < 3 or j >= len(tokens) or not COUNT.match(tokens[j]):
            continue
        label = " ".join(tokens[start:i])
        kind, by_mark = type_of(label, tok)
        if kind:
            rows.append({"type": kind, "mark": tok, "count": int(tokens[j]), "label": label,
                         "renamed": bool(by_mark and by_mark != kind)})
        start = j + 1
    return rows


def tep_counts(text):
    """Число квартир по типам из ТЭП: {тип: число, "total": всего} или {}."""
    head = TEP_HEAD.search(text)
    if not head:
        return {}
    out = {"total": int(head.group(1).replace(" ", ""))}
    for m in TEP_ITEM.finditer(text[head.end(): head.end() + 700]):
        word = m.group(1).lower()
        kind = next((t for prefix, t in TEP_WORD.items() if word.startswith(prefix)), None)
        if kind and kind not in out:
            out[kind] = int(m.group(2))
    return out if len(out) > 1 else {}


def show(counts):
    """«студии 54; однокомнатные 184; двухкомнатные 123; трёхкомнатные 61 (всего 422)»."""
    parts = [f"{NAME[t]} {counts[t]}" for t in ORDER if counts.get(t)]
    total = counts.get("total") or sum(counts.get(t, 0) for t in ORDER)
    return "; ".join(parts) + f" (всего {total})"


def changes(pd, rd):
    """Типы, у которых число квартир изменилось: [(тип, ПД, РД)]."""
    return [(t, pd.get(t, 0), rd.get(t, 0)) for t in ORDER if pd.get(t, 0) != rd.get(t, 0)]


def by_rooms(counts):
    """Число квартир по числу комнат: студии — вместе с однокомнатными (R4-Q-PZ-011)."""
    out = {t: v for t, v in counts.items() if t != "studio"}
    if counts.get("studio"):
        out["1"] = out.get("1", 0) + counts["studio"]
    return out
