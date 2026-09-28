// Уверенность в выводе записи (#80): уровень из предметных признаков и сами признаки.
// Тела находок — по образцу записей Тюменской-5, Новослободской и ДОО на стенде.
import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import { confidenceOf } from "../dist/confidence.js";
import { findingView } from "../dist/finding-view.js";
import { addSharedSchemas, sharedSchemas } from "../dist/schemas.js";

const layer = (value, extra = {}) => ({ value, support: 3, binding: "CLAUSE", ...extra });

test("уверенности нет, если сравнения не было или значения прочитаны не разбором правил", () => {
  assert.equal(confidenceOf({ extraction: { pd: layer("B30") } }, "COMPARISON_IMPOSSIBLE"), null);
  assert.equal(confidenceOf({}, null), null);
  // гипотеза разбора помещений: значения есть, признаков чтения нет — оценивать нечем
  assert.equal(confidenceOf({ needs_expert: true, pd_value: "13,7", extraction: { detail: "площадь изменена" } }, "VIOLATION_PRESENT"), null);
});

test("значения из текстового слоя, подтверждённые страницами, — высокая", () => {
  const got = confidenceOf({ extraction: { pd: layer("B30"), rd: layer("B30", { support: 1 }) } }, "NO_VIOLATION");
  assert.equal(got.level, "HIGH");
  assert.deepEqual(got.down, []);
  assert.ok(got.up.includes("значения из текстового слоя PDF"));
  assert.ok(got.up.includes("ПД: подтверждено на 3 стр."));
  assert.ok(!got.up.some((u) => u.startsWith("РД: подтверждено")), "одна страница — не подтверждение");
});

test("прочитанное машиной, взятое с листа, колонка по положению, соперник — средняя", () => {
  const got = confidenceOf(
    {
      extraction: {
        pd: layer("1,8", { text_source: "RECOGNIZED" }),
        rd: layer("2,1", { binding: "SHEET", column_choice: "rule", columns: ["1,5", "2,1"], support: 1,
                           alternatives: [{ value: "1,7", pages: 1 }] }),
      },
    },
    "VIOLATION_PRESENT",
  );
  assert.equal(got.level, "MEDIUM");
  assert.deepEqual(got.down, [
    "ПД: значение прочитано машиной — распознаванием или моделью",
    "РД: значение с листа чертежа — может относиться к соседнему элементу",
    "РД: шапка таблицы не распознана, колонка выбрана по положению",
    "РД: на других страницах стоит и «1,7» — 1 стр. против 1",
  ]);
  assert.ok(!got.up.includes("значения из текстового слоя PDF"));
});

test("значение не из раздела-источника — средняя; соперник слабее значения — не в счёт", () => {
  const got = confidenceOf(
    { extraction: { pd: layer("12", { alternatives: [{ value: "13", pages: 1 }] }), rd: layer("12"),
                    source_fallback: { PD: false, RD: "ПЗ" } } },
    "NO_VIOLATION",
  );
  assert.equal(got.level, "MEDIUM");
  assert.deepEqual(got.down, ["РД: значение найдено не в разделе, который каталог называет источником"]);
});

test("расхождение со слоем и похожее на ошибку чтения — низкая, причины первыми", () => {
  const got = confidenceOf(
    {
      needs_expert: true,
      extraction: {
        recognized: { stages: ["RD"], confirmation: true },
        pd: layer("B35"),
        rd: layer("B50", { text_source: "RECOGNIZED", layer_conflict: "B30",
                           doubtful: [{ value: "B50", mentions: 1, against: "B30", against_mentions: 62 }] }),
      },
    },
    "VIOLATION_PRESENT",
  );
  assert.equal(got.level, "LOW");
  assert.deepEqual(got.down.slice(0, 2), [
    "РД: прочитано машиной, а текстовый слой других страниц даёт «B30»",
    "РД: «B50» похоже на ошибку распознавания рядом с «B30»",
  ]);
  assert.ok(!got.down.includes("нарушение опирается на значение, прочитанное машиной"), "общая причина не дублирует названные");
});

