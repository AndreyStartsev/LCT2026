"""Загрузчик папки: отказ сервиса посреди передачи пакета — код и сообщение, а не трассировка (Р-161).

  python tests/test_upload_broken_pipe_161.py

29.09 на демо-стенде дозагрузка в процесс, который ещё разбирался, упала у загрузчика трассировкой
`BrokenPipeError: [Errno 32] Broken pipe`, а причина — 409 PROCESS_BUSY — осталась в журнале api.
Сервис отклоняет такую дозагрузку по полям, до файлов: отвечает, не дочитав тело, и закрывает
соединение, а загрузчик ломался на отправке следующего куска. Проверяется на подставном API —
локальном http.server, который отвечает на первые байты тела пакета и закрывает соединение:

- 409 PROCESS_BUSY посреди передачи: загрузчик печатает код, сообщение сервиса и что дозагрузку
  повторить после окончания разбора, выходит с кодом 1, трассировки нет;
- сервер закрыл соединение, не ответив: короткое «сервер закрыл соединение до конца загрузки»,
  код 1, трассировки нет;
- ответил прокси страницей 502: статус и текст страницы, трассировки нет;
- у других отказов — код и сообщение без совета про разбор; пакет, который сервис дочитал,
  уходит целиком и получает 202, как раньше.
Загрузчик запускается отдельным процессом, как у пользователя. Файл пакета разреженный: 64 МБ
не занимают места на диске и не помещаются в буферы сокета, так что передача обрывается наверняка.
"""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import upload_object as uo  # noqa: E402

MB = 1024 * 1024
PROCESS = "0d9c3f7e-5b1a-4c2e-9f00-2a6b8e4d1c11"
BUSY = {"error": {"code": "PROCESS_BUSY",
                  "message": "Идёт обработка документов. Дозагрузка станет доступна, когда она закончится",
                  "details": {"process_id": PROCESS}}}
BAD_GATEWAY = (b"<html>\r\n<head><title>502 Bad Gateway</title></head>\r\n<body>\r\n"
               b"<center><h1>502 Bad Gateway</h1></center>\r\n<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n")


def read_chunked(rfile):
    """Тело запроса с Transfer-Encoding: chunked целиком."""
    data = bytearray()
    while size := int(rfile.readline().split(b";")[0], 16):
        data += rfile.read(size)
        rfile.readline()
    rfile.readline()
    return bytes(data)


class Api(http.server.BaseHTTPRequestHandler):
    """Подставной API: вход, лимиты и маршрут загрузчика. Как ответить на пакет — `mode`;
    сколько байт тела пакета прочитано до ответа — `read`, всё тело принятого пакета — `received`."""
    mode, read, received = "busy", 0, b""

    def reply(self, status, body, content_type="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.reply(200, {"limits": {"max_file_mb": 50, "max_package_mb": 200, "formats": ["PDF"],
                                    "loader_path": "/api/v1/documents/bulk"}})

    def do_POST(self):
        if self.path == "/api/v1/auth/token":
            self.rfile.read(int(self.headers["Content-Length"]))
            return self.reply(200, {"access_token": "t", "role": "admin"})
        if Api.mode == "accept":
            Api.received = read_chunked(self.rfile)
            return self.reply(202, {"process_id": PROCESS, "object_id": "OBJ-TEST", "accepted": [], "rejected": []})
        # отказ по первым байтам тела, как у сервиса по полям до файлов: ответ и закрытое соединение
        Api.read = len(self.rfile.read1(64))
        self.close_connection = True
        if Api.mode == "busy":
            self.reply(409, BUSY)
        elif Api.mode == "proxy":
            self.reply(502, BAD_GATEWAY, "text/html")
        # silent — соединение закрывается без ответа

    def log_message(self, *args):
        pass


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def run(api, folder, *extra):
    """Загрузчик как у пользователя, отдельным процессом: код выхода и всё, что он напечатал."""
    command = [sys.executable, os.path.join(ROOT, "tools", "upload_object.py"), "--api", api, "--folder", folder, *extra]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None, "загрузчик не завершился за 120 с"
    return done.returncode, done.stdout + done.stderr


