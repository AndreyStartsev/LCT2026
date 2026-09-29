"""Шаги обработки процесса: разбор, сравнение, протокол. Задача #32.

Каждый шаг воркер запускает отдельным процессом:

    python -m service.worker.steps parse <process_id>

Так у шага свой таймаут, который можно выдержать, убив процесс, и свой каталог
сборки конвейера: переменную PIPELINE_OUT выставляет воркер, и два процесса одного
объекта не пишут в одни файлы. Кеш конвейера общий: он адресован SHA-256
содержимого и от процесса не зависит.

Шаги повторяют команды `python -m pipeline.cli`: registry, pages, sheets — разбор;
rules — сравнение; submit — протокол.
"""
import argparse
import collections
import hashlib
import io
import json
import os
import sys

from psycopg.types.json import Jsonb

from service.worker import infra, paths, settings

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STAGES = ("PD", "RD", "ID")


def files_dir(process_id):
    return os.path.join(settings.WORK_DIR, process_id, "files")


def load_process(conn, process_id):
    row = conn.execute(
        "select p.*, o.name as object_name from processes p join objects o on o.id = p.object_id where p.id = %s",
        (process_id,),
    ).fetchone()
    if row is None:
        raise SystemExit(f"процесс {process_id} не найден")
    return row


def register(process):
    """Регистрирует загруженную папку как объект конвейера."""
    from pipeline import config as pipeline_config
    root = files_dir(str(process["id"]))
    pipeline_config.register_object(process["object_id"], root, process["object_name"])
    return root


def _load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def out_path(object_id, name):
    from pipeline.config import OUT
    return os.path.join(OUT, object_id, name)


def rooms_index(obj):
    """Где встречается помещение: номер → документы (#82). Индекс кладётся в отчёт протокола,
    чтобы контекст находки не читал рабочий каталог воркера. Разбор помещений — прежний
    (pipeline/rooms.py), фильтр ложных связей — в API: короткие номера, «клубок», редакции."""
    from pipeline import cli

    path = out_path(obj, "rooms.jsonl")
    if not os.path.exists(path):
        return None
    index = {}
    for room in cli.read_jsonl(path):
        files = {s["file_id"] for s in room.get("seen_on") or [] if s.get("file_id")}
        if files:
            index.setdefault(str(room["number"]), set()).update(files)
    # пустой индекс — разбор помещений не нашёл, это не то же, что «индекса нет»
    return {number: sorted(files) for number, files in sorted(index.items())}


def text_key(sha256):
    return f"texts/{sha256}.jsonl"


def store_page_texts(documents, rows):
    """Прочитанный текст страниц — в хранилище, по одному файлу на документ (#52).

    Инспектору нужно видеть, что система прочитала: на сканах текст даёт распознавание,
    и по нему принимаются решения. Рабочий каталог воркера API не виден, поэтому текст
    едет туда же, куда картинки страниц-доказательств. Ключ — SHA-256 содержимого:
    тот же файл в другом процессе выгружать заново не нужно.
    """
    by_sha = {d["file_id"]: d.get("sha256") for d in documents if d.get("sha256")}
    pages = collections.defaultdict(list)
    for r in rows:
        sha = by_sha.get(r["file_id"])
        if sha:
            pages[sha].append(r)
    client, stored = infra.storage(), 0
    for sha, items in pages.items():
        key = text_key(sha)
        try:
            client.stat_object(settings.S3_BUCKET, key)
            continue
        except Exception:
            pass
        body = "".join(json.dumps({"p": r["pdf_page_number"], "s": r.get("text_source"),
                                   "k": r.get("kind"), "q": r.get("quality"),
                                   "t": r.get("text") or ""}, ensure_ascii=False) + "\n"
                       for r in sorted(items, key=lambda r: r["pdf_page_number"])).encode("utf-8")
        client.put_object(settings.S3_BUCKET, key, io.BytesIO(body), len(body),
                          content_type="application/x-ndjson")
        stored += 1
    return stored


# ---------------------------------------------------------------- разбор

def materialize(conn, process):
    """Выкладывает принятые файлы процесса из хранилища по их путям внутри папки."""
    pid = str(process["id"])
    rows = conn.execute(
        "select relative_path, file_hash, size_bytes from files where process_id = %s and status = 'ACCEPTED'",
        (pid,),
    ).fetchall()
    root = files_dir(pid)
    wanted = set()
    client = infra.storage()
    for i, row in enumerate(rows, 1):
        # длинные имена папок пакета организатора не помещаются в предел файловой
        # системы контейнера и укорачиваются на диске (service/worker/paths.py)
        dest = os.path.join(root, paths.disk_path(row["relative_path"]))
        wanted.add(os.path.normpath(dest))
        if not (os.path.exists(dest) and os.path.getsize(dest) == row["size_bytes"]):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            client.fget_object(settings.S3_BUCKET, infra.blob_key(row["file_hash"]), dest)
        if i % 10 == 0 or i == len(rows):
            infra.progress(pid, "parse", "Файлы выкладываются из хранилища", i, len(rows))
    # файлы, которые заменили или отклонили после прошлого разбора, убираются
    for dirpath, _, names in os.walk(root):
        for name in names:
            path = os.path.normpath(os.path.join(dirpath, name))
            if path not in wanted:
                os.remove(path)
    return len(rows)


# Отдельная электронная подпись к документу — не документ стадии: её отклонение не делает
# стадию загруженной частично. Подпись в сервисе не проверяется, сам документ принимается.
SIGNATURE_EXTENSIONS = (".sig", ".p7s", ".sgn")


def stage_file_counts(conn, pid):
    """Принятые и отклонённые файлы по стадиям. Стадию отклонённого файла угадываем по пути,
    как делает реестр для незнакомых файлов; отдельные подписи в счёт не идут."""
    from pipeline.registry import guess_stage
    rows = conn.execute(
        "select relative_path, status, doc_stage, extension, reject_code from files where process_id = %s", (pid,)
    ).fetchall()
    counts = {st: {"accepted": 0, "rejected": 0, "signatures": 0, "reject_codes": {}} for st in STAGES}
    for r in rows:
        stage = r["doc_stage"] if r["status"] == "ACCEPTED" and r["doc_stage"] else guess_stage(r["relative_path"])
        stages = ("RD", "ID") if stage == "RD_ID_MIXED" else (stage,)
        signature = (r["extension"] or os.path.splitext(r["relative_path"])[1]).lower() in SIGNATURE_EXTENSIONS
        for st in stages:
            if st not in STAGES:
                continue
            if r["status"] == "ACCEPTED":
                counts[st]["accepted"] += 1
            elif signature:
                counts[st]["signatures"] += 1
            else:
                counts[st]["rejected"] += 1
                code = r["reject_code"] or "REJECTED"
                counts[st]["reject_codes"][code] = counts[st]["reject_codes"].get(code, 0) + 1
    return counts


def upload_status(conn, pid):
    """Статусы загрузки по стадиям и сценарий проверки по ТЗ, раздел 9.1–9.2.

    Стадия загружена частично, если часть её файлов принята, а часть отклонена
    («5 из 15 файлов ИД» в ТЗ). Если не принят ни один файл, стадии в проверке нет:
    она MISSING, а отклонённые файлы видны в таблице комплектности.
    """
    counts = stage_file_counts(conn, pid)
    statuses = []
    for st in STAGES:
        present, broken = counts[st]["accepted"], counts[st]["rejected"]
        if present and broken:
            statuses.append(f"{st}_PARTIAL")
        elif present:
            statuses.append(f"{st}_UPLOADED")
        else:
            statuses.append(f"{st}_MISSING")
    have = tuple(st for st in STAGES if counts[st]["accepted"])
    if any(s.endswith("_PARTIAL") for s in statuses):
        scenario = "PARTIALLY_LOADED"
    elif len(have) == 3:
        scenario = "FULL"
    elif have == ("PD", "RD"):
        scenario = "PD_RD_ONLY"
    elif have == ("PD", "ID"):
        scenario = "PD_ID_ONLY"
    elif have == ("RD", "ID"):
        scenario = "RD_ID_ONLY"
    elif len(have) == 1:
        scenario = "SINGLE_ONLY"
    else:
        scenario = None
    return statuses, scenario


def manual_revisions(conn, pid):
    """Редакции, которые инспектор назвал актуальными руками (#10): {file_id: True}."""
    rows = conn.execute(
        "select file_id from files where process_id = %s and revision_manual is true and file_id is not null", (pid,)
    ).fetchall()
    return {r["file_id"]: True for r in rows}


