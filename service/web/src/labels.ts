// Подписи для кодов API. Коды остаются в интерфейсе моноширинным шрифтом: по ним ищут в журнале.

export const PROCESS_STATUS: Record<string, string> = {
  PENDING: "Документы загружены",
  PARSING: "Идёт обработка",
  READY: "Протокол готов",
  VERIFYING: "Идёт верификация",
  COMPLETED: "Верификация завершена",
  FINALIZED: "Протокол финализирован",
};

export const STEP: Record<string, string> = {
  parse: "Разбор документов",
  compare: "Сравнение по Матрице",
  protocol: "Сборка протокола",
};

export const SCENARIO: Record<string, string> = {
  FULL: "ПД · РД · ИД",
  PD_RD_ONLY: "ПД · РД",
  PD_ID_ONLY: "ПД · ИД",
  RD_ID_ONLY: "РД · ИД",
  SINGLE_ONLY: "одна стадия",
  PARTIALLY_LOADED: "загружено частично",
};

export const STAGE: Record<string, string> = { PD: "ПД", RD: "РД", ID: "ИД" };

export const STAGE_NAME: Record<string, string> = {
  PD: "Проектная документация",
  RD: "Рабочая документация",
  ID: "Исполнительная документация",
};

/** Стадии и разделы для правки руками (#39); коды — из pipeline/config.py. */
export const DOC_STAGES: { code: string; label: string }[] = [
  { code: "PD", label: "Проектная" },
  { code: "RD", label: "Рабочая" },
  { code: "ID", label: "Исполнительная" },
  { code: "RD_ID_MIXED", label: "Рабочая и исполнительная" },
];

export const DOC_SECTIONS: { code: string; label: string }[] = [
  { code: "PZ", label: "Пояснительная записка" },
  { code: "GP", label: "Генплан, ПЗУ" },
  { code: "AR", label: "Архитектурные решения" },
  { code: "KR", label: "Конструктивные решения" },
  { code: "OV", label: "Отопление и вентиляция" },
  { code: "VK", label: "Водоснабжение и канализация" },
  { code: "EOM", label: "Электроснабжение" },
  { code: "SS", label: "Слаботочные системы" },
  { code: "PB", label: "Пожарная безопасность" },
  { code: "POS", label: "Организация строительства" },
  { code: "OTHER", label: "Не определён" },
];

export const UPLOAD_STATE: Record<string, string> = {
  UPLOADED: "загружена",
  PARTIAL: "загружена частично",
  MISSING: "не загружена",
};

export const LABEL: Record<string, string> = {
  VIOLATION_PRESENT: "Расхождение",
  NO_VIOLATION: "Расхождения нет",
  MISSING_DOCUMENT: "Нет документа",
  COMPARISON_IMPOSSIBLE: "Сравнение невозможно",
};

export const COMPARISON: Record<string, string> = {
  VALUE_MISMATCH: "Значения различаются",
  VALUE_DECREASE: "Значение уменьшено",
  VALUE_INCREASE: "Значение увеличено",
  EQUAL_PD_RD: "Значения совпадают",
  EQUAL_AFTER_DECIMAL_NORMALIZATION: "Совпадают после приведения записи",
  CLASS_DOWNGRADE: "Класс понижен",
  DIMENSION_REDUCED: "Размер уменьшен",
  NON_TRIGGERING_DIFFERENCE_NO_DECREASE: "Разница без ухудшения",
  EQUAL_ALL_AVAILABLE_STAGES: "Совпадают все стадии",
  ELEMENT_ABSENT: "Элемент проекта отсутствует",
  CONFIGURATION_CHANGED: "Конфигурация изменена",
};

export const LOCATION_TYPE: Record<string, string> = {
  ROOM: "помещение",
  SITE: "участок",
  OBJECT: "объект",
  CONSTRUCTION_ELEMENT: "конструктивный элемент",
  AXES: "оси",
  LEVEL: "отметка",
};

