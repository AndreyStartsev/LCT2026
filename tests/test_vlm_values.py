"""Проход модели по чертежам: отбор листов, разбор ответа, проверка ответа. Задача #98.

  python tests/test_vlm_values.py

Данные взяты из замера 24.09. Модель читает то, что на листе подписано, и придумывает то,
чего на листе нет: на листе спецификаций Алтуфьевского она заполнила графу «место»
восемью названиями помещений, которых в таблице нет вовсе, а на плане второго этажа
ответила «900 мм» там, где подписано «Защитное ограждение 1200». Поэтому проход
принимает ответ только подтверждённым, а у параметров-размеров — подтверждённым рядом
со словом о предмете. Здесь проверяется именно эта защита.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import matrix_rules, vlm_values  # noqa: E402

# Алтуфьевское, L0010 стр. 20: подпись плана и размеры рядом с ней
PLAN_TEXT = ("План 2-го этажа М1 : 100 1 Защитное ограждение 1200 Направляющие прямоугольные "
             "25х25 Верхний поручень круглый D=50 Держатель стекла травмобезопасное закалённое "
             "стекло толщиной 10 мм по ГОСТ 30698-2014 Инв. № подл. Подпись и дата Взам. инв. № "
             "Согласовано Стадия Лист Листов Р 12 48 Дверной проём в свету 900 850")
# Алтуфьевское, L0057 стр. 15: план кровли с подписями уклонов
ROOF_TEXT = "План кровли на отм. +16.400 2.0% 2.0% i=2% воронка ВР-1 уклон 2%"

RULE = {"code": "AR-049", "unit": "мм",
        "vlm": {"stage": ["PD", "RD"], "sections": ["AR"], "kinds": ["DRAWING"],
                "min_mm": 290, "sheet_text": r"огражд\w*\s+кровл", "confirm_near": "огражд",
                "prompt": "вопрос"}}


def page(file_id, no, **kw):
    row = {"file_id": file_id, "pdf_page_number": no, "stage": "RD", "section": "AR",
           "kind": "DRAWING", "width_pt": 3370, "height_pt": 2384, "text": "ограждение кровли"}
    row.update(kw)
    return row


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def test_sheets_for():
    """Отбор листов: раздел, вид, размер, слово в тексте и потолок на каждую стадию."""
    ok = True
    pages = [page("L1", 1),
             page("L2", 2, section="OV"),                       # чужой раздел
             page("L3", 3, kind="TEXT"),                        # не чертёж
             page("L4", 4, width_pt=420, height_pt=595),        # А5: мелкий лист
             page("L5", 5, text="план фундамента"),             # нет слова правила
             page("L6", 6, text="ведомость рабочих чертежей ограждение кровли"),
             page("L7", 7, stage="PD"),
             page("L8", 8)]
    got = vlm_values.sheets_for(RULE, pages)
    ids = [f for f, _p, _why in got]
    ok &= check("взяты только подходящие листы", ids == ["L1", "L7", "L8"], str(ids))
    got = vlm_values.sheets_for(RULE, pages, limit=1)
    ids = [f for f, _p, _why in got]
    ok &= check("потолок считается на каждую стадию", ids == ["L1", "L7"], str(ids))
    # название листа в штампе в конце текста (у Речникова на 6300-м знаке); заменённая редакция;
    # смешанная папка «РД и ИД»
    tail = page("T1", 1, text="х " * 4000 + "ограждение кровли")
    got = [f for f, _p, _w in vlm_values.sheets_for(RULE, [tail, page("S1", 2), page("M1", 3, stage="RD_ID_MIXED")],
                                                     skip={"S1"})]
    ok &= check("название в хвосте текста найдено, заменённая редакция пропущена, «РД и ИД» — рабочая",
                got == ["T1", "M1"], str(got))
    return ok


def test_parse_numbers():
    """Разбор ответа: JSON, единица ответа и приведение к единице правила."""
    ok = True
    ok &= check("числа из JSON", vlm_values.parse_numbers('{"values": [1200, 900], "unit": "мм"}',
                                                          "мм") == [1200.0, 900.0])
    ok &= check("метры ответа приведены к миллиметрам правила",
                vlm_values.parse_numbers('{"values": [1.2], "unit": "м"}', "мм") == [1200.0])
    ok &= check("доля переведена правилом, а не разбором",
                vlm_values.parse_numbers('{"values": [2.1], "unit": "%"}', "%") == [2.1])
    ok &= check("пустой ответ — пустой список", vlm_values.parse_numbers('{"values": []}', "мм") == [])
    ok &= check("ответ без JSON тоже разбирается",
                vlm_values.parse_numbers("высота ограждения 1200 мм", "мм") == [1200.0])
    return ok


def test_confirmed():
    """Ответ принимается только подтверждённым текстом листа."""
    ok = True
    got, how = vlm_values.confirmed([1200.0], PLAN_TEXT, "огражд")
    ok &= check("1200 рядом со словом «ограждение» — подтверждено", got and how == "near", how)
    got, how = vlm_values.confirmed([900.0], PLAN_TEXT, "огражд")
    ok &= check("900 на листе есть, но не у ограждения — не подтверждено", not got, how)
    got, how = vlm_values.confirmed([900.0], PLAN_TEXT)
    ok &= check("без предмета проверка слабее: то же 900 проходит", got and how == "layer", how)
    got, how = vlm_values.confirmed([2.0], ROOF_TEXT, r"уклон|i\s*=|%")
    ok &= check("уклон 2 % подтверждён подписью плана кровли", got and how == "near", how)
    got, how = vlm_values.confirmed([1200.0], "План кровли парапет воронка ВР-1 1200", "огражд")
    ok &= check("листа без предмета ответ не подтверждает", not got and how == "нет предмета", how)
    got, how = vlm_values.confirmed([1200.0], "", "огражд")
    ok &= check("скан без текста: значение берётся как прочитанное машиной",
                got and how == "none", how)
    # доля: соседство со знаком процента слабо — номер пункта «2.1. Монтаж системы
    # канализации» на листе общих данных ВК его проходил (#98)
    clause = "2. КАНАЛИЗАЦИЯ. 2.1. Монтаж системы канализации, уклон по СП, 100 %"
    form = r"{v}\s*(?:%|‰)|i\s*=\s*{f}"
    got, how = vlm_values.confirmed([2.1], clause, r"уклон|%", form)
    ok &= check("номер пункта «2.1» уклоном не считается", not got and how == "не в своей форме", how)
    got, how = vlm_values.confirmed([2.0], ROOF_TEXT, r"уклон|%", form)
    ok &= check("подпись «2.0%» на плане кровли подтверждает значение",
                got and how == "форма", how)
    got, how = vlm_values.confirmed([2.0], "уклон кровли i=0,02 по плану", r"уклон|%", form)
    ok &= check("подпись долей «i=0,02» тоже подтверждает 2 %", got and how == "форма", how)
    # на плане кровли подписано «1.50%», а модель отвечает «1,5»
    got, how = vlm_values.confirmed([1.5], "Выход на кровлю 1.50% 1.50% Водосточная воронка",
                                    r"уклон|%", form)
    ok &= check("лишний нуль в подписи «1.50%» не мешает", got and how == "форма", how)
    got, how = vlm_values.confirmed([2.0], "уклон кровли 2,0% по плану", r"уклон|%", form)
    ok &= check("целое значение находится и как «2,0%»", got and how == "форма", how)
    return ok


def test_confirmed_values():
    """Набор ответа сверяется по значению; разряды через пробел — то же число (#135, черновики)."""
    got, _ = vlm_values.confirmed_values([1800, 520, 999], "Шахта лифта 1800 х 520 мм")
    ok = check("значение, которого на листе нет, из набора выброшено", got == [1800, 520], str(got))
    got, _ = vlm_values.confirmed_values([2100, 1730], "размеры шахты 2 100 и 1 730")
    ok &= check("«2 100» подтверждает 2100", got == [2100, 1730], str(got))
    got, how = vlm_values.confirmed_values([5], "")
    ok &= check("у страницы без текста значения берутся с пометкой", got == [5] and how == "none")
    # план кровли Новослободской (F0106 стр. 131): уклоны подписаны диапазонами, знак — у верхней границы
    slope_form = r"{v}\s*(?:%|‰)|i\s*=\s*{f}"
    roof = "2780 1230 2050 3490 23700 1.4-1.8% 0.9-1.2% 4.5-4.9% 4.5-4.9% 1.4-1.8%"
    got, _ = vlm_values.confirmed_values([0.9, 1.2, 1.4, 1.8, 4.5, 4.9], roof, r"уклон|i\s*=|%", slope_form)
    ok &= check("нижняя граница диапазона «0.9-1.2%» — тоже подписанный уклон", got == [0.9, 1.2, 1.4, 1.8, 4.5, 4.9],
                str(got))
    got, _ = vlm_values.confirmed_values([1.6, 3.0], roof, r"уклон|i\s*=|%", slope_form)
    ok &= check("число внутри диапазона и число без знака не подтверждаются", got == [], str(got))
    return ok


def test_in_range():
    """Длины коридоров и номера осей отсекаются пределами параметра (Новослободская, #95)."""
    want = {"value_range": [600, 4000]}
    got = vlm_values.in_range([1200, 1500, 5985, 27300, 17], want)
    ok = check("вне пределов ширины коридора — выброшено", got == [1200, 1500], str(got))
    ok &= check("без пределов ничего не отсекается", vlm_values.in_range([1, 27300], {}) == [1, 27300])
    ok &= check("один предел — только снизу", vlm_values.in_range([5, 50], {"value_range": [10, None]}) == [50])
    return ok


def test_cache_kind():
    """Кеш ответа зависит от вопроса: правка вопроса не берёт старый ответ."""
    ok = True
    one = vlm_values.cache_kind("AR-049", "вопрос")
    two = vlm_values.cache_kind("AR-049", "вопрос другой редакции")
    ok &= check("вид записи назван кодом параметра", one.startswith("vlm-AR-049-"), one)
    ok &= check("другой вопрос — другая запись", one != two, f"{one} / {two}")
    return ok


def test_set_decrease():
    """Сравнение набором: у кровли и ограждений значений несколько (#98)."""
    rule = {"unit": "%", "compare": {"type": "set_decrease", "tolerance": 0.1,
                                     "result_violation": "VALUE_DECREASE"}}

    def side(values):
        return {"value": values[0], "raw": f"{values[0]:g}", "all_values": sorted(values)}

    ok = True
    label, _r, detail = matrix_rules.decide(rule, side([1.7, 2.0, 2.1]), side([2.0]))
    ok &= check("уклон одного участка внутри проектного разброса — нарушения нет",
                label == "NO_VIOLATION", detail)
    label, _r, detail = matrix_rules.decide(rule, side([2.1]), side([2.0]))
    ok &= check("разница 0,1 % — разброс подписей, а не занижение",
                label == "NO_VIOLATION" and "разброс" in detail, detail)
    label, result, detail = matrix_rules.decide(rule, side([2.0]), side([1.5]))
    ok &= check("уклон ниже проектного на всех участках — нарушение",
                label == "VIOLATION_PRESENT" and result == "VALUE_DECREASE", detail)
    label, _r, detail = matrix_rules.decide(rule, side([2.0]), side([2.0, 0.9]))
    ok &= check("наборы пересекаются — сравнение невозможно, решает инспектор",
                label == "COMPARISON_IMPOSSIBLE", detail)
    label, result, detail = matrix_rules.decide(rule, side([1.5, 2.0]), side([2.0, 1.5]))
    ok &= check("наборы совпали — равенство", result == "EQUAL_PD_RD", detail)
    return ok


def test_cache_ages_with_pass():
    """Кеш кандидатов стареет вместе с проходом: иначе правила отвечают старым ответом.

    Значения с чертежей лежат вне документа, в `build/<объект>/vlm_values.jsonl`. Пока
    отпечатка этого файла не было в ключе кеша, прогон правил сразу после прохода модели
    показывал «значение в рабочей стадии не найдено» на объекте, где проход уже прочитал
    18 уклонов (Речников, 24.09).
    """
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as out:
        obj = os.path.join(out, "OBJ-X")
        os.makedirs(obj)
        doc = {"object_id": "OBJ-X", "file_id": "F0001"}
        path = os.path.join(obj, "vlm_values.jsonl")
        ok &= check("без файла прохода отпечатка нет",
                    matrix_rules.vlm_digest(doc, out=out) is None)
        row = {"object_id": "OBJ-X", "parameter_code": "AR-045", "file_id": "F0001",
               "pdf_page_number": 15, "values": [2.0]}
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        matrix_rules._VLM_DIGEST.clear()
        one = matrix_rules.vlm_digest(doc, out=out)
        ok &= check("с ответами отпечаток появился", bool(one), str(one))
        ok &= check("чужому документу отпечаток не достаётся",
                    matrix_rules.vlm_digest({"object_id": "OBJ-X", "file_id": "F0002"}, out=out) is None)
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({**row, "values": [1.5]}, ensure_ascii=False) + "\n")
        matrix_rules._VLM_DIGEST.clear()
        ok &= check("другое значение — другой отпечаток",
                    matrix_rules.vlm_digest(doc, out=out) != one, str(matrix_rules.vlm_digest(doc, out=out)))
    return ok


