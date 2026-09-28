"""Долгий шаг не выполняется второй раз, когда брокер забирает доставку назад. Р-130.

  python tests/test_consumer_timeout.py

28.09 на стенде :8080 разбор Полярной 16 шёл около 40 минут. Воркер подтверждает доставку после
конца шага, а RabbitMQ 3.13 ждёт подтверждения 30 минут (`consumer_timeout`). Брокер закрыл канал
и вернул сообщение в очередь, отправка следующего шага упала с ChannelWrongStateError, и после
переподключения разбор пошёл заново. Шаг, который всегда дольше срока брокера, шёл бы по кругу.

Проверки:
- docker-compose.yml задаёт брокеру `consumer_timeout` больше, чем воркер держит доставку:
  предельный срок любого шага и пауза перед повтором по умолчаниям compose;
- повторная доставка шага, чей итог уже записан в processing, шаг заново не запускает: воркер
  ставит в очередь следующий шаг или повтор из processing и подтверждает доставку, администратор
  не получает второе уведомление. Упавший посреди шага воркер получает шаг заново, как раньше;
  первая доставка с processing не сверяется.
Без брокера и базы: канал, база и шаг подменены.
"""
import glob
import json
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

COMPOSE = open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8").read()


def service_block(text, name):
    """Блок сервиса из docker-compose.yml: от «  name:» до следующего сервиса."""
    found = re.search(rf"^  {name}:\n(.*?)(?=^  \S|^\S|\Z)", text, re.M | re.S)
    return found.group(1) if found else ""


# сроки шагов — по умолчаниям воркера в compose, до импорта настроек воркера
WORKER_DEFAULTS = dict(re.findall(r"^\s+(TIMEOUT_\w+|STALL_TIMEOUT_S|RETRY_DELAY_S|MAX_RETRIES):"
                                  r"\s*\$\{\1:-([^}]*)\}\s*$", service_block(COMPOSE, "worker"), re.M))
os.environ.update(WORKER_DEFAULTS)

try:
    import pika  # noqa: E402
except ImportError:
    # pika стоит в образе воркера; здесь хватает исключений и свойств сообщения
    pika = types.ModuleType("pika")
    pika.exceptions = types.ModuleType("pika.exceptions")
    pika.exceptions.AMQPError = type("AMQPError", (Exception,), {})
    pika.exceptions.AMQPChannelError = type("AMQPChannelError", (pika.exceptions.AMQPError,), {})
    pika.exceptions.ChannelWrongStateError = type("ChannelWrongStateError", (pika.exceptions.AMQPChannelError,), {})
    pika.BasicProperties = lambda **kwargs: types.SimpleNamespace(**kwargs)
    sys.modules["pika"], sys.modules["pika.exceptions"] = pika, pika.exceptions

from service.worker import infra, settings  # noqa: E402
from service.worker import main as worker  # noqa: E402

PROCESS_ID = "ed5cbff5-4434-4dca-8eab-582e87fb7d8f"
REQUEST_ID = "8ec566f2-6a30-42b4-8e1e-86db565b67b4"


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def test_compose():
    ok = True
    block = service_block(COMPOSE, "rabbitmq")
    found = re.search(r'RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS:\s*"-rabbit consumer_timeout '
                      r'\$\{RABBITMQ_CONSUMER_TIMEOUT_MS:-(\d+)\}"', block)
    ok &= check("у брокера в compose задан consumer_timeout с умолчанием", found is not None)
    if not found:
        return False
    timeout_s = int(found.group(1)) / 1000
    ok &= check("умолчание — сутки", timeout_s == 86400, f"{timeout_s:.0f} с")
    ok &= check("сроки шагов взяты из compose", {"TIMEOUT_PARSE_S", "TIMEOUT_PARSE_MAX_S"} <= set(WORKER_DEFAULTS),
                str(WORKER_DEFAULTS))
    # доставку воркер держит до конца шага, а шаг снимается за предельным сроком; перед повтором
    # он ещё ждёт RETRY_DELAY_S. Брокер проверяет сроки раз в минуту, запас — на записи в базу
    hold = max(settings.STEP_TIMEOUT_MAX_S.values()) + settings.RETRY_DELAY_S
    ok &= check("срок брокера больше, чем воркер держит доставку, с запасом 10 минут", timeout_s > hold + 600,
                f"брокер {timeout_s:.0f} с, шаг до {hold:.0f} с: {settings.STEP_TIMEOUT_MAX_S}")
    ok &= check("срок брокера не меньше пяти минут — меньше RabbitMQ не советует", timeout_s >= 300)
    overlays = [path for path in glob.glob(os.path.join(ROOT, "deploy", "*.yml"))
                if "RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS" in open(path, encoding="utf-8").read()
                and "consumer_timeout" not in open(path, encoding="utf-8").read()]
    ok &= check("надстройки deploy/ не убирают срок брокера", not overlays, str(overlays))
    return ok


