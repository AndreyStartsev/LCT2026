// Журнал обработки объекта (#83): как читали документы, что из этого вышло и что сервис
// об этом сказал. Наблюдения о качестве разбора с рабочего экрана инспектора убраны —
// там они читались как дефект объекта; здесь они собраны вместе с числами прогона.
import { iso } from "./process.js";

type Json = Record<string, any>;

export interface LogRun {
  version: number;
  created_at: string | null;
  status: string;
  reading_mode: string | null;
  model_name: string | null;
  /** версия правил Матрицы (очереди с хешами) и конвейера, по которым собрана версия */
  matrix_version: string | null;
  model_version: string | null;
  ocr: boolean | null;
  model: boolean | null;
  /** сколько страниц в объекте по отчёту готовности этой версии */
  pages: number | null;
  findings: number | null;
  checks: number | null;
  labels: Json | null;
  recompute: Json | null;
  changes: Json | null;
  readiness: Json | null;
}

/** Числа готовности, которые стоит показать словами; остальное живёт в протоколе. */
function readinessView(readiness: Json | null | undefined): Json | null {
  if (!readiness) return null;
  const pick = [
    "files", "pages", "pages_without_text", "pages_low_quality", "share_without_text",
    "stage_unknown", "section_other", "unsupported", "reading_mode", "model_name",
    "ocr_enabled", "model_enabled", "read_seconds", "model_calls", "model_answered",
    "model_looped", "model_seconds", "by_text_source",
  ];
  const out: Json = {};
  for (const key of pick) if (readiness[key] !== undefined) out[key] = readiness[key];
  return Object.keys(out).length ? out : null;
}

export function logView(
  process: Json,
  protocols: Json[],
  notifications: Json[],
  rejected: Json[],
): Json {
  const runs: LogRun[] = protocols.map((p) => {
    const report = p.report ?? {};
    const diff = report.changes ?? null;
    return {
      version: Number(p.version),
      created_at: iso(p.created_at),
      status: p.status,
      reading_mode: report.reading_mode ?? null,
      model_name: report.model_name ?? null,
      matrix_version: p.matrix_version ?? null,
      model_version: p.model_version ?? null,
      ocr: report.ocr ?? null,
      model: report.model ?? null,
      pages: report.readiness?.pages ?? null,
      findings: report.findings ?? null,
      checks: report.checks ?? null,
      labels: report.labels ?? null,
      recompute: report.recompute ?? null,
      // В отчёте изменения лежат списками; журналу нужны числа, а разбор — в протоколе
      changes: diff
        ? Object.fromEntries(Object.entries(diff).map(([k, v]) => [k, Array.isArray(v) ? v.length : v]))
        : null,
      readiness: readinessView(report.readiness),
    };
  });
  return {
    process_id: process.id,
    object_id: process.object_id,
    status: process.status,
    processing: process.processing ?? { state: "IDLE" },
    runs,
    notifications: notifications.map((n) => ({
      id: Number(n.id),
      role: n.role,
      level: n.level,
      category: n.category ?? "INFO",
      message: n.message,
      created_at: iso(n.created_at),
    })),
    rejected_files: rejected.map((r) => ({
      code: r.reject_code ?? "UNKNOWN",
      count: Number(r.count),
      message: r.reject_message ?? null,
    })),
  };
}
