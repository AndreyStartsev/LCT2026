import type { FastifyInstance } from "fastify";
import { authenticate, bearer, requireRole } from "../auth.js";
import { config } from "../config.js";
import { audit, pool, withTransaction } from "../db.js";
import { ApiError } from "../errors.js";
import { redis } from "../cache.js";
import { limitsView } from "../filecheck.js";
import { deletionBlockers, iso, statusView } from "../process.js";
import { queueReady } from "../queue.js";
import { errorResponses } from "../schemas.js";
import { blobKey, minio } from "../storage.js";

export async function objectRoutes(app: FastifyInstance): Promise<void> {
  app.get(
    "/api/v1/objects",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["objects"],
        summary: "Объекты для дашборда",
        description: "Объекты с последним процессом проверки: его статус и счётчики находок дают светофор.",
        security: bearer,
        response: {
          200: {
            type: "object",
            required: ["objects"],
            properties: {
              objects: {
                type: "array",
                items: {
                  type: "object",
                  required: ["object_id", "name", "processes"],
                  properties: {
                    object_id: { type: "string" },
                    name: { type: "string" },
                    processes: { type: "integer" },
                    last_process: { $ref: "ProcessStatus#" },
                  },
                },
              },
            },
          },
          ...errorResponses,
        },
      },
    },
    async () => {
      const { rows } = await pool.query<{ id: string; name: string; processes: string; last_id: string | null }>(
        `select o.id, o.name, count(p.id) as processes,
                (select id from processes where object_id = o.id order by created_at desc limit 1) as last_id
         from objects o left join processes p on p.object_id = o.id
         group by o.id order by max(p.updated_at) desc nulls last, o.id`,
      );
      const objects = [];
      for (const row of rows) {
        // у объекта без процессов поле last_process отсутствует
        objects.push({
          object_id: row.id,
          name: row.name,
          processes: Number(row.processes),
          ...(row.last_id ? { last_process: await statusView(pool, row.last_id) } : {}),
        });
      }
      return { objects };
    },
  );

  app.get(
    "/api/v1/health",
    {
      schema: {
        tags: ["system"],
        summary: "Состояние сервиса и зависимостей",
        response: {
          200: {
            type: "object",
            required: ["status", "checks", "limits"],
            properties: {
              status: { type: "string", enum: ["ok", "degraded"] },
              checks: {
                type: "object",
                properties: {
                  database: { type: "boolean" },
                  queue: { type: "boolean" },
                  storage: { type: "boolean" },
                  cache: { type: "boolean" },
                },
              },
              limits: { $ref: "Limits#" },
            },
          },
        },
      },
    },
    async () => {
      const probe = async (fn: () => Promise<unknown>) => {
        try {
          await fn();
          return true;
        } catch {
          return false;
        }
      };
      const checks = {
        database: await probe(() => pool.query("select 1")),
        queue: queueReady(),
        storage: await probe(() => minio.bucketExists(config.s3.bucket)),
        cache: await probe(() => redis.ping()),
      };
      return {
        status: Object.values(checks).every(Boolean) ? "ok" : "degraded",
        checks,
        limits: limitsView(),
      };
    },
  );

  app.get(
    "/api/v1/notifications",
    {
      preHandler: [authenticate],
      schema: {
        tags: ["system"],
        summary: "Уведомления своей роли",
        description:
          "Инспектор получает уведомление о готовности протокола, администратор — о сбоях обработки " +
          "после исчерпания повторов (ТЗ: таймаут — до двух повторов, затем уведомление администратора).",
        security: bearer,
        response: {
          200: {
            type: "object",
            required: ["notifications"],
            properties: {
              notifications: {
                type: "array",
                items: {
                  type: "object",
                  required: ["id", "role", "level", "message", "created_at"],
                  properties: {
                    id: { type: "integer" },
                    role: { type: "string" },
                    level: { type: "string" },
                    category: { type: "string", description: "ACTION — требует действия, QUALITY — наблюдение о разборе (живёт в журнале), INFO" },
                    message: { type: "string" },
                    process_id: { type: "string", nullable: true },
                    created_at: { type: "string", format: "date-time" },
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
      const { rows } = await pool.query(
        "select * from notifications where role = $1 order by created_at desc limit 100",
        // эксперт работает с правами инспектора (Р-134): своих уведомлений у него нет, он видит инспекторские
        [request.user.role === "expert" ? "inspector" : request.user.role],
      );
      return {
        notifications: rows.map((r) => ({
          id: Number(r.id),
          role: r.role,
          level: r.level,
          category: r.category ?? "INFO",
          message: r.message,
          process_id: r.process_id,
          created_at: iso(r.created_at),
        })),
      };
    },
  );

  app.get(
    "/api/v1/audit",
    {
      preHandler: [authenticate, requireRole("admin")],
      schema: {
        tags: ["system"],
        summary: "Журнал аудита процесса (администратор)",
        querystring: {
          type: "object",
          required: ["process_id"],
          properties: { process_id: { type: "string", format: "uuid" } },
        },
        security: bearer,
        response: {
          200: {
            type: "object",
            required: ["entries"],
            properties: {
              entries: {
                type: "array",
                items: {
                  type: "object",
                  properties: {
                    id: { type: "integer" },
                    user_id: { type: "string", nullable: true },
                    action: { type: "string" },
                    details: { type: "object", additionalProperties: true },
                    timestamp: { type: "string", format: "date-time" },
                    ip_address: { type: "string", nullable: true },
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
      const { process_id } = request.query as { process_id: string };
      const { rows } = await pool.query(
        "select * from audit_log where process_id = $1 order by timestamp",
        [process_id],
      );
      return {
        entries: rows.map((r) => ({
          id: Number(r.id),
          user_id: r.user_id,
          action: r.action,
          details: r.details,
          timestamp: iso(r.timestamp),
          ip_address: r.ip_address,
        })),
      };
    },
  );

  app.delete(
    "/api/v1/objects/:id",
    {
      preHandler: [authenticate, requireRole("admin")],
      schema: {
        tags: ["objects"],
        summary: "Удалить черновой объект со всеми его проверками (администратор)",
        description:
          "Удаляются объекты, у которых нет финализированных протоколов: загрузили не тот пакет, " +
          "перепутали идентификатор, пробный прогон. Финализированный протокол — документ с версией, " +
          "решениями инспектора и записью в ИАИС «РиН», поэтому такой объект не удаляется (409 " +
          "OBJECT_NOT_DELETABLE); идущая обработка тоже мешает. Вместе с объектом уходят его процессы, " +
          "файлы, находки и протоколы; журнал аудита, уведомления и выпущенные версии набора решений " +
          "остаются — это записи о том, что делали, и снимки. Содержимое файлов из хранилища удаляется " +
          "только то, на которое больше никто не ссылается: хранилище адресовано по SHA-256, и один " +
          "и тот же файл может принадлежать другому объекту.",
        params: {
          type: "object",
          required: ["id"],
          properties: { id: { type: "string", minLength: 1, maxLength: 200 } },
        },
        security: bearer,
        response: {
          200: {
            type: "object",
            required: ["object_id", "processes", "files", "blobs_removed"],
            properties: {
              object_id: { type: "string" },
              processes: { type: "integer" },
              files: { type: "integer" },
              blobs_removed: { type: "integer", description: "сколько файлов удалено из хранилища как никому не нужные" },
            },
          },
          ...errorResponses,
        },
      },
    },
    async (request) => {
      const { id } = request.params as { id: string };
      // удаление в транзакции, хранилище — после: откат транзакции не должен оставлять
      // базу целой, а содержимое файлов удалённым
      const result = await withTransaction(async (db) => {
        const { rows: objects } = await db.query<{ id: string; name: string }>(
          "select id, name from objects where id = $1 for update",
          [id],
        );
        if (objects.length === 0) {
          throw new ApiError(404, "OBJECT_NOT_FOUND", `Объект ${id} не найден`);
        }
        const { rows: processes } = await db.query("select * from processes where object_id = $1 for update", [id]);
        const blockers = deletionBlockers(processes);
        if (blockers.length > 0) {
          throw new ApiError(409, "OBJECT_NOT_DELETABLE",
            `Объект ${id} не удаляется: ${blockers.join("; ")}`, { blockers });
        }
        const { rows: hashes } = await db.query<{ file_hash: string }>(
          "select distinct file_hash from files where object_id = $1 and file_hash is not null",
          [id],
        );
        const { rows: fileCount } = await db.query<{ n: string }>(
          "select count(*) as n from files where object_id = $1",
          [id],
        );
        // процессы уносят за собой файлы, находки, протоколы и очередь передачи (каскад в схеме)
        await db.query("delete from processes where object_id = $1", [id]);
        await db.query("delete from objects where id = $1", [id]);
        const orphans: string[] = [];
        for (const { file_hash } of hashes) {
          const { rows: left } = await db.query<{ n: string }>(
            "select count(*) as n from files where file_hash = $1",
            [file_hash],
          );
          if (Number(left[0].n) === 0) orphans.push(file_hash);
        }
        await audit(db, {
          userId: request.user.sub,
          action: "OBJECT_DELETE",
          objectId: id,
          processId: null,
          details: {
            name: objects[0].name,
            processes: processes.length,
            files: Number(fileCount[0].n),
            orphan_blobs: orphans.length,
          },
          ip: request.ip,
          userAgent: request.headers["user-agent"] ?? null,
        });
        return { processes: processes.length, files: Number(fileCount[0].n), orphans };
      });

      // содержимое, на которое больше никто не ссылается: сам файл, его страницы и текст
      let removed = 0;
      for (const sha of result.orphans) {
        const keys = [blobKey(sha), `texts/${sha}.jsonl`];
        for await (const item of minio.listObjectsV2(config.s3.bucket, `renders/${sha}/`, true)) {
          if (item.name) keys.push(item.name);
        }
        try {
          await minio.removeObjects(config.s3.bucket, keys);
          removed += 1;
        } catch (error) {
          request.log.warn({ err: error, sha }, "содержимое файла удалить не удалось");
        }
      }
      return { object_id: id, processes: result.processes, files: result.files, blobs_removed: removed };
    },
  );
}
