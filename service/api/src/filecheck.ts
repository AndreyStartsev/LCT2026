// Проверка загружаемых файлов по ТЗ: формат, размер, целостность.
import { config } from "./config.js";

export const FORMATS: Record<string, string> = { ".pdf": "PDF", ".docx": "DOCX", ".xml": "XML" };
export const FORMAT_LIST = Object.values(FORMATS);

/** Чем отдавать исходный файл браузеру: PDF он покажет встроенным просмотрщиком. */
export const MEDIA_TYPES: Record<string, string> = {
  ".pdf": "application/pdf",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".xml": "application/xml",
};

/**
 * Маршрут загрузчика папки объекта (`tools/upload_object.py`), роль admin. Лимитов размера
 * файла и пакета у него нет: лимиты ТЗ относятся к загрузке инспектором в браузере, крупные
 * пакеты идут через бэк (установочная сессия, 21:13; Р-110).
 */
export const LOADER_UPLOAD_PATH = "/api/v1/documents/bulk";

/**
 * Лимиты и настройки загрузки одним местом: их отдаёт и /health (с него их берёт клиент),
 * и ответы загрузки. Раньше health собирал свой объект и не знал про список моделей (#54).
 * max_file_mb и max_package_mb — лимиты загрузки в браузере.
 */
export function limitsView() {
  return {
    max_file_mb: config.limits.maxFileBytes / 1024 / 1024,
    max_package_mb: config.limits.maxPackageBytes / 1024 / 1024,
    formats: FORMAT_LIST,
    loader_path: LOADER_UPLOAD_PATH,
    reading_models: config.reading.models,
    model_default: config.reading.modelDefault || null,
  };
}

export type RejectCode =
  | "UNSUPPORTED_FORMAT"
  | "FILE_TOO_LARGE"
  | "EMPTY_FILE"
  | "CORRUPTED_PDF"
  | "CORRUPTED_FILE";

export interface Rejection {
  code: RejectCode;
  message: string;
}

export function extensionOf(path: string): string {
  const name = path.split("/").pop() ?? path;
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

const SIGNATURES = new Set([".sig", ".p7s", ".sgn"]);

export function unsupported(ext: string): Rejection {
  if (SIGNATURES.has(ext)) {
    // подпись к документу, а не документ: стадию загруженной частично она не делает
    return {
      code: "UNSUPPORTED_FORMAT",
      message: `Файл электронной подписи ${ext} не загружается: подпись сервис не проверяет, подписанный документ принимается отдельно`,
    };
  }
  return {
    code: "UNSUPPORTED_FORMAT",
    message: `Формат ${ext || "без расширения"} не поддерживается. Поддерживаемые форматы: ${FORMAT_LIST.join(", ")}`,
  };
}

export function tooLarge(limitBytes: number): Rejection {
  return {
    code: "FILE_TOO_LARGE",
    message: `Файл больше допустимого размера ${Math.round(limitBytes / 1024 / 1024)} МБ`,
  };
}

/**
 * Структурная проверка по началу и концу файла.
 *
 * Полностью файл разбирает воркер; здесь ловится то, что ТЗ называет повреждённым
 * файлом при загрузке: оборванная передача (у PDF нет «%%EOF» в конце), чужое
 * содержимое под расширением, пустой файл. Проверка не читает файл целиком
 * и не держит его в памяти.
 */
export function checkContent(ext: string, size: number, head: Buffer, tail: Buffer): Rejection | null {
  if (size === 0) {
    return { code: "EMPTY_FILE", message: "Файл пустой. Загрузите его заново" };
  }
  if (ext === ".pdf") {
    const start = head.indexOf("%PDF-");
    // спецификация разрешает мусор перед заголовком в пределах первого килобайта
    if (start < 0 || !tail.includes("%%EOF")) {
      return {
        code: "CORRUPTED_PDF",
        message: "Файл PDF повреждён или загружен не полностью. Загрузите его заново",
      };
    }
    return null;
  }
  if (ext === ".docx") {
    if (!(head[0] === 0x50 && head[1] === 0x4b && head[2] === 0x03 && head[3] === 0x04)) {
      return { code: "CORRUPTED_FILE", message: "Файл DOCX повреждён: это не архив Office Open XML. Загрузите его заново" };
    }
    return null;
  }
  if (ext === ".xml") {
    const text = head.toString("utf-8").replace(/^﻿/, "").trimStart();
    if (!text.startsWith("<")) {
      return { code: "CORRUPTED_FILE", message: "Файл XML повреждён: содержимое не начинается с разметки. Загрузите его заново" };
    }
    return null;
  }
  return unsupported(ext);
}

/** Путь внутри загруженной папки: без выхода за её пределы и без пустых частей. */
export function safeRelativePath(raw: string): string | null {
  const parts = raw
    .replace(/\\/g, "/")
    .split("/")
    .filter((part) => part !== "" && part !== ".");
  if (parts.length === 0 || parts.some((part) => part === "..")) {
    return null;
  }
  return parts.join("/").normalize("NFC");
}