export const VERDICT: Record<string, { glyph: string; word: string; tone: "confirm" | "reject" | "clarify" }> = {
  CONFIRMED_VIOLATION: { glyph: "✓", word: "Нарушение подтверждено", tone: "confirm" },
  NEGATIVE_VERIFIED: { glyph: "✗", word: "Отклонено", tone: "reject" },
  CLARIFICATION_REQUIRED: { glyph: "?", word: "Требует уточнения", tone: "clarify" },
};

/**
 * Уверенность в выводе (#80). Процента нет: уровень выводится из признаков записи — чем прочитано
 * значение, к чему привязано, сколько страниц его подтверждают — и показывается вместе с ними.
 */
export const CONFIDENCE: Record<string, { word: string }> = {
  HIGH: { word: "высокая" },
  MEDIUM: { word: "средняя" },
  LOW: { word: "низкая" },
};

/**
 * Решение специалиста о виде записей (#129, Р-86, Р-108): оно о виде расхождения, а не об одной
 * записи (Р-116). Слово — то же, что в пояснении записи (pipeline/specialist.py, VERDICT).
 */
export const SPECIALIST: Record<string, { word: string; glyph: string; tone: "confirm" | "reject" | "clarify" }> = {
  violation: { word: "нарушение", glyph: "✓", tone: "confirm" },
  need_info: { word: "нужны данные", glyph: "?", tone: "clarify" },
  no_violation: { word: "не нарушение", glyph: "✗", tone: "reject" },
  hypothesis: { word: "гипотеза", glyph: "~", tone: "clarify" },
  // специалист предложил не показывать; показываются в конце таблицы гипотез (решение пользователя 26.09)
  drop: { word: "низкий приоритет", glyph: "–", tone: "reject" },
};

// Коды причин отклонения из ТЗ, раздел 9.3 (contracts/enums.json)
export const REASONS: { code: string; label: string }[] = [
  { code: "WRONG_REVISION", label: "Редакция выбрана неверно" },
  { code: "APPROVED_CHANGE", label: "Согласованное изменение" },
  { code: "OCR_ERROR", label: "Ошибка распознавания" },
  { code: "LINKING_ERROR", label: "Ошибка привязки" },
  { code: "NOT_APPLICABLE", label: "Параметр неприменим" },
];

/**
 * Статус утверждения документа (ТЗ 9.3: инспектор видит его в карточке). В реестре он пока
 * всегда UNKNOWN — извлечение штампа утверждения это #10 — и тогда карточка его не показывает.
 */
export const APPROVAL: Record<string, string> = {
  APPROVED: "утверждён",
  NOT_APPROVED: "не утверждён",
  SUPERSEDED: "заменён",
  UNKNOWN: "утверждение неизвестно",
};

/** Чем прочитана страница. На сканах текст даёт распознавание, и по нему принимаются решения (#52). */
export const TEXT_SOURCE: Record<string, string> = {
  TEXT_LAYER: "текстовый слой",
  TESSERACT: "распознано",
  UNION: "слой и распознавание",
  MODEL: "модель",
  NONE: "не прочитано",
};

/**
 * Способ чтения объекта (#54). Выбирается при загрузке: коротко — в списке, подробно —
 * подсказкой под ним, потому что выбор меняет и время разбора, и то, что увидят правила.
 */
export const READING_MODE: Record<string, string> = {
  layer: "только текстовый слой",
  tesseract: "слой и распознавание сканов",
  model: "слой, распознавание и модель на страницах без текста",
};

export const READING_MODE_HINT: Record<string, string> = {
  layer: "Самый быстрый разбор. На сканах правила молчат: текста на странице для них нет.",
  tesseract: "Сканы распознаются, чертежи без текстового слоя остаются без текста. Модель читает только исполнительные схемы и отдельные значения на чертежах, нужные проверкам.",
  model: "Способ по умолчанию. Модель дочитывает только сканы без текста и чертежи без текстового слоя, остальное читается слоем и распознаванием.",
};

