"""Командная строка конвейера.

  python -m pipeline.cli objects
  python -m pipeline.cli registry --object OBJ-TYUMENSKAYA-5-GOLD-SEED
  python -m pipeline.cli pages    --object OBJ-TYUMENSKAYA-5-GOLD-SEED --limit-files 3
  python -m pipeline.cli pages    --object OBJ-TYUMENSKAYA-5-GOLD-SEED --no-model
  python -m pipeline.cli sheets   --object OBJ-TYUMENSKAYA-5-GOLD-SEED --ocr
  python -m pipeline.cli readiness --object OBJ-TYUMENSKAYA-5-GOLD-SEED
  python -m pipeline.cli revisions --object OBJ-RECHNIKOV-7-7
  python -m pipeline.cli plans    --object OBJ-TYUMENSKAYA-5-GOLD-SEED
  python -m pipeline.cli run      --object OBJ-NOVOSLOBODSKAYA
  python -m pipeline.cli normrefs
  python -m pipeline.cli rules    --object OBJ-RECHNIKOV-7-7
  python -m pipeline.cli submit   --object OBJ-TYUMENSKAYA-5-GOLD-SEED --findings f.jsonl

Объект, которого нет в конфигурации, задаётся папкой; идентификаторы файлов возьмутся
из реестров организатора, перечисленных в INSPECTOR_MANIFESTS (см. docs/new-object.md):

  python -m pipeline.cli registry --object OBJ-NEW --root "/data/Новый объект"

Результат кладётся в build/<object_id>/documents.jsonl и pages.jsonl.
Чтение кешируется по SHA-256 файла, повторный прогон бесплатен.
"""
import argparse
import collections
import glob
import json
import multiprocessing
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import pages as pages_mod
from pipeline import acts_check, aosr_xml, plan_rooms, reading, rooms as rooms_mod
from pipeline import matrix_rules, normrefs, sheet_sequence, submission as submission_mod, titleblock
from pipeline import titleblock_ocr
from pipeline import incremental
from pipeline import readiness as readiness_mod
from pipeline import registry, revisions
from pipeline.config import OBJECTS, OUT, manifest_paths, register_object


