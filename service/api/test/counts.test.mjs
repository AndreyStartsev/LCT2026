// Счётчики записей и разделы для фильтра реестра объектов (#83, ТЗ модуль 7).
//   npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { countFindings, sectionOfCode } from "../dist/process.js";

test("раздел по коду параметра, свободный поиск — по второму слову", () => {
  assert.equal(sectionOfCode("PZ-001"), "PZ");
  assert.equal(sectionOfCode("IOS4-078"), "IOS4");
  assert.equal(sectionOfCode("SPZU-025"), "SPZU");
  assert.equal(sectionOfCode("FREE-AR-ROOM-AREA"), "AR");
  assert.equal(sectionOfCode("FREE-OV-SYSTEMS"), "IOS4");
  assert.equal(sectionOfCode("FREE-ID-001"), null);
  assert.equal(sectionOfCode(null), null);
});

const row = (code, status, extra = {}) => ({
  parameter_code: code, verification_status: status, violation_label: "VIOLATION_PRESENT",
  matrix_scope: null, promoted: false, n: 1, ...extra,
});

test("по разделам считаются ожидающие решения и подтверждённые", () => {
  const c = countFindings([
    row("KR-055", "PENDING"),
    row("KR-055", "CLARIFICATION_REQUIRED"),
    row("KR-058", "CONFIRMED_VIOLATION"),
    row("IOS4-078", "PENDING", { n: 7 }),
    row("AR-001", "NEGATIVE_VERIFIED"),                     // отклонено — не замечание
    row("PZ-001", "NOT_REQUIRED", { violation_label: "NO_VIOLATION" }),
  ]);
  assert.deepEqual(c.by_section, {
    KR: { candidates: 2, confirmed: 1 },
    IOS4: { candidates: 7, confirmed: 0 },
  });
  // общие счётчики не изменились от того, что строки теперь с кодом параметра
  assert.equal(c.pending, 8);
  assert.equal(c.confirmed, 1);
  assert.equal(c.candidates, 11);
});

test("гипотеза, не взятая в кандидаты, раздел не отмечает; взятая и подтверждённая — отмечает", () => {
  const c = countFindings([
    row("FREE-AR-ROOM-AREA", "PENDING", { matrix_scope: "FREE_SEARCH" }),
    row("FREE-OV-SYSTEMS", "CONFIRMED_VIOLATION", { matrix_scope: "FREE_SEARCH", promoted: true }),
  ]);
  assert.deepEqual(c.by_section, { IOS4: { candidates: 0, confirmed: 1 } });
  assert.equal(c.hypotheses, 1);
});

test("пересмотреть: решённые записи, у которых после решения изменились значения", () => {
  const c = countFindings([
    row("KR-055", "CONFIRMED_VIOLATION", { changed: true }),
    row("KR-056", "NEGATIVE_VERIFIED", { changed: true, n: 2 }),
    row("KR-057", "CLARIFICATION_REQUIRED", { changed: true }),
    row("KR-058", "PENDING", { changed: true }),                // решения нет — пересматривать нечего
    row("KR-059", "CONFIRMED_VIOLATION"),                       // значения прежние
  ]);
  assert.equal(c.revisit, 4);
});