/**
 * Предупреждение, когда модель чтения подключена во внешнем сервисе (признак external_model
 * в /api/v1/health). От способа чтения не зависит: исполнительные схемы и проход по чертежам идут
 * к модели при любом способе, кроме «только слой».
 */
export const EXTERNAL_MODEL_NOTICE = {
  title: "Новый комплект прочитает внешняя модель.",
  text:
    "Этот стенд подключён к модели во внешнем сервисе. Загрузка и дозагрузка отправляют страницы " +
    "комплекта на чтение в неё, перечитывание и пересборка — страницы и листы, по которым ответа модели " +
    "ещё нет. Объекты, которые уже есть на стенде, разобраны заранее, их просмотр ничего наружу не " +
    "отправляет. Если вы не согласны обрабатывать документы внешними моделями, загружайте только " +
    "тестовый пакет, предназначенный для демонстрации.",
};

/** То же коротко — в подтверждении перечитывания, пересборки и нового разбора. */
export const EXTERNAL_MODEL_RERUN =
  "Стенд подключён к модели во внешнем сервисе: страницы и листы без готового ответа модели уйдут на чтение в неё.";

/** Вид страницы по разбору: от него зависит, включалось ли распознавание. */
export const PAGE_KIND: Record<string, string> = {
  TEXT: "текст",
  DENSE_TEXT: "плотный текст",
  DRAWING: "чертёж",
  SCAN_SPARSE: "скан, текста мало",
  SCAN_NO_TEXT: "скан без текста",
};

export const HIGHLIGHT_SOURCE: Record<string, string> = {
  VALUE: "зона доказательства: найдена по значению",
  ROWS: "зона доказательства: строки ведомости, из которых сложено значение",
  LOCATION: "зона доказательства: найдена по номеру помещения или оси",
  FINDING: "зона доказательства: строка таблицы или фрагмент чертежа",
  REVISION: "места, где лист изменился между редакциями",
};

/**
 * Подпись под страницей: чем найдено место или почему рамки нет. Доказательство уровня
 * страницы — «в таблице систем помещение 140 не названо» — рамки не имеет по существу:
 * обводить нечего, и это не промах подсветки (задача #50).
 */
export function highlightNote(evidence: { highlight_source?: string | null; localization?: string | null }): string {
  if (evidence.highlight_source) return HIGHLIGHT_SOURCE[evidence.highlight_source] ?? evidence.highlight_source;
  if (evidence.localization === "PAGE_LEVEL") return "доказательство о странице целиком: обводить нечего";
  if (evidence.localization === "DOCUMENT_LEVEL") return "доказательство о документе целиком: обводить нечего";
  return "зона доказательства на странице не определена";
}

/**
 * Что значит код правила. Расшифровки взяты из самого проекта: у свободного поиска —
 * из правил, которые эти коды и ставят (`pipeline/room_explications.py`, `free_search.py`,
 * `acts_check.py`), у Матрицы — из каталога 132 параметров, где у кода есть раздел ПД
 * (`docs/extracted/parameter_catalog_132.jsonl`). Того, чего в проекте нет, здесь не
 * выдумываем: раздел называется так же, как в каталоге.
 */
const FREE_CODE_HINT: Record<string, string> = {
  "FREE-AR-ROOM-MISSING": "Помещение проекта не найдено в экспликациях рабочей документации",
  "FREE-AR-ROOM-AREA": "Площадь помещения в рабочей документации меньше проектной",
  "FREE-PB-ROOM-CATEGORY": "Категория помещения по пожарной опасности изменена между стадиями",
  "FREE-ID-001": "Материал акта освидетельствования не назван на листе рабочей документации",
  "FREE-KR-002": "Отклонения по исполнительной схеме больше допусков, объявленных на том же листе",
  "FREE-REV-UNMARKED":
    "Лист рабочей документации изменён в новой редакции, а номера изменения нет ни в штампе листа, " +
    "ни в ведомости рабочих чертежей",
};

