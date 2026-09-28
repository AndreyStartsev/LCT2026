"""Подбор соответствующих листов проектной и рабочей стадии. Задача #21.

## Назначение
Сопоставление листов ПД и РД представляет собой отношение «один ко многим» (1-to-many):
- Листы проектной документации (например, принципиальные схемы ОВ или ВК) охватывают всё здание
  и обслуживают сразу несколько этажей (is_multi_floor = True).
- Листы рабочей документации представляют собой поэтажные планы (отм. -2.950, отм. 0.000, +3.300 и т.д.).
- Для каждого элемента проектного листа (например, помещения с вентиляцией) подбирается строго
  соответствующий поэтажный рабочий лист РД по дисциплине, этажу и системе.
- Если для дисциплины, этажа или системы лист РД отсутствует, возвращается статус RD_MISSING
  / COMPARISON_NOT_POSSIBLE (а не ложное нарушение).
"""

from dataclasses import dataclass, field
import json
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple


DISCIPLINE_PATTERNS = [
    ("АР", [
        re.compile(r"[-/_.]АР\b", re.I),
        re.compile(r"[-/_.]АР\d+", re.I),
        re.compile(r"\bАР\d*\b", re.I),
        re.compile(r"\bАрхитектурн\w*", re.I),
    ]),
    ("КР", [
        re.compile(r"[-/_.]К[РЖМД]\b", re.I),
        re.compile(r"[-/_.]К[РЖМД]\d+", re.I),
        re.compile(r"[-/_.]ОК\b", re.I),
        re.compile(r"\bКЖ\d*\b", re.I),
        re.compile(r"\bКонструк\w*", re.I),
        re.compile(r"\bЖелезобетон\w*", re.I),
    ]),
    ("ГП", [
        re.compile(r"[-/_.]ГП\b", re.I),
        re.compile(r"[-/_.]ПЗУ\b", re.I),
        re.compile(r"\bГенеральн\w*\s+план\b", re.I),
        re.compile(r"\bСПОЗУ\b", re.I),
    ]),
    ("ОВ", [
        re.compile(r"[-/_.]А?ОВ\b", re.I),
        re.compile(r"[-/_.]ОВ\d+", re.I),
        re.compile(r"[-/_.]ИОС\s*4\b", re.I),
        re.compile(r"[-/_.]ИОС\s*4\.\d+", re.I),
        re.compile(r"\bОтоплен\w*", re.I),
        re.compile(r"\bВентиляц\w*", re.I),
        re.compile(r"\bКондиционир\w*", re.I),
        re.compile(r"\bТеплоснабжен\w*", re.I),
    ]),
    ("ВК", [
        re.compile(r"[-/_.]А?ВК\b", re.I),
        re.compile(r"[-/_.]НВК\b", re.I),
        re.compile(r"[-/_.]ИОС\s*[23]\b", re.I),
        re.compile(r"[-/_.]ИОС\s*[23]\.\d+", re.I),
        re.compile(r"\bВодопровод\w*", re.I),
        re.compile(r"\bКанализац\w*", re.I),
        re.compile(r"\bВодоотведен\w*", re.I),
        re.compile(r"\bПожаротушен\w*", re.I),
    ]),
    ("ЭОМ", [
        re.compile(r"[-/_.]Э[ОМСНГ]\b", re.I),
        re.compile(r"[-/_.]ЭОМ\b", re.I),
        re.compile(r"[-/_.]ИОС\s*1\b", re.I),
        re.compile(r"[-/_.]ИОС\s*1\.\d+", re.I),
        re.compile(r"\bЭлектроснабжен\w*", re.I),
        re.compile(r"\bЭлектроосвещен\w*", re.I),
        re.compile(r"\bСиловое\s+электрооборудован\w*", re.I),
    ]),
    ("СС", [
        re.compile(r"[-/_.]СС(?:\d+|\b)", re.I),
        re.compile(r"\bСети\s+связи\b", re.I),
        re.compile(r"\bСКС\b", re.I),
        re.compile(r"\bЛВС\b", re.I),
    ]),
    ("ПОС", [
        re.compile(r"[-/_.]ПОС(?:\d+|\b)", re.I),
        re.compile(r"\bПроект\s+организации\s+строительства\b", re.I),
    ]),
    ("ООС", [
        re.compile(r"[-/_.]ООС(?:\d+|\b)", re.I),
        re.compile(r"\bОхрана\s+окружающей\s+среды\b", re.I),
    ]),
    ("ПБ", [
        re.compile(r"[-/_.]ПБ(?:\d+|\b)", re.I),
        re.compile(r"\bПожарная\s+безопасность\b", re.I),
    ]),
    ("ТБЭ", [
        re.compile(r"[-/_.]ТБЭ(?:\d+|\b)", re.I),
        re.compile(r"\bБезопасная\s+эксплуатация\b", re.I),
    ]),
    ("ЭЭ", [
        re.compile(r"[-/_.]ЭЭ(?:\d+|\b)", re.I),
        re.compile(r"\bЭнергоэффективност\w*", re.I),
    ]),
]


