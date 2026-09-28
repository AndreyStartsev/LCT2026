"""Проверка сверки наименований помещений. Задача #46.

  python tests/test_room_names.py

Случай, с которого всё началось, — Тюменская-5: том ОВ проекта называет номером 140
кабинет «Физического эксперимента», а экспликация и рабочая стадия — «Моделирования
и конструирования»; физический эксперимент у них стоит под номером 143. Остальное —
синтетические объекты: перенумерованная рабочая стадия, обрезанные и склеенные подписи.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import room_names as rn  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


ROOMS = {"101": "Вестибюль с гардеробом", "102": "Кабинет директора", "103": "Серверная телекоммуникаций",
         "104": "Медицинский процедурный кабинет", "105": "Библиотека с читальным залом",
         "106": "Спортивный зал универсальный", "107": "Мастерская трудового обучения",
         "108": "Лаборантская химическая"}


def explications(mapping, stage, file_id, pages=(1, 2)):
    return [(stage, file_id, number, name) for number, name in mapping.items() for _ in pages]


def test_same_object():
    ok = True
    names = rn.Names(explications(ROOMS, "PD", "P-AR") + explications(ROOMS, "RD", "R-AR"))
    reason, named, differ = rn.refusal(names, sorted(ROOMS))
    ok &= check("стадии называют номера одинаково — отказа нет",
                reason is None and named == len(ROOMS) and differ == 0, f"{named}/{differ}")
    return ok


def test_renumbered_object():
    ok = True
    numbers = sorted(ROOMS)
    shifted = {numbers[(i + 1) % len(numbers)]: ROOMS[n] for i, n in enumerate(numbers)}
    names = rn.Names(explications(ROOMS, "PD", "P-AR") + explications(shifted, "RD", "R-AR"))
    reason, named, differ = rn.refusal(names, numbers)
    ok &= check("рабочая стадия перенумеровала все помещения — сравнение по номеру невозможно",
                reason is not None and differ == len(ROOMS), f"{reason}")
    ok &= check("в причине названо, сколько номеров расходится",
                reason and f"{len(ROOMS)} из {len(ROOMS)}" in reason, str(reason))
    # два помещения поменялись местами — это не перенумерация объекта
    swapped = dict(ROOMS, **{"101": ROOMS["102"], "102": ROOMS["101"]})
    names = rn.Names(explications(ROOMS, "PD", "P-AR") + explications(swapped, "RD", "R-AR"))
    reason, named, differ = rn.refusal(names, numbers)
    ok &= check("два помещения из восьми поменялись — отказа нет, расхождение посчитано",
                reason is None and differ == 2, f"{named}/{differ}")
    return ok


def test_noisy_names():
    ok = True
    ok &= check("обрезанное распознаванием наименование — то же помещение",
                rn.same(rn.name_words("моделирования"), rn.name_words("Моделирования и конструирования")) is True)
    ok &= check("разные кабинеты — разные помещения",
                rn.same(rn.name_words("Физического эксперимента"),
                        rn.name_words("Моделирования и конструирования")) is False)
    ok &= check("пустое наименование ответа не даёт",
                rn.same(set(), rn.name_words("Коридор рекреации")) is None)
    # подпись на листе склеена с соседями: «Астрономии» — это 141, «Лаборантская» — 144
    clean = (explications({"140": "Моделирования и конструирования", "141": "Астрономии кабинет",
                           "143": "Физического эксперимента", "144": "Лаборантская физики"}, "PD", "P-AR")
             + explications({"140": "Моделирования и конструирования", "141": "Астрономии кабинет",
                             "143": "Физического эксперимента", "144": "Лаборантская физики"}, "RD", "R-OV"))
    labels = [("PD", "P-OV", "140", "Астрономии Моделирования конструирования"),
              ("PD", "P-OV", "141", "Астрономии кабинет"),
              ("PD", "P-OV", "143", "Физического эксперимента Лаборантская"),
              ("PD", "P-OV", "144", "Лаборантская физики")]
    names = rn.Names(clean, labels)
    ok &= check("подпись склеена с соседней — помещение не считается другим",
                names.check("140", "P-OV")["status"] == "SAME" and names.check("143", "P-OV")["status"] == "SAME",
                str((names.check("140", "P-OV")["status"], names.check("143", "P-OV")["status"])))
    return ok


def test_volume_against_explication():
    ok = True
    clean = (explications({"140": "Моделирования и конструирования", "141": "Астрономии кабинет",
                           "142": "Физики кабинет", "143": "Физического эксперимента"}, "PD", "P-AR")
             + explications({"140": "Моделирования и конструирования", "141": "Астрономии кабинет",
                             "142": "Физики кабинет", "143": "Физического эксперимента"}, "RD", "R-OV"))
    # том ОВ проекта: 140 и 143 поменяны местами, подписи склеены с соседями, как на Тюменской-5
    labels = [("PD", "P-OV", "140", "Астрономии Физического эксперимента"),
              ("PD", "P-OV", "141", "Астрономии кабинет"),
              ("PD", "P-OV", "142", "Физики кабинет"),
              ("PD", "P-OV", "143", "Моделирования конструирования")]
    names = rn.Names(clean, labels)
    got = names.check("140", "P-OV")
    ok &= check("том раздела называет номером 140 другое помещение, чем экспликация",
                got["status"] == "DIFFERENT" and got["carried_by"] == "143", str(got["status"]))
    text = rn.note("140", got)
    ok &= check("в пояснении оба наименования и номер по экспликации",
                "Моделирования и конструирования" in text and "Физического эксперимента" in text
                and "143" in text, text)
    ok &= check("сосед, названный томом верно, соперником не считается",
                names.check("141", "P-OV")["status"] == "SAME")
    # «Тамбур» носят десять номеров: по такому наименованию помещение не опознать
    many = {str(200 + i): "Тамбур входной" for i in range(10)}
    names = rn.Names(explications(many, "PD", "P-AR") + explications(many, "RD", "R-AR"),
                     [("PD", "P-OV", "200", "Комната охраны")])
    ok &= check("неприметное наименование расхождением не объявляется",
                names.check("200", "P-OV")["status"] == "UNKNOWN", names.check("200", "P-OV")["status"])
    return ok


def test_no_findings_when_renumbered():
    """Перенумерованная рабочая стадия: находок «помещение не названо» нет, ответ — отказ с причиной."""
    from pipeline import room_compare
    ok = True
    numbers = sorted(ROOMS)
    shifted = {numbers[(i + 1) % len(numbers)]: ROOMS[n] for i, n in enumerate(numbers)}
    names = rn.Names(explications(ROOMS, "PD", "P-AR") + explications(shifted, "RD", "R-AR"))
    reason, _named, _differ = rn.refusal(names, numbers)
    compared = [(n, "VIOLATION_PRESENT", "MISSING_DESIGN_ELEMENT",
                 "в таблице систем рабочей стадии помещение не названо") for n in numbers]
    got = [room_compare.refuse_renumbered(label, result, detail, reason) for _n, label, result, detail in compared]
    ok &= check("ни одной находки «помещение не названо»",
                all(label == "COMPARISON_IMPOSSIBLE" and result is None for label, result, _d in got))
    ok &= check("в ответе причина и то, что вышло бы по номеру",
                all("разные наименования" in d and "помещение не названо" in d for _l, _r, d in got), got[0][2])
    same_label = room_compare.refuse_renumbered("NO_VIOLATION", "EQUAL_PD_RD", "состав систем совпадает", reason)
    ok &= check("записи без нарушения отказ не трогает", same_label[0] == "NO_VIOLATION")
    kept = room_compare.refuse_renumbered("VIOLATION_PRESENT", "MISSING_DESIGN_ELEMENT", "помещение не названо", None)
    ok &= check("без перенумерации находка остаётся находкой", kept[0] == "VIOLATION_PRESENT")
    return ok


def main():
    ok = True
    for title, fn in (("Одинаковая нумерация", test_same_object), ("Перенумерация", test_renumbered_object),
                      ("Находки при перенумерации", test_no_findings_when_renumbered),
                      ("Шумные наименования", test_noisy_names),
                      ("Том раздела против экспликации", test_volume_against_explication)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
