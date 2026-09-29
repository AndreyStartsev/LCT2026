import { Redis } from "ioredis";
import { config } from "./config.js";

export const redis = new Redis(config.redisUrl, { lazyConnect: true, maxRetriesPerRequest: 2 });

export interface Progress {
  step: string;
  message: string;
  done?: number;
  total?: number;
  updated_at: string;
}

// Воркер пишет ход обработки в Redis: опрос статуса идёт часто,
// и дёргать ради него базу незачем.
export async function readProgress(processId: string): Promise<Progress | null> {
  try {
    const raw = await redis.get(`process:${processId}:progress`);
    return raw ? (JSON.parse(raw) as Progress) : null;
  } catch {
    return null;
  }
}

// Воркеры держат в Redis признак «чтение моделью уходит во внешний сервис» (service/worker/main.py,
// ключ worker:reading:<узел> со сроком жизни). Экран загрузки по нему предупреждает, что страницы
// прочитает внешняя модель. «Да», если так говорит хоть один живой воркер; живых нет или Redis
// недоступен — признак неизвестен, и поле в /health не отдаётся.
export function externalModel(values: (string | null | undefined)[]): boolean | undefined {
  const known = values.filter((v): v is string => v === "0" || v === "1");
  if (known.length === 0) return undefined;
  return known.includes("1");
}

export async function readExternalModel(): Promise<boolean | undefined> {
  try {
    const keys: string[] = [];
    let cursor = "0";
    do {
      const [next, batch] = await redis.scan(cursor, "MATCH", "worker:reading:*", "COUNT", 100);
      keys.push(...batch);
      cursor = next;
    } while (cursor !== "0");
    return externalModel(keys.length ? await redis.mget(...keys) : []);
  } catch {
    return undefined;
  }
}
