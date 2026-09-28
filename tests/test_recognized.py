"""Распознанное значение не решает молча. Задача #41.

  python tests/test_recognized.py

Правила читают страницы, распознанные машиной, и цифры там путаются. Проверяется, что
такое значение не принимается наравне со значением из текстового слоя: похожее на ошибку
чтения откладывается под вопрос, расхождение со слоем и нарушение по распознанному
значению требуют подтверждения инспектора, привязка «лист» названа в пояснении.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import matrix_rules  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def cand(value, raw, page, source=None, binding="CLAUSE", file_id="F"):
    c = {"value": value, "raw": raw, "columns": [raw], "snippet": raw, "file_id": file_id, "page": page,
         "binding": binding, "location": "стена"}
    if source:
        c["text_source"] = source
    return c


def test_doubts():
    print("\n1. Похожее на ошибку чтения откладывается")
    ok = check("одна цифра: B30 и B50", matrix_rules._one_digit_apart("B30", "B50"))
    ok &= check("две цифры — не похоже: 1200 и 1050", not matrix_rules._one_digit_apart("1200", "1050"))
    ok &= check("буква — не цифра: B30 и C30", not matrix_rules._one_digit_apart("B30", "C30"))
    ok &= check("разная длина: 100 и 1000", not matrix_rules._one_digit_apart("100", "1000"))
    cands = [cand(30, "B30", p, "RECOGNIZED") for p in range(1, 10)] + [cand(50, "B50", 11, "RECOGNIZED"), cand(50, "B50", 12, "RECOGNIZED")]
    doubts = matrix_rules.recognized_doubts(cands)
    ok &= check("B50 дважды рядом с B30 девять раз, всё распознано — отложено",
                len(doubts) == 1 and doubts[0]["value"] == "B50" and doubts[0]["against"] == "B30"
                and doubts[0]["mentions"] == 2 and doubts[0]["against_mentions"] == 9, str(doubts))
    cands = [cand(30, "B30", p, "RECOGNIZED") for p in range(1, 10)] + [cand(50, "B50", 11)]
    ok &= check("B50 из текстового слоя не откладывается", matrix_rules.recognized_doubts(cands) == [])
    cands = [cand(30, "B30", p, "RECOGNIZED") for p in range(1, 4)] + [cand(50, "B50", p, "RECOGNIZED") for p in (5, 6)]
    ok &= check("3 против 2 — не редкость, сомнения нет", matrix_rules.recognized_doubts(cands) == [])
    cands = [cand(30, "B30", p, "RECOGNIZED") for p in range(1, 10)] + [cand(40, "B40", 11, "RECOGNIZED")]
    ok &= check("B40 против B30 — другая цифра той же позиции, тоже похоже на ошибку", len(matrix_rules.recognized_doubts(cands)) == 1)
    cands = [cand(30, "B30", p, "RECOGNIZED") for p in range(1, 10)] + [cand(60, "B60", 11, "RECOGNIZED"), cand(8, "W8", 12, "RECOGNIZED")]
    got = matrix_rules.recognized_doubts(cands)
    ok &= check("W8 не похоже ни на что — не откладывается; B60 — да", [d["value"] for d in got] == ["B60"], str(got))
    return ok


def test_reconcile():
    print("\n2. Согласование стадии с распознанными значениями")
    rule = {"kind": "element_class", "compare": {"type": "class_downgrade", "result": "CLASS_DOWNGRADE"}}
    cands = [cand(30, "B30", p, "RECOGNIZED") for p in range(1, 10)] + [cand(50, "B50", 11, "RECOGNIZED")]
    side = matrix_rules.reconcile_set(rule, cands)
    ok = check("множество элемента без отложенного значения: B30, не B30/B50", side["raw"] == "B30", side["raw"])
    ok &= check("отложенное видно в стороне", side.get("doubtful") and side["doubtful"][0]["value"] == "B50", str(side.get("doubtful")))
    ok &= check("сторона помечена как распознанная", side["text_source"] == "RECOGNIZED")
    cands = [cand(30, "B30", 1, "RECOGNIZED"), cand(50, "B50", 2, binding="SHEET")]
    side = matrix_rules.reconcile_set(rule, cands)
    ok &= check("указания распознаны как B30, лист из слоя — B50: конфликт со слоем назван",
                side["raw"] == "B30" and side.get("layer_conflict") == "B50", str(side))
    cands = [cand(30, "B30", 1), cand(50, "B50", 2, binding="SHEET")]
    side = matrix_rules.reconcile_set(rule, cands)
    ok &= check("обе из слоя — конфликта со слоем нет", "layer_conflict" not in side)
    # числовое значение: голосование страниц
    density = {}
    cands = [cand(3694.6, "3694,60", p, "RECOGNIZED") for p in (1, 2, 3)] + [cand(3694.8, "3694,80", 4, "RECOGNIZED")] * 1
    side = matrix_rules.reconcile(cands, density)
    ok &= check("число: 3694,80 один раз рядом с 3694,60 трижды — отложено, победило 3694,60",
                side["raw"] == "3694,60" and side.get("doubtful") and side["doubtful"][0]["value"] == "3694,80", str(side.get("doubtful")))
    cands = [cand(4.0, "4", p, "RECOGNIZED") for p in (1, 2)] + [cand(5.0, "5", 3)]
    side = matrix_rules.reconcile(cands, density)
    ok &= check("победило распознанное 4 (две страницы), слой даёт 5 — конфликт назван",
                side["raw"] == "4" and side.get("layer_conflict") == "5", str(side))
    cands = [cand(4.0, "4", 1, "RECOGNIZED"), cand(4.0, "4", 2)]
    side = matrix_rules.reconcile(cands, density)
    ok &= check("распознанное подтверждено слоем — конфликта нет", "layer_conflict" not in side and side["text_source"] == "RECOGNIZED")
    return ok


def finding(label, pd, rd, built=None):
    return {"violation_label": label, "extraction": {"detail": "d", "pd": pd, "rd": rd, "id": built}}


def test_review():
    print("\n3. Что следует из распознанного значения")
    f = finding("NO_VIOLATION", {"value": 4, "raw": "4"}, {"value": 4, "raw": "4", "text_source": "RECOGNIZED"})
    matrix_rules.recognized_review([f])
    ok = check("совпадение со слоем: помечено, подтверждения не требует",
               not f.get("needs_expert") and f["extraction"]["recognized"] == {"stages": ["RD"], "confirmation": False}
               and "прочитано распознаванием" in f["extraction"]["detail"], f["extraction"]["detail"])
    f = finding("VIOLATION_PRESENT", {"value": 4, "raw": "4"}, {"value": 5, "raw": "5", "text_source": "RECOGNIZED"})
    matrix_rules.recognized_review([f])
    ok &= check("нарушение по распознанному значению — требует подтверждения",
                f.get("needs_expert") is True and "нарушение опирается на распознанное" in f["extraction"]["detail"]
                and "расходится со значением из текстового слоя" in f["extraction"]["detail"], f["extraction"]["detail"])
    f = finding("NO_VIOLATION", {"value": 4.0, "raw": "4,0"}, {"value": 4.1, "raw": "4,1", "text_source": "RECOGNIZED"})
    matrix_rules.recognized_review([f])
    ok &= check("нарушения нет, но распознанное расходится со слоем (допуск) — подтверждение", f.get("needs_expert") is True)
    f = finding("NO_VIOLATION", {"value": 4, "raw": "4"}, {"value": 4, "raw": "4", "text_source": "RECOGNIZED", "layer_conflict": "5"})
    matrix_rules.recognized_review([f])
    ok &= check("слой других страниц даёт иное — подтверждение", f.get("needs_expert") is True and "даёт 5" in f["extraction"]["detail"])
    f = finding("NO_VIOLATION", {"value": [30], "raw": "B30"},
                {"value": [30], "raw": "B30", "text_source": "RECOGNIZED",
                 "doubtful": [{"value": "B50", "mentions": 3, "against": "B30", "against_mentions": 62}]})
    matrix_rules.recognized_review([f])
    ok &= check("отложенное значение — вопрос инспектору",
                f.get("needs_expert") is True and "«B50» (3) рядом с «B30» (62)" in f["extraction"]["detail"], f["extraction"]["detail"])
    f = finding("NO_VIOLATION", {"value": 4, "raw": "4"}, {"value": 4, "raw": "4"})
    matrix_rules.recognized_review([f])
    ok &= check("всё из слоя — запись не тронута", "recognized" not in f["extraction"] and f["extraction"]["detail"] == "d")
    f = finding("VIOLATION_PRESENT", {"value": 4, "raw": "4"}, {"value": 4, "raw": "4"}, {"value": 5, "raw": "5", "text_source": "RECOGNIZED"})
    matrix_rules.recognized_review([f])
    ok &= check("исполнительная стадия распознана и даёт нарушение — подтверждение",
                f.get("needs_expert") is True and "исполнительной стадии прочитано" in f["extraction"]["detail"])
    return ok


def test_binding():
    print("\n4. Привязка не из указаний — в пояснении")
    ok = check("указания — пояснения нет", matrix_rules.binding_note({"binding": "CLAUSE"}, {"binding": "CLAUSE"}) is None)
    got = matrix_rules.binding_note({"binding": "CLAUSE"}, {"binding": "SHEET"})
    ok &= check("лист в рабочей стадии", got == "значение рабочей стадии взято с листа чертежа; на чертеже значение может относиться к соседнему элементу", got)
    got = matrix_rules.binding_note({"binding": "PAGE"}, None, {"binding": "PATH"})
    ok &= check("страница и путь", got == "значение проектной стадии взято со страницы, не из указаний; значение исполнительной стадии взято по пути файла", got)
    return ok


def main():
    ok = True
    for fn in (test_doubts, test_reconcile, test_review, test_binding):
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
