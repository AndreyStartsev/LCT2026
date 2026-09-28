// Дашборд объекта (#83): карта 132 параметров и сводка сходятся с протоколом.
//   npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { Ajv } from "ajv";
import addFormats from "ajv-formats";
import fastJson from "fast-json-stringify";
import { buildDashboard, CELL_STATES, DASHBOARD_RESPONSE } from "../dist/dashboard.js";
import { buildReport, NOT_CHECKED_REASON } from "../dist/report.js";

const crit = "Критическое (приостановка работ)";
const sig = "Существенное (предписание)";
const param = (id, code, section, extra = {}) => ({
  parameter_id: id, parameter_code: code, parameter_name: `Параметр ${code}`, section,
  criticality: id % 5 === 0 ? sig : crit, queue: 1, implemented: true, findings: [], status: "COMPLETE", ...extra,
});

// Семь параметров — по одному на каждое состояние клетки
const coverage = [
  param(1, "PZ-001", "ПЗ"),                                    // подтверждённое нарушение
  param(2, "PZ-002", "ПЗ"),                                    // кандидат
  param(3, "PZ-003", "ПЗ"),                                    // без замечаний
  param(4, "AR-004", "АР"),                                    // несопоставимо
  param(5, "AR-005", "АР", { status: "MISSING_EVIDENCE", reason: "значение не найдено" }),
  param(6, "AR-006", "АР", { status: "NOT_APPLICABLE", reason: "у объекта нет подземной части" }),
  param(7, "KR-007", "КР", { implemented: false, status: "NOT_CHECKED", reason: "правило не реализовано" }),
];

const f = (id, code, label, status, body = {}) => ({
  id, finding_id: `O::${code}::${id}`, parameter_code: code, location: null,
  violation_label: label, verification_status: status, criticality: crit, body,
});

const findings = [
  f("u1", "PZ-001", "VIOLATION_PRESENT", "PENDING"),
  f("u2", "PZ-001", "VIOLATION_PRESENT", "CONFIRMED_VIOLATION"),
  f("u3", "PZ-002", "VIOLATION_PRESENT", "PENDING"),
  f("u4", "PZ-003", "NO_VIOLATION", "NOT_REQUIRED"),
  f("u5", "AR-004", null, "NOT_REQUIRED", { protocol: { completeness_status: "NOT_COMPARABLE" } }),
  // подтверждённая гипотеза свободного поиска: в итог нарушений входит, в карту Матрицы — нет
  f("u6", "FREE-AR-ROOM-AREA", "VIOLATION_PRESENT", "CONFIRMED_VIOLATION",
    { matrix_scope: "FREE_SEARCH", promoted_at: "2026-09-18T12:29:06Z" }),
  // разделённая запись в сводку не входит
  f("u7", "PZ-003", "VIOLATION_PRESENT", "SPLIT"),
];

const input = {
  process: { id: "p1", object_id: "OBJ-1", status: "VERIFYING", upload_status: ["PD_UPLOADED", "RD_PARTIAL"], scenario: "PD_RD_ONLY" },
  object: { name: "Объект один" },
  protocol: {
    version: 3, status: "READY", created_at: "2026-09-18T12:00:00Z",
    report: {
      coverage,
      changes: { added: ["O::PZ-002::u3"], removed: [], changed: [{ finding_id: "O::PZ-001::u2" }],
                 decided_changed: [{ finding_id: "O::PZ-001::u2" }] },
    },
  },
  files: [],
  findings,
  sync: null,
};

test("каждый параметр получает ровно одно состояние клетки", () => {
  const d = buildDashboard(input);
  assert.equal(d.cells.length, coverage.length);
  assert.deepEqual(
    Object.fromEntries(d.cells.map((c) => [c.code, c.state])),
    {
      "PZ-001": "VIOLATION", "PZ-002": "CANDIDATE", "PZ-003": "CLEAN", "AR-004": "NOT_COMPARABLE",
      "AR-005": "MISSING_EVIDENCE", "AR-006": "NOT_APPLICABLE", "KR-007": "NOT_CHECKED",
    },
  );
});

