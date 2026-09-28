"""DOC, XLS и XLSX в исполнительной документации: текст и акты. Задача #112.

  python tests/test_office_text.py

XLSX собирается тут же `openpyxl`. DOC — `textutil`, если он есть (macOS); где его нет,
проверка DOC пропускается и говорит об этом. XLS собрать нечем (`xlrd` только читает),
поэтому у него проверяется разбор значений и то, что испорченный файл не роняет чтение.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import aosr_text, office_text  # noqa: E402


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def test_cells():
    import datetime
    v = office_text.cell_text
    ok = check("целое без «.0»", v(12.0) == "12", v(12.0))
    ok &= check("дробь с запятой", v(3.5) == "3,5", v(3.5))
    ok &= check("дата — дд.мм.гггг", v(datetime.datetime(2025, 12, 29)) == "29.12.2025")
    ok &= check("пустая ячейка — пусто", v(None) == "")
    return ok


def test_xlsx():
    import openpyxl
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "Реестр передаваемой док. К1.xlsx")
        book = openpyxl.Workbook()
        ws = book.active
        ws.title = "Реестр"
        ws.append(["№", "Наименование документа", "Листов"])
        ws.append([1, "Акт освидетельствования скрытых работ № 1-ВК/К1", 2.0])
        ws.append([2, "Исполнительная схема К1", 1.5])
        book.save(path)
        text = office_text.text(path)
        ok &= check("строки листа — строки текста, ячейки через табуляцию",
                    "1\tАкт освидетельствования скрытых работ № 1-ВК/К1\t2" in text, repr(text[:120]))
        ok &= check("название листа в тексте", text.startswith("Лист: Реестр"))
        ok &= check("дробь с запятой", "\t1,5" in text)
        broken = os.path.join(tmp, "сломан.xls")
        open(broken, "wb").write(b"not an excel file")
        ok &= check("испорченный XLS — пустой текст, без исключения", office_text.text(broken) == "")
    return ok


def test_doc():
    if not shutil.which("textutil"):
        print("  пропущено: нет textutil, чтобы собрать DOC (на Linux DOC читает catdoc из образа воркера)")
        return True
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "акт.txt")
        open(src, "w", encoding="utf-8").write("АКТ\nприемки систем естественной вентиляции\nг. Москва 29 декабря 2025 г.\n")
        path = os.path.join(tmp, "19.1 Акт приёмки системы естественной вентиляции.doc")
        subprocess.run(["textutil", "-convert", "doc", src, "-output", path], check=True, capture_output=True)
        text = office_text.text(path)
        ok &= check("DOC прочитан, кириллица цела", "приемки систем естественной вентиляции" in text, repr(text[:80]))
        ok &= check("программа для DOC названа", office_text.converter() in ("catdoc", "textutil", "antiword"),
                    str(office_text.converter()))
    return ok


def test_rules_text():
    """Текст для правил: весь документ одной страницей, источник — формат файла."""
    import openpyxl
    from pipeline import matrix_rules
    ok = True
    # кеш текста — во временной папке. Модули не перезагружаются: под pytest у них общее состояние,
    # и новый словарь объектов в `config` терял бы объекты, которые другие проверки добавили в старый
    before = matrix_rules.CACHE
    with tempfile.TemporaryDirectory() as tmp:
        matrix_rules.CACHE = tmp
        try:
            ok &= _rules_text(matrix_rules, openpyxl, tmp)
        finally:
            matrix_rules.CACHE = before
    return ok


def _rules_text(matrix_rules, openpyxl, tmp):
    ok = True
    path = os.path.join(tmp, "Акт на пролив.xlsx")
    book = openpyxl.Workbook()
    book.active.append(["Акт на пролив", "система К2"])
    book.save(path)
    doc = {"file_id": "U1", "sha256": "ab" * 32, "extension": ".xlsx", "relative_path": os.path.basename(path)}
    rows = list(matrix_rules.page_texts_src(doc, tmp))
    ok &= check("одна страница, источник XLSX", len(rows) == 1 and rows[0][0] == 1 and rows[0][2] == "XLSX",
                str([(p, s) for p, _, s in rows]))
    ok &= check("текст ячеек дошёл до правил", "система К2" in rows[0][1])
    ok &= check("XLSX среди читаемых правилами", ".xlsx" in matrix_rules.READABLE_EXT
                and ".doc" in matrix_rules.READABLE_EXT)
    # строка кеша DOCX прежнего разбора (без отметки `f`) — перечитывается, а не отдаётся
    docx = os.path.join(tmp, "акт.docx")
    _docx(docx, '<w:p><w:r><w:t>№ 52</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>20.04.2026</w:t></w:r></w:p>')
    doc = {"file_id": "U2", "sha256": "cd" * 32, "extension": ".docx", "relative_path": "акт.docx"}
    with open(matrix_rules._text_cache_path(doc["sha256"]), "w", encoding="utf-8") as f:
        f.write(json.dumps({"v": matrix_rules.TEXT_CACHE_VERSION, "p": 1, "t": "№ 5220.04.2026",
                            "s": "DOCX"}, ensure_ascii=False) + "\n")
    rows = list(matrix_rules.page_texts_src(doc, tmp))
    ok &= check("DOCX из кеша прежнего разбора перечитан", rows and rows[0][1] == "№ 52\t20.04.2026",
                repr(rows))
    cached = json.loads(open(matrix_rules._text_cache_path(doc["sha256"]), encoding="utf-8").readline())
    ok &= check("в кеше — отметка разбора", cached.get("f") == matrix_rules.OFFICE_TEXT_VERSION, str(cached))
    return ok


def _docx(path, body):
    import zipfile
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>')


def test_docx_tabs():
    """Табуляция в абзаце DOCX — разделитель: номер акта не слипается с датой (Октябрьская, акт № 52)."""
    from pipeline import matrix_rules
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "Полная версия акта № 52.docx")
        _docx(path, '<w:p><w:r><w:t>освидетельствования скрытых работ</w:t></w:r></w:p>'
                    '<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="7895"/></w:tabs></w:pPr>'
                    '<w:r><w:t>№ 52</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>20.04.2026 г.</w:t></w:r></w:p>'
                    '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>а</w:t><w:tab/><w:t>б</w:t></w:r></w:p></w:tc>'
                    '<w:tc><w:p><w:r><w:t>в</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
        text = matrix_rules.docx_text(path)
        ok &= check("табуляция прогона — знак, позиция табуляции абзаца — нет",
                    "№ 52\t20.04.2026 г." in text, repr(text))
        ok &= check("табуляция внутри ячейки — пробел, ячейки — через табуляцию", "а б\tв" in text, repr(text))
    rec = aosr_text.parse(ACT.replace("№ 6-ОВ2/К7 от 12.03.2025", "№ 52 20.04.2026 г."),
                          "Полная версия акта № 52.docx")
    ok &= check("номер и дата разобраны раздельно", rec and (rec["act_number"], rec["act_date"]) == ("52", "20.04.2026"),
                str(rec and (rec["act_number"], rec["act_date"])))
    ok &= check("совпавший номер записью не становится", rec and "number_in_filename" not in rec)
    return ok


def test_act_dates():
    v = aosr_text.after_date
    ok = check("«« 29 » октября 2025 г.» → 29.10.2025", v(" « 29 » октября 2025 г. (дата") == "29.10.2025")
    ok &= check("«21 февраля 2025 г.» → 21.02.2025", v(" 21 февраля 2025 г.") == "21.02.2025")
    ok &= check("незаполненная «« » 20 г.» — не дата", v(" « » 20 г. (дата") is None)
    sec = aosr_text.sections("2. Работы выполнены по проектной документации: ООО «МСК Проект», шифр проекта "
                             "О4-П.СКБ-ПИР-Р-ВК, листы № 15 (номер, другие реквизиты чертежа")
    ok &= check("«О4» в начале шифра — ноль", sec and sec[0]["code"] == "04-П.СКБ-ПИР-Р-ВК"
                and sec[0]["sheets"] == ["15"], str(sec))
    return ok


ACT = ("АКТ освидетельствования скрытых работ № 6-ОВ2/К7 от 12.03.2025 "
       "1. К освидетельствованию предъявлены следующие работы: монтаж креплений воздуховодов "
       "2. Работы выполнены по проектной документации: 04-П.СКБ-ПИР-Р-ОВ2 лист 3 "
       "3. При выполнении работ применены: шпилька М8 ")


def test_acts():
    ok = True
    rec = aosr_text.parse(ACT, "4. АОСР №1  Монтаж креплений.docx")
    ok &= check("номер акта — из текста", rec and rec["act_number"].startswith("6"), str(rec and rec["act_number"]))
    ok &= check("номер в имени файла не тот — записан", rec and rec.get("number_in_filename") == "1",
                str(rec and rec.get("number_in_filename")))
    same = aosr_text.parse(ACT.replace("6-ОВ2/К7", "4-ВК/К2/К9"), "10. АОСР №4 К2 Изоляция.docx")
    ok &= check("«№4» в имени и «4-ВК/К2/К9» в тексте — один акт", same and "number_in_filename" not in same)
    registry = aosr_text.parse(ACT, "Реестр №1 ЭМ-К9.docx")
    ok &= check("номер реестра в имени файла с номером акта не сверяется",
                registry and "number_in_filename" not in registry)
    docs = [{"file_id": "DOO25-000400", "stage": "ID", "extension": ".docx",
             "relative_path": "ИД/ВИС/ОВ/Кондиционирование/4. АОСР №1  Монтаж креплений.docx"},
            {"file_id": "U0001", "stage": "ID", "extension": ".doc",
             "relative_path": "ИД/ВИС/ОВ/Акты/5. АОСР №5.doc"},
            {"file_id": "X", "stage": "ID", "extension": ".xlsx", "relative_path": "ИД/Реестр.xlsx"}]
    texts = {"DOO25-000400": ACT, "U0001": ACT.replace("6-ОВ2/К7", "5-ОВ2/К7"), "X": ACT}
    rows, stats = aosr_text.scan(docs, lambda d: [(1, texts[d["file_id"]])])
    ok &= check("акты из DOCX и DOC разобраны, XLSX — нет", sorted(r["file_id"] for r in rows) == ["DOO25-000400", "U0001"],
                str(stats))
    ok &= check("источник акта — формат файла", {r["source"] for r in rows} == {"DOCX", "DOC"})
    found = aosr_text.number_findings("OBJ-X", rows)
    ok &= check("запись о несовпадении номера — одна, для инспектора, не в сдачу",
                len(found) == 1 and found[0]["locations"] == ["4. АОСР №1  Монтаж креплений.docx"]
                and found[0]["for_submission"] is False and found[0]["finding_status"] == "SUSPICION",
                json.dumps([f["id_value"] for f in found], ensure_ascii=False))
    return ok


def main():
    ok = True
    for title, fn in (("Значения ячеек", test_cells), ("XLSX и испорченный XLS", test_xlsx),
                      ("DOC", test_doc), ("Табуляция в DOCX", test_docx_tabs),
                      ("Дата и шифр раздела", test_act_dates), ("Текст для правил", test_rules_text),
                      ("Акты из DOCX и DOC", test_acts)):
        print(f"\n{title}")
        ok &= fn()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ СБОИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