def test_side_keeps_all_values():
    """Сторона стадии несёт весь набор, а «расхождение со слоем» у набора не считается."""
    cands = [{"value": 2.1, "text_source": "RECOGNIZED"}, {"value": 1.7}, {"value": 2.0}]
    side = matrix_rules.with_all_values(
        {"value": 2.1, "raw": "2,1", "layer_conflict": "1,7",
         "doubtful": [{"value": "1,6", "mentions": 1, "against": "1,5", "against_mentions": 3}]}, cands)
    ok = check("в стороне все значения стадии", side["all_values"] == [1.7, 2.0, 2.1],
               str(side.get("all_values")))
    ok &= check("второй участок — не расхождение чтения", "layer_conflict" not in side, str(side))
    ok &= check("участок 1,6 % рядом с 1,5 % — не описка распознавания", "doubtful" not in side, str(side))
    ok &= check("стороны без чисел не меняются",
                matrix_rules.with_all_values({"value": "B25", "raw": "B25"}, [{"value": "B25"}])
                .get("all_values") is None)
    return ok


if __name__ == "__main__":
    print("Проход модели по чертежам (#98)")
    results = [test_sheets_for(), test_parse_numbers(), test_confirmed(), test_confirmed_values(), test_in_range(), test_cache_kind(),
               test_cache_ages_with_pass(), test_set_decrease(), test_side_keeps_all_values()]
    print("\nИТОГ: " + ("все проверки пройдены" if all(results) else "есть сбои"))
    sys.exit(0 if all(results) else 1)
