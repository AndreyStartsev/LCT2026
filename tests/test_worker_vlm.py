"""Проход модели по чертежам в воркере сервиса. Задача #98, поставка на стенд проверки (Р-98).

  python tests/test_worker_vlm.py

Проход был только в командной строке (`run --vlm`), и на объекте, загруженном через сервис,
30 правил `vlm_value` молчали: файла ответов не было. Теперь его запускает шаг разбора по флагу
PIPELINE_VLM. Проверяется:

- флаг выключен в основном compose и включён в надстройке поставки;
- вопросы в потоках дают тот же файл ответов, что и по одному, а PDF рисуется по очереди;
- ход прохода виден: всего листов и сколько спрошено;
- несостоявшийся вызов не кешируется и спрашивается снова, зациклившийся — кешируется;
- потолок вызовов общий на объект: прод-правила и черновики делят его;
- повторный разбор не зовёт модель, а коды с изменившимися ответами видит шаг сравнения.

Модель подставная, объект — три листа в одном PDF.
"""
import collections
import importlib.util
import json
import os
import re
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="test-worker-vlm-")
os.environ["PIPELINE_CACHE"] = os.path.join(TMP, "cache")
os.environ["PIPELINE_OUT"] = os.path.join(TMP, "build")
os.environ["PIPELINE_VLM_MAX_PX"] = "400"         # картинка листа маленькая: тест не про растр

import pymupdf  # noqa: E402

from pipeline import cli, config, matrix_rules, reading, vlm_values  # noqa: E402

OBJ = "TST-VLM"
RULE = {"kind": "vlm_value", "implemented": True, "unit": "%",
        "vlm": {"stage": "RD", "sections": ["AR"], "kinds": ["DRAWING"], "sheet_text": "кровл",
                "prompt": "Какой уклон кровли?"}}
DRAFT = {**RULE, "vlm": {**RULE["vlm"], "prompt": "Какой уклон кровли? (черновик)"}}


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def make_object():
    root = os.path.join(TMP, "files")
    os.makedirs(root, exist_ok=True)
    pdf = pymupdf.open()
    for _ in range(3):
        pdf.new_page(width=842, height=595)
    path = os.path.join(root, "AR.pdf")
    pdf.save(path)
    pdf.close()
    config.register_object(OBJ, root, "Тестовый объект")
    out = os.path.join(config.OUT, OBJ)
    os.makedirs(out, exist_ok=True)
    cli.write_jsonl(os.path.join(out, "documents.jsonl"), [
        {"file_id": "F1", "object_id": OBJ, "sha256": "ab" * 32, "relative_path": "AR.pdf", "stage": "RD",
         "section": "AR"}])
    # на листе n подписан уклон n+1 %: модель отвечает тем же, и ответ подтверждается текстом
    cli.write_jsonl(os.path.join(out, "pages.jsonl"), [
        {"file_id": "F1", "pdf_page_number": n, "stage": "RD", "section": "AR", "kind": "DRAWING",
         "width_pt": 842, "height_pt": 595, "text": f"План кровли, уклон {n + 1}%"} for n in (1, 2, 3)])


class FakeModel:
    """read_model: отвечает уклоном по номеру страницы из имени картинки; считает одновременность."""

    def __init__(self):
        self.lock = threading.Lock()
        self.active = self.peak = self.calls = 0
        self.fail_pages, self.loop_pages = set(), set()
        self.render_active = self.render_peak = 0

    def read_model(self, png, model=None, prompt=None, **kw):
        page_no = int(re.search(r"-(\d{5})-", os.path.basename(png)).group(1))
        with self.lock:
            self.active += 1
            self.calls += 1
            self.peak = max(self.peak, self.active)
        time.sleep(0.05)
        with self.lock:
            self.active -= 1
        if page_no in self.fail_pages:
            return {"text": "", "error": "URLError"}
        if page_no in self.loop_pages:
            return {"text": "", "looped": True, "error": vlm_values.LOOPED, "model": "fake"}
        return {"text": json.dumps({"values": [page_no + 1], "unit": "%"}), "model": "fake", "cost_usd": 0.0,
                "ms": 50}

    def render(self, doc, page_no, png, dpi=300, max_px=None):
        with self.lock:
            self.render_active += 1
            self.render_peak = max(self.render_peak, self.render_active)
        try:
            time.sleep(0.01)
            return REAL_RENDER(doc, page_no, png, dpi=dpi, max_px=max_px)
        finally:
            with self.lock:
                self.render_active -= 1


REAL_RENDER = reading.render


def use_rules(prod=True, draft=True):
    matrix_rules.load_rules = lambda path: {"parameters": {"TST-001": dict(RULE)}} \
        if prod and path == matrix_rules.QUEUES[2] else {"parameters": {}}
    matrix_rules.load_provisional = lambda q: {"parameters": {"TST-P01": dict(DRAFT)}} \
        if draft and q == 2 else None


