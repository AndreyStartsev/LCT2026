// Раскладка записей по пяти таблицам протокола ТЗ, раздел 9.2, пункт 4:
// (1) комплектность и сопоставимость; (2) предварительные кандидаты;
// (3) подтверждённые инспектором нарушения; (4) проверенные отрицательные результаты;
// (5) гипотезы свободного поиска.
import type { FileItem, Finding, ObjectItem, ProcessStatus } from "./api";

export type TableKey = "completeness" | "candidates" | "confirmed" | "negatives" | "hypotheses";

export const TABLES: { key: TableKey; n: number; title: string; empty: string; hint: string }[] = [
  {
    key: "completeness",
    n: 1,
    title: "Комплектность и сопоставимость",
    empty: "Все параметры удалось сравнить",
    hint: "Статус загрузки томов ПД, РД и ИД и связка актуальных редакций по шифрам",
  },
  {
    key: "candidates",
    n: 2,
    title: "Кандидаты в нарушения",
    empty: "Кандидатов в нарушения нет",
    hint: "Найденные расхождения, по которым решение принимает инспектор",
  },
  {
    key: "confirmed",
    n: 3,
    title: "Подтверждённые нарушения",
    empty: "Подтверждённых нарушений нет",
    hint: "Нарушения, подтверждённые инспектором: они идут в итоговый протокол",
  },
  {
    key: "negatives",
    n: 4,
    title: "Проверенные отрицательные",
    empty: "Отрицательных результатов нет",
    hint: "Параметры, проверенные автоматически: расхождений между ПД, РД и ИД не найдено",
  },
  {
    key: "hypotheses",
    n: 5,
    title: "Гипотезы свободного поиска",
    empty: "Гипотез вне Матрицы нет",
    hint: "Расхождения, найденные вне Матрицы 132 параметров; в итоги нарушений не входят",
  },
];

/**
 * Гипотеза свободного поиска, которую инспектор ещё не взял в кандидаты. ТЗ 9.2: SUSPICION
 * вне итогов нарушений, решение по ней принимается только после перевода в кандидаты.
 */
export function isHypothesis(f: Finding): boolean {
  // гипотеза свободного поиска или черновика правила (#95): в кандидаты её берёт инспектор
  const origin = f.matrix_scope === "FREE_SEARCH" || f.provisional === true;
  return origin && f.verification_status === "PENDING" && !f.promoted_at;
}

/**
 * Сверка исполнительной схемы с допусками, объявленными на том же листе (FREE-KR-002): допуск
 * и отклонение — с одного листа ИД. Допуск конвейер кладёт в pd_value (в выгрузке это ожидаемое
 * значение), отклонение — в id_value; ПД и РД в проверке не участвуют.
 */
export function isSheetTolerance(f: Pick<Finding, "parameter_code">): boolean {
  return f.parameter_code === "FREE-KR-002";
}

/**
 * Участвует ли стадия в сравнении. У Матрицы и черновиков правил ПД и РД участвуют всегда: пустая
 * сторона там — пропуск, и инспектор должен его видеть. Свободный поиск сравнивает то, что задаёт
 * сама проверка: сторона без значения и без страницы в ней не участвует (акт против листа РД,
 * номер акта в имени файла, редакции одного листа), и рамка «не найдено» только сбивала бы.
 */
export function usesStage(f: Finding, stage: "PD" | "RD"): boolean {
  if (isSheetTolerance(f)) return false;
  if (f.matrix_scope !== "FREE_SEARCH") return true;
  const value = stage === "PD" ? f.pd_value : f.rd_value;
  return value != null || f.evidence.some((e) => e.stage === stage);
}

/** Таблица записи или null, если запись в протоколе не показывается (разделённая целиком). */
export function tableOf(f: Finding): TableKey | null {
  if (f.verification_status === "SPLIT") return null;
  if (isHypothesis(f)) return "hypotheses";
  switch (f.verification_status) {
    case "PENDING":
    case "CLARIFICATION_REQUIRED":
      return "candidates";
    case "CONFIRMED_VIOLATION":
      return "confirmed";
    case "NEGATIVE_VERIFIED":
      return "negatives";
    default:
      return f.violation_label === "NO_VIOLATION" ? "negatives" : "completeness";
  }
}

