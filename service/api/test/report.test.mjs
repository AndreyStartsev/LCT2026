// Протокол проверки объекта: разделы, статусы и PDF. Задача #30.
//   npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { inflateSync } from "node:zlib";
import { buildReport, findingStatus } from "../dist/report.js";
import { renderReportPdf } from "../dist/report-pdf.js";
import { renderReportDocx } from "../dist/report-docx.js";
import { protocolBlocks } from "../dist/report-blocks.js";
import JSZip from "jszip";
import { toXml } from "../dist/routes/report.js";

const coverage = [
  { parameter_id: 27, parameter_code: "SPZU-027", parameter_name: "Площадь озеленения", section: "СПЗУ", criticality: "Критическое (приостановка работ)", queue: 1, implemented: true, findings: ["O::SPZU-027"], status: "COMPLETE" },
  { parameter_id: 26, parameter_code: "SPZU-026", parameter_name: "Площадь плиточного покрытия", section: "СПЗУ", criticality: "Существенное (предписание)", queue: 1, implemented: true, findings: ["O::SPZU-026"], status: "COMPLETE" },
  { parameter_id: 9, parameter_code: "PZ-009", parameter_name: "Отметка 0.000", section: "ПЗ", criticality: "Критическое (приостановка работ)", queue: 1, implemented: true, findings: ["O::PZ-009"], status: "COMPLETE" },
  { parameter_id: 1, parameter_code: "PZ-001", parameter_name: "Площадь застройки", section: "ПЗ", criticality: "Критическое (приостановка работ)", queue: 1, implemented: true, findings: ["O::PZ-001"], status: "MISSING_EVIDENCE" },
  { parameter_id: 2, parameter_code: "PZ-002", parameter_name: "Общая площадь", section: "ПЗ", criticality: "Критическое (приостановка работ)", queue: 1, implemented: true, findings: [], status: "MISSING_EVIDENCE", reason: "значение не найдено ни в проектной, ни в рабочей стадии" },
  { parameter_id: 40, parameter_code: "AR-040", parameter_name: "Ширина коридоров", section: "АР", criticality: "Критическое (приостановка работ)", queue: 2, implemented: false, findings: [], status: "NOT_CHECKED", reason: "размер на чертеже" },
];

const ev = (stage, fid, page) => ({ stage, file_id: fid, pdf_page_number: page, sha256: "ab".repeat(32), revision: "кор.3", approval_status: "UNKNOWN", bbox_tz: [[0.1, 0.2, 0.3, 0.4]], quote: "цитата" });
const finding = (fid, code, label, verification, extra = {}) => ({
  id: `00000000-0000-4000-8000-${String(Math.random()).slice(2, 14).padEnd(12, "0")}`,
  finding_id: fid, parameter_code: code, violation_label: label, verification_status: verification,
  pd_value: "1", rd_value: "2", criticality: label === "VIOLATION_PRESENT" ? "Критическое (приостановка работ)" : null,
  reason_code: null, comment: null, decided_by: null, decided_at: null,
  body: { object_id: "O", title: code, locations: ["SITE"], evidence: [ev("PD", "F1", 3), ev("RD", "F2", 4)],
    extraction: { detail: "разница", rule_basis: "триггер", pd: { revisions: [{ used: { revision: "кор.3", values: ["1"] }, superseded: [{ revision: "исходная", values: ["5"] }] }] } },
    protocol: { completeness_status: label === "COMPARISON_IMPOSSIBLE" ? "MISSING_EVIDENCE" : "COMPLETE" } },
  ...extra,
});

function input(status, findings) {
  return {
    process: { id: "11111111-2222-4333-8444-555555555555", object_id: "O", status, scenario: "PD_RD_ONLY", upload_status: ["PD_UPLOADED", "RD_UPLOADED", "ID_MISSING"], finalized_at: status === "FINALIZED" ? new Date() : null },
    object: { name: "Объект" },
    protocol: { version: 2, matrix_version: "q1-x", dataset_version: "m-y", model_version: "p", input_manifest_hash: "cd".repeat(32), created_at: new Date(), report: { coverage, stage_files: { PD: { accepted: 3, rejected: 0 }, RD: { accepted: 2, rejected: 1, reject_codes: { UNSUPPORTED_FORMAT: 1 } }, ID: { accepted: 0, rejected: 0 } } } },
    files: [],
    findings,
  };
}

