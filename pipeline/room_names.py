"""Сверка наименований помещений: один ли это номер в томе раздела, в экспликации и в рабочей стадии. Задача #46.

Сравнение по помещениям идёт по номеру. Но номер в томе инженерного раздела может
расходиться с экспликацией того же проекта. Тюменская-5: том ОВ проектной стадии (F0171)
называет помещением 140 кабинет «Физического эксперимента», а одиннадцать других томов
проекта и вся рабочая стадия — кабинет «Моделирования и конструирования»; физический
эксперимент у них — помещение 143. Таблица систем ОВ назначает местные отсосы «помещению
140», имея в виду кабинет, который по экспликации носит номер 143.

На закрытом объекте, где том раздела или рабочая стадия нумеруют помещения по-своему,
каждое помещение проекта оказалось бы «не названо в рабочей стадии» — пачка ложных
находок высокой критичности. Поэтому:

1. У каждой находки по помещению проверяется, что номер носит то же наименование в томе,
   откуда взята находка, и в остальной документации. Если нет — в пояснении сказано,
   какое помещение том имел в виду и под каким номером оно стоит в экспликации.
2. Если на объекте номера массово носят разные наименования в двух стадиях, сравнение
   по номеру отвечает «сравнение невозможно» с причиной, а не находками.

Откуда наименования. Словарь «номер — наименование» по стадиям берётся из экспликаций
(`build/<объект>/rooms_pages.jsonl`): после #15 наименование собирается только из своего
столбца, и записи чистые. У тома-источника своей экспликации часто нет — тогда берутся
подписи у номера на его листах (`plan_rooms.jsonl`). Они шумные: распознавание обрезает
(«моделирования» вместо «Моделирования и конструирования»), подписи соседей склеиваются
(«Астрономии Физического эксперимента» у номера 140), а на листах спецификаций рядом
с числом стоит что угодно («140 Стеллаж»).

Поэтому вопрос ставится в одну сторону: **названо ли чистое наименование номера среди
слов тома-источника**. Если нет, а наименование у номера приметное (не «Тамбур»,
которых на этаже десять), ищется другой номер, чьё приметное наименование том-источник
называет целиком и который сам в этом томе «не занят». Один такой номер — расхождение
найдено; ни одного или несколько — ответа нет, и находка остаётся как была.
"""
import collections
import re

MIN_WORD = 5                 # короткие слова в подписях — предлоги и обрывки
SHARE_IN_LABELS = 0.4        # слово входит в наименование номера, если стоит в такой доле записей
SAME_OVERLAP = 0.5           # доля общих слов, при которой два наименования — одно помещение
COVERED = 0.6                # доля слов чистого наименования, названная в подписях тома
DISTINCT_MAX = 2             # наименование приметное, если его носят не больше двух номеров
# Доля номеров с разными наименованиями в двух стадиях, выше которой сравнивать по номеру
# нельзя. Замер (docs/room-names-report.md): Тюменская-5 — 0,005 (1 из 195), стадии
# нумеруют одинаково; Алтуфьевское — 0,42 (5 из 12), рабочая стадия сдвинула номера
# начиная с четырнадцатого. Порог 0,3 лежит между ними с запасом в обе стороны
RENUMBERED_SHARE = 0.3
MIN_COMPARED = 5             # на трёх помещениях доля ничего не значит

STAGES = {"PD": "PD", "RD": "RD", "RD_ID_MIXED": "RD"}


def stem(word):
    w = word.lower().replace("ё", "е")
    return w[:-2] if len(w) > 6 else w


def name_words(name):
    """Значимые слова наименования: основы слов от пяти букв."""
    return {stem(w) for w in re.findall(r"[А-Яа-яЁё]{%d,}" % MIN_WORD, name or "")}


def same(a, b):
    """Одно ли помещение называют два набора слов. Обрезанное наименование допустимо."""
    if not a or not b:
        return None
    common = len(a & b)
    return common >= 1 and common / min(len(a), len(b)) >= SAME_OVERLAP


