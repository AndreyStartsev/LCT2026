import { useEffect, useRef, useState, type ReactNode } from "react";
import type { FileItem, Finding, Readiness, Recompute } from "../api";
import { criticalityWeight, duration, READING_MODE, STAGE, UPLOAD_STATE, STAGE_NAME, VERDICT } from "../labels";
import { TABLES, type StageLoad, type TableKey } from "../protocol";
import { ConfidenceMark, SpecialistMark } from "./Marks";
import type { Filter as FileFilter } from "./FilesPane";
import Tip from "./Tip";

interface Props {
  table: TableKey;
  counts: Record<TableKey, number>;
  rows: Finding[];
  /** Текст пустой таблицы; по умолчанию — из описания таблицы. */
  empty?: string;
  activeId: string | null;
  loads: StageLoad[];
  rejectedFiles: FileItem[];
  /** готовность объекта (#39): на что опирается вывод по объекту */
  readiness?: Readiness | null;
  /** что пересчитано при последней обработке, а что перенесено из прошлой версии (#60) */
  recompute?: Recompute | null;
  onTable: (table: TableKey) => void;
  onSelect: (id: string) => void;
  onRejectedFiles: () => void;
  /** Открыть реестр файлов, при надобности — сразу в нужном отборе (#74, п. 2.3). */
  onFiles: (filter?: FileFilter) => void;
  /** Администратору — перечитать страницы, на которых модель не ответила (#74, п. 4.2). */
  canRetryRead?: boolean;
  onRetryRead?: () => void;
  /** Открыть журнал обработки: там живут наблюдения о качестве разбора (#83). */
  onLog?: () => void;
  /** Решений, принятых по прежним значениям: после дозагрузки значения изменились (п. 9). */
  revisit?: number;
  /** Перейти к первой такой записи. */
  onRevisit?: () => void;
  /** Листов рабочей документации, изменённых между редакциями без отметки (#81). */
  unmarked?: number;
  /**
   * Ручные правки файлов, ещё не вошедшие в протокол (п. 11): строка в «Полноте обработки»
   * с кнопкой пересборки — не отдельной строкой над рабочей областью.
   */
  pendingEdits?: number;
  onRebuild?: () => void;
  /**
   * Все кандидаты решены (п. 10): итог — строкой над списком таблицы 2, а не над рабочей
   * областью; ссылка переводит фокус на значок финализации, сама не финализирует.
   */
  finished?: { confirmed: number; rejected: number; clarification: number; revisit: number } | null;
  onToFinalize?: () => void;
}

/** Свёрнутое состояние блока переживает перезагрузку: инспектор раскрыл — пусть остаётся раскрытым. */
function readFold(id: string): boolean {
  try {
    return localStorage.getItem(`inspector-fold-${id}`) === "1";
  } catch {
    return false;
  }
}

/**
 * Блок, свёрнутый по умолчанию: комплектность и готовность занимали весь левый столбец,
 * и список записей протокола не было видно. В свёрнутом виде блок сохраняет суть одной
 * строкой, а когда цифра мешает выводам — ещё и метку, чтобы её не пропустили.
 */