const findings = () => [
  finding("O::SPZU-027", "SPZU-027", "VIOLATION_PRESENT", "PENDING"),
  finding("O::SPZU-026", "SPZU-026", "VIOLATION_PRESENT", "NEGATIVE_VERIFIED", { reason_code: "APPROVED_CHANGE", comment: "письмо заказчика №5", decided_by: "inspector", decided_at: new Date() }),
  finding("O::PZ-009", "PZ-009", "NO_VIOLATION", "NOT_REQUIRED"),
  finding("O::PZ-001", "PZ-001", "COMPARISON_IMPOSSIBLE", "NOT_REQUIRED", { rd_value: null }),
];

test("статус записи: метка конвейера и решение инспектора", () => {
  const [pending, rejected, auto, missing] = findings();
  assert.equal(findingStatus(pending), "CANDIDATE");
  assert.equal(findingStatus(rejected), "NEGATIVE_VERIFIED");
  assert.equal(findingStatus(auto), "NEGATIVE_VERIFIED");
  assert.equal(findingStatus(missing), "MISSING_EVIDENCE");
});

test("сводка: группы параметров в сумме дают все параметры Матрицы", () => {
  const report = buildReport(input("VERIFYING", findings()));
  const groups = Object.fromEntries(report.section_2_summary.parameters.map((r) => [r.key, r.count]));
  assert.equal(groups.TOTAL, 6);
  assert.equal(groups.COMPARED + groups.MISSING_EVIDENCE + groups.NOT_COMPARABLE + groups.NOT_CHECKED, groups.TOTAL);
  assert.equal(groups.COMPARED, 3);
  assert.equal(groups.MISSING_EVIDENCE, 2);
  assert.equal(groups.NOT_CHECKED, 1);
  assert.equal(groups.CANDIDATE, 1);
  // по разделам — те же числа: разделы в порядке каталога, суммы совпадают с общими
  const sections = report.section_2_summary.sections;
  assert.deepEqual(sections.map((s) => s.section), ["ПЗ", "СПЗУ", "АР"]);
  const sum = (key) => sections.reduce((acc, s) => acc + s[key], 0);
  assert.equal(sum("parameters"), groups.TOTAL);
  assert.equal(sum("compared"), groups.COMPARED);
  assert.equal(sum("not_checked"), groups.NOT_CHECKED);
  assert.equal(sections.find((s) => s.section === "СПЗУ").candidates, 1);
});

test("таблицы: кандидат по риску, отрицательные, комплектность со стадией ИД", () => {
  const report = buildReport(input("VERIFYING", findings()));
  assert.deepEqual(report.tables.candidates.high.map((r) => r.parameter_code), ["SPZU-027"]);
  assert.deepEqual(report.tables.negatives.map((r) => r.parameter_code).sort(), ["PZ-009", "SPZU-026"]);
  const kinds = report.tables.completeness.map((r) => `${r.kind}:${r.parameter_code ?? r.stage}`);
  assert.ok(kinds.includes("STAGE:ID"), kinds.join(" "));
  assert.ok(kinds.includes("RECORD:PZ-001"));
  assert.ok(kinds.includes("PARAMETER:PZ-002"));
  assert.deepEqual(report.not_checked.map((r) => r.parameter_code), ["AR-040"]);
  const rd = report.section_1_upload.stages.find((s) => s.stage === "RD");
  assert.equal(rd.files_expected, 3);
});

test("частичная загрузка: сценарий называет недопринятую и отсутствующую стадии", () => {
  const base = input("VERIFYING", findings());
  const report = buildReport({ ...base, process: { ...base.process, scenario: "PARTIALLY_LOADED", upload_status: ["PD_UPLOADED", "RD_PARTIAL", "ID_MISSING"] } });
  assert.equal(report.section_1_upload.scenario, "PARTIALLY_LOADED");
  assert.equal(report.section_1_upload.scenario_text,
    "загружено частично (РД — не приняты 1); исполнительная документация не загружена");
  assert.equal(buildReport(base).section_1_upload.scenario_text, "ПД и РД, исполнительная документация не загружена");
});

test("резолютивная часть только после финализации", () => {
  const before = buildReport(input("COMPLETED", findings()));
  assert.equal(before.resolution.available, false);
  const confirmed = findings();
  confirmed[0] = { ...confirmed[0], verification_status: "CONFIRMED_VIOLATION", decided_by: "inspector", decided_at: new Date() };
  const after = buildReport(input("FINALIZED", confirmed));
  assert.equal(after.resolution.available, true);
  assert.deepEqual(after.resolution.high.map((r) => r.parameter_code), ["SPZU-027"]);
  assert.equal(after.protocol.status, "PROTOCOL_FINALIZED");
});