test("воронка карточки совпадает с разделом 2 протокола", () => {
  const d = buildDashboard(input);
  const params = Object.fromEntries(buildReport(input).section_2_summary.parameters.map((p) => [p.key, p.count]));
  assert.equal(d.matrix.total, params.TOTAL);
  assert.equal(d.matrix.compared, params.COMPARED);
  assert.equal(d.matrix.missing_evidence, params.MISSING_EVIDENCE);
  assert.equal(d.matrix.not_comparable, params.NOT_COMPARABLE);
  assert.equal(d.matrix.not_checked, params.NOT_CHECKED);
  // неприменимый параметр — своя группа, как в разделе 2 протокола
  assert.equal(d.matrix.not_applicable, params.NOT_APPLICABLE);
  assert.equal(d.matrix.not_applicable, 1);
  assert.equal(d.cells.filter((c) => c.group === "MISSING_EVIDENCE").length, params.MISSING_EVIDENCE);
});

test("группы клеток в сумме дают все параметры", () => {
  const d = buildDashboard(input);
  const m = d.matrix;
  assert.equal(
    m.compared + m.missing_evidence + m.not_comparable + m.not_checked + m.not_applicable + (m.out_of_scope ?? 0) + (m.hypothesis ?? 0),
    m.total,
  );
  assert.equal(d.cells.length, m.total, "клеток столько же, сколько параметров");
});

test("подтверждённая гипотеза — в итоге нарушений, но не в карте Матрицы", () => {
  const d = buildDashboard(input);
  assert.equal(d.records.confirmed, 2);
  assert.equal(d.records.confirmed_free, 1);
  assert.ok(!d.cells.some((c) => c.code.startsWith("FREE")));
});

test("щелчок по клетке открывает самую важную запись параметра", () => {
  const d = buildDashboard(input);
  assert.equal(d.cells.find((c) => c.code === "PZ-001").finding, "u2"); // подтверждённая раньше ожидающей
  assert.equal(d.cells.find((c) => c.code === "PZ-003").finding, "u4"); // разделённая не выбирается
  assert.equal(d.cells.find((c) => c.code === "KR-007").finding, null);
});

test("изменения — числами, неактуальные решения — ссылками на записи", () => {
  const d = buildDashboard(input);
  assert.deepEqual(d.changes, { added: 1, changed: 1, removed: 0, decided_changed: ["u2"] });
});

test("причина — только своя, по этому объекту", () => {
  const d = buildDashboard(input);
  assert.equal(d.cells.find((c) => c.code === "PZ-003").reason, null);
  assert.equal(d.cells.find((c) => c.code === "AR-006").reason, "у объекта нет подземной части");
  // заметка разработки у нереализованного правила — про корпус, а не про объект
  assert.equal(d.cells.find((c) => c.code === "KR-007").reason, null);
});

test("у непроверенного параметра — пометка для инспектора из правила, у остальных её нет", () => {
  const note = "Правило на проверке: итог сводного сметного расчёта сравнивается со сметой рабочей стадии, а смета в рабочую документацию не входит.";
  const withNote = {
    ...input,
    protocol: {
      ...input.protocol,
      report: {
        ...input.protocol.report,
        coverage: coverage.map((c) =>
          c.parameter_code === "KR-007" || c.parameter_code === "AR-005" ? { ...c, note } : c),
      },
    },
  };
  const d = buildDashboard(withNote);
  const cell = d.cells.find((c) => c.code === "KR-007");
  assert.equal(cell.note, note);
  assert.equal(cell.reason, null, "заметка разработки по-прежнему не показывается");
  assert.equal(d.cells.find((c) => c.code === "AR-005").note, null, "пометка — только у «не проверено»");
  assert.equal(d.cells.find((c) => c.code === "PZ-003").note, null);
  // ответ проходит схему маршрута, и сериализатор поле не выбрасывает
  const out = JSON.parse(fastJson(DASHBOARD_RESPONSE)(d));
  assert.equal(out.cells.find((c) => c.code === "KR-007").note, note);
});

test("протокол не печатает заметку разработки у непроверенного параметра", () => {
  const withNote = {
    ...input,
    protocol: {
      ...input.protocol,
      report: {
        ...input.protocol.report,
        coverage: coverage.map((c) =>
          c.parameter_code === "KR-007" ? { ...c, reason: "текстом встречается на Речникове на 7 страницах" } : c),
      },
    },
  };
  const nc = buildReport(withNote).not_checked.find((p) => p.parameter_code === "KR-007");
  assert.equal(nc.reason, NOT_CHECKED_REASON);
  assert.doesNotMatch(JSON.stringify(buildReport(withNote).not_checked), /Речников/);
});