/**
 * Сверка исполнительной схемы с допусками того же листа (FREE-KR-002): стороны карточки — допуск
 * и отклонение с одного листа ИД. Подсказка к стороне допуска.
 */
export const SHEET_TOLERANCE_SIDES =
  "Допуск и отклонение взяты с одного листа исполнительной схемы: из таблицы допустимых отклонений " +
  "и таблицы замеров. Проект и рабочая документация в этой проверке не участвуют.";

/**
 * Где искать согласованное изменение — строка под листом. ТЗ 9.2 подтверждает нарушение только после
 * проверки, что согласованного изменения нет. У этих проверок отступление обычно согласуют прямо
 * в исполнительной документации, а найти такое согласование система не может, поэтому строка стоит
 * у каждой их записи.
 */
export const APPROVAL_HINT: Record<string, { line: string; tip: string }> = {
  // согласование на схеме — часто рукописная отметка проектировщика, распознавание рукописи не читает
  "FREE-KR-002": {
    line: "Отступление могли согласовать с проектировщиком: отметка бывает на самом листе, часто от руки у штампа",
    tip:
      "Отметка на схеме сама по себе рабочую документацию не меняет. Если согласование оформлено изменением РД, " +
      "запись в кандидатах отклоните с причиной «Согласованное изменение» и назовите изменение в комментарии.",
  },
  // замену материала согласуют письмом проектировщика или изменением РД, ссылку на них дают в акте
  "FREE-ID-001": {
    line: "Замену материала могли согласовать с проектировщиком: ссылка на согласование бывает в акте или в приложениях к нему",
    tip:
      "Если замена оформлена документом проектировщика — изменением РД или письмом о согласовании замены, — запись " +
      "в кандидатах отклоните с причиной «Согласованное изменение» и назовите документ в комментарии.",
  },
};

/**
 * Виды свободного поиска для страницы правил эксперта (Р-134). Свободный поиск — правила в коде
 * конвейера, а не в файлах правил, поэтому перечень здесь; названия — те, что эти правила ставят
 * записям (`pipeline/room_explications.py`, `apartment_areas.py`, `free_search.py`, `tolerances.py`,
 * `steel.py`, `acts_check.py`, `aosr_text.py`, `revision_diff.py`). Решения специалиста по видам
 * приходят с правилами воркера.
 */
export const FREE_SEARCH_KINDS: { code: string; title: string }[] = [
  { code: "FREE-AR-ROOM-MISSING", title: "Помещение проекта не найдено в экспликациях рабочей документации" },
  { code: "FREE-AR-ROOM-AREA", title: "Площадь помещения в рабочей документации меньше проектной" },
  { code: "FREE-AR-ROOM-PURPOSE", title: "Назначение помещений этажа изменено в рабочей документации" },
  { code: "FREE-PB-ROOM-CATEGORY", title: "Категория помещения по пожарной опасности изменена между стадиями" },
  { code: "FREE-AR-RD-NOT-UPDATED", title: "Рабочая документация частично не обновлена после корректировки проекта" },
  { code: "FREE-AR-FLAT-AREA", title: "Площади одинаковых квартир в рабочей документации отличаются от проектных" },
  ...["AR", "KR", "OV", "VK", "EOM"].map((section) => ({
    code: `FREE-${section}-DESIGN-ELEMENT`,
    title: `Проект предусматривает для помещений элемент раздела «${
      DOC_SECTIONS.find((s) => s.code === section)?.label ?? section
    }», в рабочей документации он не назван`,
  })),
  { code: "FREE-KR-002", title: "Превышение допусков геометрических параметров по исполнительной схеме" },
  { code: "FREE-KR-003", title: "Понижение прокатного профиля распорной системы между стадиями" },
  { code: "FREE-ID-001", title: "Материал акта освидетельствования не назван на листе рабочей документации" },
  { code: "FREE-ID-002", title: "Номер акта в имени файла не совпадает с номером в документе" },
  { code: "FREE-REV-UNMARKED", title: "Лист изменён в новой редакции без отметки об изменении в штампе и ведомости" },
];

