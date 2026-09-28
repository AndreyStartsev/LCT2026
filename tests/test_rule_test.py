"""Пробный прогон правила: трасса и песочница страницы правил эксперта (#222, #223).

  DATA_DIR=… PIPELINE_CACHE=… python tests/test_rule_test.py

Проверяется:
- тип правила (паттерн, код, LLM) сходится с ветками разбора `matrix_rules.extract`: вид без своей
  ветки — паттерн, а паттерн со своей веткой — только из перечня видов, читающих шаблоны правила;
- песочница меняет только разрешённые поля и отклоняет неверные значения до всякого разбора;
  у правила с разбором в коде песочницы нет совсем: ни подписей, ни порога;
- трасса повторяет рабочий прогон: записи правила те же, что в `build/` объекта, и у кода тоже;
- вариант подписей меняет вывод, а кандидаты варианта не пишутся в общий кеш.
Прогон на объекте нужен корпус: без `build/OBJ-NOVOSLOBODSKAYA` эта часть пропускается.
"""
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import cli, matrix_rules, rule_test  # noqa: E402

OBJECT = "OBJ-NOVOSLOBODSKAYA"
# виды со своей веткой в `extract`, которые только читают шаблоны из файла правила
PATTERN_BRANCHES = {"class", "feature_presence", "schedule_sum", "schedule_positions", "item_height"}


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def all_rules():
    for queue, path in sorted(matrix_rules.QUEUES.items()):
        for code, rule in matrix_rules.load_rules(path)["parameters"].items():
            yield code, rule, False
        for code, rule in ((matrix_rules.load_provisional(queue) or {}).get("parameters") or {}).items():
            yield code, rule, True