function FoldPane({
  id,
  title,
  digest,
  attention,
  action,
  remember = true,
  children,
}: {
  id: string;
  title: string;
  digest: string;
  attention?: boolean;
  action?: ReactNode;
  /** Помнить раскрытие между заходами; без этого блок всякий раз открывается свёрнутым. */
  remember?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(() => remember && readFold(id));
  const toggle = () => {
    setOpen((was) => {
      if (remember) {
        try {
          localStorage.setItem(`inspector-fold-${id}`, was ? "0" : "1");
        } catch {
          // приватное окно или запрет на хранилище: состояние живёт до перезагрузки
        }
      }
      return !was;
    });
  };
  return (
    <section className={`pane statuses fold${open ? " open" : ""}`}>
      <div className="pane-head">
        <button type="button" className="fold-toggle" aria-expanded={open} aria-controls={`fold-${id}`} onClick={toggle}>
          <span className="fold-arrow" aria-hidden="true">
            ▸
          </span>
          <h2>{title}</h2>
        </button>
        {open ? action : <span className={`count fold-digest${attention ? " attention" : ""}`}>{digest}</span>}
      </div>
      {open && (
        <div id={`fold-${id}`} className="fold-body">
          {children}
        </div>
      )}
    </section>
  );
}

export default function ProtocolColumn({
  table,
  counts,
  rows,
  empty,
  activeId,
  loads,
  rejectedFiles,
  readiness,
  recompute,
  onTable,
  onSelect,
  onRejectedFiles,
  onFiles,
  canRetryRead,
  onRetryRead,
  onLog,
  unmarked = 0,
  revisit = 0,
  onRevisit,
  pendingEdits = 0,
  onRebuild,
  finished,
  onToFinalize,
}: Props) {
  // Выбранная строка всегда видна: после решения и при листании ↑ ↓ список прокручивается за
  // ней, а если фокус был в списке — он переходит на неё же (п. 7). В списке одна остановка
  // Tab — у выбранной строки, дальше по строкам ходят стрелками.
  const listRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const list = listRef.current;
    const row = list?.querySelector<HTMLElement>('[aria-current="true"]');
    if (!list || !row) return;
    // Прокручивается только сам список, не страница: scrollIntoView двигал бы и документ,
    // и на узком окне экран уезжал бы к списку при каждом решении
    const r = row.getBoundingClientRect();
    const l = list.getBoundingClientRect();
    if (r.top < l.top) list.scrollTop -= l.top - r.top;
    else if (r.bottom > l.bottom) list.scrollTop += r.bottom - l.bottom;
    if (list.contains(document.activeElement) && document.activeElement !== row) row.focus({ preventScroll: true });
  }, [activeId, table]);
  const share = readiness ? Math.round(readiness.share_without_text * 1000) / 10 : 0;
  const spec = TABLES.find((t) => t.key === table)!;
  // Свёрнутая сводка отвечает на один вопрос: есть ли повод открыть блок.
  const missing = loads.filter((l) => l.state === "MISSING").map((l) => STAGE[l.stage] ?? l.stage);
  const loadsDigest = missing.length
    ? `нет: ${missing.join(", ")}`
    : loads.map((l) => STAGE[l.stage] ?? l.stage).join(" · ");
  const modelCalls = readiness?.model_calls ?? 0;
  const silentCalls = modelCalls ? modelCalls - (readiness?.model_answered ?? 0) : 0;
  // треть неотвеченных вызовов — уже повод отметить строку штриховкой: столько же берёт
  // за порог отчёт готовности (pipeline/readiness.py)
  const modelSilenceHurts = modelCalls > 0 && silentCalls >= modelCalls / 3;
  const readyNotes: string[] = [];
  if (readiness) {
    if (share > 20) readyNotes.push(`без текста ${share}%`);
    if (readiness.stage_unknown > 0) readyNotes.push(`без стадии ${readiness.stage_unknown}`);
    if (readiness.ocr_enabled === false && readiness.pages_without_text > 0) readyNotes.push("сканы не читались");
    // Молчание модели в свёрнутую сводку не выносится: сколько вызовов осталось без ответа и
    // кнопка «перечитать» — внутри блока, у строки модели
  }
  if (unmarked > 0) readyNotes.push(`без отметки изменений ${unmarked}`);
  if (pendingEdits > 0) readyNotes.push(`правки не в протоколе ${pendingEdits}`);
  return (
    <div className="col protocol-col">
      <section className="pane grow">
        <div className="pane-head">
          <h2>Протокол</h2>
          {/* решения по прежним значениям видны сразу, с переходом к первому из них (п. 9) */}
          {revisit > 0 && onRevisit ? (
            <Tip text="После дозагрузки у этих записей изменились значения: решение принято по прежним — пересмотрите его">
              <button type="button" className="link count revisit-link" onClick={onRevisit}>
                пересмотреть: {revisit}
              </button>
            </Tip>
          ) : (
            <span className="count">5 таблиц</span>
          )}
        </div>
        <nav className="protocol-nav" aria-label="Таблицы протокола">
          {TABLES.map((t) => (
            <Tip key={t.key} text={t.hint} block>
              <button type="button" className="pnav" aria-current={t.key === table} onClick={() => onTable(t.key)}>
                <span className="n">{t.n}</span> {t.title} <span className="c">{counts[t.key]}</span>
              </button>
            </Tip>
          ))}
        </nav>
        {table === "candidates" && finished && (
          <div className="list-done small">
            Все кандидаты решены: подтверждено {finished.confirmed}, отклонено {finished.rejected}
            {finished.clarification ? `, на уточнении ${finished.clarification}` : ""}
            {finished.revisit ? `; пересмотреть ${finished.revisit}` : ""}.
            {onToFinalize && (
              <>
                {" "}
                <button type="button" className="link" onClick={onToFinalize}>
                  к финализации
                </button>
              </>
            )}
          </div>
        )}
        <div className="list" role="listbox" aria-label={spec.title} ref={listRef}>
          {rows.length === 0 && <div className="empty-state">{empty ?? spec.empty}</div>}
          {rows.map((f, i) => {
            const verdict = VERDICT[f.verification_status];
            const weight = criticalityWeight(f.criticality);
            // В таблице 2 кроме ждущих решения стоят записи на уточнении: к ним инспектор ещё
            // вернётся, поэтому они не зачёркнуты, а собраны под своим подзаголовком (п. 10).
            const clarifyStart =
              table === "candidates" &&
              f.verification_status === "CLARIFICATION_REQUIRED" &&
              rows[i - 1]?.verification_status !== "CLARIFICATION_REQUIRED";
            const clarifying = clarifyStart ? rows.filter((r) => r.verification_status === "CLARIFICATION_REQUIRED").length : 0;
            // то же правило, что у счётчика «пересмотреть»: запись с решением и изменившимися значениями
            const stale =
              !!f.changed_after_decision && ["CONFIRMED_VIOLATION", "NEGATIVE_VERIFIED", "CLARIFICATION_REQUIRED"].includes(f.verification_status);
            const focusable = f.id === activeId || (!rows.some((r) => r.id === activeId) && i === 0);
            return (
              <div key={f.id} role="presentation">
              {clarifyStart && (
                <div className="list-sub" role="presentation">
                  На уточнении · {clarifying}
                </div>
              )}
              <button
                type="button"
                role="option"
                aria-selected={f.id === activeId}
                aria-current={f.id === activeId}
                tabIndex={focusable ? 0 : -1}
                className="row"
                onClick={() => onSelect(f.id)}
              >
                <span className="row-top">
                  <span>{f.parameter_code}</span>
                  {(f.locations.length ? f.locations : [f.location ?? ""]).slice(0, 3).map((l) =>
                    l ? (
                      <span key={l} className="room">
                        {l}
                      </span>
                    ) : null,
                  )}
                  {f.locations.length > 3 && <span className="muted">+{f.locations.length - 3}</span>}
                  {verdict && <span className={`verdict v-${verdict.tone}`}>{verdict.glyph}</span>}
                  {/* мини-пометки (#80): решение специалиста по виду и уверенность ниже высокой — значком с подсказкой */}
                  {f.specialist && <SpecialistMark specialist={f.specialist} />}
                  {f.confidence && <ConfidenceMark confidence={f.confidence} />}
                  {stale && (
                    <span className="row-stale" title="После решения значения изменились — пересмотрите решение">
                      значения изменились
                    </span>
                  )}
                  {/* решение вернула пересборка: расхождения больше нет, решает инспектор */}
                  {f.reopened && f.verification_status === "PENDING" && (
                    <span className="row-stale" title="После дозагрузки автоматика расхождения больше не видит — прежнее решение вернулось к вам">
                      решить заново
                    </span>
                  )}
                  {weight && <span className={`crit ${weight}`}>{weight === "high" ? "критическое" : "существенное"}</span>}
                </span>
                <span className="row-title">{f.title ?? f.detail ?? f.finding_id}</span>
              </button>
              </div>
            );
          })}
          {table === "completeness" && rejectedFiles.length > 0 && (
            <button type="button" className="row" onClick={onRejectedFiles}>
              <span className="row-top">
                <span>ФАЙЛЫ</span>
                <span className="tag">REJECTED</span>
              </span>
              <span className="row-title">Не принято при загрузке: {rejectedFiles.length}</span>
            </button>
          )}
        </div>
      </section>

      <FoldPane
        id="loads"
        title="Комплектность"
        digest={loadsDigest}
        attention={missing.length > 0}
      >
        {loads.map((l) => (
          <div key={l.stage} className={`status-row${l.state === "MISSING" ? " hatched" : ""}`}>
            <span>
              {STAGE_NAME[l.stage]} {UPLOAD_STATE[l.state]}
            </span>
            <span className="tag">{`${l.stage}_${l.state}`}</span>
            {l.state !== "MISSING" && <span className="why">Принято файлов: {l.files}</span>}
          </div>
        ))}
      </FoldPane>

      {/* Полнота обработки документации (#39, переименовано в #74): на что опирается вывод.
          Без этих чисел объект, прочитанный только по текстовому слою, выглядит так же, как
          прочитанный целиком. Прежнее название «Готовность объекта» в надзоре значит
          строительную готовность — процент выполненных работ, а не качество разбора. */}
      {readiness && (
        // Свёрнут при каждом заходе: блок нужен, когда что-то чинят, а раскрытый однажды
        // оставался раскрытым навсегда и занимал колонку списка записей.
        <FoldPane
          id="readiness"
          remember={false}
          title="Полнота обработки документации"
          digest={readyNotes.length ? readyNotes.join(" · ") : "в норме"}
          attention={readyNotes.length > 0}
          action={
            <span className="fold-actions">
              {onLog && (
                <button type="button" className="link" onClick={onLog}>
                  журнал
                </button>
              )}
              <button type="button" className="link" onClick={() => onFiles()}>
                файлы
              </button>
            </span>
          }
        >
          <div className={`status-row${share > 20 ? " hatched" : ""}`}>
            <span>Страниц с прочитанным текстом</span>
            <span className="tag">{readiness.pages - readiness.pages_without_text} из {readiness.pages}</span>
            {readiness.pages_without_text > 0 && <span className="why">Без текста: {share}%</span>}
          </div>
          <div className={`status-row${readiness.stage_unknown > 0 ? " hatched" : ""}`}>
            <span>Файлов без стадии</span>
            <span className="tag">{readiness.stage_unknown}</span>
            {readiness.stage_unknown > 0 && (
              <span className="why">
                В сравнение стадий не попадают{" "}
                <button type="button" className="link" onClick={() => onFiles("unknown")}>
                  задать стадию
                </button>
              </span>
            )}
          </div>
          {/* Раздел задаётся в реестре, и найти там нужные файлы среди сотен — отдельная работа:
              строка ведёт сразу в отбор «без раздела» (#74, п. 2.3). */}
          <div className="status-row">
            <span>Файлов без раздела</span>
            <span className="tag">{readiness.section_other}</span>
            {readiness.section_other > 0 ? (
              <span className="why">
                Правила с разделом-источником их не прочитают{" "}
                <button type="button" className="link" onClick={() => onFiles("nosection")}>
                  задать раздел
                </button>
              </span>
            ) : (
              readiness.unsupported > 0 && <span className="why">Формат вне разбора: {readiness.unsupported}</span>
            )}
          </div>
          {pendingEdits > 0 && (
            <div className="status-row hatched">
              <span>Правки файлов не в протоколе</span>
              <span className="tag">{pendingEdits}</span>
              <span className="why">
                Стадия, раздел или редакция заданы после сборки протокола{" "}
                <button type="button" className="link" onClick={() => onFiles()}>
                  какие
                </button>
                {onRebuild && (
                  <>
                    {" · "}
                    <button type="button" className="link" onClick={onRebuild}>
                      пересобрать протокол
                    </button>
                  </>
                )}
              </span>
            </div>
          )}
          {/* Сравнение редакций (#81): строка появляется, только когда есть что показать, и ведёт
              в тот же отбор реестра, что и «Редакции»: там у файла — «что изменилось». */}
          {unmarked > 0 && (
            <div className="status-row hatched">
              <span>Листов изменено без отметки</span>
              <span className="tag">{unmarked}</span>
              <span className="why">
                Номера изменения нет ни в штампе, ни в ведомости{" "}
                <button type="button" className="link" onClick={() => onFiles("revisions")}>
                  к редакциям
                </button>
              </span>
            </div>
          )}
          <div className={`status-row${readiness.ocr_enabled === false && readiness.pages_without_text > 0 ? " hatched" : ""}`}>
            <span>Способ чтения</span>
            <span className="tag">
              {readiness.reading_mode
                ? READING_MODE[readiness.reading_mode] ?? readiness.reading_mode
                : `${readiness.ocr_enabled ? "OCR" : "без OCR"} · ${readiness.model_enabled ? "модель" : "без модели"}`}
            </span>
            {readiness.model_name && <span className="why">Модель: {readiness.model_name}</span>}
            {readiness.ocr_enabled === false && readiness.pages_without_text > 0 && (
              <span className="why">Сканы прочитаны не будут</span>
            )}
          </div>
          {readiness.read_seconds != null && (
            <div className={`status-row${modelSilenceHurts ? " hatched" : ""}`}>
              <span>Чтение заняло</span>
              <span className="tag">{duration(readiness.read_seconds)}</span>
              {readiness.model_calls ? (
                <span className="why">
                  {/* Счётчик зацикливаний убран с экрана инспектора (#74, п. 4.2): «зациклилась»
                      читается как сбой платформы. Сколько вызовов осталось без ответа, видно
                      из «ответила X из Y», а разбор причин — дело журнала и админки. */}
                  Модель ответила {readiness.model_answered ?? 0} из {readiness.model_calls}
                  {modelSilenceHurts ? " — эти страницы прочитаны только распознаванием" : ""}
                </span>
              ) : null}
            </div>
          )}
          {/* Сырые числа чтения — администратору (#74, п. 4.2): инспектору они читаются как сбой.
              Повторный разбор зовёт модель только там, где её ответа в источниках страницы нет,
              то есть добирает именно эти страницы, а остальное берёт из кеша. */}
          {canRetryRead && silentCalls > 0 && (
            <div className="status-row">
              <span>Модель не ответила</span>
              <span className="tag">
                {silentCalls} из {modelCalls}
              </span>
              <span className="why">
                Зациклилась {readiness.model_looped ?? 0}, остальное — обрыв или отказ провайдера.{" "}
                {onRetryRead && (
                  <Tip text="Перечитать эти страницы: модель зовётся только там, где ответа нет, остальное берётся из кеша, решения инспектора сохраняются">
                    <button type="button" className="link" onClick={onRetryRead}>
                      перечитать
                    </button>
                  </Tip>
                )}
              </span>
            </div>
          )}
          {/* Дозагрузка не пересчитывает объект заново (#60): видно, что пересчитано,
              а что перенесено из прошлой версии вместе с решениями инспектора */}
          {recompute && !recompute.full && (
            <div className="status-row">
              <span>Последняя дозагрузка</span>
              <span className="tag">
                пересчитано {recompute.recomputed}, перенесено {recompute.carried_over}
              </span>
              <span className="why">
                Прочитано документов: {recompute.documents_read}
                {recompute.documents_total ? ` из ${recompute.documents_total}` : ""}
              </span>
            </div>
          )}
        </FoldPane>
      )}
    </div>
  );
}
