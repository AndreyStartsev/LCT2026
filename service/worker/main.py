"""Воркер «Инспектора ИИ»: шаги обработки из очереди RabbitMQ. Задача #32.

Очереди: parse → compare → protocol. Сообщение — идентификатор процесса и номер попытки.
Шаг выполняется отдельным процессом (`service.worker.steps`) с таймаутом. По ТЗ сбой
или таймаут повторяются до двух раз, затем администратор получает уведомление. Шаг,
который после срока показывает ход, не снимается до предельного срока (#113, `watchdog.py`).

Сообщение подтверждается после окончания шага: если воркер упадёт посреди разбора,
брокер отдаст шаг заново после перезапуска. Пока шаг идёт, воркер обслуживает
соединение с брокером, иначе тот разорвал бы его по пропущенным heartbeat.

Доставку без подтверждения дольше `consumer_timeout` брокер забирает назад и закрывает канал.
Срок брокера задан в docker-compose.yml — сутки, дольше предельного срока любого шага (Р-130).
Если канал всё же закрылся, повторная доставка шага, чей итог уже записан в `processing`, шаг
заново не запускает: воркер ставит в очередь то, что там записано, и подтверждает доставку.

Если соединение с брокером оборвалось посреди шага — брокер перезапущен или пересоздан, сбой
сети, — шаг не бросается: воркер ждёт его под тем же сторожем, записывает итог, а следующий шаг
или повтор ставит в очередь первым делом после переподключения (Р-131). Брокер, пересозданный
с пустыми очередями, исходную доставку потерял, и следующий шаг приходит только так. Отметка
`published_at` в `processing` значит, что брокер сообщение принял: по ней повторная доставка
того же шага не ставит следующий шаг в очередь второй раз.
"""
import json
import os
import resource
import signal
import socket
import subprocess
import sys
import threading
import time

import pika

from service.worker import infra, rules_snapshot, settings, watchdog

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QUEUES = ("parse", "compare", "protocol")
# Пробные прогоны правил со страницы правил эксперта (#222, #223): берутся, только когда шагов
# обработки документов в очередях нет, и ничего на стенде не меняют
RULE_TEST_QUEUE = "ruletest"
_stop = False
# следующий шаг или повтор, который не ушёл по оборванному соединению: (процесс, шаг, попытка, контекст)
_pending = None


def log(message, level="INFO", **fields):
    """Структурный лог по ТЗ, раздел 13: JSON с timestamp, level, service, message."""
    print(json.dumps({"timestamp": infra.now_iso(), "level": level, "service": "worker", "message": message,
                      "request_id": fields.pop("request_id", None), "user_id": fields.pop("user_id", None), **fields},
                     ensure_ascii=False), flush=True)


def record_metrics(step, ok, elapsed):
    """Метрики воркера для /metrics API: число и время шагов, память и процессор. Сбой Redis не мешает работе."""
    try:
        usage_self = resource.getrusage(resource.RUSAGE_SELF)
        usage_children = resource.getrusage(resource.RUSAGE_CHILDREN)
        r = infra.redis()
        r.hincrby("metrics:worker:step_runs", f"{step}:{'ok' if ok else 'failed'}", 1)
        r.hincrbyfloat("metrics:worker:step_seconds", step, elapsed)
        r.hset("metrics:worker:resources", mapping={
            # ru_maxrss в Linux — килобайты
            "rss_bytes": usage_self.ru_maxrss * 1024,
            "children_max_rss_bytes": usage_children.ru_maxrss * 1024,
            "cpu_seconds": usage_self.ru_utime + usage_self.ru_stime + usage_children.ru_utime + usage_children.ru_stime,
            "heartbeat_unixtime": time.time(),
        })
    except Exception:
        pass


def publish(channel, step, process_id, attempt, requested_by=None, request_id=None):
    """Следующий шаг или повтор. Пользователь и запрос API переходят из исходного сообщения:
    по request_id все строки логов обработки связываются с запросом загрузки."""
    channel.basic_publish(
        exchange="",
        routing_key=step,
        body=json.dumps({"process_id": process_id, "step": step, "attempt": attempt,
                         "requested_by": requested_by or "worker", "requested_at": infra.now_iso(),
                         "request_id": request_id}),
        properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
    )


