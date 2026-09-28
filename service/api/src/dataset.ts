// Решения инспектора как версионированный набор примеров. Задача #34, ТЗ 9.4.
//
// Подтверждённые нарушения финализированных протоколов — положительные примеры, отклонённые
// кандидаты с кодом причины — отрицательные. Запросы уточнения, непроверенные записи
// и гипотезы в набор не входят.
//
// Черновик не хранится, а считается из решений финализированных протоколов: отмена
// финализации убирает решения процесса из черновика, новое решение после неё попадает
// туда при следующей финализации. Куратор выпускает версию — снимок черновика целиком
// с разницей к предыдущей версии. Строки версии не меняются, идентификатор версии — хеш
// состава, поэтому одинаковый состав всегда даёт одну и ту же версию.

import { createHash } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { authenticate, bearer, requireRole } from "./auth.js";
import { audit, pool, withTransaction, type Queryable } from "./db.js";
import { ApiError } from "./errors.js";
import { iso } from "./process.js";
import { errorResponses } from "./schemas.js";

export const DATASET_LABELS = ["CONFIRMED_VIOLATION", "NEGATIVE_VERIFIED"];

interface Item {
  finding_row_id: string;
  process_id: string;
  object_id: string;
  protocol_version: number;
  finding_id: string;
  parameter_code: string | null;
  location: string | null;
  gold_label: string;
  reason_code: string | null;
  comment: string | null;
  expert_id: string | null;
  decided_at: string | null;
  evidence: Record<string, unknown>[];
  card: Record<string, unknown>;
}

const keyOf = (i: Pick<Item, "process_id" | "finding_id">) => `${i.process_id}::${i.finding_id}`;

/** То, что определяет пример: метка, причина, версия протокола, решение и страницы доказательств. */
function fingerprint(i: Item): string {
  return JSON.stringify([
    i.gold_label, i.reason_code, i.protocol_version, i.decided_at,
    i.evidence.map((e) => [e.stage, e.file_id, e.pdf_page_number, e.sha256]),
  ]);
}

/** Решения процесса, которые попадают в черновик набора, пока протокол финализирован. */
export async function datasetDecisions(db: Queryable, processId: string): Promise<number> {
  const { rows } = await db.query<{ n: string }>(
    "select count(*) as n from findings where process_id = $1 and verification_status = any($2)",
    [processId, DATASET_LABELS],
  );
  return Number(rows[0]?.n ?? 0);
}

async function draftItems(db: Queryable): Promise<Item[]> {
  const { rows } = await db.query(
    `select f.id, f.process_id, p.object_id, f.protocol_version, f.finding_id, f.parameter_code, f.location,
            f.verification_status, f.reason_code, f.comment, f.decided_by, f.decided_at, f.pd_value, f.rd_value, f.body
     from findings f join processes p on p.id = f.process_id
     where p.status = 'FINALIZED' and f.verification_status = any($1)
     order by p.object_id, f.process_id, f.finding_id`,
    [DATASET_LABELS],
  );
  return rows.map((r) => {
    const body = r.body ?? {};
    return {
      finding_row_id: r.id,
      process_id: r.process_id,
      object_id: r.object_id,
      protocol_version: r.protocol_version,
      finding_id: r.finding_id,
      parameter_code: r.parameter_code,
      location: r.location,
      gold_label: r.verification_status,
      reason_code: r.reason_code,
      comment: r.comment,
      expert_id: r.decided_by,
      decided_at: iso(r.decided_at),
      evidence: Array.isArray(body.evidence) ? body.evidence : [],
      card: {
        expected_value: r.pd_value, actual_value: r.rd_value, rule_basis: body.extraction?.rule_basis ?? null,
        detail: body.extraction?.detail ?? null, comparison_result: body.comparison_result ?? null,
      },
    };
  });
}

async function versionItems(db: Queryable, version: string): Promise<Item[]> {
  const { rows } = await db.query(
    "select * from dataset_items where dataset_version = $1 order by object_id, process_id, finding_id",
    [version],
  );
  return rows.map((r) => ({
    finding_row_id: r.finding_row_id,
    process_id: r.process_id,
    object_id: r.object_id,
    protocol_version: r.protocol_version,
    finding_id: r.finding_id,
    parameter_code: r.parameter_code,
    location: r.location,
    gold_label: r.gold_label,
    reason_code: r.reason_code,
    comment: r.comment,
    expert_id: r.expert_id,
    decided_at: iso(r.decided_at),
    evidence: r.evidence ?? [],
    card: r.card ?? {},
  }));
}

