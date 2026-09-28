"""Разбор актов освидетельствования в XML по схеме Минстроя. Задача #7.

Зачем: в исполнительной документации акты лежат комплектами «PDF плюс XML плюс
DOCX плюс подписи». XML отдаёт структурно то, ради чего мы иначе читали бы картинку,
и отдаёт лучше, чем это можно прочитать с листа.

Самое ценное в нём — готовая связка исполнительной документации с рабочей:

    работы            «Устройство гидрошпонки ХВС 150/1»
    место             «в осях 14-17/А-Ж на отм. -6.100»
    шифр раздела РД   23.009-Р-ГИ
    номер листа       2

То есть акт сам говорит, какой лист какой рабочей документации он подтверждает
и в каких осях. Ни распознавания, ни разбора основной надписи для этого не нужно.

Практический вес: текстовый слой есть только у 39 процентов страниц исполнительной
документации, то есть она самая трудная для чтения и одновременно самая
структурированная в XML.

Пространство имён схемы: http://idActs/AOSR.xsd
"""
import os
import re
import xml.etree.ElementTree as ET


def _tag(el):
    return re.sub(r"^\{[^}]*\}", "", el.tag)


def _find(root, path):
    """Поиск по пути из локальных имён, без учёта пространств имён.

    Если путь не разрешается напрямую, ищем его первый элемент среди всех потомков
    и пробуем снова. Схема вложена глубоко и неравномерно: список разделов рабочей
    документации лежит на шесть уровней ниже акта, а в другой редакции может лежать
    иначе. Точные пути на такой схеме ломаются молча, поиск по имени — нет.
    """
    parts = path.split("/")
    cur = [root]
    for part in parts:
        nxt = []
        for el in cur:
            nxt.extend(c for c in el if _tag(c) == part)
        if not nxt:
            break
        cur = nxt
    else:
        return cur
    # прямой путь не сошёлся: ищем голову пути где угодно в поддереве
    heads = [el for el in root.iter() if _tag(el) == parts[0]]
    for head in heads:
        got = _find(head, "/".join(parts[1:])) if len(parts) > 1 else [head]
        if got:
            return got
    return []


def _all(root, name):
    """Все потомки с данным локальным именем, на любой глубине."""
    return [el for el in root.iter() if _tag(el) == name]


def _first(root, name, default=None):
    """Значение первого потомка с таким локальным именем, на любой глубине."""
    for el in _all(root, name):
        t = (el.text or "").strip()
        if t:
            return t
    return default


def _text(root, path, default=None):
    els = _find(root, path)
    if not els:
        return default
    t = (els[0].text or "").strip()
    return t or default


def _org(el):
    """Реквизиты организации: наименование, ОГРН, ИНН, саморегулируемая организация."""
    if el is None:
        return None
    return {
        "name": _text(el, "organizationInfo/legalEntity/name"),
        "ogrn": _text(el, "organizationInfo/legalEntity/ogrn"),
        "inn": _text(el, "organizationInfo/legalEntity/inn"),
        "address": _text(el, "organizationInfo/legalEntity/address/stringAddress"),
        "sro": _text(el, "organizationInfo/sro/name"),
    }


def _person(el):
    if el is None:
        return None
    r = _find(el, "representative")
    r = r[0] if r else el
    fio = " ".join(x for x in (_text(r, "lastName"), _text(r, "firstName"),
                               _text(r, "middleName")) if x)
    return {
        "fio": fio or None,
        "position": _text(r, "position"),
        "person_id": _text(r, "personId"),
        "order_number": _text(r, "administrativeDocument/number"),
        "order_date": _text(r, "administrativeDocument/date"),
    }