export function isCandidate(f: Finding): boolean {
  return !["NOT_REQUIRED", "SPLIT"].includes(f.verification_status);
}

export interface StageLoad {
  stage: "PD" | "RD" | "ID";
  state: "UPLOADED" | "PARTIAL" | "MISSING";
  files: number;
}

export function stageLoads(status: ProcessStatus, files: FileItem[]): StageLoad[] {
  const stages: ("PD" | "RD" | "ID")[] = ["PD", "RD", "ID"];
  return stages.map((stage) => {
    const code = status.upload_status.find((u) => u.startsWith(`${stage}_`));
    const state = (code?.slice(3) as StageLoad["state"]) ?? "MISSING";
    const count = files.filter(
      (f) => f.status === "ACCEPTED" && (f.doc_stage === stage || (f.doc_stage === "RD_ID_MIXED" && stage !== "PD")),
    ).length;
    return { stage, state, files: count };
  });
}

export type Light = "violations" | "pending" | "clean" | "incomplete" | "processing" | "failed" | "empty";

/**
 * Светофор объекта. Зелёный только когда сравнение прошло и нарушений нет: если
 * часть параметров сравнить не удалось, объект не «соответствует», а проверен не полностью.
 */
export function lightOf(item: ObjectItem | ProcessStatus): { light: Light; label: string } {
  const p = "last_process" in item ? item.last_process : (item as ProcessStatus);
  if (!p) return { light: "empty", label: "Проверок нет" };
  const state = p.processing?.state;
  if (state === "FAILED") return { light: "failed", label: "Сбой обработки" };
  if (state === "QUEUED" || state === "RUNNING" || !p.protocol_version) return { light: "processing", label: "Обработка" };
  const c = p.findings;
  if (!c) return { light: "processing", label: "Обработка" };
  const also = (parts: (string | false)[]) => parts.filter(Boolean).join(" · ");
  // пока верификация не закончена, итог объекта неизвестен: незавершённая работа важнее уже найденного.
  // Решение, принятое по прежним значениям (после дозагрузки они изменились), — тоже незавершённая работа.
  // у финализированного протокола решения закрыты: пересматривать уже нечем
  const revisit = p.status === "FINALIZED" ? 0 : c.revisit ?? 0;
  if (c.pending + c.clarification + revisit > 0) {
    return {
      light: "pending",
      label: also([
        c.pending > 0 && `Ждут решения: ${c.pending}`,
        revisit > 0 && `пересмотреть: ${revisit}`,
        c.clarification > 0 && `на уточнении: ${c.clarification}`,
        c.confirmed > 0 && `подтверждено: ${c.confirmed}`,
      ]).replace(/^([нп])/, (m) => m.toUpperCase()),
    };
  }
  if (c.confirmed > 0) return { light: "violations", label: `Нарушений подтверждено: ${c.confirmed}` };
  // Есть параметры, у которых правило отработало, а сравнить не удалось, — объект проверен не
  // полностью. Прежде здесь стояло число записей, закрытых автоматикой, под словом «параметров»,
  // и оно не сходилось с охватом рядом; сколько сопоставлено — охват, чего нет — столбец «Без сравнения»
  const without = uncomparedOf(p);
  if (without ? without.total > 0 : c.not_comparable > 0) return { light: "incomplete", label: "Проверен не полностью" };
  return { light: "clean", label: "Нарушений не выявлено" };
}

/**
 * Без сравнения: параметры с правилом, по которым значения не сопоставлены, — как группы «нет
 * доказательств» и «несопоставимо» дашборда. Параметры без правила, черновики, «вне проверки»
 * и неприменимые сюда не входят. У API до этих полей — null.
 */
export function uncomparedOf(
  item: ObjectItem | ProcessStatus | null | undefined,
): { total: number; missing: number; notComparable: number } | null {
  const p = item && "last_process" in item ? item.last_process : (item as ProcessStatus | null | undefined);
  const cov = p?.coverage;
  if (!cov || cov.missing_evidence == null) return null;
  const notComparable = cov.not_comparable ?? 0;
  return { total: cov.missing_evidence + notComparable, missing: cov.missing_evidence, notComparable };
}

