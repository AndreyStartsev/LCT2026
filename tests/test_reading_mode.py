"""Способ чтения объекта: выбор при загрузке доходит до страницы. Задача #54.

  python tests/test_reading_mode.py

Один объект приходит сканами, другой — выгрузкой с текстовым слоем, третий — сканами
такого качества, что распознавание на них молчит. Раньше это решалось переменными
окружения на весь воркер: сменить способ чтения одному объекту было нельзя. Теперь способ
выбирается при загрузке и едет с процессом.

Проверяется три вещи: выбор инспектора сильнее настройки сервиса; режим, для которого
модель не настроена, понижается до распознавания, а не падает и не читает молча слоем;
и что флаг доезжает до чтения страницы, а не только до отчёта.
"""
import importlib.util
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import readiness  # noqa: E402

SETTINGS_PATH = os.path.join(ROOT, "service", "worker", "settings.py")
KEY = "OPENROUTER_API_KEY"
LOCAL_MODEL = "http://localhost:8000/v1/chat/completions"


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def load_settings(**env):
    """Настройки воркера с заданным окружением: они читаются при импорте."""
    saved = dict(os.environ)
    for name, value in env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    try:
        spec = importlib.util.spec_from_file_location("worker_settings_probe", SETTINGS_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return mod


def test_choice_wins():
    """Выбор инспектора сильнее настройки сервиса и прежних флагов."""
    service = load_settings(PIPELINE_READING_MODE="tesseract", PIPELINE_OCR=None,
                            PIPELINE_MODEL=None, **{KEY: "ключ-для-проверки"})
    ok = check("объект просит только слой — распознавание выключается",
               service.reading_flags("layer") == ("layer", False, False),
               str(service.reading_flags("layer")))
    ok &= check("объект просит модель, модель настроена — включается",
                service.reading_flags("model") == ("model", True, True),
                str(service.reading_flags("model")))
    ok &= check("без выбора работает настройка сервиса",
                service.reading_flags(None) == ("tesseract", True, False),
                str(service.reading_flags(None)))
    ok &= check("незнакомое значение — это отсутствие выбора, а не сбой",
                service.reading_flags("быстро") == ("tesseract", True, False))
    return ok


def test_model_not_configured():
    """Режим с моделью без настроенной модели: распознавание, а не тишина и не падение."""
    bare = load_settings(PIPELINE_READING_MODE="tesseract", PIPELINE_OCR=None,
                         PIPELINE_MODEL=None, PIPELINE_MODEL_URL=None, **{KEY: None})
    ok = check("модель не настроена — режим понижается до распознавания",
               bare.reading_flags("model") == ("tesseract", True, False),
               str(bare.reading_flags("model")))
    ok &= check("понижение видно и отдельно", bare.reading_mode("model") == "tesseract")
    own = load_settings(PIPELINE_READING_MODE="tesseract", PIPELINE_OCR=None, PIPELINE_MODEL=None,
                        PIPELINE_MODEL_URL=LOCAL_MODEL, **{KEY: None})
    ok &= check("своя модель на своём железе работает без ключа",
                own.reading_flags("model") == ("model", True, True),
                str(own.reading_flags("model")))
    return ok


def test_named_by_what_ran():
    """Без выбора режим называется по тому, что включено: в протоколе стоит, чем читали."""
    layer = load_settings(PIPELINE_READING_MODE=None, PIPELINE_OCR="0", PIPELINE_MODEL="0", **{KEY: None})
    ok = check("флаги выключили распознавание — режим «только слой»",
               layer.reading_flags(None) == ("layer", False, False),
               str(layer.reading_flags(None)))
    with_model = load_settings(PIPELINE_READING_MODE="model", PIPELINE_OCR=None, PIPELINE_MODEL=None,
                               **{KEY: "ключ-для-проверки"})
    ok &= check("сервис настроен на модель — режим «модель»",
                with_model.reading_flags(None) == ("model", True, True),
                str(with_model.reading_flags(None)))
    ok &= check("название режима по флагам", layer.mode_of(False, False) == "layer"
                and layer.mode_of(True, False) == "tesseract" and layer.mode_of(True, True) == "model")
    return ok


def test_readiness_names_the_mode():
    """Отчёт готовности называет способ чтения: без него доля пустых страниц не читается."""
    docs = [{"file_id": "F1", "extension": ".pdf", "stage": "RD", "section": "KR"}]
    pages = [{"text": "", "text_source": "NONE", "kind": "SCAN_NO_TEXT"},
             {"text": "бетон В25", "text_source": "TEXT_LAYER", "kind": "TEXT"}]
    rep = readiness.report(docs, pages, ocr_enabled=False, model_enabled=False, reading_mode="layer")
    ok = check("режим записан в отчёт", rep["reading_mode"] == "layer")
    ok &= check("способ чтения назван словами",
                readiness.mode_line(rep) == "только текстовый слой (layer)", readiness.mode_line(rep))
    note = " ".join(readiness.notes(rep))
    ok &= check("предупреждение объясняет пустые страницы выбором, а не сбоем",
                "только текстовым слоем" in note, note)
    with_model = readiness.report(docs, pages, ocr_enabled=True, model_enabled=True,
                                  reading_mode="model", model_name="проверочная-модель")
    ok &= check("модель названа в отчёте",
                "проверочная-модель" in readiness.mode_line(with_model), readiness.mode_line(with_model))
    ok &= check("старый отчёт без режима не ломает показ",
                readiness.mode_line({"reading_mode": None}) == "не записан")
    ok &= check("способ чтения попадает в строки протокола",
                any("способ чтения" in line for line in readiness.show(rep)))
    return ok


def test_cost_is_observed():
    """Время и ответы модели — наблюдение в отчёте, а не ограничитель расхода."""
    pages = [
        {"text": "ведомость", "text_source": "UNION", "ms": 3800, "cost_usd": 0.0025,
         "model_call": {"model": "проверочная-модель", "ms": 2600, "cost_usd": 0.0025}},
        {"text": "", "text_source": "NONE", "ms": 1200, "cost_usd": 0.0265,
         "model_call": {"model": "проверочная-модель", "ms": 9000, "cost_usd": 0.0265,
                        "looped": True, "error": "ответ зациклился"}},
    ]
    rep = readiness.report([], pages, ocr_enabled=True, model_enabled=True,
                           reading_mode="model", model_name="проверочная-модель")
    ok = check("время чтения посчитано", rep["read_seconds"] == 5.0, str(rep["read_seconds"]))
    ok &= check("вызовы модели посчитаны", rep["model_calls"] == 2 and rep["model_answered"] == 1,
                f'{rep["model_calls"]}/{rep["model_answered"]}')
    ok &= check("зациклившийся ответ виден отдельно", rep["model_looped"] == 1)
    ok &= check("время и стоимость модели сложены",
                rep["model_seconds"] == 11.6 and rep["model_cost_usd"] == 0.029,
                f'{rep["model_seconds"]} с, ${rep["model_cost_usd"]}')
    line = readiness.cost_line(rep)
    ok &= check("наблюдение читается строкой", "зациклилась 1" in line and "$0.029" in line, line)
    ok &= check("без модели строка короткая",
                readiness.cost_line(readiness.report([], [{"text": "a", "ms": 900}])) == "чтение заняло 0.9 с")
    return ok


def test_model_silence_is_noticed():
    """Молчание модели заметно, но не назойливо: числа всегда, уведомление — с трети вызовов (#71)."""
    base = {"pages": 100, "share_without_text": 0.0, "pages_without_text": 0, "stage_unknown": 0,
            "section_other": 0, "unsupported": 0, "unsupported_by_extension": {}, "pages_low_quality": 0,
            "read_seconds": 10.0}
    quiet = readiness.notes({**base, "model_calls": 30, "model_answered": 28})
    loud = readiness.notes({**base, "model_calls": 30, "model_answered": 18})
    ok = check("два неответа из тридцати инспектора не дёргают", quiet == [], str(quiet))
    ok &= check("треть неотвеченных вызовов — уже уведомление",
                len(loud) == 1 and "не ответила на 12" in loud[0], str(loud))
    ok &= check("без модели строки нет", readiness.notes(base) == [])
    line = readiness.cost_line({**base, "model_calls": 30, "model_answered": 18, "model_looped": 4,
                                "model_seconds": 90.0, "model_cost_usd": 0.02})
    ok &= check("числа ответов есть всегда, даже когда уведомления нет",
                "ответила 18" in line and "зациклилась 4" in line, line)
    return ok


def test_flag_reaches_the_page():
    """Флаг доезжает до чтения страницы, а не остаётся в отчёте."""
    from pipeline import reading

    saved = (reading.CACHE, reading.read_text_layer, reading.render, reading.read_tesseract)
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        reading.CACHE = tmp
        # страница без текстового слоя с картинкой — это скан: на нём и решается,
        # звать ли распознавание
        reading.read_text_layer = lambda doc, page_no: {
            "text": "", "words": [], "images": 1, "rotation": 0, "coords_rotated": True,
            "width_pt": 595.0, "height_pt": 842.0}
        reading.render = lambda doc, page_no, out_png, dpi=300, max_px=None: out_png
        reading.read_tesseract = lambda png: {"text": "ведомость отделки",
                                              "words": [{"t": "ведомость", "bbox": [0, 0, 1, 1],
                                                         "source": "TESSERACT"}]}
        try:
            on = reading.read_page(object(), 1, "a" * 64, use_model=False, use_ocr=True)
            off = reading.read_page(object(), 1, "b" * 64, use_model=False, use_ocr=False)
            ok &= check("с распознаванием страница прочитана", on["text_source"] == "TESSERACT",
                        on["text_source"])
            ok &= check("без распознавания текста у скана нет", off["text_source"] == "NONE"
                        and not off["text"], off["text_source"])
            ok &= check("пропуск распознавания записан в странице", off["ocr_skipped"] is True)
            ok &= check("прочитанное записано в кеш",
                        reading.cache_get("a" * 64, 1, "read")["text"] == "ведомость отделки")
        finally:
            reading.CACHE, reading.read_text_layer, reading.render, reading.read_tesseract = saved
    return ok


def test_renders_are_dropped():
    """Картинка страницы стирается после чтения: иначе каталог растёт на гигабайты (#67)."""
    import pymupdf

    from pipeline import reading

    ok = True
    saved = (reading.CACHE, reading.read_tesseract, reading.read_model)
    with tempfile.TemporaryDirectory() as tmp:
        renders = os.path.join(tmp, "renders")
        reading.CACHE = os.path.join(tmp, "cache")
        # скан: страница с картинкой и без текстового слоя — на ней работают и распознавание,
        # и модель, то есть рисуются обе картинки
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.draw_rect(pymupdf.Rect(20, 20, 575, 822), color=(0, 0, 0), fill=(0.9, 0.9, 0.9))
        reading.read_tesseract = lambda png: {"text": "ведомость отделки" if os.path.exists(png) else "",
                                              "words": []}
        reading.read_model = lambda png, model=None, timeout=180, url=None: {
            "text": "ведомость отделки" if os.path.exists(png) else "", "model": "проверочная",
            "ms": 1, "cost_usd": 0.0}
        try:
            got = reading.read_page(doc, 1, "c" * 64, use_model=True, use_ocr=True, work_dir=renders)
            ok &= check("страница прочитана распознаванием и моделью",
                        got["sources"] == ["TESSERACT", "MODEL"], str(got["sources"]))
            left = sorted(os.listdir(renders)) if os.path.isdir(renders) else []
            ok &= check("картинок после чтения не осталось", left == [], f"осталось: {left}")
            # тот же вызов по готовому кешу: модель зовётся второй раз, картинка снова стирается
            stale = reading.cache_get("c" * 64, 1, "read")
            stale["sources"].remove("MODEL")
            stale.pop("model_call", None)
            reading.cache_put("c" * 64, 1, "read", stale)
            reading.read_model = lambda png, model=None, timeout=180, url=None: {
                "text": "", "model": "проверочная", "ms": 2, "cost_usd": 0.004, "error": "timeout"}
            got = reading.read_page(doc, 1, "c" * 64, use_model=True, use_ocr=True, work_dir=renders)
            left = sorted(os.listdir(renders)) if os.path.isdir(renders) else []
            ok &= check("по готовому кешу — тоже", left == [], f"осталось: {left}")
            # отказ модели по готовому кешу тоже виден: иначе отчёт готовности не считает
            # ни вызовов, ни денег на повторном разборе (#54)
            ok &= check("отказ модели записан в страницу и деньги посчитаны",
                        (got.get("model_call") or {}).get("error") == "timeout" and got["cost_usd"] >= 0.004,
                        str(got.get("model_call")))
        finally:
            reading.CACHE, reading.read_tesseract, reading.read_model = saved
            doc.close()
    return ok


def test_ocr_image_limit():
    """Предел растра для распознавания: плоский на A4, от размера листа на крупном (#105).

    Замер 24.09 на тринадцати сканах без слоя стенда: поднимать предел всем нельзя — на A4
    точных значений становится меньше. Выигрыш только там, где плоского потолка не хватает
    на разрешение: лист 1165 мм при 3500 px — это 76 dpi.
    """
    from pipeline import reading

    ok = check("A4 остаётся на плоском потолке", reading.ocr_max_px(595, 842) == reading.OCR_MAX_PX)
    ok &= check("A2 остаётся на плоском потолке", reading.ocr_max_px(1684, 1191) == reading.OCR_MAX_PX)
    big = reading.ocr_max_px(3303, 2835)
    ok &= check("лист 1165 мм поднимается до 100 dpi",
                big == round(3303 / 72 * reading.OCR_MIN_DPI), str(big))
    ok &= check("выше потолка не поднимается", reading.ocr_max_px(20000, 500) == reading.OCR_BIG_PX)
    ok &= check("без размера страницы — плоский потолок", reading.ocr_max_px() == reading.OCR_MAX_PX)
    return ok


def test_model_image_limit():
    """Предел картинки для модели: скан без слоя получает больше пикселей, чертёж — прежние.

    Плоские 2000 пикселей по длинной стороне — это 170 dpi на A4 и 43 dpi на A0. На листе A0
    без текстового слоя qwen3.6-27b при таком уменьшении возвращала 196 символов, только
    заголовки разделов; при пределе от размера листа прочитала таблицу материалов целиком
    (#105). Крупным чертежам со слоем предел не поднимается: замер показал, что там модель
    на большой картинке переписывает меньше, а значения и так берутся из слоя.
    """
    from pipeline import reading

    class Rect:
        def __init__(self, w, h):
            self.width, self.height = w, h

    class Page:
        def __init__(self, long_mm):
            pt = long_mm / 25.4 * 72
            self.rect = Rect(pt * 0.7, pt)

    ok = True
    ok &= check("A4 без слоя — как было", reading.page_max_px(Page(297), "SCAN_NO_TEXT") <= 2000,
                str(reading.page_max_px(Page(297), "SCAN_NO_TEXT")))
    ok &= check("A1 без слоя — больше пикселей", reading.page_max_px(Page(841), "SCAN_NO_TEXT") == 4000)
    ok &= check("A0 без слоя — упирается в потолок", reading.page_max_px(Page(1189), "SCAN_NO_TEXT") == 4000)
    ok &= check("чертёж со слоем — предел прежний", reading.page_max_px(Page(1189), "DRAWING") == 2000)
    ok &= check("страница-невидимка не даёт нуля", reading.page_max_px(Page(20), "SCAN_NO_TEXT") >= 1600)
    return ok


def main():
    ok = True
    for title, fn in (("Выбор инспектора", test_choice_wins),
                      ("Модель не настроена", test_model_not_configured),
                      ("Режим называется по тому, что работало", test_named_by_what_ran),
                      ("Отчёт готовности", test_readiness_names_the_mode),
                      ("Время и стоимость как наблюдение", test_cost_is_observed),
                      ("Молчание модели заметно", test_model_silence_is_noticed),
                      ("Флаг доходит до страницы", test_flag_reaches_the_page),
                      ("Картинки страниц не остаются", test_renders_are_dropped),
                      ("Предел картинки для модели", test_model_image_limit),
                      ("Предел растра для распознавания", test_ocr_image_limit)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
