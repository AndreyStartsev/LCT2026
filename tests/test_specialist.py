"""Решения специалиста по видам гипотез: что идёт в сдачу, что показывается и что написано в пометке (Р-86, Р-108, Р-116).

  python tests/test_specialist.py

Проверяется на действующем `rules/specialist_guidance.json`: файл — и есть решение, и тест держит
его смысл — подтверждённые виды в сдаче, остальные гипотезами с пометкой специалиста, виды
«низкий приоритет» видны с пометкой и доводом против (решение пользователя 26.09), а «элемент
проекта не найден в РД» КР, АР и ЭОМ в сдачу не идёт (решение пользователя 28.09, Р-155). Решений по
отдельной записи нет (Р-116), а пометки короткие: слово решения и одна-две фразы по существу.
"""
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import specialist  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def rec(code, aspect=None, pd="", rd_files=(), detail="расхождение", label="VIOLATION_PRESENT", finding_id=None, rd=""):
    f = {"parameter_code": code, "for_submission": False, "finding_status": "SUSPICION", "pd_value": pd, "rd_value": rd,
         "violation_label": label, "evidence": [{"stage": "RD", "file_id": x} for x in rd_files],
         "extraction": {"detail": detail}}
    if aspect:
        f["aspect"] = aspect
    if finding_id:
        f["finding_id"] = finding_id
    return f


def round2():
    """Второй круг (24.09): подтверждённые виды — в сдачу, «нужны данные» — гипотезами."""
    sections = {"R_OV": "OV", "R_AR": "AR"}
    rows = [rec("FREE-AR-FLAT-AREA", "площадь с летними"), rec("FREE-AR-RD-NOT-UPDATED", "площадь"),
            rec("FREE-AR-RD-NOT-UPDATED", "категория"), rec("FREE-AR-ROOM-AREA", rd_files=["R_OV"]),
            rec("FREE-AR-ROOM-AREA", rd_files=["R_AR"]),
            rec("FREE-AR-ROOM-PURPOSE", pd="23 Помещение, 19,41 м²"), rec("FREE-GP-DESIGN-ELEMENT"),
            rec("FREE-AR-FLAT-AREA", "жилая площадь")]
    rows[-2]["for_submission"] = None
    got, stats = specialist.apply(rows, sections.get)
    flat, area, cat, room_ov, room_ar, purpose, other, living = got
    ok = check("подтверждённые виды — в сдачу: квартиры и площади «не обновлена»",
               flat["for_submission"] is True and area["for_submission"] is True and flat["finding_status"] == "CANDIDATE")
    ok &= check("подтверждённый вид взят в кандидаты, как гипотеза, взятая инспектором",
                flat.get("promoted_at") and flat.get("promoted_by") == specialist.PROMOTED_BY
                and "promoted_at" not in cat, str(flat.get("promoted_at")))
    ok &= check("категории «не обновлена», площадь и назначение помещения — гипотезами",
                not any(f["for_submission"] for f in (cat, room_ov, room_ar, purpose)), str(stats))
    ok &= check("пометка — в конце пояснения: слово решения, затем фразы специалиста",
                room_ov["extraction"]["detail"].startswith("расхождение. Специалист о таких записях: нужны данные. ")
                and "справочно" in room_ov["extraction"]["detail"], room_ov["extraction"]["detail"][-200:])
    ok &= check("дата разбора и решение по виду — в пометке значка",
                room_ov["specialist"]["reviewed"] == "24.09.2026" and room_ov["specialist"]["scope"] == "kind")
    ok &= check("площадь РД не из тома АР — названо, из какого", "из томов ОВ, а не АР" in room_ov["specialist"]["note"],
                room_ov["specialist"]["note"])
    ok &= check("площадь РД из тома АР — оговорки про смежные разделы нет", "а не АР" not in room_ar["specialist"]["note"])
    ok &= check("помещение без назначения в проекте — так и сказано, что проверить — в общей фразе",
                "В проекте назначения нет («Помещение»)." in purpose["specialist"]["note"]
                and "эвакуационный выход" in purpose["specialist"]["note"], purpose["specialist"]["note"])
    ok &= check("вид без решения специалиста не тронут", "specialist" not in other and other["for_submission"] is None)
    ok &= check("площади квартир: лоджии — нарушение, жилая площадь студий — гипотеза, решает эксперт",
                "лоджии" in flat["specialist"]["note"] and living["specialist"]["verdict"] == "hypothesis"
                and living["for_submission"] is False and living["specialist"]["note"].startswith("Решает эксперт.")
                and "R5-Q-A2-studio" in living["specialist"]["cases"] and "promoted_at" not in living,
                living["specialist"]["note"])
    return ok


