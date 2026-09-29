// Предложения правки правила из песочницы (#224, Р-164). Эксперт сохраняет вариант правила вместе
// с разницей по объектам, которую показал прогон; разработчик переносит его в файл правил через PR
// и гейт качества (tools/rule_proposals.py) и отмечает статус: перенесено или отклонено с причиной.
// Правила прода API не меняет: файлы правил живут в git и в образе воркера.
import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { authenticate, bearer, requireRole, requireRoles } from "../auth.js";
import { audit, pool, withTransaction } from "../db.js";
import { ApiError } from "../errors.js";
import { iso } from "../process.js";
import { proposalDiff, proposalPatch, ruleDigest, ruleSource, variantProblems } from "../rules.js";
import { errorResponses } from "../schemas.js";
import { latestSnapshot, snapshotView } from "./rules.js";

const STATUSES = ["NEW", "APPLIED", "REJECTED"] as const;
type Status = (typeof STATUSES)[number];

const text = { type: "string", nullable: true };
const count = { type: "integer" };
const uuid = { type: "string", format: "uuid" };

const TOTALS = {
  type: "object",
  required: ["objects", "done", "failed", "changed_objects", "changes", "added", "removed", "changed", "disputed"],
  properties: {
    objects: { ...count, description: "объектов в прогоне" },
    done: { ...count, description: "из них посчитано" },
    failed: { ...count, description: "не прогнано: сбой на объекте" },
    changed_objects: { ...count, description: "на скольких объектах вариант меняет записи" },
    changes: { ...count, description: "сколько записей меняется" },
    added: count,
    removed: count,
    changed: count,
    disputed: { ...count, description: "перемены записей, по которым инспектор уже решил" },
  },
};

const SUMMARY = {
  type: "object",
  required: ["id", "code", "queue", "draft", "file", "variant", "status", "created_by", "created_at", "totals"],
  properties: {
    id: { type: "string" },
    code: { type: "string" },
    queue: count,
    draft: { type: "boolean", description: "правка черновика правила, а не рабочего" },
    file: { type: "string", description: "файл правил, к которому прикладывается правка" },
    variant: { type: "object", additionalProperties: true, description: "поля правила поверх рабочего" },
    comment: { ...text, description: "зачем правка — словами эксперта" },
    status: { type: "string", enum: [...STATUSES], description: "NEW — ждёт разработчика, APPLIED — перенесено, REJECTED — отклонено" },
    status_reason: { ...text, description: "причина отклонения или что сделано при переносе" },
    status_by: text,
    status_at: { type: "string", format: "date-time", nullable: true },
    created_by: { type: "string" },
    created_at: { type: "string", format: "date-time" },
    test_id: { ...text, description: "прогон песочницы, из которого предложение; прогоны старше двух недель убираются" },
    fingerprint: { type: "string", description: "снимок правил, на котором предложено" },
    totals: TOTALS,
  },
};

const FULL = {
  ...SUMMARY,
  required: [...SUMMARY.required, "rule", "objects"],
  properties: {
    ...SUMMARY.properties,
    rule: { type: "object", additionalProperties: true, description: "правило из файла на момент предложения" },
    objects: {
      type: "array",
      description: "объекты, где вариант меняет записи, и те, где прогон не удался",
      items: {
        type: "object",
        required: ["process_id", "status", "same", "changes"],
        properties: {
          process_id: { type: "string" },
          object_id: text,
          object_name: text,
          status: { type: "string" },
          error: text,
          same: count,
          changes: { type: "array", items: { type: "object", additionalProperties: true } },
        },
      },
    },
  },
};

const PATCH = {
  type: "object",
  required: ["format", "file", "patch", "proposal", "totals"],
  properties: {
    format: { type: "integer", description: "формат документа правки" },
    file: { type: "string", description: "файл правил от корня репозитория" },
    patch: {
      type: "array",
      description: "правка по RFC 6902: проверка прежнего значения и замена",
      items: {
        type: "object",
        required: ["op", "path", "value"],
        properties: { op: { type: "string", enum: ["test", "replace", "add"] }, path: { type: "string" }, value: {} },
      },
    },
    proposal: {
      type: "object",
      required: ["id", "code", "created_by", "created_at"],
      properties: {
        id: { type: "string" },
        code: { type: "string" },
        comment: text,
        created_by: { type: "string" },
        created_at: { type: "string", format: "date-time" },
        fingerprint: { type: "string" },
      },
    },
    totals: TOTALS,
  },
};

function view(row: Record<string, any>, full: boolean) {
  const diff = row.diff ?? {};
  return {
    id: String(row.id),
    code: row.code,
    queue: Number(row.queue),
    draft: !!row.draft,
    file: row.file,
    variant: row.variant ?? {},
    comment: row.comment ?? null,
    status: row.status as Status,
    status_reason: row.status_reason ?? null,
    status_by: row.status_by ?? null,
    status_at: iso(row.status_at),
    created_by: row.created_by,
    created_at: iso(row.created_at)!,
    test_id: row.test_id ? String(row.test_id) : null,
    fingerprint: row.fingerprint,
    totals: row.totals ?? diff.totals,
    ...(full ? { rule: row.rule ?? {}, objects: diff.objects ?? [] } : {}),
  };
}

