# Пример ответа сервиса

[`submission.json`](submission.json) — протокол в формате сдачи по схеме
[`../submission.schema.json`](../submission.schema.json). Это то, что сервис выдаёт без решений
инспектора на открытом учебном объекте Тюменская-5 (`OBJ-TYUMENSKAYA-5-GOLD-SEED`, выборка
`TRAIN_PUBLIC`). Тот же ответ отдаёт `GET /api/v1/process/{id}/protocol`, а загрузчик
`tools/upload_object.py` (в поставке — сервис `loader`) сохраняет его файлом.

В файле 66 проверок:
- 13 нарушений `VIOLATION_PRESENT`: 8 критических и 5 существенных;
- 10 без нарушения `NO_VIOLATION`;
- 43 `COMPARISON_IMPOSSIBLE`: сравнить не с чем.

У каждой проверки есть доказательства: стадия, `file_id` из реестра объекта и номер страницы PDF.

Проверка по схеме (нужен пакет `jsonschema`):

```bash
python3 -c "import json, jsonschema; jsonschema.Draft202012Validator(json.load(open('contracts/submission.schema.json'))).validate(json.load(open('contracts/examples/submission.json')))"
```
