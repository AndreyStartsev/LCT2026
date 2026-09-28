// Страница правил эксперта (Р-134): снимок файлов правил, который воркер кладёт в базу при старте
// (`service/worker/rules_snapshot.py`), в виде для чтения человеком. Что правило сравнивает, каким
// порогом, в каких документах ищет значение и почему параметр не проверяется — всё берётся из
// самих файлов правил; словами здесь только то, чего в файлах нет: виды сравнения, найденные
// в разборе, но не описанные в `compare_types` очереди.

type Json = Record<string, any>;

/** Состояние параметра Матрицы в правилах — те же группы, что в покрытии протокола (pipeline/protocol.py). */
export const RULE_STATES = ["ACTIVE", "DRAFT", "NOT_CHECKED", "OUT_OF_SCOPE"] as const;
export type RuleState = (typeof RULE_STATES)[number];

/** Статус черновика — те же слова, что у его находок в протоколе (`matrix_rules.PROVISIONAL_REASON`). */
const DRAFT_NOTE = "Черновик правила: расхождение показывается гипотезой, в сдачу — только решением инспектора";

/**
 * Что считается нарушением при виде сравнения — по `decide` и разборам pipeline/matrix_rules.py.
 * Вид, которого здесь нет, берёт описание из `compare_types` своей очереди, а без него — общее:
 * такой разбор свой, и его смысл рассказывает пояснение правила.
 */
const COMPARE: Record<string, string> = {
  any_change: "нарушение — значения ПД и РД расходятся после приведения к одной точности",
  relative: "нарушение — значение РД отклоняется от проектного больше порога",
  decrease: "нарушение — в РД меньше, чем в ПД",
  increase: "нарушение — в РД больше, чем в ПД",
  min_absolute: "нарушение — в РД меньше нормативного порога; проектное значение не требуется",
  class_downgrade: "нарушение — класс в РД хуже проектного",
  min_trigger:
    "нарушение — наименьшее значение РД меньше порога Матрицы; меньше требования ПД при соблюдённом пороге — тоже расхождение",
  max_trigger:
    "нарушение — наибольшее значение РД больше порога Матрицы; больше проектного при соблюдённом пороге — тоже расхождение",
  set_decrease:
    "значение стадии — набор подписей; нарушение — весь набор РД ниже наименьшего проектного, пересекающиеся наборы — сравнение невозможно",
  set_change: "значение стадии — набор; нарушение — в РД есть значение, которого нет в проекте",
  min_decrease: "нарушение — наименьшее значение элемента в РД меньше наименьшего в ПД",
  presence: "нарушение — в РД не названо ни одно из решений, названных в ПД",
  decrease_or_text_change: "нарушение — значение в РД уменьшилось или строка перечня изменилась",
  count_by_type: "количество по видам; нарушение — по виду в РД меньше, чем в ПД",
};

/** Единица порога, записанного долей: 0,01 — «1 %». */
const SHARE_THRESHOLD = new Set(["relative", "keyed", "construction_duration"]);

/** Как правило находит значение (#222): шаблоны из файла правила, свой разбор в коде или модель по чертежам. */
export const ENGINES = ["pattern", "code", "llm"] as const;
export type Engine = (typeof ENGINES)[number];
/** Числа сравнения, которые меняет песочница (#223), — те же, что в `pipeline/rule_test.py`. */
export const NUMERIC = ["threshold", "trigger", "tolerance", "tolerance_pct"] as const;

export interface RuleLogic {
  /** тип правила из снимка воркера; null — снимок старый, типа в нём нет */
  engine: Engine | null;
  /** поля, которые песочница может поменять: compare, labels, exclude, features */
  editable: string[];
  /** текущие числа сравнения: порог, порог Матрицы, допуск */
  values: Partial<Record<(typeof NUMERIC)[number], number>>;
  compare: string | null;
  threshold: string | null;
  unit: string | null;
  labels: string[];
  exclude: string[];
  features: { name: string; pattern: string }[];
  documents: { stage: "PD" | "RD" | "ID"; names: string[]; pattern: string | null }[];
  model: { what: string | null; stages: string[]; sections: string[]; prompt: string | null } | null;
  hypothesis_only: boolean;
  note: string | null;
}

