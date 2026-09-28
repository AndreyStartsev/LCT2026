"""Обрыв соединения с брокером посреди шага: процесс шага не остаётся без хозяина, итог записан,
следующий шаг встаёт в очередь один раз. Р-131.

  python tests/test_worker_connection_loss.py

До Р-131 ошибка соединения из `process_data_events` вылетала из run_step в main, и процесс шага
оставался без хозяина: его итог никто не записывал. Брокер, перезапущенный с сохранёнными
очередями, отдавал доставку заново, и воркер запускал второй такой же шаг рядом с первым.
Пересозданный брокер доставку терял, и процесс навсегда оставался в RUNNING — API такой
процесс не перезапускает.

Проверки:
- run_step с настоящим процессом шага: после обрыва соединение больше не обслуживается, шаг
  доходит до конца, молчащий и бесконечный шаги сторож снимает, как раньше;
- воркер целиком (main) на брокере в памяти. Брокер перезапущен с очередями, пересоздан пустым,
  остановлен так, что его имя не разрешается, закрыл канал по consumer_timeout, упал между отправкой
  повтора и подтверждением доставки. Каждый шаг выполняется один раз, процесс шага идёт один,
  следующий шаг и повтор встают в очередь один раз, повторная доставка только подтверждается,
  переподключение воркер не роняет;
- после переподключения шаг ставится, только если processing всё ещё ждёт его, а брокер его
  не принял.
Без брокера и базы: брокер, база и Redis подменены, шаги — короткие процессы Python.
"""
import copy
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import pika  # noqa: E402
except ImportError:
    # pika стоит в образе воркера; здесь хватает исключений и свойств сообщения
    pika = types.ModuleType("pika")
    pika.exceptions = types.ModuleType("pika.exceptions")
    errors = pika.exceptions
    errors.AMQPError = type("AMQPError", (Exception,), {})
    errors.AMQPConnectionError = type("AMQPConnectionError", (errors.AMQPError,), {})
    errors.StreamLostError = type("StreamLostError", (errors.AMQPConnectionError,), {})
    errors.ConnectionWrongStateError = type("ConnectionWrongStateError", (errors.AMQPConnectionError,), {})
    errors.AMQPChannelError = type("AMQPChannelError", (errors.AMQPError,), {})
    errors.ChannelWrongStateError = type("ChannelWrongStateError", (errors.AMQPChannelError,), {})
    pika.BasicProperties = lambda **kwargs: types.SimpleNamespace(**kwargs)
    pika.BlockingConnection = None
    sys.modules["pika"], sys.modules["pika.exceptions"] = pika, pika.exceptions

from service.worker import infra, settings  # noqa: E402
from service.worker import main as worker  # noqa: E402

PROCESS_ID = "ed5cbff5-4434-4dca-8eab-582e87fb7d8f"
REQUEST_ID = "8ec566f2-6a30-42b4-8e1e-86db565b67b4"
REAL_POPEN = subprocess.Popen
LOST = "Stream connection lost: ConnectionResetError(104, 'Connection reset by peer')"


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


class Steps:
    """Процессы шагов: короткие процессы Python вместо `service.worker.steps`.

    plan — шаг → исходы запусков по порядку: (строк хода по 0,1 с, код выхода). Считает запуски
    и сколько процессов шагов шло одновременно; оставшиеся после проверки — снимает.
    """

    def __init__(self, plan=None):
        self.plan = {step: list(outcomes) for step, outcomes in (plan or {}).items()}
        self.children, self.runs, self.overlap = [], [], 0

    def popen(self, args, **kwargs):
        step = args[3]
        if len(self.runs) >= 20:
            worker._stop = True     # предохранитель: шаги по кругу воркер запускать не должен
        ticks, code = self.plan[step].pop(0) if self.plan.get(step) else (3, 0)
        return self.spawn(step, "import sys, time\n"
                                f"for i in range({ticks}):\n    print('ход', i, flush=True); time.sleep(0.1)\n"
                                f"sys.exit({code})", **kwargs)

    def spawn(self, step, script, **kwargs):
        alive = sum(child.poll() is None for child in self.children)
        self.overlap = max(self.overlap, alive + 1)
        child = REAL_POPEN([sys.executable, "-c", script], **{**kwargs, "cwd": None})
        self.children.append(child)
        self.runs.append(step)
        return child

    def cleanup(self):
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.wait()


