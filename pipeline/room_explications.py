"""Экспликации помещений между стадиями: пропавшее помещение, площадь, категория. Задача #56.

Экспликации читаются постранично по стадиям (`build/<объект>/rooms_pages.jsonl`, #46): номер,
наименование, площадь, категория по пожарной опасности, файл, страница. По замеру #55 это
единственный источник по помещениям, у которого обе стадии есть у всех пяти объектов разработки.
Параметра Матрицы про площадь или категорию помещения нет, поэтому расхождения идут гипотезами
свободного поиска (`matrix_scope: FREE_SEARCH`, `needs_expert`), как тёплые полы (#31).

Три вида расхождений, по номерам, у которых наименование в двух стадиях одно (`room_names.same`):

- **помещение пропало** — номер есть в экспликациях проекта и нет ни в одной экспликации рабочей
  стадии, хотя на одной странице рабочей экспликации стоят его соседи по номеру с обеих сторон:
  экспликации рабочей стадии почти всегда неполны (Речников: 46 номеров против 343 в проекте),
  и без соседей «пропажа» — просто незакрытый лист;
- **площадь уменьшена** — площадь в рабочей стадии меньше проектной больше чем на `AREA_TOLERANCE`;
- **категория изменена** — категория по взрывопожарной и пожарной опасности в стадиях разная.

Порог площади — замером, не на глаз (Д-54). Шум разбора меряется по одному и тому же помещению
с одним наименованием на разных страницах одного тома: на Тюменской-5 (1 464 пары) и Алтуфьевском
(284 пары) он равен нулю — площадь читается одинаково. Разброс между томами одной стадии — это уже
не шум, а переиздания: на Тюменской-5 лаборантская 339 в одном томе проекта 21,9 м², в другом 18,0,
и рабочая стадия повторяет второе. Поэтому порог расхождения между стадиями — 5 % (меньше инспектор
вряд ли сочтёт существенным; вопрос ему задан). Площадь стадии — значение, на котором сходится
большинство её томов (не меньше `MAJORITY` томов с площадью): на Тюменской-5 у сорока помещений
один том проекта (F0174) называет площадь не ту, что шесть остальных, и большинство решает.
Без большинства стадия сама с собой не согласна, и такой номер в сравнение по площади не идёт.
На объектах, где номера повторяются по этажам (Новослободская, Речников, Октябрьская: «1 Жилая»
на каждом этаже), это же условие выключает сравнение по площади само собой.

Пропажа помещения не объявляется, если проект сам с собой не согласен: в каком-то томе проекта соседи
номера стоят на одной странице, а самого номера нет. На Тюменской-5 помещения 105, 126 и 128 есть
только в томе сетей связи, а действующий том АР, как и РД, их уже объединил во «130 Вестибюль… в том
числе» (#114) — это переиздание проекта, а не расхождение стадий.

Пропажа помещения проверяется по тексту страницы рабочей экспликации: разбор экспликаций теряет
часть строк (Тюменская-5 — 13 %), и «247 Кладовая инвентаря» на листе есть, хотя в разобранных
строках его нет. Если номер с наименованием стоит в тексте — это не пропажа, а незакрытая строка.

Экспликации заменённых редакций (`revision_status: SUPERSEDED`, #10) в сравнение не идут. У объекта
с несколькими выпусками одного тома голосуют все выпуски, и большинство может оказаться за старым:
у Речникова строк экспликаций заменённых томов проекта больше, чем действующих (2256 против 2107).
Полярная 25 (ДОО) показывает, чем это кончается: пищеблок перепланирован корректировкой ПД 2025
(пом. 145: 11,8 → 13,7 м²), а рабочая стадия осталась по ПД 2022 (#100).

Если стадии нумеруют помещения по-разному (`room_names.refusal`, #46) — отказ с причиной, гипотез
нет. Если помещений с расхождением одного вида много, запись одна на вид: сорок гипотез «площадь
изменилась» инспектору не нужны, ему нужен перечень.

Если в рабочей стадии помещение разделено — рядом с номером появились подномера того же помещения
(«002.1 Коридор»), которых в проекте нет, — площадь проекта сравнивается с суммой частей (#114).

Гипотезы помечены `for_submission: false`: в файл сдачи они не идут, пока инспектор не взял их
в кандидаты (ТЗ 9.2), — лишняя гипотеза в сдаче стоит балла, а подтверждённых точек такого
вида в эталоне нет. Исключение — вид, который специалист подтвердил нарушением: площади
помещений, где рабочая стадия не обновлена после корректировки проекта. Его в сдачу пускает
`pipeline/specialist.py` (Р-86).

**Рабочая стадия не обновлена после корректировки проекта (#111).** Корректировка проекта меняет
площадь или категорию помещения, а часть томов рабочей стадии остаётся по прежней редакции проекта.
У ДОО на Полярной 25 корректировка ПД 2025 перепланировала пищеблок (пом. 145: 11,8 → 13,7 м²):
том интерьеров АИ2 повторяет 13,7, а АР1 изм. 3 «к 15.09.2025» и тома инженерных разделов — 11,8
из ПД 2022. Большинства у рабочей стадии тут нет или оно за старым значением, и обычная сверка
либо молчит, либо пишет «площадь уменьшена», не называя причины. Поэтому для номера, у которого
действующая и заменённая редакции проекта расходятся больше порога, тома рабочей стадии делятся:
повторяющие заменённую редакцию — не обновлены, повторяющие действующую — обновлены. Если
необновлённые есть, это одна гипотеза на объект с перечнем помещений и томов; обычная гипотеза
по такому номеру не пишется. Так же — для категории: у ДОО электрощитовая 123 в ПД 2022 — В4,
в ПД 2025 — В3, в АР1 рабочей стадии — В3, в томах ЭОМ, СС, ПС — В4.

**Поэтажная сверка (#114).** Там, где номера на каждом этаже начинаются заново (Алтуфьевское:
«1 Зона мойки» на первом этаже, «1 Тех.помещение» на антресоли, «1 Склад» на втором), сверка
по номеру отказывает — одному номеру объекта в стадиях отвечают разные помещения. Тогда
экспликации сравниваются как последовательности: этаж берётся из заголовка таблицы
(«Спецификация помещений 1-го этажа»), том проекта — только того же шифра, что тома рабочей
стадии (у Алтуфьевского три тома АР проекта, и лишь один из них по проекту 2254266, как РД),
строки выравниваются по наименованиям. Помещение на своём месте последовательности с той же
площадью, но с другим наименованием — назначение изменено: «23 Помещение, 19,41 м²» → «22 Комната
отдыха, 19,62 м²». Так размечен кандидат организатора ALT79B-V01. Если один том рабочей стадии
назначение сменил, а другой повторяет проект, это сказано в пояснении: рабочая стадия сама
с собой не согласна (как пищеблок ДОО, #111).
"""
import collections
import difflib
import re

