import multipart from "@fastify/multipart";
import responseValidation from "@fastify/response-validation";
import swagger from "@fastify/swagger";
import swaggerUi from "@fastify/swagger-ui";
import { Ajv } from "ajv";
import addFormats from "ajv-formats";
import { randomUUID } from "node:crypto";
import Fastify, { LogController, type FastifyInstance } from "fastify";
import { registerAuth } from "./auth.js";
import { config } from "./config.js";
import { installErrorHandler } from "./errors.js";
import { FORMAT_LIST, LOADER_UPLOAD_PATH } from "./filecheck.js";
import { documentRoutes } from "./routes/documents.js";
import { findingRoutes } from "./routes/findings.js";
import { objectRoutes } from "./routes/objects.js";
import { processRoutes } from "./routes/process.js";
import { addSharedSchemas, sharedSchemas } from "./schemas.js";
import { datasetRoutes } from "./dataset.js";
import { registerMetrics } from "./metrics.js";
import { reportRoutes } from "./routes/report.js";
import { linksRoutes } from "./routes/links.js";
import { proposalRoutes } from "./routes/proposals.js";
import { rulesRoutes } from "./routes/rules.js";

const UPLOAD_BODY = {
  type: "object",
  properties: {
    process_id: { type: "string", format: "uuid", description: "дозагрузка в существующий процесс" },
    object_id: { type: "string", description: "идентификатор объекта для нового процесса, например OBJ-NOVOSLOBODSKAYA" },
    object_name: { type: "string" },
    final_batch: { type: "boolean", default: true, description: "false — не запускать разбор после этого пакета" },
    upload_key: {
      type: "string",
      pattern: "^[A-Za-z0-9-]{8,64}$",
      description:
        "ключ загрузки, один на все пакеты и повторы: повтор без process_id попадает в уже заведённый процесс, " +
        "повтор принятого последнего пакета получает already_accepted=true",
    },
    reading_mode: { type: "string", enum: ["layer", "tesseract", "model"], description: "способ чтения нового объекта" },
    model_name: { type: "string", description: "модель для способа «model» из limits.reading_models" },
    relative_path: { type: "string", description: "путь файла внутри папки; поле идёт перед файлом" },
    skipped: {
      type: "string",
      description: "JSON-массив {relative_path, size_bytes}: файлы, не переданные клиентом как заведомо неподходящие",
    },
    files: {
      type: "array",
      items: { type: "string", format: "binary" },
      description: `файлы: ${FORMAT_LIST.join(", ")}`,
    },
  },
};

/** Собирает приложение без подключения к зависимостям: так его можно выгрузить в OpenAPI. */
export async function buildApp(): Promise<FastifyInstance> {
  const app = Fastify({
    // Структурные логи по ТЗ, раздел 13: JSON с полями timestamp, level, service, message,
    // request_id, user_id (user_id добавляет проверка токена)
    logger: {
      level: config.logLevel,
      messageKey: "message",
      base: { service: "api" },
      timestamp: () => `,"timestamp":"${new Date().toISOString()}"`,
      formatters: { level: (label: string) => ({ level: label.toUpperCase() }) },
    },
    logController: new LogController({ requestIdLogLabel: "request_id" }),
    // Идентификатор запроса уникален между перезапусками и уходит в сообщение очереди, так что
    // строки логов воркера связываются с запросом загрузки. Заголовок X-Request-Id от прокси
    // принимается, если похож на идентификатор, иначе создаётся новый.
    genReqId: (req) => {
      const incoming = req.headers["x-request-id"];
      return typeof incoming === "string" && /^[A-Za-z0-9._-]{8,64}$/.test(incoming) ? incoming : randomUUID();
    },
    bodyLimit: 1024 * 1024,
    ajv: { customOptions: { removeAdditional: false } },
  });
  installErrorHandler(app);
  addSharedSchemas(app);
  app.addHook("onRequest", async (request, reply) => {
    reply.header("x-request-id", request.id);
  });

  await app.register(swagger, {
    openapi: {
      openapi: "3.0.3",
      info: {
        title: "Инспектор ИИ",
        version: "0.1.0",
        description:
          "Сверка проектной, рабочей и исполнительной документации. Асинхронная pull-модель: " +
          "загрузка возвращает process_id, клиент опрашивает статус и забирает протокол.",
      },
      components: {
        securitySchemes: { bearerAuth: { type: "http", scheme: "bearer", bearerFormat: "JWT" } },
      },
      tags: [
        { name: "auth", description: "доступ" },
        { name: "documents", description: "загрузка и дозагрузка" },
        { name: "process", description: "процесс проверки и протокол" },
        { name: "findings", description: "верификация инспектором" },
        { name: "objects", description: "дашборд объектов" },
        { name: "dataset", description: "решения инспектора как набор примеров" },
        { name: "rules", description: "правила сверки для эксперта" },
        { name: "system", description: "служебное" },
      ],
    },
    refResolver: {
      buildLocalReference: (json, _baseUri, _fragment, i) => (typeof json.$id === "string" ? json.$id : `def-${i}`),
    },
    // Тело multipart разбирается потоком и Fastify его не валидирует,
    // поэтому схема тела есть только в описании API.
    transform: ({ schema, url }) => {
      if (url === "/api/v1/documents/upload" || url === LOADER_UPLOAD_PATH) {
        return { schema: { ...schema, body: UPLOAD_BODY } as typeof schema, url };
      }
      return { schema, url };
    },
  });
  await app.register(swaggerUi, { routePrefix: "/api/docs" });

  if (config.validateResponses) {
    // Ответы проверяются по той же схеме, из которой собран OpenAPI:
    // расхождение кода и описания ловится сразу, ошибкой 500, а не у клиента.
    const ajv = new Ajv({ allErrors: true, coerceTypes: false, useDefaults: false, removeAdditional: false, strict: false });
    addFormats.default(ajv);
    for (const schema of sharedSchemas) {
      ajv.addSchema(schema);
    }
    await app.register(responseValidation, { ajv });
  }

  await app.register(multipart, {
    throwFileSizeLimit: false,
    limits: {
      // лимит загрузки в браузере; маршрут загрузчика снимает его на свой запрос (Р-110)
      fileSize: config.limits.maxFileBytes,
      files: 5000,
      fields: 20000,
      fieldSize: 1024 * 1024,
      parts: 30000,
    },
  });

  await registerMetrics(app);
  await registerAuth(app);
  await app.register(documentRoutes);
  await app.register(processRoutes);
  await app.register(findingRoutes);
  await app.register(objectRoutes);
  await app.register(reportRoutes);
  await app.register(linksRoutes);
  await app.register(datasetRoutes);
  await app.register(rulesRoutes);
  await app.register(proposalRoutes);

  app.get("/api/v1/openapi.json", { schema: { hide: true } }, async () => app.swagger());
  return app;
}
