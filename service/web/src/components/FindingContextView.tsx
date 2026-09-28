import { useEffect, useState } from "react";
import { api, openInTab, sourceUrl, type FindingContext, type LinkState } from "../api";

/** Короткие имена разделов для карты и контекста (#82). */
export const SECTION_SHORT: Record<string, string> = {
  PZ: "ПЗ", GP: "ГП", AR: "АР", KR: "КР", OV: "ОВ", VK: "ВК", EOM: "ЭОМ", SS: "СС", PB: "ПБ", POS: "ПОС",
  POD: "ПОД", OOS: "ООС", ODI: "ОДИ", TX: "ТХ", OTHER: "без раздела",
};
export const STAGE_SHORT: Record<string, string> = { PD: "ПД", RD: "РД", ID: "ИД" };
const STAGE_FULL: Record<string, string> = { PD: "проектной", RD: "рабочей", ID: "исполнительной" };
export const STATE_TEXT: Record<LinkState, string> = {
  VIOLATION: "нарушение",
  CANDIDATE: "кандидат",
  CLEAN: "без замечаний",
  NOT_COMPARABLE: "несопоставимо",
  MISSING_EVIDENCE: "нет доказательств",
  SUSPICION: "гипотеза",
};

interface Props {
  processId: string;
  findingId: string;
  /** В карточке находки заголовок записи уже есть — показываем только связи. */
  compact?: boolean;
  /** Открыть другую запись: из «той же проверки на объекте». */
  onOpenFinding?: (id: string) => void;
  onError?: (message: string) => void;
}

/**
 * Контекст находки (#82): документы доказательства по стадиям ПД, РД, ИД — со страницами,
 * цитатой и редакцией, та же проверка на других участках объекта и помещения — где ещё они
 * встречаются. Связи по помещению с коротким номером или из «клубка» отсечены фильтром,
 * их можно показать отдельно; заменённая редакция в связи не входит.
 */
export default function FindingContextView({ processId, findingId, compact, onOpenFinding, onError }: Props) {
  const [ctx, setCtx] = useState<FindingContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showCut, setShowCut] = useState(false);

  useEffect(() => {
    let alive = true;
    setCtx(null);
    setError(null);
    api
      .context(processId, findingId)
      .then((c) => alive && setCtx(c))
      .catch((e) => alive && setError((e as Error).message));
    return () => {
      alive = false;
    };
  }, [processId, findingId]);

  if (error) return <div className="alert">Связи не загрузились: {error}</div>;
  if (!ctx) return <div className="empty-state">Связи собираются…</div>;

  const f = ctx.finding;
  const open = (fileId: string, page?: number) =>
    openInTab(sourceUrl(processId, fileId), page ? `#page=${page}` : "").catch((e) =>
      onError?.(`Исходный файл не открылся: ${(e as Error).message}`),
    );
  const cutRooms = (ctx.rooms ?? []).filter((r) => r.cut && r.documents.length);

  return (
    <div className={`lk${compact ? " lk-compact" : ""}`}>
      {!compact && (
        <div className="lk-finding">
          <div className="lk-finding-top">
            <span className="code">{f.code}</span>
            <span className={`lk-state st-${f.state}`}>{STATE_TEXT[f.state]}</span>
            {f.location && <span className="mono small muted">{f.location}</span>}
          </div>
          <div className="lk-finding-title">{f.title ?? f.finding_id}</div>
        </div>
      )}
      {!compact && <div className="lk-bus" aria-hidden="true" />}

      <div className="lk-stages">
        {ctx.stages.map((s) => (
          <div key={s.stage} className={`lk-col${s.documents.length ? "" : " empty"}`}>
            <div className="lk-col-head">
              {STAGE_SHORT[s.stage] ?? s.stage}
              <span className="lk-val">{s.value ?? "—"}</span>
            </div>
            {s.documents.length === 0 ? (
              <div className="lk-none">В {STAGE_FULL[s.stage] ?? s.stage} документации доказательства нет</div>
            ) : (
              s.documents.map((d) => (
                <div key={d.file_id} className="lk-doc">
                  <div className="lk-doc-top">
                    <b>{d.code ?? d.file_id}</b>
                    <button type="button" className="link" onClick={() => open(d.file_id, d.pages?.[0])}>
                      открыть
                    </button>
                  </div>
                  <div className="lk-meta">
                    {d.file_id} · {d.name}
                  </div>
                  <div className="lk-meta">
                    стр. {d.pages?.join(", ") || "—"}
                    {d.page_count ? ` из ${d.page_count}` : ""}{" "}
                    {d.current ? (
                      <span className="lk-rev old" title={`Актуальная редакция: ${d.current.name}`}>
                        заменена → {d.current.file_id}
                      </span>
                    ) : d.revision_status === "CURRENT" ? (
                      <span className="lk-rev">актуальная</span>
                    ) : null}
                  </div>
                  {d.quote && <div className="lk-quote">«{d.quote}»</div>}
                </div>
              ))
            )}
          </div>
        ))}
      </div>

      <div className="lk-related">
        <div>
          <div className="lk-h">Та же проверка на объекте · {ctx.same_parameter.total}</div>
          <div className="lk-chips">
            {ctx.same_parameter.items.length === 0 && <span className="muted small">других участков нет</span>}
            {ctx.same_parameter.items.map((g) => (
              <button
                key={g.id}
                type="button"
                className="lk-chip"
                disabled={!onOpenFinding}
                onClick={() => onOpenFinding?.(g.id)}
                title="Открыть эту запись"
              >
                {g.location ?? "—"} <span className={`lk-dot st-${g.state}`} aria-hidden="true" />
                <span className="muted">{STATE_TEXT[g.state]}</span>
              </button>
            ))}
            {ctx.same_parameter.total > ctx.same_parameter.items.length && (
              <span className="muted small">ещё {ctx.same_parameter.total - ctx.same_parameter.items.length}</span>
            )}
          </div>
        </div>

        {f.location_type === "ROOM" && (
          <div>
            <div className="lk-h">Где ещё встречается помещение</div>
            {!ctx.rooms_indexed ? (
              <div className="muted small">Индекс помещений появится после пересборки протокола.</div>
            ) : (
              (ctx.rooms ?? []).map((r) => (
                <div key={r.room} className={`lk-room${r.cut ? " cut" : ""}`}>
                  <b>Помещение {r.room}</b>{" "}
                  <span className="muted">
                    —{" "}
                    {r.cut === "SHORT"
                      ? "номер из одной-двух цифр — часто номер строки таблицы, связь не ставим"
                      : r.cut === "TANGLED"
                        ? `встречается в ${r.total} документах — это поэтажный план или сводная ведомость, связь не ставим`
                        : r.documents.length
                          ? `встречается ещё в ${r.documents.length} документах`
                          : "других документов с этим помещением нет"}
                    {r.superseded_skipped ? ` · заменённых редакций не учтено: ${r.superseded_skipped}` : ""}
                  </span>
                  {r.documents.length > 0 && (!r.cut || showCut) && (
                    <div className={`lk-roomdocs${r.cut ? " ghost" : ""}`}>
                      {r.documents.map((d) => (
                        <button key={d.file_id} type="button" onClick={() => open(d.file_id)} title={d.name}>
                          {STAGE_SHORT[d.stage ?? ""] ?? "?"} · {d.code ?? d.file_id}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ))
            )}
            {cutRooms.length > 0 && (
              <label className="lk-toggle">
                <input id={`lk-cut-${findingId}`} type="checkbox" checked={showCut} onChange={(e) => setShowCut(e.target.checked)} /> показать
                отсечённые связи
              </label>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
