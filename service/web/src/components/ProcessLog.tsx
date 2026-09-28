import { useEffect, useState } from "react";
import { api, type ProcessLog as LogData } from "../api";
import { duration, READING_MODE, when } from "../labels";
import { matrixShort } from "../protocol";

interface Props {
  processId: string;
  /** Название объекта в шапке окна: в реестре оно уже известно. */
  title: string;
  onClose: () => void;
}

/** Что означает вид уведомления, если инспектор увидел его впервые. */
const CATEGORY: Record<string, string> = {
  ACTION: "нужно действие",
  QUALITY: "качество разбора",
  INFO: "событие",
};

function Row({ k, v, why, title }: { k: string; v: string | number; why?: string; title?: string }) {
  return (
    <div className="status-row">
      <span>{k}</span>
      <span className="tag" title={title}>
        {v}
      </span>
      {why && <span className="why">{why}</span>}
    </div>
  );
}

/**
 * Журнал обработки объекта (#83). Наблюдения о качестве разбора — «чтение отметило низкое
 * качество на 95 страницах» и подобные — раньше висели на рабочем экране инспектора и
 * читались там как дефект объекта. Их место здесь, рядом с числами прогона: чем читали,
 * сколько это заняло, что ответила модель, что изменилось между версиями протокола.
 */
