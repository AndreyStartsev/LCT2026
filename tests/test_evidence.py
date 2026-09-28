"""Проверка страницы-доказательства: картинка и место на ней. Задача #33.

  python tests/test_evidence.py

PDF собираются здесь же, корпус не нужен. Главная проверка — повёрнутая страница:
место должно попасть на тот участок картинки, где действительно напечатано значение.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pymupdf  # noqa: E402

from pipeline import evidence  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def make_page(rotation=0, text_at=((72, 144, "Площадь озеленения 3 694,60 м2"),)):
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    font = pymupdf.Font("cour")  # у встроенного Helvetica нет кириллицы
    writer = pymupdf.TextWriter(page.rect)
    for x, y, text in text_at:
        writer.append((x, y), text, font=font, fontsize=14)
    writer.write_text(page)
    page.set_rotation(rotation)
    return doc, page


def dark_share(page, box):
    """Доля тёмных пикселей картинки внутри прямоугольника видимой страницы."""
    pix = page.get_pixmap(matrix=pymupdf.Matrix(1, 1), alpha=False, colorspace=pymupdf.csGRAY)
    x0, y0, x1, y1 = box
    xs = range(int(x0 * pix.width), max(int(x1 * pix.width), int(x0 * pix.width) + 1))
    ys = range(int(y0 * pix.height), max(int(y1 * pix.height), int(y0 * pix.height) + 1))
    total = dark = 0
    for y in ys:
        for x in xs:
            total += 1
            dark += pix.pixel(x, y)[0] < 128
    return dark / max(total, 1)


def test_variants():
    ok = True
    v = evidence.value_variants("3694,60")
    ok &= check("пробел между тысячами и точка вместо запятой",
                "3 694,60" in v and "3694.60" in v and "3694,6" in v, str(v))
    ok &= check("без цифр вариантов нет", evidence.value_variants("II") == [])
    return ok


def test_locate():
    ok = True
    for rotation in (0, 90, 270):
        doc, page = make_page(rotation)
        rects, how = evidence.locate(page, "3694,60", ["Участок"])
        ok &= check(f"значение найдено на странице с поворотом {rotation}",
                    rects and how == "VALUE", str(rects))
        if rects:
            share = dark_share(page, rects[0])
            ok &= check(f"поворот {rotation}: прямоугольник лежит на напечатанном значении",
                        share > 0.05, f"тёмных пикселей {share:.0%}")
        doc.close()

    doc, page = make_page(0, ((72, 144, "Площадь 13694,60 м2"),))
    ok &= check("часть более длинного числа не считается значением",
                evidence.find_value(page, "3694,60") == [])
    doc.close()

    doc, page = make_page(0, ((72, 144, "Помещения 2012 и 012 венткамера"),))
    rects, how = evidence.locate(page, None, ["012"])
    ok &= check("номер помещения ищется целым словом", len(rects) == 1 and how == "LOCATION", str(rects))
    doc.close()

    doc, page = make_page(0)
    ok &= check("не найдено — прямоугольников нет, а не рамка по умолчанию",
                evidence.locate(page, "1225,8", ["Здание"]) == ([], None))
    doc.close()
    return ok


def test_render():
    ok = True
    doc, page = make_page(90)
    data, w, h = evidence.render_page(page, long_side_px=1000)
    ok &= check("картинка видимой страницы: повёрнутая страница стоит вертикально",
                data[:2] == b"\xff\xd8" and h == 1000 and w < h, f"{w}x{h}")
    doc.close()
    return ok


def test_element_values():
    ok = True
    # класс бетона в документе кириллицей, в разборе латиницей; толщина с обозначением t=
    doc, page = make_page(text_at=((72, 144, "Фундаментная плита выполнена из бетона класса В40, F150, W6"),
                                   (72, 200, "Отметка верха и толщина фундаментной плиты t=1200"),
                                   (72, 260, "Размер 11200 по осям")))
    got = evidence.find_element_values(page, "element_class", ["B40"])
    ok &= check("класс B40 из разбора находит «В40» кириллицей на листе",
                len(got) == 1 and dark_share(page, got[0]) > 0.05, str(got))
    got = evidence.find_element_values(page, "element_thickness", ["1200 мм"])
    ok &= check("толщина находит «t=1200», а не размер 11200",
                len(got) == 1 and got[0][1] < 200 / 595 + 0.02, str(got))
    ok &= check("значения нет на листе — прямоугольников нет",
                evidence.find_element_values(page, "element_class", ["B60"]) == [])
    doc.close()
    return ok


def main():
    ok = True
    for title, fn in (("Написания значения", test_variants), ("Место на странице", test_locate),
                      ("Значения элемента", test_element_values), ("Картинка", test_render)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