from pipeline import room_names

STAGES = {"PD": "PD", "RD": "RD", "RD_ID_MIXED": "RD"}
AREA_TOLERANCE = 0.05        # доля проектной площади; обоснование — в докстринге и Д-54
MAJORITY = 0.6               # доля томов стадии, называющих одну площадь, с которой она — площадь стадии
NEIGHBOUR_GAP = 3            # соседи пропавшего номера стоят не дальше стольких номеров
MAX_SINGLE = 5               # больше расхождений одного вида — одна запись на вид, а не на помещение
MAX_EVIDENCE = 3
CRITICALITY = "Существенное (предписание) — требует утверждения"

KINDS = {
    "missing": ("FREE-AR-ROOM-MISSING", "MISSING_DESIGN_ELEMENT",
                "Помещение проекта не найдено в экспликациях рабочей документации"),
    "area": ("FREE-AR-ROOM-AREA", "VALUE_DECREASE",
             "Площадь помещения в рабочей документации меньше проектной"),
    "category": ("FREE-PB-ROOM-CATEGORY", "VALUE_MISMATCH",
                 "Категория помещения по пожарной опасности изменена между стадиями"),
    "stale": ("FREE-AR-RD-NOT-UPDATED", "VALUE_MISMATCH",
              "Рабочая документация частично не обновлена после корректировки проекта"),
}


def norm_number(number):
    """Ключ номера для сверки стадий: ведущие нули целого номера не значат — «0010», «010» и «10» одно
    помещение (Тюменская-5: проект пишет «0010», рабочая стадия «010»). Составные номера («1.01»)
    не трогаются: там ноль может быть значащим (#41)."""
    number = (number or "").strip()
    if re.fullmatch(r"0+\d+[а-яa-z]?", number):
        return number.lstrip("0")
    return number


def _num_key(number):
    """Числовая часть номера для соседства: «1.01» → (1, 1), «12а» → (12,)."""
    return tuple(int(x) for x in re.findall(r"\d+", number or ""))


def _series(number):
    """Серия номера: всё, кроме последнего числа, — «1.01» и «1.02» соседи, «1.01» и «2.01» нет."""
    key = _num_key(number)
    return (re.sub(r"\d+", "#", number or ""), key[:-1]) if key else None


class Explications:
    """Экспликации объекта по стадиям: номер → записи страниц."""

    def __init__(self, rows):
        self.by_stage = {"PD": collections.defaultdict(list), "RD": collections.defaultdict(list)}
        self.shown_number = {}
        for r in rows:
            stage = STAGES.get(r.get("stage"))
            if stage and r.get("labeled") and r.get("number"):
                key = norm_number(r["number"])
                self.by_stage[stage][key].append(r)
                self.shown_number.setdefault((stage, key), r["number"])

    def numbers(self, stage):
        return set(self.by_stage[stage])

    def pages(self, stage, number):
        seen, out = set(), []
        for r in self.by_stage[stage].get(number, []):
            key = (r["file_id"], r["pdf_page_number"])
            if key not in seen:
                seen.add(key)
                out.append(key)
        return out

    def areas(self, stage, number, words):
        """Площади номера в стадии по записям с тем же наименованием: [(площадь, файл, страница)]."""
        out = []
        for r in self.by_stage[stage].get(number, []):
            if r.get("area_m2") and room_names.same(room_names.name_words(r.get("name")), words) is not False:
                out.append((float(r["area_m2"]), r["file_id"], r["pdf_page_number"]))
        return out

    def has_area(self, stage, number):
        return any(r.get("area_m2") for r in self.by_stage[stage].get(number, []))

    def categories(self, stage, number, words=None):
        """Категории номера в стадии по записям с тем же наименованием: {категория: [(файл, страница)]}.

        Наименование сверяется: на Полярной 16 номер 2.3 носят тамбур-шлюз, вестибюль, машинное
        помещение и технический этаж, и категории чужих помещений сравнивались между собой (#100).
        """
        out = collections.defaultdict(list)
        for r in self.by_stage[stage].get(number, []):
            if not r.get("category"):
                continue
            if words is not None and room_names.same(room_names.name_words(r.get("name")), words) is False:
                continue
            if (r["file_id"], r["pdf_page_number"]) not in out[r["category"]]:
                out[r["category"]].append((r["file_id"], r["pdf_page_number"]))
        return out

    def shown(self, stage, number):
        names = collections.Counter(r.get("name") for r in self.by_stage[stage].get(number, []) if r.get("name"))
        return names.most_common(1)[0][0] if names else None