def fresh_cache():
    reading.CACHE = tempfile.mkdtemp(prefix="cache-", dir=TMP)


def run_vlm(fake, workers=1, limit=40, provisional=False, fresh=False, progress=None, sheets=6):
    from argparse import Namespace
    reading.read_model, reading.render = fake.read_model, fake.render
    return cli.cmd_vlm(Namespace(object=OBJ, code=None, limit=limit, sheets=sheets, model=None, dry=False, fresh=fresh,
                                 provisional=provisional, workers=workers, progress=progress)) or {}


def values_file(provisional=False):
    path = vlm_values.path_for(OBJ, provisional=provisional)
    return open(path, encoding="utf-8").read() if os.path.exists(path) else ""


def test_compose():
    """Флаг по умолчанию включён (Р-118: прицельный подход по умолчанию везде); надстройка поставки
    на H100 (если она есть в копии — в master её нет, Р-113) тоже включает его."""
    ok = True
    main = open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8").read()
    ok &= check("docker-compose.yml: PIPELINE_VLM по умолчанию 1", "PIPELINE_VLM: ${PIPELINE_VLM:-1}" in main)
    release_path = os.path.join(ROOT, "deploy", "docker-compose.release.yml")
    if os.path.exists(release_path):
        release = open(release_path, encoding="utf-8").read()
        ok &= check("надстройка поставки: PIPELINE_VLM по умолчанию 1", "PIPELINE_VLM: ${PIPELINE_VLM:-1}" in release)
    spec = importlib.util.spec_from_file_location("settings_probe", os.path.join(ROOT, "service", "worker",
                                                                                 "settings.py"))
    for value, want in ((None, False), ("1", True), ("0", False)):
        if value is None:
            os.environ.pop("PIPELINE_VLM", None)
        else:
            os.environ["PIPELINE_VLM"] = value
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ok &= check(f"settings.VLM при PIPELINE_VLM={value!r} — {want}", module.VLM is want)
    os.environ.pop("PIPELINE_VLM", None)
    return ok


def test_threads_same_answers():
    """Потоки не меняют файл ответов, PDF рисуется по очереди, ход прохода виден."""
    ok = True
    use_rules(draft=False)
    fresh_cache()
    one = FakeModel()
    run_vlm(one, workers=1)
    single = values_file()
    fresh_cache()
    many = FakeModel()
    seen = []
    stats = run_vlm(many, workers=3, progress=lambda n, total: seen.append((n, total)))
    ok &= check("три листа — три вызова", many.calls == 3 and stats.get("вызовов") == 3, dict(stats))
    ok &= check("вопросы шли одновременно", many.peak >= 2, f"одновременно {many.peak}")
    ok &= check("по одному — по одному", one.peak == 1, f"одновременно {one.peak}")
    ok &= check("PDF рисовался по очереди", many.render_peak == 1, f"одновременно {many.render_peak}")
    ok &= check("файл ответов тот же, что и по одному", single and values_file() == single)
    rows = vlm_values.load(OBJ)
    ok &= check("значения по листам в порядке перечня",
                [(r["pdf_page_number"], r["values"]) for r in rows] == [(1, [2.0]), (2, [3.0]), (3, [4.0])],
                str([(r["pdf_page_number"], r["values"]) for r in rows]))
    ok &= check("ход: от 0 до 3 из 3", seen and seen[0] == (0, 3) and seen[-1] == (3, 3), str(seen))
    return ok


def test_failed_not_cached():
    """Модель не ответила — лист спрашивается снова; зациклилась — ответ кешируется."""
    ok = True
    use_rules(draft=False)
    fresh_cache()
    fake = FakeModel()
    fake.fail_pages, fake.loop_pages = {2}, {3}
    stats = run_vlm(fake, workers=2)
    ok &= check("сбой посчитан", stats.get("ошибка модели") == 1, dict(stats))
    kind = vlm_values.cache_kind("TST-001", RULE["vlm"]["prompt"])
    ok &= check("сбой не в кеше", reading.cache_get("ab" * 32, 2, kind) is None)
    ok &= check("зацикливание в кеше", (reading.cache_get("ab" * 32, 3, kind) or {}).get("looped") is True)
    fake.fail_pages = set()
    again = FakeModel()
    stats = run_vlm(again, workers=2)
    ok &= check("повторный проход спросил только лист со сбоем", again.calls == 1, f"вызовов {again.calls}")
    ok &= check("ответ листа со сбоем теперь в файле",
                [r["pdf_page_number"] for r in vlm_values.load(OBJ)] == [1, 2], dict(stats))
    # кеш до 25.09 писал и несостоявшиеся вызовы: такой ответ ответом не считается
    reading.cache_put("ab" * 32, 1, kind, {"text": "", "error": "HTTP 503"})
    ok &= check("старый сбой в кеше ответом не считается",
                vlm_values.cached_answer("ab" * 32, 1, "TST-001", RULE["vlm"]["prompt"]) is None)
    return ok


