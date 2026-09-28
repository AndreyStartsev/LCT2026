// Загрузки, идущие из этого окна браузера (#74). Загрузка папки — это несколько пакетов по
// сотне мегабайт, и сервер узнаёт об объекте только когда ляжет первый пакет. Пока пакеты
// идут, загрузку видел лишь экран «Новая проверка»: стоило уйти с него, она пропадала из
// виду, хотя продолжалась. Здесь её ход общий — реестр объектов показывает загрузки
// в очереди обработки наравне с тем, что уже делает сервер.
import { useSyncExternalStore } from "react";

export interface UploadJob {
  /** ключ загрузки в этом окне */
  id: string;
  /** название объекта или «дозагрузка» для существующего процесса */
  name: string;
  /** процесс появляется после первого пакета; до того сервер об объекте не знает */
  processId: string | null;
  batchIndex: number;
  batchCount: number;
  /** отправлено байтов по всей загрузке и сколько всего */
  sent: number;
  total: number;
  startedAt: string;
  /** загрузка оборвалась: запись остаётся, пока её не уберут, иначе сбой прошёл бы незамеченным */
  error?: string;
  /** на каком пакете оборвалась (с 1) */
  failedBatch?: number;
  /**
   * Продолжить с оборвавшегося пакета в тот же процесс. Есть, пока выбранные файлы живы
   * в этом окне браузера: после перезагрузки страницы их нет, и догружать придётся заново.
   */
  resume?: () => void;
  /** что делает resume — подпись кнопки: «продолжить с пакета 3» или «запустить разбор» */
  resumeLabel?: string;
  /** что происходит сейчас, если это не обычная отправка: «связь оборвалась, повтор через 6 с» */
  note?: string;
}

let jobs: UploadJob[] = [];
const listeners = new Set<() => void>();
let seq = 0;

function emit() {
  jobs = [...jobs];
  listeners.forEach((listener) => listener());
  // Закрытие вкладки обрывает загрузку: пока она идёт, браузер переспросит
  // и после сбоя, который можно продолжить: выбранные файлы живут только в этой вкладке
  window.onbeforeunload = jobs.some((j) => !j.error || j.resume) ? () => "Загрузка документов не закончена" : null;
}

export function beginUpload(name: string, total: number, batchCount: number, processId: string | null): string {
  const id = `u${++seq}`;
  jobs.push({ id, name, processId, batchIndex: 1, batchCount, sent: 0, total, startedAt: new Date().toISOString() });
  emit();
  return id;
}

export function updateUpload(id: string, patch: Partial<UploadJob>) {
  const at = jobs.findIndex((j) => j.id === id);
  if (at < 0) return;
  jobs[at] = { ...jobs[at], ...patch };
  emit();
}

/**
 * Убрать оборвавшиеся загрузки процесса: разбор по принятым запущен или началась новая
 * загрузка в тот же процесс — старая строка «загрузка прервалась» только путала бы.
 */
export function dropFailed(processId: string) {
  const left = jobs.filter((j) => !(j.error && j.processId === processId));
  if (left.length === jobs.length) return;
  jobs = left;
  emit();
}

/** Загрузка закончена: дальше процесс виден по состоянию на сервере. */
export function endUpload(id: string) {
  jobs = jobs.filter((j) => j.id !== id);
  emit();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useUploads(): UploadJob[] {
  return useSyncExternalStore(subscribe, () => jobs);
}