def _load_env(path=None):
    path = path or os.path.join(os.path.dirname(OUT), ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def read_jsonl(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def object_arg(parser):
    """Ключи объекта: из конфигурации по идентификатору или свой по --root (#39)."""
    parser.add_argument("--object", required=True, metavar="ИДЕНТИФИКАТОР",
                        help="объект из конфигурации (" + ", ".join(OBJECTS) + ") "
                             "или любой другой вместе с --root")
    parser.add_argument("--root", metavar="ПАПКА",
                        help="папка объекта, которого нет в конфигурации; идентификаторы файлов "
                             "возьмутся из реестров организатора, см. INSPECTOR_MANIFESTS")
    parser.add_argument("--name", help="название объекта для отчётов, по умолчанию идентификатор")
    return parser


def resolve_object(args):
    """Объект вне конфигурации живёт на время запуска: путь берётся из --root."""
    oid = getattr(args, "object", None)
    root = getattr(args, "root", None)
    if not oid:
        return
    if root:
        root = os.path.abspath(os.path.expanduser(root))
        if not os.path.isdir(root):
            raise SystemExit(f"папка объекта не найдена: {root}")
        register_object(oid, root, getattr(args, "name", None), split="EXTERNAL")
    elif oid not in OBJECTS:
        raise SystemExit(f"объект {oid} не настроен. Укажите папку ключом --root "
                         f"или выберите из: {', '.join(OBJECTS)}")


def cmd_objects(_):
    print(f'{"идентификатор":32} {"сплит":12} {"есть":5}  название')
    for oid, spec in OBJECTS.items():
        ok = "да" if os.path.isdir(spec["root"]) else "нет"
        print(f'{oid:32} {spec["split"]:12} {ok:5}  {spec["name"]}')


def cmd_registry(args):
    known = [m for m in manifest_paths() if os.path.exists(m)]
    print("реестры организатора: " + (", ".join(known) if known else
                                      "не найдены, идентификаторы файлов будут локальными"))
    path = os.path.join(OUT, args.object, "documents.jsonl")
    # прежние локальные идентификаторы сохраняются: на них ссылаются связки и находки
    previous = read_jsonl(path) if os.path.exists(path) else None
    rows = registry.build(args.object, progress=lambda n: print(f"  {n} файлов", end="\r"),
                          previous=previous)
    path = write_jsonl(path, rows)
    s = registry.summary(rows)
    print(f"\nреестр: {path}")
    print(f'  файлов {s["files"]}, уникальных {s["unique"]}, дублей {s["duplicates"]}')
    print(f'  с официальным идентификатором {s["with_official_id"]}, страниц {s["pages"]}')
    print(f'  по стадиям: {s["by_stage"]}')
    if s["unsupported"]:
        print(f'  формат не читается, файл только в реестре: {s["unsupported"]} '
              f'{s["unsupported_by_extension"]}')


def cmd_readiness(args):
    """Готовность объекта: на что опирается вывод правил и что осталось неопознанным (#39)."""
    docs_path = os.path.join(OUT, args.object, "documents.jsonl")
    if not os.path.exists(docs_path):
        print("сначала соберите реестр: python -m pipeline.cli registry --object " + args.object)
        return
    pages_path = os.path.join(OUT, args.object, "pages.jsonl")
    rep = readiness_mod.report(read_jsonl(docs_path),
                               read_jsonl(pages_path) if os.path.exists(pages_path) else [])
    out = os.path.join(OUT, args.object, "readiness.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(f"готовность: {out}")
    for line in readiness_mod.show(rep):
        print(f"  {line}")


def cmd_pages(args):
    _load_env()
    doc_path = os.path.join(OUT, args.object, "documents.jsonl")
    if not os.path.exists(doc_path):
        print("сначала соберите реестр: python -m pipeline.cli registry --object " + args.object)
        return
    docs = read_jsonl(doc_path)
    if args.stage:
        docs = [d for d in docs if d["stage"] == args.stage]
    want = _file_ids(args)
    if want is not None:
        docs = [d for d in docs if d["file_id"] in want]
    if args.limit_files:
        docs = docs[: args.limit_files]
    rows = pages_mod.build(args.object, docs, use_model=not args.no_model,
                           model=args.model, workers=args.workers,
                           progress=lambda n: print(f"  {n} страниц", end="\r"))
    # Прогон по части файлов не должен затирать уже проиндексированные страницы:
    # сливаем с существующим индексом по ключу «файл + страница».
    out_path = os.path.join(OUT, args.object, "pages.jsonl")
    merged = {}
    if os.path.exists(out_path):
        for old in read_jsonl(out_path):
            merged[(old["file_id"], old["pdf_page_number"])] = old
    for r in rows:
        merged[(r["file_id"], r["pdf_page_number"])] = r
    rows_all = sorted(merged.values(), key=lambda r: (r["file_id"], r["pdf_page_number"]))
    path = write_jsonl(out_path, rows_all)
    s = pages_mod.summary(rows_all)
    print(f"\nиндекс: {path} (в этом прогоне {len(rows)} страниц)")
    print(f'  страниц {s["pages"]}, с текстом {s["with_text"]}, ошибок {s["errors"]}')
    print(f'  по типам: {s["by_kind"]}')
    print(f'  по источнику: {s["by_source"]}')
    print(f'  стоимость: ${s["cost_usd"]}')


def _read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_jsonl_if(path):
    return read_jsonl(path) if os.path.exists(path) else []


def _group_room_pages(rows):
    """Строки `rooms_pages.jsonl` обратно в «страница → помещения»: (файл, страница, записи)."""
    out, order = {}, []
    for r in rows:
        key = (r["file_id"], r["pdf_page_number"])
        if key not in out:
            out[key] = []
            order.append(key)
        out[key].append({"number": r["number"], "name": r.get("name"), "area_m2": r.get("area_m2"),
                         "category": r.get("category"), "labeled": r.get("labeled", False)})
    return [(fid, page, out[(fid, page)]) for fid, page in order]


def _file_ids(args):
    """Документы, которые нужно пересчитать, или None — значит все.

    Дозагрузка (#60) просит пересчитать только новые документы: строки прежнего разбора
    по остальным берутся как есть.
    """
    value = getattr(args, "file_ids", None)
    if not value:
        return None
    return {x.strip() for x in value.split(",") if x.strip()} if isinstance(value, str) else set(value)


def _cached_pages(object_id, file_ids=None):
    """Страницы объекта со словами: слова лежат в кеше чтения, а не в индексе."""
    docs = read_jsonl(os.path.join(OUT, object_id, "documents.jsonl"))
    by_id = {d["file_id"]: d for d in docs}
    for row in read_jsonl(os.path.join(OUT, object_id, "pages.jsonl")):
        d = by_id.get(row["file_id"])
        if not d or (file_ids is not None and row["file_id"] not in file_ids):
            continue
        got = reading.cache_get(d["sha256"], row["pdf_page_number"], "read")
        if got:
            yield row, got


def _ocr_titleblock(task):
    path, sha, page = task
    t = time.time()
    return titleblock_ocr.parse_page(path, sha, page), time.time() - t


def cmd_sheets(args):
    """Связка «шифр + лист» с номером страницы PDF.

    Сначала основная надпись разбирается по текстовому слою. На страницах, где номер
    листа так не найден, с ключом --ocr распознаётся угол листа (задача #16).
    Затем номера проверяются по соседним страницам.

    При дозагрузке (#60) надпись разбирается только у новых документов, а прежние строки
    берутся из `sheets_raw.jsonl` — это разбор до проверки соседями. Проверка соседями
    и выравнивание шифров глобальные, поэтому идут по всему объекту заново: иначе номер,
    подставленный по ряду, участвовал бы в следующей проверке как прочитанный.
    """
    want = _file_ids(args)
    raw_path = os.path.join(OUT, args.object, "sheets_raw.jsonl")
    if want is not None and not os.path.exists(raw_path):
        want = None          # прошлого разбора надписей нет — считаем весь объект
    out = []
    for row, got in _cached_pages(args.object, want):
        page_kind = got.get("kind") or row.get("kind")
        # Отделяем слова векторного текстового слоя от слов полностраничного распознавания Tesseract:
        # полностраничное распознавание скана загрязняет надпись и перебивает точное чтение угла (задача #16, #22).
        vec_words = [w for w in (got.get("words") or []) if w.get("source") != "TESSERACT"]
        if page_kind == "SCAN_NO_TEXT":
            vec_words = []
        vec_text = "" if page_kind in reading.OCR_KINDS else (got.get("text", "") if "TEXT_LAYER" in (got.get("sources") or ["TEXT_LAYER"]) else "")
        # размер листа: зона штампа считается в миллиметрах, а не в долях листа (#41)
        tb = titleblock.parse(vec_words, vec_text,
                              page_size=(got.get("width_pt"), got.get("height_pt")))
        tb["sheet_source"] = "TEXT_LAYER" if tb["document_sheet_number"] is not None else None
        # Пометка обязательна: по ней sheet_sequence не трогает шифры текстового слоя
        # и берёт их опорой для шифров из распознавания. Без неё в 7b5c9e4 выравнивание
        # перезаписало «ИОС5.5.5» шифром другого тома «ИОС5.5.1».
        tb["code_source"] = "TEXT_LAYER" if tb["document_code"] else None
        out.append({
            "file_id": row["file_id"],
            "pdf_page_number": row["pdf_page_number"],
            "kind": page_kind,
            **tb,
        })

    if args.ocr:
        docs = {d["file_id"]: d for d in read_jsonl(os.path.join(OUT, args.object, "documents.jsonl"))}
        root = OBJECTS[args.object]["root"]
        todo = [r for r in out if r["document_sheet_number"] is None]
        tasks = [(os.path.join(root, docs[r["file_id"]]["relative_path"]),
                  docs[r["file_id"]]["sha256"], r["pdf_page_number"]) for r in todo]
        print(f"распознавание угла: {len(tasks)} страниц без номера листа в текстовом слое",
              flush=True)
        # ход распознавания: у объекта со сканами оно идёт десятки минут, и без хода сервис
        # не отличает долгий шаг от зависшего (#113)
        progress = getattr(args, "progress", None)
        t0, spent = time.time(), 0.0
        with multiprocessing.Pool(args.workers) as pool:
            for done, (r, (got, dt)) in enumerate(zip(todo, pool.imap(_ocr_titleblock, tasks, chunksize=4)), 1):
                spent += dt
                if progress and (done % 50 == 0 or done == len(tasks)):
                    progress(done, len(tasks))
                if done % 1000 == 0:
                    print(f"  прочитано {done} из {len(tasks)} за {time.time() - t0:.0f} с", flush=True)
                if got.get("document_sheet_number") is not None:
                    r["document_sheet_number"] = got["document_sheet_number"]
                    r["sheet_source"] = ("OCR_CELL" if got.get("how") == "подписи, графа отдельно"
                                         else "OCR_CORNER")
                for k in ("document_code", "stage_from_titleblock", "sheets_total"):
                    if r.get(k) is None and got.get(k) is not None:
                        r[k] = got[k]
                        if k == "document_code":
                            r["code_source"] = "OCR_CORNER"
                if got.get("sheet_candidate") is not None:
                    r["sheet_candidate"] = got["sheet_candidate"]
                r["has_titleblock"] = bool(r.get("has_titleblock") or got.get("has_titleblock"))
        print(f"  {time.time() - t0:.0f} с на {args.workers} процессах, "
              f"{spent / max(len(tasks), 1):.2f} с на страницу в процессе (с кешем быстрее)")

    if want is not None:
        out = incremental.merge(incremental.keep(read_jsonl(raw_path), want), out)
        print(f"  из прошлого разбора взято страниц: {sum(1 for r in out if r['file_id'] not in want)}")
    write_jsonl(raw_path, out)

    # шифр комплекта из реестра: им выправляются знаки, спутанные распознаванием (#52)
    registry_codes = {d["file_id"]: d.get("document_code")
                      for d in read_jsonl(os.path.join(OUT, args.object, "documents.jsonl"))
                      if d.get("document_code")}
    checks = sheet_sequence.check(out, registry_codes)
    path = write_jsonl(os.path.join(OUT, args.object, "sheets.jsonl"), out)
    have = [r for r in out if r["document_sheet_number"] is not None]
    read = [r for r in have if r["sheet_source"] != "SEQUENCE"]
    stamped = [r for r in out if r.get("has_titleblock")]
    keys = {(r["document_code"], r["document_sheet_number"]) for r in have}
    print(f"связка листов: {path}")
    print(f"  страниц {len(out)}, с основной надписью {len(stamped)}")
    print(f"  номер листа прочитан у {len(read)} ({len(read)/max(len(out),1):.0%} всех страниц, "
          f"{len(read)/max(len(stamped),1):.0%} страниц с надписью)")
    print(f"  по источникам: {dict(collections.Counter(r['sheet_source'] for r in have))}")
    print(f"  проверка соседями: подтверждено {checks['CONFIRMED']}, "
          f"не подтверждено {checks['UNCONFIRMED']}, снято как противоречащие {checks['CONFLICT']}")
    print(f"  слабые прочтения графы: принято {checks['WEAK_CONFIRMED']}, "
          f"отброшено {checks['WEAK_REJECTED']}")
    print(f"  шифры из распознавания: выровнено по ряду {checks['CODE_HARMONIZED']}, "
          f"подставлено из ряда {checks['CODE_FROM_RUN']}, "
          f"выправлено по реестру {checks['CODE_FIXED_BY_REGISTRY']}")
    print(f"  с заполненными пропусками {len(have)} ({len(have)/max(len(stamped),1):.0%} страниц с надписью)")
    print(f"  уникальных пар «шифр + лист»: {len(keys)} из {len(have)}")
    codes = collections.Counter(r["document_code"] for r in have if r["document_code"])
    print(f"  шифров: {dict(codes.most_common(5))}")


def cmd_revisions(args):
    """Стадия, марка, раздел и редакция документа, цепочки редакций. Задача #10.

    Дописывает поля в documents.jsonl и кладёт цепочки в revisions.jsonl. Номер изменения
    из штампа читается из текстового слоя PDF. Связка листов не обязательна: без неё марка
    берётся только из имён файлов, а переиздания без общей марки не связываются.
    """
    docs_path = os.path.join(OUT, args.object, "documents.jsonl")
    if not os.path.exists(docs_path):
        print("сначала соберите реестр: python -m pipeline.cli registry --object " + args.object)
        return
    docs = read_jsonl(docs_path)
    sheets_path = os.path.join(OUT, args.object, "sheets.jsonl")
    sheets = read_jsonl(sheets_path) if os.path.exists(sheets_path) else None
    # Номер изменения из штампа читается по документу и от остальных не зависит: при
    # дозагрузке (#60) читаются только новые документы, прежние берутся из прошлого разбора.
    # Цепочки редакций собираются заново — они связывают документы между собой.
    want = _file_ids(args)
    tb_path = os.path.join(OUT, args.object, "titleblock_revisions.json")
    if want is not None and not os.path.exists(tb_path):
        want = None          # прошлых штампов нет — читаем все документы
    todo = [d for d in docs if want is None or d["file_id"] in want]
    tb = revisions.titleblock_revisions(todo, OBJECTS[args.object]["root"], workers=args.workers)
    if want is not None:
        tb = {**{k: v for k, v in (_read_json(tb_path) or {}).items() if k not in want}, **tb}
    with open(tb_path, "w", encoding="utf-8") as f:
        json.dump(tb, f, ensure_ascii=False, indent=2)
    manual = getattr(args, "manual", None) or {}
    out_docs, chains = revisions.analyse(args.object, docs, sheets, tb,
                                         root=OBJECTS[args.object]["root"],
                                         require_approval=args.require_approval, manual=manual)
    # цепочка по именам проверяется содержимым: тома разных корпусов с одной маркой — не редакции (#19)
    from pipeline import revision_diff
    root = OBJECTS[args.object]["root"]
    # сравнение редакций читает слой и у сканов со штампом: распознанные сканы одного листа
    # расходятся шумом (#116)
    chains, out_docs = revision_diff.verify_chains(chains, out_docs,
                                                   lambda d: matrix_rules.page_texts(d, root, scans=False))
    write_jsonl(docs_path, out_docs)
    path = write_jsonl(os.path.join(OUT, args.object, "revisions.jsonl"), chains)
    s = revisions.summary(out_docs, chains)
    print(f"цепочки редакций: {path}")
    print(f"  источники: связка листов {'есть' if sheets else 'нет'}, "
          f"редакция из штампа у {len(tb)} файлов")
    print(f'  документов {s["documents"]}, уникальных {s["unique"]}, дублей по SHA-256 {s["duplicates"]}')
    print(f'  с маркой {s["with_mark"]}, с отметкой редакции {s["with_revision_mark"]}, '
          f'раздел не определён {s["section_other"]}, с признаком утверждения {s["approved"]}')
    print(f'  цепочек {s["chains"]}, из них с несколькими редакциями {s["chains_with_revisions"]}: '
          f'актуальная определена {s["resolved"]}, требует уточнения {s["clarification"]}'
          + (f', по выбору инспектора {sum(1 for c in chains if c.get("resolved_by") == "INSPECTOR")}' if manual else "")
          + f', не редакции по содержимому {sum(1 for c in chains if c.get("status") == "UNRELATED")}')
    kinds = collections.Counter(c["reason"].split(":")[0] for c in chains
                                if c["status"] == "CLARIFICATION_REQUIRED")
    for kind, n in kinds.most_common():
        print(f"    {n:3d}  {kind}")


def _sheet_numbers(object_id):
    """Номер листа по (файл, страница) из связки листов: только подтверждённые соседями."""
    path = os.path.join(OUT, object_id, "sheets.jsonl")
    if not os.path.exists(path):
        return {}
    return {(r["file_id"], r["pdf_page_number"]): r["document_sheet_number"] for r in read_jsonl(path)
            if r.get("document_sheet_number") is not None and r.get("sheet_check") in ("CONFIRMED", "INFERRED")}


def _file_layers(path, pages=None):
    """Текстовый слой страниц PDF: {страница: слой}; pages — какие страницы, None — все.
    Пустой словарь, если файл не открылся."""
    import pymupdf
    from pipeline import reading
    try:
        doc = pymupdf.open(path)
    except Exception:
        return {}
    try:
        want = range(1, doc.page_count + 1) if pages is None else sorted(p for p in pages if 1 <= p <= doc.page_count)
        return {n: reading.read_text_layer(doc, n) for n in want}
    except Exception:
        return {}
    finally:
        doc.close()


def _revdiff_pair(task):
    """Одна пара редакций: постраничное сравнение (#19), места изменений и отметки (#81).

    Отдельной функцией, чтобы пары шли параллельно. Всё нужное приходит в задаче: реестр
    объектов в процессе-потомке пуст — объект сервиса регистрируется во время разбора.
    Отметки читаются только у рабочей документации (`revision_diff.UNMARKED_STAGES`): для них
    нужен слой всех страниц обеих редакций, а у томов проекта хватает изменённых страниц
    и их соседей: текст, сдвинувшийся на соседние страницы, — не изменение.
    """
    from pipeline import revision_diff
    object_id, pair, old_doc, new_doc, root, sheets = task
    old_id, new_id = pair["old_file_id"], pair["new_file_id"]
    pair_id = f"{object_id}::REV::{old_id}-{new_id}"
    rows, summary = revision_diff.compare(list(matrix_rules.page_texts(old_doc, root, scans=False)),
                                          list(matrix_rules.page_texts(new_doc, root, scans=False)))
    marked = pair.get("stage_group") in revision_diff.UNMARKED_STAGES
    changed = [r for r in rows if r["status"] in ("CHANGED", "UNREADABLE")]

    def layers(doc, pages):
        if (doc.get("extension") or "").lower() != ".pdf":
            return {}
        return _file_layers(os.path.join(root, doc["relative_path"]), None if marked else pages)

    # и соседние страницы: текст записки при правке перетекает на них
    near = lambda pages: {p + d for p in pages for d in (-1, 0, 1)}  # noqa: E731
    old_layers = layers(old_doc, near({r["old_page"] for r in changed}))
    new_layers = layers(new_doc, near({r["new_page"] for r in changed}))
    # штампы документооборота стоят на каждой странице файла на одном месте
    repeated_old = revision_diff.furniture(old_layers.values())
    repeated_new = revision_diff.furniture(new_layers.values())
    streams = {}

    def stream(side, page):
        if (side, page) not in streams:
            layer = (old_layers if side == "old" else new_layers).get(page)
            streams[side, page] = revision_diff.page_stream(layer, repeated_old if side == "old" else repeated_new)
        return streams[side, page]

    for r in changed:
        p, q = r["old_page"], r["new_page"]
        if p in old_layers and q in new_layers:
            where = revision_diff.place(old_layers[p], new_layers[q], repeated_old, repeated_new,
                                        old_near=(stream("old", p - 1), stream("old", p + 1)),
                                        new_near=(stream("new", q - 1), stream("new", q + 1)))
            if where:
                r["place"] = where
    reg, found = None, []
    # пара, не похожая на переиздание (том в 1 страницу против тома в 66), — не про изменения листов
    if marked and old_layers and new_layers and summary["looks_like_revision"] is not False:
        reg = revision_diff.registration(rows, revision_diff.file_marks(sorted(old_layers.items())),
                                         revision_diff.file_marks(sorted(new_layers.items())),
                                         lambda page: sheets.get((new_id, page)))
        found = revision_diff.unmarked(object_id, {**pair, "pair_id": pair_id, "introduced": reg["introduced"]},
                                       rows, "RD", code=new_doc.get("document_code") or pair.get("mark"))
    out = [{"kind": "pair", "pair_id": pair_id, "object_id": object_id, **pair, **summary,
            "old_document": os.path.basename(old_doc["relative_path"]),
            "new_document": os.path.basename(new_doc["relative_path"]),
            "registration": reg, "unmarked": len(found)}]
    for r in rows:
        if r["status"] not in ("SAME", "NO_TEXT"):
            old_sheet = sheets.get((old_id, r["old_page"])) if r.get("old_page") else None
            sheet = sheets.get((new_id, r["new_page"])) if r.get("new_page") else None
            if sheet is None:
                sheet = old_sheet
            # в записке страницы сдвигаются: лист 30 прежней редакции — лист 32 новой
            out.append({"kind": "page", "pair_id": pair_id, "object_id": object_id,
                        "old_file_id": old_id, "new_file_id": new_id, **r, "sheet": sheet, "old_sheet": old_sheet,
                        "content_changed": revision_diff.content_changed(r),
                        "what": revision_diff.describe(r)})
    return out, found


def cmd_revdiff(args):
    """Постраничное сравнение пар редакций из цепочек (#19): что изменилось в переиздании.

    Где на листе изменилось и отмечено ли изменение (#81) — по словам текстового слоя обеих
    редакций: сравнение по месту (`revision_diff.place`) и отметки в штампах и ведомости
    (`revision_diff.registration`). Листы рабочей документации, изменённые без отметки, —
    гипотезы свободного поиска в `findings_revisions.jsonl`: в сдачу они не идут, пока
    инспектор их не взял. Пары считаются параллельно (`--workers`).
    """
    import multiprocessing
    docs = {d["file_id"]: d for d in read_jsonl(os.path.join(OUT, args.object, "documents.jsonl"))}
    chains_path = os.path.join(OUT, args.object, "revisions.jsonl")
    if not os.path.exists(chains_path):
        print("сначала соберите цепочки: python -m pipeline.cli revisions --object " + args.object)
        return
    from pipeline import revision_diff
    pairs, unordered = revision_diff.pairs_of(read_jsonl(chains_path))
    root = OBJECTS[args.object]["root"]
    sheets = _sheet_numbers(args.object)
    tasks = []
    for pair in pairs:
        old_doc, new_doc = docs.get(pair["old_file_id"]), docs.get(pair["new_file_id"])
        if old_doc and new_doc:
            own = {k: v for k, v in sheets.items() if k[0] in (pair["old_file_id"], pair["new_file_id"])}
            tasks.append((args.object, pair, old_doc, new_doc, root, own))
    t0 = time.time()
    workers = max(1, min(getattr(args, "workers", None) or 4, len(tasks)))
    if workers > 1:
        with multiprocessing.Pool(workers) as pool:
            results = pool.map(_revdiff_pair, tasks, chunksize=1)
    else:
        results = [_revdiff_pair(t) for t in tasks]
    out, hypotheses = [], []
    for n, (rows, found) in enumerate(results, 1):
        out += rows
        hypotheses += found
        p, reg = rows[0], rows[0]["registration"]
        print(f"  {n}/{len(tasks)} {p['old_file_id']} → {p['new_file_id']} ({p['mark']}): "
              f"страниц {p['old_pages']} → {p['new_pages']}, без изменений {p['same']}, "
              f"изменено {p['changed']}, добавлено {p['added']}, удалено {p['removed']}, "
              f"слой не читается {p['unreadable']}, без текста {p['no_text']}"
              + ("" if p["looks_like_revision"] else " — на переиздание не похоже")
              + (f"; изменения {', '.join(map(str, reg['introduced']))}: отмечено {reg.get('registered', 0)}, "
                 f"без отметки {reg.get('unregistered', 0)}, только служебные поля {reg.get('not_needed', 0)}"
                 if reg and reg["introduced"] else ""))
    path = write_jsonl(os.path.join(OUT, args.object, "revision_diff.jsonl"), out)
    # решение специалиста по виду (Р-108, Р-116): «гипотеза», пометка — в конце пояснения
    from pipeline import specialist
    hypotheses, spec_stats = specialist.apply(hypotheses)
    hyp_path = write_jsonl(os.path.join(OUT, args.object, "findings_revisions.jsonl"), hypotheses)
    print(f"сравнение редакций: {path}")
    print(f"  пар {len(tasks)}, цепочек без порядка (пропущены) {unordered}, {time.time() - t0:.0f} с")
    print(f"  гипотез «лист изменён без отметки»: {len(hypotheses)} — {hyp_path}; решения специалиста: {spec_stats}")


def cmd_rooms(args):
    """Реестр помещений объекта из экспликаций.

    При дозагрузке (#60) экспликации разбираются только у новых документов, прежние
    строки берутся из `rooms_pages.jsonl`, а счётчики разбора — из `rooms_stats.json`:
    доля неразобранных строк должна остаться долей по всему объекту.
    """
    want = _file_ids(args)
    pages_path = os.path.join(OUT, args.object, "rooms_pages.jsonl")
    if want is not None and not os.path.exists(pages_path):
        want = None          # прошлого разбора экспликаций нет — считаем весь объект
    per_page = []
    by_file = {}
    for row, got in _cached_pages(args.object, want):
        items, stats = rooms_mod.parse_page_full(got["words"], got["text"])
        acc = by_file.setdefault(row["file_id"], {"rows": 0, "parsed": 0, "unparsed": 0, "shapes": []})
        for k in ("rows", "parsed", "unparsed"):
            acc[k] += stats[k]
        acc["shapes"] = sorted(set(acc["shapes"]) | set(stats["shapes"]))
        if items:
            per_page.append((row["file_id"], row["pdf_page_number"], items))
    stats_path = os.path.join(OUT, args.object, "rooms_stats.json")
    if want is not None:
        by_file = {**{k: v for k, v in (_read_json(stats_path) or {}).items() if k not in want}, **by_file}
        per_page = _group_room_pages(incremental.keep(read_jsonl(pages_path), want)) + per_page
    per_page.sort(key=lambda t: (t[0], t[1]))
    total = {k: sum(v[k] for v in by_file.values()) for k in ("rows", "parsed", "unparsed")}
    shapes = {s for v in by_file.values() for s in v["shapes"]}
    pages_with = len(per_page)
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(by_file, f, ensure_ascii=False, indent=2)
    reg = rooms_mod.merge(per_page)
    # Экспликации постранично: реестр выше сводит номер к одной записи, а сверке наименований
    # нужно знать, как номер назван в каждой стадии и в каждом томе (#46)
    stages = {d["file_id"]: d.get("stage") for d in read_jsonl(os.path.join(OUT, args.object, "documents.jsonl"))}
    write_jsonl(os.path.join(OUT, args.object, "rooms_pages.jsonl"),
                [{"file_id": fid, "stage": stages.get(fid), "pdf_page_number": page, "number": it["number"],
                  "name": it["name"], "area_m2": it["area_m2"], "category": it.get("category"),
                  "labeled": it.get("labeled", False), "table": it.get("table")}
                 for fid, page, items in per_page for it in items])
    path = write_jsonl(os.path.join(OUT, args.object, "rooms.jsonl"), reg)
    print(f"реестр помещений: {path}")
    print(f"  страниц с экспликацией {pages_with}, помещений {len(reg)}")
    named = sum(1 for r in reg if r["name"])
    print(f"  с наименованием {named}, с площадью {sum(1 for r in reg if r['area_m2'])}")
    # доля строк, которые начинаются номером, но записью не стали: по ней видно,
    # разобралась экспликация или только притворилась разобранной (#41)
    share = round(total["unparsed"] / total["rows"], 4) if total["rows"] else 0.0
    report = {**total, "share_unparsed": share, "number_shapes": sorted(shapes),
              "pages_with_explication": pages_with, "rooms": len(reg)}
    with open(os.path.join(OUT, args.object, "rooms_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'  строк с номером {total["rows"]}, из них не разобрано {total["unparsed"]} '
          f'({share * 100:.1f} %), формы номеров {sorted(shapes)}')


# длинная сторона чертёжного листа в пунктах: А4 — 842, А3 — 1191
MIN_SHEET_PT = 1000


def cmd_plans(args):
    """Помещения, найденные на чертежах по координатам слов. Задача #4."""
    out, with_rooms = [], 0
    for row, got in _cached_pages(args.object):
        # Классификатор reading.classify относит все листы формата А3 и крупнее
        # (длинная сторона >= 1000 pt) к DRAWING независимо от числа слов (задача #20).
        # Поэтажные планы этажей с помещениями выполняются строго на А3 и крупнее.
        # Альбомные листы А4 могут иметь тип DRAWING при малом числе слов (например,
        # небольшие схемы или ведомости), но строительными планами не являются и несут
        # ложный шум из таблиц (как в сметах F0186). Поэтому отбираем чертежи формата А3+.
        if max(got.get("width_pt") or 0, got.get("height_pt") or 0) < MIN_SHEET_PT:
            continue
        items = plan_rooms.extract(got["words"],
                                   page_size=(got.get("width_pt"), got.get("height_pt")))
        if not items:
            continue
        with_rooms += 1
        for it in items:
            out.append({"file_id": row["file_id"], "stage": row.get("stage"),
                        "pdf_page_number": row["pdf_page_number"], **it})
    path = write_jsonl(os.path.join(OUT, args.object, "plan_rooms.jsonl"), out)
    marks = sum(1 for r in out if r["marks"])
    print(f"помещения на чертежах: {path}")
    print(f"  листов с помещениями {with_rooms}, записей {len(out)},"
          f" уникальных номеров {len({r['number'] for r in out})}")
    print(f"  с маркой инженерной системы {marks}")
    counts = collections.Counter(m[0] for r in out for m in r["marks"])
    print(f"  марки по первой букве: {dict(counts.most_common(6))}")


def cmd_systems(args):
    """Таблицы характеристик систем ОВ и пары листов ПД — РД. Задачи #21 и #37."""
    from pipeline import room_compare, sheet_pairs
    import time
    t0 = time.time()

    def progress(n, total, pages):
        print(f"  документов {n} из {total}, листов разобрано {pages}", end="\r", flush=True)

    rows, summary = room_compare.collect_systems(args.object, use_ocr=not args.no_ocr, progress=progress)
    path = write_jsonl(os.path.join(OUT, args.object, "hvac_systems.jsonl"), rows)
    print(f"\nтаблицы систем: {path}  ({time.time() - t0:.0f} с)")
    for key in ("документов", "документов с таблицей", "листов разобрано", "ячеек распознано",
                "листов без распознавания"):
        print(f"  {key:26} {summary.get(key, 0)}")
    by_stage = collections.Counter((r["stage"], r["file_id"], r["pdf_page_number"]) for r in rows)
    for (stage, fid, page), n in sorted(by_stage.items()):
        print(f"  {stage} {fid} стр. {page}: строк {n}")
    doubtful = sum(1 for r in rows if r.get("rooms_doubtful"))
    print(f"  строк с помещениями {sum(1 for r in rows if r['rooms'])}, с неуверенно прочитанным номером {doubtful}")

    documents = {d["file_id"]: d for d in read_jsonl(os.path.join(OUT, args.object, "documents.jsonl"))}
    hvac = {fid for fid, d in documents.items() if d.get("section") == "OV"} | {r["file_id"] for r in rows}
    plan_rows = room_compare._plan_rows(args.object, documents, hvac)
    keys = {(r["file_id"], r["pdf_page_number"]) for r in plan_rows}
    paired = sheet_pairs.pairs(plan_rows, documents, room_compare._titles(documents, keys, OBJECTS[args.object]["root"]))
    flat = [{"pd_file_id": k[0], "pd_page": k[1], "rank": i + 1, **r}
            for k, found in sorted(paired.items()) for i, r in enumerate(found)]
    path = write_jsonl(os.path.join(OUT, args.object, "sheet_pairs.jsonl"), flat)
    print(f"пары листов: {path}")
    print(f"  проектных листов с парой {len(paired)}, всего пар {len(flat)}")


def cmd_free(args):
    """Свободный поиск: предусмотрено проектом для помещений — нет в рабочей документации (#31)."""
    from pipeline import free_search
    docs = read_jsonl(os.path.join(OUT, args.object, "documents.jsonl"))
    root = OBJECTS[args.object]["root"]
    pages = {"PD": [], "RD": []}
    with_doc = []               # (документ, страница, текст): разбору профиля нужен путь файла
    for d in docs:
        stage = matrix_rules.STAGE.get(d.get("stage"))
        if stage not in pages or d.get("duplicate_of") \
                or (d.get("extension") or "").lower() not in matrix_rules.READABLE_EXT:
            continue
        for page, text in matrix_rules.page_texts(d, root):
            pages[stage].append((d["file_id"], page, text, d.get("section")))
            with_doc.append((dict(d, stage=stage), page, text))
    findings, stats = free_search.search(args.object, pages["PD"], pages["RD"])
    # понижение прокатного профиля распорной системы между стадиями (#106)
    from pipeline import steel
    profile = steel.profile_findings(args.object, with_doc)
    findings += profile
    # экспликации между стадиями: пропавшее помещение, площадь, категория (#56)
    from pipeline import room_explications, room_names
    rows = read_jsonl(os.path.join(OUT, args.object, "rooms_pages.jsonl"))
    names = room_names.load(args.object, OUT)
    sha = {d["file_id"]: d.get("sha256") for d in docs}

    def text_of(file_id, page):
        got = reading.cache_get(sha.get(file_id) or "", page, "read") if sha.get(file_id) else None
        return (got or {}).get("text") or ""

    # экспликации заменённых редакций не голосуют за площадь стадии (#10, #100)
    superseded = {d["file_id"] for d in docs if not d.get("duplicate_of") and d.get("revision_status") == "SUPERSEDED"}
    # подписи томов — для пояснения гипотезы «рабочая стадия не обновлена после корректировки» (#111)
    volumes = {d["file_id"]: " ".join(x for x in (d.get("mark") or os.path.splitext(os.path.basename(d["relative_path"]))[0][:40],
                                                  d.get("revision")) if x)
               for d in docs if not d.get("duplicate_of")}
    chain_of = {d["file_id"]: d.get("chain_id") for d in docs if not d.get("duplicate_of") and d.get("chain_id")}
    explication, ex_stats = room_explications.compare(args.object, rows, names, text_of=text_of,
                                                      superseded=superseded, volumes=volumes, chain_of=chain_of)
    findings += explication
    # поэтажная сверка там, где номера помещений на каждом этаже начинаются заново (#114):
    # том проекта сверяется с томами рабочей стадии того же шифра
    revisions = _read_jsonl_if(os.path.join(OUT, args.object, "revisions.jsonl"))
    code_base = {fid: detail.get("code_base") for chain in revisions
                 for fid, detail in (chain.get("member_detail") or {}).items()}
    floors, floor_stats = room_explications.compare_floors(args.object, rows, code_base, superseded,
                                                           {d["file_id"]: d.get("section") for d in docs})
    findings += floors
    # штампы квартир на планах АР действующих редакций: площади одинаковых квартир (#100)
    from pipeline import apartment_areas
    current = apartment_areas.current_files(docs, revisions)
    flats, flat_stats = apartment_areas.compare(args.object, [
        (stage, fid, page, text) for stage in ("PD", "RD") for fid, page, text, section in pages[stage]
        if section == "AR" and fid in current])
    findings += flats
    # решения специалиста по видам гипотез: подтверждённые — в сдачу, остальные с его словами (Р-86, Р-108)
    from pipeline import specialist
    section = {d["file_id"]: d.get("section") for d in docs}
    findings, spec_stats = specialist.apply(findings, section.get)
    path = write_jsonl(os.path.join(OUT, args.object, "findings_free.jsonl"), findings)
    print(f"свободный поиск: {path}")
    print(f"  решения специалиста: {spec_stats}")
    print(f"  страниц: проектных {len(pages['PD'])}, рабочих {len(pages['RD'])}; {stats}")
    print(f"  экспликации: {ex_stats}")
    print(f"  экспликации по этажам: {floor_stats}")
    print(f"  квартиры: {flat_stats}")
    for f in profile:
        print(f"  профиль проката: {f['locations'][0]} — {f['extraction']['detail'][:130]}")
    for f in findings:
        where = ", ".join(f["locations"][:6]) + ("…" if len(f["locations"]) > 6 else "")
        label = "пом." if f.get("location_type") == "ROOM" and where[:1].isdigit() else ""
        print(f"  гипотеза: {label} {where} — {f['pd_value'][:70]}")


def cmd_vlm(args):
    """Проход модели по чертежам: прицельный вопрос правила к листу. Задача #98.

    Сами правила модель не вызывают: проход складывает ответы в build/<объект>/vlm_values.jsonl,
    а правило с `kind: vlm_value` берёт значения оттуда. Так прогон правил остаётся быстрым
    и бесплатным, а расход вызовов и денег виден здесь и в протоколе. Правило `door_opening`
    (AR-043) спрашивает не число, а перечень дверей с направлением открывания (`vlm.answer: "doors"`).
    """
    from pipeline import vlm_values
    _load_env()
    pages_path = os.path.join(OUT, args.object, "pages.jsonl")
    docs_path = os.path.join(OUT, args.object, "documents.jsonl")
    if not (os.path.exists(pages_path) and os.path.exists(docs_path)):
        print("нужны реестр и постраничный индекс: registry и pages")
        return
    pages = read_jsonl(pages_path)
    docs = {d["file_id"]: d for d in read_jsonl(docs_path)}
    root = OBJECTS[args.object]["root"]
    # заменённые редакции не спрашиваются: иначе потолок листов уходит на прежние выпуски. Копии
    # не в счёт: у копии идентификатор оригинала (ДОО), и пометка копии выбросила бы оригинал
    superseded = {d["file_id"] for d in read_jsonl(docs_path)
                  if not d.get("duplicate_of") and d.get("revision_status") == "SUPERSEDED"}

    wanted = {}
    for q, path in sorted(matrix_rules.QUEUES.items()):
        # с `--provisional` спрашиваются и черновики правил (#95): ответы ложатся в тот же файл,
        # у каждого параметра свои строки, прод-правила читают только свои коды
        rules = (matrix_rules.load_provisional(q) or {"parameters": {}}) if getattr(args, "provisional", False) \
            else matrix_rules.load_rules(path)
        for code, rule in rules["parameters"].items():
            if rule.get("kind") not in vlm_values.VLM_KINDS or not rule.get("implemented"):
                continue
            if args.code and code != args.code:
                continue
            wanted[code] = rule
    if not wanted:
        print("правил с вопросом к чертежу нет" + (f" по коду {args.code}" if args.code else ""))
        return

    import pymupdf
    from concurrent.futures import ThreadPoolExecutor, as_completed
    out_rows, stats = [], collections.Counter()
    budget = args.limit
    use_cache = not getattr(args, "fresh", False)
    progress = getattr(args, "progress", None)
    workers = max(1, int(getattr(args, "workers", None) or vlm_values.WORKERS))
    # Прежние строки файла: лист, до которого не дошёл потолок вызовов, сохраняет свой ответ.
    # Потолок ограничивает новые вызовы, а не ответы из кеша: пересборка с потолком 0
    # (`tools/rebuild.py`) берёт всё из кеша и не тратит денег
    before = {(r.get("parameter_code"), r.get("file_id"), r.get("pdf_page_number")): r
              for r in vlm_values.load(args.object, provisional=getattr(args, "provisional", False))}

    # Сначала перечень листов целиком: так известно, сколько всего спрашивать (ход шага у воркера),
    # и потолок вызовов раздаётся в том же порядке, что и при вопросах по одному
    todo, ask_at = [], []
    for code, rule in wanted.items():
        prompt = (rule.get("vlm") or {}).get("prompt")
        if not prompt:
            print(f"  {code}: у правила нет vlm.prompt")
            continue
        sheets = vlm_values.sheets_for(rule, pages, limit=args.sheets, skip=superseded)
        # Потолок листов ограничивает новые вызовы, а не ответы из кеша: лист за потолком, по
        # которому ответ уже есть, спрашивать не нужно, и его значение не теряется. Отбор идёт в
        # порядке тома: у Речникова «Спецификация металлических ограждений балконов» (F0334, стр. 23)
        # — седьмой подходящий лист рабочей стадии, и при потолке 6 AR-049 оставался без неё
        beyond = 0
        if use_cache and args.sheets:
            chosen = {(f, p) for f, p, _why in sheets}
            for f, p, why in vlm_values.sheets_for(rule, pages, skip=superseded):
                row = docs.get(f)
                if (f, p) not in chosen and row and vlm_values.cached_answer(row["sha256"], p, code, prompt):
                    sheets.append((f, p, why + ", за потолком, ответ в кеше"))
                    beyond += 1
        print(f"  {code}: листов отобрано {len(sheets)}" + (f", из них за потолком с ответом в кеше {beyond}" if beyond else ""))
        for file_id, page_no, why in sheets:
            doc_row = docs.get(file_id)
            if not doc_row:
                continue
            cached = use_cache and vlm_values.cached_answer(doc_row["sha256"], page_no, code, prompt)
            if args.dry:
                print(f"     {file_id}/{page_no} {why}")
                stats["листов в сухом прогоне"] += 1
                continue
            if budget <= 0 and not cached:
                todo.append((code, rule, file_id, page_no, None))
                continue
            if not cached:
                budget -= 1
            ask_at.append(len(todo))
            todo.append((code, rule, file_id, page_no, doc_row))

    def ask_one(i):
        code, rule, file_id, page_no, doc_row = todo[i]
        path = os.path.join(root, doc_row["relative_path"])
        with vlm_values.PDF_LOCK:
            try:
                pdf = pymupdf.open(path)
            except Exception as e:
                return {"open_error": type(e).__name__}
        try:
            return vlm_values.ask(pdf, page_no, doc_row["sha256"], code, rule["vlm"]["prompt"],
                                  model=args.model, use_cache=use_cache)
        finally:
            with vlm_values.PDF_LOCK:
                pdf.close()

    # Вопросы к модели — в потоках: время прохода — это ожидание ответов, а своя модель
    # отвечает на несколько сразу. Ответы разбираются потом по порядку перечня, так что файл
    # значений от числа потоков не зависит
    answers, done = {}, len(todo) - len(ask_at)
    if progress and todo:
        progress(done, len(todo))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(ask_one, i): i for i in ask_at}
        for future in as_completed(futures):
            answers[futures[future]] = future.result()
            done += 1
            if progress:
                progress(done, len(todo))

    for i, (code, rule, file_id, page_no, doc_row) in enumerate(todo):
        if doc_row is None:
            stats["лимит вызовов исчерпан"] += 1
            if (code, file_id, page_no) in before:
                out_rows.append(before[(code, file_id, page_no)])
            continue
        got = answers[i]
        if got.get("open_error"):
            print(f"     {file_id}: {got['open_error']}")
            continue
        stats["вызовов" if not got.get("cached") else "из кеша"] += 1
        if vlm_values.failed(got):
            # модель не ответила: вызов не закеширован, лист спросится при следующем проходе,
            # а прежний ответ листа, если он был, остаётся в файле
            stats["ошибка модели"] += 1
            if (code, file_id, page_no) in before:
                out_rows.append(before[(code, file_id, page_no)])
            continue
        stats_cost = got.get("cost_usd") or 0.0
        want = rule.get("vlm") or {}
        page_text = next((p.get("text") for p in pages
                          if p["file_id"] == file_id and p["pdf_page_number"] == page_no), "")
        if want.get("answer") == "doors":
            # перечень дверей с направлением открывания (AR-043, #191): дверь принимается, если её
            # марка или помещение есть в тексте листа
            asked_doors = vlm_values.parse_doors(got.get("text"))
            doors, how = vlm_values.confirmed_doors(asked_doors, page_text) if asked_doors else ([], "нет дверей")
            stats[f"ответ: {how}"] += 1
            if len(doors) < len(asked_doors):
                stats["дверей отброшено: нет на листе"] += len(asked_doors) - len(doors)
            if doors:
                out_rows.append({"object_id": args.object, "parameter_code": code,
                                 "file_id": file_id, "pdf_page_number": page_no, "values": [], "doors": doors,
                                 "answer": (got.get("text") or "")[:400], "confirmed_by": how,
                                 "what": want.get("what") or code, "model": got.get("model"),
                                 "cost_usd": stats_cost, "ms": got.get("ms"), "max_px": got.get("max_px")})
                stats["дверей принято"] += len(doors)
            continue
        parsed = vlm_values.parse_numbers(got.get("text"), unit=rule.get("unit"))
        values = vlm_values.in_range(parsed, want)
        if len(values) < len(parsed):
            stats["значений отброшено: вне пределов параметра"] += len(parsed) - len(values)
        asked = values
        values, how = (vlm_values.confirmed_values(values, page_text, want.get("confirm_near"),
                                                   want.get("confirm_form"))
                       if values else ([], "нет чисел"))
        ok = bool(values)
        stats[f"ответ: {how}"] += 1
        if len(values) < len(asked):
            stats["значений отброшено: нет на листе"] += len(asked) - len(values)
        if values and ok:
            out_rows.append({"object_id": args.object, "parameter_code": code,
                             "file_id": file_id, "pdf_page_number": page_no,
                             "values": values, "unit": rule.get("unit"),
                             "answer": (got.get("text") or "")[:400], "confirmed_by": how,
                             "what": (rule.get("vlm") or {}).get("what") or code,
                             "model": got.get("model"), "cost_usd": stats_cost,
                             "ms": got.get("ms"), "max_px": got.get("max_px")})
            stats["значений принято"] += len(values)
        elif values:
            stats["ответ не подтверждён текстом листа"] += 1
    if args.dry:
        print(f"  сухой прогон: {dict(stats)}")
        return stats
    # Значения других параметров из файла не теряются: проход мог быть вызван с `--code`,
    # и тогда переписываются только строки спрошенных параметров. Сухой прогон не пишет вовсе:
    # иначе `--dry` обнулял бы уже прочитанные значения
    provisional = getattr(args, "provisional", False)
    keep = [r for r in vlm_values.load(args.object, provisional=provisional) if r.get("parameter_code") not in wanted]
    path = write_jsonl(vlm_values.path_for(args.object, provisional=provisional), keep + out_rows)
    cost = sum(r.get("cost_usd") or 0 for r in out_rows)
    print(f"проход модели: {path}")
    print(f"  {dict(stats)}")
    doors = sum(len(r.get("doors") or ()) for r in out_rows)
    print(f"  принято значений {sum(len(r['values']) for r in out_rows)}" + (f" и дверей {doors}" if doors else "")
          + f" на {len(out_rows)} листах, стоимость ${cost:.4f}")
    # счётчики — воркеру: сколько вызовов потрачено из потолка объекта и сколько не удалось
    return stats


def cmd_acts(args):
    """Разбор актов освидетельствования: XML по схеме Минстроя и текст акта из PDF, DOCX, DOC (#73, #112)."""
    root = OBJECTS[args.object]["root"]
    rows, errors = aosr_xml.scan(root)
    # Акты в PDF: у Новослободской их 80, а XML нет вовсе, и в сверку они не попадали (#73);
    # в DOCX и DOC — у Полярной 25, ДОО 57 актов скрытых работ (#112)
    from pipeline import aosr_text
    docs_path = os.path.join(OUT, args.object, "documents.jsonl")
    pdf_stats = {}
    if os.path.exists(docs_path):
        all_docs = read_jsonl(docs_path)
        pdf_rows, pdf_stats = aosr_text.scan(
            all_docs, lambda d: matrix_rules.page_texts(d, root))
        known = {(r.get("relative_path") or "").replace(os.sep, "/") for r in rows}
        rows += [r for r in pdf_rows
                 if (r.get("relative_path") or "").replace(os.sep, "/") not in known]
    path = write_jsonl(os.path.join(OUT, args.object, "acts.jsonl"), rows)
    print(f"акты: {path}")
    print(f"  разобрано {len(rows)}, ошибок {len(errors)}")
    if pdf_stats:
        print(f"  из текста (PDF, DOCX, DOC): {pdf_stats}")
    if not rows:
        print("  актов у объекта не найдено")
        return
    with_sec = sum(1 for r in rows if r["documentation_sections"])
    with_sheet = sum(1 for r in rows
                     if any(s["sheets"] for s in r["documentation_sections"]))
    with_place = sum(1 for r in rows if any(w.get("place") for w in r["works"]))
    print(f"  со ссылкой на раздел рабочей документации {with_sec}")
    print(f"  с номером листа {with_sheet}")
    print(f"  с указанием места работ {with_place}")
    codes = collections.Counter(s["code"] for r in rows
                                for s in r["documentation_sections"] if s["code"])
    print(f"  шифры разделов: {dict(codes.most_common(6))}")
    for e in errors[:3]:
        print(f"  ошибка: {e['path'][-56:]} {e['error'][:60]}")

    # сверка актов с рабочей документацией: лист, названный актом, и материалы на нём (#42)
    sheets_path = os.path.join(OUT, args.object, "sheets.jsonl")
    docs_path = os.path.join(OUT, args.object, "documents.jsonl")
    if not (os.path.exists(sheets_path) and os.path.exists(docs_path)):
        print("  для сверки с рабочей документацией нужны documents.jsonl и sheets.jsonl")
        return
    docs = read_jsonl(docs_path)
    by_path = {d["relative_path"]: d for d in docs}
    by_id = {d["file_id"]: d for d in docs}
    # материал акта ищется в рабочей документации, а не в самих актах ИД
    sheets = acts_check.rd_sheets(read_jsonl(sheets_path), lambda fid: (by_id.get(fid) or {}).get("stage"))
    spec_root = OBJECTS[args.object]["root"]
    cache = {}

    def page_text(file_id, page):
        doc = by_id.get(file_id)
        if not doc:
            return ""
        if file_id not in cache:
            cache[file_id] = dict(matrix_rules.page_texts(doc, spec_root))
        return cache[file_id].get(page, "")

    def act_file(act):
        rel = (act.get("relative_path") or "").replace(os.sep, "/")
        doc = by_path.get(rel)
        return doc["file_id"] if doc else None

    findings, stats = acts_check.check(args.object, rows, sheets, page_text, act_file)
    # отклонения исполнительных схем против допусков, объявленных на том же листе (#89)
    from pipeline import tolerances
    schemes = tolerances.findings(args.object, docs, page_text)
    findings += schemes
    # номер акта в имени файла не тот, что в документе — дефект комплекта ИД (#112)
    numbers = aosr_text.number_findings(args.object, rows)
    findings += numbers
    # решение специалиста по виду (Р-108): номер акта в имени файла он не показывал бы, но этот
    # дефект комплекта организатор отметил сам (F-0008) — запись остаётся гипотезой с его словами
    from pipeline import specialist
    findings, spec_stats = specialist.apply(findings)
    out = write_jsonl(os.path.join(OUT, args.object, "findings_acts.jsonl"), findings)
    print(f"сверка актов с рабочей документацией: {out}")
    print(f"  записей {len(findings)}, {stats}; решения специалиста: {spec_stats}")
    if schemes:
        over = sum(len((f["extraction"] or {}).get("over") or []) for f in schemes)
        print(f"  исполнительные схемы: записей {len(schemes)}, отклонений больше допуска {over}")
    if numbers:
        print(f"  номер акта в имени файла не совпадает с документом: {len(numbers)}")


def cmd_normrefs(args):
    """Перечень нормативных ссылок корпуса: где записаны с опечаткой, где редакции разные. Задача #18."""
    objects = [args.object] if args.object else sorted(
        d for d in os.listdir(OUT)
        if os.path.exists(os.path.join(OUT, d, "pages.jsonl")) or os.path.exists(os.path.join(OUT, d, "acts.jsonl")))
    entries = []
    for obj in objects:
        pages_path = os.path.join(OUT, obj, "pages.jsonl")
        if os.path.exists(pages_path):
            for row in read_jsonl(pages_path):
                for ref in normrefs.parse(row.get("text")):
                    entries.append({**ref, "object_id": obj, "source": "страницы"})
        acts_path = os.path.join(OUT, obj, "acts.jsonl")
        if os.path.exists(acts_path):
            for row in read_jsonl(acts_path):
                for item in row.get("regulations") or []:
                    for ref in normrefs.parse(f"{item.get('number') or ''} {item.get('name') or ''}"):
                        entries.append({**ref, "object_id": obj, "source": "акты"})
    refs = normrefs.inventory(entries)
    path = write_jsonl(args.out or os.path.join(OUT, "normrefs.jsonl"), refs)
    print(f"нормативные ссылки: {path}")
    print(f"  объектов {len(objects)}, упоминаний {len(entries)}, различных ссылок {len(refs)}")
    kinds = collections.Counter(r["kind"] for r in refs)
    print(f"  по виду документа: {dict(kinds.most_common())}")
    no_year = sum(1 for r in refs if r["year"] is None)
    print(f"  без года редакции {no_year}: сравнить редакции по такой ссылке нельзя")

    typos = [r for r in refs if r["typo_of"]]
    print(f"  записаны с разницей в одну цифру от более частой записи: {len(typos)}")
    for r in typos[:10]:
        print(f"     {r['label']} — {r['mentions']} раз, {r['typo_hint']} против {r['typo_of']}; "
              f"объектов {len(r['objects'])}, где {', '.join(r['sources'])}")

    # документ с несколькими редакциями: настоящий кандидат в расхождения, а не опечатка
    editions = collections.defaultdict(collections.Counter)
    places = collections.defaultdict(set)
    for r in refs:
        if r["year"]:
            editions[r["document"]][r["year"]] += r["mentions"]
            places[r["document"]] |= set(r["objects"])
    many = {k: v for k, v in editions.items() if len(v) > 1}
    print(f"  документов больше чем в одной редакции: {len(many)}")
    for document, years in sorted(many.items(), key=lambda kv: -sum(kv[1].values()))[:10]:
        line = ", ".join(f"{y} ({n})" for y, n in sorted(years.items()))
        print(f"     {document}: {line}; объектов {len(places[document])}")


def cmd_rules(args):
    """Правила Матрицы: первая очередь — ПЗ и СПЗУ (этап 4б), вторая — АР и КР по элементам (#26),
    третья — ППМ и ОДИ (#27), четвёртая — ПОС, ПОД и ЗУ (#28), пятая — ИОС по номерам групп ВРУ и стояков (#29)."""
    import time

    def progress(n, total, pages):
        if n % 20 == 0 or n == total:
            print(f"  документов {n} из {total}, страниц {pages}", end="\r", flush=True)

    queues = sorted(matrix_rules.QUEUES) if args.queue == "all" else [int(args.queue)]
    provisional = getattr(args, "provisional", False)
    for q in queues:
        t0 = time.time()
        if provisional:
            # черновики правил (#95): свой файл находок, прод-очередь не трогается
            rules = matrix_rules.load_provisional(q)
            if not rules:
                continue
            findings, summary = matrix_rules.build_findings(args.object, rules=rules, progress=progress)
            path = write_jsonl(os.path.join(OUT, args.object, f"provisional_q{q}.jsonl"),
                               matrix_rules.mark_provisional(findings))
            print(f"\nчерновики очереди {q}, находки: {path}  ({time.time() - t0:.0f} с)")
            for key in ("VIOLATION_PRESENT", "NO_VIOLATION", "COMPARISON_IMPOSSIBLE", "не найдено"):
                print(f"  {key:24} {summary.get(key, 0)}")
            continue
        rules = matrix_rules.load_rules(matrix_rules.QUEUES[q])
        findings, summary = matrix_rules.build_findings(args.object, rules=rules, progress=progress)
        path = write_jsonl(os.path.join(OUT, args.object, f"findings_matrix_q{q}.jsonl"), findings)
        print(f"\nочередь {q}, находки: {path}  ({time.time() - t0:.0f} с)")
        applicable = matrix_rules.applicability(args.object, rules)
        if applicable:
            # применимость параметров к объекту читает протокол (pipeline/protocol.py)
            write_jsonl(os.path.join(OUT, args.object, f"applicability_q{q}.jsonl"), applicable)
            states = collections.Counter(r["status"] for r in applicable)
            print(f"  применимость: {dict(states)}; {applicable[0]['reason'][:160]}")
        print(f"  страниц прочитано {summary.get('страниц прочитано', 0)}")
        for key in ("VIOLATION_PRESENT", "NO_VIOLATION", "COMPARISON_IMPOSSIBLE",
                    "не найдено", "не реализовано"):
            print(f"  {key:24} {summary.get(key, 0)}")
        if summary.get("решения специалиста"):
            print(f"  решения специалиста по записям: {summary['решения специалиста']}")
        if summary.get("пояснения"):
            print(f"  пояснения: {summary['пояснения']}")
        decided = [f for f in findings if f["violation_label"] in ("VIOLATION_PRESENT", "NO_VIOLATION")]
        if decided:
            print("  решённые:")
            for f in decided:
                where = f" {f['locations'][0]}" if f.get("location_type") == "CONSTRUCTION_ELEMENT" else ""
                print(f"     {f['parameter_code']:9} {f['violation_label']:18} "
                      f"ПД {str(f['pd_value']):20} РД {f['rd_value']}{where}")


# Публичная обучающая разметка: эталон по умолчанию для объектов, у которых он есть
PUBLIC_GOLD = os.path.join(os.path.dirname(OUT), "docs", "extracted", "public_train_checks.jsonl")


def gold_covers(path, object_id):
    """Есть ли в эталоне контрольные точки этого объекта.

    Скорер сравнивает записи по объекту, и эталон чужого объекта даёт не ошибку, а
    бессмысленный балл: F1 нулевой, а комплектность полная. На публичной обучающей части
    точки есть только у Тюменской-5, поэтому объект без точек лучше не «оценивать» вовсе.
    """
    if not path or not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip() and json.loads(line).get("object_id") == object_id:
                return True
    return False


def cmd_run(args):
    """Сквозная нить: объект на входе, файл сдачи и балл на выходе. Задача #8.

    Та же последовательность, что в сервисе (service/worker/steps.py): реестр документов,
    постраничный индекс, основная надпись, акты, правила Матрицы, проекция в формат сдачи.
    Нужна, чтобы весь путь проходился одной командой и без сервиса — и чтобы балл был виден
    сразу, а не после сборки по частям. Чтение кешируется, поэтому повторный прогон дешёвый.
    """
    from argparse import Namespace

    steps = []

    def stage(title, fn):
        print(f"\n== {title}")
        t0 = time.time()
        fn()
        steps.append((title, time.time() - t0))

    stage("реестр документов", lambda: cmd_registry(Namespace(object=args.object)))
    if not args.no_pages:
        stage("постраничный индекс", lambda: cmd_pages(Namespace(
            object=args.object, stage=None, file_ids=None, limit_files=None,
            no_model=args.no_model, model=None, workers=args.workers)))
        stage("основная надпись: шифр и лист", lambda: cmd_sheets(Namespace(
            object=args.object, ocr=args.ocr, workers=args.workers)))
    # редакции и цепочки (#10): правила берут значение из актуальной редакции, конфликт
    # редакций уходит на уточнение
    stage("редакции документов", lambda: cmd_revisions(Namespace(
        object=args.object, workers=args.workers, require_approval=False, manual=None)))
    # что изменилось между редакциями (#19): перечень страниц и строк по парам цепочек
    stage("изменения между редакциями", lambda: cmd_revdiff(Namespace(object=args.object)))
    # экспликации нужны сверке наименований помещений (#46): без них перенумерацию не заметить
    stage("экспликации помещений", lambda: cmd_rooms(Namespace(object=args.object)))
    stage("готовность объекта", lambda: cmd_readiness(Namespace(object=args.object)))
    stage("акты освидетельствования", lambda: cmd_acts(Namespace(object=args.object)))
    # значения, которых в тексте нет вовсе: подписи на чертежах читает модель (#98). Шаг
    # платный и по умолчанию выключен: без него правила `vlm_value` просто не находят
    # значения рабочей стадии, а прогон остаётся бесплатным
    if args.vlm:
        stage("значения с чертежей: проход модели", lambda: cmd_vlm(Namespace(
            object=args.object, code=None, limit=args.vlm_limit, sheets=6,
            model=None, dry=False, fresh=args.vlm_fresh)))
    stage("правила Матрицы", lambda: cmd_rules(Namespace(object=args.object, queue="all")))
    stage("свободный поиск", lambda: cmd_free(Namespace(object=args.object)))

    findings = sorted(glob.glob(os.path.join(OUT, args.object, "findings_matrix_q*.jsonl")))
    # находки вне правил Матрицы: свободный поиск (#31) и сверка актов (#42)
    findings += [p for p in (os.path.join(OUT, args.object, "findings_free.jsonl"),
                             os.path.join(OUT, args.object, "findings_acts.jsonl")) if os.path.exists(p)]
    if not findings:
        raise SystemExit("правила не дали ни одного файла находок: смотрите вывод шага «правила Матрицы»")
    gold = args.score
    if gold is None and gold_covers(PUBLIC_GOLD, args.object):
        gold = PUBLIC_GOLD
        print(f"\nэталон по умолчанию: {os.path.relpath(gold, os.path.dirname(OUT))}")
    elif gold and not gold_covers(gold, args.object):
        print(f"\nв эталоне {gold} нет контрольных точек объекта {args.object}: балл будет бессмысленным")
    stage("формат сдачи и балл", lambda: cmd_submit(Namespace(
        object=args.object, findings=findings, out=args.out, strict=args.strict,
        only_decided=args.only_decided, with_bbox=args.with_bbox, score=gold)))

    print("\nсквозной прогон завершён")
    for title, seconds in steps:
        print(f"  {seconds:6.0f} с  {title}")
    print(f"  {sum(s for _, s in steps):6.0f} с  всего")
    if not gold:
        print(f"  балл не считался: в публичной разметке нет контрольных точек объекта "
              f"{args.object}, задайте свой эталон ключом --score")
    elif not args.only_decided:
        print("  в ответ ушли и записи «сравнение невозможно»; с ключом --only-decided "
              "остаются только «нарушение» и «нарушения нет», и балл выше")


def cmd_submit(args):
    """Проекция находок в формат сдачи организатора. Задача #8."""
    docs_path = os.path.join(OUT, args.object, "documents.jsonl")
    allowed, stage_by_file = None, {}
    if os.path.exists(docs_path):
        rows = read_jsonl(docs_path)
        allowed = {r["file_id"] for r in rows}
        stage_by_file = {r["file_id"]: r.get("stage") for r in rows}
    else:
        print(f"  реестр объекта не найден, ссылки на файлы не проверяются: {docs_path}")

    findings = [f for path in args.findings for f in read_jsonl(path)]
    if args.only_decided:
        # «Сравнение невозможно» против эталона оказывается лишней записью:
        # на первой очереди выгрузка с ними дала 33,86 против 52,75 без них.
        # Нужны ли они организатору — вопрос 5 на встречу.
        findings = [f for f in findings
                    if f.get("violation_label") in ("VIOLATION_PRESENT", "NO_VIOLATION")]
    doc, rep = submission_mod.build(
        args.object, findings, allowed_files=allowed, stage_by_file=stage_by_file,
        keep_evidenceless=not args.strict, with_bbox=args.with_bbox)

    errors = submission_mod.validate(doc)
    out = args.out or os.path.join(OUT, args.object, "submission.json")
    submission_mod.write(out, doc)
    # Отчёт проекции рядом с файлом сдачи: что отброшено, что сведено и что отложено
    # до решения инспектора. Из него сервис берёт записи отложенных гипотез (#63).
    with open(os.path.splitext(out)[0] + "_report.json", "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)

    print(f"сдача: {out}")
    print(f'  находок {rep["findings_in"]}, записей {rep["checks_out"]}'
          f', схлопнуто повторов {rep["duplicates_dropped"]}')
    labels = collections.Counter(c["violation_label"] for c in doc["checks"])
    print(f"  по метке: {dict(labels)}")
    ev = sum(len(c["evidence"]) for c in doc["checks"])
    print(f"  доказательств {ev}, отброшено {len(rep['evidence_dropped'])}")
    for d in rep["evidence_dropped"][:5]:
        print(f'     {d["file_id"]} стр. {d["page"]}: {d["reason"]}')
    if rep["checks_without_evidence"]:
        print(f'  записей без доказательств: {len(rep["checks_without_evidence"])}'
              f' ({"оставлены" if not args.strict else "убраны"})')
    if rep["criticality_from_catalog"]:
        print(f'  критичность взята из каталога вопреки находке:'
              f' {len(rep["criticality_from_catalog"])}')
        for c in rep["criticality_from_catalog"][:3]:
            print(f'     {c["parameter_code"]}: «{c["was"]}» -> «{c["now"]}»')
    if rep["stage_adapted"]:
        files = sorted({a["file_id"] for a in rep["stage_adapted"]})
        print(f'  сведений стадии к стадии файла: {len(rep["stage_adapted"])}'
              f' ({", ".join(files[:6])})')
    if rep["findings_from_other_objects"]:
        print(f'  находок чужого объекта пропущено: {len(rep["findings_from_other_objects"])}')
    for row in rep.get("excluded_by_origin") or []:
        print(f'  не для сдачи: {row["finding_id"]} — {row["reason"]}')
    for row in (rep.get("locations_merged") or [])[:5]:
        print(f'  локации сведены в одну запись: «{row["kept"]}» и «{row["merged"]}» '
              f'({row["parameter_code"]})')
    if errors:
        print(f"  СХЕМА ОРГАНИЗАТОРА НЕ ПРОЙДЕНА, ошибок {len(errors)}:")
        for e in errors[:5]:
            print(f"     {e}")
    else:
        print("  схема организатора пройдена")

    if args.score:
        import subprocess
        scorer = os.path.join(os.path.dirname(OUT), "scoring", "score_submission.py")
        cmd = [sys.executable, "-X", "utf8", scorer, "--submission", out, "--gold", args.score]
        if os.path.exists(docs_path):
            cmd += ["--files-index", docs_path]
        print(flush=True)          # иначе вывод скорера обгоняет наш
        subprocess.run(cmd, check=False)


def fresh_arg(p, rules=True):
    """Флаги полного пересбора кешей разбора: для случаев, которых отпечаток кода не видит."""
    if rules:
        p.add_argument("--fresh", action="store_true",
                       help="собрать заново текст страниц и кандидатов всех правил, не глядя в кеши")
        p.add_argument("--fresh-candidates", action="store_true",
                       help="собрать заново кандидатов всех правил; текст — из кеша")
        p.add_argument("--fresh-rules", metavar="КОДЫ",
                       help="собрать заново кандидатов только этих правил, через запятую: AR-045,KR-055")
    p.add_argument("--fresh-text", action="store_true",
                   help="перечитать текстовый слой PDF и пересобрать текст страниц")
    return p


def apply_fresh(args):
    """Флаги пересбора — в окружение: его читают разбор, инструменты замера и воркер (`matrix_rules`)."""
    parts = {x for x in os.environ.get("PIPELINE_FRESH", "").split(",") if x}
    if getattr(args, "cmd", None) != "vlm" and getattr(args, "fresh", False):
        parts.add("all")
    if getattr(args, "fresh_text", False):
        parts.add("text")
    if getattr(args, "fresh_candidates", False):
        parts.add("candidates")
    if parts:
        os.environ["PIPELINE_FRESH"] = ",".join(sorted(parts))
    if getattr(args, "fresh_rules", None):
        os.environ["PIPELINE_FRESH_RULES"] = args.fresh_rules


def main():
    ap = argparse.ArgumentParser(description="конвейер «Инспектор ИИ»")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("objects", help="какие объекты настроены и доступны")
    p = object_arg(sub.add_parser("registry", help="собрать реестр документов"))
    object_arg(sub.add_parser("readiness",
                              help="готовность объекта: страницы без текста, файлы без стадии и раздела"))
    p = object_arg(sub.add_parser("pages", help="собрать постраничный индекс"))
    p.add_argument("--stage", choices=["PD", "RD", "ID", "RD_ID_MIXED", "UNKNOWN"])
    p.add_argument("--limit-files", type=int, default=0)
    p.add_argument("--file-ids", help="через запятую: F0171,F0201")
    p.add_argument("--no-model", action="store_true", help="только слой и Tesseract")
    p.add_argument("--model", help="идентификатор модели OpenRouter")
    p.add_argument("--workers", type=int, default=6)
    p = fresh_arg(object_arg(sub.add_parser("revdiff", help="постраничное сравнение пар редакций: что изменилось, где "
                                                            "на листе и отмечено ли изменение (#19, #81)")), rules=False)
    p.add_argument("--workers", type=int, default=4, help="сколько пар считать параллельно")
    p = object_arg(sub.add_parser("revisions", help="стадия, марка, редакция и цепочки редакций (#10)"))
    p.add_argument("--workers", type=int, default=4, help="процессов для чтения штампов")
    p.add_argument("--require-approval", action="store_true",
                   help="строго по ТЗ: без признака утверждения актуальная редакция не определена")
    p = object_arg(sub.add_parser("sheets", help="связка «шифр + лист» с номером страницы"))
    p.add_argument("--ocr", action="store_true",
                   help="распознать угол листа там, где текстовый слой номера не дал (#16)")
    p.add_argument("--workers", type=int, default=8)
    for name, help_ in (("rooms", "реестр помещений из экспликаций"),
                        ("plans", "помещения и марки систем с чертежей"),
                        ("acts", "разбор актов освидетельствования из XML"),
                        ("free", "свободный поиск: предусмотрено проектом, нет в рабочей документации")):
        fresh_arg(object_arg(sub.add_parser(name, help=help_)), rules=False)
    p = object_arg(sub.add_parser("vlm", help="проход модели по чертежам: значение, которого нет в тексте (#98)"))
    p.add_argument("--code", help="один параметр, например AR-045")
    p.add_argument("--limit", type=int, default=40, help="потолок вызовов модели за прогон")
    p.add_argument("--sheets", type=int, default=6, help="сколько листов брать на параметр")
    p.add_argument("--model", help="имя модели; по умолчанию выбранная под прод")
    p.add_argument("--dry", action="store_true", help="только показать отобранные листы, без вызовов")
    p.add_argument("--workers", type=int, default=None,
                   help="сколько вопросов к модели держать одновременно; по умолчанию PIPELINE_VLM_WORKERS или 1")
    p.add_argument("--fresh", action="store_true",
                   help="спросить модель заново, не глядя в кеш ответов: вызовы платные")
    p.add_argument("--provisional", action="store_true",
                   help="черновики правил из rules/provisional (#95), а не прод-правила")
    p = sub.add_parser("normrefs", help="перечень нормативных ссылок корпуса: опечатки и редакции")
    p.add_argument("--object", metavar="ИДЕНТИФИКАТОР", help="один объект; по умолчанию все собранные")
    p.add_argument("--out", help="куда положить перечень, по умолчанию build/normrefs.jsonl")
    p = object_arg(sub.add_parser("systems", help="таблицы характеристик систем ОВ и пары листов ПД — РД"))
    p.add_argument("--no-ocr", action="store_true", help="только текстовый слой, ячейки без слоя не распознавать")
    p = object_arg(sub.add_parser(
        "rules", help="правила Матрицы: ПЗ и СПЗУ, АР и КР, ППМ и ОДИ, ПОС, ПОД и ЗУ, ИОС"))
    p.add_argument("--queue", choices=["1", "2", "3", "4", "5", "all"], default="all",
                   help="очередь Матрицы: 1 — ПЗ и СПЗУ, 2 — АР и КР, 3 — ППМ и ОДИ, 4 — ПОС, ПОД и ЗУ, "
                        "5 — ИОС, ООС, СМ; по умолчанию все")
    p.add_argument("--provisional", action="store_true",
                   help="черновики правил из rules/provisional (#95): находки в provisional_q<N>.jsonl, прод не трогается")
    fresh_arg(p)
    p = object_arg(sub.add_parser(
        "run", help="сквозной прогон: реестр, страницы, надпись, акты, правила, файл сдачи и балл"))
    p.add_argument("--score", help="эталон jsonl для балла; у обучающего объекта берётся публичная разметка")
    p.add_argument("--out", help="куда положить submission.json")
    p.add_argument("--no-pages", action="store_true",
                   help="не перечитывать страницы и надпись: идти по уже собранному индексу")
    p.add_argument("--no-model", action="store_true", help="не вызывать модель на сканах и чертежах")
    p.add_argument("--vlm", action="store_true",
                   help="спросить модель о значениях, которых в тексте нет: подписи чертежей (#98)")
    p.add_argument("--vlm-limit", type=int, default=40, help="потолок вызовов модели на объект в этом шаге")
    p.add_argument("--vlm-fresh", action="store_true",
                   help="в шаге прохода модели спросить заново, не глядя в кеш ответов: вызовы платные")
    fresh_arg(p)
    p.add_argument("--ocr", action="store_true", help="распознавать основную надпись на сканах")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--strict", action="store_true",
                   help="убирать записи, у которых не уцелело ни одного доказательства")
    p.add_argument("--only-decided", action="store_true",
                   help="оставить только записи «нарушение» и «нарушения нет»")
    p.add_argument("--with-bbox", action="store_true",
                   help="класть в доказательство прямоугольник в системе координат организатора")
    p = object_arg(sub.add_parser("submit", help="проекция находок в формат сдачи"))
    p.add_argument("--findings", required=True, nargs="+",
                   help="jsonl находок по contracts/finding.schema.json, можно несколько: очереди Матрицы")
    p.add_argument("--out", help="куда положить submission.json")
    p.add_argument("--strict", action="store_true",
                   help="убирать записи, у которых не уцелело ни одного доказательства")
    p.add_argument("--only-decided", action="store_true",
                   help="оставить только записи «нарушение» и «нарушения нет»")
    p.add_argument("--with-bbox", action="store_true",
                   help="необязательный вариант под ТЗ: класть в доказательство "
                        "прямоугольник в системе координат организатора")
    p.add_argument("--score", help="эталон jsonl: сразу прогнать скорер")
    args = ap.parse_args()
    resolve_object(args)
    apply_fresh(args)
    {"objects": cmd_objects, "registry": cmd_registry, "pages": cmd_pages, "readiness": cmd_readiness,
     "sheets": cmd_sheets, "revisions": cmd_revisions, "revdiff": cmd_revdiff, "rooms": cmd_rooms, "plans": cmd_plans,
     "systems": cmd_systems, "acts": cmd_acts, "free": cmd_free, "normrefs": cmd_normrefs, "rules": cmd_rules,
     "vlm": cmd_vlm,
     "run": cmd_run, "submit": cmd_submit}[args.cmd](args)


if __name__ == "__main__":
    main()