def covered(name, bag):
    """Какая доля слов наименования названа среди слов bag."""
    return len(name & bag) / len(name) if name else 0.0


class Names:
    """Наименования помещений объекта: словарь экспликаций по стадиям и подписи тома-источника."""

    def __init__(self, clean, labels=()):
        """clean — записи экспликаций, labels — подписи на листах: [(стадия, file_id, номер, текст)]."""
        self.clean = collections.defaultdict(lambda: collections.defaultdict(list))
        self.clean_by_file = collections.defaultdict(lambda: collections.defaultdict(list))
        self.labels_by_file = collections.defaultdict(lambda: collections.defaultdict(set))
        # наименования как написаны — для пояснения находки: инспектору нужны слова, а не основы
        self.text = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
        self.label_text = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
        for stage, file_id, number, name in clean:
            stage, words = STAGES.get(stage), name_words(name)
            if stage and words:
                self.clean[stage][number].append((file_id, words))
                self.clean_by_file[file_id][number].append(words)
                self.text[stage][number][" ".join(name.split())] += 1
        for _stage, file_id, number, name in labels:
            self.labels_by_file[file_id][number] |= name_words(name)
            if name:
                self.label_text[file_id][number][" ".join(name.split())] += 1
        self._names, self._carriers = {}, {}

    def shown(self, stage, number):
        """Наименование номера в стадии так, как оно написано в экспликации: самое частое и полное."""
        found = self.text[stage].get(number)
        if not found:
            return None
        top = max(found.values())
        return max((n for n, c in found.items() if c >= top * 0.5), key=len)

    def shown_in_file(self, file_id, number):
        found = self.label_text[file_id].get(number)
        return max(found, key=lambda n: (found[n], len(n))) if found else None

    @staticmethod
    def _vote(bags):
        """Слова, которые повторяются от записи к записи; у единственной записи — все её слова."""
        if not bags:
            return set()
        if len(bags) == 1:
            return set(bags[0])
        counts = collections.Counter(w for bag in bags for w in bag)
        return {w for w, n in counts.items() if n / len(bags) >= SHARE_IN_LABELS}

    def name(self, stage, number, skip_file=None):
        """Чистое наименование номера в стадии по экспликациям."""
        key = (stage, number, skip_file)
        if key not in self._names:
            self._names[key] = self._vote([w for fid, w in self.clean[stage].get(number, [])
                                           if fid != skip_file])
        return self._names[key]

    def distinctive(self, stage, words, skip_file=None):
        """Приметное ли наименование: носят ли его не больше двух номеров стадии."""
        if not words:
            return False
        key = (stage, frozenset(words), skip_file)
        if key not in self._carriers:
            # носитель — номер, чьё наименование называет почти все эти слова: «моделирования»
            # у помещения 312 не делает неприметным «моделирования и конструирования» у 140
            self._carriers[key] = sum(1 for n in self.clean[stage]
                                      if covered(words, self.name(stage, n, skip_file)) >= COVERED)
        return self._carriers[key] <= DISTINCT_MAX

    def source_bag(self, file_id, number):
        """Как том называет номер: его экспликация, а если её нет — слова подписей на его листах."""
        own = self._vote(list(self.clean_by_file[file_id].get(number, [])))
        return own or set(self.labels_by_file[file_id].get(number, set()))

    def check(self, number, source_file):
        """Сверка номера находки с остальной документацией.

        Возвращает словарь: source — как номер назван в томе-источнике; pd, rd — чистые
        наименования номера в стадиях без этого тома; status — SAME, DIFFERENT или UNKNOWN;
        carried_by — номер, под которым остальная документация называет помещение тома.
        """
        bag = self.source_bag(source_file, number)
        pd = self.name("PD", number, skip_file=source_file)
        rd = self.name("RD", number, skip_file=source_file)
        out = {"source": sorted(bag), "pd": sorted(pd), "rd": sorted(rd),
               "status": "UNKNOWN", "carried_by": None,
               "source_text": self.shown_in_file(source_file, number),
               "pd_text": self.shown("PD", number), "rd_text": self.shown("RD", number)}
        if not bag:
            return out
        verdicts = []
        for stage, own in (("RD", rd), ("PD", pd)):
            if not own:
                continue
            if covered(own, bag) >= SAME_OVERLAP:
                verdicts.append(("SAME", None))
                continue
            if not self.distinctive(stage, own, source_file):
                continue
            rivals = []
            for other in self.clean[stage]:
                if other == number:
                    continue
                theirs = self.name(stage, other, source_file)
                if not theirs or covered(theirs, bag) < COVERED or not self.distinctive(stage, theirs, source_file):
                    continue
                # помещение, которое том сам называет под его номером, «занято»: его слова
                # попали в подпись от соседа по листу
                if covered(theirs, self.source_bag(source_file, other)) >= SAME_OVERLAP:
                    continue
                rivals.append(other)
            if len(rivals) == 1:
                verdicts.append(("DIFFERENT", rivals[0]))
        if not verdicts:
            return out
        kinds = {v[0] for v in verdicts}
        if kinds == {"SAME"}:
            out["status"] = "SAME"
        elif kinds == {"DIFFERENT"} and len({v[1] for v in verdicts}) == 1:
            out["status"], out["carried_by"] = "DIFFERENT", verdicts[0][1]
            out["carried_text"] = self.shown("RD", out["carried_by"]) or self.shown("PD", out["carried_by"])
        return out

    def renumbered_share(self, numbers):
        """Доля номеров, которые в двух стадиях носят разные приметные наименования.

        Возвращает (доля, сравнено, разных). В счёт идут только номера, по которым ответ
        возможен: наименования совпали либо оба приметные.
        """
        compared = different = 0
        for number in numbers:
            pd, rd = self.name("PD", number), self.name("RD", number)
            verdict = same(pd, rd)
            if verdict is None:
                continue
            if verdict:
                compared += 1
            elif self.distinctive("PD", pd) and self.distinctive("RD", rd):
                compared += 1
                different += 1
        return (different / compared if compared else 0.0), compared, different


