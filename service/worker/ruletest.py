"""Пробный прогон правила на одном объекте: трасса и песочница страницы правил эксперта (#222, #223).

    python -m service.worker.ruletest <test_id> <process_id>

Воркер запускает его отдельным процессом, по объекту за раз. Каталог сборки конвейера задаёт
переменная окружения (PIPELINE_OUT), конвейер читает её при импорте, поэтому у каждого объекта свой
процесс. Прогон ничего не меняет: `pipeline.rule_test` в каталог сборки не пишет, а отсюда в базу
пишется только итог — строка rule_test_results.

Код выхода 3 — вариант правила неверный (`VariantError`): прогонять его на прочих объектах незачем.
"""
import sys
import time

from psycopg.types.json import Jsonb

from service.worker import infra, steps

BAD_VARIANT = 3
# решения инспектора, которые песочница показывает рядом с записью: вариант, переворачивающий такую
# запись, спорит с человеком
DECIDED = ("CONFIRMED_VIOLATION", "NEGATIVE_VERIFIED", "CLARIFICATION_REQUIRED")


def decisions(conn, process_id, code):
    """Решения инспектора по записям параметра в этой проверке: {finding_id: статус}."""
    rows = conn.execute(
        "select finding_id, verification_status from findings "
        "where process_id = %s and parameter_code = %s and verification_status = any(%s)",
        (process_id, code, list(DECIDED)),
    ).fetchall()
    return {r["finding_id"]: r["verification_status"] for r in rows}


def mark(result, decided):
    """Решение инспектора — у записи до прогона и у каждой перемены, которая её касается."""
    for f in result.get("base", {}).get("findings", []):
        f["decision"] = decided.get(f.get("finding_id"))
    for change in (result.get("variant") or {}).get("changes", []):
        change["decision"] = decided.get(change.get("finding_id"))
    return result


def main():
    test_id, process_id = sys.argv[1], sys.argv[2]
    from pipeline import rule_test

    started = time.monotonic()
    status, result, error, exit_code = "DONE", None, None, 0
    with infra.db() as conn:
        test = conn.execute("select code, variant, trace from rule_tests where id = %s", (test_id,)).fetchone()
        if test is None:
            print(f"пробный прогон {test_id} не найден")
            return 1
        process = steps.load_process(conn, process_id)
        steps.register(process)
        try:
            result = rule_test.run(process["object_id"], test["code"], test["variant"], with_trace=test["trace"])
            mark(result, decisions(conn, process_id, test["code"]))
        except rule_test.VariantError as e:
            status, error, exit_code = "FAILED", f"вариант правила: {e}", BAD_VARIANT
        except KeyError as e:
            status, error = "FAILED", str(e.args[0]) if e.args else "правило не найдено"
        except FileNotFoundError:
            status, error = "FAILED", "проверка объекта не разобрана: нет реестра документов"
        except Exception as e:   # сбой прогона на одном объекте не должен ронять прогон по остальным
            status, error = "FAILED", f"{type(e).__name__}: {e}"
        elapsed = round(time.monotonic() - started, 1)
        conn.execute(
            "insert into rule_test_results (test_id, process_id, object_id, status, result, error, elapsed_s) "
            "values (%s, %s, %s, %s, %s, %s, %s) on conflict (test_id, process_id) do update set "
            "status = excluded.status, result = excluded.result, error = excluded.error, "
            "elapsed_s = excluded.elapsed_s, finished_at = now()",
            (test_id, process_id, process["object_id"], status, Jsonb(result) if result is not None else None,
             error, elapsed),
        )
    changes = len((result or {}).get("variant", {}).get("changes", [])) if result else 0
    print(f"пробный прогон {test['code']} на {process['object_id']}: {status}, {elapsed} с"
          + (f", перемен {changes}" if result and result.get("variant") else "") + (f": {error}" if error else ""))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