def _relay(stream, step, process_id, context, beat):
    """Вывод шага — строками структурного лога: конвейер печатает текст, в логи он уходит JSON.
    Каждая строка — признак хода шага для сторожа таймаута."""
    for raw in iter(stream.readline, b""):
        beat["at"] = time.monotonic()
        for line in raw.decode("utf-8", errors="replace").replace("\r", "\n").split("\n"):
            if line.strip():
                log(line.strip(), process_id=process_id, step=step, source="step", **context)
    stream.close()


def _quiet(beat, process_id):
    """Сколько секунд шаг не показывает хода: ни строки вывода, ни хода в Redis.

    Redis спрашивается, только когда вывода нет дольше допустимого, и не чаще раза в 30 с:
    цикл шага обслуживает соединение с брокером, и долгий ответ Redis не должен его держать.
    """
    now = time.monotonic()
    quiet = now - beat["at"]
    if quiet <= settings.STALL_TIMEOUT_S:
        return quiet
    # строк давно нет, но чтение страниц пишет ход в Redis каждые 25 страниц, а не в вывод
    if now - beat.get("polled", float("-inf")) >= 30:
        beat["polled"] = now
        try:
            age = watchdog.progress_age(infra.redis().get(f"process:{process_id}:progress"))
        except Exception:
            age = None
        beat["redis_at"] = None if age is None else now - age
    if beat.get("redis_at") is not None:
        quiet = min(quiet, now - beat["redis_at"])
    return quiet