def parse(path):
    """Разобрать один акт. Возвращает запись, готовую к укладке в находку."""
    root = ET.parse(path).getroot()
    act = _find(root, "actInfo")
    act = act[0] if act else root

    works = []
    for it in _all(act, "worksListItem"):
        works.append({
            "name": _text(it, "workDescription/workName"),
            "place": _text(it, "location/place"),
        })

    sections = []
    for it in _all(act, "workDocumentationSectionsListItem"):
        sheets = [(_x.text or "").strip() for _x in _all(it, "sheetNumber")]
        sections.append({
            "code": _text(it, "workDocumentationSectionCode"),
            "name": _text(it, "workDocumentationSectionName"),
            "sheets": [s for s in sheets if s],
        })
    # в части актов раздел лежит в сокращённом списке
    for it in _all(act, "shortWorkDocumentationSectionsListItem"):
        code, name = _text(it, "number"), _text(it, "name")
        if code and not any(s["code"] == code for s in sections):
            sections.append({"code": code, "name": name, "sheets": []})

    materials = []
    for it in _all(act, "usedMaterialsListItem"):
        docs = []
        for d in _all(it, "untypedQualityApproveDocumentsListItem"):
            docs.append({"name": _text(d, "name"), "number": _text(d, "number"),
                         "date": _text(d, "date")})
        materials.append({"name": _text(it, "name"), "quality_documents": docs})

    regulations = [{"number": _text(it, "number"), "name": _text(it, "name")}
                   for it in _all(act, "technicalRegulationDetailsListItem")]

    schemas = [{"name": _text(it, "name"), "number": _text(it, "number"),
                "date": _text(it, "date"), "doc_id": _text(it, "docId")}
               for it in _all(act, "asBuiltSchemasListItem")]

    def one(path):
        els = _find(act, path)
        return els[0] if els else None

    return {
        "doc_kind": "AOSR" if _tag(root) == "aosr" else _tag(root),
        "source_path": os.path.basename(path),
        "act_uuid": _text(root, "uuid"),
        # У исполнительных схем своя схема XML (корень asBuiltSchemaDoc) и свои
        # имена полей: docCode вместо number, docDate вместо date. Читаем оба варианта.
        "act_number": _text(act, "documentInfo/number") or _first(root, "docCode"),
        "act_date": _text(act, "documentInfo/date") or _first(root, "docDate"),
        "act_name": _text(act, "documentInfo/name") or _first(root, "docName"),
        "doc_type": _first(root, "docType"),
        "attached_file": _first(root, "name") if _tag(root) != "aosr" else None,
        "issuer": _first(root, "organizationName"),
        "status": _text(root, "actsServiceAttributes/status/docStatus"),
        "object_name": _text(act, "permanentObjectInfo/permanentObjectName"),
        "object_uuid": _text(root, "permanentObjectUUID"),
        "oktmo": _text(act, "permanentObjectInfo/permanentObjectAddress/constructionSiteAddress"
                            "/oktmoCodesList/oktmoCodesListItem"),
        "technical_customer": _org(one("technicalCustomer")),
        "building_contractor": _org(one("buildingContractor")),
        "project_contractor": _org(one("projectDocumentationContractor")),
        "work_executor": _text(act, "workExecutor/legalEntity"),
        "representatives": {
            "technical_customer": _person(one("technicalCustomerRepresentative")),
            "construction_management": _person(one("constructionManagementRepresentative")),
            "project_contractor": _person(one("projDocContractRepresentative")),
            "work_executor": _person(one("workExecutorRepresentative")),
        },
        "works": works,
        "documentation_sections": sections,
        "materials": materials,
        "regulations": regulations,
        "as_built_schemas": schemas,
        "work_begin": _text(act, "worksDate/beginDate"),
        "work_end": _text(act, "worksDate/endDate"),
        "signatures": len(_find(root, "signatures")[0]) if _find(root, "signatures") else 0,
    }


def scan(root_dir):
    """Разобрать все акты в каталоге объекта."""
    out, errors = [], []
    for dirpath, _, files in os.walk(root_dir):
        for fn in sorted(files):
            if not fn.lower().endswith(".xml"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                rec = parse(path)
            except Exception as e:
                errors.append({"path": os.path.relpath(path, root_dir),
                               "error": f"{type(e).__name__}: {e}"[:160]})
                continue
            if rec.get("act_number") or rec.get("works") or rec.get("documentation_sections"):
                rec["relative_path"] = os.path.relpath(path, root_dir)
                out.append(rec)
    return out, errors