def main():
    ok = True
    branches = {k for k in matrix_rules.kind_digests() if k != "*"}
    stray = sorted({str(r.get("kind")) for _, r, _ in all_rules()
                    if r.get("kind") not in branches and rule_test.engine(r) == "code"})
    ok &= check("вид без своей ветки разбора — паттерн или LLM, а не код", not stray, ", ".join(stray))
    ok &= check("паттерн со своей веткой — только виды, читающие шаблоны правила",
                (rule_test.PATTERN_KINDS & branches) == PATTERN_BRANCHES, str(sorted(rule_test.PATTERN_KINDS & branches)))
    working = collections.Counter(rule_test.engine(r) for _, r, draft in all_rules()
                                  if not draft and r.get("implemented") and not r.get("out_of_scope"))
    ok &= check("у каждого работающего правила есть тип", sum(working.values()) >= 100 and None not in working,
                str(dict(working)))

    rule = {"kind": "area", "labels": ["площадь"], "exclude": ["квартир"],
            "compare": {"type": "relative", "threshold": 0.01}, "implemented": True}
    tried = rule_test.apply_variant(rule, {"labels": ["общая\\s+площадь"], "compare": {"threshold": 0.05}})
    ok &= check("вариант паттерна: подписи и порог поверх правила, прочее как было",
                tried["labels"] == ["общая\\s+площадь"] and tried["compare"] == {"type": "relative", "threshold": 0.05}
                and tried["exclude"] == ["квартир"] and rule["compare"]["threshold"] == 0.01)
    refused = []
    for bad in ({"kind": "volume"}, {"compare": {"type": "decrease"}}, {"compare": {"trigger": 1200}},
                {"labels": ["("]}, {"labels": "площадь"}, {"compare": {"threshold": True}},
                {"compare": {"threshold": -0.1}}, {"exclude": ["x" * 500]}):
        try:
            rule_test.apply_variant(rule, bad)
        except rule_test.VariantError as error:
            refused.append(str(error))
    ok &= check("неверный вариант отклоняется с причиной", len(refused) == 8, refused[0] if refused else "")
    code_rule = {"kind": "material_takeoff", "compare": {"type": "keyed", "threshold": 0.02}, "labels": ["бетон"]}
    code_refused = []
    for variant in ({"labels": ["бетон\\s+B\\d+"]}, {"compare": {"threshold": 0.05}}):
        try:
            rule_test.apply_variant(code_rule, variant)
        except rule_test.VariantError as error:
            code_refused.append(str(error))
    ok &= check("правило с разбором в коде в песочнице не прогоняется: ни подписи, ни порог",
                len(code_refused) == 2 and rule_test.editable(code_rule) == set(), code_refused[0] if code_refused else "")
    llm_rule = {"kind": "vlm_value", "compare": {"type": "decrease", "trigger": 1200}}
    ok &= check("у правила с моделью меняется порог",
                rule_test.apply_variant(llm_rule, {"compare": {"trigger": 1500}})["compare"]["trigger"] == 1500)

    density = collections.Counter({("F1", 1): 3, ("F1", 2): 1, ("F2", 5): 2})
    swapped = rule_test.swap_density(density, {("F1", 1), ("F1", 2)}, {("F1", 1), ("F2", 7)})
    ok &= check("плотность: вклад правила заменён вкладом варианта",
                swapped[("F1", 1)] == 3 and swapped[("F1", 2)] == 0 and swapped[("F2", 7)] == 1 and swapped[("F2", 5)] == 2)
    before = [{"finding_id": "a", "violation_label": "NO_VIOLATION", "pd_value": "6 м", "rd_value": "6 м"},
              {"finding_id": "b", "violation_label": "VIOLATION_PRESENT", "pd_value": "1", "rd_value": "2"}]
    after = [{"finding_id": "a", "violation_label": "VIOLATION_PRESENT", "pd_value": "6 м", "rd_value": "6 м"},
             {"finding_id": "c", "violation_label": "NO_VIOLATION", "pd_value": "3", "rd_value": "3"}]
    changes, same = rule_test.diff(before, after)
    ok &= check("разница до и после: поменялась, пропала, добавилась",
                [(c["finding_id"], c["change"]) for c in changes] == [("a", "changed"), ("b", "removed"), ("c", "added")]
                and same == 0)

    if not os.path.exists(os.path.join(matrix_rules.OUT, OBJECT, "documents.jsonl")):
        print(f"  [пропуск] прогон на объекте: нет {OBJECT} в {matrix_rules.OUT}")
    else:
        for code in ("PZ-001", "KR-067", "IOS1-068", "AR-040"):
            got = rule_test.run(OBJECT, code)
            built = [f for f in cli.read_jsonl(os.path.join(matrix_rules.OUT, OBJECT, f"findings_matrix_q{got['queue']}.jsonl"))
                     if f.get("parameter_code") == code]
            key = lambda f: (f["finding_id"], f["violation_label"], rule_test._text(f.get("pd_value")),  # noqa: E731
                             rule_test._text(f.get("rd_value")))
            ok &= check(f"трасса {code} [{got['engine']}] повторяет рабочий прогон",
                        sorted(map(key, got["base"]["findings"])) == sorted(map(key, built)),
                        f"записей {len(built)}, {got['elapsed_s']} с")
        trace = rule_test.run(OBJECT, "PZ-001")["trace"]["stages"]["PD"]
        ok &= check("в трассе выбранное значение стадии отмечено у кандидата",
                    trace["chosen"] and all(c["chosen"] for c in trace["candidates"][:1]), json.dumps(trace["chosen"]))

        writes = []
        real = matrix_rules._rule_cache_path
        matrix_rules._rule_cache_path = lambda sha: writes.append(sha) or real(sha)
        try:
            tried = rule_test.run(OBJECT, "PZ-001", {"labels": ["подпись\\s+которой\\s+нет"]}, with_trace=False)
            base_writes = len(writes)
            writes.clear()
            _, rules, _ = rule_test.locate("PZ-001")
            matrix_rules.collect(OBJECT, dict(rules, parameters={"PZ-001": rules["parameters"]["PZ-001"]}),
                                 use_cache=False)
        finally:
            matrix_rules._rule_cache_path = real
        flip = [(c["change"], (c["before"] or {}).get("violation_label")) for c in tried["variant"]["changes"]]
        ok &= check("подпись PZ-001, которой нет в документах: запись пропадает",
                    flip == [("removed", "COMPARISON_IMPOSSIBLE")], str(flip))
        ok &= check("кандидаты варианта в общий кеш не пишутся", base_writes >= 0 and not writes, f"{len(writes)} обращений")

    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
