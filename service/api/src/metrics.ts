// Метрики в формате Prometheus. Задача #34, ТЗ раздел 13: запросы в секунду, время ответа,
// ошибки 5xx, размер очереди, активные сессии, диск, CPU и память сервиса.
//
// Метрики API собираются здесь, метрики воркера он пишет в Redis (шаги, время, память),
// а /metrics отдаёт их вместе. Счётчики базы — процессы, решения, передачи — считаются
// в момент запроса метрик.

import { statfs } from "node:fs/promises";
import type { FastifyInstance } from "fastify";
import client from "prom-client";
import { redis } from "./cache.js";
import { pool } from "./db.js";
import { queueDepths } from "./queue.js";

export const registry = new client.Registry();
registry.setDefaultLabels({ service: "api" });
client.collectDefaultMetrics({ register: registry, prefix: "inspector_api_" });

const ACTIVE_WINDOW_MS = 15 * 60 * 1000;
const lastSeen = new Map<string, number>();

export const metrics = {
  requests: new client.Counter({
    name: "inspector_http_requests_total",
    help: "HTTP-запросы к API",
    labelNames: ["method", "route", "status_code"],
    registers: [registry],
  }),
  errors5xx: new client.Counter({
    name: "inspector_http_errors_5xx_total",
    help: "Ответы API с кодом 5xx",
    labelNames: ["route"],
    registers: [registry],
  }),
  duration: new client.Histogram({
    name: "inspector_http_request_duration_seconds",
    help: "Время ответа API",
    labelNames: ["method", "route"],
    buckets: [0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 15, 60],
    registers: [registry],
  }),
  syncAttempts: new client.Counter({
    name: "inspector_iais_sync_attempts_total",
    help: "Попытки передачи протокола в ИАИС «РиН» по результату",
    labelNames: ["result"],
    registers: [registry],
  }),
  syncSeconds: new client.Histogram({
    name: "inspector_iais_sync_seconds",
    help: "Время передачи протокола в ИАИС «РиН»",
    buckets: [0.1, 0.5, 1, 5, 10, 30],
    registers: [registry],
  }),
};

new client.Gauge({
  name: "inspector_active_sessions",
  help: "Пользователи с запросами за последние 15 минут",
  registers: [registry],
  collect() {
    const now = Date.now();
    for (const [user, seen] of lastSeen) {
      if (now - seen > ACTIVE_WINDOW_MS) lastSeen.delete(user);
    }
    this.set(lastSeen.size);
  },
});

new client.Gauge({
  name: "inspector_queue_messages",
  help: "Сообщения в очередях RabbitMQ",
  labelNames: ["queue"],
  registers: [registry],
  async collect() {
    const depths = await queueDepths();
    // без соединения с брокером значений нет: прежние не должны держать QueueBacklog и WorkerSilent
    this.reset();
    for (const [queue, depth] of Object.entries(depths)) {
      this.set({ queue }, depth);
    }
  },
});

const dbGauge = (name: string, help: string, label: string, sql: string) =>
  new client.Gauge({
    name,
    help,
    labelNames: [label],
    registers: [registry],
    async collect() {
      this.reset();
      try {
        const { rows } = await pool.query<{ key: string; n: string }>(sql);
        for (const row of rows) this.set({ [label]: row.key ?? "none" }, Number(row.n));
      } catch {
        // база недоступна: метрика пропускается, а не роняет весь /metrics
      }
    },
  });

dbGauge("inspector_processes", "Процессы проверки по статусу", "status", "select status as key, count(*) as n from processes group by 1");
dbGauge("inspector_findings", "Записи протоколов по статусу верификации", "verification_status",
  "select verification_status as key, count(*) as n from findings group by 1");
dbGauge("inspector_iais_sync", "Передачи в ИАИС «РиН» по статусу", "status",
  "select status as key, count(*) as n from inspection_sync group by 1");
dbGauge("inspector_dataset_items", "Примеры набора решений: черновик и последняя выпущенная версия", "source",
  `select 'draft' as key, count(*) as n from findings f join processes p on p.id = f.process_id
     where p.status = 'FINALIZED' and f.verification_status in ('CONFIRMED_VIOLATION', 'NEGATIVE_VERIFIED')
   union all
   select 'released', coalesce((select items from dataset_versions order by released_at desc limit 1), 0)`);

new client.Gauge({
  name: "inspector_disk_bytes",
  help: "Диск контейнера API",
  labelNames: ["kind"],
  registers: [registry],
  async collect() {
    try {
      const fs = await statfs("/");
      this.set({ kind: "total" }, fs.blocks * fs.bsize);
      this.set({ kind: "free" }, fs.bavail * fs.bsize);
    } catch {
      // statfs недоступен
    }
  },
});

// Метрики воркера: он пишет их в Redis после каждого шага
const workerSteps = new client.Gauge({
  name: "inspector_worker_step_runs_total",
  help: "Шаги обработки воркера по результату (накопительно)",
  labelNames: ["step", "result"],
  registers: [registry],
});
const workerSeconds = new client.Gauge({
  name: "inspector_worker_step_seconds_total",
  help: "Суммарное время шагов воркера, секунд",
  labelNames: ["step"],
  registers: [registry],
});
const workerResources = new client.Gauge({
  name: "inspector_worker_resource",
  help: "Ресурсы процесса воркера: rss_bytes, cpu_seconds, heartbeat_unixtime",
  labelNames: ["kind"],
  registers: [registry],
});

async function collectWorker(): Promise<void> {
  try {
    const [runs, seconds, resources] = await Promise.all([
      redis.hgetall("metrics:worker:step_runs"),
      redis.hgetall("metrics:worker:step_seconds"),
      redis.hgetall("metrics:worker:resources"),
    ]);
    for (const [key, value] of Object.entries(runs)) {
      const [step, result] = key.split(":");
      workerSteps.set({ step, result }, Number(value));
    }
    for (const [step, value] of Object.entries(seconds)) workerSeconds.set({ step }, Number(value));
    for (const [kind, value] of Object.entries(resources)) workerResources.set({ kind }, Number(value));
  } catch {
    // Redis недоступен
  }
}

/**
 * Хуки учёта запросов и маршрут /metrics. Вызывается прямо на корневом приложении, а не через
 * app.register: хуки внутри плагина Fastify действуют только на маршруты этого плагина,
 * и запросы к остальному API не считались бы.
 */
export async function registerMetrics(app: FastifyInstance): Promise<void> {
  app.addHook("onRequest", async (request) => {
    (request as { startedAt?: bigint }).startedAt = process.hrtime.bigint();
  });
  app.addHook("onResponse", async (request, reply) => {
    const route = request.routeOptions.url ?? "unmatched";
    if (route === "/metrics") return;
    const started = (request as { startedAt?: bigint }).startedAt;
    const seconds = started ? Number(process.hrtime.bigint() - started) / 1e9 : 0;
    metrics.requests.inc({ method: request.method, route, status_code: String(reply.statusCode) });
    metrics.duration.observe({ method: request.method, route }, seconds);
    if (reply.statusCode >= 500) metrics.errors5xx.inc({ route });
    const user = (request as { user?: { sub?: string } }).user?.sub;
    if (user) lastSeen.set(user, Date.now());
  });

  app.get("/metrics", { schema: { hide: true } }, async (_request, reply) => {
    await collectWorker();
    reply.header("content-type", registry.contentType);
    return registry.metrics();
  });
}