export interface RuleView {
  code: string;
  id: number | null;
  name: string | null;
  section: string | null;
  queue: number | null;
  criticality: string | null;
  unit: string | null;
  sources: { pd: string | null; rd: string | null; id: string | null };
  trigger: string | null;
  state: RuleState;
  state_note: string | null;
  rule: RuleLogic | null;
  draft: RuleLogic | null;
}

export interface GuidanceView {
  code: string;
  aspect: string | null;
  verdict: string | null;
  /** вид признан нарушением и идёт в сдачу без перевода инспектором (pipeline/specialist.py) */
  submit: boolean;
  note: string | null;
}

export interface RulesView {
  fingerprint: string;
  published_at: string;
  counts: Record<"parameters" | "active" | "draft" | "not_checked" | "out_of_scope", number>;
  parameters: RuleView[];
  guidance: GuidanceView[];
}

// ---------- тексты без служебных хвостов ----------

// Ссылки разработки: решения и задачи (Р-91, #145), разбор записей со специалистом (R4-H06, R6-KR-067,
// V-insulation-walls), метки разметки (ANN-C-0001), номера вопросов, круги разбора, даты, пути к коду,
// команды в обратных кавычках и имена полей, функций и кодов (matrix_rules.door_findings, MATERIAL_…).
// JS-граница слова \b кириллицу не видит — отсюда просмотр по буквам \p{L}.
const REF_SOURCE =
  "(?<![\\p{L}\\d-])(?:Р-\\d+|R\\d+-[A-Za-z0-9-]+|[A-Z]-[a-z][a-z-]*|ANN-[A-Z0-9-]+)|#\\d+|`[^`]*`" +
  "|(?<!\\p{L})круг(?:а|е|у|ом|и|ов)?(?!\\p{L})|(?<!\\p{L})вопрос\\p{L}*\\s+\\d+|pipeline/|docs/|\\.py(?![\\p{L}\\d])" +
  "|\\d{1,2}\\.\\d{2}\\.\\d{4}|(?<![\\p{L}\\d])(?:[a-z]+(?:[._][a-z]+)+|[A-Z]+(?:_[A-Z]+)+)(?![\\p{L}\\d])";
const REF = new RegExp(REF_SOURCE, "u");
const REFS = new RegExp(REF_SOURCE, "gu");
// История внутри скобок: «третий круг 25.09», «перенесено из черновиков», «разметка организатора»
const PROVENANCE_SOURCE =
  "(?<!\\p{L})\\p{L}+\\s+круг(?:а|е|у|ом|и|ов)?(?!\\p{L})(?:\\s+\\d{1,2}\\.\\d{2}(?:\\.\\d{4})?)?" +
  "|перенесено из черновиков|(?:черновик\\s+)?принят[оа]?\\s+как\\s+есть|(?<!\\p{L})правка(?!\\p{L})|разметк\\p{L}*\\s+организатора";
const PROVENANCE = new RegExp(PROVENANCE_SOURCE, "iu");
const PROVENANCES = new RegExp(PROVENANCE_SOURCE, "giu");
// «специалист, шестой круг, R6-…», «ответ специалиста R6-POS-082: показывать» — кто ответил, а не что
const ATTRIBUTION = /^(?:специалист\p{L}*|ответы?\s+специалиста)[^:]*:\s*/iu;
// Предложения-история: откуда правило, как его переносили, чем разбирают, на чьей разметке выбрано
const DROP_SENTENCE = [
  /^Правило специалиста по проектированию\.?$/u,
  /^Черновик(?: для специалиста)?\.?$/u,
  /^Черновик принят как есть/u,
  /^Разбор\s+—/u,
  /(?<!\p{L})запись строит/iu,
  /организатор|(?<!\p{L})эталон|контрольн\p{L}*\s+точк/iu,
];
// Вводные к ответу специалиста: ответ и есть правило, вводная — кто и когда ответил
const LEAD_IN = [
  /^\p{L}+\s+круг(?!\p{L})[^:]*:\s*/u,
  /^Специалист велел\s+/u,
  /^Специалист(?:,[^:]*)?:\s*/u,
  /^Ответы? специалиста[^:]*:\s*/u,
  /^Правило специалиста[^:]*:\s*/u,
  /^Черновик(?: для специалиста)?[.:]\s*/u,
];
// Разбор отдельной записи («R4-H04 — не нарушение: 1000 мм у …») — случай, а не правило
const CASE = /(?<![\p{L}\d-])R\d+-H\d+|^обе гипотезы/iu;

