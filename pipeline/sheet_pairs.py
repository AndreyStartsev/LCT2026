"""Соответствие листов проектной и рабочей стадии. Задача #21.

## В чём дело

Сравнение «по всему объекту» не работает: вытяжка помещения может быть показана на другом листе
того же комплекта, и её отсутствие на произвольном листе ничего не доказывает. Сравнивать надо
лист с соответствующим ему листом, и эти же листы нужны находке как страницы-доказательства:
инспектор смотрит на схему проекта и на план рабочей документации рядом.

## Признаки пары

**Состав помещений.** У листа есть множество номеров помещений (`plan_rooms.jsonl`): у проектной
схемы — подписи у систем, у рабочего плана — экспликация на том же листе. Мера — доля помещений
проектного листа, найденных на рабочем (включение, а не Жаккар): проектная схема показывает
три этажа разом, рабочие планы поэтажные, и одному проектному листу законно соответствуют
несколько рабочих.

**Дисциплина листа.** Планы одного этажа в комплекте повторяются: вентиляция, кондиционирование,
отопление — экспликация у них одна, и по составу помещений они неразличимы. Различает их
наименование листа в основной надписи: «План 1-го этажа (вентиляция)». Наименование берётся
из графы 4 основной надписи по её месту в миллиметрах от угла листа — из слов текстового слоя
или распознанных (`pipeline/titleblock_ocr.py`). Наименование комплекта над ней не годится:
оно общее всем листам тома.
Совпадение дисциплины поднимает пару, расхождение опускает, отсутствие наименования — ничего
не меняет: порядок тогда решает состав помещений.

**Наименование листа целиком.** Там, где рабочая стадия повторяет чертёж проектной («АУПТ и ВПВ.
План 1 этажа» в обеих), наименования совпадают дословно, и это сильнее состава помещений. Замер
на втором объекте (Алтуфьевское, `docs/room-compare-report.md`) показал, что один состав помещений
там ошибается: лист «Общие данные» или спецификация перечисляет все помещения и обгоняет настоящий
план. Поэтому близость наименований добавляется к мере, а лист без помещений, но с тем же
наименованием тоже становится парой. Числа в наименовании — этаж, отметка, номер разреза —
обязаны совпасть: «План 1-го этажа» и «План 2-го этажа» по наименованию не пара.

Раздел документа (ОВ с ОВ) — жёсткий фильтр, если раздел известен у обоих документов.

## Что отдаёт

`pairs(...)` — для каждого проектного листа ранжированный список рабочих; `for_room(...)` —
рабочие листы, соответствующие проектному листу и содержащие заданное помещение.
"""
import collections
import re

# Графа 4 основной надписи по ГОСТ Р 21.101 (наименование изображений листа), в миллиметрах
# от правого нижнего угла листа: рамка отступает на 5 мм, правее графы стоят стадия, лист
# и организация (50 мм), сама графа шириной 70 мм и высотой 15 мм. Выше неё — наименование
# комплекта, общее всем листам тома: «Отопление, вентиляция и кондиционирование воздуха».
# По нему лист вентиляции не отличить от листа кондиционирования, поэтому берётся только графа 4.
NAME_DX_MM = (52.0, 128.0)
NAME_DY_MM = (4.0, 21.0)

MIN_SHARED = 3            # меньше общих помещений — совпадение случайно: «101», «102» есть везде
MIN_CONTAINMENT = 0.15    # доля помещений проектного листа, найденных на рабочем
DISCIPLINE_BONUS = 0.25   # прибавка к мере при совпадении дисциплины листа, вычет — при расхождении
SAME_NAME_BONUS = 2.0     # наименования совпали дословно: тот же чертёж в другой стадии, он идёт первым
NAME_BONUS = 0.5          # наименования близки: прибавка пропорциональна близости
MIN_NAME_SIMILARITY = 0.6 # ниже этой близости наименование пару не поддерживает
MIN_NAME_WORDS = 3        # короче — наименование общее («Общие данные») и само по себе парой не делает
TOP = 12

