// Роль эксперта и страница правил (Р-134). Эксперт входит, работает с правами инспектора и видит правила;
// маршрут правил закрыт всем остальным, администратору тоже. Снимок правил воркера становится видом для
// чтения, пояснения — без служебных ссылок. База подменена: проверяются маршруты, схема ответа и вид.
//   npm test
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { mock, test } from "node:test";

process.env.LOG_LEVEL = "silent";
process.env.AUTH_USERS = "insp:insp-pass:inspector,adm:adm-pass:admin,exp:exp-pass:expert";

const queries = [];
let snapshotRow = null;
// проверки на стенде: у двух есть протокол, у третьей нет
const READY = ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"];
const NOT_READY = "33333333-3333-4333-8333-333333333333";
let testRow = null;
let resultRows = [];
let estimateRows = [];
let queuedAhead = 0;
const rows = (list) => ({ rows: list, rowCount: list.length });
const realDb = await import("../dist/db.js");
mock.module("../dist/db.js", {
  namedExports: {
    ...realDb,
    pool: {
      async query(sql, params) {
        queries.push({ sql, params });
        if (/from rule_snapshots/.test(sql)) return rows(snapshotRow ? [snapshotRow] : []);
        if (/as variant_runs/.test(sql)) return rows(estimateRows);
        if (/as ahead/.test(sql)) return rows([{ ahead: queuedAhead }]);
        if (/select distinct on \(p\.object_id\)/.test(sql)) return rows(READY.map((id) => ({ id })));
        if (/from processes p where p\.id = any/.test(sql)) return rows(params[0].filter((id) => READY.includes(id)).map((id) => ({ id })));
        if (/insert into rule_tests/.test(sql)) {
          const [id, code, variant, trace, processIds, total, createdBy] = params;
          testRow = { id, code, variant, trace, process_ids: JSON.parse(processIds), total, done: 0, status: "QUEUED",
                      error: null, created_by: createdBy, created_at: new Date("2026-09-28T12:00:00Z"), started_at: null, finished_at: null };
          return rows([testRow]);
        }
        if (/select \* from rule_tests where id/.test(sql)) return rows(testRow && testRow.id === params[0] ? [testRow] : []);
        if (/select \* from rule_tests where code/.test(sql)) return rows(testRow ? [testRow] : []);
        if (/from rule_test_results/.test(sql)) return rows(resultRows);
        if (/join objects o on o\.id = p\.object_id/.test(sql)) {
          return rows(params[0].map((id, i) => ({ id, object_id: `OBJ-${i + 1}`, name: `Объект ${i + 1}` })));
        }
        return rows([]);
      },
    },
  },
});
const published = [];
const realQueue = await import("../dist/queue.js");
mock.module("../dist/queue.js", {
  namedExports: { ...realQueue, publishRuleTest: async (id) => { published.push(id); } },
});

const { buildApp } = await import("../dist/app.js");
const { buildRulesView, plainNote, variantProblems } = await import("../dist/rules.js");

