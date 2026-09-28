// Протокол проверки объекта для инспектора. Задача #30.
//
// Структура — по образцу Приложения 2 к ТЗ («Протокол автоматизированной сверки»,
// существенная редакция ТЗ): статус загрузки, тип проверки, сводка по 132 параметрам,
// пять таблиц из раздела 9.2, резолютивная часть после финализации, карточки
// доказательств и правила подсчёта. Часть, не зависящую от решений инспектора, воркер
// кладёт в report протокола (pipeline/protocol.py); решения берутся из базы в момент
// выгрузки, поэтому выгрузка всегда совпадает с тем, что видно на экране верификации.

type Json = Record<string, any>;

export const STAGES = ["PD", "RD", "ID"] as const;
type Stage = (typeof STAGES)[number];

const STAGE_NAME: Record<Stage, string> = {
  PD: "Проектная документация",
  RD: "Рабочая документация",
  ID: "Исполнительная документация",
};

const SCENARIO_TEXT: Record<string, string> = {
  FULL: "полный комплект: ПД, РД и ИД",
  PD_RD_ONLY: "ПД и РД, исполнительная документация не загружена",
  PD_ID_ONLY: "ПД и ИД, рабочая документация не загружена",
  RD_ID_ONLY: "РД и ИД, проектная документация не загружена",
  SINGLE_ONLY: "загружена одна стадия",
  PARTIALLY_LOADED: "загружено частично: часть файлов не принята",
};

export const FINDING_STATUS_TEXT: Record<string, string> = {
  CANDIDATE: "Кандидат — ожидает решения инспектора",
  CONFIRMED_VIOLATION: "Нарушение подтверждено инспектором",
  NEGATIVE_VERIFIED: "Проверено: расхождения нет",
  CLARIFICATION_REQUIRED: "Требует уточнения",
  MISSING_EVIDENCE: "Нет документа или доказательного фрагмента",
  NOT_COMPARABLE: "Источники нельзя сопоставить",
  NOT_APPLICABLE: "Неприменимо",
  NOT_CHECKED: "Не проверено",
  OUT_OF_SCOPE: "Не проверяется по документам",
  HYPOTHESIS: "Проверяется черновиком правила",
  SUSPICION: "Гипотеза свободного поиска",
};
// Гипотеза черновика правила (#95) — тот же статус SUSPICION, но источник свой
const PROVISIONAL_STATUS_TEXT = "Гипотеза: правило на проверке";

const REASON_TEXT: Record<string, string> = {
  WRONG_REVISION: "актуальная редакция выбрана неверно",
  APPROVED_CHANGE: "согласованное изменение",
  OCR_ERROR: "ошибка распознавания",
  LINKING_ERROR: "ошибка привязки",
  NOT_APPLICABLE: "параметр неприменим",
};

export interface ReportInput {
  process: Json;
  object: Json;
  protocol: Json | null;
  files: Json[];
  findings: Json[];
  sync?: Json | null;
  /** Чем файл сдачи организатору отличается от находок автоматики (#63). */
  submission?: { checks: number; removed: number; added: number; undecided: number } | null;
  generatedAt?: Date;
}

const iso = (value: unknown): string | null =>
  value === null || value === undefined ? null : value instanceof Date ? value.toISOString() : new Date(String(value)).toISOString();

const text = (value: unknown): string | null => (value === null || value === undefined || value === "" ? null : String(value));

export function reviewPriority(criticality: string | null | undefined): "HIGH" | "MEDIUM" | "LOW" {
  if (criticality?.startsWith("Критическое")) return "HIGH";
  if (criticality?.startsWith("Существенное")) return "MEDIUM";
  return "LOW";
}

/** Запись свободного поиска вне Матрицы — взятая в кандидаты или нет. */
export function isFreeSearch(row: Json): boolean {
  return row.body?.matrix_scope === "FREE_SEARCH";
}

/**
 * Гипотеза черновика правила (#95, Р-89): параметр Матрицы без правила прода, проверенный
 * черновиком. Как гипотеза свободного поиска, она вне итогов нарушений, пока инспектор не
 * взял её в кандидаты: подход 25.09 — в гипотезы по максимуму, в нарушения только одобренное.
 */
