// Выгрузка протокола проверки объекта: JSON, PDF, XML. Задача #30.
import type { FastifyInstance, FastifyReply } from "fastify";
import { authenticate, bearer } from "../auth.js";
import { pool, type Queryable } from "../db.js";
import { ApiError } from "../errors.js";
import { loadProcess } from "../process.js";
import { buildReport, type ProtocolReport } from "../report.js";
import { buildDashboard, DASHBOARD_RESPONSE } from "../dashboard.js";
import { renderReportPdf } from "../report-pdf.js";
import { renderReportDocx } from "../report-docx.js";
import { errorResponses } from "../schemas.js";
import { decidedSubmission } from "../submission.js";
import { syncView } from "../sync.js";

const idParams = {
  type: "object",
  required: ["id"],
  properties: { id: { type: "string", format: "uuid" } },
};

export async function loadReport(db: Queryable, id: string): Promise<ProtocolReport> {
  const process = await loadProcess(db, id);
  const [objects, protocols, files, findings, sync] = await Promise.all([
    db.query("select * from objects where id = $1", [process.object_id]),
    db.query(
      `select version, status, matrix_version, dataset_version, model_version, input_manifest_hash,
              report, body, created_at
       from protocols where process_id = $1 order by version desc limit 1`,
      [id],
    ),
    db.query(
      "select relative_path, status, doc_stage, reject_code, reject_message from files where process_id = $1 order by relative_path",
      [id],
    ),
    db.query("select * from findings where process_id = $1 order by parameter_code, finding_id", [id]),
    syncView(db, id),
  ]);
  if (protocols.rows.length === 0) {
    throw new ApiError(404, "PROTOCOL_NOT_READY", "Протокол ещё не сформирован", { status: process.status });
  }
  // Чем файл сдачи организатору отличается от находок автоматики (#63): протокол
  // инспектора должен показывать это числом, а не только заголовками выгрузки.
  const body = protocols.rows[0].body ?? { checks: [] };
  const decided = await decidedSubmission(db, id, body, protocols.rows[0].report?.held_back_checks ?? null);
  return buildReport({
    submission: { checks: decided.body.checks.length, removed: decided.removed,
                  added: decided.added, undecided: decided.undecided },
    process,
    object: objects.rows[0] ?? {},
    protocol: protocols.rows[0],
    files: files.rows,
    findings: findings.rows,
    sync,
  });
}

/**
 * Данные для дашборда объекта (#83). Те же источники, что у протокола, но без того, что
 * дашборду не нужно: без тела протокола и доказательств записей. Полный /report весит
 * около 200 КБ и собирается до секунды; дашборд открывается кнопкой в реестре и должен
 * отвечать сразу.
 */
export async function loadDashboard(db: Queryable, id: string) {
  const process = await loadProcess(db, id);
  const [objects, protocols, files, findings, sync, versions] = await Promise.all([
    db.query("select * from objects where id = $1", [process.object_id]),
    db.query(
      `select version, status, matrix_version, dataset_version, model_version, input_manifest_hash,
              report, created_at
       from protocols where process_id = $1 order by version desc limit 1`,
      [id],
    ),
    db.query("select relative_path, status, doc_stage, reject_code, reject_message from files where process_id = $1", [id]),
    // из тела записи — только то, от чего зависит статус: свободный поиск, взятие в кандидаты,
    // комплектность; доказательства и значения дашборду не нужны
    db.query(
      `select id, finding_id, parameter_code, location, violation_label, verification_status, criticality,
              jsonb_build_object('matrix_scope', body->'matrix_scope', 'promoted_at', body->'promoted_at',
                                 'provisional', body->'provisional',
                                 'protocol', body->'protocol', 'origin', body->'origin') as body
       from findings where process_id = $1 order by parameter_code, finding_id`,
      [id],
    ),
    syncView(db, id),
    // ход автоматики по версиям протокола: считается в базе, отчёты версий целиком не читаются
    db.query(
      `select version, created_at, report->'findings' as records,
              coalesce((report->'labels'->>'VIOLATION_PRESENT')::int, 0) as candidates,
              (select count(*) from jsonb_array_elements(coalesce(report->'coverage', '[]'::jsonb)) c
                where c->>'status' = 'COMPLETE') as compared
       from protocols where process_id = $1 order by version`,
      [id],
    ),
  ]);
  if (protocols.rows.length === 0) {
    throw new ApiError(404, "PROTOCOL_NOT_READY", "Протокол ещё не сформирован", { status: process.status });
  }
  return buildDashboard({
    process,
    object: objects.rows[0] ?? {},
    protocol: protocols.rows[0],
    files: files.rows,
    findings: findings.rows,
    sync,
  }, versions.rows);
}

function filename(report: ProtocolReport, ext: string): string {
  const base = `protocol-${report.object.object_id}-v${report.protocol.version ?? 0}`.replace(/[^\w.-]+/g, "_");
  return `${base}.${ext}`;
}

function xmlEscape(value: string): string {
  return value.replace(/[<>&"']/g, (ch) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&apos;" })[ch]!);
}

