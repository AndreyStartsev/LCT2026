"""Материал труб по участку системы: водопровод IOS2-072 и канализация IOS3-075. Черновики шестого круга.

Триггеры Матрицы: «подмена оцинкованных/чугунных труб на полипропилен без перерасчёта расширения»
(IOS2-072) и «самовольная замена малошумных или чугунных труб на тонкостенный ПВХ» (IOS3-075).
Сравнивается не спецификация — там каждая строка сама по себе, — а проектное решение:
«магистрали и стояки … из стальных водогазопроводных оцинкованных труб», «выпуски … из труб
ВЧШГ». Поэтому материал берётся только из фразы-решения: перед ним «из» или в той же фразе
«предусмотрен», «выполнен», «запроектирован».

Участок — ключ: магистрали, стояки, разводка, выпуски. Если участок не назван, а система
названа («системы холодного водоснабжения запроектированы из…»), ключ — «система целиком»,
и он сравнивается с любым участком другой стадии. Материал сводится к группе: металл (сталь,
оцинкованная сталь, чугун, медь, нержавеющая сталь) и полимер; у канализации отдельно —
малошумный полимер (по марке) и ПВХ. Замена — в рабочей стадии полимер на участке, где проект
назначил только металл (или малошумную трубу). Компенсаторы замену не снимают: перерасчёта
расширения в пакете нет (решение специалиста шестого круга). Участок, о котором проект молчит,
из полимера при металле на остальных — гипотеза низкой уверенности; переход на схеме РД на
трубу, которой проект в системе не назначал («переход ПП–НПВХ» при чугуне и ПП в ПД), — замена.
"""
import re

WATER, SEWER = "water", "sewer"
WHOLE = "система целиком"

METAL = "металл"
POLYMER = "полимер"
QUIET = "малошумный полимер"
# у канализации ПВХ — отдельно от полипропилена: триггер IOS3-075 называет именно «тонкостенный ПВХ», и
# «переход ПП–НПВХ» на стояке — уже замена (решение специалиста шестого круга, IOS3-075, вопрос 3)
PVC = "ПВХ"

# группа материала по словам фразы; первое совпадение в порядке перечня
_WATER_MATERIALS = (
    ("сталь оцинкованная", r"оцинкован\w*|водогазопровод\w*|ВГП\b|ГОСТ\s*3262"),
    ("сталь", r"стальн\w+\s+(?:\w+\s+){0,2}(?:электросварн|бесшовн)\w*|ГОСТ\s*(?:10704|8732)"),
    ("нержавеющая сталь", r"нержав\w*"),
    ("медь", r"медн\w+\s+труб"),
    ("полимер", r"полипропилен\w*|\bPP-?RC?T?\b|\bPPR\b|PE-?X\w?|PE-?RT|сшит\w*\s+полиэтилен\w*|металлопласт\w*"
                r"|термопласт\w*|полимерн\w+\s+(?:труб|материал)"),
)
_SEWER_MATERIALS = (
    ("чугун", r"чугун\w*|ВЧШГ|\bSML\b"),
    ("малошумный полимер", r"малошумн\w*|Sinikon|Raupiano|Ostendorf|Wavin\s*AS|Blue\s*Power"),
    ("ПВХ", r"(?<![А-ЯЁA-Z])Н?ПВХ(?![а-яё])|поливинилхлорид\w*"),
    ("полимер", r"полипропилен\w*|\bPP-?H\b|(?<![А-ЯЁA-Z])ПП-?Г\b|полимерн\w+\s+(?:труб|материал)"),
)
GROUP = {"сталь оцинкованная": METAL, "сталь": METAL, "нержавеющая сталь": METAL, "медь": METAL,
         "чугун": METAL, "малошумный полимер": QUIET, "полимер": POLYMER, "ПВХ": PVC}

_WATER_PARTS = (("магистрали", r"магистрал\w*"), ("стояки", r"стояк\w*"),
                ("разводка", r"разводк\w*|подводк\w*|поквартирн\w+\s+(?:развод|трубопровод)\w*|ввод\w*\s+в\s+квартир"))
