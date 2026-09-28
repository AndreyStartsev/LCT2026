// Обрыв связи с брокером не роняет API (Р-135). amqplib 0.10 сообщает об обрыве событием «error»
// соединения, а об отказе брокера в операции — «error» канала; событие «error» без слушателя Node
// превращает в исключение, и процесс завершается. amqplib подменён: соединение и канал —
// EventEmitter, события идут в порядке amqplib: «error», затем «close» каналов, затем «close»
// соединения. Тесты идут по очереди и оставляют модуль подключённым.
//   npm test
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mock, test } from "node:test";

process.env.LOG_LEVEL = "silent";

class FakeChannel extends EventEmitter {
  sent = [];
  closed = false;
  async assertQueue(queue) {
    // брокер закрывает канал кадром, пришедшим вместе с ответом на последнее объявление
    if (queue === "protocol" && shutOnLastAssert) this.shut(new Error("Channel closed by server: 406 (PRECONDITION-FAILED)"));
    return { queue, messageCount: 0, consumerCount: 0 };
  }
  async checkQueue(queue) {
    if (this.closed) throw new Error("Channel closed");
    return { queue, messageCount: 3, consumerCount: 1 };
  }
  sendToQueue(queue, content) {
    this.sent.push({ queue, message: JSON.parse(content.toString()) });
    return true;
  }
  async waitForConfirms() {}
  /** Закрытие канала: брокер отказал в операции (с ошибкой) или ушло соединение (без неё). */
  shut(error) {
    if (this.closed) return;
    this.closed = true;
    if (error) this.emit("error", error);
    this.emit("close");
  }
}

class FakeConnection extends EventEmitter {
  closed = false;
  closeCalls = 0;
  channel = null;
  async createConfirmChannel() {
    this.channel = new FakeChannel();
    return this.channel;
  }
  async close() {
    this.closeCalls++;
    if (this.closed) throw new Error("Connection closed (by client)");
    this.drop();
  }
  /** Конец соединения: с ошибкой — обрыв сокета или heartbeat, без неё — CONNECTION_FORCED. */
  drop(error) {
    if (this.closed) return;
    this.closed = true;
    if (error) this.emit("error", error);
    this.channel?.shut();
    this.emit("close", error);
  }
}

const connections = [];
let attempts = 0;
let refuse = 0; // сколько следующих подключений отклонить, как у остановленного брокера
let shutOnLastAssert = false;
mock.module("amqplib", {
  defaultExport: {
    async connect() {
      attempts++;
      if (refuse > 0) {
        refuse--;
        throw Object.assign(new Error("getaddrinfo ENOTFOUND rabbitmq"), { code: "ENOTFOUND" });
      }
      const connection = new FakeConnection();
      connections.push(connection);
      return connection;
    },
  },
});

const { connectQueue, publish, queueReady } = await import("../dist/queue.js");
const { registry } = await import("../dist/metrics.js");

const logged = [];
const log = Object.fromEntries(
  ["error", "warn", "info"].map((level) => [level, (fields, message) => logged.push({ level, fields, message })]),
);
/** Дать отработать отложенному на следующий обход событий. */
const turn = () => new Promise((resolve) => setImmediate(resolve));

test("обрыв соединения: «error» и «close» не роняют процесс, следующая отправка подключается заново", async () => {
  await connectQueue(log);
  assert.equal(queueReady(), true);
  const first = connections.at(-1);

  const error = Object.assign(new Error("read ECONNRESET"), { code: "ECONNRESET" });
  assert.doesNotThrow(() => first.drop(error));
  assert.equal(queueReady(), false, "канал сброшен");
  assert.ok(logged.some((l) => l.level === "error" && l.fields?.err === error), "ошибка соединения в журнале");

  await publish("parse", "p-1", "inspector", "req-1");
  const second = connections.at(-1);
  assert.notEqual(second, first, "отправка открыла новое соединение");
  assert.equal(queueReady(), true);
  assert.deepEqual(
    second.channel.sent.map(({ queue, message }) => [queue, message.process_id, message.request_id]),
    [["parse", "p-1", "req-1"]],
  );
});

test("брокер закрыл только канал: процесс жив, соединение без канала закрыто и не сбрасывает новый канал", async () => {
  const before = connections.at(-1);
  const error = Object.assign(new Error("Channel closed by server: 404 (NOT-FOUND)"), { code: 404 });
  assert.doesNotThrow(() => before.channel.shut(error));
  assert.equal(queueReady(), false);
  assert.ok(logged.some((l) => l.level === "error" && l.fields?.err === error), "ошибка канала в журнале");

  // отправка успевает раньше, чем закроется прежнее соединение
  await publish("compare", "p-2", null);
  const after = connections.at(-1);
  assert.notEqual(after, before);
  assert.equal(after.channel.sent.length, 1);

  await turn();
  assert.equal(before.closeCalls, 1, "соединение без канала закрыто");
  assert.equal(before.closed, true);
  assert.equal(queueReady(), true, "закрытие прежнего соединения не трогает канал нового");
});

test("фоновое переподключение: очередь в /health оживает без отправки, паузы растут", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  refuse = 2;
  const start = attempts;
  connections.at(-1).drop(); // штатная остановка брокера: только «close»
  assert.equal(queueReady(), false);

  t.mock.timers.tick(999);
  await turn();
  assert.equal(attempts, start, "первая попытка — через секунду");
  t.mock.timers.tick(1);
  await turn();
  assert.equal(attempts, start + 1);
  assert.equal(queueReady(), false, "брокер ещё не отвечает");

  t.mock.timers.tick(1999);
  await turn();
  assert.equal(attempts, start + 1, "вторая пауза вдвое длиннее");
  t.mock.timers.tick(1);
  await turn();
  assert.equal(attempts, start + 2);

  t.mock.timers.tick(4000);
  await turn();
  assert.equal(attempts, start + 3);
  assert.equal(queueReady(), true, "подключено без отправки");
  assert.ok(logged.some((l) => l.level === "warn" && l.fields?.err?.code === "ENOTFOUND"), "неудачная попытка в журнале");
  assert.ok(logged.some((l) => l.level === "info" && typeof l.fields?.down_ms === "number"), "восстановление в журнале");

  t.mock.timers.tick(60_000);
  await turn();
  assert.equal(attempts, start + 3, "после подключения попыток больше нет");
});

test("канал, закрытый брокером сразу за объявлением очередей, рабочим не становится", async () => {
  connections.at(-1).drop();
  shutOnLastAssert = true;
  await assert.rejects(connectQueue(), /канал закрылся при подключении/);
  shutOnLastAssert = false;
  assert.equal(queueReady(), false);
  assert.equal(connections.at(-1).closed, true, "соединение с закрытым каналом закрыто");

  await connectQueue();
  assert.equal(queueReady(), true);
});

test("метрика очередей без соединения пуста, а не держит прежние значения", async () => {
  const gauge = registry.getSingleMetric("inspector_queue_messages");
  const depths = async () => (await gauge.get()).values.map((v) => [v.labels.queue, v.value]);
  assert.deepEqual(await depths(), [["parse", 3], ["compare", 3], ["protocol", 3]]);

  connections.at(-1).drop(new Error("Heartbeat timeout"));
  assert.deepEqual(await depths(), []);

  await connectQueue();
  assert.deepEqual(await depths(), [["parse", 3], ["compare", 3], ["protocol", 3]]);
});