// Снимок в том виде, в каком его кладёт воркер (service/worker/rules_snapshot.py, формат 1)
const BODY = {
  format: 1,
  queues: {
    1: {
      compare_types: { relative: "нарушение, если |РД − ПД| / ПД больше порога" },
      parameters: {
        "PZ-002": {
          implemented: true,
          kind: "area",
          labels: ["общая площадь"],
          exclude: ["квартир"],
          compare: { type: "relative", threshold: 0.01 },
          basis: "Дельта общей площади > 1%.",
          note:
            "Правило специалиста по проектированию (третий круг 25.09, Р-91; #145). Нарушение — площадь в РД " +
            "другая. Разбор — pipeline/tep.py.",
        },
        "SPZU-030": {
          implemented: true,
          unit: "м",
          compare: { type: "min_absolute", threshold: 4.2 },
          documents: { PD: "(?<![А-ЯЁа-яё])(?:ПЗУ|СПОЗУ)(?![а-яё])", RD: "(?<![А-ЯЁа-яё])ГП(?=\\d|\\b)|план\\w* благоустр" },
          basis: "Ширина проезда меньше 4,2 м.",
        },
        "SPZU-034": { implemented: false, reason: "Точки подключения в корпусе — координатами.", basis: "Смещение > 0.5 м." },
      },
    },
    2: {
      compare_types: {},
      parameters: {
        "AR-040": {
          implemented: true,
          kind: "vlm_value",
          unit: "мм",
          compare: { type: "min_trigger", trigger: 1200 },
          vlm: { what: "ширина эвакуационного коридора", stage: ["PD", "RD"], sections: ["AR", "PB"], prompt: "Это лист документации." },
          hypotheses: "drawing",
          source_names: { source_pd: ["АР", "ПБ"], source_rd: ["АР"] },
          basis: "Ширина коридора менее 1.2 м.",
        },
      },
    },
    5: {
      compare_types: {},
      parameters: {
        "OOS-098": {
          implemented: false,
          out_of_scope: { kind: "EXTERNAL", reason: "Отказ по замеру 18.09.2026 (#55, #57): событие во внешней системе" },
          basis: "Работы без разрешения.",
        },
        "SM-132": {
          implemented: false,
          reason: "Сметы рабочей стадии в корпусе нет: Речников — 9 страниц.",
          inspector_note: "Правило на проверке: смета в рабочую документацию не входит.",
          basis: "Удорожание > 10%.",
        },
      },
    },
  },
  provisional: {
    1: {
      about: "Черновики правил (#95): не прод.",
      parameters: {
        "SPZU-034": {
          kind: "vlm_value",
          compare: { type: "set_decrease" },
          note: "Черновик для специалиста (#95, третий круг): По каждой сети — узел подключения.",
        },
      },
    },
  },
  catalog: [
    { parameter_id: 132, parameter_code: "SM-132", pd_section: "Раздел 12. СМ", parameter_name: "Сметная стоимость", source_pd: "ССР", source_rd: "Смета", source_id: null, trigger: "Удорожание > 10%.", criticality: "Существенное" },
    { parameter_id: 2, parameter_code: "PZ-002", pd_section: "Раздел 1. ПЗ", parameter_name: "Общая площадь здания", unit: "м²", source_pd: "ПЗ: ТЭП", source_rd: "АР: общие данные", source_id: "Технический план БТИ", trigger: "Дельта общей площади между ПД и РД (или ИД) > 1%.", criticality: "Критическое (приостановка работ)" },
    { parameter_id: 30, parameter_code: "SPZU-030", pd_section: "Раздел 2. СПЗУ", parameter_name: "Ширина проезда", unit: "м", source_pd: "ПЗУ", source_rd: "ГП", source_id: null, trigger: "Ширина проезда меньше 4,2 м.", criticality: "Критическое (приостановка работ)" },
    { parameter_id: 34, parameter_code: "SPZU-034", pd_section: "Раздел 2. СПЗУ", parameter_name: "Точки подключения", unit: "м", source_pd: "ПЗУ", source_rd: "НВК", source_id: null, trigger: "Смещение > 0.5 м.", criticality: "Существенное" },
    { parameter_id: 40, parameter_code: "AR-040", pd_section: "Раздел 3. АР", parameter_name: "Ширина коридоров", unit: "м", source_pd: "АР", source_rd: "АР", source_id: null, trigger: "Ширина коридора менее 1.2 м.", criticality: "Критическое (приостановка работ)" },
    { parameter_id: 98, parameter_code: "OOS-098", pd_section: "Раздел 8. ООС", parameter_name: "Разрешение ОСС", source_pd: null, source_rd: null, source_id: "АИС «ОСИГ»", trigger: "Работы без разрешения.", criticality: "Существенное" },
  ],
  guidance: {
    kinds: [
      { code: "FREE-KR-003", verdict: "hypothesis", submit: false, note: "Повод проверить расчёт, а не нарушение (Р-86)." },
      { code: "FREE-AR-FLAT-AREA", aspect: "площадь с летними", verdict: "violation", submit: true, note: "Лоджии учтены целиком." },
    ],
  },
  // тип правила и поля песочницы кладёт воркер (pipeline/rule_test.py)
  engines: {
    rules: {
      "PZ-002": { engine: "pattern", editable: ["compare", "exclude", "labels"] },
      "SPZU-030": { engine: "pattern", editable: ["compare"] },
      "AR-040": { engine: "llm", editable: ["compare"] },
    },
    drafts: { "SPZU-034": { engine: "llm", editable: [] } },
  },
};

