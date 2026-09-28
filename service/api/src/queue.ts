import amqp from "amqplib";
import type { FastifyBaseLogger } from "fastify";
import { config, QUEUES, RULE_TEST_QUEUE, type QueueName } from "./config.js";

// Одно соединение с брокером и один канал с подтверждениями. Обрыв связи не должен ронять API
// (Р-135). amqplib 0.10 сообщает об обрыве событием «error» соединения: ошибка или конец сокета,
// пропущенный heartbeat, закрытие брокером с тяжёлым кодом; штатная остановка брокера
// (CONNECTION_FORCED) приходит одним «close». Канал получает «error», когда брокер отказал
// в операции и закрыл только его, например checkQueue удалённой очереди. Событие «error» без
// слушателя Node превращает в исключение, и процесс завершается, поэтому слушаются оба.
// Потерянный канал сбрасывается, а соединение восстанавливается в фоне с растущей паузой:
// проверка очереди в /health и метрика очередей оживают, не дожидаясь следующей отправки.

/** Паузы фонового переподключения: первая, затем вдвое длиннее, но не больше потолка. */
const RETRY_FIRST_MS = 1000;
const RETRY_MAX_MS = 15_000;

let channel: amqp.ConfirmChannel | null = null;
let connecting: Promise<void> | null = null;
let retryTimer: NodeJS.Timeout | null = null;
let retryDelay = RETRY_FIRST_MS;
/** когда пропал рабочий канал; null — канал есть или ещё не открывался */
let lostAt: number | null = null;
/** журнал приложения, его передаёт server.ts при первом подключении */
let log: FastifyBaseLogger | null = null;

/** Подключается к брокеру и объявляет очереди; одновременные вызовы ждут одно подключение. */
export async function connectQueue(logger?: FastifyBaseLogger): Promise<void> {
  if (logger) log = logger;
  if (channel) return;
  connecting ??= open().finally(() => {
    connecting = null;
  });
  await connecting;
}

async function open(): Promise<void> {
  const connection = await amqp.connect(config.amqpUrl);
  let connectionClosed = false;
  let channelClosed = false;
  connection.on("error", (error: Error) => {
    log?.error({ err: error }, "RabbitMQ: ошибка соединения");
  });
  connection.on("close", (error?: Error) => {
    connectionClosed = true;
    log?.warn({ reason: error?.message ?? null }, "RabbitMQ: соединение закрыто");
    if (!channel && lostAt !== null) scheduleRetry();
  });
  try {
    const ch = await connection.createConfirmChannel();
    ch.on("error", (error: Error) => {
      log?.error({ err: error }, "RabbitMQ: ошибка канала");
    });
    ch.on("close", () => {
      channelClosed = true;
      if (channel === ch) {
        channel = null;
        lostAt = Date.now();
      }
      // При обрыве соединения amqplib закрывает каналы раньше, чем объявляет «close» соединения.
      // Если к следующему обходу событий соединение живо, канал закрыл брокер: соединение без
      // канала не нужно, а его «close» запустит переподключение.
      setImmediate(() => {
        if (!connectionClosed) connection.close().catch(() => {});
      });
    });
    for (const name of [...QUEUES, RULE_TEST_QUEUE]) {
      await ch.assertQueue(name, { durable: true });
    }
    // amqplib разбирает несколько кадров за раз: закрытие могло прийти сразу за ответом
    if (channelClosed) throw new Error("RabbitMQ: канал закрылся при подключении");
    channel = ch;
  } catch (error) {
    if (!connectionClosed) connection.close().catch(() => {});
    throw error;
  }
  retryDelay = RETRY_FIRST_MS;
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
  if (lostAt !== null) {
    log?.info({ down_ms: Date.now() - lostAt }, "RabbitMQ: соединение восстановлено");
    lostAt = null;
  }
}

/** Следующая попытка фонового переподключения; таймер не держит процесс. */
function scheduleRetry(): void {
  if (retryTimer) return;
  const delay = retryDelay;
  retryDelay = Math.min(retryDelay * 2, RETRY_MAX_MS);
  retryTimer = setTimeout(() => {
    retryTimer = null;
    connectQueue().catch((error: Error) => {
      log?.warn({ err: error, retry_in_ms: retryDelay }, "RabbitMQ недоступен");
      scheduleRetry();
    });
  }, delay);
  retryTimer.unref();
}

export interface JobMessage {
  process_id: string;
  step: QueueName;
  attempt: number;
  requested_by: string | null;
  requested_at: string;
  /** запрос API, с которого началась обработка: по нему строки логов воркера связываются с запросом */
  request_id: string | null;
}

/** Ставит шаг обработки в очередь и ждёт подтверждения брокера. */
export async function publish(step: QueueName, processId: string, requestedBy: string | null, requestId: string | null = null): Promise<void> {
  await connectQueue();
  const ch = channel;
  if (!ch) throw new Error("RabbitMQ: нет канала");
  const message: JobMessage = {
    process_id: processId,
    step,
    attempt: 1,
    requested_by: requestedBy,
    requested_at: new Date().toISOString(),
    request_id: requestId,
  };
  ch.sendToQueue(step, Buffer.from(JSON.stringify(message)), {
    persistent: true,
    contentType: "application/json",
  });
  await ch.waitForConfirms();
}

/** Ставит пробный прогон правила в очередь воркера (#222, #223) и ждёт подтверждения брокера. */
export async function publishRuleTest(testId: string, requestedBy: string | null, requestId: string | null = null): Promise<void> {
  await connectQueue();
  const ch = channel;
  if (!ch) throw new Error("RabbitMQ: нет канала");
  const message = { test_id: testId, requested_by: requestedBy, requested_at: new Date().toISOString(), request_id: requestId };
  ch.sendToQueue(RULE_TEST_QUEUE, Buffer.from(JSON.stringify(message)), { persistent: true, contentType: "application/json" });
  await ch.waitForConfirms();
}

export function queueReady(): boolean {
  return channel !== null;
}

/** Сообщения в очередях для метрик. Без соединения с брокером — пусто. */
export async function queueDepths(): Promise<Record<string, number>> {
  const out: Record<string, number> = {};
  const ch = channel;
  if (!ch) return out;
  // только очереди обработки документов: пробные прогоны правил (#223) в метрики и оповещения не входят
  for (const name of QUEUES) {
    try {
      const info = await ch.checkQueue(name);
      out[name] = info.messageCount;
    } catch {
      // очередь недоступна; если брокер закрыл канал, переподключение объявит очереди заново
    }
  }
  return out;
}
