"""Внутренний противопожарный водопровод: число струй и расход струи. Третья очередь Матрицы, #27.

Расход ВПВ записывают расчётным случаем: «2 струи по 2,9 л/с», «1 струя по 3,7 л/сек»,
«2 струи, 2,9л/с», «2 струи с расходом не менее 5,2 л/с каждая». Случаев у здания бывает
несколько: у Речникова автостоянка 2 струи по 5,2 л/с, надземная часть 2 струи по 2,9 л/с,
у Октябрьской ещё и встроенные помещения 1 струя по 2,9 л/с. К какой части относится случай,
текст говорит не всегда, поэтому значение стадии — набор случаев, как толщина плиты во второй
очереди.

Цитаты нормы вида «следует принимать 4 струи по 0,6 / 1,0 л/с» не берутся.
"""
import re

JETS = re.compile(
    r"(?<![\d,.])(\d{1,2})\s*(?:пожарн\w+\s+)?стру[йияею]\w*\s*"
    r"(?:,\s*|по\s+|на\s+|с\s+расходом\s+(?:воды\s+)?(?:не\s+менее\s+)?(?:по\s+)?)?"
    r"(\d{1,2}(?:[,.]\d{1,2})?)\s*л\s?/\s?се?к?(?![а-яё])", re.I)
NORM_QUOTE = re.compile(r"следует\s+принимать", re.I)


def label(jets, flow):
    word = "струя" if jets % 10 == 1 and jets % 100 != 11 else \
        "струи" if 2 <= jets % 10 <= 4 and not 12 <= jets % 100 <= 14 else "струй"
    return f"{jets} {word} по {flow:g} л/с".replace(".", ",")


def show(cases):
    """«2 струи по 2,9 л/с; 2 струи по 5,2 л/с» или None, если случаев нет."""
    return "; ".join(label(*case) for case in sorted(cases)) or None


def jet_cases(flat):
    """Расчётные случаи ВПВ на странице: число струй и расход одной струи."""
    out = []
    for m in JETS.finditer(flat):
        if NORM_QUOTE.search(flat[max(0, m.start() - 80):m.start()]):
            continue
        jets, flow = int(m.group(1)), round(float(m.group(2).replace(",", ".")), 2)
        if not jets or not flow:
            continue
        out.append({"value": (jets, flow), "raw": label(jets, flow),
                    "snippet": " ".join(flat[max(0, m.start() - 90):m.end() + 40].split())})
    return out


def _below(case, cases):
    """Случай меньше хотя бы одного из cases по числу струй или по расходу струи.

    Это два независимых требования: 1 струя по 5,8 л/с не заменяет 2 струи по 2,9 л/с,
    хотя суммарный расход тот же.
    """
    jets, flow = case
    return any(jets < j or flow < f for j, f in cases)


def decide(pd, rd):
    """Решение по наборам случаев (струй, расход струи). Возвращает (метка, тип, пояснение).

    Нарушение — только когда у проекта один случай, а рабочая стадия называет меньше струй
    или меньший расход струи: при нескольких случаях меньший случай РД может относиться
    к другой части здания.
    """
    if not pd and not rd:
        return None, None, "расход ВПВ не найден ни в одной стадии"
    if not pd:
        return "COMPARISON_IMPOSSIBLE", None, "расход ВПВ в проектной стадии не найден"
    if not rd:
        return "COMPARISON_IMPOSSIBLE", None, "расход ВПВ в рабочей стадии не найден"
    if pd == rd:
        return "NO_VIOLATION", "EQUAL_PD_RD", f"случаи совпадают: {show(pd)}"
    lower = sorted(c for c in rd - pd if _below(c, pd))
    if lower and len(pd) == 1:
        return "VIOLATION_PRESENT", "VALUE_DECREASE", f"расход уменьшен: {show(pd)} → {show(lower)}"
    if lower:
        return ("COMPARISON_IMPOSSIBLE", None,
                f"в рабочей стадии {show(lower)}, в проектной несколько случаев ({show(pd)}); "
                f"к какой части здания относится меньший случай, по тексту не определить")
    missing = sorted(pd - rd)
    tail = f"; рабочая стадия не называет {show(missing)}" if missing else ""
    return ("NO_VIOLATION", "NON_TRIGGERING_DIFFERENCE_NO_DECREASE",
            f"проект {show(pd)}, рабочая {show(rd)}: расход не уменьшен{tail}")