test("нарушение по прочитанному машиной — низкая; «требует подтверждения» само по себе уровень не роняет", () => {
  const recognized = confidenceOf(
    { needs_expert: true, extraction: { recognized: { stages: ["PD"], confirmation: true }, pd: layer("64", { text_source: "RECOGNIZED" }), rd: layer("78") } },
    "VIOLATION_PRESENT",
  );
  assert.equal(recognized.level, "LOW");
  assert.equal(recognized.down[0], "нарушение опирается на значение, прочитанное машиной");
  // замена марки стали (KR-056): значения из слоя надёжны, решает специалист — это видно значком
  const steel = confidenceOf({ needs_expert: true, extraction: { pd: layer("C355"), rd: layer("C345") } }, "VIOLATION_PRESENT");
  assert.equal(steel.level, "HIGH");
});

test("запись для экрана несёт статус по легенде, решение специалиста и уверенность", () => {
  const view = findingView({
    id: "5d0c4f5e-1111-4222-8333-444455556666",
    finding_id: "DOO25-FREE-AR-RD-NOT-UPDATED",
    verification_status: "PENDING",
    violation_label: "VIOLATION_PRESENT",
    criticality: "Существенное (предписание)",
    body: {
      matrix_scope: "FREE_SEARCH",
      promoted_at: "2026-09-24T10:00:00Z",
      specialist: { verdict: "violation", reviewed: "24.09.2026", cases: ["B-kitchen"], note: "площади из АР" },
      extraction: { pd: layer("13,7"), rd: layer("11,8", { support: 1 }) },
    },
  });
  assert.equal(view.finding_status, "CANDIDATE");
  assert.deepEqual(view.specialist, { verdict: "violation", scope: "kind", reviewed: "24.09.2026", note: "площади из АР",
                                      cases: ["B-kitchen"] });
  assert.equal(view.confidence.level, "HIGH");
  const hypothesis = findingView({ id: "x", finding_id: "H", verification_status: "PENDING", violation_label: "VIOLATION_PRESENT",
                                   body: { matrix_scope: "FREE_SEARCH", needs_expert: true, specialist: { verdict: "maybe" } } });
  assert.equal(hypothesis.finding_status, "SUSPICION");
  assert.equal(hypothesis.specialist, null, "неизвестный вердикт не выдаётся за решение");
  assert.equal(hypothesis.confidence, null, "у гипотезы без прочитанных сторон уровня нет");
});

test("элемент проекта не найден в РД: значений нет, уровень — по доводам разбора (Р-108)", () => {
  const view = findingView({
    id: "x", finding_id: "OKT::FREE::электрощитовые::ВРУ", verification_status: "PENDING", violation_label: "VIOLATION_PRESENT",
    body: {
      matrix_scope: "FREE_SEARCH", needs_expert: true,
      specialist: { verdict: "drop", note: "не показывать; по решению пользователя — в конце таблицы с низкой уверенностью" },
      extraction: { confidence: { up: [], medium: [], low: ["элемент искали по словам проекта, в РД он может быть назван иначе",
                                                             "так было в 3 из 8 записей видов КР, АР и ЭОМ"] } },
    },
  });
  assert.equal(view.confidence.level, "LOW");
  assert.deepEqual(view.confidence.down, ["элемент искали по словам проекта, в РД он может быть назван иначе",
                                          "так было в 3 из 8 записей видов КР, АР и ЭОМ"]);
  assert.equal(view.specialist.verdict, "drop", "решение специалиста — отдельной пометкой, в уровень не подмешано");
  const bare = findingView({ id: "y", finding_id: "Z", verification_status: "PENDING", violation_label: "VIOLATION_PRESENT",
                             body: { matrix_scope: "FREE_SEARCH", extraction: { confidence: { up: [], medium: [], low: [] } } } });
  assert.equal(bare.confidence, null, "пустые доводы — оценивать нечем");
});

