import { useCallback, useEffect, useState } from "react";
import { api, type DatasetChange, type DatasetItem, type DatasetVersion, type DatasetView } from "../api";
import { REASONS, when } from "../labels";
import Tip from "./Tip";

const CHANGE: Record<DatasetChange, string> = {
  ADDED: "добавлена",
  CHANGED: "изменена",
  UNCHANGED: "без изменений",
  REMOVED: "убрана",
};

/**
 * Решения инспектора как набор примеров для дообучения, ТЗ 9.4. Черновик — решения
 * финализированных протоколов, с разницей к последней версии; куратор выпускает версию —
 * неизменяемый снимок черновика, её идентификатор — хеш состава.
 */
export default function DatasetScreen() {
  const [draft, setDraft] = useState<DatasetView | null>(null);
  const [versions, setVersions] = useState<DatasetVersion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Отзыв версии (#74): версия остаётся в истории, но в дообучение не берётся.
  // Причина обязательна — по ней потом понятно, почему на этих примерах учить нельзя.
  const [withdraw, setWithdraw] = useState<string | null>(null);
  const [reason, setReason] = useState("");

  const load = useCallback(async () => {
    try {
      const [d, v] = await Promise.all([api.dataset(), api.datasetVersions()]);
      setDraft(d);
      setVersions(v.versions);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function release() {
    setBusy(true);
    setNotice(null);
    try {
      const v = await api.datasetRelease();
      setNotice(
        `Выпущена версия ${v.dataset_version}: примеров ${v.items} (положительных ${v.positives}, отрицательных ${v.negatives}); ` +
          `к прошлой версии добавлено ${v.added}, изменено ${v.changed}, убрано ${v.removed}`,
      );
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function withdrawVersion(version: string) {
    setBusy(true);
    setNotice(null);
    try {
      const v = await api.datasetWithdraw(version, reason.trim());
      setNotice(`Версия ${v.dataset_version} отозвана: в дообучение не берётся, в истории остаётся`);
      setWithdraw(null);
      setReason("");
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const c = draft?.counts;
  const pending = c ? c.added + c.changed + c.removed : 0;
  const rows: DatasetItem[] = draft ? [...draft.items, ...draft.removed] : [];

  return (
    <div className="frame">
      <header className="sheet-head">
        <div>
          <h1>Набор решений</h1>
          <div className="sub">Примеры для дообучения из финализированных протоколов</div>
        </div>
        <div className="head-meta">
          <div className="head-cell">
            <span className="k">Черновик</span>
            <span className="v">
              {c ? c.positives : 0} подтв. · {c ? c.negatives : 0} откл.
            </span>
          </div>
          <div className="head-cell" title={draft?.base_version ? `Последняя версия ${draft.base_version}` : ""}>
            <span className="k">{draft?.base_version ? "К последней версии" : "Версий ещё нет"}</span>
            <span className="v">
              +{c ? c.added : 0} · ~{c ? c.changed : 0} · −{c ? c.removed : 0}
            </span>
          </div>
        </div>
        <Tip
          text={
            pending === 0
              ? "Черновик совпадает с последней версией: выпускать нечего"
              : "Снимок черновика с именем ds-…: именно он идёт в обучение. Изменить или отозвать выпущенную версию нельзя"
          }
        >
          <button className="btn btn-primary" type="button" disabled={busy || pending === 0} onClick={release}>
            Выпустить версию
          </button>
        </Tip>
      </header>
      {error && <div className="alert">{error}</div>}
      {notice && !error && <div className="note-line">{notice}</div>}
      {/* Экран непонятен человеку, который видит его впервые: объясняем словами, зачем он,
          что сюда попадает и на что это влияет (#74, вопросы после репетиции #53). */}
      <details className="explain" open>
        <summary>Что это за экран и на что он влияет</summary>
        <div className="explain-body">
          <p>
            <b>Зачем.</b> Каждое ваше решение по находке — это пример для системы: подтверждённое нарушение говорит
            «так выглядит нарушение», отклонённый кандидат — «так выглядит ложная тревога». Набор решений собирает
            такие примеры в одном месте, чтобы на них дообучали разбор.
          </p>
          <p>
            <b>Что сюда попадает.</b> Только решения из финализированных протоколов. Подтверждённое нарушение —
            положительный пример, отклонённый кандидат с названной причиной — отрицательный. «Требует уточнения» и
            записи без решения не берутся: по ним неизвестно, как правильно. Если финализацию отменить, решения этого
            процесса уходят из черновика.
          </p>
          <p>
            <b>На что влияет.</b> Черновик — просто список, он ни на что не влияет. В обучение идёт выпущенная
            версия: неизменяемый снимок черновика с именем вида <span className="mono">ds-…</span>. Её имя пишется
            в протоколы, чтобы потом было видно, на каких примерах училась система, считавшая объект.
          </p>
          <p>
            <b>Если версия оказалась неверной.</b> Изменить или удалить её нельзя: на неё ссылаются протоколы, и правка
            задним числом лишила бы их доказательной силы. Версию <b>отзывают</b> — она остаётся в истории с причиной
            отзыва, но в дообучение не берётся. Сами решения исправляют так: отменить финализацию протокола, изменить
            решение, финализировать снова и выпустить новую версию — разница к прошлой видна в столбце «К версии».
          </p>
        </div>
      </details>

      <section className="pane grow">
        <div className="pane-head">
          <h2>Черновик</h2>
          <span className="count">{c ? c.items : 0}</span>
        </div>
        {rows.length === 0 ? (
          <div className="empty-state">Черновик пуст: примеры появятся после финализации протоколов с решениями.</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Объект</th>
                  <th>Запись</th>
                  <th>Метка</th>
                  <th>Причина</th>
                  <th>Эксперт</th>
                  <th>Решение</th>
                  <th>К версии</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={`${d.process_id}::${d.finding_id}`} className={d.change === "REMOVED" ? "muted" : undefined}>
                    <td className="mono small">{d.object_id}</td>
                    <td>
                      <div className="cell-title">{d.parameter_code}</div>
                      <div className="mono small">{d.location ?? d.finding_id}</div>
                    </td>
                    <td>{d.gold_label === "CONFIRMED_VIOLATION" ? "положительный" : "отрицательный"}</td>
                    <td>
                      {d.reason_code ? REASONS.find((r) => r.code === d.reason_code)?.label ?? d.reason_code : "—"}
                      {d.comment && <div className="small muted">{d.comment}</div>}
                    </td>
                    <td className="mono small">{d.expert_id ?? "—"}</td>
                    <td className="mono small">{when(d.decided_at)}</td>
                    <td className="small">{d.change ? CHANGE[d.change] : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="pane">
        <div className="pane-head">
          <h2>Выпущенные версии</h2>
          <span className="count">{versions.length}</span>
        </div>
        {versions.length === 0 ? (
          <div className="empty-state">Версий ещё нет.</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Версия</th>
                  <th className="num">Примеров</th>
                  <th className="num">Положит.</th>
                  <th className="num">Отрицат.</th>
                  <th className="num">Изменения</th>
                  <th>Объекты</th>
                  <th>Выпустил</th>
                  <th aria-label="Действия" />
                </tr>
              </thead>
              <tbody>
                {versions.map((v) => (
                  <tr key={v.dataset_version} className={v.withdrawn_at ? "muted" : undefined}>
                    <td className="mono small">
                      {v.dataset_version}
                      {v.withdrawn_at && (
                        <div className="small">
                          отозвана: {v.withdrawn_by ?? "—"} · {when(v.withdrawn_at)}
                          {v.withdrawn_reason ? ` · ${v.withdrawn_reason}` : ""}
                        </div>
                      )}
                    </td>
                    <td className="num">{v.items}</td>
                    <td className="num">{v.positives}</td>
                    <td className="num">{v.negatives}</td>
                    <td className="num mono small">
                      +{v.added} ~{v.changed} −{v.removed}
                    </td>
                    <td className="mono small">{v.objects.join(", ")}</td>
                    <td className="mono small">
                      {v.released_by ?? "—"} · {when(v.released_at ?? null)}
                    </td>
                    <td className="row-actions">
                      {v.withdrawn_at ? (
                        <span className="small muted">отозвана</span>
                      ) : withdraw === v.dataset_version ? (
                        <span className="withdraw-form">
                          <input
                            autoFocus
                            placeholder="почему отзываем"
                            value={reason}
                            onChange={(e) => setReason(e.target.value)}
                          />
                          <button
                            type="button"
                            className="btn small-btn"
                            disabled={busy || reason.trim().length < 3}
                            onClick={() => withdrawVersion(v.dataset_version)}
                          >
                            Отозвать
                          </button>
                          <button type="button" className="btn small-btn" disabled={busy} onClick={() => setWithdraw(null)}>
                            Отмена
                          </button>
                        </span>
                      ) : (
                        <Tip place="above" text="Пометить версию отозванной: в дообучение её не берут, из истории она не исчезает. Причина обязательна">
                          <button
                            type="button"
                            className="btn small-btn"
                            disabled={busy}
                            onClick={() => {
                              setWithdraw(v.dataset_version);
                              setReason("");
                            }}
                          >
                            Отозвать
                          </button>
                        </Tip>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
