import { createHash, randomUUID } from "node:crypto";
import { Transform, type Readable, type TransformCallback } from "node:stream";
import { pipeline } from "node:stream/promises";
import * as Minio from "minio";
import { config } from "./config.js";

let client: Minio.Client | null = null;

// Клиент создаётся при первом обращении: выгрузке OpenAPI ключ хранилища не нужен.
function getClient(): Minio.Client {
  if (!client) {
    client = new Minio.Client({
      endPoint: config.s3.endPoint,
      port: config.s3.port,
      useSSL: config.s3.useSSL,
      accessKey: config.s3.accessKey,
      secretKey: config.s3.secretKey(),
    });
  }
  return client;
}

export const minio = new Proxy({} as Minio.Client, {
  get(_target, property) {
    const target = getClient();
    const value = Reflect.get(target, property, target);
    return typeof value === "function" ? value.bind(target) : value;
  },
});

const bucket = config.s3.bucket;

export async function ensureBucket(): Promise<void> {
  if (!(await minio.bucketExists(bucket))) {
    await minio.makeBucket(bucket);
  }
}

// Содержимое хранится по SHA-256: один и тот же файл, загруженный в разные
// процессы или дважды, лежит в хранилище один раз. Кеш разбора конвейера
// адресован так же, поэтому повторная проверка того же файла не читает его заново.
export function blobKey(sha256: string): string {
  return `blobs/${sha256.slice(0, 2)}/${sha256}`;
}

const HEAD_BYTES = 1024;
const TAIL_BYTES = 2048;

/** Считает SHA-256 и размер и запоминает начало и конец потока для проверки формата. */
class Inspecting extends Transform {
  readonly hash = createHash("sha256");
  size = 0;
  head = Buffer.alloc(0);
  tail = Buffer.alloc(0);

  override _transform(chunk: Buffer, _enc: BufferEncoding, done: TransformCallback): void {
    this.hash.update(chunk);
    this.size += chunk.length;
    if (this.head.length < HEAD_BYTES) {
      this.head = Buffer.concat([this.head, chunk.subarray(0, HEAD_BYTES - this.head.length)]);
    }
    const joined = Buffer.concat([this.tail, chunk]);
    this.tail = joined.subarray(Math.max(0, joined.length - TAIL_BYTES));
    done(null, chunk);
  }
}

export interface StoredUpload {
  tmpKey: string;
  sha256: string;
  size: number;
  head: Buffer;
  tail: Buffer;
}

/** Пишет поток во временный объект, попутно считая хеш. */
export async function storeTemporary(stream: Readable): Promise<StoredUpload> {
  const tmpKey = `tmp/${randomUUID()}`;
  const probe = new Inspecting();
  const upload = minio.putObject(bucket, tmpKey, probe);
  await Promise.all([pipeline(stream, probe), upload]);
  return {
    tmpKey,
    sha256: probe.hash.digest("hex"),
    size: probe.size,
    head: probe.head,
    tail: probe.tail,
  };
}

/** Переносит временный объект в хранилище по хешу. Возвращает true, если объект новый. */
export async function promote(stored: StoredUpload): Promise<boolean> {
  const key = blobKey(stored.sha256);
  let created = false;
  try {
    await minio.statObject(bucket, key);
  } catch {
    await minio.copyObject(
      new Minio.CopySourceOptions({ Bucket: bucket, Object: stored.tmpKey }),
      new Minio.CopyDestinationOptions({ Bucket: bucket, Object: key }),
    );
    created = true;
  }
  await discard(stored.tmpKey);
  return created;
}

export async function discard(key: string): Promise<void> {
  try {
    await minio.removeObject(bucket, key);
  } catch {
    // объекта может уже не быть: очистка не должна ронять ответ
  }
}
