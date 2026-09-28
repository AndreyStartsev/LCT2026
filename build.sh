#!/usr/bin/env bash
# Сборка и запуск «Инспектора ИИ» одной командой.
#
#   ./build.sh            # спросит токен доступа к правилам, если его нет в .env, и поднимет сервис
#
# Правила Матрицы в открытый репозиторий не входят: сборка воркера выкачивает их по токену
# RULES_TOKEN из .env (rules/README.md). Токен, введённый здесь, дописывается в .env и в
# репозиторий не попадает. Ключи после имени скрипта уходят в docker compose up.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f rules/matrix_queue1.json ] && ! grep -Eq '^[[:space:]]*RULES_TOKEN=[^[:space:]]' .env 2>/dev/null; then
  read -rsp "Токен доступа к правилам: " token
  echo
  if [ -z "$token" ]; then
    echo "токен не введён: без правил воркер не соберётся" >&2
    exit 2
  fi
  printf '\nRULES_TOKEN=%s\n' "$token" >> .env
  chmod 600 .env
fi

docker compose up --build -d "$@"
echo
echo "Веб-клиент: http://localhost:8080   API и Swagger: http://localhost:3000/api/docs"