test("решения четвёртого круга: показывать гипотезой, не показывать и решение по записи (Р-108)", () => {
  const row = (specialist) => findingView({ id: "x", finding_id: "F", verification_status: "PENDING",
                                            violation_label: "VIOLATION_PRESENT", body: { matrix_scope: "FREE_SEARCH", specialist } });
  assert.equal(row({ verdict: "hypothesis", reviewed: "26.09.2026" }).specialist.verdict, "hypothesis");
  const act = row({ verdict: "drop", note: "оставлено: организатор отметил F-0008" }).specialist;
  assert.equal(act.verdict, "drop", "вид «не показывать», оставленный с объяснением, виден инспектору");
  assert.equal(act.scope, "kind");
  const record = row({ verdict: "no_violation", scope: "record", cases: ["R4-H04"] }).specialist;
  assert.deepEqual([record.verdict, record.scope, record.cases], ["no_violation", "record", ["R4-H04"]]);
  assert.equal(row({ verdict: "no_violation", scope: "всё" }).specialist.scope, "kind", "неизвестная область — решение по виду");
});

test("каждое поле записи названо в схеме ответа: иначе сериализатор его выбрасывает", async () => {
  const schema = sharedSchemas.find((s) => s.$id === "Finding");
  const view = findingView({ id: "x", finding_id: "F", verification_status: "PENDING", violation_label: "NO_VIOLATION", body: {} });
  assert.deepEqual(Object.keys(view).filter((k) => !(k in schema.properties)), []);

  const app = Fastify();
  addSharedSchemas(app);
  const row = {
    id: "5d0c4f5e-1111-4222-8333-444455556666",
    finding_id: "KR-055-RD",
    verification_status: "PENDING",
    violation_label: "VIOLATION_PRESENT",
    criticality: "Критическое (приостановка работ)",
    body: {
      needs_expert: true,
      id_value: "B30",
      extraction: {
        id_check: "исполнительная документация: B30",
        recognized: { stages: ["RD"], confirmation: true },
        pd: layer("B35"),
        rd: layer("B50", { text_source: "RECOGNIZED", binding: "SHEET" }),
      },
    },
  };
  app.get("/f", { schema: { response: { 200: { type: "object", properties: { findings: { type: "array", items: { $ref: "Finding#" } } } } } } },
    async () => ({ findings: [findingView(row)] }));
  const got = JSON.parse((await app.inject({ method: "GET", url: "/f" })).body).findings[0];
  assert.equal(got.needs_expert, true);
  assert.equal(got.id_value, "B30");
  assert.equal(got.id_check, "исполнительная документация: B30");
  assert.deepEqual(got.sources.rd, { text_source: "RECOGNIZED", binding: "SHEET" });
  assert.equal(got.value_read_by.rd, "RECOGNIZED");
  assert.equal(got.finding_status, "CANDIDATE");
  assert.equal(got.confidence.level, "LOW");
  assert.ok(got.confidence.down.length > 0);
  await app.close();
});

test("доводы правила (Р-104): гипотеза по триггеру — средняя, по одной привязке планом — низкая", () => {
  const door = confidenceOf(
    {
      extraction: {
        pd: { raw: "1200 мм" },
        rd: { raw: "1050 мм" },
        confidence: { up: ["порог — триггер Матрицы"], medium: ["ширина прочитана с чертежа: какая это дверь, по ответу модели не видно"], low: [] },
      },
    },
    "VIOLATION_PRESENT",
  );
  assert.equal(door.level, "MEDIUM");
  assert.ok(door.up.includes("порог — триггер Матрицы"));
  assert.ok(door.down.includes("ширина прочитана с чертежа: какая это дверь, по ответу модели не видно"));
  const finish = confidenceOf(
    { extraction: { pd: { raw: "КМ1" }, rd: { raw: "КМ2" }, confidence: { low: ["марка отделки привязана к помещению только планом потолков"] } } },
    "VIOLATION_PRESENT",
  );
  assert.equal(finish.level, "LOW");
  assert.equal(finish.down[0], "марка отделки привязана к помещению только планом потолков");
});