# --- run_step: шаг не бросается, сторож прежний --------------------------------------------------------


class DroppingConnection:
    """Соединение, которое обрывается на первом же обслуживании: брокер перезапущен."""

    def __init__(self):
        self.calls = 0

    def process_data_events(self, time_limit=0):
        self.calls += 1
        raise pika.exceptions.StreamLostError(LOST)


def test_run_step():
    scripts = {
        "ход, затем конец": "import time\nfor i in range(8):\n    print(i, flush=True); time.sleep(0.3)",
        "молчит": "import time\nprint('старт', flush=True); time.sleep(30)",
        "ход без конца": "import time\nwhile True:\n    print('.', flush=True); time.sleep(0.3)",
        "падает": "import sys\nprint('старт', flush=True); sys.exit(3)",
    }
    saved = (dict(settings.STEP_TIMEOUT_S), dict(settings.STEP_TIMEOUT_MAX_S), settings.STALL_TIMEOUT_S,
             worker.log, infra.redis)
    lines, got, calls, took, children = [], {}, {}, {}, {}

    def no_redis():
        raise ConnectionError("Redis в тесте нет")

    try:
        settings.STEP_TIMEOUT_S["parse"], settings.STEP_TIMEOUT_MAX_S["parse"] = 1, 4
        settings.STALL_TIMEOUT_S = 1.5
        worker.log = lambda message, level="INFO", **fields: lines.append((level, message))
        infra.redis = no_redis
        for name, script in scripts.items():
            steps = Steps()
            worker.subprocess.Popen = lambda args, _script=script, _steps=steps, **kwargs: _steps.spawn(
                "parse", _script, **kwargs)
            connection = DroppingConnection()
            started = time.monotonic()
            try:
                got[name] = worker.run_step(connection, "parse", PROCESS_ID, {"user_id": None, "request_id": None})
            except pika.exceptions.AMQPError as error:
                got[name] = error
            took[name], calls[name] = time.monotonic() - started, connection.calls
            children[name] = steps.children[0].poll() is not None
            steps.cleanup()
    finally:
        worker.subprocess.Popen = REAL_POPEN
        settings.STEP_TIMEOUT_S.update(saved[0])
        settings.STEP_TIMEOUT_MAX_S.update(saved[1])
        settings.STALL_TIMEOUT_S, worker.log, infra.redis = saved[2:]
    ok = True
    ok &= check("ошибка соединения не вылетает из run_step", not any(isinstance(v, Exception) for v in got.values()),
                str({k: v for k, v in got.items() if isinstance(v, Exception)}))
    ok &= check("run_step возвращается, когда процесса шага уже нет", all(children.values()), str(children))
    ok &= check("после обрыва соединение не обслуживается", set(calls.values()) == {1}, str(calls))
    ok &= check("шаг с ходом дошёл до конца после обрыва", got["ход, затем конец"] == (True, None, False)
                and took["ход, затем конец"] >= 2.4, f"{got['ход, затем конец']} за {took['ход, затем конец']:.1f} с")
    ok &= check("молчащий шаг сторож снял, как раньше", isinstance(got["молчит"], tuple) and got["молчит"][2]
                and "нет хода" in got["молчит"][1], str(got["молчит"]))
    ok &= check("бесконечный шаг снят за предельным сроком", isinstance(got["ход без конца"], tuple)
                and got["ход без конца"][2] and "предельный" in got["ход без конца"][1], str(got["ход без конца"]))
    ok &= check("сбой шага — не таймаут", got["падает"] == (False, "шаг parse завершился с кодом 3", False),
                str(got["падает"]))
    warned = [text for level, text in lines if level == "WARNING" and "оборвалось посреди шага parse" in text]
    ok &= check("об обрыве — одна строка в журнале на шаг", len(warned) == len(scripts), str(warned[:1]))
    return ok