/**
 * Тип правила на странице правил (#222): где живёт разбор значения. От типа зависит и песочница (#223):
 * у паттерна меняются шаблоны и порог, у кода и модели — только порог и допуск.
 */
export const ENGINE: Record<string, { word: string; hint: string }> = {
  pattern: {
    word: "паттерн",
    hint: "Значение ищут подписи и шаблоны из файла правила. В песочнице меняются подписи, исключения и порог",
  },
  code: {
    word: "код",
    hint: "Разбор значения написан в коде сервиса. В песочнице такие правила не прогоняются — код в ней не меняют; как правило решило на объекте, показывает трасса",
  },
  llm: {
    word: "LLM",
    hint: "Значение с чертежей читает модель по вопросу из правила. В песочнице меняются только порог и допуск, ответы модели берутся уже полученные",
  },
};

/**
 * Сравнение редакций (#81): отмечено ли изменение листа. Слово «облако» здесь не
 * используется намеренно: на экране так называется зона доказательства на странице.
 */
export const REGISTRATION: Record<string, { label: string; hint: string }> = {
  REGISTERED: { label: "отмечено", hint: "номер нового изменения стоит в штампе листа или у листа в ведомости" },
  UNREGISTERED: {
    label: "без отметки",
    hint: "содержание листа изменилось, а номера нового изменения нет ни в штампе листа, ни в ведомости",
  },
  NOT_NEEDED: {
    label: "не нужна",
    hint: "содержание листа то же: изменились только дата выдачи, подписи или перенос строк, либо текст сдвинулся между страницами",
  },
  UNKNOWN: { label: "не определено", hint: "ответа нет: номер листа не определён или лист не удалось сравнить по месту" },
};

/** Место файла в цепочке редакций (#10), как его показать инспектору. */
export const REVISION_LABEL: Record<string, string> = {
  CURRENT: "актуальная",
  SUPERSEDED: "устаревшая",
  DUPLICATE: "дубль",
  CLARIFICATION_REQUIRED: "требует уточнения",
};

/** Что стало со страницей между редакциями. */
export const PAGE_CHANGE: Record<string, string> = {
  CHANGED: "изменена",
  ADDED: "добавлена",
  REMOVED: "удалена",
  UNREADABLE: "слой не читается",
};

/** Как лист удалось сравнить по месту. Другой формат и перекомпоновку называет само описание
 * изменения (`what`), здесь — только то, чего в нём нет. */
export const LAYOUT_NOTE: Record<string, string> = {
  SHIFTED: "лист или его части сдвинуты — сдвиг учтён",
};

/** Разделы проектной документации по коду параметра: как в каталоге Матрицы. */
export const MATRIX_SECTION: Record<string, string> = {
  PZ: "раздел 1, ПЗ",
  SPZU: "раздел 2, СПЗУ",
  AR: "раздел 3, АР",
  KR: "раздел 4, КР",
  IOS1: "раздел 5, ИОС1",
  IOS2: "раздел 5, ИОС2",
  IOS3: "раздел 5, ИОС3",
  IOS4: "раздел 5, ИОС4",
  IOS5: "раздел 5, ИОС5",
  POS: "раздел 6, ПОС",
  POD: "раздел 7, ПОД",
  OOS: "раздел 8, ООС",
  PPM: "раздел 9, ППМ",
  ODI: "раздел 10, ОДИ",
  ZU: "раздел 11, ЗУ",
  SM: "раздел 12, СМ",
};

/** Разделы Матрицы в её порядке: ключ кода и короткое имя («KR» — «КР»). */
export const MATRIX_SECTIONS: { key: string; short: string; title: string }[] = Object.entries(MATRIX_SECTION).map(
  ([key, title]) => ({ key, short: title.split(", ").pop() ?? key, title }),
);

