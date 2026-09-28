"""Применимость раздела ПОД: предусмотрен ли на объекте снос. Четвёртая очередь Матрицы, #28.

Параметры ПОД (POD-090…097) сравнивают проект организации работ по сносу с ППР. Если сноса
на объекте нет, правильный ответ по ним — «неприменимо», а не «значение не найдено». Тома ПОД
в корпусе нет ни у одного объекта, поэтому применимость берётся из того, что о сносе говорят
другие разделы проектной документации.

Ответ бывает четырёх видов, по убыванию силы:
- «снос по отдельному проекту»: «объекты капитального строительства, которые подлежат сносу
  (разрабатывается отдельным проектом)», «Снос и демонтаж будет производится в рамках отдельного
  проекта» (Речников). В комплект объекта такой проект не входит, проверять его не по чему;
- «снос есть»: «Здания и сооружения, расположенные на участке, подлежат демонтажу в соответствии
  с разделом „Проект организации работ по сносу…“» (Новослободская), «Предусмотреть разработку
  проекта организации работ по сносу» (задание Изумрудной), «конструкций сносимых зданий» (ПОС
  Октябрьской), «Высота зоны развала сносимых зданий» и том «7. ТР снос» (Алтуфьевское);
- «сноса нет»: «Сооружения и строения, подлежащие сносу, на объекте отсутствуют» (ПЗУ Тюменской-5),
  «снос не предусмотрен», «раздел ПОД не разрабатывается»;
- ничего не сказано.

Шаблонные строки ответом не считаются: пункт пояснительной записки «Сведения о предполагаемых
затратах, связанных со сносом зданий и сооружений», название раздела сметы «…капитальный ремонт,
снос объекта…», ссылка на МДС 12-46.2008 и название части ООС «Мероприятия по обращению с отходами
строительства и сноса» — она есть в составе проекта и у Тюменской-5, где сноса нет. Подстрока
«снос» сидит в слове «безопасности», поэтому слово ищется только с начала.
"""
import json
import os
import re

from pipeline.config import OBJECTS, OUT

SEPARATE = [re.compile(p, re.I) for p in (
    r"подлежат\s+сносу\s*\(\s*разрабатывается\s+отдельн\w+\s+проект\w*",
    r"(?<![а-яё])снос\w*(?:\s+и\s+демонтаж\w*)?\s+буд\w+\s+производит\w*\s+в\s+рамках\s+отдельн\w+\s+проект\w*",
)]
DEMOLITION = [re.compile(p, re.I) for p in (
    r"(?:здани|сооружени|строени|объект\w*\s+капитального\s+строительства)[^.;]{0,80}?подлежат\s+(?:сносу|демонтажу)",
    r"предусмотреть\s+разработку\s+проекта\s+организации\s+работ\s+по\s+сносу",
    r"(?<![а-яё])сносим\w+\s+(?:здани|сооружени|строени|объект)\w*",
)]
NO_DEMOLITION = [re.compile(p, re.I) for p in (
    r"(?:здани|сооружени|строени)\w*(?:\s+и\s+(?:здани|сооружени|строени)\w*)?,?\s+подлежащ\w+\s+сносу,?\s+"
    r"(?:на\s+(?:объекте|участке|территории)\s+)?отсутству\w*",
    r"отсутству\w+\s+(?:здани|сооружени|строени)\w*[^.;]{0,60}?подлежащ\w+\s+(?:сносу|демонтажу)",
    # «снос существующих зданий проектом не предусмотрен», «снос … на участке не предусматривается»
    r"(?<![а-яё])снос\w*\s+(?:(?:существующ|здани|сооружени|строени|проект|документаци|объект|участк|на|в|данн)\w*\s+){0,4}"
    r"не\s+(?:предусм|требует|планиру)\w*",
    r"организации\s+работ\s+по\s+сносу[^.;]{0,120}?не\s+(?:разрабатыва|требует|предусм)\w*",
)]
# «7. ТР снос Алтуфьевское ш 79Б корр.pdf», «…-П-ПОД1.pdf»
FILE_NAME = re.compile(r"(?<![А-ЯЁа-яё])снос|[-_\s]ПОД\d*(?![А-ЯЁа-яё])")

STATUS_ORDER = ("SEPARATE_PROJECT", "APPLICABLE", "NOT_APPLICABLE")
REASONS = {
    "SEPARATE_PROJECT": "снос выполняется по отдельному проекту и в комплект объекта не входит",
    "APPLICABLE": "снос на объекте предусмотрен",
    "NOT_APPLICABLE": "сноса на объекте нет",
    "UNKNOWN": "в проектной документации о сносе не сказано",
}


