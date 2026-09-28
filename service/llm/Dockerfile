# Модель чтения для стенда с видеокартой: vLLM и веса внутри образа, при работе сеть не нужна.
#
# Драйвер NVIDIA в образ не кладётся: его отдаёт хост через NVIDIA Container Toolkit.
# CUDA runtime приходит с образом vLLM, его версия должна подходить к драйверу хоста:
# сборка cu129 требует драйвер не ниже 575, сборка без суффикса (CUDA 13) — не ниже 580.
# Другой образ vLLM передаётся сборке: --build-arg VLLM_IMAGE=vllm/vllm-openai:<тег>.
#
# Веса — Qwen3.6-27B в FP8 (Р-55: 0,986 на представительной выборке и 0,988 на трудной,
# замер через OpenRouter), около 31 ГБ. Ревизия закреплена: от весов зависит прочитанный текст.
# Лицензия Apache 2.0 разрешает класть веса в образ.
#
# Сборка тянет веса с Hugging Face, поэтому образ собирают один раз и передают готовым:
#   docker compose -f docker-compose.yml -f deploy/docker-compose.release.yml build llm
ARG VLLM_IMAGE=vllm/vllm-openai:v0.30.0-cu129
FROM ${VLLM_IMAGE}

ARG MODEL_REPO=Qwen/Qwen3.6-27B-FP8
ARG MODEL_REVISION=e89b16ebf1988b3d6befa7de50abc2d76f26eb09
RUN python3 -c "import sys; from huggingface_hub import snapshot_download; \
snapshot_download(sys.argv[1], revision=sys.argv[2], local_dir='/models/model')" "$MODEL_REPO" "$MODEL_REVISION" \
 && rm -rf /root/.cache/huggingface /models/model/.cache

COPY serve.py /opt/inspector/serve.py

# Закрытый контур: ни весов, ни статистики использования наружу не просить
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 \
    LLM_MODEL_PATH=/models/model LLM_MODEL_REPO=${MODEL_REPO} LLM_MODEL_REVISION=${MODEL_REVISION}

EXPOSE 8000
# Сервер поднимается минутами: веса в память карты, затем сборка ядер
HEALTHCHECK --interval=15s --timeout=5s --start-period=20m --retries=4 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1
ENTRYPOINT ["python3", "/opt/inspector/serve.py"]