def link_predecessors(conn, pid, predecessors):
    """predecessor_id таблицы файлов — строка предыдущей редакции того же процесса (ТЗ 10)."""
    for file_id, before in predecessors.items():
        conn.execute(
            """update files set predecessor_id = prev.id from files prev
               where files.process_id = %s and files.file_id = %s and prev.process_id = files.process_id and prev.file_id = %s""",
            (pid, file_id, before),
        )


def apply_manual_stages(conn, pid, obj, documents):
    """Стадия и раздел, заданные инспектором руками, сильнее угадывания по пути. Задача #39.

    На чужом оформлении папок стадия не определяется («Том 1 ПД», «Проект», «АОСР»
    разбираются, но словарь путей не бесконечен), и документ без стадии выпадает
    из сравнения. Инспектор задаёт её на экране файлов, разбор её не перезаписывает,
    правка видна в журнале аудита (FILE_STAGE_SET).
    """
    from pipeline import cli

    rows = conn.execute(
        """select relative_path, stage_manual, section_manual from files
           where process_id = %s and (stage_manual is not null or section_manual is not null)""",
        (pid,),
    ).fetchall()
    if not rows:
        return set()
    # в реестре путь такой, каким он лежит на диске: длинные имена там укорочены
    manual = {paths.disk_path(r["relative_path"]): r for r in rows}
    changed, fields = set(), 0
    for d in documents:
        m = manual.get(d["relative_path"])
        if not m:
            continue
        if m["stage_manual"] and d.get("stage") != m["stage_manual"]:
            d["stage"] = m["stage_manual"]
            changed.add(d["file_id"])
            fields += 1
        if m["section_manual"] and d.get("section") != m["section_manual"]:
            d["section"] = m["section_manual"]
            changed.add(d["file_id"])
            fields += 1
    if changed:
        cli.write_jsonl(out_path(obj, "documents.jsonl"), documents)
    print(f"правка инспектора: файлов {len(manual)}, полей стадии и раздела изменено {fields}")
    # возвращаются документы, а не число: у них поменялась стадия, и при дозагрузке
    # их нужно пересчитать, хотя содержимое то же (#60)
    return changed


def _vlm_rows(rows):
    """Ответы прохода по коду параметра: что изменилось — видно сравнением до и после."""
    out = collections.defaultdict(set)
    for r in rows:
        out[r.get("parameter_code")].add((r.get("file_id"), r.get("pdf_page_number"), tuple(r.get("values") or ())))
    return out


def vlm_pass(pid, obj):
    """Значения с чертежей: проход модели по листам (#98) перед правилами.

    Правила `vlm_value` берут значения из build/<объект>/vlm_values.jsonl (прод) и
    vlm_provisional.jsonl (черновики, #95), и без прохода на новом объекте они молчат. Проход
    идёт по всему объекту, но спрашивает модель только о листах, ответа по которым в кеше нет:
    кеш адресован SHA-256 файла, страницей и вопросом правила. Поэтому дозагрузка стоит
    вызовов только по новым листам (#60), а повторный разбор — ни одного.

    Возвращает (коды прод-правил, у которых ответы изменились, счётчики прохода). Коды нужны
    шагу сравнения: при дозагрузке очередь пересчитывается, если её правила получили новые
    значения, даже когда новые документы кандидатов по ним не дали.
    """
    from argparse import Namespace
    from pipeline import cli, vlm_values

    changed, total = set(), collections.Counter()
    budget = vlm_values.CALLS_PER_OBJECT
    for provisional in ((False, True) if settings.PROVISIONAL else (False,)):
        label = "черновики правил" if provisional else "правила Матрицы"
        before = _vlm_rows(vlm_values.load(obj, provisional=provisional))
        print(f"значения с чертежей, {label}: потолок новых вызовов {budget}, "
              f"одновременно {vlm_values.WORKERS}")
        stats = cli.cmd_vlm(Namespace(
            object=obj, code=None, limit=budget, sheets=settings.VLM_SHEETS, model=None, dry=False,
            fresh=False, provisional=provisional, workers=vlm_values.WORKERS,
            progress=lambda n, of, label=label: infra.progress(
                pid, "parse", f"Значения с чертежей, {label}: проход модели", n, of))) or {}
        total.update(stats)
        # потолок — на объект, а не на каждый из двух проходов
        budget = max(0, budget - stats.get("вызовов", 0))
        if not provisional:
            after = _vlm_rows(vlm_values.load(obj))
            changed = {code for code in set(before) | set(after) if before.get(code) != after.get(code)}
    return changed, total


# каким способом прочитаны страницы постраничного индекса объекта
PAGES_MODE = "pages_mode.json"
MODE_UNKNOWN = "не записан"


def pages_mode_changed(obj, mode):
    """Способ, которым прочитаны прежние страницы объекта, если он не тот, что сейчас (#54, #60).

    Дозагрузка перечитывает только новые документы, а смена способа чтения — не новый документ.
    После включения модели на стенде (PIPELINE_MODEL=1) прежние страницы остались бы прочитанными
    без неё, а протокол назвал бы способом «модель» — так 27.09 вышло с Полярной 16. Поэтому смена
    способа — повод перечитать весь объект. Прочитанное берётся из кеша чтения: модель дочитывает
    только свои страницы, распознавание — свои.

    Способ пишется в `pages_mode.json` после чтения страниц. У разбора до этой правки файла нет,
    способ его страниц неизвестен, и объект перечитывается один раз.
    """
    if not os.path.exists(out_path(obj, "pages.jsonl")):
        return None                       # прошлого индекса нет: объект и так читается весь
    before = (_load_json(out_path(obj, PAGES_MODE)) or {}).get("reading_mode")
    if before is None:
        return MODE_UNKNOWN
    return before if before != mode else None


def parse_plan(obj, documents, previous, restaged, mode):
    """Что перечитывать при разборе (#60): (весь объект, документы для чтения, причина)."""
    from pipeline import incremental

    # стадия или раздел не те, что при прошлом разборе (правка, снятая правка), — весь объект:
    # `incremental.plan` сравнивает с итогом прошлого разбора. Ручная стадия, отличная от
    # угаданной по пути, перечитывает документ и тогда, когда стоит с прошлого разбора
    full, fresh, why = incremental.plan(documents, previous)
    fresh |= restaged
    if not full and not os.path.exists(out_path(obj, "pages.jsonl")):
        full, why = True, "постраничного индекса прошлого разбора нет"
    was = pages_mode_changed(obj, mode)
    if not full and was:
        full, why = True, (f"способ чтения страниц сменился: {was} → {mode}" if was != MODE_UNKNOWN
                           else f"способ чтения прежних страниц не записан, объект читается способом {mode}")
    return full, fresh, why


def vlm_skip_reason(mode):
    """Почему прицельный проход по чертежам не идёт, или None — идёт.

    Проход — прицельный вопрос модели по листу для правил `vlm_value`, а не переписывание страниц,
    и зависит от настройки сервиса, а не от способа чтения страниц (27.09). Веб-форма всегда
    присылает способ, по умолчанию «распознавание», и пока проход шёл только у объекта, читаемого
    моделью, при загрузке через веб он не шёл вовсе. Исключение — «только слой»: его выбирают ради
    самого быстрого разбора, без распознавания и модели.
    """
    if not settings.VLM:
        return "выключен (PIPELINE_VLM)"
    if not settings.MODEL_READY:
        return "модель не настроена"
    if mode == "layer":
        return "объект читается только слоем"
    return None


