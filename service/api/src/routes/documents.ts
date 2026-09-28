import type { MultipartFile, MultipartValue } from "@fastify/multipart";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { authenticate, bearer, requireRole } from "../auth.js";
import { config } from "../config.js";
import { audit, pool, withTransaction, type Queryable } from "../db.js";
import { ApiError } from "../errors.js";
import {
  checkContent,
  extensionOf,
  FORMATS,
  limitsView,
  LOADER_UPLOAD_PATH,
  safeRelativePath,
  tooLarge,
  unsupported,
  type Rejection,
} from "../filecheck.js";
import { assertUploadAllowed, loadProcess, newProcessId, type ProcessRow } from "../process.js";
import { publish } from "../queue.js";
import { errorResponses, READING_MODES } from "../schemas.js";
import { discard, promote, storeTemporary } from "../storage.js";

const OBJECT_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{1,79}$/;
const UPLOAD_KEY_RE = /^[A-Za-z0-9-]{8,64}$/;

/** Последний пакет загрузки с этим ключом, если он уже принят: повтор после потерянного ответа. */
async function finalBatchOf(db: Queryable, processId: string, uploadKey: string): Promise<string | null> {
  const { rows } = await db.query<{ id: string }>(
    "select id from upload_batches where process_id = $1 and upload_key = $2 and final_batch order by created_at desc limit 1",
    [processId, uploadKey],
  );
  return rows[0]?.id ?? null;
}

/** Отказ в дозагрузке — с номером процесса: клиент продолжает в него, а не заводит новый. */
function uploadAllowed(process: ProcessRow): void {
  try {
    assertUploadAllowed(process);
  } catch (error) {
    if (error instanceof ApiError) {
      throw new ApiError(error.statusCode, error.code, error.message, { ...(error.details ?? {}), process_id: process.id });
    }
    throw error;
  }
}
// Заголовок и разделители multipart добавляют к пакету немного байт сверх файлов.
const ENVELOPE_SLACK_BYTES = 1024 * 1024;

/** Лимиты приёма, байт; null — лимита нет. */
interface UploadLimits {
  fileBytes: number | null;
  packageBytes: number | null;
}

// Загрузка инспектором в браузере — по лимитам ТЗ: файл до MAX_FILE_MB, пакет до MAX_PACKAGE_MB.
const browserLimits = (): UploadLimits => ({
  fileBytes: config.limits.maxFileBytes,
  packageBytes: config.limits.maxPackageBytes,
});

// Загрузчик папки объекта — без лимитов: так организатор ответил на установочной сессии (21:13),
// крупные пакеты идут через бэк. В корпусе 115 PDF больше 50 МБ, самый большой — 912 МБ, и среди
// них действующие ПЗ и ПЗУ Тюменской и вся ИД Лосевской и Полярной 16 (Р-110).
const LOADER_LIMITS: UploadLimits = { fileBytes: null, packageBytes: null };

interface Accepted {
  relative_path: string;
  sha256: string;
  size_bytes: number;
  extension: string;
  created_blob: boolean;
}

function packageTooLarge(): ApiError {
  return new ApiError(413, "PACKAGE_TOO_LARGE",
    `Пакет файлов превышает общий лимит загрузки ${config.limits.maxPackageBytes / 1024 / 1024} МБ. ` +
    "Разделите папку на несколько пакетов и дозагрузите их в тот же процесс",
    { limits: limitsView() });
}

async function drain(stream: NodeJS.ReadableStream): Promise<void> {
  for await (const _chunk of stream) {
    // содержимое отклонённого файла не нужно, но поток надо дочитать
  }
}

const UPLOAD_DESCRIPTION =
  "multipart/form-data. Поля до файлов: process_id — для дозагрузки в существующий процесс; " +
  "object_id и object_name — для нового процесса; reading_mode — способ чтения объекта " +
  "(layer, tesseract, model; по умолчанию режим сервиса); model_name — модель для режима «модель» " +
  "из списка limits.reading_models; final_batch=false — не запускать разбор после пакета " +
  "(папка грузится несколькими пакетами). Перед каждым файлом можно передать поле relative_path — " +
  "путь файла внутри папки объекта. Поле skipped — JSON-массив {relative_path, size_bytes} файлов, " +
  "которые клиент не передаёт как заведомо неподходящие: сервер записывает их отказ по своим правилам. " +
  "Поле upload_key — ключ загрузки (8–64 символа: латиница, цифры, дефис), один на все пакеты и повторы " +
  "одной загрузки: пакет без process_id с ключом, под которым процесс уже заведён, дописывается в этот " +
  "процесс, а повтор последнего пакета, уже принятого, получает ответ с already_accepted=true — так повтор " +
  "после обрыва не создаёт дубль и не запускает разбор второй раз. Пакет, в котором ни один файл не принят, " +
  "у известного процесса записывает отказы и отвечает 422 NO_ACCEPTED_FILES с details.process_id; " +
  "у последнего пакета разбор запускается, если загрузка с этим ключом приняла хотя бы один файл. " +
  "Отклонённые файлы перечисляются в ответе с причиной.";