export function isProvisional(row: Json): boolean {
  return row.body?.provisional === true;
}

/**
 * Статус записи по ТЗ, раздел 9.2: метка конвейера и решение инспектора.
 *
 * Гипотеза свободного поиска остаётся SUSPICION, пока инспектор не взял её в кандидаты
 * (ТЗ 9.5). Взятая идёт общим путём: ожидает решения — CANDIDATE, подтверждена —
 * CONFIRMED_VIOLATION и входит в итог нарушений, как в /status и в ИАИС «РиН».
 */
export function findingStatus(row: Json): string {
  const body = row.body ?? {};
  if ((isFreeSearch(row) || isProvisional(row)) && !body.promoted_at) return "SUSPICION";
  const label = row.violation_label;
  if (label === "VIOLATION_PRESENT") {
    switch (row.verification_status) {
      case "CONFIRMED_VIOLATION":
      case "NEGATIVE_VERIFIED":
      case "CLARIFICATION_REQUIRED":
        return row.verification_status;
      default:
        return "CANDIDATE";
    }
  }
  if (label === "NO_VIOLATION") return "NEGATIVE_VERIFIED";
  return body.protocol?.completeness_status === "NOT_COMPARABLE" ? "NOT_COMPARABLE" : "MISSING_EVIDENCE";
}

const STAGE_GENITIVE: Record<Stage, string> = { PD: "ПД", RD: "РД", ID: "ИД" };

/**
 * ТЗ 9.1 ставит PARTIALLY_LOADED выше остальных сценариев, и одно это слово скрывает,
 * какой стадии нет вовсе: у Алтуфьевского не приняты два тома ПД и нет ИД. Поэтому
 * к частичной загрузке дописывается, чего не хватает по каждой стадии.
 */
function scenarioText(scenario: string | null, stages: Array<{ stage: Stage; status: string; files_rejected: number; name: string }>): string {
  if (!scenario) return "не определён";
  const base = SCENARIO_TEXT[scenario] ?? scenario;
  if (scenario !== "PARTIALLY_LOADED") return base;
  const partial = stages.filter((s) => s.status.endsWith("_PARTIAL"))
    .map((s) => `${STAGE_GENITIVE[s.stage]} — не приняты ${s.files_rejected}`);
  const missing = stages.filter((s) => s.status.endsWith("_MISSING")).map((s) => `${s.name.toLowerCase()} не загружена`);
  return [`загружено частично (${partial.join(", ")})`, ...missing].join("; ");
}

function percent(n: number, total: number): number {
  return total ? Math.round((n / total) * 1000) / 10 : 0;
}

function source(e: Json) {
  return {
    file_id: e.file_id ?? null,
    sha256: e.sha256 ?? null,
    stage: e.stage ?? null,
    document: e.document ?? null,
    document_code: e.document_code ?? null,
    revision: e.revision ?? null,
    approval_status: e.approval_status ?? "UNKNOWN",
    sheet: e.document_sheet_number ?? null,
    page: e.pdf_page_number ?? null,
    bbox: Array.isArray(e.bbox_tz) && e.bbox_tz.length ? e.bbox_tz : null,
    quote: e.quote ?? null,
  };
}

function decisionOf(row: Json) {
  if (!["CONFIRMED_VIOLATION", "NEGATIVE_VERIFIED", "CLARIFICATION_REQUIRED"].includes(row.verification_status)) {
    return null;
  }
  return {
    user_id: row.decided_by ?? null,
    timestamp: iso(row.decided_at),
    decision: row.verification_status,
    reason_code: row.reason_code ?? null,
    reason: row.reason_code ? REASON_TEXT[row.reason_code] ?? row.reason_code : null,
    comment: row.comment ?? null,
  };
}

