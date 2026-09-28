// Правила верификации по ТЗ 9.1 и 9.3: где решение разрешено и что считается кандидатом. Задача #43.
import assert from "node:assert/strict";
import test from "node:test";
import { assertDecisionAllowed, assertVerificationAllowed, isDisputed, isHypothesis } from "../dist/verification.js";

const process = (status, state = "DONE") => ({ status, processing: { state } });
const finding = (verification_status, body = {}) => ({ verification_status, body });
const candidate = finding("PENDING", { matrix_scope: "MATRIX" });
const hypothesis = finding("PENDING", { matrix_scope: "FREE_SEARCH" });

function refused(fn) {
  try {
    fn();
  } catch (error) {
    return { code: error.code, status: error.statusCode, message: error.message };
  }
  return null;
}

test("решение по кандидату принимается в READY и VERIFYING", () => {
  for (const status of ["READY", "VERIFYING"]) {
    for (const action of ["CONFIRM", "REJECT", "CLARIFY"]) {
      assert.equal(refused(() => assertDecisionAllowed(process(status), candidate, action)), null, `${status} ${action}`);
    }
  }
});

test("финализированный протокол и обработка закрывают решения", () => {
  assert.equal(refused(() => assertDecisionAllowed(process("FINALIZED"), candidate, "CONFIRM"))?.code, "PROCESS_FINALIZED");
  assert.equal(refused(() => assertDecisionAllowed(process("FINALIZED"), finding("CONFIRMED_VIOLATION"), "RESET"))?.code, "PROCESS_FINALIZED");
  assert.equal(refused(() => assertDecisionAllowed(process("VERIFYING", "RUNNING"), candidate, "CONFIRM"))?.code, "PROCESS_BUSY");
  assert.equal(refused(() => assertDecisionAllowed(process("PARSING"), candidate, "CONFIRM"))?.code, "PROTOCOL_NOT_READY");
  assert.equal(refused(() => assertDecisionAllowed(process("PENDING"), candidate, "CONFIRM"))?.code, "PROTOCOL_NOT_READY");
});

test("в COMPLETED решения не принимаются, но ошибочное можно вернуть в кандидаты", () => {
  const decided = finding("CONFIRMED_VIOLATION", { matrix_scope: "MATRIX" });
  assert.equal(refused(() => assertDecisionAllowed(process("COMPLETED"), decided, "RESET")), null);
  for (const action of ["CONFIRM", "REJECT", "CLARIFY"]) {
    const no = refused(() => assertDecisionAllowed(process("COMPLETED"), candidate, action));
    assert.equal(no?.code, "VERIFICATION_COMPLETED", action);
    assert.match(no.message, /верните запись в кандидаты/i);
  }
});

test("запись без нарушения и разделённая запись решению не подлежат", () => {
  assert.equal(refused(() => assertDecisionAllowed(process("READY"), finding("NOT_REQUIRED"), "CONFIRM"))?.code, "NOT_A_CANDIDATE");
  assert.equal(refused(() => assertDecisionAllowed(process("READY"), finding("SPLIT"), "CONFIRM"))?.code, "FINDING_SPLIT");
  assert.equal(refused(() => assertDecisionAllowed(process("READY"), candidate, "RESET"))?.code, "NOT_DECIDED");
  assert.equal(refused(() => assertDecisionAllowed(process("READY"), candidate, "APPROVE"))?.code, "UNKNOWN_ACTION");
});

test("гипотеза свободного поиска: сначала в кандидаты, потом решение", () => {
  assert.ok(isHypothesis(hypothesis));
  assert.ok(!isHypothesis(candidate));
  assert.ok(!isHypothesis(finding("PENDING", { matrix_scope: "FREE_SEARCH", promoted_at: "2026-09-17T10:00:00Z" })));
  for (const action of ["CONFIRM", "REJECT", "CLARIFY"]) {
    assert.equal(refused(() => assertDecisionAllowed(process("READY"), hypothesis, action))?.code, "HYPOTHESIS_NOT_CANDIDATE", action);
  }
  assert.equal(refused(() => assertDecisionAllowed(process("READY"), hypothesis, "PROMOTE")), null);
  const promoted = finding("PENDING", { matrix_scope: "FREE_SEARCH", promoted_at: "2026-09-17T10:00:00Z" });
  assert.equal(refused(() => assertDecisionAllowed(process("READY"), promoted, "CONFIRM")), null);
  assert.equal(refused(() => assertDecisionAllowed(process("READY"), candidate, "PROMOTE"))?.code, "NOT_A_HYPOTHESIS");
});

