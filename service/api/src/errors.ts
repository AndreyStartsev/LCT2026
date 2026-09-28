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
    if ((error as FastifyError).validation) {
      return reply.status(400).send({
        error: {
          code: "VALIDATION_ERROR",
          message: `Запрос не соответствует схеме OpenAPI: ${error.message}`,
          details: { context: (error as FastifyError).validationContext ?? null },
        },
      });
    }
    const status = (error as FastifyError).statusCode ?? 500;
    if (status >= 500) {
      request.log.error({ err: error }, "необработанная ошибка");
    }
    return reply.status(status).send({
      error: {
        code: (error as FastifyError).code ?? "INTERNAL_ERROR",
        message: status >= 500 ? "Внутренняя ошибка сервиса" : error.message,
        details: null,
      },
    });
  });
}
