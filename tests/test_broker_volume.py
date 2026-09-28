"""Очереди брокера переживают пересоздание контейнера: постоянное имя узла и том. Р-132.

  python tests/test_broker_volume.py

RabbitMQ зовёт узел rabbit@<имя машины> и держит его базу в каталоге с этим именем. У сервиса
rabbitmq не было hostname, и именем машины был id контейнера. Анонимный том образа compose при
пересоздании сохранял, но новый узел заводил в нём новую базу: шаги, ждавшие в очередях, пропадали,
а шаг, шедший в этот момент, оставлял процесс в RUNNING, и API такой процесс не перезапускает.

Проверки:
- у брокера постоянное имя машины, без подстановок, и имя узла не задано в обход него;
- каталог данных /var/lib/rabbitmq — именованный том, объявленный среди томов compose;
- надстройки deploy/docker-compose*.yml не меняют имя и не перемонтируют каталог данных;
- сохранять есть что: очереди durable, сообщения постоянные — и у воркера, и у API.
Без Docker: читается текст compose и исходников.
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = "/var/lib/rabbitmq"


def read(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def service_block(text, name):
    """Определение сервиса: хвост строки «  name:» (в надстройках бывает «{ restart: … }»)
    и строки глубже, до следующего ключа того же уровня. None — сервиса в файле нет."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        found = re.match(rf"^  {name}:(.*)$", line)
        if not found:
            continue
        block = [found.group(1)]
        for rest in lines[i + 1:]:
            if rest.strip() and not rest.startswith("   "):
                break
            block.append(rest)
        return "\n".join(block)
    return None


def top_level_volumes(text):
    found = re.search(r"^volumes:\n((?:[ \t]+.*\n?|\n)*)", text, re.M)
    return set(re.findall(r"^  ([\w.-]+):", found.group(1), re.M)) if found else set()


def data_mounts(block):
    """Источники, смонтированные в каталог данных брокера (короткая запись «источник:путь»)."""
    return re.findall(rf"^\s+-\s*[\"']?([^\s:\"']+):{re.escape(DATA_DIR)}(?::\w+)?[\"']?\s*$", block, re.M)


def test_compose():
    ok = True
    compose = read("docker-compose.yml")
    block = service_block(compose, "rabbitmq") or ""
    ok &= check("в docker-compose.yml есть сервис rabbitmq", block != "")

    hostname = re.search(r"^    hostname:\s*[\"']?([^\s\"'#]+)", block, re.M)
    ok &= check("у брокера постоянное имя машины: имя узла rabbit@<hostname> не зависит от id контейнера",
                hostname is not None and "$" not in hostname.group(1), hostname.group(1) if hostname else "hostname нет")
    nodename = re.search(r"RABBITMQ_NODENAME:\s*(\S+)", block)
    ok &= check("имя узла не задано в обход hostname переменной с подстановкой",
                nodename is None or "$" not in nodename.group(1), nodename.group(1) if nodename else "")

    sources = data_mounts(block)
    named = [s for s in sources if not s.startswith((".", "/", "~", "$"))]
    ok &= check(f"{DATA_DIR} смонтирован именованным томом", len(sources) == 1 and named == sources, str(sources))
    declared = top_level_volumes(compose)
    ok &= check("том брокера объявлен среди томов compose", bool(named) and named[0] in declared,
                f"{named[0] if named else '—'} в {sorted(declared)}")
    return ok


def test_overlays():
    ok = True
    overlays = sorted(glob.glob(os.path.join(ROOT, "deploy", "docker-compose*.yml")))
    ok &= check("надстройки compose найдены", bool(overlays), ", ".join(os.path.basename(p) for p in overlays))
    for path in overlays:
        name = os.path.basename(path)
        block = service_block(open(path, encoding="utf-8").read(), "rabbitmq")
        if block is None:
            ok &= check(f"{name}: брокер не трогает", True)
            continue
        ok &= check(f"{name}: имя машины брокера не меняет", "hostname" not in block)
        ok &= check(f"{name}: каталог данных брокера не перемонтирует", DATA_DIR not in block)
    return ok


def test_persistence_in_code():
    """Том хранит только durable-очереди и постоянные сообщения: без них он пуст после перезапуска."""
    ok = True
    worker = read("service", "worker", "main.py")
    ok &= check("воркер объявляет очереди durable", re.search(r"queue_declare\([^)]*durable=True", worker))
    ok &= check("воркер отправляет шаги постоянными (delivery_mode=2)", re.search(r"delivery_mode=2\b", worker))
    api = read("service", "api", "src", "queue.ts")
    ok &= check("API объявляет очереди durable", re.search(r"assertQueue\([^)]*durable:\s*true", api))
    ok &= check("API отправляет шаги постоянными (persistent: true)", re.search(r"persistent:\s*true", api))
    return ok


def main():
    ok = True
    for test in (test_compose, test_overlays, test_persistence_in_code):
        print(test.__name__)
        ok &= test()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