@dataclass
class SheetDescriptor:
    file_id: str
    pdf_page_number: int
    stage: str  # "PD", "RD", "ID", "UNKNOWN"
    discipline: str  # "АР", "КР", "ОВ", "ВК", "ГП", "ЭОМ", "СС", "ПОС", "ООС", "ПБ", "ДРУГОЕ"
    document_code: Optional[str] = None
    sheet_number: Optional[int] = None
    sheet_title: Optional[str] = None
    is_diagram: bool = False
    floors: Set[str] = field(default_factory=set)  # {"0"}, {"1"}, {"2"}, {"3"}, {"ROOF"}
    is_multi_floor: bool = False
    system_roots: Set[str] = field(default_factory=set)  # {"В2", "В3"}, {"К1"}
    rooms: Set[str] = field(default_factory=set)  # {"140", "142", ...}
    relative_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_id": self.file_id,
            "pdf_page_number": self.pdf_page_number,
            "stage": self.stage,
            "discipline": self.discipline,
            "document_code": self.document_code,
            "document_sheet_number": self.sheet_number,
            "sheet_title": self.sheet_title,
            "is_diagram": self.is_diagram,
            "floors": sorted(self.floors),
            "is_multi_floor": self.is_multi_floor,
            "system_roots": sorted(self.system_roots),
            "rooms_count": len(self.rooms),
            "relative_path": self.relative_path,
        }


def extract_discipline(doc_code: Optional[str] = None,
                       sheet_title: Optional[str] = None,
                       path: str = "") -> str:
    """Определение раздела/дисциплины документа или листа по шифру, наименованию и пути."""
    context = " ".join([c for c in (doc_code, sheet_title, path) if c])
    if not context:
        return "ДРУГОЕ"

    # Специфика Тюменской-5: шифры вида ИОС5.4.2 — это ОВ (вентиляция)
    if re.search(r"ИОС5\.[1234]", context, re.I):
        if re.search(r"вентиляц|отоплен|воздуховод|схема систем", context, re.I):
            return "ОВ"
        if re.search(r"водопровод|канализац", context, re.I):
            return "ВК"

    for disc, patterns in DISCIPLINE_PATTERNS:
        for pat in patterns:
            if pat.search(context):
                return disc

    return "ДРУГОЕ"


def infer_room_floor(room_number: str) -> Optional[str]:
    """Определение этажа по номеру помещения (002 -> 0, 140 -> 1, 257 -> 2, 314 -> 3)."""
    if not room_number:
        return None
    r = room_number.strip()
    if len(r) > 6:
        return None
    # Подвал / цоколь (номера 001..099, 01..09)
    if r.startswith("0") and len(r) >= 2:
        return "0"
    m = re.match(r"^([1-4])\d{2}(?:\.\d+)*[а-яА-Яa-zA-Z]?$", r)
    if m:
        return m.group(1)
    m2 = re.match(r"^([1-4])[-.](?:\d+)", r)
    if m2:
        return m2.group(1)
    return None


def extract_system_root(mark: str) -> str:
    """Извлечение корня марки системы (В2.7 -> В2, В3.1 -> В3, П1 -> П1, В4 -> В4)."""
    if not mark:
        return ""
    m = re.match(r"^([А-ЯA-Z]{1,3}\d+)(?:\.\d+)*", mark.strip())
    if m:
        return m.group(1).upper()
    m2 = re.match(r"^([А-ЯA-Z]{1,3})", mark.strip())
    if m2:
        return m2.group(1).upper()
    return mark.strip().upper()


