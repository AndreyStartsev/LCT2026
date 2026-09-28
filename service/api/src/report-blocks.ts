// Содержание протокола проверки как последовательность блоков: заголовки, пояснения,
// таблицы, пары «поле — значение». Из одних и тех же блоков собираются PDF (report-pdf.ts)
// и DOCX (report-docx.ts): вёрстка у форматов своя, а содержание одно и расходиться
// не может. Разделы повторяют образец из Приложения 2 к ТЗ (задача #30).
import type { ProtocolReport } from "./report.js";

export type Column = { title: string; width: number; align?: "left" | "right" | "center" };

export type Block =
  | { kind: "heading"; text: string }
  | { kind: "note"; text: string }
  | { kind: "table"; columns: Column[]; rows: string[][]; size?: number }
  | { kind: "kv"; pairs: [string, string][]; size?: number }
  /** заголовок карточки доказательства: жирной строкой, не отрывается от своей таблицы */
  | { kind: "card"; text: string };

export const dash = (value: unknown): string =>
  value === null || value === undefined || value === "" ? "—" : String(value);

/** Способ чтения объекта (#54) словами: в протоколе он стоит рядом с долей прочитанных страниц. */
const READING_MODE_TEXT: Record<string, string> = {
  layer: "только текстовый слой",
  tesseract: "слой и распознавание сканов",
  model: "слой, распознавание и модель на сканах без текста и чертежах без слоя",
};

function decisionText(decision: ProtocolReport["evidence_cards"][number]["expert_decision"]): string {
  if (!decision) return "решения нет";
  return [decision.decision, decision.user_id, decision.timestamp, decision.reason_code && `${decision.reason_code} — ${decision.reason}`, decision.comment]
    .filter(Boolean)
    .join("; ");
}

/** Источники по файлам: имя, редакция и хеш файла один раз, под ними страницы с листом, шифром и рамками. */
function sourceText(sources: ProtocolReport["evidence_cards"][number]["source_expected"]): string {
  if (sources.length === 0) return "—";
  const byFile = new Map<string, typeof sources>();
  for (const s of sources) {
    const key = s.file_id ?? s.document ?? "—";
    byFile.set(key, [...(byFile.get(key) ?? []), s]);
  }
  return [...byFile.values()]
    .map((pages) => {
      const f = pages[0];
      return [
        [f.file_id, f.document].filter(Boolean).join(" · "),
        [f.revision && `редакция: ${f.revision}`, `утверждение: ${f.approval_status}`].filter(Boolean).join(" · "),
        f.sha256 && `SHA-256 ${f.sha256}`,
        ...pages.map((s) =>
          [
            `стр. ${dash(s.page)}`,
            s.sheet !== null && `лист ${s.sheet}`,
            s.document_code && `шифр ${s.document_code}`,
            s.bbox && `bbox ${s.bbox.map((b: number[]) => `[${b.join(", ")}]`).join(" ")}`,
          ]
            .filter(Boolean)
            .join(" · "),
        ),
      ]
        .filter(Boolean)
        .join("\n");
    })
    .join("\n\n");
}

/** Строка колонтитула: одинакова в PDF и DOCX. */
export function footerText(report: ProtocolReport): string {
  return `Инспектор ИИ · ${report.title} № ${dash(report.number)} · ${report.protocol.preliminary ? "предварительная версия" : "финализирован"}`;
}

