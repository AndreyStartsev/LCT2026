#!/usr/bin/env python3
"""Сборка словаря марок, синонимов и сокращений. Задача #5.

Три источника, в порядке доверия:

1. «Легенда к матрице» из пакета участника: расшифровки марок чертежей, разделов
   проектной документации и единиц измерения. Это слова самого организатора.
2. Предметная часть, внесённая руками: системы отопления и вентиляции, помещения
   и элементы, вокруг которых крутятся все три эталонных нарушения. Легенда их
   не покрывает: она про разделы документации, а не про оборудование.
3. Корпус: наименования помещений из экспликаций и пары «марка — наименование»
   из спецификаций. Добываются скриптом, идут как варианты написания.

  python dictionary/build.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dictionary", "terms.jsonl")
LEGEND = os.path.join(ROOT, "data", "01_ПАКЕТ_УЧАСТНИКАМ_3_ОБЪЕКТА",
                     "ХАКАТОН_УЧАСТНИКАМ_ГОТОВО_К_ПЕРЕДАЧЕ", "00_ТЗ_И_ПРИЛОЖЕНИЯ",
                     "Легенда к матрице.docx")

# Таблицы легенды, которые нас интересуют, и вид сущности в каждой
LEGEND_TABLES = {0: "ABBREVIATION", 1: "SECTION_PD", 2: "MARK", 5: "UNIT"}


def from_legend():
    """Расшифровки из «Легенды к матрице»."""
    try:
        import docx
    except ImportError:
        print("нет python-docx, легенда пропущена", file=sys.stderr)
        return []
    if not os.path.exists(LEGEND):
        print("легенда не найдена, пропущена", file=sys.stderr)
        return []
    d = docx.Document(LEGEND)
    out = []
    for idx, kind in LEGEND_TABLES.items():
        if idx >= len(d.tables):
            continue
        for row in d.tables[idx].rows[1:]:
            cells = [c.text.strip() for c in row.cells]
            if len(cells) < 2 or not cells[0] or not cells[1]:
                continue
            short, full = cells[0], cells[1]
            # в скобках пояснение, оно не часть наименования
            clean = re.sub(r"\s*\([^)]*\)\s*$", "", full).strip()
            out.append({
                "term_id": f"LEG-{kind}-{short.replace(' ', '_').replace('/', '_')}",
                "canonical": clean or full,
                "kind": kind,
                "section": None,
                "mark": short if kind == "MARK" else None,
                "variants": sorted({short, clean, full} - {""}),
                "source": "LEGEND",
                "note": full if full != clean else None,
            })
    return out


# Предметная часть. Внесена руками, потому что легенда про разделы документации,
# а нарушения — про оборудование внутри помещений.
DOMAIN = [
    {
        "term_id": "OV-SUPPLY", "canonical": "приточная система", "kind": "SYSTEM",
        "section": "OV", "mark_pattern": r"^П\s?\d{1,2}(\.\d{1,2})?$",
        "variants": ["приточная система", "приточная установка",
                     "приточная вентиляционная установка", "приточная вентиляция",
                     "система приточной вентиляции", "приточка"],
        "note": "марка П с номером; на Тюменской-5 П5–П9 подписаны «приточная установка»",
    },
    {
        "term_id": "OV-EXHAUST", "canonical": "вытяжная система", "kind": "SYSTEM",
        "section": "OV", "mark_pattern": r"^В\s?\d{1,2}(\.\d{1,2})?$",
        "variants": ["вытяжная система", "вытяжная установка", "вытяжная вентиляция",
                     "система вытяжной вентиляции", "вытяжка"],
        "note": "марка В с номером; третье эталонное нарушение про отсутствие такой системы",
    },
    {
        "term_id": "OV-SUPPLY-EXHAUST", "canonical": "приточно-вытяжная система",
        "kind": "SYSTEM", "section": "OV", "mark_pattern": r"^ПВ\s?\d{1,2}$",
        "variants": ["приточно-вытяжная система", "приточно-вытяжная установка",
                     "приточно вытяжная система"],
    },
    {
        "term_id": "OV-SMOKE", "canonical": "система дымоудаления", "kind": "SYSTEM",
        "section": "OV", "mark_pattern": r"^(ДУ|ВД)\s?\d{0,2}$",
        "variants": ["дымоудаление", "система дымоудаления", "противодымная вентиляция",
                     "пожарное дымоудаление"],
    },
    {
        "term_id": "OV-UNDERFLOOR", "canonical": "система тёплых полов", "kind": "SYSTEM",
        "section": "OV", "mark_pattern": r"^ТП\s?\d{0,2}$",
        "variants": ["тёплый пол", "теплый пол", "тёплые полы", "теплые полы",
                     "система тёплых полов", "система теплых полов",
                     "напольное отопление", "обогрев пола"],
        "note": "второе эталонное нарушение: не выполнены предусмотренные проектом тёплые полы",
    },
    {
        "term_id": "ROOM-VENT-CHAMBER", "canonical": "венткамера", "kind": "ROOM",
        "section": "OV",
        "variants": ["венткамера", "вентиляционная камера", "вент.камера",
                     "вент камера", "помещение вентиляционного оборудования",
                     "помещение венткамеры"],
        "note": "первое эталонное нарушение: венткамера 012",
    },
    {
        "term_id": "ROOM-FORECHAMBER", "canonical": "форкамера", "kind": "ROOM",
        "section": "OV", "variants": ["форкамера", "фор.камера", "фор камера"],
        "note": "соседствует с венткамерой; на листе 26 номера 012 и 012.1 стоят рядом",
    },
    {
        "term_id": "ROOM-AIR-INTAKE", "canonical": "воздухозаборная шахта", "kind": "ROOM",
        "section": "OV",
        "variants": ["воздухозаборная шахта", "воздухозабор", "шахта воздухозабора"],
    },
    {
        "term_id": "ROOM-ITP", "canonical": "индивидуальный тепловой пункт", "kind": "ROOM",
        "section": "OV", "mark_pattern": r"^ИТП$",
        "variants": ["ИТП", "индивидуальный тепловой пункт", "тепловой пункт"],
    },
    {
        "term_id": "ROOM-MGN", "canonical": "помещение для маломобильных групп населения",
        "kind": "ROOM", "section": "ODI",
        "variants": ["МГН", "для МГН", "маломобильные группы населения",
                     "помещение МГН", "санузел для МГН"],
        "note": "второе эталонное нарушение адресовано помещениям МГН 267, 270, 271, 272",
    },
    {
        "term_id": "OV-CONDITIONING", "canonical": "кондиционирование воздуха",
        "kind": "SYSTEM", "section": "OV",
        "variants": ["кондиционирование", "кондиционирование воздуха",
                     "система кондиционирования", "кондиционер", "сплит-система"],
        "note": "встречается на 452 страницах Тюменской-5, найдено проверкой покрытия",
    },
    {
        "term_id": "OV-FAN", "canonical": "вентилятор", "kind": "EQUIPMENT",
        "section": "OV",
        "variants": ["вентилятор", "осевой вентилятор", "радиальный вентилятор",
                     "канальный вентилятор", "крышный вентилятор"],
    },
    {
        "term_id": "OV-DUCT", "canonical": "воздуховод", "kind": "EQUIPMENT",
        "section": "OV",
        "variants": ["воздуховод", "воздуховоды", "вентиляционный короб", "короб"],
    },
    {
        "term_id": "OV-HEATER", "canonical": "отопительный прибор", "kind": "EQUIPMENT",
        "section": "OV",
        "variants": ["отопительный прибор", "радиатор", "конвектор",
                     "калорифер", "нагреватель"],
    },
    {
        "term_id": "OV-NATURAL-EXHAUST", "canonical": "вытяжная с естественным побуждением",
        "kind": "SYSTEM", "section": "OV", "mark_pattern": r"^ВЕ\s?\d{0,2}$",
        "variants": ["естественное побуждение", "с естественным побуждением",
                     "вытяжная с естественным побуждением"],
        "note": "марка ВЕ; встретилась на Тюменской-5 в описании вытяжных систем",
    },
    {
        "term_id": "OV-FIRE-DAMPER", "canonical": "огнезадерживающий клапан",
        "kind": "EQUIPMENT", "section": "OV", "mark_pattern": r"^ОЗК\s?\d{0,2}$",
        "variants": ["огнезадерживающий клапан", "противопожарный клапан",
                     "клапан дымоудаления", "ОЗК"],
    },
    {
        "term_id": "ORG-FORM-OOO", "canonical": "общество с ограниченной ответственностью",
        "kind": "ORG_FORM",
        "variants": ["ООО", "общество с ограниченной ответственностью", "000"],
        "note": "распознавание читает ООО как три нуля; учтено и в нормализации скорера",
    },
    {
        "term_id": "ORG-FORM-AO", "canonical": "акционерное общество", "kind": "ORG_FORM",
        "variants": ["АО", "акционерное общество", "ПАО",
                     "публичное акционерное общество", "ЗАО",
                     "закрытое акционерное общество"],
    },
    {
        "term_id": "MAT-CONCRETE-CLASS", "canonical": "класс бетона по прочности",
        "kind": "PARAMETER", "section": "KR", "mark_pattern": r"^[ВB]\s?\d{1,3}(,\d)?$",
        "variants": ["класс бетона", "класс прочности бетона", "бетон класса",
                     "проектный класс бетона", "БСТ"],
        "note": "на листе кириллическая В, распознавание читает латинскую B",
    },
]


def mine_rooms():
    """Наименования помещений из уже собранных реестров."""
    out, seen = [], {}
    build = os.path.join(ROOT, "build")
    if not os.path.isdir(build):
        return out
    for obj in sorted(os.listdir(build)):
        path = os.path.join(build, obj, "rooms.jsonl")
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            name = (r.get("name") or "").strip().lower()
            if len(name) < 4 or len(name) > 50:
                continue
            seen.setdefault(name, 0)
            seen[name] += 1
    for name, n in sorted(seen.items(), key=lambda kv: -kv[1]):
        out.append({
            "term_id": "CORP-ROOM-" + re.sub(r"[^a-zа-я0-9]+", "-", name)[:40],
            "canonical": name, "kind": "ROOM_NAME_OBSERVED", "section": None,
            "variants": [name], "source": "CORPUS",
            "note": f"встретилось в экспликациях, раз: {n}",
        })
    return out


def main():
    rows = []
    for r in from_legend():
        rows.append(r)
    for r in DOMAIN:
        r = dict(r)
        r.setdefault("source", "MANUAL")
        r.setdefault("mark_pattern", None)
        r.setdefault("note", None)
        r["variants"] = sorted(set(r["variants"]))
        rows.append(r)
    rows.extend(mine_rooms())

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    import collections
    by_kind = collections.Counter(r["kind"] for r in rows)
    by_src = collections.Counter(r["source"] for r in rows)
    print(f"словарь: {OUT}")
    print(f"  записей {len(rows)}, вариантов написания {sum(len(r['variants']) for r in rows)}")
    print(f"  по виду: {dict(by_kind)}")
    print(f"  по источнику: {dict(by_src)}")


if __name__ == "__main__":
    main()