test("вход эксперта: токен с ролью expert, неверный пароль — 401", async () => {
  const app = await buildApp();
  await app.ready();
  try {
    const ok = await app.inject({ method: "POST", url: "/api/v1/auth/token", payload: { login: "exp", password: "exp-pass" } });
    assert.equal(ok.statusCode, 200, ok.body);
    assert.equal(ok.json().role, "expert");
    const bad = await app.inject({ method: "POST", url: "/api/v1/auth/token", payload: { login: "exp", password: "nope" } });
    assert.equal(bad.statusCode, 401);
  } finally {
    await app.close();
  }
});

test("правила открыты только эксперту: инспектору и администратору — 403, без входа — 401", async () => {
  const app = await buildApp();
  await app.ready();
  const as = (role) => ({ authorization: `Bearer ${app.jwt.sign({ sub: role, role })}` });
  try {
    snapshotRow = { fingerprint: "f".repeat(64), body: BODY, published_at: new Date("2026-09-28T10:00:00Z") };
    assert.equal((await app.inject({ method: "GET", url: "/api/v1/rules" })).statusCode, 401);
    for (const role of ["inspector", "admin"]) {
      const denied = await app.inject({ method: "GET", url: "/api/v1/rules", headers: as(role) });
      assert.equal(denied.statusCode, 403, `${role}: ${denied.body}`);
      assert.equal(denied.json().error.code, "FORBIDDEN");
    }
    // ответ проходит проверку схемы маршрута: стенд сверяет с ней каждый ответ (VALIDATE_RESPONSES)
    const got = await app.inject({ method: "GET", url: "/api/v1/rules", headers: as("expert") });
    assert.equal(got.statusCode, 200, got.body);
    const view = got.json();
    assert.equal(view.published_at, "2026-09-28T10:00:00.000Z");
    assert.deepEqual(view.counts, { parameters: 6, active: 3, draft: 1, not_checked: 1, out_of_scope: 1 });
    assert.deepEqual(view.parameters.map((p) => p.code), ["PZ-002", "SPZU-030", "SPZU-034", "AR-040", "OOS-098", "SM-132"]);

    snapshotRow = null;
    const none = await app.inject({ method: "GET", url: "/api/v1/rules", headers: as("expert") });
    assert.equal(none.statusCode, 404);
    assert.equal(none.json().error.code, "RULES_NOT_PUBLISHED");
  } finally {
    await app.close();
  }
});

test("эксперт — с правами инспектора: уведомления инспектора, администраторское закрыто", async () => {
  const app = await buildApp();
  await app.ready();
  const as = (role) => ({ authorization: `Bearer ${app.jwt.sign({ sub: role, role })}` });
  try {
    queries.length = 0;
    const notes = await app.inject({ method: "GET", url: "/api/v1/notifications", headers: as("expert") });
    assert.equal(notes.statusCode, 200, notes.body);
    const asked = queries.find((q) => /from notifications/.test(q.sql));
    assert.deepEqual(asked.params, ["inspector"], "эксперт читает уведомления инспектора");
    const dataset = await app.inject({ method: "GET", url: "/api/v1/dataset", headers: as("expert") });
    assert.equal(dataset.statusCode, 403, "набор решений — у администратора");
  } finally {
    await app.close();
  }
});