/** Схема маршрута загрузки: у загрузки в браузере и у загрузчика она одна, различаются лимиты. */
function uploadSchema(summary: string, description: string) {
  return {
    tags: ["documents"],
    summary,
    description,
    consumes: ["multipart/form-data"],
    security: bearer,
    response: {
      202: {
        type: "object",
        required: ["process_id", "object_id", "batch_id", "status", "final_batch", "processing_queued", "accepted", "rejected", "limits"],
        properties: {
          process_id: { type: "string", format: "uuid" },
          object_id: { type: "string" },
          batch_id: { type: "string", format: "uuid" },
          status: { type: "string" },
          final_batch: { type: "boolean" },
          processing_queued: { type: "boolean" },
          already_accepted: { type: "boolean", description: "повтор последнего пакета, который уже принят: разбор поставлен раньше" },
          accepted: {
            type: "array",
            items: {
              type: "object",
              required: ["relative_path", "sha256", "size_bytes"],
              properties: {
                relative_path: { type: "string" },
                sha256: { type: "string" },
                size_bytes: { type: "integer" },
              },
            },
          },
          rejected: { type: "array", items: { $ref: "Rejected#" } },
          limits: { $ref: "Limits#" },
        },
      },
      413: { $ref: "Error#" },
      422: { $ref: "Error#" },
      503: { $ref: "Error#" },
      ...errorResponses,
    },
  };
}

