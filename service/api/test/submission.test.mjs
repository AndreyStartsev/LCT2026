// Файл сдачи организатору с учётом решений инспектора. Задача #63.
//   npm test
//
// Смысл верификации в том, что итоговый документ отражает решение человека: отклонённая
// запись не уходит организатору как нарушение, подтверждённая гипотеза уходит. Проверяется
// и обратное: пока решений нет, файл сдачи не должен пустеть.
import assert from "node:assert/strict";
import { test } from "node:test";
import { decidedSubmission } from "../dist/submission.js";

const check = (code, location, label = "VIOLATION_PRESENT") => ({
  parameter_code: code, location, violation_label: label,
  evidence: [{ stage: "PD", file_id: "F1", pdf_page_number: 3 }],
});

const finding = (findingId, code, locations, status, origin = null) => ({
  finding_id: findingId, parameter_code: code, location: locations.join(", "),
  verification_status: status, origin, body: { locations },
});

/** Подделка базы: отдаёт заранее заданные записи находок. */
function db(findings) {
  return { query: async () => ({ rows: findings }) };
}

const body = () => ({
  object_id: "OBJ",
  checks: [check("IOS4-078", "140"), check("IOS4-078", "143"), check("PZ-001", "SITE")],
});

test("без решений файл сдачи не меняется", async () => {
  const findings = [finding("f1", "IOS4-078", ["140", "143"], "PENDING"),
                    finding("f2", "PZ-001", ["SITE"], "PENDING")];
  const got = await decidedSubmission(db(findings), "p1", body(), null);
  assert.equal(got.body.checks.length, 3);
  assert.equal(got.removed, 0);
  assert.equal(got.added, 0);
  assert.equal(got.undecided, 3);
});

test("отклонённая инспектором запись в сдачу не идёт", async () => {
  const findings = [finding("f1", "IOS4-078", ["140", "143"], "NEGATIVE_VERIFIED"),
                    finding("f2", "PZ-001", ["SITE"], "CONFIRMED_VIOLATION")];
  const got = await decidedSubmission(db(findings), "p1", body(), null);
  assert.deepEqual(got.body.checks.map((c) => c.parameter_code), ["PZ-001"]);
  assert.equal(got.removed, 2);
  assert.equal(got.undecided, 0);
});

test("части разделённой записи решаются по своим локациям", async () => {
  // инспектор разделил находку: по 140 нарушение подтвердил, по 143 отклонил
  const findings = [
    finding("f1", "IOS4-078", ["140", "143"], "SPLIT"),
    finding("f1-a", "IOS4-078", ["140"], "CONFIRMED_VIOLATION", "INSPECTOR_SPLIT"),
    finding("f1-b", "IOS4-078", ["143"], "NEGATIVE_VERIFIED", "INSPECTOR_SPLIT"),
    finding("f2", "PZ-001", ["SITE"], "PENDING"),
  ];
  const got = await decidedSubmission(db(findings), "p1", body(), null);
  assert.deepEqual(got.body.checks.map((c) => c.location), ["140", "SITE"]);
  assert.equal(got.removed, 1);
});

test("подтверждённая гипотеза свободного поиска приходит в сдачу", async () => {
  const findings = [finding("f1", "IOS4-078", ["140", "143"], "PENDING"),
                    finding("f2", "PZ-001", ["SITE"], "PENDING"),
                    finding("h1", "FREE-AR-ROOM-AREA", ["132"], "CONFIRMED_VIOLATION"),
                    finding("h2", "FREE-AR-ROOM-AREA", ["339"], "PENDING")];
  const held = { h1: [check("FREE-AR-ROOM-AREA", "132")], h2: [check("FREE-AR-ROOM-AREA", "339")] };
  const got = await decidedSubmission(db(findings), "p1", body(), held);
  assert.equal(got.added, 1);
  assert.equal(got.body.checks.length, 4);
  assert.deepEqual(got.body.checks.at(-1).location, "132");
});

test("разделённая гипотеза приходит в сдачу подтверждёнными частями", async () => {
  // проекция лежит под номером исходной записи, решение — у частей
  const part = (id, locations, status) => ({ ...finding(id, "FREE-OV-DESIGN-ELEMENT", locations, status, "INSPECTOR_SPLIT"),
    body: { locations, parent_finding_id: "h1" } });
  const findings = [finding("h1", "FREE-OV-DESIGN-ELEMENT", ["101", "102"], "SPLIT"),
                    part("h1::split-1", ["101"], "CONFIRMED_VIOLATION"),
                    part("h1::split-2", ["102"], "NEGATIVE_VERIFIED")];
  const held = { h1: [check("FREE-OV-DESIGN-ELEMENT", "101"), check("FREE-OV-DESIGN-ELEMENT", "102")] };
  const got = await decidedSubmission(db(findings), "p1", { object_id: "OBJ", checks: [] }, held);
  assert.equal(got.added, 1);
  assert.deepEqual(got.body.checks.map((c) => c.location), ["101"]);
});

test("непринятая гипотеза в сдачу не идёт", async () => {
  const findings = [finding("h2", "FREE-AR-ROOM-AREA", ["339"], "PENDING")];
  const held = { h2: [check("FREE-AR-ROOM-AREA", "339")] };
  const got = await decidedSubmission(db(findings), "p1", { object_id: "OBJ", checks: [] }, held);
  assert.equal(got.added, 0);
  assert.equal(got.body.checks.length, 0);
});

test("локация сравнивается без оглядки на пробелы и регистр", async () => {
  const findings = [finding("f1", "ios4-078", [" 140 "], "NEGATIVE_VERIFIED")];
  const got = await decidedSubmission(db(findings), "p1",
    { object_id: "OBJ", checks: [check("IOS4-078", "140")] }, null);
  assert.equal(got.body.checks.length, 0);
  assert.equal(got.removed, 1);
});