test("снимок → вид: состояние, порог словами, документы, модель, пометка вместо заметки разработки", () => {
  const view = buildRulesView(BODY, { fingerprint: "x", published_at: "2026-09-28T10:00:00.000Z" });
  const by = Object.fromEntries(view.parameters.map((p) => [p.code, p]));

  const pz = by["PZ-002"];
  assert.equal(pz.state, "ACTIVE");
  assert.equal(pz.section, "ПЗ");
  assert.equal(pz.queue, 1);
  assert.equal(pz.trigger, "Дельта общей площади между ПД и РД (или ИД) > 1%.");
  assert.deepEqual(pz.sources, { pd: "ПЗ: ТЭП", rd: "АР: общие данные", id: "Технический план БТИ" });
  assert.equal(pz.rule.threshold, "порог 1 %");
  assert.match(pz.rule.compare, /отклоняется от проектного больше порога/);
  assert.deepEqual(pz.rule.labels, ["общая площадь"]);
  assert.deepEqual(pz.rule.exclude, ["квартир"]);
  assert.equal(pz.rule.note, "Нарушение — площадь в РД другая.", "история и путь к коду ушли, смысл остался");
  assert.equal(pz.draft, null);

  const road = by["SPZU-030"].rule;
  assert.equal(road.threshold, "порог 4,2 м");
  assert.deepEqual(road.documents, [
    { stage: "PD", names: ["ПЗУ", "СПОЗУ"], pattern: null },
    // из сложного выражения названий не выделить — показывается выражение
    { stage: "RD", names: [], pattern: "(?<![А-ЯЁа-яё])ГП(?=\\d|\\b)|план\\w* благоустр" },
  ]);

  const corridor = by["AR-040"].rule;
  assert.equal(corridor.threshold, "порог Матрицы 1200 мм");
  assert.deepEqual(corridor.model, { what: "ширина эвакуационного коридора", stages: ["PD", "RD"], sections: ["AR", "PB"], prompt: "Это лист документации." });
  assert.equal(corridor.hypothesis_only, true);
  assert.deepEqual(corridor.documents, [{ stage: "PD", names: ["АР", "ПБ"], pattern: null }, { stage: "RD", names: ["АР"], pattern: null }]);

  const draft = by["SPZU-034"];
  assert.equal(draft.state, "DRAFT");
  assert.equal(draft.rule, null, "правила прода нет — только черновик");
  assert.equal(draft.draft.note, "По каждой сети — узел подключения.");
  assert.match(draft.state_note, /гипотез/);

  const estimate = by["SM-132"];
  assert.equal(estimate.state, "NOT_CHECKED");
  assert.equal(estimate.state_note, "Правило на проверке: смета в рабочую документацию не входит.", "заметка про корпус не показывается");

  const outside = by["OOS-098"];
  assert.equal(outside.state, "OUT_OF_SCOPE");
  assert.equal(outside.state_note, "Отказ по замеру: событие во внешней системе.");

  assert.deepEqual(view.guidance, [
    { code: "FREE-KR-003", aspect: null, verdict: "hypothesis", submit: false, note: "Повод проверить расчёт, а не нарушение." },
    { code: "FREE-AR-FLAT-AREA", aspect: "площадь с летними", verdict: "violation", submit: true, note: "Лоджии учтены целиком." },
  ]);
});

test("пояснение без служебных ссылок: смысл остаётся, история уходит", () => {
  const cases = [
    [
      "Правило специалиста по проектированию (третий круг 25.09, Р-91; перенесено из черновиков, #145, Р-105). " +
        "Ширина коридоров. Четвёртый круг 26.09 (Р-108): R4-H04 — не нарушение: 1000 мм у шахт.",
      "Ширина коридоров.",
    ],
    ["Четвёртый круг 26.09 (Р-108), R4-Q-PPM-111: правило берёт рабочую стадию только из ОВ.", "Правило берёт рабочую стадию только из ОВ."],
    ["Специалист: значения в РД нет — «сравнение невозможно».", "Значения в РД нет — «сравнение невозможно»."],
    ["Порог (триггер важнее требования ПД, Р-104) — нижний.", "Порог (триггер важнее требования ПД) — нижний."],
    ["Меньше в РД — нарушение (специалист, шестой круг, R6-AR-051).", "Меньше в РД — нарушение."],
    ["Марка только через план потолков — needs_expert.", "Марка только через план потолков — «требует подтверждения»."],
    ["Разбор — pipeline/joints.py, запись строит matrix_rules.joint_findings.", null],
    ["Ширина, разбор — elements.slab_thickness (#92). Диапазон свой.", "Ширина. Диапазон свой."],
    ["Значение читает проход модели (команда `vlm`) и только подтверждённое.", "Значение читает проход модели и только подтверждённое."],
    ["ППР в корпусе нет. Шахта в корпусе 2 — отдельно.", "ППР в загруженных пакетах нет. Шахта в корпусе 2 — отдельно."],
    ["Разница в пределах округления экспликации.", "Разница в пределах округления экспликации."],
    ["Черновик (#193). λ утеплителя по видам.", "λ утеплителя по видам."],
    ["Специалист велел сравнивать класс ПД с энергопаспортом.", "Сравнивать класс ПД с энергопаспортом."],
    ["«Нарушение без обоснования»; находку пользователь 25.09 решил ставить нарушением.", "«Нарушение без обоснования»"],
    ["Эталон организатора по листу 8 берёт вторую колонку. Колонка — последняя.", "Колонка — последняя."],
    ["", null],
    [null, null],
  ];
  for (const [text, want] of cases) assert.equal(plainNote(text), want, String(text));
});

