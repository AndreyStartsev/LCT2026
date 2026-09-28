"""Своя модель на видеокарте и запасной адрес: поставка на стенд проверки.

  python tests/test_model_fallback.py

На стенде проверки модель читает с собственной карты (deploy/docker-compose.release.yml),
а стенд разработки и демо-стенд — через OpenRouter, как раньше. Проверяется:

- размышление выключается у каждого адреса своим полем: OpenRouter — `reasoning`, vLLM —
  шаблоном чата (поле OpenRouter vLLM пропускает молча, и Qwen3.6 думает);
- своя модель не ответила — страница читается запасным адресом, если он задан, и в ответе
  это видно; не задан — ошибка, как раньше;
- плохой запрос (400) запасным не повторяется, а упавший по сети адрес какое-то время
  не спрашивается вовсе;
- воркер ждёт свою модель, пока она поднимается, и не ждёт, когда её контейнера нет;
- без запасного адреса и со стендом на OpenRouter всё как было.

Сервер модели подставной: http.server в потоке, отвечает как vLLM.
"""
import http.server
import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import reading  # noqa: E402

SETTINGS_PATH = os.path.join(ROOT, "service", "worker", "settings.py")
OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


class FakeModel(http.server.BaseHTTPRequestHandler):
    """Сервер модели: ответ, код и тело последнего запроса задаются полями класса."""
    status = 200
    text = "Лист 5. План 3 этажа"
    bodies = []

    def log_message(self, *args):
        pass

    def _send(self, status, payload):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/v1/models":
            self._send(200, {"data": [{"id": "qwen/qwen3.6-27b"}]})
        else:
            self._send(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).bodies.append({**body, "_auth": self.headers.get("Authorization")})
        if type(self).status != 200:
            self._send(type(self).status, {"error": "нет"})
            return
        self._send(200, {"model": body["model"], "usage": {"prompt_tokens": 2700, "completion_tokens": 12},
                         "choices": [{"finish_reason": "stop",
                                      "message": {"content": type(self).text}}]})


class KeyedModel(FakeModel):
    """Сервер, закрытый ключом, как vLLM с --api-key: без ключа 401 и на списке моделей."""
    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer server-secret-for-test":
            self._send(401, {"error": "нет ключа"})
            return
        super().do_GET()


def serve(handler):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"