# --- воркер целиком на брокере в памяти -----------------------------------------------------------------


class Broker:
    """RabbitMQ в памяти — столько, сколько видит воркер: очереди, доставки без подтверждения,
    подтверждения отправки, перезапуск с очередями, пересоздание пустым, закрытие канала.

    Вернувшаяся доставка встаёт в голову очереди с redelivered, как в RabbitMQ. Отправка
    в необъявленную очередь пропадает молча — так обменник по умолчанию поступает с сообщением
    без mandatory.
    """

    def __init__(self, messages):
        self.queues = {"parse": [], "compare": [], "protocol": []}
        for queue, attempt in messages:
            self.queues[queue].append((body(queue, attempt), False))
        self.unacked = {}           # тег → (канал, очередь, тело)
        self.life = 0               # перезапуск или пересоздание — новая жизнь, прежние соединения мертвы
        self.refuse = 0             # сколько подключений ещё отказать: брокер поднимается
        self.unresolved = False     # контейнер брокера остановлен: его имя в сети не разрешается
        self.tag = self.connects = self.idle = 0
        self.published, self.lost, self.events = [], [], []
        self.on_io = self.fail_after = None

    def restart(self, keep, unresolved=False):
        """Перезапуск с сохранёнными очередями (keep) или пересоздание с пустыми.

        unresolved — пока брокер поднимается, его имя не разрешается: контейнер остановлен или вне
        сети. pika тогда бросает при подключении socket.gaierror, а не AMQPError.
        """
        self.life += 1
        self.unresolved = unresolved
        if keep:
            for tag in sorted(self.unacked, reverse=True):
                _channel, queue, text = self.unacked[tag]
                self.queues[queue].insert(0, (text, True))
        else:
            self.queues = {}
        self.unacked, self.refuse = {}, 2
        self.events.append(("restart",) if keep else ("recreate",))

    def close_channel(self, channel):
        """consumer_timeout: канал закрыт, его доставки — в голову очереди с redelivered."""
        channel.closed = True
        self.requeue(channel)
        self.events.append(("channel closed",))

    def requeue(self, channel):
        for tag in sorted((t for t, (ch, _q, _b) in self.unacked.items() if ch is channel), reverse=True):
            _channel, queue, text = self.unacked.pop(tag)
            self.queues[queue].insert(0, (text, True))

    def connect(self, _params=None):
        self.connects += 1
        if self.connects > 50:
            worker._stop = True     # предохранитель: без конца переподключаться воркер не должен
        if self.refuse > 0:
            self.refuse -= 1
            if self.unresolved:
                raise socket.gaierror(-2, "Name or service not known")
            raise pika.exceptions.AMQPConnectionError("[Errno 111] Connection refused")
        self.events.append(("connect",))
        return Connection(self)

    def settled(self):
        return not any(self.queues.values()) and not self.unacked

    def trigger(self, after, action):
        """Сделать action на обслуживании соединения номер `after` + 1 — посреди первого шага."""
        state = {"calls": 0}

        def on_io(connection):
            state["calls"] += 1
            if state["calls"] == after + 1:
                self.on_io = None
                action(connection)
        self.on_io = on_io


class Connection:
    """Соединение как BlockingConnection в pika 1.4: обрыв виден на первом вызове после него — этот
    вызов бросает ошибку соединения, и соединение закрыто. На закрытом вызовы с ожиданием
    (`process_data_events`, `sleep`) падают ValueError: таймер ввода-вывода закрыт вместе с ним."""

    def __init__(self, broker):
        self.broker, self.life, self.closed, self.channels = broker, broker.life, False, []

    @property
    def is_open(self):
        return not self.closed

    def check(self):
        if self.closed:
            raise pika.exceptions.ConnectionWrongStateError()
        if self.life != self.broker.life:
            self.closed = True
            raise pika.exceptions.StreamLostError(LOST)

    def wait(self):
        if self.closed:
            raise ValueError("Timeout closed before call")
        self.check()

    def channel(self):
        self.check()
        self.channels.append(Channel(self))
        return self.channels[-1]

    def process_data_events(self, time_limit=0):
        self.wait()
        if self.broker.on_io:
            self.broker.on_io(self)
        time.sleep(0.02)
        self.check()

    def sleep(self, seconds):
        self.wait()
        self.broker.idle += 1
        if self.broker.settled() or self.broker.idle > 200:
            worker._stop = True

    def close(self):
        self.check()
        self.closed = True
        for channel in self.channels:
            self.broker.requeue(channel)