export default function ProcessLog({ processId, title, onClose }: Props) {
  const [log, setLog] = useState<LogData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .log(processId)
      .then((d) => alive && setLog(d))
      .catch((e) => alive && setError((e as Error).message));
    return () => {
      alive = false;
    };
  }, [processId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const runs = log?.runs ?? [];
  const last = runs[0];
  const ready = last?.readiness ?? null;
  // Одно и то же наблюдение повторяется на каждом разборе: показываем строку раз,
  // с числом повторов и временем последнего — иначе журнал заполняется копиями.
  const quality = Object.values(
    (log?.notifications ?? [])
      .filter((n) => n.category === "QUALITY")
      .reduce<Record<string, { id: number; message: string; times: number; last: string }>>((acc, n) => {
        const seen = acc[n.message];
        if (seen) seen.times += 1;
        else acc[n.message] = { id: n.id, message: n.message, times: 1, last: n.created_at };
        return acc;
      }, {}),
  );
  const other = (log?.notifications ?? []).filter((n) => n.category !== "QUALITY");

  return (
    <div className="viewer log" role="dialog" aria-modal="true" aria-label={`Журнал обработки: ${title}`}>
      <div className="viewer-head">
        <span className="viewer-title">Журнал обработки · {title}</span>
        <button type="button" className="btn" onClick={onClose}>
          Закрыть
        </button>
      </div>
      <div className="card-body">
        {error && <div className="alert">{error}</div>}
        {!log && !error && <div className="empty-state">Журнал загружается…</div>}

        {last && (
          <section className="pane statuses">
            <div className="pane-head">
              <h2>Как читали документы</h2>
              <span className="count">версия {last.version}</span>
            </div>
            <div className="fold-body">
              <Row
                k="Способ чтения"
                v={last.reading_mode ? READING_MODE[last.reading_mode] ?? last.reading_mode : "не записан"}
                why={last.model_name ? `модель: ${last.model_name}` : undefined}
              />
              {/* версии правил и конвейера — прежде в штампе экрана проверки */}
              <Row
                k="Правила Матрицы"
                v={matrixShort(last.matrix_version)}
                why={last.model_version ? `конвейер: ${last.model_version}` : undefined}
                title={last.matrix_version ?? undefined}
              />
              {ready?.pages != null && (
                <Row
                  k="Страницы"
                  v={`${ready.pages - (ready.pages_without_text ?? 0)} из ${ready.pages}`}
                  why={ready.pages_without_text ? `без текста: ${ready.pages_without_text}` : "текст прочитан везде"}
                />
              )}
              {ready?.pages_low_quality ? (
                <Row
                  k="Низкое качество текста"
                  v={ready.pages_low_quality}
                  why="страницы стоит сверить глазами по картинке листа"
                />
              ) : null}
              {ready?.read_seconds != null && (
                <Row
                  k="Чтение заняло"
                  v={duration(ready.read_seconds)}
                  why={
                    ready.model_calls
                      ? `модель: вызовов ${ready.model_calls}, ответила ${ready.model_answered ?? 0}` +
                        (ready.model_looped ? `, зациклилась ${ready.model_looped}` : "")
                      : undefined
                  }
                />
              )}
              {ready?.by_text_source && (
                <Row
                  k="Чем прочитан текст"
                  v={Object.entries(ready.by_text_source)
                    .map(([k, v]) => `${k}: ${v}`)
                    .join(" · ")}
                />
              )}
              {ready?.stage_unknown != null && (
                <Row k="Файлов без стадии" v={ready.stage_unknown} why={ready.section_other != null ? `без раздела: ${ready.section_other}` : undefined} />
              )}
              {last.recompute && (
                <Row
                  k={last.recompute.full ? "Полный разбор" : "Дозагрузка"}
                  v={last.recompute.full ? "весь объект" : `пересчитано ${last.recompute.recomputed}, перенесено ${last.recompute.carried_over}`}
                  why={
                    last.recompute.documents_total
                      ? `прочитано документов: ${last.recompute.documents_read} из ${last.recompute.documents_total}`
                      : undefined
                  }
                />
              )}
            </div>
          </section>
        )}

        {quality.length > 0 && (
          <section className="pane statuses">
            <div className="pane-head">
              <h2>Наблюдения о качестве разбора</h2>
              <span className="count">{quality.length}</span>
            </div>
            <div className="fold-body">
              {quality.map((n) => (
                <div key={n.id} className="status-row">
                  <span>{n.message}</span>
                  {n.times > 1 && <span className="tag">на {n.times} разборах</span>}
                  <span className="mono small muted job-when">{when(n.last)}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {runs.length > 0 && (
          <section className="pane statuses">
            <div className="pane-head">
              <h2>Версии протокола</h2>
              <span className="count">{runs.length}</span>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th className="num">Версия</th>
                    <th>Собран</th>
                    <th className="num">Записей</th>
                    <th className="num">Страниц</th>
                    <th>Изменения к прошлой версии</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.version}>
                      <td className="num mono">{r.version}</td>
                      <td className="mono small">{when(r.created_at)}</td>
                      <td className="num mono">{r.checks ?? r.findings ?? "—"}</td>
                      <td className="num mono">{r.pages ?? "—"}</td>
                      <td className="small">
                        {r.changes
                          ? `новых ${r.changes.added ?? 0} · изменились ${r.changes.changed ?? 0} · убрано ${r.changes.removed ?? 0}` +
                            (r.changes.decided_changed ? ` · решений стало неактуальными ${r.changes.decided_changed}` : "")
                          : "первая версия"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {(log?.rejected_files.length ?? 0) > 0 && (
          <section className="pane statuses">
            <div className="pane-head">
              <h2>Не принято при загрузке</h2>
              <span className="count">{log!.rejected_files.reduce((n, r) => n + r.count, 0)}</span>
            </div>
            <div className="fold-body">
              {log!.rejected_files.map((r) => (
                <Row key={r.code} k={r.code} v={r.count} why={r.message ?? undefined} />
              ))}
            </div>
          </section>
        )}

        {other.length > 0 && (
          <section className="pane statuses">
            <div className="pane-head">
              <h2>Уведомления</h2>
              <span className="count">{other.length}</span>
            </div>
            <div className="fold-body">
              {other.map((n) => (
                <div key={n.id} className="status-row">
                  <span>{n.message}</span>
                  <span className="tag">{CATEGORY[n.category ?? "INFO"] ?? n.category}</span>
                  <span className="why">
                    {n.role === "admin" ? "администратору" : "инспектору"} · {when(n.created_at)}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}

        {log && runs.length === 0 && quality.length === 0 && other.length === 0 && (
          <div className="empty-state">Обработка ещё не начиналась: записывать нечего.</div>
        )}
      </div>
    </div>
  );
}
