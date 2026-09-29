// Связи документов объекта (#82): карта объекта и контекст находки. Только чтение.
import type { FastifyInstance } from "fastify";
import { authenticate, bearer } from "../auth.js";
import { pool } from "../db.js";
import { ApiError } from "../errors.js";
import { findingContext, objectMap } from "../links.js";
import { loadProcess } from "../process.js";
import { errorResponses } from "../schemas.js";

const idParams = {
  type: "object",
  required: ["id"],
  properties: { id: { type: "string", format: "uuid" } },
};

// из записи — только то, от чего зависят связи и статус: доказательства без рамок и цитат
// длиннее нужного, локация, свободный поиск и взятие в кандидаты
const FINDING_COLUMNS = `
  id, finding_id, parameter_code, location, violation_label, verification_status, pd_value, rd_value,
  jsonb_build_object(
    'matrix_scope', body->'matrix_scope', 'promoted_at', body->'promoted_at', 'protocol', body->'protocol',
    'provisional', body->'provisional', 'title', body->'title', 'locations', body->'locations', 'location_type', body->'location_type',
    'id_value', body->'id_value',
    'evidence', (select coalesce(jsonb_agg(jsonb_build_object('stage', e->'stage', 'file_id', e->'file_id',
                                                             'pdf_page_number', e->'pdf_page_number',
                                                             'quote', left(e->>'quote', 240))), '[]'::jsonb)
                 from jsonb_array_elements(coalesce(body->'evidence', '[]'::jsonb)) e)
  ) as body`;

const FILE_COLUMNS = `file_id, relative_path, status, doc_stage, stage_manual, discipline, section_manual,
  document_code, revision, revision_status, revision_manual, chain_id, pdf_pages`;

const place = { type: "object", properties: { stage: { type: "string" }, section: { type: "string" } } };
const doc = {
  type: "object",
  additionalProperties: true,
  properties: {
    file_id: { type: "string" },
    name: { type: "string" },
    code: { type: "string", nullable: true },
    stage: { type: "string", nullable: true },
  },
};

export async function linksRoutes(app: FastifyInstance): Promise<void> {
  app.get(
    "/api/v1/process/:id/links",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Карта объекта: документы по стадиям и разделам, связи находок между стадиями",
        description:
          "Клетка — стадия и раздел, число документов в ней. Связь — находка, чьи доказательства лежат " +
          "в двух стадиях: из клетки одной стадии в клетку другой, с состоянием записи. Список findings — " +
          "такие находки, по ним открывается контекст. Считается на лету.",
        params: idParams,
        security: bearer,
        response: {
          200: {
            type: "object",
            required: ["stages", "mixed", "grid", "links", "findings"],
            properties: {
              stages: { type: "object", additionalProperties: { type: "integer" } },
              mixed: { type: "integer", description: "Смешанных комплектов РД и ИД: на карте они в колонке РД" },
              grid: {
                type: "array",
                items: { type: "object", properties: { stage: { type: "string" }, section: { type: "string" }, documents: { type: "integer" } } },
              },
              links: {
                type: "array",
                items: {
                  type: "object",
                  properties: { from: place, to: place, state: { type: "string" }, findings: { type: "integer" } },
                },
              },
              findings: {
                type: "array",
                items: {
                  type: "object",
                  properties: {
                    id: { type: "string" },
                    code: { type: "string", nullable: true },
                    title: { type: "string", nullable: true },
                    location: { type: "string", nullable: true },
                    state: { type: "string" },
                    stages: { type: "array", items: { type: "string" } },
                    cells: { type: "array", items: place },
                  },
                },
              },
            },
          },
          ...errorResponses,
        },
      },
    },
    async (request) => {
      const { id } = request.params as { id: string };
      await loadProcess(pool, id);
      const [files, findings] = await Promise.all([
        pool.query(`select ${FILE_COLUMNS} from files where process_id = $1`, [id]),
        pool.query(`select ${FINDING_COLUMNS} from findings where process_id = $1`, [id]),
      ]);
      return objectMap(files.rows, findings.rows);
    },
  );

  app.get(
    "/api/v1/process/:id/findings/:fid/context",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Контекст находки: документы по стадиям, та же проверка, помещения",
        description:
          "Документы доказательства по стадиям ПД, РД, ИД — страницы, цитата, редакция (заменённая — с указанием " +
          "актуальной); другие находки по тому же параметру; для находки по помещению — где ещё оно встречается. " +
          "Помещение с номером из одной-двух цифр или встречающееся больше чем в 8 документах связи не даёт " +
          "(cut = SHORT или TANGLED), заменённые редакции в связи не входят. rooms = null, пока протокол " +
          "не пересобран с индексом помещений.",
        params: {
          type: "object",
          required: ["id", "fid"],
          properties: { id: { type: "string", format: "uuid" }, fid: { type: "string", format: "uuid" } },
        },
        security: bearer,
        response: {
          200: {
            type: "object",
            required: ["finding", "stages", "same_parameter", "rooms_indexed"],
            properties: {
              finding: { type: "object", additionalProperties: true },
              stages: {
                type: "array",
                items: {
                  type: "object",
                  properties: {
                    stage: { type: "string" },
                    value: { type: "string", nullable: true },
                    documents: { type: "array", items: doc },
                  },
                },
              },
              same_parameter: {
                type: "object",
                properties: {
                  total: { type: "integer" },
                  items: { type: "array", items: { type: "object", additionalProperties: true } },
                },
              },
              rooms: {
                type: "array",
                nullable: true,
                items: {
                  type: "object",
                  properties: {
                    room: { type: "string" },
                    total: { type: "integer" },
                    cut: { type: "string", nullable: true, description: "SHORT — короткий номер, TANGLED — больше 8 документов" },
                    superseded_skipped: { type: "integer" },
                    documents: { type: "array", items: doc },
                  },
                },
              },
              rooms_indexed: { type: "boolean" },
            },
          },
          ...errorResponses,
        },
      },
    },
    async (request) => {
      const { id, fid } = request.params as { id: string; fid: string };
      await loadProcess(pool, id);
      const [target, files, findings, rooms] = await Promise.all([
        pool.query(`select ${FINDING_COLUMNS} from findings where process_id = $1 and id = $2`, [id, fid]),
        pool.query(`select ${FILE_COLUMNS} from files where process_id = $1`, [id]),
        pool.query(
          `select id, finding_id, parameter_code, location, violation_label, verification_status,
                  jsonb_build_object('matrix_scope', body->'matrix_scope', 'promoted_at', body->'promoted_at',
                                     'provisional', body->'provisional',
                                     'protocol', body->'protocol', 'locations', body->'locations') as body
           from findings where process_id = $1`,
          [id],
        ),
        pool.query(
          "select report->'rooms' as rooms from protocols where process_id = $1 order by version desc limit 1",
          [id],
        ),
      ]);
      if (target.rows.length === 0) {
        throw new ApiError(404, "FINDING_NOT_FOUND", `Записи ${fid} в процессе нет`);
      }
      const index = rooms.rows[0]?.rooms;
      return findingContext(target.rows[0], files.rows, findings.rows, index && typeof index === "object" ? index : null);
    },
  );
}
