"""Шаг армирования и второй размер сечения балки — не толщина плиты (#254, Р-166).

  python tests/test_step_section_166.py

Тексты — со страниц корпуса, сокращены: РД школы Полярная 25 (L3027, стр. 19), РД Речникова (F0392, стр. 6;
F0368, стр. 3; F0354, стр. 14), ПД Тюменской-5 (F0158, стр. 20). До правки хвост разбора толщины брал «число + мм»
за шагом армирования и за «N×» сечения балки: у Речникова РД перекрытий надземной части выходил «200/300 мм», у
Тюменской ПД — «200/500 мм».
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import elements, tep  # noqa: E402

# РД школы Полярная 25, L3027 стр. 19: шаг сетки-каркаса по периметру плиты
SCHOOL_STEP = ("По периметру монолитной плиты перекрытия толщиной 240 мм предусмотреть установку СК 1 с шагом 200 мм, "
               "см. лист 12")
# РД Речникова, F0392 стр. 6: шаг основного армирования «200х200»
RECHNIKOV_GRID = ("Основное армирование плиты перекрытия толщиной 250мм принято из ∅12 класса А500С ГОСТ 34028-2016 "
                  "с шагом 200х200 мм по всей площади плиты")
# РД Речникова, F0368 стр. 3: сечение контурной балки «1100х300»
RECHNIKOV_BEAM = ("В комплект включены чертежи плиты перекрытия 1 этажа в виде монолитной железобетонной плиты "
                  "толщиной 200 мм и контурной балки в виде монолитной железобетонной балки с размерами 1100х300 мм")
# ПД Тюменской-5, F0158 стр. 20: сечение балок «250х500мм»
TYUMEN_BEAMS = ("Плиты перекрытия и покрытия толщиной 200мм по балкам сечения 250х500мм выполнены из бетона "
                "В25 W4 F100")
# РД Речникова, F0354 стр. 14: подпись листа «t=200», дальше условные обозначения с шагом деталей
RECHNIKOV_SHEET = ("Отметка верха и толщина плиты перекрытия t=250 - Рабочий шов бетонирования з.с. - Защитный "
                   "слой бетона в миллиметрах - 12-ГС1 с шагом 200 мм")
# перечень толщин должен остаться: это не шаг и не сечение
ENUMERATION = ("В комплект включены чертежи плит перекрытия -1 этажа, в виде монолитных железобетонных плит "
               "толщиной 350, 250, 200 мм.")
# шаг через слова: «с шагом не более 200 мм»
STEP_WORDS = "Плита перекрытия толщиной 220 мм, анкеры установить с шагом не более 200 мм по контуру"
# фундаментная плита: шаг свай и сечение ростверка тоже не толщина
PLATE_STEP = ("Фундаментная плита толщиной 800 мм, армирование — сетки из ∅16 А500С с шагом 400х400 мм, "
              "балки ростверка сечением 600х1200 мм")


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def slab(text):
    return sorted({v for values, *_ in elements.slab_thickness(tep.flatten(text)) for v in values})


def plate(text):
    return sorted({v for values, _ in elements.plate_thickness(tep.flatten(text)) for v in values})


def test_step():
    ok = check("«с шагом 200 мм» за толщиной 240 — только 240", slab(SCHOOL_STEP) == [240], str(slab(SCHOOL_STEP)))
    ok &= check("«с шагом 200х200 мм» за толщиной 250 — только 250", slab(RECHNIKOV_GRID) == [250],
                str(slab(RECHNIKOV_GRID)))
    ok &= check("«12-ГС1 с шагом 200 мм» за подписью t=250 — только 250", slab(RECHNIKOV_SHEET) == [250],
                str(slab(RECHNIKOV_SHEET)))
    ok &= check("«с шагом не более 200 мм» — только 220", slab(STEP_WORDS) == [220], str(slab(STEP_WORDS)))
    return ok


def test_second_size():
    ok = check("балка «1100х300 мм» за толщиной 200 — только 200", slab(RECHNIKOV_BEAM) == [200],
               str(slab(RECHNIKOV_BEAM)))
    ok &= check("балки «250х500мм» за толщиной 200 — только 200", slab(TYUMEN_BEAMS) == [200],
                str(slab(TYUMEN_BEAMS)))
    return ok


def test_enumeration_kept():
    return check("перечень «350, 250, 200 мм» остаётся целиком", slab(ENUMERATION) == [200, 250, 350],
                 str(slab(ENUMERATION)))


def test_plate():
    return check("фундаментная плита: шаг «400х400» и сечение «600х1200» — не толщина", plate(PLATE_STEP) == [800],
                 str(plate(PLATE_STEP)))


if __name__ == "__main__":
    ok = True
    for fn in (test_step, test_second_size, test_enumeration_kept, test_plate):
        print(fn.__name__)
        ok &= fn()
    print("OK" if ok else "ЕСТЬ СБОИ")
    sys.exit(0 if ok else 1)