// Правила репозитория, если тест идёт из рабочей копии: в образе стенда тестов API каталога rules нет
const ROOT = new URL("../../../", import.meta.url).pathname;
const RULES = `${ROOT}rules`;
const hasRules = existsSync(`${RULES}/matrix_queue1.json`) && existsSync(`${ROOT}docs/extracted/parameter_catalog_132.jsonl`);

function repoSnapshot() {
  const json = (path) => JSON.parse(readFileSync(path, "utf-8"));
  const numbered = (dir, re) =>
    Object.fromEntries(
      readdirSync(dir)
        .map((name) => [re.exec(name)?.[1], name])
        .filter(([n]) => n)
        .map(([n, name]) => [n, json(`${dir}/${name}`)]),
    );
  return {
    format: 1,
    queues: numbered(RULES, /^matrix_queue(\d+)\.json$/),
    provisional: numbered(`${RULES}/provisional`, /^q(\d+)\.json$/),
    catalog: readFileSync(`${ROOT}docs/extracted/parameter_catalog_132.jsonl`, "utf-8")
      .split("\n")
      .filter((line) => line.trim())
      .map((line) => JSON.parse(line)),
    guidance: existsSync(`${RULES}/specialist_guidance.json`) ? json(`${RULES}/specialist_guidance.json`) : null,
  };
}

test("правила репозитория: все 132 параметра, в текстах страницы нет служебных ссылок", { skip: !hasRules && "нет rules/" }, () => {
  const body = repoSnapshot();
  const view = buildRulesView(body, { fingerprint: "repo", published_at: "2026-09-28T10:00:00.000Z" });
  assert.equal(view.parameters.length, 132);
  const c = view.counts;
  assert.equal(c.active + c.draft + c.not_checked + c.out_of_scope, 132);
  const implemented = Object.values(body.queues).flatMap((q) => Object.values(q.parameters)).filter((r) => r.implemented && !r.out_of_scope);
  assert.equal(c.active, implemented.length);

  // то, что эксперт читает словами; подписи, выражения документов и вопрос модели — сами правила, их не чистим
  const texts = view.parameters.flatMap((p) => [
    [p.code, p.state_note],
    [p.code, p.rule?.note],
    [p.code, p.rule?.compare],
    [p.code, p.draft?.note],
    [p.code, p.draft?.compare],
  ]);
  for (const g of view.guidance) texts.push([g.code, g.note]);
  const KITCHEN =
    /Р-\d|#\d|R\d+-[A-Z]|(?<!\p{L})круг(?:а|е|у|ом|и|ов)?(?!\p{L})|pipeline\/|\.py(?!\p{L})|`|\d{1,2}\.\d{2}\.\d{4}|[a-z]+_[a-z]+|организатор|эталон|пользовател|велел/u;
  const dirty = texts.filter(([, t]) => t && KITCHEN.test(t)).map(([code, t]) => `${code}: ${t.match(KITCHEN)[0]} — ${t.slice(0, 120)}`);
  assert.deepEqual(dirty, []);
});

test("тип правила и поля песочницы — из снимка воркера; старый снимок без типа — без бейджа", () => {
  const view = buildRulesView(BODY, { fingerprint: "x", published_at: "2026-09-28T10:00:00.000Z" });
  const by = Object.fromEntries(view.parameters.map((p) => [p.code, p]));
  assert.equal(by["PZ-002"].rule.engine, "pattern");
  assert.deepEqual(by["PZ-002"].rule.editable, ["compare", "exclude", "labels"]);
  assert.deepEqual(by["PZ-002"].rule.values, { threshold: 0.01 });
  assert.equal(by["AR-040"].rule.engine, "llm");
  assert.deepEqual(by["AR-040"].rule.values, { trigger: 1200 });
  assert.equal(by["SPZU-034"].draft.engine, "llm");
  const old = buildRulesView({ ...BODY, engines: undefined }, { fingerprint: "x", published_at: "2026-09-28T10:00:00.000Z" });
  assert.equal(old.parameters.find((p) => p.code === "PZ-002").rule.engine, null);
  assert.deepEqual(old.parameters.find((p) => p.code === "PZ-002").rule.editable, []);
});

