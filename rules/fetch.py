#!/usr/bin/env python3
"""Правила Матрицы: выкачать из закрытого репозитория по токену и сверить суммы.

Правила — пять очередей Матрицы, черновики и указания специалиста — в открытый репозиторий
не входят. Какие файлы нужны этой версии кода, из какого коммита закрытого репозитория их брать
и какие у них суммы SHA-256, записано в `manifest.json` рядом.

  python rules/fetch.py            # токен из RULES_TOKEN или из .env; нет ни там, ни там — спросит
  python rules/fetch.py --check    # только проверить, что правила на месте и суммы сходятся

Сборка воркера вызывает этот же скрипт (`service/worker/Dockerfile`): токен приходит секретом
сборки из строки RULES_TOKEN в `.env` и в образ не попадает. Файл, который уже лежит на месте
с верной суммой, заново не качается. Файл с другой суммой не перезаписывается без `--force`:
это чужая версия правил, и молча её подменять нельзя.

Только стандартная библиотека Python.
"""
import argparse
import getpass
import hashlib
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(HERE, "manifest.json")
API = "https://api.github.com"
TOKEN_VAR = "RULES_TOKEN"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def file_sha256(path):
    with open(path, "rb") as f:
        return sha256(f.read())


def load_manifest(path=MANIFEST):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def state(dest, files):
    """Файлы по состоянию: на месте с верной суммой, нет, есть с другой суммой."""
    ok, missing, changed = [], [], []
    for name, digest in files.items():
        path = os.path.join(dest, name)
        if not os.path.exists(path):
            missing.append(name)
        elif file_sha256(path) == digest:
            ok.append(name)
        else:
            changed.append(name)
    return ok, missing, changed


def token_from_env_file(path):
    """Строка RULES_TOKEN=… из .env: кавычки и пробелы по краям снимаются."""
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            key, sep, value = line.strip().partition("=")
            if sep and key.strip() == TOKEN_VAR:
                return value.strip().strip("'\"")
    return ""


def find_token(args):
    """Токен по порядку: ключ --token, секрет сборки, переменная окружения, .env, вопрос человеку."""
    if args.token:
        return args.token.strip()
    if args.secret and os.path.exists(args.secret):
        with open(args.secret, encoding="utf-8") as f:
            token = f.read().strip()
        if token:
            return token
    token = os.environ.get(TOKEN_VAR, "").strip() or token_from_env_file(os.path.join(ROOT, ".env"))
    if token:
        return token
    if not args.no_prompt and sys.stdin.isatty():
        return getpass.getpass("Токен доступа к правилам: ").strip()
    return ""


def download(repo, ref, path, token, attempts=3):
    """Файл из закрытого репозитория на заданном коммите: GitHub API, содержимое как есть.

    Обрыв соединения и ответ 5xx повторяются: на сборке у организатора сеть бывает всякой,
    а отказ в доступе (401, 403, 404) повтором не лечится и сразу называется словами.
    """
    url = f"{API}/repos/{repo}/contents/{path}?ref={ref}"
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.raw+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "inspector-ai-rules-fetch",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise SystemExit("токен не подошёл: неверный, отозван или истёк срок (HTTP 401)")
            if e.code in (403, 404):
                raise SystemExit(f"нет доступа к {path} в {repo}@{ref[:12]} (HTTP {e.code}): токену нужно "
                                 "право Contents: Read-only на этот репозиторий")
            if e.code < 500 or attempt == attempts:
                raise SystemExit(f"GitHub ответил HTTP {e.code} на {path}")
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            if attempt == attempts:
                raise SystemExit(f"GitHub недоступен: {getattr(e, 'reason', None) or e}")
        time.sleep(2 * attempt)


def write_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def main(argv=None):
    p = argparse.ArgumentParser(description="выкачать правила Матрицы по токену и сверить суммы")
    p.add_argument("--token", help=f"токен доступа; по умолчанию {TOKEN_VAR} из окружения или из .env")
    p.add_argument("--secret", help="файл секрета сборки с токеном (/run/secrets/…)")
    p.add_argument("--dest", default=HERE, help="куда класть правила, по умолчанию rules/")
    p.add_argument("--check", action="store_true", help="только проверить, ничего не качать")
    p.add_argument("--force", action="store_true", help="заменить файлы с другой суммой версией из манифеста")
    p.add_argument("--no-prompt", action="store_true", help="не спрашивать токен, если его нигде нет")
    args = p.parse_args(argv)

    m = load_manifest()
    files, repo, ref = m["files"], m["repo"], m["ref"]
    ok, missing, changed = state(args.dest, files)
    if not missing and not changed:
        print(f"правила на месте: {len(ok)} файлов, суммы сходятся с manifest.json ({repo}@{ref[:12]})")
        return 0
    if changed and not args.force:
        print("эти файлы правил отличаются от версии в manifest.json: " + ", ".join(changed), file=sys.stderr)
        print("заменить их версией из манифеста — ключ --force", file=sys.stderr)
        return 1
    if args.check:
        print(f"правил нет: {', '.join(missing)}. Выкачать: python rules/fetch.py", file=sys.stderr)
        return 1

    token = find_token(args)
    if not token:
        print(f"правил нет, а токена доступа к ним нет ни в {TOKEN_VAR}, ни в .env.", file=sys.stderr)
        print(f"Добавьте в .env рядом с docker-compose.yml строку {TOKEN_VAR}=<токен> и повторите.",
              file=sys.stderr)
        return 2

    todo = missing + changed
    for name in todo:
        data = download(repo, ref, f"{m.get('path', 'rules')}/{name}", token)
        if sha256(data) != files[name]:
            raise SystemExit(f"сумма {name} не сходится с manifest.json: файл не записан")
        write_atomic(os.path.join(args.dest, name), data)
        print(f"  {name}")
    print(f"выкачано файлов правил: {len(todo)}, суммы сходятся ({repo}@{ref[:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
