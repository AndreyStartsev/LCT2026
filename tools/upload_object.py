#!/usr/bin/env python3
"""Провести папку объекта через сервис: загрузка, ожидание, протокол. Задача #32.

  python tools/upload_object.py --folder "data/Новослободская" --object-id OBJ-NOVOSLOBODSKAYA

Это условие готовности каркаса, записанное командой: загрузили папку объекта,
получили идентификатор процесса, дождались статуса «готово», забрали протокол
в формате сдачи. Только стандартная библиотека Python, поэтому запускается на любой
машине рядом с `docker compose up`.

Загрузчик — это загрузка «через бэк»: он входит с ролью admin и грузит в маршрут
без лимитов размера (`limits.loader_path`, Р-110). Лимиты ТЗ, файл до 50 МБ и пакет
до 200 МБ, относятся к загрузке инспектором в браузере; в корпусе 115 PDF больше
50 МБ, среди них действующие ПЗ и ПЗУ и тома ИД под гигабайт. С ролью inspector или
с ключом --browser-limits загрузчик идёт по лимитам браузера.

Папка уходит пакетами (по лимиту браузера или по --batch-mb), файлы передаются потоком.
Файлы, которые сервис заведомо не примет (формат, а по лимитам браузера и размер),
не передаются: о них сообщается полем skipped, и сервис записывает отказ по своим правилам.
"""
import argparse
import json
import mimetypes
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.client import HTTPConnection, HTTPSConnection

sys.stdout.reconfigure(line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHUNK = 1 << 20
MB = 1024 * 1024
UPLOAD_PATH = "/api/v1/documents/upload"


def call(api, method, path, token=None, body=None, attempts=20):
    """JSON-запрос к API. Обрыв соединения повторяется: сервис могут перезапустить посреди опроса."""
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            api + path, method=method,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={**({"content-type": "application/json"} if body is not None else {}),
                     **({"authorization": f"Bearer {token}"} if token else {})})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, json.loads(response.read() or b"null"), {
                    k.lower(): v for k, v in response.headers.items()}
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"null"), {k.lower(): v for k, v in error.headers.items()}
        except (urllib.error.URLError, ConnectionError, TimeoutError) as error:
            if attempt == attempts:
                raise
            print(f"  API недоступен ({error}), повтор через 3 с", flush=True)
            time.sleep(3)


def collect(folder, limits):
    """Файлы папки: что передавать и что заведомо не примут. max_file_mb None — без лимита размера."""
    formats = {"." + f.lower() for f in limits["formats"]}
    max_file = limits["max_file_mb"] * MB if limits.get("max_file_mb") else None
    eligible, skipped = [], []
    for dirpath, dirnames, names in os.walk(folder, followlinks=True):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(names):
            if name.startswith("."):
                continue
            path = os.path.join(dirpath, name)
            rel = unicodedata.normalize("NFC", os.path.relpath(path, folder).replace(os.sep, "/"))
            size = os.path.getsize(path)
            ext = os.path.splitext(name)[1].lower()
            if ext not in formats or (max_file is not None and size > max_file):
                skipped.append({"relative_path": rel, "size_bytes": size})
            else:
                eligible.append((path, rel, size))
    return eligible, skipped


def choose_route(limits, role, browser_limits=False):
    """Маршрут загрузки и лимиты для collect. Без лимитов грузит роль admin, если сервис
    знает маршрут загрузчика (limits.loader_path); иначе — лимиты браузера."""
    if limits.get("loader_path") and role == "admin" and not browser_limits:
        return limits["loader_path"], {**limits, "max_file_mb": None, "max_package_mb": None}
    return UPLOAD_PATH, limits


def batches(eligible, max_package):
    """Пакеты не больше max_package байт; файл крупнее идёт отдельным пакетом."""
    out, current, size = [], [], 0
    for item in eligible:
        if current and size + item[2] > max_package:
            out.append(current)
            current, size = [], 0
        current.append(item)
        size += item[2]
    if current:
        out.append(current)
    return out


