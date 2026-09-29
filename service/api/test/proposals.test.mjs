// Предложения правки правила из песочницы (#224, Р-164). Эксперт предлагает вариант из законченного
// прогона — с разницей по объектам снимком; администратор (разработчик) отмечает статус; правка
// выгружается документом RFC 6902 к файлу правил. База подменена: проверяются маршруты, схема ответа,
// отказы и журнал аудита.
//   npm test
import assert from "node:assert/strict";
import { mock, test } from "node:test";

process.env.LOG_LEVEL = "silent";
process.env.AUTH_USERS = "insp:insp-pass:inspector,adm:adm-pass:admin,exp:exp-pass:expert";

const rows = (list) => ({ rows: list, rowCount: list.length });
const PID = ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"];
const TEST = {
  done: "aaaaaaaa-aaaa-4aaa-8aaa-000000000001",
  trace: "aaaaaaaa-aaaa-4aaa-8aaa-000000000002",
  running: "aaaaaaaa-aaaa-4aaa-8aaa-000000000003",
  stale: "aaaaaaaa-aaaa-4aaa-8aaa-000000000004",
  draft: "aaaaaaaa-aaaa-4aaa-8aaa-000000000005",
};

// Снимок в том виде, в каком его кладёт воркер (service/worker/rules_snapshot.py, формат 1)
const PZ002 = {
  kind: "area",
  labels: ["общая площадь здания"],
  exclude: ["квартир"],
  compare: { type: "relative", threshold: 0.01 },
  implemented: true,
};
const AR099 = { kind: "vlm_value", vlm: { what: "ширина" }, compare: { type: "min_trigger", trigger: 1200 } };
const BODY = {
  format: 1,
  queues: {
    1: { parameters: { "PZ-002": PZ002, "KR-067": { kind: "material_takeoff", compare: { type: "keyed", threshold: 0.02 }, implemented: true } } },
  },
  provisional: { 3: { parameters: { "AR-099": AR099 } } },
  catalog: [
    { parameter_id: 2, parameter_code: "PZ-002", pd_section: "Раздел 1. ПЗ", parameter_name: "Общая площадь здания" },
    { parameter_id: 67, parameter_code: "KR-067", pd_section: "Раздел 4. КР", parameter_name: "Объём бетона" },
    { parameter_id: 99, parameter_code: "AR-099", pd_section: "Раздел 3. АР", parameter_name: "Ширина проходов" },
  ],
  guidance: { kinds: [] },
  engines: {
    rules: {
      "PZ-002": { engine: "pattern", editable: ["compare", "exclude", "labels"] },
      "KR-067": { engine: "code", editable: [] },
    },
    drafts: { "AR-099": { engine: "llm", editable: ["compare"] } },
  },
};

const { ruleDigest } = await import("../dist/rules.js");
const change = (fid, before, after, decision = null) => ({
  finding_id: fid,
  change: "changed",
  before: { finding_id: fid, violation_label: before, locations: [], pd_value: "100 м²", rd_value: "102 м²" },
  after: { finding_id: fid, violation_label: after, locations: [], pd_value: "100 м²", rd_value: "102 м²" },
  decision,
});
const tests = {
  [TEST.done]: { id: TEST.done, code: "PZ-002", variant: { compare: { threshold: 0.05 }, labels: ["общая\\s+площадь"] }, status: "DONE",
                 total: 3, rule_digest: ruleDigest(PZ002) },
  [TEST.trace]: { id: TEST.trace, code: "PZ-002", variant: null, status: "DONE", total: 1, rule_digest: ruleDigest(PZ002) },
  [TEST.running]: { id: TEST.running, code: "PZ-002", variant: { compare: { threshold: 0.05 } }, status: "RUNNING", total: 3 },
  [TEST.stale]: { id: TEST.stale, code: "PZ-002", variant: { compare: { threshold: 0.05 } }, status: "DONE", total: 1,
                  rule_digest: ruleDigest({ ...PZ002, labels: ["площадь"] }) },
  [TEST.draft]: { id: TEST.draft, code: "AR-099", variant: { compare: { trigger: 1500 } }, status: "DONE", total: 1, rule_digest: null },
};
const results = {
  [TEST.done]: [
    { process_id: PID[0], object_id: "OBJ-A", object_name: "Алтуфьевское", status: "DONE", error: null,
      result: { variant: { changes: [change("OBJ-A::PZ-002", "VIOLATION_PRESENT", "NO_VIOLATION", "CONFIRMED_VIOLATION")], same: 0 } } },
    { process_id: PID[1], object_id: "OBJ-B", object_name: "Новослободская", status: "DONE", error: null,
      result: { variant: { changes: [], same: 1 } } },
    { process_id: PID[2], object_id: "OBJ-C", object_name: "Полярная", status: "FAILED", error: "сбой разбора", result: null },
  ],
  [TEST.draft]: [
    { process_id: PID[0], object_id: "OBJ-A", object_name: "Алтуфьевское", status: "DONE", error: null,
      result: { variant: { changes: [{ ...change("OBJ-A::AR-099", "NO_VIOLATION", "VIOLATION_PRESENT"), change: "added" }], same: 0 } } },
  ],
};
const proposals = new Map();
const audits = [];
let snapshot = { fingerprint: "f".repeat(64), body: BODY, published_at: new Date("2026-09-29T08:00:00Z") };

