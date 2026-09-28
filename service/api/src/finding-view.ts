// Запись протокола так, как её видит экран проверки: поля строки базы и то, что взято из тела
// находки. Вынесено из маршрутов, чтобы проверять без базы: схема ответа `Finding` в
// `schemas.ts` должна называть каждое поле отсюда, иначе сериализатор Fastify его молча
// выбрасывает — так до #80 экран не получал `sources`, `needs_expert` и `id_value`.
import { confidenceOf } from "./confidence.js";
import { iso } from "./process.js";
import { findingStatus } from "./report.js";

// Решения специалиста о виде записей (Р-108): «гипотеза» и «низкий приоритет» (drop) из четвёртого
// круга; записи вида drop по решению пользователя видны — в конце таблицы гипотез
const SPECIALIST_VERDICTS = new Set(["violation", "need_info", "no_violation", "hypothesis", "drop"]);
type SpecialistVerdictName = "violation" | "need_info" | "no_violation" | "hypothesis" | "drop";

function specialistView(value: unknown) {
  if (typeof value !== "object" || value === null) return null;
  const s = value as Record<string, any>;
  if (!SPECIALIST_VERDICTS.has(s.verdict)) return null;
  return {
    verdict: s.verdict as SpecialistVerdictName,
    // решения по отдельной записи убраны (Р-116); «record» остаётся у записей, разобранных до этого
    scope: s.scope === "record" ? ("record" as const) : ("kind" as const),
    reviewed: typeof s.reviewed === "string" ? s.reviewed : null,
    note: typeof s.note === "string" ? s.note : null,
    cases: Array.isArray(s.cases) ? s.cases.map(String) : [],
  };
}

function sideSource(side: Record<string, any> | null | undefined) {
  if (!side) return null;
  return {
    text_source: side.text_source === "RECOGNIZED" ? "RECOGNIZED" : null,
    binding: typeof side.binding === "string" ? side.binding : null,
  };
}

export function findingView(row: Record<string, any>) {
  const body = row.body ?? {};
  const text = (value: unknown) => (value === undefined || value === null ? null : String(value));
  return {
    id: row.id,
    finding_id: row.finding_id,
    protocol_version: row.protocol_version,
    parameter_code: row.parameter_code,
    parameter_id: body.parameter_id ?? null,
    location: row.location,
    violation_label: row.violation_label,
    protocol_status: row.protocol_status,
    criticality: row.criticality,
    pd_value: row.pd_value,
    rd_value: row.rd_value,
    // третий массив (#42): значение исполнительной документации и сверка с ней
    id_value: text(body.id_value),
    id_check: text(body.extraction?.id_check),
    // чем прочитано значение и к чему привязано (#41): распознанное и взятое с листа
    // инспектор должен видеть, а не принимать наравне со значением из текстового слоя
    sources: {
      pd: sideSource(body.extraction?.pd),
      rd: sideSource(body.extraction?.rd),
      id: sideSource(body.extraction?.id),
    },
    needs_expert: body.needs_expert === true,
    verification_status: row.verification_status,
    reason_code: row.reason_code,
    comment: row.comment,
    decided_by: row.decided_by,
    decided_at: iso(row.decided_at),
    title: text(body.title),
    locations: Array.isArray(body.locations) ? body.locations.map(String) : [],
    location_type: text(body.location_type),
    comparison_result: text(body.comparison_result),
    matrix_scope: text(body.matrix_scope),
    // находка черновика правила (#95): гипотеза до решения инспектора
    provisional: body.provisional === true,
    detail: text(body.extraction?.detail),
    rule_basis: text(body.extraction?.rule_basis),
    // Чем прочитано значение стороны: на сканах его даёт распознавание, и оно путает цифры (#52)
    value_read_by: {
      pd: body.extraction?.pd?.text_source === "RECOGNIZED" ? "RECOGNIZED" : null,
      rd: body.extraction?.rd?.text_source === "RECOGNIZED" ? "RECOGNIZED" : null,
      id: body.extraction?.id?.text_source === "RECOGNIZED" ? "RECOGNIZED" : null,
    },
    origin: text(body.origin),
    // Запись перенесена из прошлой версии протокола: дозагруженные документы её не
    // касались, и значения с решением относятся к тому разбору (#60)
    carried_from_version: typeof body.carried_from_version === "number" ? body.carried_from_version : null,
    parent_finding_id: text(body.parent_finding_id),
    completeness_status: text(body.protocol?.completeness_status),
    completeness_reason: text(body.protocol?.completeness_reason),
    revisions: {
      pd: Array.isArray(body.extraction?.pd?.revisions) ? body.extraction.pd.revisions : [],
      rd: Array.isArray(body.extraction?.rd?.revisions) ? body.extraction.rd.revisions : [],
    },
    changed_after_decision: body.changed_after_decision ?? null,
    // решение инспектора, которое пересборка не сняла, а вернула ему: расхождения больше нет
    reopened: body.reopened ?? null,
    // гипотеза свободного поиска, взятая инспектором в кандидаты (ТЗ 9.2)
    promoted_at: iso(body.promoted_at ?? null),
    promoted_by: text(body.promoted_by),
    // инспектор не согласился с автоматической проверкой и вернул запись в кандидаты (#74)
    disputed_at: iso(body.disputed_at ?? null),
    disputed_by: text(body.disputed_by),
    // Статус записи по легенде организатора к Матрице (#80): кандидат, подтверждено, нет доказательства…
    // — с учётом решения инспектора, как в протоколе и в ИАИС «РиН»
    finding_status: findingStatus(row),
    // Решение специалиста по виду гипотезы (#129, Р-86): отдельно от уверенности и от критичности
    specialist: specialistView(body.specialist),
    // Уверенность в выводе (#80): уровень для отбора и признаки, из которых он сложен
    confidence: confidenceOf(body, row.violation_label),
    evidence: Array.isArray(body.evidence) ? body.evidence : [],
  };
}