def area_of(values):
    """Площадь стадии по записям: значение большинства томов и его доля среди томов с площадью.

    Один том — одна площадь (страницы тома повторяют одну экспликацию); значения, отличающиеся
    меньше чем на порог, — одно значение.
    """
    if not values:
        return None, 0.0, []
    by_file = {}
    for area, fid, _page in values:
        by_file.setdefault(fid, area)
    groups = []                          # [[значения тома…], …], близкие значения — одна группа
    for area in sorted(by_file.values()):
        if groups and abs(area - groups[-1][0]) / max(area, groups[-1][0]) <= AREA_TOLERANCE:
            groups[-1].append(area)
        else:
            groups.append([area])
    best = max(groups, key=len)
    area = collections.Counter(best).most_common(1)[0][0]
    others = sorted({a for g in groups if g is not best for a in g})
    return area, len(best) / len(by_file), others


def split_parts(ex, number, words, pd_numbers):
    """Части помещения, выделенные в рабочей стадии: [(номер части, площадь)].

    У Тюменской-5 коридор подвала 002 в проекте — 62,9 м², а в ОВ1 из него выделено
    002.1 «Коридор» 20,3 м², и у самого 002 осталось 39,3 (#114). Сравнивать 62,9 с 39,3 —
    назвать уменьшение на 38 %, хотя коридор меньше на 3,3 м². Часть — номер рабочей стадии
    вида «номер.N», которого нет в проекте, с тем же наименованием.
    """
    shown = ex.shown_number.get(("RD", number)) or number
    out = []
    for other in sorted(ex.numbers("RD") - pd_numbers):
        label = ex.shown_number[("RD", other)]
        if not re.fullmatch(re.escape(shown) + r"\.\d+", label) and not re.fullmatch(re.escape(number) + r"\.\d+", other):
            continue
        area, _share, _others = area_of(ex.areas("RD", other, words))
        if area:
            out.append((label, area))
    return out


def neighbours(number, rd_pages_by_number):
    """Страница рабочей экспликации, где стоят соседи номера с обеих сторон, или None."""
    series, key = _series(number) or (None, None)
    if series is None:
        return None
    last = _num_key(number)[-1]
    by_page = collections.defaultdict(list)
    for other, pages in rd_pages_by_number.items():
        got = _series(other)
        if got != (series, key):
            continue
        for page in pages:
            by_page[page].append(_num_key(other)[-1])
    for page, nums in by_page.items():
        below = [n for n in nums if 0 < last - n <= NEIGHBOUR_GAP]
        above = [n for n in nums if 0 < n - last <= NEIGHBOUR_GAP]
        if below and above:
            return page
    return None


def _in_text(text, number, name):
    """Стоит ли в тексте страницы номер с началом наименования: «247 Кладовая»."""
    words = re.findall(r"[А-Яа-яЁё]{4,}", name or "")
    if not text or not words:
        return False
    head = words[0][:5]
    return re.search(r"(?<![\d.])%s(?![\d.])\s+\S{0,3}\s*%s" % (re.escape(number), re.escape(head)), text, re.I) is not None


def _near(a, b):
    return abs(a - b) / max(a, b) <= AREA_TOLERANCE


def _by_file(values):
    """Первое значение каждого тома: {файл: (значение, страница)}."""
    out = {}
    for value, fid, page in values:
        out.setdefault(fid, (value, page))
    return out


def corrected_in_chain(old_files, current_files, old, current, same, chain_of):
    """Видна ли корректировка внутри одной цепочки редакций: заменённый том называет прежнее значение,
    действующий том той же цепочки — новое (#111).

    Большинство томов проекта не доказывает корректировку: у Тюменской-5 венткамеру 006 четыре тома
    сетей связи называют 51,2 м², а действующий том АР, как и заменённый «Том 3.РЕД», — 71,4. Без этого
    условия рабочая стадия, повторяющая АР, выходила «не обновлённой». Если цепочки не переданы,
    условие не проверяется.
    """
    if chain_of is None:
        return True
    return any(chain_of.get(fo) and chain_of.get(fo) == chain_of.get(fc) and same(vo, old) and same(vc, current)
               for fo, (vo, _) in old_files.items() for fc, (vc, _) in current_files.items())


def stale_split(current, old, rd_by_file, same):
    """Тома рабочей стадии, повторяющие заменённую редакцию проекта, и повторяющие действующую (#111)."""
    stale = sorted(f for f, (v, _) in rd_by_file.items() if same(v, old) and not same(v, current))
    fresh = sorted(f for f, (v, _) in rd_by_file.items() if same(v, current))
    return stale, fresh