_SEWER_PARTS = (("выпуски", r"выпуск\w*"),
                ("магистрали", r"магистрал\w*|горизонтальн\w+\s+(?:трубопровод|участ|сет)\w*|транзит\w*"),
                ("стояки", r"стояк\w*"), ("разводка", r"разводк\w*|подводк\w*|отвод\w*\s+от\s+прибор"))
# какая система во фразе; фраза о другой системе не берётся вовсе
_WATER_SYSTEM = r"водоснабжени|водопровод|\bВ1\b|\bТ3\b|\bТ4\b|ХВС|ГВС|хозяйственно-питьев"
_SEWER_SYSTEM = r"канализац|водоотведени|водосток|\bК1\b|\bК2\b|\bК3\b"
_WATER_FOREIGN = (r"пожар|спринклер|ВПВ|\bВ2\b|отоплени|теплоснабжени|\bТ1\b|\bТ2\b|канализац|водосток|дренаж|"
                  r"кабел|гильз|футляр|воздуховод|электроснабж|электрооборуд|электрическ|теплов\w+\s+сет")
_SEWER_FOREIGN = (r"водопровод\w*\s+(?:из|систем)|кабел|гильз|футляр|воздуховод|электроснабж|электрооборуд|электрическ|"
                  r"дренажн\w+\s+насос|переход")
_DECISION = re.compile(r"предусм\w+|выполн\w+|запроектир\w+|принят\w*|монтир\w+|проклад\w+|применя\w+|"
                       r"используют\w*", re.I)
_EXPANSION = re.compile(r"компенсатор\w*|неподвижн\w+\s+опор\w*|температурн\w+\s+(?:удлинен|расширен)\w*", re.I)
# граница фразы: точка, точка с запятой, пункт списка «- В1 …», «• …», «11. …»
_CLAUSE = re.compile(r"(?<=[.;])\s+|\s[-–•]\s(?=[А-ЯЁA-Z])|\s(?=\d{1,2}\.\s+[А-ЯЁ])")


# номер пункта без точки: «… дождевой канализации 6 Проектом предусматривается монтаж …» — участок из
# предыдущего пункта новому не достаётся
_ITEM_START = re.compile(r"(?:^|\s)\d{1,2}\.?\s+(?=[А-ЯЁ])")
# заголовок нормы: шифр и название с прописной — «СП 40-102-2000 Проектирование и монтаж …»; решением
# проекта после него материал станет только при глаголе-решении между названием и материалом
# переход между трубами на схеме или в спецификации: «∅110 переход ПП -НПВХ», «Переход PP на трубы НПВХ 110х110»,
# «Переход ПП -Чуг». Решением о материале участка он не считается, но показывает, что труба из этого материала в
# системе есть: переход на материал, которого проект в системе не назначал, — замена (IOS3-075, вопрос 3)
_T_MAT = r"ПП|PP|Н?ПВХ|Чуг\w*|ВЧШГ|SML"
_TRANSITION = re.compile(rf"переход\w*\s+(?P<a>{_T_MAT})\s*(?:[-–]\s*|на\s+(?:трубы\s+)?)(?P<b>{_T_MAT})(?![а-яё])", re.I)
_T_GROUP = {"пп": "полимер", "pp": "полимер", "пвх": "ПВХ", "нпвх": "ПВХ", "вчшг": "чугун", "sml": "чугун"}
# чья канализация: последняя система, названная перед материалом. Внутренний водосток в ПД Полярной 16 описан
# перечнем «- стояки выше перекрытия первого этажа – …; - магистральные трубопроводы на подвале …» под одним
# заголовком; «дождевой канализации» — один знак водостока, а не бытовой канализации. Условно-чистые стоки и
# дренаж — не К1 и не К2
_SEWER_CODE = re.compile(r"(?:дождев|ливнев)\w*(?:\s+канализац\w*)?|водосток\w*|(?<![А-ЯЁA-Zа-яё])К\s?2\b|"
                         r"условно-чист\w*|дренаж\w*|(?<![А-ЯЁA-Zа-яё])К\s?(?:[34]|\dН)\b|"
                         r"(?:хозяйственно-)?бытов\w*(?:\s+канализац\w*)?|(?<![А-ЯЁA-Zа-яё])К\s?1\b|канализац\w*", re.I)
