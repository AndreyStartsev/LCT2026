"""Постраничное сравнение пар редакций документа. Задача #19.

У разделов проектной документации встречаются пары «исходник — переиздание после замечаний»
с почти одинаковым числом страниц; сравнение пары даёт перечень фактических изменений проекта,
и это сигнал для свободного поиска, не требующий никакого перечня от организатора.

Пары берутся из цепочек редакций (`build/<объект>/revisions.jsonl`, #10): в цепочке
с установленным порядком соседние редакции образуют пару «прежняя → следующая». Цепочки,
где порядок не установлен (`CLARIFICATION_REQUIRED`), пропускаются и считаются: сравнивать
две редакции, не зная, какая позже, — значит выдавать изменения задом наперёд.

Страницы выравниваются по содержимому, не по номеру: добавление одной страницы сдвигает все
следующие. Сходство страниц — Жаккар по тройкам слов; выравнивание — динамическим программированием
с монотонным порядком (пропуски бесплатны, совпадение засчитывается от `MIN_SIMILARITY`). Пара
страниц с полным совпадением нормализованного текста — `SAME` (сходство по тройкам слов чисел
не видит, поэтому само по себе совпадением не считается), со сходством от порога — `CHANGED`,
страница без пары — `ADDED` или `REMOVED`.

Что именно изменилось на странице — построчный diff (`difflib`): заменённые, добавленные и
удалённые строки и числа, которые в заменённых строках стали другими. Строки, где меняется
только номер листа в основной надписи («Лист 12» → «Лист 13»), — не изменение содержания,
они помечаются отдельно и в перечень изменений не идут.

Страница, чей текстовый слой не читается (битая кодировка шрифта: «ȼ74<. <=6. 7» в томе ПЗ
Тюменской-5 при нормальном слое переиздания), помечается `UNREADABLE` и в изменения не идёт:
там изменился слой, а не проект. Битый слой узнаётся по знакам, которых в тексте проекта
не бывает: «<», «>» и буквы расширенной латиницы. Чертёж, где почти все слова — размеры,
читается: прежде такой лист считался битым по малой доле слов из букв (#81).

Пара, у которой страниц с парой по содержимому меньше `REVISION_SHARE` от меньшего тома,
на переиздание не похожа — это разные документы с одной маркой; цепочка редакций по ней
не строится (`verify_chains`), и перечень «изменений» такой пары никто не примет за правки проекта.

Где на листе изменилось (#81) — `place`: слова двух редакций сравниваются по месту на видимой
странице, с поправкой на сдвиг листа и его частей. Изменения в служебных полях — основная
надпись, штамп «В производство работ», поле подшивки — считаются отдельно: смена даты выдачи
или подписи — не изменение проекта. Отметка изменения (`registration`) ищется там, где её
ставит проектировщик: строки таблицы изменений в штампе листа и «Изм. N (Зам.)» в ведомости
рабочих чертежей. Лист, у которого изменилось содержание, а номера нового изменения нет
ни там, ни там, — «изменение без отметки».

Текст записки при правке перетекает: абзац, вставленный на одной странице, сдвигает конец всех
следующих страниц на соседние. По месту такой лист выглядит изменённым — сверху «убран» абзац,
ушедший на предыдущую страницу, снизу «добавлен» пришедший со следующей. Поэтому слова, которые
по месту не нашлись, ищутся в потоке текста соседних страниц другой редакции: стоящие там тем же
текстом и в том же порядке — перетёкшие, а не изменённые (`place`, `old_near` и `new_near`).
"""
import collections
import difflib
import re
import statistics

MIN_SIMILARITY = 0.35        # сходство, с которого страницы считаются одной и той же, но изменённой
REVISION_SHARE = 0.5         # доля совпавших страниц, ниже которой пара не похожа на переиздание
MAX_CHANGES = 12             # сколько строк изменений записывать на страницу
GARBLED_SHARE = 0.2          # доля слов со знаками битой кодировки, с которой слой страницы — не текст
GARBLED_RE = re.compile(r"[<>\u0180-\u02AF]")   # «<», «>» и расширенная латиница
SHEET_NUMBER_RE = re.compile(r"\b(лист(?:ов)?|стр\.?)\s*\d+", re.I)
NUMBER_RE = re.compile(r"(?<![\w,.])[-+]?(?:\d{1,3}(?: \d{3})+|\d+)(?:[.,]\d+)?(?![\w])")
WORD_RE = re.compile(r"[А-Яа-яЁёA-Za-z0-9]+(?:[.,][0-9]+)?")


def normalize(text):
    """Строки страницы для сравнения: без лишних пробелов, пустые убраны."""
    lines = []
    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            lines.append(line)
    return lines


def shingles(lines, n=3):
    """Тройки слов страницы для выравнивания. Числа заменены знаком: оглавление после вставки
    страницы меняет все номера, но остаётся той же страницей; что изменилось в числах —
    считает построчный diff, а не выравнивание."""
    words = ["#" if w[0].isdigit() else w.lower() for line in lines for w in WORD_RE.findall(line)]
    if len(words) < n:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def readable(lines):
    """Читается ли слой страницы. У томов со сломанной кодировкой шрифта слой выглядит как
    «ȼ74<. <=6. 7» — сравнивать такой текст с нормальным бессмысленно. Признак — доля слов
    со знаками, которых в тексте проекта не бывает. Доля слов из букв признаком не служит:
    на чертеже почти все слова — размеры, и такой лист читается (#81)."""
    tokens = [t for line in lines for t in line.split()]
    if not tokens:
        return True
    return sum(1 for t in tokens if GARBLED_RE.search(t)) / len(tokens) < GARBLED_SHARE


