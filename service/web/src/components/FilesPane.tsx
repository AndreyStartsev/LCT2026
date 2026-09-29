import { useMemo, useState } from "react";
import { api, openInTab, sourceUrl, type FileItem, type RevisionPair } from "../api";
import { bytes, DOC_SECTIONS, DOC_STAGES, REVISION_LABEL, when } from "../labels";
import { pendingEdits } from "../protocol";
import Tip from "./Tip";

interface Props {
  processId: string;
  files: FileItem[];
  /** правка разрешена, пока протокол не финализирован и не идёт обработка */
  editable: boolean;
  busy: boolean;
  onChanged: () => void;
  onRebuild: () => void;
  /** Пересборку не предлагать: идёт загрузка в этот процесс, и разбор оборвал бы её следующий пакет. */
  rebuildBlocked?: string | null;
  onError: (message: string) => void;
  /** Показать, что система прочитала в файле: текст страниц и чем каждая прочитана (#52). */
  onShowText: (fileId: string, title: string) => void;
  /** Отбор задаёт экран: по строкам готовности в левой колонке инспектор попадает сразу в нужный (#74). */
  filter: Filter;
  onFilter: (filter: Filter) => void;
  /** Открыть журнал аудита; не задан — журнала у этой роли нет (он для администратора). */
  onAudit?: () => void;
  /** Пары редакций (#81): у файла новой редакции — ссылка «что изменилось». */
  revisions?: RevisionPair[];
  /** Когда собрана последняя версия протокола: правки новее неё в протокол ещё не вошли (п. 11). */
  builtAt?: string | null;
  onShowChanges?: (fileId: string, title: string) => void;
}

export type Filter = "all" | "unknown" | "nosection" | "revisions" | "rejected";

const STAGE_LABEL: Record<string, string> = Object.fromEntries(DOC_STAGES.map((s) => [s.code, s.label]));

/** Стадия файла или пусто: разбор пишет «UNKNOWN», когда не смог определить её по пути. */
const stageOf = (f: FileItem) => (f.doc_stage && f.doc_stage !== "UNKNOWN" ? f.doc_stage : "");
const sectionOf = (f: FileItem) => (f.discipline && f.discipline !== "OTHER" ? f.discipline : "");

/**
 * Пустая стадия или раздел. «Не определена» — разбор не смог определить. «По разбору» — значения
 * ещё нет, его даст разбор: файл не разобран или ручной выбор снят (до повторного разбора стадия
 * и раздел такого файла пусты). Тем же вариантом ручной выбор и снимается.
 */
const noStage = (f: FileItem) => (f.status === "ACCEPTED" && !f.doc_stage ? "по разбору" : "не определена");
const noSection = (f: FileItem) => (f.status === "ACCEPTED" && !f.discipline ? "по разбору" : "не определён");

/**
 * Откуда стадия и раздел файла. Ручной выбор — с тем, кто и когда его сделал. Снятый выбор виден,
 * пока протокол не пересобран; после пересборки стадия и раздел снова от разбора.
 */
function stageNote(f: FileItem, editedAfterBuild: boolean): string {
  const who = f.manual_by ? `: ${f.manual_by} · ${when(f.manual_at ?? null)}` : "";
  if (f.stage_manual && f.section_manual) return `стадия и раздел заданы вручную${who}`;
  if (f.stage_manual) return `стадия задана вручную${who}`;
  if (f.section_manual) return `раздел задан вручную${who}`;
  if (f.manual_by && editedAfterBuild) return `ручной выбор снят${who}`;
  return "стадия по названиям папок";
}

/**
 * Раздел проекта есть у проектной и рабочей документации; у исполнительной его не бывает —
 * акт освидетельствования или протокол испытаний не относится к АР или ОВ. Поэтому в отбор
 * «без раздела» попадают только те файлы, которым раздел действительно нужен: правила
 * с разделом-источником читают именно их (#74, п. 2.3).
 */
const SECTION_STAGES = new Set(["PD", "RD", "RD_ID_MIXED"]);
const needsSection = (f: FileItem) =>
  f.status === "ACCEPTED" && !sectionOf(f) && SECTION_STAGES.has(stageOf(f));

/**
 * Файлы процесса со стадией и разделом. Задача #39: на чужом оформлении папок стадия
 * не определяется, документ без стадии выпадает из сравнения, и поправить её было негде.
 * Правка пишется в журнал аудита, разбор её не перезаписывает, но в протокол она попадает
 * только после повторного разбора — об этом говорит строка под таблицей.
 */