def statements(flat):
    """Высказывания о сносе на странице: [(вид, цитата)]."""
    out = []
    for kind, patterns in (("SEPARATE_PROJECT", SEPARATE), ("APPLICABLE", DEMOLITION),
                           ("NOT_APPLICABLE", NO_DEMOLITION)):
        for rx in patterns:
            for m in rx.finditer(flat):
                out.append((kind, " ".join(flat[max(0, m.start() - 40):m.end() + 40].split())))
    return out


def decide(found):
    """Решение по объекту. found: [(вид, file_id, страница, цитата)], страница None — имя файла."""
    for status in STATUS_ORDER:
        own = [f for f in found if f[0] == status]
        if own:
            quote = own[0][3]
            return {"status": status, "reason": f"{REASONS[status]}: «{quote}»",
                    "evidence": [{"file_id": fid, "pdf_page_number": page, "quote": q}
                                 for _, fid, page, q in own[:3]]}
    return {"status": "UNKNOWN", "reason": REASONS["UNKNOWN"], "evidence": []}


def applicability(object_id, page_texts):
    """Применимость ПОД по проектной документации объекта. page_texts(doc, root) → [(страница, текст)]."""
    spec = OBJECTS[object_id]
    with open(os.path.join(OUT, object_id, "documents.jsonl"), encoding="utf-8") as f:
        docs = [json.loads(line) for line in f if line.strip()]
    found = []
    for doc in docs:
        if doc.get("stage") != "PD" or doc.get("duplicate_of"):
            continue
        name = os.path.basename(doc["relative_path"])
        if FILE_NAME.search(os.path.splitext(name)[0]):
            found.append(("APPLICABLE", doc["file_id"], None, f"том «{name}»"))
        if doc.get("extension") != ".pdf":
            continue
        for page, text in page_texts(doc, spec["root"]):
            if text:
                flat = " ".join(text.split())
                found += [(kind, doc["file_id"], page, quote) for kind, quote in statements(flat)]
    return decide(found)


# ---------- защита сетей при сносе (POD-092) ----------

# «К работам приступать после выноса коммуникаций из пятна застройки по отдельному проекту» (СГП3
# Полярной 16): сети уходят из зоны работ до начала сноса, и защищать при сносе нечего. Вынос одной
# сети («вынос сети выполняется АО "Мосводоканал" отдельным проектом») этого не значит
NETWORKS_SEPARATE = re.compile(
    r"после\s+(?:выноса|переустройства|перекладки)\s+(?:(?:существующ|инженерн|подземн)\w*\s+){0,2}"
    r"(?:коммуникаци\w*|сет(?:ей|и)(?![а-яё]))[^.;]{0,80}?по\s+отдельн\w+\s+проект\w*", re.I)


def networks_applicability(object_id, page_texts):
    """Применимость защиты действующих сетей при сносе (POD-092).

    Сначала — есть ли снос (`applicability`). Если есть, но сети из пятна застройки выносятся до
    начала работ по отдельному проекту, параметр неприменим: специалист, четвёртый круг
    (R4-Q-POD-092): «неприменим». Это пишут и в рабочей стадии — на стройгенплане, поэтому
    читаются обе стадии.
    """
    base = applicability(object_id, page_texts)
    if base["status"] != "APPLICABLE":
        return base
    spec = OBJECTS[object_id]
    with open(os.path.join(OUT, object_id, "documents.jsonl"), encoding="utf-8") as f:
        docs = [json.loads(line) for line in f if line.strip()]
    found = []
    for doc in docs:
        if doc.get("stage") not in ("PD", "RD", "RD_ID_MIXED") or doc.get("duplicate_of") \
                or doc.get("extension") != ".pdf":
            continue
        for page, text in page_texts(doc, spec["root"]):
            if not text:
                continue
            flat = " ".join(text.split())
            for m in NETWORKS_SEPARATE.finditer(flat):
                found.append((doc["file_id"], page, " ".join(flat[max(0, m.start() - 40):m.end() + 40].split())))
    if not found:
        return base
    return {"status": "SEPARATE_PROJECT",
            "reason": f"сети из пятна застройки выносятся до начала работ по отдельному проекту: «{found[0][2]}»",
            "evidence": [{"file_id": fid, "pdf_page_number": page, "quote": q} for fid, page, q in found[:3]]}
