"""Признак «модель во внешнем сервисе» для предупреждения на экране загрузки.

  python tests/test_worker_external_model.py

Демо-стенды читают моделью через OpenRouter, поставка на H100 — своей моделью в контейнере llm.
Экран загрузки должен предупреждать, что новый комплект уйдёт на чтение во внешний сервис,
только там, где это правда. Воркер решает это по адресам модели (`settings.EXTERNAL_MODEL`)
и пишет признак в Redis, API отдаёт его в /api/v1/health.
"""
import importlib
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import pika  # noqa: E402,F401
except ImportError:
    # pika стоит в образе воркера; здесь хватает исключений и свойств сообщения
    pika = types.ModuleType("pika")
    pika.exceptions = types.ModuleType("pika.exceptions")
    pika.exceptions.AMQPError = type("AMQPError", (Exception,), {})
    pika.BasicProperties = lambda **kwargs: types.SimpleNamespace(**kwargs)
    pika.BlockingConnection = None
    sys.modules["pika"], sys.modules["pika.exceptions"] = pika, pika.exceptions

from service.worker import settings  # noqa: E402

KEYS = ("PIPELINE_MODEL_URL", "PIPELINE_MODEL_KEY_ENV", "PIPELINE_MODEL_FALLBACK_URL",
        "PIPELINE_MODEL_FALLBACK_KEY_ENV", "OPENROUTER_API_KEY", "LLM_API_KEY", "PIPELINE_MODEL_EXTERNAL")
OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def external_with(**env):
    """EXTERNAL_MODEL настроек, прочитанных заново при таком окружении."""
    saved = {k: os.environ.get(k) for k in KEYS}
    try:
        for k in KEYS:
            os.environ.pop(k, None)
        os.environ.update({k: v for k, v in env.items() if v is not None})
        return importlib.reload(settings).EXTERNAL_MODEL
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        importlib.reload(settings)


def publishing():
    """Признак в Redis: ключ воркера со сроком жизни, запись не чаще раза в полминуты, сбой не роняет."""
    from service.worker import infra, main as worker
    calls, logged = [], []

    class Fake:
        fail = False

        def set(self, key, value, ex=None):
            if Fake.fail:
                raise ConnectionError("redis недоступен")
            calls.append((key, value, ex))

    saved_redis, saved_log = infra.redis, worker.log
    infra.redis, worker.log = (lambda: Fake()), (lambda message, **kw: logged.append(message))
    try:
        worker._reading.update(at=float("-inf"), warned=False)
        ok = check("первая запись: ключ воркера и срок жизни",
                   worker.publish_reading(force=True) and len(calls) == 1
                   and calls[0][0].startswith("worker:reading:") and calls[0][2] == worker.READING_TTL_S
                   and calls[0][1] in ("0", "1"), str(calls))
        worker.publish_reading()
        ok &= check("сразу следом не пишется", len(calls) == 1)
        worker._reading["at"] -= worker.READING_REFRESH_S + 1
        worker.publish_reading()
        ok &= check("через полминуты пишется снова, до истечения срока", len(calls) == 2
                    and worker.READING_REFRESH_S * 2 < worker.READING_TTL_S)
        Fake.fail = True
        attempts = []
        Fake.set_orig, Fake.set = Fake.set, lambda self, *a, **k: (attempts.append(1), Fake.set_orig(self, *a, **k))
        worker._reading["at"] = float("-inf")
        first = worker.publish_reading()
        worker.publish_reading()
        ok &= check("Redis недоступен: не падает и сразу следом не повторяет", first is False and len(attempts) == 1,
                    f"попыток {len(attempts)}")
        worker._reading["at"] -= worker.READING_REFRESH_S + 1
        worker.publish_reading()
        ok &= check("через полминуты пробует снова, в журнал один раз", len(attempts) == 2 and len(logged) == 1, str(logged))
        return ok
    finally:
        infra.redis, worker.log = saved_redis, saved_log


def main():
    is_external = settings.is_external
    ok = check("OpenRouter — внешний", is_external(OPENROUTER))
    ok &= check("сервис compose без точки — свой", not is_external("http://llm:8000/v1/chat/completions"))
    ok &= check("model-host (своя модель на Linux) — свой", not is_external("http://model-host:8000/v1/chat/completions"))
    ok &= check("host.docker.internal — свой", not is_external("http://host.docker.internal:11434/v1/chat/completions"))
    ok &= check("localhost и петля — свои", not is_external("http://localhost:8000/v1") and not is_external("http://127.0.0.1:8000/v1"))
    ok &= check("частная сеть — своя", not is_external("http://10.0.0.5:8000/v1") and not is_external("http://192.168.5.2:8000/v1"))
    ok &= check("публичный адрес чужого сервера — внешний", is_external("http://8.8.8.8:8000/v1/chat/completions"))
    ok &= check("пустой адрес — не внешний", not is_external(""))
    ok &= check("публичный IPv6 — внешний", is_external("http://[2606:4700:4700::1111]:8000/v1/chat/completions"))
    ok &= check("IPv4 числом без точек — внешний", is_external("http://134744072:8000/v1") and is_external("http://0x8080808/v1"))
    ok &= check("петля и частная сеть IPv6 — свои", not is_external("http://[::1]:8000/v1") and not is_external("http://[fd00::5]/v1"))
    ok &= check("общий провайдерский 100.64/10 (Tailscale) — свой", not is_external("http://100.64.1.2:8000/v1"))
    ok &= check("зоны .internal, .local и кластер k8s — свои",
                not is_external("http://llm.internal/v1") and not is_external("http://gpu.local/v1")
                and not is_external("http://vllm.default.svc.cluster.local/v1"))

    ok &= check("стенд разработки с ключом OpenRouter — предупреждать",
                external_with(OPENROUTER_API_KEY="k"))
    ok &= check("стенд разработки без ключа — модели нет, не предупреждать",
                not external_with())
    ok &= check("поставка: своя модель, запасной OpenRouter без ключа — не предупреждать",
                not external_with(PIPELINE_MODEL_URL="http://llm:8000/v1/chat/completions",
                                  PIPELINE_MODEL_KEY_ENV="LLM_API_KEY",
                                  PIPELINE_MODEL_FALLBACK_URL=OPENROUTER))
    ok &= check("поставка с ключом запасного OpenRouter — предупреждать",
                external_with(PIPELINE_MODEL_URL="http://llm:8000/v1/chat/completions",
                              PIPELINE_MODEL_KEY_ENV="LLM_API_KEY",
                              PIPELINE_MODEL_FALLBACK_URL=OPENROUTER, OPENROUTER_API_KEY="k"))
    ok &= check("свой сервер модели на чужой машине — предупреждать",
                external_with(PIPELINE_MODEL_URL="https://gpu.example.com/v1/chat/completions",
                              PIPELINE_MODEL_KEY_ENV="LLM_API_KEY"))
    ok &= check("PIPELINE_MODEL_EXTERNAL=1 сильнее правила адресов",
                external_with(PIPELINE_MODEL_URL="http://llm:8000/v1/chat/completions",
                              PIPELINE_MODEL_KEY_ENV="LLM_API_KEY", PIPELINE_MODEL_EXTERNAL="1"))
    ok &= check("PIPELINE_MODEL_EXTERNAL=0 сильнее правила адресов",
                not external_with(OPENROUTER_API_KEY="k", PIPELINE_MODEL_EXTERNAL="0"))
    ok &= publishing()
    print("итог:", "ок" if ok else "есть сбои")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