def compare(object_id, rows, names=None, text_of=None, superseded=(), volumes=None, chain_of=None):
    """Гипотезы по экспликациям двух стадий. Возвращает (записи, сводка).

    rows — строки rooms_pages.jsonl; names — `room_names.Names` объекта (для отказа при перенумерации
    и для сверки наименований); без него наименования сверяются по самим строкам. text_of(file_id, page)
    — текст страницы: пропажа помещения проверяется по тексту рабочей экспликации. superseded —
    файлы заменённых редакций: их строки отбрасываются до сравнения, но строки заменённых томов
    проекта нужны, чтобы узнать том рабочей стадии, не обновлённый после корректировки (#111).
    volumes — подписи томов для пояснения, {файл: «АР1 изм. 3»}; chain_of — цепочка редакций файла
    ({файл: chain_id}): корректировка проекта признаётся, только если её видно внутри одной цепочки.
    """
    dropped = sum(1 for r in rows if r.get("file_id") in superseded)
    old_pd = Explications([r for r in rows if r.get("file_id") in superseded and STAGES.get(r.get("stage")) == "PD"])
    rows = [r for r in rows if r.get("file_id") not in superseded]
    ex = Explications(rows)
    pd_numbers, rd_numbers = ex.numbers("PD"), ex.numbers("RD")
    summary = {"номеров в проекте": len(pd_numbers), "номеров в рабочей стадии": len(rd_numbers),
               "в обеих": len(pd_numbers & rd_numbers), "сверено": 0,
               "пропало": 0, "площадь": 0, "категория": 0, "площадь: стадия не согласна сама с собой": 0,
               "площадь: помещение разделено, сумма та же": 0,
               "пропало: номер есть в тексте страницы": 0, "пропало: проект сам с собой не согласен": 0,
               "не обновлено после корректировки проекта": 0,
               "строк заменённых редакций": dropped,
               "отказ": None}
    if not pd_numbers or not rd_numbers:
        summary["отказ"] = "экспликаций нет в одной из стадий"
        return [], summary
    if names is not None:
        reason, named, differ = room_names.refusal(names, sorted(ex.shown_number[("PD", n)] for n in pd_numbers & rd_numbers))
        if reason:
            summary["отказ"] = reason
            return [], summary
    found = {"missing": [], "area": [], "category": [], "stale": []}
    rd_pages = {n: ex.pages("RD", n) for n in rd_numbers}
    pd_by_file = collections.defaultdict(dict)          # том проекта → номер → страницы
    for n in pd_numbers:
        for fid, page in ex.pages("PD", n):
            pd_by_file[fid].setdefault(n, []).append((fid, page))
    for number in sorted(pd_numbers, key=lambda n: (_num_key(n), n)):
        pd_words = names.name("PD", ex.shown_number[("PD", number)]) if names else room_names.name_words(ex.shown("PD", number))
        if number not in rd_numbers:
            # строка без площади — не помещение, а пункт перечня или спецификации, попавший
            # в экспликацию с подписанным столбцом («2 — кирпичная», «8 Адресный расширитель»)
            page = neighbours(number, rd_pages) if ex.has_area("PD", number) else None
            if page:
                shown, name = ex.shown_number[("PD", number)], ex.shown("PD", number)
                if text_of and any(_in_text(text_of(*p), n, name) for p in [page] for n in {shown, number}):
                    summary["пропало: номер есть в тексте страницы"] += 1
                    continue
                # том проекта, где соседи номера стоят, а самого номера нет ни в строках, ни в тексте
                dissent = [neighbours(number, nums) for fid, nums in pd_by_file.items() if number not in nums]
                if any(p and not (text_of and any(_in_text(text_of(*p), n, name) for n in {shown, number}))
                       for p in dissent):
                    summary["пропало: проект сам с собой не согласен"] += 1
                    continue
                found["missing"].append({"number": shown, "pd_name": name,
                                         "pd_pages": ex.pages("PD", number)[:MAX_EVIDENCE], "rd_page": page})
            continue
        rd_words = names.name("RD", ex.shown_number[("RD", number)]) if names else room_names.name_words(ex.shown("RD", number))
        if not room_names.same(pd_words, rd_words):
            continue                      # другое помещение под тем же номером или наименование не разобрано
        summary["сверено"] += 1
        pd_area, pd_share, pd_others = area_of(ex.areas("PD", number, pd_words))
        rd_area, rd_share, rd_others = area_of(ex.areas("RD", number, rd_words))
        shown, pd_name = ex.shown_number[("PD", number)], ex.shown("PD", number)
        # корректировка проекта изменила площадь, а часть томов рабочей стадии — по прежней редакции
        old_area, old_share, _ = area_of(old_pd.areas("PD", number, pd_words))
        stale_area = None
        if pd_area and old_area and min(pd_share, old_share) >= MAJORITY and not _near(pd_area, old_area) \
                and corrected_in_chain(_by_file(old_pd.areas("PD", number, pd_words)),
                                       _by_file(ex.areas("PD", number, pd_words)), old_area, pd_area, _near, chain_of):
            rd_files = _by_file(ex.areas("RD", number, rd_words))
            stale, fresh = stale_split(pd_area, old_area, rd_files, _near)
            if stale:
                stale_area = {"number": shown, "pd_name": pd_name, "what": "площадь", "current": pd_area, "old": old_area,
                              "stale": {f: rd_files[f] for f in stale}, "fresh": {f: rd_files[f] for f in fresh},
                              "pd_pages": [(f, p) for v, f, p in ex.areas("PD", number, pd_words) if _near(v, pd_area)],
                              "old_pages": [(f, p) for v, f, p in old_pd.areas("PD", number, pd_words) if _near(v, old_area)]}
                found["stale"].append(stale_area)
        if pd_area and rd_area and not stale_area:
            parts = split_parts(ex, number, rd_words, pd_numbers) if (pd_area - rd_area) / pd_area > AREA_TOLERANCE else []
            rd_total = round(rd_area + sum(a for _, a in parts), 2)
            if min(pd_share, rd_share) < MAJORITY:
                summary["площадь: стадия не согласна сама с собой"] += 1
            elif parts and (pd_area - rd_total) / pd_area <= AREA_TOLERANCE:
                summary["площадь: помещение разделено, сумма та же"] += 1
            elif (pd_area - rd_total) / pd_area > AREA_TOLERANCE:
                found["area"].append({"number": ex.shown_number[("PD", number)], "pd_name": ex.shown("PD", number),
                                      "pd_area": pd_area, "rd_area": rd_total, "pd_others": pd_others, "rd_others": rd_others,
                                      "parts": [(ex.shown_number[("RD", number)], rd_area)] + parts if parts else [],
                                      "pd_pages": [(f, p) for _, f, p in ex.areas("PD", number, pd_words)][:MAX_EVIDENCE],
                                      "rd_pages": [(f, p) for _, f, p in ex.areas("RD", number, rd_words)][:MAX_EVIDENCE]})
        # категория — по наименованию, под которым номер чаще всего стоит в стадии: словарь
        # наименований номера объединяет все помещения под ним, и чужое помещение с ним «совпадает»
        pd_cat = ex.categories("PD", number, room_names.name_words(ex.shown("PD", number)))
        rd_cat = ex.categories("RD", number, room_names.name_words(ex.shown("RD", number)))
        old_cat = old_pd.categories("PD", number, room_names.name_words(ex.shown("PD", number)))
        if pd_cat and rd_cat and old_cat:
            a = max(pd_cat, key=lambda c: len(pd_cat[c]))
            o = max(old_cat, key=lambda c: len(old_cat[c]))
            rd_files = {f: (c, p) for c, pages in rd_cat.items() for f, p in pages}
            same = lambda x, y: x == y                                                        # noqa: E731
            corrected = a != o and corrected_in_chain({f: (c, p) for c, pages in old_cat.items() for f, p in pages},
                                                      {f: (c, p) for c, pages in pd_cat.items() for f, p in pages},
                                                      o, a, same, chain_of)
            stale, fresh = stale_split(a, o, rd_files, same) if corrected else ([], [])
            if stale:
                found["stale"].append({"number": shown, "pd_name": pd_name, "what": "категория", "current": a, "old": o,
                                       "stale": {f: rd_files[f] for f in stale}, "fresh": {f: rd_files[f] for f in fresh},
                                       "pd_pages": pd_cat[a], "old_pages": old_cat[o]})
                continue
        if pd_cat and rd_cat:
            a = max(pd_cat, key=lambda c: len(pd_cat[c]))
            b = max(rd_cat, key=lambda c: len(rd_cat[c]))
            if a != b:
                # доказательства — страницы, где стоит именно эта категория, а не любые страницы номера
                found["category"].append({"number": ex.shown_number[("PD", number)], "pd_name": ex.shown("PD", number), "pd_cat": a, "rd_cat": b,
                                          "pd_pages": pd_cat[a][:MAX_EVIDENCE],
                                          "rd_pages": rd_cat[b][:MAX_EVIDENCE]})
    out = []
    for kind, items in found.items():
        summary[{"missing": "пропало", "area": "площадь", "category": "категория",
                 "stale": "не обновлено после корректировки проекта"}[kind]] = len(items)
        if not items:
            continue
        if kind == "stale":
            # площади и категории — отдельными записями: специалист подтвердил нарушением площади
            # пищеблока ДОО, а по категориям помещений ему не хватило данных (Р-86)
            for what in ("площадь", "категория"):
                part = [it for it in items if it["what"] == what]
                if part:
                    out.append(_stale_record(object_id, part, volumes or {}, what))
            continue
        if len(items) > MAX_SINGLE:
            out.append(_grouped(object_id, kind, items))
        else:
            out.extend(_single(object_id, kind, it) for it in items)
    return out, summary


