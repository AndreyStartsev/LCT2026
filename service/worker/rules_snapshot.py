"""Снимок правил для страницы эксперта (Р-134).

Правила сверки — файлы в образе воркера: очереди Матрицы `rules/matrix_queue*.json`, черновики
`rules/provisional/q*.json`, каталог 132 параметров и решения специалиста по видам свободного
поиска. API собирается из каталога `service/` и этих файлов не видит, поэтому воркер при старте
кладёт их снимок в базу (`rule_snapshots`), а API отдаёт эксперту последний. Так страница правил
показывает ровно те правила, которыми разбирает этот воркер, а не копию из другого коммита.

Снимок — файлы как есть: что из них показать и какими словами, решает API. Сверх файлов — только
то, что знает конвейер (`engines`): тип правила — паттерн, код или LLM — и какие его поля песочница
может менять (#222, #223). Ключ снимка — отпечаток содержимого: перезапуск того же образа строк
не множит, а только сдвигает время.
"""
import glob
import hashlib
import json
import os
import re

from psycopg.types.json import Jsonb

from pipeline import rule_test

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Формат тела снимка: API читает поля по нему и новое поле не спутает со старым снимком
FORMAT = 1
# Сколько снимков держать: прошлые образы воркера нужны, только пока их кто-то ещё запускает
KEEP = 10


def _json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _numbered(pattern):
    """Файлы очередей по номеру: `matrix_queue2.json` и `q2.json` — очередь «2»."""
    out = {}
    for path in sorted(glob.glob(pattern)):
        m = re.search(r"(\d+)\.json$", path)
        if m:
            out[m.group(1)] = _json(path)
    return out


def _engines(docs, working):
    """Тип правила и поля, которые песочница может менять: {код: {engine, editable}}."""
    out = {}
    for doc in docs.values():
        for code, rule in (doc.get("parameters") or {}).items():
            if not isinstance(rule, dict) or (working and (not rule.get("implemented") or rule.get("out_of_scope"))):
                continue
            out[code] = {"engine": rule_test.engine(rule), "editable": sorted(rule_test.editable(rule))}
    return out


def build(root=ROOT):
    """Тело снимка и его отпечаток из файлов правил под `root`."""
    rules = os.path.join(root, "rules")
    with open(os.path.join(root, "docs", "extracted", "parameter_catalog_132.jsonl"), encoding="utf-8") as f:
        catalog = [json.loads(line) for line in f if line.strip()]
    guidance = os.path.join(rules, "specialist_guidance.json")
    queues = _numbered(os.path.join(rules, "matrix_queue*.json"))
    provisional = _numbered(os.path.join(rules, "provisional", "q*.json"))
    body = {
        "format": FORMAT,
        "queues": queues,
        "provisional": provisional,
        "catalog": catalog,
        "guidance": _json(guidance) if os.path.exists(guidance) else None,
        "engines": {"rules": _engines(queues, working=True), "drafts": _engines(provisional, working=False)},
    }
    fingerprint = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return fingerprint, body


def publish(conn, root=ROOT):
    """Кладёт снимок в базу и возвращает его отпечаток; старые снимки сверх KEEP убираются."""
    fingerprint, body = build(root)
    conn.execute(
        "insert into rule_snapshots (fingerprint, body) values (%s, %s) "
        "on conflict (fingerprint) do update set published_at = now()",
        (fingerprint, Jsonb(body)),
    )
    conn.execute(
        "delete from rule_snapshots where fingerprint not in "
        "(select fingerprint from rule_snapshots order by published_at desc limit %s)",
        (KEEP,),
    )
    return fingerprint