test("карточка доказательства: источники, редакции, согласованное изменение", () => {
  const report = buildReport(input("VERIFYING", findings()));
  const card = report.evidence_cards.find((c) => c.matrix_code === "SPZU-026");
  assert.equal(card.source_expected[0].sha256.length, 64);
  assert.deepEqual(card.source_expected[0].bbox, [[0.1, 0.2, 0.3, 0.4]]);
  assert.equal(card.approved_change_ref, "письмо заказчика №5");
  assert.equal(card.expert_decision.reason_code, "APPROVED_CHANGE");
  assert.equal(card.superseded_revisions.expected[0].superseded[0].revision, "исходная");
  assert.equal(report.evidence_cards.find((c) => c.matrix_code === "SPZU-027").approved_change_ref, "NONE");
});

// Гипотеза свободного поиска: запись вне Матрицы, которую инспектор может взять в кандидаты (ТЗ 9.5)
const hypothesis = (fid, verification, promoted, extra = {}) => {
  const f = finding(fid, "FREE-AR-ROOM-AREA", "VIOLATION_PRESENT", verification, extra);
  return { ...f, criticality: "Существенное (предписание) — требует утверждения",
    body: { ...f.body, matrix_scope: "FREE_SEARCH", locations: [fid.split("::").at(-1)],
      ...(promoted ? { promoted_at: "2026-09-18T10:00:00Z", promoted_by: "inspector" } : {}) } };
};

test("гипотеза: SUSPICION до перевода в кандидаты, после — общий путь по решению", () => {
  assert.equal(findingStatus(hypothesis("O::FREE::339", "PENDING", false)), "SUSPICION");
  assert.equal(findingStatus(hypothesis("O::FREE::339", "PENDING", true)), "CANDIDATE");
  assert.equal(findingStatus(hypothesis("O::FREE::132", "CONFIRMED_VIOLATION", true)), "CONFIRMED_VIOLATION");
  assert.equal(findingStatus(hypothesis("O::FREE::132", "NEGATIVE_VERIFIED", true)), "NEGATIVE_VERIFIED");
  assert.equal(findingStatus(hypothesis("O::FREE::132", "CLARIFICATION_REQUIRED", true)), "CLARIFICATION_REQUIRED");
});

test("вид, который специалист решил не показывать, — в конце таблицы гипотез (Р-108)", () => {
  const drop = (fid) => {
    const h = hypothesis(fid, "PENDING", false);
    return { ...h, body: { ...h.body, specialist: { verdict: "drop", scope: "kind" } } };
  };
  const rows = [...findings(), drop("O::FREE::101"), hypothesis("O::FREE::339", "PENDING", false),
    drop("O::FREE::102"), hypothesis("O::FREE::400", "PENDING", false)];
  const report = buildReport(input("VERIFYING", rows));
  assert.deepEqual(report.tables.hypotheses.map((r) => r.finding_id),
    ["O::FREE::339", "O::FREE::400", "O::FREE::101", "O::FREE::102"]);
});

test("подтверждённая гипотеза — в подтверждённых нарушениях, один раз и вне сводки по параметрам", () => {
  const decided = { decided_by: "inspector", decided_at: new Date() };
  const rows = [...findings(),
    hypothesis("O::FREE::132", "CONFIRMED_VIOLATION", true, decided),
    hypothesis("O::FREE::140", "PENDING", true),
    hypothesis("O::FREE::339", "PENDING", false)];
  const report = buildReport(input("VERIFYING", rows));
  const ids = (list) => list.map((r) => r.finding_id);
  assert.deepEqual(ids(report.tables.confirmed), ["O::FREE::132"]);
  assert.deepEqual(ids(report.tables.hypotheses), ["O::FREE::339"]);
  assert.deepEqual(ids(report.tables.candidates.medium), ["O::FREE::140"]);
  // каждая запись — ровно в одной таблице
  const all = [...report.tables.confirmed, ...report.tables.hypotheses, ...report.tables.negatives,
    ...Object.values(report.tables.candidates).flat(), ...report.tables.completeness.filter((r) => r.kind === "RECORD")];
  assert.equal(all.filter((r) => r.finding_id === "O::FREE::132").length, 1);
  const records = Object.fromEntries(report.section_2_summary.records.map((r) => [r.key, r.count]));
  assert.equal(records.CONFIRMED_VIOLATION, 1);
  assert.equal(records.CANDIDATE, 2);
  assert.equal(records.SUSPICION, 1);
  // у взятой в кандидаты гипотезы есть карточка доказательств, у невзятой — нет
  const cards = new Set(report.evidence_cards.map((c) => c.finding_id));
  assert.ok(cards.has("O::FREE::132") && cards.has("O::FREE::140") && !cards.has("O::FREE::339"));
  // сводка по параметрам Матрицы и по разделам — такая же, как без гипотез
  const baseline = buildReport(input("VERIFYING", findings()));
  assert.deepEqual(report.section_2_summary.parameters, baseline.section_2_summary.parameters);
  assert.deepEqual(report.section_2_summary.sections, baseline.section_2_summary.sections);
  // после финализации подтверждённая гипотеза входит в резолютивную часть
  const final = buildReport(input("FINALIZED", rows));
  assert.deepEqual(ids(final.resolution.medium), ["O::FREE::132"]);
});

