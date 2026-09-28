"""Готовность объекта к проверке: что прочиталось и что осталось неопознанным. Задача #39.

Оценка идёт на объекте, которого система не видела. Известные объекты читаются из
прогретого кеша, где распознавание и модель были включены, а на стенде они выключены:
без этого отчёта разница видна только по пустым результатам правил. Здесь собраны числа,
по которым сразу понятно, на что опирается вывод по объекту:

- страницы без прочитанного текста: у скана без распознавания правила не видят ничего;
- файлы без стадии и без раздела: в сравнение стадий такой файл не попадает;
- файлы форматов, которые не читает ни один разбор (`registry.SUPPORTED_EXT`);
- страницы, размеченные чтением как низкого качества.

Отчёт складывается в `build/<объект>/readiness.json` и попадает в протокол процесса.
"""
import collections

# источники текста страницы (pipeline/reading.py): слой документа, распознавание, модель
OCR_SOURCES = ("TESSERACT", "UNION")
MODEL_SOURCES = ("MODEL", "UNION")

# способы чтения объекта (#54): их выбирают при загрузке, и от выбора зависит,
# что вообще увидят правила
MODE_LABELS = {
    "layer": "только текстовый слой",
    "tesseract": "слой и распознавание сканов",
    "model": "слой, распознавание и модель на сканах без текста и чертежах без слоя",
}


def _files(n):
    """«у 1 файла», «у 7 файлов»: родительный падеж после предлога."""
    return f"{n} файла" if n % 10 == 1 and n % 100 != 11 else f"{n} файлов"


def _pages(n):
    """«на 1 странице», «на 7 страницах»."""
    return f"{n} странице" if n % 10 == 1 and n % 100 != 11 else f"{n} страницах"


def _times(n):
    """«вызвана 1 раз», «вызвана 2 раза», «вызвана 5 раз»."""
    return f"{n} раза" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else f"{n} раз"


def _share(part, whole):
    return round(part / whole, 4) if whole else 0.0


def _reading_cost(pages):
    """Во что обошлось чтение: время страниц и то, как отвечала модель.

    Наблюдение, а не ограничитель (#54): в бою модель своя, вызовы не оплачиваются, и
    заградитель по расходу мешал бы больше, чем помогал. Но знать, сколько времени ушло
    и сколько ответов модель завалила, нужно: по этому выбирается способ чтения.
    """
    calls = [p["model_call"] for p in pages if p.get("model_call")]
    answered = [c for c in calls if not c.get("error")]
    return {
        "read_seconds": round(sum(p.get("ms") or 0 for p in pages) / 1000, 1),
        "model_calls": len(calls),
        "model_answered": len(answered),
        "model_looped": sum(1 for c in calls if c.get("looped")),
        "model_seconds": round(sum(c.get("ms") or 0 for c in calls) / 1000, 1),
        "model_cost_usd": round(sum(p.get("cost_usd") or 0 for p in pages), 4),
    }


def report(documents, pages, ocr_enabled=None, model_enabled=None, reading_mode=None, model_name=None):
    """Числа готовности по реестру и постраничному индексу объекта.

    `reading_mode` и `model_name` — чем объект читали (#54). Они записываются рядом с
    числами, потому что доля страниц без текста без них не читается: у «только слоя»
    половина пустых страниц — это выбор инспектора, а у «модели» — сбой.
    """
    docs = [d for d in documents if not d.get("duplicate_of")]
    unsupported = [d for d in docs if d.get("status") == "UNSUPPORTED_FORMAT"]
    readable = [d for d in docs if d.get("status") != "UNSUPPORTED_FORMAT"]
    by_source = collections.Counter(p.get("text_source") for p in pages)
    without_text = sum(1 for p in pages if not (p.get("text") or "").strip())
    low_quality = sum(1 for p in pages if p.get("quality") and p["quality"] != "OK")
    return {
        **_reading_cost(pages),
        "files": len(readable),
        "unsupported": len(unsupported),
        "unsupported_by_extension": dict(collections.Counter(d["extension"] for d in unsupported)),
        "stage_unknown": sum(1 for d in readable if d.get("stage") in (None, "UNKNOWN")),
        "section_other": sum(1 for d in readable if d.get("section") in (None, "OTHER")),
        "pages": len(pages),
        "pages_without_text": without_text,
        "share_without_text": _share(without_text, len(pages)),
        "pages_low_quality": low_quality,
        "by_text_source": {k: v for k, v in sorted(by_source.items(), key=lambda kv: -kv[1]) if k},
        "ocr_enabled": ocr_enabled,
        "model_enabled": model_enabled,
        "reading_mode": reading_mode,
        "model_name": model_name,
        "ocr_pages": sum(by_source[s] for s in OCR_SOURCES),
        "model_pages": sum(by_source[s] for s in MODEL_SOURCES),
    }