def no_traceback(out):
    ok = check("трассировки нет", "Traceback" not in out)
    if not ok:
        print("\n".join("      " + line for line in out.splitlines()[-12:]))
    return ok


def test_busy(api, folder):
    ok = True
    Api.mode, Api.read = "busy", 0
    code, out = run(api, folder, "--process-id", PROCESS)
    ok &= check("загрузчик вышел с ошибкой, код 1", code == 1, f"код {code}")
    ok &= check("напечатаны HTTP 409, код PROCESS_BUSY и сообщение сервиса",
                f"HTTP 409 PROCESS_BUSY: {BUSY['error']['message']}" in out)
    ok &= check("сказано повторить дозагрузку после окончания разбора процесса",
                f"повторите дозагрузку после окончания разбора процесса {PROCESS}" in out)
    ok &= no_traceback(out)
    ok &= check("передача оборвалась: сервис прочитал только первые байты тела", 0 < Api.read <= 64,
                f"{Api.read} байт из 64 МБ")
    return ok


def test_silent(api, folder):
    ok = True
    Api.mode = "silent"
    code, out = run(api, folder, "--process-id", PROCESS)
    ok &= check("короткое сообщение без ответа сервера, код 1",
                code == 1 and "пакет 1 из 1: сервер закрыл соединение до конца загрузки" in out, f"код {code}")
    ok &= no_traceback(out)
    return ok


def test_proxy(api, folder):
    ok = True
    Api.mode = "proxy"
    code, out = run(api, folder, "--process-id", PROCESS)
    ok &= check("статус и текст страницы прокси, код 1",
                code == 1 and "пакет 1 из 1: HTTP 502: 502 Bad Gateway" in out, f"код {code}")
    ok &= no_traceback(out)
    return ok


def test_other_and_accepted(api):
    ok = True
    finalized = {"error": {"code": "PROCESS_FINALIZED", "message": "Протокол финализирован: дозагрузка невозможна",
                           "details": {"process_id": PROCESS}}}
    text = uo.upload_failure(409, finalized, PROCESS)
    ok &= check("у другого отказа — код и сообщение, без совета про разбор",
                text == "HTTP 409 PROCESS_FINALIZED: Протокол финализирован: дозагрузка невозможна", text)
    Api.mode = "accept"
    content = os.urandom(3 * MB + 17)
    with tempfile.TemporaryDirectory(prefix="upload-accept-") as root:
        path = os.path.join(root, "Том 2.pdf")
        with open(path, "wb") as f:
            f.write(content)
        status, body = uo.upload(api, "t", [("process_id", PROCESS), ("final_batch", "true")],
                                 [(path, "ПД/Том 2.pdf", len(content))], "/api/v1/documents/bulk")
    ok &= check("пакет, который сервис дочитал, получает 202 и тело ответа",
                status == 202 and body.get("process_id") == PROCESS, f"{status} {body}")
    ok &= check("файл дошёл целиком, тело multipart закрыто",
                content in Api.received and Api.received.endswith(b"--\r\n"), f"{len(Api.received)} байт")
    return ok


def main():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Api)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    api = f"http://127.0.0.1:{server.server_address[1]}"
    ok = True
    with tempfile.TemporaryDirectory(prefix="upload-broken-pipe-") as folder:
        os.makedirs(os.path.join(folder, "ПД"))
        with open(os.path.join(folder, "ПД", "Том 1.pdf"), "wb") as f:
            f.truncate(64 * MB)
        for title, fn in (("Отказ посреди передачи: 409 PROCESS_BUSY", lambda: test_busy(api, folder)),
                          ("Сервер закрыл соединение, не ответив", lambda: test_silent(api, folder)),
                          ("Ответил прокси страницей 502", lambda: test_proxy(api, folder)),
                          ("Другие отказы и принятый пакет", lambda: test_other_and_accepted(api))):
            print(f"\n{title}")
            ok &= fn()
    server.shutdown()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
