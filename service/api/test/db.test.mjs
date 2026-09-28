// Перезапуск PostgreSQL не роняет API (Р-138). pg-pool 3 объявляет обрыв соединения, которое ждёт
// в пуле, событием «error» пула, а обрыв посреди транзакции — событием «error» клиента на руках;
// событие «error» без слушателя EventEmitter бросает, и процесс завершается. pg подменён: пул
// и клиент — EventEmitter, клиент после обрыва отклоняет запросы, как pg.
//   npm test
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { mock, test } from "node:test";

const dir = mkdtempSync(join(tmpdir(), "db-test-"));
writeFileSync(join(dir, "schema.sql"), "select 1;");
process.env.SCHEMA_PATH = join(dir, "schema.sql");
process.env.DATABASE_PASSWORD = "test";

class FakeClient extends EventEmitter {
  queries = [];
  released = [];
  broken = false;
  async query(text) {
    if (this.broken) throw new Error("Client has encountered a connection error and is not queryable");
    this.queries.push(text);
    return { rows: [], rowCount: 0 };
  }
  release(error) {
    this.released.push(error ?? null);
  }
  /** Сервер завершил сеанс: сначала его сообщение, затем pg объявляет конец соединения. */
  drop(error) {
    this.broken = true;
    this.emit("error", error);
    this.emit("error", new Error("Connection terminated unexpectedly"));
  }
}

class FakePool extends EventEmitter {
  queries = [];
  clients = [];
  constructor(options) {
    super();
    this.options = options;
  }
  async query(text) {
    this.queries.push(text);
    return { rows: [], rowCount: 0 };
  }
  async connect() {
    const client = new FakeClient();
    this.clients.push(client);
    return client;
  }
}
mock.module("pg", { defaultExport: { Pool: FakePool } });

const { migrate, pool, withTransaction } = await import("../dist/db.js");

const logged = [];
const log = Object.fromEntries(
  ["error", "warn", "info"].map((level) => [level, (fields, message) => logged.push({ level, fields, message })]),
);
const terminated = () =>
  Object.assign(new Error("terminating connection due to administrator command"), { code: "57P01", severity: "FATAL" });
/** Дать отработать всему, что ждёт в очереди микрозадач. */
const turn = () => new Promise((resolve) => setImmediate(resolve));

test("обрыв соединения в простое: «error» пула не бросает и пишется в журнал без клиента", async () => {
  await migrate(log);
  assert.deepEqual(pool.queries, ["select 1;"], "схема применена через пул");

  // так pg-pool объявляет ошибку клиента в простое: клиент в самой ошибке и вторым аргументом
  const client = new FakeClient();
  const error = Object.assign(terminated(), { client });
  assert.doesNotThrow(() => pool.emit("error", error, client));
  assert.deepEqual(logged.at(-1), {
    level: "error",
    fields: { code: "57P01", reason: "terminating connection due to administrator command" },
    message: "PostgreSQL: оборвалось соединение в простое",
  });

  const reset = Object.assign(new Error("read ECONNRESET"), { code: "ECONNRESET" });
  assert.doesNotThrow(() => pool.emit("error", reset, new FakeClient()));
  assert.equal(logged.at(-1).fields.code, "ECONNRESET");
});

test("обрыв соединения посреди транзакции: «error» клиента не бросает, клиент в пул не возвращается", async () => {
  const before = logged.length;
  let proceed;
  const gate = new Promise((resolve) => (proceed = resolve));
  const pending = withTransaction(async (db) => {
    await db.query("insert into audit_log default values");
    await gate; // клиент на руках между запросами транзакции
    await db.query("select 2");
  });
  await turn();
  const client = pool.clients.at(-1);
  assert.deepEqual(client.queries, ["begin", "insert into audit_log default values"]);

  const error = terminated();
  assert.doesNotThrow(() => client.drop(error));
  proceed();
  await assert.rejects(pending, /not queryable/);
  assert.deepEqual(client.released, [error], "клиент отдан пулу с ошибкой — пул его закроет");
  assert.equal(client.listenerCount("error"), 0, "слушатель транзакции снят");
  assert.deepEqual(
    logged.slice(before).map((l) => [l.level, l.fields.code, l.message]),
    [["error", "57P01", "PostgreSQL: оборвалось соединение транзакции"]],
    "одна строка на обрыв, по первой ошибке",
  );
});

test("транзакция без обрыва: клиент возвращается в пул как был, слушатель не копится", async () => {
  const result = await withTransaction(async (db) => {
    await db.query("select 1");
    return 42;
  });
  assert.equal(result, 42);
  const client = pool.clients.at(-1);
  assert.deepEqual(client.queries, ["begin", "select 1", "commit"]);
  assert.deepEqual(client.released, [null]);
  assert.equal(client.listenerCount("error"), 0);

  await assert.rejects(
    withTransaction(async () => {
      throw new Error("отказ маршрута");
    }),
    /отказ маршрута/,
  );
  const failed = pool.clients.at(-1);
  assert.deepEqual(failed.queries, ["begin", "rollback"]);
  assert.deepEqual(failed.released, [null], "отказ без обрыва соединения клиента не закрывает");
  assert.equal(failed.listenerCount("error"), 0);
});