export async function documentRoutes(app: FastifyInstance): Promise<void> {
  // Приём пакета с заданными лимитами: у загрузки в браузере — лимиты ТЗ, у загрузчика их нет.
  const receive = (limits: UploadLimits) =>
    async (request: FastifyRequest, reply: FastifyReply) => {
      if (!request.isMultipart()) {
        throw new ApiError(400, "MULTIPART_REQUIRED", "Ожидается multipart/form-data с файлами");
      }
      const declared = Number(request.headers["content-length"] ?? 0);
      if (limits.packageBytes !== null && declared > limits.packageBytes + ENVELOPE_SLACK_BYTES) {
        throw packageTooLarge();
      }

      const user = request.user.sub;
      const fields: Record<string, string> = {};
      const accepted: Accepted[] = [];
      const rejected: (Rejection & { relative_path: string })[] = [];
      let pendingPath: string | null = null;
      let packageBytes = 0;
      let checkedProcess = false;

      const cleanup = async () => {
        await Promise.all(accepted.filter((a) => a.created_blob).map((a) => discard(`blobs/${a.sha256.slice(0, 2)}/${a.sha256}`)));
      };

      try {
        // лимит файла у плагина multipart — лимит браузера; загрузчику он снимается на этот запрос
        const parts = limits.fileBytes === null ? request.parts({ limits: { fileSize: Infinity } }) : request.parts();
        for await (const part of parts) {
          if (part.type === "field") {
            const value = String((part as MultipartValue).value ?? "");
            if (part.fieldname === "relative_path") {
              pendingPath = value;
            } else {
              fields[part.fieldname] = value;
            }
            continue;
          }
          const file = part as MultipartFile;
          // Дозагрузку в недоступный процесс отклоняем до того, как читать файлы.
          if (!checkedProcess) {
            checkedProcess = true;
            const key = fields.upload_key?.trim();
            if (key && !UPLOAD_KEY_RE.test(key)) {
              throw new ApiError(400, "INVALID_UPLOAD_KEY", "upload_key: от 8 до 64 символов — латиница, цифры, дефис");
            }
            if (fields.process_id) {
              const process = await loadProcess(pool, fields.process_id);
              // повтор последнего пакета этой же загрузки после потерянного ответа: процесс уже
              // занят разбором, но пакет не отклоняем — ниже он получит ответ «уже принят»
              const final = (fields.final_batch ?? "true").toLowerCase() !== "false";
              if (!(key && final && (await finalBatchOf(pool, process.id, key)))) uploadAllowed(process);
            } else if (fields.object_id && !OBJECT_ID_RE.test(fields.object_id.trim())) {
              throw new ApiError(400, "INVALID_OBJECT_ID",
                "object_id: латиница, цифры, точка, дефис и подчёркивание, от 2 до 80 символов");
            }
          }
          const raw = pendingPath ?? file.filename ?? "";
          pendingPath = null;
          const relativePath = safeRelativePath(raw);
          if (!relativePath) {
            await drain(file.file);
            rejected.push({ relative_path: raw, code: "UNSUPPORTED_FORMAT", message: "Недопустимый путь файла" });
            continue;
          }
          const ext = extensionOf(relativePath);
          if (!(ext in FORMATS)) {
            await drain(file.file);
            rejected.push({ relative_path: relativePath, ...unsupported(ext) });
            continue;
          }
          const stored = await storeTemporary(file.file);
          if (file.file.truncated) {
            await discard(stored.tmpKey);
            rejected.push({ relative_path: relativePath, ...tooLarge(limits.fileBytes ?? config.limits.maxFileBytes) });
            continue;
          }
          const problem = checkContent(ext, stored.size, stored.head, stored.tail);
          if (problem) {
            await discard(stored.tmpKey);
            rejected.push({ relative_path: relativePath, ...problem });
            continue;
          }
          packageBytes += stored.size;
          if (limits.packageBytes !== null && packageBytes > limits.packageBytes) {
            await discard(stored.tmpKey);
            throw packageTooLarge();
          }
          const created = await promote(stored);
          accepted.push({
            relative_path: relativePath,
            sha256: stored.sha256,
            size_bytes: stored.size,
            extension: ext,
            created_blob: created,
          });
        }
      } catch (error) {
        await cleanup();
        throw error;
      }

      // Всё, что может отказать до фиксации транзакции, чистит принятые в этом запросе blob-ы:
      // без строк files на них никто не сошлётся, и они остались бы в хранилище навсегда
      let committed = false;
      let result: { processId: string; objectId: string; batchId: string; status: string; repeated: boolean; queueParse: boolean };
      const finalBatch = (fields.final_batch ?? "true").toLowerCase() !== "false";
      try {
        // Файлы, которые клиент не стал передавать: крупнее лимита или неподдерживаемого
        // формата. Гонять их по сети ради отказа незачем, но отказ записывается —
        // иначе статус «загружена частично» их бы не учёл. Причину сервер определяет
        // сам по своим правилам, а не верит клиенту.
        if (fields.skipped) {
          let skipped: unknown;
          try {
            skipped = JSON.parse(fields.skipped);
          } catch {
            throw new ApiError(400, "INVALID_SKIPPED", "Поле skipped должно быть JSON-массивом");
          }
          for (const item of Array.isArray(skipped) ? skipped : []) {
            const path = safeRelativePath(String((item as { relative_path?: unknown }).relative_path ?? ""));
            const size = Number((item as { size_bytes?: unknown }).size_bytes ?? 0);
            if (!path) continue;
            const ext = extensionOf(path);
            if (!(ext in FORMATS)) {
              rejected.push({ relative_path: path, ...unsupported(ext) });
            } else if (limits.fileBytes !== null && size > limits.fileBytes) {
              rejected.push({ relative_path: path, ...tooLarge(limits.fileBytes) });
            }
          }
        }

        // Способ чтения объекта (#54): где-то хватает текстового слоя, где-то нужна модель.
        // Выбор инспектора хранится у процесса; незнакомое значение — ошибка, а не тихий откат.
        const readingMode = fields.reading_mode?.trim() || null;
        if (readingMode && !READING_MODES.includes(readingMode)) {
          throw new ApiError(400, "INVALID_READING_MODE",
            `reading_mode: ${READING_MODES.join(", ")}`);
        }
        // Модель берётся только из настроенного списка: за вызовы платит владелец стенда,
        // и произвольное имя из запроса уходить провайдеру не должно.
        const modelName = fields.model_name?.trim() || null;
        const known = config.reading.models.map((model) => model.id);
        if (modelName && known.length > 0 && !known.includes(modelName)) {
          throw new ApiError(400, "INVALID_MODEL", `model_name: ${known.join(", ")}`);
        }
        const objectIdInput = fields.object_id?.trim();
        const uploadKey = fields.upload_key?.trim() || null;

        result = await withTransaction(async (db) => {
          let processId = fields.process_id;
          // повтор первого пакета, ответ на который потерялся: процесс уже заведён под этим ключом
          let byKey = false;
          if (!processId && uploadKey) {
            const known = await db.query<{ id: string }>("select id from processes where upload_key = $1", [uploadKey]);
            if (known.rows[0]) {
              processId = known.rows[0].id;
              byKey = true;
            }
          }
          let objectId: string;
          let status: string;
          if (processId) {
            const process = await loadProcess(db, processId, true);
            if (byKey && objectIdInput && objectIdInput !== process.object_id) {
              throw new ApiError(409, "UPLOAD_KEY_MISMATCH",
                `Ключ загрузки уже относится к объекту ${process.object_id}: для другого объекта нужна новая загрузка`,
                { process_id: process.id });
            }
            // повтор последнего пакета, который уже принят: разбор поставлен тогда же
            if (uploadKey && finalBatch) {
              const seen = await finalBatchOf(db, process.id, uploadKey);
              if (seen) {
                return { processId: process.id, objectId: process.object_id, batchId: seen, status: process.status, repeated: true, queueParse: false };
              }
            }
            uploadAllowed(process);
            objectId = process.object_id;
            status = process.status;
          } else if (accepted.length === 0) {
            // процесс под пакет без единого принятого файла не заводим
            throw new ApiError(422, "NO_ACCEPTED_FILES", "Ни один файл пакета не принят", { rejected, limits: limitsView() });
          } else {
            processId = newProcessId();
            objectId = objectIdInput || `UPL-${processId.slice(0, 8).toUpperCase()}`;
            await db.query(
              "insert into objects (id, name) values ($1, $2) on conflict (id) do nothing",
              [objectId, fields.object_name?.trim() || objectId],
            );
            await db.query(
              `insert into processes (id, object_id, status, created_by, processing, reading_mode, model_name, upload_key)
               values ($1, $2, 'PENDING', $3, $4, $5, $6, $7)`,
              [processId, objectId, user, JSON.stringify({ state: "IDLE" }), readingMode,
               readingMode === "model" ? modelName : null, uploadKey],
            );
            status = "PENDING";
          }
          const batchId = newProcessId();
          await db.query(
            `insert into upload_batches (id, process_id, files_accepted, files_rejected, bytes_accepted, final_batch, created_by, upload_key)
             values ($1, $2, $3, $4, $5, $6, $7, $8)`,
            [batchId, processId, accepted.length, rejected.length, packageBytes, finalBatch, user, uploadKey],
          );
          for (const file of accepted) {
            // тот же файл, загруженный повторно, не считается новым: время приёма остаётся прежним,
            // иначе окно финализации решило бы, что он не вошёл в протокол
            await db.query(
              `insert into files (process_id, object_id, batch_id, relative_path, file_hash, size_bytes, extension, status)
               values ($1, $2, $3, $4, $5, $6, $7, 'ACCEPTED')
               on conflict (process_id, relative_path) do update
                 set uploaded_at = case when files.status = 'ACCEPTED' and files.file_hash = excluded.file_hash
                                        then files.uploaded_at else now() end,
                     file_hash = excluded.file_hash, size_bytes = excluded.size_bytes, batch_id = excluded.batch_id,
                     status = 'ACCEPTED', reject_code = null, reject_message = null`,
              [processId, objectId, batchId, file.relative_path, file.sha256, file.size_bytes, file.extension],
            );
          }
          for (const file of rejected) {
            await db.query(
              `insert into files (process_id, object_id, batch_id, relative_path, extension, status, reject_code, reject_message)
               values ($1, $2, $3, $4, $5, 'REJECTED', $6, $7)
               on conflict (process_id, relative_path) do nothing`,
              [processId, objectId, batchId, file.relative_path, extensionOf(file.relative_path), file.code, file.message],
            );
          }
          // Разбор — после последнего пакета, и только если загрузка приняла хотя бы один файл:
          // дозагрузка, отклонённая целиком, не пересобирает протокол без новых файлов
          let queueParse = false;
          if (finalBatch) {
            if (accepted.length > 0) {
              queueParse = true;
            } else if (uploadKey) {
              const sum = await db.query<{ n: string }>(
                "select coalesce(sum(files_accepted), 0) as n from upload_batches where process_id = $1 and upload_key = $2",
                [processId, uploadKey],
              );
              queueParse = Number(sum.rows[0]?.n ?? 0) > 0;
            }
          }
          if (queueParse) {
            await db.query(
              `update processes set processing = $2, updated_at = now() where id = $1`,
              [processId, JSON.stringify({ state: "QUEUED", step: "parse", attempt: 1, queued_at: new Date().toISOString() })],
            );
          } else {
            await db.query("update processes set updated_at = now() where id = $1", [processId]);
          }
          await audit(db, {
            userId: user,
            action: "DOCUMENTS_UPLOADED",
            objectId,
            processId,
            details: {
              batch_id: batchId, accepted: accepted.length, rejected: rejected.length, bytes: packageBytes, final_batch: finalBatch,
              ...(limits.fileBytes === null ? { loader: true } : {}),
            },
            ip: request.ip,
            userAgent: request.headers["user-agent"] ?? null,
          });
          return { processId, objectId, batchId, status, repeated: false, queueParse };
        });
        committed = true;
      } catch (error) {
        if (!committed) await cleanup();
        throw error;
      }

      if (result.repeated) {
        return reply.status(202).send({
          process_id: result.processId,
          object_id: result.objectId,
          batch_id: result.batchId,
          status: result.status,
          final_batch: true,
          processing_queued: true,
          already_accepted: true,
          accepted: [],
          rejected: [],
          limits: limitsView(),
        });
      }
      // Пакет, в котором ничего не принято: отказы записаны в процесс, клиент идёт к следующему
      if (accepted.length === 0 && !result.queueParse) {
        throw new ApiError(422, "NO_ACCEPTED_FILES", "Ни один файл пакета не принят", {
          process_id: result.processId,
          rejected,
          limits: limitsView(),
        });
      }

      let queued = false;
      if (result.queueParse) {
        try {
          await publish("parse", result.processId, user, request.id);
          queued = true;
        } catch (error) {
          request.log.error({ err: error }, "очередь недоступна");
          await pool.query(
            "update processes set processing = $2, updated_at = now() where id = $1",
            [result.processId, JSON.stringify({ state: "FAILED", step: "parse", error: "Очередь сообщений недоступна" })],
          );
          throw new ApiError(503, "QUEUE_UNAVAILABLE",
            "Документы сохранены, но разбор не запущен: очередь недоступна. Повторите запуск: POST /api/v1/process/{id}/start",
            { process_id: result.processId });
        }
      }

      return reply.status(202).send({
        process_id: result.processId,
        object_id: result.objectId,
        batch_id: result.batchId,
        status: result.status,
        final_batch: finalBatch,
        processing_queued: queued,
        accepted: accepted.map(({ relative_path, sha256, size_bytes }) => ({ relative_path, sha256, size_bytes })),
        rejected,
        limits: limitsView(),
      });
    };

  app.post(
    "/api/v1/documents/upload",
    {
      preHandler: [authenticate],
      schema: uploadSchema(
        "Загрузить пакет документов объекта",
        `${UPLOAD_DESCRIPTION} Лимиты ТЗ для загрузки в браузере: файл до limits.max_file_mb, ` +
          "пакет до limits.max_package_mb. Файл больше — отказ FILE_TOO_LARGE, пакет больше отклоняется целиком (413).",
      ),
    },
    receive(browserLimits()),
  );

  // Тот же приём без лимитов размера — для загрузчика папки объекта. Только роль admin:
  // инспектор в браузере лимит ТЗ не обходит.
  app.post(
    LOADER_UPLOAD_PATH,
    {
      preHandler: [authenticate, requireRole("admin")],
      schema: uploadSchema(
        "Загрузить пакет загрузчиком папки объекта: без лимитов размера",
        `${UPLOAD_DESCRIPTION} Маршрут загрузчика (tools/upload_object.py), роль admin. Лимитов размера файла ` +
          "и пакета нет: лимиты ТЗ относятся к загрузке в браузере, крупные пакеты идут через бэк. " +
          "Поля и ответ — как у /api/v1/documents/upload.",
      ),
    },
    receive(LOADER_LIMITS),
  );
}
