import { buildApp } from "./app.js";
import { redis } from "./cache.js";
import { config } from "./config.js";
import { migrate } from "./db.js";
import { connectQueue } from "./queue.js";
import { ensureBucket } from "./storage.js";
import { startSyncLoop } from "./sync.js";

async function retry(name: string, fn: () => Promise<unknown>, attempts = 60): Promise<void> {
  for (let i = 1; ; i++) {
    try {
      await fn();
      return;
    } catch (error) {
      if (i >= attempts) {
        throw new Error(`${name}: не удалось подключиться за ${attempts} попыток: ${(error as Error).message}`);
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
  }
}

async function main(): Promise<void> {
  const app = await buildApp();
  await retry("PostgreSQL", () => migrate(app.log));
  await retry("MinIO", ensureBucket);
  await retry("RabbitMQ", () => connectQueue(app.log));
  await retry("Redis", () => redis.connect());
  await app.listen({ host: "0.0.0.0", port: config.port });
  startSyncLoop(app.log);
  app.log.info(
    `лимиты: файл ${config.limits.maxFileBytes / 1024 / 1024} МБ, пакет ${config.limits.maxPackageBytes / 1024 / 1024} МБ`,
  );
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
