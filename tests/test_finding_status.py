"""Статус записи по легенде организатора: чего не хватило и что несопоставимо.

  python tests/test_finding_status.py

Легенда к матрице, раздел «Правила присвоения эталонной метки», задаёт словарь:
CANDIDATE — расхождение нашла машина, инспектор не решил; MISSING_EVIDENCE — нет
обязательного документа или фрагмента, и это не нарушение; NOT_COMPARABLE — источники
нельзя корректно сопоставить; CLARIFICATION_REQUIRED — не определена актуальная редакция;
SUSPICION — гипотеза вне Матрицы. Значения перечислены в contracts/enums.json.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import matrix_rules  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def status(label, detail, was=None):
    f = {"violation_label": label, "extraction": {"detail": detail}}
    if was:
        f["finding_status"] = was
    return matrix_rules.finding_status([f])[0].get("finding_status")


def test_missing_evidence():
    """Нечего сравнивать, потому что значения нет — это комплектность, а не нарушение."""
    ok = True
    ok &= check("значение не найдено ни в одной стадии",
                status("COMPARISON_IMPOSSIBLE", "значение не найдено ни в одной стадии") == "MISSING_EVIDENCE")
    ok &= check("значение в рабочей стадии не найдено",
                status("COMPARISON_IMPOSSIBLE", "значение в рабочей стадии не найдено") == "MISSING_EVIDENCE")
    ok &= check("номера групп в стадии не найдены",
                status("COMPARISON_IMPOSSIBLE", "Групп ВРУ в рабочей стадии не найдено") == "MISSING_EVIDENCE")
    ok &= check("документ отсутствует", status("MISSING_DOCUMENT", "") == "MISSING_EVIDENCE")
    return ok


def test_not_comparable():
    """Источники есть, но сопоставить их нельзя: это не нехватка документа."""
    ok = True
    ok &= check("номера не совпадают",
                status("COMPARISON_IMPOSSIBLE",
                       "номера групп ВРУ в ПД и РД не совпадают: сопоставить нечего") == "NOT_COMPARABLE")
    ok &= check("значение не из раздела-источника",
                status("COMPARISON_IMPOSSIBLE",
                       "оба значения не из раздела-источника и расходятся: B40 → B30") == "NOT_COMPARABLE")
    ok &= check("привязка слабее указаний",
                status("COMPARISON_IMPOSSIBLE",
                       "уменьшение А400 → А240 видно только в таблице листа или по пути файла, "
                       "в указаниях рабочей стадии значение не названо") == "NOT_COMPARABLE")
    ok &= check("часть здания не определить",
                status("COMPARISON_IMPOSSIBLE",
                       "900/600 → 800: в рабочей стадии есть 800 мм, меньше проектного наибольшего; "
                       "какой части здания это значение, по тексту не определить") == "NOT_COMPARABLE")
    return ok


def test_keeps_decisions():
    """Решения машина эталонной меткой не делает, а чужой статус не перебивает."""
    ok = True
    ok &= check("нарушение остаётся кандидатом",
                status("VIOLATION_PRESENT", "уменьшение: B40 → B30") == "CANDIDATE")
    ok &= check("«нарушения нет» остаётся кандидатом",
                status("NO_VIOLATION", "значения совпадают: B40 и B40") == "CANDIDATE")
    ok &= check("конфликт редакций не перебивается",
                status("COMPARISON_IMPOSSIBLE", "значение не найдено",
                       was="CLARIFICATION_REQUIRED") == "CLARIFICATION_REQUIRED")
    ok &= check("гипотеза свободного поиска не перебивается",
                status("VIOLATION_PRESENT", "элемента нет в рабочей стадии",
                       was="SUSPICION") == "SUSPICION")
    return ok


def test_enums():
    """Все статусы, которые ставит конвейер, объявлены в контракте."""
    with open(os.path.join(ROOT, "contracts", "enums.json"), encoding="utf-8") as f:
        allowed = set(json.load(f)["finding_status"]) - {"$comment"}
    used = {"CANDIDATE", "MISSING_EVIDENCE", "NOT_COMPARABLE", "CLARIFICATION_REQUIRED", "SUSPICION"}
    return check("статусы конвейера есть в contracts/enums.json", used <= allowed, str(used - allowed))


if __name__ == "__main__":
    print("Статус записи (легенда организатора)")
    results = [test_missing_evidence(), test_not_comparable(), test_keeps_decisions(), test_enums()]
    print("\nИТОГ: " + ("все проверки пройдены" if all(results) else "есть сбои"))
    sys.exit(0 if all(results) else 1)
