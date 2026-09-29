// Вход по паролю (Р-160). Пароль, набранный в другой раскладке, той же длины в символах, но другой в байтах
// UTF-8. Буферы разной длины timingSafeEqual не сравнивает, а бросает исключение, и вход отвечал 500 вместо 401.
//   npm test
import assert from "node:assert/strict";
import { test } from "node:test";

// журнал запросов в выводе теста не нужен; учётные записи читаются при загрузке модуля
process.env.LOG_LEVEL = "silent";
process.env.AUTH_USERS = "admin:admin-pass:admin,insp:пароль:inspector";
const { buildApp } = await import("../dist/app.js");

async function withApp(fn) {
  const app = await buildApp();
  await app.ready();
  try {
    await fn((login, password) => app.inject({ method: "POST", url: "/api/v1/auth/token", payload: { login, password } }));
  } finally {
    await app.close();
  }
}

function assertRejected(res, what) {
  assert.equal(res.statusCode, 401, `${what}: ${res.body}`);
  assert.equal(res.json().error.code, "INVALID_CREDENTIALS", what);
}

test("верный пароль — токен с ролью, в том числе пароль кириллицей", async () => {
  await withApp(async (login) => {
    const admin = await login("admin", "admin-pass");
    assert.equal(admin.statusCode, 200, admin.body);
    assert.equal(admin.json().role, "admin");
    const insp = await login("insp", "пароль");
    assert.equal(insp.statusCode, 200, insp.body);
    assert.equal(insp.json().role, "inspector");
  });
});

test("пароль в другой раскладке той же длины в символах — 401, а не 500", async () => {
  await withApp(async (login) => {
    // «admin-pass» в русской раскладке: 10 символов, 19 байт против 10
    assertRejected(await login("admin", "фвьшт-зфыы"), "admin-pass в русской раскладке");
    // «пароль» в английской раскладке: 6 символов, 6 байт против 12
    assertRejected(await login("insp", "gfhjkm"), "пароль в английской раскладке");
  });
});

test("неверный пароль той же длины в байтах, другой длины, неизвестный логин — 401", async () => {
  await withApp(async (login) => {
    assertRejected(await login("admin", "admin-pasS"), "другой пароль той же длины");
    // 5 символов кириллицей — те же 10 байт, что у «admin-pass»
    assertRejected(await login("admin", "фвьшт"), "кириллица той же длины в байтах");
    assertRejected(await login("admin", "admin"), "короче");
    assertRejected(await login("admin", ""), "пустой пароль");
    assertRejected(await login("nobody", "admin-pass"), "неизвестный логин");
    assertRejected(await login("nobody", ""), "неизвестный логин, пустой пароль");
  });
});
