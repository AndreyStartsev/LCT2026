"""Инкрементальный пересчёт при дозагрузке. Задача #60.

  python tests/test_incremental.py

Организатор: «При дозагрузке файлов система не запускает весь объект заново, а
пересчитывает только те параметры, которых коснулись новые документы».

Опасность у такой экономии одна: перенести запись, которая на самом деле изменилась.
Поэтому проверяется не только то, что пересчитывается меньше, но и то, что считается
заново в сомнительных случаях — пропал документ, инспектор поправил стадию, новый
документ встал в цепочку редакций к прежнему.

Кандидаты правил кешируются по содержимому документа и хешу правил. Здесь проверяется,
что ключ кеша стареет вместе с текстом и правилами, а значения не портятся при записи
в JSON: значение правила бывает кортежем, а JSON кортежей не знает.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import incremental  # noqa: E402
from pipeline import matrix_rules as mr  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def docs(*items):
    return [{"file_id": f, "sha256": s, "stage": st, "chain_id": ch}
            for f, s, st, ch in items]


BEFORE = docs(("F1", "aa", "PD", "c1"), ("F2", "bb", "RD", "c2"))


def test_what_changed():
    ok = True
    same = incremental.plan(BEFORE, BEFORE)
    ok &= check("ничего не пришло — пересчитывать нечего", same[0] is False and same[1] == set(), str(same))
    added = docs(("F1", "aa", "PD", "c1"), ("F2", "bb", "RD", "c2"), ("F3", "cc", "ID", "c3"))
    full, fresh, _ = incremental.plan(added, BEFORE)
    ok &= check("новый документ считается один", full is False and fresh == {"F3"}, str(fresh))
    replaced = docs(("F1", "aa", "PD", "c1"), ("F2", "zz", "RD", "c2"))
    full, fresh, _ = incremental.plan(replaced, BEFORE)
    ok &= check("документ заменили — считается он", full is False and fresh == {"F2"}, str(fresh))
    full, _, why = incremental.plan(docs(("F1", "aa", "PD", "c1")), BEFORE)
    ok &= check("документ пропал — считается весь объект", full is True, why)
    full, _, why = incremental.plan(BEFORE, [])
    ok &= check("прошлого разбора нет — считается весь объект", full is True, why)
    return ok


def test_chain_guard():
    """Новая редакция прежнего документа меняет значения у параметров, которых не упоминает."""
    with_revision = docs(("F1", "aa", "PD", "c1"), ("F2", "bb", "RD", "c2"), ("F3", "cc", "RD", "c2"))
    ok = check("новый документ в цепочке прежнего — пересчёт целиком",
               incremental.chain_broken(with_revision, {"F3"}))
    alone = docs(("F1", "aa", "PD", "c1"), ("F3", "cc", "ID", "c9"))
    ok &= check("документ со своей цепочкой пересчёт не расширяет",
                not incremental.chain_broken(alone, {"F3"}))
    ok &= check("цепочка целиком новая — тоже не расширяет",
                not incremental.chain_broken(docs(("F3", "cc", "RD", "c2"), ("F4", "dd", "RD", "c2")),
                                             {"F3", "F4"}))
    return ok


def test_rows_kept_and_merged():
    prev = [{"file_id": "F1", "pdf_page_number": 1, "text": "было"},
            {"file_id": "F2", "pdf_page_number": 1, "text": "было"}]
    fresh = [{"file_id": "F2", "pdf_page_number": 1, "text": "стало"},
             {"file_id": "F2", "pdf_page_number": 2, "text": "новая"}]
    kept = incremental.keep(prev, {"F2"})
    ok = check("строки изменившегося документа выбрасываются", [r["file_id"] for r in kept] == ["F1"])
    merged = incremental.merge(kept, fresh)
    ok &= check("строки склеены без потерь", len(merged) == 3, str(len(merged)))
    ok &= check("порядок как при полном разборе",
                [(r["file_id"], r["pdf_page_number"]) for r in merged] == [("F1", 1), ("F2", 1), ("F2", 2)])
    ok &= check("пересчитанная строка победила", merged[1]["text"] == "стало")
    return ok


def test_affected_codes():
    rules = {"parameters": {
        "PZ-001": {"kind": "area", "implemented": True},
        "IOS4-010": {"kind": "room_systems", "implemented": True},
        "IOS1-020": {"kind": "resource_meters", "implemented": True},
    }}
    documents = docs(("F1", "aa", "PD", "c1"), ("F3", "cc", "ID", "c3"))
    ok = check("акт исполнительной стадии не трогает таблицы систем и приборы учёта",
               incremental.affected_codes(rules, set(), documents, {"F3"}) == set())
    ok &= check("параметр, по которому новый документ дал кандидата, пересчитывается",
                incremental.affected_codes(rules, {"PZ-001"}, documents, {"F3"}) == {"PZ-001"})
    rd = docs(("F4", "dd", "RD", "c4"))
    ok &= check("новый том рабочей стадии трогает правила, читающие документы сами",
                incremental.affected_codes(rules, set(), rd, {"F4"}) == {"IOS4-010", "IOS1-020"})
    pd = docs(("F5", "ee", "PD", "c5"))
    ok &= check("проектный том трогает таблицы систем, но не приборы учёта",
                incremental.affected_codes(rules, set(), pd, {"F5"}) == {"IOS4-010"})
    mixed = docs(("F6", "ff", "RD_ID_MIXED", "c6"))
    ok &= check("смешанная папка считается рабочей стадией",
                incremental.affected_codes(rules, set(), mixed, {"F6"}) == {"IOS4-010", "IOS1-020"})
    return ok


def test_candidate_cache_key():
    """Ключ кеша кандидатов стареет вместе с текстом и правилами."""
    a = {"parameters": {"PZ-001": {"labels": ["площадь застройки"], "implemented": True}}, "classes": {}}
    b = {"parameters": {"PZ-001": {"labels": ["площадь застройки", "площадь"], "implemented": True}}, "classes": {}}
    ok = check("правки правил меняют ключ", mr._rules_digest(a) != mr._rules_digest(b))
    ok &= check("те же правила — тот же ключ", mr._rules_digest(a) == mr._rules_digest(dict(a)))
    pages = [(1, "площадь застройки 1 200 м2", "TEXT_LAYER")]
    later = [(1, "площадь застройки 1 200 м2", "RECOGNIZED")]
    more = [(1, "площадь застройки 1 200 м2", "TEXT_LAYER"), (2, "ещё страница", "TEXT_LAYER")]
    ok &= check("распознанный позже текст меняет отпечаток", mr._text_digest(pages) != mr._text_digest(later))
    ok &= check("дочитанная страница меняет отпечаток", mr._text_digest(pages) != mr._text_digest(more))
    ok &= check("тот же текст — тот же отпечаток", mr._text_digest(pages) == mr._text_digest(list(pages)))
    return ok


def test_candidate_cache_values():
    """Значение правила бывает кортежем: через JSON оно должно вернуться кортежем."""
    value = {"value": ("5000", "300"), "columns": ["ВЕ1"], "nested": [{"v": (1, 2)}], "n": 3.5, "none": None}
    back = mr._decode(mr._encode(value))
    ok = check("кортеж пережил запись в кеш", back == value and isinstance(back["value"], tuple), str(back["value"]))
    ok &= check("список остался списком", isinstance(back["columns"], list))
    ok &= check("кортеж внутри списка тоже", isinstance(back["nested"][0]["v"], tuple))
    return ok


def main():
    ok = True
    for title, fn in (("Что изменилось", test_what_changed),
                      ("Цепочки редакций", test_chain_guard),
                      ("Перенос строк разбора", test_rows_kept_and_merged),
                      ("Какие параметры затронуты", test_affected_codes),
                      ("Ключ кеша кандидатов", test_candidate_cache_key),
                      ("Значения в кеше кандидатов", test_candidate_cache_values)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