TRANSITION = "переход"
_NORM = re.compile(r"(?<![А-ЯЁA-Z])(?:СП|СНиП|ГОСТ(?:\s?Р)?|ВСН|МДС|ТР)\s?\d[\d.\-*]*\s+[А-ЯЁ][а-яё]+")


def _clauses(flat):
    """Фразы страницы с их началом: [(позиция, фраза)]."""
    out, pos = [], 0
    for part in _CLAUSE.split(flat):
        start = flat.find(part, pos)
        pos = start + len(part)
        if part and len(part) > 15:
            out.append((start, part))
    return out


def _system_here(flat, start, own, other):
    """Чья фраза: система, названная последней перед ней на странице. На листе общих данных ВК водопровод и
    канализация описаны подряд, и «- стояки выше перекрытия первого этажа – раструбными полипропиленовыми
    трубопроводами» Полярной 16 — канализация из пункта выше, хотя в самой фразе системы нет."""
    before = flat[max(0, start - 500):start]
    last_own = max((m.end() for m in re.finditer(own, before, re.I)), default=-1)
    last_other = max((m.end() for m in re.finditer(other, before, re.I)), default=-1)
    return last_other <= last_own


def _parts(text, parts):
    """Участки, названные в тексте; «от стояков» — откуда идёт подводка, а не участок."""
    out = []
    for key, pat in parts:
        for m in re.finditer(pat, text, re.I):
            if re.search(r"(?<![а-яё])от\s+(?:\w+\s+)?$", text[max(0, m.start() - 30):m.start()], re.I):
                continue
            out.append(key)
            break
    return out


def materials(flat, system):
    """Решения о материале труб на странице: [{key, value, raw, snippet, expansion}].

    `value` — группа материала (металл, полимер, малошумный полимер), `raw` — как названо.
    Участок материала: перечень в скобках сразу за ним («… оцинкованных труб по ГОСТ 3262-75
    (магистрали, стояки) и полипропиленовых …» у Тюменской), иначе участки в тексте перед ним — от
    предыдущего материала фразы, иначе «система целиком», если фраза называет систему.
    """
    if system == WATER:
        mats, parts, sys_pat, foreign = _WATER_MATERIALS, _WATER_PARTS, _WATER_SYSTEM, _WATER_FOREIGN
    else:
        mats, parts, sys_pat, foreign = _SEWER_MATERIALS, _SEWER_PARTS, _SEWER_SYSTEM, _SEWER_FOREIGN
    other = _SEWER_SYSTEM if system == WATER else _WATER_SYSTEM
    out = []
    for start, clause in _clauses(flat):
        if re.search(foreign, clause, re.I):
            continue
        if not re.search(sys_pat, clause, re.I) and not _system_here(flat, start, sys_pat, other):
            continue
        found = []
        for name, pat in mats:
            for m in re.finditer(pat, clause, re.I):
                # ссылка на норму в кавычках: «Проектирование и монтаж трубопроводов из полипропилена…»
                if clause.rfind("«", 0, m.start()) > clause.rfind("»", 0, m.start()):
                    continue
                # то же без кавычек в перечне норм: «СП 40-102-2000 Проектирование и монтаж трубопроводов … из
                # полимерных материалов» (ДОО Полярной, РД ВК)
                title = list(_NORM.finditer(clause[max(0, m.start() - 160):m.start()]))
                if title and not _DECISION.search(clause[max(0, m.start() - 160) + title[-1].end():m.start()]):
                    continue
                found.append((m.start(), m.end(), name))
        found.sort()
        # «из стальных водогазопроводных оцинкованных труб по ГОСТ 3262» — одна и та же труба, три слова её группы
        first = {}
        for a, b, name in found:
            first.setdefault(name, (a, b, name))
        found = sorted(first.values())
        prev_end, seen = 0, set()
        for i, (a, b, name) in enumerate(found):
            nxt = found[i + 1][0] if i + 1 < len(found) else len(clause)
            # фраза-решение: «из стальных труб», «чугунными трубопроводами», «предусмотрены …»; строка
            # спецификации «Труба из высокопрочного чугуна …» решением не считается
            before = clause[max(0, a - 60):a]
            word = clause[a:b]
            decided = (re.search(r"(?<!труба\s)(?<!трубы\s)(?<![а-яё])из\s", before, re.I)
                       or re.search(r"(?:ыми|ими)$", word, re.I)
                       or _DECISION.search(clause[max(0, a - 120):a]))
            if not decided:
                prev_end = b
                continue
            after = re.match(r"[^()]{0,40}?\(([^)]{0,90})\)", clause[b:nxt])
            keys = _parts(after.group(1), parts) if after else []
            if keys:
                own_end = b + after.end()
            else:
                window = clause[max(prev_end, a - 160):a]
                cut = [m.end() for m in _ITEM_START.finditer(window)]
                if cut:
                    window = window[cut[-1]:]
                keys = _parts(window, parts)
                own_end = b
            if not keys:
                if not re.search(sys_pat, clause[max(0, a - 160):b + 40], re.I):
                    prev_end = own_end
                    continue
                keys = [WHOLE]
            if system == SEWER and _sewer_system_at(flat, start + a, 1500) == "storm":
                # внутренние водостоки — своя система: полипропилен водостока с чугуном бытовой канализации не сравнивается
                keys = [f"водостоки: {k}" for k in keys]
            for key in keys:
                if (key, name) in seen:
                    continue
                seen.add((key, name))
                out.append({"key": key, "value": GROUP[name], "raw": name,
                            "expansion": bool(_EXPANSION.search(clause)),
                            "snippet": " ".join(clause[max(0, a - 110):b + 60].split())})
            prev_end = own_end
    if system == SEWER:
        out += _transitions(flat)
    return out


