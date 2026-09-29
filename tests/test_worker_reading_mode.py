"""Смена способа чтения перечитывает объект при повторном разборе (#54, #60).

  python tests/test_worker_reading_mode.py

27.09 на стенде включили модель для всех процессов (PIPELINE_MODEL=1) и перезапустили разбор
Полярной 16. Повторный разбор пересчитывает только новые документы, а их не было: страницы
остались прочитанными без модели, а протокол назвал способом «model». Теперь способ, которым
прочитаны страницы, пишется в `pages_mode.json`, и его смена — повод перечитать весь объект.
Проверяется план пересчёта шага разбора: что читать заново и какая причина уходит в протокол.
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="test-worker-mode-")
os.environ["PIPELINE_OUT"] = os.path.join(TMP, "build")

from service.worker import steps  # noqa: E402

OBJ = "TST-MODE"
DOCS = [{"file_id": "A", "sha256": "1"}, {"file_id": "B", "sha256": "2"}]


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def put(name, data):
    path = steps.out_path(OBJ, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data))


def drop(name):
    path = steps.out_path(OBJ, name)
    if os.path.exists(path):
        os.remove(path)


def main():
    plan = steps.parse_plan
    full, fresh, why = plan(OBJ, DOCS, [], set(), "model")
    ok = check("первый разбор — весь объект", full and why == "прошлого разбора нет", why)

    full, fresh, why = plan(OBJ, DOCS, DOCS, set(), "model")
    ok &= check("без постраничного индекса — весь объект", full and "индекса" in why, why)

    put("pages.jsonl", '{"file_id": "A", "pdf_page_number": 1}\n')
    full, fresh, why = plan(OBJ, DOCS, DOCS, set(), "model")
    ok &= check("индекс есть, способ его страниц не записан (разбор до правки) — весь объект, один раз",
                full and "не записан" in why and "model" in why, why)

    put(steps.PAGES_MODE, {"reading_mode": "tesseract"})
    full, fresh, why = plan(OBJ, DOCS, DOCS, set(), "model")
    ok &= check("страницы прочитаны распознаванием, теперь модель — весь объект",
                full and why == "способ чтения страниц сменился: tesseract → model", why)
    full, fresh, why = plan(OBJ, DOCS, DOCS, set(), "layer")
    ok &= check("и в обратную сторону: распознавание → только слой", full and "tesseract → layer" in why, why)

    put(steps.PAGES_MODE, {"reading_mode": "model"})
    full, fresh, why = plan(OBJ, DOCS, DOCS, set(), "model")
    ok &= check("способ тот же, новых документов нет — ничего не перечитывается",
                not full and fresh == set() and why == "новых документов нет", why)
    more = DOCS + [{"file_id": "C", "sha256": "3"}]
    full, fresh, why = plan(OBJ, more, DOCS, set(), "model")
    ok &= check("способ тот же, дозагружен документ — читается только он", not full and fresh == {"C"}, why)
    full, fresh, why = plan(OBJ, DOCS, DOCS, {"B"}, "model")
    ok &= check("стадию поправил инспектор — документ перечитывается", not full and fresh == {"B"}, why)
    was = [dict(DOCS[0], stage="ID"), dict(DOCS[1], stage="RD")]
    now = [dict(DOCS[0], stage="ID"), dict(DOCS[1], stage="PD")]
    full, fresh, why = plan(OBJ, now, was, {"A"}, "model")
    ok &= check("у B сняли ручную стадию, у A ручная стоит с прошлого разбора — весь объект",
                full and fresh == {"A", "B"} and "стадия или раздел" in why, why)
    full, fresh, why = plan(OBJ, DOCS[:1], DOCS, set(), "model")
    ok &= check("документа не стало — весь объект, как раньше", full and "не стало" in why, why)

    drop("pages.jsonl")
    ok &= check("нет индекса — способ прошлого разбора не спрашивается", steps.pages_mode_changed(OBJ, "tesseract") is None)

    source = open(os.path.join(ROOT, "service", "worker", "steps.py"), encoding="utf-8").read()
    written = source.find('cli.write_jsonl(out_path(obj, "pages.jsonl"), rows)')
    mode_saved = source.find('json.dump({"reading_mode": mode, "model_name": model', written)
    ok &= check("шаг разбора пишет способ сразу за постраничным индексом и берёт план из parse_plan",
                written > 0 and 0 < mode_saved - written < 300
                and "full, fresh, why = parse_plan(obj, documents, previous, restaged, mode)" in source)

    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