export default function FilesPane({
  processId,
  files,
  editable,
  busy,
  onChanged,
  onRebuild,
  rebuildBlocked,
  onError,
  onShowText,
  filter,
  onFilter,
  onAudit,
  revisions = [],
  onShowChanges,
  builtAt,
}: Props) {
  const [saving, setSaving] = useState<string | null>(null);
  // какой файл сейчас открывается и на сколько процентов: том весит десятки мегабайт
  const [opening, setOpening] = useState<{ key: string; percent: number } | null>(null);
  // Правки новее сборки протокола — по времени правки, а не по флажку экрана: флажок
  // пропадал при уходе в карточку, а правка так и не входила в протокол (п. 11).
  const waiting = useMemo(() => new Set(pendingEdits(files, builtAt).map((f) => f.relative_path)), [files, builtAt]);
  // стадия или раздел правлены после сборки протокола — по тому же времени правки, что и у pendingEdits
  const built = builtAt ? Date.parse(builtAt) : NaN;
  const stageEditedAfterBuild = (f: FileItem) => !!f.manual_at && Date.parse(f.manual_at) > built;

  // цепочки из нескольких редакций: файлы с общим chain_id (#10)
  const chainSize = useMemo(() => {
    const out: Record<string, number> = {};
    for (const f of files) if (f.chain_id) out[f.chain_id] = (out[f.chain_id] ?? 0) + 1;
    return out;
  }, [files]);
  const inChain = (f: FileItem) => Boolean(f.chain_id && chainSize[f.chain_id] > 1);
  // пара, где файл — новая редакция: с чем его сравнили (#81)
  const pairOf = useMemo(() => {
    const out: Record<string, RevisionPair> = {};
    for (const p of revisions) out[p.new_file_id] = p;
    return (f: FileItem) => (f.file_id ? out[f.file_id] : undefined);
  }, [revisions]);
  const unresolved = (f: FileItem) => f.revision_status === "CLARIFICATION_REQUIRED";

  const counts = useMemo(
    () => ({
      all: files.length,
      unknown: files.filter((f) => f.status === "ACCEPTED" && !stageOf(f)).length,
      nosection: files.filter(needsSection).length,
      // исполнительная документация без раздела: в отбор не идёт, но объяснить её нужно
      nosection_id: files.filter((f) => f.status === "ACCEPTED" && !sectionOf(f) && !SECTION_STAGES.has(stageOf(f))).length,
      revisions: files.filter((f) => f.status === "ACCEPTED" && unresolved(f)).length,
      rejected: files.filter((f) => f.status === "REJECTED").length,
    }),
    [files],
  );
  /** «Журнал аудита» в пояснениях: администратору — ссылка, остальным — подсказка, где он. */
  const Journal = () =>
    onAudit ? (
      <button type="button" className="link" onClick={onAudit}>
        журнал аудита
      </button>
    ) : (
      <Tip text="Кто, что и когда поправил, записывается в журнал аудита. Открыть его может администратор">
        <span className="hintword">журнал аудита</span>
      </Tip>
    );

  const rows = useMemo(
    () =>
      files.filter((f) =>
        filter === "unknown"
          ? f.status === "ACCEPTED" && !stageOf(f)
          : filter === "nosection"
          ? needsSection(f)
          : filter === "revisions"
            ? f.status === "ACCEPTED" && inChain(f)
            : filter === "rejected"
              ? f.status === "REJECTED"
              : true,
      ),
    [files, filter],
  );

  async function set(file: FileItem, body: { doc_stage?: string; section?: string }) {
    const key = file.file_id ?? file.relative_path;
    setSaving(key);
    try {
      await api.setFileStage(processId, key, body);
      onChanged();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setSaving(null);
    }
  }

  async function choose(file: FileItem, authoritative: boolean) {
    const key = file.file_id ?? file.relative_path;
    setSaving(key);
    try {
      await api.setFileRevision(processId, key, { authoritative });
      onChanged();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setSaving(null);
    }
  }

  return (
    <>
      <div className="pane-head">
        <h2>Файлы объекта</h2>
        <span className="count">{rows.length}</span>
      </div>
      <div className="card-body">
        <div className="filters" role="group" aria-label="Отбор файлов">
          {([
            ["all", `Все — ${counts.all}`],
            ["unknown", `Без стадии — ${counts.unknown}`],
            ["nosection", `Без раздела — ${counts.nosection}`],
            ["revisions", `Редакции — ${counts.revisions ? `уточнить ${counts.revisions}` : "в цепочках"}`],
            ["rejected", `Не приняты — ${counts.rejected}`],
          ] as [Filter, string][]).map(([key, label]) => (
            <button key={key} type="button" className="btn" aria-current={filter === key} onClick={() => onFilter(key)}>
              {label}
            </button>
          ))}
        </div>

        {/* Пояснения идут колонками по ширине блока: одной строкой на всю таблицу их
            не прочитать, а в одной узкой колонке они оставляли половину блока пустой. */}
        {(filter === "all" || filter === "unknown") && (
          <div className="explain-row">
            <p className="lede">
              Стадия определяется по названиям папок. Если её не удалось определить, документ в сравнение стадий
              не попадает.
            </p>
            <p className="lede">
              Задайте стадию здесь: правка идёт в <Journal />, разбор её не перезаписывает и учтёт при повторном
              разборе — кнопка под таблицей. Вариант «по разбору» снимает ручной выбор.
            </p>
          </div>
        )}
        {filter === "nosection" && (
          <div className="explain-row">
            <p className="lede">
              Раздел определяется по названиям папок и штампу. Файл без раздела не прочитают правила, у которых
              раздел задан источником.
            </p>
            <p className="lede">
              Задайте раздел здесь: правка уйдёт в <Journal /> и вступит в силу после повторного разбора — его
              запускает кнопка «Пересобрать протокол» под таблицей.
            </p>
            {counts.nosection_id > 0 && (
              <p className="lede">
                Исполнительной документации это не касается: ещё {counts.nosection_id} файлов без раздела — акты
                и протоколы испытаний, раздела проекта у них не бывает, и в этот отбор они не попадают.
              </p>
            )}
          </div>
        )}
        {filter === "revisions" && (
          <div className="explain-row">
            <p className="lede">Редакции одного документа собраны в цепочку, сравнение идёт по актуальной.</p>
            <p className="lede">
              Там, где порядок редакций не определён («требует уточнения»), записи сравнения ждут решения.
            </p>
            <p className="lede">
              Назовите актуальную редакцию — выбор уйдёт в <Journal /> и вступит в силу после повторного разбора,
              кнопка под таблицей.
            </p>
            <p className="lede">
              «Что изменилось» — сравнение с предыдущей редакцией: листы, где изменилось содержание, и отмечено ли
              изменение в штампе листа и в ведомости рабочих чертежей.
            </p>
          </div>
        )}

        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Файл</th>
                <th>Стадия</th>
                <th>Раздел</th>
                <th>Редакция</th>
                <th className="num">Страниц</th>
                <th>Текст</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((f) => {
                const key = f.file_id ?? f.relative_path;
                const rejected = f.status === "REJECTED";
                return (
                  <tr key={f.relative_path} className={rejected ? "muted" : undefined}>
                    <td>
                      <div className="cell-title">
                        {f.relative_path.split("/").pop()}
                        {/* Исходный файл целиком (#74, п. 2.2): чтобы задать раздел или понять,
                            что это за том, инспектору нужно увидеть штамп, а не только имя. */}
                        {!rejected && f.file_id && (
                          <Tip text="Открыть исходный файл: PDF — просмотрщиком браузера, остальные форматы браузер скачает. Большой том грузится не мгновенно — ход виден в новой вкладке">
                            <button
                              type="button"
                              className="link"
                              aria-label={`Открыть исходный файл ${f.relative_path}`}
                              disabled={opening !== null}
                              onClick={() => {
                                setOpening({ key, percent: 0 });
                                openInTab(sourceUrl(processId, f.file_id as string), "", (done, total) =>
                                  setOpening({ key, percent: Math.round((done / total) * 100) }),
                                )
                                  .catch((e) => onError(`Исходный файл не открылся: ${(e as Error).message}`))
                                  .finally(() => setOpening(null));
                              }}
                            >
                              {opening?.key === key ? `открываю… ${opening.percent} %` : "открыть файл"}
                            </button>
                          </Tip>
                        )}
                      </div>
                      <div className="mono small muted">
                        {f.file_id ?? "без идентификатора"} · {f.relative_path}
                        {f.size_bytes ? ` · ${bytes(f.size_bytes)}` : ""}
                      </div>
                      <div className="small muted">
                        {rejected ? (
                          <>
                            <span className="tag">{f.reject_code}</span> {f.reject_message}
                          </>
                        ) : (
                          stageNote(f, stageEditedAfterBuild(f))
                        )}
                        {waiting.has(f.relative_path) && (
                          <>
                            {" "}
                            <span className="tag tag-wait" title="Правка сделана после сборки протокола: в протокол она войдёт после пересборки">
                              ждёт пересборки
                            </span>
                          </>
                        )}
                      </div>
                    </td>
                    <td>
                      {rejected || !editable ? (
                        <span className={stageOf(f) ? "mono small" : "mono small absent"}>
                          {stageOf(f) ? STAGE_LABEL[stageOf(f)] ?? f.doc_stage : noStage(f)}
                        </span>
                      ) : (
                        <select
                          className="pick"
                          aria-label={`Стадия файла ${f.relative_path}`}
                          value={f.stage_manual || stageOf(f)}
                          disabled={busy || saving === key}
                          onChange={(e) => set(f, { doc_stage: e.target.value })}
                        >
                          {/* Пустой вариант у ручного значения — «по разбору», он снимает выбор. У стадии,
                              которую разбор определил сам, снимать нечего: пустого варианта нет. */}
                          {(f.stage_manual || !stageOf(f)) && (
                            <option value="">{f.stage_manual ? "по разбору" : noStage(f)}</option>
                          )}
                          {DOC_STAGES.map((s) => (
                            <option key={s.code} value={s.code}>
                              {s.label}
                            </option>
                          ))}
                        </select>
                      )}
                    </td>
                    <td>
                      {rejected || !editable ? (
                        <span className="mono small">{sectionOf(f) || noSection(f)}</span>
                      ) : (
                        <select
                          className="pick"
                          aria-label={`Раздел файла ${f.relative_path}`}
                          value={f.section_manual || sectionOf(f)}
                          disabled={busy || saving === key}
                          onChange={(e) => set(f, { section: e.target.value })}
                        >
                          {(f.section_manual || !sectionOf(f)) && (
                            <option value="">{f.section_manual ? "по разбору" : noSection(f)}</option>
                          )}
                          {DOC_SECTIONS.map((s) => (
                            <option key={s.code} value={s.code}>
                              {s.label}
                            </option>
                          ))}
                        </select>
                      )}
                    </td>
                    <td>
                      {rejected || !f.chain_id ? (
                        <span className="mono small muted">{f.revision ?? "—"}</span>
                      ) : (
                        <div className="small">
                          <span className="mono">{f.revision ?? "без отметки"}</span>
                          {inChain(f) && (
                            <>
                              {" "}
                              <span className={unresolved(f) ? "tag tag-clarify" : "tag"}>
                                {f.revision_manual
                                  ? "актуальная, выбор инспектора"
                                  : (REVISION_LABEL[f.revision_status ?? ""] ?? f.revision_status ?? "в цепочке")}
                              </span>
                              {editable && (
                                <>
                                  {" "}
                                  <button
                                    type="button"
                                    className="link"
                                    disabled={busy || saving === key}
                                    aria-label={`${f.revision_manual ? "Снять выбор" : "Считать актуальной"}: ${f.relative_path}`}
                                    onClick={() => choose(f, !f.revision_manual)}
                                  >
                                    {f.revision_manual ? "снять выбор" : "считать актуальной"}
                                  </button>
                                </>
                              )}
                            </>
                          )}
                          {f.revision_manual_by && (
                            <div className="muted">
                              выбор: {f.revision_manual_by} · {when(f.revision_manual_at ?? null)}
                            </div>
                          )}
                          {pairOf(f) && onShowChanges && (
                            <div>
                              <Tip
                                text={`Сравнение с предыдущей редакцией${pairOf(f)!.old_revision ? ` (${pairOf(f)!.old_revision})` : ""}: изменённые листы и отметки изменений`}
                              >
                                <button
                                  type="button"
                                  className="link"
                                  onClick={() => onShowChanges(f.file_id as string, f.relative_path.split("/").pop() ?? f.relative_path)}
                                >
                                  что изменилось
                                </button>
                              </Tip>
                              {pairOf(f)!.unmarked > 0 && (
                                <>
                                  {" "}
                                  <Tip text="Содержание листа изменилось, а номера нового изменения нет ни в штампе листа, ни в ведомости">
                                    <span className="tag tag-clarify">без отметки: {pairOf(f)!.unmarked}</span>
                                  </Tip>
                                </>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="num mono small">{f.pdf_pages ?? "—"}</td>
                    <td>
                      {!rejected && f.file_id && (
                        <button
                          type="button"
                          className="link"
                          onClick={() => onShowText(f.file_id as string, f.relative_path.split("/").pop() ?? f.relative_path)}
                        >
                          что прочитано
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Где запускается повторный разбор, видно всегда, а не только после правки: в пояснениях
            сказано «вступит в силу после повторного разбора», и кнопка должна быть под рукой (#74). */}
        <div className={waiting.size ? "note-line job-line" : "foot-note job-line"}>
          <span>
            {waiting.size
              ? `Правок, которые ещё не вошли в протокол: ${waiting.size} — они отмечены «ждёт пересборки». В протокол они попадут после повторного разбора.`
              : "Ручные стадии, разделы и выбранные редакции вступают в силу после повторного разбора: файлы и прочитанный текст берутся из кеша, заново считаются сравнение и протокол."}
          </span>
          <Tip
            text="Запустить разбор заново: файлы и текст берутся из кеша, пересчитываются сравнение и протокол; решения инспектора сохранятся"
            place="above"
          >
            <button
              type="button"
              className="btn"
              disabled={busy || !editable || !!rebuildBlocked}
              title={rebuildBlocked ?? undefined}
              onClick={onRebuild}
            >
              Пересобрать протокол
            </button>
          </Tip>
        </div>
      </div>
    </>
  );
}
