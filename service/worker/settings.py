"""Настройки воркера из окружения. Значения по умолчанию подходят для docker compose."""
import os


def _flag(name, default):
    return os.environ.get(name, "1" if default else "0").strip().lower() not in ("0", "false", "no", "")


def secret(name):
    """Секрет из переменной или из файла, путь к которому в переменной NAME_FILE.

    В docker compose секреты генерируются при первом запуске и лежат в томе:
    паролей в репозитории нет.
    """
    if os.environ.get(name):
        return os.environ[name]
    path = os.environ.get(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    return None


# Подключение к базе: либо DATABASE_URL целиком, либо части и пароль из файла.
DATABASE_URL = os.environ.get("DATABASE_URL") or (
    f"host={os.environ.get('DATABASE_HOST', 'postgres')} port={os.environ.get('DATABASE_PORT', '5432')} "
    f"user={os.environ.get('DATABASE_USER', 'inspector')} dbname={os.environ.get('DATABASE_NAME', 'inspector')}")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
AMQP_URL = os.environ.get("AMQP_URL", "amqp://guest:guest@rabbitmq:5672/%2F")

S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "minio:9000")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "inspector")
S3_BUCKET = os.environ.get("S3_BUCKET", "documents")
S3_SECURE = _flag("S3_USE_SSL", False)

# Рабочий каталог: сюда из хранилища выкладываются файлы процесса и пишутся
# промежуточные результаты конвейера, по подкаталогу на процесс.
WORK_DIR = os.environ.get("WORK_DIR", "/work")

# Способ чтения объекта. Один выбор вместо трёх флагов: где-то хватает текстового слоя,
# где-то нужен Tesseract, где-то модель. Режим задаётся на объект при загрузке и едет
# в процессе, поэтому он здесь — значение по умолчанию, а не окончательное (#54).
#
#   layer     — только текстовый слой: быстро, но на сканах система молчит
#   tesseract — слой и распознавание сканов: так работает стенд по умолчанию
#   model     — слой, распознавание и мультимодальная модель на сканах и чертежах
READING_MODES = ("layer", "tesseract", "model")
READING_MODE = os.environ.get("PIPELINE_READING_MODE") or "tesseract"
if READING_MODE not in READING_MODES:
    READING_MODE = "tesseract"

# Прежние флаги остаются: ими переопределяют режим поштучно, и на них опирается
# существующая настройка стендов.
PAGES = _flag("PIPELINE_PAGES", True)
OCR = _flag("PIPELINE_OCR", READING_MODE in ("tesseract", "model"))
# Шесть потоков: на восьми и десяти распознавание идёт медленнее — Tesseract сам
# многопоточный. Текст от числа потоков не зависит, проверено посимвольно (#52).
TABLE_OCR = _flag("PIPELINE_TABLE_OCR", True)

# Черновики правил (#95, Р-89): после правил прода воркер гоняет черновики из rules/provisional,
# и их нарушения идут в протокол гипотезами — в сдачу только решением инспектора. Подход
# 25.09: в гипотезы — по максимуму, в нарушения — только одобренное специалистом. Поэтому
# по умолчанию включено; PIPELINE_PROVISIONAL=0 выключает профиль целиком.
PROVISIONAL = _flag("PIPELINE_PROVISIONAL", True)
# Проход модели по чертежам (#98): 30 правил `vlm_value` берут значение, которого в тексте нет,
# из ответов модели по листам. Без прохода на новом объекте они молчат. Через OpenRouter он
# платный, поэтому по умолчанию выключен; на стенде со своей моделью (надстройка поставки на H100)
# включён. Идёт в конце разбора и только у процессов, которые читаются моделью. Потолок вызовов
# на объект, число одновременных вопросов и модель — PIPELINE_VLM_LIMIT, PIPELINE_VLM_WORKERS,
# PIPELINE_VLM_MODEL, их читает pipeline/vlm_values.py
VLM = _flag("PIPELINE_VLM", False)
# сколько листов на параметр и стадию спрашивать: столько же, сколько `run --vlm`
VLM_SHEETS = int(os.environ.get("PIPELINE_VLM_SHEETS", "6"))
PAGE_WORKERS = int(os.environ.get("PIPELINE_PAGE_WORKERS", "6"))
OCR_WORKERS = int(os.environ.get("PIPELINE_OCR_WORKERS", "6"))
# Модель включается режимом или флагом. Ключ нужен не всякому адресу: своя модель
# на своём железе обычно раздаётся без него, поэтому проверяется адрес, а не ключ.
MODEL_URL = os.environ.get("PIPELINE_MODEL_URL") or "https://openrouter.ai/api/v1/chat/completions"


