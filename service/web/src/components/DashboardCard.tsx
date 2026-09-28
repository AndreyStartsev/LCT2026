import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { api, type CellState, type Dashboard, type ObjectItem } from "../api";
import { STAGE, when } from "../labels";
import { lightOf, syncText } from "../protocol";
import LinksTab from "./LinksTab";

interface Props {
  item: ObjectItem;
  onClose: () => void;
  /** Открыть проверку объекта; с записью или таблицей протокола — сразу на ней. */
  onOpen: (processId: string, where?: { finding?: string; table?: string }) => void;
}

/**
 * Состояния клетки в порядке важности: что требует внимания — первым. Цвет несут только три
 * состояния с исходом сравнения; остальные — фактура, как отсутствие элемента на чертеже.
 * Палитра проверена на различимость при дальтонизме (ΔE ≥ 9 между цветными состояниями),
 * и каждое цветное состояние помечено знаком: карта читается и в чёрно-белой печати.
 */
const STATES: { key: CellState; label: string; text: string; glyph?: string }[] = [
  { key: "VIOLATION", label: "Нарушение", text: "подтверждено нарушение", glyph: "!" },
  { key: "CANDIDATE", label: "Кандидат", text: "кандидат ждёт решения инспектора", glyph: "?" },
  { key: "CLEAN", label: "Без замечаний", text: "сопоставлено, расхождения нет", glyph: "✓" },
  { key: "NOT_COMPARABLE", label: "Несопоставимо", text: "источники нельзя сопоставить" },
  { key: "MISSING_EVIDENCE", label: "Нет доказательств", text: "нет документа или доказательного фрагмента" },
  { key: "NOT_APPLICABLE", label: "Неприменимо", text: "параметр к объекту неприменим" },
  // Нейтрально, без «не реализовано»: инспектору важно, что параметр на объекте не сверялся,
  // а не как устроена разработка правил
  { key: "NOT_CHECKED", label: "Не проверено", text: "не проверено" },
  // Своим цветом: такие параметры не проверяются по документам вовсе — это не пробел в правилах,
  // а решение, и причина у каждого своя (внешняя система стадии строительства, отказ по замеру)
  { key: "OUT_OF_SCOPE", label: "Вне проверки документов", text: "по документам не проверяется" },
  // Черновик правила (#95): правило ждёт решения специалиста, его нарушения — гипотезы
  { key: "HYPOTHESIS", label: "Черновик правила", text: "проверено черновиком правила — нарушения гипотезами" },
];
const STATE = Object.fromEntries(STATES.map((s) => [s.key, s])) as Record<CellState, (typeof STATES)[number]>;

function Swatch({ state }: { state: CellState }) {
  return (
    <span className={`hm-cell hm-${state} hm-swatch`} aria-hidden="true">
      {STATE[state].glyph}
    </span>
  );
}

function percent(n: number, total: number): string {
  if (!total) return "0";
  const p = (n / total) * 100;
  return p > 0 && p < 1 ? "<1" : String(Math.round(p * 10) / 10).replace(".", ",");
}

/**
 * Дашборд объекта (#83): протокол одним экраном. Вывод и главные числа, стадии, карта всех
 * 132 параметров Матрицы по разделам, решения инспектора и изменения к прошлой версии.
 * Всё только для чтения: решение по записи принимается в карточке записи, щелчок по клетке
 * ведёт туда, и путь решения не удлиняется (правило трёх кликов).
 */