# Этаж по заголовку таблицы экспликации. Опечатки проектировщиков («антесольного») — та же антресоль
FLOORS = (
    (re.compile(r"(\d+)\s*-?\s*(?:го|ого|й)?\s+этаж", re.I), lambda m: f"{int(m.group(1))} этаж"),
    (re.compile(r"антр?е?сол", re.I), lambda m: "антресоль"),
    (re.compile(r"тех\w*\.?\s*этаж", re.I), lambda m: "технический этаж"),
    (re.compile(r"подвал", re.I), lambda m: "подвал"),
    (re.compile(r"цокол", re.I), lambda m: "цокольный этаж"),
    (re.compile(r"навес", re.I), lambda m: "навес"),
    (re.compile(r"кровл", re.I), lambda m: "кровля"),
)
MIN_FLOOR_ROWS = 3           # таблица этажа короче — не последовательность, а обрывок


def floor_of(title):
    """Этаж по заголовку таблицы: «Спецификация помещений 1-го этажа» → «1 этаж»; None — не назван."""
    for pattern, label in FLOORS:
        m = pattern.search(title or "")
        if m:
            return label(m)
    return None


def _name_key(name):
    return " ".join(sorted(room_names.name_words(name) or [re.sub(r"\W+", "", (name or "").lower())]))


