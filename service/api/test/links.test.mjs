// Связи документов объекта (#82): карта объекта и контекст находки.
//   npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { findingContext, objectMap, ROOM_MAX_DOCS } from "../dist/links.js";

const file = (file_id, stage, discipline, extra = {}) => ({
  file_id, relative_path: `${stage}/${file_id}.pdf`, status: "ACCEPTED", doc_stage: stage, discipline,
  document_code: `CODE-${file_id}`, pdf_pages: 100, revision_status: "CURRENT", chain_id: `ch-${file_id}`, ...extra,
});
const files = [
  file("F1", "PD", "OV"),
  file("F2", "RD_ID_MIXED", "OV"),                                   // смешанный комплект — рабочая стадия
  file("F3", "ID", "OTHER"),
  file("F4", "PD", "OV", { chain_id: "ch-ov", revision_status: "SUPERSEDED" }),
  file("F5", "PD", "OV", { chain_id: "ch-ov", revision_status: "CURRENT" }),
  file("F6", "UNKNOWN", null, { stage_manual: "RD", section_manual: "AR" }), // ручная правка инспектора
  file("F7", "PD", "AR", { status: "REJECTED" }),
  file("F8", "PD", "OV", { chain_id: "ch-ov", revision_status: "SUPERSEDED" }),
  ...Array.from({ length: 10 }, (_, i) => file(`P${i}`, "PD", "AR")),
];

const ev = (stage, file_id, page, quote = "цитата") => ({ stage, file_id, pdf_page_number: page, quote });
const finding = (id, code, label, status, body = {}) => ({
  id, finding_id: `O::${code}::${id}`, parameter_code: code, location: null, violation_label: label,
  verification_status: status, pd_value: "3 системы", rd_value: "2 системы", body,
});
const findings = [
  finding("u1", "IOS4-078", "VIOLATION_PRESENT", "PENDING", {
    location_type: "ROOM", locations: ["147", "12", "300"],
    evidence: [ev("PD", "F1", 84), ev("PD", "F1", 83), ev("PD", "F1", 84), ev("RD", "F2", 15, "В2.2 | 1 | пом. 147"), ev("PD", "F4", 3)],
  }),
  finding("u2", "IOS4-078", "VIOLATION_PRESENT", "CONFIRMED_VIOLATION", { location_type: "ROOM", locations: ["124"], evidence: [ev("PD", "F1", 1), ev("RD", "F2", 2)] }),
  finding("u3", "IOS4-078", "VIOLATION_PRESENT", "SPLIT", { locations: ["125"], evidence: [ev("PD", "F1", 1), ev("RD", "F2", 2)] }),
  finding("u4", "KR-055", "NO_VIOLATION", "NOT_REQUIRED", { evidence: [ev("PD", "F1", 5), ev("ID", "F3", 42), ev("RD", "F6", 3)] }),
  finding("u5", "PZ-001", null, "NOT_REQUIRED", { evidence: [ev("PD", "F1", 2)] }),       // одна стадия — не связь
];

const rooms = {
  "147": ["F1", "F2", "F6", "F8"],                   // F1, F2 — доказательства; F8 — заменённая редакция
  "12": ["F1", "F6"],                                 // короткий номер
  "300": ["F1", ...Array.from({ length: 10 }, (_, i) => `P${i}`)], // «клубок»
};

test("карта объекта: клетки стадий и разделов с учётом ручной правки", () => {
  const m = objectMap(files, findings);
  const cell = (s, sec) => m.grid.find((g) => g.stage === s && g.section === sec)?.documents ?? 0;
  assert.equal(cell("PD", "OV"), 4);
  assert.equal(cell("RD", "OV"), 1, "смешанный комплект считается рабочей стадией");
  assert.equal(cell("RD", "AR"), 1, "ручная стадия и раздел инспектора важнее разбора");
  assert.equal(cell("PD", "AR"), 10, "отклонённый файл в карту не попадает");
  assert.deepEqual(m.stages, { PD: 14, RD: 2, ID: 1 });
  assert.equal(m.mixed, 1, "карта говорит, сколько смешанных комплектов стоит в колонке РД");
});

test("карта объекта: связь — находка с доказательствами в двух стадиях", () => {
  const m = objectMap(files, findings);
  const link = (fs, fsec, ts, tsec, state) =>
    m.links.find((l) => l.from.stage === fs && l.from.section === fsec && l.to.stage === ts && l.to.section === tsec && l.state === state)?.findings ?? 0;
  assert.equal(link("PD", "OV", "RD", "OV", "CANDIDATE"), 1);
  assert.equal(link("PD", "OV", "RD", "OV", "VIOLATION"), 1);
  assert.equal(link("PD", "OV", "ID", "OTHER", "CLEAN"), 1);
  assert.equal(link("RD", "AR", "ID", "OTHER", "CLEAN"), 1);
  // разделённая запись и запись одной стадии связей не дают
  assert.equal(m.findings.length, 3);
  assert.deepEqual(m.findings.map((f) => f.state), ["VIOLATION", "CANDIDATE", "CLEAN"], "важное — первым");
  assert.deepEqual(m.findings.find((f) => f.id === "u4").stages, ["PD", "RD", "ID"]);
});

test("контекст: документы доказательства по стадиям, страницы и цитата", () => {
  const c = findingContext(findings[0], files, findings, rooms);
  const pd = c.stages.find((s) => s.stage === "PD");
  const f1 = pd.documents.find((d) => d.file_id === "F1");
  assert.deepEqual(f1.pages, [83, 84], "страницы без повторов, по порядку");
  assert.equal(pd.value, "3 системы");
  const rd = c.stages.find((s) => s.stage === "RD");
  assert.equal(rd.documents[0].quote, "В2.2 | 1 | пом. 147");
  assert.deepEqual(c.stages.find((s) => s.stage === "ID").documents, []);
  // заменённая редакция показана с указанием актуальной
  const f4 = pd.documents.find((d) => d.file_id === "F4");
  assert.equal(f4.revision_status, "SUPERSEDED");
  assert.deepEqual(f4.current, { file_id: "F5", name: "F5.pdf" });
});

test("контекст: та же проверка — без самой записи и без разделённых", () => {
  const c = findingContext(findings[0], files, findings, rooms);
  assert.equal(c.same_parameter.total, 1);
  assert.equal(c.same_parameter.items[0].id, "u2");
  assert.equal(c.same_parameter.items[0].state, "VIOLATION");
});

test("контекст: помещения — фильтр ложных связей", () => {
  const c = findingContext(findings[0], files, findings, rooms);
  const room = (n) => c.rooms.find((r) => r.room === n);
  // 147: доказательства не повторяются, заменённая редакция в связь не входит
  assert.equal(room("147").cut, null);
  assert.deepEqual(room("147").documents.map((d) => d.file_id), ["F6"]);
  assert.equal(room("147").superseded_skipped, 1);
  assert.equal(room("12").cut, "SHORT", "номер из двух цифр — часто номер строки таблицы");
  assert.equal(room("300").cut, "TANGLED", `больше ${ROOM_MAX_DOCS} документов — клубок`);
  assert.equal(c.rooms_indexed, true);
});

test("контекст без индекса помещений: протокол ещё не пересобран", () => {
  const c = findingContext(findings[0], files, findings, null);
  assert.equal(c.rooms, null);
  assert.equal(c.rooms_indexed, false);
});
