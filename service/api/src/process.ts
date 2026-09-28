// Жизненный цикл процесса проверки и общие выборки.
import { randomUUID } from "node:crypto";
import { readProgress } from "./cache.js";
import type { Queryable } from "./db.js";
import { ApiError } from "./errors.js";
import { syncView } from "./sync.js";

// Таблица статусов процесса из ТЗ, раздел 9.1: где разрешена дозагрузка и верификация.
// COMPLETED в верификации оставлен ради одного действия — «вернуть в кандидаты»: ТЗ 9.3
// требует, чтобы ошибочное решение снималось до финализации. Проверка действия —
// в `verification.ts`, там же отказ на все остальные решения в COMPLETED.
export const UPLOAD_ALLOWED = new Set(["PENDING", "READY", "VERIFYING", "COMPLETED"]);
export const VERIFICATION_ALLOWED = new Set(["READY", "VERIFYING", "COMPLETED"]);

export interface ProcessRow {
  id: string;
  object_id: string;
  status: string;
  scenario: string | null;
  upload_status: string[];
  processing: Record<string, unknown>;
  /** Способ чтения объекта, выбранный при загрузке (#54): layer, tesseract, model. */
  reading_mode: string | null;
  /** Модель, выбранная при загрузке для режима «модель» (#54). */
  model_name: string | null;
  created_at: Date;
  updated_at: Date;
  finalized_at: Date | null;
}

export function iso(value: Date | string | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  return value instanceof Date ? value.toISOString() : new Date(value).toISOString();
}

export function newProcessId(): string {
  return randomUUID();
}

export async function loadProcess(db: Queryable, id: string, lock = false): Promise<ProcessRow> {
  if (!/^[0-9a-f-]{36}$/i.test(id)) {
    throw new ApiError(404, "PROCESS_NOT_FOUND", `Процесс ${id} не найден`);
  }
  const { rows } = await db.query<ProcessRow>(
    `select * from processes where id = $1${lock ? " for update" : ""}`,
    [id],
  );
  if (rows.length === 0) {
    throw new ApiError(404, "PROCESS_NOT_FOUND", `Процесс ${id} не найден`);
  }
  return rows[0];
}

export function isBusy(process: ProcessRow): boolean {
  const state = process.processing?.state;
  return state === "QUEUED" || state === "RUNNING";
}

/** Дозагрузка разрешена в статусах из ТЗ и не во время разбора. */
export function assertUploadAllowed(process: ProcessRow): void {
  if (process.status === "FINALIZED") {
    throw new ApiError(409, "PROCESS_FINALIZED",
      "Протокол финализирован: дозагрузка невозможна. Отменить финализацию может администратор");
  }
  if (!UPLOAD_ALLOWED.has(process.status) || isBusy(process)) {
    throw new ApiError(409, "PROCESS_BUSY",
      "Идёт обработка документов. Дозагрузка станет доступна, когда она закончится");
  }
}

/** Разделы Матрицы по началу кода параметра: PZ-001 — ПЗ, IOS4-078 — ИОС4 и т. д. */
export const MATRIX_PREFIXES = ["PZ", "SPZU", "AR", "KR", "IOS1", "IOS2", "IOS3", "IOS4", "IOS5", "POS", "POD", "OOS", "PPM", "ODI", "ZU", "SM"];
// правила свободного поиска называются по разделу вторым словом: FREE-AR-ROOM-AREA — АР,
// FREE-OV-… — отопление и вентиляция, то есть ИОС4
const FREE_SECTION: Record<string, string> = { AR: "AR", KR: "KR", OV: "IOS4", VK: "IOS2", EOM: "IOS1" };

/** Раздел записи по коду параметра; null — раздел не определить (служебные правила ИД и т. п.). */
export function sectionOfCode(code: string | null | undefined): string | null {
  const [first, second] = String(code ?? "").split("-");
  if (first === "FREE") return FREE_SECTION[second] ?? null;
  return MATRIX_PREFIXES.includes(first) ? first : null;
}

