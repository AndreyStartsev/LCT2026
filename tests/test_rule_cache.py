"""Кеш разбора стареет вместе с тем, от чего зависит, — и пересобирается по требованию.

  python tests/test_rule_cache.py

До этой правки ключом кеша кандидатов был хеш всех правил очереди и общий номер версии, а кеш
текста держался на своём номере. Правка примечания к одному правилу перечитывала правилами весь
корпус, поднятие номера — ещё и все PDF, а одинаковые номера в двух ветках отдавали друг другу
чужой разбор (#99; 24.09 — #98 и #112 на номере 23). Здесь проверяется, что:
- отпечаток кода видит правку кода вида и не видит комментарии и чужие виды;
- отпечаток правила не видит примечания и тип сравнения, но видит подписи и классы;
- кандидаты пересобираются только у изменившегося правила, и результат тот же, что без кеша;
- текст пересобирается из сырого слоя, не открывая PDF;
- флаги полного пересбора срабатывают один раз за прогон и сбрасываются.
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import fingerprint, matrix_rules as M  # noqa: E402

TEXT = ("Технико-экономические показатели здания. Площадь застройки 1200,5 м2. Этажность 9 этажей. "
        "Строительный объём 45 000 м3. Общая площадь 8 700 м2. Количество квартир 120 шт. "
        "Площадь участка 0,85 га. Высота здания 29,7 м от уровня земли до парапета кровли. "
        "Класс функциональной пожарной опасности Ф1.3, степень огнестойкости I. "
        "Все значения приняты по заданию на проектирование и расчётам раздела архитектурных решений.")


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


# ---------- отпечаток кода ----------

MODULES = {
    "mr": '''
from pipeline import ma, mb, common

KINDS = {"room"}


def helper(x):
    return common.norm(x)


def extract(rule, text, classes=None, doc=None, page_no=None):
    if rule.get("kind") in KINDS:
        return []
    if rule.get("kind") == "a":
        return ma.parse(helper(text))
    if rule.get("kind") in ("b", "c"):
        return mb.parse(text)
    return common.generic(text)


def _extract_document(doc, pages, active, rules):
    return [extract(r, t) for r in active.values() for _, t, _ in pages]


def decide(rule, pd, rd):
    return pd == rd
''',
    "ma": "def parse(text):\n    return [text]\n",
    "mb": "def parse(text):\n    return [text.upper()]\n",
    "common": "def norm(x):\n    return x.strip()\n\n\ndef generic(text):\n    return []\n",
}


def _digests(base):
    fingerprint.PIPELINE = base
    fingerprint._parsed.cache_clear()
    fingerprint.module_digest.cache_clear()
    return fingerprint.kind_digests("mr", "extract", ("_extract_document",), {"KINDS": {"room"}})


def test_code_fingerprint():
    """Правка кода старит только виды, до которых она дотягивается."""
    saved = fingerprint.PIPELINE
    base = tempfile.mkdtemp()
    try:
        def write(name, text):
            with open(os.path.join(base, name + ".py"), "w", encoding="utf-8") as f:
                f.write(text)
        for name, text in MODULES.items():
            write(name, text)
        before = _digests(base)
        ok = check("видов с веткой три и ещё общий отпечаток", set(before) == {"*", "room", "a", "b", "c"},
                   str(sorted(before)))

        def changed(name, text):
            write(name, text)
            got = _digests(base)
            write(name, MODULES[name])
            return sorted(k for k in before if got[k] != before[k])

        ok &= check("комментарий и строка документации не старят ничего",
                    changed("ma", '"""Разбор."""\n# проба\ndef parse(text):\n    return [text]\n') == [])
        ok &= check("правка модуля ветки «a» старит только «a»",
                    changed("ma", "def parse(text):\n    return [text, text]\n") == ["a"])
        ok &= check("модуль общей ветки «b, c» старит обе",
                    changed("mb", "def parse(text):\n    return [text.lower()]\n") == ["b", "c"])
        ok &= check("функция, которую зовёт ветка «a», старит только «a»",
                    changed("mr", MODULES["mr"].replace("return common.norm(x)", "return common.norm(x) + ''"))
                    == ["a"])
        ok &= check("решение (decide) разбор не старит",
                    changed("mr", MODULES["mr"].replace("return pd == rd", "return pd != rd")) == [])
        ok &= check("общий хвост разбора старит все виды",
                    changed("common", MODULES["common"].replace("return []", "return [text]"))
                    == sorted(before))
        ok &= check("правка общего модуля, которым пользуется ветка «a», старит «a» и общий хвост",
                    "a" in changed("common", MODULES["common"].replace("x.strip()", "x.lstrip()")))
    finally:
        fingerprint.PIPELINE = saved
        fingerprint._parsed.cache_clear()
        fingerprint.module_digest.cache_clear()
        shutil.rmtree(base, ignore_errors=True)
    return ok


def test_real_kinds():
    """На настоящем коде: виды правил найдены, отпечатки разных модулей разные."""
    d = M.kind_digests()
    ok = check("отпечаток есть у видов правил из очередей",
               {"element_class", "fire_barrier_limits", "vlm_value", "room_systems", "*"} <= set(d), str(len(d)))
    ok &= check("у предела огнестойкости и у марки стали отпечатки разные",
                d["fire_barrier_limits"] != d["element_steel_grade"])
    return ok


# ---------- отпечаток правила ----------

def test_rule_fingerprint():
    """Примечание и сравнение кеш не старят, подписи и классы — старят."""
    rule = {"kind": "area", "labels": ["площадь застройки"], "rule": "first", "note": "а",
            "basis": "б", "compare": {"type": "any_change"}, "implemented": True}
    fp = M.rule_fingerprint(rule)
    ok = check("правка примечания, основания и сравнения — тот же отпечаток",
               M.rule_fingerprint(dict(rule, note="в", basis="г", compare={"type": "decrease"})) == fp)
    ok &= check("правка подписи — другой отпечаток",
                M.rule_fingerprint(dict(rule, labels=["площадь участка"])) != fp)
    ok &= check("правка перечня классов — другой отпечаток",
                M.rule_fingerprint(rule, classes=["B25", "B30"]) != M.rule_fingerprint(rule, classes=["B25"]))
    ok &= check("ответы модели по документу не касаются правила без прохода",
                M.rule_fingerprint(rule, vlm="x") == fp)
    vlm_rule = dict(rule, kind="vlm_value")
    ok &= check("а правила с проходом — касаются",
                M.rule_fingerprint(vlm_rule, vlm="x") != M.rule_fingerprint(vlm_rule, vlm="y"))
    return ok


# ---------- кандидаты по правилам ----------

RULES = {"classes": {}, "parameters": {
    "PZ-001": {"kind": "area", "labels": ["площадь застройки"], "rule": "first", "implemented": True, "code": "PZ-001"},
    "PZ-004": {"kind": "volume", "labels": ["строительный объ[её]м"], "rule": "first", "implemented": True,
               "code": "PZ-004"},
}}


def _setup(base, pages):
    saved = {"CACHE": M.CACHE, "page_texts_src": M.page_texts_src, "vlm_digest": M.vlm_digest,
             "_extract_document": M._extract_document}
    M.CACHE = base
    M.page_texts_src = lambda doc, root, scans=True: iter(pages)
    M.vlm_digest = lambda doc, out=None, provisional=False: None
    calls = []
    real = saved["_extract_document"]

    def spy(doc, pages_, active, rules):
        calls.append(sorted(active))
        return real(doc, pages_, active, rules)
    M._extract_document = spy
    return saved, calls


def _restore(saved):
    for k, v in saved.items():
        setattr(M, k, v)
    os.environ.pop("PIPELINE_FRESH", None)
    os.environ.pop("PIPELINE_FRESH_RULES", None)
    M.reset_fresh()


def test_candidates_per_rule():
    base = tempfile.mkdtemp()
    doc = {"sha256": "ab" * 32, "relative_path": "ПД/ПЗ.pdf", "stage": "PD", "file_id": "F1"}
    pages = [(1, TEXT, "LAYER"), (2, "короткая", "LAYER")]
    saved, calls = _setup(base, pages)
    try:
        def run(rules):
            active = {c: r for c, r in rules["parameters"].items() if r.get("implemented")}
            calls.clear()
            got, _ = M.document_candidates(doc, "", active, rules)
            plain, _ = M.document_candidates(doc, "", active, rules, use_cache=False)
            return got, plain, [c for batch in calls[:-1] for c in batch]

        got, plain, extracted = run(RULES)
        ok = check("первый прогон разбирает оба правила", extracted == ["PZ-001", "PZ-004"], str(extracted))
        ok &= check("и даёт то же, что разбор без кеша", got == plain)
        ok &= check("кандидаты нашлись", bool(got) and set(got[0][2]) == {"PZ-001", "PZ-004"}, str(got)[:120])

        got2, plain2, extracted = run(RULES)
        ok &= check("второй прогон не разбирает ничего", extracted == [], str(extracted))
        ok &= check("и отдаёт то же самое", got2 == plain2 == got)

        noted = json.loads(json.dumps(RULES))
        noted["parameters"]["PZ-001"]["note"] = "новое примечание"
        noted["parameters"]["PZ-001"]["compare"] = {"type": "decrease"}
        _, _, extracted = run(noted)
        ok &= check("правка примечания и сравнения не разбирает ничего", extracted == [], str(extracted))

        relabeled = json.loads(json.dumps(RULES))
        relabeled["parameters"]["PZ-004"]["labels"] = ["объ[её]м здания", "строительный объ[её]м"]
        got3, plain3, extracted = run(relabeled)
        ok &= check("правка подписи одного правила разбирает только его", extracted == ["PZ-004"], str(extracted))
        ok &= check("и результат совпадает с разбором без кеша", got3 == plain3)
        _, _, extracted = run(RULES)
        ok &= check("откат правки не разбирает ничего: прежний вариант правила в кеше", extracted == [],
                    str(extracted))
        many = json.loads(json.dumps(RULES))
        for n in range(M.RULE_VARIANTS + 1):
            many["parameters"]["PZ-004"]["labels"] = [f"объ[её]м {n}", "строительный объ[её]м"]
            run(many)
        _, _, extracted = run(RULES)
        ok &= check(f"вариантов больше {M.RULE_VARIANTS} — самый давний вытеснен", extracted == ["PZ-004"],
                    str(extracted))
        run(relabeled)

        os.environ["PIPELINE_FRESH_RULES"] = "PZ-001"
        _, _, extracted = run(relabeled)
        ok &= check("PIPELINE_FRESH_RULES пересобирает только названное правило", extracted == ["PZ-001"],
                    str(extracted))
        _, _, extracted = run(relabeled)
        ok &= check("и только один раз за прогон", extracted == [], str(extracted))
        M.reset_fresh()
        _, _, extracted = run(relabeled)
        ok &= check("после reset_fresh — снова", extracted == ["PZ-001"], str(extracted))
        os.environ.pop("PIPELINE_FRESH_RULES")

        os.environ["PIPELINE_FRESH"] = "candidates"
        M.reset_fresh()
        _, _, extracted = run(relabeled)
        ok &= check("PIPELINE_FRESH=candidates пересобирает все правила", extracted == ["PZ-001", "PZ-004"],
                    str(extracted))
        os.environ.pop("PIPELINE_FRESH")

        pages[0] = (1, TEXT.replace("1200,5", "1300,5"), "LAYER")
        got4, plain4, extracted = run(relabeled)
        ok &= check("другой текст документа — разбираются все правила", extracted == ["PZ-001", "PZ-004"],
                    str(extracted))
        ok &= check("и значение новое", got4 == plain4 and got4[0][2]["PZ-001"][0]["value"] == 1300.5,
                    str(got4[0][2].get("PZ-001"))[:80])
    finally:
        _restore(saved)
        shutil.rmtree(base, ignore_errors=True)
    return ok


# ---------- текст: сырой слой отдельно ----------

def test_text_from_layer():
    import pymupdf
    base = tempfile.mkdtemp()
    saved = {"CACHE": M.CACHE, "_TEXT_FP": M._TEXT_FP}
    real_open = pymupdf.open
    try:
        M.CACHE = base
        root = os.path.join(base, "data")
        os.makedirs(root)
        pdf = pymupdf.open()
        page = pdf.new_page()
        page.insert_text((40, 60), TEXT[:90], fontname="helv")
        pdf.save(os.path.join(root, "doc.pdf"))
        doc = {"sha256": "cd" * 32, "relative_path": "doc.pdf", "extension": ".pdf"}

        first = list(M.page_texts_src(doc, root))
        ok = check("первое чтение отдаёт текст страницы", first and first[0][1].strip() != "", str(first)[:80])
        ok &= check("сырой слой лёг в свой кеш", os.path.exists(M._layer_cache_path(doc["sha256"])))

        def refuse(*a, **k):
            raise RuntimeError("PDF открывать нельзя")
        pymupdf.open = refuse
        M._TEXT_FP = "другой код обработки"
        again = list(M.page_texts_src(doc, root))
        ok &= check("обработка поменялась — текст собран из сырого слоя, PDF не открывался", again == first)
        with open(M._text_cache_path(doc["sha256"]), encoding="utf-8") as f:
            row = json.loads(f.readline())
        ok &= check("строка кеша помнит новый отпечаток обработки", row.get("pf") == "другой код обработки",
                    str(row.get("pf")))

        os.environ["PIPELINE_FRESH"] = "text"
        M.reset_fresh()
        refused = list(M.page_texts_src(doc, root))
        ok &= check("PIPELINE_FRESH=text открывает PDF заново (здесь — отказ, текста нет)", refused == [])
        pymupdf.open = real_open
        M.reset_fresh()
        fresh = list(M.page_texts_src(doc, root))
        ok &= check("с доступным PDF пересбор даёт тот же текст", fresh == first)
    finally:
        pymupdf.open = real_open
        os.environ.pop("PIPELINE_FRESH", None)
        M.reset_fresh()
        for k, v in saved.items():
            setattr(M, k, v)
        shutil.rmtree(base, ignore_errors=True)
    return ok


if __name__ == "__main__":
    print("Кеш разбора: отпечатки и пересбор по требованию")
    results = [test_code_fingerprint(), test_real_kinds(), test_rule_fingerprint(),
               test_candidates_per_rule(), test_text_from_layer()]
    print("\nИТОГ: " + ("все проверки пройдены" if all(results) else "есть сбои"))
    sys.exit(0 if all(results) else 1)
