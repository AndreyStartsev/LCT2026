"""Цвет элементов фасада: AR-052, черновик шестого круга.

Триггер Матрицы — «изменение колористического решения фасада в РД без согласования». Цвет задан
кодом у элемента фасада: в ПД — списком «В отделке фасадов применяются материалы: • Цоколь -
керамогранитные плиты Тан Браун RAL 7024 …», в РД — таблицей «Элемент фасада | Вид отделки и
материал»: «7 Оконные переплеты - алюминиевый профиль по типу "Татпроф" RAL 7024». Ключ —
элемент фасада, значение — набор кодов. Код без элемента фасада рядом не берётся: в тех же
томах RAL стоит у клапанов ОВ, коробок ЭОМ и ограждений лестниц.

Сравниваются только одинаково обозначенные коды (указание специалиста третьего круга): RAL с RAL,
NCS с NCS. Согласование по документам пакета почти не видно, поэтому расхождение — гипотеза;
ссылка на АГР на той же странице РД снижает уверенность.
"""
import re

RAL = re.compile(r"\bRAL\s?(\d{4})\b")
NCS = re.compile(r"\bN[CS]{2}\s+S\s*(\d{4}-[A-Z]\d{0,2}[A-Z]?)\b")
ELEMENTS = (
    ("цоколь", r"цокол\w*"),
    ("оконные переплёты", r"оконн\w+\s+(?:перепл[её]т|заполнени|блок|профил)\w*|перепл[её]т\w*|окон(?![а-яё])"),
    ("витражи", r"витраж\w*"),
    ("двери", r"(?<![а-яё])двер\w*|ворот(?:а|а,)?(?![а-яё])"),
    ("козырьки", r"козыр\w+"),
    ("ограждения", r"ограждени\w*"),
    ("откосы и отливы", r"откос\w*|отлив\w*|нащельник\w*"),
    ("наружные стены", r"наружн\w+\s+стен\w*|сэндвич\w*|алюк[оа]бонд\w*|фасадн\w+\s+(?:панел|кассет|плит|штукатур)\w*"
                       r"|облицовк\w*|штукатурк\w*|керамогранит\w*|клинкер\w*|плитк\w*"),
)
# элемент не фасада: интерьер, кровля, инженерные изделия
FOREIGN = re.compile(r"внутренн\w*|коридор\w*|помещени\w*|кровл\w*|клапан\w*|воздуховод\w*|решетк\w*|решётк\w*|кабел\w*|"
                     r"коробк\w*|щит\w*|светильник\w*|опор[аы]\w*|МАФ|скамь\w*|урн\w*|лестниц\w*|приямк\w*|"
                     r"покрыти\w+\s+площадк|резинов\w+\s+крошк", re.I)
APPROVAL = re.compile(r"(?<![А-ЯЁ])АГР(?![А-ЯЁ])|архитектурно-градостроительн\w+\s+решени|Москомархитектур", re.I)
# пункт списка или строка таблицы: «1 Наружные стены - …», «• Цоколь - …»; тире внутри пункта его не делит:
# «9 Козырьки - Стеклянные на металлическом каркасе RAL 9006»
_ITEM = re.compile(r"\s(?=\d{1,2}\s+[А-ЯЁ][а-яё])|•|;|\.\s")


def colors(flat):
    """Коды цвета у элементов фасада на странице: [{key, value, raw, snippet, approval}]."""
    if not re.search(r"фасад", flat, re.I):
        return []
    approval = bool(APPROVAL.search(flat))
    out = []
    for item in _ITEM.split(flat):
        codes = [f"RAL {m.group(1)}" for m in RAL.finditer(item)] + [f"NCS S {m.group(1)}" for m in NCS.finditer(item)]
        if not codes or FOREIGN.search(item):
            continue
        first = min(m.start() for m in list(RAL.finditer(item)) + list(NCS.finditer(item)))
        head = item[:first]
        element = next((name for name, pat in ELEMENTS if re.search(pat, head, re.I)), None)
        if not element:
            continue
        for code in dict.fromkeys(codes):
            out.append({"key": element, "value": code, "raw": code, "approval": approval,
                        "snippet": " ".join(item[:220].split())})
    return out


def system(code):
    return code.split()[0]


def changes(pd, rd):
    """Изменённые цвета элементов: [(элемент, проект, рабочая, почему)]. pd, rd — {элемент: {код}}."""
    out = []
    for key in sorted(set(pd) & set(rd)):
        for sys in ("RAL", "NCS"):
            p = {c for c in pd[key] if system(c) == sys}
            r = {c for c in rd[key] if system(c) == sys}
            if not p or not r or r <= p:
                continue
            why = "другой код" if not (p & r) else "добавлен код"
            out.append((key, p, r, why))
    return out


def show(key, values):
    return ", ".join(sorted(values))