async function latestVersion(db: Queryable): Promise<string | null> {
  const { rows } = await db.query<{ dataset_version: string }>(
    "select dataset_version from dataset_versions order by released_at desc limit 1",
  );
  return rows[0]?.dataset_version ?? null;
}

/** Черновик и его разница с последней выпущенной версией. */
async function draftView(db: Queryable) {
  const [items, base] = await Promise.all([draftItems(db), latestVersion(db)]);
  const previous = new Map((base ? await versionItems(db, base) : []).map((i) => [keyOf(i), i]));
  const current = new Set(items.map(keyOf));
  const marked = items.map((i) => {
    const before = previous.get(keyOf(i));
    return { ...i, change: !before ? "ADDED" : fingerprint(before) === fingerprint(i) ? "UNCHANGED" : "CHANGED" };
  });
  const removed = [...previous.values()].filter((i) => !current.has(keyOf(i))).map((i) => ({ ...i, change: "REMOVED" }));
  return { base, items: marked, removed };
}

function summary(items: Item[]) {
  const positives = items.filter((i) => i.gold_label === "CONFIRMED_VIOLATION").length;
  return {
    items: items.length,
    positives,
    negatives: items.length - positives,
    objects: [...new Set(items.map((i) => i.object_id))],
  };
}

function manifestOf(items: Item[]) {
  return items.map((i) => ({
    object_id: i.object_id, process_id: i.process_id, finding_id: i.finding_id, protocol_version: i.protocol_version,
    gold_label: i.gold_label, reason_code: i.reason_code, decided_at: i.decided_at,
    evidence: i.evidence.map((e) => [e.stage, e.file_id, e.pdf_page_number, e.sha256]),
  }));
}

const itemSchema = { type: "object", additionalProperties: true };
const versionSchema = {
  type: "object",
  required: ["dataset_version", "items", "positives", "negatives", "added", "changed", "removed", "objects", "manifest_sha256"],
  properties: {
    dataset_version: { type: "string" },
    items: { type: "integer" },
    positives: { type: "integer" },
    negatives: { type: "integer" },
    added: { type: "integer" },
    changed: { type: "integer" },
    removed: { type: "integer" },
    objects: { type: "array", items: { type: "string" } },
    manifest_sha256: { type: "string" },
    comment: { type: "string", nullable: true },
    released_by: { type: "string", nullable: true },
    released_at: { type: "string", format: "date-time", nullable: true },
    // отзыв версии (#74): запись остаётся, но в обучение такая версия не берётся
    withdrawn_at: { type: "string", format: "date-time", nullable: true },
    withdrawn_by: { type: "string", nullable: true },
    withdrawn_reason: { type: "string", nullable: true },
  },
};

