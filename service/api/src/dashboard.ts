// Дашборд объекта (#83): сводка протокола одним экраном — стадии, воронка по 132 параметрам,
// карта Матрицы по параметрам, разделы, решения и изменения к прошлой версии. Все числа
// берутся из того же построения, что протокол (buildReport, parameterGroups): карточка
// и PDF-протокол не могут разойтись.
import { buildReport, findingStatus, isFreeSearch, parameterGroups, type ReportInput } from "./report.js";

type Json = Record<string, any>;

/**
 * Состояния клетки карты. Группы протокола уточнены: «сопоставлен» делится на нарушение,
 * кандидата и «без замечаний». Уточнение не меняет групп: сумма по группам та же, что
 * в разделе 2 протокола, и клеток ровно столько, сколько параметров в Матрице.
 * Из этого же списка — перечень в схеме ответа: новое состояние не разойдётся со схемой,
 * по которой стенд проверяет ответ.
 */
export const CELL_STATES = [
  "VIOLATION",
  "CANDIDATE",
  "CLEAN",
  "NOT_COMPARABLE",
  "MISSING_EVIDENCE",
  "NOT_APPLICABLE",
  "NOT_CHECKED",
  "OUT_OF_SCOPE",
  "HYPOTHESIS",
] as const;

export type CellState = (typeof CELL_STATES)[number];

const countSchema = { type: "integer" };

/**
 * Схема ответа GET /process/{id}/summary. Стенд сверяет с ней каждый ответ
 * (@fastify/response-validation), а поле, которого в ней нет, сериализатор выбрасывает молча:
 * новое поле сводки или состояние клетки — сразу сюда.
 */
export const DASHBOARD_RESPONSE = {
  type: "object",
  required: ["process_id", "object_id", "matrix", "cells"],
  properties: {
    process_id: { type: "string" },
    object_id: { type: "string" },
    object_name: { type: "string" },
    protocol: { type: "object", additionalProperties: true },
    scenario_text: { type: "string", nullable: true },
    stages: { type: "array", items: { type: "object", additionalProperties: true } },
    matrix: {
      type: "object",
      required: ["total", "compared", "missing_evidence", "not_comparable", "not_checked"],
      properties: {
        total: countSchema, compared: countSchema, with_violation: countSchema, with_candidate: countSchema,
        missing_evidence: countSchema, not_comparable: countSchema, not_checked: countSchema, not_applicable: countSchema,
        out_of_scope: countSchema, hypothesis: countSchema,
      },
    },
    records: { type: "object", additionalProperties: { type: "integer" } },
    sections: { type: "array", items: { type: "object", additionalProperties: true } },
    changes: {
      type: "object",
      nullable: true,
      properties: {
        added: countSchema, changed: countSchema, removed: countSchema,
        decided_changed: { type: "array", items: { type: "string" } },
      },
    },
    sync: { type: "object", nullable: true, properties: { status: { type: "string", nullable: true } } },
    history: {
      type: "array",
      items: {
        type: "object",
        properties: {
          version: countSchema,
          created_at: { type: "string", nullable: true },
          records: countSchema,
          candidates: countSchema,
          compared: countSchema,
        },
      },
    },
    cells: {
      type: "array",
      items: {
        type: "object",
        required: ["code", "state"],
        properties: {
          code: { type: "string" },
          id: { type: "integer", nullable: true },
          name: { type: "string", nullable: true },
          section: { type: "string", nullable: true },
          queue: { type: "integer", nullable: true },
          critical: { type: "boolean", nullable: true },
          state: {
            type: "string",
            enum: [...CELL_STATES],
          },
          group: { type: "string" },
          records: countSchema,
          reason: { type: "string", nullable: true },
          // у непроверенного параметра — пометка для инспектора: что нужно правилу и чего нет в пакете
          note: { type: "string", nullable: true },
          finding: { type: "string", nullable: true },
        },
      },
    },
  },
};

/** Какую запись открывать щелчком по клетке: сначала то, что требует внимания. */
const PICK_ORDER = ["CONFIRMED_VIOLATION", "CANDIDATE", "CLARIFICATION_REQUIRED", "NEGATIVE_VERIFIED", "NOT_COMPARABLE", "MISSING_EVIDENCE"];

function pick(rows: Json[]): Json | null {
  const ranked = rows
    .map((row) => ({ row, rank: PICK_ORDER.indexOf(findingStatus(row)) }))
    .sort((a, b) => (a.rank < 0 ? 99 : a.rank) - (b.rank < 0 ? 99 : b.rank));
  return ranked[0]?.row ?? null;
}

/**
 * Версии протокола объекта: что давала автоматика на каждой. Сопоставлено — параметров
 * со статусом COMPLETE в отчёте версии, кандидатов — записей с меткой нарушения до решений.
 * Решения инспектора по версиям не хранятся, поэтому их хода здесь нет.
 */
export interface VersionRow {
  version: number;
  created_at: string | Date | null;
  records: number | string | null;
  candidates: number | string | null;
  compared: number | string | null;
}

