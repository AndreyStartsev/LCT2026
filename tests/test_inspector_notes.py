"""Пометки для инспектора у непроверенных параметров: коротко, по существу, без внутренней кухни (28.09).

  python tests/test_inspector_notes.py

Пометка `inspector_note` видна на дашборде в клетке «не проверено» и в отчёте. 28.09 пользователь
увидел там «Правила пока нет … специалист велел показывать гипотезой — это ещё не сделано. Черновик
правила разобран со специалистом»: это заметки разработки, а не слова для инспектора. Теперь каждая
пометка — «Правило на проверке:» и одна фраза о том, почему параметр пока не сравнивается.
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# слова разработки: чьи решения, что не доделано, номера задач и решений, корпус
KITCHEN = re.compile(r"специалист|черновик|велел|ещё не|еще не|не сделано|разобран|корпус|#\d|Р-\d", re.I)


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def main():
    notes = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "rules", "matrix_queue*.json"))):
        for code, rule in (json.load(open(path, encoding="utf-8")).get("parameters") or {}).items():
            if rule.get("inspector_note"):
                notes[code] = (rule["inspector_note"], rule.get("implemented"))
    ok = check("пометки есть у всех нереализованных параметров с объяснением", len(notes) >= 17, str(len(notes)))
    bad = [f"{c}: {t}" for c, (t, impl) in notes.items() if not impl and not t.startswith("Правило на проверке: ")]
    ok &= check("у нереализованного параметра пометка начинается с «Правило на проверке:»", not bad, "; ".join(bad))
    bad = [f"{c}: {t}" for c, (t, _) in notes.items() if KITCHEN.search(t)]
    ok &= check("в пометках нет внутренней кухни: чьи решения, что не доделано, номера задач", not bad, "; ".join(bad))
    bad = [f"{c}: {len(t)}" for c, (t, _) in notes.items() if len(t) > 170 or not t.endswith(".") or ".." in t]
    ok &= check("пометка — одна фраза до 170 знаков с точкой", not bad, "; ".join(bad))
    # тексты, которые конвейер пишет в записи: пояснения, причины уверенности, статусы черновых правил
    import ast
    bad = []
    for path in sorted(glob.glob(os.path.join(ROOT, "pipeline", "*.py"))):
        if path.endswith("cli.py"):
            continue                       # вывод командной строки для разработчиков
        tree = ast.parse(open(path, encoding="utf-8").read())
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and len(n.value) > 15 \
                    and re.search(r"\bР-\d|#\d|шестой круг|четвёртый круг|по решению специалиста|специалист (допустил|признал|считает|велел)"
                                  r"|решение специалиста|черновик правила ждёт|организатор", n.value):
                bad.append(f"{os.path.basename(path)}:{n.lineno}")
    ok &= check("в текстах записей конвейера нет номеров решений и задач, кругов и «специалист велел»", not bad,
                ", ".join(bad))
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