class Channel:
    def __init__(self, connection):
        self.connection, self.broker, self.closed = connection, connection.broker, False

    def check(self):
        if self.closed or self.connection.closed:
            raise pika.exceptions.ChannelWrongStateError("Channel is closed.")
        self.connection.check()

    def queue_declare(self, queue, durable=False):
        self.check()
        self.broker.queues.setdefault(queue, [])

    def basic_qos(self, prefetch_count=0):
        self.check()

    def confirm_delivery(self):
        self.check()
        self.broker.events.append(("confirm",))

    def basic_publish(self, exchange, routing_key, body, properties=None, mandatory=False):
        self.check()
        key = (routing_key, json.loads(body)["attempt"])
        if routing_key in self.broker.queues:
            self.broker.queues[routing_key].append((body, False))
            self.broker.published.append(key)
        else:
            self.broker.lost.append(key)
        self.broker.events.append(("publish",) + key)
        if self.broker.fail_after == key:
            # брокер принял сообщение и подтвердил отправку, а до подтверждения доставки не дожил
            self.broker.fail_after = None
            self.broker.restart(keep=True)

    def basic_get(self, queue, auto_ack=False):
        self.check()
        waiting = self.broker.queues.get(queue) or []
        if not waiting:
            return None, None, None
        text, redelivered = waiting.pop(0)
        self.broker.tag += 1
        self.broker.unacked[self.broker.tag] = (self, queue, text)
        self.broker.events.append(("get", queue, json.loads(text)["attempt"], redelivered))
        return types.SimpleNamespace(delivery_tag=self.broker.tag, redelivered=redelivered), None, text

    def basic_ack(self, delivery_tag):
        self.check()
        owner, queue, text = self.broker.unacked.pop(delivery_tag)
        assert owner is self, "доставка подтверждается не на своём канале"
        self.broker.events.append(("ack", queue, json.loads(text)["attempt"]))


def body(step, attempt):
    return json.dumps({"process_id": PROCESS_ID, "step": step, "attempt": attempt, "requested_by": "admin",
                       "requested_at": "2026-09-28T01:12:40+00:00", "request_id": REQUEST_ID}).encode()


class Service:
    """База и Redis: processing сливается, как `infra.set_processing` в jsonb; уведомления — списком."""

    def __init__(self, processing):
        self.processing, self.notified, self.log, self.crashed = processing, [], [], None

    def db(self):
        service = self

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=()):
                row = {"object_id": "LOC-POLYARNAYA-16", "status": "PARSING",
                       "processing": copy.deepcopy(service.processing)}
                return types.SimpleNamespace(fetchone=lambda: row)

        return Conn()

    def set_processing(self, conn, process_id, **fields):
        self.processing = {**(self.processing or {}), **fields}


