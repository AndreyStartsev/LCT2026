// Список моделей для способа чтения «модель» (#54): разбор настройки PIPELINE_MODEL_CHOICES.
//   npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseModels } from "../dist/config.js";

test("«id=Название» через запятую, лишние пробелы не мешают", () => {
  const models = parseModels(" qwen/qwen3-vl-30b-a3b-instruct = Qwen3-VL 30B , google/gemini-2.5-flash-lite=Gemini 2.5 Flash Lite ");
  assert.deepEqual(models, [
    { id: "qwen/qwen3-vl-30b-a3b-instruct", label: "Qwen3-VL 30B" },
    { id: "google/gemini-2.5-flash-lite", label: "Gemini 2.5 Flash Lite" },
  ]);
});

test("без названия подписью служит сам идентификатор", () => {
  assert.deepEqual(parseModels("qwen/qwen3-vl-8b-instruct"), [
    { id: "qwen/qwen3-vl-8b-instruct", label: "qwen/qwen3-vl-8b-instruct" },
  ]);
});

test("пусто и мусор дают пустой список: выбор инспектору не предлагается", () => {
  assert.deepEqual(parseModels(undefined), []);
  assert.deepEqual(parseModels(" , =Название, "), []);
});
