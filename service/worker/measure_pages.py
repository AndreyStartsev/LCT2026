"""Замер скорости чтения PDF: страниц в минуту против п. 2 и 3 раздела 11 ТЗ.

ТЗ: распознавание PDF до 100 страниц — не больше 3 минут (±30 с), до 500 страниц — не больше
10 минут (±60 с). Производительность организатор мерит с видеокартой (Р-98), то есть в режиме
с моделью: в нём чтение и берёт порог 0,95 Character Accuracy. Цифра Tesseract без модели
для этих пунктов не годится.

Страницы читаются тем же путём, что в разборе воркера: `pages.build` с флагами способа чтения
и числом процессов воркера. Кеш чтения на каждый прогон — пустой временный каталог, поэтому
каждое чтение холодное, а кеш стенда не трогается. Запуск — в контейнере воркера, где те же
Tesseract, настройки и адрес модели:

  docker compose -f docker-compose.yml -f deploy/docker-compose.release.yml exec -T worker \
    python -m service.worker.measure_pages /input/bench-100/скан.pdf /input/bench-500/скан.pdf

Время шага разбора целиком (угол листа, экспликации, проход по чертежам) этот замер не
показывает — его даёт журнал воркера при загрузке того же файла объектом (deploy/RELEASE.md).
"""
import argparse
import collections
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.parse

from service.worker import settings

# Нормы п. 2 и 3 раздела 11 ТЗ: (страниц не больше, секунд, допуск)
NORMS = ((100, 180, 30), (500, 600, 60))


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))]


def verdict(pages, seconds):
    """Вывод против нормы ТЗ. Сценарии ТЗ — до 500 страниц; больший файл пересчитывается на 500."""
    for limit, norm, tolerance in NORMS:
        if pages <= limit:
            break
    else:
        limit, norm, tolerance = NORMS[-1]
        seconds = seconds * limit / pages
    scenario = f"до {limit} страниц — {norm // 60} мин (±{tolerance} с)"
    if seconds <= norm:
        word = "укладывается"
    elif seconds <= norm + tolerance:
        word = "в допуске"
    else:
        word = "НЕ укладывается"
    return {"scenario": scenario, "seconds_for_norm": round(seconds, 1), "norm_s": norm,
            "tolerance_s": tolerance, "verdict": word}


def measure(path, mode, use_ocr, use_model, model, workers, max_pages, stage):
    """Один холодный прогон файла: пустой кеш чтения, тот же pages.build, что у разбора."""
    cache = tempfile.mkdtemp(prefix="measure-pages-")
    # кеш задаётся и окружением, и в уже загруженном модуле: процессы чтения при запуске
    # через spawn читают окружение, при fork наследуют модуль
    os.environ["PIPELINE_CACHE"] = cache
    from pipeline import config, pages, reading
    reading.CACHE = cache
    object_id = "MEASURE-PAGES"
    config.register_object(object_id, os.path.dirname(os.path.abspath(path)))
    import pymupdf
    with pymupdf.open(path) as probe:
        total_pages = probe.page_count
    document = {"file_id": "M0001", "relative_path": os.path.basename(path), "extension": ".pdf",
                "sha256": sha256_of(path), "stage": stage, "section": None, "duplicate_of": None}
    started = time.monotonic()

    def progress(done):
        elapsed = time.monotonic() - started
        print(f"   {done} стр., {elapsed:.0f} с, {done / elapsed * 60:.1f} стр./мин", flush=True)

    try:
        if max_pages and max_pages < total_pages:
            # урезанный файл — только для проверки самого замера, вывод против нормы не делается
            with pymupdf.open(path) as src, pymupdf.open() as cut:
                cut.insert_pdf(src, from_page=0, to_page=max_pages - 1)
                trimmed = os.path.join(cache, os.path.basename(path))
                cut.save(trimmed)
            config.register_object(object_id, cache)
            document["sha256"] = sha256_of(trimmed)
            started = time.monotonic()
        rows = pages.build(object_id, [document], use_model=use_model, model=model, use_ocr=use_ocr,
                           workers=workers, progress=progress)
        seconds = time.monotonic() - started
    finally:
        shutil.rmtree(cache, ignore_errors=True)

    calls = [r["model_call"] for r in rows if r.get("model_call")]
    call_ms = [c["ms"] for c in calls if c.get("ms") is not None]
    page_ms = [r["ms"] for r in rows if r.get("ms") is not None]
    n = len(rows)
    result = {
        "file": os.path.basename(path),
        "pages": n,
        "pages_in_file": total_pages,
        "seconds": round(seconds, 1),
        "pages_per_min": round(n / seconds * 60, 1) if seconds else None,
        "by_kind": dict(collections.Counter(r.get("kind") for r in rows)),
        "by_source": dict(collections.Counter(r.get("text_source") for r in rows)),
        "page_ms_p50": percentile(page_ms, 0.5),
        "page_ms_p95": percentile(page_ms, 0.95),
        "model_calls": len(calls),
        "model_ms_p50": percentile(call_ms, 0.5),
        "model_ms_p95": percentile(call_ms, 0.95),
        "model_ms_max": max(call_ms) if call_ms else None,
        "model_looped": sum(1 for c in calls if c.get("looped")),
        "model_errors": sum(1 for c in calls if c.get("error")),
        "model_fallback": sum(1 for c in calls if c.get("fallback")),
        "tokens_out": sum(c.get("tokens_out") or 0 for c in calls),
        "read_errors": sum(1 for r in rows if r.get("error")),
    }
    if not (max_pages and max_pages < total_pages):
        result["tz"] = verdict(n, seconds)
    return result


