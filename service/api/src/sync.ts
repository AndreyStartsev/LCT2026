// Передача финализированного протокола в ИАИС «РиН». Задача #34, ТЗ 9.6.
//
// Передаются только подтверждённые инспектором нарушения вместе с версиями протокола,
// Матрицы, модели и реестром входных файлов. При ошибке 5xx, таймауте или обрыве связи —
// до трёх повторов с задержкой 1, 5 и 15 минут. Пока передача не удалась, протокол
// остаётся финализированным, а передача — PENDING_SYNC: сбой внешней системы решение
// инспектора не меняет. Ответ 4xx повтором не лечится: передача отклонена, администратор
// получает уведомление. Подписание запроса УКЭП на стенде не выполняется.

import { createHash } from "node:crypto";
import type { FastifyBaseLogger } from "fastify";
import { config } from "./config.js";
import { audit, notify, pool, withTransaction, type Queryable } from "./db.js";
import { iso } from "./process.js";
import { metrics } from "./metrics.js";
import { sidesOf } from "./sides.js";

export interface SyncRow {
  id: number;
  process_id: string;
  protocol_version: number;
  status: string;
  attempts: number;
  next_attempt_at: Date | null;
  last_error: string | null;
  last_status_code: number | null;
  external_id: string | null;
  created_at: Date;
  updated_at: Date;
  synced_at: Date | null;
}

export function syncConfigured(): boolean {
  return Boolean(config.iais.url);
}

export async function syncView(db: Queryable, processId: string) {
  const { rows } = await db.query<SyncRow>(
    "select * from inspection_sync where process_id = $1 order by id desc limit 1",
    [processId],
  );
  const row = rows[0];
  if (!row) return null;
  return {
    status: row.status,
    protocol_version: row.protocol_version,
    attempts: row.attempts,
    max_retries: config.iais.retryDelaysS.length,
    next_attempt_at: iso(row.next_attempt_at),
    last_error: row.last_error,
    last_status_code: row.last_status_code,
    external_id: row.external_id,
    created_at: iso(row.created_at),
    updated_at: iso(row.updated_at),
    synced_at: iso(row.synced_at),
  };
}

/** При финализации: новая передача протокола этой версии. */
export async function enqueueSync(db: Queryable, processId: string, protocolVersion: number, userId: string): Promise<void> {
  if (!syncConfigured()) return;
  await db.query(
    "update inspection_sync set status = 'CANCELLED', next_attempt_at = null, updated_at = now() where process_id = $1 and status = 'PENDING_SYNC'",
    [processId],
  );
  await db.query(
    `insert into inspection_sync (process_id, protocol_version, status, attempts, next_attempt_at, requested_by)
     values ($1, $2, 'PENDING_SYNC', 0, now(), $3)`,
    [processId, protocolVersion, userId],
  );
}

/** При отмене финализации: неотправленная передача снимается, отправленная остаётся в истории. */
export async function cancelSync(db: Queryable, processId: string): Promise<void> {
  await db.query(
    "update inspection_sync set status = 'CANCELLED', next_attempt_at = null, updated_at = now() where process_id = $1 and status = 'PENDING_SYNC'",
    [processId],
  );
}

/** Повторить передачу вручную: счётчик попыток начинается заново. */
export async function retrySync(db: Queryable, processId: string): Promise<boolean> {
  const { rowCount } = await db.query(
    `update inspection_sync set attempts = 0, next_attempt_at = now(), last_error = null, updated_at = now()
     where id = (select id from inspection_sync where process_id = $1 order by id desc limit 1)
       and status in ('PENDING_SYNC', 'REJECTED')`,
    [processId],
  );
  if (rowCount) {
    await db.query(
      `update inspection_sync set status = 'PENDING_SYNC'
       where id = (select id from inspection_sync where process_id = $1 order by id desc limit 1)`,
      [processId],
    );
  }
  return Boolean(rowCount);
}

/** Что уходит во внешнюю систему: подтверждённые нарушения, версии и реестр входных файлов. */
export async function syncPayload(db: Queryable, processId: string, protocolVersion: number) {
  const [process, protocol, files, confirmed] = await Promise.all([
    db.query("select p.*, o.name as object_name, o.permit_number from processes p join objects o on o.id = p.object_id where p.id = $1", [processId]),
    db.query(
      `select version, status, matrix_version, dataset_version, model_version, input_manifest_hash, finalized_at
       from protocols where process_id = $1 and version = $2`,
      [processId, protocolVersion],
    ),
    db.query(
      "select file_id, relative_path, file_hash, doc_stage from files where process_id = $1 and status = 'ACCEPTED' order by relative_path",
      [processId],
    ),
    db.query(
      `select finding_id, parameter_code, location, criticality, pd_value, rd_value, reason_code, comment, decided_by, decided_at, body
       from findings where process_id = $1 and verification_status = 'CONFIRMED_VIOLATION' order by finding_id`,
      [processId],
    ),
  ]);
  const p = process.rows[0];
  const v = protocol.rows[0];
  return {
    process_id: processId,
    object: { object_id: p?.object_id, name: p?.object_name, permit_number: p?.permit_number ?? null },
    protocol: {
      version: protocolVersion,
      status: v?.status,
      finalized_at: iso(v?.finalized_at),
      matrix_version: v?.matrix_version,
      dataset_version: v?.dataset_version,
      model_version: v?.model_version,
      input_manifest_sha256: v?.input_manifest_hash,
    },
    violations: confirmed.rows.map((r) => {
      // у проверки внутри листа ИД фактическое — отклонение со схемы, а не значение РД
      const sides = sidesOf(r);
      return {
        finding_id: r.finding_id,
        parameter_code: r.parameter_code,
        location: r.location,
        criticality: r.criticality,
        expected_value: sides.expected,
        actual_value: sides.actual,
        decided_by: r.decided_by,
        decided_at: iso(r.decided_at),
        comment: r.comment,
        evidence: (r.body?.evidence ?? []).map((e: Record<string, unknown>) => ({
          stage: e.stage, file_id: e.file_id, sha256: e.sha256, page: e.pdf_page_number, sheet: e.document_sheet_number,
          bbox: e.bbox_tz ?? null,
        })),
      };
    }),
    input_files: files.rows.map((f) => ({ file_id: f.file_id, relative_path: f.relative_path, sha256: f.file_hash, stage: f.doc_stage })),
  };
}