export default function DashboardCard({ item, onClose, onOpen }: Props) {
  const process = item.last_process!;
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [focus, setFocus] = useState<CellState | null>(null);
  const [active, setActive] = useState(0);
  const [hovered, setHovered] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);
  const [tab, setTab] = useState<"summary" | "links">("summary");
  // Карта группируется по разделам Матрицы или по очередям правил (#83): разделы понятнее
  // инспектору, очереди — тому, кто следит за тем, какие правила уже написаны
  const [groupBy, setGroupBy] = useState<"section" | "queue">("section");
  const cellRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    let alive = true;
    api
      .summary(process.process_id)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError((e as Error).message));
    return () => {
      alive = false;
    };
  }, [process.process_id]);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Клетки по разделам в порядке Матрицы или по очередям; индекс клетки — сквозной, для клавиатуры
  const rows = useMemo(() => {
    if (!data) return [];
    if (groupBy === "queue") {
      const queues = [...new Set(data.cells.map((c) => c.queue ?? 0))].sort((a, b) => a - b);
      return queues.map((q) => {
        const cells = data.cells.map((c, i) => (c.queue === q ? i : -1)).filter((i) => i >= 0);
        const sections = [...new Set(cells.map((i) => data.cells[i].section ?? "—"))];
        const compared = cells.filter((i) => data.cells[i].group === "COMPARED").length;
        return {
          section: q ? `Очередь ${q}` : "Без очереди",
          hint: sections.join(", "),
          cells,
          compared,
          stats: undefined as Dashboard["sections"][number] | undefined,
        };
      });
    }
    const order = data.sections.map((s) => s.section);
    const groups = new Map<string, number[]>();
    data.cells.forEach((c, i) => {
      const key = c.section ?? "—";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(i);
    });
    const known = order.filter((s) => groups.has(s));
    const rest = [...groups.keys()].filter((s) => !known.includes(s));
    return [...known, ...rest].map((section) => {
      const stats = data.sections.find((s) => s.section === section);
      return { section, hint: "", cells: groups.get(section)!, compared: stats?.compared ?? 0, stats };
    });
  }, [data, groupBy]);

  // группы, которых на старых протоколах нет: графа таблицы — только если такие параметры есть
  const extraGroups = useMemo(
    () =>
      (
        [
          { key: "not_applicable", title: "Неприменимо" },
          { key: "out_of_scope", title: "Вне проверки" },
          { key: "hypothesis", title: "Черновик" },
        ] as const
      ).filter((g) => data?.sections.some((s) => (s[g.key] ?? 0) > 0)),
    [data],
  );

  const counts = useMemo(() => {
    const out = Object.fromEntries(STATES.map((s) => [s.key, 0])) as Record<CellState, number>;
    data?.cells.forEach((c) => (out[c.state] += 1));
    return out;
  }, [data]);

  const { light, label } = lightOf(item);
  const f = process.findings;
  const decided = f ? f.candidates - f.pending : 0;
  const busy = process.processing?.state === "QUEUED" || process.processing?.state === "RUNNING";
  // Раскладка записей по пяти таблицам — как на экране проверки (protocol.ts, tableOf):
  // из счётчиков статуса процесса, без загрузки самих записей
  const tables = f
    ? (() => {
        const candidates = f.pending + f.clarification;
        const negatives = f.rejected + f.no_violation;
        return {
          candidates,
          confirmed: f.confirmed,
          negatives,
          hypotheses: f.hypotheses,
          completeness: Math.max(0, f.total - f.split - candidates - f.confirmed - negatives - f.hypotheses),
        };
      })()
    : { completeness: 0, candidates: 0, confirmed: 0, negatives: 0, hypotheses: 0 };

  function openCell(i: number) {
    const cell = data?.cells[i];
    if (cell?.finding) onOpen(process.process_id, { finding: cell.finding });
  }

  // Клавиатура: одна точка входа в карту, стрелками — по клеткам и разделам
  function onGridKey(e: KeyboardEvent<HTMLDivElement>) {
    if (!rows.length) return;
    const r = rows.findIndex((row) => row.cells.includes(active));
    const k = rows[r].cells.indexOf(active);
    let next = active;
    if (e.key === "ArrowRight") next = rows[r].cells[Math.min(k + 1, rows[r].cells.length - 1)];
    else if (e.key === "ArrowLeft") next = rows[r].cells[Math.max(k - 1, 0)];
    else if (e.key === "ArrowDown" && r < rows.length - 1) next = rows[r + 1].cells[Math.min(k, rows[r + 1].cells.length - 1)];
    else if (e.key === "ArrowUp" && r > 0) next = rows[r - 1].cells[Math.min(k, rows[r - 1].cells.length - 1)];
    else return;
    e.preventDefault();
    setActive(next);
    cellRefs.current[next]?.focus();
  }

  const shown = hovered ?? null;
  const cell = shown !== null ? data?.cells[shown] : null;
  const m = data?.matrix;

  return (
    <div className="viewer dash" role="dialog" aria-modal="true" aria-label={`Дашборд объекта: ${item.name}`}>
      <div className="viewer-head">
        <span className="viewer-title">Дашборд объекта · {item.name}</span>
        <span className="mono small muted">{item.object_id}</span>
        <div className="viewer-tools">
          <button type="button" className="btn" onClick={() => onOpen(process.process_id)}>
            Открыть проверку
          </button>
          <button type="button" className="btn" onClick={onClose}>
            Закрыть
          </button>
        </div>
      </div>

      <div className="dash-tabs" role="tablist" aria-label="Разделы дашборда">
        <button type="button" role="tab" aria-selected={tab === "summary"} onClick={() => setTab("summary")}>
          Сводка
        </button>
        <button type="button" role="tab" aria-selected={tab === "links"} onClick={() => setTab("links")}>
          Связи документов
        </button>
      </div>

      <div className="card-body dash-body">
        {tab === "links" && (
          <LinksTab processId={process.process_id} onOpenFinding={(id) => onOpen(process.process_id, { finding: id })} />
        )}
        {tab === "summary" && error && <div className="alert">{error}</div>}
        {tab === "summary" && !data && !error && <div className="empty-state">Сводка собирается…</div>}

        {tab === "summary" && data && m && (
          <>
            {/* Пока идёт обработка, карточка показывает прошлую версию и говорит об этом */}
            {busy && (
              <div className="note-line">
                Идёт обработка объекта: показана версия {data.protocol.version ?? "—"}, числа обновятся, когда она
                закончится.
              </div>
            )}
            {process.processing?.state === "FAILED" && (
              <div className="alert">
                Последняя обработка остановилась со сбоем
                {process.processing.error ? `: ${process.processing.error}` : ""}. Показана версия{" "}
                {data.protocol.version ?? "—"}.
              </div>
            )}
            <section className="dash-top">
              <div className="dash-verdict">
                <span className={`light light-${light}`} aria-hidden="true" />
                <div>
                  {/* вывод реестра — строками: «ждут решения: 7» и «подтверждено: 1» не рвутся на «·» */}
                  {label.split(" · ").map((part, i) => (
                    <div key={part} className={i === 0 ? "dash-verdict-text" : "dash-verdict-more"}>
                      {i === 0 ? part : part.charAt(0).toUpperCase() + part.slice(1)}
                    </div>
                  ))}
                  <div className="small muted">
                    протокол v{data.protocol.version ?? "—"} · {when(data.protocol.created_at)} ·{" "}
                    {data.protocol.status_text.toLowerCase()}
                  </div>
                  {data.scenario_text && <div className="small muted">сценарий: {data.scenario_text}</div>}
                </div>
              </div>
              <div className="dash-kpis">
                <div className="kpi">
                  <span className="kpi-label">Сопоставлено параметров</span>
                  <span className="kpi-value">
                    {m.compared}
                    <span className="kpi-of"> из {m.total}</span>
                  </span>
                  <span className="kpi-note">{percent(m.compared, m.total)} % Матрицы</span>
                </div>
                <div className="kpi">
                  <span className="kpi-label">
                    <Swatch state="VIOLATION" /> Подтверждённые нарушения
                  </span>
                  <span className="kpi-value">{data.records.confirmed ?? 0}</span>
                  <span className="kpi-note">
                    записей в итоге протокола
                    {data.records.confirmed_free ? ` · гипотез вне Матрицы: ${data.records.confirmed_free}` : ""}
                  </span>
                </div>
                <div className="kpi">
                  <span className="kpi-label">
                    <Swatch state="CANDIDATE" /> Ждут решения
                  </span>
                  <span className="kpi-value">{f?.pending ?? data.records.candidate ?? 0}</span>
                  <span className="kpi-note">записей · на уточнении {f?.clarification ?? data.records.clarification ?? 0}</span>
                </div>
                <div className="kpi">
                  <span className="kpi-label">
                    <Swatch state="CLEAN" /> Проверено без замечаний
                  </span>
                  <span className="kpi-value">{data.records.negative ?? 0}</span>
                  <span className="kpi-note">записей</span>
                </div>
              </div>
            </section>

            {/* Пять таблиц протокола — те же числа, что в левой колонке экрана проверки;
                щелчок открывает проверку на этой таблице */}
            {f && (
              <nav className="dash-tables" aria-label="Таблицы протокола">
                {[
                  { key: "completeness", n: 1, title: "Комплектность и сопоставимость", count: tables.completeness },
                  { key: "candidates", n: 2, title: "Кандидаты в нарушения", count: tables.candidates },
                  { key: "confirmed", n: 3, title: "Подтверждённые нарушения", count: tables.confirmed },
                  { key: "negatives", n: 4, title: "Проверенные отрицательные", count: tables.negatives },
                  { key: "hypotheses", n: 5, title: "Гипотезы", count: tables.hypotheses },
                ].map((t) => (
                  <button
                    key={t.key}
                    type="button"
                    className="dash-table"
                    onClick={() => onOpen(process.process_id, { table: t.key })}
                  >
                    <span className="dash-table-n">{t.n}</span>
                    <span className="dash-table-title">{t.title}</span>
                    <span className="dash-table-count">{t.count}</span>
                  </button>
                ))}
              </nav>
            )}

            <section className="dash-stages" aria-label="Загрузка стадий">
              {data.stages.map((s) => (
                <div key={s.stage} className={`dash-stage${s.status.endsWith("_MISSING") ? " hatched" : ""}`}>
                  <span className="dash-stage-code">{STAGE[s.stage] ?? s.stage}</span>
                  <span className="dash-stage-state">{s.status_text}</span>
                  <span className="small muted">
                    принято {s.files_accepted}
                    {s.files_expected !== s.files_accepted ? ` из ${s.files_expected}` : ""}
                    {s.files_rejected ? ` · не принято ${s.files_rejected}` : ""}
                  </span>
                </div>
              ))}
              <div className="dash-stage">
                <span className="dash-stage-code">ИАИС «РиН»</span>
                <span className="small muted">{syncText(process)}</span>
              </div>
            </section>

            <section className="pane dash-map">
              <div className="pane-head">
                <h2>Матрица · {m.total} параметров</h2>
                <span className="count">
                  клетка — параметр · {groupBy === "queue" ? "очереди правил" : "разделы в порядке Матрицы"}
                </span>
              </div>
              <div className="dash-map-body">
                {/* Доли состояний одной полосой: сразу видно, сколько Матрицы сопоставлено */}
                <div
                  className="dash-bar"
                  role="img"
                  aria-label={STATES.filter((s) => counts[s.key])
                    .map((s) => `${s.label}: ${counts[s.key]}`)
                    .join(", ")}
                >
                  {STATES.filter((s) => counts[s.key]).map((s) => (
                    <span
                      key={s.key}
                      className={`hm-${s.key} dash-bar-seg${focus && focus !== s.key ? " dim" : ""}`}
                      style={{ flexGrow: counts[s.key] }}
                    />
                  ))}
                </div>

                <div className="dash-legend" role="group" aria-label="Состояния параметров: щелчок оставляет на карте одно">
                  {STATES.map((s) => (
                    <button
                      key={s.key}
                      type="button"
                      className="legend-item"
                      aria-pressed={focus === s.key}
                      disabled={!counts[s.key]}
                      onClick={() => setFocus(focus === s.key ? null : s.key)}
                    >
                      <Swatch state={s.key} />
                      {s.label}
                      <span className="legend-count">{counts[s.key]}</span>
                    </button>
                  ))}
                </div>

                {!asTable ? (
                  <div className="dash-grid" role="grid" aria-label="Карта параметров Матрицы" onKeyDown={onGridKey}>
                    {rows.map((row) => (
                      <div key={row.section} className="dash-row" role="row">
                        <span className={`dash-row-label${groupBy === "queue" ? " wide" : ""}`} role="rowheader" title={row.hint || undefined}>
                          {row.section}
                          <span className="dash-row-n">{row.cells.length}</span>
                          {row.hint && <span className="dash-row-hint">{row.hint}</span>}
                        </span>
                        <span className="dash-row-cells">
                          {row.cells.map((i) => {
                            const c = data.cells[i];
                            return (
                              <button
                                key={c.code}
                                ref={(el) => {
                                  cellRefs.current[i] = el;
                                }}
                                type="button"
                                role="gridcell"
                                tabIndex={i === active ? 0 : -1}
                                className={`hm-cell hm-${c.state}${focus && focus !== c.state ? " dim" : ""}${
                                  shown === i ? " on" : ""
                                }${c.finding ? " linked" : ""}`}
                                aria-label={`${c.code} ${c.name ?? ""}: ${STATE[c.state].text}${c.note ? `. ${c.note}` : ""}`}
                                onMouseEnter={() => setHovered(i)}
                                onFocus={() => {
                                  setHovered(i);
                                  setActive(i);
                                }}
                                onClick={() => openCell(i)}
                              >
                                {STATE[c.state].glyph}
                              </button>
                            );
                          })}
                        </span>
                        <span className="dash-row-stat small muted">
                          сопоставлено {row.compared} из {row.cells.length}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Раздел</th>
                          <th className="num">Параметров</th>
                          <th className="num">Сопоставлено</th>
                          <th className="num">Нет доказательств</th>
                          <th className="num">Несопоставимо</th>
                          <th className="num">Не проверено</th>
                          {/* графы — только когда такие параметры есть: строка раздела складывается в «Параметров» */}
                          {extraGroups.map((g) => (
                            <th key={g.key} className="num">
                              {g.title}
                            </th>
                          ))}
                          <th className="num">Кандидатов</th>
                          <th className="num">Нарушений</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.sections.map((s) => (
                          <tr key={s.section}>
                            <td>{s.section}</td>
                            <td className="num mono">{s.parameters}</td>
                            <td className="num mono">{s.compared}</td>
                            <td className="num mono">{s.missing_evidence}</td>
                            <td className="num mono">{s.not_comparable}</td>
                            <td className="num mono">{s.not_checked}</td>
                            {extraGroups.map((g) => (
                              <td key={g.key} className="num mono">
                                {s[g.key] ?? 0}
                              </td>
                            ))}
                            <td className="num mono">{s.candidates}</td>
                            <td className="num mono">{s.confirmed}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                <div className="dash-detail" aria-live="polite">
                  {cell ? (
                    <>
                      <Swatch state={cell.state} />
                      <span className="mono">{cell.code}</span>
                      <b>{cell.name}</b>
                      <span className="muted">
                        {cell.section} · очередь {cell.queue ?? "—"}
                        {cell.critical === true ? " · критическое" : cell.critical === false ? " · существенное" : ""}
                      </span>
                      <span className="dash-detail-reason">
                        {STATE[cell.state].text}
                        {cell.reason && cell.state !== "NOT_CHECKED" ? `: ${cell.reason}` : ""}
                      </span>
                      <span className="muted">
                        {cell.finding ? `записей ${cell.records} · щелчок откроет запись` : "записей нет"}
                      </span>
                      {/* «не проверено» без объяснения ничего не говорит: у параметра без правила — что нужно
                          правилу и чего нет в пакете (пометка правила, не заметка разработки про корпус) */}
                      {cell.note ? <span className="dash-detail-note">{cell.note}</span> : null}
                    </>
                  ) : (
                    <span className="muted">
                      Наведите на клетку или пройдите по карте стрелками — здесь появятся параметр и его состояние.
                      Щелчок по клетке открывает запись в проверке.
                    </span>
                  )}
                </div>
                <div className="dash-map-foot">
                  <span className="dash-switch" role="group" aria-label="Как показать карту">
                    <button type="button" className="link" aria-pressed={!asTable && groupBy === "section"} onClick={() => { setAsTable(false); setGroupBy("section"); setActive(0); }}>
                      по разделам
                    </button>
                    <button type="button" className="link" aria-pressed={!asTable && groupBy === "queue"} onClick={() => { setAsTable(false); setGroupBy("queue"); setActive(0); }}>
                      по очередям
                    </button>
                    <button type="button" className="link" aria-pressed={asTable} onClick={() => setAsTable(true)}>
                      таблицей
                    </button>
                  </span>
                  <span className="small muted">
                    Гипотезы свободного поиска и черновиков правил вне итогов нарушений: {data.records.suspicion ?? 0}.
                  </span>
                </div>
              </div>
            </section>

            <section className="dash-bottom">
              <div className="pane">
                <div className="pane-head">
                  <h2>Решения инспектора</h2>
                  <span className="count">
                    {decided} из {f?.candidates ?? 0}
                  </span>
                </div>
                <div className="dash-pane-body">
                  <div className="bar" aria-hidden="true">
                    <div
                      className="bar-fill"
                      style={{ width: `${f?.candidates ? Math.round((decided / f.candidates) * 100) : 0}%` }}
                    />
                  </div>
                  <div className="small">
                    подтверждено {f?.confirmed ?? 0} · отклонено {f?.rejected ?? 0} · на уточнении {f?.clarification ?? 0} ·
                    ждут {f?.pending ?? 0}
                  </div>
                </div>
              </div>
              <div className="pane">
                <div className="pane-head">
                  <h2>Версии протокола</h2>
                  <span className="count">
                    {data.changes ? `v${(data.protocol.version ?? 1) - 1} → v${data.protocol.version}` : "первая версия"}
                  </span>
                </div>
                <div className="dash-pane-body">
                  {data.changes ? (
                    <>
                      <div className="small">
                        новых записей {data.changes.added} · изменились {data.changes.changed} · убрано {data.changes.removed}
                      </div>
                      {data.changes.decided_changed.length > 0 ? (
                        <button
                          type="button"
                          className="link"
                          onClick={() => onOpen(process.process_id, { finding: data.changes!.decided_changed[0] })}
                        >
                          ⚠ решений стало неактуальными: {data.changes.decided_changed.length} — пересмотреть
                        </button>
                      ) : (
                        <div className="small muted">неактуальных решений нет</div>
                      )}
                    </>
                  ) : (
                    <div className="small muted">Сравнивать не с чем: это первая версия протокола.</div>
                  )}
                  {data.history.length > 1 && (
                    <table className="table dash-history">
                      <thead>
                        <tr>
                          <th>Версия</th>
                          <th>Собрана</th>
                          <th className="num">Записей</th>
                          <th className="num">Кандидатов</th>
                          <th className="num">Сопоставлено</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.history.map((h) => (
                          <tr key={h.version}>
                            <td className="mono">v{h.version}</td>
                            <td className="mono small">{when(h.created_at)}</td>
                            <td className="num mono">{h.records}</td>
                            <td className="num mono">{h.candidates}</td>
                            <td className="num mono">{h.compared}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {data.history.length > 1 && (
                    <div className="small muted">Кандидаты — как их нашла автоматика, до решений инспектора.</div>
                  )}
                </div>
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