def main():
    ap = argparse.ArgumentParser(description="замер скорости чтения PDF против п. 2 и 3 раздела 11 ТЗ")
    ap.add_argument("files", nargs="+", help="PDF внутри контейнера, например /input/bench-100/скан.pdf")
    ap.add_argument("--mode", choices=settings.READING_MODES,
                    help="способ чтения; по умолчанию — способ сервиса (в поставке — model)")
    ap.add_argument("--runs", type=int, default=1,
                    help="холодных прогонов на файл. Повтор того же файла может попасть в кеш "
                         "префиксов сервера модели — для повторов лучше разные файлы того же размера")
    ap.add_argument("--workers", type=int, default=settings.PAGE_WORKERS,
                    help="процессов чтения; по умолчанию как у разбора (PIPELINE_PAGE_WORKERS)")
    ap.add_argument("--max-pages", type=int, help="читать только первые N страниц — проверка самого замера")
    ap.add_argument("--stage", default="ID", help="стадия документа в реестре (ИД — сканы)")
    ap.add_argument("--out", help="записать числа в JSON")
    args = ap.parse_args()

    mode, use_ocr, use_model = settings.reading_flags(args.mode)
    if args.mode and mode != args.mode:
        sys.exit(f"способ «{args.mode}» недоступен: модель не настроена (адрес или ключ), "
                 f"сервис читал бы как «{mode}»")
    route, why, model = None, None, None
    if use_model:
        route, why = settings.model_route(wait_s=120)
        if route is None:
            sys.exit(f"модель не отвечает ({why}), запасного адреса нет: замер режима с моделью невозможен")
        from pipeline import reading
        model = settings.model_for(None) or reading.model_name()
    host = urllib.parse.urlparse(settings.MODEL_URL).netloc if use_model else None
    print(f"способ чтения {mode}; процессов {args.workers}, ядер {os.cpu_count()}"
          + (f"; модель {model} на {host}" + (f", ЗАПАСНОЙ АДРЕС: {why}" if route == "fallback" else "")
             if use_model else ""))

    results = []
    for path in args.files:
        for run in range(1, args.runs + 1):
            print(f"{os.path.basename(path)}, прогон {run} из {args.runs}", flush=True)
            got = measure(path, mode, use_ocr, use_model, model, args.workers, args.max_pages, args.stage)
            got["run"] = run
            results.append(got)
            line = (f"  {got['pages']} стр. за {got['seconds']:.0f} с — {got['pages_per_min']} стр./мин; "
                    f"источники {got['by_source']}")
            if got["model_calls"]:
                line += (f"; модель {got['model_calls']} вызовов, медиана {got['model_ms_p50']} мс, "
                         f"95-й процентиль {got['model_ms_p95']} мс, зацикливаний {got['model_looped']}, "
                         f"отказов {got['model_errors']}, через запасной адрес {got['model_fallback']}")
            print(line)
            if got.get("tz"):
                tz = got["tz"]
                print(f"  ТЗ, {tz['scenario']}: {tz['seconds_for_norm']:.0f} с — {tz['verdict']}")
            elif args.max_pages:
                print("  файл урезан --max-pages: вывод против нормы ТЗ не делается")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "mode": mode, "model": model,
                       "model_host": host, "route": route, "workers": args.workers, "cpus": os.cpu_count(),
                       "results": results}, f, ensure_ascii=False, indent=1)
    bad = [r for r in results if (r.get("tz") or {}).get("verdict") == "НЕ укладывается"]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