async function sendOne(row: SyncRow, log: FastifyBaseLogger): Promise<void> {
  const payload = await syncPayload(pool, row.process_id, row.protocol_version);
  const body = JSON.stringify(payload);
  const digest = createHash("sha256").update(body).digest("hex");
  const url = `${config.iais.url.replace(/\/$/, "")}/api/v1/inspection/${row.process_id}`;
  let status: number | null = null;
  let error: string | null = null;
  let externalId: string | null = null;
  const started = Date.now();
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json", "x-payload-sha256": digest },
      body,
      signal: AbortSignal.timeout(config.iais.timeoutMs),
    });
    status = response.status;
    const text = await response.text();
    if (response.ok) {
      try {
        externalId = JSON.parse(text).inspection_id ?? null;
      } catch {
        externalId = null;
      }
    } else {
      error = `ИАИС «РиН» ответила ${response.status}: ${text.slice(0, 200)}`;
    }
  } catch (err) {
    error = `ИАИС «РиН» недоступна: ${(err as Error).name === "TimeoutError" ? `таймаут ${config.iais.timeoutMs} мс` : (err as Error).message}`;
  }
  const seconds = (Date.now() - started) / 1000;
  metrics.syncAttempts.inc({ result: error ? (status && status < 500 ? "rejected" : "failed") : "synced" });
  metrics.syncSeconds.observe(seconds);

  await withTransaction(async (db) => {
    const { rows } = await db.query<{ object_id: string }>("select object_id from processes where id = $1", [row.process_id]);
    const objectId = rows[0]?.object_id ?? null;
    if (!error) {
      await db.query(
        `update inspection_sync set status = 'SYNCED', attempts = attempts + 1, last_status_code = $2, external_id = $3,
                last_error = null, next_attempt_at = null, payload_sha256 = $4, synced_at = now(), updated_at = now()
         where id = $1`,
        [row.id, status, externalId, digest],
      );
      await audit(db, {
        userId: "system", action: "IAIS_SYNCED", objectId, processId: row.process_id,
        details: { protocol_version: row.protocol_version, attempt: row.attempts + 1, external_id: externalId, payload_sha256: digest },
      });
      log.info({ process_id: row.process_id, attempt: row.attempts + 1, external_id: externalId }, "протокол передан в ИАИС «РиН»");
      return;
    }
    const attempt = row.attempts + 1;
    const permanent = status !== null && status >= 400 && status < 500;
    // первая отправка и три повтора: задержка перед повтором n — retryDelaysS[n-1]
    const delay = config.iais.retryDelaysS[attempt - 1];
    const exhausted = !permanent && delay === undefined;
    await db.query(
      `update inspection_sync set status = $2, attempts = $3, last_status_code = $4, last_error = $5, payload_sha256 = $6,
              next_attempt_at = case when $7::int is null then null else now() + make_interval(secs => $7::int) end,
              updated_at = now()
       where id = $1`,
      [row.id, permanent ? "REJECTED" : "PENDING_SYNC", attempt, status, error, digest, permanent || exhausted ? null : delay],
    );
    await audit(db, {
      userId: "system", action: permanent ? "IAIS_REJECTED" : exhausted ? "IAIS_SYNC_FAILED" : "IAIS_RETRY_SCHEDULED",
      objectId, processId: row.process_id,
      details: { protocol_version: row.protocol_version, attempt, status_code: status, error, next_retry_in_s: permanent || exhausted ? null : delay },
    });
    if (permanent || exhausted) {
      await notify(db, "admin", "ERROR",
        permanent
          ? `ИАИС «РиН» отклонила протокол процесса ${row.process_id}: ${error}`
          : `Протокол процесса ${row.process_id} не передан в ИАИС «РиН» после ${attempt} попыток: ${error}. Протокол остаётся финализированным, передача — PENDING_SYNC`,
        row.process_id);
    }
    log.warn({ process_id: row.process_id, attempt, status_code: status, error }, "передача в ИАИС «РиН» не удалась");
  });
}

let timer: NodeJS.Timeout | null = null;
let running = false;

/** Периодическая отправка передач, срок которых наступил. Одна отправка за раз. */
export function startSyncLoop(log: FastifyBaseLogger): void {
  if (!syncConfigured() || timer) return;
  timer = setInterval(async () => {
    if (running) return;
    running = true;
    try {
      const { rows } = await pool.query<SyncRow>(
        `select * from inspection_sync where status = 'PENDING_SYNC' and next_attempt_at is not null and next_attempt_at <= now()
         order by next_attempt_at limit 5`,
      );
      for (const row of rows) {
        await sendOne(row, log);
      }
    } catch (error) {
      log.error({ err: error }, "цикл передачи в ИАИС «РиН» прерван");
    } finally {
      running = false;
    }
  }, config.iais.pollMs);
}