def closed_port_url():
    """Адрес, где никто не слушает: так выглядит сервер модели, который ещё не поднялся."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/v1/chat/completions"


def page_png():
    path = os.path.join(tempfile.mkdtemp(), "page.png")
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
    return path


def configure(url, fallback="", key_env="LLM_API_KEY"):
    reading.MODEL_URL = url
    reading.MODEL_KEY_ENV = key_env
    reading.MODEL_FALLBACK_URL = fallback
    reading.MODEL_FALLBACK_KEY_ENV = "OPENROUTER_API_KEY"
    reading._primary_paused_until = 0.0


def load_settings(**env):
    saved = dict(os.environ)
    for name, value in env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    try:
        spec = importlib.util.spec_from_file_location("worker_settings_fallback", SETTINGS_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return mod


def test_thinking_off_per_address():
    local = reading.model_body("qwen/qwen3.6-27b", None, "AAAA", "http://llm:8000/v1/chat/completions")
    remote = reading.model_body("qwen/qwen3.6-27b", None, "AAAA", OPENROUTER)
    ok = check("своей модели размышление выключается шаблоном чата",
               local.get("chat_template_kwargs") == {"enable_thinking": False} and "reasoning" not in local,
               str({k: local.get(k) for k in ("chat_template_kwargs", "reasoning")}))
    ok &= check("OpenRouter получает своё поле, как раньше",
                remote.get("reasoning") == {"enabled": False, "exclude": True}
                and "chat_template_kwargs" not in remote)
    return ok


def test_server_kinds():
    saved = (reading.MODEL_SERVER, reading.MODEL_EXTRA_BODY)
    local = "http://host.docker.internal:11434/v1/chat/completions"
    try:
        reading.MODEL_SERVER, reading.MODEL_EXTRA_BODY = "ollama", ""
        body = reading.model_body("qwen2.5vl:7b", None, "AAAA", local)
        ok = check("Ollama: размышление выключается полем reasoning_effort",
                   body.get("reasoning_effort") == "none" and "chat_template_kwargs" not in body)
        reading.MODEL_SERVER = "openai"
        body = reading.model_body("m", None, "AAAA", local)
        ok &= check("прочий сервер: полей размышления нет вовсе",
                    not any(k in body for k in ("reasoning", "reasoning_effort", "chat_template_kwargs")))
        reading.MODEL_SERVER, reading.MODEL_EXTRA_BODY = "vllm", '{"top_k": 1, "temperature": 0.1}'
        body = reading.model_body("m", None, "AAAA", local)
        ok &= check("лишние поля доходят до своего сервера и сильнее своих",
                    body.get("top_k") == 1 and body.get("temperature") == 0.1)
        body = reading.model_body("m", None, "AAAA", OPENROUTER)
        ok &= check("OpenRouter лишних полей не получает, вид сервера на него не действует",
                    "top_k" not in body and body.get("temperature") == 0 and "reasoning" in body)
    finally:
        reading.MODEL_SERVER, reading.MODEL_EXTRA_BODY = saved
    ok &= check("ожидание ответа по умолчанию — 180 с, как было", reading.MODEL_TIMEOUT_S == 180.0)
    return ok


def test_primary_answers():
    server, url = serve(FakeModel)
    FakeModel.status, FakeModel.bodies = 200, []
    configure(url, fallback=OPENROUTER)
    got = reading.read_model(page_png(), model="qwen/qwen3.6-27b")
    ok = check("своя модель ответила — текст её, запасной не нужен",
               got.get("text") == FakeModel.text and not got.get("fallback"), str(got)[:120])
    ok &= check("ключа своей модели нет — заголовка авторизации нет",
                FakeModel.bodies and FakeModel.bodies[-1]["_auth"] is None)
    FakeModel.text = "<think>\nСначала подумаю.\n</think>\n\nЛист 5"
    got = reading.read_model(page_png(), model="qwen/qwen3.6-27b")
    ok &= check("блок размышления в начале ответа отрезается", got.get("text") == "Лист 5", repr(got.get("text")))
    FakeModel.text = "Лист 5. План 3 этажа"
    server.shutdown()
    return ok


def test_fallback_on_dead_primary():
    server, fallback = serve(FakeModel)
    FakeModel.status, FakeModel.bodies = 200, []
    configure(closed_port_url(), fallback=fallback)
    got = reading.read_model(page_png(), model="qwen/qwen3.6-27b")
    ok = check("своя модель не поднялась — страницу прочитал запасной адрес",
               got.get("text") == FakeModel.text and got.get("fallback") is True, str(got)[:120])
    ok &= check("основной адрес поставлен на паузу", reading._primary_paused_until > 0)
    FakeModel.bodies = []
    got = reading.read_model(page_png(), model="qwen/qwen3.6-27b")
    ok &= check("на паузе — сразу к запасному", got.get("fallback") is True and len(FakeModel.bodies) == 1)
    server.shutdown()
    return ok


class CutModel(FakeModel):
    """Запасной сервер, который отвечает по очереди из `script`: (текст, finish_reason, токенов)."""
    script = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).bodies.append(body)
        text, finish, tokens = type(self).script.pop(0)
        self._send(200, {"model": body["model"], "usage": {"prompt_tokens": 1000, "completion_tokens": tokens},
                         "choices": [{"finish_reason": finish, "message": {"content": text}}]})


def test_retry_via_fallback():
    """Переспрос обрезанного ответа (Р-115) при лежащей своей модели идёт тоже запасным адресом."""
    server, fallback = serve(CutModel)
    CutModel.bodies = []
    CutModel.script = [("Спецификация: поз. 1", "length", reading.MODEL_MAX_TOKENS),
                       ("Спецификация: поз. 1; поз. 2; штамп", "stop", 5000)]
    configure(closed_port_url(), fallback=fallback)
    got = reading.read_model(page_png(), model="qwen/qwen3.6-27b")
    ok = check("обрезанный ответ запасного переспрошен им же с потолком побольше",
               [b["max_tokens"] for b in CutModel.bodies] == [reading.MODEL_MAX_TOKENS, reading.MODEL_RETRY_TOKENS]
               and got.get("text") == "Спецификация: поз. 1; поз. 2; штамп", str(got)[:160])
    ok &= check("в ответе видно и переспрос, и запасной адрес, токены сложены",
                got.get("retried") is True and got.get("fallback") is True
                and got.get("tokens_out") == reading.MODEL_MAX_TOKENS + 5000)
    ok &= check("запасной адрес записывается у страницы", "fallback" in reading.MODEL_NOTE_KEYS)
    server.shutdown()
    return ok


def test_fallback_needs_key_for_openrouter():
    saved = os.environ.pop("OPENROUTER_API_KEY", None)
    try:
        configure(closed_port_url(), fallback=OPENROUTER)
        ok = check("OpenRouter без ключа запасным не считается",
                   [e[0] for e in reading.model_endpoints()] == [reading.MODEL_URL])
        got = reading.read_model(page_png(), model="qwen/qwen3.6-27b")
        ok &= check("свою модель не достали — ошибка сетевая, наружу никто не звал",
                    got.get("text") == "" and "ConnectionRefusedError" in (got.get("error") or ""), str(got))
    finally:
        if saved is not None:
            os.environ["OPENROUTER_API_KEY"] = saved
    return ok


def test_http_errors():
    primary_server, primary = serve(type("Primary", (FakeModel,), {"status": 404, "bodies": []}))
    backup_server, backup = serve(type("Backup", (FakeModel,), {"status": 200, "bodies": []}))
    configure(primary, fallback=backup)
    got = reading.read_model(page_png(), model="qwen/qwen3.6-27b")
    ok = check("404 — модели на сервере нет, страница уходит на запасной",
               got.get("fallback") is True and got.get("text"), str(got)[:100])
    ok &= check("после отказа HTTP основной адрес не на паузе", reading._primary_paused_until == 0.0)
    primary_server.RequestHandlerClass.status = 400
    got = reading.read_model(page_png(), model="qwen/qwen3.6-27b")
    ok &= check("400 — запрос плохой, запасной не зовётся", got.get("error") == "HTTP 400" and not got.get("text"),
                str(got))
    primary_server.shutdown()
    backup_server.shutdown()
    return ok


def test_no_fallback_as_before():
    configure(closed_port_url(), fallback="")
    got = reading.read_model(page_png(), model="qwen/qwen3.6-27b")
    ok = check("запасного нет — ошибка основного адреса, как раньше",
               got.get("text") == "" and got.get("error") and "запасной" not in got["error"], str(got))
    saved = os.environ.pop("OPENROUTER_API_KEY", None)
    try:
        configure(OPENROUTER, key_env="OPENROUTER_API_KEY")
        got = reading.read_model(page_png(), model="qwen/qwen3.6-27b")
        ok &= check("стенд на OpenRouter без ключа — прежний отказ без вызова",
                    got == {"text": "", "error": "нет OPENROUTER_API_KEY"}, str(got))
    finally:
        if saved is not None:
            os.environ["OPENROUTER_API_KEY"] = saved
    return ok


def test_worker_route():
    stand = load_settings(PIPELINE_MODEL_URL=None, PIPELINE_MODEL_FALLBACK_URL=None,
                          OPENROUTER_API_KEY="ключ-для-проверки", PIPELINE_READING_MODE="model")
    ok = check("стенд разработки: OpenRouter основным, без проверки и ожидания",
               stand.model_route() == ("main", None) and stand.MODEL_READY and not stand.FALLBACK_READY)

    server, url = serve(FakeModel)
    up = load_settings(PIPELINE_MODEL_URL=url, PIPELINE_MODEL_FALLBACK_URL=OPENROUTER, OPENROUTER_API_KEY=None)
    ok &= check("своя модель отвечает на /v1/models — основной адрес", up.model_route(wait_s=0) == ("main", None))
    server.shutdown()

    server, url = serve(KeyedModel)
    keyed = load_settings(PIPELINE_MODEL_URL=url, PIPELINE_MODEL_KEY_ENV="LLM_API_KEY",
                          PIPELINE_MODEL_FALLBACK_URL=None)
    saved = os.environ.get("LLM_API_KEY")
    os.environ["LLM_API_KEY"] = "server-secret-for-test"
    try:
        ok &= check("сервер закрыт ключом — проверка идёт с ключом и проходит",
                    keyed.model_route(wait_s=0) == ("main", None))
    finally:
        if saved is None:
            os.environ.pop("LLM_API_KEY", None)
        else:
            os.environ["LLM_API_KEY"] = saved
    ok &= check("без ключа тот же сервер не готов", keyed.model_route(wait_s=0)[0] is None)
    server.shutdown()

    dead = closed_port_url()
    waits = []
    down = load_settings(PIPELINE_MODEL_URL=dead, PIPELINE_MODEL_FALLBACK_URL=OPENROUTER, OPENROUTER_API_KEY=None)
    route, why = down.model_route(wait_s=0.3, progress=lambda why, left: waits.append(why),
                                  sleep=lambda s: time.sleep(0.1))
    ok &= check("модель поднимается (соединение отвергнуто) — разбор ждёт", len(waits) >= 1, f"{len(waits)} проверок")
    ok &= check("не дождались, запасного нет — чтение без модели, причина названа",
                route is None and "не отвечает" in why, f"{route} {why}")

    backup = load_settings(PIPELINE_MODEL_URL=dead, PIPELINE_MODEL_FALLBACK_URL=OPENROUTER,
                           OPENROUTER_API_KEY="ключ-для-проверки")
    ok &= check("с ключом OpenRouter — запасной адрес", backup.model_route(wait_s=0)[0] == "fallback")
    ok &= check("режим «модель» не понижается, пока есть запасной", backup.reading_mode("model") == "model")

    waits = []
    gone = load_settings(PIPELINE_MODEL_URL="http://llm-missing.invalid:8000/v1/chat/completions",
                         OPENROUTER_API_KEY=None)
    route, why = gone.model_route(wait_s=60, progress=lambda why, left: waits.append(why), sleep=lambda s: None)
    ok &= check("контейнера модели нет (имя не разрешается) — не ждать", route is None and not waits, why)
    return ok


def main():
    ok = True
    for title, fn in (("Размышление выключено у каждого адреса", test_thinking_off_per_address),
                      ("Вид сервера, лишние поля, ожидание", test_server_kinds),
                      ("Своя модель отвечает", test_primary_answers),
                      ("Своя модель не поднялась", test_fallback_on_dead_primary),
                      ("Переспрос обрезанного ответа — запасным адресом", test_retry_via_fallback),
                      ("OpenRouter запасным только с ключом", test_fallback_needs_key_for_openrouter),
                      ("Ответы HTTP", test_http_errors),
                      ("Без запасного — как было", test_no_fallback_as_before),
                      ("Воркер: ждать, запасной или без модели", test_worker_route)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