def run_worker(broker, service, steps):
    """main() до тишины: очереди пусты, доставок без подтверждения нет."""
    def no_redis():
        raise ConnectionError("Redis в тесте нет")

    names = ("db", "set_processing", "progress", "redis", "notify", "audit", "settle_status", "amqp_params")
    saved_infra = {name: getattr(infra, name) for name in names}
    saved = (worker.log, worker.time, pika.BlockingConnection, settings.WORK_DIR, signal.getsignal(signal.SIGTERM))
    infra.db, infra.set_processing, infra.redis = service.db, service.set_processing, no_redis
    infra.progress = infra.audit = infra.settle_status = lambda *args, **kwargs: None
    infra.notify = lambda conn, role, level, message, *args, **kwargs: service.notified.append(message)
    infra.amqp_params = lambda: None
    worker.log = lambda message, level="INFO", **fields: service.log.append((level, message))
    # паузы main без ожидания: переподключение через 3 с и повтор через RETRY_DELAY_S
    worker.time = types.SimpleNamespace(monotonic=time.monotonic, time=time.time, sleep=lambda seconds: None)
    worker.subprocess.Popen = steps.popen
    pika.BlockingConnection = broker.connect
    settings.WORK_DIR = tempfile.mkdtemp(prefix="worker-r131-")
    worker._stop, worker._pending = False, None
    try:
        worker.main()
    except Exception as error:  # noqa: BLE001 — воркер упал: в стенде контейнер так и остался бы лежать
        service.crashed = error
    finally:
        worker.subprocess.Popen = REAL_POPEN
        for name, value in saved_infra.items():
            setattr(infra, name, value)
        shutil.rmtree(settings.WORK_DIR, ignore_errors=True)
        worker.log, worker.time, pika.BlockingConnection, settings.WORK_DIR = saved[:4]
        signal.signal(signal.SIGTERM, saved[4])
        worker._stop = False
        steps.cleanup()


def queued(step, attempt):
    """processing после запуска из API: шаг в очереди, отметки брокера нет."""
    return {"state": "QUEUED", "step": step, "attempt": attempt, "queued_at": "2026-09-28T01:12:40+00:00"}


def after_reconnect(broker):
    """События брокера после последнего подключения до первой выборки из очереди."""
    last = max(i for i, event in enumerate(broker.events) if event == ("connect",))
    tail = broker.events[last + 1:]
    first_get = next((i for i, event in enumerate(tail) if event[0] == "get"), len(tail))
    return tail[:first_get]


def warnings(service, text):
    """Строки WARNING журнала воркера с этим текстом."""
    return [message for level, message in service.log if level == "WARNING" and text in message]


def after_redelivery(broker, queue, attempt):
    """Событие брокера сразу после повторной доставки; None — повторная доставка не одна."""
    at = [i for i, event in enumerate(broker.events) if event == ("get", queue, attempt, True)]
    return broker.events[at[0] + 1] if len(at) == 1 and at[0] + 1 < len(broker.events) else None


def test_broker_restarted():
    """Брокер перезапущен с очередями посреди разбора: доставка вернётся с redelivered."""
    ok = True
    broker, service = Broker([("parse", 1)]), Service(queued("parse", 1))
    steps = Steps({"parse": [(8, 0)]})
    broker.trigger(2, lambda connection: broker.restart(keep=True))
    run_worker(broker, service, steps)
    ok &= check("каждый шаг выполнен один раз", steps.runs == ["parse", "compare", "protocol"], str(steps.runs))
    ok &= check("процесс шага шёл один — второго рядом с первым нет", steps.overlap == 1, str(steps.overlap))
    ok &= check("после переподключения сравнение поставлено до первой выборки, с подтверждениями",
                after_reconnect(broker)[:2] == [("confirm",), ("publish", "compare", 1)]
                if any(e == ("restart",) for e in broker.events) else False, str(broker.events))
    ok &= check("сравнение и протокол — в очереди по одному разу",
                broker.published == [("compare", 1), ("protocol", 1)], str(broker.published))
    ok &= check("повторная доставка разбора сразу подтверждена: ни шага, ни отправки",
                after_redelivery(broker, "parse", 1) == ("ack", "parse", 1), str(after_redelivery(broker, "parse", 1)))
    ok &= check("обработка дошла до протокола", service.processing.get("state") == "DONE", str(service.processing))
    ok &= check("очереди пусты, доставок без подтверждения нет", broker.settled(), str(broker.queues))
    lines = [warnings(service, text) for text in ("оборвалось посреди шага parse", "шаг compare, попытка 1 не поставлен",
                                                  "после переподключения в очередь поставлен шаг compare, попытка 1")]
    ok &= check("в журнале — обрыв посреди разбора, неотправленное сравнение и его отправка после переподключения",
                [len(found) for found in lines] == [1, 1, 1], str([found[:1] for found in lines]))
    return ok


