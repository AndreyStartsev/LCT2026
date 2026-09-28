// Изменения между редакциями: указатель и подробности пары (#19, #81).
//   npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { pairDetails, revisionIndex } from "../dist/revisions.js";

const row = {
  pair_id: "LOC::REV::L0012-L0013",
  chain_id: "LOC:RD:ГИ:150",
  stage_group: "RD",
  old_file_id: "L0012",
  new_file_id: "L0013",
  old_revision: "изм. 1",
  new_revision: "изм. 3",
  summary: {
    mark: "ГИ", old_document: "ГИ-изм1.pdf", new_document: "ГИ-изм3.pdf", old_pages: 9, new_pages: 9,
    same: 0, changed: 9, added: 0, removed: 0, unreadable: 0, no_text: 0, looks_like_revision: true,
    registration: { introduced: [3], registered: 3, unregistered: 2, not_needed: 3, unknown: 1 },
  },
  pages: [
    { old_page: 7, new_page: 7, sheet: 6, status: "CHANGED", what: "числа: 1100 → 800", content_changed: true,
      place: { layout: "SAME_PLACE", zones_old: [[0.1, 0.1, 0.2, 0.2]], zones_new: [[0.1, 0.1, 0.2, 0.2]] },
      registration: { status: "UNREGISTERED", why: "изменение 3 не отмечено", sheet: 6, numbers: [] },
      rendered_old: true, rendered_new: true },
    { old_page: 4, new_page: 4, sheet: 3, status: "CHANGED", what: "изменились только служебные поля", content_changed: false,
      registration: { status: "NOT_NEEDED" }, rendered_old: true, rendered_new: false },
    { old_page: 2, new_page: 2, sheet: 1, status: "CHANGED", content_changed: true, registration: { status: "REGISTERED" } },
  ],
};

test("указатель: счётчики пары и страницы без подробностей", () => {
  const [pair] = revisionIndex([row]);
  assert.equal(pair.new_file_id, "L0013");
  assert.equal(pair.content_changed, 2);
  assert.equal(pair.service_only, 1);
  assert.equal(pair.unmarked, 1);
  assert.equal(pair.checked, true);
  assert.deepEqual(pair.introduced, [3]);
  assert.equal(pair.counts.changed, 9);
  assert.deepEqual(pair.pages[0], { old_page: 7, new_page: 7, sheet: 6, status: "CHANGED", content_changed: true, registration: "UNREGISTERED" });
  assert.equal(pair.pages[0].place, undefined, "рамки — только в подробностях");
});

test("пара тома проекта: отметка не проверялась", () => {
  const [pair] = revisionIndex([{ ...row, stage_group: "PD", summary: { ...row.summary, registration: null },
    pages: row.pages.map(({ registration, ...p }) => p) }]);
  assert.equal(pair.checked, false);
  assert.equal(pair.unmarked, 0);
  assert.equal(pair.pages[0].registration, null);
});

test("подробности: рамки, отметка, картинки страниц", () => {
  const pair = pairDetails(row);
  assert.deepEqual(pair.pages[0].place.zones_new, [[0.1, 0.1, 0.2, 0.2]]);
  assert.equal(pair.pages[0].registration.status, "UNREGISTERED");
  assert.equal(pair.pages[1].rendered_new, false);
  assert.equal(pair.pages[2].rendered_old, false, "нет флага — картинки нет");
  assert.deepEqual(pair.pages[2].numbers, []);
  assert.equal(pair.pages[2].old_sheet, null, "номера листа прежней редакции нет — null");
});

test("подробности: у страницы записки свой номер листа в прежней редакции", () => {
  const pair = pairDetails({ ...row, pages: [{ old_page: 34, new_page: 37, sheet: 32, old_sheet: 30, status: "CHANGED",
    content_changed: false, place: { layout: "SHIFTED", flowed_out: 37, flowed_in: 52, zones_old: [], zones_new: [] } }] });
  assert.equal(pair.pages[0].old_sheet, 30);
  assert.equal(pair.pages[0].place.flowed_in, 52, "поля места изменений проходят как есть");
});