function recordView(row: Json, catalog: Map<string, Json>) {
  const body = row.body ?? {};
  const status = findingStatus(row);
  const param = catalog.get(row.parameter_code) ?? {};
  const criticality = row.criticality ?? param.criticality ?? null;
  const locations: string[] = Array.isArray(body.locations) ? body.locations.map(String) : [];
  return {
    finding_id: row.finding_id,
    parameter_code: row.parameter_code,
    parameter_name: text(body.title) ?? param.parameter_name ?? null,
    section: param.section ?? null,
    location: locations.join(", ") || text(row.location),
    location_type: text(body.location_type),
    pd_value: text(row.pd_value),
    rd_value: text(row.rd_value),
    id_value: text(body.id_value),
    deviation: text(body.extraction?.detail),
    comparison_result: text(body.comparison_result),
    status,
    status_text: status === "SUSPICION" && isProvisional(row) ? PROVISIONAL_STATUS_TEXT : FINDING_STATUS_TEXT[status],
    provisional: isProvisional(row),
    criticality,
    review_priority: reviewPriority(criticality),
    completeness_status: body.protocol?.completeness_status ?? null,
    completeness_reason: body.protocol?.completeness_reason ?? null,
    decision: decisionOf(row),
    changed_after_decision: body.changed_after_decision ?? null,
    origin: text(body.origin),
    // #41: значение прочитано распознаванием сканов (стадии) и требует ли запись подтверждения эксперта
    recognized_stages: Array.isArray(body.extraction?.recognized?.stages) ? body.extraction.recognized.stages.map(String) : [],
    needs_expert: body.needs_expert === true,
  };
}

function evidenceCard(row: Json, record: ReturnType<typeof recordView>, matrixVersion: string | null) {
  const body = row.body ?? {};
  const evidence: Json[] = Array.isArray(body.evidence) ? body.evidence : [];
  const side = (stages: string[]) => evidence.filter((e) => stages.includes(e.stage)).map(source);
  const revisions = (stage: "pd" | "rd") => body.extraction?.[stage]?.revisions ?? [];
  const decision = record.decision;
  return {
    finding_id: record.finding_id,
    object_id: body.object_id ?? null,
    matrix_code: record.parameter_code,
    rule_version: matrixVersion,
    parameter_name: record.parameter_name,
    location: record.location,
    expected_value: record.pd_value,
    actual_value: record.rd_value,
    // третий массив (#42): что построено по исполнительной документации и итог сверки с ней
    built_value: record.id_value,
    built_check: text(body.extraction?.id_check),
    source_expected: side(["PD"]),
    source_actual: side(["RD", "ID"]),
    superseded_revisions: { expected: revisions("pd"), actual: revisions("rd") },
    rule_basis: text(body.extraction?.rule_basis),
    // Чем прочитано значение каждой стороны. На сканах текст даёт распознавание, и оно путает
    // цифры: «B50» рядом с «B30» на одном листе. Инспектор должен видеть это в карточке,
    // а не только в находке (#52).
    value_read_by: {
      expected: body.extraction?.pd?.text_source === "RECOGNIZED" ? "RECOGNIZED" : "TEXT_LAYER",
      actual: body.extraction?.rd?.text_source === "RECOGNIZED" ? "RECOGNIZED" : "TEXT_LAYER",
    },
    deviation: record.deviation,
    // согласованное изменение называет инспектор при отклонении, других сведений о нём у системы нет
    approved_change_ref: decision?.reason_code === "APPROVED_CHANGE" ? decision.comment ?? "APPROVED_CHANGE" : "NONE",
    completeness_status: record.completeness_status,
    finding_status: record.status,
    review_priority: record.review_priority,
    expert_decision: decision,
    changed_after_decision: record.changed_after_decision,
  };
}

const PROTOCOL_STATUS: Record<string, { code: string; text: string }> = {
  PENDING: { code: "DOCUMENTS_UPLOADED", text: "Документы загружены, протокол не сформирован" },
  PARSING: { code: "PROCESSING", text: "Идёт обработка документов" },
  READY: { code: "AWAITING_VERIFICATION", text: "Ожидает верификации (дозагрузка возможна)" },
  VERIFYING: { code: "AWAITING_VERIFICATION", text: "Идёт верификация (дозагрузка возможна)" },
  COMPLETED: { code: "VERIFICATION_COMPLETED", text: "Верификация завершена, протокол не финализирован" },
  FINALIZED: { code: "PROTOCOL_FINALIZED", text: "Протокол финализирован, решения инспектора зафиксированы" },
};

const COMPARED = ["NEGATIVE_VERIFIED", "CANDIDATE", "CONFIRMED_VIOLATION", "CLARIFICATION_REQUIRED"];