test("декомпозиция закрыта там же, где верификация", () => {
  assert.equal(refused(() => assertVerificationAllowed(process("FINALIZED")))?.code, "PROCESS_FINALIZED");
  assert.equal(refused(() => assertVerificationAllowed(process("READY", "QUEUED")))?.code, "PROCESS_BUSY");
  assert.equal(refused(() => assertVerificationAllowed(process("READY"))), null);
  const no = refused(() => assertVerificationAllowed(process("PARSING"), "Декомпозиция записи"));
  assert.match(no.message, /^Декомпозиция записи/);
});

test("автоматическую проверку без нарушения инспектор может оспорить (#74)", () => {
  const auto = { verification_status: "NOT_REQUIRED", violation_label: "NO_VIOLATION", body: { matrix_scope: "MATRIX" } };
  const impossible = { verification_status: "NOT_REQUIRED", violation_label: "COMPARISON_IMPOSSIBLE", body: {} };
  // запись, закрытую автоматикой, возвращают в кандидаты — в том числе после завершения верификации
  assert.equal(refused(() => assertDecisionAllowed(process("READY"), auto, "DISPUTE")), null);
  assert.equal(refused(() => assertDecisionAllowed(process("COMPLETED"), auto, "DISPUTE")), null);
  // решение по ней по-прежнему не принимается, пока она не вернулась в кандидаты
  assert.equal(refused(() => assertDecisionAllowed(process("READY"), auto, "CONFIRM"))?.code, "NOT_A_CANDIDATE");
  // «сравнение невозможно» — качество входных данных, а не вывод об отсутствии нарушения
  assert.equal(refused(() => assertDecisionAllowed(process("READY"), impossible, "DISPUTE"))?.code, "NOT_AUTO_NEGATIVE");
  // решённую инспектором запись возвращает RESET, а не оспаривание
  assert.equal(
    refused(() => assertDecisionAllowed(process("READY"), finding("NEGATIVE_VERIFIED"), "DISPUTE"))?.code,
    "NOT_AUTO_NEGATIVE",
  );
  // финализированный протокол не трогаем
  assert.equal(refused(() => assertDecisionAllowed(process("FINALIZED"), auto, "DISPUTE"))?.code, "PROCESS_FINALIZED");
});

test("возврат из автопроверки можно отменить (#74)", () => {
  const disputed = {
    verification_status: "PENDING",
    violation_label: "NO_VIOLATION",
    body: { matrix_scope: "MATRIX", disputed_at: "2026-09-19T10:00:00Z" },
  };
  assert.ok(isDisputed(disputed));
  assert.ok(!isDisputed(candidate));
  // RESET по такой записи — отмена возврата, а не снятие решения
  assert.equal(refused(() => assertDecisionAllowed(process("READY"), disputed, "RESET")), null);
  // по обычному кандидату без решения RESET по-прежнему отказывают
  assert.equal(refused(() => assertDecisionAllowed(process("READY"), candidate, "RESET"))?.code, "NOT_DECIDED");
  // решения по возвращённой записи принимаются как по кандидату
  assert.equal(refused(() => assertDecisionAllowed(process("READY"), disputed, "CONFIRM")), null);
  // и оспорить её второй раз нельзя: она уже в кандидатах
  assert.equal(refused(() => assertDecisionAllowed(process("READY"), disputed, "DISPUTE"))?.code, "NOT_AUTO_NEGATIVE");
});

test("удаляются только черновые объекты (#74)", async () => {
  const { deletionBlockers } = await import("../dist/process.js");
  const idle = { status: "READY", processing: { state: "DONE" }, finalized_at: null };
  const finalized = { status: "FINALIZED", processing: { state: "DONE" }, finalized_at: "2026-09-19T10:00:00Z" };
  const busy = { status: "PARSING", processing: { state: "RUNNING" }, finalized_at: null };
  assert.deepEqual(deletionBlockers([]), []);
  assert.deepEqual(deletionBlockers([idle, idle]), []);
  assert.match(deletionBlockers([idle, finalized])[0], /финализированных протоколов: 1/);
  assert.match(deletionBlockers([busy])[0], /идёт обработка/);
  assert.equal(deletionBlockers([finalized, busy]).length, 2);
});
