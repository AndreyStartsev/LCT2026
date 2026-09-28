#!/usr/bin/env bash
# Самопроверка стенда проверки: сервис поднят, видеокарта видна, модель читает страницу,
# внешних вызовов нет. Запускать из корня репозитория после `up -d`:
#
#   deploy/release_check.sh
#
# Ничего не меняет: только смотрит и один раз просит модель прочитать тестовую страницу.
# Модель на внешнем сервере (deploy/LLM.md) — ту же надстройку передать и сюда:
#   RELEASE_EXTRA_COMPOSE=deploy/docker-compose.llm-external.yml deploy/release_check.sh
set -u
cd "$(dirname "$0")/.."
DC=(docker compose -f docker-compose.yml -f deploy/docker-compose.release.yml)
for extra in ${RELEASE_EXTRA_COMPOSE:-}; do DC+=(-f "$extra"); done
ok=1

line() { printf '%-52s ' "$1"; }
pass() { echo "да${1:+   $1}"; }
fail() { echo "НЕТ${1:+   $1}"; ok=0; }

model_url=$("${DC[@]}" exec -T worker printenv PIPELINE_MODEL_URL 2>/dev/null | tr -d '\r')
builtin=0
case "$model_url" in *//llm:*) builtin=1 ;; esac

line "контейнеры сервиса работают"
services="postgres redis rabbitmq minio api worker web iais"
[ "$builtin" = 1 ] && services="$services llm"
running=" $("${DC[@]}" ps --format '{{.Service}}' --status running | tr '\n' ' ') "
down=""
for s in $services; do case "$running" in *" $s "*) ;; *) down="$down $s" ;; esac; done
[ -z "$down" ] && pass "$(echo $services | wc -w | tr -d ' ') контейнеров" || fail "не работают:$down"

if [ "$builtin" = 1 ]; then
  line "сервер модели готов"
  health=$("${DC[@]}" ps --format '{{.Health}}' llm 2>/dev/null)
  case "$health" in
    healthy) pass ;;
    starting) fail "ещё поднимается (веса и сборка ядер, до 15 минут) — повторить позже" ;;
    *) fail "${health:-контейнера нет}; журнал: docker compose ... logs llm" ;;
  esac

  line "видеокарта видна в контейнере модели"
  gpu=$("${DC[@]}" exec -T llm nvidia-smi --query-gpu=name,memory.used,memory.total,driver_version \
        --format=csv,noheader 2>/dev/null | head -1)
  [ -n "$gpu" ] && pass "$gpu" || fail "nvidia-smi в контейнере не отвечает"
else
  line "модель на внешнем сервере"
  [ -n "$model_url" ] && pass "$model_url" || fail "у воркера не задан PIPELINE_MODEL_URL"
fi

line "воркер видит модель и не ходит наружу"
route=$("${DC[@]}" exec -T worker python -c "
from service.worker import settings as s
ok, why, _ = s.probe_model(s.MODEL_URL)
print(('модель отвечает' if ok else 'модель не отвечает: ' + str(why)) + '; запасной адрес '
      + ('включён ключом' if s.FALLBACK_READY else 'выключен'))
" 2>&1 | tail -1)
case "$route" in
  "модель отвечает"*) pass "$route" ;;
  *) fail "$route" ;;
esac

line "модель читает тестовую страницу"
read_out=$("${DC[@]}" exec -T worker python - <<'EOF' 2>&1 | tail -1
import os, tempfile, time
import pymupdf as fitz
from pipeline import reading
doc = fitz.open()
page = doc.new_page(width=842, height=595)
page.insert_text((72, 120), "INSPECTOR CHECK 40713", fontsize=36)
page.insert_text((72, 200), "B30 W8 F150  2400x1800", fontsize=28)
png = os.path.join(tempfile.mkdtemp(), "check.png")
page.get_pixmap(dpi=150).save(png)
got = reading.read_model(png)
text = got.get("text") or ""
found = all(v in text.replace(" ", "") for v in ("40713", "B30", "2400"))
print(("прочитано" if found else "не прочитано: " + (got.get("error") or repr(text[:60])))
      + f"; {got.get('ms', 0)} мс, токенов {got.get('tokens_in', 0)}+{got.get('tokens_out', 0)}"
      + ("; ЗАПАСНОЙ АДРЕС" if got.get("fallback") else ""))
EOF
)
case "$read_out" in
  "прочитано"*) pass "$read_out" ;;
  *) fail "$read_out" ;;
esac

line "API отвечает"
api=$("${DC[@]}" exec -T worker python -c "
import json, urllib.request
h = json.load(urllib.request.urlopen('http://api:8080/api/v1/health', timeout=5))
print(h.get('status'), 'моделей в списке', len((h.get('limits') or {}).get('reading_models') or []))
" 2>&1 | tail -1)
case "$api" in
  ok*) pass "$api" ;;
  *) fail "$api" ;;
esac

echo
[ "$ok" = 1 ] && echo "стенд готов" || echo "есть сбои — см. строки с НЕТ и deploy/RELEASE.md, раздел «Если что-то не так»"
[ "$ok" = 1 ]
