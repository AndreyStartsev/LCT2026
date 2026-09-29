import { useMemo, useState } from "react";
import { api, ApiFailure, READING_MODES, uploadBatch, type Limits, type ObjectItem, type ReadingMode, type UploadResult } from "../api";
import { bytes, EXTERNAL_MODEL_NOTICE, READING_MODE, READING_MODE_HINT } from "../labels";
import { plan, relativePathOf, type Picked, type Plan } from "../upload";
import { beginUpload, dropFailed, endUpload, updateUpload, useUploads } from "../uploads";

interface Props {
  limits: Limits;
  objects: ObjectItem[];
  /** Дозагрузка в существующий процесс: объект уже известен. */
  processId?: string;
  /** Как назвать загрузку в очереди обработки, когда объект уже известен (дозагрузка). */
  title?: string;
  /** Подпись кнопки, если протокола ещё нет: дозагрузка в незаконченную загрузку запускает разбор, а не пересборку. */
  submitLabel?: string;
  onUploaded: (processId: string) => void;
}

interface BatchState {
  index: number;
  count: number;
  sent: number;
  total: number;
  /** повтор после обрыва: вместо хода отправки — что происходит */
  note?: string;
}

/** Что было выбрано при запуске загрузки: продолжение идёт по этому, а не по текущему экрану. */
interface Snapshot {
  planned: Plan;
  objectId: string;
  objectName: string;
  readingMode: ReadingMode;
  modelName: string;
}

/** Ключ загрузки: одинаковый у всех пакетов и повторов одной загрузки (сервер по нему не заводит дубль). */
function uploadKey(): string {
  try {
    return crypto.randomUUID();
  } catch {
    // crypto.randomUUID есть только в защищённом контексте (https, localhost)
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  }
}

const pause = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Паузы перед повтором пакета после обрыва: два повтора, потом — «Продолжить» руками. */
const RETRY_DELAYS = [2000, 6000];

/** Сообщение сервера — законченной фразой: за ним в той же строке идёт, что делать дальше. */
function sentence(text: string): string {
  return /[.!?…]$/.test(text.trim()) ? text.trim() : `${text.trim()}.`;
}

/** Обрыв связи, таймаут и сбой сервера стоит повторить; отказ сервера по существу — нет. */
function retryable(failure: ApiFailure): boolean {
  return failure.status === 0 || failure.status === 408 || failure.status === 429 || failure.status >= 500;
}