def _model_choices():
    """Модели, которые инспектор выбирает при загрузке: «id=Название» через запятую.

    Список один на сервис (`PIPELINE_MODEL_CHOICES`): API показывает его на экране загрузки
    и проверяет выбор, воркер читает выбранной моделью. Пустой список означает, что модель
    одна — та, что названа в `PIPELINE_MODEL_NAME`.
    """
    out = []
    for item in (os.environ.get("PIPELINE_MODEL_CHOICES") or "").split(","):
        model_id, _, label = item.strip().partition("=")
        model_id = model_id.strip()
        if model_id:
            out.append({"id": model_id, "label": label.strip() or model_id})
    return out


MODEL_CHOICES = _model_choices()
MODEL_NAME = os.environ.get("PIPELINE_MODEL_NAME") or (MODEL_CHOICES[0]["id"] if MODEL_CHOICES else "")
MODEL_KEY_ENV = os.environ.get("PIPELINE_MODEL_KEY_ENV") or "OPENROUTER_API_KEY"
# Запасной адрес (pipeline/reading.py): своя модель не ответила — страница уходит туда.
# Для OpenRouter он годен только с ключом; без запасного стенд работает как раньше.
MODEL_FALLBACK_URL = os.environ.get("PIPELINE_MODEL_FALLBACK_URL") or ""
MODEL_FALLBACK_KEY_ENV = os.environ.get("PIPELINE_MODEL_FALLBACK_KEY_ENV") or "OPENROUTER_API_KEY"
# Сколько ждать свою модель в начале разбора: сервер модели поднимается минутами (веса,
# сборка ядер), а объект могут загрузить сразу после запуска. 0 — не ждать.
MODEL_WAIT_S = float(os.environ.get("PIPELINE_MODEL_WAIT_S") or 0)


def _is_openrouter(url):
    return "openrouter.ai" in (url or "")


def _address_ready(url, key_env):
    return bool(url) and (bool(os.environ.get(key_env)) or not _is_openrouter(url))


MAIN_READY = _address_ready(MODEL_URL, MODEL_KEY_ENV)
FALLBACK_READY = bool(MODEL_FALLBACK_URL) and MODEL_FALLBACK_URL != MODEL_URL \
    and _address_ready(MODEL_FALLBACK_URL, MODEL_FALLBACK_KEY_ENV)
MODEL_READY = MAIN_READY or FALLBACK_READY
USE_MODEL = _flag("PIPELINE_MODEL", READING_MODE == "model") and MODEL_READY


def is_external(url):
    """Адрес модели вне стенда: страницы по нему уходят с этой машины и из её сети.

    Сначала адрес проверяется как IP (в том числе IPv6 и числовая запись IPv4): свой — не
    глобальный, то есть частный, петлевой, общий провайдерский (100.64/10). Имя без точки —
    сервис compose (llm, model-host); localhost и имена в зонах .internal, .local и
    .svc.cluster.local — свои. Всё остальное — внешний сервис.
    """
    import ipaddress
    import socket
    from urllib.parse import urlsplit
    host = (urlsplit(url or "").hostname or "").lower().rstrip(".")
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            # числовая запись IPv4 без точек (134744072, 0x8080808) — тоже адрес
            address = ipaddress.ip_address(socket.inet_aton(host))
        except OSError:
            address = None
    if address is not None:
        return address.is_global
    if host == "localhost" or "." not in host:
        return False
    return not host.endswith((".internal", ".local", ".svc.cluster.local", ".localhost"))


# Чтение моделью может отправить страницы во внешний сервис: основным адресом или запасным.
# Экран загрузки об этом предупреждает (воркер держит признак в Redis, API его отдаёт).
# Признак не зависит от способа чтения объекта: исполнительные схемы читаются моделью при любом
# способе (pipeline/pages.py, PIPELINE_ID_SCHEME_MODEL), проход по чертежам — при любом, кроме
# «только слой». PIPELINE_MODEL_EXTERNAL=1 или 0 задаёт признак явно, если правило адресов ошибается.
EXTERNAL_MODEL = (_flag("PIPELINE_MODEL_EXTERNAL", False) if os.environ.get("PIPELINE_MODEL_EXTERNAL", "").strip()
                  else (MAIN_READY and is_external(MODEL_URL)) or (FALLBACK_READY and is_external(MODEL_FALLBACK_URL)))


def probe_model(url, timeout=5, key_env=None):
    """Отвечает ли сервер модели: (да ли, почему нет, сетевой ли отказ).

    Спрашивается список моделей (`/v1/models` рядом с `/v1/chat/completions`) — его отдают
    vLLM, SGLang, Ollama и llama.cpp, и он не тратит карту. Сетевой отказ без имени
    (контейнер модели остановлен) ждать бессмысленно, отвергнутое соединение — можно:
    сервер ещё грузит веса.
    """
    import socket, urllib.error, urllib.request
    base = url.rsplit("/chat/completions", 1)[0]
    # сервер, закрытый ключом (vLLM с --api-key), без ключа не отдаёт и список моделей
    key = os.environ.get(key_env or MODEL_KEY_ENV)
    request = urllib.request.Request(base + "/models", headers={"Authorization": f"Bearer {key}"} if key else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status == 200, None, False
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}", False
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        reason = getattr(e, "reason", None)
        name_missing = isinstance(reason, socket.gaierror)
        return False, "нет адреса" if name_missing else type(reason if isinstance(reason, BaseException) else e).__name__, \
            not name_missing
    except Exception as e:
        return False, type(e).__name__, False