def floor_tables(rows, superseded=()):
    """Таблицы экспликаций по тому и этажу: {(стадия, файл, этаж): (страница, [строки по порядку])}.

    Одна и та же экспликация этажа повторяется на нескольких листах тома (план отделки, полов,
    потолков): берётся самая полная, при равенстве — первая по номеру страницы.
    """
    pages = collections.defaultdict(list)
    for r in rows:
        stage = STAGES.get(r.get("stage"))
        floor = floor_of(r.get("table"))
        if not stage or not floor or not r.get("labeled") or r.get("file_id") in superseded:
            continue
        pages[(stage, r["file_id"], floor, r["pdf_page_number"])].append(r)
    best = {}
    for (stage, fid, floor, page), items in sorted(pages.items(), key=lambda kv: kv[0][3]):
        key = (stage, fid, floor)
        if len(items) >= MIN_FLOOR_ROWS and (key not in best or len(items) > len(best[key][1])):
            best[key] = (page, items)
    return best


def align(pd_rows, rd_rows):
    """Пары строк проекта и рабочей стадии одного этажа: [(строка проекта, строка РД)].

    Выравнивание по наименованиям. Внутри замены одинаковой длины строки идут парами по месту:
    там и лежит смена назначения — помещение осталось, наименование другое.
    """
    a = [_name_key(r.get("name")) for r in pd_rows]
    b = [_name_key(r.get("name")) for r in rd_rows]
    pairs = []
    for op, i0, i1, j0, j1 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal" or (op == "replace" and i1 - i0 == j1 - j0):
            pairs += list(zip(pd_rows[i0:i1], rd_rows[j0:j1]))
    return pairs


def _renamed(p, r):
    """Смена назначения: наименования разные, площадь в пределах порога."""
    if room_names.same(room_names.name_words(p.get("name")), room_names.name_words(r.get("name"))) is not False:
        return False
    pa, ra = p.get("area_m2"), r.get("area_m2")
    return bool(pa and ra and abs(pa - ra) / pa <= AREA_TOLERANCE)


def compare_floors(object_id, rows, code_base=None, superseded=(), sections=None):
    """Поэтажная сверка экспликаций: смена назначения помещений. Возвращает (записи, сводка).

    code_base — {файл: шифр проекта} из разбора редакций (#10): том проекта сверяется только с
    томами рабочей стадии того же шифра. Без шифра у тома рабочей стадии сверки нет.

    sections — {файл: раздел}. Назначение помещения задаёт раздел АР; остальные разделы переписывают
    его экспликацию в своё время и расходятся между собой — у Алтуфьевского в проекте 2254266 том АР
    пишет «23 Помещение», том ОВ уже «22 Комната отдыха», ещё один — «Помещение отдыха персонала».
    Поэтому если экспликации этажа в разделе АР есть в обеих стадиях, сверяются только они, а тома
    проекта, где назначение уже как в РД, названы в пояснении. Нет АР в одной из стадий (у Тюменской-5
    в РД только ОВ) — сверяются все тома.
    """
    code_base = code_base or {}
    sections = sections or {}
    tabs = floor_tables(rows, superseded)
    summary = {"этажей в обеих стадиях": 0, "пар томов": 0, "смена назначения": 0, "сверено по АР": 0}
    by_floor = collections.defaultdict(lambda: {"PD": [], "RD": []})
    for (stage, fid, floor), (page, items) in tabs.items():
        by_floor[floor][stage].append((fid, page, items))
    out = []
    for floor in sorted(by_floor, key=lambda f: (not f[0].isdigit(), f)):
        sides = by_floor[floor]
        if not sides["PD"] or not sides["RD"]:
            continue
        summary["этажей в обеих стадиях"] += 1
        pd_all = sorted(sides["PD"])
        pd_side, rd_side = pd_all, sorted(sides["RD"])
        ar_pd = [t for t in pd_side if sections.get(t[0]) == "AR"]
        ar_rd = [t for t in rd_side if sections.get(t[0]) == "AR"]
        if ar_pd and ar_rd:
            pd_side, rd_side = ar_pd, ar_rd
            summary["сверено по АР"] += 1
        changes, compared = [], set()
        for rd_fid, rd_page, rd_items in rd_side:
            base = code_base.get(rd_fid)
            for pd_fid, pd_page, pd_items in pd_side:
                if not base or code_base.get(pd_fid) != base:
                    continue
                summary["пар томов"] += 1
                compared.add(rd_fid)
                got = [(p, r) for p, r in align(pd_items, rd_items) if _renamed(p, r)]
                if got:
                    changes.append((pd_fid, pd_page, rd_fid, rd_page, got, pd_items, rd_items))
        if changes:
            summary["смена назначения"] += len(changes[0][4])
            changed = {c[2] for c in changes}
            base = code_base.get(changes[0][2])
            # тома проекта того же шифра, где назначение уже такое, как в РД: проект сам с собой не согласен
            renamed_to = [r for _, r in changes[0][4]]
            agree = sorted({fid for fid, _, items in pd_all if code_base.get(fid) == base and fid != changes[0][0]
                            and any(_same_room(r, x) for r in renamed_to for x in items)})
            out.append(_floor_record(object_id, floor, changes, sorted(compared - changed), agree))
    return out, summary


def _same_room(a, b):
    """Одно помещение под одним назначением: наименования совпадают, площадь в пределах порога."""
    pa, pb = a.get("area_m2"), b.get("area_m2")
    return bool(room_names.same(room_names.name_words(a.get("name")), room_names.name_words(b.get("name")))
                and pa and pb and abs(pa - pb) / pa <= AREA_TOLERANCE)


