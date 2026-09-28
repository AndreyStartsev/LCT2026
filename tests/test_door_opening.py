"""Направление открывания дверей на путях эвакуации: черновик AR-043 (#191).

  python tests/test_door_opening.py

Направление текстом почти не пишут, поэтому двери читает прицельный проход модели по планам ПД и РД:
«дверь → по ходу / против хода эвакуации», обозначена ли она как эвакуационный выход. Дверь
принимается, только если её марка или помещение есть в тексте листа. Требование проекта берётся и
текстом записки. Решения специалиста: для гипотезы — все двери, для нарушения — только явно
эвакуационные. Модель подставная, объект — два листа (план ПД и план РД).
"""
import json
import os
import re
import sys
import tempfile
from argparse import Namespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="test-doors-")
os.environ["PIPELINE_CACHE"] = os.path.join(TMP, "cache")
os.environ["PIPELINE_OUT"] = os.path.join(TMP, "build")
os.environ["PIPELINE_VLM_MAX_PX"] = "400"

import pymupdf  # noqa: E402

from pipeline import cli, config, matrix_rules, reading, vlm_values  # noqa: E402

OBJ = "TST-DOORS"
CATALOG = {"AR-043": {"parameter_id": 43, "criticality": "Критическое",
                      "parameter_name": "Направление открывания эвакуационных дверей"}}
RULE = matrix_rules.load_provisional(2)["parameters"]["AR-043"]
PD_TEXT = "План 1 этажа. Тамбур 1.05, Д-1, лестничная клетка Л1, Д-2"
RD_TEXT = "План 1 этажа на отм. 0.000. Тамбур 1.05 Д1, Д2, ДН-3 Эвакуационный выход"
ANSWERS = {
    1: {"doors": [{"mark": "Д-1", "room": "Тамбур 1.05", "opens": "по ходу", "exit": True},
                  {"mark": "Д-2", "room": "", "opens": "по ходу"}]},
    2: {"doors": [{"mark": "Д1", "room": "Тамбур 1.05", "opens": "против хода эвакуации", "exit": True},
                  {"mark": "Д-2", "room": "", "opens": "против"},
                  {"mark": "Д-9", "room": "Кладовая", "opens": "против хода"},
                  {"mark": "ДН-3", "room": "", "opens": "по ходу"}]},
}


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def parsing():
    got = vlm_values.parse_doors("Ответ: " + json.dumps({"doors": [
        {"mark": "Д-1", "room": "", "opens": "По ходу эвакуации", "exit": True},
        {"mark": "", "room": "Коридор 1.07", "opens": "против хода"},
        {"mark": "", "room": "", "opens": "по ходу"},
        {"mark": "Д-4", "opens": "непонятно"}]}, ensure_ascii=False))
    ok = check("ответ: направление приводится к «по ходу / против хода / не видно», дверь без марки и помещения "
               "отбрасывается",
               [(d["mark"] or d["room"], d["opens"], d["exit"]) for d in got]
               == [("Д-1", "по ходу", True), ("Коридор 1.07", "против хода", False), ("Д-4", "не видно", False)],
               str(got))
    ok &= check("ответ без JSON — дверей нет", vlm_values.parse_doors("не вижу дверей") == [])
    rated = vlm_values.parse_doors(json.dumps({"doors": [
        {"mark": "EI30", "room": "", "opens": "по ходу"}, {"mark": "EI 60", "room": "Тамбур 1.05", "opens": "по ходу"},
        {"mark": "ЕІ45", "room": "", "opens": "по ходу"}, {"mark": "REI120", "room": "", "opens": "по ходу"},
        {"mark": "E30", "room": "", "opens": "по ходу"}, {"mark": "ДПМ EI30", "room": "", "opens": "по ходу"},
        {"mark": "Д-1", "room": "", "opens": "по ходу"}, {"mark": "ДВМ-2п", "room": "", "opens": "по ходу"}]},
        ensure_ascii=False))
    ok &= check("подпись огнестойкости вместо марки (Полярная 16: «EI30») маркой не считается; у двери с помещением "
                "остаётся помещение; «ДПМ EI30», «Д-1» и «ДВМ-2п» не трогаются",
                [(d["mark"], d["room"]) for d in rated]
                == [("", "Тамбур 1.05"), ("ДПМ EI30", ""), ("Д-1", ""), ("ДВМ-2п", "")], str(rated))
    doors = [{"mark": "Д-1", "room": ""}, {"mark": "Д10", "room": ""}, {"mark": "", "room": "Тамбур 1.05"},
             {"mark": "", "room": "Лестничная клетка Л7"}, {"mark": "", "room": "Тамбур"}]
    kept, how = vlm_values.confirmed_doors(doors, "План. Д1 и ДД1, Тамбур 1,05, лестничная клетка Л1")
    ok &= check("подтверждение текстом листа: «Д-1» = «Д1», но не «Д10»; номер помещения с разделителем; "
                "одна цифра не подтверждает",
                [d["mark"] or d["room"] for d in kept] == ["Д-1", "Тамбур 1.05", "Тамбур"] and how == "layer",
                str(kept))
    ok &= check("лист без текста: двери берутся с пометкой «none»",
                vlm_values.confirmed_doors(doors[:1], "")[1] == "none")
    return ok