async function query(sql, params = []) {
  if (/from rule_snapshots/.test(sql)) return rows(snapshot ? [snapshot] : []);
  if (/select \* from rule_tests where id/.test(sql)) return rows(tests[params[0]] ? [tests[params[0]]] : []);
  if (/from rule_test_results r/.test(sql)) return rows(results[params[0]] ?? []);
  if (/insert into rule_proposals/.test(sql)) {
    const [id, code, queue, draft, file, variant, rule, fingerprint, testId, diff, comment, createdBy] = params;
    if ([...proposals.values()].some((p) => p.test_id === testId)) throw Object.assign(new Error("duplicate"), { code: "23505" });
    const row = { id, code, queue, draft, file, variant, rule, fingerprint, test_id: testId, diff: JSON.parse(diff), comment,
                  status: "NEW", status_reason: null, status_by: null, status_at: null, created_by: createdBy,
                  created_at: new Date("2026-09-29T09:00:00Z") };
    proposals.set(id, row);
    return rows([row]);
  }
  if (/select id from rule_proposals where test_id/.test(sql)) {
    return rows([...proposals.values()].filter((p) => p.test_id === params[0]).map((p) => ({ id: p.id })));
  }
  if (/insert into audit_log/.test(sql)) {
    audits.push({ user: params[0], action: params[1], details: JSON.parse(params[4]) });
    return rows([]);
  }
  if (/from rule_proposals\s+where \(\$1::text is null/.test(sql)) {
    const [code, status] = params;
    const list = [...proposals.values()]
      .filter((p) => (code === null || p.code === code) && (status === null || p.status === status))
      .map((p) => ({ ...p, totals: p.diff.totals }));
    return rows(list.reverse());
  }
  if (/select \* from rule_proposals where id/.test(sql)) return rows(proposals.has(params[0]) ? [proposals.get(params[0])] : []);
  if (/update rule_proposals set status/.test(sql)) {
    const p = proposals.get(params[0]);
    if (!p) return rows([]);
    Object.assign(p, { status: params[1], status_reason: params[2], status_by: params[3], status_at: new Date("2026-09-29T10:00:00Z") });
    return rows([p]);
  }
  return rows([]);
}
const realDb = await import("../dist/db.js");
mock.module("../dist/db.js", {
  namedExports: { ...realDb, pool: { query }, withTransaction: async (fn) => fn({ query }) },
});
const realQueue = await import("../dist/queue.js");
mock.module("../dist/queue.js", { namedExports: { ...realQueue, publishRuleTest: async () => {} } });
const { buildApp } = await import("../dist/app.js");

async function withApp(fn) {
  const app = await buildApp();
  await app.ready();
  const as = (role) => ({ authorization: `Bearer ${app.jwt.sign({ sub: `${role}-login`, role })}` });
  try {
    await fn(app, as);
  } finally {
    await app.close();
  }
}

test("предложение из законченного варианта: разница по объектам снимком, файл правил, журнал аудита", async () => {
  proposals.clear();
  audits.length = 0;
  await withApp(async (app, as) => {
    const post = (role, payload) => app.inject({ method: "POST", url: "/api/v1/rules/proposals", headers: as(role), payload });
    for (const role of ["inspector", "admin"]) assert.equal((await post(role, { test_id: TEST.done })).statusCode, 403, role);
    const got = await post("expert", { test_id: TEST.done, comment: "  подпись шире: «общая площадь» без «здания»  " });
    assert.equal(got.statusCode, 201, got.body);
    const p = got.json();
    assert.equal(p.status, "NEW");
    assert.equal(p.code, "PZ-002");
    assert.equal(p.file, "rules/matrix_queue1.json");
    assert.equal(p.draft, false);
    assert.equal(p.comment, "подпись шире: «общая площадь» без «здания»");
    assert.equal(p.created_by, "expert-login");
    assert.deepEqual(p.variant, { compare: { threshold: 0.05 }, labels: ["общая\\s+площадь"] });
    assert.deepEqual(p.rule, PZ002, "правило из файла на момент предложения");
    assert.deepEqual(p.totals, { objects: 3, done: 2, failed: 1, changed_objects: 1, changes: 1, added: 0, removed: 0, changed: 1, disputed: 1 });
    assert.deepEqual(p.objects.map((o) => [o.object_name, o.status, o.changes.length]), [
      ["Алтуфьевское", "DONE", 1],
      ["Полярная", "FAILED", 0],
    ], "объекты с переменами и несчитанные; объект без перемен — только в итогах");
    assert.deepEqual(audits.map((a) => [a.action, a.user, a.details.code]), [["RULE_PROPOSAL_CREATE", "expert-login", "PZ-002"]]);

    const again = await post("expert", { test_id: TEST.done });
    assert.equal(again.statusCode, 409);
    assert.equal(again.json().error.code, "PROPOSAL_EXISTS");
    assert.equal(again.json().error.details.proposal_id, p.id);

    const draft = await post("expert", { test_id: TEST.draft });
    assert.equal(draft.statusCode, 201, draft.body);
    assert.equal(draft.json().file, "rules/provisional/q3.json", "правка черновика — к файлу черновиков его очереди");
    assert.equal(draft.json().draft, true);
    assert.equal(draft.json().totals.added, 1);
  });
});

test("предложить нельзя: трасса, идущий прогон, правило изменилось, нет прогона, неверное тело", async () => {
  await withApp(async (app, as) => {
    const post = (payload) => app.inject({ method: "POST", url: "/api/v1/rules/proposals", headers: as("expert"), payload });
    const cases = [
      [{ test_id: TEST.trace }, 422, "NOT_A_VARIANT"],
      [{ test_id: TEST.running }, 422, "TEST_NOT_DONE"],
      [{ test_id: TEST.stale }, 409, "RULE_CHANGED"],
      [{ test_id: "bbbbbbbb-bbbb-4bbb-8bbb-000000000000" }, 404, "NOT_FOUND"],
      [{ test_id: "не-uuid" }, 400, "VALIDATION_ERROR"],
      [{ test_id: TEST.done, extra: 1 }, 400, "VALIDATION_ERROR"],
    ];
    for (const [payload, status, code] of cases) {
      const got = await post(payload);
      assert.equal(got.statusCode, status, `${JSON.stringify(payload)}: ${got.body}`);
      assert.equal(got.json().error.code, code, JSON.stringify(payload));
    }
    // правило с разбором в коде в песочницу не идёт: и предложение из его прогона не примется
    tests["aaaaaaaa-aaaa-4aaa-8aaa-000000000009"] = {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-000000000009", code: "KR-067", variant: { compare: { threshold: 0.05 } }, status: "DONE", total: 1,
    };
    const code = await post({ test_id: "aaaaaaaa-aaaa-4aaa-8aaa-000000000009" });
    assert.equal(code.statusCode, 422, code.body);
    assert.equal(code.json().error.code, "BAD_VARIANT");
  });
});

test("список и карточка: эксперту и администратору, инспектору — нет; отбор по параметру и статусу", async () => {
  await withApp(async (app, as) => {
    const get = (role, url) => app.inject({ method: "GET", url, headers: as(role) });
    assert.equal((await get("inspector", "/api/v1/rules/proposals")).statusCode, 403);
    for (const role of ["expert", "admin"]) {
      const all = await get(role, "/api/v1/rules/proposals");
      assert.equal(all.statusCode, 200, all.body);
      assert.equal(all.json().proposals.length, 2, role);
      assert.equal(all.json().proposals[0].objects, undefined, "в списке — итоги, без перемен по объектам");
    }
    const byCode = await get("expert", "/api/v1/rules/proposals?code=AR-099");
    assert.deepEqual(byCode.json().proposals.map((p) => p.code), ["AR-099"]);
    assert.equal((await get("expert", "/api/v1/rules/proposals?status=APPLIED")).json().proposals.length, 0);
    assert.equal((await get("expert", "/api/v1/rules/proposals?status=LOST")).statusCode, 400);
    const id = byCode.json().proposals[0].id;
    const one = await get("admin", `/api/v1/rules/proposals/${id}`);
    assert.equal(one.statusCode, 200, one.body);
    assert.equal(one.json().objects.length, 1);
    assert.equal((await get("expert", "/api/v1/rules/proposals/cccccccc-cccc-4ccc-8ccc-000000000000")).statusCode, 404);
  });
});

test("правка файла правил: RFC 6902 — проверка прежнего значения и замена, имя файла выгрузки", async () => {
  await withApp(async (app, as) => {
    const list = (await app.inject({ method: "GET", url: "/api/v1/rules/proposals?code=PZ-002", headers: as("expert") })).json();
    const id = list.proposals[0].id;
    const got = await app.inject({ method: "GET", url: `/api/v1/rules/proposals/${id}/patch`, headers: as("admin") });
    assert.equal(got.statusCode, 200, got.body);
    assert.match(got.headers["content-disposition"], /attachment; filename="rule-proposal-PZ-002-2026-09-29-[0-9a-f]{8}\.json"/);
    const doc = got.json();
    assert.equal(doc.file, "rules/matrix_queue1.json");
    assert.deepEqual(doc.patch, [
      { op: "test", path: "/parameters/PZ-002/compare/threshold", value: 0.01 },
      { op: "replace", path: "/parameters/PZ-002/compare/threshold", value: 0.05 },
      { op: "test", path: "/parameters/PZ-002/labels", value: ["общая площадь здания"] },
      { op: "replace", path: "/parameters/PZ-002/labels", value: ["общая\\s+площадь"] },
    ]);
    assert.equal(doc.proposal.code, "PZ-002");
    assert.equal(doc.totals.changes, 1);
    assert.equal((await app.inject({ method: "GET", url: `/api/v1/rules/proposals/${id}/patch`, headers: as("inspector") })).statusCode, 403);
  });
});

test("статус ставит администратор: отклонение — с причиной, перенос — с тем, что сделано; всё в журнал", async () => {
  audits.length = 0;
  await withApp(async (app, as) => {
    const id = [...proposals.values()].find((p) => p.code === "PZ-002").id;
    const set = (role, payload) =>
      app.inject({ method: "POST", url: `/api/v1/rules/proposals/${id}/status`, headers: as(role), payload });
    assert.equal((await set("expert", { status: "APPLIED" })).statusCode, 403, "эксперт статус не ставит");
    const noReason = await set("admin", { status: "REJECTED", reason: "   " });
    assert.equal(noReason.statusCode, 422);
    assert.equal(noReason.json().error.code, "REASON_REQUIRED");
    const rejected = await set("admin", { status: "REJECTED", reason: "гейт качества: −2 записи на Речникове" });
    assert.equal(rejected.statusCode, 200, rejected.body);
    assert.equal(rejected.json().status, "REJECTED");
    assert.equal(rejected.json().status_reason, "гейт качества: −2 записи на Речникове");
    assert.equal(rejected.json().status_by, "admin-login");
    const applied = await set("admin", { status: "APPLIED", reason: "перенесено в правила" });
    assert.equal(applied.json().status, "APPLIED");
    assert.equal((await set("admin", { status: "DONE" })).statusCode, 400);
    const missing = await app.inject({ method: "POST", url: "/api/v1/rules/proposals/dddddddd-dddd-4ddd-8ddd-000000000000/status",
                                       headers: as("admin"), payload: { status: "APPLIED" } });
    assert.equal(missing.statusCode, 404);
    assert.deepEqual(audits.map((a) => [a.action, a.details.status]), [["RULE_PROPOSAL_STATUS", "REJECTED"], ["RULE_PROPOSAL_STATUS", "APPLIED"]]);
  });
});
