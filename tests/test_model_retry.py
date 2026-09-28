"""Переспрос обрезанного ответа модели (27.09).

  python tests/test_model_retry.py

На Полярной 16 при потолке ответа 4000 токенов 10 честных ответов из 468 упёрлись в него:
у плотных листов пропал конец страницы. Теперь такой ответ спрашивается ещё раз с потолком
16000, а зациклившийся — нет. Проверяется на подставной модели — локальном сервере с тем же
протоколом /chat/completions:

- обрезанный честный ответ переспрашивается, берётся полный, время и деньги складываются;
- зациклившийся ответ не переспрашивается, место начала повтора записано;
- переспрос, который зациклился или упал, оставляет первый ответ и больше не повторяется;
- прицельный вопрос прохода по чертежам не переспрашивается;
- страница, чей ответ в кеше обрезан старым кодом, читается заново, и текст модели не
  дублируется; переспрошенная страница из кеша модель больше не зовёт.
"""
import http.server
import json
import os
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="test-model-retry-")

import pymupdf  # noqa: E402

from pipeline import reading  # noqa: E402

CUT = "Спецификация оборудования: поз. 1 вентилятор ВР-80; поз. 2 клапан КПУ-1Н"   # обрезан потолком
FULL = CUT + "; поз. 3 заслонка; штамп: 130-1222-ОК-1-Н-ОВ, лист 7"
LOOP = "Спецификация\n" + "Р, Па N, об/мин Тип корпуса Степень защиты IP " * 40


class Model(http.server.BaseHTTPRequestHandler):
    """Подставная модель: отвечает по очереди из `script`, запросы складывает в `seen`."""
    script, seen = [], []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Model.seen.append(body["max_tokens"])
        status, text, finish, tokens = Model.script.pop(0)
        if status != 200:
            self.send_response(status)
            self.end_headers()
            return
        data = {"model": "test-model", "choices": [{"message": {"content": text}, "finish_reason": finish}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": tokens, "cost": tokens / 1e6}}
        raw = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def ask(*script, prompt=None):
    Model.script, Model.seen = list(script), []
    png = os.path.join(TMP, "page.png")
    if not os.path.exists(png):
        pymupdf.open().new_page().get_pixmap().save(png)
    return reading.read_model(png, prompt=prompt)


def main():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    reading.MODEL_URL = f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"
    first, again = reading.MODEL_MAX_TOKENS, reading.MODEL_RETRY_TOKENS

    got = ask((200, CUT, "length", first), (200, FULL, "stop", 5200))
    ok = check("обрезанный честный ответ переспрошен с потолком 16000, взят полный",
               Model.seen == [first, again] and got["text"] == FULL and got.get("retried") is True
               and got["finish_reason"] == "stop", f"{Model.seen} {got.get('finish_reason')}")
    ok &= check("время, токены и деньги обоих вызовов сложены",
                got["tokens_out"] == first + 5200 and got["tokens_in"] == 2000
                and abs(got["cost_usd"] - (first + 5200) / 1e6) < 1e-9 and got["first_tokens_out"] == first)

    got = ask((200, LOOP, "length", first))
    ok &= check("зациклившийся ответ не переспрашивается и отбрасывается",
                Model.seen == [first] and got["text"] == "" and got.get("looped") and "retried" not in got)
    ok &= check("место начала повтора записано — ближе к началу ответа, чем к концу",
                got.get("loop_from") is not None and got["loop_from"] < first // 4, str(got.get("loop_from")))

    got = ask((200, CUT, "length", first), (200, LOOP, "length", again))
    ok &= check("переспрос зациклился — остаётся первый ответ, повтор помечен",
                got["text"] == CUT and got.get("retried") and got.get("retry_error") == "ответ зациклился"
                and got.get("loop_from") is not None and not got.get("looped"), str(got.get("retry_error")))

    got = ask((200, CUT, "length", first), (500, "", "", 0))
    ok &= check("переспрос упал — остаётся первый ответ", got["text"] == CUT and got.get("retry_error") == "HTTP 500")

    got = ask((200, "1050", "length", first), prompt="Ширина входной двери, мм?")
    ok &= check("прицельный вопрос прохода по чертежам не переспрашивается",
                Model.seen == [first] and "retried" not in got)

    got = ask((200, FULL, "stop", 900))
    ok &= check("ответ в потолок не упёрся — один вызов", Model.seen == [first] and "retried" not in got)

    # --- кеш: ответ обрезан кодом до 27.09
    reading.CACHE = os.path.join(TMP, "cache")
    pdf = os.path.join(TMP, "sheet.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=1191, height=842)                 # А3: лист крупного формата — DRAWING
    page.insert_text((60, 80), "Plan 1. Ventilation")        # шрифт PyMuPDF по умолчанию без кириллицы
    doc.save(pdf)
    doc.close()
    digest = "f" * 64
    layer = "Plan 1. Ventilation"
    reading.cache_put(digest, 1, "read", {
        "version": reading.READ_VERSION, "kind": "DRAWING", "text": layer + "\n" + CUT, "text_source": "UNION",
        "sources": ["TEXT_LAYER", "MODEL"], "words": [], "rotation": 0, "coords_rotated": True,
        "width_pt": 1191, "height_pt": 842, "images": 0, "quality": "OK",
        "model_call": {"model": "test-model", "finish_reason": "length", "tokens_out": first}})
    Model.script, Model.seen = [(200, FULL, "stop", 5200)], []
    doc = pymupdf.open(pdf)
    got = reading.read_page(doc, 1, digest, use_model=True, use_ocr=False)
    ok &= check("обрезанный в кеше ответ: страница прочитана заново, текст модели не задвоен",
                Model.seen == [first] and FULL in got["text"] and got["text"].count(CUT) == 1
                and got["text"].startswith(layer) and got["model_call"]["finish_reason"] == "stop",
                got["text"][:120].replace("\n", " | "))
    again_cached = reading.cache_get(digest, 1, "read")
    ok &= check("и в кеше лежит новый ответ", FULL in again_cached["text"])

    Model.script, Model.seen = [], []
    stored = dict(again_cached, model_call={"model": "test-model", "finish_reason": "length", "retried": True})
    reading.cache_put(digest, 1, "read", stored)
    reading.read_page(doc, 1, digest, use_model=True, use_ocr=False)
    ok &= check("переспрошенная, но всё равно длинная страница из кеша модель больше не зовёт", Model.seen == [])
    reading.cache_put(digest, 1, "read", dict(stored, model_call={"finish_reason": "length"}))
    reading.read_page(doc, 1, digest, use_model=False, use_ocr=False)
    ok &= check("без модели обрезанный ответ из кеша берётся как есть", Model.seen == [])
    doc.close()
    server.shutdown()

    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
