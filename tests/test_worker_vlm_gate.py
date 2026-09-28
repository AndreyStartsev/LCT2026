"""Прицельный проход по чертежам — по настройке сервиса, а не по способу чтения страниц (27.09).

  python tests/test_worker_vlm_gate.py

Проход шёл только у процесса, который читается моделью целиком. Веб-форма всегда присылает способ
чтения, по умолчанию «распознавание», и при загрузке через веб проход не шёл вовсе, а чтобы он пошёл
у загрузчика, на стенде включили чтение моделью по умолчанию — и с ним полное переписывание страниц
($30 на Полярной 16 без единого изменённого решения). Теперь проход идёт при любом способе, кроме
«только слой», если он включён и модель настроена.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from service.worker import settings, steps  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def gate(vlm, ready, mode):
    saved = settings.VLM, settings.MODEL_READY
    settings.VLM, settings.MODEL_READY = vlm, ready
    try:
        return steps.vlm_skip_reason(mode)
    finally:
        settings.VLM, settings.MODEL_READY = saved


def main():
    ok = check("веб по умолчанию («распознавание») — проход идёт", gate(True, True, "tesseract") is None)
    ok &= check("способ «модель» — проход идёт", gate(True, True, "model") is None)
    ok &= check("«только слой» — проход не идёт, причина названа", gate(True, True, "layer") == "объект читается только слоем")
    ok &= check("модель не настроена — не идёт", gate(True, False, "tesseract") == "модель не настроена")
    ok &= check("проход выключен — не идёт", gate(False, True, "model") == "выключен (PIPELINE_VLM)")
    compose = open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8").read()
    ok &= check("по умолчанию везде прицельно: проход включён, модель — способ по умолчанию",
                "PIPELINE_VLM: ${PIPELINE_VLM:-1}" in compose and "PIPELINE_MODEL: ${PIPELINE_MODEL:-1}" in compose
                and "PIPELINE_READING_MODE: ${PIPELINE_READING_MODE:-model}" in compose)
    source = open(os.path.join(ROOT, "service", "worker", "steps.py"), encoding="utf-8").read()
    ok &= check("шаг разбора решает о проходе через vlm_skip_reason, а не по чтению страниц моделью",
                "skip = vlm_skip_reason(mode)" in source and "if settings.VLM and not use_model" not in source)
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
