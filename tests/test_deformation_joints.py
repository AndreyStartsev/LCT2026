"""Деформационные швы здания: черновик KR-063 (#192).

  python tests/test_deformation_joints.py

Решения специалиста: узла шва может не быть — хватает записки или примечания; если узел дан,
сравниваются материал заполнения и ширина; для «шва нет в РД» достаточно схем плиты и вертикальных
конструкций. Фразы — из томов КР открытых объектов.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import joints, matrix_rules  # noqa: E402

CATALOG = {"KR-063": {"parameter_id": 63, "criticality": "Критическое",
                      "parameter_name": "Наличие и конструктивное исполнение деформационных швов"}}


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def widths(text):
    return [s["value"] for s in joints.statements(text)]


def phrases():
    ok = check("фраза записки: «отделена … деформационным швом 50 мм»",
               widths("17-этажная секция отделена от остальной части здания деформационным швом 50 мм.") == [50])
    ok &= check("подпись на плане: ширина перед словом и «t=30мм» после",
                widths("ППЛ-2 9000 20мм Деформационный шов ППЛ-1") == [20]
                and widths("Отм. верха ПС Деформационный шов t=30мм Развертка") == [30])
    ok &= check("«шириной 100 мм»", widths("Блоки секций 1 и 2 разделены деформационным швом шириной 100 мм") == [100])
    ok &= check("условное обозначение «д.ш.» и «шов 100 100» без «мм» — шов без ширины",
                widths("Условные обозначения д.ш. - Деформационный шов t - Толщина стены") == [None]
                and widths("Деформационный шов 100 100 Вп-18") == [None])
    got = joints.statements('Заполнение деформационного шва производить экструзионным пенополистиролом "CARBON PROF"')
    ok &= check("материал заполнения из примечания", got and got[0]["materials"] == ["пенополистирол"], str(got))
    ok &= check("швы стяжки и пола, нормы и общие фразы — не шов здания",
                joints.statements("необходимо нарезать деформационные швы в продольном и поперечном направлении с шагом "
                                  "6 м") == []
                and joints.statements("определяющие необходимость или отсутствие временных и постоянных "
                                      "деформационных швов") == []
                and joints.statements("Температурный шов в тротуарных покрытиях устраивать") == [])
    ok &= check("схема плиты или вертикальных конструкций узнаётся по названию листа",
                joints.schemes("Схема армирования фундаментной плиты. Нижнее армирование") is not None
                and joints.schemes("План 1 этажа") is None)
    return ok


def cand(stage, value, file_id, page, materials=(), form="joint"):
    return {"stage": stage, "form": form, "key": "деформационный шов", "value": value, "materials": list(materials),
            "raw": "шов", "snippet": f"{file_id} с.{page}", "file_id": file_id, "page": page,
            "document": f"{file_id}.pdf", "location": "шов"}


def build(cands):
    rule = matrix_rules.load_provisional(2)["parameters"]["KR-063"]
    found = {st: [c for c in cands if c["stage"] == st] for st in ("PD", "RD")}
    return matrix_rules.joint_findings("OBJ", "KR-063", rule, found, CATALOG)


def findings():
    [f] = build([cand("PD", 50.0, "P", 26), cand("RD", 30.0, "R", 13)])
    ok = check("шов в РД уже проектного — нарушение (черновик: гипотеза)",
               f["violation_label"] == "VIOLATION_PRESENT" and f["comparison_result"] == "CONFIGURATION_MISMATCH"
               and f["extraction"]["detail"] == "ширина шва в РД 30 мм меньше проектной 50 мм", f["extraction"]["detail"])
    [f] = build([cand("PD", None, "P", 18, ["герметик"]), cand("RD", None, "R", 5, ["пенополистирол"])])
    ok &= check("другой материал заполнения — нарушение", f["violation_label"] == "VIOLATION_PRESENT"
                and "материал заполнения в РД — пенополистирол, в ПД — герметик" in f["extraction"]["detail"])
    [f] = build([cand("PD", 50.0, "P", 26), cand("RD", None, "R", 15)])
    ok &= check("шов в обеих стадиях, ширина в РД не подписана — «нарушения нет», так и сказано",
                f["violation_label"] == "NO_VIOLATION"
                and f["extraction"]["detail"] == "деформационный шов есть в обеих стадиях; ширина в ПД 50 мм, в РД не "
                                                 "подписана", f["extraction"]["detail"])
    [f] = build([cand("PD", 30.0, "P", 44), cand("RD", None, "R", 3, form="scheme")])
    ok &= check("шов в ПД, в РД есть схемы плиты, а шва на них нет — нарушение: элемент проекта не выполнен",
                f["violation_label"] == "VIOLATION_PRESENT" and f["comparison_result"] == "MISSING_DESIGN_ELEMENT"
                and "на схемах плиты и вертикальных конструкций РД (1 стр.) его нет" in f["extraction"]["detail"],
                f["extraction"]["detail"])
    [f] = build([cand("PD", 30.0, "P", 44)])
    ok &= check("схем РД нет — «сравнение невозможно»", f["violation_label"] == "COMPARISON_IMPOSSIBLE")
    ok &= check("шва нет ни в одной стадии — записи нет", build([]) == [])
    return ok


def pipeline_path():
    rule = matrix_rules.load_provisional(2)["parameters"]["KR-063"]
    text = "Схема расположения вертикальных конструкций. 30мм Деформационный шов"
    kr = {"stage": "RD", "section": "KR", "relative_path": "КЖ2.pdf"}
    ar = {"stage": "RD", "section": "AR", "relative_path": "АР3.pdf"}
    got = sorted(c["form"] for c in matrix_rules.extract(rule, text, doc=kr))
    ok = check("разбор страницы тома КР: шов и схема — свои кандидаты", got == ["joint", "scheme"], str(got))
    ok &= check("том АР не читается: швы кровли и пола — не параметр", matrix_rules.extract(rule, text, doc=ar) == [])
    return ok


def main():
    ok = phrases()
    ok &= findings()
    ok &= pipeline_path()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
