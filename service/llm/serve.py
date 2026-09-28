"""Запуск сервера модели чтения: vLLM с долей видеопамяти по тому, сколько её свободно.

Карту на стенде проверки могут делить несколько команд одновременно. vLLM берёт заданную
долю всей памяти карты и падает, если столько не свободно, поэтому доля считается при
запуске: свободная память минус запас, но не больше потолка. Меньше нижней границы —
модель не влезет, и сервер не запускается вовсе. Тогда воркер читает без неё (или запасным
адресом) и пишет об этом инспектору.

Всё настраивается окружением, значения по умолчанию — под одну H100 80 ГБ:

  LLM_GPU_MEMORY_UTILIZATION  доля памяти карты явно; пусто — считать от свободной
  LLM_GPU_MEMORY_MAX          потолок доли, по умолчанию 0,85
  LLM_GPU_MEMORY_MIN          меньше этого не запускаться, по умолчанию 0,45: веса FP8 —
                              около 31 ГБ, остальное — кеш запросов
  LLM_SERVED_NAME             имя модели в API; то же, что у OpenRouter, чтобы запасной
                              адрес понимал то же имя
  LLM_MAX_MODEL_LEN           окно: скан без слоя уходит картинкой до 4000 px, это до
                              11 тысяч токенов, плюс 4000 на ответ
  LLM_MAX_NUM_SEQS            сколько страниц читается одновременно
  LLM_EXTRA_ARGS              что ещё передать vLLM, строкой
"""
import os
import shlex
import sys

GIB = 2 ** 30


def gpu_share():
    fixed = os.environ.get("LLM_GPU_MEMORY_UTILIZATION")
    if fixed:
        return float(fixed)
    ceiling = float(os.environ.get("LLM_GPU_MEMORY_MAX") or 0.85)
    floor = float(os.environ.get("LLM_GPU_MEMORY_MIN") or 0.45)
    try:
        import torch
        free, total = torch.cuda.mem_get_info()
    except Exception as e:
        print(f"видеокарта в контейнере не видна: {e}", flush=True)
        sys.exit(3)
    share = min(ceiling, (free - 2 * GIB) / total)
    print(f"видеопамять: свободно {free / GIB:.1f} из {total / GIB:.1f} ГБ, доля сервера {share:.2f}", flush=True)
    if share < floor:
        print(f"свободной памяти меньше {floor:.2f} карты — модель не поместится, сервер не запускается",
              flush=True)
        sys.exit(4)
    return round(share, 3)


def main():
    served = os.environ.get("LLM_SERVED_NAME") or "qwen/qwen3.6-27b"
    names = [served] + [n for n in [os.environ.get("LLM_MODEL_REPO")] if n and n != served]
    args = [
        "vllm", "serve", os.environ.get("LLM_MODEL_PATH") or "/models/model",
        "--served-model-name", *names,
        "--host", "0.0.0.0", "--port", "8000",
        "--gpu-memory-utilization", str(gpu_share()),
        "--max-model-len", os.environ.get("LLM_MAX_MODEL_LEN") or "32768",
        "--max-num-seqs", os.environ.get("LLM_MAX_NUM_SEQS") or "32",
        # одна картинка на запрос и никакого видео: меньше памяти уходит на запас под них
        "--limit-mm-per-prompt", '{"image": 1, "video": 0}',
    ] + shlex.split(os.environ.get("LLM_EXTRA_ARGS") or "")
    print("запуск: " + " ".join(shlex.quote(a) for a in args), flush=True)
    os.execvp(args[0], args)


if __name__ == "__main__":
    main()