def step_parse(conn, process):
    from argparse import Namespace
    from pipeline import cli, incremental, pages as pages_mod, readiness, reading

    pid, obj = str(process["id"]), process["object_id"]
    conn.execute("update processes set status = 'PARSING', updated_at = now() where id = %s", (pid,))
    total_files = materialize(conn, process)
    register(process)

    # Способ чтения объекта (#54). Выбран при загрузке: где-то хватает текстового слоя,
    # где-то без модели система молчит. Режим, для которого не настроена модель, понижается
    # до распознавания — но инспектор узнаёт об этом, иначе он ждёт разбора, которого не было.
    asked = process.get("reading_mode")
    mode, use_ocr, use_model = settings.reading_flags(asked)
    # Своя модель на своём железе проверяется до разбора: не поднялась — страницы читает
    # запасной адрес, а без него объект читается распознаванием, и инспектор узнаёт об этом
    route, route_why = (settings.model_route(progress=lambda why, left: infra.progress(
        pid, "parse", f"Ожидание модели ({why}), ещё до {left:.0f} с")) if use_model else ("main", None))
    if route is None:
        mode, use_model = "tesseract", False
    model = (settings.model_for(process.get("model_name")) or reading.model_name()) if use_model else None
    print(f"способ чтения: {readiness.mode_line({'reading_mode': mode, 'model_name': model})}"
          + (f"; {route_why}, " + ("читает запасной адрес" if route == "fallback" else "запасного нет")
             if route_why else ""))
    if route is None:
        infra.notify(conn, "inspector", "WARNING",
                     f"Модель недоступна: {route_why}, запасного адреса нет. Объект прочитан распознаванием",
                     pid, category="ACTION")
    elif route == "fallback":
        infra.notify(conn, "inspector", "WARNING",
                     f"Модель: {route_why}. Страницы читает модель по запасному адресу", pid, category="QUALITY")
    elif asked == "model" and mode != "model":
        infra.notify(conn, "inspector", "WARNING",
                     "Выбрано чтение с моделью, но модель не настроена: объект прочитан распознаванием", pid,
                     category="ACTION")

    # Дозагрузка не пересчитывает объект целиком (#60): реестр прошлого разбора остаётся
    # в рабочем каталоге процесса, и по нему видно, какие документы новые. Разбор устроен
    # по документу — страница, надпись, экспликация, штамп редакции, — поэтому прежние
    # строки берутся как есть, а читаются только новые.
    previous = cli.read_jsonl(out_path(obj, "documents.jsonl")) if os.path.exists(out_path(obj, "documents.jsonl")) else []
    infra.progress(pid, "parse", "Реестр документов: идентификаторы по SHA-256", 0, total_files)
    cli.cmd_registry(Namespace(object=obj))
    documents = cli.read_jsonl(out_path(obj, "documents.jsonl"))
    restaged = apply_manual_stages(conn, pid, obj, documents)

    full, fresh, why = parse_plan(obj, documents, previous, restaged, mode)
    only = None if full else fresh
    print(f"пересчёт: {'весь объект' if full else f'документов {len(fresh)} из {len(documents)}'} — {why}"
          + (f", стадия правлена у {len(restaged)}" if restaged else ""))
    # план читает шаг сравнения: он идёт отдельным процессом, когда реестр уже перезаписан
    with open(out_path(obj, "incremental.json"), "w", encoding="utf-8") as f:
        json.dump({"full": full, "files": sorted(fresh), "reason": why,
                   "documents": len(documents), "at": infra.now_iso()}, f, ensure_ascii=False, indent=2)

    kinds_by_file = collections.defaultdict(collections.Counter)
    unreadable = {}
    rows = []
    if settings.PAGES:
        todo = [d for d in documents if only is None or d["file_id"] in only]
        total_pages = sum(d.get("pdf_pages") or 0 for d in todo if not d.get("duplicate_of"))
        rows = pages_mod.build(
            obj, todo, use_model=use_model, model=model, use_ocr=use_ocr, workers=settings.PAGE_WORKERS,
            progress=lambda n: infra.progress(pid, "parse", "Чтение страниц", n, total_pages))
        if only is not None:
            kept = cli.read_jsonl(out_path(obj, "pages.jsonl")) if os.path.exists(out_path(obj, "pages.jsonl")) else []
            rows = incremental.merge(incremental.keep(kept, only), rows)
        cli.write_jsonl(out_path(obj, "pages.jsonl"), rows)
        with open(out_path(obj, PAGES_MODE), "w", encoding="utf-8") as f:
            json.dump({"reading_mode": mode, "model_name": model, "at": infra.now_iso()}, f, ensure_ascii=False)
        store_page_texts(documents, rows)
        for r in rows:
            kinds_by_file[r["file_id"]][r["kind"]] += 1
            if r.get("error"):
                unreadable[r["file_id"]] = r["error"]
        infra.progress(pid, "parse", "Основная надпись: шифр и лист", total_pages, total_pages)
        cli.cmd_sheets(Namespace(
            object=obj, ocr=use_ocr, workers=settings.OCR_WORKERS, file_ids=only,
            progress=lambda n, total: infra.progress(pid, "parse", "Основная надпись: распознавание угла листа",
                                                     n, total)))
        # экспликации помещений: словарь «номер — наименование» по стадиям для сверки
        # наименований в сравнении по помещениям (#46)
        infra.progress(pid, "parse", "Экспликации помещений")
        cli.cmd_rooms(Namespace(object=obj, file_ids=only))

    # стадия, марка, редакция и цепочки редакций (#10): сравнивать можно только актуальную
    # редакцию; выбор инспектора, если он был, сильнее разбора. Ручная стадия уже наложена
    # на реестр, разбор редакций её не перезаписывает
    infra.progress(pid, "parse", "Редакции документов и цепочки")
    cli.cmd_revisions(Namespace(object=obj, workers=settings.OCR_WORKERS, require_approval=False,
                                manual=manual_revisions(conn, pid), file_ids=only))
    # что изменилось между редакциями (#19): страницы и строки по парам цепочек — в revision_diff.jsonl;
    # где на листе и отмечено ли изменение (#81), листы рабочей документации без отметки — гипотезы
    infra.progress(pid, "parse", "Изменения между редакциями")
    cli.cmd_revdiff(Namespace(object=obj, workers=settings.OCR_WORKERS))
    documents = cli.read_jsonl(out_path(obj, "documents.jsonl"))

    # Акты освидетельствования из XML: они сами называют лист рабочей документации,
    # который подтверждают, и материалы работ. Разбор был только в командной строке (#42)
    infra.progress(pid, "parse", "Акты освидетельствования: разбор XML")
    cli.cmd_acts(Namespace(object=obj))

    # Значения с чертежей (#98): после редакций — заменённые выпуски модель не спрашивает. Идёт по
    # настройке сервиса при любом способе чтения страниц, кроме «только слой» (`vlm_skip_reason`).
    # Сбой прохода разбор не роняет: правила остаются с тем, что дал текст
    skip = vlm_skip_reason(mode)
    if settings.VLM and skip:
        print(f"значения с чертежей: пропущены — {skip}")
    elif settings.VLM:
        try:
            vlm_codes, vlm_stats = vlm_pass(pid, obj)
        except Exception as error:
            import traceback
            traceback.print_exc()
            vlm_codes, vlm_stats = set(), {}
            infra.notify(conn, "inspector", "WARNING",
                         f"Значения с чертежей не прочитаны: {type(error).__name__}. Правила по чертежам "
                         "взяли только текст листов", pid, category="QUALITY")
        print(f"значения с чертежей: {dict(vlm_stats)}; изменились ответы прод-правил {sorted(vlm_codes)}")
        if vlm_stats.get("ошибка модели"):
            infra.notify(conn, "inspector", "WARNING",
                         f"Значения с чертежей: модель не ответила по {vlm_stats['ошибка модели']} листам, "
                         "они будут спрошены при следующем разборе", pid, category="QUALITY")
        if vlm_stats.get("лимит вызовов исчерпан"):
            infra.notify(conn, "inspector", "WARNING",
                         f"Значения с чертежей: потолок вызовов модели исчерпан, не спрошено листов "
                         f"{vlm_stats['лимит вызовов исчерпан']} (PIPELINE_VLM_LIMIT)", pid, category="QUALITY")
        # шагу сравнения: чьи значения обновил проход (при дозагрузке — повод пересчитать очередь)
        with open(out_path(obj, "incremental.json"), encoding="utf-8") as f:
            plan_now = json.load(f)
        plan_now["vlm_codes"] = sorted(vlm_codes)
        with open(out_path(obj, "incremental.json"), "w", encoding="utf-8") as f:
            json.dump(plan_now, f, ensure_ascii=False, indent=2)

    # готовность объекта (#39): страницы без текста, файлы без стадии и раздела, форматы
    # без разбора. Считается здесь, пока страницы в памяти; в протокол идёт готовым числом
    ready = readiness.report(documents, rows, ocr_enabled=use_ocr, model_enabled=use_model,
                             reading_mode=mode, model_name=model)
    with open(out_path(obj, "readiness.json"), "w", encoding="utf-8") as f:
        json.dump(ready, f, ensure_ascii=False, indent=2)
    # в журнал — весь отчёт: способ чтения, время разбора и ответы модели (#54);
    # инспектору уведомлением — только то, что требует внимания
    for line in readiness.show(ready):
        print(f"полнота обработки документации: {line}")
    for line in readiness.notes(ready):
        # Наблюдения о качестве разбора рабочему экрану не нужны: там они читаются как дефект
        # объекта и отвлекают от разбора записей. Их место — журнал обработки объекта (#83).
        infra.notify(conn, "inspector", "WARNING", f"Контроль качества чтения: {line}", pid, category="QUALITY")

    by_path = {d["relative_path"]: d for d in documents}
    accepted = conn.execute(
        "select id, relative_path, file_hash from files where process_id = %s and status = 'ACCEPTED'", (pid,)
    ).fetchall()
    cache = None
    try:
        cache = infra.redis()
    except Exception:
        pass
    predecessors = {d["file_id"]: d.get("predecessor_file_id") for d in documents if d.get("predecessor_file_id")}
    for f in accepted:
        d = by_path.get(paths.disk_path(f["relative_path"]))
        if d is None:
            continue
        error = unreadable.get(d["file_id"]) if not d.get("duplicate_of") else None
        if error:
            # PDF прошёл проверку начала и конца при загрузке, но не открывается:
            # по ТЗ такой файл отклоняется с просьбой загрузить заново
            conn.execute(
                "update files set status = 'REJECTED', reject_code = 'CORRUPTED_PDF', reject_message = %s where id = %s",
                (f"Файл PDF не открывается ({error}). Загрузите его заново", f["id"]),
            )
            infra.notify(conn, "inspector", "WARNING",
                         f"Файл {f['relative_path']} не открывается, загрузите его заново", pid, category="ACTION")
            continue
        conn.execute(
            """update files set file_id = %s, doc_stage = %s, discipline = %s, pdf_pages = %s, approval_status = %s,
                                document_code = %s, revision = %s, chain_id = %s, revision_status = %s
               where id = %s""",
            # шифр и изменение прочитаны с листа: символ NUL из слоя PDF в text не записать
            infra.clean((d["file_id"], d["stage"], d["section"], d.get("pdf_pages"), d.get("approval_status"),
                         d.get("document_code"), d.get("revision"), d.get("chain_id"), d.get("revision_status"),
                         f["id"])),
        )
        if cache is not None:
            # ТЗ: результаты парсинга по хешу файла. Сами страницы лежат в кеше
            # конвейера по тому же SHA-256, здесь — сводка для повторных проверок.
            try:
                cache.set(f"parse:{f['file_hash']}", json.dumps({
                    "file_id": d["file_id"], "stage": d["stage"], "section": d["section"],
                    "pdf_pages": d.get("pdf_pages"), "kinds": dict(kinds_by_file.get(d["file_id"], {})),
                }, ensure_ascii=False))
            except Exception:
                cache = None
    link_predecessors(conn, pid, predecessors)
    store_revision_changes(conn, process)

    statuses, scenario = upload_status(conn, pid)
    conn.execute(
        "update processes set upload_status = %s, scenario = %s, updated_at = now() where id = %s",
        (Jsonb(statuses), scenario, pid),
    )
    print(f"разбор: файлов {total_files}, документов {len(documents)}, статусы {statuses}, сценарий {scenario}")