# Доля неотвеченных вызовов, с которой молчание модели стоит уведомления
MODEL_SILENCE_SHARE = 1 / 3


def notes(rep):
    """Что из отчёта требует внимания, словами инспектора и оператора стенда."""
    out = []
    if rep["pages"] and rep["share_without_text"] >= 0.2:
        line = (f'страниц без прочитанного текста {rep["share_without_text"] * 100:.0f} % '
                f'({rep["pages_without_text"]} из {rep["pages"]})')
        if rep.get("ocr_enabled") is False:
            # объект читали только текстовым слоем: на сканах правила молчат не потому,
            # что значения нет, а потому, что страницу никто не читал (#54)
            line += (": объект прочитан только текстовым слоем, распознавание не включалось — "
                     "перезагрузите объект со способом чтения «слой и распознавание»")
        elif rep.get("model_enabled") is False and rep.get("ocr_enabled"):
            line += ": распознавание не разобрало эти страницы, помочь может способ чтения с моделью"
        out.append(line)
    if rep["stage_unknown"]:
        out.append(f'стадия не определена у {_files(rep["stage_unknown"])}: '
                   f'в сравнение проектной и рабочей стадии они не попадут')
    if rep["section_other"]:
        out.append(f'раздел не определён у {_files(rep["section_other"])}: '
                   f'правила с разделом-источником их не прочитают')
    if rep["unsupported"]:
        out.append(f'формат не читает ни один разбор у {_files(rep["unsupported"])} '
                   f'{rep["unsupported_by_extension"]}')
    if rep["pages_low_quality"]:
        out.append(f'чтение отметило низкое качество на {_pages(rep["pages_low_quality"])}')
    # Сбой модели: уведомление поднимается только когда молчание существенное — на трети
    # вызовов и больше. Один-два неответа видны числом в блоке готовности и в протоколе,
    # и дёргать ими инспектора незачем (#71).
    silent = (rep.get("model_calls") or 0) - (rep.get("model_answered") or 0)
    if silent and silent >= MODEL_SILENCE_SHARE * rep["model_calls"]:
        out.append(f'модель не ответила на {_pages(silent)} из {rep["model_calls"]}: '
                   f'они прочитаны только распознаванием')
    return out


def show(rep):
    """Строки для командной строки и протокола."""
    lines = [
        f'файлов {rep["files"]}, страниц {rep["pages"]}',
        f'без прочитанного текста {rep["pages_without_text"]} ({rep["share_without_text"] * 100:.1f} %), '
        f'источники текста {rep["by_text_source"]}',
        f'стадия не определена у {rep["stage_unknown"]}, раздел — у {rep["section_other"]}, '
        f'формат не читается у {rep["unsupported"]}',
        f'способ чтения: {mode_line(rep)}',
        f'распознавание {_flag(rep.get("ocr_enabled"))}, модель {_flag(rep.get("model_enabled"))}',
        cost_line(rep),
    ]
    return lines + [f"внимание: {n}" for n in notes(rep)]


def cost_line(rep):
    """Во что обошлось чтение: время и ответы модели. Наблюдение для журнала."""
    line = f'чтение заняло {rep.get("read_seconds", 0)} с'
    if rep.get("model_calls"):
        line += (f', модель вызвана {_times(rep["model_calls"])}, ответила {rep.get("model_answered", 0)}'
                 f', зациклилась {rep.get("model_looped", 0)}'
                 f', заняла {rep.get("model_seconds", 0)} с, ${rep.get("model_cost_usd", 0)}')
    return line


def mode_line(rep):
    """Способ чтения словами: «слой и распознавание сканов (tesseract), модель Qwen…»."""
    mode = rep.get("reading_mode")
    if not mode:
        return "не записан"
    line = f'{MODE_LABELS.get(mode, mode)} ({mode})'
    if rep.get("model_name"):
        line += f', модель {rep["model_name"]}'
    return line


def _flag(value):
    return "не задано" if value is None else ("включено" if value else "выключено")