export default function UploadPanel({ limits, objects, processId, title, submitLabel, onUploaded }: Props) {
  // Загрузки этого окна, начатые раньше: вернувшись на экран, человек видит, что одна уже идёт
  const running = useUploads().filter((j) => !j.error);
  const [objectId, setObjectId] = useState("");
  const [objectName, setObjectName] = useState("");
  // Способ чтения объекта (#54). По умолчанию — модель, но прицельно: она дочитывает только сканы
  // без текста и чертежи без текстового слоя (Р-117), остальное — слой и распознавание. Читать моделью
  // все страницы нельзя. Слой выбирают ради самого быстрого разбора, распознавание — чтобы без модели.
  const [readingMode, setReadingMode] = useState<ReadingMode>("model");
  // Модель для режима «модель»: список задаёт сервис, по умолчанию его первая.
  const models = limits.reading_models ?? [];
  const [modelName, setModelName] = useState(limits.model_default || models[0]?.id || "");
  const [picked, setPicked] = useState<Picked[]>([]);
  const [batch, setBatch] = useState<BatchState | null>(null);
  const [results, setResults] = useState<UploadResult[]>([]);
  const [error, setError] = useState<string | null>(null);

  const planned = useMemo(() => plan(picked, limits), [picked, limits]);
  const known = objects.find((o) => o.object_id === objectId);

  function choose(list: FileList | null, fromFolder: boolean) {
    if (!list) return;
    const files = Array.from(list).map((file) => ({
      file,
      relativePath: fromFolder ? relativePathOf(file) : file.name,
    }));
    setPicked(files);
    setResults([]);
    setError(null);
    // другие файлы — прежнюю загрузку отсюда уже не продолжить
    setResume(null);
    if (fromFolder && !processId && !objectName && files.length > 0) {
      const top = ((files[0].file as File & { webkitRelativePath?: string }).webkitRelativePath || "").split("/")[0];
      if (top) setObjectName(top);
    }
  }

  // Оборванную загрузку можно продолжить — в тот же процесс и тем же, что было выбрано тогда:
  // «Продолжить» и «Отправить заново» работают по снимку оборвавшейся загрузки, а не по тому,
  // что выбрано на экране сейчас. Без этого повтор заводил новый процесс (дубль в реестре),
  // а выбор другой папки во время загрузки подменял её пакеты.
  const [resume, setResume] = useState<{ label: string; again: () => void; restart?: () => void } | null>(null);
  // Процесс, в который уже ушли пакеты оборвавшейся загрузки: основная кнопка догружает в него,
  // пока инспектор не сменил объект, способ чтения или сам не начал новый.
  const [lastTarget, setLastTarget] = useState<string | null>(null);

  function retarget() {
    setLastTarget(null);
    setResume(null);
  }

  function done(job: string, target: string | null) {
    setBatch(null);
    setResume(null);
    setLastTarget(null);
    endUpload(job);
    if (target) onUploaded(target);
  }

  /**
   * Файлы приняты, разбор не поставлен: очередь обработки была недоступна. Отправлять файлы
   * заново незачем — запускаем разбор; «уже идёт» — тоже успех.
   */
  async function startParse(target: string, job: string) {
    setError(null);
    setResume(null);
    setBatch({ index: 1, count: 1, sent: 1, total: 1, note: "Файлы приняты, запускается разбор" });
    updateUpload(job, { error: undefined, failedBatch: undefined, resume: undefined, resumeLabel: undefined, processId: target, note: "запускается разбор" });
    for (let attempt = 0; ; attempt++) {
      try {
        await api.start(target);
        break;
      } catch (e) {
        const failure = e as ApiFailure;
        if (failure.code === "PROCESS_BUSY") break;
        if (!retryable(failure) || attempt >= RETRY_DELAYS.length) {
          setBatch(null);
          const again = () => startParse(target, job);
          updateUpload(job, { error: `файлы приняты, разбор не запущен: ${failure.message}`, note: undefined, resume: again, resumeLabel: "запустить разбор" });
          setResume({ label: "Запустить разбор", again });
          setLastTarget(target);
          setError(`Файлы приняты, но разбор не запущен. ${sentence(failure.message)} Запустите разбор ещё раз — файлы отправлять заново не нужно.`);
          return;
        }
        const wait = RETRY_DELAYS[attempt];
        updateUpload(job, { note: `разбор не запустился: повтор ${attempt + 1} из ${RETRY_DELAYS.length} через ${wait / 1000} с` });
        await pause(wait);
      }
    }
    done(job, target);
  }

  function start() {
    // снимок выбора на момент запуска: продолжение идёт по нему
    const snap: Snapshot = { planned, objectId: objectId.trim(), objectName: objectName.trim(), readingMode, modelName };
    void run(snap, 0, lastTarget ?? processId ?? null, undefined, uploadKey());
  }

  async function run(snap: Snapshot, from: number, into: string | null, jobId: string | undefined, key: string) {
    const { planned: plan } = snap;
    setError(null);
    setResume(null);
    if (from === 0) setResults([]);
    let target = into;
    const count = plan.batches.length;
    // Ход загрузки пишется и в общий учёт: он переживает уход с экрана и виден в реестре объектов
    const sizes = plan.batches.map((b) => b.reduce((n, p) => n + p.file.size, 0));
    const job =
      jobId ??
      beginUpload(
        processId ? `${title ?? "объект"} — дозагрузка` : snap.objectName || snap.objectId || "новый объект",
        sizes.reduce((n, x) => n + x, 0),
        count,
        target,
      );
    // новая загрузка в тот же процесс заменяет прежнюю оборвавшуюся
    if (!jobId && target) dropFailed(target);
    let before = sizes.slice(0, from).reduce((n, x) => n + x, 0);
    updateUpload(job, { error: undefined, failedBatch: undefined, resume: undefined, resumeLabel: undefined, note: undefined, batchIndex: from + 1, sent: before, processId: target });
    // список пропущенных файлов уходит с каждым пакетом, пока ни один не принят: пакет,
    // отклонённый целиком, процесс не заводит, и отказы по пропущенным иначе потерялись бы
    let skippedSent = false;
    let current = from;
    try {
      for (let i = from; i < count; i++) {
        current = i;
        const last = i === count - 1;
        const form = new FormData();
        // ключ загрузки — до файлов: повтор пакета без process_id попадёт в уже заведённый процесс,
        // а повтор уже принятого последнего пакета не запустит разбор второй раз
        form.append("upload_key", key);
        if (target) {
          form.append("process_id", target);
        } else {
          if (snap.objectId) form.append("object_id", snap.objectId);
          if (snap.objectName) form.append("object_name", snap.objectName);
          // способ чтения задаётся при создании процесса: дозагрузка идёт тем же способом
          form.append("reading_mode", snap.readingMode);
          if (snap.readingMode === "model" && snap.modelName) form.append("model_name", snap.modelName);
        }
        // разбор запускается после последнего пакета, а не после каждого
        form.append("final_batch", String(last));
        if (!skippedSent && plan.skipped.length > 0) {
          form.append("skipped", JSON.stringify(plan.skipped.map(({ relative_path, size_bytes }) => ({ relative_path, size_bytes }))));
        }
        for (const p of plan.batches[i]) {
          form.append("relative_path", p.relativePath);
          form.append("files", p.file, p.file.name);
        }
        setBatch({ index: i + 1, count, sent: 0, total: 1 });
        updateUpload(job, { batchIndex: i + 1, sent: before });
        // Обрыв связи и ответ 5xx повторяются сами: пакет — это сотня мегабайт, и терять
        // загрузку из-за секундного сбоя сети обидно. Принятый файл сервер при повторе
        // перезаписывает, а по ключу узнаёт и процесс, и уже принятый последний пакет.
        // Отказ сервера по существу (4xx) не повторяется.
        let result: UploadResult | null = null;
        let rejectedWhole = false;
        for (let attempt = 0; result === null && !rejectedWhole; attempt++) {
          try {
            result = await uploadBatch(form, (sent, total) => {
              setBatch({ index: i + 1, count, sent, total });
              // размер пакета в запросе чуть больше файлов из-за разметки формы — не выходим за итог
              updateUpload(job, { sent: before + Math.min(sent, sizes[i]), note: undefined });
            });
          } catch (e) {
            const failure = e as ApiFailure;
            const pid = failure.details?.process_id;
            if (typeof pid === "string") {
              target = pid;
              updateUpload(job, { processId: target });
            }
            // файлы сохранены, не встал в очередь разбор: запускаем его, пакет не повторяем
            if (failure.code === "QUEUE_UNAVAILABLE" && target) {
              updateUpload(job, { sent: before + sizes[i] });
              await startParse(target, job);
              return;
            }
            if (failure.code === "NO_ACCEPTED_FILES") {
              // пакет отклонён целиком: причины — в список, отказы сервер записал в процесс
              const rejected = (failure.details?.rejected as UploadResult["rejected"] | undefined) ?? [];
              setResults((was) => [...was, { rejected, accepted: [] } as unknown as UploadResult]);
              // на последнем пакете это значит: загрузка не приняла ни одного файла, разбор не поставлен
              if (last) throw failure;
              rejectedWhole = true;
              break;
            }
            if (!retryable(failure) || attempt >= RETRY_DELAYS.length) throw failure;
            const wait = RETRY_DELAYS[attempt];
            const note = `связь оборвалась на пакете ${i + 1}: повтор ${attempt + 1} из ${RETRY_DELAYS.length} через ${wait / 1000} с`;
            setBatch({ index: i + 1, count, sent: 0, total: 1, note });
            updateUpload(job, { sent: before, note });
            await pause(wait);
          }
        }
        if (result) {
          const accepted = result;
          setResults((was) => [...was, accepted]);
          target = accepted.process_id;
          skippedSent = true;
        }
        before += sizes[i];
        updateUpload(job, { processId: target, sent: before });
      }
      done(job, target);
    } catch (e) {
      setBatch(null);
      const failure = e as ApiFailure;
      const pid = failure.details?.process_id;
      if (typeof pid === "string") target = pid;
      // процесса нет, он закрыт или ключ относится к другому объекту — продолжать в него нечего
      if (["PROCESS_NOT_FOUND", "PROCESS_FINALIZED", "UPLOAD_KEY_MISMATCH"].includes(failure.code)) target = null;
      const failed = current;
      // Продолжать имеет смысл, если повтор может пройти: сбой связи или сервера, обработка,
      // которая кончится, истёкший вход. Удалённый процесс, финализированный протокол,
      // слишком большой пакет, пакет без единого принятого файла повтором не исправить.
      const canResume = retryable(failure) || failure.code === "PROCESS_BUSY" || failure.status === 401;
      setLastTarget(target);
      const again = () => void run(snap, failed, target, job, key);
      const restart = () => void run(snap, 0, target, job, key);
      const label = `продолжить с пакета ${failed + 1}`;
      updateUpload(job, {
        error: failure.message || "загрузка оборвалась",
        processId: target,
        failedBatch: failed + 1,
        note: undefined,
        resume: canResume ? again : undefined,
        resumeLabel: canResume ? label : undefined,
      });
      if (canResume) setResume({ label: `Продолжить с пакета ${failed + 1} из ${count}`, again, restart });
      setError(
        failure.code === "NO_ACCEPTED_FILES"
          ? "Ни один файл загрузки не принят. Причины — в списке ниже."
          : failure.code === "PROCESS_NOT_FOUND"
            ? "Процесс, в который шла загрузка, удалён. Загрузите объект заново."
            : failure.code === "PACKAGE_TOO_LARGE"
              ? `${sentence(failure.message)} Выберите меньше файлов за раз.`
              : `${sentence(failure.message || "Загрузка оборвалась")}${target ? " Принятые пакеты сохранены в процессе." : ""}` +
                (canResume ? ` Загрузку можно продолжить с пакета ${failed + 1} из ${count}.` : ""),
      );
    }
  }

  const rejectedAll = results.flatMap((r) => r.rejected);
  const acceptedCount = results.reduce((n, r) => n + r.accepted.length, 0);

  return (
    <section className="upload">
      <header className="upload-head">
        <div>
          <p className="lede">
            Выберите папку объекта целиком: стадия документа определяется по пути и по реестру организатора.
            Файлы принимаются в форматах {limits.formats.join(", ")}, до {limits.max_file_mb} МБ каждый; папка
            уходит пакетами до {limits.max_package_mb} МБ.
          </p>
        </div>
      </header>

      {limits.external_model && (
        <div className="alert external-model" role="note">
          <strong>{EXTERNAL_MODEL_NOTICE.title}</strong> {EXTERNAL_MODEL_NOTICE.text}
        </div>
      )}

      {!processId && (
        <>
        <div className="grid-2">
          <label className="field">
            <span>Идентификатор объекта</span>
            <input
              id="upload-object-id"
              list="known-objects"
              placeholder="например, OBJ-NOVOSLOBODSKAYA"
              value={objectId}
              onChange={(e) => {
                setObjectId(e.target.value);
                retarget();
                const hit = objects.find((o) => o.object_id === e.target.value);
                if (hit) setObjectName(hit.name);
              }}
            />
            <datalist id="known-objects">
              {objects.map((o) => (
                <option key={o.object_id} value={o.object_id}>
                  {o.name}
                </option>
              ))}
            </datalist>
            <small>
              {known
                ? `Объект уже проверялся: будет создан новый процесс (${known.processes} было).`
                : "Для объектов организатора укажите их идентификатор: с ним протокол сопоставим с эталоном. Пусто — присвоится автоматически."}
            </small>
          </label>
          <label className="field">
            <span>Название</span>
            <input
              id="upload-object-name"
              value={objectName}
              onChange={(e) => {
                setObjectName(e.target.value);
                retarget();
              }}
            />
          </label>
        </div>
        <fieldset className="field reading-mode">
          <legend>Как читать документы</legend>
          {READING_MODES.map((mode) => (
            <label key={mode} className={`mode${readingMode === mode ? " mode-on" : ""}`}>
              <input
                type="radio"
                name="reading-mode"
                value={mode}
                checked={readingMode === mode}
                onChange={() => {
                  setReadingMode(mode);
                  retarget();
                }}
              />
              <span className="mode-title">{READING_MODE[mode]}</span>
              <span className="mode-hint">{READING_MODE_HINT[mode]}</span>
            </label>
          ))}
          {readingMode === "model" && models.length > 0 && (
            <label className="field model-pick">
              <span>Модель</span>
              <select
                id="upload-model"
                className="pick"
                value={modelName}
                onChange={(e) => {
                  setModelName(e.target.value);
                  retarget();
                }}
              >
                {models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.label}
                  </option>
                ))}
              </select>
              <small>
                Страницы, прочитанные раньше, берутся из кеша: смена модели касается тех, что читаются впервые.
              </small>
            </label>
          )}
          <small>
            Способ задаётся на объект: чем он прочитан на самом деле, видно в готовности объекта и в протоколе.
            Если модель не настроена, объект читается распознаванием, и инспектор получает об этом уведомление.
          </small>
        </fieldset>
        </>
      )}

      <div className="pickers">
        <label className="picker">
          <input
            id="upload-folder"
            type="file"
            multiple
            // webkitdirectory нет в типах React, но браузеры его поддерживают
            {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
            disabled={batch !== null}
            onChange={(e) => choose(e.target.files, true)}
          />
          <span className="picker-title">Выбрать папку</span>
          <span className="picker-sub">вся структура ПД, РД, ИД</span>
        </label>
        <label className="picker">
          <input id="upload-files" type="file" multiple disabled={batch !== null} onChange={(e) => choose(e.target.files, false)} />
          <span className="picker-title">Выбрать файлы</span>
          <span className="picker-sub">без структуры папок</span>
        </label>
      </div>

      {picked.length > 0 && (
        <div className="summary">
          <div className="stat">
            <span className="stat-value">{planned.eligible.length}</span>
            <span className="stat-label">файлов к загрузке</span>
          </div>
          <div className="stat">
            <span className="stat-value">{bytes(planned.totalBytes)}</span>
            <span className="stat-label">объём</span>
          </div>
          <div className="stat">
            <span className="stat-value">{planned.batches.length}</span>
            <span className="stat-label">пакетов</span>
          </div>
          <div className={`stat${planned.skipped.length ? " stat-warn" : ""}`}>
            <span className="stat-value">{planned.skipped.length}</span>
            <span className="stat-label">не будут приняты</span>
          </div>
        </div>
      )}

      {planned.skipped.length > 0 && (
        <details className="details">
          <summary>Файлы, которые сервис не примет по требованиям ТЗ</summary>
          <ul className="file-list">
            {planned.skipped.map((s) => (
              <li key={s.relative_path}>
                <span className="path">{s.relative_path}</span>
                <span className="reason">
                  {s.reason}, {bytes(s.size_bytes)}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {!batch && running.length > 0 && (
        <div className="note-line">
          {running.length === 1
            ? `Идёт загрузка «${running[0].name}»: пакет ${running[0].batchIndex} из ${running[0].batchCount}, ${bytes(running[0].sent)} из ${bytes(running[0].total)}.`
            : `Идут загрузки: ${running.length}.`}{" "}
          Ход загрузки и очередь обработки видны в реестре объектов, уходить с этого экрана можно.
        </div>
      )}

      {batch && (
        <div className="progress" role="status">
          <div className="progress-label">
            {batch.note ?? `Пакет ${batch.index} из ${batch.count}: ${bytes(batch.sent)} из ${bytes(batch.total)}`}
          </div>
          <div className="bar">
            <div className="bar-fill" style={{ width: `${Math.round((batch.sent / Math.max(batch.total, 1)) * 100)}%` }} />
          </div>
        </div>
      )}

      {error && <div className="alert">{error}</div>}
      {lastTarget && !resume && !batch && !processId && (
        <div className="note-line">
          Файлы уйдут в начатую загрузку этого объекта: принятые раньше пакеты не пропадут, дубля в реестре не будет.{" "}
          <button type="button" className="link" onClick={() => setLastTarget(null)}>
            начать как новый объект
          </button>
        </div>
      )}

      {results.length > 0 && (
        <div className="note-line">
          Принято файлов: {acceptedCount}. Отклонено сервером: {rejectedAll.length}.
        </div>
      )}
      {rejectedAll.length > 0 && (
        <ul className="file-list">
          {rejectedAll.map((r) => (
            <li key={r.relative_path}>
              <span className="path">{r.relative_path}</span>
              <span className="reason">{r.message}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="actions">
        {resume && !batch ? (
          <>
            <button className="btn btn-primary" onClick={resume.again}>
              {resume.label}
            </button>
            {/* заново — в тот же процесс и те же файлы: дубля объекта не будет */}
            {resume.restart && (
              <button className="btn" onClick={resume.restart}>
                Отправить все пакеты заново
              </button>
            )}
          </>
        ) : (
          <button className="btn btn-primary" disabled={planned.eligible.length === 0 || batch !== null} onClick={start}>
            {submitLabel ?? (processId ? "Дозагрузить и пересобрать протокол" : "Загрузить и проверить")}
          </button>
        )}
      </div>
    </section>
  );
}
