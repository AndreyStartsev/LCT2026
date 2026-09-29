"""Исполнительная схема у объекта, который читается без модели: какой моделью и по какому адресу (Р-168).

  python tests/test_id_scheme_model.py

Исполнительные схемы читаются моделью и при способе «распознавание» (Р-77, `pipeline/pages.py`):
числа на них нарисованы, и распознавание их не берёт. Шаг разбора передавал имя модели только способу
«модель», и схему читал `reading.DEFAULT_MODEL` вместо модели сервиса. На стенде это был другой
провайдер, в поставке своя модель отвечала на чужое имя 404, и схема без ключа не читалась, а с ключом
уходила на запасной адрес, из контура. Теперь схему читает модель сервиса по его адресу. Своя модель
проверяется один раз, без ожидания. «Только слой» модель не зовёт.

Путь проверяется целиком: окружение воркера из docker-compose.yml и надстройки поставки → шаг
разбора до чтения страниц → pages.build → read_page → read_model. Сети нет: `reading._post_model`
подставной. Он записывает адрес и имя модели и отвечает как сервер: vLLM на чужое имя модели
отвечает 404, OpenRouter без ключа не спрашивается. Подставная и проверка своей модели
(`settings.model_route`): она записывает, сколько её ждали.

- стенд :8080 и демо: модель через OpenRouter, ключ задан в .env;
- поставка на H100: своя модель в http://llm:8000, OpenRouter — запасной адрес. На стенде проверки
  ключа нет, на репетиции он может быть.
"""
import contextlib
import hashlib
import importlib
import io
import multiprocessing
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="test-id-scheme-model-")
BASE_ENV = {"PIPELINE_OUT": os.path.join(TMP, "build"), "PIPELINE_CACHE": os.path.join(TMP, "cache"),
            "PIPELINE_RENDER_DIR": os.path.join(TMP, "render"), "WORK_DIR": os.path.join(TMP, "work")}
os.environ.update(BASE_ENV)

import pymupdf  # noqa: E402

from pipeline import cli, pages, reading  # noqa: E402
from service.worker import infra, measure_pages, settings, steps  # noqa: E402

OBJ = "TST-ID-SCHEME"
PID = "tst-id-scheme"
SCHEME = "ИД/КЖ/Исполнительная схема вертикальных конструкций на отм. -5,250.pdf"
LLM = "http://llm:8000/v1/chat/completions"
OPENROUTER = reading.OPENROUTER_URL
SERVED = "qwen/qwen3.6-27b"          # под этим именем сервер своей модели её раздаёт (service/llm)
KEY = "key-for-test"
ANSWER = "Отм. -5,250; отклонение от вертикали +8 мм"
DOWN = "своя модель не отвечает (ConnectionRefusedError)"
# переменные оболочки, которые подменили бы окружение стенда: ключ, имя модели, адреса
FOREIGN = re.compile(r"^(PIPELINE_|BENCH_MODEL$|OPENROUTER_API_KEY$|LLM_|INSPECTOR_)")


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def compose_env(path, variables):
    """Окружение воркера из файла compose: `${X:-по умолчанию}` раскрывается по `.env` стенда."""
    text = open(os.path.join(ROOT, path), encoding="utf-8").read()
    block = re.search(r"^  worker:\n(.*?)(?=^  \S|\Z)", text, re.S | re.M).group(1)
    env = re.search(r"^    environment:\n(.*?)(?=^    \S|\Z)", block, re.S | re.M).group(1)

    def expand(m):
        name, op, default = m.group(1), m.group(2) or "", m.group(3) or ""
        return variables.get(name) or (default if op == ":-" else "")

    return {name: re.sub(r"\$\{([A-Z0-9_]+)(?:(:[-?])([^}]*))?\}", expand, value.strip().strip('"'))
            for name, value in re.findall(r"^      ([A-Z][A-Z0-9_]*):(.*)$", env, re.M)}


def stand(variables):
    """Стенд :8080 и демо-стенд: docker-compose.yml."""
    return compose_env("docker-compose.yml", variables)


def release(variables):
    """Поставка на H100: docker-compose.yml и надстройка deploy/docker-compose.release.yml."""
    return {**stand(variables), **compose_env("deploy/docker-compose.release.yml", variables)}