def _sewer_system_at(flat, pos, reach=3000):
    """Какая канализация названа последней перед позицией: «storm», «other» (К3, К4, дренаж), «domestic» или
    None, если на странице перед позицией система не названа."""
    systems = list(_SEWER_CODE.finditer(flat[max(0, pos - reach):pos]))
    if not systems:
        return None
    last = systems[-1].group(0).lower().replace(" ", "")
    if re.match(r"к2|водосток|дождев|ливнев", last):
        return "storm"
    if re.match(r"к[34]|к\dн|условно|дренаж", last):
        return "other"
    return "domestic"


# типовой узел с перечнем вариантов: «Узел выпуска систем канализации с переходом Чугун-Чугун … ПП-Чугун … ПВХ-Чугун»
# (ДОО Полярной, РД ВК) — выбор из каталога, а не труба этой системы
_TYPICAL_NODE = re.compile(r"(?:узел|узл\w+)\s+[^.;]{0,60}$", re.I)


def _transitions(flat):
    """Материалы, названные переходом между трубами: [{key: «…переход», value, raw, snippet, transition}]."""
    out = []
    for m in _TRANSITION.finditer(flat):
        if _TYPICAL_NODE.search(flat[max(0, m.start() - 60):m.start()]):
            continue
        # лист спецификации начат с середины раздела («2.4.17 Переход НПВХ-ВЧШГ» без заголовка «К4» на этой
        # странице, Полярная 16): чья труба, не видно — переход не берётся
        where = _sewer_system_at(flat, m.start())
        if where in ("other", None):
            continue
        prefix = "водостоки: " if where == "storm" else ""
        for side in ("a", "b"):
            word = m.group(side).lower()
            name = _T_GROUP.get(word) or ("чугун" if word.startswith("чуг") else None)
            if name:
                out.append({"key": prefix + TRANSITION, "value": GROUP[name], "raw": f"{name} (переход)",
                            "expansion": False, "transition": True,
                            "snippet": " ".join(flat[max(0, m.start() - 110):m.end() + 60].split())})
    return out


def water_materials(flat):
    return materials(flat, WATER)


def sewer_materials(flat):
    return materials(flat, SEWER)