test("ход автоматики по версиям протокола", () => {
  const d = buildDashboard(input, [
    { version: 1, created_at: "2026-09-18T09:00:00Z", records: "40", candidates: 12, compared: "5" },
    { version: 2, created_at: "2026-09-18T12:00:00Z", records: 39, candidates: "12", compared: 6 },
  ]);
  assert.deepEqual(d.history.map((h) => [h.version, h.records, h.candidates, h.compared]), [[1, 40, 12, 5], [2, 39, 12, 6]]);
  assert.deepEqual(buildDashboard(input).history, []);
});

test("параметр вне проверки документов — своя клетка с причиной и своя строка сводки", () => {
  const reason = "Регистрация лимитов в АИС «ОСИГ» — событие стадии строительства во внешней системе";
  const withOut = {
    ...input,
    protocol: {
      ...input.protocol,
      report: {
        ...input.protocol.report,
        coverage: [...coverage, param(8, "OOS-098", "ООС",
          { implemented: false, status: "OUT_OF_SCOPE", out_of_scope: "EXTERNAL", reason })],
      },
    },
  };
  const dash = buildDashboard(withOut);
  const cell = dash.cells.find((c) => c.code === "OOS-098");
  assert.equal(cell.state, "OUT_OF_SCOPE");
  assert.equal(cell.reason, reason, "причина видна, в отличие от «не проверено»");
  assert.equal(dash.cells.find((c) => c.code === "KR-007").state, "NOT_CHECKED");
  const report = buildReport(withOut);
  const row = report.section_2_summary.parameters.find((r) => r.key === "OUT_OF_SCOPE");
  assert.equal(row?.count, 1);
  assert.equal(report.out_of_scope[0].parameter_code, "OOS-098");
  assert.ok(!report.not_checked.some((r) => r.parameter_code === "OOS-098"), "в «не проверено» не попадает");
  const groups = ["COMPARED", "MISSING_EVIDENCE", "NOT_COMPARABLE", "NOT_APPLICABLE", "NOT_CHECKED", "OUT_OF_SCOPE"];
  const sum = report.section_2_summary.parameters.filter((r) => groups.includes(r.key)).reduce((a, r) => a + r.count, 0);
  assert.equal(sum, withOut.protocol.report.coverage.length, "группы по-прежнему дают все параметры");
});

test("параметр черновика правила — своя клетка, гипотеза в таблице 5 до решения инспектора (#95)", async () => {
  const { isHypothesis } = await import("../dist/verification.js");
  const { countFindings } = await import("../dist/process.js");
  const reason = "правило на проверке: похоже на нарушение — 1";
  const draft = f("u8", "KR-054", "VIOLATION_PRESENT", "PENDING", { provisional: true, needs_expert: true });
  const withDraft = {
    ...input,
    findings: [...findings, draft],
    protocol: {
      ...input.protocol,
      report: {
        ...input.protocol.report,
        coverage: [...coverage, param(8, "KR-054", "КР", {
          implemented: false, status: "HYPOTHESIS", reason, findings: [draft.finding_id],
          hypothesis: { violation: 1, no_violation: 0, not_comparable: 0 } })],
      },
    },
  };
  const dash = buildDashboard(withDraft);
  const cell = dash.cells.find((c) => c.code === "KR-054");
  assert.equal(cell.state, "HYPOTHESIS");
  assert.equal(cell.reason, reason, "что нашёл черновик — видно");
  assert.equal(dash.matrix.hypothesis, 1);
  const report = buildReport(withDraft);
  assert.equal(report.section_2_summary.parameters.find((r) => r.key === "HYPOTHESIS")?.count, 1);
  assert.ok(report.tables.hypotheses.some((r) => r.finding_id === draft.finding_id && r.provisional),
    "гипотеза черновика — в таблице 5");
  assert.equal(report.tables.hypotheses.find((r) => r.provisional).status_text, "Гипотеза: правило на проверке");
  assert.ok(!report.tables.candidates.high.some((r) => r.finding_id === draft.finding_id), "в кандидатах её нет");
  assert.equal(report.hypothesis_params[0].parameter_code, "KR-054");
  const groups = ["COMPARED", "MISSING_EVIDENCE", "NOT_COMPARABLE", "NOT_APPLICABLE", "NOT_CHECKED", "OUT_OF_SCOPE", "HYPOTHESIS"];
  const sum = report.section_2_summary.parameters.filter((r) => groups.includes(r.key)).reduce((a, r) => a + r.count, 0);
  assert.equal(sum, withDraft.protocol.report.coverage.length, "группы по-прежнему дают все параметры");
  assert.equal(isHypothesis(draft), true, "решение по ней — только после «взять в кандидаты»");
  const counts = countFindings([{ verification_status: "PENDING", violation_label: "VIOLATION_PRESENT",
    matrix_scope: "MATRIX", provisional: true, promoted: false, parameter_code: "KR-054", n: 1 }]);
  assert.deepEqual([counts.hypotheses, counts.candidates, counts.pending], [1, 0, 0], "финализацию не блокирует");

  // инспектор взял гипотезу в кандидаты: параметр сопоставлен, как у правила прода
  const taken = { ...draft, body: { ...draft.body, promoted_at: "2026-09-25T10:00:00Z" } };
  const promoted = buildDashboard({ ...withDraft, findings: [...findings, taken] });
  assert.equal(promoted.cells.find((c) => c.code === "KR-054").state, "CANDIDATE");
  assert.equal(isHypothesis(taken), false);
});

