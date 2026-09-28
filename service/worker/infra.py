"""Подключения воркера: база, хранилище, Redis, очередь."""
import datetime as dt
import json

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb, set_json_dumps

from service.worker import settings


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def clean(value):
    """Убрать символ NUL из строк: Postgres не хранит его ни в text, ни в jsonb.

    В текстовом слое PDF со сломанной кодировкой шрифта он встречается, и разбор Полярной 16
    падал на записи изменений между редакциями: «\\u0000 cannot be converted to text».
    """
    if isinstance(value, str):
        return value.replace("\x00", "") if "\x00" in value else value
    if isinstance(value, dict):
        return {clean(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


# Всё, что воркер пишет в jsonb, — протокол, записи, изменения редакций — проходит через clean
set_json_dumps(lambda obj: json.dumps(clean(obj)))


def db():
    password = settings.secret("DATABASE_PASSWORD")
    extra = {"password": password} if password else {}
    return psycopg.connect(settings.DATABASE_URL, row_factory=dict_row, autocommit=True, **extra)


def storage():
    from minio import Minio
    key = settings.secret("S3_SECRET_KEY")
    if not key:
        raise RuntimeError("не задан S3_SECRET_KEY: укажите переменную S3_SECRET_KEY или S3_SECRET_KEY_FILE")
    return Minio(settings.S3_ENDPOINT, access_key=settings.S3_ACCESS_KEY, secret_key=key, secure=settings.S3_SECURE)


def blob_key(sha256):
    return f"blobs/{sha256[:2]}/{sha256}"


_redis = None


def redis():
    global _redis
    if _redis is None:
        import redis as redis_lib
        _redis = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def progress(process_id, step, message, done=None, total=None):
    """Ход обработки для опроса статуса. Сбой Redis обработку не останавливает."""
    payload = {"step": step, "message": message, "updated_at": now_iso()}
    if done is not None:
        payload["done"] = int(done)
    if total is not None:
        payload["total"] = int(total)
    try:
        redis().set(f"process:{process_id}:progress", json.dumps(payload, ensure_ascii=False), ex=24 * 3600)
    except Exception:
        pass


def set_processing(conn, process_id, **fields):
    """Сливает поля в processes.processing."""
    conn.execute(
        "update processes set processing = coalesce(processing, '{}'::jsonb) || %s, updated_at = now() where id = %s",
        (Jsonb(fields), process_id),
    )


def notify(conn, role, level, message, process_id=None, category="INFO"):
    """Уведомление роли. `category` — куда оно попадёт: ACTION показывается на рабочем экране,
    QUALITY живёт в журнале обработки объекта, INFO — событие без действия."""
    conn.execute(
        "insert into notifications (role, process_id, level, category, message) values (%s, %s, %s, %s, %s)",
        (role, process_id, level, category, message),
    )


def audit(conn, action, process_id, object_id, details, user_id="worker"):
    conn.execute(
        "insert into audit_log (user_id, action, object_id, process_id, details) values (%s, %s, %s, %s, %s)",
        (user_id, action, object_id, process_id, Jsonb(details)),
    )


def amqp_params():
    import pika
    params = pika.URLParameters(settings.AMQP_URL)
    params.heartbeat = 60
    params.blocked_connection_timeout = 300
    return params


def settle_status(conn, process_id):
    """Статус процесса по его протоколу и решениям: для сбоя и для завершения шага.

    Без протокола документы загружены, а проверка не выполнена — PENDING. С протоколом
    статус определяют решения инспектора: ни одного — READY, все кандидаты решены —
    COMPLETED, иначе VERIFYING. Финализированный процесс не трогаем.
    """
    row = conn.execute(
        """select p.status,
                  exists(select 1 from protocols where process_id = p.id) as has_protocol,
                  (select count(*) from findings where process_id = p.id and verification_status = 'PENDING') as pending,
                  (select count(*) from findings where process_id = p.id
                     and verification_status in ('CONFIRMED_VIOLATION', 'NEGATIVE_VERIFIED', 'CLARIFICATION_REQUIRED')) as decided
           from processes p where p.id = %s""",
        (process_id,),
    ).fetchone()
    if row is None or row["status"] == "FINALIZED":
        return
    if not row["has_protocol"]:
        status = "PENDING"
    elif row["decided"] == 0:
        status = "READY"
    else:
        status = "COMPLETED" if row["pending"] == 0 else "VERIFYING"
    conn.execute("update processes set status = %s, updated_at = now() where id = %s", (status, process_id))
    return status