def make_scheme():
    """Лист А3 с подписью и без растра: чертёж с тонким слоем, его модель читает (Р-117)."""
    path = os.path.join(steps.files_dir(PID), SCHEME)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=1191, height=842)
    page.insert_text((60, 80), "Ispolnitelnaya skhema, otm. -5,250", fontsize=14)
    doc.save(path)
    doc.close()
    with open(path, "rb") as f:
        return path, hashlib.sha256(f.read()).hexdigest()


class Conn:
    """Соединение с базой: запросы записываются, строк нет."""
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))
        return self

    def fetchall(self):
        return []

    def fetchone(self):
        return None


class InlinePool:
    """Пул чтения страниц в этом же процессе: иначе подставной `_post_model` не дойдёт до страницы."""
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def imap(self, fn, tasks, chunksize=1):
        return map(fn, tasks)


class Stop(Exception):
    """Шаг разбора дочитал страницы: остальное ему здесь не нужно."""


def stand_in(env, route=("main", None), llm_up=True):
    """Окружение стенда и подставные сервер модели и проверка своей модели. Возвращает, что они видели."""
    for name in [n for n in os.environ if FOREIGN.match(n)]:
        del os.environ[name]
    os.environ.update({**BASE_ENV, **env})
    importlib.reload(settings)
    importlib.reload(reading)
    for path in ("cache", "build"):
        shutil.rmtree(os.path.join(TMP, path), ignore_errors=True)
    seen = {"calls": [], "waits": [], "service_model": settings.model_for(None)}

    def post(url, key_env, body, timeout):
        seen["calls"].append((url, body["model"]))
        if reading.is_openrouter(url) and not os.environ.get(key_env):
            return None, f"нет {key_env}", False
        if url == LLM and not llm_up:
            return None, "ConnectionRefusedError", True
        if url == LLM and body["model"] != SERVED:
            return None, "HTTP 404", False         # vLLM: модели с таким именем на сервере нет
        return {"model": body["model"], "usage": {"prompt_tokens": 2700, "completion_tokens": 20},
                "choices": [{"finish_reason": "stop", "message": {"content": ANSWER}}]}, None, False

    def model_route(wait_s=None, progress=None, sleep=None):
        seen["waits"].append(wait_s)
        return route

    reading._post_model = post
    settings.model_route = model_route
    return seen


@contextlib.contextmanager
def inline_pool():
    pool, multiprocessing.Pool = multiprocessing.Pool, InlinePool
    try:
        yield
    finally:
        multiprocessing.Pool = pool


def parse(env, mode, sha, route=("main", None), llm_up=True):
    """Шаг разбора с окружением стенда до чтения страниц включительно.

    Возвращает, что шаг передал чтению страниц, какие адреса и имена модели спрошены, сколько ждали
    свою модель, что записано у страницы схемы и что сказано инспектору.
    """
    seen = stand_in(env, route, llm_up)

    def registry(args):
        cli.write_jsonl(steps.out_path(args.object, "documents.jsonl"), [{
            "file_id": "TST-000001", "object_id": OBJ, "stage": "ID", "section": "KZh",
            "relative_path": SCHEME, "sha256": sha, "pdf_pages": 1, "extension": ".pdf",
            "duplicate_of": None, "revision_status": "CURRENT"}])

    build = pages.build

    def read_pages(obj, todo, **kwargs):
        seen["passed"] = {k: kwargs.get(k) for k in ("use_model", "model", "id_scheme_model")}
        with inline_pool():
            seen["rows"] = build(obj, todo, **kwargs)
        raise Stop

    saved = (steps.materialize, infra.progress, cli.cmd_registry)
    steps.materialize = lambda conn, process: 1    # файл уже выложен: хранилища нет
    infra.progress = lambda *args, **kwargs: None  # Redis нет
    cli.cmd_registry = registry
    pages.build = read_pages
    conn, log = Conn(), io.StringIO()
    try:
        with contextlib.redirect_stdout(log):
            steps.step_parse(conn, {"id": PID, "object_id": OBJ, "object_name": "схема", "reading_mode": mode})
    except Stop:
        pass
    finally:
        steps.materialize, infra.progress, cli.cmd_registry = saved
        pages.build = build
    row = (seen.get("rows") or [{}])[0]
    seen["read"] = ANSWER in (row.get("text") or "")
    seen["notes"] = [params[4] for sql, params in conn.sql if "notifications" in sql]
    seen["log"] = [line for line in log.getvalue().splitlines() if line.startswith("исполнительные схемы")]
    return seen