# дисциплина листа по словам наименования; порядок не важен, лист может нести несколько
DISCIPLINES = (
    ("VENT", r"вентиляц|воздухообмен|воздуховод"),
    ("SMOKE", r"дымоудален|противодымн|подпор"),
    ("HEAT", r"отоплен|теплоснабжен|т[её]пл\w+\s+пол"),
    ("COND", r"кондиционир|холодоснабжен"),
    ("WATER", r"водоснабжен|водопровод"),
    ("SEWER", r"канализац|водоотведен|водосток"),
    ("POWER", r"электроснабжен|электрооборудован|освещен|силов\w+\s+сет"),
    ("LOW", r"связ[ьи]|сигнализац|оповещен|видеонаблюден"),
)
_DISCIPLINES = [(tag, re.compile(pattern, re.I)) for tag, pattern in DISCIPLINES]
# слова наименования комплекта, общие всем листам тома: «Система общеобменной вентиляции
# и кондиционирования воздуха. Пожарное дымоудаление». Дисциплину листа называет последняя скобка
# или последние слова наименования, поэтому сначала пробуем её.
_BRACKET = re.compile(r"\(([^()]{4,40})\)\s*\S{0,12}\s*$|\(([^()]{4,40})\)")


def sheet_name(words):
    """Наименование листа из слов угла: [(текст, мм от правого края, мм от нижнего края)] → строка."""
    inside = [(round(dy / 3.5), -dx, t) for t, dx, dy in words
              if NAME_DX_MM[0] <= dx <= NAME_DX_MM[1] and NAME_DY_MM[0] <= dy <= NAME_DY_MM[1]]
    return " ".join(t for _, _, t in sorted(inside, key=lambda w: (-w[0], w[1])))


def disciplines(title):
    """Дисциплины листа по наименованию: {«VENT», …}. Скобка в конце наименования решает."""
    title = (title or "").replace("ё", "е")
    brackets = [a or b for a, b in _BRACKET.findall(title)]
    for text in brackets[::-1]:
        found = {tag for tag, rx in _DISCIPLINES if rx.search(text)}
        if found:
            return found
    return {tag for tag, rx in _DISCIPLINES if rx.search(title)}


# масштаб в наименовании и подписи граф основной надписи, попавшие в вырез графы 4 на чужом штампе
_SCALE = re.compile(r"\(?\s*м(?:асштаб)?\s*1\s*[:к]\s*\d+\s*\)?", re.I)
_STAMP_WORDS = {"изм", "кол", "лист", "листов", "подп", "дата", "док", "стадия", "разраб", "разработал",
                "проверил", "пров", "контр", "нконтр", "гип", "утв", "формат", "копировал"}


def name_words(title):
    """Слова и числа наименования листа для сравнения: (слова, числа)."""
    text = _SCALE.sub(" ", (title or "").lower().replace("ё", "е"))
    words = {w for w in re.findall(r"[a-zа-я]{3,}", text) if w not in _STAMP_WORDS}
    numbers = set(re.findall(r"\d+", text))
    return words, numbers


def name_similarity(a, b):
    """Близость наименований двух листов, 0…1: доля общих слов, если числа совпали.

    Числа в наименовании — этаж, отметка, номер разреза. Разные числа — разные чертежи,
    сколько бы слов ни совпало.
    """
    (words_a, numbers_a), (words_b, numbers_b) = a, b
    if not words_a or not words_b or numbers_a != numbers_b:
        return 0.0
    tokens_a, tokens_b = words_a | numbers_a, words_b | numbers_b
    if len(tokens_a) < 2 or len(tokens_b) < 2:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def room_sets(plan_rows):
    """Помещения по листам: {(file_id, страница): {номера}}."""
    out = collections.defaultdict(set)
    for r in plan_rows:
        out[(r["file_id"], r["pdf_page_number"])].add(r["number"])
    return out


