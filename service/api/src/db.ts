import { readFile } from "node:fs/promises";
import type { FastifyBaseLogger } from "fastify";
import pg from "pg";
import { config } from "./config.js";

let _pool: pg.Pool | null = null;
/** журнал приложения, его передаёт server.ts при применении схемы */
let log: FastifyBaseLogger | null = null;

/** Ошибка соединения с базой: код SQLSTATE (57P01 при остановке базы) или системный (ECONNRESET). */
type ConnectionError = Error & { code?: string };

/** Поля журнала для ошибки соединения. pg-pool кладёт в ошибку весь клиент (err.client), он в журнал не идёт. */
const lostFields = (error: ConnectionError) => ({ code: error.code, reason: error.message });

// Пул создаётся при первом обращении: выгрузке OpenAPI база и её пароль не нужны.
// Перезапуск PostgreSQL или обрыв сети не должен ронять API (Р-138). Соединение, которое ждёт
// в пуле, сообщает об обрыве событием «error», и pg-pool 3 передаёт его событием «error» пула.
// Событие «error» без слушателя Node превращает в исключение, и процесс завершается. Такого
// клиента пул уже убрал сам, следующий запрос откроет новое соединение, поэтому ошибка только
// пишется в журнал.
function getPool(): pg.Pool {
  if (!_pool) {
    _pool = new pg.Pool({ ...config.database(), max: 10 });
    _pool.on("error", (error: ConnectionError) => {
      log?.error(lostFields(error), "PostgreSQL: оборвалось соединение в простое");
    });
  }
  return _pool;
}

export const pool = new Proxy({} as pg.Pool, {
  get(_target, property) {
    const target = getPool();
    const value = Reflect.get(target, property, target);
    return typeof value === "function" ? value.bind(target) : value;
  },
});

export type Queryable = pg.Pool | pg.PoolClient;

// Схема применяется при каждом старте: все выражения в ней идемпотентны.
export async function migrate(logger?: FastifyBaseLogger): Promise<void> {
  if (logger) log = logger;
  const sql = await readFile(config.schemaPath, "utf-8");
  await pool.query(sql);
}

export async function withTransaction<T>(fn: (client: pg.PoolClient) => Promise<T>): Promise<T> {
  const client = await pool.connect();
  // Клиента на руках пул не слушает: обрыв соединения посреди транзакции приходит событием «error»
  // самого клиента и без слушателя тоже завершает процесс. Запросы транзакции получают отказ,
  // а клиент с оборванным соединением в пул не возвращается.
  let lost: ConnectionError | undefined;
  const onError = (error: ConnectionError) => {
    // за сообщением сервера о завершении сеанса pg объявляет ещё и конец соединения
    if (lost) return;
    lost = error;
    log?.error(lostFields(error), "PostgreSQL: оборвалось соединение транзакции");
  };
  client.on("error", onError);
  try {
    await client.query("begin");
    const result = await fn(client);
    await client.query("commit");
    return result;
  } catch (error) {
    await client.query("rollback");
    throw error;
  } finally {
    client.off("error", onError);
    client.release(lost);
  }
}

export async function audit(
  db: Queryable,
  entry: {
    userId: string | null;
    action: string;
    objectId?: string | null;
    processId?: string | null;
    details?: Record<string, unknown>;
    ip?: string | null;
    userAgent?: string | null;
  },
): Promise<void> {
  await db.query(
    `insert into audit_log (user_id, action, object_id, process_id, details, ip_address, user_agent)
     values ($1, $2, $3, $4, $5, $6, $7)`,
    [
      entry.userId,
      entry.action,
      entry.objectId ?? null,
      entry.processId ?? null,
      JSON.stringify(entry.details ?? {}),
      entry.ip ?? null,
      entry.userAgent ?? null,
    ],
  );
}

export async function notify(
  db: Queryable,
  role: "inspector" | "admin",
  level: "INFO" | "WARNING" | "ERROR",
  message: string,
  processId: string | null = null,
): Promise<void> {
  await db.query(
    "insert into notifications (role, process_id, level, message) values ($1, $2, $3, $4)",
    [role, processId, level, message],
  );
}