export type CountRow = {
  verification_status: string;
  violation_label: string | null;
  matrix_scope: string | null;
  provisional?: boolean;
  promoted: boolean;
  parameter_code?: string | null;
  /** после решения инспектора значения записи изменились (дозагрузка, пересборка) */
  changed?: boolean;
  n: string | number;
};

/** Решение инспектора принято: подтверждено, отклонено или отправлено на уточнение. */
const DECIDED = ["CONFIRMED_VIOLATION", "NEGATIVE_VERIFIED", "CLARIFICATION_REQUIRED"];

/**
 * Счётчики записей процесса для реестра и пяти таблиц протокола. by_section — по разделам
 * Матрицы, сколько записей ждут решения и сколько подтверждено: по ним реестр объектов
 * отбирает объекты с замечаниями в нужном разделе (ТЗ, модуль 7: фильтры по разделам).
 */
export function countFindings(rows: CountRow[]) {
  const sum = (pred: (r: CountRow) => boolean) => rows.filter(pred).reduce((acc, r) => acc + Number(r.n), 0);
  // гипотеза свободного поиска ожидает не решения, а перевода в кандидаты (ТЗ 9.2),
  // поэтому в кандидатах не считается и финализацию не блокирует
  // гипотеза черновика правила (#95) — так же
  const hypothesis = (r: CountRow) =>
    (r.matrix_scope === "FREE_SEARCH" || r.provisional === true) && r.verification_status === "PENDING" && !r.promoted;
  const bySection: Record<string, { candidates: number; confirmed: number }> = {};
  for (const r of rows) {
    const open = (r.verification_status === "PENDING" || r.verification_status === "CLARIFICATION_REQUIRED") && !hypothesis(r);
    const confirmed = r.verification_status === "CONFIRMED_VIOLATION";
    const section = sectionOfCode(r.parameter_code);
    if (!section || (!open && !confirmed)) continue;
    const slot = (bySection[section] ??= { candidates: 0, confirmed: 0 });
    if (open) slot.candidates += Number(r.n);
    else slot.confirmed += Number(r.n);
  }
  return {
    total: sum(() => true),
    // кандидат — запись, по которой инспектор принимает решение; разделённая запись им быть перестала
    candidates: sum((r) => !["NOT_REQUIRED", "SPLIT"].includes(r.verification_status) && !hypothesis(r)),
    pending: sum((r) => r.verification_status === "PENDING" && !hypothesis(r)),
    hypotheses: sum(hypothesis),
    confirmed: sum((r) => r.verification_status === "CONFIRMED_VIOLATION"),
    rejected: sum((r) => r.verification_status === "NEGATIVE_VERIFIED"),
    clarification: sum((r) => r.verification_status === "CLARIFICATION_REQUIRED"),
    split: sum((r) => r.verification_status === "SPLIT"),
    no_violation: sum((r) => r.verification_status === "NOT_REQUIRED" && r.violation_label === "NO_VIOLATION"),
    not_comparable: sum((r) => r.verification_status === "NOT_REQUIRED" &&
      ["COMPARISON_IMPOSSIBLE", "MISSING_DOCUMENT"].includes(r.violation_label ?? "")),
    // решения, принятые по прежним значениям: после дозагрузки значения записи изменились,
    // и решение надо пересмотреть. Пока его не пересмотрели, запись видна в реестре и списке
    revisit: sum((r) => !!r.changed && DECIDED.includes(r.verification_status)),
    by_section: bySection,
  };
}

export async function findingCounts(db: Queryable, processId: string) {
  const { rows } = await db.query<CountRow>(
    `select verification_status, violation_label, body->>'matrix_scope' as matrix_scope,
            (body->>'promoted_at') is not null as promoted, parameter_code,
            coalesce((body->>'provisional')::boolean, false) as provisional,
            body ? 'changed_after_decision' as changed, count(*) as n
     from findings where process_id = $1 group by 1, 2, 3, 4, 5, 6, 7`,
    [processId],
  );
  return countFindings(rows);
}