def test_broker_recreated():
    """Брокер пересоздан пустым посреди разбора: доставка потеряна, очередей нет."""
    ok = True
    broker, service = Broker([("parse", 1)]), Service(queued("parse", 1))
    steps = Steps({"parse": [(8, 0)]})
    broker.trigger(2, lambda connection: broker.restart(keep=False))
    run_worker(broker, service, steps)
    ok &= check("каждый шаг выполнен один раз", steps.runs == ["parse", "compare", "protocol"], str(steps.runs))
    ok &= check("процесс не остался в RUNNING: дошёл до протокола", service.processing.get("state") == "DONE",
                str(service.processing))
    ok &= check("сравнение ушло в объявленную очередь, ничего не пропало",
                broker.published == [("compare", 1), ("protocol", 1)] and not broker.lost,
                f"{broker.published} потеряно {broker.lost}")
    ok &= check("повторной доставки нет — её некому было сохранить",
                not any(e[0] == "get" and e[3] for e in broker.events))
    return ok


def test_broker_stopped():
    """Контейнер брокера остановлен посреди разбора: пока он не поднят, имя брокера не разрешается."""
    ok = True
    broker, service = Broker([("parse", 1)]), Service(queued("parse", 1))
    steps = Steps({"parse": [(8, 0)]})
    broker.trigger(2, lambda connection: broker.restart(keep=True, unresolved=True))
    run_worker(broker, service, steps)
    ok &= check("воркер не упал, пока имя брокера не разрешалось (socket.gaierror)", service.crashed is None,
                repr(service.crashed))
    ok &= check("каждый шаг выполнен один раз, сравнение в очереди один раз",
                steps.runs == ["parse", "compare", "protocol"]
                and broker.published == [("compare", 1), ("protocol", 1)], f"{steps.runs} {broker.published}")
    ok &= check("обработка дошла до протокола", service.processing.get("state") == "DONE", str(service.processing))
    return ok


def test_consumer_timeout():
    """Р-130: брокер закрыл канал посреди разбора, соединение живо. Оба пути сходятся на одной отправке."""
    ok = True
    broker, service = Broker([("parse", 1)]), Service(queued("parse", 1))
    steps = Steps({"parse": [(8, 0)]})
    broker.trigger(2, lambda connection: broker.close_channel(connection.channels[0]))
    run_worker(broker, service, steps)
    ok &= check("каждый шаг выполнен один раз", steps.runs == ["parse", "compare", "protocol"], str(steps.runs))
    ok &= check("сравнение в очереди один раз: после переподключения, а не ещё и при повторной доставке",
                broker.published == [("compare", 1), ("protocol", 1)], str(broker.published))
    ok &= check("повторная доставка разбора сразу подтверждена: ни шага, ни отправки",
                after_redelivery(broker, "parse", 1) == ("ack", "parse", 1), str(after_redelivery(broker, "parse", 1)))
    ok &= check("обработка дошла до протокола", service.processing.get("state") == "DONE", str(service.processing))
    return ok


def test_retries():
    ok = True
    # разбор упал, пока соединения не было: повтор уходит после переподключения
    broker, service = Broker([("parse", 1)]), Service(queued("parse", 1))
    steps = Steps({"parse": [(8, 1), (3, 0)]})
    broker.trigger(2, lambda connection: broker.restart(keep=True))
    run_worker(broker, service, steps)
    ok &= check("сбой без соединения: повтор 2 поставлен один раз, упавшая попытка не повторяется",
                steps.runs == ["parse", "parse", "compare", "protocol"]
                and broker.published.count(("parse", 2)) == 1 and service.processing.get("state") == "DONE",
                f"{steps.runs} {broker.published}")
    # повтор поставлен, брокер упал до подтверждения доставки: отметка не даёт поставить повтор второй раз
    broker, service = Broker([("parse", 1)]), Service(queued("parse", 1))
    steps = Steps({"parse": [(3, 1), (3, 0)]})
    broker.fail_after = ("parse", 2)
    run_worker(broker, service, steps)
    ok &= check("подтверждение не прошло: повтор 2 в очереди один раз, разбор — две попытки",
                broker.published.count(("parse", 2)) == 1 and steps.runs == ["parse", "parse", "compare", "protocol"],
                f"{steps.runs} {broker.published}")
    ok &= check("повторная доставка первой попытки — с отметкой, что повтор уже в очереди",
                warnings(service, "шаг parse, попытка 2 уже в очереди"), str(warnings(service, "повторная доставка")))
    # последняя попытка упала без соединения: процесс остановлен, администратор уведомлён один раз
    last = settings.MAX_RETRIES + 1
    broker, service = Broker([("parse", last)]), Service(queued("parse", last))
    steps = Steps({"parse": [(8, 1)]})
    broker.trigger(2, lambda connection: broker.restart(keep=True))
    run_worker(broker, service, steps)
    ok &= check("повторы исчерпаны без соединения: FAILED, одно уведомление, в очередь ничего",
                steps.runs == ["parse"] and service.processing.get("state") == "FAILED"
                and len(service.notified) == 1 and not broker.published and broker.settled(),
                f"{steps.runs} {service.processing.get('state')} {len(service.notified)} {broker.published}")
    return ok