/**
 * Ручные правки файлов, которые ещё не вошли в протокол (разбор интерфейса, п. 11): стадия,
 * раздел или актуальная редакция заданы после сборки последней версии. Прежде об этом говорил
 * флажок экрана, и он пропадал, стоило уйти в карточку, — протокол можно было финализировать
 * без своей правки.
 */
export function pendingEdits(files: FileItem[], builtAt: string | null | undefined): FileItem[] {
  if (!builtAt) return [];
  const built = Date.parse(builtAt);
  const after = (t: string | null | undefined) => !!t && Date.parse(t) > built;
  return files.filter((f) => f.status === "ACCEPTED" && (after(f.manual_at) || after(f.revision_manual_at)));
}

/**
 * Охват Матрицы: «сопоставлено 20 из 132» рядом с выводом, подробнее — в подсказке. Без него зелёный
 * вывод «нарушений не выявлено» читался как «объект проверен целиком», хотя правила есть не для всех
 * параметров. Словами, а не дробью: «6/132» рядом с числом записей читалось как его часть.
 */
export function coverageText(item: ObjectItem | ProcessStatus): { short: string; full: string } | null {
  const p = "last_process" in item ? item.last_process : (item as ProcessStatus);
  const cov = p?.coverage;
  return cov
    ? { short: `сопоставлено ${cov.compared} из ${cov.total}`, full: `сопоставлено параметров Матрицы: ${cov.compared} из ${cov.total}` }
    : null;
}

/** Передача финализированного протокола во внешнюю систему, ТЗ 9.6. */
export function syncText(status: ProcessStatus): string {
  const sync = status.sync;
  if (!sync) return status.status === "FINALIZED" ? "передача не настроена" : "после финализации";
  switch (sync.status) {
    case "SYNCED":
      return `передан${sync.external_id ? ` · ${sync.external_id}` : ""}`;
    case "PENDING_SYNC":
      return sync.next_attempt_at
        ? `ожидает передачи · попытка ${sync.attempts + 1} из ${sync.max_retries + 1}`
        : `не передан после ${sync.attempts} попыток`;
    case "REJECTED":
      return `отклонён${sync.last_status_code ? ` · ${sync.last_status_code}` : ""}`;
    case "CANCELLED":
      return "передача отменена";
    default:
      return sync.status;
  }
}

/**
 * Передача в ИАИС «РиН» для шапки экрана проверки: коротко, чтобы данные объекта уместились
 * в одну строку; номер во внешней системе, попытки и ошибка — в подсказке.
 */
export function syncShort(status: ProcessStatus): { text: string; title: string } {
  const sync = status.sync;
  const full = syncText(status);
  if (!sync) {
    return status.status === "FINALIZED"
      ? { text: "не настроена", title: "Передача в ИАИС «РиН» не настроена" }
      : { text: "не передан", title: "Протокол передаётся в ИАИС «РиН» после финализации" };
  }
  const title = `ИАИС «РиН»: ${full}${sync.last_error ? `\n${sync.last_error}` : ""}`;
  switch (sync.status) {
    case "SYNCED":
      return { text: "передан", title };
    case "PENDING_SYNC":
      return {
        text: sync.next_attempt_at ? `ожидает · ${sync.attempts + 1} из ${sync.max_retries + 1}` : "не передан",
        title,
      };
    case "REJECTED":
      return { text: "отклонён", title };
    case "CANCELLED":
      return { text: "отменена", title };
    default:
      return { text: sync.status, title };
  }
}

/**
 * Версия правил складывается из очередей Матрицы с хешем каждой: «q1-3456f99a7d13+q2-…».
 * Коротко — очереди, целиком — в подсказке и в выгрузке протокола.
 */
export function matrixShort(version: string | null | undefined): string {
  if (!version) return "не записана";
  const queues = version.split("+").map((part) => part.split("-")[0]);
  if (queues.length < 2) return version;
  const n = queues.map((q) => Number(q.replace(/^q/, "")));
  // подряд идущие очереди — диапазоном: «очереди 1–5», а не «1, 2, 3, 4, 5»
  const consecutive = n.every((x, i) => Number.isInteger(x) && (i === 0 || x === n[i - 1] + 1));
  return `очереди ${consecutive ? `${n[0]}–${n[n.length - 1]}` : queues.map((q) => q.replace(/^q/, "")).join(", ")}`;
}
