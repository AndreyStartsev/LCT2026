// Ответ не по своей схеме (Р-163). Проверка ответов (@fastify/response-validation, VALIDATE_RESPONSES включён
// по умолчанию) ставит на свою ошибку 500 поле validation, как у ошибки запроса. Обработчик ошибок отдавал её
// клиенту как 400 VALIDATION_ERROR «Запрос не соответствует схеме OpenAPI: response …» и в журнал ERROR не писал.
// Теперь это внутренняя ошибка: 500 INTERNAL_ERROR, строка ERROR и счётчик 5xx. Запрос не по схеме, как и раньше,
// получает 400 VALIDATION_ERROR с частью запроса.
//   npm test
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { test } from "node:test";

// журнал запросов в выводе теста не нужен; настройки читаются при загрузке модуля
process.env.LOG_LEVEL = "silent";
// проверка ответов — как на стендах, где VALIDATE_RESPONSES не задан
delete process.env.VALIDATE_RESPONSES;
const { buildApp } = await import("../dist/app.js");
const { metrics } = await import("../dist/metrics.js");

const INTERNAL = { error: { code: "INTERNAL_ERROR", message: "Внутренняя ошибка сервиса", details: null } };
const N = { type: "object", required: ["n"], properties: { n: { type: "integer" } } };

/** Маршруты с ответом не по своей схеме: нет обязательного поля, поле не того типа, отказ не по схеме Error. */
const BROKEN = {
  "/test/reply/missing": { schema: { 200: N }, handler: async () => ({}) },
  "/test/reply/type": { schema: { 200: N }, handler: async () => ({ n: "семь" }) },
  "/test/reply/refusal": {
    schema: { 200: N, 409: { $ref: "Error#" } },
    handler: async (_request, reply) => reply.code(409).send({ reason: "процесс занят" }),
  },
};

const valueOf = async (metric, labels) =>
  (await metric.get()).values.find((v) => Object.entries(labels).every(([k, x]) => v.labels[k] === x))?.value ?? 0;

async function withApp(fn) {
  const app = await buildApp();
  for (const [url, { schema, handler }] of Object.entries(BROKEN)) {
    app.get(url, { schema: { response: schema } }, handler);
  }
  // запрос проверяется по всем четырём частям, ответ — по схеме
  app.post(
    "/test/request/:n",
    {
      schema: {
        params: { type: "object", properties: { n: { type: "integer" } } },
        querystring: { type: "object", required: ["q"], properties: { q: { type: "string" } } },
        headers: { type: "object", required: ["x-test"], properties: { "x-test": { type: "string" } } },
        body: N,
        response: { 200: N },
      },
    },
    async (request) => ({ n: request.params.n + request.body.n }),
  );
  await app.ready();
  try {
    await fn(app);
  } finally {
    await app.close();
  }
}

test("ответ не по своей схеме — 500 INTERNAL_ERROR и счётчик 5xx, а не 400 VALIDATION_ERROR", async () => {
  await withApp(async (app) => {
    for (const url of Object.keys(BROKEN)) {
      const before = await valueOf(metrics.errors5xx, { route: url });
      const res = await app.inject({ method: "GET", url });
      assert.equal(res.statusCode, 500, `${url}: ${res.body}`);
      assert.deepEqual(res.json(), INTERNAL, url);
      assert.ok(res.headers["x-request-id"], url);
      assert.equal(await valueOf(metrics.errors5xx, { route: url }), before + 1, url);
    }
  });
});

test("запрос не по схеме — 400 VALIDATION_ERROR с частью запроса, как раньше", async () => {
  await withApp(async (app) => {
    const route = { route: "/test/request/:n" };
    const before = [await valueOf(metrics.errors5xx, route), await valueOf(metrics.requests, { ...route, status_code: "400" })];
    const send = (url, { headers = { "x-test": "1" }, payload = { n: 3 } } = {}) =>
      app.inject({ method: "POST", url, headers, payload });
    const ok = await send("/test/request/2?q=a");
    assert.equal(ok.statusCode, 200, ok.body);
    assert.deepEqual(ok.json(), { n: 5 });

    const cases = [
      ["params", "params/n must be integer", await send("/test/request/x?q=a")],
      ["body", "body must have required property 'n'", await send("/test/request/2?q=a", { payload: {} })],
      ["querystring", "querystring must have required property 'q'", await send("/test/request/2")],
      ["headers", "headers must have required property 'x-test'", await send("/test/request/2?q=a", { headers: {} })],
      // маршрут сервиса
      [
        "body",
        "body must have required property 'password'",
        await app.inject({ method: "POST", url: "/api/v1/auth/token", payload: { login: "admin" } }),
      ],
    ];
    for (const [context, message, res] of cases) {
      assert.equal(res.statusCode, 400, res.body);
      assert.deepEqual(res.json(), {
        error: { code: "VALIDATION_ERROR", message: `Запрос не соответствует схеме OpenAPI: ${message}`, details: { context } },
      });
    }
    const after = [await valueOf(metrics.errors5xx, route), await valueOf(metrics.requests, { ...route, status_code: "400" })];
    assert.deepEqual(after, [before[0], before[1] + 4], "ошибки клиента не считаются ошибками 5xx");
  });
});

test("в журнале сервиса — строка ERROR с кодом и местом расхождения; request_id — из заголовка ответа", () => {
  // pino приложения пишет прямо в fd 1, поэтому журнал читается выводом отдельного процесса
  const script = `
    const { buildApp } = await import(${JSON.stringify(new URL("../dist/app.js", import.meta.url).href)});
    const app = await buildApp();
    app.get("/test/reply/missing", { schema: { response: { 200: ${JSON.stringify(N)} } } }, async () => ({}));
    await app.ready();
    const broken = await app.inject({ method: "GET", url: "/test/reply/missing" });
    const request = await app.inject({ method: "POST", url: "/api/v1/auth/token", payload: { login: "admin" } });
    await app.close();
    const result = [broken, request].map((res) => ({ status: res.statusCode, id: res.headers["x-request-id"] }));
    process.stderr.write("RESULT " + JSON.stringify(result) + "\\n");
  `;
  const child = spawnSync(process.execPath, ["--input-type=module", "-e", script], {
    env: { ...process.env, LOG_LEVEL: "error" },
    encoding: "utf8",
    timeout: 60_000,
  });
  assert.equal(child.status, 0, child.stderr);
  const result = child.stderr.split("\n").find((line) => line.startsWith("RESULT "));
  const [broken, request] = JSON.parse(result.slice("RESULT ".length));
  assert.deepEqual([broken.status, request.status], [500, 400]);

  // одна строка — о сбое ответа; отказ по запросу — ошибка клиента, в журнал ERROR она не пишется
  const lines = child.stdout.split("\n").filter(Boolean).map((line) => JSON.parse(line));
  assert.equal(lines.length, 1, child.stdout);
  const [line] = lines;
  assert.equal(line.level, "ERROR");
  assert.equal(line.message, "необработанная ошибка");
  assert.equal(line.request_id, broken.id);
  assert.equal(line.err.code, "FST_RESPONSE_VALIDATION_FAILED_VALIDATION");
  assert.equal(line.err.message, "response must have required property 'n'");
  assert.deepEqual(
    line.err.validation.map((e) => [e.keyword, e.params.missingProperty]),
    [["required", "n"]],
  );
  assert.ok(line.err.stack, "стек исходной ошибки");
});
