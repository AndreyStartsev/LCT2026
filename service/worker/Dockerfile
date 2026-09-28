# Сборка из корня репозитория: воркер запускает конвейер pipeline/ как есть.

# Правила Матрицы в открытый репозиторий не входят. Этот этап берёт их из папки rules/, а если их
# там нет — выкачивает из закрытого репозитория по токену RULES_TOKEN из .env и сверяет суммы
# с rules/manifest.json (rules/fetch.py). Токен приходит секретом сборки и в образ не попадает.
# Этап идёт параллельно с установкой пакетов, поэтому неверный токен виден в первые секунды.
FROM python:3.11-slim-trixie AS rules
WORKDIR /app
COPY rules rules
RUN --mount=type=secret,id=rules_token \
    python rules/fetch.py --secret /run/secrets/rules_token --no-prompt

FROM python:3.11-slim-trixie
# Версия распознавания закреплена: от неё зависят прочитанный текст и замеры качества.
# Если Debian увёл пакет, доступную версию покажет `apt-cache policy tesseract-ocr`,
# и она передаётся сборке: docker compose build --build-arg TESSERACT_VERSION=... worker
ARG TESSERACT_VERSION=5.5.0-1+b1
ARG TESSERACT_LANG_VERSION=1:4.1.0-2
# catdoc — текст документов Word прежнего формата (DOC) для ИД, #112: pipeline/office_text.py
ARG CATDOC_VERSION=1:0.95-6
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      "tesseract-ocr=$TESSERACT_VERSION" \
      "tesseract-ocr-rus=$TESSERACT_LANG_VERSION" \
      "tesseract-ocr-eng=$TESSERACT_LANG_VERSION" \
      "catdoc=$CATDOC_VERSION" \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY service/worker/requirements.txt service/worker/requirements.txt
RUN pip install --no-cache-dir -r service/worker/requirements.txt
COPY pipeline pipeline
COPY contracts contracts
COPY --from=rules /app/rules rules
COPY docs/extracted docs/extracted
# Эмбеддинги BGE-M3 (#72) в образ не ставятся (#79, Р-127): на настоящих весах их единственный
# потребитель — перенос гипотезы свободного поиска в MATRIX — ронял балл с 99,28 до 93,96, и он
# выключен флагом FREE_SEARCH_MATRIX. Сопоставление в classify() идёт на стеммах; веса для опытов
# вне сервиса качает models/embeddings/download.py.
# загрузчик папки объекта (#32): в поставке он работает из этого образа, deploy/docker-compose.release.yml
COPY tools/upload_object.py tools/upload_object.py
COPY service/__init__.py service/__init__.py
COPY service/worker service/worker
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app PIPELINE_CACHE=/app/.cache WORK_DIR=/work
CMD ["python", "-m", "service.worker.main"]
