"""Снимок правил для страницы эксперта (Р-134): воркер кладёт в базу правила своего образа.

  python tests/test_rules_snapshot.py

API собирается из каталога service/ и файлов правил не видит, поэтому страница правил эксперта
показывает снимок, который воркер передаёт при запуске. Проверяется, что в снимок попадают все
файлы правил — пять очередей, черновики, каталог 132 параметров, решения специалиста, — что его
отпечаток зависит только от содержимого, что запись в базу не множит строк одного образа, а сбой
базы не останавливает воркер.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# брокер тесту не нужен: без pika — пустой модуль, как в test_parse_time.py
try:
    import pika  # noqa: F401
except ImportError:
    sys.modules["pika"] = types.ModuleType("pika")

from service.worker import main, rules_snapshot  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


class Conn:
    """Подключение к базе, которое запоминает запросы."""

    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def copy_rules(target):
    """Копия файлов, из которых собирается снимок: rules/ и каталог параметров."""
    shutil.copytree(os.path.join(ROOT, "rules"), os.path.join(target, "rules"))
    os.makedirs(os.path.join(target, "docs", "extracted"))
    shutil.copy(os.path.join(ROOT, "docs", "extracted", "parameter_catalog_132.jsonl"),
                os.path.join(target, "docs", "extracted"))


def main_():
    ok = True
    fingerprint, body = rules_snapshot.build()
    queues = body["queues"]
    ok &= check("формат снимка — 1", body["format"] == 1)
    ok &= check("пять очередей Матрицы", sorted(queues) == ["1", "2", "3", "4", "5"], str(sorted(queues)))
    total = sum(len(q["parameters"]) for q in queues.values())
    ok &= check("в очередях все 132 параметра", total == 132, str(total))
    ok &= check("каталог — 132 строки", len(body["catalog"]) == 132, str(len(body["catalog"])))
    drafts = sum(len(q["parameters"]) for q in body["provisional"].values())
    on_disk = len([n for n in os.listdir(os.path.join(ROOT, "rules", "provisional")) if re.match(r"q\d+\.json$", n)])
    ok &= check("черновики — все файлы rules/provisional", len(body["provisional"]) == on_disk and drafts > 0,
                f"файлов {on_disk}, черновиков {drafts}")
    ok &= check("решения специалиста по свободному поиску", bool((body["guidance"] or {}).get("kinds")))
    engines = body["engines"]["rules"]
    working = {code for q in queues.values() for code, r in q["parameters"].items()
               if r.get("implemented") and not r.get("out_of_scope")}
    ok &= check("тип и поля песочницы — у каждого работающего правила и черновика (#222)",
                set(engines) == working and len(body["engines"]["drafts"]) == drafts
                and all(v["engine"] in ("pattern", "code", "llm") for v in engines.values()),
                f"{len(engines)} правил, {len(body['engines']['drafts'])} черновиков")
    ok &= check("у правила с разбором в коде песочницы нет, у правила с моделью — только сравнение",
                all(v["editable"] == [] for v in engines.values() if v["engine"] == "code")
                and all(v["editable"] in ([], ["compare"]) for v in engines.values() if v["engine"] == "llm"))
    ok &= check("отпечаток — SHA-256 содержимого", re.fullmatch(r"[0-9a-f]{64}", fingerprint) is not None, fingerprint)
    ok &= check("отпечаток не меняется от сборки к сборке", rules_snapshot.build()[0] == fingerprint)
    ok &= check("снимок сериализуется в JSON для jsonb", len(json.dumps(body, ensure_ascii=False)) > 100_000)

    with tempfile.TemporaryDirectory() as tmp:
        copy_rules(tmp)
        same = rules_snapshot.build(tmp)[0]
        ok &= check("та же копия правил — тот же отпечаток", same == fingerprint)
        path = os.path.join(tmp, "rules", "matrix_queue1.json")
        data = json.load(open(path, encoding="utf-8"))
        data["parameters"]["PZ-001"]["note"] = "другое пояснение"
        json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        ok &= check("правка правила меняет отпечаток", rules_snapshot.build(tmp)[0] != fingerprint)
        shutil.rmtree(os.path.join(tmp, "rules", "provisional"))
        os.remove(os.path.join(tmp, "rules", "specialist_guidance.json"))
        _, bare = rules_snapshot.build(tmp)
        ok &= check("без черновиков и решений специалиста снимок всё равно собирается",
                    bare["provisional"] == {} and bare["guidance"] is None)

    conn = Conn()
    got = rules_snapshot.publish(conn)
    insert, delete = conn.calls
    ok &= check("publish возвращает отпечаток снимка", got == fingerprint)
    ok &= check("повтор того же образа строк не множит: on conflict сдвигает время",
                "insert into rule_snapshots" in insert[0] and "on conflict (fingerprint) do update set published_at = now()"
                in insert[0] and insert[1][0] == fingerprint, insert[0])
    ok &= check("старые снимки сверх KEEP убираются",
                "delete from rule_snapshots" in delete[0] and delete[1] == (rules_snapshot.KEEP,), delete[0])

    logged = []
    real_db, real_log = main.infra.db, main.log
    try:
        main.log = lambda message, level="INFO", **fields: logged.append((level, message))

        def broken():
            raise RuntimeError("база недоступна")

        main.infra.db = broken
        ok &= check("сбой базы: воркер не падает, снимок повторится позже", main.publish_rules() is False)
        ok &= check("и пишет предупреждение в лог", logged and logged[-1][0] == "WARNING", str(logged[-1:]))
        fake = Conn()
        main.infra.db = lambda: fake
        ok &= check("база доступна: снимок передан", main.publish_rules() is True and len(fake.calls) == 2)
    finally:
        main.infra.db, main.log = real_db, real_log

    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main_())
