"""Редакции документов в правилах Матрицы и сравнении по помещениям. Задача #10.

  python tests/test_revision_rules.py

Цепочки редакций строит `pipeline/revisions.py` (проверки — `tests/test_revisions.py`).
Здесь проверяется, что правила ими пользуются: значение берётся из актуальной редакции,
устаревшая редакция видна инспектору как история, а цепочка, порядок которой не определён
и редакции которой расходятся в значении, даёт «требует уточнения», а не нарушение
и не «нарушения нет» (ТЗ 9.1). Объекты синтетические: два PDF проектной стадии в двух
редакциях и один рабочей.
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="revrules-")
os.environ["PIPELINE_OUT"] = os.path.join(_TMP, "build")
os.environ["PIPELINE_CACHE"] = os.path.join(_TMP, "cache")

import pymupdf  # noqa: E402

from pipeline import config, matrix_rules, registry, revisions  # noqa: E402

FONT = pymupdf.Font("cour")


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def cand(file_id, document, value, chain=None):
    c = {"file_id": file_id, "document": document, "value": value, "raw": str(value), "page": 1,
         "stage": "PD", "snippet": f"Этажность {value}", "columns": [value]}
    if chain:
        c["chain"] = chain
    return c


def test_chain_index():
    print("\n1. Место документа в цепочке и выбор актуальной редакции")
    docs = [{"file_id": "F1", "chain_id": "c1", "revision_status": "SUPERSEDED", "predecessor_file_id": None},
            {"file_id": "F2", "chain_id": "c1", "revision_status": "SUPERSEDED", "predecessor_file_id": "F1"},
            {"file_id": "F3", "chain_id": "c1", "revision_status": "CURRENT", "predecessor_file_id": "F2"},
            {"file_id": "F9", "chain_id": None}]
    chains = [{"chain_id": "c1", "reason": None}]
    index = matrix_rules.chain_index(docs, chains)
    ok = check("ранг по предшественникам: исходная 0, актуальная 2",
               [index[f]["rank"] for f in ("F1", "F2", "F3")] == [0, 1, 2] and "F9" not in index, str(index))
    cands = [cand("F1", "ПЗ.pdf", 3, index["F1"]), cand("F2", "ПЗ (1).pdf", 3, index["F2"]),
             cand("F3", "ПЗ (2).pdf", 4, index["F3"])]
    kept = matrix_rules.latest_only(cands)
    ok &= check("остаётся значение актуальной редакции, хотя имена файлов её не выделяют",
                [c["file_id"] for c in kept] == ["F3"], str([c["file_id"] for c in kept]))
    kept = matrix_rules.latest_only(cands[:2])
    ok &= check("если актуальная редакция значение не называет, берётся последняя из тех, где оно есть",
                [c["file_id"] for c in kept] == ["F2"])
    ok &= check("документ без цепочки — редакция по имени файла, как прежде",
                matrix_rules.revision_rank(cand("F9", "ПОС-кор3.pdf", 1))[1] == 3)
    history = matrix_rules.revision_history(cands, {"pages": [("F3", 1)]})
    ok &= check("устаревшая редакция с другим значением видна в истории",
                len(history) == 1 and [h["file_id"] for h in history[0]["superseded"]] == ["F1", "F2"], str(history))
    return ok


def test_copy_rows():
    print("\n1а. Строки-копии реестра не сбивают место в цепочке")
    # Полярная 16, СПА: изм.6 «(ВП)» → изм.6 «(ОП)» → изм.9 «(ВП)»; у «(ОП)» и у изм.9 в той же папке
    # лежит копия без пометки. Копия носит file_id оригинала, предшественника у неё нет
    docs = [{"file_id": "F1", "chain_id": "c4", "revision_status": "SUPERSEDED", "predecessor_file_id": None},
            {"file_id": "F2", "chain_id": "c4", "revision_status": "SUPERSEDED", "predecessor_file_id": "F1"},
            {"file_id": "F2", "chain_id": "c4", "revision_status": "DUPLICATE", "predecessor_file_id": None,
             "duplicate_of": "F2"},
            {"file_id": "F3", "chain_id": "c4", "revision_status": "CURRENT", "predecessor_file_id": "F2"},
            {"file_id": "F3", "chain_id": "c4", "revision_status": "DUPLICATE", "predecessor_file_id": None,
             "duplicate_of": "F3"}]
    index = matrix_rules.chain_index(docs, [{"chain_id": "c4", "reason": None}])
    ok = check("ранг по оригиналам: изм.6 — 0 и 1, изм.9 — 2",
               sorted(index) == ["F1", "F2", "F3"] and [index[f]["rank"] for f in ("F1", "F2", "F3")] == [0, 1, 2],
               str(index))
    ok &= check("статус в цепочке — оригинала, а не копии",
                [index[f]["status"] for f in ("F1", "F2", "F3")] == ["SUPERSEDED", "SUPERSEDED", "CURRENT"],
                str([index[f]["status"] for f in ("F1", "F2", "F3")]))
    cands = [cand("F1", "СПА изм.6 (ВП).pdf", 3, index["F1"]), cand("F2", "СПА изм.6 (ОП).pdf", 3, index["F2"]),
             cand("F3", "СПА изм.9 (ВП).pdf", 4, index["F3"])]
    kept = matrix_rules.latest_only(cands)
    ok &= check("остаётся только изм.9, изм.6 рядом с ней не берётся",
                [c["file_id"] for c in kept] == ["F3"], str([c["file_id"] for c in kept]))
    # порядок не определён (Алтуфьевское): копия с тем же file_id подменяла статус на DUPLICATE,
    # и документ выпадал из спора редакций
    unordered = [{"file_id": "F4", "chain_id": "c5", "revision_status": "CLARIFICATION_REQUIRED"},
                 {"file_id": "F4", "chain_id": "c5", "revision_status": "DUPLICATE", "duplicate_of": "F4"},
                 {"file_id": "F5", "chain_id": "c5", "revision_status": "CLARIFICATION_REQUIRED"}]
    index = matrix_rules.chain_index(unordered, [{"chain_id": "c5", "reason": "редакции не упорядочить"}])
    conflicts = matrix_rules.revision_conflicts([cand("F4", "ПЗ Изм 2.pdf", 3, index["F4"]),
                                                 cand("F5", "ПЗ-кор3.pdf", 4, index["F5"])])
    ok &= check("документ с копией остаётся в споре редакций",
                len(conflicts) == 1 and conflicts[0][0] == {"F4", "F5"}, str(conflicts))
    return ok


def test_conflicts():
    print("\n2. Конфликт редакций — «требует уточнения»")
    unordered = {"chain": "c2", "rank": 0, "status": "CLARIFICATION_REQUIRED",
                 "reason": "редакции не упорядочить: F4 (Изм 2) и F5 (кор3)"}
    cands = [cand("F4", "ПЗ Изм 2.pdf", 3, unordered), cand("F5", "ПЗ-кор3.pdf", 4, unordered)]
    conflicts = matrix_rules.revision_conflicts(cands)
    ok = check("значения расходятся в неупорядоченных редакциях — конфликт",
               len(conflicts) == 1 and conflicts[0][0] == {"F4", "F5"} and "не упорядочить" in conflicts[0][2],
               str(conflicts))
    by_element = [dict(cand("F4", "КР Изм 2.pdf", "B25", unordered), location="ростверки"),
                  dict(cand("F5", "КР-кор3.pdf", "B30", unordered), location="плита"),
                  dict(cand("F4", "КР Изм 2.pdf", "B30", unordered), location="плита")]
    ok &= check("у параметров по элементам разные элементы одного тома не конфликт",
                matrix_rules.revision_conflicts(by_element) == [], str(matrix_rules.revision_conflicts(by_element)))
    by_element.append(dict(cand("F5", "КР-кор3.pdf", "B35", unordered), location="ростверки"))
    got = matrix_rules.revision_conflicts(by_element)
    ok &= check("а один элемент с разными классами в неупорядоченных редакциях — конфликт этого элемента",
                len(got) == 1 and got[0][1] == "ростверки", str(got))
    element_finding = {"violation_label": "NO_VIOLATION", "locations": ["плита"], "criticality": None,
                       "finding_status": "CANDIDATE", "extraction": {"detail": "d"},
                       "evidence": [{"stage": "PD", "file_id": "F4", "pdf_page_number": 1}]}
    matrix_rules.clarify_revisions([element_finding], got)
    ok &= check("запись по другому элементу из тех же томов не трогается", element_finding["violation_label"] == "NO_VIOLATION")
    same = [cand("F4", "ПЗ Изм 2.pdf", 4, unordered), cand("F5", "ПЗ-кор3.pdf", 4, unordered)]
    ok &= check("значения совпали — конфликта нет: какая редакция действует, для сравнения неважно",
                matrix_rules.revision_conflicts(same) == [])
    finding = {"violation_label": "NO_VIOLATION", "comparison_result": "EQUAL_PD_RD", "criticality": None,
               "finding_status": "CANDIDATE", "extraction": {"detail": "значения равны"},
               "evidence": [{"stage": "PD", "file_id": "F5", "pdf_page_number": 1}]}
    matrix_rules.clarify_revisions([finding], conflicts)
    ok &= check("запись с доказательством из такой цепочки уходит на уточнение",
                finding["violation_label"] == "COMPARISON_IMPOSSIBLE"
                and finding["finding_status"] == "CLARIFICATION_REQUIRED"
                and finding["extraction"]["detail"].startswith("конфликт редакций"), str(finding))
    other = {"violation_label": "VIOLATION_PRESENT", "criticality": "x", "finding_status": "CANDIDATE",
             "extraction": {"detail": "d"}, "evidence": [{"stage": "PD", "file_id": "F7", "pdf_page_number": 1}]}
    matrix_rules.clarify_revisions([other], conflicts)
    ok &= check("запись из другого документа не трогается", other["violation_label"] == "VIOLATION_PRESENT")
    # значение-набор с пустым местом: повысительная установка без названной модели (школа на Полярной 25)
    pumps = [cand("F4", "ИОС2 Изм 2.pdf", (None, 15.98, 44.36, "calc"), unordered),
             cand("F5", "ИОС2-кор3.pdf", ("PBS 3 CDM10-5", 15.98, 44.36, "working"), unordered)]
    got = matrix_rules.revision_conflicts(pumps)
    ok &= check("пустое место в наборе значений разбор не роняет, наборы сравниваются", len(got) == 1, str(got))
    return ok


def test_tied_copies():
    print("\n2а. Две копии последней редакции — спор только между ними")
    # Полярная 16: изм.5 лежит двумя файлами «(ВП)» и «(ОП)», изм.2 — прежний выпуск той же цепочки
    tie = {"chain": "c3", "rank": 0, "status": "CLARIFICATION_REQUIRED", "candidates": ["F6", "F7"],
           "reason": "одинаковая редакция у разных файлов: F6 и F7 (изм. 5)"}
    cands = [cand("F5", "АР2 изм.2 (ВП).pdf", 54, tie), cand("F6", "АР2 изм.5 (ВП).pdf", 0, tie),
             cand("F7", "АР2 изм.5 (ОП).pdf", 0, tie)]
    ok = check("прежний выпуск не спорит с копиями последней редакции",
               matrix_rules.revision_conflicts(cands) == [], str(matrix_rules.revision_conflicts(cands)))
    ok &= check("значение берётся у кандидатов в актуальные, прежний выпуск отброшен",
                sorted(c["file_id"] for c in matrix_rules.latest_only(cands)) == ["F6", "F7"])
    split = cands[:2] + [cand("F7", "АР2 изм.5 (ОП).pdf", 54, tie)]
    ok &= check("копии последней редакции расходятся — это конфликт",
                len(matrix_rules.revision_conflicts(split)) == 1)
    ok &= check("если кандидаты значение не называют, берётся прежний выпуск",
                [c["file_id"] for c in matrix_rules.latest_only(cands[:1])] == ["F5"])
    # многозначный параметр: обе копии изм.3 АР1 называют толщины 190 и 300 мм
    same = [cand(fid, name, v, tie) for fid, name in (("F6", "АР1 изм.3 (ВП).pdf"), ("F7", "АР1 изм.3 (ОП).pdf"))
            for v in (190, 300)]
    ok &= check("копии называют один и тот же набор значений — спора нет, хотя значений два",
                matrix_rules.revision_conflicts(same) == [], str(matrix_rules.revision_conflicts(same)))
    misread = [cand("F6", "АР1 изм.3 (ВП).pdf", 1500, tie), cand("F7", "АР1 изм.3 (ОП).pdf", 1000, tie),
               cand("F7", "АР1 изм.3 (ОП).pdf", 1500, tie)]
    ok &= check("наборы у копий разные — спор", len(matrix_rules.revision_conflicts(misread)) == 1)
    return ok


def _row(file_id, path, pages=10, approval="UNKNOWN"):
    return {"file_id": file_id, "relative_path": path, "pdf_pages": pages, "approval_status": approval}


def test_approval_and_manual():
    print("\n3. Признак утверждения и выбор инспектора")
    rows = [_row("A1", "ПД/01-24-П-ПЗ.pdf"), _row("A2", "ПД/01-24-П-ПЗ кор.1.pdf")]
    names = {r["file_id"]: revisions.parse_name(r["relative_path"]) for r in rows}
    codes = {r["file_id"]: revisions.parse_code(names[r["file_id"]]["rest"]) for r in rows}
    chain = revisions.resolve(rows, names, codes)
    ok = check("без признаков утверждения актуальна последняя корректировка",
               chain["status"] == "RESOLVED" and chain["current_file_id"] == "A2", str(chain.get("reason")))
    rows[0]["approval_status"] = "APPROVED"
    chain = revisions.resolve(rows, names, codes)
    ok &= check("утверждена прежняя редакция, последняя нет — требует уточнения",
                chain["status"] == "CLARIFICATION_REQUIRED" and "прежней редакции A1" in chain["reason"], str(chain.get("reason")))
    rows[1]["approval_status"] = "APPROVED"
    chain = revisions.resolve(rows, names, codes)
    ok &= check("утверждены обе — последняя актуальна", chain["status"] == "RESOLVED" and chain["current_file_id"] == "A2")
    rows[1]["approval_status"] = "UNKNOWN"
    strict = revisions.resolve(rows, names, codes, require_approval=True)
    ok &= check("строгий режим ТЗ: без утверждения актуальная не определена", strict["status"] == "CLARIFICATION_REQUIRED")
    chosen = revisions.choose_manually(revisions.resolve(rows, names, codes), {"A2": True})
    ok &= check("выбор инспектора сильнее разбора и помечен как его решение",
                chosen["status"] == "RESOLVED" and chosen["current_file_id"] == "A2"
                and chosen["resolved_by"] == "INSPECTOR" and chosen["member_status"] == {"A1": "SUPERSEDED", "A2": "CURRENT"},
                str(chosen))
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


def _build(obj, root, files, copies=()):
    for rel, text in files:
        _pdf(os.path.join(root, rel), text)
    for src, dst in copies:
        # тот же файл байт в байт в другой папке: реестр заводит строку-копию (`duplicate_of`)
        os.makedirs(os.path.dirname(os.path.join(root, dst)), exist_ok=True)
        shutil.copyfile(os.path.join(root, src), os.path.join(root, dst))
    config.register_object(obj, root, obj, split="EXTERNAL")
    docs = registry.build(obj)
    out_docs, chains = revisions.analyse(obj, docs, None, {}, root=root)
    os.makedirs(os.path.join(config.OUT, obj), exist_ok=True)
    for name, rows in (("documents.jsonl", out_docs), ("revisions.jsonl", chains)):
        with open(os.path.join(config.OUT, obj, name), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    rules = matrix_rules.load_rules(matrix_rules.QUEUES[1])
    findings, _ = matrix_rules.build_findings(obj, rules=rules)
    return out_docs, chains, next((f for f in findings if f["parameter_code"] == "PZ-007"), None)


def test_end_to_end():
    print("\n4. Сквозной путь: реестр → цепочки → правило Матрицы")
    obj = "OBJ-TEST-REV-A"
    docs, chains, finding = _build(obj, os.path.join(_TMP, "А"), [
        ("Проектная документация/01-24-П-ПЗ 12.03.2025.pdf", "Этажность 3"),
        ("Проектная документация/01-24-П-ПЗ 20.05.2025.pdf", "Этажность 4"),
        ("Рабочая документация/01-24-Р-АР.pdf", "Этажность 4"),
    ])
    chain = next((c for c in chains if len(c["members"]) == 2), None)
    ok = check("две редакции без отметок упорядочены по дате, актуальна поздняя",
               chain and chain["status"] == "RESOLVED"
               and docs[[d["file_id"] for d in docs].index(chain["current_file_id"])]["relative_path"].endswith("20.05.2025.pdf"),
               str(chain and chain.get("reason")))
    ok &= check("правило берёт этажность из актуальной редакции: 4 = 4, нарушения нет",
                finding is not None and finding["violation_label"] == "NO_VIOLATION" and finding["pd_value"] == "4",
                str(finding and (finding["violation_label"], finding["pd_value"], finding["rd_value"])))
    revs = ((finding or {}).get("extraction") or {}).get("pd", {}).get("revisions") or []
    ok &= check("устаревшая редакция с другим значением показана в истории записи",
                bool(revs) and revs[0]["superseded"][0]["values"] == ["3"], str(revs))

    obj = "OBJ-TEST-REV-B"
    docs, chains, finding = _build(obj, os.path.join(_TMP, "Б"), [
        ("Проектная документация/01-24-П-ПЗ Изм 2.pdf", "Этажность 3"),
        ("Проектная документация/01-24-П-ПЗ-кор3.pdf", "Этажность 4"),
        ("Рабочая документация/01-24-Р-АР.pdf", "Этажность 4"),
    ])
    chain = next((c for c in chains if len(c["members"]) == 2), None)
    ok &= check("«Изм 2» и «кор3» не упорядочить — цепочка требует уточнения",
                chain and chain["status"] == "CLARIFICATION_REQUIRED", str(chain and chain.get("reason")))
    ok &= check("запись правила — не нарушение и не «нарушения нет», а «требует уточнения» с причиной",
                finding is not None and finding["violation_label"] == "COMPARISON_IMPOSSIBLE"
                and finding["finding_status"] == "CLARIFICATION_REQUIRED"
                and "конфликт редакций" in finding["extraction"]["detail"],
                str(finding and (finding["violation_label"], finding["extraction"]["detail"][:160])))

    obj = "OBJ-TEST-REV-C"
    pd = "Проектная документация/"
    docs, chains, finding = _build(obj, os.path.join(_TMP, "В"), [
        (pd + "01-24-П-ПЗ Изм 1.pdf", "Этажность 3"),
        (pd + "01-24-П-ПЗ Изм 2.pdf", "Этажность 3"),
        (pd + "01-24-П-ПЗ Изм 3.pdf", "Этажность 4"),
        ("Рабочая документация/01-24-Р-АР.pdf", "Этажность 4"),
    ], copies=[(pd + "01-24-П-ПЗ Изм 2.pdf", pd + "Копия/01-24-П-ПЗ Изм 2.pdf"),
               (pd + "01-24-П-ПЗ Изм 3.pdf", pd + "Копия/01-24-П-ПЗ Изм 3.pdf")])
    chain = next((c for c in chains if len(c["members"]) == 3), None)
    ok &= check("копии второй и третьей редакции — строки реестра с file_id оригинала, цепочка из трёх",
                sum(1 for d in docs if d.get("duplicate_of")) == 2 and chain and chain["status"] == "RESOLVED",
                str(chain and (chain["status"], chain.get("reason"))))
    ok &= check("с копиями в реестре правило берёт этажность из третьей редакции: 4 = 4, нарушения нет",
                finding is not None and finding["violation_label"] == "NO_VIOLATION" and finding["pd_value"] == "4",
                str(finding and (finding["violation_label"], finding["pd_value"], finding["rd_value"])))
    return ok


def main():
    ok = True
    for fn in (test_chain_index, test_copy_rows, test_conflicts, test_tied_copies, test_approval_and_manual,
               test_end_to_end):
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
