// Уверенность в выводе записи (#80): уровень для отбора в списке и признаки, из которых он сложен.
//
// Процента здесь нет, и это решение, а не упущение. Число «72 %» нечем обосновать: у записи есть
// предметные признаки — чем прочитано значение, к чему привязано, сколько страниц его подтверждают,
// нет ли рядом похожего на ошибку чтения, — и инспектору они говорят больше. Уровень считается из
// этих признаков и показывается вместе с ними, а не вместо них.
//
// Признаки ставит конвейер (`pipeline/matrix_rules.py`: `recognized_review`, `reconcile`,
// `binding_note`, доводы правила `confidence_note` — Р-104), здесь они только читаются. Уровень есть у записи, где сравнение состоялось
// («нарушение» и «нарушения нет») и значения сторон прочитаны разбором правил: у несравнённой
// записи вывода нет, а у гипотез других разборов (помещения, редакции) нет признаков чтения —
// оценивать нечем, и уровень не ставится. Исключение — доводы, которые разбор ставит сам
// (`extraction.confidence`): у записи «элемент проекта не найден в РД» значений нет, но способ
// поиска — по словам проекта — известен, и это довод против (Р-108).
//
// Уверенность — о чтении и привязке значений, не о том, кто решает. Пометка «требует
// подтверждения» (`needs_expert`) у гипотез — правило, а не сомнение в данных: она видна своим
// значком и уровень не роняет. Критичность — по каталогу (`criticality`), решение специалиста —
// отдельно (`specialist`): это другие вопросы, и в уровень они не подмешиваются.

type Json = Record<string, any>;

export type ConfidenceLevel = "HIGH" | "MEDIUM" | "LOW";

export interface Confidence {
  level: ConfidenceLevel;
  /** что снижает уверенность, начиная с того, что делает её низкой */
  down: string[];
  /** на что вывод опирается */
  up: string[];
}

const SIDES: [key: "pd" | "rd" | "id", stage: "PD" | "RD" | "ID", short: string][] = [
  ["pd", "PD", "ПД"],
  ["rd", "RD", "РД"],
  ["id", "ID", "ИД"],
];

const BINDING: Record<string, string> = {
  SHEET: "значение с листа чертежа — может относиться к соседнему элементу",
  PAGE: "значение со страницы, не из указаний",
  PATH: "значение по пути файла, не из текста",
};

const COMPARED = new Set(["VIOLATION_PRESENT", "NO_VIOLATION"]);

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function shown(value: unknown): string {
  return String(value ?? "").trim();
}

export function confidenceOf(body: Json | null | undefined, violationLabel: string | null | undefined): Confidence | null {
  if (!violationLabel || !COMPARED.has(violationLabel)) return null;
  const ext: Json = isObject(body?.extraction) ? body!.extraction : {};
  const sides = SIDES.map(([key, stage, short]) => ({ stage, short, side: ext[key] })).filter(
    (s): s is { stage: "PD" | "RD" | "ID"; short: string; side: Json } => isObject(s.side),
  );
  // доводы, которые знает только разбор (Р-104, Р-108): «порог — триггер Матрицы», «элемент искали по словам проекта»
  const note: Json = isObject(ext.confidence) ? ext.confidence : {};
  const noted = [note.low, note.medium, note.up].some((items) => Array.isArray(items) && items.length > 0);
  if (sides.length === 0 && !noted) return null;
  const low: string[] = [];
  const mid: string[] = [];
  const up: string[] = [];

  // Низкая: сама система этим значениям не доверяет (#41) — прочитанное машиной расходится
  // со слоем других страниц, значение похоже на ошибку распознавания, вывод держится на прочитанном машиной
  for (const { short, side } of sides) {
    if (side.layer_conflict != null && shown(side.layer_conflict)) {
      low.push(`${short}: прочитано машиной, а текстовый слой других страниц даёт «${shown(side.layer_conflict)}»`);
    }
    for (const d of Array.isArray(side.doubtful) ? side.doubtful : []) {
      if (!isObject(d)) continue;
      low.push(
        `${short}: «${shown(d.value)}» похоже на ошибку распознавания` +
          (d.against != null ? ` рядом с «${shown(d.against)}»` : ""),
      );
    }
  }
  const recognized: Json = isObject(ext.recognized) ? ext.recognized : {};
  if (recognized.confirmation === true && low.length === 0) {
    low.push(
      violationLabel === "VIOLATION_PRESENT"
        ? "нарушение опирается на значение, прочитанное машиной"
        : "значение, прочитанное машиной, требует подтверждения",
    );
  }

  // Средняя: вывод держится, но опирается на то, что стоит проверить глазами
  for (const { short, side } of sides) {
    if (side.text_source === "RECOGNIZED" && recognized.confirmation !== true) {
      mid.push(`${short}: значение прочитано машиной — распознаванием или моделью`);
    }
    if (typeof side.binding === "string" && BINDING[side.binding]) {
      mid.push(`${short}: ${BINDING[side.binding]}`);
    }
    if (side.column_choice === "rule" && Array.isArray(side.columns) && side.columns.length > 1) {
      mid.push(`${short}: шапка таблицы не распознана, колонка выбрана по положению`);
    }
    const support = typeof side.support === "number" ? side.support : null;
    const rival = (Array.isArray(side.alternatives) ? side.alternatives : []).find(
      (a: unknown) => isObject(a) && typeof a.pages === "number" && support !== null && a.pages >= support,
    );
    if (rival) {
      mid.push(`${short}: на других страницах стоит и «${shown(rival.value)}» — ${rival.pages} стр. против ${support}`);
    }
  }
  const fallback: Json = isObject(ext.source_fallback) ? ext.source_fallback : {};
  for (const { stage, short } of sides) {
    if (fallback[stage]) mid.push(`${short}: значение найдено не в разделе, который каталог называет источником`);
  }

  // На что вывод опирается
  if (sides.length > 0 && sides.every(({ side }) => side.text_source !== "RECOGNIZED")) {
    up.push("значения из текстового слоя PDF");
  }
  for (const { short, side } of sides) {
    if (typeof side.support === "number" && side.support >= 2) up.push(`${short}: подтверждено на ${side.support} стр.`);
    if (side.binding === "CLAUSE") up.push(`${short}: из указаний к элементу`);
  }

  // Доводы, которые знает только правило (Р-104): «порог — триггер Матрицы», «какая это дверь, по ответу
  // модели не видно», «марка привязана только планом потолков». Их ставит конвейер (`confidence_note`)
  for (const [items, into] of [[note.low, low], [note.medium, mid], [note.up, up]] as [unknown, string[]][]) {
    for (const x of Array.isArray(items) ? items : []) {
      const text = shown(x);
      if (text && !into.includes(text)) into.push(text);
    }
  }

  return { level: low.length ? "LOW" : mid.length ? "MEDIUM" : "HIGH", down: [...low, ...mid], up };
}
