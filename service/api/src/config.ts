// Настройки сервиса из окружения. Значения по умолчанию подходят для docker compose.

import { randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";

const MB = 1024 * 1024;

/**
 * Секрет из переменной или из файла, путь к которому в переменной с суффиксом _FILE.
 * В docker compose секреты генерируются при первом запуске и лежат в томе: паролей
 * в репозитории нет.
 */
export function secret(name: string): string | undefined {
  const direct = process.env[name];
  if (direct) return direct;
  const file = process.env[`${name}_FILE`];
  if (file) {
    try {
      return readFileSync(file, "utf-8").trim();
    } catch (error) {
      throw new Error(`${name}_FILE: не удалось прочитать ${file}: ${(error as Error).message}`);
    }
  }
  return undefined;
}

function required(name: string): string {
  const value = secret(name);
  if (!value) {
    throw new Error(`не задан ${name}: укажите переменную ${name} или ${name}_FILE`);
  }
  return value;
}

function num(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`переменная ${name} должна быть положительным числом, получено «${raw}»`);
  }
  return value;
}

/**
 * Роли стенда. Эксперт (Р-134) работает с правами инспектора и вдобавок видит все правила сверки:
 * страница правил открыта только ему, администратору тоже нет.
 */
export const ROLES = ["inspector", "admin", "expert"] as const;
export type Role = (typeof ROLES)[number];

export interface User {
  login: string;
  password: string;
  role: Role;
}

// Учётные записи для демонстрации: «логин:пароль:роль» через запятую.
// Это заглушка вместо внешнего поставщика удостоверений, а не система учёта.
function parseUsers(raw: string): User[] {
  return raw
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      const [login, password, role] = item.split(":");
      if (!login || !password || !(ROLES as readonly string[]).includes(role)) {
        throw new Error(`AUTH_USERS: запись «${item}» должна иметь вид логин:пароль:${ROLES.join("|")}`);
      }
      return { login, password, role: role as Role };
    });
}

/**
 * Модели для режима чтения «модель» (#54): «id=Название» через запятую в PIPELINE_MODEL_CHOICES.
 * Тот же список читает воркер, поэтому переменная одна на сервис. Пустой список означает,
 * что выбор инспектору не предлагается и работает модель из PIPELINE_MODEL_NAME.
 */
export function parseModels(raw: string | undefined): { id: string; label: string }[] {
  return (raw ?? "")
    .split(",")
    .map((item) => {
      const at = item.indexOf("=");
      const id = (at < 0 ? item : item.slice(0, at)).trim();
      const label = at < 0 ? "" : item.slice(at + 1).trim();
      return { id, label: label || id };
    })
    .filter((model) => model.id.length > 0);
}

export const config = {
  port: num("PORT", 8080),
  database: () =>
    process.env.DATABASE_URL
      ? { connectionString: process.env.DATABASE_URL }
      : {
          host: process.env.DATABASE_HOST ?? "postgres",
          port: num("DATABASE_PORT", 5432),
          user: process.env.DATABASE_USER ?? "inspector",
          database: process.env.DATABASE_NAME ?? "inspector",
          password: required("DATABASE_PASSWORD"),
        },
  redisUrl: process.env.REDIS_URL ?? "redis://redis:6379",
  amqpUrl: process.env.AMQP_URL ?? "amqp://guest:guest@rabbitmq:5672",
  s3: {
    endPoint: process.env.S3_ENDPOINT ?? "minio",
    port: num("S3_PORT", 9000),
    useSSL: process.env.S3_USE_SSL === "1",
    accessKey: process.env.S3_ACCESS_KEY ?? "inspector",
    secretKey: () => required("S3_SECRET_KEY"),
    bucket: process.env.S3_BUCKET ?? "documents",
  },
  schemaPath: process.env.SCHEMA_PATH ?? new URL("../../db/schema.sql", import.meta.url).pathname,
  // Без заданного секрета токены подписываются случайным ключом и живут до перезапуска:
  // так работает выгрузка OpenAPI и локальная разработка, а compose задаёт постоянный.
  jwtSecret: secret("JWT_SECRET") ?? randomBytes(32).toString("hex"),
  jwtTtlSeconds: num("JWT_TTL_SECONDS", 12 * 3600),
  users: parseUsers(process.env.AUTH_USERS ?? "inspector:inspector:inspector,admin:admin:admin,expert:expert:expert"),
  // Лимиты ТЗ для загрузки инспектором в браузере: файл до 50 МБ, пакет до 200 МБ. У загрузчика
  // папки объекта (роль admin, маршрут LOADER_UPLOAD_PATH) лимитов нет: организатор на установочной
  // сессии сказал, что крупные пакеты идут через бэк (вопрос 18, Р-110). В корпусе 115 PDF больше
  // 50 МБ, самый большой — 912 МБ.
  limits: {
    maxFileBytes: num("MAX_FILE_MB", 50) * MB,
    maxPackageBytes: num("MAX_PACKAGE_MB", 200) * MB,
  },
  // Способ чтения выбирается на объект (#54); для режима «модель» инспектор выбирает и саму
  // модель из настроенного списка. Читает ею воркер, здесь список только показывается и проверяется.
  reading: {
    models: parseModels(process.env.PIPELINE_MODEL_CHOICES),
    modelDefault: process.env.PIPELINE_MODEL_NAME ?? "",
  },
  validateResponses: process.env.VALIDATE_RESPONSES !== "0",
  logLevel: process.env.LOG_LEVEL ?? "info",
  // Передача финализированного протокола в ИАИС «РиН» (ТЗ 9.6). Пустой адрес — передача выключена.
  // Повторы по ТЗ — через 1, 5 и 15 минут; на стенде задержки можно сократить.
  iais: {
    url: process.env.IAIS_URL ?? "",
    retryDelaysS: (process.env.IAIS_RETRY_DELAYS_S ?? "60,300,900")
      .split(",")
      .map((x) => Number(x.trim()))
      .filter((x) => Number.isFinite(x) && x > 0),
    timeoutMs: num("IAIS_TIMEOUT_MS", 30000),
    pollMs: num("IAIS_POLL_MS", 5000),
  },
};

export const QUEUES = ["parse", "compare", "protocol"] as const;
export type QueueName = (typeof QUEUES)[number];
/** Пробные прогоны правил эксперта (#222, #223): воркер берёт их после шагов обработки документов. */
export const RULE_TEST_QUEUE = "ruletest";