/**
 * Непроверенный параметр — словами для протокола объекта: нейтрально, без заметок разработки
 * и без «правило не реализовано» — инспектору важно, что значения на объекте не сверялись.
 */
export const NOT_CHECKED_REASON = "Значения параметра на объекте не сопоставлялись";

/**
 * Группа каждого параметра Матрицы по его записям: не проверен, сопоставлен (хотя бы одна
 * запись сравнена), несопоставим или без доказательств. Параметр попадает ровно в одну
 * группу, и в сумме группы дают все 132. Одна функция на протокол и на дашборд объекта (#83):
 * иначе числа на карточке и в протоколе разошлись бы при первой же правке одного из них.
 */
export function parameterGroups(coverage: Json[], matrixRecords: Array<{ row: Json; record: { status: string } }>) {
  return coverage.map((param) => {
    const mine = matrixRecords.filter((x) => x.row.parameter_code === param.parameter_code);
    const statuses = mine.map((x) => x.record.status);
    // параметр, который по документам не проверяется (внешние системы, отказ по замеру), —
    // своя группа, а не «не проверено» наравне с правилами в работе (pipeline/protocol.py)
    // параметр, который проверяет черновик правила (#95): своя группа, пока инспектор не взял
    // его гипотезу в кандидаты — тогда это сопоставление, как у правила прода. «Расхождения нет»
    // от черновика записью не становится, поэтому любой статус сопоставления здесь — решение инспектора
    const taken = statuses.some((s) => COMPARED.includes(s));
    // Неприменимость к объекту определяет разбор (pipeline/applicability), а не правило: параметр,
    // неприменимый к объекту, — неприменим и тогда, когда правила для него нет. Раньше проверка
    // «правило не реализовано» стояла первой, и такие параметры попадали в «не проверено»
    const group = param.status === "OUT_OF_SCOPE"
      ? "OUT_OF_SCOPE"
      : param.status === "NOT_APPLICABLE" && !taken
      ? "NOT_APPLICABLE"
      : param.status === "HYPOTHESIS"
      ? (taken ? "COMPARED" : "HYPOTHESIS")
      : !param.implemented
      ? "NOT_CHECKED"
      : statuses.some((s) => COMPARED.includes(s))
        ? "COMPARED"
        : statuses.includes("NOT_COMPARABLE")
          ? "NOT_COMPARABLE"
          : "MISSING_EVIDENCE";
    return { param, statuses, group, rows: mine.map((x) => x.row) };
  });
}

