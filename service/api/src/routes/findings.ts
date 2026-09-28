import type { FastifyInstance } from "fastify";
import { authenticate, bearer } from "../auth.js";
import { audit, pool, withTransaction } from "../db.js";
import { ApiError } from "../errors.js";
import { findingCounts, loadProcess, settleStatus } from "../process.js";
import { errorResponses, REASON_CODES } from "../schemas.js";
import { ACTIONS, assertDecisionAllowed, assertVerificationAllowed, isDisputed } from "../verification.js";
import { findingView } from "../finding-view.js";

export async function findingRoutes(app: FastifyInstance): Promise<void> {
  app.post(
    "/api/v1/findings/:id/decision",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["findings"],
        summary: "Решение инспектора по кандидату",
        description:
          "ТЗ, раздел 9.3. CONFIRM — нарушение подтверждено; REJECT — отклонено, reason_code и комментарий " +
          "обязательны; CLARIFY — требуется уточнение; RESET — вернуть решённую запись в кандидаты до финализации; " +
          "PROMOTE — взять гипотезу свободного поиска в кандидаты; DISPUTE — вернуть в кандидаты запись, " +
          "которую автоматика закрыла сама как «расхождения нет» (#74). Комментарий инспектора можно оставить при любом " +
          "решении, он попадает в журнал аудита и в протокол вместе с пользователем и временем. В статусе COMPLETED " +
          "(верификация завершена) принимается только RESET: по таблице статусов ТЗ 9.1 решения там не принимаются.",
        params: {
          type: "object",
          required: ["id"],
          properties: { id: { type: "string", format: "uuid" } },
        },
        body: {
          type: "object",
          required: ["action"],
          properties: {
            action: { type: "string", enum: Object.keys(ACTIONS) },
            reason_code: { type: "string", enum: REASON_CODES },
            comment: { type: "string", maxLength: 4000 },
          },
          additionalProperties: false,
        },
        security: bearer,
        response: {
          200: {
            type: "object",
            required: ["finding", "process_status", "counts"],
            properties: {
              finding: { $ref: "Finding#" },
              process_status: { type: "string" },
              counts: { $ref: "FindingCounts#" },
            },
          },
          ...errorResponses,
        },
      },
    },
    async (request) => {
      const { id } = request.params as { id: string };
      const { action, reason_code, comment } = request.body as {
        action: string;
        reason_code?: string;
        comment?: string;
      };
      if (action === "REJECT" && (!reason_code || !comment?.trim())) {
        throw new ApiError(400, "REASON_REQUIRED", "Отклонение требует кода причины и комментария");
      }
      return withTransaction(async (db) => {
        const { rows } = await db.query("select * from findings where id = $1 for update", [id]);
        if (rows.length === 0) {
          throw new ApiError(404, "FINDING_NOT_FOUND", `Находка ${id} не найдена`);
        }
        const finding = rows[0];
        const process = await loadProcess(db, finding.process_id, true);
        assertDecisionAllowed(process, finding, action);
        const status = ACTIONS[action];
        const reset = action === "RESET";
        // отмена возврата в кандидаты: запись снова закрыта автоматикой, пометка снимается
        const undispute = reset && isDisputed(finding);
        // Перевод гипотезы в кандидаты — не решение по ней: он только открывает решение,
        // поэтому автор и время пишутся в саму запись, а решение остаётся пустым.
        const promote = action === "PROMOTE";
        // Оспаривание автоматической проверки (#74) устроено так же: это не решение по записи,
        // а её возврат в кандидаты, поэтому автор и время пишутся в саму запись.
        const dispute = action === "DISPUTE";
        const { rows: updated } = undispute
          ? await db.query(
              `update findings set verification_status = 'NOT_REQUIRED',
                      body = body - 'disputed_at' - 'disputed_by',
                      reason_code = null, decided_by = null, decided_at = null
               where id = $1 returning *`,
              [id],
            )
          : promote || dispute
          ? await db.query(
              `update findings set verification_status = 'PENDING',
                      body = jsonb_set(jsonb_set(body, $4::text[], to_jsonb(now())), $5::text[], to_jsonb($2::text)),
                      comment = coalesce($3, comment)
               where id = $1 returning *`,
              [id, request.user.sub, comment?.trim() || null,
               promote ? "{promoted_at}" : "{disputed_at}", promote ? "{promoted_by}" : "{disputed_by}"],
            )
          : await db.query(
              // новое решение (или возврат в кандидаты) принимается по текущим значениям:
              // отметки «значения изменились после решения» и «решение вернула пересборка»
              // своё отработали и снимаются
              `update findings set verification_status = $2, reason_code = $3, comment = $4,
                      decided_by = $5, decided_at = ${reset ? "null" : "now()"},
                      body = body - 'changed_after_decision' - 'reopened'
               where id = $1 returning *`,
              [id, status, action === "REJECT" ? reason_code : null, reset ? null : comment?.trim() || null,
               reset ? null : request.user.sub],
            );
        const next = await settleStatus(db, process.id);
        const counts = await findingCounts(db, process.id);
        await audit(db, {
          userId: request.user.sub,
          action: `FINDING_${action}`,
          objectId: process.object_id,
          processId: process.id,
          details: {
            finding_id: finding.finding_id,
            parameter_code: finding.parameter_code,
            from: finding.verification_status,
            to: undispute ? "NOT_REQUIRED" : status,
            reason_code: reason_code ?? null,
            comment: comment ?? null,
          },
          ip: request.ip,
          userAgent: request.headers["user-agent"] ?? null,
        });
        return { finding: findingView(updated[0]), process_status: next, counts };
      });
    },
  );

  app.post(
    "/api/v1/findings/:id/split",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["findings"],
        summary: "Разделение составного кандидата на атомарные",
        description:
          "ТЗ и задача #33: декомпозиция составного нарушения (например, несколько помещений в одном кандидате) " +
          "на отдельные атомарные записи с сохранением доказательной базы.",
        params: {
          type: "object",
          required: ["id"],
          properties: { id: { type: "string", format: "uuid" } },
        },
        body: {
          type: "object",
          required: ["locations"],
          properties: {
            locations: {
              type: "array",
              minItems: 2,
              items: { type: "string", minLength: 1 },
            },
            comment: { type: "string", maxLength: 1000 },
          },
          additionalProperties: false,
        },
        security: bearer,
        response: {
          200: {
            type: "object",
            required: ["original_finding_id", "created_findings", "counts", "process_status"],
            properties: {
              original_finding_id: { type: "string" },
              created_findings: { type: "array", items: { $ref: "Finding#" } },
              counts: { $ref: "FindingCounts#" },
              process_status: { type: "string" },
            },
          },
          ...errorResponses,
        },
      },
    },
    async (request) => {
      const { id } = request.params as { id: string };
      const { locations, comment } = request.body as {
        locations: string[];
        comment?: string;
      };

      const cleanedLocations = [...new Set(locations.map((l) => l.trim()).filter(Boolean))];
      if (cleanedLocations.length < 2) {
        throw new ApiError(400, "INVALID_LOCATIONS", "Для разделения требуется не менее 2 уникальных локаций");
      }

      return withTransaction(async (db) => {
        const { rows } = await db.query("select * from findings where id = $1 for update", [id]);
        if (rows.length === 0) {
          throw new ApiError(404, "FINDING_NOT_FOUND", `Находка ${id} не найдена`);
        }
        const finding = rows[0];
        const process = await loadProcess(db, finding.process_id, true);
        assertVerificationAllowed(process, "Декомпозиция записи");
        // Делится нерешённый кандидат: у решённой записи решение относилось к целому,
        // а запись без нарушения кандидатом не станет от того, что её разделили.
        if (finding.verification_status !== "PENDING") {
          throw new ApiError(409, "NOT_SPLITTABLE",
            "Разделить можно только кандидата без решения. Верните решение в кандидаты, затем разделите");
        }

        // Исходная запись не удаляется, а помечается разделённой. Иначе при пересборке
        // протокола (дозагрузка) конвейер вернул бы её нерешённой, а части потерялись бы.
        await db.query("update findings set verification_status = 'SPLIT' where id = $1", [id]);

        const createdRows = [];
        for (let i = 0; i < cleanedLocations.length; i++) {
          const loc = cleanedLocations[i];
          const newFindingId = `${finding.finding_id}::split-${i + 1}`;
          const newBody = {
            ...(finding.body || {}),
            finding_id: newFindingId,
            location: loc,
            locations: [loc],
            origin: "INSPECTOR_SPLIT",
            parent_finding_id: finding.finding_id,
            split_comment: comment?.trim() || null,
          };

          const { rows: inserted } = await db.query(
            `insert into findings (
               id, process_id, finding_id, protocol_version, parameter_code, location,
               violation_label, protocol_status, criticality, pd_value, rd_value,
               verification_status, body
             ) values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'PENDING', $12)
             on conflict (process_id, finding_id) do update
               set verification_status = 'PENDING', body = excluded.body, location = excluded.location,
                   reason_code = null, comment = null, decided_by = null, decided_at = null
             returning *`,
            [
              crypto.randomUUID(),
              finding.process_id,
              newFindingId,
              finding.protocol_version,
              finding.parameter_code,
              loc,
              finding.violation_label,
              finding.protocol_status,
              finding.criticality,
              finding.pd_value,
              finding.rd_value,
              JSON.stringify(newBody),
            ],
          );
          createdRows.push(inserted[0]);
        }

        const next = await settleStatus(db, process.id);
        const counts = await findingCounts(db, process.id);

        await audit(db, {
          userId: request.user.sub,
          action: "FINDING_SPLIT",
          objectId: process.object_id,
          processId: process.id,
          details: {
            original_finding_id: finding.finding_id,
            parts_count: cleanedLocations.length,
            locations: cleanedLocations,
            comment: comment ?? null,
          },
          ip: request.ip,
          userAgent: request.headers["user-agent"] ?? null,
        });

        return {
          original_finding_id: finding.finding_id,
          created_findings: createdRows.map(findingView),
          counts,
          process_status: next,
        };
      });
    },
  );
}

