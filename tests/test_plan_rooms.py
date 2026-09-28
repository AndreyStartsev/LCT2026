"""Тесты модуля привязки элементов к помещениям pipeline/plan_rooms.py. Задача #22.

  python tests/test_plan_rooms.py

Проверяются:
1. Извлечение помещений по чистому текстовому слою.
2. Поддержка распознавания (OCR): латинские омоглифы («B» -> «В», «T» -> «Т», «P» -> «Р»).
3. Очистка скобочного шума вокруг номеров («[140]», «(142)», ««147»»).
4. Защита от ошибочного захвата позиций оборудования («поз. 169» не становится помещением и не перехватывает марки).
5. Фильтрация низкодостоверного шума OCR (conf < 20).
6. Слияние дублирующихся записей одного помещения (наименование из экспликации, марки с плана).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import plan_rooms  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def w(t, x0, y0, x1, y1, conf=100.0, source="TEXT_LAYER"):
    return {"t": t, "bbox": [x0, y0, x1, y1], "conf": conf, "source": source}


def test_text_layer():
    print("\n1. Текстовый слой")
    words = [
        w("140", 0.220, 0.655, 0.225, 0.663),
        w("Физического", 0.227, 0.655, 0.244, 0.663),
        w("эксперимента", 0.220, 0.665, 0.240, 0.673),
        w("поз.169", 0.216, 0.645, 0.227, 0.654),
        w("В2.7", 0.216, 0.606, 0.222, 0.614),
        w("В2.8", 0.216, 0.616, 0.222, 0.624),
        w("В2.9", 0.216, 0.624, 0.222, 0.633),
    ]
    res = plan_rooms.extract(words)
    ok = True
    ok &= check("найдено ровно одно помещение 140", len(res) == 1 and res[0]["number"] == "140")
    ok &= check("наименование собрано по строкам", res[0]["name"] == "Физического эксперимента")
    ok &= check("все три марки В2.7-В2.9 привязаны", res[0]["marks"] == ["В2.7", "В2.8", "В2.9"])
    ok &= check("позиция поз.169 привязана", res[0]["positions"] == ["поз.169"])
    return ok


def test_ocr_latin_twins():
    print("\n2. Латинские близнецы в марках OCR (B -> В, T -> Т, P -> Р)")
    words = [
        w("142", 0.168, 0.655, 0.173, 0.663, source="TESSERACT"),
        w("Астрономии", 0.175, 0.655, 0.191, 0.663, source="TESSERACT"),
        w("физики", 0.171, 0.666, 0.180, 0.673, source="TESSERACT"),
        w("B2.4", 0.166, 0.610, 0.172, 0.616, source="TESSERACT"),  # Latin B
        w("B2.5", 0.166, 0.618, 0.172, 0.624, source="TESSERACT"),  # Latin B
        w("B2.6", 0.166, 0.626, 0.172, 0.632, source="TESSERACT"),  # Latin B
        w("T1.1", 0.166, 0.635, 0.172, 0.641, source="TESSERACT"),  # Latin T
    ]
    res = plan_rooms.extract(words)
    ok = True
    ok &= check("помещение 142 распознано", len(res) == 1 and res[0]["number"] == "142")
    ok &= check("марки с латинскими буквами нормализованы в кириллицу",
                res[0]["marks"] == ["В2.4", "В2.5", "В2.6", "Т1.1"])
    return ok


def test_ocr_bracket_noise():
    print("\n3. Очистка скобочного и пунктуационного шума OCR")
    words = [
        w("[140]", 0.200, 0.300, 0.205, 0.308, source="TESSERACT"),
        w("(142)", 0.300, 0.300, 0.305, 0.308, source="TESSERACT"),
        w("«147»", 0.400, 0.300, 0.405, 0.308, source="TESSERACT"),
        w("Лаборатория", 0.206, 0.300, 0.225, 0.308, source="TESSERACT"),
        w("Венткамера", 0.306, 0.300, 0.325, 0.308, source="TESSERACT"),
        w("Учебный", 0.406, 0.300, 0.425, 0.308, source="TESSERACT"),
    ]
    res = plan_rooms.extract(words)
    ok = True
    nums = [r["number"] for r in res]
    ok &= check("номера [140], (142), «147» очищены от скобок", nums == ["140", "142", "147"])
    return ok


def test_pos_equipment_protection():
    print("\n4. Защита от ошибочного захвата позиций оборудования (поз. 169)")
    words = [
        w("B2.7", 0.216, 0.606, 0.222, 0.612, source="TESSERACT"),
        w("B2.8", 0.216, 0.616, 0.222, 0.622, source="TESSERACT"),
        w("B2.9", 0.216, 0.625, 0.222, 0.631, source="TESSERACT"),
        w("оз", 0.216, 0.648, 0.221, 0.652, conf=50.0, source="TESSERACT"),
        w("169", 0.222, 0.641, 0.227, 0.652, conf=28.0, source="TESSERACT"),
        w("140", 0.220, 0.655, 0.225, 0.661, conf=95.0, source="TESSERACT"),
        w("Физического", 0.227, 0.655, 0.244, 0.661, conf=90.0, source="TESSERACT"),
        w("эксперимента", 0.220, 0.667, 0.239, 0.673, conf=90.0, source="TESSERACT"),
    ]
    res = plan_rooms.extract(words)
    ok = True
    ok &= check("число 169 не стало отдельным помещением", not any(r["number"] == "169" for r in res))
    ok &= check("помещение 140 получило все свои марки В2.7-В2.9",
                len(res) == 1 and res[0]["number"] == "140" and res[0]["marks"] == ["В2.7", "В2.8", "В2.9"])
    ok &= check("позиция поз.169 успешно привязана к помещению 140",
                res[0]["positions"] == ["поз.169"])
    return ok


def test_noise_filtering():
    print("\n5. Фильтрация низкодостоверного шума OCR (conf < 20)")
    words = [
        w("140", 0.220, 0.655, 0.225, 0.661, conf=95.0, source="TESSERACT"),
        w("Физического", 0.227, 0.655, 0.244, 0.661, conf=90.0, source="TESSERACT"),
        w("99", 0.500, 0.500, 0.505, 0.508, conf=12.0, source="TESSERACT"),
        w("ШумМусор", 0.506, 0.500, 0.525, 0.508, conf=15.0, source="TESSERACT"),
    ]
    res = plan_rooms.extract(words)
    ok = True
    ok &= check("мусор с conf < 20 отброшен", len(res) == 1 and res[0]["number"] == "140")
    return ok


def test_dedup_and_merge():
    print("\n6. Слияние записей экспликации и плана одного помещения")
    words = [
        w("012", 0.800, 0.100, 0.805, 0.108),
        w("Венткамера", 0.806, 0.100, 0.820, 0.108),
        w("приточных", 0.822, 0.100, 0.838, 0.108),
        w("систем", 0.806, 0.110, 0.818, 0.118),
        w("012", 0.400, 0.500, 0.405, 0.508),
        w("Венткамера", 0.406, 0.500, 0.425, 0.508),
        w("П1", 0.400, 0.480, 0.405, 0.488),
    ]
    res = plan_rooms.extract(words)
    ok = True
    ok &= check("записи объединены в одну", len(res) == 1 and res[0]["number"] == "012")
    ok &= check("взято длинное наименование из экспликации",
                res[0]["name"] == "Венткамера приточных систем")
    ok &= check("марка П1 сохранена", res[0]["marks"] == ["П1"])
    ok &= check("координаты взяты от записи с марками на плане", res[0]["bbox"] == [0.400, 0.500, 0.405, 0.508])
    return ok


def main():
    print("=" * 80)
    print("ТЕСТЫ ПРИВЯЗКИ ПОМЕЩЕНИЙ И СЛОВ OCR (Задача #22)")
    print("=" * 80)
    ok = True
    ok &= test_text_layer()
    ok &= test_ocr_latin_twins()
    ok &= test_ocr_bracket_noise()
    ok &= test_pos_equipment_protection()
    ok &= test_noise_filtering()
    ok &= test_dedup_and_merge()
    print("\n" + "=" * 80)
    if ok:
        print("ИТОГ: все проверки пройдены")
        return 0
    else:
        print("ИТОГ: ЕСТЬ ОШИБКИ")
        return 1


if __name__ == "__main__":
    sys.exit(main())