test("неприменимый параметр без правила — «неприменимо», а не «не проверено»", () => {
  // POD-090…097 на Речникове: снос по отдельному проекту, правила для параметров нет
  const reason = "снос выполняется по отдельному проекту и в комплект объекта не входит";
  const withNa = {
    ...input,
    protocol: {
      ...input.protocol,
      report: {
        ...input.protocol.report,
        coverage: [...coverage, param(9, "POD-090", "ПОД", { implemented: false, status: "NOT_APPLICABLE", reason })],
      },
    },
  };
  const dash = buildDashboard(withNa);
  const cell = dash.cells.find((c) => c.code === "POD-090");
  assert.equal(cell.state, "NOT_APPLICABLE");
  assert.equal(cell.group, "NOT_APPLICABLE");
  assert.equal(cell.reason, reason, "причина по объекту видна");
  assert.equal(dash.matrix.not_applicable, 2);
  const report = buildReport(withNa);
  assert.equal(report.section_2_summary.parameters.find((r) => r.key === "NOT_APPLICABLE")?.count, 2);
  assert.ok(!report.not_checked.some((r) => r.parameter_code === "POD-090"), "в «не проверено» не попадает");
  const row = report.tables.completeness.find((r) => r.parameter_code === "POD-090");
  assert.equal(row?.status, "NOT_APPLICABLE", "в таблице 1 — со своим статусом и причиной");
  assert.equal(row?.reason, reason);
  assert.equal(report.section_2_summary.sections.find((s) => s.section === "ПОД")?.not_applicable, 1);
  const groups = ["COMPARED", "MISSING_EVIDENCE", "NOT_COMPARABLE", "NOT_APPLICABLE", "NOT_CHECKED"];
  const sum = report.section_2_summary.parameters.filter((r) => groups.includes(r.key)).reduce((a, r) => a + r.count, 0);
  assert.equal(sum, withNa.protocol.report.coverage.length, "группы дают все параметры");
});

test("ответ со всеми состояниями клеток проходит схему, по которой стенд проверяет ответы", () => {
  // черновик и «вне проверки» пришли в протоколы 25.09 — схема о них не знала, и стенд
  // отвечал на сводку ошибкой «Запрос не соответствует схеме OpenAPI»
  const all = {
    ...input,
    protocol: {
      ...input.protocol,
      report: {
        ...input.protocol.report,
        coverage: [
          ...coverage,
          param(8, "OOS-098", "ООС", { implemented: false, status: "OUT_OF_SCOPE", out_of_scope: "EXTERNAL", reason: "внешняя система" }),
          param(9, "KR-054", "КР", { implemented: false, status: "HYPOTHESIS", reason: "черновик правила" }),
        ],
      },
    },
  };
  const dash = buildDashboard(all);
  assert.deepEqual(new Set(dash.cells.map((c) => c.state)), new Set(CELL_STATES), "в примере все состояния клетки");

  // так же, как на стенде (app.ts): ответ сверяется до сериализации
  const ajv = new Ajv({ allErrors: true, coerceTypes: false, useDefaults: false, removeAdditional: false, strict: false });
  addFormats.default(ajv);
  const validate = ajv.compile(DASHBOARD_RESPONSE);
  assert.ok(validate(dash), ajv.errorsText(validate.errors));

  // сериализатор Fastify выбрасывает поля, которых нет в схеме: счётчики должны дойти до клиента
  const sent = JSON.parse(fastJson(DASHBOARD_RESPONSE)(dash));
  assert.equal(sent.matrix.hypothesis, 1);
  assert.equal(sent.matrix.out_of_scope, 1);
  assert.deepEqual(sent.matrix, JSON.parse(JSON.stringify(dash.matrix)));
  assert.deepEqual(sent.cells, JSON.parse(JSON.stringify(dash.cells)));
});