async function load(id: string) {
  const { rows } = await pool.query("select * from rule_proposals where id = $1", [id]);
  if (!rows[0]) throw new ApiError(404, "NOT_FOUND", "Предложение не найдено");
  return rows[0];
}

export async function proposalRoutes(app: FastifyInstance): Promise<void> {
  app.post(
    "/api/v1/rules/proposals",
    {
      preHandler: [authenticate, requireRole("expert")],
      schema: {
        tags: ["rules"],
        summary: "Предложить правку правила из прогона песочницы (эксперт)",
        description:
          "Вариант правила из законченного прогона песочницы сохраняется предложением вместе с разницей по объектам — " +
          "снимком: прогон убирается через две недели, предложение остаётся. Правила прода не меняются: разработчик " +
          "переносит правку в файл правил через PR и гейт качества и отмечает статус. Правило, которое изменилось после " +
          "прогона, — 409 RULE_CHANGED: разница говорила бы о другом правиле.",
        security: bearer,
        body: {
          type: "object",
          required: ["test_id"],
          additionalProperties: false,
          properties: { test_id: uuid, comment: { type: "string", maxLength: 2000 } },
        },
        response: { 201: FULL, 422: { $ref: "Error#" }, ...errorResponses },
      },
    },
    async (request, reply) => {
      const body = request.body as { test_id: string; comment?: string };
      const { rows } = await pool.query("select * from rule_tests where id = $1", [body.test_id]);
      const test = rows[0];
      if (!test) throw new ApiError(404, "NOT_FOUND", "Прогон не найден: прогоны старше двух недель убираются");
      if (!test.variant) {
        throw new ApiError(422, "NOT_A_VARIANT", "Предложить можно вариант правила из песочницы: у трассы правки нет");
      }
      if (test.status !== "DONE") {
        throw new ApiError(
          422,
          "TEST_NOT_DONE",
          test.status === "FAILED"
            ? "Прогон не удался: предлагать нечего — прогоните вариант заново"
            : "Прогон ещё идёт: предложить вариант можно, когда он закончится",
        );
      }
      const snapshot = await latestSnapshot();
      const source = ruleSource(snapshot.body, test.code);
      const param = snapshotView(snapshot).parameters.find((p) => p.code === test.code);
      const logic = source ? (source.draft ? param?.draft : param?.rule) : null;
      if (!source || !logic) {
        throw new ApiError(422, "NO_MACHINE_RULE", `У параметра ${test.code} нет машинного правила: править нечего`);
      }
      // вариант проверяется снова: правила могли смениться с прогона, а правило с кодом в песочницу не идёт
      const problems = variantProblems(test.variant, logic);
      if (problems.length) {
        throw new ApiError(422, "BAD_VARIANT", `Вариант правила не принят: ${problems.join("; ")}`, { problems });
      }
      if (test.rule_digest && test.rule_digest !== ruleDigest(source.rule)) {
        throw new ApiError(409, "RULE_CHANGED", "Правило изменилось после прогона: прогоните вариант заново и предложите его");
      }
      const results = await pool.query(
        `select r.process_id, r.object_id, r.status, r.error, r.result, o.name as object_name
           from rule_test_results r
           left join processes p on p.id = r.process_id
           left join objects o on o.id = p.object_id
          where r.test_id = $1`,
        [test.id],
      );
      const diff = proposalDiff(results.rows, Number(test.total) || 0);
      const id = randomUUID();
      const comment = body.comment?.trim() || null;
      try {
        const row = await withTransaction(async (client) => {
          const inserted = await client.query(
            `insert into rule_proposals (id, code, queue, draft, file, variant, rule, fingerprint, test_id, diff, comment, created_by)
             values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12) returning *`,
            [id, test.code, source.queue, source.draft, source.file, test.variant, source.rule, snapshot.fingerprint,
             test.id, JSON.stringify(diff), comment, request.user.sub],
          );
          await audit(client, {
            userId: request.user.sub,
            action: "RULE_PROPOSAL_CREATE",
            details: { proposal_id: id, code: test.code, test_id: test.id, variant: test.variant, totals: diff.totals },
            ip: request.ip,
            userAgent: request.headers["user-agent"] ?? null,
          });
          return inserted.rows[0];
        });
        reply.status(201);
        return view(row, true);
      } catch (error) {
        if ((error as { code?: string }).code !== "23505") throw error;
        const existing = await pool.query("select id from rule_proposals where test_id = $1", [test.id]);
        throw new ApiError(409, "PROPOSAL_EXISTS", "Этот вариант уже предложен", {
          proposal_id: existing.rows[0] ? String(existing.rows[0].id) : null,
        });
      }
    },
  );

  app.get(
    "/api/v1/rules/proposals",
    {
      preHandler: [authenticate, requireRoles("expert", "admin")],
      schema: {
        tags: ["rules"],
        summary: "Предложения правки правил (эксперт, администратор)",
        description: "Последние 200 предложений, новые сверху; отбор по параметру и статусу. Разница по объектам — итогами.",
        security: bearer,
        querystring: {
          type: "object",
          additionalProperties: false,
          properties: { code: { type: "string", maxLength: 32 }, status: { type: "string", enum: [...STATUSES] } },
        },
        response: {
          200: { type: "object", required: ["proposals"], properties: { proposals: { type: "array", items: SUMMARY } } },
          ...errorResponses,
        },
      },
    },
    async (request) => {
      const { code, status } = request.query as { code?: string; status?: Status };
      const { rows } = await pool.query(
        `select id, code, queue, draft, file, variant, comment, status, status_reason, status_by, status_at,
                created_by, created_at, test_id, fingerprint, diff->'totals' as totals
           from rule_proposals
          where ($1::text is null or code = $1) and ($2::text is null or status = $2)
          order by created_at desc limit 200`,
        [code ?? null, status ?? null],
      );
      return { proposals: rows.map((r) => view(r, false)) };
    },
  );

  app.get(
    "/api/v1/rules/proposals/:id",
    {
      preHandler: [authenticate, requireRoles("expert", "admin")],
      schema: {
        tags: ["rules"],
        summary: "Предложение правки с разницей по объектам (эксперт, администратор)",
        security: bearer,
        params: { type: "object", required: ["id"], properties: { id: uuid } },
        response: { 200: FULL, ...errorResponses },
      },
    },
    async (request) => view(await load((request.params as { id: string }).id), true),
  );

  app.get(
    "/api/v1/rules/proposals/:id/patch",
    {
      preHandler: [authenticate, requireRoles("expert", "admin")],
      schema: {
        tags: ["rules"],
        summary: "Правка файла правил по предложению — JSON (эксперт, администратор)",
        description:
          "Документ правки: файл правил от корня репозитория и операции RFC 6902 — на каждое поле варианта проверка " +
          "прежнего значения и замена. Правило, изменившееся с предложения, проверку не пройдёт, и правка не наложится. " +
          "Применяет `tools/rule_proposals.py apply`.",
        security: bearer,
        params: { type: "object", required: ["id"], properties: { id: uuid } },
        response: { 200: PATCH, ...errorResponses },
      },
    },
    async (request, reply) => {
      const row = await load((request.params as { id: string }).id);
      const created = iso(row.created_at)!;
      reply.header(
        "content-disposition",
        `attachment; filename="rule-proposal-${row.code}-${created.slice(0, 10)}-${String(row.id).slice(0, 8)}.json"`,
      );
      return {
        format: 1,
        file: row.file,
        patch: proposalPatch(row.code, row.rule ?? {}, row.variant ?? {}),
        proposal: {
          id: String(row.id),
          code: row.code,
          comment: row.comment ?? null,
          created_by: row.created_by,
          created_at: created,
          fingerprint: row.fingerprint,
        },
        totals: row.diff?.totals,
      };
    },
  );

  app.post(
    "/api/v1/rules/proposals/:id/status",
    {
      preHandler: [authenticate, requireRole("admin")],
      schema: {
        tags: ["rules"],
        summary: "Статус предложения правки (администратор)",
        description:
          "Разработчик отмечает, что стало с предложением: APPLIED — правка перенесена в файл правил, REJECTED — " +
          "отклонена, причина обязательна: эксперт видит её у предложения. NEW возвращает предложение в ожидание.",
        security: bearer,
        params: { type: "object", required: ["id"], properties: { id: uuid } },
        body: {
          type: "object",
          required: ["status"],
          additionalProperties: false,
          properties: { status: { type: "string", enum: [...STATUSES] }, reason: { type: "string", maxLength: 2000 } },
        },
        response: { 200: FULL, 422: { $ref: "Error#" }, ...errorResponses },
      },
    },
    async (request) => {
      const { id } = request.params as { id: string };
      const body = request.body as { status: Status; reason?: string };
      const reason = body.reason?.trim() || null;
      if (body.status === "REJECTED" && !reason) {
        throw new ApiError(422, "REASON_REQUIRED", "Отклонение — с причиной: эксперт увидит её у предложения");
      }
      const row = await withTransaction(async (client) => {
        const updated = await client.query(
          `update rule_proposals set status = $2, status_reason = $3, status_by = $4, status_at = now()
            where id = $1 returning *`,
          [id, body.status, reason, request.user.sub],
        );
        if (!updated.rows[0]) throw new ApiError(404, "NOT_FOUND", "Предложение не найдено");
        await audit(client, {
          userId: request.user.sub,
          action: "RULE_PROPOSAL_STATUS",
          details: { proposal_id: id, code: updated.rows[0].code, status: body.status, reason },
          ip: request.ip,
          userAgent: request.headers["user-agent"] ?? null,
        });
        return updated.rows[0];
      });
      return view(row, true);
    },
  );
}