/** Протокол в XML: тот же документ, что и JSON; элементы массивов — item. */
export function toXml(value: unknown, name = "protocol", indent = ""): string {
  const tag = /^[A-Za-z_][\w.-]*$/.test(name) ? name : "field";
  if (value === null || value === undefined) return `${indent}<${tag}/>\n`;
  if (Array.isArray(value)) {
    return `${indent}<${tag}>\n${value.map((item) => toXml(item, "item", `${indent}  `)).join("")}${indent}</${tag}>\n`;
  }
  if (typeof value === "object") {
    const inner = Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => toXml(item, key, `${indent}  `))
      .join("");
    return `${indent}<${tag}>\n${inner}${indent}</${tag}>\n`;
  }
  return `${indent}<${tag}>${xmlEscape(String(value))}</${tag}>\n`;
}

function attachment(reply: FastifyReply, name: string, type: string) {
  reply.header("content-type", type);
  reply.header("content-disposition", `attachment; filename="${name}"`);
  reply.header("cache-control", "no-store");
}

export async function reportRoutes(app: FastifyInstance): Promise<void> {
  app.get(
    "/api/v1/process/:id/summary",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Дашборд объекта: сводка протокола и карта 132 параметров",
        description:
          "Сводка последней версии протокола одним ответом: стадии, воронка по 132 параметрам Матрицы, " +
          "состояние каждого параметра для карты, разделы, записи по статусам, изменения к прошлой версии. " +
          "Числа строятся той же функцией, что раздел 2 протокола. Гипотезы свободного поиска в карту " +
          "Матрицы не входят (ТЗ 9.5), «нет доказательств» — не нарушение (ТЗ 9.3).",
        params: idParams,
        security: bearer,
        response: {
          200: DASHBOARD_RESPONSE,
          ...errorResponses,
        },
      },
    },
    async (request) => {
      const { id } = request.params as { id: string };
      return loadDashboard(pool, id);
    },
  );

  const description =
    "Документ для инспектора по образцу Приложения 2 к ТЗ: статус загрузки и тип проверки, сводка по 132 " +
    "параметрам Матрицы, пять таблиц (комплектность и сопоставимость, кандидаты по уровню риска, подтверждённые, " +
    "проверенные отрицательные, гипотезы), резолютивная часть после финализации, карточки доказательств с SHA-256, " +
    "редакциями и решениями, правила подсчёта. Решения инспектора берутся на момент запроса. Файл сдачи организатору " +
    "— отдельно, GET /api/v1/process/{id}/protocol.";

  app.get(
    "/api/v1/process/:id/report",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Протокол проверки объекта (JSON)",
        description,
        params: idParams,
        security: bearer,
        response: {
          200: {
            type: "object",
            required: ["document", "object", "protocol", "traceability", "section_1_upload", "section_2_summary", "tables", "evidence_cards"],
            additionalProperties: true,
            properties: {
              document: { type: "string" },
              number: { type: "string", nullable: true },
              object: { type: "object", additionalProperties: true },
              protocol: { type: "object", additionalProperties: true },
              traceability: { type: "object", additionalProperties: true },
              section_1_upload: { type: "object", additionalProperties: true },
              section_2_summary: { type: "object", additionalProperties: true },
              tables: { type: "object", additionalProperties: true },
              evidence_cards: { type: "array", items: { type: "object", additionalProperties: true } },
            },
          },
          ...errorResponses,
        },
      },
    },
    async (request) => loadReport(pool, (request.params as { id: string }).id),
  );

  app.get(
    "/api/v1/process/:id/report.pdf",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Протокол проверки объекта (PDF)",
        description,
        params: idParams,
        security: bearer,
        response: {
          200: { description: "PDF протокола", content: { "application/pdf": { schema: { type: "string", format: "binary" } } } },
          ...errorResponses,
        },
      },
    },
    async (request, reply) => {
      const report = await loadReport(pool, (request.params as { id: string }).id);
      const pdf = await renderReportPdf(report);
      attachment(reply, filename(report, "pdf"), "application/pdf");
      return reply.send(pdf);
    },
  );

  app.get(
    "/api/v1/process/:id/report.docx",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Протокол проверки объекта (DOCX)",
        description:
          description +
          " DOCX — то же содержание, что PDF (оба формата собираются из одних блоков), " +
          "в виде, который открывается и правится в Word: ТЗ, модуль 7, «экспорт протоколов в PDF, DOCX, XML».",
        params: idParams,
        security: bearer,
        response: {
          200: {
            description: "DOCX протокола",
            content: {
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
                schema: { type: "string", format: "binary" },
              },
            },
          },
          ...errorResponses,
        },
      },
    },
    async (request, reply) => {
      const report = await loadReport(pool, (request.params as { id: string }).id);
      const docx = await renderReportDocx(report);
      attachment(reply, filename(report, "docx"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
      return reply.send(docx);
    },
  );

  app.get(
    "/api/v1/process/:id/report.xml",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Протокол проверки объекта (XML)",
        description,
        params: idParams,
        security: bearer,
        response: {
          200: { description: "XML протокола", content: { "application/xml": { schema: { type: "string" } } } },
          ...errorResponses,
        },
      },
    },
    async (request, reply) => {
      const report = await loadReport(pool, (request.params as { id: string }).id);
      attachment(reply, filename(report, "xml"), "application/xml; charset=utf-8");
      return reply.send(`<?xml version="1.0" encoding="UTF-8"?>\n${toXml(report)}`);
    },
  );
}
