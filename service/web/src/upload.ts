// Разбор выбранной папки: что уйдёт на сервер, что нет, и как разбить на пакеты.
import type { Limits } from "./api";

export interface Picked {
  file: File;
  relativePath: string;
}

export interface Plan {
  eligible: Picked[];
  skipped: { relative_path: string; size_bytes: number; reason: string }[];
  batches: Picked[][];
  totalBytes: number;
}

const MB = 1024 * 1024;

/** Путь внутри папки объекта: имя выбранной папки отбрасывается. */
export function relativePathOf(file: File): string {
  const raw = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
  const parts = raw.split("/");
  return (parts.length > 1 ? parts.slice(1) : parts).join("/");
}

export function plan(files: Picked[], limits: Limits): Plan {
  const formats = new Set(limits.formats.map((f) => `.${f.toLowerCase()}`));
  const maxFile = limits.max_file_mb * MB;
  const maxPackage = limits.max_package_mb * MB;
  const eligible: Picked[] = [];
  const skipped: Plan["skipped"] = [];
  for (const picked of files) {
    const name = picked.relativePath.split("/").pop() ?? "";
    if (name.startsWith(".")) continue; // служебные файлы системы: .DS_Store и подобные
    const dot = name.lastIndexOf(".");
    const ext = dot >= 0 ? name.slice(dot).toLowerCase() : "";
    if (!formats.has(ext)) {
      skipped.push({ relative_path: picked.relativePath, size_bytes: picked.file.size, reason: `формат ${ext || "без расширения"} не поддерживается` });
    } else if (picked.file.size > maxFile) {
      skipped.push({ relative_path: picked.relativePath, size_bytes: picked.file.size, reason: `больше ${limits.max_file_mb} МБ` });
    } else {
      eligible.push(picked);
    }
  }
  // Пакеты не больше общего лимита: папка объекта обычно весит сотни мегабайт.
  const batches: Picked[][] = [];
  let current: Picked[] = [];
  let size = 0;
  for (const picked of eligible) {
    if (current.length > 0 && size + picked.file.size > maxPackage) {
      batches.push(current);
      current = [];
      size = 0;
    }
    current.push(picked);
    size += picked.file.size;
  }
  if (current.length > 0) batches.push(current);
  return { eligible, skipped, batches, totalBytes: eligible.reduce((sum, p) => sum + p.file.size, 0) };
}
