// Правила верификации инспектором: что считается кандидатом и где решение разрешено.
// Задача #43, ТЗ 9.1 (таблица статусов процесса) и 9.3 (алгоритм верификации).
//
// Вынесено из маршрута, чтобы правила проверялись тестом без базы: в них легко
// ошибиться, а цена ошибки — подтверждённое нарушение, которого инспектор не видел.

import { ApiError } from "./errors.js";
import { isBusy, VERIFICATION_ALLOWED, type ProcessRow } from "./process.js";

/** Действие инспектора -> статус верификации записи. */
export const ACTIONS: Record<string, string> = {
  CONFIRM: "CONFIRMED_VIOLATION",
  REJECT: "NEGATIVE_VERIFIED",
  CLARIFY: "CLARIFICATION_REQUIRED",
  // «Вернуть в кандидаты» из макета: ошибочное решение снимается до финализации, с записью в аудит
  RESET: "PENDING",
  // «Взять в кандидаты»: гипотеза свободного поиска становится кандидатом (ТЗ 9.2)
  PROMOTE: "PENDING",
  // «Вернуть в кандидаты» для записи, которую автоматика проверила сама (#74): инспектор
  // не согласен с выводом «расхождения нет» — например, значение прочитано неверно
  DISPUTE: "PENDING",
};

export const DECIDED = new Set(["CONFIRMED_VIOLATION", "NEGATIVE_VERIFIED", "CLARIFICATION_REQUIRED"]);

export interface FindingRow {
  verification_status: string;
  violation_label?: string | null;
  body?: { matrix_scope?: string | null; provisional?: boolean | null; promoted_at?: string | null; disputed_at?: string | null } | null;
}

/**
 * Гипотеза свободного поиска, которую инспектор ещё не взял в кандидаты.
 *
 * ТЗ 9.2: SUSPICION вне итогов нарушений, в кандидаты запись переводит инспектор.
 * Поэтому гипотеза не считается ожидающей решения (иначе блокировала бы финализацию)
 * и решение по ней сервер не принимает, пока она не переведена в кандидаты.
 */
export function isDisputed(finding: FindingRow): boolean {
  return !!finding.body?.disputed_at && finding.verification_status === "PENDING";
}

export function isHypothesis(finding: FindingRow): boolean {
  const body = finding.body ?? {};
  // гипотеза свободного поиска или черновика правила (#95): обе инспектор берёт в кандидаты сам
  const origin = body.matrix_scope === "FREE_SEARCH" || body.provisional === true;
  return origin && finding.verification_status === "PENDING" && !body.promoted_at;
}

/** Состояние процесса, в котором инспектор вообще может менять протокол. */
export function assertVerificationAllowed(process: ProcessRow, what = "Верификация"): void {
  if (process.status === "FINALIZED") {
    throw new ApiError(409, "PROCESS_FINALIZED", "Протокол финализирован: решения изменить нельзя");
  }
  if (isBusy(process)) {
    throw new ApiError(409, "PROCESS_BUSY", `${what} станет доступна, когда закончится обработка документов`);
  }
  if (!VERIFICATION_ALLOWED.has(process.status)) {
    throw new ApiError(409, "PROTOCOL_NOT_READY", `${what} доступна, когда протокол сформирован`);
  }
}

/**
 * Можно ли принять это решение по этой записи. Порядок проверок — от процесса к записи,
 * чтобы сообщение называло настоящую причину отказа.
 */
export function assertDecisionAllowed(process: ProcessRow, finding: FindingRow, action: string): void {
  if (!(action in ACTIONS)) {
    throw new ApiError(400, "UNKNOWN_ACTION", `Действие ${action} не поддерживается`);
  }
  assertVerificationAllowed(process, "Решение по записи");
  // ТЗ 9.1: в статусе COMPLETED верификация не ведётся. Ошибочное решение всё равно
  // должно сниматься до финализации (ТЗ 9.3), поэтому «вернуть в кандидаты» разрешено:
  // процесс возвращается в VERIFYING, и дальше решения принимаются в нём.
  if (process.status === "COMPLETED" && action !== "RESET" && action !== "DISPUTE") {
    throw new ApiError(409, "VERIFICATION_COMPLETED",
      "Верификация по протоколу завершена. Чтобы изменить решение, верните запись в кандидаты");
  }
  // Оспаривание касается только записей, которые автоматика закрыла сама без нарушения:
  // инспектор возвращает их в кандидаты, когда не согласен — ошиблось распознавание,
  // не та редакция. Остальные проверки к ней не относятся: решения по ней ещё нет.
  if (action === "DISPUTE") {
    if (finding.verification_status !== "NOT_REQUIRED" || finding.violation_label !== "NO_VIOLATION") {
      throw new ApiError(409, "NOT_AUTO_NEGATIVE",
        "В кандидаты возвращается запись, проверенная автоматически без нарушения; " +
        "решённую инспектором верните действием «вернуть в кандидаты»");
    }
    return;
  }
  if (finding.verification_status === "NOT_REQUIRED") {
    throw new ApiError(409, "NOT_A_CANDIDATE",
      "Решение принимается по кандидатам в нарушения; эта запись — результат проверки без нарушения");
  }
  if (finding.verification_status === "SPLIT") {
    throw new ApiError(409, "FINDING_SPLIT",
      "Запись разделена на атомарные: решение принимается по каждой части отдельно");
  }
  const hypothesis = isHypothesis(finding);
  if (hypothesis && action !== "PROMOTE") {
    throw new ApiError(409, "HYPOTHESIS_NOT_CANDIDATE",
      "Запись свободного поиска вне Матрицы: сначала переведите её в кандидаты, затем принимайте решение");
  }
  if (!hypothesis && action === "PROMOTE") {
    throw new ApiError(409, "NOT_A_HYPOTHESIS",
      "В кандидаты переводится только гипотеза свободного поиска или черновика правила, ожидающая решения");
  }
  // RESET снимает решение, а у записи, возвращённой в кандидаты из автопроверки, решения
  // ещё нет: для неё это отмена самого возврата, иначе случайное нажатие не исправить (#74)
  if (action === "RESET" && !DECIDED.has(finding.verification_status) && !isDisputed(finding)) {
    throw new ApiError(409, "NOT_DECIDED", "По записи ещё нет решения");
  }
}