def model_route(wait_s=None, progress=None, sleep=None):
    """Чем читать модель в этом разборе: ("main" | "fallback" | None, почему не основной).

    OpenRouter основным адресом не проверяется: он есть всегда, а ключ проверен настройкой.
    Своя модель проверяется запросом; пока она поднимается, разбор ждёт до `wait_s` секунд.
    Не поднялась — запасной адрес, если он годен, иначе чтение без модели.
    """
    import time
    if _is_openrouter(MODEL_URL):
        return ("main", None) if MAIN_READY else \
            (("fallback", f"нет {MODEL_KEY_ENV}") if FALLBACK_READY else (None, f"нет {MODEL_KEY_ENV}"))
    wait_s = MODEL_WAIT_S if wait_s is None else wait_s
    sleep = sleep or time.sleep
    deadline = time.monotonic() + wait_s
    while True:
        ok, why, retry = probe_model(MODEL_URL)
        if ok:
            return "main", None
        left = deadline - time.monotonic()
        if not retry or left <= 0:
            break
        if progress:
            progress(why, left)
        sleep(min(10, max(left, 0.1)))
    return ("fallback" if FALLBACK_READY else None), f"своя модель не отвечает ({why})"


def reading_mode(requested=None):
    """Режим чтения процесса: выбор инспектора, иначе значение сервиса.

    Режим, для которого нет модели (не задан адрес или ключ), понижается до распознавания:
    молча читать слоем вместо обещанного разбора нельзя, а падать из-за настройки — тем более.
    """
    mode = requested if requested in READING_MODES else READING_MODE
    if mode == "model" and not MODEL_READY:
        return "tesseract"
    return mode


def model_for(requested=None):
    """Модель процесса: выбор инспектора, если он среди настроенных, иначе модель сервиса.

    Незнакомую модель не берём: список задаёт тот, кто платит за вызовы, и случайное
    имя из запроса не должно уходить провайдеру.
    """
    known = [choice["id"] for choice in MODEL_CHOICES]
    if requested and (requested in known or not known):
        return requested
    return MODEL_NAME or None


def mode_of(ocr, model):
    """Как назвать способ чтения по тому, что включено."""
    return "model" if model else "tesseract" if ocr else "layer"


def reading_flags(requested=None):
    """Способ чтения и что он включает: (режим, распознавание, модель).

    Выбор инспектора сильнее флагов окружения: он сделан на этот объект и записан у
    процесса. Когда выбора нет, работают прежние флаги, а режим называется по ним —
    в протоколе должно стоять то, чем читали, а не то, что задумывалось.
    """
    if requested in READING_MODES:
        mode = reading_mode(requested)
        return mode, mode in ("tesseract", "model"), mode == "model"
    return mode_of(OCR, USE_MODEL), OCR, USE_MODEL

# ТЗ: таймаут обработки — до двух повторов, затем уведомление администратора.
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "2"))
RETRY_DELAY_S = float(os.environ.get("RETRY_DELAY_S", "10"))
STEP_TIMEOUT_S = {
    "parse": int(os.environ.get("TIMEOUT_PARSE_S", "7200")),
    "compare": int(os.environ.get("TIMEOUT_COMPARE_S", "1800")),
    "protocol": int(os.environ.get("TIMEOUT_PROTOCOL_S", "600")),
}
# После срока шаг живёт, пока показывает ход, но не дольше предельного срока: по умолчанию
# втрое больше срока — столько же давали три попытки. Молчание дольше STALL_TIMEOUT_S после
# срока — зависание, шаг снимается и повторяется (#113, service/worker/watchdog.py).
STEP_TIMEOUT_MAX_S = {step: max(int(os.environ.get(f"TIMEOUT_{step.upper()}_MAX_S", str(3 * timeout))), timeout)
                      for step, timeout in STEP_TIMEOUT_S.items()}
STALL_TIMEOUT_S = int(os.environ.get("STALL_TIMEOUT_S", "1800"))
# Пробный прогон правила на одном объекте (#222, #223): из кеша — секунды, у холодного кеша большого
# объекта — минуты. Дольше срока прогон снимается, объект получает отказ, прогон идёт дальше
RULETEST_TIMEOUT_S = int(os.environ.get("TIMEOUT_RULETEST_S", "900"))
NEXT_STEP = {"parse": "compare", "compare": "protocol", "protocol": None}

PIPELINE_VERSION = os.environ.get("PIPELINE_VERSION", "dev")