def test_outcome_recorded():
    ok = True
    cases = [
        ("шаг ждёт в очереди — не итог", {"state": "QUEUED", "step": "parse", "attempt": 1}, "parse", 1, False),
        ("воркер упал посреди шага — не итог", {"state": "RUNNING", "step": "parse", "attempt": 1}, "parse", 1, False),
        ("после шага ждёт следующий — итог", {"state": "QUEUED", "step": "compare", "attempt": 1}, "parse", 1, True),
        ("записан повтор — итог", {"state": "QUEUED", "step": "parse", "attempt": 2}, "parse", 1, True),
        ("идёт следующий шаг — итог", {"state": "RUNNING", "step": "compare", "attempt": 1}, "parse", 1, True),
        ("обработка закончена — итог", {"state": "DONE", "step": "protocol", "attempt": 1}, "protocol", 1, True),
        ("повторы исчерпаны — итог", {"state": "FAILED", "step": "parse", "attempt": 3}, "parse", 3, True),
        ("processing пуст — не итог", None, "parse", 1, False),
        ("processing без состояния — не итог", {}, "parse", 1, False),
        ("попытка не читается — не итог", {"state": "QUEUED", "step": "compare", "attempt": "x"}, "parse", 1, False),
    ]
    for name, processing, step, attempt, expected in cases:
        got = worker.outcome_recorded(processing, step, attempt)
        ok &= check(name, got is expected, f"{got}")
    return ok


class Channel:
    """Канал брокера: отправленное и подтверждённое. Закрытый канал падает, как BlockingChannel в pika."""

    def __init__(self):
        self.open, self.sent, self.acked = True, [], []

    def _check_open(self):
        if not self.open:
            raise pika.exceptions.ChannelWrongStateError("Channel is closed.")

    def basic_publish(self, exchange, routing_key, body, properties=None):
        self._check_open()
        self.sent.append((routing_key, json.loads(body)))

    def basic_ack(self, delivery_tag):
        self._check_open()
        self.acked.append(delivery_tag)


class Connection:
    is_open = True

    def sleep(self, seconds):
        pass


class Service:
    """Процесс в базе и шаг: processing сливается, как `infra.set_processing` в jsonb.

    Шаг возвращает заданный итог и, если задан канал, закрывает его, пока идёт: так брокер
    закрывает канал по consumer_timeout посреди долгого разбора.
    """

    def __init__(self, processing, result=(True, None, False)):
        self.processing = processing
        self.result, self.close_during = result, None
        self.runs, self.notified, self.log = [], [], []

    def db(self):
        service = self

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=()):
                row = {"object_id": "LOC-POLYARNAYA-16", "status": "PARSING",
                       "processing": json.loads(json.dumps(service.processing))}
                return types.SimpleNamespace(fetchone=lambda: row)

        return Conn()

    def set_processing(self, conn, process_id, **fields):
        self.processing = {**(self.processing or {}), **fields}

    def run_step(self, connection, step, process_id, context):
        self.runs.append(step)
        if self.close_during is not None:
            self.close_during.open = False
        return self.result

    def patch(self):
        def no_redis():
            raise ConnectionError("Redis в тесте нет")

        saved = {name: getattr(infra, name) for name in
                 ("db", "set_processing", "progress", "redis", "notify", "audit", "settle_status")}
        saved_worker = {"run_step": worker.run_step, "log": worker.log}
        infra.db, infra.set_processing, infra.redis = self.db, self.set_processing, no_redis
        infra.progress = lambda *args, **kwargs: None
        infra.notify = lambda conn, role, level, message, *args, **kwargs: self.notified.append(message)
        infra.audit = lambda *args, **kwargs: None
        infra.settle_status = lambda *args, **kwargs: None
        worker.run_step = self.run_step
        worker.log = lambda message, level="INFO", **fields: self.log.append((level, message))
        return saved, saved_worker

    @staticmethod
    def restore(saved):
        saved_infra, saved_worker = saved
        for name, value in saved_infra.items():
            setattr(infra, name, value)
        for name, value in saved_worker.items():
            setattr(worker, name, value)


def body(step, attempt):
    return json.dumps({"process_id": PROCESS_ID, "step": step, "attempt": attempt, "requested_by": "admin",
                       "requested_at": "2026-09-28T01:12:40+00:00", "request_id": REQUEST_ID}).encode()


def delivery(tag, redelivered):
    return types.SimpleNamespace(delivery_tag=tag, redelivered=redelivered)


def deliver(service, channel, step, attempt, tag=1, redelivered=False):
    """Доставка в handle, как из consume. Сбой канала worker.main ловит и переподключается — здесь то же."""
    saved = service.patch()
    try:
        worker.handle(Connection(), channel, delivery(tag, redelivered), body(step, attempt))
        return None
    except pika.exceptions.AMQPError as error:
        return error
    finally:
        Service.restore(saved)


def sent(channel):
    return [(queue, message["attempt"]) for queue, message in channel.sent]


