"""Тесты модуля координатных систем pipeline/coords.py. Задача #35.

  python tests/test_coords.py

Проверяются:
1. Взаимная обратимость internal_to_tz и tz_to_internal (инверсия Y, сохранение X).
2. Зажатие clamp_bbox в [0, 1] и упорядочивание x0 <= x1, y0 <= y1.
3. Точность вычисления IoU (полное совпадение, непересекающиеся, касание, частичное).
4. Взаимная обратимость internal_to_organizer и organizer_to_internal на всех 4 углах (0, 90, 180, 270).
5. Поведение на синтетическом PDF-документе PyMuPDF со всеми 4 поворотами.
6. Слово в известном месте даёт ожидаемый прямоугольник при каждом угле: ожидание считается
   явными формулами поворота, поэтому модуль без учёта поворота этот тест не проходит.
"""
import math
import os
import sys
import pymupdf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import coords  # noqa: E402
from pipeline import reading  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def approx_eq(a, b, tol=1e-5):
    if len(a) != len(b):
        return False
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_internal_to_tz_inversion():
    ok = True
    b_in = [0.1, 0.2, 0.4, 0.5]  # x0, y0, x1, y1 (Y сверху)
    b_tz = coords.internal_to_tz(b_in)
    ok &= check("internal_to_tz переворачивает Y", b_tz == [0.1, 0.5, 0.4, 0.8])
    b_back = coords.tz_to_internal(b_tz)
    ok &= check("tz_to_internal восстанавливает исходный bbox", approx_eq(b_back, b_in))
    return ok


def test_clamp_bbox():
    ok = True
    ok &= check("нормальный bbox остаётся неизменным",
                 coords.clamp_bbox([0.1, 0.2, 0.3, 0.4]) == [0.1, 0.2, 0.3, 0.4])
    ok &= check("выход за пределы [0, 1] зажимается",
                 coords.clamp_bbox([-0.2, 0.1, 1.5, 0.8]) == [0.0, 0.1, 1.0, 0.8])
    ok &= check("перевёрнутые min/max упорядочиваются",
                 coords.clamp_bbox([0.5, 0.8, 0.2, 0.3]) == [0.2, 0.3, 0.5, 0.8])
    return ok


def test_iou():
    ok = True
    ok &= check("IoU одинаковых bbox == 1.0",
                 abs(coords.iou([0.1, 0.1, 0.5, 0.5], [0.1, 0.1, 0.5, 0.5]) - 1.0) < 1e-6)
    ok &= check("IoU непересекающихся bbox == 0.0",
                 coords.iou([0.0, 0.0, 0.2, 0.2], [0.5, 0.5, 0.8, 0.8]) == 0.0)
    ok &= check("IoU касающихся стороной == 0.0",
                 coords.iou([0.0, 0.0, 0.5, 0.5], [0.5, 0.0, 1.0, 0.5]) == 0.0)
    # [0, 0, 1, 1] и [0.5, 0, 1.5, 1] -> перекрытие 0.5, площадь объединения 1.5 -> iou = 1/3
    ok &= check("IoU частичного перекрытия",
                 abs(coords.iou([0.0, 0.0, 1.0, 1.0], [0.5, 0.0, 1.5, 1.0]) - (1.0 / 3.0)) < 1e-6)
    return ok


def test_organizer_roundtrip():
    ok = True
    for rot in (0, 90, 180, 270):
        doc = pymupdf.open()
        p = doc.new_page(width=1000, height=800)
        p.set_rotation(rot)
        b_in = [0.15, 0.25, 0.45, 0.65]
        org_b = coords.internal_to_organizer(b_in, p)
        back = coords.organizer_to_internal(org_b, p)
        ok &= check(f"roundtrip internal -> organizer -> internal при rot={rot}°",
                     approx_eq(back, b_in),
                     f"org={org_b}")
        doc.close()
    return ok


