import { useMemo, useState } from "react";
import { api, type ObjectItem, type Session } from "../api";
import { bytes, MATRIX_SECTIONS, PROCESS_STATUS, SCENARIO, STEP, when } from "../labels";
import { coverageText, lightOf, uncomparedOf, type Light } from "../protocol";
import { endUpload, useUploads } from "../uploads";
import DashboardCard from "./DashboardCard";
import ProcessLog from "./ProcessLog";
import Tip from "./Tip";

interface Props {
  objects: ObjectItem[];
  error: string | null;
  session: Session;
  /** Открыть проверку; с дашборда — сразу на записи или на таблице протокола. */
  onOpen: (processId: string, where?: { finding?: string; table?: string }) => void;
  onNew: () => void;
  /** объект удалён — перечитать реестр */
  onChanged: () => void;
}

const FILTERS: { key: Light | "all"; label: string }[] = [
  { key: "all", label: "Все" },
  { key: "violations", label: "Нарушения" },
  { key: "pending", label: "Ждут решения" },
  { key: "incomplete", label: "Проверены не полностью" },
  { key: "clean", label: "Без нарушений" },
  { key: "processing", label: "В обработке" },
  { key: "failed", label: "Сбой" },
];

/**
 * Период по дате последнего изменения проверки (ТЗ, модуль 7: фильтры по датам). Считается
 * от начала суток: «сегодня» — с полуночи, «7 дней» — сегодня и шесть дней до него.
 */
type Period = "all" | "today" | "7" | "30" | "range";
const PERIODS: { key: Period; label: string }[] = [
  { key: "all", label: "за всё время" },
  { key: "today", label: "сегодня" },
  { key: "7", label: "7 дней" },
  { key: "30", label: "30 дней" },
  { key: "range", label: "период" },
];

function dayStart(offsetDays: number): number {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - offsetDays);
  return d.getTime();
}

/** Попадает ли время изменения в выбранный период; from/to — даты поля ввода, YYYY-MM-DD. */
function inPeriod(iso: string | undefined, period: Period, from: string, to: string): boolean {
  if (period === "all") return true;
  if (!iso) return false;
  const t = new Date(iso).getTime();
  if (period === "today") return t >= dayStart(0);
  if (period === "7") return t >= dayStart(6);
  if (period === "30") return t >= dayStart(29);
  const start = from ? new Date(`${from}T00:00:00`).getTime() : -Infinity;
  const end = to ? new Date(`${to}T00:00:00`).getTime() + 86400000 : Infinity;
  return t >= start && t < end;
}

/** Есть ли у объекта в разделе записи, ждущие решения, или подтверждённые нарушения. */
function inSection(item: ObjectItem, section: string): boolean {
  if (section === "all") return true;
  const slot = item.last_process?.findings?.by_section?.[section];
  return !!slot && slot.candidates + slot.confirmed > 0;
}

// Подтверждённые нарушения считаются и у объектов, где решения ещё идут: это итог проверки, а не её состояние
function matches(item: ObjectItem, light: Light, key: Light | "all"): boolean {
  if (key === "all") return true;
  if (key === "violations") return (item.last_process?.findings?.confirmed ?? 0) > 0;
  return light === key;
}