def round4_kinds():
    """Четвёртый круг (26.09): «гипотеза» и «низкий приоритет» — решение специалиста «не показывать»."""
    rows = [rec("FREE-VK-DESIGN-ELEMENT"), rec("FREE-EOM-DESIGN-ELEMENT"), rec("FREE-KR-DESIGN-ELEMENT"),
            rec("FREE-AR-DESIGN-ELEMENT"), rec("FREE-ID-002"), rec("FREE-KR-003"),
            rec("FREE-KR-003", label="NO_VIOLATION"), rec("FREE-REV-UNMARKED"), rec("FREE-OV-DESIGN-ELEMENT")]
    for f in rows:
        f["for_submission"] = None
    got, stats = specialist.apply(rows)
    ok = check("записи не убираются: «низкий приоритет» по решению пользователя показывается", got is rows and len(got) == 9,
               str(stats))
    by = {(f["parameter_code"], f["violation_label"]): f for f in got}
    vk, rev, prof = (by[("FREE-VK-DESIGN-ELEMENT", "VIOLATION_PRESENT")], by[("FREE-REV-UNMARKED", "VIOLATION_PRESENT")],
                     by[("FREE-KR-003", "VIOLATION_PRESENT")])
    ok &= check("«гипотеза»: ВК, правка листа без отметки, профиль — гипотезы с пометкой",
                all(f["specialist"]["verdict"] == "hypothesis" and f["finding_status"] == "SUSPICION"
                    and "Специалист о таких записях: гипотеза." in f["extraction"]["detail"] for f in (vk, rev, prof)))
    ok &= check("решение по виду, кроме подтверждения, сдачу не трогает (тёплые полы Тюменской — эталон организатора)",
                all(f["for_submission"] is None for f in (vk, rev, prof)))
    drops = [by[(c, "VIOLATION_PRESENT")] for c in ("FREE-KR-DESIGN-ELEMENT", "FREE-AR-DESIGN-ELEMENT",
                                                    "FREE-EOM-DESIGN-ELEMENT")]
    ok &= check("элемент ПД не найден по КР, АР, ЭОМ: «низкий приоритет» пометкой и не в сдачу (Р-155)",
                all(f["specialist"]["verdict"] == "drop" and f["for_submission"] is False
                    and f["exclusion_reason"] == specialist.HELD and f["finding_status"] == "SUSPICION"
                    and "Специалист о таких записях: низкий приоритет." in f["extraction"]["detail"] for f in drops),
                drops[0]["extraction"]["detail"])
    ov = by[("FREE-OV-DESIGN-ELEMENT", "VIOLATION_PRESENT")]
    ok &= check("элемент ПД не найден по ОВ (тёплые полы Тюменской — эталон организатора) — в сдачу, как собрал разбор",
                ov["for_submission"] is None and "exclusion_reason" not in ov)
    ok &= check("довод против — «3 из 8» у КР, АР, ЭОМ, «8 из 12» у ВК; у ОВ своего довода нет",
                all("3 из 8" in f["extraction"]["confidence"]["low"][-1] for f in drops)
                and "8 из 12" in vk["extraction"]["confidence"]["low"][-1]
                and "confidence" not in by[("FREE-OV-DESIGN-ELEMENT", "VIOLATION_PRESENT")]["extraction"])
    ok &= check("решение специалиста в уровень не подмешано: довод — только о том, как найдено",
                all("приоритет" not in x for f in drops for x in f["extraction"]["confidence"]["low"]))
    ok &= check("«нарушения нет» того же вида не трогается",
                "specialist" not in by[("FREE-KR-003", "NO_VIOLATION")]
                and by[("FREE-KR-003", "NO_VIOLATION")]["for_submission"] is None)
    act = by[("FREE-ID-002", "VIOLATION_PRESENT")]
    ok &= check("номер акта в имени файла: «низкий приоритет», довода против нет",
                act["specialist"]["verdict"] == "drop" and "нарушением не считает" in act["specialist"]["note"]
                and act["for_submission"] is None and "confidence" not in act["extraction"], act["specialist"]["note"])
    ok &= check("дата четвёртого круга — у вида, а не общая", vk["specialist"]["reviewed"] == "26.09.2026")
    ok &= check("сводка считает вид «низкий приоритет» и снятые со сдачи",
                stats.get("вид «низкий приоритет»") == 4 and stats.get("снято со сдачи") == 3, str(stats))
    held = rec("FREE-EOM-DESIGN-ELEMENT")
    held["exclusion_reason"] = "прежняя причина"
    specialist.apply([held])
    ok &= check("запись уже не для сдачи — причина своя, в сводку снятых не идёт",
                held["for_submission"] is False and held["exclusion_reason"] == "прежняя причина")
    return ok


