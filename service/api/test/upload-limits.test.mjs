// Раздельные лимиты загрузки (Р-110): в браузере — лимиты ТЗ, у загрузчика папки их нет.
// Приложение собирается без базы и хранилища, поэтому здесь проверяется то, что решается
// до них: доступ к маршруту загрузчика, отказ пакета по заявленному размеру, описание API.
//   npm test
import assert from "node:assert/strict";
import { test } from "node:test";

// журнал запросов в выводе теста не нужен; настройка читается при загрузке модуля
process.env.LOG_LEVEL = "silent";
const { buildApp } = await import("../dist/app.js");
const { limitsView, LOADER_UPLOAD_PATH } = await import("../dist/filecheck.js");

const MB = 1024 * 1024;
const BOUNDARY = "limits-test";
// пакет, заявленный больше лимита браузера (200 МБ): тело короткое, отказ — по заголовку
const HUGE = {
  "content-type": `multipart/form-data; boundary=${BOUNDARY}`,
  "content-length": String(300 * MB),
};
const BODY = `--${BOUNDARY}\r\nContent-Disposition: form-data; name="final_batch"\r\n\r\nfalse\r\n--${BOUNDARY}--\r\n`;

async function withApp(fn) {
  const app = await buildApp();
  await app.ready();
  try {
    await fn(app, (role) => ({ authorization: `Bearer ${app.jwt.sign({ sub: role, role })}` }));
  } finally {
    await app.close();
  }
}

test("лимиты браузера прежние, маршрут загрузчика объявлен в limits", () => {
  const limits = limitsView();
  assert.equal(limits.max_file_mb, 50);
  assert.equal(limits.max_package_mb, 200);
  assert.equal(limits.loader_path, "/api/v1/documents/bulk");
  assert.equal(LOADER_UPLOAD_PATH, limits.loader_path);
});

test("маршрут загрузчика — только роль admin", async () => {
  await withApp(async (app, auth) => {
    const anonymous = await app.inject({ method: "POST", url: LOADER_UPLOAD_PATH, payload: {} });
    assert.equal(anonymous.statusCode, 401);
    const inspector = await app.inject({ method: "POST", url: LOADER_UPLOAD_PATH, headers: auth("inspector"), payload: {} });
    assert.equal(inspector.statusCode, 403);
    assert.equal(inspector.json().error.code, "FORBIDDEN");
    // admin доходит до приёма: без multipart — 400, а не отказ в доступе
    const admin = await app.inject({ method: "POST", url: LOADER_UPLOAD_PATH, headers: auth("admin"), payload: {} });
    assert.equal(admin.statusCode, 400);
    assert.equal(admin.json().error.code, "MULTIPART_REQUIRED");
  });
});

test("пакет больше 200 МБ в браузере — 413 по заголовку, у загрузчика такого отказа нет", async () => {
  await withApp(async (app, auth) => {
    for (const role of ["inspector", "admin"]) {
      const browser = await app.inject({
        method: "POST", url: "/api/v1/documents/upload", headers: { ...auth(role), ...HUGE }, payload: BODY,
      });
      assert.equal(browser.statusCode, 413, `браузер, роль ${role}`);
      assert.equal(browser.json().error.code, "PACKAGE_TOO_LARGE");
    }
    // без базы приём загрузчика дальше не пройдёт, но лимит пакета его не останавливает
    const loader = await app.inject({
      method: "POST", url: LOADER_UPLOAD_PATH, headers: { ...auth("admin"), ...HUGE }, payload: BODY,
    });
    assert.notEqual(loader.statusCode, 413);
    assert.notEqual(loader.json().error?.code, "PACKAGE_TOO_LARGE");
  });
});

test("в описании API оба маршрута: загрузка в браузере и загрузчик папки", async () => {
  await withApp(async (app) => {
    const spec = app.swagger();
    const upload = spec.paths["/api/v1/documents/upload"].post;
    const loader = spec.paths[LOADER_UPLOAD_PATH].post;
    assert.match(upload.description, /Лимиты ТЗ для загрузки в браузере/);
    assert.match(loader.summary, /без лимитов размера/);
    assert.match(loader.description, /роль admin/);
    for (const op of [upload, loader]) {
      assert.ok(op.requestBody.content["multipart/form-data"].schema.properties.files, "тело multipart описано");
      assert.ok(op.responses["202"], "ответ 202 описан");
    }
    assert.equal(spec.components.schemas.Limits.properties.loader_path.type, "string", "loader_path в схеме Limits");
  });
});
