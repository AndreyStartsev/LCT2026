"""Проверка протокола проверки объекта: покрытие Матрицы, комплектность, изменения версии. Задача #30.

  python tests/test_protocol.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import protocol  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def finding(fid, code, label, pd="1", rd="2", detail=None):
    return {"finding_id": fid, "parameter_code": code, "violation_label": label, "pd_value": pd, "rd_value": rd,
            "extraction": {"detail": detail}}


def test_completeness():
    ok = True
    present = {"PD", "RD"}
    ok &= check("сравнение выполнено — COMPLETE",
                protocol.completeness(finding("a", "PZ-1", "NO_VIOLATION"), present) == ("COMPLETE", None))
    got = protocol.completeness(finding("a", "PZ-1", "COMPARISON_IMPOSSIBLE", rd=None,
                                        detail="значение в рабочей стадии не найдено"), present)
    ok &= check("значение не найдено в загруженной стадии — MISSING_EVIDENCE с причиной конвейера",
                got == ("MISSING_EVIDENCE", "значение в рабочей стадии не найдено"), str(got))
    got = protocol.completeness(finding("a", "PZ-1", "COMPARISON_IMPOSSIBLE", rd=None), {"PD"})
    ok &= check("стадия не загружена — MISSING_EVIDENCE «нет РД»",
                got[0] == "MISSING_EVIDENCE" and got[1].startswith("нет РД"), str(got))
    got = protocol.completeness(finding("a", "PZ-1", "COMPARISON_IMPOSSIBLE",
                                        detail="оба значения не из раздела-источника и расходятся"), present)
    ok &= check("оба значения есть, но сравнить нельзя — NOT_COMPARABLE", got[0] == "NOT_COMPARABLE", str(got))
    ok &= check("стадии процесса по статусам загрузки",
                protocol.stages_present(["PD_UPLOADED", "RD_PARTIAL", "ID_MISSING"]) == {"PD", "RD"})
    f = finding("a", "PZ-1", "COMPARISON_IMPOSSIBLE", rd=None, detail="значение в рабочей стадии не найдено")
    ok &= check("стадия загружена, значение не найдено — метка остаётся",
                protocol.mark_absent_stage(dict(f), present) is None)
    marked = dict(f)
    stage = protocol.mark_absent_stage(marked, {"PD"})
    ok &= check("стадии нет вовсе — MISSING_DOCUMENT и RD_MISSING по перечню организатора",
                stage == "RD" and marked["violation_label"] == "MISSING_DOCUMENT" and marked["protocol_status"] == "RD_MISSING",
                str(marked.get("protocol_status")))
    got = protocol.completeness(marked, {"PD"})
    ok &= check("после отметки причина комплектности та же — «нет РД»", got[0] == "MISSING_EVIDENCE" and got[1].startswith("нет РД"),
                str(got))
    ok &= check("решённая правилом запись не отмечается",
                protocol.mark_absent_stage(finding("a", "PZ-1", "NO_VIOLATION", rd="5"), {"PD"}) is None)
    return ok


def test_coverage():
    ok = True
    catalog = [
        {"parameter_id": 1, "parameter_code": "PZ-001", "pd_section": "Раздел 1. ПЗ", "parameter_name": "Площадь застройки",
         "criticality": "Критическое (приостановка работ)"},
        {"parameter_id": 2, "parameter_code": "PZ-002", "pd_section": "Раздел 1. ПЗ", "parameter_name": "Общая площадь"},
        {"parameter_id": 55, "parameter_code": "KR-055", "pd_section": "Раздел 4. КР", "parameter_name": "Класс бетона"},
        {"parameter_id": 54, "parameter_code": "KR-054", "pd_section": "Раздел 4. КР", "parameter_name": "Шаг осей"},
        {"parameter_id": 108, "parameter_code": "PPM-108", "pd_section": "Раздел 9. ППМ", "parameter_name": "Извещатели"},
    ]
    rules = {1: {"parameters": {"PZ-001": {"implemented": True}, "PZ-002": {"implemented": True}}},
             2: {"parameters": {"KR-055": {"implemented": True}, "KR-054": {"implemented": False, "reason": "размер на чертеже"}}}}
    findings = [finding("O::PZ-001", "PZ-001", "NO_VIOLATION"),
                finding("O::KR-055::плита", "KR-055", "NO_VIOLATION"),
                finding("O::KR-055::стены", "KR-055", "COMPARISON_IMPOSSIBLE", rd=None)]
    cov = {c["parameter_code"]: c for c in protocol.coverage(catalog, rules, findings, {"PD", "RD"})}
    ok &= check("все параметры каталога в покрытии", len(cov) == 5)
    ok &= check("раздел из «Раздел 4. КР»", cov["KR-055"]["section"] == "КР")
    ok &= check("правило есть, записей нет — MISSING_EVIDENCE", cov["PZ-002"]["status"] == "MISSING_EVIDENCE")
    ok &= check("параметр по элементам сопоставлен, если сравнена хотя бы одна запись",
                cov["KR-055"]["status"] == "COMPLETE", cov["KR-055"]["status"])
    ok &= check("нереализованное правило — NOT_CHECKED с причиной правила",
                cov["KR-054"]["status"] == "NOT_CHECKED" and cov["KR-054"]["reason"] == "размер на чертеже")
    ok &= check("у нереализованного правила без пометки для инспектора пометки нет", "note" not in cov["KR-054"])
    noted = {q: {"parameters": dict(r["parameters"])} for q, r in rules.items()}
    noted[2]["parameters"]["KR-054"] = {"implemented": False, "reason": "размер на чертеже",
                                        "inspector_note": "Правила пока нет: шаг осей — размер на чертеже."}
    got = {c["parameter_code"]: c for c in protocol.coverage(catalog, noted, findings, {"PD", "RD"})}
    ok &= check("пометка для инспектора (inspector_note) — в note, причина разработки остаётся в reason",
                got["KR-054"]["note"] == "Правила пока нет: шаг осей — размер на чертеже."
                and got["KR-054"]["reason"] == "размер на чертеже", str(got["KR-054"]))
    ok &= check("очередь не взята в работу — NOT_CHECKED с номером очереди",
                cov["PPM-108"]["status"] == "NOT_CHECKED" and cov["PPM-108"]["queue"] == 3
                and "очереди 3" in cov["PPM-108"]["reason"], cov["PPM-108"]["reason"])
    # параметр, который по документам не проверяется (OOS-098…101, AR-050): свой статус с причиной
    oos = {"parameters": {"OOS-098": {"implemented": False, "reason": "заметка разработки",
                                       "out_of_scope": {"kind": "EXTERNAL", "reason": "событие в АИС «ОСИГ»"}}}}
    got = {c["parameter_code"]: c for c in protocol.coverage(
        catalog + [{"parameter_id": 98, "parameter_code": "OOS-098", "pd_section": "ООС", "parameter_name": "ОСИГ"}],
        {**rules, 5: oos}, findings, {"PD", "RD"})}
    ok &= check("вне проверки документов — OUT_OF_SCOPE с причиной из out_of_scope",
                got["OOS-098"]["status"] == "OUT_OF_SCOPE" and got["OOS-098"]["reason"] == "событие в АИС «ОСИГ»"
                and got["OOS-098"]["out_of_scope"] == "EXTERNAL", str(got["OOS-098"]))
    # параметр без правила прода, который проверяет черновик (#95): гипотеза, а не проверка
    draft = [dict(finding("O::KR-054", "KR-054", "VIOLATION_PRESENT"), provisional=True)]
    got = {c["parameter_code"]: c for c in protocol.coverage(
        catalog, rules, findings, {"PD", "RD"}, provisional={"KR-054": draft, "PPM-108": []})}
    ok &= check("черновик нашёл нарушение — HYPOTHESIS, гипотеза в записях параметра",
                got["KR-054"]["status"] == "HYPOTHESIS" and got["KR-054"]["findings"] == ["O::KR-054"]
                and got["KR-054"]["hypothesis"]["violation"] == 1 and not got["KR-054"]["implemented"],
                str(got["KR-054"]))
    ok &= check("черновик ничего не нашёл — всё равно HYPOTHESIS, «значение не найдено»",
                got["PPM-108"]["status"] == "HYPOTHESIS" and "значение не найдено" in got["PPM-108"]["reason"],
                got["PPM-108"]["reason"])
    ok &= check("правило прода черновиком не перебивается", got["KR-055"]["status"] == "COMPLETE")
    ok &= check("без профиля черновиков — прежний NOT_CHECKED",
                {c["parameter_code"]: c for c in protocol.coverage(catalog, rules, findings, {"PD", "RD"})}
                ["KR-054"]["status"] == "NOT_CHECKED")
    from pipeline import matrix_rules
    marked = matrix_rules.mark_provisional([finding("O::A", "KR-054", "VIOLATION_PRESENT"),
                                            finding("O::B", "KR-060", "NO_VIOLATION"),
                                            finding("O::C", "KR-061", "COMPARISON_IMPOSSIBLE", rd=None)])
    ok &= check("в протокол гипотезами — только нарушения черновика",
                [f["finding_id"] for f in matrix_rules.provisional_hypotheses(marked)] == ["O::A"])
    # исполнительная документация загружена: у параметра без значения в ней названа причина (Д-57)
    catalog[0]["source_id"] = "Технический план БТИ; ЗОС"
    catalog[2]["source_id"] = "АОСР; исполнительная схема"
    cov = {c["parameter_code"]: c for c in protocol.coverage(catalog, rules, findings, {"PD", "RD", "ID"})}
    ok &= check("источник в ИД — только документы ввода: причина «у строящегося объекта его нет»",
                cov["PZ-001"]["id_status"] == "NOT_FOUND" and "документ ввода" in cov["PZ-001"]["id_reason"],
                cov["PZ-001"].get("id_reason"))
    ok &= check("источник в ИД есть на стройке, значения нет — пробел комплекта",
                cov["KR-055"]["id_status"] == "NOT_FOUND" and cov["KR-055"]["id_reason"] == "в загруженной исполнительной документации значение не найдено")
    ok &= check("без ИД в комплекте статуса по ИД нет", "id_status" not in
                {c["parameter_code"]: c for c in protocol.coverage(catalog, rules, findings, {"PD", "RD"})}["PZ-001"])
    return ok


def test_changes():
    ok = True
    previous = {
        "O::A": {"pd_value": "1", "rd_value": "2", "violation_label": "VIOLATION_PRESENT", "verification_status": "CONFIRMED_VIOLATION"},
        "O::B": {"pd_value": "5", "rd_value": None, "violation_label": "COMPARISON_IMPOSSIBLE", "verification_status": "NOT_REQUIRED"},
        "O::C": {"pd_value": "7", "rd_value": "7", "violation_label": "NO_VIOLATION", "verification_status": "NOT_REQUIRED"},
        "O::A::split-1": {"pd_value": "1", "rd_value": "2", "violation_label": "VIOLATION_PRESENT",
                          "verification_status": "PENDING", "origin": "INSPECTOR_SPLIT"},
    }
    current = [finding("O::A", "X", "VIOLATION_PRESENT", pd="1", rd="3"),
               finding("O::B", "X", "NO_VIOLATION", pd="5", rd="5"),
               finding("O::D", "X", "NO_VIOLATION")]
    diff = protocol.changes(previous, current)
    ok &= check("новая запись", diff["added"] == ["O::D"])
    ok &= check("пропавшая запись, части разделённой записи не считаются пропавшими", diff["removed"] == ["O::C"],
                str(diff["removed"]))
    ok &= check("изменились значения", [c["finding_id"] for c in diff["changed"]] == ["O::A", "O::B"])
    ok &= check("решение инспектора относилось к прежним значениям — на пересмотр",
                [c["finding_id"] for c in diff["decided_changed"]] == ["O::A"]
                and diff["decided_changed"][0]["before"]["rd_value"] == "2")
    return ok


def main():
    ok = True
    for title, fn in (("Комплектность записи", test_completeness), ("Покрытие Матрицы", test_coverage),
                      ("Изменения версии", test_changes)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