export function buildDashboard(input: ReportInput, versions: VersionRow[] = []) {
  const report = buildReport(input);
  const coverage: Json[] = Array.isArray(input.protocol?.report?.coverage) ? input.protocol!.report.coverage : [];
  const rows = input.findings.filter((r) => r.verification_status !== "SPLIT");
  const matrixRecords = rows
    .filter((row) => !isFreeSearch(row))
    .map((row) => ({ row, record: { status: findingStatus(row) } }));

  const cells = parameterGroups(coverage, matrixRecords).map(({ param, statuses, group, rows: mine }) => {
    const state: CellState =
      group === "COMPARED"
        ? statuses.includes("CONFIRMED_VIOLATION")
          ? "VIOLATION"
          : statuses.some((s) => s === "CANDIDATE" || s === "CLARIFICATION_REQUIRED")
            ? "CANDIDATE"
            : "CLEAN"
        : (group as CellState);
    const open = pick(mine);
    return {
      code: String(param.parameter_code),
      id: param.parameter_id ?? null,
      name: param.parameter_name ?? null,
      section: param.section ?? null,
      queue: param.queue ?? null,
      critical: typeof param.criticality === "string" ? param.criticality.startsWith("Критическое") : null,
      state,
      group,
      records: mine.length,
      // у непроверенного параметра в правилах лежит заметка разработки про корпус, а не про
      // этот объект: её не показываем (#83); у остальных причина своя — по этому объекту
      reason: group === "COMPARED" || group === "NOT_CHECKED" ? null : param.reason ?? null,
      // вместо заметки разработки — пометка для инспектора из правила (`inspector_note`): без привязки к корпусу
      note: group === "NOT_CHECKED" && typeof param.note === "string" ? param.note : null,
      finding: open?.id ?? null,
    };
  });

  // Изменения к прошлой версии: числа, а записи с ставшим неактуальным решением — ссылками
  const byFindingId = new Map<string, Json>(rows.map((r) => [String(r.finding_id), r]));
  const diff: Json | null = input.protocol?.report?.changes ?? null;
  const count = (key: string) => (Array.isArray(diff?.[key]) ? diff![key].length : 0);
  const stale: string[] = Array.isArray(diff?.decided_changed)
    ? diff!.decided_changed
        .map((c: Json) => byFindingId.get(String(c.finding_id))?.id)
        .filter((id: unknown): id is string => typeof id === "string")
    : [];

  const summary = report.section_2_summary;
  const param = (key: string) => summary.parameters.find((p) => p.key === key)?.count ?? 0;
  const record = (key: string) => summary.records.find((r) => r.key === key)?.count ?? 0;
  return {
    process_id: report.traceability.process_id,
    object_id: report.object.object_id,
    object_name: report.object.name,
    protocol: {
      version: report.protocol.version,
      status: report.protocol.status,
      status_text: report.protocol.status_text,
      preliminary: report.protocol.preliminary,
      created_at: report.protocol.created_at,
      finalized_at: report.protocol.finalized_at,
    },
    scenario_text: report.section_1_upload.scenario_text,
    stages: report.section_1_upload.stages.map((s) => ({
      stage: s.stage,
      name: s.name,
      status: s.status,
      status_text: s.status_text,
      files_accepted: s.files_accepted,
      files_expected: s.files_expected,
      files_rejected: s.files_rejected,
    })),
    matrix: {
      total: summary.parameters_total,
      compared: param("COMPARED"),
      with_violation: param("CONFIRMED_VIOLATION"),
      with_candidate: param("CANDIDATE"),
      missing_evidence: param("MISSING_EVIDENCE"),
      not_comparable: param("NOT_COMPARABLE"),
      not_checked: param("NOT_CHECKED"),
      out_of_scope: param("OUT_OF_SCOPE"),
      // проверяется черновиком правила (#95): нарушения — гипотезы до решения специалиста
      hypothesis: param("HYPOTHESIS"),
      not_applicable: param("NOT_APPLICABLE"),
    },
    records: {
      confirmed: record("CONFIRMED_VIOLATION"),
      // из них — гипотезы свободного поиска: в итог нарушений входят, на карте Матрицы их нет
      confirmed_free: rows.filter((r) => isFreeSearch(r) && findingStatus(r) === "CONFIRMED_VIOLATION").length,
      candidate: record("CANDIDATE"),
      clarification: record("CLARIFICATION_REQUIRED"),
      negative: record("NEGATIVE_VERIFIED"),
      missing_evidence: record("MISSING_EVIDENCE"),
      not_comparable: record("NOT_COMPARABLE"),
      suspicion: record("SUSPICION"),
    },
    sections: summary.sections,
    changes: diff
      ? { added: count("added"), changed: count("changed"), removed: count("removed"), decided_changed: stale }
      : null,
    sync: input.sync ? { status: input.sync.status ?? null } : null,
    history: versions.map((v) => ({
      version: Number(v.version),
      created_at: v.created_at ? new Date(v.created_at).toISOString() : null,
      records: Number(v.records ?? 0),
      candidates: Number(v.candidates ?? 0),
      compared: Number(v.compared ?? 0),
    })),
    cells,
  };
}

export type Dashboard = ReturnType<typeof buildDashboard>;