def extract_system_roots(sheet_title: Optional[str] = None,
                         marks: Optional[Set[str]] = None,
                         text: str = "") -> Set[str]:
    """Извлечение всех корней систем вентиляции/отопления/водоснабжения листа."""
    roots: Set[str] = set()
    if marks:
        for m in marks:
            r = extract_system_root(m)
            if r:
                roots.add(r)

    context = " ".join([c for c in (sheet_title, text) if c])
    if context:
        for match in re.finditer(r"\b([ВВППТК]\d{1,2})\b", context):
            roots.add(match.group(1).upper())

    return roots


def is_diagram_sheet(sheet_title: Optional[str] = None, text: str = "") -> bool:
    """Определение типа листа: принципиальная/аксонометрическая схема vs поэтажный план."""
    context = " ".join([c for c in (sheet_title, text) if c])
    if not context:
        return False
    if re.search(r"\b(схема|принципиальная\s+схема|аксонометрическая\s+схема)\b", context, re.I):
        return True
    return False


def extract_floors(sheet_title: Optional[str] = None,
                   text: str = "",
                   rooms: Optional[Set[str]] = None) -> Tuple[Set[str], bool]:
    """Извлечение этажей листа: возвращает (множество этажей, is_multi_floor)."""
    floors: Set[str] = set()
    context = " ".join([c for c in (sheet_title, text) if c])

    if re.search(r"подвал|подземн|на отм\.?\s*-[0-9]|-1\s*этаж", context, re.I):
        floors.add("0")

    # Поэтажные планы вида «1 этаж», «1-го этажа», «этаж 1», «Экспликация помещений 1 этажа»
    for m in re.finditer(r"(?:(\d+)[- ]*(?:й|ти|го)?\s*этаж|этаж[а-я]*\s*(\d+))", context, re.I):
        f = m.group(1) or m.group(2)
        if f and int(f) <= 25:
            floors.add(f)

    # Диапазоны «с 2 по 12 этаж»
    m_range = re.search(r"с\s*(\d+)\s*по\s*(\d+)\s*этаж", context, re.I)
    if m_range:
        a, b = int(m_range.group(1)), int(m_range.group(2))
        for i in range(a, b + 1):
            floors.add(str(i))

    # Отметки уровня чистого пола
    if re.search(r"отм\.?\s*0[.,]000", context, re.I):
        floors.add("1")
    if re.search(r"отм\.?\s*\+?3[.,][0-9]", context, re.I):
        floors.add("2")
    if re.search(r"отм\.?\s*\+?6[.,][0-9]", context, re.I):
        floors.add("3")
    if re.search(r"кровл|чердак", context, re.I):
        floors.add("ROOF")

    # Определение по распределению комнат
    if rooms:
        floor_counts: Dict[str, int] = {}
        for r in rooms:
            fl = infer_room_floor(r)
            if fl:
                floor_counts[fl] = floor_counts.get(fl, 0) + 1

        total_inferred = sum(floor_counts.values())
        if total_inferred >= 5:
            sorted_fl = sorted(floor_counts.items(), key=lambda kv: -kv[1])
            top_fl, top_count = sorted_fl[0]
            if top_count / total_inferred >= 0.70:
                # Поэтажный план конкретного этажа
                floors.add(top_fl)
            else:
                # Мульти-этажный лист (схема всего здания)
                for fl, cnt in sorted_fl:
                    if cnt >= 2:
                        floors.add(fl)
        elif total_inferred > 0:
            for fl in floor_counts:
                floors.add(fl)

    is_diag = is_diagram_sheet(sheet_title, text)
    is_multi = len(floors) > 1 or is_diag
    return floors, is_multi