def test_cache_beyond_sheet_cap():
    """Потолок листов ограничивает новые вызовы, а не ответы из кеша (Р-139).

    Отбор идёт в порядке тома: у Речникова лист «Спецификация металлических ограждений балконов»
    — седьмой подходящий лист рабочей стадии, и пересборка с потолком 6 теряла его значение, хотя
    ответ модели по нему лежал в кеше и на листе подтверждался."""
    ok = True
    use_rules(draft=False)
    fresh_cache()
    run_vlm(FakeModel(), sheets=3)                      # все три листа спрошены, ответы в кеше
    capped = FakeModel()
    stats = run_vlm(capped, sheets=1, limit=0)          # пересборка: потолок листов 1, новых вызовов нет
    rows = [(r["pdf_page_number"], r["values"]) for r in vlm_values.load(OBJ)]
    ok &= check("листы за потолком отвечают из кеша, модель не зовётся",
                capped.calls == 0 and stats.get("из кеша") == 3, dict(stats))
    ok &= check("значения всех трёх листов на месте", rows == [(1, [2.0]), (2, [3.0]), (3, [4.0])], str(rows))
    fresh_cache()
    empty = FakeModel()
    stats = run_vlm(empty, sheets=1)
    ok &= check("без кеша потолок держит: спрошен один лист", empty.calls == 1, dict(stats))
    return ok


def test_worker_pass():
    """Шаг разбора: прод и черновики, общий потолок, повторный разбор без вызовов."""
    from service.worker import infra, settings, steps
    ok = True
    use_rules()
    fresh_cache()
    for provisional in (False, True):
        path = vlm_values.path_for(OBJ, provisional=provisional)
        if os.path.exists(path):
            os.remove(path)
    fake = FakeModel()
    reading.read_model, reading.render = fake.read_model, fake.render
    shown = []
    real_progress, real_limit, real_prov = infra.progress, vlm_values.CALLS_PER_OBJECT, settings.PROVISIONAL
    infra.progress = lambda pid, step, message, done=None, total=None: shown.append((step, message, done, total))
    try:
        settings.PROVISIONAL = True
        vlm_values.CALLS_PER_OBJECT = 4
        changed, stats = steps.vlm_pass("pid", OBJ)
        ok &= check("потолок общий: 3 вызова прода и 1 черновика", fake.calls == 4 and stats.get("вызовов") == 4,
                    dict(stats))
        ok &= check("черновикам не хватило двух листов", stats.get("лимит вызовов исчерпан") == 2, dict(stats))
        ok &= check("изменились ответы прод-правила", changed == {"TST-001"}, str(changed))
        ok &= check("ответы черновика — в своём файле",
                    [r["parameter_code"] for r in vlm_values.load(OBJ, provisional=True)] == ["TST-P01"])
        labels = {m for step, m, _d, _t in shown if step == "parse"}
        ok &= check("ход прохода виден у обоих профилей",
                    any("правила Матрицы" in m for m in labels) and any("черновики правил" in m for m in labels),
                    str(sorted(labels)))

        vlm_values.CALLS_PER_OBJECT = 40
        again = FakeModel()
        reading.read_model = again.read_model
        changed, stats = steps.vlm_pass("pid", OBJ)
        ok &= check("второй разбор дочитал два листа черновика", again.calls == 2, f"вызовов {again.calls}")
        ok &= check("прод-ответы не изменились — сравнению пересчитывать нечего", changed == set(), str(changed))

        third = FakeModel()
        reading.read_model = third.read_model
        changed, stats = steps.vlm_pass("pid", OBJ)
        ok &= check("повторный разбор модель не зовёт", third.calls == 0 and stats.get("из кеша") == 6, dict(stats))

        settings.PROVISIONAL = False
        fourth = FakeModel()
        reading.read_model = fourth.read_model
        changed, stats = steps.vlm_pass("pid", OBJ)
        ok &= check("черновики выключены — спрашивается только прод", stats.get("из кеша") == 3, dict(stats))
    finally:
        infra.progress, vlm_values.CALLS_PER_OBJECT, settings.PROVISIONAL = real_progress, real_limit, real_prov
    return ok


def main():
    make_object()
    results = collections.OrderedDict()
    for test in (test_compose, test_threads_same_answers, test_failed_not_cached, test_cache_beyond_sheet_cap,
                 test_worker_pass):
        print(test.__doc__.splitlines()[0])
        results[test.__name__] = test()
    reading.render = REAL_RENDER
    failed = [name for name, good in results.items() if not good]
    print("\nвсё прошло" if not failed else f"\nСБОИ: {', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