# ---------------------------------------------------------------- изменения между редакциями

# Сколько страниц томов проекта рисовать за разбор для сравнения редакций. Рабочая документация
# рисуется вся: там отметка изменения проверяется у каждого листа. У томов проекта переиздание
# меняет сотни страниц (у Речникова 1600), и картинка каждой — это 0,2 с и 360 КБ в хранилище.
REVISION_RENDER_LIMIT = 300
PAGE_FIELDS = ("old_page", "new_page", "sheet", "old_sheet", "status", "what", "content_changed", "similarity",
               "changes_total", "numbers", "sheet_number_only", "unreadable")
PLACE_FIELDS = ("layout", "matched_share", "numbers", "service", "moved", "flowed_out", "flowed_in",
                "content_removed", "content_added", "service_removed", "service_added", "removed_sample",
                "added_sample", "zones_old", "zones_new")


def render_revision_pages(process, pairs, pages):
    """Картинки страниц пар редакций — в хранилище, как страницы-доказательства (ключ по SHA-256
    файла и номеру страницы): сравнение «было — стало» на экране показывает обе страницы.
    Возвращает множество (файл, страница), для которых картинка в хранилище есть."""
    from pipeline import cli

    obj = process["object_id"]
    documents = {d["file_id"]: d for d in cli.read_jsonl(out_path(obj, "documents.jsonl"))}
    order, seen, rd_files = [], set(), set()
    for rd_first in (True, False):
        for p in pairs:
            if (p.get("stage_group") == "RD") != rd_first:
                continue
            if rd_first:
                rd_files |= {p["old_file_id"], p["new_file_id"]}
            rows = sorted(pages.get(p["pair_id"], []), key=lambda r: r.get("content_changed") is not True)
            for r in rows:
                for fid, page in ((p["old_file_id"], r.get("old_page")), (p["new_file_id"], r.get("new_page"))):
                    if page is not None and (fid, page) not in seen:
                        seen.add((fid, page))
                        order.append((fid, page))
    have, drawn = _store_renders(process, documents, order, budget=REVISION_RENDER_LIMIT, free=rd_files,
                                 progress=("parse", "Страницы редакций для сравнения"))
    print(f"страницы редакций: нужно {len(order)}, в хранилище {len(have)}, отрисовано сейчас {drawn}")
    return have


def _store_renders(process, documents, order, budget=None, free=frozenset(), progress=None):
    """Картинки страниц [(файл, страница)] в хранилище: ключ — SHA-256 файла и номер страницы, как
    у страниц-доказательств, так что картинка одного файла общая для всех процессов. Уже лежащие
    не перерисовываются. budget — сколько новых картинок нарисовать для файлов не из free
    (None — без предела). Возвращает (есть в хранилище, нарисовано сейчас)."""
    import pymupdf
    from pipeline import evidence as evidence_mod

    pid = str(process["id"])
    client, root = infra.storage(), files_dir(pid)
    have, opened, drawn = set(), {}, 0
    for i, (fid, page) in enumerate(order, 1):
        doc = documents.get(fid)
        if not doc or (doc.get("extension") or "").lower() != ".pdf" or not doc.get("sha256"):
            continue
        key = f"renders/{doc['sha256']}/{page}.jpg"
        try:
            client.stat_object(settings.S3_BUCKET, key)
            have.add((fid, page))
            continue
        except Exception:
            pass
        if budget is not None and fid not in free:
            if budget <= 0:
                continue
            budget -= 1
        path = os.path.join(root, doc["relative_path"])
        if path not in opened:
            try:
                opened[path] = pymupdf.open(path)
            except Exception:
                opened[path] = None
        pdf = opened[path]
        if pdf is None or not 1 <= page <= pdf.page_count:
            continue
        try:
            data, _w, _h = evidence_mod.render_page(pdf[page - 1])
            client.put_object(settings.S3_BUCKET, key, io.BytesIO(data), len(data), content_type="image/jpeg")
            have.add((fid, page))
            drawn += 1
        except Exception as error:
            print(f"страница редакции {fid} стр. {page}: {error}")
        if progress and (i % 20 == 0 or i == len(order)):
            infra.progress(pid, progress[0], progress[1], i, len(order))
    for pdf in opened.values():
        if pdf is not None:
            pdf.close()
    return have, drawn


def render_revision_evidence(conn, process, findings):
    """Прежняя редакция листа доказательства — для ссылки «сравнить с …» под его страницей (#81).

    У томов проекта страницы пар редакций рисуются в пределах REVISION_RENDER_LIMIT за разбор,
    и у листа доказательства прежней редакции могло не оказаться картинки: сравнение открывалось
    с пустой левой стороной (КР1 Речникова, «кор. 2 → кор. 3», стр. 21 → 29). Здесь дорисовываются
    обе стороны тех строк сравнения, чья новая страница — доказательство находки и у которых
    изменилось содержание (для них экран и показывает ссылку), и в `revision_changes` отмечается,
    что картинки есть. Таких страниц единицы, предела нет."""
    from pipeline import cli

    pid, obj = str(process["id"]), process["object_id"]
    wanted = {(e.get("file_id"), e.get("pdf_page_number")) for f in findings for e in (f.get("evidence") or [])
              if isinstance(e.get("pdf_page_number"), int)}
    rows = conn.execute("select pair_id, old_file_id, new_file_id, pages from revision_changes where process_id = %s",
                        (pid,)).fetchall()
    order, touched = [], []
    for row in rows:
        items = row["pages"] or []
        hit = [p for p in items if (row["new_file_id"], p.get("new_page")) in wanted and p.get("content_changed") is not False
               and not (p.get("rendered_old") and p.get("rendered_new"))]
        if not hit:
            continue
        touched.append((row, items, hit))
        for p in hit:
            for fid, page in ((row["old_file_id"], p.get("old_page")), (row["new_file_id"], p.get("new_page"))):
                if page is not None and (fid, page) not in order:
                    order.append((fid, page))
    if not order:
        return
    documents = {d["file_id"]: d for d in cli.read_jsonl(out_path(obj, "documents.jsonl"))}
    have, drawn = _store_renders(process, documents, order)
    with conn.transaction():
        for row, items, hit in touched:
            for p in hit:
                p["rendered_old"] = p.get("old_page") is None or (row["old_file_id"], p.get("old_page")) in have
                p["rendered_new"] = p.get("new_page") is None or (row["new_file_id"], p.get("new_page")) in have
            conn.execute("update revision_changes set pages = %s where process_id = %s and pair_id = %s",
                         (Jsonb(items), pid, row["pair_id"]))
    print(f"страницы редакций у доказательств: строк сравнения {sum(len(h) for _, _, h in touched)}, "
          f"картинок нужно {len(order)}, отрисовано сейчас {drawn}")


