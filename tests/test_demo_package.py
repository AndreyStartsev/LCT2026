"""Демонстрационный пакет «НК12-2023» находит свои два нарушения и ничего лишнего.

  python tests/test_demo_package.py

Пакет `examples/demo-package/НК12-2023` — для живого показа на защите. Правка правил или конвейера
может тихо увести из него заложенные нарушения, и это выяснится на сцене. Здесь пакет проводится
тем же сквозным прогоном, что `pipeline.cli run`, во временный каталог сборки и кеша, и проверяется:

- стадии по папкам, шифр и лист из основной надписи;
- все страницы читаются текстовым слоем: ни распознавания, ни модели, ни прицельного прохода по чертежам;
- ровно два нарушения — класс бетона фундаментной плиты (ПД B30, РД и ИД B25) и вытяжка помещения 107;
- у остальных параметров «нарушения нет», «сравнение невозможно» нет, гипотез черновиков нет.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "examples", "demo-package", "НК12-2023")
OBJECT = "DEMO-NK12"
MB = 1024 * 1024


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def cli(env, *args):
    got = subprocess.run([sys.executable, "-m", "pipeline.cli", *args, "--object", OBJECT, "--root", PACKAGE],
                         cwd=ROOT, env=env, capture_output=True, text=True)
    if got.returncode:
        print(got.stdout[-2000:], got.stderr[-2000:])
    return got


def test_limits():
    files = [os.path.join(d, n) for d, _, names in os.walk(PACKAGE) for n in names if n.endswith(".pdf")]
    sizes = [os.path.getsize(f) for f in files]
    ok = check("в пакете есть PDF", bool(files), str(len(files)))
    ok &= check("каждый файл меньше 50 МБ", all(s < 50 * MB for s in sizes))
    ok &= check("пакет меньше 200 МБ", sum(sizes) < 200 * MB, f"{sum(sizes) / MB:.2f} МБ")
    return ok


def test_run(tmp):
    env = dict(os.environ, PIPELINE_OUT=os.path.join(tmp, "out"), PIPELINE_CACHE=os.path.join(tmp, "cache"),
               PIPELINE_FRESH="", PIPELINE_FRESH_RULES="")
    env.pop("INSPECTOR_MANIFESTS", None)
    ok = check("сквозной прогон проходит", cli(env, "run", "--no-model").returncode == 0)
    out = os.path.join(tmp, "out", OBJECT)

    print("\n2. Реестр и чтение")
    docs = read_jsonl(os.path.join(out, "documents.jsonl"))
    stages = {d["relative_path"].split("/")[0]: d["stage"] for d in docs}
    ok &= check("стадия по папке: 01_ПД, 02_РД, 03_ИД", stages == {"01_ПД": "PD", "02_РД": "RD", "03_ИД": "ID"},
                str(stages))
    pages = read_jsonl(os.path.join(out, "pages.jsonl"))
    ok &= check("все страницы — текстовый слой", pages and all(p.get("text_source") == "TEXT_LAYER" for p in pages),
                str({p.get("text_source") for p in pages}))
    thin = [(p["file_id"], p["pdf_page_number"]) for p in pages
            if p.get("kind") == "DRAWING" and len((p.get("text") or "").split()) < 40]
    ok &= check("у чертежей слой не тоньше порога, с которого страницу читает модель", not thin, str(thin))
    with open(os.path.join(out, "readiness.json"), encoding="utf-8") as f:
        ready = json.load(f)
    ok &= check("вызовов модели нет", ready.get("model_calls") == 0 and ready.get("pages_without_text") == 0)
    by_id = {d["file_id"]: d["relative_path"] for d in docs}
    sheets = {(by_id[r["file_id"]].split("/")[-1], r["pdf_page_number"]): r for r in read_jsonl(os.path.join(out, "sheets.jsonl"))}
    kzh1 = sheets.get(("НК12-2023-КЖ1 Подземная часть.pdf", 2)) or {}
    ok &= check("основная надпись листа КЖ1: шифр, лист 2, стадия Р",
                (kzh1.get("document_code"), kzh1.get("document_sheet_number"), kzh1.get("stage_from_titleblock"))
                == ("НК12-2023-КЖ1", 2, "RD"), str({k: kzh1.get(k) for k in ("document_code", "document_sheet_number")}))

    print("\n3. Нарушения")
    findings = [f for name in sorted(os.listdir(out)) if name.startswith("findings_")
                for f in read_jsonl(os.path.join(out, name))]
    violations = {f["parameter_code"]: f for f in findings if f["violation_label"] == "VIOLATION_PRESENT"}
    ok &= check("нарушений ровно два: KR-055 и IOS4-078", sorted(violations) == ["IOS4-078", "KR-055"],
                str([(f["parameter_code"], f["locations"]) for f in findings if f["violation_label"] == "VIOLATION_PRESENT"]))
    concrete = violations.get("KR-055") or {}
    ok &= check("KR-055: фундаментная плита, ПД B30, РД B25, ИД B25",
                (concrete.get("locations"), concrete.get("pd_value"), concrete.get("rd_value"), concrete.get("id_value"))
                == (["Фундаментная плита"], "B30", "B25", "B25"))
    seen = {(e["stage"], by_id.get(e["file_id"], "").split("/")[-1], e["pdf_page_number"])
            for e in concrete.get("evidence") or []}
    ok &= check("KR-055: доказательства — лист опалубки КЖ1, протокол испытаний и акт",
                {("RD", "НК12-2023-КЖ1 Подземная часть.pdf", 2), ("ID", "Протокол № 218-Б испытаний бетона.pdf", 1),
                 ("ID", "АООК № 001 Фундаментная плита.pdf", 1)} <= seen, str(sorted(seen)))
    room = violations.get("IOS4-078") or {}
    ok &= check("IOS4-078: помещение 107, в рабочей документации систем нет",
                (room.get("locations"), room.get("comparison_result")) == (["107"], "MISSING_DESIGN_ELEMENT"))
    roles = {(e["stage"], e.get("role")) for e in room.get("evidence") or []}
    ok &= check("IOS4-078: таблицы систем обеих стадий, схема проекта и план рабочей документации",
                {("PD", "SYSTEMS_TABLE"), ("RD", "SYSTEMS_TABLE"), ("PD", "SCHEME"), ("RD", "PLAN")} <= roles, str(roles))
    unsure = [(f["parameter_code"], f["locations"]) for f in findings if f["violation_label"] == "COMPARISON_IMPOSSIBLE"]
    ok &= check("«сравнение невозможно» нет", not unsure, str(unsure))
    free = read_jsonl(os.path.join(out, "findings_free.jsonl")) + read_jsonl(os.path.join(out, "findings_acts.jsonl"))
    ok &= check("свободный поиск и сверка актов гипотез не дают", not free, str([f["parameter_code"] for f in free]))

    print("\n4. Черновики правил и проход по чертежам")
    ok &= check("черновики правил проходят", cli(env, "rules", "--provisional").returncode == 0)
    drafts = [(f["parameter_code"], f["locations"]) for name in sorted(os.listdir(out)) if name.startswith("provisional_q")
              for f in read_jsonl(os.path.join(out, name)) if f["violation_label"] == "VIOLATION_PRESENT"]
    ok &= check("гипотез черновиков нет", not drafts, str(drafts))
    vlm_env = dict(env, OPENROUTER_API_KEY=env.get("OPENROUTER_API_KEY") or "dry-run")
    for extra in ((), ("--provisional",)):
        got = cli(vlm_env, "vlm", "--dry", *extra)
        picked = [int(n) for n in re.findall(r"листов отобрано (\d+)", got.stdout)]
        ok &= check(f"прицельный проход не отбирает ни одного листа{' (черновики)' if extra else ''}",
                    got.returncode == 0 and picked and not any(picked), f"правил {len(picked)}, листов {sum(picked)}")
    return ok


def main():
    print("\n1. Лимиты браузера")
    ok = test_limits()
    with tempfile.TemporaryDirectory() as tmp:
        ok &= test_run(tmp)
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