def no_records():
    """Решений по отдельной записи нет (Р-116): запись открытого корпуса не получает готового ответа."""
    data = json.load(open(specialist.PATH, encoding="utf-8"))
    ok = check("в действующем файле решений по записи нет", "records" not in data)
    door = rec("ODI-117", finding_id="LOC-POLYARNAYA-16::ODI-117", rd="1050 мм")
    specialist.apply([door])
    ok &= check("правило Матрицы на записи, которую разбирал специалист, остаётся как собрал разбор",
                "specialist" not in door and door["for_submission"] is False and door["finding_status"] == "SUSPICION")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "guidance.json")
        json.dump({"reviewed": "01.01.2026", "kinds": [{"code": "FREE-X", "verdict": "drop", "note": "Вид."}],
                   "records": [{"finding_id": "A::FREE-X", "when": {"rd_value": ["5"]}, "verdict": "violation",
                                "submit": True, "note": "Запись."}]}, open(path, "w", encoding="utf-8"))
        a = rec("FREE-X", finding_id="A::FREE-X", rd="5 шт.")
        specialist.apply([a], path=path)
    ok &= check("старый файл с решениями по записи: они не применяются, действует решение по виду",
                a["specialist"]["verdict"] == "drop" and a["specialist"]["scope"] == "kind" and a["for_submission"] is False)
    return ok


def style():
    """Пометки короткие и грамотные: одна-две фразы, с заглавной буквы и с точкой."""
    data = json.load(open(specialist.PATH, encoding="utf-8"))
    bad = []
    for k in data["kinds"]:
        for field in ("note", "not_ar", "unnamed"):
            text = k.get(field)
            if not text:
                continue
            probe = text.format(sections="ОВ", name="Помещение")
            if len(probe) > 130 or not re.match(r"[А-ЯЁA-Z0-9«]", probe) or not probe.endswith(".") or ".." in probe \
                    or re.search(r"специалист (решил|оставил)|по решению пользователя|разобранн", probe):
                bad.append(f"{k['code']}/{field}: {probe}")
        low = k.get("confidence_low")
        if low and (not low[0].islower() or low.endswith(".")):
            bad.append(f"{k['code']}/confidence_low: {low}")
    ok = check("каждая фраза пометки: до 130 знаков, с заглавной, с точкой, без канцелярита", not bad, "; ".join(bad))
    f = rec("FREE-AR-ROOM-AREA", rd_files=["R_OV"], detail="площадь 19,4 → 21,0 м².")
    specialist.apply([f], {"R_OV": "OV"}.get)
    detail = f["extraction"]["detail"]
    ok &= check("пояснение с пометкой читается одной строкой: без двойных точек и пустых фраз",
                ".." not in detail and ". ." not in detail and detail.count("Специалист о таких записях:") == 1, detail)
    empty = rec("FREE-OV-DESIGN-ELEMENT", detail="")
    specialist.apply([empty])
    ok &= check("пустое пояснение — пометка с начала строки", empty["extraction"]["detail"].startswith("Специалист о таких"),
                empty["extraction"]["detail"])
    return ok


def main():
    ok = round2()
    ok &= round4_kinds()
    ok &= no_records()
    ok &= style()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