def make_object():
    root = os.path.join(TMP, "files")
    os.makedirs(root, exist_ok=True)
    for name in ("PD.pdf", "RD.pdf"):
        pdf = pymupdf.open()
        pdf.new_page(width=1191, height=842)
        pdf.save(os.path.join(root, name))
        pdf.close()
    config.register_object(OBJ, root, "Тестовый объект")
    out = os.path.join(config.OUT, OBJ)
    os.makedirs(out, exist_ok=True)
    cli.write_jsonl(os.path.join(out, "documents.jsonl"), [
        {"file_id": "P1", "object_id": OBJ, "sha256": "aa" * 32, "relative_path": "PD.pdf", "stage": "PD",
         "section": "AR"},
        {"file_id": "R1", "object_id": OBJ, "sha256": "bb" * 32, "relative_path": "RD.pdf", "stage": "RD",
         "section": "AR"}])
    cli.write_jsonl(os.path.join(out, "pages.jsonl"), [
        {"file_id": fid, "pdf_page_number": 1, "stage": st, "section": "AR", "kind": "DRAWING",
         "width_pt": 1191, "height_pt": 842, "text": text}
        for fid, st, text in (("P1", "PD", PD_TEXT), ("R1", "RD", RD_TEXT))])


def fake_model(png, model=None, prompt=None, **kw):
    sha = re.search(r"vlm-([0-9a-f]{12})-", os.path.basename(png)).group(1)
    return {"text": json.dumps(ANSWERS[1 if sha.startswith("aa") else 2], ensure_ascii=False), "model": "fake",
            "cost_usd": 0.001, "ms": 5}


def the_pass():
    make_object()
    saved = matrix_rules.load_rules, matrix_rules.load_provisional, reading.read_model
    matrix_rules.load_rules = lambda path: {"parameters": {}}
    matrix_rules.load_provisional = lambda q: {"parameters": {"AR-043": dict(RULE)}} if q == 2 else None
    reading.read_model = fake_model
    try:
        stats = cli.cmd_vlm(Namespace(object=OBJ, code=None, limit=40, sheets=6, model=None, dry=False, fresh=False,
                                      provisional=True, workers=1, progress=None)) or {}
    finally:
        matrix_rules.load_rules, matrix_rules.load_provisional, reading.read_model = saved
    rows = vlm_values.load(OBJ, provisional=True)
    ok = check("проход спрашивает правило с ответом-перечнем дверей: оба листа", stats.get("вызовов") == 2, dict(stats))
    rd = next(r for r in rows if r["file_id"] == "R1")
    ok &= check("дверь, которой нет в тексте листа («Д-9», «Кладовая»), отброшена",
                [d["mark"] for d in rd["doors"]] == ["Д1", "Д-2", "ДН-3"]
                and stats.get("дверей отброшено: нет на листе") == 1, str(rd["doors"]))
    ok &= check("строка ответа — в файле черновиков, без чисел", rd["values"] == [] and rd["confirmed_by"] == "layer")
    ok &= check("двери входят в отпечаток ответов документа: кеш кандидатов стареет с ними",
                matrix_rules.vlm_digest({"object_id": OBJ, "file_id": "R1"}, provisional=True) is not None)
    return ok


