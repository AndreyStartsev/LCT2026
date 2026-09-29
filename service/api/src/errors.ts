import type { FastifyError, FastifyInstance } from "fastify";

/** Ошибка с кодом для клиента. Сообщение пишется для человека, код — для программы. */
export class ApiError extends Error {
  constructor(
    readonly statusCode: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> | null = null,
  ) {
    super(message);
  }
}

export function installErrorHandler(app: FastifyInstance): void {
  app.setErrorHandler((error: FastifyError | ApiError, request, reply) => {
    if (error instanceof ApiError) {
      return reply.status(error.statusCode).send({
        error: { code: error.code, message: error.message, details: error.details },
      });
    }
    const status = (error as FastifyError).statusCode ?? 500;
    if (status >= 500) {
      // Код исходной ошибки (код Node, SQLSTATE PostgreSQL, ECONNREFUSED) — только в журнал:
      // клиенту он ничего не говорит, а устройство сервиса выдаёт (Р-162).
      // Сюда же идёт ответ не по своей схеме: @fastify/response-validation ставит на свою ошибку validation,
      // как у ошибки запроса, но со статусом 500 — ошибка в коде сервиса, а не в запросе (Р-163)
      request.log.error({ err: error }, "необработанная ошибка");
      return reply.status(status).send({
        error: { code: "INTERNAL_ERROR", message: "Внутренняя ошибка сервиса", details: null },
      });
    }
    // запрос не по схеме: у Fastify это 400 с частью запроса — body, querystring, params, headers
    if ((error as FastifyError).validation) {
      return reply.status(400).send({
        error: {
          code: "VALIDATION_ERROR",
          message: `Запрос не соответствует схеме OpenAPI: ${error.message}`,
          details: { context: (error as FastifyError).validationContext ?? null },
        },
      });
    }
    // 4xx самого Fastify и плагинов, например 413 FST_ERR_CTP_BODY_TOO_LARGE, — со своим кодом
    return reply.status(status).send({
      error: { code: (error as FastifyError).code ?? "INTERNAL_ERROR", message: error.message, details: null },
    });
  });
}