def build_sheet_descriptors(object_id: str,
                            build_dir: str = "build") -> Dict[Tuple[str, int], SheetDescriptor]:
    """Сборка дескрипторов всех листов объекта из sheets.jsonl, documents.jsonl и plan_rooms.jsonl."""
    obj_dir = os.path.join(build_dir, object_id)
    docs_path = os.path.join(obj_dir, "documents.jsonl")
    sheets_path = os.path.join(obj_dir, "sheets.jsonl")
    rooms_path = os.path.join(obj_dir, "plan_rooms.jsonl")

    docs: Dict[str, Dict[str, Any]] = {}
    if os.path.exists(docs_path):
        with open(docs_path, encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                docs[d["file_id"]] = d

    # Группировка помещений по (file_id, pdf_page_number)
    rooms_by_sheet: Dict[Tuple[str, int], Set[str]] = {}
    marks_by_sheet: Dict[Tuple[str, int], Set[str]] = {}
    if os.path.exists(rooms_path):
        with open(rooms_path, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                key = (r["file_id"], r["pdf_page_number"])
                rooms_by_sheet.setdefault(key, set()).add(r["number"])
                for m in r.get("marks", []):
                    marks_by_sheet.setdefault(key, set()).add(m)

    descriptors: Dict[Tuple[str, int], SheetDescriptor] = {}
    if os.path.exists(sheets_path):
        with open(sheets_path, encoding="utf-8") as f:
            for line in f:
                s = json.loads(line)
                fid = s["file_id"]
                page = s["pdf_page_number"]
                doc = docs.get(fid, {})
                stage = s.get("stage_from_titleblock") or doc.get("stage", "UNKNOWN")
                rel_path = doc.get("relative_path", "")
                doc_code = s.get("document_code")
                title = s.get("sheet_title")
                sheet_no = s.get("document_sheet_number")

                disc = extract_discipline(doc_code, title, rel_path)
                rms = rooms_by_sheet.get((fid, page), set())
                mrks = marks_by_sheet.get((fid, page), set())

                floors, is_multi = extract_floors(title, "", rooms=rms)
                sys_roots = extract_system_roots(title, mrks)
                diag = is_diagram_sheet(title) or (is_multi and len(sys_roots) > 0)

                descriptors[(fid, page)] = SheetDescriptor(
                    file_id=fid,
                    pdf_page_number=page,
                    stage=stage,
                    discipline=disc,
                    document_code=doc_code,
                    sheet_number=sheet_no,
                    sheet_title=title,
                    is_diagram=diag,
                    floors=floors,
                    is_multi_floor=is_multi,
                    system_roots=sys_roots,
                    rooms=rms,
                    relative_path=rel_path,
                )

    return descriptors


def match_sheets(pd_sheet: SheetDescriptor,
                 all_rd_sheets: List[SheetDescriptor]) -> Dict[str, Any]:
    """Подбор соответствующих листов РД для заданного листа ПД (1-to-many отношение).

    Возвращает словарь:
      - status: 'MATCHED' | 'RD_MISSING' | 'NO_CANDIDATES'
      - pd_sheet: дескриптор исходного листа ПД
      - rd_sheets: список подобранных листов РД
      - mapping_by_floor: отображение этаж -> список листов РД
    """
    # 1. Фильтрация кандидатов по дисциплине
    disc_cand = [rd for rd in all_rd_sheets if rd.discipline == pd_sheet.discipline]
    if not disc_cand:
        return {
            "status": "RD_MISSING",
            "pd_sheet": pd_sheet,
            "rd_sheets": [],
            "mapping_by_floor": {},
            "reason": f"В рабочей документации отсутствует раздел {pd_sheet.discipline}",
        }

    # 2. Фильтрация кандидатов по общим корням систем (если определены)
    if pd_sheet.system_roots:
        cand_with_sys = [rd for rd in disc_cand if rd.system_roots & pd_sheet.system_roots]
        if cand_with_sys:
            candidate_pool = cand_with_sys
        else:
            candidate_pool = disc_cand
    else:
        candidate_pool = disc_cand

    # 3. Сопоставление по этажам
    matched: List[SheetDescriptor] = []
    mapping_by_floor: Dict[str, List[SheetDescriptor]] = {}

    target_floors = pd_sheet.floors if pd_sheet.floors else {"1"}
    for fl in target_floors:
        fl_cand = [rd for rd in candidate_pool if fl in rd.floors or not rd.floors]
        if fl_cand:
            mapping_by_floor[fl] = fl_cand
            for rd in fl_cand:
                if rd not in matched:
                    matched.append(rd)

    if not matched:
        return {
            "status": "NO_CANDIDATES",
            "pd_sheet": pd_sheet,
            "rd_sheets": [],
            "mapping_by_floor": {},
            "reason": f"Листы РД для этажей {sorted(target_floors)} не найдены",
        }

    return {
        "status": "MATCHED",
        "pd_sheet": pd_sheet,
        "rd_sheets": matched,
        "mapping_by_floor": mapping_by_floor,
        "reason": None,
    }


def match_room_to_rd_sheet(pd_sheet: SheetDescriptor,
                           room_number: str,
                           rd_sheets: List[SheetDescriptor]) -> Optional[SheetDescriptor]:
    """Для конкретного помещения проектного листа подбирает целевой поэтажный лист РД."""
    room_floor = infer_room_floor(room_number)

    # 1. Приоритет листам, где комната физически найдена в экспликации/плане
    containing = [rd for rd in rd_sheets if room_number in rd.rooms]
    if containing:
        containing.sort(key=lambda rd: (
            not rd.is_diagram,
            bool(rd.system_roots & pd_sheet.system_roots),
            room_floor in rd.floors if room_floor else False,
            len(rd.rooms),
        ), reverse=True)
        return containing[0]

    # 2. Если комната не найдена (например удалена из экспликации в РД),
    # подбираем основной поэтажный план соответствующего этажа
    if room_floor:
        floor_plans = [rd for rd in rd_sheets if room_floor in rd.floors and not rd.is_diagram]
        if floor_plans:
            floor_plans.sort(key=lambda rd: (
                bool(rd.system_roots & pd_sheet.system_roots),
                len(rd.rooms),
            ), reverse=True)
            return floor_plans[0]

        any_floor = [rd for rd in rd_sheets if room_floor in rd.floors]
        if any_floor:
            any_floor.sort(key=lambda rd: (
                bool(rd.system_roots & pd_sheet.system_roots),
                len(rd.rooms),
            ), reverse=True)
            return any_floor[0]

    return rd_sheets[0] if rd_sheets else None


def verify_room_systems(pd_sheet: SheetDescriptor,
                        room: Dict[str, Any],
                        rd_sheet: Optional[SheetDescriptor],
                        rd_room: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Проверка сохранности систем вентиляции/оборудования для помещения.

    Возвращает результат проверки:
      - status: 'OK' | 'VIOLATION' | 'COMPARISON_NOT_POSSIBLE'
      - missing_marks: список отсутствующих марок
      - target_rd_sheet: лист РД, на котором проводилась проверка
    """
    if rd_sheet is None:
        return {
            "status": "COMPARISON_NOT_POSSIBLE",
            "reason": "RD_SHEET_NOT_FOUND",
            "missing_marks": [],
            "target_rd_sheet": None,
        }

    pd_marks = room.get("marks", [])
    if not pd_marks:
        return {
            "status": "OK",
            "missing_marks": [],
            "target_rd_sheet": (rd_sheet.file_id, rd_sheet.pdf_page_number),
        }

    if rd_room is None:
        return {
            "status": "VIOLATION",
            "reason": "ROOM_MISSING_ON_RD_PLAN",
            "missing_marks": pd_marks,
            "target_rd_sheet": (rd_sheet.file_id, rd_sheet.pdf_page_number),
        }

    rd_marks = rd_room.get("marks", [])
    rd_roots = {extract_system_root(m) for m in rd_marks}

    missing = []
    for pm in pd_marks:
        p_root = extract_system_root(pm)
        if p_root not in rd_roots and pm not in rd_marks:
            missing.append(pm)

    if missing:
        return {
            "status": "VIOLATION",
            "reason": "SYSTEM_NOT_ON_RD_PLAN",
            "missing_marks": missing,
            "target_rd_sheet": (rd_sheet.file_id, rd_sheet.pdf_page_number),
        }

    return {
        "status": "OK",
        "missing_marks": [],
        "target_rd_sheet": (rd_sheet.file_id, rd_sheet.pdf_page_number),
    }
