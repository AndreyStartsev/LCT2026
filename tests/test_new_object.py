"""Проверка подключения объекта, которого система не видела: реестры организатора и готовность. Задача #39.

  python tests/test_new_object.py

Реестр нового объекта приходит в одном из двух форматов организатора и подключается
переменной INSPECTOR_MANIFESTS. Отчёт готовности показывает то, что иначе видно только
по пустому результату правил: страницы без текста, файлы без стадии, чужие форматы.
"""
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import config, readiness, registry  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def write(path, rows):
    with io.open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def test_manifests():
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        ours = write(os.path.join(tmp, "document_manifest.jsonl"), [
            {"file_id": "F0001", "sha256": "aa", "stage": "PD", "section": "AR", "pdf_pages": 12},
            {"file_id": "F0002", "sha256": "bb", "stage": "RD", "section": "KR", "pdf_pages": 3},
        ])
        theirs = write(os.path.join(tmp, "files_index.jsonl"), [
            {"file_id": "F9001", "source_sha256": "aa", "stage": "RD", "section": "OV",
             "source_relative_path": "РД/ОВ.pdf", "source_page_count": 40},
            {"file_id": "F9002", "source_sha256": "cc", "stage": "ID", "section": "OTHER",
             "source_relative_path": "ИД/Акт.pdf", "source_page_count": 1},
            {"sha256": "dd", "stage": "PD"},                      # без идентификатора — пропускается
        ])
        both = registry.load_official([theirs, ours])
        ok &= check("файловый индекс пакета читается наравне с нашим реестром",
                    both["cc"]["file_id"] == "F9002" and both["cc"]["pdf_pages"] == 1)
        ok &= check("реестр нового объекта идёт первым и выигрывает у пакета",
                    both["aa"]["file_id"] == "F9001" and both["aa"]["stage"] == "RD")
        ok &= check("строка без идентификатора пропускается", "dd" not in both)
        ok &= check("файл только в реестре пакета остаётся", both["bb"]["file_id"] == "F0002")

        os.environ[config.MANIFESTS_ENV] = os.pathsep.join([theirs, os.path.join(tmp, "нет.jsonl")])
        try:
            paths = config.manifest_paths()
            by_env = registry.load_official()
            ok &= check("пути берутся из переменной окружения, реестр пакета остаётся последним",
                        paths[0] == theirs and paths[-1] == config.OFFICIAL_MANIFEST, str(len(paths)))
            ok &= check("отсутствующий путь пропускается молча", by_env["cc"]["file_id"] == "F9002")
        finally:
            del os.environ[config.MANIFESTS_ENV]
    return ok


def test_registry_rows():
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "Новый объект")
        for rel in ("Том 1 ПД/Пояснительная записка.xml", "Раздел 3. РД/КЖ1.xml",
                    "АОСР/Акт 12.xml", "Чертежи/план.dwg"):
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            io.open(path, "w", encoding="utf-8").write(f"<doc>{rel}</doc>")
        config.register_object("OBJ-TEST-NEW", root, "Новый объект", split="EXTERNAL")
        rows = registry.build("OBJ-TEST-NEW")
        by_path = {r["relative_path"]: r for r in rows}
        stages = {p.split("/")[0]: r["stage"] for p, r in by_path.items()}
        ok &= check("стадия по чужим названиям папок",
                    stages == {"Том 1 ПД": "PD", "Раздел 3. РД": "RD", "АОСР": "ID", "Чертежи": "UNKNOWN"},
                    str(stages))
        dwg = by_path["Чертежи/план.dwg"]
        ok &= check("файл формата без разбора остаётся строкой реестра",
                    dwg["status"] == "UNSUPPORTED_FORMAT" and dwg["id_source"] == "NONE", dwg["file_id"])
        s = registry.summary(rows)
        ok &= check("в сводке он считается отдельно, а не как документ",
                    s["files"] == 3 and s["unsupported"] == 1 and s["unsupported_by_extension"] == {".dwg": 1}, str(s))
    return ok


def test_readiness():
    ok = True
    docs = [
        {"stage": "PD", "section": "AR", "extension": ".pdf"},
        {"stage": "UNKNOWN", "section": "OTHER", "extension": ".pdf"},
        {"stage": "RD", "section": "KR", "extension": ".pdf", "duplicate_of": "L0001"},
        {"stage": "UNKNOWN", "section": "OTHER", "extension": ".dwg", "status": "UNSUPPORTED_FORMAT"},
    ]
    pages = ([{"text": "есть", "text_source": "TEXT_LAYER", "quality": "OK"}] * 3
             + [{"text": "", "text_source": "NONE", "quality": "LOW_QUALITY"}] * 7)
    rep = readiness.report(docs, pages, ocr_enabled=False, model_enabled=False)
    ok &= check("дубль и чужой формат не считаются документами объекта",
                rep["files"] == 2 and rep["unsupported"] == 1, str(rep["files"]))
    ok &= check("страницы без текста считаются долей",
                rep["pages_without_text"] == 7 and rep["share_without_text"] == 0.7)
    ok &= check("файлы без стадии и без раздела видны",
                rep["stage_unknown"] == 1 and rep["section_other"] == 1)
    notes = " | ".join(readiness.notes(rep))
    # способ чтения выбирает инспектор при загрузке (#54), поэтому предупреждение
    # говорит ему, что сделать, а не какую переменную окружения поставить оператору
    ok &= check("при выключенном распознавании сказано, чем помочь",
                "только текстовым слоем" in notes and "слой и распознавание" in notes)
    ok &= check("предупреждение про формат без разбора есть", ".dwg" in notes, notes)
    quiet = readiness.report([{"stage": "PD", "section": "AR", "extension": ".pdf"}],
                             [{"text": "есть", "text_source": "TEXT_LAYER", "quality": "OK"}])
    ok &= check("на прочитанном объекте предупреждений нет", readiness.notes(quiet) == [])
    return ok


def main():
    ok = True
    for title, fn in (("Реестры организатора", test_manifests),
                      ("Реестр объекта вне конфигурации", test_registry_rows),
                      ("Готовность объекта", test_readiness)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