def store_revision_changes(conn, process):
    """Что изменилось между редакциями (#19, #81) — в базу: экран файлов и карточка находки видят
    это без рабочего каталога воркера. Таблица процесса перезаписывается каждым разбором."""
    from pipeline import cli

    pid, obj = str(process["id"]), process["object_id"]
    path = out_path(obj, "revision_diff.jsonl")
    rows = cli.read_jsonl(path) if os.path.exists(path) else []
    pairs = [r for r in rows if r.get("kind") == "pair"]
    pages = collections.defaultdict(list)
    for r in rows:
        if r.get("kind") == "page":
            pages[r["pair_id"]].append(r)
    have = render_revision_pages(process, pairs, pages) if pairs else set()
    with conn.transaction():
        conn.execute("delete from revision_changes where process_id = %s", (pid,))
        for p in pairs:
            items = []
            for r in pages[p["pair_id"]]:
                item = {k: r.get(k) for k in PAGE_FIELDS if r.get(k) is not None}
                item["changes"] = [{"was": (c.get("was") or "")[:200] or None, "now": (c.get("now") or "")[:200] or None}
                                   for c in (r.get("changes") or [])[:6]]
                if r.get("place"):
                    item["place"] = {k: r["place"].get(k) for k in PLACE_FIELDS}
                if r.get("registration"):
                    item["registration"] = r["registration"]
                item["rendered_old"] = (p["old_file_id"], r.get("old_page")) in have
                item["rendered_new"] = (p["new_file_id"], r.get("new_page")) in have
                items.append(item)
            summary = {k: p.get(k) for k in ("mark", "old_document", "new_document", "old_pages", "new_pages", "same",
                                              "changed", "added", "removed", "unreadable", "no_text",
                                              "looks_like_revision", "registration", "unmarked")}
            conn.execute(
                """insert into revision_changes (process_id, pair_id, chain_id, stage_group, old_file_id, new_file_id,
                                                 old_revision, new_revision, summary, pages)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (pid, p["pair_id"], p.get("chain_id"), p.get("stage_group"), p["old_file_id"], p["new_file_id"],
                 p.get("old_revision"), p.get("new_revision"), Jsonb(summary), Jsonb(items)),
            )
    print(f"изменения между редакциями: пар {len(pairs)}, страниц {sum(len(v) for v in pages.values())}, "
          f"листов без отметки {sum(p.get('unmarked') or 0 for p in pairs)}")


# ---------------------------------------------------------------- сравнение

def carried(path, version):
    """Пометить записи прошлой версии как перенесённые и вернуть их число.

    Инспектор должен видеть в протоколе, что запись не пересчитана: её значение и решение
    относятся к прошлому разбору, а дозагруженные документы её не касались (#60).
    """
    if not os.path.exists(path):
        return 0
    from pipeline import cli
    rows = cli.read_jsonl(path)
    for r in rows:
        r["carried_from_version"] = r.get("carried_from_version") or version
    cli.write_jsonl(path, rows)
    return len(rows)


def step_compare(conn, process):
    from pipeline import cli, incremental, matrix_rules

    pid, obj = str(process["id"]), process["object_id"]
    register(process)
    # Пересбор по требованию (PIPELINE_FRESH, PIPELINE_FRESH_RULES) — один раз на документ
    # за сравнение: воркер живёт долго, и без сброса пересобрался бы только первый процесс
    matrix_rules.reset_fresh()

    # Что пересчитывать (#60): план записан шагом разбора. Пересчитываются только те
    # параметры, по которым новые документы дали кандидатов, плюс правила, читающие
    # документы сами. Остальные записи переносятся из прошлой версии с решениями инспектора.
    plan = _load_json(out_path(obj, "incremental.json")) or {}
    documents = cli.read_jsonl(out_path(obj, "documents.jsonl"))
    fresh = set(plan.get("files") or [])
    full = bool(plan.get("full", True)) or not fresh
    if not full and incremental.chain_broken(documents, fresh):
        full, plan["reason"] = True, "новый документ встал в цепочку редакций"
    version = conn.execute(
        "select coalesce(max(version), 0) as v from protocols where process_id = %s", (pid,)
    ).fetchone()["v"]
    if not full:
        print(f"пересчёт сравнения: {plan.get('reason')}, новых документов {len(fresh)}")

    # Способ чтения объекта распространяется и на таблицы систем (#54): в режиме «только слой»
    # ячейки не распознаются — инспектор просил не распознавать, и обещание должно держаться
    # на всех шагах. Значение ставится каждый раз: воркер обрабатывает процессы подряд.
    _, use_ocr, _ = settings.reading_flags(process.get("reading_mode"))
    os.environ["PIPELINE_TABLE_OCR"] = "1" if use_ocr and settings.TABLE_OCR else "0"

    names = {1: "первая очередь", 2: "вторая очередь", 3: "третья очередь", 4: "четвёртая очередь", 5: "пятая очередь"}
    for queue in sorted(matrix_rules.QUEUES):
        def progress(n, total, pages, queue=queue):
            if n % 10 == 0 or n == total:
                infra.progress(pid, "compare", f"Правила Матрицы, {names.get(queue, queue)}: прочитано страниц {pages}",
                               n, total)

        rules = matrix_rules.load_rules(matrix_rules.QUEUES[queue])
        findings_path = out_path(obj, f"findings_matrix_q{queue}.jsonl")
        if not full and os.path.exists(findings_path):
            # чего коснулись новые документы: коды, по которым они дали кандидатов, плюс
            # правила, читающие документы сами (таблицы систем, приборы учёта)
            got, _, _ = matrix_rules.collect(obj, rules, only_files=fresh)
            touched = incremental.affected_codes(
                rules, {c for c, st in got.items() if any(st.values())}, documents, fresh)
            # проход по чертежам обновил значения правила — и на прежних листах тоже (#98)
            touched |= set(plan.get("vlm_codes") or []) & set(rules["parameters"])
            if not touched:
                n = carried(findings_path, version)
                print(f"сравнение, очередь {queue}: новые документы её не касаются, "
                      f"перенесено записей {n} из версии {version}")
                continue
            print(f"сравнение, очередь {queue}: пересчитывается, затронуто параметров {len(touched)}")

        findings, summary = matrix_rules.build_findings(obj, rules=rules, progress=progress)
        cli.write_jsonl(findings_path, findings)
        print(f"сравнение, очередь {queue}: находок {len(findings)}, {dict(summary)}")
        applicable = matrix_rules.applicability(obj, rules)
        if applicable:
            cli.write_jsonl(out_path(obj, f"applicability_q{queue}.jsonl"), applicable)

    # Черновики правил (#95, Р-89): параметры без правила прода. Считаются заново на каждом
    # сравнении — кандидаты у них в кеше по правилу, как у прода, а находок немного. Если профиль
    # выключен, прежние файлы черновиков убираются: иначе протокол показал бы старые гипотезы
    for queue in sorted(matrix_rules.QUEUES):
        path = out_path(obj, f"provisional_q{queue}.jsonl")
        rules = matrix_rules.load_provisional(queue) if settings.PROVISIONAL else None
        if not rules:
            if os.path.exists(path):
                os.remove(path)
            continue

        def progress(n, total, pages, queue=queue):
            if n % 10 == 0 or n == total:
                infra.progress(pid, "compare", f"Черновики правил, {names.get(queue, queue)}: прочитано страниц {pages}",
                               n, total)

        findings, summary = matrix_rules.build_findings(obj, rules=rules, progress=progress)
        cli.write_jsonl(path, matrix_rules.mark_provisional(findings))
        print(f"черновики правил, очередь {queue}: находок {len(findings)}, {dict(summary)}")

    # Свободный поиск (#31): предусмотрено проектом для помещений — нет в рабочей документации.
    # Гипотезы идут в пятую таблицу протокола и нарушениями не считаются, пока инспектор их не взял.
    # Он читает проектную и рабочую стадию: акт освидетельствования его не касается (#60).
    free_path = out_path(obj, "findings_free.jsonl")
    free_stages = {"RD" if d.get("stage") == "RD_ID_MIXED" else d.get("stage")
                   for d in documents if d["file_id"] in fresh}
    if not full and os.path.exists(free_path) and not free_stages & {"PD", "RD"}:
        print(f"свободный поиск: новые документы его не касаются, перенесено записей "
              f"{carried(free_path, version)} из версии {version}")
    else:
        infra.progress(pid, "compare", "Свободный поиск: проектные решения против рабочей документации")
        cli.cmd_free(argparse.Namespace(object=obj))


# ---------------------------------------------------------------- протокол

def provisional_findings(obj):
    """Находки черновиков правил по коду параметра (#95). У черновика без находок — пустой
    список: покрытие покажет, что параметр проверял черновик и ничего не нашёл."""
    from pipeline import cli, matrix_rules
    out = {}
    for queue in sorted(matrix_rules.QUEUES):
        rules = matrix_rules.load_provisional(queue)
        path = out_path(obj, f"provisional_q{queue}.jsonl")
        if not rules or not os.path.exists(path):
            continue
        for code, rule in rules["parameters"].items():
            if rule.get("implemented"):
                out.setdefault(code, [])
        for f in cli.read_jsonl(path):
            out.setdefault(f.get("parameter_code"), []).append(f)
    return out


def provisional_profile():
    """Отпечаток профиля черновиков для протокола: какими черновиками проверяли (#95)."""
    from pipeline import matrix_rules
    return "+".join(f"p{q}-" + (_sha_file(os.path.join(matrix_rules.PROVISIONAL_DIR, f"q{q}.json")) or "none")
                    for q in sorted(matrix_rules.QUEUES))


def _sha_file(path, length=12):
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:length]


def _text(value):
    if value is None:
        return None
    value = infra.clean(value)
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def enrich_evidence(process, findings):
    """Страницы-доказательства для экрана инспектора. Меняет доказательства в находках на месте.

    Каждая страница, на которую ссылается находка, рисуется в JPEG и кладётся в хранилище
    по SHA-256 файла и номеру страницы: картинка одного файла общая для всех процессов.
    На странице ищется место — значение из находки или номер помещения (`pipeline.evidence`).
    Доказательство получает шифр и лист из связки «шифр плюс лист», число страниц файла,
    пропорции страницы и прямоугольники места. Сбой отрисовки одной страницы протокол не
    останавливает: у такого доказательства просто нет картинки.
    """
    import io
    import pymupdf
    from pipeline import cli, coords, evidence as evidence_mod, matrix_rules

    pid, obj = str(process["id"]), process["object_id"]
    documents = {d["file_id"]: d for d in cli.read_jsonl(out_path(obj, "documents.jsonl"))
                 if not d.get("duplicate_of")}
    sheets = {}
    if os.path.exists(out_path(obj, "sheets.jsonl")):
        for r in cli.read_jsonl(out_path(obj, "sheets.jsonl")):
            if r.get("document_sheet_number") is not None:
                sheets[(r["file_id"], r["pdf_page_number"])] = r
    kinds = {}
    for queue, queue_path in matrix_rules.QUEUES.items():
        try:
            kinds.update({code: rule.get("kind") for code, rule in matrix_rules.load_rules(queue_path)["parameters"].items()})
            # у гипотез черновиков (#95) вид правила — из профиля
            for code, rule in ((matrix_rules.load_provisional(queue) or {}).get("parameters") or {}).items():
                kinds.setdefault(code, rule.get("kind"))
        except Exception:
            pass
    try:
        pymupdf.TOOLS.mupdf_display_errors(False)
    except Exception:
        pass

    client = infra.storage()
    root = files_dir(pid)
    opened, stored = {}, set()
    items = [(f, e) for f in findings for e in (f.get("evidence") or [])]
    stats = collections.Counter()
    for i, (f, e) in enumerate(items, 1):
        if i % 5 == 0 or i == len(items):
            infra.progress(pid, "protocol", "Страницы-доказательства", i, len(items))
        doc = documents.get(e.get("file_id"))
        page_no = e.get("pdf_page_number")
        if not doc or doc.get("extension") != ".pdf" or not isinstance(page_no, int):
            stats["без файла"] += 1
            continue
        e["page_count"] = doc.get("pdf_pages")
        e["sha256"] = doc.get("sha256")
        e["document"] = os.path.basename(doc.get("relative_path") or "")
        e["revision"] = matrix_rules.revision_label(doc.get("relative_path") or "")
        e["approval_status"] = doc.get("approval_status") or "UNKNOWN"
        sheet = sheets.get((e["file_id"], page_no))
        if sheet:
            e.setdefault("document_code", sheet.get("document_code"))
            e.setdefault("document_sheet_number", sheet.get("document_sheet_number"))
            e["sheet_source"] = sheet.get("sheet_source")
        path = os.path.join(root, doc["relative_path"])
        if path not in opened:
            try:
                opened[path] = pymupdf.open(path)
            except Exception:
                opened[path] = None
        pdf = opened[path]
        if pdf is None or not 1 <= page_no <= pdf.page_count:
            stats["страница не открылась"] += 1
            continue
        try:
            page = pdf[page_no - 1]
            e["preview"] = {"aspect": round(page.rect.width / max(page.rect.height, 1.0), 5)}
            key = f"renders/{doc['sha256']}/{page_no}.jpg"
            if key not in stored:
                try:
                    client.stat_object(settings.S3_BUCKET, key)
                except Exception:
                    data, _w, _h = evidence_mod.render_page(page)
                    client.put_object(settings.S3_BUCKET, key, io.BytesIO(data), len(data),
                                      content_type="image/jpeg")
                    stats["отрисовано"] += 1
                stored.add(key)
            extraction = (f.get("extraction") or {}).get(str(e.get("stage", "")).lower()) or {}
            columns = extraction.get("columns") or []
            kind = kinds.get(f.get("parameter_code"))
            if kind in ("element_class", "element_thickness"):
                # у элемента значение — набор «B30/B35», «1200/1500 мм», на листе они порознь
                rects = evidence_mod.find_element_values(page, kind, columns)
                how = "VALUE" if rects else None
            else:
                rows = columns if kind == "schedule_sum" and len(columns) > 1 else ()
                rects, how = evidence_mod.locate(page, extraction.get("raw"), f.get("locations") or [], rows)
            if e.get("bbox_norm"):
                # Место известно самой находке: строка таблицы систем или подпись помещения на схеме (#37).
                # На листе без текстового слоя поиск по тексту его не найдёт, а найденный номер помещения
                # на плане — не та строка, о которой говорит доказательство.
                rects, how = [e["bbox_norm"]], "FINDING"
            if "boxes_norm" in e:
                # сравнение редакций (#81): места, где лист изменился; поиск по тексту находки тут
                # нашёл бы шифр в штампе, а не изменение
                rects, how = [list(b) for b in e["boxes_norm"] or []], ("REVISION" if e["boxes_norm"] else None)
            e["highlights"] = rects
            e["highlight_source"] = how
            # в карточке протокола рамки — в системе ТЗ: видимая страница, начало внизу слева
            e["bbox_tz"] = [coords.internal_to_tz(r) for r in rects]
            stats["место найдено" if rects else "место не найдено"] += 1
        except Exception as error:
            print(f"доказательство {e.get('file_id')} стр. {page_no}: {error}")
            stats["сбой"] += 1
    for pdf in opened.values():
        if pdf is not None:
            pdf.close()
    print(f"страницы-доказательства: {len(items)}, {dict(stats)}")


def step_protocol(conn, process):
    from argparse import Namespace
    from pipeline import cli, submission

    pid, obj = str(process["id"]), process["object_id"]
    register(process)
    infra.progress(pid, "protocol", "Проекция находок в формат сдачи")
    from pipeline import matrix_rules
    findings_paths = [out_path(obj, f"findings_matrix_q{q}.jsonl") for q in sorted(matrix_rules.QUEUES)]
    # сверка актов освидетельствования с рабочей документацией идёт в протокол наравне
    # с правилами Матрицы: это единственное место, где участвует исполнительная стадия (#42)
    findings_paths.append(out_path(obj, "findings_acts.jsonl"))
    findings_paths.append(out_path(obj, "findings_free.jsonl"))
    # листы рабочей документации, изменённые между редакциями без отметки (#81): гипотезы
    findings_paths.append(out_path(obj, "findings_revisions.jsonl"))
    findings_paths = [p for p in findings_paths if os.path.exists(p)]
    findings = [f for p in findings_paths for f in cli.read_jsonl(p)]
    # черновики правил (#95): нарушения черновика — гипотезы, остальное — отметка в покрытии
    provisional = provisional_findings(obj) if settings.PROVISIONAL else None
    hypotheses = matrix_rules.provisional_hypotheses([f for got in (provisional or {}).values() for f in got])
    findings += hypotheses

    # Протокол для инспектора (#30): статусы комплектности, покрытие Матрицы, изменения версии.
    # Запись без значения из-за стадии, которой в процессе нет, — «обязательный документ
    # отсутствует» (MISSING_DOCUMENT, RD_MISSING) и в файле сдачи, поэтому отметка — до проекции.
    from pipeline import protocol as protocol_mod
    present = protocol_mod.stages_present(process.get("upload_status"))
    for f in findings:
        status, reason = protocol_mod.completeness(f, present)
        f["protocol"] = {"completeness_status": status, "completeness_reason": reason}
        protocol_mod.mark_absent_stage(f, present)
    marked_path = out_path(obj, "findings_protocol.jsonl")
    cli.write_jsonl(marked_path, findings)

    protocol_path = out_path(obj, "submission.json")
    cli.cmd_submit(Namespace(object=obj, findings=[marked_path], out=protocol_path, strict=False,
                             only_decided=False, with_bbox=False, score=None))
    with open(protocol_path, encoding="utf-8") as f:
        body = json.load(f)
    # Записи, отложенные до решения инспектора (#63): гипотезы свободного поиска в файл
    # сдачи не идут, пока их не взяли в кандидаты и не подтвердили. Проекция посчитана
    # здесь же — в API её посчитать нечем, реестр файлов и стадии живут в конвейере.
    held_back = {row["finding_id"]: row.get("checks") or []
                 for row in ((_load_json(out_path(obj, "submission_report.json")) or {})
                             .get("excluded_by_origin") or []) if row.get("finding_id")}
    errors = submission.validate(body)
    if errors:
        raise RuntimeError(f"протокол не проходит схему сдачи организатора: {errors[:3]}")
    enrich_evidence(process, findings)
    render_revision_evidence(conn, process, findings)
    previous = {
        r["finding_id"]: {"pd_value": r["pd_value"], "rd_value": r["rd_value"], "violation_label": r["violation_label"],
                          "verification_status": r["verification_status"], "origin": r["origin"]}
        for r in conn.execute(
            """select finding_id, pd_value, rd_value, violation_label, verification_status, body->>'origin' as origin
               from findings where process_id = %s""", (pid,)).fetchall()
    }
    catalog = cli.read_jsonl(os.path.join(ROOT, "docs", "extracted", "parameter_catalog_132.jsonl"))
    rules_by_queue = {q: matrix_rules.load_rules(path) for q, path in matrix_rules.QUEUES.items()}
    applicability_paths = [out_path(obj, f"applicability_q{q}.jsonl") for q in sorted(matrix_rules.QUEUES)]
    applicability = [r for p in applicability_paths if os.path.exists(p) for r in cli.read_jsonl(p)]
    diff = protocol_mod.changes(previous, [dict(f, pd_value=_text(f.get("pd_value")), rd_value=_text(f.get("rd_value")))
                                           for f in findings]) if previous else None
    stale = {c["finding_id"]: c for c in (diff or {}).get("decided_changed", [])}
    for f in findings:
        if f["finding_id"] in stale:
            # решение переносится, но относилось к прежним значениям: инспектор видит это в карточке
            f["changed_after_decision"] = stale[f["finding_id"]]["before"]

    manifest = conn.execute(
        "select relative_path, file_hash from files where process_id = %s and status = 'ACCEPTED' order by relative_path",
        (pid,),
    ).fetchall()
    manifest_hash = hashlib.sha256(
        "\n".join(f"{r['relative_path']}\t{r['file_hash']}" for r in manifest).encode("utf-8")).hexdigest()
    labels = collections.Counter(c["violation_label"] for c in body["checks"])
    # чем объект прочитан, берётся из отчёта готовности, а не из настроек воркера: разбор
    # шёл со способом чтения этого процесса, и мог идти в другом воркере с другими флагами (#54)
    ready = _load_json(out_path(obj, "readiness.json")) or {}
    # что пересчитано, а что перенесено из прошлой версии (#60): по числам видно, во что
    # обошлась дозагрузка и на каких записях решения инспектора относятся к прежнему разбору
    step = _load_json(out_path(obj, "incremental.json")) or {}
    carried_over = sum(1 for f in findings if f.get("carried_from_version"))
    report = {
        "findings": len(findings),
        "checks": len(body["checks"]),
        "labels": dict(labels),
        "recompute": {
            "full": bool(step.get("full", True)),
            "reason": step.get("reason"),
            "documents_read": len(step.get("files") or []),
            "documents_total": step.get("documents"),
            "carried_over": carried_over,
            "recomputed": len(findings) - carried_over,
        },
        "pages_read": settings.PAGES,
        "reading_mode": ready.get("reading_mode") or settings.reading_mode(process.get("reading_mode")),
        "ocr": ready.get("ocr_enabled", settings.OCR),
        "model": ready.get("model_enabled", settings.USE_MODEL),
        "model_name": ready.get("model_name"),
        # черновики правил (#95): включены ли, сколькими проверяли и сколько гипотез дали
        "provisional": {"enabled": settings.PROVISIONAL, "rules": len(provisional or {}),
                        "hypotheses": len(hypotheses),
                        "profile": provisional_profile() if settings.PROVISIONAL else None},
    }
    detailed = {
        **report,
        "run_timestamp": infra.now_iso(),
        "stages_present": sorted(present),
        "stage_files": stage_file_counts(conn, pid),
        "coverage": protocol_mod.coverage(catalog, rules_by_queue, findings, present, applicability,
                                          provisional=provisional),
        "readiness": ready or None,
        "changes": diff,
        # записи, которые войдут в файл сдачи, если инспектор возьмёт гипотезу
        # в кандидаты и подтвердит её (#63)
        "held_back_checks": held_back or None,
        # помещение → документы, где оно встречается: для контекста находки (#82)
        "rooms": rooms_index(obj),
    }

    with conn.transaction():
        version = conn.execute(
            "select coalesce(max(version), 0) + 1 as v from protocols where process_id = %s", (pid,)
        ).fetchone()["v"]
        conn.execute(
            """insert into protocols (process_id, object_id, version, matrix_version, dataset_version,
                                      model_version, input_manifest_hash, status, body, report)
               values (%s, %s, %s, %s, %s, %s, %s, 'READY', %s, %s)""",
            (pid, obj, version,
             "+".join(f"q{q}-" + (_sha_file(path) or "none") for q, path in sorted(matrix_rules.QUEUES.items())),
             "manifest-" + (_sha_file(os.path.join(ROOT, "docs", "extracted", "document_manifest.jsonl")) or "none"),
             f"pipeline-{settings.PIPELINE_VERSION}+{report['reading_mode']}"
             + (f"/{report['model_name']}" if report.get("model_name") else ""),
             manifest_hash, Jsonb(body), Jsonb(detailed)),
        )
        seen = []
        for f in findings:
            # конфликт редакций (#10) — тоже решение инспектора: назвать актуальную редакцию
            # на экране файлов или оставить «требует уточнения»
            candidate = (f.get("violation_label") == "VIOLATION_PRESENT"
                         or f.get("finding_status") == "CLARIFICATION_REQUIRED")
            seen.append(f["finding_id"])
            location = infra.clean(", ".join(str(x) for x in (f.get("locations") or []))) or None
            conn.execute(
                """insert into findings (id, process_id, finding_id, protocol_version, parameter_code, location,
                                         violation_label, protocol_status, criticality, pd_value, rd_value,
                                         verification_status, body)
                   values (gen_random_uuid(), %(pid)s, %(fid)s, %(v)s, %(code)s, %(loc)s, %(label)s, %(ps)s, %(crit)s,
                           %(pd)s, %(rd)s, %(vs)s, %(body)s)
                   on conflict (process_id, finding_id) do update set
                       protocol_version = excluded.protocol_version, parameter_code = excluded.parameter_code,
                       location = excluded.location, violation_label = excluded.violation_label,
                       protocol_status = excluded.protocol_status, criticality = excluded.criticality,
                       pd_value = excluded.pd_value, rd_value = excluded.rd_value,
                       -- пометки инспектора живут в body и пересборку переживают, как решения:
                       -- гипотеза, взятая в кандидаты (ТЗ 9.2), и запись, где он не согласился
                       -- с автоматической проверкой (#74). Иначе разбор молча вернул бы их назад
                       body = excluded.body
                              || (select coalesce(jsonb_object_agg(k, v), '{}'::jsonb)
                                    from jsonb_each(findings.body) as m(k, v)
                                   where k in ('promoted_at', 'promoted_by', 'disputed_at', 'disputed_by'))
                              -- «значения изменились после решения» держится, пока решение не пересмотрено:
                              -- следующая пересборка изменений уже не видит и стёрла бы отметку. Прежнее
                              -- «было» важнее нового — это значения на момент решения. Снимает отметку
                              -- новое решение инспектора (API, routes/findings.ts)
                              || case when findings.body ? 'changed_after_decision'
                                           and findings.verification_status in
                                               ('CONFIRMED_VIOLATION', 'NEGATIVE_VERIFIED', 'CLARIFICATION_REQUIRED')
                                           and excluded.verification_status <> 'NOT_REQUIRED'
                                      then jsonb_build_object('changed_after_decision', findings.body->'changed_after_decision')
                                      else '{}'::jsonb end
                              -- Решение инспектора автоматика не снимает. Если после дозагрузки расхождения
                              -- по подтверждённой или отправленной на уточнение записи больше нет, запись
                              -- возвращается инспектору в кандидаты, а прежнее решение — кто, когда, по каким
                              -- значениям — остаётся в «reopened», пока он не решит заново (API снимает отметку).
                              -- Отклонённую запись, с которой автоматика теперь согласна, пересматривать незачем
                              || case when excluded.verification_status = 'NOT_REQUIRED'
                                           and findings.verification_status in ('CONFIRMED_VIOLATION', 'CLARIFICATION_REQUIRED')
                                      then jsonb_build_object('reopened', jsonb_build_object(
                                             'decision', findings.verification_status, 'by', findings.decided_by,
                                             'at', findings.decided_at, 'reason_code', findings.reason_code,
                                             'comment', findings.comment, 'version', excluded.protocol_version,
                                             'before', jsonb_build_object('pd_value', findings.pd_value,
                                                                          'rd_value', findings.rd_value,
                                                                          'violation_label', findings.violation_label)))
                                      when findings.body ? 'reopened' and findings.verification_status = 'PENDING'
                                      then jsonb_build_object('reopened', findings.body->'reopened')
                                      else '{}'::jsonb end,
                       decided_by = case when excluded.verification_status = 'NOT_REQUIRED'
                                           and findings.verification_status in ('CONFIRMED_VIOLATION', 'CLARIFICATION_REQUIRED') then null else findings.decided_by end,
                       decided_at = case when excluded.verification_status = 'NOT_REQUIRED'
                                           and findings.verification_status in ('CONFIRMED_VIOLATION', 'CLARIFICATION_REQUIRED') then null else findings.decided_at end,
                       reason_code = case when excluded.verification_status = 'NOT_REQUIRED'
                                           and findings.verification_status in ('CONFIRMED_VIOLATION', 'CLARIFICATION_REQUIRED') then null else findings.reason_code end,
                       verification_status = case
                           when findings.verification_status = 'SPLIT' then 'SPLIT'
                           when findings.body ? 'disputed_at' then 'PENDING'
                           when excluded.verification_status = 'NOT_REQUIRED'
                                           and findings.verification_status in ('CONFIRMED_VIOLATION', 'CLARIFICATION_REQUIRED') then 'PENDING'
                           -- возвращённая инспектору запись ждёт его решения и в следующих пересборках
                           when findings.body ? 'reopened' and findings.verification_status = 'PENDING' then 'PENDING'
                           when excluded.verification_status = 'NOT_REQUIRED' then 'NOT_REQUIRED'
                           when findings.verification_status = 'NOT_REQUIRED' then 'PENDING'
                           else findings.verification_status end""",
                {"pid": pid, "fid": f["finding_id"], "v": version, "code": f.get("parameter_code"), "loc": location,
                 "label": f.get("violation_label"), "ps": f.get("protocol_status"), "crit": f.get("criticality"),
                 "pd": _text(f.get("pd_value")), "rd": _text(f.get("rd_value")),
                 "vs": "PENDING" if candidate else "NOT_REQUIRED", "body": Jsonb(f)},
            )
        # части, на которые инспектор разделил запись, конвейер не порождает: их не удаляем
        conn.execute(
            """delete from findings where process_id = %s and not (finding_id = any(%s))
               and coalesce(body->>'origin', '') <> 'INSPECTOR_SPLIT'""",
            (pid, seen),
        )
        # решения инспектора переживают пересборку: статус считается по ним
        infra.settle_status(conn, pid)
        # Кандидаты и гипотезы считаются так же, как таблицы протокола и шапка экрана проверки
        # (service/api/src/process.ts, countFindings): гипотеза свободного поиска, не взятая
        # в кандидаты, в кандидатах не числится (ТЗ 9.2). Раньше уведомление считало все записи
        # с расхождением и насчитывало 11 кандидатов там, где таблица показывала 8.
        # гипотеза — запись свободного поиска или черновика правила (#95), не взятая в кандидаты
        tally = conn.execute(
            """select
                 count(*) filter (where verification_status not in ('NOT_REQUIRED', 'SPLIT') and not hypothesis) as candidates,
                 count(*) filter (where verification_status = 'PENDING' and not hypothesis) as pending,
                 count(*) filter (where hypothesis) as hypotheses
               from (select verification_status,
                            (coalesce(body->>'matrix_scope', '') = 'FREE_SEARCH'
                               or coalesce((body->>'provisional')::boolean, false))
                              and verification_status = 'PENDING' and body->>'promoted_at' is null as hypothesis
                       from findings where process_id = %s) f""",
            (pid,),
        ).fetchone()
        name = process.get("object_name") or obj
        # «ждут решения N» — как в шапке экрана проверки и в реестре: после решений
        # кандидатов больше, чем строк в таблице 2
        infra.notify(conn, "inspector", "INFO",
                     f"Протокол версии {version} по объекту «{name}» сформирован: кандидатов в нарушения "
                     f"{tally['candidates']}, ждут решения {tally['pending']}"
                     + (f", гипотез {tally['hypotheses']}" if tally["hypotheses"] else ""),
                     pid)
        if stale:
            # Решённые записи, у которых изменились значения и решение осталось: их надо пересмотреть,
            # они отмечены в списке и ведут к себе с экрана проверки. Записи, по которым автоматика
            # расхождения больше не видит, вернулись в кандидаты (reopened) — о них вторая фраза
            final = {r["finding_id"]: r["verification_status"] for r in conn.execute(
                "select finding_id, verification_status from findings where process_id = %s and finding_id = any(%s)",
                (pid, list(stale)),
            ).fetchall()}
            decided = ("CONFIRMED_VIOLATION", "NEGATIVE_VERIFIED", "CLARIFICATION_REQUIRED")
            reopen = [fid for fid, st in final.items() if st in decided]
        else:
            reopen = []
        # решения, которые автоматика не сняла, а вернула инспектору: расхождения больше нет
        returned = conn.execute(
            "select count(*) as n from findings where process_id = %s and (body->'reopened'->>'version')::int = %s",
            (pid, version),
        ).fetchone()["n"]
        # одним уведомлением: экран проверки показывает по одному свежему уведомлению каждого вида
        parts = []
        if reopen:
            parts.append(f"После дозагрузки изменились значения у {len(reopen)} записей с решением инспектора: "
                         "они отмечены в списке протокола знаком «значения изменились» — пересмотрите решения")
        if returned:
            parts.append(f"{'У ещё' if reopen else 'После дозагрузки у'} {returned} записей с решением инспектора "
                         "автоматика расхождения больше не видит: они возвращены в кандидаты — решите заново")
        if parts:
            infra.notify(conn, "inspector", "WARNING", ". ".join(parts), pid, category="ACTION")
        infra.audit(conn, "PROTOCOL_CREATED", pid, obj,
                    {"version": version, **report,
                     "changes": diff and {k: len(v) for k, v in diff.items()}})
    print(f"протокол: версия {version}, записей {len(body['checks'])}, {dict(labels)}")


STEPS = {"parse": step_parse, "compare": step_compare, "protocol": step_protocol}


def main():
    ap = argparse.ArgumentParser(description="шаг обработки процесса проверки")
    ap.add_argument("step", choices=list(STEPS))
    ap.add_argument("process_id")
    args = ap.parse_args()
    if not os.environ.get("PIPELINE_OUT"):
        raise SystemExit("PIPELINE_OUT не задан: шаг запускается воркером")
    with infra.db() as conn:
        process = load_process(conn, args.process_id)
        STEPS[args.step](conn, process)
    return 0


if __name__ == "__main__":
    sys.exit(main())