test("вариант правила: меняются только разрешённые поля, числа — неотрицательные", () => {
  const view = buildRulesView(BODY, { fingerprint: "x", published_at: "2026-09-28T10:00:00.000Z" });
  const pz = view.parameters.find((p) => p.code === "PZ-002").rule;
  const road = view.parameters.find((p) => p.code === "SPZU-030").rule;
  assert.deepEqual(variantProblems(undefined, pz), []);
  assert.deepEqual(variantProblems({ compare: { threshold: 0.05 }, labels: ["общая\\s+площадь"], exclude: [] }, pz), []);
  const bad = [
    [{}, /вариант пуст/],
    [[], /объект/],
    [{ kind: "volume" }, /«kind»/],
    [{ labels: ["площадь"] }, /«labels»/, road],
    [{ compare: { type: "decrease" } }, /compare\.type/],
    [{ compare: { trigger: 1 } }, /compare\.trigger/],
    [{ compare: { threshold: -1 } }, /неотрицательное/],
    [{ compare: { threshold: "5" } }, /неотрицательное/],
    [{ labels: [] }, /хотя бы одна подпись/],
    [{ labels: ["x".repeat(401)] }, /не длиннее/],
  ];
  for (const [variant, why, logic] of bad) {
    const got = variantProblems(variant, logic ?? pz);
    assert.ok(got.some((p) => why.test(p)), `${JSON.stringify(variant)}: ${got.join("; ")}`);
  }
  // правило с разбором в коде в песочнице не прогоняется, даже если прежний снимок воркера разрешал ему порог
  const code = { ...pz, engine: "code", editable: ["compare"], values: { threshold: 0.02 } };
  assert.deepEqual(variantProblems({ compare: { threshold: 0.05 } }, code), [
    "правило с разбором в коде в песочнице не прогоняется: код в песочнице не меняют",
  ]);
  assert.deepEqual(variantProblems(undefined, code), [], "трасса правила с кодом — без варианта — разрешена");
});

test("примерное время прогона: по тёплым прогонам на проверке, без них — по страницам", async () => {
  const app = await buildApp();
  await app.ready();
  const as = (role) => ({ authorization: `Bearer ${app.jwt.sign({ sub: role, role })}` });
  estimateRows = [
    { id: READY[0], object_id: "OBJ-1", pages: "4087", trace_runs: null, variant_runs: null },
    // трасса: быстрейший из последних; вариант: единственный замер — пересборка кеша после выкладки (794 с)
    { id: READY[1], object_id: "OBJ-2", pages: 28786, trace_runs: [30, 44.5, "41.2"], variant_runs: [793.8] },
  ];
  try {
    const got = await app.inject({ method: "GET", url: "/api/v1/rules/tests/estimate", headers: as("expert") });
    assert.equal(got.statusCode, 200, got.body);
    assert.deepEqual(got.json().processes, [
      { process_id: READY[0], object_id: "OBJ-1", pages: 4087, trace_s: 7.6, variant_s: 11.7, measured: false },
      { process_id: READY[1], object_id: "OBJ-2", pages: 28786, trace_s: 30, variant_s: 73.5, measured: true },
    ]);
    const sql = queries.at(-1).sql;
    assert.match(sql, /limit 3/, "по трём последним прогонам того же рода");
    for (const role of ["inspector", "admin"]) {
      assert.equal((await app.inject({ method: "GET", url: "/api/v1/rules/tests/estimate", headers: as(role) })).statusCode, 403);
    }
  } finally {
    await app.close();
  }
});