export function buildReport(input: ReportInput) {
  const { process, object, protocol, files, findings } = input;
  const report: Json = protocol?.report ?? {};
  const coverage: Json[] = Array.isArray(report.coverage) ? report.coverage : [];
  const catalog = new Map<string, Json>(coverage.map((c) => [c.parameter_code, c]));
  const finalized = process.status === "FINALIZED";
  const version = protocol?.version ?? null;
  const matrixVersion = protocol?.matrix_version ?? null;

  // ---- раздел 1: статус загрузки ----
  const stageFiles: Json = report.stage_files ?? {};
  const uploadStatus: string[] = Array.isArray(process.upload_status) ? process.upload_status : [];
  const rejectedFiles = files.filter((f) => f.status === "REJECTED");
  const stages = STAGES.map((stage) => {
    const status = uploadStatus.find((s) => s.startsWith(`${stage}_`)) ?? `${stage}_MISSING`;
    const counts = stageFiles[stage] ?? {};
    const accepted = Number(counts.accepted ?? files.filter((f) => f.status === "ACCEPTED" && f.doc_stage === stage).length);
    const rejected = Number(counts.rejected ?? 0);
    const state = status.slice(stage.length + 1);
    const codes = Object.entries((counts.reject_codes ?? {}) as Record<string, number>)
      .map(([code, n]) => `${code} — ${n}`)
      .join(", ");
    const comment =
      state === "MISSING"
        ? rejected
          ? `Ни один файл не принят (${codes})`
          : "Документы стадии не загружены"
        : state === "PARTIAL"
          ? `Не приняты ${rejected} из ${accepted + rejected}: ${codes}`
          : "Все файлы приняты";
    return {
      stage,
      name: STAGE_NAME[stage],
      status,
      status_text: state === "UPLOADED" ? "Полностью" : state === "PARTIAL" ? "Частично" : "Не загружена",
      files_accepted: accepted,
      files_expected: accepted + rejected,
      files_rejected: rejected,
      signatures_skipped: Number(counts.signatures ?? 0),
      comment,
    };
  });

  // ---- записи и их статусы ----
  const rows = findings.filter((r) => r.verification_status !== "SPLIT");
  const records = rows.map((row) => ({ row, record: recordView(row, catalog) }));
  const by = (status: string) => records.filter((x) => x.record.status === status).map((x) => x.record);
  // Сводка по параметрам и разделам — только о Матрице. Гипотеза свободного поиска в неё
  // не входит и после подтверждения: параметра Матрицы у неё нет, она считается записью.
  const matrixRecords = records.filter((x) => !isFreeSearch(x.row));

  // ---- раздел 2: сводка по параметрам Матрицы и по записям ----
  // Параметр относится ровно к одной группе, и группы в сумме дают все 132: не проверен,
  // сопоставлен (хотя бы одна запись сравнена), несопоставим или без доказательств.
  const total = coverage.length || 132;
  const params = parameterGroups(coverage, matrixRecords);
  const countParams = (pred: (p: (typeof params)[number]) => boolean) => params.filter(pred).length;
  const summaryParams = [
    { key: "TOTAL", label: "Всего параметров в Матрице", count: total },
    { key: "COMPARED", label: "Выполнено сопоставление актуальных редакций", count: countParams((p) => p.group === "COMPARED") },
    {
      key: "CONFIRMED_VIOLATION", label: "в том числе с подтверждённым нарушением",
      count: countParams((p) => p.statuses.includes("CONFIRMED_VIOLATION")),
    },
    {
      key: "CANDIDATE", label: "в том числе с кандидатом, ожидающим решения",
      count: countParams((p) => p.statuses.includes("CANDIDATE")),
    },
    { key: "MISSING_EVIDENCE", label: "Нет документа или доказательного фрагмента", count: countParams((p) => p.group === "MISSING_EVIDENCE") },
    { key: "NOT_COMPARABLE", label: "Источники нельзя сопоставить", count: countParams((p) => p.group === "NOT_COMPARABLE") },
    // строка — только если такие параметры есть
    ...(countParams((p) => p.group === "NOT_APPLICABLE")
      ? [{
          key: "NOT_APPLICABLE", label: "Неприменимо к объекту",
          count: countParams((p) => p.group === "NOT_APPLICABLE"),
        }]
      : []),
    { key: "NOT_CHECKED", label: "Не проверено", count: countParams((p) => p.group === "NOT_CHECKED") },
    // строка — только если такие параметры есть: у протокола на старых правилах её нет
    ...(countParams((p) => p.group === "OUT_OF_SCOPE")
      ? [{
          key: "OUT_OF_SCOPE", label: "Не проверяется по документам: внешние системы или отказ по замеру",
          count: countParams((p) => p.group === "OUT_OF_SCOPE"),
        }]
      : []),
    ...(countParams((p) => p.group === "HYPOTHESIS")
      ? [{
          key: "HYPOTHESIS", label: "Проверяется черновиком правила: нарушения — гипотезы до решения специалиста",
          count: countParams((p) => p.group === "HYPOTHESIS"),
        }]
      : []),
  ].map((r) => ({ ...r, percent: percent(r.count, total) }));
  const recordCount = (status: string) => by(status).length;
  const summaryRecords = [
    { key: "NEGATIVE_VERIFIED", label: "NEGATIVE_VERIFIED — проверено, расхождения нет", count: recordCount("NEGATIVE_VERIFIED"), in_total: false },
    { key: "CANDIDATE", label: "CANDIDATE — ожидает решения инспектора", count: recordCount("CANDIDATE"), in_total: false },
    { key: "CONFIRMED_VIOLATION", label: "CONFIRMED_VIOLATION — подтверждено инспектором", count: recordCount("CONFIRMED_VIOLATION"), in_total: true },
    { key: "CLARIFICATION_REQUIRED", label: "CLARIFICATION_REQUIRED — требует уточнения", count: recordCount("CLARIFICATION_REQUIRED"), in_total: false },
    { key: "MISSING_EVIDENCE", label: "MISSING_EVIDENCE — нет документа или фрагмента", count: recordCount("MISSING_EVIDENCE"), in_total: false },
    { key: "NOT_COMPARABLE", label: "NOT_COMPARABLE — источники несопоставимы", count: recordCount("NOT_COMPARABLE"), in_total: false },
    { key: "SUSPICION", label: "SUSPICION — вне итогов нарушений", count: recordCount("SUSPICION"), in_total: false },
  ];
  // Те же группы параметров и статусы записей по разделам Матрицы, в порядке каталога
  const sectionNames = [...new Set(
    [...params].sort((a, b) => Number(a.param.parameter_id ?? 0) - Number(b.param.parameter_id ?? 0))
      .map((p) => String(p.param.section ?? "—")),
  )];
  const summarySections = sectionNames.map((section) => {
    const inSection = params.filter((p) => String(p.param.section ?? "—") === section);
    const codes = new Set(inSection.map((p) => p.param.parameter_code));
    const statuses = matrixRecords.filter((x) => codes.has(x.row.parameter_code)).map((x) => x.record.status);
    const groupCount = (group: string) => inSection.filter((p) => p.group === group).length;
    const recordsWith = (...wanted: string[]) => statuses.filter((s) => wanted.includes(s)).length;
    return {
      section,
      parameters: inSection.length,
      implemented: inSection.filter((p) => p.param.implemented).length,
      compared: groupCount("COMPARED"),
      missing_evidence: groupCount("MISSING_EVIDENCE"),
      not_comparable: groupCount("NOT_COMPARABLE"),
      not_checked: groupCount("NOT_CHECKED"),
      not_applicable: groupCount("NOT_APPLICABLE"),
      out_of_scope: groupCount("OUT_OF_SCOPE"),
      hypothesis: groupCount("HYPOTHESIS"),
      records: statuses.length,
      negatives: recordsWith("NEGATIVE_VERIFIED"),
      candidates: recordsWith("CANDIDATE", "CLARIFICATION_REQUIRED"),
      confirmed: recordsWith("CONFIRMED_VIOLATION"),
    };
  });

  // ---- исполнительная документация (#42): параметры без значения ИД перечислены отдельно ----
  const withId = coverage.filter((p) => p.id_status !== undefined);
  const notFound = withId.filter((p) => p.id_status === "NOT_FOUND");
  const isCommissioning = (p: Json) => typeof p.id_reason === "string" && p.id_reason.startsWith("источник в ИД — документ ввода");
  const idCoverage = withId.length === 0 ? null : {
    found: withId.filter((p) => p.id_status === "FOUND").length,
    not_found: notFound.length,
    // источник в ИД — документ ввода в эксплуатацию: у строящегося объекта его нет, это не пробел комплекта (Д-57)
    not_found_commissioning: notFound.filter(isCommissioning).length,
    parameters_without_id: notFound
      .map((p) => ({ parameter_code: p.parameter_code, parameter_name: p.parameter_name, reason: p.id_reason ?? null })),
  };

  // ---- таблица 1: комплектность и сопоставимость ----
  const completeness: Json[] = [];
  for (const stage of stages) {
    if (stage.status.endsWith("_MISSING")) {
      completeness.push({
        kind: "STAGE", stage: stage.stage, parameter_code: null, parameter_name: stage.name, location: null,
        status: "MISSING_EVIDENCE", reason: `${stage.name} не загружена: сравнение с этой стадией не выполнено`,
      });
    }
  }
  for (const { record } of records) {
    if (record.status === "MISSING_EVIDENCE" || record.status === "NOT_COMPARABLE") {
      completeness.push({
        kind: "RECORD", finding_id: record.finding_id, parameter_code: record.parameter_code,
        parameter_name: record.parameter_name, section: record.section, location: record.location,
        pd_value: record.pd_value, rd_value: record.rd_value, status: record.status,
        reason: record.completeness_reason ?? record.deviation,
      });
    }
  }
  for (const { param, group } of params) {
    // неприменимый параметр — со своим статусом и причиной по объекту, есть правило или нет
    if (group === "NOT_APPLICABLE") {
      completeness.push({
        kind: "PARAMETER", parameter_code: param.parameter_code, parameter_name: param.parameter_name,
        section: param.section, location: null, status: "NOT_APPLICABLE", reason: param.reason,
      });
    } else if (param.implemented && param.findings?.length === 0) {
      completeness.push({
        kind: "PARAMETER", parameter_code: param.parameter_code, parameter_name: param.parameter_name,
        section: param.section, location: null, status: "MISSING_EVIDENCE", reason: param.reason,
      });
    }
  }
  // Причина непроверенного параметра — одна для всех: у правила без реализации в файле
  // правил лежит заметка разработчика о том, почему его нет («текстом встречается на Речникове
  // на 7 страницах»). Она про корпус, а не про этот объект, и в протокол объекта не идёт (#83).
  // У параметра вне проверки причина своя и про сам параметр, а не про корпус: её и показываем
  const outOfScope = params
    .filter((p) => p.group === "OUT_OF_SCOPE")
    .map(({ param }) => ({
      parameter_code: param.parameter_code, parameter_name: param.parameter_name, section: param.section,
      queue: param.queue, criticality: param.criticality, kind: param.out_of_scope ?? null, reason: param.reason ?? null,
    }));
  // параметры, которые проверяет черновик правила (#95): что черновик нашёл — словами
  const hypothesisParams = params
    .filter((p) => p.group === "HYPOTHESIS")
    .map(({ param }) => ({
      parameter_code: param.parameter_code, parameter_name: param.parameter_name, section: param.section,
      queue: param.queue, criticality: param.criticality, found: param.hypothesis ?? null, reason: param.reason ?? null,
    }));
  const notChecked = params
    .filter((p) => p.group === "NOT_CHECKED")
    .map(({ param }) => ({
      parameter_code: param.parameter_code, parameter_name: param.parameter_name, section: param.section,
      queue: param.queue, criticality: param.criticality, reason: NOT_CHECKED_REASON,
    }));

  // ---- таблица 2: кандидаты по уровню риска ----
  const candidates = records
    .filter((x) => x.record.status === "CANDIDATE" || x.record.status === "CLARIFICATION_REQUIRED")
    .map((x) => x.record);
  const risk = (level: string) => candidates.filter((c) => c.review_priority === level);

  // ---- раздел 7: резолютивная часть ----
  const confirmed = by("CONFIRMED_VIOLATION");
  const resolution = finalized
    ? {
        available: true,
        note: "Включены только нарушения, подтверждённые инспектором. Действие определяет инспектор в пределах полномочий.",
        high: confirmed.filter((c) => c.review_priority === "HIGH"),
        medium: confirmed.filter((c) => c.review_priority !== "HIGH"),
      }
    : {
        available: false,
        note: "Не формируется до финализации. В финализированный протокол включаются только нарушения, подтверждённые инспектором.",
        high: [],
        medium: [],
      };

  const cards = records
    .filter((x) => x.record.status !== "SUSPICION")
    .map((x) => evidenceCard(x.row, x.record, matrixVersion));

  const status = PROTOCOL_STATUS[process.status] ?? { code: process.status, text: process.status };
  return {
    document: "PROTOCOL_OF_AUTOMATED_CHECK",
    title: "Протокол автоматизированной сверки",
    number: version ? `${process.object_id}-${String(process.id).slice(0, 8)}-v${version}` : null,
    generated_at: (input.generatedAt ?? new Date()).toISOString(),
    object: {
      object_id: process.object_id,
      name: object?.name ?? process.object_id,
      address: object?.address ?? null,
      customer: object?.customer ?? null,
      contractor: object?.contractor ?? null,
      permit_number: object?.permit_number ?? null,
    },
    protocol: {
      version,
      preliminary: !finalized,
      status: status.code,
      status_text: status.text,
      process_status: process.status,
      created_at: iso(protocol?.created_at),
      finalized_at: iso(process.finalized_at),
      reupload_allowed: !finalized,
      sync: input.sync ?? null,
    },
    traceability: {
      process_id: process.id,
      matrix_version: matrixVersion,
      dataset_version: protocol?.dataset_version ?? null,
      model_version: protocol?.model_version ?? null,
      run_timestamp: report.run_timestamp ?? iso(protocol?.created_at),
      input_manifest_sha256: protocol?.input_manifest_hash ?? null,
    },
    section_1_upload: {
      scenario: process.scenario ?? null,
      scenario_text: scenarioText(process.scenario ?? null, stages),
      stages,
      rejected_files: rejectedFiles.map((f) => ({
        relative_path: f.relative_path, reject_code: f.reject_code, message: f.reject_message,
      })),
      // готовность объекта (#39): на что опирается вывод — сколько страниц прочитано,
      // сколько файлов осталось без стадии и раздела, включались ли распознавание и модель
      readiness: report.readiness ?? null,
      // дозагрузка не пересчитывает объект заново (#60): сколько записей пересчитано,
      // а сколько перенесено из прошлой версии вместе с решениями инспектора
      recompute: report.recompute ?? null,
      // файл сдачи организатору собирается по решениям инспектора (#63): сколько записей
      // в нём сейчас, сколько убрано отклонением и сколько добавлено подтверждённых гипотез
      submission: input.submission ?? null,
      comparison_note:
        "Правила Матрицы сравнивают проектную и рабочую документацию попарно; если загружена исполнительная " +
        "документация, построенное сверяется с рабочей стадией (или с проектной, когда рабочей нет), " +
        "и значение ИД показано в записи третьей колонкой (#42). Для парных правил стадия ИД не требуется.",
      // третий массив (#42): у каких параметров значение в исполнительной документации найдено,
      // а у каких она промолчала — по параметрам с записями, когда ИД загружена
      id_coverage: idCoverage,
    },
    section_2_summary: {
      parameters_total: total,
      parameters: summaryParams,
      records: summaryRecords,
      sections: summarySections,
    },
    tables: {
      completeness,
      candidates: { high: risk("HIGH"), medium: risk("MEDIUM"), low: risk("LOW") },
      confirmed,
      negatives: by("NEGATIVE_VERIFIED"),
      // вид, который специалист решил не показывать, — в конце таблицы гипотез (Р-108)
      hypotheses: records
        .filter((x) => x.record.status === "SUSPICION")
        .sort((a, b) => Number(a.row.body?.specialist?.verdict === "drop") - Number(b.row.body?.specialist?.verdict === "drop"))
        .map((x) => x.record),
    },
    not_checked: notChecked,
    out_of_scope: outOfScope,
    hypothesis_params: hypothesisParams,
    resolution,
    evidence_cards: cards,
    changes: report.changes ?? null,
    counting_rules: [
      { category: "Подтверждённые нарушения", rule: "Только CONFIRMED_VIOLATION после решения инспектора" },
      { category: "Предварительные кандидаты", rule: "Показываются отдельно; не суммируются с подтверждёнными" },
      { category: "Отсутствующие и непригодные документы", rule: "Показатель комплектности; не нарушение" },
      { category: "Проверенные отрицательные", rule: "Отдельный показатель качества и источник отрицательных примеров" },
      {
        category: "Гипотезы свободного поиска и черновиков правил",
        rule: "SUSPICION; не входят в итог до перевода в CANDIDATE и подтверждения. Взятая в кандидаты гипотеза " +
          "учитывается как CANDIDATE, подтверждённая — как CONFIRMED_VIOLATION. Гипотеза свободного поиска в сводку " +
          "по параметрам Матрицы не входит, гипотеза черновика относится к своему параметру",
      },
      { category: "Непроверенные параметры", rule: "NOT_CHECKED: значения не сопоставлялись; не нарушение и не отсутствие нарушения" },
      ...(params.some((p) => p.group === "NOT_APPLICABLE")
        ? [{
            category: "Неприменимые параметры",
            rule: "NOT_APPLICABLE: параметр не относится к объекту (причина — в таблице 1); не нарушение и не отсутствие нарушения",
          }]
        : []),
      ...(outOfScope.length
        ? [{
            category: "Параметры вне проверки документов",
            rule: "OUT_OF_SCOPE: проверяются во внешних системах стадии строительства или отказаны по замеру; правило не пишется",
          }]
        : []),
      ...(hypothesisParams.length
        ? [{
            category: "Параметры с черновиком правила",
            rule: "HYPOTHESIS: правило ждёт решения специалиста; его нарушения — гипотезы, «расхождения нет» не засчитывается",
          }]
        : []),
    ],
  };
}

export type ProtocolReport = ReturnType<typeof buildReport>;
