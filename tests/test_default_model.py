"""Модель по умолчанию одна: чтение страниц, прицельный проход, список сервиса и своя модель (Р-169).

  python tests/test_default_model.py

Под прод выбрана qwen/qwen3.6-27b (Р-55). Умолчанием чтения страниц (`reading.DEFAULT_MODEL`) до Р-169
оставалась google/gemini-2.5-flash-lite. Где у вызова не было имени модели — командная строка, замер
скорости, сервис с пустым списком моделей, исполнительные схемы до Р-168 — страницу читала не та модель,
а своя модель поставки отвечала на это имя 404. Проверяется, что умолчания совпадают:

- `reading.DEFAULT_MODEL` и `reading.model_name()` без переменных окружения;
- `vlm_values.MODEL` без `PIPELINE_VLM_MODEL`;
- первая модель `PIPELINE_MODEL_CHOICES` в docker-compose.yml у воркера и API и в надстройке поставки:
  её берёт сервис, когда `PIPELINE_MODEL_NAME` не задан;
- имя, под которым модель раздаёт сервер своей модели (service/llm/serve.py).
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for name in ("PIPELINE_MODEL_NAME", "BENCH_MODEL", "PIPELINE_VLM_MODEL"):
    os.environ.pop(name, None)

from pipeline import reading, vlm_values  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def first_choices(path):
    """Первая модель каждого списка `PIPELINE_MODEL_CHOICES` по умолчанию в файле compose."""
    return re.findall(r"PIPELINE_MODEL_CHOICES: \$\{PIPELINE_MODEL_CHOICES:-([^=,}]+)", read(path))


def main():
    want = reading.DEFAULT_MODEL
    ok = check("без переменных окружения страницу читает модель по умолчанию", reading.model_name() == want, want)
    ok &= check("прицельный проход спрашивает ту же модель", vlm_values.MODEL == want, vlm_values.MODEL)
    stand = first_choices("docker-compose.yml")
    ok &= check("стенд: первая в списке моделей воркера и API — она же",
                len(stand) == 2 and set(stand) == {want}, str(stand))
    release = first_choices("deploy/docker-compose.release.yml")
    ok &= check("поставка: первая в списке моделей — она же", release and set(release) == {want}, str(release))
    served = re.search(r'os\.environ\.get\("LLM_SERVED_NAME"\) or "([^"]+)"', read("service/llm/serve.py"))
    ok &= check("своя модель раздаётся под этим именем", served and served.group(1) == want,
                served.group(1) if served else "имени нет")
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