export default function ObjectsScreen({ objects, error, session, onOpen, onNew, onChanged }: Props) {
  const [filter, setFilter] = useState<Light | "all">("all");
  const [query, setQuery] = useState("");
  // Отбор по разделу Матрицы и по дате изменения (#83, ТЗ модуль 7)
  const [section, setSection] = useState("all");
  const [period, setPeriod] = useState<Period>("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  // Удаление — действие администратора и необратимое, поэтому сначала подтверждение
  // с перечнем того, что уйдёт, и только потом запрос (#74).
  const [confirm, setConfirm] = useState<ObjectItem | null>(null);
  // Журнал обработки объекта (#83): наблюдения о разборе живут здесь, а не на экране инспектора
  const [log, setLog] = useState<{ processId: string; title: string } | null>(null);
  // Дашборд объекта (#83): сводка протокола и карта 132 параметров
  const [dash, setDash] = useState<ObjectItem | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const admin = session.role === "admin";

  async function remove(item: ObjectItem) {
    setBusy(true);
    setFailure(null);
    try {
      const done = await api.deleteObject(item.object_id);
      setNotice(
        `Объект ${item.object_id} удалён: проверок ${done.processes}, файлов ${done.files}, ` +
          `из хранилища убрано ${done.blobs_removed}`,
      );
      setConfirm(null);
      onChanged();
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const rows = useMemo(() => objects.map((o) => ({ ...o, ...lightOf(o), coverage: coverageText(o) })), [objects]);
  /**
   * Очередь обработки (#74). Обработка — работа на минуты, и запускают её с разных экранов:
   * загрузка объекта, дозагрузка, пересборка, перечитывание. Раньше её ход был виден только
   * на том экране, где её начали, и терялся при уходе с него; а новый объект, пока грузится
   * первый пакет, на сервере ещё не существует. Здесь очередь целиком: загрузки из этого окна,
   * загрузки, которые сервер принимает пакетами, обработка, которая идёт, и ожидающие своей
   * очереди — по порядку постановки. Воркер берёт задания по одному.
   */
  const uploads = useUploads();
  const queue = useMemo(() => {
    // Процессы, в которые идёт загрузка из этого окна, в очереди показывает строка загрузки.
    // Оборвавшаяся загрузка процесс не прячет: по нему мог быть запущен разбор, и его ход нужен.
    const mine = new Set(uploads.filter((u) => !u.error).map((u) => u.processId).filter(Boolean));
    const live = rows.filter((r) => r.last_process && !mine.has(r.last_process.process_id));
    const stateOf = (r: (typeof rows)[number]) => r.last_process!.processing.state;
    const running = live.filter((r) => stateOf(r) === "RUNNING");
    const queued = live
      .filter((r) => stateOf(r) === "QUEUED")
      .sort((a, b) =>
        (a.last_process!.processing.queued_at ?? a.last_process!.updated_at).localeCompare(
          b.last_process!.processing.queued_at ?? b.last_process!.updated_at,
        ),
      );
    // сервер принял часть пакетов, последнего ещё нет: разбор не поставлен
    const receiving = live.filter(
      (r) => r.last_process!.status === "PENDING" && (stateOf(r) ?? "IDLE") === "IDLE" && r.last_process!.files.accepted > 0,
    );
    return { running, queued, receiving };
  }, [rows, uploads]);
  const queueSize = uploads.length + queue.running.length + queue.queued.length + queue.receiving.length;

  // Каждое измерение отбора — отдельная проверка. Число на кнопке считается с учётом
  // остальных отборов: видно, сколько объектов останется, если нажать именно её.
  const q = query.trim().toLowerCase();
  const byQuery = (r: (typeof rows)[number]) =>
    !q || r.name.toLowerCase().includes(q) || r.object_id.toLowerCase().includes(q);
  const byDate = (r: (typeof rows)[number]) => inPeriod(r.last_process?.updated_at, period, from, to);
  // Объектов десятки: счёт на каждой отрисовке дешевле, чем следить за зависимостями
  const counted = (pred: (r: (typeof rows)[number]) => boolean) => rows.filter(pred).length;
  const counts: Record<string, number> = Object.fromEntries(
    FILTERS.map((f) => [f.key, counted((r) => matches(r, r.light, f.key) && inSection(r, section) && byDate(r) && byQuery(r))]),
  );
  const sectionCounts: Record<string, number> = Object.fromEntries(
    [{ key: "all" }, ...MATRIX_SECTIONS].map((s) => [
      s.key,
      counted((r) => matches(r, r.light, filter) && inSection(r, s.key) && byDate(r) && byQuery(r)),
    ]),
  );
  const periodCounts: Record<string, number> = Object.fromEntries(
    PERIODS.map((p) => [
      p.key,
      counted(
        (r) => matches(r, r.light, filter) && inSection(r, section) && inPeriod(r.last_process?.updated_at, p.key, from, to) && byQuery(r),
      ),
    ]),
  );
  const shown = rows.filter((r) => matches(r, r.light, filter) && inSection(r, section) && byDate(r) && byQuery(r));
  const narrowed = filter !== "all" || section !== "all" || period !== "all" || !!q;
  const resetFilters = () => {
    setFilter("all");
    setSection("all");
    setPeriod("all");
    setFrom("");
    setTo("");
    setQuery("");
  };

  return (
    <div className="frame">
      <header className="sheet-head">
        <div>
          <h1>Объекты</h1>
          <div className="sub">Последний процесс проверки каждого объекта</div>
        </div>
        <div className="head-meta">
          <div className="head-cell">
            <span className="k">Объектов</span>
            <span className="v">{rows.length}</span>
          </div>
          <div className="head-cell">
            <span className="k">Ждут решения</span>
            <span className="v">{counts.pending ?? 0}</span>
          </div>
          <div className="head-cell">
            <span className="k">С нарушениями</span>
            <span className="v">{counts.violations ?? 0}</span>
          </div>
        </div>
        <button className="btn btn-primary" type="button" onClick={onNew}>
          Новая проверка
        </button>
      </header>

      {confirm && (
        <div className="viewer confirm" role="dialog" aria-modal="true" aria-label="Удаление объекта">
          <div className="viewer-head">
            <span className="viewer-title">Удалить объект «{confirm.name}»?</span>
          </div>
          <div className="card-body">
            <p>
              Уйдут все проверки объекта <span className="mono">{confirm.object_id}</span> ({confirm.processes} шт.):
              загруженные файлы, находки и черновые протоколы. Отменить это нельзя.
            </p>
            <p className="small muted">
              Останутся журнал аудита (запись об удалении в нём тоже появится), уведомления и выпущенные версии набора
              решений — это записи о том, что делали, и снимки. Объект с финализированным протоколом сервис удалить
              не даст: протокол — документ с решениями инспектора и записью в ИАИС «РиН».
            </p>
            {failure && <div className="alert">{failure}</div>}
            <div className="actions-row">
              <button type="button" className="btn" disabled={busy} onClick={() => setConfirm(null)}>
                Отмена
              </button>
              <button type="button" className="btn btn-danger" disabled={busy} onClick={() => remove(confirm)}>
                Удалить объект
              </button>
            </div>
          </div>
        </div>
      )}

      {queueSize > 0 && (
        <section className="pane jobs">
          <div className="pane-head">
            <h2>Очередь обработки</h2>
            <span className="count">{queueSize}</span>
          </div>
          <div className="card-body">
            {queue.running.map((j) => {
              const p = j.last_process!;
              const total = p.progress?.total ?? 0;
              const done = p.progress?.done ?? 0;
              return (
                <div key={j.object_id} className="job">
                  <div className="job-top">
                    <span className="tag tag-run">идёт</span>
                    <button type="button" className="link" onClick={() => onOpen(p.process_id)}>
                      {j.name}
                    </button>
                    <span className="small muted">
                      {STEP[p.processing.step ?? ""] ?? p.processing.step}
                      {p.progress?.message && p.progress.message !== STEP[p.processing.step ?? ""]
                        ? ` · ${p.progress.message}`
                        : ""}
                      {total ? ` — ${done} из ${total}` : ""}
                    </span>
                    {/* ход пишется воркером отдельно от записи процесса: время берём у хода */}
                    <span className="mono small muted job-when">обновлено {when(p.progress?.updated_at ?? p.updated_at)}</span>
                  </div>
                  <div className="bar">
                    <div
                      className={`bar-fill${total ? "" : " bar-indeterminate"}`}
                      style={total ? { width: `${Math.round((done / total) * 100)}%` } : undefined}
                    />
                  </div>
                </div>
              );
            })}
            {queue.queued.map((j, i) => {
              const p = j.last_process!;
              return (
                <div key={j.object_id} className="job">
                  <div className="job-top">
                    <span className="tag">в очереди · {i + 1}</span>
                    <button type="button" className="link" onClick={() => onOpen(p.process_id)}>
                      {j.name}
                    </button>
                    <span className="small muted">
                      {i === 0 && queue.running.length === 0
                        ? "следующий: начнётся, как только воркер его возьмёт"
                        : `перед ним ${i + queue.running.length}`}
                    </span>
                    <span className="mono small muted job-when">
                      ждёт с {when(p.processing.queued_at ?? p.updated_at)}
                    </span>
                  </div>
                </div>
              );
            })}
            {uploads.map((u) => (
              <div key={u.id} className="job">
                <div className="job-top">
                  <span className={`tag${u.error ? " tag-fail" : ""}`}>{u.error ? "загрузка прервалась" : "загрузка"}</span>
                  {u.processId ? (
                    <button type="button" className="link" onClick={() => onOpen(u.processId as string)}>
                      {u.name}
                    </button>
                  ) : (
                    <span className="job-name">{u.name}</span>
                  )}
                  <span className="small muted">
                    {u.error
                      ? `${u.error}${u.failedBatch ? ` · на пакете ${u.failedBatch} из ${u.batchCount}` : ""}`
                      : u.note ??
                        `пакет ${u.batchIndex} из ${u.batchCount}: ${bytes(u.sent)} из ${bytes(u.total)}` +
                          (u.processId ? "" : " · объект появится в реестре после первого пакета")}
                  </span>
                  {u.error ? (
                    <span className="job-when job-actions">
                      {/* продолжить — в тот же процесс, с оборвавшегося пакета: принятые не уходят заново */}
                      {u.resume && (
                        <button type="button" className="link" onClick={u.resume}>
                          {u.resumeLabel ?? "продолжить"}
                        </button>
                      )}
                      <button type="button" className="link" onClick={() => endUpload(u.id)}>
                        убрать
                      </button>
                    </span>
                  ) : (
                    <span className="mono small muted job-when">с {when(u.startedAt)}</span>
                  )}
                </div>
                {!u.error && (
                  <div className="bar">
                    <div className="bar-fill" style={{ width: `${Math.round((u.sent / Math.max(u.total, 1)) * 100)}%` }} />
                  </div>
                )}
              </div>
            ))}
            {queue.receiving.map((j) => {
              const p = j.last_process!;
              return (
                <div key={j.object_id} className="job">
                  <div className="job-top">
                    <span className="tag">загрузка не закончена</span>
                    <button type="button" className="link" onClick={() => onOpen(p.process_id)}>
                      {j.name}
                    </button>
                    <span className="small muted">
                      принято файлов {p.files.accepted}; разбор начнётся после последнего пакета.{" "}
                      {/* файлы из прерванной загрузки в этом окне уже не живы: догрузить или начать
                          разбор с принятыми можно на экране проверки объекта */}
                      <button type="button" className="link" onClick={() => onOpen(p.process_id)}>
                        догрузить или начать разбор
                      </button>
                    </span>
                    <span className="mono small muted job-when">последний пакет {when(p.updated_at)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {log && <ProcessLog processId={log.processId} title={log.title} onClose={() => setLog(null)} />}
      {dash && (
        <DashboardCard
          item={dash}
          onClose={() => setDash(null)}
          onOpen={(processId, where) => {
            setDash(null);
            onOpen(processId, where);
          }}
        />
      )}

      {error && <div className="alert">Сервис недоступен: {error}</div>}
      {failure && !confirm && <div className="alert">{failure}</div>}
      {notice && !failure && <div className="note-line">{notice}</div>}

      <div className="toolbar">
        <div className="filters" role="group" aria-label="Фильтр по состоянию">
          {FILTERS.filter((f) => f.key === "all" || counts[f.key] || filter === f.key).map((f) => (
            <button
              key={f.key}
              type="button"
              className="filter"
              aria-pressed={filter === f.key}
              onClick={() => setFilter(f.key)}
            >
              {f.key !== "all" && <span className={`light light-${f.key}`} aria-hidden="true" />}
              {f.label} <span className="count">{counts[f.key] ?? 0}</span>
            </button>
          ))}
        </div>
        <input
          id="objects-search"
          type="search"
          className="search"
          placeholder="Название или идентификатор объекта"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {/* Разделы и даты (#83, ТЗ модуль 7). Раздел отбирает объекты, у которых в нём есть
          записи, ждущие решения, или подтверждённые нарушения; показаны только разделы,
          где такие объекты есть. Дата — последнего изменения проверки. */}
      <div className="toolbar toolbar-2">
        <div className="filters" role="group" aria-label="Фильтр по разделу Матрицы">
          <span className="filters-label">Разделы</span>
          <button type="button" className="filter" aria-pressed={section === "all"} onClick={() => setSection("all")}>
            все <span className="count">{sectionCounts.all ?? 0}</span>
          </button>
          {MATRIX_SECTIONS.filter((s) => sectionCounts[s.key] || section === s.key).map((s) => (
            <Tip key={s.key} place="above" text={`Объекты, где в разделе «${s.title}» есть записи, ждущие решения, или подтверждённые нарушения`}>
              <button
                type="button"
                className="filter"
                aria-pressed={section === s.key}
                onClick={() => setSection(section === s.key ? "all" : s.key)}
              >
                {s.short} <span className="count">{sectionCounts[s.key] ?? 0}</span>
              </button>
            </Tip>
          ))}
        </div>
        <div className="filters" role="group" aria-label="Фильтр по дате изменения">
          <span className="filters-label">Изменены</span>
          {PERIODS.map((p) => (
            <button
              key={p.key}
              type="button"
              className="filter"
              aria-pressed={period === p.key}
              onClick={() => setPeriod(p.key)}
            >
              {p.label}
              {p.key !== "range" && <span className="count">{periodCounts[p.key] ?? 0}</span>}
            </button>
          ))}
          {period === "range" && (
            <span className="date-range">
              <label>
                с{" "}
                <input id="objects-from" type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
              </label>
              <label>
                по <input id="objects-to" type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
              </label>
            </span>
          )}
        </div>
        {narrowed && (
          <button type="button" className="link reset-filters" onClick={resetFilters}>
            сбросить отбор
          </button>
        )}
      </div>

      <section className="pane grow">
        <div className="pane-head">
          <h2>Реестр проверок</h2>
          <span className="count">{shown.length}</span>
        </div>
        {shown.length === 0 ? (
          <div className="empty-state">
            {objects.length === 0 ? (
              "Проверок ещё нет. Начните с загрузки папки объекта."
            ) : (
              <>
                Под отбор ничего не попало.{" "}
                <button type="button" className="link" onClick={resetFilters}>
                  сбросить отбор
                </button>
              </>
            )}
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th aria-label="Светофор" />
                  <th>Объект</th>
                  <th>Состояние</th>
                  <th>Статус процесса</th>
                  <th>Стадии</th>
                  <th className="num">Ждут решения</th>
                  <th className="num">Подтв.</th>
                  <th className="num">Откл.</th>
                  <th
                    className="num"
                    title="Параметры с правилом, по которым значения не сопоставлены: нет значения или документа в одной из стадий, либо значения несопоставимы"
                  >
                    Без сравнения
                  </th>
                  <th>Обновлено</th>
                  <th aria-label="Действия" />
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => {
                  const p = r.last_process;
                  const c = p?.findings;
                  const without = uncomparedOf(p);
                  return (
                    <tr
                      key={r.object_id}
                      className={p ? "clickable" : ""}
                      onClick={() => p && onOpen(p.process_id)}
                      onKeyDown={(e) => e.key === "Enter" && p && onOpen(p.process_id)}
                      tabIndex={p ? 0 : -1}
                    >
                      <td>
                        <span className={`light light-${r.light}`} title={r.coverage ? `${r.label} · ${r.coverage.full}` : r.label} />
                      </td>
                      <td>
                        <div className="cell-title">{r.name}</div>
                        <div className="mono small">{r.object_id}</div>
                      </td>
                      <td>
                        {r.label}
                        {/* вывод без охвата вводил в заблуждение: «нарушений не выявлено» при 7 сопоставленных
                            из 132. Охват — в той же строке, коротко, чтобы строка реестра не стала выше */}
                        {r.coverage && (
                          <span className="muted small" title={`${r.coverage.full}: по ним значения ПД, РД и ИД сопоставлены правилами`}>
                            {" · "}
                            {r.coverage.short}
                          </span>
                        )}
                      </td>
                      <td>{p ? PROCESS_STATUS[p.status] ?? p.status : "—"}</td>
                      <td className="mono small">{p?.scenario ? SCENARIO[p.scenario] ?? p.scenario : "—"}</td>
                      <td className="num">
                        {c ? `${c.pending} из ${c.candidates}` : "—"}
                        {c?.revisit ? (
                          <div className="small" title="Решения, принятые по прежним значениям: после дозагрузки значения изменились">
                            пересмотреть {c.revisit}
                          </div>
                        ) : null}
                      </td>
                      <td className="num">{c?.confirmed ?? "—"}</td>
                      <td className="num">{c?.rejected ?? "—"}</td>
                      <td
                        className="num"
                        title={
                          without
                            ? `Параметров с правилом без сравнения: ${without.total} — нет доказательств ${without.missing}, несопоставимо ${without.notComparable}`
                            : undefined
                        }
                      >
                        {without ? without.total : "—"}
                      </td>
                      <td className="mono small">{when(p?.updated_at)}</td>
                      <td className="row-actions" onClick={(e) => e.stopPropagation()}>
                        {/* Журнал обработки (#83): чем читали, что вышло, что сервис заметил */}
                        <Tip place="above" text="Дашборд объекта: главные числа, стадии и карта всех 132 параметров Матрицы">
                          <button
                            type="button"
                            className="btn small-btn"
                            disabled={!p?.protocol_version}
                            onClick={() => p && setDash(r)}
                          >
                            Дашборд
                          </button>
                        </Tip>{" "}
                        <Tip place="above" text="Журнал обработки: способ чтения, качество разбора, версии протокола и что сервис заметил по дороге">
                          <button
                            type="button"
                            className="btn small-btn"
                            disabled={!p}
                            onClick={() => p && setLog({ processId: p.process_id, title: r.name })}
                          >
                            Лог
                          </button>
                        </Tip>{" "}
                        {/* Действие администратора, но видно всем: иначе непонятно, есть ли оно
                            вообще. Инспектору кнопка погашена и объясняет, к кому идти (#74). */}
                        <Tip
                          place="above"
                          text={
                            admin
                              ? "Удалить объект со всеми его проверками. Объект с финализированным протоколом не удаляется: это документ"
                              : "Удаление объекта доступно администратору"
                          }
                        >
                          <button
                            type="button"
                            className={`btn small-btn${admin ? "" : " disabled"}`}
                            aria-disabled={!admin}
                            onClick={() => (admin ? setConfirm(r) : setNotice("Удаление объекта доступно администратору"))}
                          >
                            Удалить
                          </button>
                        </Tip>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
