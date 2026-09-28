"""Профиль предварительных правил (#95): черновик не попадает ни в прод, ни в сдачу.

  python tests/test_provisional.py
"""
import glob
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import matrix_rules, submission  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def main():
    ok = True
    before = matrix_rules.PROVISIONAL_DIR
    with tempfile.TemporaryDirectory() as tmp:
        matrix_rules.PROVISIONAL_DIR = tmp
        try:
            ok &= check("черновиков нет — профиль пуст", matrix_rules.load_provisional(2) is None)
            json.dump({"parameters": {"KR-060": {"kind": "vlm_value", "implemented": True, "unit": "мм",
                                                 "vlm": {"prompt": "Найди сечения колонн"}}}},
                      open(os.path.join(tmp, "q2.json"), "w", encoding="utf-8"), ensure_ascii=False)
            rules = matrix_rules.load_provisional(2)
            ok &= check("черновик помечен и знает свой код",
                        rules["parameters"]["KR-060"].get("provisional") is True
                        and rules["parameters"]["KR-060"]["code"] == "KR-060")
            ok &= check("классы значений — от правил очереди", rules.get("classes") == matrix_rules.load_rules(
                matrix_rules.QUEUES[2]).get("classes"))
        finally:
            matrix_rules.PROVISIONAL_DIR = before
    core = {code for path in matrix_rules.QUEUES.values() for code in matrix_rules.load_rules(path)["parameters"]}
    ok &= check("очереди прода черновиков не содержат",
                not any(r.get("provisional") for path in matrix_rules.QUEUES.values()
                        for r in matrix_rules.load_rules(path)["parameters"].values()), str(len(core)))
    with tempfile.TemporaryDirectory() as out:
        # у черновиков свой файл ответов прохода и свой отпечаток в ключе кеша кандидатов
        os.makedirs(os.path.join(out, "OBJ-X"))
        doc = {"object_id": "OBJ-X", "file_id": "F0001"}
        with open(os.path.join(out, "OBJ-X", "vlm_provisional.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"object_id": "OBJ-X", "parameter_code": "KR-060", "file_id": "F0001",
                                "pdf_page_number": 3, "values": [400]}) + "\n")
        matrix_rules._VLM_DIGEST.clear()
        ok &= check("ответы черновиков дают отпечаток черновикам",
                    bool(matrix_rules.vlm_digest(doc, out=out, provisional=True)))
        ok &= check("и не трогают отпечаток прод-правил", matrix_rules.vlm_digest(doc, out=out) is None)
        matrix_rules._VLM_DIGEST.clear()
    # каждый черновик решается движком: вид сравнения без нужного поля ронял прогон всей очереди
    # (ODI-117: min_absolute без порога, Речников, 25.09)
    numbers = ({"value": 1000.0, "raw": "1000", "all_values": [1000.0, 1200.0]},
               {"value": 900.0, "raw": "900", "all_values": [900.0]})
    classes = ({"value": "A", "raw": "A"}, {"value": "B", "raw": "B"})
    broken = []
    for q in matrix_rules.QUEUES:
        profile = matrix_rules.load_provisional(q) or {"parameters": {}}
        for code, rule in profile["parameters"].items():
            pd, rd = classes if rule["compare"]["type"] == "class_downgrade" else numbers
            try:
                matrix_rules.decide(rule, pd, rd, profile.get("classes"))
            except Exception as e:
                broken.append(f"{code}: {type(e).__name__} {e}")
    ok &= check("каждый черновик решается движком", not broken, "; ".join(broken)[:300])
    marked = matrix_rules.mark_provisional([{"finding_id": "O::KR-060", "object_id": "O", "parameter_code": "KR-060",
                                             "violation_label": "VIOLATION_PRESENT", "evidence": []}])
    ok &= check("находка черновика — отложенная, для специалиста",
                marked[0]["for_submission"] is False and marked[0]["needs_expert"] is True
                and marked[0]["finding_status"] == "SUSPICION" and marked[0]["provisional"] is True)
    doc, report = submission.build("O", marked)
    ok &= check("в файл сдачи черновик не идёт", not doc.get("checks") and report["excluded_by_origin"],
                str(report.get("excluded_by_origin"))[:120])
    # отчёт о качестве и стенд читают только findings_*.jsonl: файл черновиков туда не попадает
    ok &= check("файл находок черновиков называется не findings_*", not glob.fnmatch.fnmatch("provisional_q2.jsonl", "findings_*.jsonl"))
    ok &= check_worker()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


def check_worker():
    """Воркер (#95): находки черновиков по коду, с пустым списком у черновика без находок."""
    from pipeline import config
    from service.worker import settings, steps
    ok = True
    before = config.OUT
    with tempfile.TemporaryDirectory() as out:
        config.OUT = out
        try:
            os.makedirs(os.path.join(out, "O"))
            got = matrix_rules.mark_provisional([{"finding_id": "O::KR-060", "parameter_code": "KR-060",
                                                  "violation_label": "VIOLATION_PRESENT", "evidence": []}])
            with open(os.path.join(out, "O", "provisional_q2.jsonl"), "w", encoding="utf-8") as f:
                f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in got))
            found = steps.provisional_findings("O")
            profile = set(matrix_rules.load_provisional(2)["parameters"])
            ok &= check("воркер: находки черновика — по коду", [f["finding_id"] for f in found["KR-060"]] == ["O::KR-060"])
            ok &= check("воркер: черновик очереди без находок — пустой список",
                        all(found.get(c) == [] for c in profile - {"KR-060"}), str(sorted(profile - set(found))))
            ok &= check("воркер: очередь без файла черновиков в покрытие не идёт",
                        not any(c.startswith(("PPM", "ODI")) for c in found), str(sorted(found)))
            ok &= check("профиль черновиков в сервисе по умолчанию включён", settings.PROVISIONAL is True)
            ok &= check("отпечаток профиля — по пяти очередям", steps.provisional_profile().count("+") == 4,
                        steps.provisional_profile())
        finally:
            config.OUT = before
    return ok


if __name__ == "__main__":
    sys.exit(main())