export async function datasetRoutes(app: FastifyInstance): Promise<void> {
  app.get(
    "/api/v1/dataset",
    {
      preHandler: [authenticate, requireRole("admin")],
      schema: {
        tags: ["dataset"],
        summary: "Черновик набора или состав выпущенной версии (администратор)",
        description:
          "ТЗ 9.4: подтверждённые нарушения финализированных протоколов — положительные примеры, отклонённые " +
          "кандидаты с кодом причины — отрицательные. Без параметра — черновик: у каждой записи change " +
          "ADDED, CHANGED или UNCHANGED относительно последней версии, в removed — записи, которых в черновике " +
          "больше нет. С dataset_version — состав этой версии.",
        querystring: {
          type: "object",
          properties: { dataset_version: { type: "string" } },
          additionalProperties: false,
        },
        security: bearer,
        response: {
          200: {
            type: "object",
            required: ["source", "base_version", "counts", "items", "removed"],
            properties: {
              source: { type: "string", description: "DRAFT или идентификатор версии" },
              base_version: { type: "string", nullable: true },
              counts: {
                type: "object",
                required: ["items", "positives", "negatives", "added", "changed", "removed"],
                properties: {
                  items: { type: "integer" }, positives: { type: "integer" }, negatives: { type: "integer" },
                  added: { type: "integer" }, changed: { type: "integer" }, removed: { type: "integer" },
                },
              },
              items: { type: "array", items: itemSchema },
              removed: { type: "array", items: itemSchema },
            },
          },
          ...errorResponses,
        },
      },
    },
    async (request) => {
      const { dataset_version } = request.query as { dataset_version?: string };
      if (dataset_version) {
        const items = await versionItems(pool, dataset_version);
        if (items.length === 0) {
          throw new ApiError(404, "DATASET_VERSION_NOT_FOUND", `Версии набора ${dataset_version} нет`);
        }
        const s = summary(items);
        return {
          source: dataset_version, base_version: null, items, removed: [],
          counts: { items: s.items, positives: s.positives, negatives: s.negatives, added: 0, changed: 0, removed: 0 },
        };
      }
      const draft = await draftView(pool);
      const s = summary(draft.items);
      return {
        source: "DRAFT",
        base_version: draft.base,
        items: draft.items,
        removed: draft.removed,
        counts: {
          items: s.items, positives: s.positives, negatives: s.negatives,
          added: draft.items.filter((i) => i.change === "ADDED").length,
          changed: draft.items.filter((i) => i.change === "CHANGED").length,
          removed: draft.removed.length,
        },
      };
    },
  );

  app.get(
    "/api/v1/dataset/versions",
    {
      preHandler: [authenticate, requireRole("admin")],
      schema: {
        tags: ["dataset"],
        summary: "Выпущенные версии набора, новые первыми (администратор)",
        security: bearer,
        response: {
          200: { type: "object", required: ["versions"], properties: { versions: { type: "array", items: versionSchema } } },
          ...errorResponses,
        },
      },
    },
    async () => {
      const { rows } = await pool.query("select * from dataset_versions order by released_at desc");
      return {
        versions: rows.map((r) => ({
          dataset_version: r.dataset_version, items: r.items, positives: r.positives, negatives: r.negatives,
          added: r.added, changed: r.changed, removed: r.removed, objects: r.objects, manifest_sha256: r.manifest_sha256,
          comment: r.comment, released_by: r.released_by, released_at: iso(r.released_at),
          withdrawn_at: iso(r.withdrawn_at), withdrawn_by: r.withdrawn_by, withdrawn_reason: r.withdrawn_reason,
        })),
      };
    },
  );

  app.post(
    "/api/v1/dataset/versions/:version/withdraw",
    {
      preHandler: [authenticate, requireRole("admin")],
      schema: {
        tags: ["dataset"],
        summary: "Отозвать выпущенную версию набора (администратор)",
        description:
          "Версия не удаляется: на неё ссылаются протоколы, и правка задним числом лишила бы их " +
          "доказательной силы. Отзыв — пометка: версия остаётся в истории, но в дообучение не берётся. " +
          "Причина обязательна и видна в списке версий. Повторный отзыв — 409 VERSION_WITHDRAWN.",
        params: {
          type: "object",
          required: ["version"],
          properties: { version: { type: "string", minLength: 1, maxLength: 100 } },
        },
        body: {
          type: "object",
          required: ["reason"],
          properties: { reason: { type: "string", minLength: 3, maxLength: 1000 } },
          additionalProperties: false,
        },
        security: bearer,
        response: { 200: versionSchema, ...errorResponses },
      },
    },
    async (request) => {
      const { version } = request.params as { version: string };
      const { reason } = request.body as { reason: string };
      return withTransaction(async (db) => {
        const { rows } = await db.query("select * from dataset_versions where dataset_version = $1 for update", [version]);
        if (rows.length === 0) {
          throw new ApiError(404, "VERSION_NOT_FOUND", `Версия набора ${version} не найдена`);
        }
        if (rows[0].withdrawn_at) {
          throw new ApiError(409, "VERSION_WITHDRAWN", `Версия ${version} уже отозвана`);
        }
        const { rows: updated } = await db.query(
          `update dataset_versions set withdrawn_at = now(), withdrawn_by = $2, withdrawn_reason = $3
           where dataset_version = $1 returning *`,
          [version, request.user.sub, reason.trim()],
        );
        await audit(db, {
          userId: request.user.sub,
          action: "DATASET_WITHDRAW",
          objectId: null,
          processId: null,
          details: { dataset_version: version, reason: reason.trim(), items: updated[0].items },
          ip: request.ip,
          userAgent: request.headers["user-agent"] ?? null,
        });
        const r = updated[0];
        return {
          dataset_version: r.dataset_version, items: r.items, positives: r.positives, negatives: r.negatives,
          added: r.added, changed: r.changed, removed: r.removed, objects: r.objects, manifest_sha256: r.manifest_sha256,
          comment: r.comment, released_by: r.released_by, released_at: iso(r.released_at),
          withdrawn_at: iso(r.withdrawn_at), withdrawn_by: r.withdrawn_by, withdrawn_reason: r.withdrawn_reason,
        };
      });
    },
  );

  app.post(
    "/api/v1/dataset/release",
    {
      preHandler: [authenticate, requireRole("admin")],
      schema: {
        tags: ["dataset"],
        summary: "Выпустить версию набора из черновика (куратор)",
        description:
          "Версия — снимок черновика целиком: все решения финализированных протоколов на момент выпуска. " +
          "Идентификатор — хеш состава (записи, метки, причины, время решения, страницы доказательств). " +
          "409 DATASET_UNCHANGED, если черновик совпадает с последней версией.",
        body: {
          type: "object",
          properties: { comment: { type: "string", maxLength: 1000 } },
          additionalProperties: false,
        },
        security: bearer,
        response: { 200: versionSchema, ...errorResponses },
      },
    },
    async (request) => {
      const { comment } = (request.body ?? {}) as { comment?: string };
      return withTransaction(async (db) => {
        // выпуски по одному: иначе два куратора посчитают разницу к одной и той же версии
        await db.query("select pg_advisory_xact_lock(hashtext('dataset_release'))");
        const draft = await draftView(db);
        const added = draft.items.filter((i) => i.change === "ADDED").length;
        const changed = draft.items.filter((i) => i.change === "CHANGED").length;
        const removed = draft.removed.length;
        if (draft.items.length === 0 && !draft.base) {
          throw new ApiError(409, "DATASET_EMPTY_DRAFT", "В черновике набора нет примеров: они появляются при финализации протоколов с решениями");
        }
        if (added + changed + removed === 0) {
          throw new ApiError(409, "DATASET_UNCHANGED", `Черновик совпадает с последней версией ${draft.base}`);
        }
        const digest = createHash("sha256").update(JSON.stringify(manifestOf(draft.items))).digest("hex");
        const version = `ds-${digest.slice(0, 12)}`;
        const { rows: existing } = await db.query("select 1 from dataset_versions where dataset_version = $1", [version]);
        if (existing.length) {
          throw new ApiError(409, "DATASET_VERSION_EXISTS", `Такой состав уже выпущен как версия ${version}`);
        }
        const s = summary(draft.items);
        await db.query(
          `insert into dataset_versions (dataset_version, items, positives, negatives, added, changed, removed, objects,
                                         manifest_sha256, comment, released_by)
           values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)`,
          [version, s.items, s.positives, s.negatives, added, changed, removed, JSON.stringify(s.objects), digest,
           comment ?? null, request.user.sub],
        );
        for (const i of draft.items) {
          await db.query(
            `insert into dataset_items (dataset_version, finding_row_id, process_id, object_id, protocol_version, finding_id,
                                        parameter_code, location, gold_label, reason_code, comment, expert_id, decided_at,
                                        evidence, card)
             values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)`,
            [version, i.finding_row_id, i.process_id, i.object_id, i.protocol_version, i.finding_id, i.parameter_code,
             i.location, i.gold_label, i.reason_code, i.comment, i.expert_id, i.decided_at, JSON.stringify(i.evidence),
             JSON.stringify(i.card)],
          );
        }
        const result = {
          dataset_version: version, ...s, added, changed, removed, manifest_sha256: digest, comment: comment ?? null,
          released_by: request.user.sub, released_at: new Date().toISOString(),
        };
        await audit(db, {
          userId: request.user.sub, action: "DATASET_RELEASED",
          details: { dataset_version: version, items: s.items, positives: s.positives, negatives: s.negatives, added, changed, removed,
                     base_version: draft.base, objects: s.objects, comment: comment ?? null },
          ip: request.ip, userAgent: request.headers["user-agent"] ?? null,
        });
        return result;
      });
    },
  );
}