export function ruleCodeHint(code: string | null | undefined): string {
  if (!code) return "Запись вне Матрицы 132 параметров: правило свободного поиска";
  if (code.startsWith("FREE-")) {
    const known = FREE_CODE_HINT[code];
    const element = /^FREE-(.+)-DESIGN-ELEMENT$/.exec(code);
    // раздел в коде записан латиницей (OV, AR): называем его так же, как на экране файлов
    const section = element ? DOC_SECTIONS.find((s) => s.code === element[1])?.label ?? element[1] : "";
    const what = known
      ? known
      : element
        ? `Проект предусматривает элемент раздела «${section}», в рабочей документации он не назван`
        : "Расхождение, найденное вне Матрицы 132 параметров";
    return `Свободный поиск. ${what}. В итоги нарушений запись попадает только после перевода в кандидаты`;
  }
  const section = MATRIX_SECTION[code.split("-")[0]];
  return (
    // номер параметра в Матрице — число в самом коде (AR-078 — параметр № 78): отдельно не пишем
    `Код параметра Матрицы${section ? `: ${section}` : ""}` +
    ". Проверка идёт по триггеру каталога: что сравнивается и какое отклонение считается нарушением"
  );
}

/** Вес критичности: без цвета, линией, как в макете. */
export function criticalityWeight(criticality: string | null): "high" | "mid" | null {
  if (!criticality) return null;
  if (criticality.startsWith("Критическое")) return "high";
  if (criticality.startsWith("Существенное")) return "mid";
  return null;
}

export function bytes(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} ГБ`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} МБ`;
  if (n >= 1024) return `${Math.round(n / 1024)} КБ`;
  return `${n} Б`;
}

