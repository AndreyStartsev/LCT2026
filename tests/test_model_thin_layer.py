"""Модель читает только страницы, чей текст возьмут правила (27.09).

  python tests/test_model_thin_layer.py

На Полярной 16 режим «модель» переписал 4266 страниц за $30, из них 3922 — векторные чертежи со
слоем за $29. Ни одного решения это не изменило: у страницы со слоем правила читают сам слой, а
прочитанный текст берут только у тонкого (`matrix_rules._may_be_scan`, меньше 40 слов). Теперь
модели отдаются скан без текста и чертёж с тонким слоем — текст кривыми или растр со штампом.
Проверяется на подставной модели: свежая страница и страница из кеша, довызов и переспрос. Порог не
настраивается, а веб-форма по умолчанию читает прицельно моделью: читать моделью все страницы нельзя.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="test-thin-layer-")

import pymupdf  # noqa: E402

from pipeline import reading  # noqa: E402

CALLS = []


def fake_model(png, model=None, timeout=180, url=None, prompt=None):
    CALLS.append(png)
    return {"text": "Текст модели: план 1 этажа, коридор 1500", "model": "test", "cost_usd": 0.001,
            "tokens_in": 10, "tokens_out": 10, "finish_reason": "stop"}


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def sheet(path, words):
    """Лист А3 с `words` словами слоя: чертёж (крупный формат), картинок нет."""
    doc = pymupdf.open()
    page = doc.new_page(width=1191, height=842)
    for i in range(words):
        page.insert_text((40 + (i % 12) * 90, 60 + (i // 12) * 20), f"W{i}")
    doc.save(path)
    doc.close()
    return pymupdf.open(path)


def fresh(words, digest):
    CALLS.clear()
    got = reading.read_page(sheet(os.path.join(TMP, f"{digest}.pdf"), words), 1, digest * 64, use_model=True,
                            use_ocr=False)
    return got, len(CALLS)


def cached(words, digest, **extra):
    row = {"version": reading.READ_VERSION, "kind": "DRAWING", "text": "слой", "text_source": "TEXT_LAYER",
           "sources": ["TEXT_LAYER"], "words": [{"t": f"w{i}", "bbox": [0, 0, 0, 0]} for i in range(words)],
           "rotation": 0, "coords_rotated": True, "width_pt": 1191, "height_pt": 842, "images": 0,
           "quality": "OK", **extra}
    reading.cache_put(digest * 64, 1, "read", row)
    CALLS.clear()
    reading.read_page(sheet(os.path.join(TMP, f"{digest}.pdf"), max(words, 1)), 1, digest * 64, use_model=True,
                      use_ocr=False)
    return len(CALLS)


def main():
    reading.CACHE = os.path.join(TMP, "cache")
    reading.read_model = fake_model
    limit = reading.MODEL_LAYER_WORDS
    ok = check("порог модели — тот же, что у правил и у типа страницы", limit == reading.MIN_WORDS_FOR_TEXT_LAYER == 40)
    source = open(os.path.join(ROOT, "pipeline", "reading.py"), encoding="utf-8").read()
    ok &= check("порог не настраивается: прочитать моделью все страницы нельзя и настройкой",
                "PIPELINE_MODEL_LAYER_WORDS" not in source and "MODEL_LAYER_WORDS = MIN_WORDS_FOR_TEXT_LAYER" in source)
    web = open(os.path.join(ROOT, "service", "web", "src", "components", "UploadPanel.tsx"), encoding="utf-8").read()
    hint = open(os.path.join(ROOT, "service", "web", "src", "labels.ts"), encoding="utf-8").read()
    ok &= check("веб-форма по умолчанию — модель, прицельно: подсказка говорит, какие страницы она читает",
                'useState<ReadingMode>("model")' in web
                and "Модель дочитывает только сканы без текста и чертежи без текстового слоя" in hint)
    ok &= check("решение по виду и числу слов слоя",
                reading.wants_model("SCAN_NO_TEXT", 0) and reading.wants_model("DRAWING", 39)
                and not reading.wants_model("DRAWING", 40) and not reading.wants_model("SCAN_SPARSE", 3)
                and not reading.wants_model("TEXT", 5))

    got, n = fresh(120, "a")
    ok &= check("векторный чертёж со слоем — модель не зовётся, текст — слой",
                n == 0 and got["kind"] == "DRAWING" and "MODEL" not in got["sources"], f"{got['kind']} {got['sources']}")
    got, n = fresh(12, "b")
    ok &= check("чертёж с тонким слоем (текст кривыми, штамп) — модель читает",
                n == 1 and got["kind"] == "DRAWING" and "MODEL" in got["sources"], f"{got['kind']} {got['sources']}")
    got, n = fresh(0, "c")
    ok &= check("страница без текста — модель читает", n == 1 and got["kind"] == "SCAN_NO_TEXT", got["kind"])

    ok &= check("кеш: чертёж со слоем без ответа модели — довызова нет", cached(80, "d") == 0)
    ok &= check("кеш: чертёж с тонким слоем без ответа модели — довызов", cached(8, "e") == 1)
    cut = {"sources": ["TEXT_LAYER", "MODEL"], "text_source": "UNION",
           "model_call": {"finish_reason": "length", "tokens_out": 4000}}
    ok &= check("кеш: обрезанный ответ у чертежа со слоем не переспрашивается", cached(80, "f", **cut) == 0)
    ok &= check("кеш: обрезанный ответ у чертежа с тонким слоем переспрашивается", cached(8, "g", **cut) == 1)
    tess = [{"t": f"o{i}", "bbox": [0, 0, 0, 0], "source": "TESSERACT"} for i in range(200)]
    ok &= check("слова распознавания в слой не считаются",
                reading.layer_words({"words": tess + [{"t": "штамп"}]}) == 1)

    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
