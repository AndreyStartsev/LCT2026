"""Фундамент башенного крана — не конструкция здания (Р-157).

  python tests/test_crane_foundation_157.py

Тексты — со страниц Полярной 16 (ПД КР1 стр. 27 и 34, РД КЖ03 и КЖ04, ИД стр. 170), Тюменской-5
(ПД КР 4.1.1 стр. 19) и Речникова (РД К1-КЖ1 стр. 5), сокращены. До правки у Полярной 16 толщина ростверка
крана 1200 мм шла в KR-058 из раздела «ж. 4» записки и из тома КЖ04 «Ростверк башенного крана», а B35
протокола испытаний ростверка крана в ИД — в доказательства KR-055 «Ростверки».
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import elements, fingerprint, matrix_rules as mr  # noqa: E402

# ПД КР1, стр. 34: хвост раздела о козырьках, раздел о фундаменте крана, начало следующего раздела
KR1_CRANE = (
    "Выполнены из бетона класса В25F75 с армированием отдельными стержнями вязаной арматуры класса А500С и А240. "
    "ж. 4 Фундаменты под отдельно стоящий башенный кран Фундамент под отдельно стоящий башенный кран – свайный. "
    "Сваи сборные железобетонные забивные сечением 350х350 мм длинной 15 м с шагом 2,175 м, с применением "
    "лидерного бурения диаметром 0,2м на глубину 5,13м. Ростверк – монолитная железобетонная плита толщиной "
    "1200 мм, размерами в плане 5,0х5,0 м. Плитный ростверк предусмотрен из бетона класса В35W6F150, арматуры "
    "класса А500С, (низ на отм. -4,650, абс. отм. 141,55). Ростверк выполняется по бетонной подготовке из бетона "
    "В7,5 толщиной 100мм. Для крепления башенного крана к ростверку предусмотрены штатные закладные детали, "
    "имеющие соответствующий сертификат. После окончания строительства фундамент под отдельно стоящий башенный "
    "кран демонтируется. л) Обоснование проектных решений и мероприятий, обеспечивающих: л. 1 Соблюдение "
    "требуемых теплозащитных характеристик ограждающих конструкций")
# ПД КР1, стр. 27: ростверк здания
KR1_BUILDING = (
    "ж. 2 Подземная часть жилых секций Фундаменты зданий – свайные. Сваи сборные железобетонные забивные сечением "
    "350х350 мм длинной 15 м с шагом 1,05 ... 1,25 м, с применением лидерного бурения диаметром 0,2м на глубину "
    "5,13м. Ростверк – монолитная железобетонная плита толщиной 900 мм (низ на отм. -4,400, абс. отм. 141,80) "
    "с гидроизоляцией по распределительной плите. Плитные ростверки выполняются из бетона В35W6F150.")
# РД КЖ03 «Ростверк. Секции 1, 2», стр. 3: в общих указаниях по ошибке — «ростверка башенного крана»
KZH03_NOTES = (
    "ОБЩИЕ УКАЗАНИЯ 1. Настоящий раздел содержит рабочие чертежи плитного ростверка башенного крана. 2. За условную "
    "отметку 0,000 принят уровень чистого пола 1-го этажа, что соответствует абсолютной отметке 146,20. "
    "КОНСТРУКТИВНЫЕ РЕШЕНИЯ Плитный ростверк – монолитная железобетонная плита толщиной 900 мм (низ на отм. -4,400, "
    "абс. отм. 141,800) с гидроизоляцией по распределительной плите.")
# РД КЖ04, стр. 3: в тексте тома о кране ничего, толщина 1200 мм — та же фраза, что в КЖ03
KZH04_NOTES = KZH03_NOTES.replace("900 мм (низ на отм. -4,400, абс. отм. 141,800) с гидроизоляцией по распределительной "
                                  "плите", "1200 мм (низ на отм. -4,650, абс. отм. 141,550) по бетонной подготовке")
TITLE_TAIL = (" 130-1222-ОК-1/Н-КЖ04 СтройПроект Регистрационный номер в государственном реестре саморегулируемых "
              "организаций: П-182-006318056609-1647 от 06.07.2020 общество с ограниченной ответственностью")
TITLE_HEAD = ("Согласовано Инв. № подл. Подпись и дата Взам. инв. № 2024 РАБОЧАЯ ДОКУМЕНТАЦИЯ «Жилой дом с инженерными "
              "сетями и благоустройством территории (со сносом жилого здания по адресу: ул. Полярная д.16, корп.1)» "
              "(Северо-Восточный административный округ) ")
KZH04_TITLE = TITLE_HEAD + "Ростверк башенного крана" + TITLE_TAIL
KZH03_TITLE = TITLE_HEAD + "Ростверк. Секции1,2" + TITLE_TAIL.replace("КЖ04", "КЖ03")
# перечень томов в общих данных КЖ03, КЖ05, КЖ9.x — на длинной странице
VOLUME_LIST = ("130-1222-ОК-1/Н-КЖ05 Секции 1,2. Вертикальные железобетонные конструкции ниже отметки -0,150 "
               "130-1222-ОК-1/Н-КЖ04 Ростверк башенного крана 130-1222-ОК-1/Н-КЖ03 Ростверк. Секции 1, 2 "
               "130-1222-ОК-1/Н-КЖ02 Свайное поле ")
# ИД Полярной 16, стр. 170: протокол испытаний бетона ростверка крана
ID_PROTOCOL = ("Результаты испытаний к протоколу № 72 от 09.01.2025 г. Плитный ростверк Башенного крана в/о 12-15/А-А "
               "Ha OTM. -4,650 3980 | 3780 1 | Участок 1 3760 | 4000 30,1 27,2 78 Заключение: Фактическая прочность "
               "бетона в испытанных конструкциях, в промежуточном возрасте, составляет от 73% до 85% от проектного "
               "класса бетона B35. Примечание: Лаборатория не несет ответственности за данные в протоколе")
# Тюменская-5, ПД КР 4.1.1, стр. 19: заголовок без номера, дальше — раздел о надземной части
TYUMEN = (
    "межтрубное пространство футляра заполняется цементно-песчаным раствором. Фундаментная плита под установку "
    "крана Башенный кран, установленный на опоре 6,0х6,0м на монолитной железобетонной фундаментной плите. "
    "Фундамент башенного крана выполняется размерами в плане 7500х7500 мм, высотой 500 мм. Материал "
    "железобетонных конструкций запроектирован из бетона B25 W8 F200 по ГОСТ 26633-91*. Абсолютная отметка низа "
    "фундамента 134,950. ж') описание конструктивных и технических решений надземной части объекта капитального "
    "строительства Наружные стены первого этажа выполнены из бетона В25 W4 F100 толщиной 250мм.")
# Речников, РД К1-КЖ1 стр. 5: примечания о плите под кран и условные обозначения плиты здания
RECHNIKOV = (
    "7. Фундаментную плиту под кран ФПмк1 см. лист 20; 8. Монтаж опорных стоек башенного крана произвести до "
    "начала бетонирования фундаментной плиты. 9. Информацию по монтажу анкеров см. в инструкции по монтажу "
    "и эксплуатации башенного крана \"POTAIN\" для ФПмк1; 10. Гидроизоляция подземных конструкций разработана "
    "в отдельном проекте. Условные обозначения: +0.000 - Отметка верха и толщина фундаментной плиты t=900 - "
    "Рабочий шов бетонирования")


def check(name, condition, detail=""):
    mark = "ок  " if condition else "СБОЙ"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    return bool(condition)


def rule(code):
    for path in mr.QUEUES.values():
        got = mr.load_rules(path)["parameters"].get(code)
        if got:
            return got
    raise KeyError(code)


def values(code, text, doc=None, where=None):
    got = mr.extract(rule(code), text, doc=doc)
    return sorted({c["value"] for c in got if where is None or c.get("location") == where})


def test_pd_section():
    """ПД: раздел о фундаменте крана — от заголовка «ж. 4 …» до следующего пункта «л)»."""
    spans = elements.crane_sections(KR1_CRANE)
    ok = check("один раздел: от «Фундаменты под…» до «л)»",
               len(spans) == 1 and KR1_CRANE[spans[0][0]:].startswith("Фундаменты под отдельно")
               and KR1_CRANE[spans[0][1]:].lstrip().startswith("л) Обоснование"), str(spans))
    ok &= check("толщина 1200 мм ростверка крана — не толщина плиты", values("KR-058", KR1_CRANE) == [],
                str(values("KR-058", KR1_CRANE)))
    ok &= check("класс B35 ростверка крана не идёт в ростверки",
                values("KR-055", KR1_CRANE, where="Ростверки") == [], str(mr.extract(rule("KR-055"), KR1_CRANE)))
    ok &= check("класс арматуры ростверка крана тоже", values("KR-057", KR1_CRANE, where="Ростверки") == [])
    ok &= check("ростверк здания в том же томе: 900 мм и B35",
                900 in values("KR-058", KR1_BUILDING) and values("KR-055", KR1_BUILDING, where="Ростверки") == [35.0],
                f"{values('KR-058', KR1_BUILDING)} {values('KR-055', KR1_BUILDING)}")
    ok &= check("и раздел о кране рядом с ним ростверк здания не трогает",
                900 in values("KR-058", KR1_BUILDING + " " + KR1_CRANE)
                and 1200 not in values("KR-058", KR1_BUILDING + " " + KR1_CRANE))
    return ok


def test_not_a_section():
    """Название фундамента крана посреди фразы или в примечании раздела не открывает."""
    ok = check("общие указания КЖ03 «…чертежи плитного ростверка башенного крана» — том о ростверке здания",
               elements.crane_sections(KZH03_NOTES) == [] and 900 in values("KR-058", KZH03_NOTES),
               str(values("KR-058", KZH03_NOTES)))
    ok &= check("примечания Речникова «7. Фундаментную плиту под кран ФПмк1 см. лист 20;» — плита здания 900 мм",
                elements.crane_sections(RECHNIKOV) == [] and values("KR-058", RECHNIKOV) == [900],
                str(values("KR-058", RECHNIKOV)))
    spans = elements.crane_sections(TYUMEN)
    ok &= check("заголовок без номера (Тюменская): раздел кончается на «ж')»",
                len(spans) == 1 and TYUMEN[spans[0][1]:].lstrip().startswith("ж')"), str(spans))
    walls = values("KR-055", TYUMEN, where="Вертикальные конструкции надземной части")
    ok &= check("класс стен надземной части после раздела о кране остаётся", walls == [25.0], str(walls))
    ok &= check("страница без крана не меняется", elements.without_crane_sections(KR1_BUILDING) == KR1_BUILDING)
    return ok


def test_crane_mentions():
    """«Ростверк башенного крана», «фундаментная плита под башенный кран» — не упоминание элемента здания."""
    ok = check("строка протокола «Плитный ростверк Башенного крана»",
               elements.element_mentions("Плитный ростверк Башенного крана в/о 12-15/А-А") == [])
    ok &= check("«Контур фундаментной плиты под башенный кран»",
                elements.element_mentions("Контур фундаментной плиты под башенный кран -3,820") == [])
    ok &= check("«Фундаментная плита под установку крана»",
                elements.element_mentions("Фундаментная плита под установку крана") == [])
    got = [m[2] for m in elements.element_mentions("Плитный ростверк секция 1 Ростверк – монолитная плита")]
    ok &= check("ростверк здания — упоминание", got == ["Ростверки", "Ростверки"], str(got))
    built = {"stage": "ID", "relative_path": "ИД/singleFile.pdf"}
    got = mr.extract(rule("KR-055"), ID_PROTOCOL, doc=built)
    ok &= check("B35 протокола испытаний ростверка крана не идёт в ростверки", got == [], str(got))
    building = ID_PROTOCOL.replace("Плитный ростверк Башенного крана в/о 12-15/А-А", "Плитный ростверк секции 1 в/о 1-13/А-И")
    got = sorted((c["location"], c["binding"]) for c in mr.extract(rule("KR-055"), building, doc=built))
    ok &= check("а протокол ростверка здания — идёт: строкой протокола и привязкой по листу",
                got == [("Ростверки", "CLAUSE"), ("Ростверки", "SHEET")], str(got))
    text = "Ростверк – монолитная плита под отдельно стоящий башенный кран, из бетона класса В35W6F150."
    ok &= check("класс рядом с «под отдельно стоящий башенный кран» отбрасывается, как рядом с «под кран»",
                elements.concrete_classes(text) == []
                and elements.concrete_classes("Ростверк – монолитная плита под кран, бетон класса В30.") == [],
                str(elements.concrete_classes(text)))
    got = [(c["location"], c["raw"]) for c in
           elements.concrete_classes("Ростверк – монолитная железобетонная плита из бетона класса В35.")]
    ok &= check("без крана — ростверк B35", got == [("Ростверки", "B35")], str(got))
    return ok


def test_crane_volume():
    """РД: том о фундаменте крана — по названию на титульном листе."""
    ok = check("титул КЖ04 «Ростверк башенного крана»", elements.crane_volume([KZH04_TITLE]))
    ok &= check("титул КЖ03 «Ростверк. Секции 1,2» — нет", not elements.crane_volume([KZH03_TITLE]))
    long_page = (KZH03_NOTES + " ") * 4 + VOLUME_LIST
    ok &= check("перечень томов на длинной странице — нет", not elements.crane_volume([long_page]),
                str(len(long_page)))
    ok &= check("пустые страницы — нет", not elements.crane_volume([None, ""]))
    return ok


RULES = {"classes": {}, "parameters": {
    "PZ-001": {"kind": "area", "labels": ["площадь застройки"], "rule": "first", "implemented": True, "code": "PZ-001"},
}}


def test_document_candidates():
    """Кандидаты тома крана: правила по элементам — пусто, остальные правила — как были; с кешем и без."""
    rules = {"classes": RULES["classes"], "parameters": dict(RULES["parameters"], **{"KR-058": rule("KR-058")})}
    active = rules["parameters"]
    saved = {"CACHE": mr.CACHE, "page_texts_src": mr.page_texts_src, "vlm_digest": mr.vlm_digest}
    base = tempfile.mkdtemp()
    ok = True
    try:
        mr.CACHE = base
        mr.vlm_digest = lambda doc, out=None, provisional=False: None
        body = KZH04_NOTES + " Площадь застройки 1200,5 м2."
        for title, sha, want_plate in ((KZH04_TITLE, "cd" * 32, False), (KZH03_TITLE, "ef" * 32, True)):
            pages = [(1, title, "LAYER"), (2, title, "LAYER"), (3, body, "LAYER")]
            mr.page_texts_src = lambda doc, root, scans=True, pages=pages: iter(pages)
            doc = {"sha256": sha, "relative_path": "рд/КЖ.pdf", "stage": "RD", "file_id": "F1"}
            for use_cache in (True, True, False):
                got, read = mr.document_candidates(doc, "", active, rules, use_cache=use_cache)
                codes = {code for _p, _s, by_code in got for code in by_code}
                name = "КЖ04" if not want_plate else "КЖ03"
                ok &= check(f"{name}, кеш {use_cache}: KR-058 {'есть' if want_plate else 'нет'}, площадь есть",
                            ("KR-058" in codes) == want_plate and "PZ-001" in codes and read == 3, str(codes))
    finally:
        for k, v in saved.items():
            setattr(mr, k, v)
        shutil.rmtree(base, ignore_errors=True)
    return ok


def test_fingerprint():
    """Правка elements.py старит кеш только правил, чей разбор его читает: условие `in ELEMENT_KINDS` — ветка вида."""
    tmp = tempfile.mkdtemp()
    saved = fingerprint.PIPELINE
    try:
        for name in os.listdir(os.path.join(ROOT, "pipeline")):
            if name.endswith(".py"):
                shutil.copy(os.path.join(ROOT, "pipeline", name), tmp)

        def digests():
            fingerprint._parsed.cache_clear()
            fingerprint.module_digest.cache_clear()
            return fingerprint.kind_digests("matrix_rules", "extract", ("_extract_document",),
                                            {"ROOM_KINDS": mr.ROOM_KINDS, "ELEMENT_KINDS": mr.ELEMENT_KINDS})
        fingerprint.PIPELINE = tmp
        before = digests()
        with open(os.path.join(tmp, "elements.py"), "a", encoding="utf-8") as f:
            f.write("\n\ndef _probe():\n    return 1\n")
        after = digests()
        changed = {k for k in before if before[k] != after[k]}
        ok = check("все виды по элементам получили новый отпечаток", mr.ELEMENT_KINDS <= changed, str(changed))
        ok &= check("площадь, объём и вид без своей ветки — нет",
                    not changed & {"area", "volume", "count", "*", "class", "vlm_value"}, str(changed))
    finally:
        fingerprint.PIPELINE = saved
        fingerprint._parsed.cache_clear()
        fingerprint.module_digest.cache_clear()
        shutil.rmtree(tmp, ignore_errors=True)
    return ok


if __name__ == "__main__":
    ok = True
    for fn in (test_pd_section, test_not_a_section, test_crane_mentions, test_crane_volume, test_document_candidates,
               test_fingerprint):
        print(fn.__name__)
        ok &= fn()
    print("OK" if ok else "ЕСТЬ СБОИ")
    sys.exit(0 if ok else 1)