/**
 * Что мешает удалить объект (#74). Удаляются только черновые объекты: загрузили не то,
 * перепутали идентификатор, пробный прогон. Финализированный протокол — документ:
 * у него есть версия, решения инспектора и запись в ИАИС «РиН», и уносить его вместе
 * с объектом нельзя. Идущая обработка тоже мешает: воркер пишет в те же таблицы.
 */
export function deletionBlockers(processes: Pick<ProcessRow, "status" | "processing" | "finalized_at">[]): string[] {
  const blockers: string[] = [];
  const finalized = processes.filter((p) => p.status === "FINALIZED" || p.finalized_at).length;
  if (finalized > 0) {
    blockers.push(`финализированных протоколов: ${finalized}`);
  }
  const busy = processes.filter((p) => isBusy(p as ProcessRow)).length;
  if (busy > 0) {
    blockers.push(`идёт обработка документов: процессов ${busy}`);
  }
  return blockers;
}

/**
 * Статус процесса по решениям инспектора, раздел 9.1 ТЗ: ни одного решения —
 * READY, решены все кандидаты — COMPLETED, иначе VERIFYING.
 */
export async function settleStatus(db: Queryable, processId: string): Promise<string> {
  const counts = await findingCounts(db, processId);
  const decided = counts.confirmed + counts.rejected + counts.clarification;
  const next = decided === 0 && counts.split === 0 ? "READY" : counts.pending === 0 ? "COMPLETED" : "VERIFYING";
  await db.query(
    "update processes set status = $2, updated_at = now() where id = $1 and status <> 'FINALIZED'",
    [processId, next],
  );
  return next;
}

/**
 * Охват Матрицы: сколько параметров сопоставлено из всех. Зелёный вывод «нарушений не
 * выявлено» без этого числа читался как «объект проверен и чист», даже когда сопоставлено
 * 7 параметров из 132. Правило то же, что у группы COMPARED (report.ts, parameterGroups):
 * параметр по документам проверяется (не OUT_OF_SCOPE), у него есть правило — прода
 * (implemented) или черновик (HYPOTHESIS, #95), — и хотя бы одна запись Матрицы с исходом
 * сравнения (findingStatus): расхождение или его отсутствие. Запись черновика и свободного
 * поиска, не взятая в кандидаты, — гипотеза (SUSPICION) и сопоставлением не считается.
 *
 * Без сравнения — параметры, у которых правило прода есть и отработало, а значения не
 * сопоставлены: группы «нет доказательств» и «несопоставимо» дашборда. Неприменимые,
 * черновики, «вне проверки» и параметры без правила сюда не входят. Реестр объектов раньше
 * показывал здесь число записей, закрытых автоматикой, под словом «параметров» (44 записи
 * по 33 параметрам), и оно не сходилось ни с охватом, ни с дашбордом.
 */
export async function coverageOf(db: Queryable, processId: string, version: number) {
  const { rows } = await db.query<{ compared: string; total: string; uncompared: string; not_comparable: string }>(
    `with cov as (
       select c->>'parameter_code' as code,
              coalesce((c->>'implemented')::boolean, false) as implemented,
              coalesce(c->>'status', '') as status
         from protocols p, jsonb_array_elements(coalesce(p.report->'coverage', '[]'::jsonb)) c
        where p.process_id = $1 and p.version = $2
     ),
     rec as (
       select f.parameter_code as code, f.violation_label as label,
              coalesce(f.body->'protocol'->>'completeness_status', '') as completeness
         from findings f
        where f.process_id = $1
          and f.verification_status <> 'SPLIT'
          and coalesce(f.body->>'matrix_scope', '') <> 'FREE_SEARCH'
          and not (coalesce((f.body->>'provisional')::boolean, false) and f.body->>'promoted_at' is null)
     ),
     compared as (
       select distinct rec.code
         from rec
         join cov on cov.code = rec.code
                 and cov.status <> 'OUT_OF_SCOPE'
                 and (cov.implemented or cov.status = 'HYPOTHESIS')
        where rec.label in ('VIOLATION_PRESENT', 'NO_VIOLATION')
     ),
     uncompared as (
       select cov.code
         from cov
        where cov.implemented
          and cov.status not in ('OUT_OF_SCOPE', 'NOT_APPLICABLE', 'HYPOTHESIS')
          and cov.code not in (select code from compared)
     )
     select (select count(*) from cov) as total,
            (select count(*) from compared) as compared,
            (select count(*) from uncompared) as uncompared,
            (select count(*) from uncompared u
              where exists (select 1 from rec
                             where rec.code = u.code
                               and rec.label is distinct from 'VIOLATION_PRESENT'
                               and rec.label is distinct from 'NO_VIOLATION'
                               and rec.completeness = 'NOT_COMPARABLE')) as not_comparable`,
    [processId, version],
  );
  const total = Number(rows[0]?.total ?? 0);
  if (!total) return null;
  const notComparable = Number(rows[0].not_comparable);
  return {
    compared: Number(rows[0].compared),
    total,
    missing_evidence: Number(rows[0].uncompared) - notComparable,
    not_comparable: notComparable,
  };
}