def findings():
    rule = dict(RULE, code="AR-043", provisional=True)
    requirement = ("Двери эвакуационных выходов и другие двери на путях эвакуации открываются по направлению "
                   "выхода из здания.")
    cands = {"PD": [], "RD": []}
    for fid, st, text in (("P1", "PD", PD_TEXT + " " + requirement), ("R1", "RD", RD_TEXT + " " + requirement)):
        doc = {"object_id": OBJ, "file_id": fid, "stage": st, "section": "AR"}
        for c in matrix_rules.extract(rule, text, doc=doc, page_no=1):
            cands[st].append(dict(c, stage=st, file_id=fid, page=1, document=f"{fid}.pdf"))
    ok = check("требование проекта — только из текста ПД; двери — из ответов прохода",
               sum(c["form"] == "requirement" for c in cands["PD"]) == 1
               and not any(c["form"] == "requirement" for c in cands["RD"])
               and {c["key"] for c in cands["RD"] if c["form"] == "door"} == {"Д1", "Д2", "ДН3"})
    [f] = matrix_rules.door_findings(OBJ, "AR-043", rule, cands, CATALOG)
    ok &= check("дверь РД против хода при «по ходу» в ПД — гипотеза, в сдачу только решением инспектора",
                f["violation_label"] == "VIOLATION_PRESENT" and f["finding_status"] == "SUSPICION"
                and f["for_submission"] is False
                and f["extraction"]["detail"] == "дверь Д1: в РД против хода эвакуации, в ПД по ходу; дверь Д-2: в РД "
                                                 "против хода эвакуации, в ПД по ходу", f["extraction"]["detail"])
    conf = f["extraction"]["confidence"]
    ok &= check("уверенность: направление прочитано моделью — «низкая»; дверь-выход — довод «за»",
                conf["low"] and conf["up"] == ["дверь обозначена на плане как эвакуационный выход"], str(conf))
    ok &= check("локации — двери", f["locations"] == ["Д1", "Д-2"], str(f["locations"]))
    ok &= check("значение прочитано машиной — видно в записи", f["extraction"]["rd"].get("text_source") == "RECOGNIZED")
    only_need = {"PD": [c for c in cands["PD"] if c["form"] == "requirement"], "RD": cands["RD"]}
    [f] = matrix_rules.door_findings(OBJ, "AR-043", rule, only_need, CATALOG)
    ok &= check("двери в ПД нет на плане — опора на требование текстом",
                "проект требует открывания по направлению выхода" in f["extraction"]["detail"])
    same = {"PD": [dict(c, value="против хода") if c.get("form") == "door" else c for c in cands["PD"]],
            "RD": [c for c in cands["RD"] if c.get("key") != "ДН3"]}
    [f] = matrix_rules.door_findings(OBJ, "AR-043", rule, same, CATALOG)
    ok &= check("та же дверь против хода и в ПД — не изменение стадий, так и сказано",
                f["violation_label"] == "NO_VIOLATION" and f["extraction"]["detail"] == "против хода, как и в ПД: Д-2, Д1",
                f["extraction"]["detail"])
    good = {"PD": cands["PD"], "RD": [dict(c, value="по ходу") if c.get("form") == "door" else c for c in cands["RD"]]}
    [f] = matrix_rules.door_findings(OBJ, "AR-043", rule, good, CATALOG)
    ok &= check("все двери РД по ходу — «нарушения нет»", f["violation_label"] == "NO_VIOLATION", f["extraction"]["detail"])
    ok &= check("ничего не прочитано — записи нет", matrix_rules.door_findings(OBJ, "AR-043", rule,
                                                                           {"PD": [], "RD": []}, CATALOG) == [])
    return ok


def main():
    ok = parsing()
    ok &= the_pass()
    ok &= findings()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