def refusal(names, numbers):
    """Причина отказа от сравнения по номеру, если стадии нумеруют помещения по-разному.

    Возвращает (причина или None, сверено номеров, из них с разными наименованиями).
    """
    share, named, differ = names.renumbered_share(numbers)
    if named >= MIN_COMPARED and share > RENUMBERED_SHARE:
        return (f"номера помещений в двух стадиях носят разные наименования: {differ} из {named}; "
                f"сравнение по номеру невозможно"), named, differ
    return None, named, differ


def load(object_id, out_dir):
    """Наименования объекта из сборки: экспликации постранично и подписи на листах."""
    import json
    import os

    def rows(name):
        path = os.path.join(out_dir, object_id, name)
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    # в словарь идут только экспликации помещений: столбец номеров подписан «Номер помещения».
    # Без этого в него попадали экспликация зданий генплана («20 колледж существующий»)
    # и спецификации («25 Пилон монолитный»), и стадии «расходились» на каждом номере
    clean = [(r.get("stage"), r["file_id"], r["number"], r.get("name"))
             for r in rows("rooms_pages.jsonl") if r.get("labeled")]
    labels = [(r.get("stage"), r["file_id"], r["number"], r.get("name")) for r in rows("plan_rooms.jsonl")]
    return Names(clean, labels)


def note(number, checked):
    """Фраза для пояснения находки, если том-источник и остальная документация расходятся."""
    if checked["status"] != "DIFFERENT":
        return ""
    elsewhere = checked.get("rd_text") or checked.get("pd_text") or " ".join(checked["rd"] or checked["pd"])
    text = f"; по экспликации и в рабочей стадии номер {number} — «{elsewhere}»"
    if checked.get("carried_by"):
        text += (f", а том-источник называет этим номером помещение «{checked.get('carried_text') or '—'}», "
                 f"которое по экспликации стоит под номером {checked['carried_by']}")
    return text