def similarity(a, b):
    """Сходство двух страниц по тройкам слов: Жаккар; пустые страницы сходства не имеют."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return len(a & b) / len(a | b)


def align(sims, n, m):
    """Монотонное выравнивание страниц: пары (i, j) с максимальной суммой сходств не ниже порога."""
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        row, prev = best[i], best[i - 1]
        for j in range(1, m + 1):
            s = sims[i - 1][j - 1]
            diag = prev[j - 1] + s if s >= MIN_SIMILARITY else -1.0
            row[j] = max(prev[j], row[j - 1], diag)
    pairs, i, j = [], n, m
    while i > 0 and j > 0:
        s = sims[i - 1][j - 1]
        if s >= MIN_SIMILARITY and abs(best[i][j] - (best[i - 1][j - 1] + s)) < 1e-9:
            pairs.append((i, j))
            i, j = i - 1, j - 1
        elif best[i - 1][j] >= best[i][j - 1]:
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def _only_sheet_number(a, b):
    """Строки различаются только номером листа в основной надписи."""
    return SHEET_NUMBER_RE.sub("лист N", a.lower()) == SHEET_NUMBER_RE.sub("лист N", b.lower())


def page_changes(old_lines, new_lines):
    """Что изменилось на странице: замены, добавления, удаления строк и изменившиеся числа."""
    changes, numbers, sheet_only = [], [], 0
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                was = old_lines[i1 + k] if i1 + k < i2 else None
                now = new_lines[j1 + k] if j1 + k < j2 else None
                if was and now and _only_sheet_number(was, now):
                    sheet_only += 1
                    continue
                changes.append({"was": was, "now": now})
                if was and now and NUMBER_RE.sub("#", was) == NUMBER_RE.sub("#", now):
                    # строка та же, изменились только числа в ней — это и есть изменение значения
                    a_nums, b_nums = NUMBER_RE.findall(was), NUMBER_RE.findall(now)
                    numbers += [f"{x} → {y}" for x, y in zip(a_nums, b_nums) if x != y]
        elif tag == "delete":
            changes += [{"was": old_lines[k], "now": None} for k in range(i1, i2)]
        elif tag == "insert":
            changes += [{"was": None, "now": new_lines[k]} for k in range(j1, j2)]
    return changes, numbers, sheet_only


def compare(old_pages, new_pages):
    """Сравнить две последовательности страниц: [(номер, текст)] → строки по страницам и сводка."""
    old = [(p, normalize(t)) for p, t in old_pages]
    new = [(p, normalize(t)) for p, t in new_pages]
    old_sh = [shingles(lines) for _, lines in old]
    new_sh = [shingles(lines) for _, lines in new]
    sims = [[similarity(a, b) for b in new_sh] for a in old_sh]
    pairs = align(sims, len(old), len(new))
    aligned = set(pairs)
    # страницы без пары между двумя соседними якорями: удалённые и добавленные подряд — это скорее
    # переписанные страницы (оглавление после вставки, таблица с новыми значениями), чем замена
    # одних страниц другими; они складываются в пары по порядку и сравниваются как изменённые
    anchors = [(0, 0)] + pairs + [(len(old) + 1, len(new) + 1)]
    for (i0, j0), (i1, j1) in zip(anchors, anchors[1:]):
        gap_old, gap_new = list(range(i0 + 1, i1)), list(range(j0 + 1, j1))
        for i, j in zip(gap_old, gap_new):
            pairs.append((i, j))
    pairs.sort()
    rows, used_old, used_new = [], set(), set()
    for i, j in pairs:
        used_old.add(i)
        used_new.add(j)
        (op, ol), (np_, nl) = old[i - 1], new[j - 1]
        s = sims[i - 1][j - 1]
        if not ol and not nl:
            rows.append({"status": "NO_TEXT", "old_page": op, "new_page": np_, "similarity": 0.0, "changes": [], "changes_total": 0, "numbers": []})
            continue
        if ol == nl:
            rows.append({"status": "SAME", "old_page": op, "new_page": np_, "similarity": round(s, 3)})
            continue
        if not ol or not nl or not readable(ol) or not readable(nl):
            rows.append({"status": "UNREADABLE", "old_page": op, "new_page": np_, "similarity": round(s, 3),
                         "changes": [], "changes_total": 0, "numbers": [],
                         "unreadable": [side for side, lines in (("old", ol), ("new", nl)) if not lines or not readable(lines)]})
            continue
        changes, numbers, sheet_only = page_changes(ol, nl)
        status = "SAME" if not changes and sheet_only else "CHANGED"
        rows.append({"status": status, "old_page": op, "new_page": np_, "similarity": round(s, 3),
                     "changes": changes[:MAX_CHANGES], "changes_total": len(changes), "numbers": numbers[:MAX_CHANGES],
                     "sheet_number_only": sheet_only})
    for i, (op, ol) in enumerate(old, 1):
        if i not in used_old:
            rows.append({"status": "REMOVED", "old_page": op, "new_page": None, "similarity": 0.0,
                         "changes": [{"was": line, "now": None} for line in ol[:4]], "changes_total": len(ol)})
    for j, (np_, nl) in enumerate(new, 1):
        if j not in used_new:
            rows.append({"status": "ADDED", "old_page": None, "new_page": np_, "similarity": 0.0,
                         "changes": [{"was": None, "now": line} for line in nl[:4]], "changes_total": len(nl)})
    rows.sort(key=lambda r: (r["old_page"] if r["old_page"] is not None else 10 ** 6, r["new_page"] or 0))
    counts = collections.Counter(r["status"] for r in rows)
    smaller = max(1, min(len(old), len(new)))
    readable_pairs = counts["SAME"] + counts["CHANGED"]
    # похоже ли на переиздание: хотя бы половина страниц меньшего тома нашла пару по содержимому
    # (выравниванием, а не заполнением разрыва); когда читаемых пар меньше трёх (сканы), ответа нет.
    # Том корпуса-близнеца и корректировка по содержимому неразличимы — оба почти совпадают;
    # различимы тома, у которых общих страниц нет
    looks = None
    if readable_pairs >= 3:
        looks = len(aligned) / smaller >= REVISION_SHARE
    summary = {"old_pages": len(old), "new_pages": len(new), "same": counts["SAME"], "changed": counts["CHANGED"],
               "added": counts["ADDED"], "removed": counts["REMOVED"], "unreadable": counts["UNREADABLE"],
               "no_text": counts["NO_TEXT"], "aligned": len(aligned), "looks_like_revision": looks}
    return rows, summary


def pairs_of(chains):
    """Пары «прежняя → следующая» из цепочек с установленным порядком; сколько цепочек без порядка."""
    out, unordered = [], 0
    for chain in chains:
        order = chain.get("order") or []
        if len(chain.get("members") or ()) < 2:
            continue
        if not order or chain.get("status") != "RESOLVED":
            unordered += 1
            continue
        for old_id, new_id in zip(order, order[1:]):
            out.append({"chain_id": chain["chain_id"], "stage_group": chain.get("stage_group"), "mark": chain.get("mark"),
                        "old_file_id": old_id, "new_file_id": new_id,
                        "old_revision": (chain.get("member_detail") or {}).get(old_id, {}).get("revision"),
                        "new_revision": (chain.get("member_detail") or {}).get(new_id, {}).get("revision")})
    return out, unordered


def _same_text(where):
    """Весь текст страницы нашёлся в другой редакции — по месту или в потоке текста соседних страниц."""
    return bool(where.get("text_checked")) and not where.get("content_removed") and not where.get("content_added")


def _flow_phrase(where):
    """«текст сдвинулся между страницами — на соседние ушло слов 29, с соседних пришло слов 52»."""
    gone, came = where.get("flowed_out", 0), where.get("flowed_in", 0)
    if not gone and not came:
        return ""
    parts = ([f"на соседние ушло слов {gone}"] if gone else []) + ([f"с соседних пришло слов {came}"] if came else [])
    return "текст сдвинулся между страницами — " + ", ".join(parts)


def describe(row):
    """Одна фраза о том, что изменилось на странице, для отчёта и экрана.

    Если страницу удалось сравнить по месту (`place`), фраза говорит о содержании листа:
    изменения служебных полей — дата выдачи, подписи — отделены, числа «было → стало» — те,
    что стоят на одном месте, текст, сдвинувшийся на соседние страницы, — не изменение.
    Построчное сравнение здесь не цитируется: оно не отличает номер страницы в рамке
    («33» → «35») от содержания. Иначе — по построчному сравнению."""
    if row["status"] == "ADDED":
        return "страница добавлена"
    if row["status"] == "REMOVED":
        return "страница удалена"
    if row["status"] == "SAME":
        return "без изменений" + ("; сменился только номер листа" if row.get("sheet_number_only") else "")
    if row["status"] == "NO_TEXT":
        return "текста нет ни в одной редакции (сканы без распознавания) — сравнить нельзя"
    where = row.get("place")
    # переверстанная страница, весь текст которой нашёлся в другой редакции в том же порядке
    same_text = bool(where) and where.get("layout") == "RELAID" and _same_text(where)
    placed = bool(where) and (where.get("layout") != "RELAID" or same_text)
    if row["status"] == "UNREADABLE" and not placed:
        sides = {"old": "прежней", "new": "новой"}
        return "текстовый слой " + " и ".join(sides[x] for x in row.get("unreadable", [])) + " редакции не читается или пуст — сравнить нельзя"
    first = next((c for c in row.get("changes", []) if c.get("was") and c.get("now")), None)
    if placed:
        removed, added = where["content_removed"], where["content_added"]
        flow = _flow_phrase(where)
        if not removed and not added:
            dates = "; ".join((where.get("service") or [])[:2])
            if flow:
                out = "содержание не изменилось: " + flow
            elif same_text and (where.get("matched") or where.get("moved")):
                out = "содержание не изменилось: страница переверстана, текст тот же"
            elif where.get("service_removed") or where.get("service_added"):
                out = "изменились только служебные поля" + (f": {dates}" if dates else "")
                dates = ""
            else:
                out = "содержание не изменилось: слова на своих местах"
            if dates:
                out += f"; в служебных полях: {dates}"
            # сдвиг текста по странице — часть его перетекания, отдельно его не называем
            if where.get("moved") and not flow and not same_text:
                out += f"; перенесено подписей и слов: {where['moved']}"
            return out
        parts = []
        if where.get("numbers"):
            parts.append("числа: " + "; ".join(where["numbers"][:4]))
        else:
            parts += _samples(where)
        if where.get("layout") == "RESIZED":
            parts.append("лист перевыпущен в другом формате")
        if flow:
            parts.append(flow)
        return f"изменено на листе: убрано слов {removed}, добавлено {added}" + ("; " + "; ".join(parts) if parts else "")
    parts = []
    if row.get("numbers"):
        parts.append("числа: " + "; ".join(row["numbers"][:4]))
    if first:
        parts.append(f"«{first['was'][:70]}» → «{first['now'][:70]}»")
    elif row.get("changes"):
        c = row["changes"][0]
        parts.append(("добавлено: «" + c["now"][:80] + "»") if c.get("now") else ("удалено: «" + c["was"][:80] + "»"))
    if where and where.get("layout") == "RELAID":
        parts.append("лист перекомпонован: места изменений не показаны")
    return f"{row.get('changes_total', 0)} изменённых строк" + ("; " + "; ".join(parts) if parts else "")


def verify_chains(chains, docs, page_texts):
    """Проверка цепочек по содержимому: тома с одной маркой, но не похожие на редакции одного документа.

    Проверяется, что у соседних редакций есть общие по содержимому страницы: у переиздания
    и у тома корпуса-близнеца они есть (по содержимому эти случаи неразличимы), у томов
    разных документов с одной маркой — нет. Такая цепочка получает статус UNRELATED: порядка
    нет, каждый том — сам себе актуальный, и правила не отбрасывают его значения как устаревшие.
    Пары, где ответа нет (сканы без читаемого слоя), цепочку не меняют.

    Возвращает (цепочки, документы) с правками; page_texts(doc) → [(страница, текст)].
    """
    from pipeline.revisions import issue_order
    by_id = {d["file_id"]: d for d in docs}
    for chain in chains:
        if chain.get("status") != "RESOLVED" or len(chain.get("order") or ()) < 2:
            continue
        checks, verdicts = [], []
        detail = chain.get("member_detail") or {}
        for old_id, new_id in zip(chain["order"], chain["order"][1:]):
            if old_id not in by_id or new_id not in by_id:
                continue
            _rows, summary = compare(list(page_texts(by_id[old_id])), list(page_texts(by_id[new_id])))
            checks.append({"old_file_id": old_id, "new_file_id": new_id, **summary})
            # тома из разных выпусков по папкам («ПД 2022» и «ПД 2025/Корр1», архив) — заведомо один
            # документ: переиздание через три года меняет больше половины страниц, и проверка
            # содержимым сочла бы его другим томом (#110). Сравнение записывается, но не решает
            if issue_order({"issue": (detail.get(old_id) or {}).get("issue")},
                           {"issue": (detail.get(new_id) or {}).get("issue")}) is not None:
                checks[-1]["by_issue_folder"] = True
                continue
            verdicts.append(summary["looks_like_revision"])
        chain["content_check"] = checks
        if any(v is False for v in verdicts):
            bad = next(c for c in checks if c["looks_like_revision"] is False)
            chain.update({
                "status": "UNRELATED", "current_file_id": None, "order": None,
                "reason": (f"тома с одной маркой не похожи на редакции одного документа: "
                           f"у {bad['old_file_id']} и {bad['new_file_id']} общих по содержимому страниц {bad['aligned']} "
                           f"из {min(bad['old_pages'], bad['new_pages'])}; каждый том считается действующим"),
                "member_status": {f: "CURRENT" for f in chain["members"]},
            })
            for f in chain["members"]:
                if f in by_id:
                    by_id[f]["revision_status"] = "CURRENT"
                    by_id[f]["predecessor_file_id"] = None
                    by_id[f]["successor_file_id"] = None
    return chains, docs


# ---------------------------------------------------------------- где на листе изменилось (#81)
#
# Построчный diff знает, что строки стали другими, но не где: на чертеже порядок строк текстового
# слоя плавает, и пары «было → стало» в нём — соседние по порядку строки, а не соседние на листе.
# Здесь слова сравниваются по месту на видимой странице (слова `reading.read_text_layer`: доли
# листа после поворота, Y сверху): слово совпало, если тот же текст стоит там же с точностью
# до POS_TOL_PT. Лист бывает сдвинут целиком, а часть видов — отдельно: на листе 3 изм. 1
# цепочки 23.009-Р-ГИ чертёж выше на 55 pt при штампе на месте, на листе 8 узлы сдвинуты
# на 20 pt. Поэтому сдвигов несколько: общий и местные, каждый — по голосованию редких слов.

POS_TOL_PT = 4.0             # слово на том же месте: ±4 pt, около 1,4 мм листа
MAX_OFFSETS = 6              # сколько сдвигов частей листа искать
MIN_VOTES = 6                # столько редких слов должно подтвердить местный сдвиг
FIRST_VOTES = 3              # и столько — общий
RARE = 3                     # слово редкое, если на странице встречается не больше стольких раз
REGION_PT = 60.0             # местный сдвиг действует на области проголосовавших слов с таким запасом
PAIR_PT = 40.0               # удалённое и добавленное число ближе этого — «было → стало»
SAMPLE = 8                   # сколько убранных и добавленных слов называть, если пар «было → стало» нет
ZONE_GAP_PT = 12.0           # рамки изменений ближе этого сливаются в одну зону
MAX_ZONES = 40               # зон на сторону страницы; больше — самые крупные
MIN_MATCHED = 0.35           # доля совпавших слов, ниже которой лист перекомпонован и рамкам не верим
MIN_CHANGED_WORDS = 3        # меньше изменённых слов без пары чисел — изменение слишком мало, чтобы судить
SUBSTANTIAL_WORDS = 10       # столько изменённых слов без пары чисел — уже правка, о которой спрашивать отметку
MOVE_PT = 30.0               # то же число не дальше этого от прежнего места — перенесено, не изменено
MOVE_TEXT_PT = 150.0         # слово не дальше этого — перенесено (строка надписи переломилась иначе)
LOCAL_SUPPORT = 0.3          # за местный сдвиг голосует не меньше этой доли редких слов его области
PT_PER_MM = 72 / 25.4
STAMP_ZONE_MM = (30.0, 6.0, 40.0, 65.0)   # от фразы «В производство работ»: влево, вверх, вправо, вниз
                                          # (ниже фразы — QR-код, под ним фамилия и дата: 42–55 мм)
ARCHIVE_ZONE_MM = (15.0, 15.0, 60.0, 10.0)      # «Архивный № …» и название организации над ним
PAGE_STAMP_ZONE_MM = (60.0, 12.0, 30.0, 8.0)    # «Страница 6 из 27» документооборота и номер над ним
CORNER_MM = (45.0, 15.0)     # правый верхний угол листа: номер листа в рамке, штамп документооборота
PAGE_NO_RE = re.compile(r"^\d{1,4}$")
FURNITURE_GRID_MM = 4.0      # клетка, в которой слово считается стоящим на одном месте на разных страницах
FURNITURE_SHARE = 0.6        # слово на стольких страницах файла на одном месте — штамп, а не содержание
FURNITURE_MIN_PAGES = 3      # у файла короче повторяющиеся слова не ищутся
BINDING_MM = 21.0            # поле подшивки: «Взам. инв. №», «Подп. и дата», «Инв. № подл.»
EDGE_MM = 5.0                # рамка чертежа в 5 мм от края листа: за ней — строка печати и метки обреза
STAMP_W_MM = 190.0           # основная надпись — 185 мм по ширине, с запасом
STAMP_FIRST_MM = 60.0        # формы 3 и 5 (первый лист): до 55 мм по высоте
STAMP_NEXT_MM = 25.0         # формы 6 и 2а (последующие листы): 15 мм
# подпись графы штампа целиком и с большой буквы: «Проверка …», «проверяется», «гипохлорит»
# в тексте записки над штампом первым листом его не делают (ИОС1.1 Речникова, «кор. 3», стр. 36)
FIRST_SHEET_RE = re.compile(r"^(Разраб(?:\.|отал)?|Пров(?:\.|ерил)?|Н\.\s?[Кк]онтр(?:\.|оль)?|Нормоконтр(?:\.|оль)?"
                            r"|Стадия|Листов|ГИП|Утв(?:\.|ердил)?)$")
NUMERIC_RE = re.compile(r"^[-+±]?\d+(?:[.,]\d+)*$")
DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{2,4}$")
FLOW_RUN = 6                 # столько слов подряд тем же текстом и в том же порядке — перетёкший текст
FLOW_LETTER_WORDS = 4        # ... и среди них столько слов из букв: цепочка размеров или подписи соседнего
                             # чертежа («Тех. этаж Тех. этаж» на листах ОВ3 Полярной 16) совпадают
                             # случайно, это не перетекание текста
LETTERS_RE = re.compile(r"[А-Яа-яЁёA-Za-z]{3}")
# маркер списка: знак шрифта Symbol или Wingdings в одной редакции, «•» в другой (ИОС5.5 Полярной 25 ДОО);
# тире отдельным словом — дефис, короткое или длинное
BULLETS = {**dict.fromkeys("\uf0b7\uf0a7\uf0d8\uf076\uf0fc\u2022\u25cf\u25aa\u25e6\u2219\u00b7", "\u2022"),
           **dict.fromkeys("-\u2013\u2014", "\u2013")}
# знаки, которыми две выгрузки одного текста расходятся без правки: «коридоры ,» против «коридоры,»,
# кавычки и скобки отдельным словом, перенос через дефис. В потоке текста слова сравниваются без них
# и без различия строчных и прописных; запятая или кавычка отдельным словом — не содержание листа
BARE = str.maketrans("", "", ",.;:«»\"'()[]-\u00ad")
SEPARATOR_RE = re.compile(r"^[,.;:«»\"'()\[\]]+$")


def _pt_words(layer):
    """Слова текстового слоя в пунктах видимой страницы: текст, центр и рамка."""
    w, h = layer.get("width_pt") or 1.0, layer.get("height_pt") or 1.0
    out = []
    for word in layer.get("words") or []:
        t = (word.get("t") or "").strip()
        t = BULLETS.get(t, t)
        x0, y0, x1, y1 = word["bbox"]
        if not t:
            continue
        box = (x0 * w, y0 * h, x1 * w, y1 * h)
        out.append({"t": t, "x": (box[0] + box[2]) / 2, "y": (box[1] + box[3]) / 2, "box": box})
    return out


def _furniture_key(word, width_pt, height_pt):
    """Место слова от правого нижнего угла листа в клетках FURNITURE_GRID_MM: штампы привязаны к углу,
    а листы одного тома бывают разного формата."""
    step = FURNITURE_GRID_MM * PT_PER_MM
    return word["t"], round((width_pt - word["x"]) / step), round((height_pt - word["y"]) / step)


def furniture(layers):
    """Слова, стоящие на большинстве страниц файла на одном месте: штампы документооборота
    и архива, которые система ставит на каждую страницу («Архивный № ПО00988-01» на Полярной 25 ДОО,
    где сама надпись нарисована векторами, а в текстовом слое — только номер). layers — слои
    страниц одного файла. Возвращает множество ключей `_furniture_key`."""
    counts, pages = collections.Counter(), 0
    for layer in layers:
        words = _pt_words(layer)
        if not words:
            continue
        pages += 1
        w, h = layer.get("width_pt") or 1.0, layer.get("height_pt") or 1.0
        counts.update({_furniture_key(v, w, h) for v in words})
    if pages < FURNITURE_MIN_PAGES:
        return frozenset()
    return frozenset(k for k, n in counts.items() if n >= FURNITURE_SHARE * pages)


def service_zone(words, width_pt, height_pt, repeated=frozenset()):
    """Служебные поля листа: предикат «слово стоит в основной надписи, в штампе
    «В производство работ» или в поле подшивки». Изменения там — дата выдачи, подписи,
    номер листа, строки таблицы изменений, — а не содержание проекта.

    Основная надпись — правые STAMP_W_MM листа и снизу по её форме: у первого листа (формы 3
    и 5, до 55 мм, в ней «Разраб.», «Стадия») — STAMP_FIRST_MM, у последующих (формы 6 и 2а,
    15 мм) — STAMP_NEXT_MM. Зона поиска подписей штампа (`titleblock.band_bounds`) для этого
    велика: на А4 это нижние 90 мм правой половины страницы, а там идёт текст записки.

    Штампы документооборота узнаются по словам: «В производство работ» (Октябрьская),
    «Архивный №» и «Страница N из M» с номером документа (Полярная 25 ДОО). Правый верхний угол —
    номер листа в рамке и тот же штамп документооборота: при выгрузке из системы он ставится
    на каждую страницу, и без маски каждый лист тома выглядел бы изменённым."""
    x_min = width_pt - STAMP_W_MM * PT_PER_MM
    first = any(FIRST_SHEET_RE.match(w["t"]) and w["x"] >= x_min and w["y"] >= height_pt - STAMP_FIRST_MM * PT_PER_MM
                for w in words)
    y_min = height_pt - (STAMP_FIRST_MM if first else STAMP_NEXT_MM) * PT_PER_MM
    stamps = []

    def zone(first, last, sizes):
        left, up, right, down = (v * PT_PER_MM for v in sizes)
        stamps.append((first["box"][0] - left, min(first["box"][1], last["box"][1]) - up,
                       last["box"][2] + right, max(first["box"][3], last["box"][3]) + down))

    for i, word in enumerate(words):
        if not 0 < i < len(words) - 1:
            continue
        before, after = words[i - 1], words[i + 1]
        same = lambda v: abs(v["y"] - word["y"]) <= 3.0  # noqa: E731
        low = word["t"].lower()
        # штамп — отдельная строка «В производство работ»; те же слова в общих указаниях
        # («… передаются в производство работ после …») продолжаются в строке и штампом не считаются
        if (low.startswith("производств") and before["t"] in ("В", "в") and same(before)
                and after["t"].lower().startswith("работ") and same(after)
                and not (i + 2 < len(words) and same(words[i + 2]) and words[i + 2]["x"] > after["x"])):
            zone(before, after, STAMP_ZONE_MM)
        # архивный штамп проектировщика: «Архивный № ПО00988-01» над основной надписью
        elif low.startswith("архивн") and after["t"].startswith("№") and same(after):
            zone(word, after, ARCHIVE_ZONE_MM)
        # штамп документооборота: «Страница 6 из 27» и номер документа над ним
        elif (low == "страница" and PAGE_NO_RE.match(after["t"]) and i + 3 < len(words)
              and words[i + 2]["t"] == "из" and PAGE_NO_RE.match(words[i + 3]["t"]) and same(words[i + 3])):
            zone(word, words[i + 3], PAGE_STAMP_ZONE_MM)
    binding = BINDING_MM * PT_PER_MM
    corner_x, corner_y = width_pt - CORNER_MM[0] * PT_PER_MM, CORNER_MM[1] * PT_PER_MM

    edge = EDGE_MM * PT_PER_MM

    def inside(word):
        if word["x"] >= x_min and word["y"] >= y_min:
            return True
        if word["x"] <= binding:
            return True
        # за рамкой чертежа: строка печати плоттера («Время печати: … 21.03.2025 10:44:08»), метки обреза
        if word["y"] <= edge or word["y"] >= height_pt - edge or word["x"] >= width_pt - edge:
            return True
        # слово со знаками битой кодировки шрифта: сравнивать его текст нельзя
        if GARBLED_RE.search(word["t"]):
            return True
        # правый верхний угол: номер листа в рамке и штампы документооборота
        if word["x"] >= corner_x and word["y"] <= corner_y:
            return True
        if repeated:
            t, gx, gy = _furniture_key(word, width_pt, height_pt)
            if any((t, gx + a, gy + b) in repeated for a in (-1, 0, 1) for b in (-1, 0, 1)):
                return True
        return any(x0 <= word["x"] <= x1 and y0 <= word["y"] <= y1 for x0, y0, x1, y1 in stamps)

    return inside


def _match(old, new, used_o, used_n, dx, dy, region=None, only=None):
    """Слова, стоящие на своём месте при сдвиге (dx, dy): пары (i, j), по одной на слово.
    only(i) — какие старые слова сопоставлять; по умолчанию все."""
    by_text = collections.defaultdict(list)
    for j, w in enumerate(new):
        if j not in used_n:
            by_text[w["t"]].append(j)
    got = []
    for i, w in enumerate(old):
        if i in used_o:
            continue
        if region and not (region[0] <= w["x"] <= region[2] and region[1] <= w["y"] <= region[3]):
            continue
        if only is not None and not only(i):
            continue
        x, y = w["x"] + dx, w["y"] + dy
        best, best_d = None, POS_TOL_PT
        for j in by_text.get(w["t"], ()):
            if j in used_n:
                continue
            d = max(abs(new[j]["x"] - x), abs(new[j]["y"] - y))
            if d <= best_d:
                best, best_d = j, d
        if best is not None:
            used_o.add(i)
            used_n.add(best)
            got.append((i, best))
    return got


def _votes(old, new, used_o, used_n):
    """Голоса редких слов за сдвиг: {(dx, dy) в шагах допуска: [(i, j)]}."""
    count_o = collections.Counter(w["t"] for i, w in enumerate(old) if i not in used_o)
    count_n = collections.Counter(w["t"] for j, w in enumerate(new) if j not in used_n)
    by_text = collections.defaultdict(list)
    for j, w in enumerate(new):
        if j not in used_n and count_n[w["t"]] <= RARE:
            by_text[w["t"]].append(j)
    votes = collections.defaultdict(list)
    for i, w in enumerate(old):
        if i in used_o or count_o[w["t"]] > RARE:
            continue
        for j in by_text.get(w["t"], ()):
            dx, dy = new[j]["x"] - w["x"], new[j]["y"] - w["y"]
            votes[(round(dx / POS_TOL_PT), round(dy / POS_TOL_PT))].append((i, j))
    return votes


def _zones(boxes, width_pt, height_pt):
    """Рамки слов в зоны: близкие сливаются; в долях видимой страницы, самые крупные первыми."""
    zones = [list(b) for b in boxes]
    merged = True
    while merged:
        merged = False
        for a in range(len(zones)):
            for b in range(a + 1, len(zones)):
                p, q = zones[a], zones[b]
                if (p[0] - ZONE_GAP_PT <= q[2] and q[0] - ZONE_GAP_PT <= p[2]
                        and p[1] - ZONE_GAP_PT <= q[3] and q[1] - ZONE_GAP_PT <= p[3]):
                    zones[a] = [min(p[0], q[0]), min(p[1], q[1]), max(p[2], q[2]), max(p[3], q[3])]
                    del zones[b]
                    merged = True
                    break
            if merged:
                break
    zones.sort(key=lambda z: (z[2] - z[0]) * (z[3] - z[1]), reverse=True)
    return [[round(max(0.0, min(1.0, v / s)), 4) for v, s in zip(z, (width_pt, height_pt, width_pt, height_pt))]
            for z in zones[:MAX_ZONES]]


def _scaled(words, kx, ky):
    """Слова, перенесённые на лист другого формата пропорционально: лист перевыпущен
    в другом формате с тем же чертежом (лист 2 цепочки 23.009-Р-ГИ: А2 → А1)."""
    return [{"t": w["t"], "x": w["x"] * kx, "y": w["y"] * ky,
             "box": (w["box"][0] * kx, w["box"][1] * ky, w["box"][2] * kx, w["box"][3] * ky)} for w in words]


def _align(old, new, fixed=None):
    """Слова по месту со сдвигами: (совпавшие старые, совпавшие новые, сдвиги [dx, dy, слов]).

    Первый сдвиг — общий для листа, по всем редким словам. Следующие — сдвиги частей листа:
    за сдвиг должна голосовать заметная доля (LOCAL_SUPPORT) ещё не сопоставленных редких слов
    его области. Вид, сдвинутый целиком, голосует почти весь, даже если тянется на всю ширину
    листа (средний вид листа 7 цепочки 23.009-Р-ГИ); случайные совпадения, разбросанные
    по листу, дают малую долю, и такой сдвиг совпадений наделал бы из частых слов вроде «500».
    """
    used_o, used_n, offsets = set(), set(), []
    for k in range(MAX_OFFSETS):
        votes = _votes(old, new, used_o, used_n)
        counts = collections.Counter(w["t"] for i, w in enumerate(old) if i not in used_o)
        chosen = None
        for key in sorted(votes, key=lambda q: len(votes[q]), reverse=True):
            near = [p for a in (-1, 0, 1) for b in (-1, 0, 1) for p in votes.get((key[0] + a, key[1] + b), ())]
            if len(near) < (FIRST_VOTES if k == 0 else MIN_VOTES):
                break
            if k == 0:
                chosen = (near, None)
                break
            xs, ys = [old[i]["x"] for i, _ in near], [old[i]["y"] for i, _ in near]
            region = (min(xs) - REGION_PT, min(ys) - REGION_PT, max(xs) + REGION_PT, max(ys) + REGION_PT)
            voters = {i for i, _ in near}
            rare = sum(1 for i, w in enumerate(old) if i not in used_o and counts[w["t"]] <= RARE
                       and region[0] <= w["x"] <= region[2] and region[1] <= w["y"] <= region[3])
            if len(voters) >= LOCAL_SUPPORT * max(rare, 1):
                chosen = (near, region)
                break
        if chosen is None:
            break
        near, region = chosen
        dx = statistics.median(new[j]["x"] - old[i]["x"] for i, j in near)
        dy = statistics.median(new[j]["y"] - old[i]["y"] for i, j in near)
        got = _match(old, new, used_o, used_n, dx, dy, region)
        if not got:
            break
        offsets.append([round(dx, 1), round(dy, 1), len(got)])
    if fixed is not None and offsets and (abs(offsets[0][0]) > 1 or abs(offsets[0][1]) > 1):
        # чертёж сдвинут внутри рамки, а рамка, штамп и поле подшивки остались на месте
        got = _match(old, new, used_o, used_n, 0.0, 0.0, only=fixed)
        if got:
            offsets.append([0.0, 0.0, len(got)])
    return used_o, used_n, offsets


def _reading_order(items):
    """Слова в порядке чтения: строки сверху вниз, в строке — слева направо. items — [(ключ, слово)]."""
    if not items:
        return []
    heights = sorted(w["box"][3] - w["box"][1] for _, w in items)
    tol = max(2.0, heights[len(heights) // 2] / 2)
    lines, line, top = [], [], 0.0
    for item in sorted(items, key=lambda it: (it[1]["y"], it[1]["x"])):
        if line and item[1]["y"] - top > tol:
            lines.append(line)
            line = []
        if not line:
            top = item[1]["y"]
        line.append(item)
    lines.append(line)
    return [it for ln in lines for it in sorted(ln, key=lambda it: it[1]["x"])]


def _stream(items):
    """Поток текста: [(текст, [ключи слов])] в порядке чтения. Слово, перенесённое со знаком «-»
    в конце строки, склеивается: в другой редакции оно могло встать в строку целиком. Дефисы
    при сравнении не учитываются (`_flow`): «ОККМ(н)-» и «00-НГ(а)» в строку сливаются
    в «ОККМ(н)00-НГ(а)», а в другой редакции стоит «ОККМ(н)-00-НГ(а)»."""
    out = []
    for key, w in _reading_order(items):
        t = w["t"]
        if out and len(out[-1][0]) > 2 and out[-1][0][-1] in "-\u00ad" and t[:1].isalnum():
            out[-1] = (out[-1][0][:-1] + t, out[-1][1] + [key])
        else:
            out.append((t, [key]))
    return out


def page_stream(layer, repeated=frozenset()):
    """Поток текста содержания страницы — без служебных полей. Для `place`: соседние страницы."""
    words = _pt_words(layer) if layer else []
    if not words:
        return []
    inside = service_zone(words, layer.get("width_pt") or 1.0, layer.get("height_pt") or 1.0, repeated)
    return _stream([(i, w) for i, w in enumerate(words) if not inside(w)])


def _flow(page_old, near_old, page_new, near_new):
    """Слова страницы, стоящие в другой редакции тем же текстом и в том же порядке — на этой же
    странице или на соседней. page_* — поток страницы (`_stream`), near_* — потоки предыдущей
    и следующей страниц своей редакции (None — страницы нет). Возвращает два словаря
    {ключ слова: -1, 0 или 1} — на какой странице другой редакции слово нашлось: предыдущей,
    этой же или следующей. В счёт идут только совпавшие отрезки от FLOW_RUN слов, где не меньше
    FLOW_LETTER_WORDS слов из букв: строка текста, а не случайно совпавшие числа чертежей."""
    def window(page, near):
        prev, nxt = near or (None, None)
        return ([(-1, t, keys) for t, keys in prev or ()] + [(0, t, keys) for t, keys in page]
                + [(1, t, keys) for t, keys in nxt or ()])

    wo, wn = window(page_old, near_old), window(page_new, near_new)
    bare = lambda t: t.translate(BARE).lower() or t  # noqa: E731
    # частые слова («и», «мм», «100») отрезка не начинают, но входят в него продолжением: так
    # на плотном чертеже сравнение втрое быстрее, а отрезки те же (ОВ3 Полярной 16, 40 листов)
    sm = difflib.SequenceMatcher(None, [bare(t) for _, t, _ in wo], [bare(t) for _, t, _ in wn])
    got_old, got_new = {}, {}
    for a, b, size in sm.get_matching_blocks():
        if size < FLOW_RUN or sum(1 for _, t, _ in wo[a:a + size] if LETTERS_RE.search(t)) < FLOW_LETTER_WORDS:
            continue
        for (so, _, ko), (sn, _, kn) in zip(wo[a:a + size], wn[b:b + size]):
            if so == 0:
                got_old.update((k, sn) for k in ko)
            if sn == 0:
                got_new.update((k, so) for k in kn)
    return got_old, got_new


def place(old_layer, new_layer, repeated_old=frozenset(), repeated_new=frozenset(), old_near=None, new_near=None):
    """Где на листе изменилось: слова двух редакций по месту с поправкой на сдвиги. Задача #81.

    old_layer, new_layer — результат `reading.read_text_layer`: слова в долях видимой страницы
    и её размер в пунктах. Возвращает None, если слов нет хотя бы на одной стороне, иначе:
    layout — SAME_PLACE (лист на месте), SHIFTED (лист или его части сдвинуты), RESIZED (лист
    перевыпущен в другом формате), RELAID (совпало меньше MIN_MATCHED слов: лист перекомпонован,
    мест изменений не показываем); content_removed/added — сколько слов исчезло и появилось
    в содержании листа, moved — сколько подписей того же текста сдвинулись недалеко (размер
    перенесён, значение то же); service_removed/added — изменения служебных полей; numbers —
    «было → стало» для чисел, стоящих рядом; zones_old и zones_new — рамки изменений содержания
    в долях своей страницы; service — какие даты сменились в служебных полях («20.02.26 → 14.05.26»).
    repeated_old, repeated_new — слова, стоящие на большинстве страниц файла на одном месте
    (`furniture`): штампы документооборота, их изменения — служебные.

    old_near, new_near — потоки текста (`page_stream`) предыдущей и следующей страниц своей
    редакции: (предыдущая, следующая), None — страницы нет. С ними слова, не нашедшиеся по месту,
    ищутся в тексте другой редакции: стоящие там тем же текстом и в том же порядке — не изменения.
    flowed_out — сколько слов ушло на соседние страницы новой редакции, flowed_in — сколько пришло
    с соседних страниц прежней; слова, сдвинутые по той же странице дальше переноса подписи, —
    в moved. text_checked — поток текста проверен.
    """
    raw_old, new = _pt_words(old_layer), _pt_words(new_layer)
    if not raw_old or not new:
        return None
    ow, oh = old_layer.get("width_pt") or 1.0, old_layer.get("height_pt") or 1.0
    nw, nh = new_layer.get("width_pt") or 1.0, new_layer.get("height_pt") or 1.0
    in_old, in_new = service_zone(raw_old, ow, oh, repeated_old), service_zone(new, nw, nh, repeated_new)
    frames = [("points", raw_old, ow, oh)]
    if abs(ow - nw) > 0.01 * nw or abs(oh - nh) > 0.01 * nh:
        frames.insert(0, ("scaled", _scaled(raw_old, nw / ow, nh / oh), nw, nh))
    best = None
    for name, old, fw, fh in frames:
        used_o, used_n, offsets = _align(old, new, fixed=lambda i: in_old(raw_old[i]))
        if best is None or len(used_o) > len(best[1]):
            best = (name, used_o, used_n, offsets, old, fw, fh)
    frame, used_o, used_n, offsets, old, fw, fh = best
    share = len(used_o) / max(1, min(len(old), len(new)))
    gx, gy = (offsets[0][0], offsets[0][1]) if offsets else (0.0, 0.0)
    removed = [i for i in range(len(old)) if i not in used_o and not in_old(raw_old[i])]
    added = [j for j in range(len(new)) if j not in used_n and not in_new(new[j])]
    # текст перетёк на соседнюю страницу или сдвинулся по странице: тот же текст в том же порядке.
    # Раньше переноса подписей: иначе частые слова ушедшего и пришедшего абзацев («и», «в»)
    # сошлись бы в пары «перенесено»
    checked = old_near is not None or new_near is not None
    flow_o, flow_n = {}, {}
    # без слов из букв среди не нашедшихся по месту перетекать нечему: на чертеже изменились размеры
    letters = (sum(1 for i in removed if LETTERS_RE.search(raw_old[i]["t"]))
               + sum(1 for j in added if LETTERS_RE.search(new[j]["t"])))
    if checked and letters >= FLOW_LETTER_WORDS:
        flow_o, flow_n = _flow(_stream([(i, raw_old[i]) for i in range(len(raw_old)) if not in_old(raw_old[i])]),
                               old_near, _stream([(j, new[j]) for j in range(len(new)) if not in_new(new[j])]),
                               new_near)
    flowed_out = sum(1 for i in removed if flow_o.get(i) in (-1, 1))
    flowed_in = sum(1 for j in added if flow_n.get(j) in (-1, 1))
    relaid = sum(1 for i in removed if flow_o.get(i) == 0)
    removed = [i for i in removed if i not in flow_o]
    added = [j for j in added if j not in flow_n]
    # подпись того же текста рядом — размер или надпись перенесены, значение то же
    moved_o, moved_n = set(), set()
    added_by_text = collections.defaultdict(list)
    for j in added:
        added_by_text[new[j]["t"]].append(j)
    for d, i, j in sorted((max(abs(new[j]["x"] - old[i]["x"] - gx), abs(new[j]["y"] - old[i]["y"] - gy)), i, j)
                          for i in removed for j in added_by_text.get(old[i]["t"], ())):
        limit = MOVE_PT if NUMERIC_RE.match(old[i]["t"]) else MOVE_TEXT_PT
        if d <= limit and i not in moved_o and j not in moved_n:
            moved_o.add(i)
            moved_n.add(j)
    content_r = [old[i] for i in removed if i not in moved_o and not SEPARATOR_RE.match(old[i]["t"])]
    content_a = [new[j] for j in added if j not in moved_n and not SEPARATOR_RE.match(new[j]["t"])]
    service_r = [old[i] for i in range(len(old)) if i not in used_o and in_old(raw_old[i])]
    service_a = [new[j] for j in range(len(new)) if j not in used_n and in_new(new[j])]
    moved = any(abs(o[0]) > 1 or abs(o[1]) > 1 for o in offsets) or len(offsets) > 1
    layout = ("RELAID" if share < MIN_MATCHED else "RESIZED" if frame == "scaled"
              else "SHIFTED" if moved else "SAME_PLACE")
    out = {"layout": layout, "matched": len(used_o), "matched_share": round(share, 3), "offsets": offsets,
           "content_removed": len(content_r), "content_added": len(content_a),
           "moved": len(moved_o) + relaid, "flowed_out": flowed_out, "flowed_in": flowed_in,
           "text_checked": checked,
           "service_removed": len(service_r), "service_added": len(service_a),
           "numbers": _number_pairs(content_r, content_a, gx, gy)[:MAX_CHANGES],
           "removed_sample": [w["t"] for w in sorted(content_r, key=lambda w: (w["y"], w["x"]))][:SAMPLE],
           "added_sample": [w["t"] for w in sorted(content_a, key=lambda w: (w["y"], w["x"]))][:SAMPLE],
           # штамп и рамка со сдвигом чертежа не едут: даты служебных полей сравниваются без сдвига
           "service": _number_pairs(service_r, service_a, 0.0, 0.0, pattern=DATE_RE)[:4],
           "zones_old": [], "zones_new": []}
    if layout != "RELAID":
        out["zones_old"] = _zones([w["box"] for w in content_r], fw, fh)
        out["zones_new"] = _zones([w["box"] for w in content_a], nw, nh)
    return out


def _number_pairs(removed, added, dx, dy, pattern=None):
    """Пары «было → стало» по месту: удалённое и добавленное слово рядом друг с другом.
    Для содержания — только числа: подпись, ставшая другой, видна и в построчном сравнении;
    для служебных полей — даты."""
    ok = (pattern or NUMERIC_RE).match
    was = [w for w in removed if ok(w["t"])]
    now = [v for v in added if ok(v["t"])]
    cands = []
    for a, w in enumerate(was):
        for b, v in enumerate(now):
            if v["t"] == w["t"]:
                continue
            ddx, ddy = v["x"] - w["x"] - dx, v["y"] - w["y"] - dy
            if abs(ddx) <= PAIR_PT and abs(ddy) <= PAIR_PT:
                d = (ddx * ddx + ddy * ddy) ** 0.5
                if d <= PAIR_PT:
                    cands.append((d, a, b))
    used_a, used_b, pairs = set(), set(), []
    for d, a, b in sorted(cands):
        if a in used_a or b in used_b:
            continue
        used_a.add(a)
        used_b.add(b)
        pairs.append((was[a]["y"], was[a]["x"], f"{was[a]['t']} → {now[b]['t']}"))
    return [p[2] for p in sorted(pairs)]


def content_changed(row):
    """Изменилось ли содержание листа, а не только служебные поля: True, False или None — неизвестно.

    Ответ даёт сравнение по месту (`place`). Если лист перекомпонован или слов нет, остаётся
    построчное сравнение: оно не отличает служебные поля от содержания, и ответа нет. Кроме
    переверстанной страницы, весь текст которой нашёлся в другой редакции в том же порядке:
    её содержание то же."""
    where = row.get("place")
    if row.get("status") in ("ADDED", "REMOVED"):
        return True
    if where and where.get("layout") == "RELAID" and _same_text(where):
        return False
    if row.get("status") not in ("CHANGED", "UNREADABLE") or not where or where.get("layout") == "RELAID":
        return None if row.get("status") in ("CHANGED", "UNREADABLE") else False
    changed = where["content_removed"] + where["content_added"]
    if not changed:
        return False
    # одно-два слова без пары чисел — сдвинутая подпись или обломок штампа, а не правка проекта:
    # судить по ним, изменился ли лист, нельзя
    if changed < MIN_CHANGED_WORDS and not where.get("numbers"):
        return None
    return True


# ---------------------------------------------------------------- отмечено ли изменение (#81)
#
# Изменение листа проектировщик отмечает дважды: строкой в таблице изменений основной надписи
# самого листа («3 | Зам. | 158-26 | подпись | 02.26») и в примечании ведомости рабочих чертежей
# на листе «Общие данные» («Изм. 3 (Зам.)» в строке листа). Номер изменения, появившийся
# в новой редакции, должен стоять хотя бы в одном из этих мест у каждого изменённого листа.

LIST_MARK_RE = re.compile(r"^[Ии]зм\.?(\d{1,2})?$")
LIST_KIND_RE = re.compile(r"^\(?(Зам|Нов|Аннул|Изм)\.?\)?,?$", re.I)
LIST_NUMBER_RE = re.compile(r"^\d{1,2}$")
LIST_SHEET_RE = re.compile(r"^\d{1,3}$")
LIST_COLUMN_MM = 12.0        # номер листа в ведомости — в колонке «Лист» шириной 15 мм
LIST_HEADER_MM = 150.0       # «Наименование» стоит правее «Лист» в пределах этого
LIST_MARK_MM = 14.0          # номер изменения — сразу правее «Изм.»
LIST_KIND_MM = 30.0          # вид изменения «(Зам.)» — правее номера
LIST_GAP_MM = 60.0           # пустота по вертикали, на которой ведомость кончилась


def listed_changes(words, page_size=None):
    """Отметки изменений в ведомости рабочих чертежей: {номер листа: [{number, kind}]}. Задача #81.

    Ведомость узнаётся по шапке «Лист … Наименование» вне основной надписи. Номера листов стоят
    в колонке «Лист» под шапкой по возрастанию; отметки «Изм. 1 (Зам.)» — в той же строке таблицы,
    обычно столбиком в примечании, по вертикали вокруг середины строки. Поэтому отметки сначала
    собираются в столбики, а столбик относится к ближайшему по высоте номеру листа.
    """
    from pipeline import coords, titleblock
    size = coords.page_mm(page_size)
    if not size or not words:
        return {}
    w_mm, h_mm = size
    bx, by = titleblock.band_bounds(page_size)
    items = [w for w in words if not (w["bbox"][0] >= bx and w["bbox"][1] >= by)]

    def cy(w):
        return (w["bbox"][1] + w["bbox"][3]) / 2

    def cx(w):
        return (w["bbox"][0] + w["bbox"][2]) / 2

    heads = []
    for w in items:
        if w["t"].strip().rstrip(".") != "Лист":
            continue
        if any(v["t"].strip().startswith("Наименован") and abs(cy(v) - cy(w)) < 3 / h_mm
               and 0 < v["bbox"][0] - w["bbox"][0] < LIST_HEADER_MM / w_mm for v in items):
            heads.append(w)
    out = {}
    for head in heads:
        col = LIST_COLUMN_MM / w_mm
        rows = sorted((w for w in items if LIST_SHEET_RE.match(w["t"].strip()) and abs(cx(w) - cx(head)) <= col
                       and cy(w) > cy(head)), key=cy)
        sheets, last_y, last_n = [], cy(head), 0
        for w in rows:
            n = int(w["t"])
            if (cy(w) - last_y) * h_mm > LIST_GAP_MM:
                break
            if n <= last_n:
                continue
            sheets.append((n, cy(w)))
            last_y, last_n = cy(w), n
        if not sheets:
            continue
        top, bottom = cy(head), sheets[-1][1] + LIST_GAP_MM / 2 / h_mm
        marks = []
        for w in items:
            m = LIST_MARK_RE.match(w["t"].strip())
            if not m or not top < cy(w) < bottom or w["bbox"][0] < head["bbox"][0]:
                continue
            number = int(m.group(1)) if m.group(1) else None
            right = sorted((v for v in items if abs(cy(v) - cy(w)) < 2 / h_mm and 0 < v["bbox"][0] - w["bbox"][0]
                            < (LIST_MARK_MM + LIST_KIND_MM) / w_mm), key=lambda v: v["bbox"][0])
            if number is None:
                num = next((v for v in right if LIST_NUMBER_RE.match(v["t"].strip())
                            and v["bbox"][0] - w["bbox"][0] < LIST_MARK_MM / w_mm), None)
                if num is None:
                    continue
                number = int(num["t"])
            kind = next((LIST_KIND_RE.match(v["t"].strip()).group(1).capitalize() + "." for v in right
                         if LIST_KIND_RE.match(v["t"].strip())), None)
            if not 1 <= number <= 50:
                continue
            marks.append((cy(w), w["bbox"][3] - w["bbox"][1], number, kind))
        if not marks:
            continue
        marks.sort()
        height = statistics.median(m[1] for m in marks) or 2 / h_mm
        stacks, cur = [], [marks[0]]
        for m in marks[1:]:
            if m[0] - cur[-1][0] <= 1.7 * height:
                cur.append(m)
            else:
                stacks.append(cur)
                cur = [m]
        stacks.append(cur)
        centers = [y for _, y in sheets]
        for stack in stacks:
            # столбик, перекрывший середины двух строк, делится между ними по ближайшей середине
            for y, _, number, kind in stack:
                mid = sum(m[0] for m in stack) / len(stack)
                inside = [c for c in centers if stack[0][0] - height <= c <= stack[-1][0] + height]
                anchor = mid if len(inside) <= 1 else y
                sheet = sheets[min(range(len(centers)), key=lambda k: abs(centers[k] - anchor))][0]
                bucket = out.setdefault(sheet, [])
                if not any(b["number"] == number for b in bucket):
                    bucket.append({"number": number, "kind": kind})
    for sheet in out:
        out[sheet].sort(key=lambda b: b["number"])
    return out


def file_marks(pages):
    """Отметки изменений по файлу: pages — [(страница, слой `read_text_layer`)].

    Возвращает {"stamp": {страница: [номера]}, "listed": {лист: [номера]}, "numbers": [все номера],
    "readable": [страницы]}: номера из таблиц изменений штампов по страницам и из ведомостей рабочих
    чертежей по листам; readable — страницы, у которых таблица изменений штампа читается.
    """
    from pipeline import titleblock
    stamp, listed, readable = {}, {}, []
    for page_no, layer in pages:
        size = (layer.get("width_pt"), layer.get("height_pt"))
        rows = titleblock.change_rows(layer.get("words") or [], size)
        if rows:
            stamp[page_no] = [r["number"] for r in rows]
        if rows or titleblock.change_table_readable(layer.get("words") or [], size):
            readable.append(page_no)
        for sheet, marks in listed_changes(layer.get("words") or [], size).items():
            got = listed.setdefault(sheet, [])
            got += [m["number"] for m in marks if m["number"] not in got]
    numbers = sorted({n for ns in stamp.values() for n in ns} | {n for ns in listed.values() for n in ns})
    return {"stamp": stamp, "listed": {k: sorted(v) for k, v in listed.items()}, "numbers": numbers,
            "readable": readable}


def _substantial(row):
    """Изменение, о котором можно спорить с проектировщиком: изменилось число на своём месте или
    не меньше SUBSTANTIAL_WORDS слов содержания. Несколько сдвинутых слов без чисел — чаще всего
    обломки штампа или перенос подписи, а не правка проекта."""
    where = row.get("place") or {}
    if where.get("numbers"):
        return True
    return where.get("content_removed", 0) + where.get("content_added", 0) >= SUBSTANTIAL_WORDS


def _numbers_phrase(numbers):
    """«изменение 3 не отмечено» или «изменения 1, 2 не отмечены»."""
    listed = ", ".join(map(str, numbers)) or "—"
    return f"изменения {listed} не отмечены" if len(numbers) > 1 else f"изменение {listed} не отмечено"


def registration(rows, old_marks, new_marks, sheet_of):
    """Отмечено ли изменение каждого изменённого листа. Меняет строки на месте, возвращает сводку.

    Номера изменений новой редакции — те, что есть в её штампах и ведомостях, но нет в прежней.
    Строка получает `registration`:
    - REGISTERED — номер нового изменения стоит в штампе листа или у листа в ведомости;
    - UNREGISTERED — содержание листа изменилось, а номера нет ни там, ни там;
    - NOT_NEEDED — изменились только служебные поля или текст сдвинулся на соседние страницы;
    - UNKNOWN — ответа нет: в новой редакции нет ни одной отметки, номер листа не подтверждён,
      сравнение по месту не сказало, изменилось ли содержание, или ведомость с отметками
      не найдена.
    «Без отметки» утверждается, только когда в новой редакции разобрана ведомость с отметками:
    без неё неизвестно, как проектировщик отмечает изменения — у Полярной 16 изм. 2 тома КЖ6.1
    стоит только в штампе листа «Общие данные», на выпуск целиком. Добавленный лист без отметки
    «Нов.» — тоже UNKNOWN: признак «добавлен» даёт выравнивание страниц, и он ненадёжен. Изменение
    без изменившихся чисел меньше SUBSTANTIAL_WORDS слов — UNKNOWN: это обломки штампов и переносы. И лист,
    чья таблица изменений в штампе не читается (чертёжный шрифт в слой не попадает — КЖ04 Полярной 16:
    строка «2 Зам.» в штампе есть, а в слое её нет), — UNKNOWN.
    sheet_of(страница новой редакции) → номер листа или None.
    """
    introduced = sorted(set(new_marks.get("numbers") or []) - set(old_marks.get("numbers") or []))
    summary = collections.Counter()
    for row in rows:
        if row["status"] not in ("CHANGED", "UNREADABLE", "ADDED") or row.get("new_page") is None:
            continue
        changed = content_changed(row)
        sheet = sheet_of(row["new_page"])
        stamp = set((new_marks.get("stamp") or {}).get(row["new_page"]) or [])
        listed = set((new_marks.get("listed") or {}).get(sheet) or []) if sheet is not None else set()
        got = sorted((stamp | listed) & set(introduced))
        if changed is False:
            status, why = "NOT_NEEDED", ("содержание листа не изменилось: только служебные поля, перенос строк "
                                          "или текст, сдвинувшийся на соседние страницы")
        elif got:
            where = (["штамп листа"] if stamp & set(introduced) else []) + (["ведомость"] if listed & set(introduced) else [])
            status, why = "REGISTERED", f"изм. {', '.join(map(str, got))}: {' и '.join(where)}"
        elif not introduced:
            status, why = "UNKNOWN", "в новой редакции нет отметок об изменениях"
        elif sheet is None:
            status, why = "UNKNOWN", "номер листа не определён"
        elif changed is None:
            status, why = "UNKNOWN", "не удалось сравнить лист по месту или изменение слишком мало"
        elif not new_marks.get("listed"):
            status, why = "UNKNOWN", "ведомость с отметками изменений не найдена: как отмечен лист, проверить нельзя"
        elif not _substantial(row):
            status, why = "UNKNOWN", ("изменение невелико и без изменившихся чисел: отмечать ли его, "
                                      "решает проектировщик, гипотезой оно не идёт")
        elif "readable" in new_marks and row["new_page"] not in set(new_marks["readable"]):
            status, why = "UNKNOWN", ("таблица изменений в штампе листа не читается текстовым слоем "
                                      "(чертёжный шрифт): отметку в штампе проверить нельзя")
        elif row["status"] == "ADDED":
            status, why = "UNKNOWN", "новый лист: отметка «Нов.» у него не найдена"
        else:
            status, why = "UNREGISTERED", f"{_numbers_phrase(introduced)} ни в штампе листа, ни в ведомости"
        row["registration"] = {"status": status, "why": why, "sheet": sheet, "numbers": got}
        summary[status] += 1
    return {"introduced": introduced, **{k.lower(): v for k, v in summary.items()}}


# ---------------------------------------------------------------- гипотезы «изменение без отметки» (#81)

UNMARKED_CODE = "FREE-REV-UNMARKED"
UNMARKED_TITLE = "Лист изменён в новой редакции без отметки об изменении"
UNMARKED_CRITICALITY = "Существенное (предписание) — требует утверждения"
UNMARKED_STAGES = ("RD",)    # гипотезы — по рабочей документации: там отметка ставится у каждого листа
GROUP_LIMIT = 3              # больше листов без отметки в паре — одна запись с перечнем
MAX_EVIDENCE = 5             # страниц-доказательств в записи с перечнем


def _sheet_label(code, sheet, page):
    head = f"{code}, " if code else ""
    return f"{head}лист {sheet}" if sheet is not None else f"{head}стр. {page}"


def _samples(where):
    """«убрано: 6900, 1800 …», «добавлено: …» — когда пар «было → стало» нет."""
    out = []
    for key, word, total in (("removed_sample", "убрано", "content_removed"), ("added_sample", "добавлено", "content_added")):
        if where.get(key):
            more = where.get(total, 0) - len(where[key])
            out.append(f"{word}: " + ", ".join(where[key]) + (f" и ещё {more}" if more > 0 else ""))
    return out


def _what(where):
    numbers = where.get("numbers") or []
    if numbers:
        return ", ".join(numbers[:4]) + (f" и ещё {len(numbers) - 4}" if len(numbers) > 4 else "")
    head = f"изменено слов на листе: убрано {where.get('content_removed', 0)}, добавлено {where.get('content_added', 0)}"
    return "; ".join([head] + _samples(where))


def _page_evidence(stage, file_id, page, revision, quote, zones, sheet=None):
    return {"stage": stage, "file_id": file_id, "pdf_page_number": page, "document_sheet_number": sheet,
            "revision": revision, "quote": quote, "localization": "BBOX" if zones else "PAGE_LEVEL",
            "boxes_norm": zones or []}


def _unmarked_record(object_id, pair, suffix, label, rd_value, detail, evidence):
    return {
        "finding_id": f"{object_id}::REV::{pair['old_file_id']}-{pair['new_file_id']}::{suffix}",
        "object_id": object_id,
        "matrix_scope": "FREE_SEARCH",
        "parameter_code": UNMARKED_CODE,
        "parameter_id": None,
        "title": UNMARKED_TITLE,
        "comparison_result": "CONFIGURATION_MISMATCH",
        "location_type": "OBJECT",
        "locations": [label],
        "pd_value": None,
        "rd_value": rd_value,
        "id_value": None,
        "violation_label": "VIOLATION_PRESENT",
        "criticality": UNMARKED_CRITICALITY,
        "finding_status": "SUSPICION",
        "needs_expert": True,
        "for_submission": False,
        "exclusion_reason": "гипотеза сравнения редакций: в сдачу — после решения инспектора",
        "evidence": evidence,
        "revision_pair": {"pair_id": pair.get("pair_id"), "old_file_id": pair["old_file_id"],
                          "new_file_id": pair["new_file_id"], "old_revision": pair.get("old_revision"),
                          "new_revision": pair.get("new_revision")},
        "extraction": {
            "rule_basis": ("изменение листа отмечается номером изменения в таблице изменений основной надписи "
                           "листа и в ведомости рабочих чертежей; номер нового изменения не найден ни там, ни там"),
            "detail": detail,
            "source": "revision_diff",
        },
    }


def unmarked(object_id, pair, rows, stage, code=None):
    """Гипотезы свободного поиска по листам, изменённым без отметки. Задача #81.

    Запись на лист, пока таких листов в паре не больше GROUP_LIMIT: инспектор решает по каждому
    листу отдельно. Если их больше — одна запись на пару с перечнем листов: двадцать гипотез
    «лист изменён» инспектору не нужны, ему нужен перечень (так же делает сверка экспликаций).
    Записи не идут в файл сдачи (`for_submission: false`), пока инспектор не взял их в кандидаты:
    подтверждённых точек такого вида в эталоне нет, а лишняя запись в сдаче стоит балла.
    Доказательства — новая и прежняя страницы с рамками изменений."""
    found = [r for r in rows if (r.get("registration") or {}).get("status") == "UNREGISTERED"]
    if not found:
        return []
    new_rev = pair.get("new_revision") or "новая редакция"
    old_rev = pair.get("old_revision") or "прежняя редакция"
    if len(found) <= GROUP_LIMIT:
        out = []
        for r in found:
            where, reg = r.get("place") or {}, r["registration"]
            # редакция в подписи: один лист бывает изменён без отметки в нескольких редакциях
            label = f"{_sheet_label(code, reg.get('sheet'), r['new_page'])}, {new_rev}"
            what = "лист добавлен" if r["status"] == "ADDED" else _what(where)
            why = reg.get("why") or ""
            detail = (f"{label}: содержание изменилось между «{old_rev}» ({pair['old_file_id']}, стр. {r['old_page']}) и "
                      f"«{new_rev}» ({pair['new_file_id']}, стр. {r['new_page']}) — {what}. {why[:1].upper() + why[1:]}.")
            evidence = [_page_evidence(stage, pair["new_file_id"], r["new_page"], pair.get("new_revision"),
                                       f"{new_rev}: {what}", where.get("zones_new"), reg.get("sheet"))]
            if r.get("old_page") is not None:
                evidence.append(_page_evidence(stage, pair["old_file_id"], r["old_page"], pair.get("old_revision"),
                                               f"{old_rev}: прежний вид листа", where.get("zones_old")))
            out.append(_unmarked_record(object_id, pair, str(r["new_page"]), label, f"{new_rev}: {what}", detail, evidence))
        return out
    sheets = [r["registration"].get("sheet") for r in found]
    listed = ", ".join(str(x) for x in sheets if x is not None)
    label = (f"{code}, листы {listed}" if code and listed else _sheet_label(code, None, found[0]["new_page"])) + f", {new_rev}"
    parts = [f"{_sheet_label(None, r['registration'].get('sheet'), r['new_page'])} — "
             f"{'лист добавлен' if r['status'] == 'ADDED' else _what(r.get('place') or {})}" for r in found]
    detail = (f"в «{new_rev}» ({pair['new_file_id']}) изменено листов без отметки: {len(found)} "
              f"({_numbers_phrase(pair.get('introduced') or [])} ни в штампе листа, ни в ведомости); " + "; ".join(parts))
    evidence = [_page_evidence(stage, pair["new_file_id"], r["new_page"], pair.get("new_revision"),
                               f"{new_rev}: {_what(r.get('place') or {})}", (r.get("place") or {}).get("zones_new"),
                               r["registration"].get("sheet")) for r in found[:MAX_EVIDENCE]]
    return [_unmarked_record(object_id, pair, "GROUP", label, f"{new_rev}: листов без отметки {len(found)}",
                             detail[:2000], evidence)]