/** Всё, что идёт после названия и номера протокола, в порядке документа. */
export function protocolBlocks(report: ProtocolReport): Block[] {
  const out: Block[] = [];
  const heading = (text: string) => out.push({ kind: "heading", text });
  const note = (text: string) => out.push({ kind: "note", text });
  const table = (columns: Column[], rows: string[][], size?: number) => out.push({ kind: "table", columns, rows, size });
  const kv = (pairs: [string, string][], size?: number) => out.push({ kind: "kv", pairs, size });

  // ---- шапка ----
  const p = report.protocol;
  kv([
    ["Объект", `${report.object.name} (${report.object.object_id})`],
    ["Адрес", dash(report.object.address)],
    ["Застройщик", dash(report.object.customer)],
    ["Подрядчик", dash(report.object.contractor)],
    ["Номер разрешения / надзорного дела", dash(report.object.permit_number)],
    ["Дата формирования", report.generated_at],
    ["Версия протокола", `${dash(p.version)}${p.preliminary ? " (предварительная)" : " (финализирована)"}`],
    ["Статус", `${p.status} — ${p.status_text}`],
    ...(p.finalized_at ? [["Финализирован", p.finalized_at] as [string, string]] : []),
    ...(p.sync ? [["Передача в ИАИС «РиН»", `${p.sync.status}${p.sync.last_error ? ` — ${p.sync.last_error}` : ""}`] as [string, string]] : []),
  ]);

  heading("Обязательная трассируемость");
  const t = report.traceability;
  kv([
    ["process_id", t.process_id],
    ["matrix_version", dash(t.matrix_version)],
    ["dataset_version", dash(t.dataset_version)],
    ["model_version", dash(t.model_version)],
    ["run_timestamp", dash(t.run_timestamp)],
    ["input_manifest_sha256", dash(t.input_manifest_sha256)],
  ]);

  // ---- раздел 1 ----
  heading("Раздел 1. Статус загрузки документов");
  const u = report.section_1_upload;
  note(`Тип проверки (сценарий загрузки): ${dash(u.scenario)} — ${u.scenario_text}.`);
  table([
    { title: "Тип документа", width: 0.22 },
    { title: "Статус", width: 0.18 },
    { title: "Загружено файлов", width: 0.14, align: "right" },
    { title: "Ожидается", width: 0.12, align: "right" },
    { title: "Комментарий", width: 0.34 },
  ], u.stages.map((s) => [s.name, `${s.status_text}\n${s.status}`, String(s.files_accepted), String(s.files_expected),
    s.comment + (s.signatures_skipped ? `; отдельные подписи не загружаются: ${s.signatures_skipped}` : "")]));
  const ready = u.readiness as Record<string, number | boolean | string | null> | null;
  if (ready) {
    // Полнота обработки: без этих чисел непонятно, на что опирается вывод по объекту (#39)
    const share = Math.round(Number(ready.share_without_text ?? 0) * 1000) / 10;
    const mode = (READING_MODE_TEXT[String(ready.reading_mode ?? "")] ?? dash(ready.reading_mode))
      + (ready.model_name ? `, модель ${ready.model_name}` : "");
    kv([
      ["Страниц прочитано", `${Number(ready.pages ?? 0) - Number(ready.pages_without_text ?? 0)} из ${dash(ready.pages)}` +
        (ready.pages_without_text ? `; без текста ${ready.pages_without_text} (${String(share).replace(".", ",")}%)` : "")],
      ["Файлов без стадии / без раздела", `${dash(ready.stage_unknown)} / ${dash(ready.section_other)}`],
      ["Файлов формата вне разбора", dash(ready.unsupported)],
      ["Распознавание сканов / модель", `${ready.ocr_enabled ? "включено" : "выключено"} / ${ready.model_enabled ? "включена" : "выключена"}`],
      // способ чтения объекта (#54): от него зависит, что вообще увидели правила
      ["Способ чтения", mode],
      // Ответы модели (#71): строка появляется, только если модель вообще звали
      ...(Number(ready.model_calls ?? 0)
        ? [["Модель ответила", `${dash(ready.model_answered)} из ${dash(ready.model_calls)}` +
            (Number(ready.model_looped ?? 0) ? `, зациклилась ${ready.model_looped}` : "")] as [string, string]]
        : []),
    ], 8);
  }
  // Файл сдачи организатору собирается по решениям инспектора (#63)
  const sub = u.submission as Record<string, number> | null;
  if (sub) {
    kv([
      ["Файл сдачи организатору", `записей ${dash(sub.checks)}; убрано отклонённых ${dash(sub.removed)}, ` +
        `добавлено подтверждённых гипотез ${dash(sub.added)}, без решения ${dash(sub.undecided)}`],
    ], 8);
  }
  // Дозагрузка пересчитывает только затронутые параметры (#60)
  const again = u.recompute as Record<string, number | boolean | string | null> | null;
  if (again && again.full === false) {
    kv([
      ["Последняя дозагрузка", `пересчитано записей ${dash(again.recomputed)}, перенесено из прошлой версии ` +
        `${dash(again.carried_over)}; прочитано документов ${dash(again.documents_read)} из ${dash(again.documents_total)}`],
    ], 8);
  }
  note(u.comparison_note);

  // ---- раздел 2 ----
  heading("Раздел 2. Сводная статистика");
  const summary = report.section_2_summary;
  table([
    { title: "Показатель", width: 0.62 },
    { title: "Параметров", width: 0.19, align: "right" },
    { title: `% от ${summary.parameters_total}`, width: 0.19, align: "right" },
  ], summary.parameters.map((r) => [r.label, String(r.count), `${String(r.percent).replace(".", ",")}%`]));
  table([
    { title: "Записей протокола по статусу", width: 0.62 },
    { title: "Количество", width: 0.19, align: "right" },
    { title: "В итоге нарушений", width: 0.19, align: "center" },
  ], summary.records.map((r) => [r.label, String(r.count), r.in_total ? "да" : "нет"]));
  note("По разделам Матрицы: параметры по группам и записи протокола по статусам.");
  const n = (value: number) => (value ? String(value) : "·");
  table([
    { title: "Раздел", width: 0.1 },
    { title: "Пара-метров", width: 0.08, align: "right" },
    { title: "Правил", width: 0.08, align: "right" },
    { title: "Сопо-ставлено", width: 0.1, align: "right" },
    { title: "Нет доказа-тельств", width: 0.1, align: "right" },
    { title: "Несопо-ставимы", width: 0.1, align: "right" },
    { title: "Не прове-рено", width: 0.09, align: "right" },
    { title: "Отрица-тельных", width: 0.1, align: "right" },
    { title: "Канди-датов", width: 0.09, align: "right" },
    { title: "Подтвер-ждено", width: 0.16, align: "right" },
  ], summary.sections.map((s) => [
    s.section, String(s.parameters), n(s.implemented), n(s.compared), n(s.missing_evidence), n(s.not_comparable),
    n(s.not_checked), n(s.negatives), n(s.candidates), n(s.confirmed),
  ]), 7.5);

  // ---- пять таблиц ----
  // колонка ИД появляется, когда хотя бы у одной записи есть значение исполнительной документации (#42)
  const allRecords = Object.values(report.tables).flat() as ProtocolReport["tables"]["confirmed"];
  const withId = allRecords.some((r) => r.id_value);
  const recordColumns: Column[] = withId
    ? [
        { title: "Код", width: 0.09 },
        { title: "Параметр", width: 0.17 },
        { title: "Локация", width: 0.12 },
        { title: "ПД", width: 0.1 },
        { title: "РД", width: 0.1 },
        { title: "ИД", width: 0.1 },
        { title: "Отклонение", width: 0.17 },
        { title: "Решение инспектора", width: 0.15 },
      ]
    : [
        { title: "Код", width: 0.1 },
        { title: "Параметр", width: 0.2 },
        { title: "Локация", width: 0.14 },
        { title: "ПД", width: 0.12 },
        { title: "РД", width: 0.12 },
        { title: "Отклонение", width: 0.17 },
        { title: "Решение инспектора", width: 0.15 },
      ];
  const recordRow = (r: ProtocolReport["tables"]["confirmed"][number]) => [
    dash(r.parameter_code), dash(r.parameter_name), dash(r.location), dash(r.pd_value), dash(r.rd_value),
    ...(withId ? [dash(r.id_value)] : []),
    // запись, которую система не решает сама (#41): причина уже в отклонении, здесь — пометка
    (r.needs_expert ? "требует подтверждения. " : "") + dash(r.deviation),
    r.decision ? `${r.decision.decision}${r.decision.reason ? `: ${r.decision.reason}` : ""}${r.decision.comment ? `. ${r.decision.comment}` : ""}` : r.status_text,
  ];

  heading(`Таблица 1. Комплектность и сопоставимость — ${report.tables.completeness.length}`);
  table([
    { title: "Код", width: 0.11 },
    { title: "Параметр / стадия", width: 0.22 },
    { title: "Локация", width: 0.15 },
    { title: "Статус", width: 0.17 },
    { title: "Причина", width: 0.35 },
  ], report.tables.completeness.map((r) => [dash(r.parameter_code), dash(r.parameter_name), dash(r.location), r.status, dash(r.reason)]));

  const candidates = report.tables.candidates;
  heading(`Таблица 2. Предварительные кандидаты высокого риска — ${candidates.high.length}`);
  table(recordColumns, candidates.high.map(recordRow));
  heading(`Предварительные кандидаты среднего риска — ${candidates.medium.length + candidates.low.length}`);
  table(recordColumns, [...candidates.medium, ...candidates.low].map(recordRow));
  heading(`Таблица 3. Подтверждённые инспектором нарушения — ${report.tables.confirmed.length}`);
  table(recordColumns, report.tables.confirmed.map(recordRow));
  heading(`Таблица 4. Проверенные отрицательные результаты — ${report.tables.negatives.length}`);
  table(recordColumns, report.tables.negatives.map(recordRow));
  heading(`Таблица 5. Гипотезы свободного поиска и черновиков правил — ${report.tables.hypotheses.length}`);
  note("Не входят в число нарушений. Гипотеза, взятая инспектором в кандидаты, показывается в таблицах 2 и 3.");
  table(recordColumns, report.tables.hypotheses.map(recordRow));

  // Причина у всех строк одна, поэтому она не колонкой, а строкой под заголовком
  heading(`Непроверенные параметры — ${report.not_checked.length}`);
  note("Значения этих параметров на объекте не сопоставлялись. В итоги они не входят — ни как нарушение, ни как его отсутствие.");
  table([
    { title: "Код", width: 0.12 },
    { title: "Раздел", width: 0.1 },
    { title: "Параметр", width: 0.78 },
  ], report.not_checked.map((r) => [r.parameter_code, dash(r.section), dash(r.parameter_name)]), 7.5);

  if (report.out_of_scope.length) {
    heading(`Параметры вне проверки документов — ${report.out_of_scope.length}`);
    note("Проверяются не по документам ПД, РД и ИД: во внешних системах стадии строительства либо отказаны по замеру. Правило для них не пишется.");
    table([
      { title: "Код", width: 0.12 },
      { title: "Параметр", width: 0.38 },
      { title: "Почему не проверяется", width: 0.5 },
    ], report.out_of_scope.map((r) => [r.parameter_code, dash(r.parameter_name), dash(r.reason)]), 7.5);
  }

  if (report.hypothesis_params.length) {
    heading(`Параметры, которые проверяет черновик правила — ${report.hypothesis_params.length}`);
    note("Правила ждут решения специалиста. Нарушения, найденные черновиком, — гипотезы в таблице 5; " +
      "«расхождения нет» от черновика проверкой не считается.");
    table([
      { title: "Код", width: 0.12 },
      { title: "Параметр", width: 0.38 },
      { title: "Что нашёл черновик", width: 0.5 },
    ], report.hypothesis_params.map((r) => [r.parameter_code, dash(r.parameter_name), dash(r.reason)]), 7.5);
  }

  // ---- раздел 7 ----
  heading("Резолютивная часть");
  note(report.resolution.note);
  if (report.resolution.available) {
    table(recordColumns, [...report.resolution.high, ...report.resolution.medium].map(recordRow));
  }

  // ---- изменения версии ----
  if (report.changes) {
    heading("Изменения по сравнению с прошлой версией");
    const c = report.changes;
    kv([
      ["Добавлено записей", String(c.added?.length ?? 0)],
      ["Удалено записей", String(c.removed?.length ?? 0)],
      ["Изменились значения", String(c.changed?.length ?? 0)],
      ["Из них с решением инспектора — пересмотреть", (c.decided_changed ?? []).map((x: any) => x.finding_id).join(", ") || "—"],
    ]);
  }

  // ---- карточки ----
  heading(`Раздел 8. Карточки доказательств — ${report.evidence_cards.length}`);
  for (const card of report.evidence_cards) {
    out.push({ kind: "card", text: `${card.finding_id} — ${dash(card.parameter_name)}` });
    const superseded = [...card.superseded_revisions.expected, ...card.superseded_revisions.actual]
      .map((r: any) => `используется ${r.used.revision} (${r.used.values.join(", ")}); устаревшие: ` +
        r.superseded.map((s: any) => `${s.revision} (${s.values.join(", ")})`).join(", "))
      .join("\n");
    kv([
      ["object_id / matrix_code / rule_version", `${dash(card.object_id)} / ${card.matrix_code} / ${dash(card.rule_version)}`],
      ["Локация", dash(card.location)],
      ["expected_value (ПД)", dash(card.expected_value)],
      ["actual_value (РД)", dash(card.actual_value)],
      ...(card.built_value ? [["built_value (ИД)", `${card.built_value}${card.built_check ? ` — ${card.built_check}` : ""}`] as [string, string]] : []),
      ["source_expected", sourceText(card.source_expected)],
      ["source_actual", sourceText(card.source_actual)],
      ...(superseded ? [["Редакции", superseded] as [string, string]] : []),
      ["Обоснование (правило)", dash(card.rule_basis)],
      ["Отклонение", dash(card.deviation)],
      ["approved_change_ref", card.approved_change_ref],
      ["completeness_status", dash(card.completeness_status)],
      ["finding_status", card.finding_status],
      ["review_priority", card.review_priority],
      ["expert_decision", decisionText(card.expert_decision)],
      ...(card.changed_after_decision
        ? [["Изменилось после решения", `прежние значения: ПД ${dash(card.changed_after_decision.pd_value)}, РД ${dash(card.changed_after_decision.rd_value)}`] as [string, string]]
        : []),
    ], 7.5);
  }

  heading("Раздел 9. Правила подсчёта");
  table([{ title: "Категория", width: 0.35 }, { title: "Правило включения в итог", width: 0.65 }],
    report.counting_rules.map((r) => [r.category, r.rule]));
  return out;
}