def _area(v):
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


def _room(r):
    return f"{r['number']} «{r.get('name') or '—'}», {_area(r['area_m2'])} м²"


def _floor_record(object_id, floor, changes, same_as_pd, pd_agree=()):
    pd_fid, pd_page, rd_fid, rd_page, got, pd_items, rd_items = changes[0]
    parts = []
    for p, r in got:
        parts.append(f"{_room(p)} → {_room(r)}" + ("" if p["number"] == r["number"] else "; номер другой"))
    detail = (f"{floor}: назначение изменено у {len(got)} помещений при той же площади (порог {AREA_TOLERANCE:.0%}): "
              + "; ".join(parts))
    # сумма площадей этажа сравнима, только если обе таблицы разобраны одинаково полно: организатор
    # отмечает и её («итоговые площади этажей», ALT79B-V01), но по неполной таблице она врёт
    if len(pd_items) == len(rd_items):
        pd_sum = sum(x["area_m2"] or 0 for x in pd_items)
        rd_sum = sum(x["area_m2"] or 0 for x in rd_items)
        detail += f". Сумма площадей помещений по экспликации этажа: {_area(pd_sum)} → {_area(rd_sum)} м²"
    others = sorted({c[2] for c in changes} - {rd_fid})
    if others:
        detail += "; то же в томах рабочей стадии " + ", ".join(others)
    if same_as_pd:
        detail += ("; в томах рабочей стадии " + ", ".join(same_as_pd)
                   + " назначения прежние, как в проекте: рабочая стадия сама с собой не согласна")
    if pd_agree:
        detail += ("; в томах проекта того же шифра " + ", ".join(pd_agree)
                   + " назначение уже как в рабочей стадии: проект сам с собой не согласен")
    evidence = (_evidence("PD", [(pd_fid, pd_page)], f"экспликация проекта, {floor}")
                + _evidence("RD", [(rd_fid, rd_page)], f"экспликация рабочей документации, {floor}"))
    return {
        "finding_id": f"{object_id}::FREE::ROOM_PURPOSE::{floor}",
        "object_id": object_id,
        "matrix_scope": "FREE_SEARCH",
        "parameter_code": "FREE-AR-ROOM-PURPOSE",
        "parameter_id": None,
        "title": "Назначение помещений этажа изменено в рабочей документации",
        "comparison_result": "VALUE_MISMATCH",
        "location_type": "SECTION",
        "locations": [floor],
        "pd_value": "; ".join(_room(p) for p, _ in got)[:500],
        "rd_value": "; ".join(_room(r) for _, r in got)[:500],
        "id_value": None,
        "violation_label": "VIOLATION_PRESENT",
        "criticality": CRITICALITY,
        "finding_status": "SUSPICION",
        "needs_expert": True,
        "for_submission": False,
        "evidence": evidence,
        "extraction": {
            "rule_basis": "экспликации этажа проекта и рабочей стадии одного шифра сверяются как последовательности",
            "detail": detail[:2000],
            "source": "rooms_pages",
        },
    }


def _value(what, v):
    return f"{v:g} м²" if what == "площадь" else str(v)


def _stale_record(object_id, items, volumes, aspect=None):
    """Гипотеза на объект и сторону (#111, Р-86): помещения, где тома рабочей стадии повторяют
    заменённую редакцию проекта, и сами эти тома. Первыми в доказательствах — тома АР: по ним сверяют
    помещения. Сторона — «площадь» или «категория»: у них разные решения специалиста."""
    label = lambda f: volumes.get(f) or f                                                  # noqa: E731
    stale_files = collections.Counter(f for it in items for f in it["stale"])
    fresh_files = collections.Counter(f for it in items for f in it["fresh"])
    ar_first = lambda f: (not str(volumes.get(f) or "").startswith("АР"), -stale_files[f], f)  # noqa: E731

    def names(files, limit=None):
        """Подписи томов без повторов: у двух файлов одного тома подпись одна."""
        out = list(dict.fromkeys(label(f) for f in sorted(files, key=ar_first)))
        return ", ".join(out[:limit] if limit else out)

    parts = []
    for it in items:
        stale = names(it["stale"])
        fresh = names(it["fresh"])
        parts.append(f"{it['number']} «{it['pd_name'] or '—'}», {it['what']}: в действующей редакции проекта "
                     f"{_value(it['what'], it['current'])}, в заменённой {_value(it['what'], it['old'])}; "
                     f"как в заменённой — {stale}" + (f"; как в действующей — {fresh}" if fresh else ""))
    head = (f"рабочая документация не обновлена после корректировки проекта у {len(items)} помещений: "
            f"по заменённой редакции проекта — {names(stale_files, 8)}"
            + (f"; по действующей — {names(fresh_files, 8)}" if fresh_files else ""))
    pd_pages, old_pages, rd_pages, seen = [], [], [], set()
    for it in sorted(items, key=lambda it: min(ar_first(f) for f in it["stale"])):
        for f, p in sorted(it["pd_pages"], key=lambda fp: ar_first(fp[0])):
            if ("PD", f, p) not in seen and len(pd_pages) < MAX_EVIDENCE - 1:
                seen.add(("PD", f, p)), pd_pages.append((f, p))
        for f, p in sorted(it["old_pages"], key=lambda fp: ar_first(fp[0])):
            if ("OLD", f, p) not in seen and not old_pages:
                seen.add(("OLD", f, p)), old_pages.append((f, p))
        for f in sorted(it["stale"], key=ar_first):
            p = it["stale"][f][1]
            if ("RD", f, p) not in seen and len(rd_pages) < MAX_EVIDENCE:
                seen.add(("RD", f, p)), rd_pages.append((f, p))
    evidence = (_evidence("PD", pd_pages, "экспликация действующей редакции проекта")
                + _evidence("PD", old_pages, "экспликация заменённой редакции проекта")
                + _evidence("RD", rd_pages, "экспликация рабочей документации по заменённой редакции проекта"))
    rooms = [it["number"] for it in items]
    rec = _record(object_id, "stale", rooms, "значения действующей редакции проекта",
                  "значения заменённой редакции проекта", (head + ". " + "; ".join(parts))[:2000], evidence)
    if aspect:
        rec["aspect"] = aspect
        if aspect == "категория":
            rec["title"] += ": категории помещений"
    return rec


