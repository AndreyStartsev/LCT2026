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
