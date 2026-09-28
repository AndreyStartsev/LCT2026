"""Исполнительная документация в правилах Матрицы. Задача #42.

  python tests/test_id_stage.py

По ТЗ 1.2 сверяются три массива. Правило сравнивает проект с рабочей стадией, а построенное
(исполнительную документацию) — с рабочей стадией, или с проектной, когда рабочей нет.
Объекты синтетические: по одному PDF на стадию с фразой «Этажность N» (правило PZ-007,
любое изменение — нарушение).
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="idstage-")
os.environ["PIPELINE_OUT"] = os.path.join(_TMP, "build")
os.environ["PIPELINE_CACHE"] = os.path.join(_TMP, "cache")

import pymupdf  # noqa: E402

from pipeline import config, matrix_rules, protocol, registry  # noqa: E402

FONT = pymupdf.Font("cour")


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def side(value, raw=None, pages=(("F", 1),)):
    return {"value": value, "raw": raw or str(value), "pages": list(pages), "snippet": f"Этажность {raw or value}",
            "support": 1, "alternatives": [], "columns": [value]}


def test_review():
    print("\n1. Сверка построенного с документацией")
    rule = {"compare": {"type": "any_change"}}
    label, result, detail = matrix_rules.decide(rule, side(4), side(4))
    got = matrix_rules.id_review(rule, side(4), side(4), side(4), label, result, detail, matrix_rules.decide, classes=None)
    ok = check("все три стадии сошлись — EQUAL_ALL_AVAILABLE_STAGES",
               got[0] == "NO_VIOLATION" and got[1] == "EQUAL_ALL_AVAILABLE_STAGES" and "ИД против рабочей" in got[2], str(got[:2]))
    got = matrix_rules.id_review(rule, side(4), side(4), side(5), label, result, detail, matrix_rules.decide, classes=None)
    ok &= check("проект и рабочая стадия сошлись, построено иначе — нарушение по ИД",
                got[0] == "VIOLATION_PRESENT" and got[1] == "VALUE_MISMATCH" and "4 → 5" in got[2], str(got))
    label, result, detail = matrix_rules.decide(rule, side(4), None)
    got = matrix_rules.id_review(rule, side(4), None, side(4), label, result, detail, matrix_rules.decide, classes=None)
    ok &= check("рабочей стадии нет (PD_ID_ONLY): решает пара проект — ИД, нарушения нет",
                got[0] == "NO_VIOLATION" and "против проектной" in got[2], str(got[:2]))
    got = matrix_rules.id_review(rule, side(4), None, side(3), label, result, detail, matrix_rules.decide, classes=None)
    ok &= check("рабочей стадии нет, построено иначе, чем в проекте — нарушение", got[0] == "VIOLATION_PRESENT")
    got = matrix_rules.id_review(rule, side(4), side(4), None, "NO_VIOLATION", "EQUAL_PD_RD", "d", matrix_rules.decide, classes=None)
    ok &= check("без ИД запись не меняется", got[:3] == ("NO_VIOLATION", "EQUAL_PD_RD", "d") and got[3] is None)
    got = matrix_rules.id_review(rule, None, None, side(4), None, None, "", matrix_rules.decide, classes=None)
    ok &= check("значение только в ИД — сравнивать не с чем, только заметка", got[0] is None and "только в исполнительной" in got[3])
    # набор значений элемента: класс бетона понижен в построенном
    rule_set = {"kind": "element_class", "compare": {"type": "class_downgrade", "result": "CLASS_DOWNGRADE"}}
    pd = {"value": (2,), "raw": "B30", "binding": "CLAUSE", "pages": [("P", 1)], "snippet": "B30"}
    rd = dict(pd, pages=[("R", 1)])
    built = {"value": (1,), "raw": "B25", "binding": "CLAUSE", "pages": [("I", 5)], "snippet": "B25"}
    label, result, detail = matrix_rules.decide_set(rule_set, pd, rd)
    got = matrix_rules.id_review(rule_set, pd, rd, built, label, result, detail, matrix_rules.decide_set)
    ok &= check("класс бетона по акту ниже рабочей стадии — CLASS_DOWNGRADE с доказательством из ИД",
                got[0] == "VIOLATION_PRESENT" and got[1] == "CLASS_DOWNGRADE", str(got[:2]))
    evidence = []
    matrix_rules.id_evidence(built, evidence)
    ok &= check("страница ИД в доказательствах", evidence == [{"stage": "ID", "file_id": "I", "pdf_page_number": 5,
                                                              "quote": "B25", "localization": "PAGE_LEVEL"}], str(evidence))
    return ok


def _pdf(path, text):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    writer = pymupdf.TextWriter(page.rect)
    writer.append((60, 80), "Общие сведения об объекте.", font=FONT, fontsize=10)
    writer.append((60, 110), text, font=FONT, fontsize=10)
    writer.write_text(page)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc.save(path)
    doc.close()


def _run(obj, root, files):
    for rel, text in files:
        _pdf(os.path.join(root, rel), text)
    config.register_object(obj, root, obj, split="EXTERNAL")
    docs = registry.build(obj)
    os.makedirs(os.path.join(config.OUT, obj), exist_ok=True)
    with open(os.path.join(config.OUT, obj, "documents.jsonl"), "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    findings, _ = matrix_rules.build_findings(obj, rules=matrix_rules.load_rules(matrix_rules.QUEUES[1]))
    return docs, next((f for f in findings if f["parameter_code"] == "PZ-007"), None)


def test_end_to_end():
    print("\n2. Сквозной путь: три стадии в реестре → запись правила")
    docs, f = _run("OBJ-TEST-ID-A", os.path.join(_TMP, "А"), [
        ("Проектная документация/01-24-П-ПЗ.pdf", "Этажность 4"),
        ("Рабочая документация/01-24-Р-АР.pdf", "Этажность 4"),
        ("Исполнительная документация/Акт освидетельствования.pdf", "Этажность 4"),
    ])
    ok = check("стадии по папкам: PD, RD, ID", sorted(d["stage"] for d in docs) == ["ID", "PD", "RD"], str([d["stage"] for d in docs]))
    ok &= check("значение ИД в записи, сверка со всеми стадиями",
                f is not None and f["id_value"] == "4" and f["violation_label"] == "NO_VIOLATION"
                and f["comparison_result"] == "EQUAL_ALL_AVAILABLE_STAGES", str(f and (f["id_value"], f["violation_label"], f["comparison_result"])))
    ok &= check("страница ИД среди доказательств, сторона ИД в извлечении",
                any(e["stage"] == "ID" for e in (f or {}).get("evidence", [])) and (f or {}).get("extraction", {}).get("id"),
                str([(e["stage"], e["file_id"]) for e in (f or {}).get("evidence", [])]))
    docs, f = _run("OBJ-TEST-ID-B", os.path.join(_TMP, "Б"), [
        ("Проектная документация/01-24-П-ПЗ.pdf", "Этажность 4"),
        ("Рабочая документация/01-24-Р-АР.pdf", "Этажность 4"),
        ("Исполнительная документация/Акт освидетельствования.pdf", "Этажность 5"),
    ])
    ok &= check("построено не по рабочей стадии — нарушение, хотя проект и рабочая стадия сошлись",
                f is not None and f["violation_label"] == "VIOLATION_PRESENT" and f["id_value"] == "5"
                and "ИД против рабочей стадии" in f["extraction"]["detail"], str(f and (f["violation_label"], f["extraction"]["detail"][:120])))
    docs, f = _run("OBJ-TEST-ID-C", os.path.join(_TMP, "В"), [
        ("Проектная документация/01-24-П-ПЗ.pdf", "Этажность 4"),
        ("Исполнительная документация/Акт освидетельствования.pdf", "Этажность 4"),
    ])
    ok &= check("PD_ID_ONLY: рабочей стадии нет, пара проект — ИД даёт «нарушения нет»",
                f is not None and f["violation_label"] == "NO_VIOLATION" and f["rd_value"] is None and f["id_value"] == "4",
                str(f and (f["violation_label"], f["rd_value"], f["id_value"])))
    cov = protocol.coverage([{"parameter_code": "PZ-007", "parameter_id": 7, "parameter_name": "Этажность"}],
                            {1: matrix_rules.load_rules(matrix_rules.QUEUES[1])}, [f], {"PD", "ID"})
    ok &= check("покрытие протокола: значение в ИД найдено", cov[0].get("id_status") == "FOUND", str(cov[0].get("id_status")))
    cov = protocol.coverage([{"parameter_code": "PZ-007", "parameter_id": 7, "parameter_name": "Этажность"}],
                            {1: matrix_rules.load_rules(matrix_rules.QUEUES[1])}, [dict(f, id_value=None)], {"PD", "RD", "ID"})
    ok &= check("ИД загружена, а значения по параметру в ней нет — параметр помечен отдельно",
                cov[0].get("id_status") == "NOT_FOUND")
    cov = protocol.coverage([{"parameter_code": "PZ-007", "parameter_id": 7, "parameter_name": "Этажность"}],
                            {1: matrix_rules.load_rules(matrix_rules.QUEUES[1])}, [dict(f, id_value=None)], {"PD", "RD"})
    ok &= check("ИД не загружена — для парного сравнения она не требуется, пометки нет", "id_status" not in cov[0])
    return ok


def main():
    ok = True
    for fn in (test_review, test_end_to_end):
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
