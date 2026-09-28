// Учёт запросов в метриках: хуки должны действовать на все маршруты приложения, а не только на /metrics.
// Сам /metrics здесь не запрашивается: он обращается к Redis и базе, которых в тесте нет.
import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import { metrics, registerMetrics } from "../dist/metrics.js";

const valueOf = async (metric, labels) =>
  (await metric.get()).values.find((v) => Object.entries(labels).every(([k, x]) => v.labels[k] === x))?.value ?? 0;

test("запросы к маршрутам приложения попадают в счётчики и гистограмму", async () => {
  const app = Fastify({ logger: false });
  await registerMetrics(app);
  app.get("/api/v1/ping", async () => ({ ok: true }));
  app.get("/api/v1/boom", async () => {
    throw new Error("сбой");
  });
  await app.ready();
  await app.inject({ method: "GET", url: "/api/v1/ping" });
  await app.inject({ method: "GET", url: "/api/v1/ping" });
  await app.inject({ method: "GET", url: "/api/v1/boom" });

  assert.equal(await valueOf(metrics.requests, { route: "/api/v1/ping", status_code: "200" }), 2);
  assert.equal(await valueOf(metrics.errors5xx, { route: "/api/v1/boom" }), 1);
  const count = (await metrics.duration.get()).values.find(
    (v) => v.metricName === "inspector_http_request_duration_seconds_count" && v.labels.route === "/api/v1/ping",
  );
  assert.equal(count?.value, 2);
  await app.close();
});
