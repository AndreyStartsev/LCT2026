import { timingSafeEqual } from "node:crypto";
import jwt from "@fastify/jwt";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { config, ROLES, type Role } from "./config.js";
import { ApiError } from "./errors.js";
import { bearer } from "./schemas.js";

declare module "@fastify/jwt" {
  interface FastifyJWT {
    payload: { sub: string; role: Role };
    user: { sub: string; role: Role };
  }
}

export async function registerAuth(app: FastifyInstance): Promise<void> {
  await app.register(jwt, { secret: config.jwtSecret, sign: { expiresIn: config.jwtTtlSeconds } });

  app.post(
    "/api/v1/auth/token",
    {
      schema: {
        tags: ["auth"],
        summary: "Получить токен доступа",
        description:
          "Демонстрационная выдача JWT по учётным записям из AUTH_USERS. " +
          "В промышленном контуре заменяется внешним поставщиком удостоверений.",
        body: {
          type: "object",
          required: ["login", "password"],
          properties: { login: { type: "string" }, password: { type: "string" } },
          additionalProperties: false,
        },
        response: {
          200: {
            type: "object",
            required: ["access_token", "token_type", "expires_in", "role"],
            properties: {
              access_token: { type: "string" },
              token_type: { type: "string" },
              expires_in: { type: "integer" },
              role: { type: "string", enum: [...ROLES] },
            },
          },
          401: { $ref: "Error#" },
        },
      },
    },
    async (request) => {
      const { login, password } = request.body as { login: string; password: string };
      const user = config.users.find((u) => u.login === login);
      const ok =
        user !== undefined &&
        user.password.length === password.length &&
        timingSafeEqual(Buffer.from(user.password), Buffer.from(password));
      if (!ok || !user) {
        throw new ApiError(401, "INVALID_CREDENTIALS", "Неверный логин или пароль");
      }
      const token = app.jwt.sign({ sub: user.login, role: user.role });
      return { access_token: token, token_type: "Bearer", expires_in: config.jwtTtlSeconds, role: user.role };
    },
  );
}

export async function authenticate(request: FastifyRequest, reply: FastifyReply): Promise<void> {
  try {
    await request.jwtVerify();
  } catch {
    throw new ApiError(401, "UNAUTHORIZED", "Нужен действующий токен: POST /api/v1/auth/token");
  }
  // user_id в структурных логах запроса и его завершения (ТЗ, раздел 13)
  request.log = request.log.child({ user_id: request.user.sub });
  reply.log = request.log;
}

export function requireRole(role: Role) {
  return async (request: FastifyRequest): Promise<void> => {
    if (request.user.role !== role) {
      throw new ApiError(403, "FORBIDDEN", `Действие доступно только роли ${role}`);
    }
  };
}

export { bearer };