/** Первая буква — прописная, и после открывающей кавычки или скобки тоже; знак вроде «λ» — как есть. */
function capital(text: string): string {
  return text.replace(/^([«"(]*)([а-яёa-z])/u, (_m, lead: string, letter: string) => lead + letter.toLocaleUpperCase("ru"));
}

function plainSentence(sentence: string): string {
  let t = sentence.trim();
  for (let guard = 0; guard < 4; guard++) {
    const before = t;
    for (const lead of LEAD_IN) t = t.replace(lead, "");
    if (t === before) break;
  }
  if (CASE.test(t) || DROP_SENTENCE.some((re) => re.test(t))) return "";
  // решения по ходу разработки («пользователь 25.09 решил…») — не правило: такая часть уходит
  t = t
    .split(/;\s+/u)
    .filter((part) => !/пользовател/u.test(part))
    .join("; ");
  t = t
    .replace(/needs_expert/gu, "«требует подтверждения»")
    .replace(/\s+с\s+[A-Z]+(?:_[A-Z]+)+\s+и\s+/gu, " с ")
    .replace(/,?\s*[Рр]азбор\s+—\s+`?[A-Za-z0-9_]+(?:[./][A-Za-z0-9_]+)+`?/gu, "")
    .replace(/\s*—\s*проверка применимости\s+[a-z_]+/gu, "")
    .replace(/(?<!\p{L})велел(?!\p{L})/gu, "решил")
    // «корпус» — это загруженные пакеты объектов; корпус здания («в корпусе 2») не трогаем
    .replace(/(?<!\p{L})в корпусе(?!\s*[\d№«])/gu, "в загруженных пакетах")
    .replace(/(?<!\p{L})по корпусу(?!\p{L})/gu, "по загруженным пакетам");
  if (REF.test(t)) {
    // ссылка вне скобок: предложение о круге разбора — история, прочее остаётся без ссылки
    if (/(?<!\p{L})круг/u.test(t)) return "";
    t = t.replace(REFS, "");
  }
  t = t
    .replace(/\(\s*[,;]?\s*\)/gu, "")
    .replace(/\s+([,.;:])/gu, "$1")
    .replace(/[,;:](?=\.)/gu, "")
    .replace(/[;:,]\s*$/u, "")
    .replace(/\s{2,}/gu, " ")
    .trim();
  return capital(t);
}

/**
 * Скобки со ссылкой по частям через «;»: часть без ссылки остаётся как есть, из части со ссылкой
 * уходят ссылка, история и вводная «специалист: …», а остаток — только если в нём есть смысл,
 * хотя бы три слова: «(триггер важнее требования ПД, Р-104)» → «(триггер важнее требования ПД)».
 */
function plainParen(inner: string): string {
  return inner
    .split(/;\s*/u)
    .map((part) => {
      if (!REF.test(part) && !PROVENANCE.test(part)) return part.trim();
      const rest = part
        .replace(ATTRIBUTION, "")
        .replace(PROVENANCES, "")
        .replace(REFS, "")
        .replace(/\s*,(?:\s*,)+/gu, ",")
        .replace(/^[\s,.:;—–-]+|[\s,.:;—–-]+$/gu, "")
        .replace(/\s{2,}/gu, " ")
        .trim();
      return (rest.match(/\p{L}{3,}/gu) ?? []).length >= 3 ? rest : "";
    })
    .filter(Boolean)
    .join("; ");
}

/**
 * Пояснение правила без внутренней кухни. В заметках файлов правил рядом со смыслом лежит история
 * разработки: номера решений и задач, круги разбора со специалистом, записи, на которых решали, пути
 * к коду. Эксперту это ничего не говорит, а в интерфейсе выглядит недоделкой. Смысл остаётся целиком,
 * уходят скобки со ссылкой, предложения-история, разбор отдельных записей и вводные «Специалист: …»
 * перед ответом, который и есть правило.
 */
export function plainNote(text: unknown): string | null {
  if (typeof text !== "string" || !text.trim()) return null;
  let s = text;
  // скобки со ссылкой: смысл остаётся, ссылка и история уходят; вложенные раскрываются изнутри
  for (let guard = 0; guard < 8; guard++) {
    const next = s.replace(/\s*\(([^()]*)\)/gu, (whole, inner: string) => {
      if (!REF.test(inner) && !PROVENANCE.test(inner)) return whole;
      const kept = plainParen(inner);
      return kept ? ` (${kept})` : "";
    });
    if (next === s) break;
    s = next;
  }
  const out = s
    .split(/(?<=[.!?])\s+(?=[«"\p{Lu}])/u)
    .map(plainSentence)
    .filter(Boolean)
    .map((t) => (/[.!?»]$/u.test(t) ? t : `${t}.`))
    .join(" ")
    .trim();
  return out || null;
}

// ---------- правило ----------

function num(n: number): string {
  return String(Math.round(n * 1000) / 1000).replace(".", ",");
}

function threshold(compare: Json, unit: string | null): string | null {
  const parts: string[] = [];
  const type = String(compare.type ?? "");
  const u = unit ? ` ${unit}` : "";
  if (typeof compare.trigger === "number") parts.push(`порог Матрицы ${num(compare.trigger)}${u}`);
  if (typeof compare.threshold === "number") {
    parts.push(
      SHARE_THRESHOLD.has(type) || (compare.threshold > 0 && compare.threshold < 1 && type !== "min_absolute")
        ? `порог ${num(compare.threshold * 100)} %`
        : `порог ${num(compare.threshold)}${u}`,
    );
  }
  if (typeof compare.tolerance === "number") parts.push(`допуск ${num(compare.tolerance * 100)} %`);
  if (typeof compare.tolerance_pct === "number") parts.push(`допуск ${num(compare.tolerance_pct)} %`);
  return parts.length ? parts.join(", ") : null;
}

/** «(?<![А-ЯЁа-яё])(?:ПОС|ПОД|ДР)(?![а-яё])» → ПОС, ПОД, ДР; сложное выражение остаётся выражением. */
export function documentNames(pattern: string): string[] {
  const bare = pattern.replace(/\(\?<?[=!][^()]*\)/gu, "").replace(/\(\?:/gu, "(").replace(/[()]/gu, "");
  const names = bare.split("|").map((p) => p.trim());
  return names.every((p) => /^[\p{L}\d.\- ]+$/u.test(p)) ? names : [];
}

function documents(rule: Json): RuleLogic["documents"] {
  const out: RuleLogic["documents"] = [];
  const named: Json = rule.source_names ?? {};
  const patterns: Json = rule.documents ?? {};
  for (const stage of ["PD", "RD", "ID"] as const) {
    const names: string[] = Array.isArray(named[`source_${stage.toLowerCase()}`])
      ? named[`source_${stage.toLowerCase()}`].filter((n: unknown) => typeof n === "string" && n !== "*")
      : [];
    const pattern = typeof patterns[stage] === "string" ? (patterns[stage] as string) : null;
    const fromPattern = pattern ? documentNames(pattern) : [];
    const list = names.length ? names : fromPattern;
    if (list.length || pattern) out.push({ stage, names: list, pattern: list.length ? null : pattern });
  }
  return out;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

function logic(rule: Json | null | undefined, compareTypes: Json, meta?: Json): RuleLogic | null {
  if (!rule || typeof rule !== "object") return null;
  const compare: Json | null = rule.compare && typeof rule.compare === "object" ? rule.compare : null;
  const type = compare ? String(compare.type ?? "") : "";
  const own = typeof compareTypes[type] === "string" ? plainNote(compareTypes[type]) : null;
  const vlm: Json | null = rule.vlm && typeof rule.vlm === "object" ? rule.vlm : null;
  const unit = typeof rule.unit === "string" ? rule.unit : null;
  const values: RuleLogic["values"] = {};
  for (const key of NUMERIC) {
    if (typeof compare?.[key] === "number" && Number.isFinite(compare[key])) values[key] = compare[key];
  }
  const engine = (ENGINES as readonly string[]).includes(meta?.engine) ? (meta!.engine as Engine) : null;
  return {
    engine,
    editable: engine ? strings(meta?.editable) : [],
    values,
    compare: compare ? COMPARE[type] ?? own ?? "свой разбор: что считается нарушением, сказано в пояснении" : null,
    threshold: compare ? threshold(compare, unit) : null,
    unit,
    labels: strings(rule.labels),
    exclude: strings(rule.exclude),
    features: Array.isArray(rule.features)
      ? rule.features
          .filter((f: Json) => typeof f?.name === "string" && typeof f?.pattern === "string")
          .map((f: Json) => ({ name: f.name, pattern: f.pattern }))
      : [],
    documents: documents(rule),
    model: vlm
      ? {
          what: typeof vlm.what === "string" ? vlm.what : null,
          stages: strings(vlm.stage),
          sections: strings(vlm.sections),
          prompt: typeof vlm.prompt === "string" ? vlm.prompt : null,
        }
      : null,
    hypothesis_only: rule.hypotheses === "drawing",
    note: plainNote(rule.note),
  };
}

function sectionOf(pdSection: unknown): string | null {
  if (typeof pdSection !== "string") return null;
  const m = /\.\s*(\S+)\s*$/u.exec(pdSection);
  return m ? m[1] : pdSection;
}

function queueOf(code: string, queues: Record<string, Json>): number | null {
  for (const [queue, doc] of Object.entries(queues)) {
    if (doc?.parameters && Object.prototype.hasOwnProperty.call(doc.parameters, code)) return Number(queue);
  }
  return null;
}

/**
 * Вид правил для страницы эксперта. `body` — тело снимка воркера (формат 1): очереди, черновики,
 * каталог 132 параметров, решения специалиста. Порядок — как в Матрице; состояние — как в покрытии
 * протокола: вне документов, работает, черновик, не проверяется.
 */
export function buildRulesView(body: Json, meta: { fingerprint: string; published_at: string }): RulesView {
  const queues: Record<string, Json> = body?.queues ?? {};
  // тип правила и поля песочницы знает конвейер: их кладёт в снимок воркер (#222, #223)
  const engines: { rules?: Json; drafts?: Json } = body?.engines ?? {};
  const provisional: Record<string, Json> = body?.provisional ?? {};
  const catalog: Json[] = Array.isArray(body?.catalog) ? body.catalog : [];
  const rules = new Map<string, { rule: Json; types: Json }>();
  for (const doc of Object.values(queues)) {
    for (const [code, rule] of Object.entries<Json>(doc?.parameters ?? {})) {
      rules.set(code, { rule, types: doc?.compare_types ?? {} });
    }
  }
  const drafts = new Map<string, { rule: Json; types: Json }>();
  for (const [queue, doc] of Object.entries(provisional)) {
    // классы и виды сравнения черновик берёт у своей очереди прода
    const types = { ...(queues[queue]?.compare_types ?? {}), ...(doc?.compare_types ?? {}) };
    for (const [code, rule] of Object.entries<Json>(doc?.parameters ?? {})) drafts.set(code, { rule, types });
  }

  const parameters: RuleView[] = [...catalog]
    .sort((a, b) => (Number(a.parameter_id) || 0) - (Number(b.parameter_id) || 0))
    .map((row) => {
      const code = String(row.parameter_code);
      const prod = rules.get(code);
      const draft = drafts.get(code);
      const rule = prod?.rule ?? null;
      let state: RuleState;
      let note: string | null;
      if (rule?.out_of_scope) {
        state = "OUT_OF_SCOPE";
        note = plainNote(rule.out_of_scope.reason);
      } else if (rule?.implemented) {
        state = "ACTIVE";
        note = null;
      } else if (draft) {
        state = "DRAFT";
        note = DRAFT_NOTE;
      } else {
        state = "NOT_CHECKED";
        // пометка правила для инспектора — «Правило на проверке: …»; заметка разработки про корпус (reason)
        // не показывается, как и на дашборде
        note = typeof rule?.inspector_note === "string" ? rule.inspector_note : "Правило на проверке";
      }
      return {
        code,
        id: Number.isFinite(Number(row.parameter_id)) ? Number(row.parameter_id) : null,
        name: row.parameter_name ?? null,
        section: sectionOf(row.pd_section),
        queue: queueOf(code, queues),
        criticality: row.criticality ?? null,
        unit: row.unit ?? null,
        sources: { pd: row.source_pd ?? null, rd: row.source_rd ?? null, id: row.source_id ?? null },
        trigger: row.trigger ?? rule?.basis ?? null,
        state,
        state_note: note,
        rule: rule?.implemented ? logic(rule, prod!.types, engines.rules?.[code]) : null,
        draft: draft ? logic(draft.rule, draft.types, engines.drafts?.[code]) : null,
      };
    });

  const kinds: Json[] = Array.isArray(body?.guidance?.kinds) ? body.guidance.kinds : [];
  const guidance: GuidanceView[] = kinds
    .filter((k) => typeof k?.code === "string")
    .map((k) => ({
      code: k.code,
      aspect: typeof k.aspect === "string" ? k.aspect : null,
      verdict: typeof k.verdict === "string" ? k.verdict : null,
      submit: k.submit === true,
      note: plainNote(k.note),
    }));

  const count = (state: RuleState) => parameters.filter((p) => p.state === state).length;
  return {
    fingerprint: meta.fingerprint,
    published_at: meta.published_at,
    counts: {
      parameters: parameters.length,
      active: count("ACTIVE"),
      draft: count("DRAFT"),
      not_checked: count("NOT_CHECKED"),
      out_of_scope: count("OUT_OF_SCOPE"),
    },
    parameters,
    guidance,
  };
}

// ---------- песочница (#223) ----------

const MAX_PATTERNS = 40;
const MAX_PATTERN_LEN = 400;

function patternList(value: unknown, key: string, allowEmpty: boolean): string | null {
  if (!Array.isArray(value) || value.length > MAX_PATTERNS) return `${key}: нужен список до ${MAX_PATTERNS} выражений`;
  if (!allowEmpty && value.length === 0) return `${key}: нужна хотя бы одна подпись`;
  if (value.some((v) => typeof v !== "string" || !v.trim() || v.length > MAX_PATTERN_LEN)) {
    return `${key}: каждое выражение — непустая строка не длиннее ${MAX_PATTERN_LEN} знаков`;
  }
  return null;
}

/**
 * Что не так с вариантом правила из песочницы — до постановки прогона в очередь. Меняются только поля,
 * которые конвейер разрешил этому правилу (`editable` из снимка воркера); регулярные выражения проверяет
 * воркер: у Python свой синтаксис, и JavaScript его не судья. Правило с разбором в коде в песочнице не
 * прогоняется совсем, даже с порогом: код в песочнице не меняют, и снимок прежнего воркера этого не отменяет.
 */
export function variantProblems(variant: unknown, logic: RuleLogic): string[] {
  if (variant === undefined || variant === null) return [];
  if (typeof variant !== "object" || Array.isArray(variant)) return ["вариант правила — объект с полями правила"];
  const entries = Object.entries(variant as Json);
  if (!entries.length) return ["вариант пуст: поменяйте хотя бы одно поле"];
  if (logic.engine === "code") return ["правило с разбором в коде в песочнице не прогоняется: код в песочнице не меняют"];
  const out: string[] = [];
  for (const [key, value] of entries) {
    if (!logic.editable.includes(key)) {
      out.push(`поле «${key}» у этого правила в песочнице не меняется`);
      continue;
    }
    if (key === "labels" || key === "exclude") {
      const problem = patternList(value, key, key === "exclude");
      if (problem) out.push(problem);
    } else if (key === "features") {
      if (
        !Array.isArray(value) ||
        !value.length ||
        value.length > MAX_PATTERNS ||
        value.some(
          (f) =>
            typeof f?.name !== "string" ||
            !f.name.trim() ||
            typeof f?.pattern !== "string" ||
            !f.pattern.trim() ||
            f.pattern.length > MAX_PATTERN_LEN,
        )
      ) {
        out.push(`features: нужен список до ${MAX_PATTERNS} признаков с названием и выражением`);
      }
    } else if (key === "compare") {
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        out.push("compare: нужен объект с порогом или допуском");
        continue;
      }
      for (const [k, v] of Object.entries(value as Json)) {
        if (!(NUMERIC as readonly string[]).includes(k) || !(k in logic.values)) {
          out.push(`compare.${k}: меняются только порог и допуск, которые у правила уже есть`);
        } else if (typeof v !== "number" || !Number.isFinite(v) || v < 0) {
          out.push(`compare.${k}: нужно неотрицательное число`);
        }
      }
    }
  }
  return out;
}