export async function statusView(db: Queryable, processId: string) {
  const process = await loadProcess(db, processId);
  const [{ rows: objectRows }, { rows: fileRows }, { rows: protocolRows }, counts, progress, sync] = await Promise.all([
    db.query<{ name: string }>("select name from objects where id = $1", [process.object_id]),
    db.query<{ status: string; n: string; bytes: string | null }>(
      "select status, count(*) as n, sum(size_bytes) as bytes from files where process_id = $1 group by 1",
      [processId],
    ),
    db.query<{
      version: number;
      status: string;
      matrix_version: string | null;
      dataset_version: string | null;
      model_version: string | null;
      created_at: Date;
      readiness: Record<string, unknown> | null;
      recompute: Record<string, unknown> | null;
    }>(
      `select version, status, matrix_version, dataset_version, model_version, created_at,
              report->'readiness' as readiness, report->'recompute' as recompute
       from protocols where process_id = $1 order by version desc limit 1`,
      [processId],
    ),
    findingCounts(db, processId),
    readProgress(processId),
    syncView(db, processId),
  ]);
  const coverage = protocolRows[0] ? await coverageOf(db, processId, protocolRows[0].version) : null;
  const accepted = fileRows.find((r) => r.status === "ACCEPTED");
  const rejected = fileRows.find((r) => r.status === "REJECTED");
  const processing = process.processing ?? {};
  return {
    process_id: process.id,
    object_id: process.object_id,
    object_name: objectRows[0]?.name ?? process.object_id,
    status: process.status,
    scenario: process.scenario,
    upload_status: process.upload_status ?? [],
    // способ чтения объекта (#54): пусто — читали способом сервиса; чем читали на самом
    // деле, видно в readiness.reading_mode после разбора
    reading_mode: process.reading_mode ?? null,
    model_name: process.model_name ?? null,
    processing: { state: "IDLE", ...processing },
    progress: isBusy(process) ? progress : null,
    files: {
      accepted: Number(accepted?.n ?? 0),
      rejected: Number(rejected?.n ?? 0),
      bytes: Number(accepted?.bytes ?? 0),
    },
    protocol_version: protocolRows[0]?.version ?? null,
    // готовность объекта (#39): на что опирается вывод по объекту — доля страниц без
    // прочитанного текста, файлы без стадии и раздела, включались ли распознавание и модель
    readiness: protocolRows[0]?.readiness ?? null,
    // что пересчитано при последней обработке, а что перенесено из прошлой версии (#60)
    recompute: protocolRows[0]?.recompute ?? null,
    ...(protocolRows[0]
      ? {
          protocol: {
            version: protocolRows[0].version,
            status: protocolRows[0].status,
            matrix_version: protocolRows[0].matrix_version,
            dataset_version: protocolRows[0].dataset_version,
            model_version: protocolRows[0].model_version,
            created_at: iso(protocolRows[0].created_at)!,
          },
        }
      : {}),
    findings: counts,
    coverage,
    sync,
    created_at: iso(process.created_at)!,
    updated_at: iso(process.updated_at)!,
    finalized_at: iso(process.finalized_at),
  };
}