def _evidence(stage, pages, quote):
    return [{"stage": stage, "file_id": fid, "pdf_page_number": page, "quote": quote, "localization": "PAGE_LEVEL"}
            for fid, page in pages]


def _values(kind, it):
    if kind == "missing":
        return (f"{it['number']} {it['pd_name'] or ''}".strip(), "в экспликациях рабочей документации номера нет",
                f"помещение {it['number']} «{it['pd_name'] or '—'}» есть в экспликации проекта; в рабочей экспликации "
                f"на одной странице стоят его соседи по номеру, самого номера нет")
    if kind == "area":
        note = ""
        if it.get("pd_others"):
            note += f"; в части томов проекта {', '.join(f'{a:g}' for a in it['pd_others'])} м²"
        if it.get("rd_others"):
            note += f"; в части томов рабочей стадии {', '.join(f'{a:g}' for a in it['rd_others'])} м²"
        if it.get("parts"):
            note += ("; в рабочей стадии помещение разделено: "
                     + ", ".join(f"{n} — {a:g}" for n, a in it["parts"]) + f", вместе {it['rd_area']:g} м²")
        return (f"{it['pd_area']:g} м²", f"{it['rd_area']:g} м²",
                f"площадь помещения {it['number']} «{it['pd_name'] or '—'}» уменьшена: {it['pd_area']:g} → {it['rd_area']:g} м² "
                f"({(it['pd_area'] - it['rd_area']) / it['pd_area']:.1%}); порог {AREA_TOLERANCE:.0%}{note}")
    return (it["pd_cat"], it["rd_cat"],
            f"категория помещения {it['number']} «{it['pd_name'] or '—'}» изменена: {it['pd_cat']} → {it['rd_cat']}")


def _record(object_id, kind, rooms, pd_value, rd_value, detail, evidence):
    code, result, title = KINDS[kind]
    return {
        "finding_id": f"{object_id}::FREE::{kind.upper()}::{'-'.join(rooms)[:80]}",
        "object_id": object_id,
        "matrix_scope": "FREE_SEARCH",
        "parameter_code": code,
        "parameter_id": None,
        "title": title,
        "comparison_result": result,
        "location_type": "ROOM",
        "locations": rooms,
        "pd_value": pd_value,
        "rd_value": rd_value,
        "id_value": None,
        "violation_label": "VIOLATION_PRESENT",
        "criticality": CRITICALITY,
        "finding_status": "SUSPICION",
        "needs_expert": True,
        "for_submission": False,
        "evidence": evidence,
        "extraction": {
            "rule_basis": "экспликации помещений проектной и рабочей стадий сверяются по номеру при одном наименовании",
            "detail": detail,
            "source": "rooms_pages",
        },
    }


def _single(object_id, kind, it):
    pd_value, rd_value, detail = _values(kind, it)
    evidence = _evidence("PD", it["pd_pages"], f"помещение {it['number']} в экспликации проекта")
    rd_pages = [it["rd_page"]] if kind == "missing" else it["rd_pages"]
    evidence += _evidence("RD", rd_pages, f"экспликация рабочей документации: {rd_value}")
    return _record(object_id, kind, [it["number"]], pd_value, rd_value, detail, evidence)


def _grouped(object_id, kind, items):
    rooms = [it["number"] for it in items]
    parts = [_values(kind, it)[2] for it in items]
    heads = {"missing": f"помещений проекта нет в экспликациях рабочей документации: {len(items)}",
             "area": f"площадь уменьшена у {len(items)} помещений",
             "category": f"категория изменена у {len(items)} помещений"}
    pd_pages, rd_pages, seen = [], [], set()
    for it in items:
        for f, p in it["pd_pages"]:
            if ("PD", f, p) not in seen and len(pd_pages) < MAX_EVIDENCE:
                seen.add(("PD", f, p)), pd_pages.append((f, p))
        for f, p in ([it["rd_page"]] if kind == "missing" else it["rd_pages"]):
            if ("RD", f, p) not in seen and len(rd_pages) < MAX_EVIDENCE:
                seen.add(("RD", f, p)), rd_pages.append((f, p))
    evidence = _evidence("PD", pd_pages, "экспликация проекта") + _evidence("RD", rd_pages, "экспликация рабочей документации")
    detail = heads[kind] + "; " + "; ".join(parts)
    return _record(object_id, kind, rooms, heads[kind], "см. пояснение", detail[:2000], evidence)