test("пробный прогон: ставится в очередь, закрыт для остальных ролей, неверное — 422", async () => {
  const app = await buildApp();
  await app.ready();
  const as = (role) => ({ authorization: `Bearer ${app.jwt.sign({ sub: `${role}-login`, role })}` });
  snapshotRow = { fingerprint: "f".repeat(64), body: BODY, published_at: new Date("2026-09-28T10:00:00Z") };
  const post = (role, payload) => app.inject({ method: "POST", url: "/api/v1/rules/tests", headers: as(role), payload });
  try {
    for (const role of ["inspector", "admin"]) {
      assert.equal((await post(role, { code: "PZ-002" })).statusCode, 403, role);
    }
    published.length = 0;
    const all = await post("expert", { code: "PZ-002", variant: { compare: { threshold: 0.05 } } });
    assert.equal(all.statusCode, 202, all.body);
    const test = all.json();
    assert.equal(test.status, "QUEUED");
    assert.equal(test.total, READY.length, "без выбора — последняя проверка каждого объекта с протоколом");
    assert.equal(test.trace, false, "по многим объектам — без трассы");
    assert.deepEqual(test.variant, { compare: { threshold: 0.05 } });
    assert.equal(test.created_by, "expert-login");
    assert.deepEqual(published, [test.id], "задание ушло в очередь воркера");

    const one = await post("expert", { code: "AR-040", process_ids: [READY[0]] });
    assert.equal(one.statusCode, 202, one.body);
    assert.equal(one.json().trace, true, "на одном объекте — трасса");
    assert.equal(one.json().variant, null);

    const cases = [
      [{ code: "SM-132" }, "NO_MACHINE_RULE"],
      [{ code: "ZZ-999" }, "NO_MACHINE_RULE"],
      [{ code: "PZ-002", variant: { kind: "volume" } }, "BAD_VARIANT"],
      [{ code: "AR-040", variant: { labels: ["ширина"] } }, "BAD_VARIANT"],
      [{ code: "PZ-002", process_ids: [READY[0], NOT_READY] }, "PROCESS_NOT_READY"],
    ];
    for (const [payload, code] of cases) {
      const got = await post("expert", payload);
      assert.equal(got.statusCode, 422, `${JSON.stringify(payload)}: ${got.body}`);
      assert.equal(got.json().error.code, code, JSON.stringify(payload));
    }
  } finally {
    await app.close();
  }
});

test("ход пробного прогона: по объектам — итог или ожидание; список прогонов правила", async () => {
  const app = await buildApp();
  await app.ready();
  const as = (role) => ({ authorization: `Bearer ${app.jwt.sign({ sub: role, role })}` });
  snapshotRow = { fingerprint: "f".repeat(64), body: BODY, published_at: new Date("2026-09-28T10:00:00Z") };
  try {
    const created = await app.inject({ method: "POST", url: "/api/v1/rules/tests", headers: as("expert"), payload: { code: "PZ-002" } });
    const id = created.json().id;
    queuedAhead = 2;
    const waiting = await app.inject({ method: "GET", url: `/api/v1/rules/tests/${id}`, headers: as("expert") });
    assert.equal(waiting.statusCode, 200, waiting.body);
    assert.equal(waiting.json().ahead, 2, "ждущему прогону — сколько прогонов перед ним");
    testRow = { ...testRow, status: "RUNNING", done: 1, started_at: new Date("2026-09-28T12:00:05Z") };
    resultRows = [{ process_id: READY[1], object_id: "OBJ-2", status: "DONE", elapsed_s: 2.5, error: null,
                    result: { base: { findings: [] }, variant: { changes: [], same: 0 } } }];
    const got = await app.inject({ method: "GET", url: `/api/v1/rules/tests/${id}`, headers: as("expert") });
    assert.equal(got.statusCode, 200, got.body);
    const view = got.json();
    assert.equal(view.status, "RUNNING");
    assert.equal(view.ahead, 0, "идущему прогону очередь не считается");
    assert.deepEqual(view.results.map((r) => [r.process_id, r.status, r.object_name]), [
      [READY[0], "QUEUED", "Объект 1"],
      [READY[1], "DONE", "Объект 2"],
    ]);
    assert.deepEqual(view.results[1].result, { base: { findings: [] }, variant: { changes: [], same: 0 } });
    assert.equal((await app.inject({ method: "GET", url: `/api/v1/rules/tests/${id}`, headers: as("admin") })).statusCode, 403);
    const missing = await app.inject({ method: "GET", url: "/api/v1/rules/tests/44444444-4444-4444-8444-444444444444", headers: as("expert") });
    assert.equal(missing.statusCode, 404);
    const list = await app.inject({ method: "GET", url: "/api/v1/rules/tests?code=PZ-002", headers: as("expert") });
    assert.equal(list.statusCode, 200, list.body);
    assert.equal(list.json().tests[0].id, id);
  } finally {
    await app.close();
  }
});
