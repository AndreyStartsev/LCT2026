// Приём файла больше лимита браузера (Р-110): маршрут загрузчика принимает его целиком,
// загрузка в браузере отклоняет FILE_TOO_LARGE. Хранилище, база и очередь подменены:
// проверяется разбор multipart маршрутом, а не MinIO и PostgreSQL.
//   npm test
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mock, test } from "node:test";

process.env.LOG_LEVEL = "silent";
const MB = 1024 * 1024;

// что увидело хранилище: размер и хеш каждого принятого на хранение файла
const stored = [];
const realStorage = await import("../dist/storage.js");
mock.module("../dist/storage.js", {
  namedExports: {
    ...realStorage,
    async storeTemporary(stream) {
      const hash = createHash("sha256");
      let size = 0;
      let head = Buffer.alloc(0);
      let tail = Buffer.alloc(0);
      for await (const chunk of stream) {
        hash.update(chunk);
        size += chunk.length;
        if (head.length < 1024) head = Buffer.concat([head, chunk.subarray(0, 1024 - head.length)]);
        tail = Buffer.concat([tail, chunk]).subarray(-2048);
      }
      const item = { tmpKey: `tmp/${stored.length}`, sha256: hash.digest("hex"), size, head, tail };
      stored.push(item);
      return item;
    },
    async promote() {
      return true;
    },
    async discard() {},
  },
});
const realDb = await import("../dist/db.js");
const client = { query: async () => ({ rows: [], rowCount: 0 }) };
mock.module("../dist/db.js", {
  namedExports: { ...realDb, withTransaction: async (fn) => fn(client), audit: async () => {} },
});
const realQueue = await import("../dist/queue.js");
mock.module("../dist/queue.js", { namedExports: { ...realQueue, publish: async () => {} } });

const { buildApp } = await import("../dist/app.js");
const { LOADER_UPLOAD_PATH } = await import("../dist/filecheck.js");

/** Пакет из одного PDF заданного размера: заголовок и %%EOF на месте, внутри нули. */
function multipart(size, relativePath) {
  const boundary = "bulk-test";
  const pdf = Buffer.alloc(size);
  pdf.write("%PDF-1.7\n", 0);
  pdf.write("\n%%EOF\n", size - 7);
  const head = Buffer.from(
    `--${boundary}\r\nContent-Disposition: form-data; name="object_id"\r\n\r\nOBJ-BULK-TEST\r\n` +
      `--${boundary}\r\nContent-Disposition: form-data; name="relative_path"\r\n\r\n${relativePath}\r\n` +
      `--${boundary}\r\nContent-Disposition: form-data; name="files"; filename="big.pdf"\r\n` +
      "Content-Type: application/pdf\r\n\r\n",
  );
  const tail = Buffer.from(`\r\n--${boundary}--\r\n`);
  const sha256 = createHash("sha256").update(pdf).digest("hex");
  return { body: Buffer.concat([head, pdf, tail]), type: `multipart/form-data; boundary=${boundary}`, sha256 };
}

test("файл 60 МБ: загрузчик принимает целиком, браузер отклоняет FILE_TOO_LARGE", async () => {
  const app = await buildApp();
  await app.ready();
  const auth = (role) => ({ authorization: `Bearer ${app.jwt.sign({ sub: role, role })}` });
  const path = "ПД/2 Схема планировочной организации ЗУ/ИЗМ ПО ЗАМЕЧАНИЯМ ПЗУ.pdf";
  const pkg = multipart(60 * MB, path);
  try {
    stored.length = 0;
    const loader = await app.inject({
      method: "POST", url: LOADER_UPLOAD_PATH, headers: { ...auth("admin"), "content-type": pkg.type }, payload: pkg.body,
    });
    assert.equal(loader.statusCode, 202, loader.body);
    const got = loader.json();
    assert.deepEqual(got.rejected, []);
    assert.deepEqual(got.accepted, [{ relative_path: path, sha256: pkg.sha256, size_bytes: 60 * MB }]);
    assert.equal(stored[0].size, 60 * MB, "хранилище получило файл целиком");

    stored.length = 0;
    const browser = await app.inject({
      method: "POST", url: "/api/v1/documents/upload", headers: { ...auth("admin"), "content-type": pkg.type }, payload: pkg.body,
    });
    assert.equal(browser.statusCode, 422, browser.body);
    const error = browser.json().error;
    assert.equal(error.code, "NO_ACCEPTED_FILES");
    assert.deepEqual(error.details.rejected.map((r) => [r.relative_path, r.code]), [[path, "FILE_TOO_LARGE"]]);
    assert.equal(stored[0].size, 50 * MB, "браузерный лимит обрезал поток на 50 МБ");
  } finally {
    await app.close();
  }
});