def test_incident():
    """28.09: разбор дольше срока брокера — канал закрыт посреди шага, после переподключения доставка та же."""
    ok = True
    service = Service({"state": "QUEUED", "step": "parse", "attempt": 1})
    first = Channel()
    service.close_during = first
    error = deliver(service, first, "parse", 1)
    ok &= check("шаг закончился на закрытом канале: отправка упала, как на стенде",
                isinstance(error, pika.exceptions.ChannelWrongStateError), repr(error))
    ok &= check("итог шага записан до отправки: ждёт сравнение", service.processing.get("state") == "QUEUED"
                and service.processing.get("step") == "compare", str(service.processing))
    second = Channel()
    service.close_during = None
    error = deliver(service, second, "parse", 1, redelivered=True)
    ok &= check("повторная доставка без сбоя", error is None, repr(error))
    ok &= check("разбор выполнен один раз", service.runs == ["parse"], str(service.runs))
    ok &= check("сравнение поставлено в очередь, повторная доставка подтверждена",
                sent(second) == [("compare", 1)] and second.acked == [1], f"{sent(second)} {second.acked}")
    ok &= check("пользователь и запрос API переходят к сравнению",
                second.sent[0][1]["requested_by"] == "admin" and second.sent[0][1]["request_id"] == REQUEST_ID)
    ok &= check("в журнале — почему шаг не выполнен заново",
                any(level == "WARNING" and "заново не выполняется" in text for level, text in service.log),
                str(service.log[-1:]))
    error = deliver(service, second, "compare", 1, tag=2)
    ok &= check("дальше сравнение идёт как обычно", error is None and service.runs == ["parse", "compare"]
                and sent(second)[-1] == ("protocol", 1) and second.acked == [1, 2], f"{service.runs} {sent(second)}")
    return ok


def test_retry_and_failure():
    ok = True
    # сбой шага с закрытым каналом: повтор записан, а отправить его воркер не смог
    service = Service({"state": "QUEUED", "step": "parse", "attempt": 1},
                      result=(False, "шаг parse завершился с кодом 1", False))
    first = Channel()
    service.close_during = first
    deliver(service, first, "parse", 1)
    second = Channel()
    service.close_during = None
    deliver(service, second, "parse", 1, redelivered=True)
    ok &= check("сбой: упавшая попытка не повторяется второй раз, в очередь идёт повтор 2",
                service.runs == ["parse"] and sent(second) == [("parse", 2)] and second.acked == [1],
                f"{service.runs} {sent(second)}")
    # последняя попытка: процесс остановлен, администратор уведомлён, подтвердить не удалось
    last = settings.MAX_RETRIES + 1
    service = Service({"state": "QUEUED", "step": "parse", "attempt": last}, result=(False, "таймаут шага parse", True))
    first = Channel()
    service.close_during = first
    deliver(service, first, "parse", last)
    second = Channel()
    service.close_during = None
    deliver(service, second, "parse", last, redelivered=True)
    ok &= check("повторы исчерпаны: шаг не выполняется заново, в очередь ничего, доставка подтверждена",
                service.runs == ["parse"] and not second.sent and second.acked == [1], f"{service.runs} {sent(second)}")
    ok &= check("администратор уведомлён один раз", len(service.notified) == 1, str(len(service.notified)))
    ok &= check("процесс остался FAILED", service.processing.get("state") == "FAILED", str(service.processing))
    # последний шаг закончен, подтверждение потерялось
    service = Service({"state": "DONE", "step": "protocol", "attempt": 1})
    channel = Channel()
    deliver(service, channel, "protocol", 1, redelivered=True)
    ok &= check("протокол уже сформирован: не пересобирается, доставка подтверждена",
                not service.runs and not channel.sent and channel.acked == [1], f"{service.runs} {sent(channel)}")
    return ok


def test_unchanged():
    ok = True
    # воркер упал посреди шага: брокер отдаёт доставку, шаг выполняется заново, как до Р-130
    service = Service({"state": "RUNNING", "step": "parse", "attempt": 1})
    channel = Channel()
    deliver(service, channel, "parse", 1, redelivered=True)
    ok &= check("воркер упал посреди шага: шаг выполняется заново", service.runs == ["parse"]
                and sent(channel) == [("compare", 1)] and channel.acked == [1], f"{service.runs} {sent(channel)}")
    service = Service(None)
    channel = Channel()
    deliver(service, channel, "parse", 1, redelivered=True)
    ok &= check("processing пуст: повторная доставка выполняется", service.runs == ["parse"], str(service.runs))
    # первая доставка с processing не сверяется
    service = Service({"state": "QUEUED", "step": "compare", "attempt": 1})
    channel = Channel()
    deliver(service, channel, "parse", 1)
    ok &= check("первая доставка выполняется, что бы ни было в processing", service.runs == ["parse"]
                and channel.acked == [1], str(service.runs))
    return ok


def main():
    ok = True
    for name, test in (("срок брокера в compose", test_compose),
                       ("итог доставки в processing", test_outcome_recorded),
                       ("случай 28.09: канал закрыт посреди разбора", test_incident),
                       ("повтор, исчерпанные повторы, готовый протокол", test_retry_and_failure),
                       ("что осталось как было", test_unchanged)):
        print(f"\n{name}")
        ok &= test()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
