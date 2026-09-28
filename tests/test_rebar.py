"""Проверка класса рабочей арматуры по элементам. KR-057, вторая очередь Матрицы.

  python tests/test_rebar.py

Фрагменты взяты с настоящих страниц корпуса: проектная и рабочая стадии Новослободской
(контрольная точка ANN-0001) и акт освидетельствования той же работы. У каждой проверки
написано, какую ошибку она ловит.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import matrix_rules, rebar  # noqa: E402

# ПД, F0105 стр. 13: элемент назван предложением раньше, назначения — в одном предложении
PD = ("Далее бетонируется монолитная железобетонная форшахта – балка прямоугольного профиля "
      "шириной 400мм, высотой 1000 мм. Для бетонирования применяется бетон класса В15 "
      "(F и W не регламентируются) ГОСТ 26633-2015. Армирование производится сборными и "
      "вязанными арматурными каркасами, основная рабочая арматура А400, конструктивная А240 "
      "по ГОСТ 34028-2016.")
# РД, F0137 стр. 2: назначение и элемент в одном предложении
RD = ("Продольные стержни арматуры ∅12 А240, использованные для армирования форшахты, "
      "стыкуются внахлестку.")
# ИД, F0068 стр. 2: назначения нет, элемент назван папкой работ
ID_TEXT = "Арматура А240С d12 Сертификат качества №1720110087 от 04.09.2028."
ID_DOC = {"stage": "ID",
          "relative_path": "Новослободская/Исполнительная документация/"
                           "Ограждение котлована. Форшахта/АОСР №1АФ от 11.02.2026.pdf"}


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def got(text, doc=None, as_built=False):
    return {(c["location"], c["purpose"], c["raw"], c["binding"])
            for c in rebar.rebar_classes(text, doc, as_built=as_built)}


def test_purpose():
    """Назначение — по ближайшей метке слева, иначе конструктивная А240 станет рабочей.

    Так выглядела ошибка пилота: правило брало первое значение и объявляло подмену
    А500С на А240 там, где А240 — хомуты в обеих стадиях.
    """
    ok = True
    rows = got(PD)
    ok &= check("проект: рабочая А400 у форшахты", ("Форшахта", "working", "А400", "PAGE") in rows, str(rows))
    ok &= check("проект: А240 названа конструктивной",
                ("Форшахта", "constructive", "А240", "PAGE") in rows)
    ok &= check("в сравнение идёт только рабочая",
                {c["raw"] for c in rebar.working(rebar.rebar_classes(PD))} == {"А400"})
    ok &= check("«хомуты ∅8 А240» — конструктивная",
                rebar.purpose("каркасы и хомуты ∅8 ") == "constructive")
    ok &= check("«продольные стержни» — рабочая", rebar.purpose("Продольные стержни арматуры ∅12 ") == "working")
    return ok


def test_binding():
    """Привязка к элементу: предложение сильнее пути, путь сильнее упоминания раньше.

    У акта освидетельствования предмет работ назван папкой, а в тексте акта раньше
    поминается ограждение котлована — то есть стена в грунте, другой элемент.
    """
    ok = True
    ok &= check("рабочая стадия: элемент в том же предложении",
                ("Форшахта", "working", "А240", "CLAUSE") in got(RD))
    ok &= check("акт: элемент из пути файла",
                ("Форшахта", "unknown", "А240С", "PATH") in got(ID_TEXT, ID_DOC, as_built=True))
    ok &= check("без назначения в проектной стадии класс не берётся",
                got(ID_TEXT, ID_DOC) == set())
    return ok


def test_decision():
    """Решение по элементу: подмена рабочей А400 на А240 — понижение класса (ANN-0001)."""
    rule = {"kind": "element_rebar_class", "scope": "element",
            "compare": {"type": "min_decrease", "result": "CLASS_DOWNGRADE"}}
    named = {"PD": {"Форшахта"}, "RD": {"Форшахта"}, "ID": set()}
    pd = {"value": {400}, "raw": "А400", "binding": "PAGE"}
    rd = {"value": {240}, "raw": "А240", "binding": "CLAUSE"}
    label, result, detail = matrix_rules.decide_set(rule, pd, rd, named, "Форшахта")
    ok = check("А400 → А240 — нарушение", (label, result) == ("VIOLATION_PRESENT", "CLASS_DOWNGRADE"), detail)
    both = {"value": {400, 240}, "raw": "А240/А400", "binding": "CLAUSE"}
    label2, _, detail2 = matrix_rules.decide_set(rule, both, both, named, "Форшахта")
    ok &= check("смешанное множество нарушения не даёт: поэтому конструктивную и не берём",
                label2 == "NO_VIOLATION", detail2)
    weak = {"value": {240}, "raw": "А240", "binding": "PAGE"}
    label3, _, detail3 = matrix_rules.decide_set(rule, pd, weak, named, "Форшахта")
    ok &= check("понижение без указаний рабочей стадии — не вердикт",
                label3 == "COMPARISON_IMPOSSIBLE", detail3)
    return ok


def test_no_false_alarms():
    """Класс без элемента и без назначения не даёт кандидата.

    Сертификаты и ГОСТы поминают классы арматуры на каждой странице актов; без элемента
    такой класс сравнивать нельзя.
    """
    ok = True
    ok &= check("класс без элемента отброшен",
                got("Прокат арматурный периодического профиля классов А500, А500С по ГОСТ 34028-2016.") == set())
    ok &= check("«А500» в тексте без назначения в рабочей стадии не берётся",
                got("Сетка 3ВрI условно не показана. ∅12 А500 (поз. 1)") == set())
    return ok


if __name__ == "__main__":
    print("Класс рабочей арматуры по элементам (KR-057)")
    results = [test_purpose(), test_binding(), test_decision(), test_no_false_alarms()]
    print("\nИТОГ: " + ("все проверки пройдены" if all(results) else "есть сбои"))
    sys.exit(0 if all(results) else 1)
