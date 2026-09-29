// Стороны сравнения записи: ожидаемое и фактическое значения и их стадии (ТЗ 9.3). По ним
// собираются карточка протокола, передача в ИАИС, набор решений и связи документов.
//   npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { sidesOf } from "../dist/sides.js";

test("обычная запись: ожидаемое — ПД, фактическое — РД, ИД третьим массивом", () => {
  const s = sidesOf({ parameter_code: "KR-054", pd_value: "B30", rd_value: "B25", body: { id_value: "B25" } });
  assert.deepEqual([s.expected, s.actual, s.built], ["B30", "B25", "B25"]);
  assert.deepEqual([s.expected_stage, s.actual_stage], ["PD", "RD"]);
  assert.deepEqual(s.by_stage, { PD: "B30", RD: "B25", ID: "B25" });
});

test("сверка схемы с допусками того же листа: фактическое — отклонение со схемы, у ПД и РД значения нет", () => {
  const s = sidesOf({
    parameter_code: "FREE-KR-002", pd_value: "допуски листа: 12 мм, 15 мм, 20 мм", rd_value: null,
    body: { id_value: "+980 мм" },
  });
  assert.deepEqual([s.expected, s.actual, s.built], ["допуски листа: 12 мм, 15 мм, 20 мм", "+980 мм", null]);
  assert.deepEqual([s.expected_stage, s.actual_stage], ["ID", "ID"]);
  assert.deepEqual([s.expected_sources, s.actual_sources], [["ID"], ["ID"]]);
  assert.deepEqual(s.by_stage, { PD: null, RD: null, ID: "+980 мм" });
});

test("запись без тела и значений: пусто, а не undefined", () => {
  const s = sidesOf({ parameter_code: "PZ-001" });
  assert.deepEqual([s.expected, s.actual, s.built], [null, null, null]);
});
