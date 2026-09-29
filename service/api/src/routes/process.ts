import type { FastifyInstance } from "fastify";
import { authenticate, bearer, requireRole } from "../auth.js";
import { audit, notify, pool, withTransaction } from "../db.js";
import { ApiError } from "../errors.js";
import { findingCounts, isBusy, iso, loadProcess, statusView } from "../process.js";
import { config } from "../config.js";
import { publish } from "../queue.js";
import { blobKey, minio } from "../storage.js";
import { DOC_SECTIONS, DOC_STAGES, errorResponses, REASON_CODES } from "../schemas.js";
import { extensionOf, MEDIA_TYPES } from "../filecheck.js";
import { logView } from "../log.js";
import { datasetDecisions } from "../dataset.js";
import { decidedSubmission } from "../submission.js";
import { cancelSync, enqueueSync, retrySync, syncConfigured, syncView } from "../sync.js";
import { assertVerificationAllowed } from "../verification.js";
import { pairDetails, revisionIndex, type RevisionRow } from "../revisions.js";
import { findingView } from "../finding-view.js";

const idParams = {
  type: "object",
  required: ["id"],
  properties: { id: { type: "string", format: "uuid" } },
};

export async function processRoutes(app: FastifyInstance): Promise<void> {
  app.get(
    "/api/v1/process/:id/status",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Статус процесса проверки",
        description:
          "Pull-модель ТЗ: клиент опрашивает статус, пока он не станет READY. " +
          "Ход обработки — в processing и progress, сбой обработки — processing.state = FAILED.",
        params: idParams,
        security: bearer,
        response: { 200: { $ref: "ProcessStatus#" }, ...errorResponses },
      },
    },
    async (request) => statusView(pool, (request.params as { id: string }).id),
  );

  app.get(
    "/api/v1/process/:id/protocol",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Протокол в формате сдачи",
        description:
          "Последняя версия протокола или указанная в version. Прежние версии сохраняются: " +
          "дозагрузка пересобирает протокол с новым номером версии. Файл собирается по решениям " +
          "инспектора на момент запроса: отклонённая запись в него не идёт, подтверждённая " +
          "гипотеза свободного поиска идёт, записи без решения остаются. Сколько убрано, добавлено " +
          "и осталось без решения — в заголовках X-Checks-Rejected, X-Checks-Promoted, X-Checks-Undecided.",
        params: idParams,
        querystring: {
          type: "object",
          properties: { version: { type: "integer", minimum: 1 } },
        },
        security: bearer,
        response: { 200: { $ref: "Protocol#" }, ...errorResponses },
      },
    },
    async (request, reply) => {
      const { id } = request.params as { id: string };
      const { version } = request.query as { version?: number };
      const process = await loadProcess(pool, id);
      const { rows } = await pool.query(
        `select version, body, matrix_version, dataset_version, model_version, input_manifest_hash, created_at,
                report->'held_back_checks' as held_back
         from protocols where process_id = $1 ${version ? "and version = $2" : ""}
         order by version desc limit 1`,
        version ? [id, version] : [id],
      );
      if (rows.length === 0) {
        throw new ApiError(404, "PROTOCOL_NOT_READY",
          version ? `Версии протокола ${version} нет` : "Протокол ещё не сформирован",
          { status: process.status, processing_state: String(process.processing?.state ?? "IDLE") });
      }
      const row = rows[0];
      // Решения инспектора на момент запроса (#63): отклонённая запись из файла сдачи
      // уходит, подтверждённая гипотеза свободного поиска в него приходит. Записи без
      // решения остаются: до верификации файл сдачи не должен пустеть.
      const decided = await decidedSubmission(pool, id, row.body, row.held_back ?? null);
      reply.header("X-Protocol-Version", String(row.version));
      reply.header("X-Matrix-Version", row.matrix_version ?? "");
      reply.header("X-Dataset-Version", row.dataset_version ?? "");
      reply.header("X-Model-Version", row.model_version ?? "");
      reply.header("X-Input-Manifest-Hash", row.input_manifest_hash ?? "");
      reply.header("X-Checks-Rejected", String(decided.removed));
      reply.header("X-Checks-Promoted", String(decided.added));
      reply.header("X-Checks-Undecided", String(decided.undecided));
      return decided.body;
    },
  );

  app.get(
    "/api/v1/process/:id/log",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Журнал обработки объекта",
        description:
          "Как читали документы и что из этого вышло: способ чтения и модель, числа готовности, " +
          "версии протокола с изменениями, отклонённые файлы и все уведомления по процессу — " +
          "включая наблюдения о качестве разбора, которые не показываются на рабочем экране инспектора.",
        params: idParams,
        security: bearer,
        response: {
          200: {
            type: "object",
            required: ["process_id", "object_id", "runs", "notifications"],
            properties: {
              process_id: { type: "string" },
              object_id: { type: "string" },
              status: { type: "string" },
              processing: { $ref: "Processing#" },
              runs: {
                type: "array",
                items: {
                  type: "object",
                  required: ["version"],
                  additionalProperties: true,
                  properties: {
                    version: { type: "integer" },
                    created_at: { type: "string", nullable: true },
                    status: { type: "string" },
                    reading_mode: { type: "string", nullable: true },
                    model_name: { type: "string", nullable: true },
                    matrix_version: { type: "string", nullable: true },
                    model_version: { type: "string", nullable: true },
                    pages: { type: "integer", nullable: true },
                    findings: { type: "integer", nullable: true },
                    checks: { type: "integer", nullable: true },
                  },
                },
              },
              notifications: {
                type: "array",
                items: {
                  type: "object",
                  required: ["id", "level", "category", "message"],
                  properties: {
                    id: { type: "integer" },
                    role: { type: "string" },
                    level: { type: "string" },
                    category: { type: "string" },
                    message: { type: "string" },
                    created_at: { type: "string", nullable: true },
                  },
                },
              },
              rejected_files: {
                type: "array",
                items: {
                  type: "object",
                  required: ["code", "count"],
                  properties: {
                    code: { type: "string" },
                    count: { type: "integer" },
                    message: { type: "string", nullable: true },
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
      const process = await loadProcess(pool, id);
      const [protocols, notifications, rejected] = await Promise.all([
        pool.query(
          "select version, created_at, status, matrix_version, model_version, report from protocols where process_id = $1 order by version desc",
          [id],
        ),
        pool.query("select id, role, level, category, message, created_at from notifications where process_id = $1 order by created_at desc limit 200", [id]),
        pool.query(
          `select reject_code, min(reject_message) as reject_message, count(*)::int as count
             from files where process_id = $1 and status = 'REJECTED'
            group by reject_code order by count desc`,
          [id],
        ),
      ]);
      return logView(process, protocols.rows, notifications.rows, rejected.rows);
    },
  );

  app.get(
    "/api/v1/process/:id/files",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Файлы процесса: принятые и отклонённые",
        params: idParams,
        security: bearer,
        response: {
          200: {
            type: "object",
            required: ["process_id", "files"],
            properties: {
              process_id: { type: "string" },
              files: {
                type: "array",
                items: {
                  type: "object",
                  required: ["relative_path", "status"],
                  properties: {
                    relative_path: { type: "string" },
                    status: { type: "string", enum: ["ACCEPTED", "REJECTED"] },
                    reject_code: { type: "string", nullable: true },
                    reject_message: { type: "string", nullable: true },
                    sha256: { type: "string", nullable: true },
                    size_bytes: { type: "integer", nullable: true },
                    file_id: { type: "string", nullable: true },
                    doc_stage: { type: "string", nullable: true },
                    discipline: { type: "string", nullable: true },
                    pdf_pages: { type: "integer", nullable: true },
                    uploaded_at: { type: "string", format: "date-time" },
                    stage_manual: { type: "string", nullable: true, description: "стадия, заданная инспектором" },
                    section_manual: { type: "string", nullable: true },
                    manual_by: { type: "string", nullable: true },
                    manual_at: { type: "string", format: "date-time", nullable: true },
                    document_code: { type: "string", nullable: true },
                    revision: { type: "string", nullable: true, description: "отметка редакции из имени файла или штампа" },
                    chain_id: { type: "string", nullable: true, description: "цепочка редакций: общий у редакций одного документа" },
                    revision_status: {
                      type: "string", nullable: true,
                      description: "CURRENT, SUPERSEDED, DUPLICATE или CLARIFICATION_REQUIRED — актуальную редакцию не определить без человека",
                    },
                    revision_manual: { type: "boolean", nullable: true, description: "инспектор назвал этот файл актуальной редакцией" },
                    revision_manual_by: { type: "string", nullable: true },
                    revision_manual_at: { type: "string", format: "date-time", nullable: true },
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
      const { rows } = await pool.query(
        `select relative_path, status, reject_code, reject_message, file_hash, size_bytes, file_id,
                doc_stage, discipline, pdf_pages, uploaded_at, stage_manual, section_manual, manual_by, manual_at,
                document_code, revision, chain_id, revision_status, revision_manual, revision_manual_by, revision_manual_at
         from files where process_id = $1 order by relative_path`,
        [id],
      );
      return {
        process_id: id,
        files: rows.map((r) => ({
          relative_path: r.relative_path,
          status: r.status,
          reject_code: r.reject_code,
          reject_message: r.reject_message,
          sha256: r.file_hash,
          size_bytes: r.size_bytes === null ? null : Number(r.size_bytes),
          file_id: r.file_id,
          doc_stage: r.doc_stage,
          discipline: r.discipline,
          pdf_pages: r.pdf_pages,
          uploaded_at: iso(r.uploaded_at),
          stage_manual: r.stage_manual,
          section_manual: r.section_manual,
          manual_by: r.manual_by,
          manual_at: iso(r.manual_at),
          document_code: r.document_code,
          revision: r.revision,
          chain_id: r.chain_id,
          revision_status: r.revision_status,
          revision_manual: r.revision_manual,
          revision_manual_by: r.revision_manual_by,
          revision_manual_at: iso(r.revision_manual_at),
        })),
      };
    },
  );

  // Пара редакций в ответе: шапка общая у указателя и у подробностей (#81)
  const pairHead = {
    pair_id: { type: "string" },
    chain_id: { type: "string", nullable: true },
    stage_group: { type: "string", nullable: true, description: "PD или RD: у рабочей документации проверяется отметка изменения" },
    mark: { type: "string", nullable: true },
    old_file_id: { type: "string" },
    new_file_id: { type: "string" },
    old_revision: { type: "string", nullable: true },
    new_revision: { type: "string", nullable: true },
    old_document: { type: "string", nullable: true },
    new_document: { type: "string", nullable: true },
    counts: { type: "object", additionalProperties: { type: "integer" } },
    looks_like_revision: { type: "boolean", nullable: true },
    content_changed: { type: "integer", description: "страниц, где изменилось содержание" },
    service_only: { type: "integer", description: "страниц, где содержание не изменилось: только служебные поля, перенос строк или текст, сдвинувшийся на соседние страницы" },
    checked: { type: "boolean", description: "проверялась ли отметка изменения (только рабочая документация)" },
    introduced: { type: "array", items: { type: "integer" }, description: "номера изменений, появившиеся в новой редакции" },
    unmarked: { type: "integer", description: "листов, изменённых без отметки" },
  };

  app.get(
    "/api/v1/process/:id/revisions",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Что изменилось между редакциями: указатель",
        description:
          "Пары «прежняя → следующая редакция» из цепочек редакций и их страницы без подробностей: " +
          "статус страницы, изменилось ли содержание и отмечено ли изменение. По указателю " +
          "реестр файлов показывает, что изменилось, а карточка находки — менялся ли лист доказательства. " +
          "Подробности пары — GET /api/v1/process/{id}/files/{fileId}/changes.",
        params: idParams,
        security: bearer,
        response: {
          200: {
            type: "object",
            required: ["process_id", "pairs"],
            properties: {
              process_id: { type: "string" },
              pairs: {
                type: "array",
                items: {
                  type: "object",
                  properties: {
                    ...pairHead,
                    pages: {
                      type: "array",
                      items: {
                        type: "object",
                        properties: {
                          old_page: { type: "integer", nullable: true },
                          new_page: { type: "integer", nullable: true },
                          sheet: { type: "integer", nullable: true },
                          status: { type: "string", description: "CHANGED, ADDED, REMOVED, UNREADABLE" },
                          content_changed: { type: "boolean", nullable: true },
                          registration: {
                            type: "string", nullable: true,
                            description: "REGISTERED, UNREGISTERED, NOT_NEEDED, UNKNOWN; null — отметка не проверялась",
                          },
                        },
                      },
                    },
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
      const { rows } = await pool.query<RevisionRow>(
        `select pair_id, chain_id, stage_group, old_file_id, new_file_id, old_revision, new_revision, summary, pages
         from revision_changes where process_id = $1 order by stage_group desc nulls last, pair_id`,
        [id],
      );
      return { process_id: id, pairs: revisionIndex(rows) };
    },
  );

  app.get(
    "/api/v1/process/:id/files/:fileId/changes",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Что изменилось в этой редакции относительно предыдущей",
        description:
          "Пара редакций, где файл — новая редакция: страницы с тем, что изменилось, где на листе " +
          "(place.zones_old и place.zones_new — рамки в долях видимой страницы, Y сверху, как highlights " +
          "доказательств) и отмечено ли изменение (registration: REGISTERED — номер нового изменения в штампе " +
          "листа или в ведомости, UNREGISTERED — лист изменён без отметки, NOT_NEEDED — изменились только " +
          "служебные поля, UNKNOWN — ответа нет). rendered_old и rendered_new — есть ли картинки страниц " +
          "для сравнения (GET /api/v1/process/{id}/pages/{fileId}/{page}).",
        params: {
          type: "object",
          required: ["id", "fileId"],
          properties: {
            id: { type: "string", format: "uuid" },
            fileId: { type: "string", pattern: "^[A-Za-z0-9_-]{1,40}$" },
          },
        },
        security: bearer,
        response: {
          200: {
            type: "object",
            properties: {
              ...pairHead,
              pages: {
                type: "array",
                items: {
                  type: "object",
                  properties: {
                    old_page: { type: "integer", nullable: true },
                    new_page: { type: "integer", nullable: true },
                    sheet: { type: "integer", nullable: true },
                    old_sheet: {
                      type: "integer", nullable: true,
                      description: "номер листа прежней редакции: в записке страницы сдвигаются, лист 30 становится листом 32",
                    },
                    status: { type: "string" },
                    what: { type: "string", nullable: true },
                    content_changed: { type: "boolean", nullable: true },
                    numbers: { type: "array", items: { type: "string" } },
                    changes: { type: "array", items: { type: "object", additionalProperties: true } },
                    place: { type: "object", nullable: true, additionalProperties: true },
                    registration: { type: "object", nullable: true, additionalProperties: true },
                    rendered_old: { type: "boolean" },
                    rendered_new: { type: "boolean" },
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
      const { id, fileId } = request.params as { id: string; fileId: string };
      await loadProcess(pool, id);
      const { rows } = await pool.query<RevisionRow>(
        `select pair_id, chain_id, stage_group, old_file_id, new_file_id, old_revision, new_revision, summary, pages
         from revision_changes where process_id = $1 and new_file_id = $2 order by pair_id limit 1`,
        [id, fileId],
      );
      if (rows.length === 0) {
        throw new ApiError(404, "NO_PREVIOUS_REVISION",
          `У файла ${fileId} нет предыдущей редакции в цепочке, или разбор её ещё не сравнил`);
      }
      return pairDetails(rows[0]);
    },
  );

  app.post(
    "/api/v1/process/:id/files/:fileId/revision",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Назвать файл актуальной редакцией своей цепочки",
        description:
          "ТЗ 9.1: конфликт редакций система не решает, а отдаёт инспектору. " +
          "Инспектор называет актуальную редакцию; у остальных файлов той же цепочки выбор снимается. " +
          "Правка идёт в журнал аудита (FILE_REVISION_SET). Чтобы она попала в сравнение, после правок " +
          "нужен повторный разбор: POST /api/v1/process/{id}/start.",
        params: {
          type: "object",
          required: ["id", "fileId"],
          properties: { id: { type: "string", format: "uuid" }, fileId: { type: "string" } },
        },
        body: {
          type: "object",
          required: ["authoritative"],
          properties: {
            authoritative: { type: "boolean", description: "true — считать актуальной; false — снять выбор" },
            comment: { type: "string", maxLength: 1000 },
          },
          additionalProperties: false,
        },
        security: bearer,
        response: { 200: { type: "object", additionalProperties: true }, ...errorResponses },
      },
    },
    async (request) => {
      const { id, fileId } = request.params as { id: string; fileId: string };
      const { authoritative, comment } = request.body as { authoritative: boolean; comment?: string };
      return withTransaction(async (db) => {
        const process = await loadProcess(db, id, true);
        assertVerificationAllowed(process, "Выбор редакции");
        const { rows } = await db.query(
          `select id, relative_path, file_id, chain_id, revision_status, revision_manual from files
           where process_id = $1 and (file_id = $2 or relative_path = $2) for update`,
          [id, fileId],
        );
        const file = rows[0];
        if (!file) {
          throw new ApiError(404, "FILE_NOT_FOUND", `Файла ${fileId} в процессе нет`);
        }
        if (authoritative && !file.chain_id) {
          throw new ApiError(409, "NO_REVISION_CHAIN", "У файла нет цепочки редакций: разбор ещё не выполнен или файл в цепочку не входит");
        }
        let released: string[] = [];
        if (authoritative) {
          const { rows: others } = await db.query(
            `update files set revision_manual = null, revision_manual_by = null, revision_manual_at = null
             where process_id = $1 and chain_id = $2 and id <> $3 and revision_manual is true returning file_id`,
            [id, file.chain_id, file.id],
          );
          released = others.map((r) => r.file_id as string);
        }
        const { rows: updated } = await db.query(
          `update files set revision_manual_by = $3,
                  revision_manual_at = case when revision_manual is not distinct from $2 then revision_manual_at else now() end,
                  revision_manual = $2
           where id = $1
           returning relative_path, file_id, chain_id, revision_status, revision_manual, revision_manual_by, revision_manual_at`,
          [file.id, authoritative ? true : null, request.user.sub],
        );
        await audit(db, {
          userId: request.user.sub, action: "FILE_REVISION_SET", objectId: process.object_id, processId: id,
          details: {
            file_id: file.file_id, relative_path: file.relative_path, chain_id: file.chain_id,
            from: { authoritative: file.revision_manual === true, revision_status: file.revision_status },
            to: { authoritative, released },
            comment: comment ?? null,
          },
          ip: request.ip, userAgent: request.headers["user-agent"] ?? null,
        });
        const row = updated[0];
        return {
          relative_path: row.relative_path, file_id: row.file_id, chain_id: row.chain_id,
          revision_status: row.revision_status, revision_manual: row.revision_manual,
          revision_manual_by: row.revision_manual_by, revision_manual_at: iso(row.revision_manual_at),
          released,
          note: "Чтобы выбор попал в сравнение, запустите повторный разбор: POST /api/v1/process/{id}/start",
        };
      });
    },
  );

  app.get(
    "/api/v1/process/:id/findings",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Находки последней версии протокола с решениями инспектора",
        params: idParams,
        security: bearer,
        response: {
          200: {
            type: "object",
            required: ["process_id", "findings", "counts"],
            properties: {
              process_id: { type: "string" },
              protocol_version: { type: "integer", nullable: true },
              counts: { $ref: "FindingCounts#" },
              findings: { type: "array", items: { $ref: "Finding#" } },
            },
          },
          ...errorResponses,
        },
      },
    },
    async (request) => {
      const { id } = request.params as { id: string };
      await loadProcess(pool, id);
      const { rows } = await pool.query(
        `select * from findings where process_id = $1
         order by case verification_status when 'PENDING' then 0 when 'CLARIFICATION_REQUIRED' then 1
                    when 'CONFIRMED_VIOLATION' then 2 when 'NEGATIVE_VERIFIED' then 3 when 'SPLIT' then 5 else 4 end,
                  violation_label, parameter_code, location`,
        [id],
      );
      return {
        process_id: id,
        protocol_version: rows[0]?.protocol_version ?? null,
        counts: await findingCounts(pool, id),
        findings: rows.map(findingView),
      };
    },
  );

  app.get(
    "/api/v1/process/:id/text/:fileId",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Что система прочитала в файле",
        description:
          "Текст страниц файла в том виде, в каком его читали правила: у каждой страницы сказано, " +
          "чем она прочитана — текстовым слоем, распознаванием (TESSERACT) или моделью, — и какого " +
          "она вида. На сканах текст даёт распознавание, и по нему принимаются решения, " +
          "поэтому инспектор должен видеть его целиком, а не только в цитате доказательства. " +
          "Страницы отдаются по порядку, окном: from — номер первой страницы окна, limit — сколько.",
        params: {
          type: "object",
          required: ["id", "fileId"],
          properties: {
            id: { type: "string", format: "uuid" },
            fileId: { type: "string", pattern: "^[A-Za-z0-9_-]{1,40}$" },
          },
        },
        querystring: {
          type: "object",
          properties: {
            from: { type: "integer", minimum: 1, maximum: 100000, default: 1 },
            limit: { type: "integer", minimum: 1, maximum: 200, default: 25 },
          },
        },
        security: bearer,
        response: {
          200: {
            type: "object",
            required: ["file_id", "pages", "total_pages"],
            properties: {
              file_id: { type: "string" },
              relative_path: { type: "string" },
              total_pages: { type: "integer", description: "страниц с прочитанным текстом" },
              from: { type: "integer" },
              sources: {
                type: "object", additionalProperties: true,
                description: "сколько страниц каким источником прочитано: TEXT_LAYER, TESSERACT, UNION, MODEL, NONE",
              },
              pages: {
                type: "array",
                items: {
                  type: "object",
                  properties: {
                    page: { type: "integer" },
                    text_source: { type: "string", nullable: true },
                    kind: { type: "string", nullable: true },
                    quality: { type: "string", nullable: true },
                    chars: { type: "integer" },
                    text: { type: "string" },
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
      const { id, fileId } = request.params as { id: string; fileId: string };
      const { from = 1, limit = 25 } = request.query as { from?: number; limit?: number };
      await loadProcess(pool, id);
      const { rows } = await pool.query<{ file_hash: string; relative_path: string }>(
        "select file_hash, relative_path from files where process_id = $1 and file_id = $2 and status = 'ACCEPTED' limit 1",
        [id, fileId],
      );
      if (rows.length === 0) {
        throw new ApiError(404, "FILE_NOT_FOUND", `Файла ${fileId} в процессе нет`);
      }
      let body: string;
      try {
        const stream = await minio.getObject(config.s3.bucket, `texts/${rows[0].file_hash}.jsonl`);
        const chunks: Buffer[] = [];
        for await (const chunk of stream) chunks.push(chunk as Buffer);
        body = Buffer.concat(chunks).toString("utf-8");
      } catch {
        throw new ApiError(404, "TEXT_NOT_READ",
          `Файл ${fileId} ещё не прочитан: текст страниц появляется после разбора (POST /api/v1/process/{id}/start)`);
      }
      const all = body.split("\n").filter(Boolean).map((line) => JSON.parse(line) as Record<string, unknown>);
      const sources: Record<string, number> = {};
      for (const r of all) {
        const key = String(r.s ?? "NONE");
        sources[key] = (sources[key] ?? 0) + 1;
      }
      const window = all.filter((r) => Number(r.p) >= from).slice(0, limit);
      return {
        file_id: fileId,
        relative_path: rows[0].relative_path,
        total_pages: all.length,
        from,
        sources,
        pages: window.map((r) => ({
          page: Number(r.p),
          text_source: (r.s as string) ?? null,
          kind: (r.k as string) ?? null,
          quality: (r.q as string) ?? null,
          chars: String(r.t ?? "").length,
          text: String(r.t ?? ""),
        })),
      };
    },
  );

  app.get(
    "/api/v1/process/:id/pages/:fileId/:page",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Картинка страницы-доказательства",
        description:
          "JPEG видимой страницы (с учётом поворота), отрисованный воркером при сборке протокола. " +
          "Прямоугольники места лежат в доказательстве находки в долях этой картинки. " +
          "Отдаются только страницы файлов этого процесса.",
        params: {
          type: "object",
          required: ["id", "fileId", "page"],
          properties: {
            id: { type: "string", format: "uuid" },
            fileId: { type: "string", pattern: "^[A-Za-z0-9_-]{1,40}$" },
            page: { type: "integer", minimum: 1, maximum: 100000 },
          },
        },
        security: bearer,
        response: {
          200: {
            description: "JPEG страницы",
            content: { "image/jpeg": { schema: { type: "string", format: "binary" } } },
          },
          ...errorResponses,
        },
      },
    },
    async (request, reply) => {
      const { id, fileId, page } = request.params as { id: string; fileId: string; page: number };
      await loadProcess(pool, id);
      const { rows } = await pool.query<{ file_hash: string }>(
        "select file_hash from files where process_id = $1 and file_id = $2 and status = 'ACCEPTED' limit 1",
        [id, fileId],
      );
      if (rows.length === 0) {
        throw new ApiError(404, "FILE_NOT_FOUND", `Файла ${fileId} в процессе нет`);
      }
      const key = `renders/${rows[0].file_hash}/${page}.jpg`;
      try {
        const stream = await minio.getObject(config.s3.bucket, key);
        reply.header("content-type", "image/jpeg");
        reply.header("cache-control", "private, max-age=86400, immutable");
        return reply.send(stream);
      } catch {
        throw new ApiError(404, "PAGE_NOT_RENDERED",
          `Страница ${page} файла ${fileId} не отрисована: картинки готовятся для страниц-доказательств при сборке протокола`);
      }
    },
  );

  app.get(
    "/api/v1/process/:id/files/:fileId/source",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Исходный файл документа",
        description:
          "Файл, как он был загружен: инспектор открывает чертёж или том целиком, а не только " +
          "страницу-доказательство. Отдаются только принятые файлы этого процесса. " +
          "Заголовок Content-Disposition — inline: PDF открывается просмотрщиком браузера.",
        params: {
          type: "object",
          required: ["id", "fileId"],
          properties: {
            id: { type: "string", format: "uuid" },
            fileId: { type: "string", pattern: "^[A-Za-z0-9_-]{1,40}$" },
          },
        },
        security: bearer,
        response: {
          200: {
            description: "Файл как загружен",
            content: { "application/octet-stream": { schema: { type: "string", format: "binary" } } },
          },
          ...errorResponses,
        },
      },
    },
    async (request, reply) => {
      const { id, fileId } = request.params as { id: string; fileId: string };
      await loadProcess(pool, id);
      const { rows } = await pool.query<{ file_hash: string; relative_path: string; size_bytes: string | null }>(
        `select file_hash, relative_path, size_bytes from files
         where process_id = $1 and file_id = $2 and status = 'ACCEPTED' limit 1`,
        [id, fileId],
      );
      if (rows.length === 0) {
        throw new ApiError(404, "FILE_NOT_FOUND", `Файла ${fileId} в процессе нет`);
      }
      const name = rows[0].relative_path.split("/").pop() || fileId;
      try {
        const stream = await minio.getObject(config.s3.bucket, blobKey(rows[0].file_hash));
        reply.header("content-type", MEDIA_TYPES[extensionOf(name)] ?? "application/octet-stream");
        reply.header("content-disposition", `inline; filename*=UTF-8''${encodeURIComponent(name)}`);
        reply.header("cache-control", "private, max-age=86400, immutable");
        // Размер известен из реестра файлов: без него браузер не покажет ход загрузки,
        // а том проектной документации весит десятки мегабайт и идёт полминуты (#83).
        if (rows[0].size_bytes !== null) reply.header("content-length", String(rows[0].size_bytes));
        return reply.send(stream);
      } catch {
        throw new ApiError(404, "FILE_CONTENT_MISSING",
          `Содержимое файла ${fileId} в хранилище не найдено`);
      }
    },
  );

  app.post(
    "/api/v1/process/:id/files/:fileId/stage",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Задать стадию и раздел файла руками",
        description:
          "На чужом оформлении папок стадия угадывается неверно, и документ выпадает " +
          "из сравнения. Инспектор задаёт стадию (и при необходимости раздел) до сравнения; разбор " +
          "заданное руками не перезаписывает. Правка попадает в журнал аудита. Чтобы она попала " +
          "в протокол, после правок нужен повторный разбор: POST /api/v1/process/{id}/start. " +
          "Снятая правка оставляет стадию (раздел) пустой до повторного разбора, затем её определяет разбор.",
        params: {
          type: "object",
          required: ["id", "fileId"],
          properties: { id: { type: "string", format: "uuid" }, fileId: { type: "string" } },
        },
        body: {
          type: "object",
          properties: {
            doc_stage: { type: "string", enum: [...DOC_STAGES, ""], description: "пустая строка снимает правку: стадию снова определит разбор" },
            section: { type: "string", enum: [...DOC_SECTIONS, ""], description: "пустая строка снимает правку: раздел снова определит разбор" },
            comment: { type: "string", maxLength: 1000 },
          },
          additionalProperties: false,
        },
        security: bearer,
        response: { 200: { type: "object", additionalProperties: true }, ...errorResponses },
      },
    },
    async (request) => {
      const { id, fileId } = request.params as { id: string; fileId: string };
      const { doc_stage, section, comment } = request.body as { doc_stage?: string; section?: string; comment?: string };
      if (doc_stage === undefined && section === undefined) {
        throw new ApiError(400, "NOTHING_TO_SET", "Укажите стадию, раздел или оба поля");
      }
      return withTransaction(async (db) => {
        const process = await loadProcess(db, id, true);
        assertVerificationAllowed(process, "Правка стадии файла");
        const { rows } = await db.query(
          `select id, relative_path, file_id, doc_stage, discipline, stage_manual, section_manual
           from files where process_id = $1 and (file_id = $2 or relative_path = $2) for update`,
          [id, fileId],
        );
        const file = rows[0];
        if (!file) {
          throw new ApiError(404, "FILE_NOT_FOUND", `Файла ${fileId} в процессе нет`);
        }
        const stage = doc_stage === undefined ? file.stage_manual : doc_stage || null;
        const sect = section === undefined ? file.section_manual : section || null;
        const { rows: updated } = await db.query(
          // Кто и когда правил, меняется, только если ручное значение изменилось: повторный выбор того же
          // значения не делает файл «правкой после сборки протокола» в окне финализации, а пустой выбор
          // у файла без ручной правки не выдаёт его стадию за заданную вручную. Снятая правка возвращает
          // стадию и раздел разбору: ручное значение было записано и в doc_stage (discipline), поэтому
          // до повторного разбора они пусты, а не показывают снятое значение как действующее
          `update files set
                  manual_by = case when stage_manual is not distinct from $2 and section_manual is not distinct from $3
                                   then manual_by else $4 end,
                  manual_at = case when stage_manual is not distinct from $2 and section_manual is not distinct from $3
                                   then manual_at else now() end,
                  stage_manual = $2, section_manual = $3,
                  doc_stage = case when $2::text is null and stage_manual is not null then null
                                   else coalesce($2, doc_stage) end,
                  discipline = case when $3::text is null and section_manual is not null then null
                                    else coalesce($3, discipline) end
           where id = $1
           returning relative_path, file_id, doc_stage, discipline, stage_manual, section_manual, manual_by, manual_at`,
          [file.id, stage, sect, request.user.sub],
        );
        await audit(db, {
          userId: request.user.sub, action: "FILE_STAGE_SET", objectId: process.object_id, processId: id,
          details: {
            file_id: file.file_id, relative_path: file.relative_path,
            from: { stage: file.doc_stage, section: file.discipline },
            to: { stage, section: sect },
            comment: comment ?? null,
          },
          ip: request.ip, userAgent: request.headers["user-agent"] ?? null,
        });
        const row = updated[0];
        return {
          relative_path: row.relative_path, file_id: row.file_id, doc_stage: row.doc_stage,
          discipline: row.discipline, stage_manual: row.stage_manual, section_manual: row.section_manual,
          manual_by: row.manual_by, manual_at: iso(row.manual_at),
          rebuild_required: true,
        };
      });
    },
  );

  app.post(
    "/api/v1/process/:id/start",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Запустить разбор заново",
        description:
          "Нужен после сбоя обработки (processing.state = FAILED) или когда папка загружена пакетами " +
          "с final_batch=false и последний пакет не пришёл.",
        params: idParams,
        security: bearer,
        response: { 202: { $ref: "ProcessStatus#" }, 503: { $ref: "Error#" }, ...errorResponses },
      },
    },
    async (request, reply) => {
      const { id } = request.params as { id: string };
      await withTransaction(async (db) => {
        const process = await loadProcess(db, id, true);
        if (process.status === "FINALIZED") {
          throw new ApiError(409, "PROCESS_FINALIZED", "Протокол финализирован: повторный разбор невозможен");
        }
        if (isBusy(process)) {
          throw new ApiError(409, "PROCESS_BUSY", "Обработка уже идёт");
        }
        const { rows } = await db.query("select count(*) as n from files where process_id = $1 and status = 'ACCEPTED'", [id]);
        if (Number(rows[0].n) === 0) {
          throw new ApiError(409, "NO_FILES", "В процессе нет принятых файлов");
        }
        await db.query("update processes set processing = $2, updated_at = now() where id = $1", [
          id,
          JSON.stringify({ state: "QUEUED", step: "parse", attempt: 1, queued_at: new Date().toISOString() }),
        ]);
        await audit(db, { userId: request.user.sub, action: "PROCESSING_STARTED", objectId: process.object_id, processId: id, ip: request.ip });
      });
      try {
        await publish("parse", id, request.user.sub, request.id);
      } catch {
        await pool.query("update processes set processing = $2 where id = $1", [
          id,
          JSON.stringify({ state: "FAILED", step: "parse", error: "Очередь сообщений недоступна" }),
        ]);
        throw new ApiError(503, "QUEUE_UNAVAILABLE", "Очередь сообщений недоступна");
      }
      return reply.status(202).send(await statusView(pool, id));
    },
  );

  app.post(
    "/api/v1/process/:id/finalize",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Финализировать протокол",
        description:
          "ТЗ, раздел 9.3: финализация разрешена только после обработки всех кандидатов " +
          "(подтверждены, отклонены или переведены в CLARIFICATION_REQUIRED). После неё дозагрузка " +
          "и изменение решений невозможны.",
        params: idParams,
        security: bearer,
        response: { 200: { $ref: "ProcessStatus#" }, ...errorResponses },
      },
    },
    async (request) => {
      const { id } = request.params as { id: string };
      await withTransaction(async (db) => {
        const process = await loadProcess(db, id, true);
        if (process.status === "FINALIZED") {
          throw new ApiError(409, "PROCESS_FINALIZED", "Протокол уже финализирован");
        }
        if (!["READY", "VERIFYING", "COMPLETED"].includes(process.status) || isBusy(process)) {
          throw new ApiError(409, "PROTOCOL_NOT_READY", "Финализировать можно только сформированный протокол");
        }
        const counts = await findingCounts(db, id);
        if (counts.pending > 0) {
          throw new ApiError(409, "CANDIDATES_PENDING",
            `Не обработано кандидатов: ${counts.pending}. Подтвердите, отклоните или переведите их в уточнение`,
            { counts });
        }
        await db.query(
          "update processes set status = 'FINALIZED', finalized_at = now(), updated_at = now() where id = $1",
          [id],
        );
        const { rows: versions } = await db.query<{ version: number }>(
          `update protocols set status = 'PROTOCOL_FINALIZED', finalized_at = now()
           where process_id = $1 and version = (select max(version) from protocols where process_id = $1)
           returning version`,
          [id],
        );
        const version = versions[0]?.version ?? 0;
        // решения финализированного протокола входят в черновик набора примеров (ТЗ 9.4),
        // протокол — в очередь передачи в ИАИС «РиН» (ТЗ 9.6)
        const datasetItems = await datasetDecisions(db, id);
        await enqueueSync(db, id, version, request.user.sub);
        await audit(db, {
          userId: request.user.sub, action: "PROTOCOL_FINALIZED", objectId: process.object_id, processId: id,
          details: { counts, protocol_version: version, dataset_items: datasetItems, iais_sync: syncConfigured() ? "PENDING_SYNC" : "NOT_CONFIGURED" },
          ip: request.ip, userAgent: request.headers["user-agent"] ?? null,
        });
      });
      return statusView(pool, id);
    },
  );

  app.post(
    "/api/v1/process/:id/unfinalize",
    {
      preHandler: [authenticate, requireRole("admin")],
      schema: {
        tags: ["process"],
        summary: "Отменить финализацию (администратор)",
        description: "ТЗ, раздел 9.3: только администратор, причина обязательна, протокол возвращается в COMPLETED.",
        params: idParams,
        body: {
          type: "object",
          required: ["reason"],
          properties: { reason: { type: "string", minLength: 5 } },
          additionalProperties: false,
        },
        security: bearer,
        response: { 200: { $ref: "ProcessStatus#" }, ...errorResponses },
      },
    },
    async (request) => {
      const { id } = request.params as { id: string };
      const { reason } = request.body as { reason: string };
      await withTransaction(async (db) => {
        const process = await loadProcess(db, id, true);
        if (process.status !== "FINALIZED") {
          throw new ApiError(409, "NOT_FINALIZED", "Протокол не финализирован");
        }
        await db.query(
          "update processes set status = 'COMPLETED', finalized_at = null, updated_at = now() where id = $1",
          [id],
        );
        await db.query(
          `update protocols set status = 'VERIFICATION_COMPLETED', finalized_at = null
           where process_id = $1 and version = (select max(version) from protocols where process_id = $1)`,
          [id],
        );
        await cancelSync(db, id);
        // решения процесса выходят из черновика набора; выпущенные версии не меняются
        const dropped = await datasetDecisions(db, id);
        await audit(db, {
          userId: request.user.sub, action: "PROTOCOL_UNFINALIZED", objectId: process.object_id, processId: id,
          details: { reason, dataset_draft_removed: dropped }, ip: request.ip, userAgent: request.headers["user-agent"] ?? null,
        });
        await notify(db, "inspector", "WARNING", `Финализация протокола отменена администратором: ${reason}`, id);
      });
      return statusView(pool, id);
    },
  );

  app.post(
    "/api/v1/process/:id/sync",
    {
      preHandler: [authenticate, requireRole("admin")],
      schema: {
        tags: ["process"],
        summary: "Повторить передачу протокола в ИАИС «РиН» (администратор)",
        description:
          "ТЗ 9.6: передаётся только финализированный протокол. Нужна, когда автоматические повторы исчерпаны " +
          "или внешняя система отклонила запрос; счётчик попыток начинается заново.",
        params: idParams,
        security: bearer,
        response: { 202: { $ref: "ProcessStatus#" }, ...errorResponses },
      },
    },
    async (request, reply) => {
      const { id } = request.params as { id: string };
      await withTransaction(async (db) => {
        const process = await loadProcess(db, id, true);
        if (process.status !== "FINALIZED") {
          throw new ApiError(409, "NOT_FINALIZED", "В ИАИС «РиН» передаётся только финализированный протокол");
        }
        if (!syncConfigured()) {
          throw new ApiError(409, "IAIS_NOT_CONFIGURED", "Адрес ИАИС «РиН» не задан: переменная IAIS_URL");
        }
        const current = await syncView(db, id);
        if (current?.status === "SYNCED") {
          throw new ApiError(409, "ALREADY_SYNCED", "Протокол уже передан в ИАИС «РиН»");
        }
        if (!(await retrySync(db, id))) {
          const { rows } = await db.query<{ version: number }>("select max(version) as version from protocols where process_id = $1", [id]);
          await enqueueSync(db, id, rows[0]?.version ?? 0, request.user.sub);
        }
        await audit(db, {
          userId: request.user.sub, action: "IAIS_RETRY_REQUESTED", objectId: process.object_id, processId: id,
          ip: request.ip, userAgent: request.headers["user-agent"] ?? null,
        });
      });
      return reply.status(202).send(await statusView(pool, id));
    },
  );

  app.get(
    "/api/v1/processes",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["process"],
        summary: "Процессы проверки, последние сверху",
        querystring: {
          type: "object",
          properties: {
            object_id: { type: "string" },
            limit: { type: "integer", minimum: 1, maximum: 200, default: 50 },
          },
        },
        security: bearer,
        response: {
          200: {
            type: "object",
            required: ["processes"],
            properties: { processes: { type: "array", items: { $ref: "ProcessStatus#" } } },
          },
          ...errorResponses,
        },
      },
    },
    async (request) => {
      const { object_id, limit } = request.query as { object_id?: string; limit: number };
      const { rows } = await pool.query<{ id: string }>(
        `select id from processes ${object_id ? "where object_id = $2" : ""} order by created_at desc limit $1`,
        object_id ? [limit, object_id] : [limit],
      );
      const processes = [];
      for (const row of rows) {
        processes.push(await statusView(pool, row.id));
      }
      return { processes };
    },
  );
}

export { REASON_CODES };