def measure(env, path, mode):
    """Замер скорости чтения (measure_pages) на файле схемы: читает тем же путём, что разбор."""
    seen = stand_in(env)
    use_ocr, use_model = mode != "layer", mode == "model"
    with inline_pool(), contextlib.redirect_stdout(io.StringIO()):
        got = measure_pages.measure(path, mode, use_ocr, use_model, None, workers=1, max_pages=None, stage="ID")
    seen["model_calls"] = got["model_calls"]
    return seen


def short(calls):
    return ", ".join(f"{'OpenRouter' if reading.is_openrouter(url) else url.split('/v1')[0]} ← {model}"
                     for url, model in calls) or "не спрашивалась"


def main():
    path, sha = make_scheme()
    ok = True

    print("стенд :8080 и демо (ключ OpenRouter задан)")
    env = stand({"INSPECTOR_OPENROUTER_API_KEY": KEY})
    got = parse(env, "model", sha)
    want = got["service_model"]
    ok &= check("модель сервиса — первая из PIPELINE_MODEL_CHOICES", want == SERVED, want)
    ok &= check("способ «модель»: схему читает модель сервиса", got["calls"] == [(OPENROUTER, want)] and got["read"],
                short(got["calls"]))
    got = parse(env, "tesseract", sha)
    ok &= check("способ «распознавание»: схему читает та же модель сервиса",
                got["calls"] == [(OPENROUTER, want)] and got["read"] and got["passed"]["id_scheme_model"] is True,
                f"{short(got['calls'])}; шаг разбора передал {got['passed']}")
    ok &= check("свою модель проверили один раз и без ожидания", got["waits"] == [0], str(got["waits"]))
    got = parse(env, "layer", sha)
    ok &= check("способ «только слой»: модель не зовётся и не проверяется",
                got["calls"] == [] and got["waits"] == [] and got["passed"]["id_scheme_model"] is False,
                short(got["calls"]))
    got = measure(env, path, "tesseract")
    ok &= check("замер скорости читает схему так же, как разбор",
                got["calls"] == [(OPENROUTER, want)] and got["model_calls"] == 1, short(got["calls"]))

    print("\nстенд без ключа модели")
    got = parse(stand({}), "tesseract", sha)
    ok &= check("модели нет — схема читается без неё, без лишних вызовов и уведомлений",
                got["calls"] == [] and got["waits"] == [] and not got["notes"], short(got["calls"]))

    print("\nпоставка на H100, стенд проверки: своя модель, ключа OpenRouter нет")
    env = release({})
    got = parse(env, "tesseract", sha)
    ok &= check("способ «распознавание»: схему читает своя модель", got["calls"] == [(LLM, want)] and got["read"],
                short(got["calls"]))
    got = parse(env, "tesseract", sha, route=(None, DOWN), llm_up=False)
    ok &= check("своя модель не отвечает, запасного адреса нет — схема без модели, инспектору сказано",
                got["calls"] == [] and any("Исполнительные схемы прочитаны без модели" in n for n in got["notes"]),
                "; ".join(got["notes"]) or "уведомлений нет")
    got = parse(env, "model", sha, route=(None, DOWN), llm_up=False)
    ok &= check("способ «модель», своя модель не поднялась — объект читается распознаванием, "
                "схемы не спрашивают её второй раз",
                got["calls"] == [] and got["waits"] == [None] and not got["log"],
                f"{short(got['calls'])}; проверок модели {len(got['waits'])}")

    print("\nпоставка на H100, репетиция: своя модель и ключ OpenRouter для запасного адреса")
    env = release({"INSPECTOR_OPENROUTER_API_KEY": KEY})
    got = parse(env, "tesseract", sha)
    ok &= check("способ «распознавание»: схема не уходит из контура, её читает своя модель",
                got["calls"] == [(LLM, want)] and got["read"], short(got["calls"]))
    got = parse(env, "tesseract", sha, route=("fallback", DOWN), llm_up=False)
    ok &= check("своя модель не отвечает — схему читает запасной адрес той же моделью, инспектору сказано",
                got["calls"] == [(LLM, want), (OPENROUTER, want)] and got["read"]
                and any("по запасному адресу" in n for n in got["notes"]),
                f"{short(got['calls'])}; " + ("; ".join(got["notes"]) or "уведомлений нет"))

    shutil.rmtree(TMP, ignore_errors=True)
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