def test_send_pending():
    """Шаг после переподключения ставится, только если processing ждёт именно его."""
    if not hasattr(worker, "_send_pending"):
        return check("шаг, который не ушёл по оборванному соединению, ставится после переподключения", False,
                     "в service/worker/main.py этого нет")
    ok = True
    context = {"user_id": "admin", "request_id": REQUEST_ID}
    cases = [
        ("ждёт, отметки нет — ставится", queued("compare", 1), [("compare", 1)]),
        ("уже поставлен повторной доставкой — не ставится",
         {**queued("compare", 1), "published_at": "2026-09-28T01:53:00+00:00"}, []),
        ("processing ждёт другую попытку — не ставится", queued("compare", 2), []),
        ("обработка уже остановлена — не ставится", {"state": "FAILED", "step": "compare", "attempt": 1}, []),
    ]
    for name, processing, expected in cases:
        broker, service = Broker([]), Service(processing)
        saved = (infra.db, infra.set_processing, worker.log)
        infra.db, infra.set_processing = service.db, service.set_processing
        worker.log = lambda message, level="INFO", **fields: service.log.append((level, message))
        try:
            worker._pending = (PROCESS_ID, "compare", 1, context)
            worker._send_pending(broker.connect().channel())
        finally:
            infra.db, infra.set_processing, worker.log = saved
        marked = bool(service.processing.get("published_at"))
        ok &= check(name, broker.published == expected and worker._pending is None and marked == bool(expected
                    or processing.get("published_at")), f"{broker.published} {service.processing}")
    # брокер снова недоступен: шаг остаётся ждать следующего подключения
    broker, service = Broker([]), Service(queued("compare", 1))
    channel = broker.connect().channel()
    broker.restart(keep=True)
    saved = (infra.db, infra.set_processing, worker.log)
    infra.db, infra.set_processing = service.db, service.set_processing
    worker.log = lambda message, level="INFO", **fields: service.log.append((level, message))
    try:
        worker._pending = (PROCESS_ID, "compare", 1, context)
        error = None
        worker._send_pending(channel)
    except pika.exceptions.AMQPError as caught:
        error = caught
    finally:
        infra.db, infra.set_processing, worker.log = saved
    ok &= check("отправка упала: шаг ждёт следующего подключения, отметки нет", error is not None
                and worker._pending == (PROCESS_ID, "compare", 1, context)
                and not service.processing.get("published_at"), repr(error))
    worker._pending = None
    return ok


def main():
    ok = True
    for name, test in (("run_step: обрыв соединения посреди шага", test_run_step),
                       ("брокер перезапущен с очередями посреди разбора", test_broker_restarted),
                       ("брокер пересоздан пустым посреди разбора", test_broker_recreated),
                       ("брокер остановлен посреди разбора: имя не разрешается", test_broker_stopped),
                       ("consumer_timeout: канал закрыт посреди разбора (Р-130)", test_consumer_timeout),
                       ("повторы и исчерпанные повторы", test_retries),
                       ("шаг после переподключения", test_send_pending)):
        print(f"\n{name}")
        ok &= test()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
