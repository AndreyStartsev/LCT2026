// Ответ на внутреннюю ошибку (Р-162). При 5xx клиент получает код INTERNAL_ERROR и общее сообщение, а код
// исходной ошибки — код Node, SQLSTATE PostgreSQL, ECONNREFUSED — остаётся только в строке журнала ERROR.
// 29.09 вход на демо-стенде ответил кодом ERR_CRYPTO_TIMING_SAFE_EQUAL_LENGTH (Р-160). Коды 4xx самого
// Fastify клиент получает, как раньше.
//   npm test
import assert from "node:assert/strict";
import { timingSafeEqual } from "node:crypto";
import { test } from "node:test";
import Fastify from "fastify";
import pg from "pg";

// журнал запросов в выводе теста не нужен; настройка читается при загрузке модуля
process.env.LOG_LEVEL = "silent";
const { buildApp } = await import("../dist/app.js");
const { installErrorHandler } = await import("../dist/errors.js");

const INTERNAL = { error: { code: "INTERNAL_ERROR", message: "Внутренняя ошибка сервиса", details: null } };

/** Ошибка сервера PostgreSQL в том виде, в каком её собирает разборщик протокола pg. */
function dbError(code, message, fields) {
  return Object.assign(new pg.DatabaseError(message, message.length, "error"), { code, ...fields });
}

/** Ошибки зависимостей по коду, который до Р-162 уходил клиенту. */
const FAILURES = {
  // перезапуск PostgreSQL обрывает сеансы: SQLSTATE admin_shutdown
  "57P01": () => dbError("57P01", "terminating connection due to administrator command", { severity: "FATAL" }),
  // нарушение уникальности: в полях ошибки — имя ограничения и значение ключа
  "23505": () => dbError("23505", 'duplicate key value violates unique constraint "processes_pkey"', {
    severity: "ERROR", constraint: "processes_pkey", detail: "Key (id)=(11111111-1111-4111-8111-111111111111) already exists.",
  }),
  // база или брокер не принимают соединение: в сообщении — адрес во внутренней сети
  ECONNREFUSED: () => Object.assign(new Error("connect ECONNREFUSED 172.18.0.5:5432"), {
    errno: -111, code: "ECONNREFUSED", syscall: "connect", address: "172.18.0.5", port: 5432,
  }),
  // так ответил вход на демо-стенде: буферы разной длины
  ERR_CRYPTO_TIMING_SAFE_EQUAL_LENGTH: () => {
    try {
      timingSafeEqual(Buffer.from("admin-pass"), Buffer.from("фвьшт-зфыы"));
    } catch (error) {
      return error;
    }
    throw new Error("timingSafeEqual не бросил на буферах разной длины");
  },
  // код самого Fastify при 5xx — тоже внутренний
  FST_ERR_BAD_STATUS_CODE: () => new Fastify.errorCodes.FST_ERR_BAD_STATUS_CODE(999),
  // ошибка со своим статусом 5xx: статус остаётся, код — нет
  UPSTREAM_UNAVAILABLE: () => Object.assign(new Error("upstream unavailable"), { statusCode: 503, code: "UPSTREAM_UNAVAILABLE" }),
};

/** Маршрут теста бросает ошибку зависимости, как маршрут сервиса при сбое базы, брокера или кода. */
function failRoute(app) {
  app.get("/test/fail/:code", async (request) => {
    throw FAILURES[request.params.code]();
  });
}

async function withApp(fn) {
  const app = await buildApp();
  failRoute(app);
  await app.ready();
  try {
    await fn(app);
  } finally {
    await app.close();
  }
}

test("5xx: клиент получает INTERNAL_ERROR и общее сообщение, а не код и подробности исходной ошибки", async () => {
  await withApp(async (app) => {
    for (const [code, make] of Object.entries(FAILURES)) {
      const error = make();
      assert.equal(error.code, code, "у исходной ошибки свой код");
      const res = await app.inject({ method: "GET", url: `/test/fail/${code}` });
      assert.equal(res.statusCode, error.statusCode ?? 500, code);
      assert.deepEqual(res.json(), INTERNAL, `${code}: ${res.body}`);
    }
  });
});

test("4xx самого Fastify — со своим кодом и сообщением, как раньше", async () => {
  await withApp(async (app) => {
    const login = (headers, payload) => app.inject({ method: "POST", url: "/api/v1/auth/token", headers, payload });
    const tooLarge = await login(
      { "content-type": "application/json" },
      JSON.stringify({ login: "admin", password: "x".repeat(1024 * 1024) }),
    );
    assert.equal(tooLarge.statusCode, 413, tooLarge.body);
    assert.deepEqual(tooLarge.json().error, { code: "FST_ERR_CTP_BODY_TOO_LARGE", message: "Request body is too large", details: null });
    const media = await login({ "content-type": "application/xml" }, "<login/>");
    assert.equal(media.statusCode, 415, media.body);
    assert.equal(media.json().error.code, "FST_ERR_CTP_INVALID_MEDIA_TYPE");
    const json = await login({ "content-type": "application/json" }, "{");
    assert.equal(json.statusCode, 400, json.body);
    assert.equal(json.json().error.code, "FST_ERR_CTP_INVALID_JSON_BODY");
  });
});

test("исходная ошибка с её кодом остаётся в строке журнала ERROR", async () => {
  const lines = [];
  const app = Fastify({ logger: { level: "error", stream: { write: (line) => lines.push(JSON.parse(line)) } } });
  installErrorHandler(app);
  failRoute(app);
  await app.ready();
  try {
    for (const code of Object.keys(FAILURES)) {
      const res = await app.inject({ method: "GET", url: `/test/fail/${code}` });
      assert.deepEqual(res.json(), INTERNAL, code);
    }
  } finally {
    await app.close();
  }
  const logged = lines.filter((line) => line.msg === "необработанная ошибка");
  assert.deepEqual(logged.map((line) => line.err.code), Object.keys(FAILURES));
  for (const line of logged) {
    assert.equal(line.level, 50, line.err.code);
    assert.ok(line.err.message && line.err.stack, line.err.code);
  }
  const unique = logged.find((line) => line.err.code === "23505").err;
  assert.equal(unique.constraint, "processes_pkey", "поля ошибки базы — в журнале");
  assert.equal(logged.find((line) => line.err.code === "ECONNREFUSED").err.address, "172.18.0.5");
});