/** Длительность разбора словами: секунды у короткого объекта, часы у большого (#54). */
export function duration(seconds: number): string {
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)} ч`;
  if (seconds >= 60) return `${Math.round(seconds / 60)} мин`;
  return `${Math.round(seconds)} с`;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
}

const AUDIT_ACTION: Record<string, string> = {
  DOCUMENTS_UPLOADED: "Загружен пакет документов",
  PROCESSING_STARTED: "Разбор запущен",
  PROCESSING_FAILED: "Обработка остановлена",
  PROTOCOL_CREATED: "Протокол сформирован",
  PROTOCOL_FINALIZED: "Протокол финализирован",
  PROTOCOL_UNFINALIZED: "Финализация отменена",
  FINDING_CONFIRM: "Нарушение подтверждено",
  FINDING_REJECT: "Кандидат отклонён",
  FINDING_CLARIFY: "Отправлено на уточнение",
  FINDING_RESET: "Решение отменено",
  FINDING_SPLIT: "Запись разделена по локациям",
  // те же слова, что в сообщении инспектору после решения
  FINDING_PROMOTE: "Гипотеза взята в кандидаты",
  FINDING_DISPUTE: "Запись возвращена в кандидаты: автоматическая проверка оспорена",
  FILE_STAGE_SET: "Стадия или раздел файла изменены вручную",
  FILE_REVISION_SET: "Актуальная редакция выбрана вручную",
  IAIS_SYNCED: "Протокол передан в ИАИС «РиН»",
  IAIS_RETRY_SCHEDULED: "Передача в ИАИС «РиН» не удалась, назначен повтор",
  IAIS_SYNC_FAILED: "Протокол не передан в ИАИС «РиН»: повторы исчерпаны",
  IAIS_REJECTED: "ИАИС «РиН» отклонила протокол",
  IAIS_RETRY_REQUESTED: "Передача в ИАИС «РиН» поставлена заново",
  OBJECT_DELETE: "Объект удалён",
  DATASET_RELEASED: "Выпущена версия набора примеров",
  DATASET_WITHDRAW: "Версия набора примеров отозвана",
};

/** Передача в ИАИС «РиН» в момент финализации. */
const IAIS_AT_FINALIZE: Record<string, string> = {
  PENDING_SYNC: "передача в ИАИС «РиН» поставлена в очередь",
  NOT_CONFIGURED: "передача в ИАИС «РиН» не настроена",
};

const STAGE_WORD: Record<string, string> = Object.fromEntries(DOC_STAGES.map((s) => [s.code, s.label.toLowerCase()]));
const SECTION_WORD: Record<string, string> = Object.fromEntries(DOC_SECTIONS.map((s) => [s.code, s.label]));

/** Строка журнала аудита по-русски; неизвестное действие показывается кодом и деталями как есть. */
export function auditLine(action: string, d: Record<string, unknown>): { title: string; detail: string } {
  const title = AUDIT_ACTION[action] ?? action;
  const s = (v: unknown) => (v === null || v === undefined ? "" : String(v));
  const obj = (v: unknown) => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
  const file = s(d.relative_path).split("/").pop() || s(d.file_id);
  // передача в ИАИС «РиН»: версия протокола, номер попытки и ответ внешней системы, как он записан
  const iais = () =>
    [d.protocol_version != null && `версия протокола ${s(d.protocol_version)}`, d.attempt != null && `попытка ${s(d.attempt)}`]
      .filter(Boolean)
      .join(", ") + (d.error ? `: ${s(d.error)}` : "");
  switch (action) {
    case "DOCUMENTS_UPLOADED":
      return {
        title,
        detail: `принято ${s(d.accepted)}, отклонено ${s(d.rejected)}, ${bytes(Number(d.bytes ?? 0))}${d.final_batch ? ", последний пакет" : ""}`,
      };
    case "PROTOCOL_CREATED": {
      const labels = Object.entries((d.labels as Record<string, number>) ?? {})
        .map(([k, n]) => `${LABEL[k] ?? k}: ${n}`)
        .join(", ");
      return { title: `${title}, версия ${s(d.version)}`, detail: `записей ${s(d.findings)}${labels ? ` (${labels})` : ""}` };
    }
    case "PROTOCOL_UNFINALIZED":
      return { title, detail: s(d.reason) };
    case "PROCESSING_FAILED":
      return { title, detail: `шаг ${STEP[s(d.step)] ?? s(d.step)}, попыток ${s(d.attempts)}: ${s(d.error)}` };
    case "PROTOCOL_FINALIZED": {
      // ранние записи хранят только счётчики: без версии, набора примеров и передачи
      const c = obj(d.counts);
      const n = (k: string) => Number(c[k] ?? 0);
      const counts =
        Object.keys(c).length > 0 &&
        `записей ${n("total")}: подтверждено ${n("confirmed")}, отклонено ${n("rejected")}, ` +
          `нарушения нет ${n("no_violation")}, несопоставимо ${n("not_comparable")}, на уточнении ${n("clarification")}` +
          (n("split") > 0 ? `, разделено ${n("split")}` : "") +
          (n("hypotheses") > 0 ? `, гипотез ${n("hypotheses")}` : "");
      return {
        title: d.protocol_version != null ? `${title}, версия ${s(d.protocol_version)}` : title,
        detail: [
          counts,
          d.dataset_items != null && `в набор примеров: ${s(d.dataset_items)}`,
          IAIS_AT_FINALIZE[s(d.iais_sync)] ?? s(d.iais_sync),
        ]
          .filter(Boolean)
          .join(" · "),
      };
    }
    case "FILE_STAGE_SET": {
      // from — стадия и раздел файла до правки, to — заданное вручную после неё (null — вручную не задано)
      const from = obj(d.from);
      const to = obj(d.to);
      // разбор пишет UNKNOWN и OTHER, когда не определил стадию или раздел, — так их называет и экран файлов
      const stage = (v: unknown) => (v && v !== "UNKNOWN" ? STAGE_WORD[s(v)] ?? s(v) : "не определена");
      const section = (v: unknown) => (v && v !== "OTHER" ? SECTION_WORD[s(v)] ?? s(v) : "не определён");
      const changes = [
        !!to.stage && to.stage !== from.stage && `стадия ${stage(from.stage)} → ${stage(to.stage)}`,
        !!to.section && to.section !== from.section && `раздел ${section(from.section)} → ${section(to.section)}`,
      ].filter(Boolean);
      // Значения не поменялись — выбор снят, и стадию или раздел снова определит разбор. Какое
      // из двух полей снимали, по записи не видно, когда вручную не было задано ни одно
      const auto = [!to.stage && "стадия", !to.section && "раздел"].filter(Boolean).join(" и ");
      const what = changes.length
        ? changes.join(", ")
        : auto
          ? `выбор снят, ${auto} — по разбору`
          : `стадия ${stage(to.stage)}, раздел ${section(to.section)} — без изменений`;
      return { title, detail: [`${file}: ${what}`, s(d.comment)].filter(Boolean).join(" · ") };
    }
    case "FILE_REVISION_SET": {
      const from = obj(d.from);
      const to = obj(d.to);
      // у других файлов цепочки прежний выбор снимается: актуальной редакция бывает одна
      const released = Array.isArray(to.released) ? to.released.map(s) : [];
      const parsed = REVISION_LABEL[s(from.revision_status)] ?? s(from.revision_status);
      return {
        title: to.authoritative ? title : "Выбор актуальной редакции снят",
        detail: [
          `${file}${parsed ? ` (по разбору — ${parsed})` : ""}` +
            (released.length ? `; прежний выбор снят: ${released.join(", ")}` : ""),
          s(d.comment),
        ]
          .filter(Boolean)
          .join(" · "),
      };
    }
    case "IAIS_SYNCED":
      return {
        title,
        detail: [iais(), s(d.external_id) && `номер во внешней системе ${s(d.external_id)}`].filter(Boolean).join(", "),
      };
    case "IAIS_RETRY_SCHEDULED":
      return {
        title,
        detail: iais() + (d.next_retry_in_s != null ? `; повтор через ${duration(Number(d.next_retry_in_s))}` : ""),
      };
    case "IAIS_SYNC_FAILED":
    case "IAIS_REJECTED":
      return { title, detail: iais() };
    case "OBJECT_DELETE":
      return {
        title,
        detail: `${s(d.name)}: проверок ${s(d.processes)}, файлов ${s(d.files)}, из хранилища убрано ${s(d.orphan_blobs)}`,
      };
    case "DATASET_RELEASED":
      return {
        title,
        detail: [
          `${s(d.dataset_version)}: примеров ${s(d.items)} (положительных ${s(d.positives)}, отрицательных ${s(d.negatives)}); ` +
            (d.base_version
              ? `к прошлой версии ${s(d.base_version)} добавлено ${s(d.added)}, изменено ${s(d.changed)}, убрано ${s(d.removed)}`
              : "первая версия"),
          s(d.comment),
        ]
          .filter(Boolean)
          .join(" · "),
      };
    case "DATASET_WITHDRAW":
      return { title, detail: [`${s(d.dataset_version)}, примеров ${s(d.items)}`, s(d.reason)].filter(Boolean).join(" · ") };
    case "FINDING_SPLIT":
      return { title, detail: `${s(d.original_finding_id)}: частей ${s(d.parts_count)}` };
    default:
      if (action.startsWith("FINDING_")) {
        const reason = REASONS.find((r) => r.code === d.reason_code)?.label;
        // у записи свободного поиска кода параметра может не быть: тогда её называет номер записи
        const record = s(d.parameter_code) || s(d.finding_id);
        return { title, detail: [record, reason, s(d.comment)].filter(Boolean).join(" · ") };
      }
      return { title, detail: Object.keys(d).length ? JSON.stringify(d) : "" };
  }
}