def multipart(fields, files, boundary):
    """Тело multipart потоком: поля, затем перед каждым файлом его путь внутри папки."""
    def part_header(name, filename=None, content_type=None):
        disposition = f'form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{urllib.parse.quote(filename)}"'
        lines = [f"--{boundary}", f"Content-Disposition: {disposition}"]
        if content_type:
            lines.append(f"Content-Type: {content_type}")
        return ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")

    for name, value in fields:
        yield part_header(name) + value.encode("utf-8") + b"\r\n"
    for path, rel, _size in files:
        yield part_header("relative_path") + rel.encode("utf-8") + b"\r\n"
        yield part_header("files", os.path.basename(path), mimetypes.guess_type(path)[0] or "application/octet-stream")
        with open(path, "rb") as f:
            while block := f.read(CHUNK):
                yield block
        yield b"\r\n"
    yield f"--{boundary}--\r\n".encode("utf-8")


def upload(api, token, fields, files, path=UPLOAD_PATH):
    boundary = uuid.uuid4().hex
    parsed = urllib.parse.urlparse(api)
    conn_cls = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
    conn = conn_cls(parsed.hostname, parsed.port, timeout=600)
    conn.putrequest("POST", path)
    conn.putheader("authorization", f"Bearer {token}")
    conn.putheader("content-type", f"multipart/form-data; boundary={boundary}")
    conn.putheader("transfer-encoding", "chunked")
    conn.endheaders()
    for chunk in multipart(fields, files, boundary):
        conn.send(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
    conn.send(b"0\r\n\r\n")
    response = conn.getresponse()
    body = json.loads(response.read() or b"null")
    conn.close()
    return response.status, body


def validate(protocol):
    schema_path = os.path.join(ROOT, "contracts", "submission.schema.json")
    try:
        import jsonschema
    except ImportError:
        ok = isinstance(protocol.get("checks"), list) and "object_id" in protocol
        return ["jsonschema не установлен, проверена только структура"] if ok else ["нет object_id или checks"]
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    return [e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(protocol)]


def main():
    ap = argparse.ArgumentParser(description="загрузить папку объекта в сервис и забрать протокол")
    ap.add_argument("--api", default="http://localhost:3000")
    ap.add_argument("--folder", help="папка объекта; не нужна с --process-id")
    ap.add_argument("--object-id")
    ap.add_argument("--object-name")
    ap.add_argument("--reading-mode", choices=("layer", "tesseract", "model"),
                    help="способ чтения объекта (#54); по умолчанию — способ сервиса")
    ap.add_argument("--model", help="модель для способа чтения model, из списка сервиса "
                                    "(его видно в /api/v1/health, поле limits.reading_models)")
    ap.add_argument("--login", default="admin",
                    help="учётная запись сервиса; маршрут без лимитов размера доступен роли admin")
    ap.add_argument("--password", default="admin")
    ap.add_argument("--browser-limits", action="store_true",
                    help="грузить по лимитам браузера (ТЗ: файл до 50 МБ, пакет до 200 МБ), как инспектор")
    ap.add_argument("--batch-mb", type=int, default=1024,
                    help="размер пакета без лимитов, МБ: пакеты меньше — повтор после обрыва дешевле")
    ap.add_argument("--out", help="куда положить протокол, по умолчанию protocol-<объект>.json")
    ap.add_argument("--timeout", type=int, default=3 * 3600, help="сколько ждать протокола, секунд")
    ap.add_argument("--process-id", help="без --folder — дождаться протокола идущего процесса; "
                                         "с --folder — дозагрузить папку в этот процесс")
    args = ap.parse_args()

    started = time.monotonic()
    status, body, _ = call(args.api, "POST", "/api/v1/auth/token", body={"login": args.login, "password": args.password})
    if status != 200:
        sys.exit(f"вход не выполнен: {body}")
    token = body["access_token"]
    _, health, _ = call(args.api, "GET", "/api/v1/health")
    limits = health["limits"]
    route, limits = choose_route(limits, body.get("role"), args.browser_limits)
    if route == UPLOAD_PATH and args.folder:
        print(f"лимиты браузера: файл до {limits['max_file_mb']:g} МБ, пакет до {limits['max_package_mb']:g} МБ; "
              "файлы крупнее не передаются"
              + ("" if args.browser_limits or not limits.get("loader_path") else " (без лимитов грузит роль admin)"))

    if args.process_id and not args.folder:
        return wait_and_fetch(args, token, args.process_id, started)
    if not args.folder:
        sys.exit("нужна --folder или --process-id")

    eligible, skipped = collect(args.folder, limits)
    plan = batches(eligible, (limits["max_package_mb"] or args.batch_mb) * MB)
    total = sum(size for *_, size in eligible)
    print(f"папка: {len(eligible)} файлов к загрузке, {total / 2**20:.0f} МБ, пакетов {len(plan)}; "
          f"заведомо не будут приняты {len(skipped)}"
          + ("; маршрут загрузчика, лимитов размера нет" if route != UPLOAD_PATH else ""))

    # --process-id вместе с --folder — дозагрузка в идущий процесс: так меряется,
    # во что обходится добавление одного документа к разобранному объекту (#60)
    process_id, rejected = args.process_id, []
    for i, files in enumerate(plan, 1):
        # способ чтения задаётся при создании процесса (#54): дозагрузка идёт тем же способом
        fields = [("process_id", process_id)] if process_id else [
            (k, v) for k, v in (("object_id", args.object_id), ("object_name", args.object_name),
                                ("reading_mode", args.reading_mode), ("model_name", args.model)) if v]
        fields.append(("final_batch", "true" if i == len(plan) else "false"))
        if i == 1 and skipped:
            fields.append(("skipped", json.dumps(skipped, ensure_ascii=False)))
        t0 = time.monotonic()
        status, body = upload(args.api, token, fields, files, route)
        if status != 202:
            sys.exit(f"пакет {i}: HTTP {status}: {body}")
        process_id = body["process_id"]
        rejected += body["rejected"]
        size = sum(s for *_, s in files)
        print(f"  пакет {i} из {len(plan)}: {len(body['accepted'])} файлов, {size / 2**20:.0f} МБ "
              f"за {time.monotonic() - t0:.0f} с")
    upload_seconds = time.monotonic() - started
    print(f"процесс {process_id}, объект {body['object_id']}; загрузка {upload_seconds:.0f} с, отклонено {len(rejected)}")
    for r in rejected[:10]:
        print(f"    {r['code']}: {r['relative_path']}")
    return wait_and_fetch(args, token, process_id, started)


def wait_and_fetch(args, token, process_id, started):
    last = None
    while True:
        status, st, _ = call(args.api, "GET", f"/api/v1/process/{process_id}/status", token)
        p = st["processing"]
        g = st.get("progress") or {}
        line = f"{st['status']} {p.get('state')} {p.get('step')}"
        if g.get("total"):
            line += f": {g.get('message')} {g.get('done', 0)}/{g['total']}"
        if line != last:
            print(f"  {time.monotonic() - started:6.0f} с  {line}")
            last = line
        if p.get("state") in ("DONE", "FAILED"):
            break
        if time.monotonic() - started > args.timeout:
            sys.exit("протокол не дождались")
        time.sleep(3)
    if p.get("state") == "FAILED":
        sys.exit(f"обработка остановлена: {p.get('error')}")

    status, protocol, headers = call(args.api, "GET", f"/api/v1/process/{process_id}/protocol", token)
    out = args.out or f"protocol-{st['object_id']}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(protocol, f, ensure_ascii=False, indent=2)
    errors = validate(protocol)
    labels = {}
    for c in protocol["checks"]:
        labels[c["violation_label"]] = labels.get(c["violation_label"], 0) + 1
    print(f"протокол: {out}, версия {headers.get('x-protocol-version')}, записей {len(protocol['checks'])}, {labels}")
    print(f"статус загрузки: {st['upload_status']}, сценарий {st['scenario']}")
    print("схема сдачи организатора: " + ("пройдена" if not errors else f"ОШИБКИ {errors[:3]}"))
    print(f"всего {time.monotonic() - started:.0f} с")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