def test_rotation_positions():
    """Слово в известном месте даёт ожидаемый прямоугольник при каждом угле (условие 5 задачи #35).

    Ожидание считается явными формулами поворота листа, а не матрицей PyMuPDF и не самим
    модулем: лист 1000 × 800 пт, слово в исходных координатах (200, 300)–(260, 320).
    При 90° видимая страница 800 × 1000, точка (x, y) переходит в (H − y, x); при 180° —
    в (W − x, H − y); при 270° — в (y, W − x). Разметка организатора — исходные координаты
    с осью Y снизу от высоты MediaBox, делённые на размеры видимой страницы.
    """
    ok = True
    W, H = 1000.0, 800.0
    x0, y0, x1, y1 = 200.0, 300.0, 260.0, 320.0
    expected_visible = {
        0: (x0, y0, x1, y1, W, H),
        90: (H - y1, x0, H - y0, x1, H, W),
        180: (W - x1, H - y1, W - x0, H - y0, W, H),
        270: (y0, W - x1, y1, W - x0, H, W),
    }
    for rot, (vx0, vy0, vx1, vy1, wv, hv) in expected_visible.items():
        doc = pymupdf.open()
        page = doc.new_page(width=W, height=H)
        page.set_rotation(rot)
        internal = [vx0 / wv, vy0 / hv, vx1 / wv, vy1 / hv]
        organizer = [x0 / wv, (H - y1) / hv, x1 / wv, (H - y0) / hv]
        tz = [vx0 / wv, 1 - vy1 / hv, vx1 / wv, 1 - vy0 / hv]
        got = coords.organizer_to_internal(organizer, page)
        ok &= check(f"rot={rot}°: разметка организатора → внутренняя система, как по формуле поворота",
                    approx_eq(got, internal, 1e-4), "" if approx_eq(got, internal, 1e-4) else f"{got} ≠ {internal}")
        got = coords.internal_to_organizer(internal, page)
        ok &= check(f"rot={rot}°: внутренняя → разметка организатора", approx_eq(got, organizer, 1e-4), "" if approx_eq(got, organizer, 1e-4) else f"{got} ≠ {organizer}")
        got = coords.internal_to_tz(internal)
        ok &= check(f"rot={rot}°: внутренняя → система ТЗ (ось Y снизу видимой страницы)", approx_eq(got, tz, 1e-4), "" if approx_eq(got, tz, 1e-4) else f"{got} ≠ {tz}")
        # и слово, положенное на лист, читается слоем в ожидаемом месте видимой страницы
        page.insert_text((x0, y1), "WORD12", fontsize=20)
        bytes_ = doc.tobytes()
        doc.close()
        doc2 = pymupdf.open(stream=bytes_, filetype="pdf")
        words = reading.read_text_layer(doc2, 1)["words"]
        w = next((w for w in words if "WORD12" in w["t"]), None)
        # точка внутри первой буквы в исходных координатах — (x0 + 5, y1 − 5); после поворота
        # она обязана лежать внутри прямоугольника слова из слоя
        px, py = x0 + 5, y1 - 5
        point = {0: (px, py), 90: (H - py, px), 180: (W - px, H - py), 270: (py, W - px)}[rot]
        point = (point[0] / wv, point[1] / hv)
        inside = w is not None and w["bbox"][0] <= point[0] <= w["bbox"][2] and w["bbox"][1] <= point[1] <= w["bbox"][3]
        ok &= check(f"rot={rot}°: слово в слое лежит там, куда его переносит поворот", inside,
                    "" if inside else f"{w and w['bbox']} не содержит {point}")
        doc2.close()
    return ok


def test_synthetic_pdf():
    ok = True
    for rot in (0, 90, 180, 270):
        doc = pymupdf.open()
        page = doc.new_page(width=1000, height=800)
        page.insert_text((200, 300), "TEST123", fontsize=20)
        page.set_rotation(rot)
        pdf_bytes = doc.tobytes()
        doc.close()

        doc_read = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        p = doc_read[0]

        layer = reading.read_text_layer(doc_read, 1)
        words = layer["words"]

        w_found = next((w for w in words if "TEST" in w["t"]), None)
        ok &= check(f"синтетический PDF rot={rot}°: слово найдено в слое", w_found is not None)
        if not w_found:
            doc_read.close()
            continue

        bx0, by0, bx1, by1 = w_found["bbox"]
        ok &= check(f"синтетический PDF rot={rot}°: координаты в [0, 1]",
                     0.0 <= bx0 < bx1 <= 1.0 and 0.0 <= by0 < by1 <= 1.0,
                     f"bbox={w_found['bbox']}")

        org_bbox = coords.internal_to_organizer(w_found["bbox"], p)
        back_internal = coords.organizer_to_internal(org_bbox, p)
        overlap = coords.iou(w_found["bbox"], back_internal)
        ok &= check(f"синтетический PDF rot={rot}°: IoU восстановления > 0.9999",
                     overlap > 0.9999,
                     f"IoU={overlap:.6f}")
        doc_read.close()
    return ok


def main():
    print("--- Проверка координатных систем и разметки организатора ---")
    ok = True

    print("\nИнверсия по разделу 9.1 ТЗ:")
    ok &= test_internal_to_tz_inversion()

    print("\nЗажатие и нормализация границ (clamp_bbox):")
    ok &= test_clamp_bbox()

    print("\nВычисление метрики IoU:")
    ok &= test_iou()

    print("\nОбратимость преобразования организатора:")
    ok &= test_organizer_roundtrip()

    print("\nСлово в известном месте при каждом угле (формулы поворота, не матрица):")
    ok &= test_rotation_positions()

    print("\nСинтетические страницы PyMuPDF с углами 0°, 90°, 180°, 270°:")
    ok &= test_synthetic_pdf()

    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