def _split(key):
    """Подсистема и участок ключа: «водостоки: стояки» → («водостоки: », «стояки»)."""
    head, sep, tail = key.rpartition(": ")
    return (head + sep, tail) if sep else ("", key)


def _pair(pd, rd):
    """Пары ключей стадий внутри подсистемы: общий участок, иначе «система целиком» против каждого участка другой
    стадии (в ПД Речникова водостоки названы по участкам, в РД — системой целиком)."""
    out = []
    for prefix in sorted({_split(k)[0] for k in list(pd) + list(rd)}):
        p = {_split(k)[1] for k in pd if _split(k)[0] == prefix} - {TRANSITION}
        r = {_split(k)[1] for k in rd if _split(k)[0] == prefix} - {TRANSITION}
        common = sorted(p & r)
        if common:
            out += [(prefix + k, prefix + k) for k in common]
        elif WHOLE in p:
            out += [(prefix + WHOLE, prefix + k) for k in sorted(r)]
        elif WHOLE in r:
            out += [(prefix + k, prefix + WHOLE) for k in sorted(p)]
    return out


def _replaced(p, r):
    """Почему набор рабочей стадии `r` — замена проектного `p`, или None."""
    if not (METAL in p or QUIET in p):
        return None
    was = "металл" if METAL in p else "малошумная труба"
    if PVC in r and PVC not in p:
        return f"{was} в проекте, ПВХ в рабочей стадии"
    if POLYMER in r and POLYMER not in p and PVC not in p:
        return f"{was} в проекте, полимер в рабочей стадии"
    return None


UNNAMED = "в проекте участок не назван"


def changes(pd, rd):
    """Замены материала: [(ключ, проект, рабочая, почему)]. pd, rd — {участок: {группа}}.

    Кроме пар участков — два случая по решениям специалиста шестого круга: участок рабочей стадии, о котором
    проект молчит, из полимера при металле на остальных участках проекта (IOS2-072, вопрос 2 — гипотеза), и
    переход на материал, которого проект в этой системе не назначал (IOS3-075, вопрос 3)."""
    out = []
    paired = set()
    for kp, kr in _pair(pd, rd):
        paired.add(kr)
        p, r = pd[kp], rd[kr]
        key = kp if kp == kr else f"{kp} → {kr}"
        why = _replaced(p, r)
        if why:
            out.append((key, p, r, why))
    for prefix in sorted({_split(k)[0] for k in rd}):
        # переход в проекте («Переход PP на чугун» на схеме ПД) тоже показывает, что материал проектом назначен
        project = set().union(*[v for k, v in pd.items() if _split(k)[0] == prefix])
        if not project:
            continue
        pd_parts = {_split(k)[1] for k in pd if _split(k)[0] == prefix}
        for k in sorted(rd):
            head, part = _split(k)
            if head != prefix or k in paired:
                continue
            why = _replaced(project, rd[k])
            if not why:
                continue
            if part == TRANSITION:
                out.append((k, project, rd[k], f"переход на трубу, которой проект в системе не назначал: {why}"))
            elif part != WHOLE and WHOLE not in pd_parts:
                out.append((k, project, rd[k], f"{UNNAMED}, на остальных участках — {why}"))
    return out


def strict(change):
    """Замена, которую специалист признал нарушением (шестой круг, Р-111, Р-112): тот же названный участок в обеих
    стадиях (IOS2-072, вопрос 1: сталь на полипропилен и при компенсаторах; IOS3-075, вопрос 1: участок целиком) или
    переход на ПВХ, которого проект в системе не назначал (IOS3-075, вопрос 3). Сравнение системы целиком, участок,
    о котором проект молчит (IOS2-072, вопрос 2), и переход на полипропилен — замена части участка или неизвестно
    какого участка: гипотезы."""
    key, _p, r, why = change
    part = _split(key)[1]
    if "→" in key or part == WHOLE:
        return False
    if part == TRANSITION:
        return PVC in r and "ПВХ в рабочей стадии" in why
    return UNNAMED not in why


def compare_pairs(pd, rd):
    return _pair(pd, rd)


def show(key, values):
    return ", ".join(sorted(values))
