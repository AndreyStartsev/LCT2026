// Признак «модель во внешнем сервисе» по ключам воркеров: предупреждение на экране загрузки.
//   npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { externalModel } from "../dist/cache.js";

test("хоть один живой воркер с внешней моделью — предупреждать", () => {
  assert.equal(externalModel(["0", "1"]), true);
  assert.equal(externalModel(["1"]), true);
});

test("все живые воркеры читают своей моделью — не предупреждать", () => {
  assert.equal(externalModel(["0", "0"]), false);
});

test("живых воркеров нет или ключи истекли между SCAN и MGET — признак неизвестен", () => {
  assert.equal(externalModel([]), undefined);
  assert.equal(externalModel([null, null]), undefined);
  assert.equal(externalModel([null, "0"]), false);
});