/** Строки текста на каждом листе PDF от pdfkit: высота строки от низа листа (оператор Tm). */
function textLinesByPage(pdf) {
  const raw = pdf.toString("latin1");
  return [...raw.matchAll(/\/Type \/Page\b(?!s)[^>]*?\/Contents (\d+) 0 R/g)].map(([, id]) => {
    const head = new RegExp(`\\n${id} 0 obj\\s*<<\\s*/Length (\\d+)(\\s*/Filter /FlateDecode)?\\s*>>\\s*stream\\n`).exec(raw);
    const start = head.index + head[0].length;
    const stream = pdf.subarray(start, start + Number(head[1]));
    const content = (head[2] ? inflateSync(stream) : stream).toString("latin1");
    return [...content.matchAll(/1 0 0 1 \S+ (\S+) Tm/g)].map(([, y]) => Number(y));
  });
}

test("PDF и XML собираются", async () => {
  const report = buildReport(input("VERIFYING", findings()));
  const pdf = await renderReportPdf(report);
  assert.equal(pdf.subarray(0, 5).toString(), "%PDF-");
  assert.ok(pdf.length > 5000, `PDF ${pdf.length} байт`);
  // Колонтитул не должен добавлять листы: строку ниже нижнего поля pdfkit переносит на новый лист.
  // Потолок числа листов для этого не годится — число зависит от шрифта: тот же протокол в образе API
  // (DejaVu Sans Condensed) занимает 5 листов, на macOS (Arial Narrow) — 4. Поэтому проверяется
  // каждый лист: колонтитул ниже нижнего поля (36 pt, MARGIN в report-pdf.ts) и содержание над ним.
  const pages = (pdf.toString("latin1").match(/\/Type \/Page\b(?!s)/g) ?? []).length;
  const lines = textLinesByPage(pdf);
  assert.ok(pages >= 1 && lines.length === pages, `листов в PDF ${pages}, прочитано ${lines.length}`);
  lines.forEach((ys, i) => {
    assert.ok(ys.some((y) => y < 36), `лист ${i + 1} из ${pages}: нет колонтитула`);
    assert.ok(ys.some((y) => y > 36), `лист ${i + 1} из ${pages}: только колонтитул`);
  });
  const xml = toXml(report);
  assert.ok(xml.startsWith("<protocol>"));
  assert.ok(xml.includes("<parameter_code>SPZU-027</parameter_code>"));
  assert.ok(!xml.includes("<№"), "имена элементов — только допустимые в XML");
});

test("DOCX собирается из тех же блоков, что PDF (ТЗ, модуль 7)", async () => {
  const report = buildReport(input("VERIFYING", findings()));
  const docx = await renderReportDocx(report);
  assert.equal(docx.subarray(0, 2).toString(), "PK", "DOCX — это zip-архив");
  const zip = await JSZip.loadAsync(docx);
  assert.ok(zip.file("word/document.xml"), "в архиве есть основной документ");
  const xml = await zip.file("word/document.xml").async("string");
  const text = xml.replace(/<[^>]+>/g, "");
  // название, разделы и записи на месте
  assert.match(text, /ПРОТОКОЛ АВТОМАТИЗИРОВАННОЙ СВЕРКИ/);
  assert.match(text, /РАЗДЕЛ 2\. СВОДНАЯ СТАТИСТИКА/);
  assert.match(text, /SPZU-027/);
  // каждый заголовок блоков есть в документе — содержание у форматов одно
  for (const block of protocolBlocks(report).filter((b) => b.kind === "heading")) {
    assert.ok(text.includes(block.text.toUpperCase()), `нет раздела «${block.text}»`);
  }
  // шапка таблицы повторяется на новой странице, в колонтитуле — «Лист N из M»
  assert.match(xml, /<w:tblHeader\/>/);
  const footer = Object.keys(zip.files).find((name) => /word\/footer\d*\.xml/.test(name));
  assert.ok(footer, "колонтитул есть");
  assert.match(await zip.file(footer).async("string"), /Инспектор ИИ/);
});