def run_step(connection, step, process_id, context):
    """Запускает шаг отдельным процессом. Возвращает (успех, ошибка, снят ли по таймауту).

    Срок шага — не предел: после него шаг идёт, пока показывает ход, до предельного срока
    (#113, `service/worker/watchdog.py`). Молчащий после срока шаг снимается.

    Если соединение с брокером оборвалось, шаг не бросается: воркер перестаёт обслуживать
    соединение и ждёт шаг под тем же сторожем (Р-131). Раньше ошибка соединения вылетала отсюда
    в main, и процесс шага оставался без хозяина: итог никто не записывал, а повторная доставка
    запускала рядом второй такой же шаг.
    """
    env = dict(os.environ, PIPELINE_OUT=os.path.join(settings.WORK_DIR, process_id, "build"),
               PYTHONPATH=ROOT, PYTHONUNBUFFERED="1")
    proc = subprocess.Popen([sys.executable, "-m", "service.worker.steps", step, process_id],
                            env=env, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    beat = {"at": time.monotonic()}
    relay = threading.Thread(target=_relay, args=(proc.stdout, step, process_id, context, beat), daemon=True)
    relay.start()
    timeout, limit = settings.STEP_TIMEOUT_S[step], settings.STEP_TIMEOUT_MAX_S[step]
    started = time.monotonic()
    extended = False
    serviced = True
    while proc.poll() is None:
        publish_reading()
        if serviced:
            try:
                connection.process_data_events(time_limit=1)
            except pika.exceptions.AMQPError as error:
                serviced = False
                log(f"соединение с брокером оборвалось посреди шага {step}: {error!r}; шаг идёт дальше "
                    f"под сторожем, итог запишется после его конца", level="WARNING", process_id=process_id,
                    step=step, **context)
        else:
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        elapsed = time.monotonic() - started
        if elapsed <= timeout:
            continue
        quiet = _quiet(beat, process_id)
        why = watchdog.overdue(elapsed, quiet, timeout, limit, settings.STALL_TIMEOUT_S)
        if why:
            proc.kill()
            proc.wait()
            return False, f"таймаут шага {step}: {why}", True
        if not extended:
            extended = True
            log(f"шаг {step} идёт дольше срока {timeout} с и показывает ход: продолжается, предельный срок {limit} с",
                process_id=process_id, step=step, **context)
    relay.join(timeout=5)
    if proc.returncode != 0:
        return False, f"шаг {step} завершился с кодом {proc.returncode}", False
    return True, None, False


def _attempt(value):
    try:
        return int(value or 1)
    except (TypeError, ValueError):
        return None


def outcome_recorded(processing, step, attempt):
    """Итог доставки шага `step` попытки `attempt` уже записан в processing (Р-130).

    Брокер отдаёт доставку заново, если канал закрылся до подтверждения: воркер упал, оборвалось
    соединение, истёк consumer_timeout. Если в processing этот же шаг и попытка, QUEUED или RUNNING,
    шаг не закончился, и его нужно выполнить. Если там другой шаг, другая попытка, DONE или FAILED,
    шаг закончился, и выполнять его второй раз не нужно. Пустой или нечитаемый processing итогом
    не считается: шаг выполняется, как до Р-130.
    """
    if not isinstance(processing, dict) or not processing.get("state"):
        return False
    recorded = _attempt(processing.get("attempt"))
    if recorded is None:
        return False
    same = processing.get("step") == step and recorded == attempt
    return not (same and processing["state"] in ("QUEUED", "RUNNING"))


def _awaits(processing, step, attempt):
    """processing ждёт, что шаг `step` попытки `attempt` встанет в очередь, а брокер его ещё не принял."""
    return (isinstance(processing, dict) and processing.get("state") == "QUEUED" and processing.get("step") == step
            and _attempt(processing.get("attempt")) == attempt and not processing.get("published_at"))


def _send(conn, channel, process_id, step, attempt, context):
    """Ставит в очередь следующий шаг или повтор и отмечает в processing, что брокер его принял (Р-131).

    Канал — с подтверждениями издателя (`main`), поэтому `published_at` пишется, только когда
    сообщение у брокера. По этой отметке повторная доставка закончившегося шага не ставит его
    следующий шаг второй раз. Если отправить не удалось — соединение оборвалось посреди шага
    или брокер закрыл канал, — сообщение запоминается и уходит первым после переподключения
    (`_send_pending`), а ошибка идёт в main.
    """
    global _pending
    try:
        publish(channel, step, process_id, attempt, context["user_id"], context["request_id"])
    except pika.exceptions.AMQPError as error:
        _pending = (process_id, step, attempt, context)
        log(f"шаг {step}, попытка {attempt} не поставлен в очередь: {error!r}; встанет после переподключения",
            level="WARNING", process_id=process_id, step=step, attempt=attempt, **context)
        raise
    infra.set_processing(conn, process_id, published_at=infra.now_iso())


def _send_pending(channel):
    """Первым после переподключения — следующий шаг или повтор, который не ушёл по оборванному соединению.

    Ставится, если processing всё ещё ждёт именно его: брокер его не принял, и повторная доставка
    (`_hand_over`) его тоже ещё не поставила. Брокер, сохранивший исходную доставку, отдаст её заново,
    и по отметке `published_at` её только подтвердят. Пересозданный брокер её потерял, и следующий
    шаг приходит только отсюда (Р-131).
    """
    global _pending
    if _pending is None:
        return
    process_id, step, attempt, context = _pending
    with infra.db() as conn:
        row = conn.execute("select processing from processes where id = %s", (process_id,)).fetchone()
        if _awaits(row["processing"] if row else None, step, attempt):
            _send(conn, channel, process_id, step, attempt, context)
            log(f"после переподключения в очередь поставлен шаг {step}, попытка {attempt}", level="WARNING",
                process_id=process_id, step=step, attempt=attempt, **context)
        else:
            log(f"шаг {step}, попытка {attempt} после переподключения не ставится: processing его уже не ждёт",
                process_id=process_id, step=step, attempt=attempt, **context)
    _pending = None


def _hand_over(conn, channel, process_id, step, attempt, processing, context):
    """Повторная доставка закончившегося шага: вместо шага — то, что после него записано в processing.

    Закончившийся шаг мог не поставить следующий шаг или повтор в очередь: канал был уже закрыт,
    и отправка упала. Поэтому QUEUED из processing ставится в очередь здесь, если брокер его ещё
    не принял. С отметкой `published_at` сообщение уже в очереди: его поставил сам шаг или воркер
    после переподключения (Р-131), и второй раз его не ставят.
    """
    state, following = processing.get("state"), processing.get("step")
    if state == "QUEUED" and following in QUEUES:
        next_attempt = _attempt(processing.get("attempt"))
        if processing.get("published_at"):
            done = f"шаг {following}, попытка {next_attempt} уже в очереди"
        else:
            _send(conn, channel, process_id, following, next_attempt, context)
            done = f"в очередь поставлен шаг {following}, попытка {next_attempt}"
        log(f"повторная доставка шага {step}, попытка {attempt}: шаг уже закончен и заново не выполняется, {done}",
            level="WARNING", process_id=process_id, step=step, attempt=attempt, **context)
    else:
        log(f"повторная доставка шага {step}, попытка {attempt}: итог уже записан ({state} {following}), "
            f"шаг заново не выполняется", level="WARNING", process_id=process_id, step=step, attempt=attempt,
            **context)


def _pause(connection, seconds):
    """Пауза перед повтором. Живое соединение в ней обслуживается, оборванное — нет, пауза та же (Р-131).

    Закрытое соединение не трогаем: `sleep` на нём падает не AMQPError, а ValueError («Timeout closed
    before call») — таймер ввода-вывода pika закрыт вместе с соединением.
    """
    deadline = time.monotonic() + seconds
    if connection.is_open:
        try:
            connection.sleep(seconds)
        except pika.exceptions.AMQPError:
            pass
    time.sleep(max(deadline - time.monotonic(), 0))


def handle(connection, channel, method, body):
    try:
        message = json.loads(body)
        process_id, step = message["process_id"], message["step"]
        attempt = int(message.get("attempt", 1))
    except (ValueError, KeyError, TypeError):
        log(f"сообщение не разобрано и отброшено: {body[:200]!r}", level="WARNING")
        channel.basic_ack(method.delivery_tag)
        return

    user_id, request_id = message.get("requested_by"), message.get("request_id")
    context = {"user_id": user_id, "request_id": request_id}
    with infra.db() as conn:
        process = conn.execute("select object_id, status, processing from processes where id = %s",
                               (process_id,)).fetchone()
        if process is None:
            log(f"процесс {process_id} не найден, шаг {step} отброшен", level="WARNING", process_id=process_id, step=step)
            channel.basic_ack(method.delivery_tag)
            return
        # сверяется только повторная доставка; первую воркер выполняет, как и до Р-130
        if method.redelivered and outcome_recorded(process["processing"], step, attempt):
            _hand_over(conn, channel, process_id, step, attempt, process["processing"], context)
            channel.basic_ack(method.delivery_tag)
            return
        infra.set_processing(conn, process_id, state="RUNNING", step=step, attempt=attempt,
                             started_at=infra.now_iso(), error=None, message=None)
    infra.progress(process_id, step, "Шаг запущен")
    log(f"шаг {step} запущен, попытка {attempt}", process_id=process_id, step=step, attempt=attempt, **context)
    started = time.monotonic()
    ok, error, timed_out = run_step(connection, step, process_id, context)
    elapsed = round(time.monotonic() - started, 1)
    record_metrics(step, ok, elapsed)

    with infra.db() as conn:
        if ok:
            following = settings.NEXT_STEP[step]
            if following:
                infra.set_processing(conn, process_id, state="QUEUED", step=following, attempt=1,
                                     queued_at=infra.now_iso(), last_step_seconds=elapsed, published_at=None)
            else:
                infra.set_processing(conn, process_id, state="DONE", step=step, finished_at=infra.now_iso(),
                                     message="Протокол сформирован", last_step_seconds=elapsed)
            log(f"шаг {step} выполнен за {elapsed} с", process_id=process_id, step=step, seconds=elapsed, **context)
            if following:
                _send(conn, channel, process_id, following, 1, context)
        elif attempt <= settings.MAX_RETRIES:
            infra.set_processing(conn, process_id, state="QUEUED", step=step, attempt=attempt + 1, error=error,
                                 message=f"Повтор {attempt} из {settings.MAX_RETRIES} после "
                                         f"{'таймаута' if timed_out else 'сбоя'}", published_at=None)
            log(f"{error}; повтор {attempt} из {settings.MAX_RETRIES}", level="WARNING", process_id=process_id, step=step,
                attempt=attempt, **context)
            _pause(connection, settings.RETRY_DELAY_S)
            _send(conn, channel, process_id, step, attempt + 1, context)
        else:
            infra.set_processing(conn, process_id, state="FAILED", step=step, attempt=attempt, error=error,
                                 finished_at=infra.now_iso())
            infra.settle_status(conn, process_id)
            infra.notify(conn, "admin", "ERROR",
                         f"Обработка процесса {process_id} (объект {process['object_id']}) остановлена на шаге "
                         f"{step} после {attempt} попыток: {error}", process_id, category="ACTION")
            infra.audit(conn, "PROCESSING_FAILED", process_id, process["object_id"],
                        {"step": step, "attempts": attempt, "error": error})
            log(f"{error}; повторы исчерпаны, уведомлён администратор", level="ERROR", process_id=process_id, step=step,
                attempt=attempt, **context)
    finished = (ok and settings.NEXT_STEP[step] is None) or (not ok and attempt > settings.MAX_RETRIES)
    if finished:
        try:
            infra.redis().delete(f"process:{process_id}:progress")
        except Exception:
            pass
    channel.basic_ack(method.delivery_tag)


# Признак «модель во внешнем сервисе» для предупреждения на экране загрузки: ключ на воркер со сроком
# жизни, обновляется из циклов воркера. Пропал Redis или воркер — ключ истекает, а живой воркер
# записывает его снова за полминуты; API берёт «да», если так говорит хоть один живой воркер.
READING_KEY = f"worker:reading:{socket.gethostname()}"
READING_TTL_S = 120
READING_REFRESH_S = 30
_reading = {"at": float("-inf"), "warned": False}


def publish_reading(force=False):
    """Записать признак внешней модели, если с прошлой записи прошло больше READING_REFRESH_S.
    Сбой Redis не мешает обработке; в журнал он пишется один раз до следующей удачной записи."""
    now = time.monotonic()
    if not force and now - _reading["at"] < READING_REFRESH_S:
        return True
    try:
        infra.redis().set(READING_KEY, "1" if settings.EXTERNAL_MODEL else "0", ex=READING_TTL_S)
        _reading.update(at=now, warned=False)
        return True
    except Exception as error:
        # следующая попытка — тоже через READING_REFRESH_S: недоступный Redis не должен
        # держать каждый виток цикла, который обслуживает соединение с брокером
        _reading["at"] = now
        if not _reading["warned"]:
            log(f"признак внешней модели в Redis не записан: {error!r}", level="WARNING")
            _reading["warned"] = True
        return False


def publish_rules():
    """Снимок правил образа — в базу, для страницы правил эксперта (Р-134). Сбой не мешает обработке:
    без снимка страница правил пуста, а разбор идёт как шёл."""
    try:
        with infra.db() as conn:
            fingerprint = rules_snapshot.publish(conn)
        log(f"правила переданы в базу: снимок {fingerprint[:12]}")
        return True
    except Exception as error:
        log(f"правила в базу не переданы: {error!r}", level="WARNING")
        return False


def run_ruletest(connection, test_id, process_id):
    """Пробный прогон правила на одном объекте отдельным процессом (`service.worker.ruletest`).

    Возвращает код выхода или None, если прогон снят по сроку. Пока он идёт, воркер обслуживает
    соединение с брокером, как на шаге обработки.
    """
    env = dict(os.environ, PIPELINE_OUT=os.path.join(settings.WORK_DIR, process_id, "build"),
               PYTHONPATH=ROOT, PYTHONUNBUFFERED="1")
    proc = subprocess.Popen([sys.executable, "-m", "service.worker.ruletest", test_id, process_id],
                            env=env, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    relay = threading.Thread(target=_relay, args=(proc.stdout, RULE_TEST_QUEUE, process_id, {"test_id": test_id},
                                                  {"at": time.monotonic()}), daemon=True)
    relay.start()
    started = time.monotonic()
    serviced = True
    while proc.poll() is None:
        publish_reading()
        if serviced:
            try:
                connection.process_data_events(time_limit=1)
            except pika.exceptions.AMQPError:
                serviced = False
        else:
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        if time.monotonic() - started > settings.RULETEST_TIMEOUT_S:
            proc.kill()
            proc.wait()
            relay.join(timeout=5)
            return None
    relay.join(timeout=5)
    return proc.returncode


def handle_ruletest(connection, channel, method, body):
    """Пробный прогон правила по объектам задания (#222, #223): по объекту за раз, итог — в базе.

    Повторная доставка — после перезапуска воркера — продолжает прогон с объектов без итога.
    Неверный вариант правила останавливает прогон на первом объекте: на прочих он неверен так же.
    """
    try:
        test_id = str(json.loads(body)["test_id"])
    except (ValueError, KeyError, TypeError):
        log("пробный прогон: сообщение без test_id — пропущено", level="WARNING")
        channel.basic_ack(method.delivery_tag)
        return
    with infra.db() as conn:
        test = conn.execute("select code, process_ids, status from rule_tests where id = %s", (test_id,)).fetchone()
        if test is None or test["status"] in ("DONE", "FAILED"):
            channel.basic_ack(method.delivery_tag)
            return
        conn.execute("update rule_tests set status = 'RUNNING', started_at = coalesce(started_at, now()) "
                     "where id = %s", (test_id,))
        finished = {str(r["process_id"]) for r in conn.execute(
            "select process_id from rule_test_results where test_id = %s", (test_id,)).fetchall()}
    log(f"пробный прогон {test['code']}: объектов {len(test['process_ids'])}", test_id=test_id)
    started = time.monotonic()
    error = None
    for process_id in [str(p) for p in test["process_ids"] or []]:
        if process_id in finished:
            continue
        if _stop:
            # доставка не подтверждена: после перезапуска прогон продолжится с этого объекта
            return
        code = run_ruletest(connection, test_id, process_id)
        with infra.db() as conn:
            if code is None:
                conn.execute(
                    "insert into rule_test_results (test_id, process_id, status, error) values (%s, %s, 'FAILED', %s) "
                    "on conflict (test_id, process_id) do update set status = 'FAILED', error = excluded.error",
                    (test_id, process_id, f"прогон на объекте дольше {settings.RULETEST_TIMEOUT_S} с — снят"))
            conn.execute("update rule_tests set done = (select count(*) from rule_test_results where test_id = %s) "
                         "where id = %s", (test_id, test_id))
            if code == ruletest_bad_variant():
                row = conn.execute("select error from rule_test_results where test_id = %s and process_id = %s",
                                   (test_id, process_id)).fetchone()
                error = (row or {}).get("error") or "вариант правила неверный"
                break
    with infra.db() as conn:
        conn.execute("update rule_tests set status = %s, error = %s, finished_at = now() where id = %s",
                     ("FAILED" if error else "DONE", error, test_id))
        # прогоны нужны, пока их смотрят: старше двух недель — убираются вместе с итогами
        conn.execute("delete from rule_tests where created_at < now() - interval '14 days'")
    # метка жизни воркера — и после пробного прогона: иначе WorkerSilent считал бы его молчащим
    record_metrics(RULE_TEST_QUEUE, error is None, time.monotonic() - started)
    channel.basic_ack(method.delivery_tag)


def ruletest_bad_variant():
    from service.worker import ruletest
    return ruletest.BAD_VARIANT


def consume(connection, channel):
    while not _stop:
        publish_reading()
        handled = False
        # сначала доводим начатые процессы до протокола, потом берём новые
        for queue in reversed(QUEUES):
            method, _props, body = channel.basic_get(queue=queue, auto_ack=False)
            if method is not None:
                handle(connection, channel, method, body)
                handled = True
                break
        if not handled:
            # пробные прогоны правил — только когда обработке документов ждать нечего
            method, _props, body = channel.basic_get(queue=RULE_TEST_QUEUE, auto_ack=False)
            if method is not None:
                handle_ruletest(connection, channel, method, body)
                handled = True
        if not handled:
            connection.sleep(1)


def _close(connection):
    """Прежнее соединение закрывается перед переподключением: доставку без подтверждения с живого
    канала брокер тогда вернёт в очередь сразу, а не когда заметит, что соединение молчит."""
    if connection is not None and connection.is_open:
        try:
            connection.close()
        except pika.exceptions.AMQPError:
            pass


def main():
    def stop(_signum, _frame):
        global _stop
        _stop = True
        log("остановка после текущего шага", level="WARNING")

    signal.signal(signal.SIGTERM, stop)
    os.makedirs(settings.WORK_DIR, exist_ok=True)
    log(f"страницы {'да' if settings.PAGES else 'нет'}, распознавание {'да' if settings.OCR else 'нет'}, "
        f"модель {'да' if settings.USE_MODEL else 'нет'}, повторов {settings.MAX_RETRIES}"
        f"{', модель во внешнем сервисе' if settings.EXTERNAL_MODEL else ''}")
    rules_published = publish_rules()
    publish_reading(force=True)
    while not _stop:
        connection = None
        # база могла быть недоступна при старте: снимок повторяется при переподключении к очереди
        if not rules_published:
            rules_published = publish_rules()
        publish_reading()
        try:
            connection = pika.BlockingConnection(infra.amqp_params())
            channel = connection.channel()
            for queue in (*QUEUES, RULE_TEST_QUEUE):
                channel.queue_declare(queue=queue, durable=True)
            channel.basic_qos(prefetch_count=1)
            # отправка возвращается, когда брокер принял сообщение: только тогда пишется published_at
            channel.confirm_delivery()
            log("подключён к очереди")
            # очереди объявлены: пересозданный брокер без них сообщение молча выбросил бы
            _send_pending(channel)
            consume(connection, channel)
            connection.close()
        # имя брокера не разрешается, пока его контейнер остановлен или вне сети: pika отдаёт
        # socket.gaierror как есть, а не AMQPError, и без него воркер падал бы вместе с неотправленным
        except (pika.exceptions.AMQPError, socket.gaierror) as error:
            log(f"очередь недоступна: {error!r}; переподключение", level="ERROR")
            _close(connection)
            time.sleep(3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
