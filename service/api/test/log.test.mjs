// Журнал обработки объекта (#83): что в нём видно и чего в нём не должно быть.
//   npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { logView } from "../dist/log.js";

const process = {
  id: "11111111-2222-3333-4444-555555555555",
  object_id: "OBJ-1",
  status: "VERIFYING",
  processing: { state: "DONE", step: "protocol", last_step_seconds: 12 },
};

const protocols = [
  {
    version: 2,
    created_at: "2026-09-18T12:29:00.000Z",
    status: "READY",
    report: {
      reading_mode: "tesseract", model_name: null, ocr: true, model: false,
      pages_read: true, findings: 39, checks: 40, labels: { VIOLATION_PRESENT: 9 },
      recompute: { full: false, documents_read: 4, documents_total: 64, carried_over: 21, recomputed: 18 },
      changes: { added: [], changed: ["a", "b", "c"], removed: ["d"], decided_changed: [] },
      readiness: {
        pages: 4609, pages_without_text: 0, pages_low_quality: 95, stage_unknown: 0, section_other: 17,
        read_seconds: 14400, model_calls: 0, by_text_source: { UNION: 4000 },
        // поля, которых в журнале быть не должно: они есть в протоколе и только шумят
        documents: [{ file_id: "F0001" }], notes_internal: "x",
      },
    },
  },
  { version: 1, created_at: "2026-09-18T09:00:00.000Z", status: "READY", report: {} },
];

const notifications = [
  { id: 7, role: "inspector", level: "WARNING", category: "QUALITY", message: "Контроль качества чтения: чтение отметило низкое качество на 95 страницах", created_at: "2026-09-18T12:29:01.000Z" },
  { id: 6, role: "inspector", level: "INFO", category: "INFO", message: "Протокол версии 2 сформирован", created_at: "2026-09-18T12:29:02.000Z" },
  { id: 5, role: "admin", level: "ERROR", message: "Обработка остановлена", created_at: "2026-09-17T10:00:00.000Z" },
];

const rejected = [{ reject_code: "FILE_TOO_LARGE", reject_message: "Файл больше 100 МБ", count: 3 }];

test("журнал собирает прогоны от свежего к старому", () => {
  const log = logView(process, protocols, notifications, rejected);
  assert.equal(log.process_id, process.id);
  assert.deepEqual(log.runs.map((r) => r.version), [2, 1]);
  assert.equal(log.runs[0].reading_mode, "tesseract");
  assert.equal(log.runs[0].pages, 4609);
  assert.equal(log.runs[0].readiness.pages_low_quality, 95);
});

test("изменения версии идут числами, а не списками", () => {
  const log = logView(process, protocols, notifications, rejected);
  assert.deepEqual(log.runs[0].changes, { added: 0, changed: 3, removed: 1, decided_changed: 0 });
  assert.equal(log.runs[1].changes, null);
});

test("из готовности берутся только числа для человека", () => {
  const log = logView(process, protocols, notifications, rejected);
  const ready = log.runs[0].readiness;
  assert.equal(ready.documents, undefined);
  assert.equal(ready.notes_internal, undefined);
  assert.equal(ready.section_other, 17);
});

test("наблюдения о качестве видны в журнале, роль и вид сохранены", () => {
  const log = logView(process, protocols, notifications, rejected);
  const quality = log.notifications.filter((n) => n.category === "QUALITY");
  assert.equal(quality.length, 1);
  assert.match(quality[0].message, /низкое качество на 95 страницах/);
  // у старых записей вида нет — считаем их событием без действия
  assert.equal(log.notifications.find((n) => n.id === 5).category, "INFO");
  assert.equal(log.notifications.find((n) => n.id === 5).role, "admin");
});

test("отклонённые файлы — по причинам", () => {
  const log = logView(process, protocols, notifications, rejected);
  assert.deepEqual(log.rejected_files, [{ code: "FILE_TOO_LARGE", count: 3, message: "Файл больше 100 МБ" }]);
});

test("пустой объект: журнал не падает", () => {
  const log = logView({ id: "x", object_id: "OBJ-2", status: "PENDING" }, [], [], []);
  assert.deepEqual(log.runs, []);
  assert.deepEqual(log.notifications, []);
  assert.deepEqual(log.processing, { state: "IDLE" });
});