def _stage(value):
    return "RD" if value == "RD_ID_MIXED" else value


def pairs(plan_rows, documents, titles=None, top=TOP):
    """Рабочие листы для каждого проектного: {(file_id, стр.): [{file_id, page, shared, containment, score, …}]}.

    plan_rows — строки `plan_rooms.jsonl`; documents — {file_id: строка реестра} со стадией и разделом;
    titles — {(file_id, стр.): наименование листа}, необязательно.
    """
    titles = titles or {}
    sets = room_sets(plan_rows)
    names = {key: name_words(title) for key, title in titles.items()}
    by_stage = collections.defaultdict(list)
    for key in set(sets) | set(names):
        doc = documents.get(key[0]) or {}
        by_stage[_stage(doc.get("stage"))].append(key)
    nothing = (set(), set())
    out = {}
    for pd_key in sorted(by_stage.get("PD", [])):
        pd_rooms = sets.get(pd_key, set())
        pd_name = names.get(pd_key, nothing)
        informative = len(pd_name[0] | pd_name[1]) >= MIN_NAME_WORDS
        if len(pd_rooms) < MIN_SHARED and not informative:
            continue
        pd_section = (documents.get(pd_key[0]) or {}).get("section")
        pd_tags = disciplines(titles.get(pd_key))
        found = []
        for rd_key in by_stage.get("RD", []):
            rd_section = (documents.get(rd_key[0]) or {}).get("section")
            if pd_section and rd_section and "OTHER" not in (pd_section, rd_section) and pd_section != rd_section:
                continue
            shared = pd_rooms & sets.get(rd_key, set())
            containment = len(shared) / len(pd_rooms) if pd_rooms else 0.0
            by_rooms = len(shared) >= MIN_SHARED and containment >= MIN_CONTAINMENT
            similarity = name_similarity(pd_name, names.get(rd_key, nothing))
            named = similarity >= MIN_NAME_SIMILARITY
            # одно наименование делает пару, только если оно содержательное и раздел у документов один
            by_name = named and informative and pd_section == rd_section
            if not by_rooms and not by_name:
                continue
            rd_tags = disciplines(titles.get(rd_key))
            if pd_tags and rd_tags:
                bonus = DISCIPLINE_BONUS if pd_tags & rd_tags else -DISCIPLINE_BONUS
            else:
                bonus = 0.0
            same = similarity >= 0.999
            score = containment + bonus + (SAME_NAME_BONUS if same else NAME_BONUS * similarity if named else 0.0)
            found.append({"file_id": rd_key[0], "pdf_page_number": rd_key[1], "shared": len(shared),
                          "containment": round(containment, 3), "score": round(score, 3),
                          "discipline": "MATCH" if bonus > 0 else "MISMATCH" if bonus < 0 else "UNKNOWN",
                          "name_similarity": round(similarity, 3),
                          "by": "BOTH" if by_rooms and named else "ROOMS" if by_rooms else "NAME",
                          "tags": sorted(rd_tags), "rooms": sorted(shared)})
        found.sort(key=lambda r: (-r["score"], -r["shared"], r["file_id"], r["pdf_page_number"]))
        if found:
            out[pd_key] = found[:top]
    return out


def for_room(paired, pd_key, room, want=None):
    """Рабочие листы, соответствующие проектному листу и показывающие помещение room.

    want — дисциплина самой находки («VENT»): установка вентиляции нарисована и на схеме
    теплоснабжения калориферов, но показывать рядом с ней надо план вентиляции, а не отопления.
    Листы нужной дисциплины идут первыми, дальше порядок пары.
    """
    found = [r for r in paired.get(pd_key, []) if room in r["rooms"]]
    if want:
        found.sort(key=lambda r: 0 if want in r.get("tags", ()) else 1)
    return found
